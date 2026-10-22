import sys, threading, urllib.request, urllib.error, json, urllib.parse
sys.path.insert(0,'.')
import app
app.init()
assert app.payfast_config()["mode"] in ("sandbox","live")
assert app.pf_form_signature({"merchant_id":"10000100","amount":"105.00"},"test")
ok,msg=app.process_payfast_itn(b"merchant_id=10000100&signature=bad")
assert not ok and "signature" in msg.lower(), (ok,msg)
server=app.ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
base="http://127.0.0.1:"+str(server.server_address[1])
def get(path):
 with urllib.request.urlopen(base+path,timeout=4) as r: return r.status,r.read().decode()
assert get("/")[0]==200
assert get("/customer")[0]==200
assert get("/owner-control")[0]==200
assert get("/manifest.json")[0]==200
status,body=get("/api/categories")
assert status==200 and "Builders & construction" in body
# PayFast is intentionally retired: the old payment route must stay disabled,
# while PayPal remains the only supported checkout provider.
req=urllib.request.Request(base+"/api/payments",data=json.dumps({"plan":"local","billing":"monthly"}).encode(),headers={"Content-Type":"application/json"},method="POST")
try:
 urllib.request.urlopen(req,timeout=4)
 raise AssertionError("Retired PayFast route unexpectedly accepted a payment")
except urllib.error.HTTPError as e:
 assert e.code==410
server.shutdown()
print("PASS: Python compile/import, database migration, PayFast signature rejection, root/customer/owner routes, manifest/categories, retired PayFast checkout stays disabled (HTTP 410)")
