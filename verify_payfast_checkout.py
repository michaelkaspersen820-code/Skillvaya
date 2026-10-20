import os, sys, tempfile, threading, urllib.request, urllib.error, json
sys.path.insert(0,'.')
import app
fd,db=tempfile.mkstemp(suffix=".sqlite3"); os.close(fd)
app.DB=db
os.environ["SKILLVAYA_PAYFAST_MODE"]="sandbox"
os.environ["SKILLVAYA_PUBLIC_URL"]="https://skillvaya.example.test"
app.init()
server=app.ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
base="http://127.0.0.1:"+str(server.server_address[1])
def post(path,payload,token=None):
 headers={"Content-Type":"application/json"}
 if token: headers["Authorization"]="Bearer "+token
 req=urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers=headers,method="POST")
 with urllib.request.urlopen(req,timeout=8) as r:return r.status,json.loads(r.read().decode())
status,signup=post("/api/signup",{"name":"Test Provider","email":"test-provider@example.test","password":"SecureTestPass123","role":"provider","accept_terms":True})
assert status==200,(status,signup)
status,payment=post("/api/payments",{"plan":"priority","billing":"monthly"},signup["token"])
assert status==200,(status,payment)
assert payment["checkout_ready"] is True,payment
assert payment["fields"]["amount"]=="210.00"
assert payment["fields"]["notify_url"]=="https://skillvaya.example.test/api/payfast/itn"
assert payment["fields"]["signature"]==app.pf_form_signature({k:v for k,v in payment["fields"].items() if k!="signature"},app.payfast_config()["passphrase"])
# A verified payment record is not created just by returning from PayFast.
with app.conn() as c:
 row=c.execute("SELECT status,pf_payment_id FROM payments WHERE reference=?",(payment["reference"],)).fetchone()
 assert row["status"]=="pending" and not row["pf_payment_id"]
server.shutdown()
print("PASS: sandbox checkout fields, amount, public HTTPS ITN URL, signature, and pending-until-verified behavior")
