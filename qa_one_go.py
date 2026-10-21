import json, os, tempfile, threading, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
import app as sv

tmp=tempfile.TemporaryDirectory(prefix="skillvaya_qa_")
if not os.environ.get("DATABASE_URL"):
    sv.DB=os.path.join(tmp.name,"qa.sqlite3")
sv.SESSIONS.clear()
os.environ.setdefault("SKILLVAYA_OWNER_EMAIL","owner-ci@example.com")
os.environ.setdefault("SKILLVAYA_OWNER_PASSWORD","ci-test-password-12345")
os.environ.setdefault("SKILLVAYA_PAYPAL_MODE","sandbox")
sv.init()
server=ThreadingHTTPServer(("127.0.0.1",0),sv.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
base="http://127.0.0.1:%d"%server.server_address[1]
passed=[]; skipped=[]

def request(path,method="GET",data=None,token=None,expected=200):
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    req=urllib.request.Request(base+path,method=method,headers=headers,
        data=None if data is None else json.dumps(data).encode())
    try:
        with urllib.request.urlopen(req,timeout=8) as r: status,body=r.status,r.read()
    except urllib.error.HTTPError as e: status,body=e.code,e.read()
    assert status==expected,"%s %s expected %s got %s: %s"%(method,path,expected,status,body[:300])
    if path in ("/","/customer","/website","/customer-app","/owner-control","/owner-app"): return body.decode("utf-8",errors="replace")
    return json.loads(body) if body else {}

def db_one(sql,params=()):
    with sv.conn() as c: return c.execute(sql,params).fetchone()

def check(name,fn):
    fn();passed.append(name);print("PASS",name)

try:
    root=request("/")
    customer_entry=request("/customer")
    website=request("/website")
    workspace=request("/customer-app")
    manifest=request("/manifest.json")
    check("Root route opens sign-in first",lambda: (_ for _ in ()).throw(AssertionError("login missing")) if "Sign in to open your Skillvaya workspace." not in root else None)
    check("Customer entry route opens sign-in first",lambda: (_ for _ in ()).throw(AssertionError("customer entry bypasses login")) if "Sign in to open your Skillvaya workspace." not in customer_entry else None)
    check("Marketing page remains separate on /website",lambda: (_ for _ in ()).throw(AssertionError("website route missing")) if "Find your people" not in website or "Install Skillvaya" not in website else None)
    check("Installed web app manifest launches at /login",lambda: (_ for _ in ()).throw(AssertionError(manifest)) if manifest.get("start_url","").split("?")[0]!="/login" else None)
    check("Workspace route has a valid-session guard",lambda: (_ for _ in ()).throw(AssertionError("session guard missing")) if "if(!token){location.replace('/');return}" not in workspace else None)
    owner_app=request("/owner-app")
    owner_control=request("/owner-control")
    check("Owner app uses the SV brand image",lambda: (_ for _ in ()).throw(AssertionError("owner shell missing")) if "Owner App" not in owner_app or "/sv-logo.jpeg" not in owner_app else None)
    check("Owner Control exposes PayPal payment/refund controls",lambda: (_ for _ in ()).throw(AssertionError("PayPal controls missing")) if "PayPal payment requests & refunds" not in owner_control else None)
    check("Searchable category directory is available",lambda: (_ for _ in ()).throw(AssertionError("category directory too small")) if len(request("/api/categories")["categories"])<30 else None)
    check("Terms acceptance is enforced",lambda: request("/api/signup","POST",{"name":"QA","email":"no-terms@example.invalid","password":"SafePass123","role":"customer","accept_terms":False},expected=400))
    provider=request("/api/signup","POST",{"name":"QA Provider","email":"qa-provider@example.invalid","password":"SafePass123","role":"provider","accept_terms":True})
    pt=provider["token"]
    row=db_one("SELECT accepted_terms_version,password_hash,accepted_terms_at FROM users WHERE email=?",("qa-provider@example.invalid",))
    check("Signup stores accepted terms and PBKDF2 password hash",lambda: (_ for _ in ()).throw(AssertionError(str(row))) if not row or row[0]!="2026-10-21-v1.2" or not row[1].startswith("pbkdf2_sha256$") or not row[2] else None)
    check("Server requires terms agreement at sign-in",lambda: request("/api/login","POST",{"email":"qa-provider@example.invalid","password":"SafePass123"},expected=400))
    check("Provider login succeeds after explicit terms agreement",lambda: request("/api/login","POST",{"email":"qa-provider@example.invalid","password":"SafePass123","accept_terms":True}))
    check("Wrong password is rejected",lambda: request("/api/login","POST",{"email":"qa-provider@example.invalid","password":"wrong-pass"},expected=401))
    check("Provider can submit a listing",lambda: request("/api/businesses","POST",{"name":"QA Real Service","category":"Plumbers","area":"Johannesburg","phone":"+27123456789","description":"QA-only service listing."},token=pt,expected=201))
    owner=request("/api/login","POST",{"email":os.environ["SKILLVAYA_OWNER_EMAIL"],"password":os.environ["SKILLVAYA_OWNER_PASSWORD"],"accept_terms":True})
    at=owner["token"]
    check("Owner account logs in as administrator",lambda: (_ for _ in ()).throw(AssertionError("owner role mismatch")) if owner.get("user",{}).get("role")!="admin" else None)
    gateway=request("/api/payment-provider")
    check("PayPal is the only advertised checkout provider",lambda: (_ for _ in ()).throw(AssertionError(gateway)) if gateway.get("provider")!="paypal" else None)
    before=db_one("SELECT count(*) FROM payments")[0]
    request("/api/payments","POST",{"plan":"local","billing":"monthly"},token=pt,expected=410)
    request("/api/payfast/itn","POST",{},expected=410)
    after=db_one("SELECT count(*) FROM payments")[0]
    check("Retired PayFast endpoints create no payment rows",lambda: (_ for _ in ()).throw(AssertionError((before,after))) if before!=after else None)
    pay_status=request("/api/admin/paypal/status",token=at)
    check("Owner diagnostics expose PayPal Sandbox readiness safely",lambda: (_ for _ in ()).throw(AssertionError(pay_status)) if pay_status.get("provider")!="paypal" or pay_status.get("mode")!="sandbox" else None)
    bid=db_one("SELECT id FROM businesses WHERE name=?",("QA Real Service",))[0]
    request("/api/admin/businesses/%s"%bid,"POST",{"status":"active"},token=at)
    customer=request("/api/signup","POST",{"name":"QA Customer","email":"qa-customer@example.invalid","password":"SafePass456","role":"customer","accept_terms":True})
    check("Customer can send an enquiry",lambda: request("/api/enquiries","POST",{"business_id":bid,"message":"QA enquiry"},token=customer["token"],expected=201))
    check("Customer can submit a complaint",lambda: request("/api/complaints","POST",{"business_id":bid,"reason":"QA-only report"},token=customer["token"],expected=201))
    complaints=request("/api/admin/complaints",token=at)["items"]
    cid=next(x["id"] for x in complaints if x["reason"]=="QA-only report")
    request("/api/admin/complaints/%s"%cid,"POST",{},token=at)
    check("Owner can review complaints",lambda: (_ for _ in ()).throw(AssertionError("complaint not reviewed")) if not any(x["id"]==cid and x["status"]=="reviewed" for x in request("/api/admin/complaints",token=at)["items"]) else None)
    check("Fresh install has no fabricated demo businesses",lambda: (_ for _ in ()).throw(AssertionError("demo business found")) if any(x.get("payment_status")=="demo" for x in request("/api/businesses")["businesses"]) else None)
    print("RESULT %d checks passed; %d skipped"%(len(passed),len(skipped)))
finally:
    server.shutdown();server.server_close()
    try:tmp.cleanup()
    except PermissionError:pass
