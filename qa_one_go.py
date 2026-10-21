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
    check("Root route opens the public app with sign-in in Profile",lambda: (_ for _ in ()).throw(AssertionError("app shell or Profile sign-in missing")) if 'id="customer"' not in root or "Profile / Sign in" not in root or "Sign in to open your Skillvaya workspace." in root else None)
    check("Customer entry route opens the same public app",lambda: (_ for _ in ()).throw(AssertionError("customer app shell missing")) if 'id="customer"' not in customer_entry or "Profile / Sign in" not in customer_entry else None)
    check("Marketing page remains separate on /website",lambda: (_ for _ in ()).throw(AssertionError("website route missing")) if "Find your people" not in website or "Install Skillvaya" not in website else None)
    check("Installed web app manifest launches at /login",lambda: (_ for _ in ()).throw(AssertionError(manifest)) if manifest.get("start_url","").split("?")[0]!="/login" else None)
    check("Workspace route restores saved sessions instead of forcing a gateway login",lambda: (_ for _ in ()).throw(AssertionError("session restore or profile-only login missing")) if "if(!token){location.replace('/');return}" in workspace or "Profile / Sign in" not in workspace else None)
    check("Sign-in is not duplicated in the main navigation",lambda: (_ for _ in ()).throw(AssertionError("duplicate sign-in/logout navigation found")) if 'id="nav-account"' in workspace or '<button onclick="logout()">Log out</button>' in workspace else None)
    check("Provider profile form is gated behind verified payment",lambda: (_ for _ in ()).throw(AssertionError("provider profile gate missing")) if 'id="providerProfileCard" class="card hidden"' not in workspace or "refreshProviderGate" not in workspace else None)
    check("Main tabs hide unrelated owner promotions and owner login routes to owner workspace",lambda: (_ for _ in ()).throw(AssertionError("tab isolation or owner routing missing")) if "ownerPublic.classList.toggle('hidden',v!=='customer')" not in workspace or "if(v==='admin'){location.href='/owner-app';return}" not in workspace else None)
    check("Owner-free provider studio has its own no-payment path",lambda: (_ for _ in ()).throw(AssertionError("owner free profile path missing")) if "OWNER FREE ACCESS" not in workspace or "providerPlansCard" not in workspace or "payment is required" not in workspace else None)
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
    check("Provider cannot create profile before verified payment",lambda: request("/api/businesses","POST",{"name":"QA Real Service","category":"Plumbers","area":"Johannesburg","phone":"+27123456789","description":"QA-only service listing."},token=pt,expected=403))
    with sv.conn() as c:
        c.execute("INSERT INTO payments(user_id,plan,billing,amount,reference,status,created_at,verified_at) VALUES(?,?,?,?,?,'verified',?,?)",(provider["user"]["id"],"spotlight","monthly",500,"SV-QA-PROFILE",sv.now(),sv.now()))
    listing=request("/api/businesses","POST",{"name":"QA Real Service","category":"Plumbers","area":"Johannesburg","phone":"+27123456789","description":"QA-only service listing."},token=pt,expected=201)
    check("Verified payment unlocks and activates provider profile",lambda: (_ for _ in ()).throw(AssertionError(str(listing))) if not listing.get("ok") else None)
    row=db_one("SELECT plan,status,payment_status FROM businesses WHERE name=?",("QA Real Service",))
    check("Paid provider profile inherits the verified plan",lambda: (_ for _ in ()).throw(AssertionError(str(row))) if not row or row[0]!="spotlight" or row[1]!="active" or row[2]!="verified" else None)
    payment=db_one("SELECT business_id FROM payments WHERE reference=?",("SV-QA-PROFILE",))
    check("Verified payment is linked to the created provider profile",lambda: (_ for _ in ()).throw(AssertionError(str(payment))) if not payment or payment[0] is None else None)
    def cookie_session_check():
        req=urllib.request.Request(base+"/api/login",method="POST",headers={"Content-Type":"application/json"},data=json.dumps({"email":"qa-provider@example.invalid","password":"SafePass123","accept_terms":True}).encode())
        with urllib.request.urlopen(req,timeout=8) as r:
            data=json.loads(r.read()); cookie=r.headers.get("Set-Cookie","")
        assert "skillvaya_session=" in cookie, "persistent session cookie was not set"
        token_value=cookie.split("skillvaya_session=",1)[1].split(";",1)[0]
        q=urllib.request.Request(base+"/api/me",headers={"Cookie":"skillvaya_session="+token_value})
        with urllib.request.urlopen(q,timeout=8) as r: restored=json.loads(r.read())
        assert restored.get("user",{}).get("role")=="provider", restored
    check("Persistent cookie restores provider session without localStorage bearer token",cookie_session_check)
    owner=request("/api/login","POST",{"email":os.environ["SKILLVAYA_OWNER_EMAIL"],"password":os.environ["SKILLVAYA_OWNER_PASSWORD"],"accept_terms":True})
    at=owner["token"]
    check("Owner account logs in as administrator",lambda: (_ for _ in ()).throw(AssertionError("owner role mismatch")) if owner.get("user",{}).get("role")!="admin" else None)
    owner_free=request("/api/admin/owner-promotions","POST",{"kind":"business","business_name":"QA Owner Free Service","title":"QA Owner Free Service","category":"Plumbers","description":"QA-only owner listing with free publication.","area":"Johannesburg","phone":"+27110000000","contact_email":os.environ["SKILLVAYA_OWNER_EMAIL"]},token=at,expected=201)
    check("Owner can publish a service listing free without a provider payment",lambda: (_ for _ in ()).throw(AssertionError(str(owner_free))) if not owner_free.get("owner_free") or owner_free.get("payment_required") is not False or not owner_free.get("directory_business_id") else None)
    owner_listing=db_one("SELECT area,phone,plan,status,payment_status FROM businesses WHERE name=?",("QA Owner Free Service",))
    check("Owner free listing includes entered service area and contact details",lambda: (_ for _ in ()).throw(AssertionError(str(owner_listing))) if not owner_listing or owner_listing[0]!="Johannesburg" or owner_listing[1]!="+27110000000" or owner_listing[2]!="local" or owner_listing[3]!="active" or owner_listing[4]!="verified" else None)
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
