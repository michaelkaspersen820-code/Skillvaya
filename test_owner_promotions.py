import gc, json, os, tempfile, threading, urllib.request, urllib.error
import app
from http.server import ThreadingHTTPServer

def main():
    db = os.path.join(tempfile.gettempdir(), "skillvaya_owner_promotions_regression.sqlite3")
    try:
        os.remove(db)
    except OSError:
        pass
    app.DB = db
    app.SESSIONS.clear()
    app.init()
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:" + str(server.server_address[1])
    def request(path, method="GET", data=None, expected=200):
        req = urllib.request.Request(
            base + path, method=method,
            headers={"Content-Type": "application/json"},
            data=None if data is None else json.dumps(data).encode("utf-8"))
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        assert status == expected, (path, status, raw[:300])
        return json.loads(raw) if raw else {}
    try:
        assert "owner-control" not in app.HTML
        assert "My Businesses & Promotions" in app.OWNER_HTML
        # Current owner app intentionally keeps Payments & refunds in its own
        # top-level area; free owner listings/promotions live in the Owner Control.
        assert 'data-tab="payments"' in app.OWNER_APP_HTML
        assert 'My Free App' in app.OWNER_APP_HTML
        assert 'class="tabs"' in app.OWNER_APP_HTML
        assert 'My businesses & promotions (free)' in app.OWNER_HTML
        created = request("/api/admin/owner-promotions", "POST", {
            "kind": "app", "business_name": "Test Studio", "title": "Test App",
            "category": "Web & software developers", "description": "Regression test",
            "target_url": "https://example.com", "image_url": ""
        }, 201)
        assert created["owner_free"] is True
        rows = request("/api/admin/owner-promotions")["items"]
        assert len(rows) == 1 and rows[0]["owner_free"] == 1
        public = request("/api/owner-promotions")["items"]
        assert len(public) == 1 and public[0]["title"] == "Test App"
        request("/api/admin/owner-promotions/" + str(created["id"]), "POST", {"status": "paused"})
        assert request("/api/owner-promotions")["items"] == []
        request("/api/admin/owner-promotions/" + str(created["id"]), "POST", {"status": "active"})
        assert len(request("/api/owner-promotions")["items"]) == 1

        # Business-type promotions must stay synchronized with the public service directory.
        business = request("/api/admin/owner-promotions", "POST", {
            "kind": "business", "business_name": "Test Free Plumbing", "title": "Test Free Plumbing",
            "category": "Plumbers", "description": "Free owner plumbing listing",
            "area": "Johannesburg", "phone": "+27110000000", "whatsapp": "+27820000000",
            "contact_email": "owner-listing@example.test", "target_url": "", "image_url": ""
        }, 201)
        assert business["owner_free"] is True and business["payment_required"] is False
        directory_id = business["directory_business_id"]
        public = request("/api/businesses")["businesses"]
        listing = next(x for x in public if x["id"] == directory_id)
        assert listing["name"] == "Test Free Plumbing" and listing["area"] == "Johannesburg"
        assert listing["phone"] == "+27110000000" and listing["whatsapp"] == "+27820000000"
        assert listing["email"] == "owner-listing@example.test"

        request("/api/admin/owner-promotions/" + str(business["id"]), "POST", {"status": "paused"})
        assert all(x["id"] != directory_id for x in request("/api/businesses")["businesses"])
        request("/api/admin/owner-promotions/" + str(business["id"]), "POST", {"status": "active"})
        assert any(x["id"] == directory_id for x in request("/api/businesses")["businesses"])

        updated = request("/api/admin/owner-promotions/" + str(business["id"]), "POST", {
            "action": "update", "kind": "business", "business_name": "Updated Free Plumbing",
            "title": "Updated Free Plumbing", "category": "Plumbers", "description": "Updated free owner listing",
            "area": "Cape Town", "phone": "+27210000000", "whatsapp": "+27821111111",
            "contact_email": "updated-owner@example.test", "target_url": "", "image_url": ""
        })
        assert updated["ok"] and updated["directory_business_id"] == directory_id
        listing = next(x for x in request("/api/businesses")["businesses"] if x["id"] == directory_id)
        assert listing["name"] == "Updated Free Plumbing" and listing["area"] == "Cape Town"
        assert listing["phone"] == "+27210000000" and listing["whatsapp"] == "+27821111111"
        assert listing["email"] == "updated-owner@example.test"
        request("/api/admin/owner-promotions/" + str(business["id"]), "POST", {"status": "removed"})
        assert all(x["id"] != directory_id for x in request("/api/businesses")["businesses"])
        print("PASS owner promotions: fee exemption, public publishing, contact fields, linked directory pause/republish/remove, and edits")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    gc.collect()
    try:
        os.remove(db)
    except OSError:
        pass

if __name__ == "__main__":
    main()
