import gc, json, os, tempfile, threading, urllib.request, urllib.error, datetime
from http.server import ThreadingHTTPServer

os.environ.pop("DATABASE_URL", None)
os.environ.pop("PORT", None)
os.environ.pop("SKILLVAYA_OWNER_EMAIL", None)
os.environ.pop("SKILLVAYA_OWNER_PASSWORD", None)
import app

tmp = tempfile.TemporaryDirectory(prefix="skillvaya-growth-e2e-")
app.DB = os.path.join(tmp.name, "growth.sqlite3")
app.SESSIONS.clear()
app.init()
server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = "http://127.0.0.1:%d" % server.server_address[1]

def request(path, method="GET", data=None, token="growth-owner", expected=200):
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token}
    req = urllib.request.Request(base + path, method=method, headers=headers,
        data=None if data is None else json.dumps(data).encode("utf-8"))
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    assert status == expected, (method, path, status, raw[:600])
    return json.loads(raw) if raw else {}

def add_user(name, email, role, token):
    with app.conn() as c:
        cur=c.execute("INSERT INTO users(name,email,password_hash,role,created_at,phone) VALUES(?,?,?,?,?,?) RETURNING id",
            (name,email,"disabled-test-password",role,app.now(),"+27000000000"))
        uid=int(cur.fetchone()["id"])
        c.execute("INSERT INTO auth_sessions(token,user_id,expires_at,created_at) VALUES(?,?,?,?)",
            (token,uid,"2999-12-31T23:59:59+00:00",app.now()))
    return uid

def add_business(uid,name,plan):
    with app.conn() as c:
        cur=c.execute("""INSERT INTO businesses(user_id,name,category,area,phone,email,website,description,photos,plan,billing,status,payment_status,rating,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
            (uid,name,"Plumbers","Sandbox Area","+27000000000","", "", "Test-only provider profile","",plan,"monthly","active","verified",0,app.now()))
        return int(cur.fetchone()["id"])

try:
    owner=add_user("Test Owner","owner@growth.example.test","admin","growth-owner")
    customer=add_user("Sandbox Customer","sandbox-customer@growth.example.test","customer","growth-customer")
    provider_plus=add_user("Plus Provider","plus@growth.example.test","provider","growth-plus")
    provider_local=add_user("Local Provider","local@growth.example.test","provider","growth-local")
    owner_biz=add_business(owner,"Skillvaya Digital & Creative Studio","spotlight")
    plus_biz=add_business(provider_plus,"Plus Test Business","plus")
    local_biz=add_business(provider_local,"Local Test Business","local")

    # Seed one quote-linked request and customer interaction in the Local tier's isolated sandbox.
    sandbox_plus=app.subscription_test_business_id(owner,"plus")
    sandbox_spotlight=app.subscription_test_business_id(owner,"spotlight")
    sandbox_local=app.subscription_test_business_id(owner,"local")
    with app.conn() as c:
        c.execute("INSERT INTO contacts(business_id,customer_id,created_at) VALUES(?,?,?)",(sandbox_plus,customer,app.now()))
        cur=c.execute("""INSERT INTO job_requests(customer_id,business_id,title,description,area,preferred_date,budget_cents,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,'quoted',?,?) RETURNING id""",
            (customer,sandbox_plus,"Sandbox tap repair","Example request used only to test quote follow-ups and the job pipeline.","Sandbox Area","",85000,app.now(),app.now()))
        job_id=int(cur.fetchone()["id"])
        c.execute("""INSERT INTO job_quotes(job_id,business_id,provider_id,amount_cents,eta,message,status,created_at)
            VALUES(?,?,?,?,?,?,?,?)""",(job_id,sandbox_plus,owner,85000,"2 working days","Sandbox quote only","pending",app.now()))
        c.execute("INSERT INTO ratings(business_id,rater_id,target_type,target_user_id,stars,created_at) VALUES(?,?,?,?,?,?)",
            (sandbox_plus,customer,"provider",owner,5,app.now()))

    # Pipeline reads isolated sandbox requests even though no public businesses row exists for its negative sandbox ID.
    sandbox_pipeline=request("/api/provider/growth/pipeline?test_tier=plus")["items"]
    assert any(int(x["id"])==job_id and x["business_name"]=="Sandbox Plus test account" for x in sandbox_pipeline)
    assert request("/api/provider/growth/pipeline?test_tier=spotlight")["items"]==[]

    # Entitlements: Local and Priority cannot invoke Business Plus tools, and previews cannot borrow Spotlight rights.
    request("/api/provider/growth/bookings?test_tier=local",expected=403)
    request("/api/provider/growth/bookings?test_tier=priority",expected=403)
    request("/api/provider/growth/campaigns?test_tier=spotlight",expected=404)
    request("/api/provider/growth/team?test_tier=plus",expected=403)
    request("/api/provider/growth/bookings",token="growth-local",expected=403)
    request("/api/provider/growth/bookings",token="growth-plus",expected=200)

    # Booking creation/read/update is persisted against the chosen Plus sandbox, not the live owner studio.
    booking=request("/api/provider/growth/bookings", "POST", {"test_tier":"plus","action":"create",
        "title":"Sandbox appointment","customer_name":"Sandbox Customer","customer_contact":"sandbox-only",
        "starts_at":"2099-02-01T10:00","ends_at":"2099-02-01T11:00","notes":"Isolated E2E fixture"}, expected=201)
    plus_bookings=request("/api/provider/growth/bookings?test_tier=plus")["items"]
    assert any(x["id"]==booking["id"] for x in plus_bookings)
    assert request("/api/provider/growth/bookings?test_tier=spotlight")["items"]==[]
    with app.conn() as c:
        assert c.execute("SELECT count(*) FROM provider_bookings WHERE business_id=?",(owner_biz,)).fetchone()[0]==0

    # CRM notes are tied to prior contact and remain scoped to the tier sandbox.
    request("/api/provider/growth/crm","POST",{"test_tier":"plus","action":"save_note","customer_id":customer,
        "notes":"Sandbox-only customer preference","tags":"test,repeat"})
    crm=request("/api/provider/growth/crm?test_tier=plus")["items"]
    assert any(int(x["customer_id"])==customer and "Sandbox-only" in x["notes"] for x in crm)

    # Quote follow-up requires a pending quote and stores a private reminder.
    followup=request("/api/provider/growth/followups","POST",{"test_tier":"plus","action":"create","job_id":job_id,
        "remind_at":"2099-02-01T09:00","note":"Sandbox follow-up"}, expected=201)
    followups=request("/api/provider/growth/followups?test_tier=plus")["followups"]
    assert any(x["id"]==followup["id"] for x in followups)

    # Invoice ledger stores amounts in cents; it records bookkeeping only and never calls a payment processor.
    invoice=request("/api/provider/growth/invoices","POST",{"test_tier":"plus","action":"create","customer_name":"Sandbox Customer",
        "customer_email":"sandbox-customer@growth.example.test","description":"Sandbox plumbing work","amount_rands":500,
        "due_date":"2099-02-15"}, expected=201)
    recorded=request("/api/provider/growth/invoices","POST",{"test_tier":"plus","action":"record_payment","id":invoice["id"],"amount_rands":125})
    assert recorded["amount_paid_cents"]==12500
    request("/api/provider/growth/invoices","POST",{"test_tier":"plus","action":"record_payment","id":invoice["id"],"amount_rands":500},expected=400)
    invoices=request("/api/provider/growth/invoices?test_tier=plus")["items"]
    assert any(x["id"]==invoice["id"] and x["amount_paid_cents"]==12500 for x in invoices)

    # Packages and offers are persistent; offer redemption is a usage ledger, not a charge.
    package=request("/api/provider/growth/packages","POST",{"test_tier":"plus","action":"create","name":"Sandbox service pack",
        "description":"Test package", "price_rands":250,"add_ons":"Urgent booking|75","status":"draft"}, expected=201)
    request("/api/provider/growth/packages","POST",{"test_tier":"plus","action":"status","id":package["id"],"status":"active"})
    packages=request("/api/provider/growth/packages?test_tier=plus")["items"]
    assert any(x["id"]==package["id"] and x["status"]=="active" for x in packages)
    offer=request("/api/provider/growth/offers","POST",{"test_tier":"spotlight","action":"create","title":"Sandbox special",
        "code":"SANDBOX25","description":"Sandbox offer for testing","discount_type":"percent","discount_value":25,
        "starts_on":"","ends_on":"","usage_limit":5}, expected=201)
    request("/api/provider/growth/offers","POST",{"test_tier":"spotlight","action":"active","id":offer["id"]})
    redeemed=request("/api/provider/growth/offers","POST",{"test_tier":"spotlight","action":"redeem","id":offer["id"]})
    assert redeemed["usage_count"]==1
    request("/api/provider/growth/offers?test_tier=plus", expected=403)

    # Team invites are stored in the selected sandbox and explicitly do not email real recipients in test mode.
    invite=request("/api/provider/growth/team","POST",{"test_tier":"spotlight","action":"invite","name":"Test Staff",
        "email":"owner@growth.example.test","team_role":"staff"}, expected=201)
    assert invite["test_mode"] is True and invite["email_sent"] is False
    request("/api/provider/growth/team","POST",{"test_tier":"spotlight","action":"accept_invite","invite_code":invite["invite_url"].split("team_invite=")[1]})
    team=request("/api/provider/growth/team?test_tier=spotlight")["items"]
    assert any(x["id"]==invite["id"] and x["status"]=="active" for x in team)
    request("/api/provider/growth/team?test_tier=plus", expected=403)  # Plus cannot access Spotlight team controls.

    # Announcements can be drafted, but the lab cannot publish a message to opted-in live customers.
    ann=request("/api/provider/growth/announcements","POST",{"test_tier":"spotlight","action":"create","title":"Sandbox announcement",
        "body":"This is a test-only draft, not a customer message."}, expected=201)
    request("/api/provider/growth/announcements","POST",{"test_tier":"spotlight","action":"publish","id":ann["id"]},expected=409)
    assert any(x["id"]==ann["id"] for x in request("/api/provider/growth/announcements?test_tier=spotlight")["items"])

    # Templates/campaigns are stored under test-only identities; selected tier locks are server-side.
    request("/api/provider/quote-templates?test_tier=local",expected=403)
    template=request("/api/provider/quote-templates","POST",{"test_tier":"priority","name":"Sandbox quote template","eta":"2 days","message":"Sandbox quote wording."},expected=201)
    assert len(request("/api/provider/quote-templates?test_tier=priority")["items"])==1
    assert request("/api/provider/quote-templates?test_tier=spotlight")["items"]==[]
    request("/api/provider/campaigns?test_tier=plus",expected=403)
    campaign=request("/api/provider/campaigns","POST",{"test_tier":"spotlight","title":"Sandbox campaign","description":"Promotion draft for isolated test accounts."},expected=201)
    assert len(request("/api/provider/campaigns?test_tier=spotlight")["items"])==1
    request("/api/provider/campaigns?test_tier=plus",expected=403)
    assert request("/api/provider/campaigns")["items"]==[]

    # Analytics reads only sandbox rows in test mode, while normal owner dashboard still includes the real studio.
    metrics=request("/api/provider/insights?test_tier=plus")
    assert metrics["plan"]=="plus" and metrics["job_requests"]==1
    request("/api/provider/insights?test_tier=local",expected=403)
    with app.conn() as c:
        assert c.execute("SELECT count(*) FROM provider_campaigns WHERE business_id=?",(owner_biz,)).fetchone()[0]==0
        assert c.execute("SELECT count(*) FROM provider_invoices WHERE business_id=?",(owner_biz,)).fetchone()[0]==0
        assert c.execute("SELECT count(*) FROM provider_bookings WHERE business_id=?",(owner_biz,)).fetchone()[0]==0

    # Hourly automation worker creates in-app reminders for real Plus records, suppresses duplicates, and ignores sandbox negative IDs.
    stamp=app.now()
    tomorrow=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=2)).isoformat()
    yesterday=(datetime.date.today()-datetime.timedelta(days=1)).isoformat()
    with app.conn() as c:
        c.execute("INSERT INTO provider_automation_rules(business_id,user_id,rule_key,enabled,config_json,updated_at) VALUES(?,?,?,1,?,?)",(plus_biz,provider_plus,"quote_followup",json.dumps({"title":"Follow-up"}),stamp))
        c.execute("INSERT INTO provider_automation_rules(business_id,user_id,rule_key,enabled,config_json,updated_at) VALUES(?,?,?,1,?,?)",(plus_biz,provider_plus,"booking_reminder",json.dumps({"title":"Booking"}),stamp))
        c.execute("INSERT INTO provider_automation_rules(business_id,user_id,rule_key,enabled,config_json,updated_at) VALUES(?,?,?,1,?,?)",(plus_biz,provider_plus,"invoice_overdue",json.dumps({"title":"Invoice"}),stamp))
        cur=c.execute("INSERT INTO job_requests(customer_id,business_id,title,description,area,preferred_date,budget_cents,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'quoted',?,?) RETURNING id",(customer,plus_biz,"Real plus reminder request","Fixture for the scheduled reminder worker","Sandbox Area","",85000,stamp,stamp))
        real_plus_job=int(cur.fetchone()["id"])
        cur=c.execute("INSERT INTO provider_followups(business_id,user_id,job_id,customer_id,remind_at,note,status,created_at,updated_at) VALUES(?,?,?,?,?,?, 'pending',?,?) RETURNING id",(plus_biz,provider_plus,real_plus_job,customer,(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=5)).isoformat(),"Automatic test reminder",stamp,stamp))
        real_plus_followup=int(cur.fetchone()["id"])
        c.execute("INSERT INTO provider_bookings(business_id,user_id,customer_name,customer_contact,title,notes,starts_at,ends_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(plus_biz,provider_plus,"Sandbox Customer","","Upcoming automation test booking","Fixture",""+tomorrow,"", "scheduled",stamp,stamp))
        c.execute("INSERT INTO provider_invoices(business_id,user_id,invoice_number,customer_name,customer_email,description,amount_cents,amount_paid_cents,due_date,status,created_at,updated_at,paid_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(plus_biz,provider_plus,"SVI-AUTOTEST","Sandbox Customer","","Overdue automation test invoice",20000,0,yesterday,"issued",stamp,stamp,""))
    created_alerts=app.evaluate_provider_automation_due()
    assert created_alerts==3, ("scheduled automation alerts",created_alerts)
    with app.conn() as c:
        alert_kinds={r["kind"] for r in c.execute("SELECT kind FROM provider_notifications WHERE business_id=?",(plus_biz,)).fetchall()}
        assert alert_kinds=={"quote_followup","booking_reminder","invoice_overdue"}, alert_kinds
        assert c.execute("SELECT count(*) FROM provider_notifications WHERE business_id=?",(sandbox_plus,)).fetchone()[0]==0
    assert app.evaluate_provider_automation_due()==0, "scheduled automation should suppress duplicate alerts within 24 hours"

    # Spotlight automation creates in-app notices only; no email/text integrations are called by evaluation.
    rules=request("/api/provider/growth/automation?test_tier=spotlight")["rules"]
    assert len(rules)>=3
    rule=request("/api/provider/growth/automation","POST",{"test_tier":"spotlight","action":"toggle","rule_key":"invoice_overdue","enabled":False})
    assert rule["enabled"] is False

    print("PASS: tier entitlements, bookings, CRM notes, follow-ups, invoice ledger, service packages, offer lifecycle, isolated team invites, announcement safety, template/campaign isolation, insights, and hourly automation deduplication.")
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    gc.collect()
    tmp.cleanup()
