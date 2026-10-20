import json, os, sqlite3, tempfile, threading, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
import app as sv

tmp=tempfile.TemporaryDirectory(prefix="skillvaya_qa_")
sv.DB=os.path.join(tmp.name,"qa.sqlite3")
sv.SESSIONS.clear()
os.environ["SKILLVAYA_PAYFAST_MODE"]="sandbox"
os.environ.pop("SKILLVAYA_PUBLIC_URL",None)
sv.init()
server=ThreadingHTTPServer(("127.0.0.1",0),sv.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
base="http://127.0.0.1:%d"%server.server_address[1]
passed=[]
def request(path,method="GET",data=None,token=None,expected=200):
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    req=urllib.request.Request(base+path,method=method,headers=headers,data=None if data is None else json.dumps(data).encode())
    try:
        with urllib.request.urlopen(req,timeout=5) as r: status,body=r.status,r.read()
    except urllib.error.HTTPError as e: status,body=e.code,e.read()
    assert status==expected,"%s %s expected %s got %s: %s"%(method,path,expected,status,body[:300])
    if path in ("/","/customer","/owner-control","/owner-app"): return body.decode("utf-8",errors="replace")
    return json.loads(body) if body else {}
def check(name,fn):
    fn(); passed.append(name); print("PASS",name)
try:
    root=request("/")
    check("Public Skillvaya website serves as the root screen",lambda: (_ for _ in ()).throw(AssertionError()) if "Find your people" not in root or "Download / install app" not in root else None)
    check("Owner App remains on its separate route",lambda: (_ for _ in ()).throw(AssertionError()) if "Owner App" not in request("/owner-app") else None)
    check("Customer app remains a separate route",lambda: (_ for _ in ()).throw(AssertionError()) if "Choose plan" not in request("/customer") else None)
    check("Owner Control has a payment/refund section",lambda: (_ for _ in ()).throw(AssertionError()) if "PayFast payment requests" not in request("/owner-control") else None)
    check("category directory is available",lambda: (_ for _ in ()).throw(AssertionError()) if len(request("/api/categories")["categories"])<30 else None)
    check("Terms acceptance is enforced",lambda: request("/api/signup","POST",{"name":"QA","email":"no-terms@example.invalid","password":"SafePass123","role":"customer","accept_terms":False},expected=400))
    provider=request("/api/signup","POST",{"name":"QA Provider","email":"qa-provider@example.invalid","password":"SafePass123","role":"provider","accept_terms":True})
    pt=provider["token"]
    check("signup stores accepted terms and a strong password hash",lambda: (lambda row: (_ for _ in ()).throw(AssertionError(str(row))) if not row or row[0]!="2026-10-20" or not row[1].startswith("pbkdf2_sha256$") or not row[2] else None)(sqlite3.connect(sv.DB).execute("select accepted_terms_version,password_hash,accepted_terms_at from users where email='qa-provider@example.invalid'").fetchone()))
    check("provider login succeeds",lambda: request("/api/login","POST",{"email":"qa-provider@example.invalid","password":"SafePass123"}))
    check("wrong password is rejected",lambda: request("/api/login","POST",{"email":"qa-provider@example.invalid","password":"wrong-pass"},expected=401))
    check("provider can submit a listing",lambda: request("/api/businesses","POST",{"name":"QA Real Service","category":"Plumbers","area":"Johannesburg","phone":"+27123456789","description":"QA-only service listing."},token=pt,expected=201))
    before=sqlite3.connect(sv.DB).execute("select count(*) from payments").fetchone()[0]
    request("/api/payments","POST",{"plan":"local","billing":"monthly"},token=pt,expected=503)
    after=sqlite3.connect(sv.DB).execute("select count(*) from payments").fetchone()[0]
    check("checkout is blocked without a public HTTPS callback and creates no ghost payment",lambda: (_ for _ in ()).throw(AssertionError((before,after))) if before!=after else None)
    os.environ["SKILLVAYA_PUBLIC_URL"]="https://skillvaya.example.test"
    payment=request("/api/payments","POST",{"plan":"priority","billing":"monthly"},token=pt)
    check("sandbox checkout fields are signed and contain the HTTPS ITN callback",lambda: (_ for _ in ()).throw(AssertionError(payment)) if not payment.get("checkout_ready") or payment["fields"]["amount"]!="210.00" or payment["fields"]["notify_url"]!="https://skillvaya.example.test/api/payfast/itn" or payment["fields"]["signature"]!=sv.pf_form_signature({k:v for k,v in payment["fields"].items() if k!="signature"},sv.payfast_config()["passphrase"]) else None)
    check("payment remains pending until PayFast verification",lambda: (_ for _ in ()).throw(AssertionError(payment)) if payment.get("status")!="pending" else None)
    rows=request("/api/admin/payments")["items"]
    pid=next(x["id"] for x in rows if x["reference"]==payment["reference"])
    request("/api/admin/payments/%s"%pid,"POST",{},expected=409)
    check("manual payment verification is blocked",lambda: (_ for _ in ()).throw(AssertionError()) if sqlite3.connect(sv.DB).execute("select status from payments where id=?",(pid,)).fetchone()[0]!="pending" else None)
    ok,msg=sv.process_payfast_itn(b"merchant_id=10000100&pf_payment_id=12345&signature=bad")
    check("invalid PayFast ITN signature is rejected",lambda: (_ for _ in ()).throw(AssertionError((ok,msg))) if ok or "signature" not in msg.lower() else None)
    status=request("/api/admin/payfast/status")
    check("owner can see gateway mode and readiness",lambda: (_ for _ in ()).throw(AssertionError(status)) if status["mode"]!="sandbox" or not status["public_https_configured"] or not status["checkout_ready"] else None)
    bid=sqlite3.connect(sv.DB).execute("select id from businesses where name='QA Real Service'").fetchone()[0]
    request("/api/admin/businesses/%s"%bid,"POST",{"status":"active"})
    customer=request("/api/signup","POST",{"name":"QA Customer","email":"qa-customer@example.invalid","password":"SafePass456","role":"customer","accept_terms":True})
    check("customer can send an enquiry",lambda: request("/api/enquiries","POST",{"business_id":bid,"message":"QA enquiry"},token=customer["token"],expected=201))
    check("customer can submit a complaint",lambda: request("/api/complaints","POST",{"business_id":bid,"reason":"QA-only report"},token=customer["token"],expected=201))
    complaints=request("/api/admin/complaints")["items"]
    cid=next(x["id"] for x in complaints if x["reason"]=="QA-only report")
    request("/api/admin/complaints/%s"%cid,"POST",{})
    check("owner can review a complaint",lambda: (_ for _ in ()).throw(AssertionError()) if not any(x["id"]==cid and x["status"]=="reviewed" for x in request("/api/admin/complaints")["items"]) else None)
    check("fresh install does not publish fabricated demo providers",lambda: (_ for _ in ()).throw(AssertionError()) if any(x.get("payment_status")=="demo" for x in request("/api/businesses")["businesses"]) else None)
    print("RESULT %d/%d checks passed"%(len(passed),len(passed)))
finally:
    server.shutdown(); server.server_close()
    try: tmp.cleanup()
    except PermissionError: pass
