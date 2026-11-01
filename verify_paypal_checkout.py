import json, os, tempfile, threading, urllib.request, urllib.error
from http.server import ThreadingHTTPServer

# All payment-provider calls below are mocked. This test cannot charge a real account.
os.environ.pop("DATABASE_URL", None)
os.environ.pop("SKILLVAYA_DB_PATH", None)
os.environ["SKILLVAYA_OWNER_EMAIL"] = "qa-owner@example.test"
os.environ["SKILLVAYA_OWNER_PASSWORD"] = "QA-owner-password-12345"
os.environ["SKILLVAYA_PAYPAL_MODE"] = "sandbox"
os.environ["SKILLVAYA_PAYPAL_CLIENT_ID"] = "mock-sandbox-client-id"
os.environ["SKILLVAYA_PAYPAL_CLIENT_SECRET"] = "mock-sandbox-secret"
os.environ["SKILLVAYA_PUBLIC_URL"] = "https://skillvaya.example.test"
os.environ["SKILLVAYA_PAYPAL_ZAR_PER_USD"] = "16.0" # deterministic QA-only quote
import app

fd, db = tempfile.mkstemp(suffix=".sqlite3")
os.close(fd)
app.DB = db
app.SESSIONS.clear()
app.init()

state = {"number": 0, "orders": {}, "wrong_amount": False, "refund_calls": 0}
def fake_paypal_request(method, path, payload=None):
    if method == "POST" and path == "/v2/checkout/orders":
        state["number"] += 1
        order_id = "MOCK-ORDER-%03d" % state["number"]
        unit = payload["purchase_units"][0]
        state["orders"][order_id] = {
            "reference": unit["custom_id"],
            "amount": unit["amount"]["value"],
            "currency": unit["amount"]["currency_code"],
        }
        return {"id": order_id, "status": "CREATED", "links": [
            {"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=" + order_id}
        ]}
    if method == "POST" and path.endswith("/capture"):
        order_id = path.split("/")[-2]
        item = state["orders"][order_id]
        amount = "200.00" if state["wrong_amount"] else item["amount"]
        return {"id": order_id, "status": "COMPLETED", "purchase_units": [{
            "custom_id": item["reference"],
            "payments": {"captures": [{
                "id": "MOCK-CAPTURE-" + order_id,
                "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": amount},
            }]},
        }]}
    if method == "POST" and "/v2/payments/captures/" in path and path.endswith("/refund"):
        state["refund_calls"] += 1
        return {"id": "MOCK-REFUND-%03d" % state["refund_calls"], "status": "COMPLETED",
                "amount": payload["amount"]}
    raise AssertionError("Unexpected PayPal call: %s %s" % (method, path))

app.paypal_api_request = fake_paypal_request
app.paypal_access_token = lambda: "mock-oauth-access-token"
server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % server.server_address[1]
passed = []

def request(path, method="GET", data=None, token=None, expected=200):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, method=method, headers=headers,
        data=None if data is None else json.dumps(data).encode())
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    assert status == expected, "%s %s expected %s got %s: %s" % (method, path, expected, status, body[:300])
    return json.loads(body) if body else {}

def db_one(sql, params=()):
    with app.conn() as c:
        return c.execute(sql, params).fetchone()

def check(name, fn):
    fn()
    passed.append(name)
    print("PASS", name)

try:
    provider = request("/api/signup", "POST", {
        "name":"PayPal QA Provider", "email":"qa-paypal-provider@example.test",
        "password":"SecureQApass123", "phone":"+27821110009",
        "role":"provider", "accept_terms":True,
    })
    token = provider["token"]
    admin = request("/api/login", "POST", {
        "email":os.environ["SKILLVAYA_OWNER_EMAIL"],
        "password":os.environ["SKILLVAYA_OWNER_PASSWORD"],
    })
    admin_token = admin["token"]

    gateway = request("/api/payment-provider")
    check("PayPal Sandbox is the only provider advertised", lambda: (_ for _ in ()).throw(AssertionError(gateway)) if gateway.get("provider") != "paypal" or gateway.get("mode") != "sandbox" or not gateway.get("paypal_ready") else None)
    status = request("/api/admin/paypal/status", token=admin_token)
    check("Owner diagnostics successfully verify mocked Sandbox OAuth without exposing secrets", lambda: (_ for _ in ()).throw(AssertionError(status)) if not status.get("oauth_valid") or not status.get("checkout_ready") or status.get("provider") != "paypal" else None)

    play_only = request("/api/paypal/create-order", "POST", {"plan":"priority","billing":"monthly"}, token=token, expected=410)
    check("Website PayPal checkout is retired with the Google Play-only notice", lambda: (_ for _ in ()).throw(AssertionError(play_only)) if not play_only.get("play_only") or "Google Play" not in play_only.get("error","") else None)

    capture = request("/api/paypal/capture", "POST", {"order_id":"MOCK-ORDER-001"}, token=token, expected=404)
    check("Capture without a matching Skillvaya payment is refused", lambda: (_ for _ in ()).throw(AssertionError(capture)) if "does not match" not in capture.get("error","") else None)

    check("Retired website checkout creates no payment record and calls no PayPal API", lambda: (_ for _ in ()).throw(AssertionError((db_one("SELECT count(*) FROM payments")[0], state))) if db_one("SELECT count(*) FROM payments")[0] != 0 or state["number"] != 0 or state["refund_calls"] != 0 else None)

    before = db_one("SELECT count(*) FROM payments")[0]
    retired_checkout = request("/api/payments", "POST", {"plan":"local","billing":"monthly"}, token=token, expected=410)
    assert "Sandbox" not in retired_checkout.get("error", "") and "PayPal" in retired_checkout.get("error", ""), retired_checkout
    request("/api/payfast/itn", "POST", {}, expected=410)
    after = db_one("SELECT count(*) FROM payments")[0]
    check("Legacy PayFast endpoints remain retired without misleading PayPal Sandbox instructions", lambda: (_ for _ in ()).throw(AssertionError((before,after))) if before != after else None)
    print("RESULT %d PayPal flow checks passed; calls to PayPal were mocked, so no real payment was sent." % len(passed))
finally:
    server.shutdown()
    server.server_close()
    try:
        os.unlink(db)
    except OSError:
        pass
