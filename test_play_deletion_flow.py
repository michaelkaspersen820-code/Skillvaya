import os, sys, tempfile, threading, urllib.request, urllib.error, json, sqlite3
from pathlib import Path
root=Path(__file__).resolve().parent
os.environ.pop("DATABASE_URL",None)
os.environ.pop("PORT",None)
os.environ["SKILLVAYA_HOST"]="127.0.0.1"
os.environ["SKILLVAYA_DB_PATH"]=str(root/"play-prep-test.sqlite3")
sys.path.insert(0,str(root))
import app
server=app.ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
base="http://127.0.0.1:"+str(server.server_address[1])
def req(path,method="GET",data=None,token=None):
    body=None if data is None else json.dumps(data).encode()
    headers={}
    if body is not None: headers["Content-Type"]="application/json"
    if token: headers["Authorization"]="Bearer "+token
    r=urllib.request.Request(base+path,data=body,headers=headers,method=method)
    try:
        with urllib.request.urlopen(r,timeout=8) as resp: return resp.status,resp.read().decode()
    except urllib.error.HTTPError as e: return e.code,e.read().decode()
try:
    app.init()
    status,body=req("/account-deletion")
    assert status==200 and "Request deletion of your Skillvaya account" in body
    status,_=req("/account-deletion","HEAD")
    assert status==200
    status,body=req("/api/signup","POST",{"name":"Play Prep Tester","email":"playprep-test@example.invalid","phone":"","password":"Test-only-password-9841","role":"customer","accept_terms":True})
    assert status==200, (status,body)
    token=json.loads(body)["token"]
    status,body=req("/api/account/delete-request","POST",{"reason":"Automated isolated Play readiness test"},token)
    assert status==202, (status,body)
    first=json.loads(body); assert first["ok"] and first["request_id"]
    status,body=req("/api/account/delete-request","POST",{"reason":"duplicate"},token)
    second=json.loads(body); assert status==202 and second["request_id"]==first["request_id"] and second["already_pending"]
    with app.conn() as c:
        user=c.execute("SELECT id FROM users WHERE email=?",( "playprep-test@example.invalid",)).fetchone()
        request=c.execute("SELECT status FROM account_deletion_requests WHERE id=?",(first["request_id"],)).fetchone()
        assert user and request and request["status"]=="pending"
        user_id=int(user["id"])
        c.execute("INSERT INTO payments(user_id,business_id,plan,billing,amount,reference,status,created_at) VALUES(?,NULL,'local','monthly',105,'deletion-test-ref','verified',?)",(user_id,app.now()))
        c.execute("INSERT INTO password_reset_tokens(user_id,token_hash,created_at,expires_at,used_at) VALUES(?,?,?,?, '')",(user_id,"deletion-reset-token-hash",app.now(),app.now()))
    status,body=req("/api/admin/account-deletion-requests")
    queued=json.loads(body)
    assert status==200 and any(int(x["id"])==int(first["request_id"]) for x in queued["items"])
    status,body=req("/api/admin/account-deletion-requests/"+str(first["request_id"])+"/complete","POST",{})
    completed=json.loads(body)
    assert status==200 and completed["ok"], (status,body)
    with app.conn() as c:
        assert not c.execute("SELECT id FROM users WHERE id=?",(user_id,)).fetchone()
        audit=c.execute("SELECT status,user_email,reason FROM account_deletion_requests WHERE id=?",(first["request_id"],)).fetchone()
        assert audit and audit["status"]=="completed" and audit["user_email"]=="" and audit["reason"]==""
        payment=c.execute("SELECT user_id,business_id,pf_payment_id,paypal_order_id,paypal_capture_id FROM payments WHERE reference='deletion-test-ref'").fetchone()
        assert payment and int(payment["user_id"])==0 and payment["business_id"] is None
        assert not c.execute("SELECT token FROM auth_sessions WHERE user_id=?",(user_id,)).fetchone()
        assert not c.execute("SELECT id FROM password_reset_tokens WHERE user_id=?",(user_id,)).fetchone()
    status,body=req("/api/admin/account-deletion-requests/"+str(first["request_id"])+"/complete","POST",{})
    assert status==409, (status,body)

    # Provider deletion regression: remove its listing, conversations/media, jobs, and provider workspace data.
    status,body=req("/api/signup","POST",{"name":"Provider Test","email":"provider-delete-test@example.invalid","phone":"","password":"Test-only-password-9842","role":"provider","accept_terms":True})
    assert status==200, (status,body)
    provider_token=json.loads(body)["token"]
    with app.conn() as c:
        provider=c.execute("SELECT id FROM users WHERE email='provider-delete-test@example.invalid'").fetchone()
        provider_id=int(provider["id"])
        business_id=int(c.execute("INSERT INTO businesses(user_id,name,category,area,phone,email,description,created_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",(provider_id,"Disposable Test Listing","Other professional services","Test Area","0000000000","provider-delete-test@example.invalid","Temporary test record",app.now())).fetchone()["id"])
        c.execute("INSERT INTO provider_campaigns(user_id,business_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",(provider_id,business_id,"Temporary campaign",app.now(),app.now()))
        c.execute("INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)",(business_id,provider_id,provider_id,"Temporary message",app.now()))
        message_id=int(c.execute("SELECT id FROM messages WHERE business_id=?",(business_id,)).fetchone()["id"])
        c.execute("INSERT INTO message_attachments(message_id,business_id,customer_id,sender_id,filename,mime_type,size_bytes,data_base64,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(message_id,business_id,provider_id,provider_id,"temp.txt","text/plain",4,"dGVzdA==",app.now()))
        c.execute("INSERT INTO payments(user_id,business_id,plan,billing,amount,reference,status,created_at) VALUES(?,?,'local','monthly',105,'provider-deletion-test-ref','verified',?)",(provider_id,business_id,app.now()))
        c.execute("CREATE TABLE IF NOT EXISTS google_play_subscriptions (purchase_token TEXT PRIMARY KEY,user_id BIGINT NOT NULL,business_id BIGINT,product_id TEXT NOT NULL,base_plan_id TEXT NOT NULL,order_id TEXT,state TEXT NOT NULL,expiry_time TEXT NOT NULL,auto_renew_enabled BOOLEAN NOT NULL,updated_at TEXT NOT NULL)")
        c.execute("INSERT INTO google_play_subscriptions(purchase_token,user_id,business_id,product_id,base_plan_id,order_id,state,expiry_time,auto_renew_enabled,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",("test-purchase-token",provider_id,business_id,"skillvaya_local","monthly","test-order","SUBSCRIPTION_STATE_ACTIVE",app.now(),True,app.now()))
    status,body=req("/api/account/delete-request","POST",{"reason":"Provider deletion regression test"},provider_token)
    provider_request=json.loads(body)
    assert status==202, (status,body)
    status,body=req("/api/admin/account-deletion-requests/"+str(provider_request["request_id"])+"/complete","POST",{})
    assert status==200, (status,body)
    with app.conn() as c:
        assert not c.execute("SELECT id FROM users WHERE id=?",(provider_id,)).fetchone()
        assert not c.execute("SELECT id FROM businesses WHERE id=?",(business_id,)).fetchone()
        assert not c.execute("SELECT id FROM messages WHERE business_id=?",(business_id,)).fetchone()
        assert not c.execute("SELECT id FROM message_attachments WHERE business_id=?",(business_id,)).fetchone()
        assert not c.execute("SELECT id FROM provider_campaigns WHERE business_id=?",(business_id,)).fetchone()
        pp=c.execute("SELECT user_id,business_id FROM payments WHERE reference='provider-deletion-test-ref'").fetchone()
        assert pp and int(pp["user_id"])==0 and pp["business_id"] is None
        assert not c.execute("SELECT purchase_token FROM google_play_subscriptions WHERE purchase_token='test-purchase-token'").fetchone()
    print("PASS: public deletion information GET and HEAD return 200")
    print("PASS: signed-in deletion request is recorded and duplicates are idempotent")
    print("PASS: owner-only queue lists pending requests")
    print("PASS: completion deletes account, sessions and associated app data transactionally")
    print("PASS: completion clears email/reason from the audit request and minimizes payment identifiers")
    print("PASS: account deletion removes password-reset tokens and Google Play purchase tokens")
    print("PASS: repeated completion is rejected without repeating deletion")
finally:
    server.shutdown(); server.server_close()
    try:
        Path(os.environ["SKILLVAYA_DB_PATH"]).unlink(missing_ok=True)
    except Exception: pass
