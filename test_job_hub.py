import json, os, tempfile, threading, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
os.environ.pop("DATABASE_URL",None); os.environ.pop("PORT",None)
os.environ["SKILLVAYA_OWNER_EMAIL"]="job-owner@example.test"
os.environ["SKILLVAYA_OWNER_PASSWORD"]="Job-hub-QA-password-123"
import app
fd,db=tempfile.mkstemp(suffix=".sqlite3"); os.close(fd)
app.DB=db; app.SESSIONS.clear(); app.init()
server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
base="http://127.0.0.1:%d"%server.server_address[1]
passed=[]
def req(path,method="GET",data=None,token=None,expected=200):
 headers={"Content-Type":"application/json"}
 if token: headers["Authorization"]="Bearer "+token
 q=urllib.request.Request(base+path,method=method,headers=headers,data=None if data is None else json.dumps(data).encode())
 try:
  with urllib.request.urlopen(q,timeout=8) as r: status,body=r.status,r.read()
 except urllib.error.HTTPError as e: status,body=e.code,e.read()
 assert status==expected,"%s %s: expected %s got %s %s"%(method,path,expected,status,body[:400])
 return json.loads(body) if body else {}
def check(name,fn): fn(); passed.append(name); print("PASS",name)
def one(sql,p=()):
 with app.conn() as c:return c.execute(sql,p).fetchone()
try:
 provider=req("/api/signup","POST",{"name":"Job Provider","email":"provider-jobs@example.test","password":"SecurePass123","role":"provider","accept_terms":True})
 customer=req("/api/signup","POST",{"name":"Job Customer","email":"customer-jobs@example.test","password":"SecurePass123","role":"customer","accept_terms":True})
 other=req("/api/signup","POST",{"name":"Other Customer","email":"other-jobs@example.test","password":"SecurePass123","role":"customer","accept_terms":True})
 with app.conn() as c:
  c.execute("INSERT INTO businesses(user_id,name,category,area,phone,email,description,plan,billing,status,payment_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(provider["user"]["id"],"QA Plumbing","Plumbers","Johannesburg","+27123456789","jobs@example.test","QA job provider listing","local","monthly","active","verified",app.now()))
  bid=c.execute("SELECT id FROM businesses WHERE name='QA Plumbing'").fetchone()["id"]
 check("Favorites require customer authentication",lambda: req("/api/favorites",expected=401))
 check("New customer starts with an empty saved-provider list",lambda: (_ for _ in ()).throw(AssertionError("favorites were not empty")) if req("/api/favorites",token=customer["token"])["items"] else None)
 fav=req("/api/favorites","POST",{"business_id":bid},customer["token"])
 check("Customer can save an active provider",lambda: (_ for _ in ()).throw(AssertionError(fav)) if fav.get("saved") is not True else None)
 check("Saved provider is persisted in customer list",lambda: (_ for _ in ()).throw(AssertionError("saved provider missing")) if not any(x["id"]==bid for x in req("/api/favorites",token=customer["token"])["items"]) else None)
 fav=req("/api/favorites","POST",{"business_id":bid},customer["token"])
 check("Customer can remove a saved provider",lambda: (_ for _ in ()).throw(AssertionError(fav)) if fav.get("saved") is not False or req("/api/favorites",token=customer["token"])["items"] else None)
 check("Providers cannot use the customer favorites endpoint",lambda: req("/api/favorites",token=provider["token"],expected=401))
 job=req("/api/jobs","POST",{"business_id":bid,"title":"Repair leaking kitchen pipe","description":"The kitchen sink pipe is leaking and needs inspection and repair.","area":"Randburg","preferred_date":"Flexible","budget_rands":"1200.00"},customer["token"],201)
 jid=job["job_id"]
 check("Customer can create a job request",lambda: (_ for _ in ()).throw(AssertionError(job)) if job.get("status")!="requested" else None)
 check("Job request is stored with rand budget in cents",lambda: (_ for _ in ()).throw(AssertionError(one("SELECT budget_cents,status FROM job_requests WHERE id=?",(jid,)))) if tuple(one("SELECT budget_cents,status FROM job_requests WHERE id=?",(jid,)))!=(120000,"requested") else None)
 check("Other customer cannot view another customer's job",lambda: req("/api/jobs",token=other["token"])["items"]==[] or (_ for _ in ()).throw(AssertionError("job leaked to another customer")))
 check("Provider sees the assigned job",lambda: (_ for _ in ()).throw(AssertionError(req("/api/jobs",token=provider["token"]))) if not any(x["id"]==jid for x in req("/api/jobs",token=provider["token"])["items"]) else None)
 check("Customer cannot quote their own request",lambda: req("/api/jobs/%d/quote"%jid,"POST",{"amount_rands":900,"eta":"1 day","message":"Labour and materials included"},customer["token"],403))
 quote=req("/api/jobs/%d/quote"%jid,"POST",{"amount_rands":"950.50","eta":"1 business day","message":"Includes inspection, replacement pipe fitting and labour."},provider["token"],201)
 q=one("SELECT id,amount_cents,status FROM job_quotes WHERE job_id=?",(jid,))
 check("Provider quote persists exact cents and pending status",lambda: (_ for _ in ()).throw(AssertionError(tuple(q))) if tuple(q)[1:]!=(95050,"pending") else None)
 check("Provider cannot accept their own quote",lambda: req("/api/jobs/%d/accept"%jid,"POST",{"quote_id":q["id"]},provider["token"],403))
 req("/api/jobs/%d/accept"%jid,"POST",{"quote_id":q["id"]},customer["token"])
 check("Customer acceptance advances job and quote together",lambda: (_ for _ in ()).throw(AssertionError((tuple(one("SELECT status FROM job_requests WHERE id=?",(jid,))),tuple(one("SELECT status FROM job_quotes WHERE id=?",(q["id"],)))))) if tuple(one("SELECT status FROM job_requests WHERE id=?",(jid,)))!=("accepted",) or tuple(one("SELECT status FROM job_quotes WHERE id=?",(q["id"],)))!=("accepted",) else None)
 req("/api/jobs/%d/status"%jid,"POST",{"status":"scheduled"},provider["token"])
 req("/api/jobs/%d/status"%jid,"POST",{"status":"in_progress"},provider["token"])
 req("/api/jobs/%d/status"%jid,"POST",{"status":"completed"},provider["token"])
 check("Provider can advance accepted job through completion",lambda: (_ for _ in ()).throw(AssertionError(one("SELECT status FROM job_requests WHERE id=?",(jid,)))) if one("SELECT status FROM job_requests WHERE id=?",(jid,))[0]!="completed" else None)
 check("Completed job cannot be cancelled afterward",lambda: req("/api/jobs/%d/status"%jid,"POST",{"status":"cancelled"},customer["token"],409))
 check("Unauthorised provider cannot access a job",lambda: req("/api/jobs/%d/quote"%jid,"POST",{"amount_rands":10,"eta":"soon","message":"test"},other["token"],403))
 print("RESULT %d Job Hub checks passed"%len(passed))
finally:
 server.shutdown(); server.server_close()
 try: os.unlink(db)
 except OSError: pass
