import gc
import json
import os
import sqlite3
import tempfile
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

import app as sv


def main():
    tmp = tempfile.TemporaryDirectory(prefix="skillvaya_plus_spotlight_")
    sv.DB = os.path.join(tmp.name, "qa.sqlite3")
    sv.SESSIONS.clear()
    sv.init()
    server = ThreadingHTTPServer(("127.0.0.1", 0), sv.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % server.server_address[1]

    def request(path, method="GET", data=None, token=None, expected=200):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(
            base + path, method=method, headers=headers,
            data=None if data is None else json.dumps(data).encode("utf-8"))
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        assert status == expected, (method, path, status, raw[:400])
        if path.startswith("/business-profile/") or path.startswith("/review/") or path == "/subscription-test-lab":
            return raw.decode("utf-8", errors="replace")
        return json.loads(raw) if raw else {}

    try:
        lab = request("/api/subscription-test-lab")
        assert lab["simulation_only"] is True and lab["payments_enabled"] is False and lab["mutations_enabled"] is False
        assert {x["id"] for x in lab["plans"]} == {"local", "priority", "plus", "spotlight"}
        lab_page = request("/subscription-test-lab")
        assert "Simulation only" in lab_page and "PayFast" in lab_page
        provider = request("/api/signup", "POST", {
            "name": "Plus QA", "email": "plus-qa@example.invalid",
            "password": "SafePass123", "role": "provider", "accept_terms": True,
        }, expected=200)
        token = provider["token"]
        request("/api/businesses", "POST", {
            "name": "Plus QA Services", "category": "Plumbers", "area": "Johannesburg",
            "phone": "+27123456789", "description": "QA test business only",
        }, token=token, expected=201)
        with sqlite3.connect(sv.DB) as c:
            c.execute("UPDATE businesses SET status='active',payment_status='verified',plan='plus',subscription_expires_at=? WHERE user_id=?",
                      ((sv.datetime.datetime.now(sv.datetime.timezone.utc)+sv.datetime.timedelta(days=20)).isoformat(), provider["user"]["id"]))
        data = request("/api/business-tools/data", token=token)
        assert data["business"]["plan"] == "plus"
        assert {"jobs", "calendar", "customers", "quotes", "invoices", "packages"}.issubset(set(data["available"]))
        assert "team" not in data["available"]
        assert "campaigns" not in data["available"] and "offers" not in data["available"]

        job = request("/api/business-tools/jobs", "POST", {
            "title": "Leaking tap", "customer_name": "QA Customer", "amount": "1250.50", "scheduled_for": "2026-11-01",
        }, token=token, expected=201)
        request("/api/business-tools/calendar/%d" % job["id"], "POST", {
            "status": "booked",
        }, token=token)
        request("/api/business-tools/customers", "POST", {
            "name": "QA Customer", "phone": "0123456789", "notes": "Test record",
        }, token=token, expected=201)
        request("/api/business-tools/quotes", "POST", {
            "customer_name": "QA Customer", "description": "Tap replacement", "amount": "750",
        }, token=token, expected=201)
        invoice = request("/api/business-tools/invoices", "POST", {
            "customer_name": "QA Customer", "reference": "QA-INV-1", "amount": "750",
        }, token=token, expected=201)
        request("/api/business-tools/invoices/%d" % invoice["id"], "POST", {
            "status": "paid",
        }, token=token)
        request("/api/business-tools/packages", "POST", {
            "title": "Standard plumbing visit", "description": "Labour included", "price": "650",
        }, token=token, expected=201)
        request("/api/business-tools/campaigns", "POST", {
            "title": "Plus must not create this",
        }, token=token, expected=403)
        request("/api/business-tools/team", "POST", {
            "name": "Plus should not add staff", "email": "blocked@example.invalid", "role": "Technician",
        }, token=token, expected=403)

        with sqlite3.connect(sv.DB) as c:
            c.execute("UPDATE businesses SET plan='spotlight' WHERE user_id=?", (provider["user"]["id"],))
        data = request("/api/business-tools/data", token=token)
        assert {"campaigns", "offers", "announcements", "team"}.issubset(set(data["available"]))
        member = request("/api/business-tools/team", "POST", {
            "name": "Sam Tech", "email": "sam-tech@example.invalid", "phone": "0820000000", "role": "Technician",
        }, token=token, expected=201)
        profile = request("/business-profile/%d" % data["business"]["id"])
        assert "BUSINESS SPOTLIGHT" in profile and "Plus QA Services" in profile
        campaign = request("/api/business-tools/campaigns", "POST", {
            "title": "Spring plumbing offer", "channel": "Skillvaya",
            "description": "Test campaign", "start_date": "2026-11-01",
        }, token=token, expected=201)
        request("/api/business-tools/campaigns/%d" % campaign["id"], "POST", {
            "status": "active",
        }, token=token)
        request("/api/business-tools/jobs", "POST", {
            "title": "Campaign lead", "customer_name": "Attributed customer",
            "lead_source": "Spring plumbing offer", "amount": "300", "assigned_to": "Sam Tech",
        }, token=token, expected=201)
        completed_job = request("/api/business-tools/jobs", "POST", {
            "title": "Completed bathroom repair", "customer_name": "Review Customer", "amount": "900",
        }, token=token, expected=201)
        request("/api/business-tools/jobs/%d" % completed_job["id"], "POST", {
            "status": "completed",
        }, token=token)
        request("/api/business-tools/jobs/%d/assignment" % completed_job["id"], "POST", {
            "assigned_to": "Sam Tech",
        }, token=token)
        review_link = request("/api/business-tools/review-links", "POST", {
            "job_id": completed_job["id"],
        }, token=token, expected=201)
        review_page = request(review_link["review_url"])
        assert "Review Plus QA Services" in review_page
        review_token = review_link["review_url"].rsplit("/", 1)[1]
        request("/api/review/" + review_token, "POST", {
            "customer_name": "Review Customer", "rating": 5,
            "review_text": "Excellent work and clear communication.",
        }, expected=201)
        request("/api/review/" + review_token, "POST", {
            "customer_name": "Review Customer", "rating": 5,
            "review_text": "Duplicate should not be accepted.",
        }, expected=404)
        with sqlite3.connect(sv.DB) as c:
            rating = c.execute("SELECT rating FROM businesses WHERE id=?", (data["business"]["id"],)).fetchone()[0]
        assert rating == 5.0
        request("/api/business-tools/offers", "POST", {
            "title": "Spring discount", "code": "SPRINGQA", "discount_text": "10% off",
            "redemption_limit": 20,
        }, token=token, expected=201)
        request("/api/business-tools/announcements", "POST", {
            "title": "Holiday hours", "message": "We are open for emergency call-outs.",
        }, token=token, expected=201)
        customer = request("/api/signup", "POST", {
            "name": "Campaign Customer", "email": "campaign-customer@example.invalid",
            "password": "SafePass789", "role": "customer", "accept_terms": True,
        }, expected=200)
        request("/api/enquiries", "POST", {
            "business_id": data["business"]["id"], "message": "I found this through the campaign",
            "lead_source": "Spring plumbing offer",
        }, token=customer["token"], expected=201)
        data = request("/api/business-tools/data", token=token)
        assert len(data["jobs"]) == 3
        assert any(x["assigned_to"] == "Sam Tech" for x in data["jobs"])
        assert len(data["team"]) == 1 and data["team"][0]["name"] == "Sam Tech"
        assert any(x["status"] == "booked" for x in data["jobs"])
        assert any(x["scheduled_for"] == "2026-11-01" for x in data["calendar"])
        assert len(data["customers"]) == 1 and len(data["quotes"]) == 1
        assert data["invoices"][0]["status"] == "paid"
        assert len(data["packages"]) == 1 and len(data["campaigns"]) == 1 and len(data["offers"]) == 1
        assert len(data["announcements"]) == 1
        profile = request("/business-profile/%d" % data["business"]["id"])
        assert "Spring discount" in profile and "SPRINGQA" in profile
        assert "Holiday hours" in profile and "emergency call-outs" in profile
        assert data["campaigns"][0]["tracked_leads"] == 2
        assert data["campaigns"][0]["tracked_estimated_value_cents"] == 30000

        no_token = request("/api/business-tools/data", expected=401)
        assert "error" in no_token
        print("PASS Plus/Spotlight workspace: paid entitlement gate, Plus CRUD, Spotlight-only campaign/offers, status updates and persistence")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        sv.SESSIONS.clear()
        tmp.cleanup()
        gc.collect()


if __name__ == "__main__":
    main()
