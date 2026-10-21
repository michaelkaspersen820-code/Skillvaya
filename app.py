from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import json, sqlite3, hashlib, hmac, secrets, os, datetime, threading, webbrowser, urllib.parse, urllib.request, urllib.error, base64, time
from contextlib import contextmanager

ROOT = os.path.dirname(os.path.abspath(__file__))
TERMS_VERSION = "2026-10-21-v1.2"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB = os.environ.get("SKILLVAYA_DB_PATH", os.path.join(ROOT, "skillvaya.sqlite3"))

# Never allow a hosted service to silently fall back to ephemeral SQLite.
if os.environ.get("PORT") and not DATABASE_URL:
    raise RuntimeError("Hosted Skillvaya startup blocked: set DATABASE_URL to the Neon PostgreSQL connection string. SQLite is for local development only.")

# SQLite remains the zero-configuration local development database. Hosted free deployments
# use managed PostgreSQL so customer records survive web-service restarts and redeploys.
if DATABASE_URL:
    import psycopg
    DBIntegrityError = psycopg.IntegrityError

    class HybridRow(dict):
        def __init__(self, columns, values):
            super().__init__(zip(columns, values))
            self._values = tuple(values)
        def __getitem__(self, key):
            if isinstance(key, int):
                return self._values[key]
            return super().__getitem__(key)

    def hybrid_row(cursor):
        # psycopg calls the row-factory with the cursor before the SQL statement runs,
        # so description is not available yet. Resolve column names lazily when a row
        # is actually produced; statements without result sets never invoke this maker.
        def make_row(values):
            description = cursor.description
            if description is None:
                return values
            return HybridRow([d.name for d in description], values)
        return make_row

    class PgConnection:
        def __init__(self, raw):
            self.raw = raw
        def execute(self, sql, params=()):
            return self.raw.execute(sql.replace("?", "%s"), params)
        def commit(self): return self.raw.commit()
        def rollback(self): return self.raw.rollback()
        def close(self): return self.raw.close()
    def connect_db():
        return PgConnection(psycopg.connect(DATABASE_URL, row_factory=hybrid_row))
else:
    DBIntegrityError = sqlite3.IntegrityError
    def connect_db():
        c = sqlite3.connect(DB, timeout=15)
        c.row_factory = sqlite3.Row
        return c

def execute_script(c, script):
    if not DATABASE_URL:
        script = script.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY")
    for statement in script.split(";"):
        if statement.strip():
            c.execute(statement)

def table_columns(c, table):
    if DATABASE_URL:
        rows = c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=?", (table,)).fetchall()
        return {r["column_name"] for r in rows}
    return {r[1] for r in c.execute("PRAGMA table_info(" + table + ")")}
# Local development remains loopback-only. A managed host supplies PORT; public deployment
# must also complete the production owner-authentication release gate before going live.
HOST = os.environ.get("SKILLVAYA_HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
PORT = int(os.environ.get("PORT", "8877"))
CATEGORIES = [
"Builders & construction","Plumbers","Electricians","Painters & decorators","Mechanics & automotive","Cleaning & housekeeping","Gardening & landscaping","Roofing & waterproofing","Carpenters & furniture","Welders & fabricators","Appliance repairs","IT & computer support","Graphic designers","Artists & photographers","Marketing & advertising","Web & software developers","Lawyers & legal services","Private doctors & clinics","Dentists & specialists","Nurses & home care","Accountants & tax","Financial & insurance services","Real estate & property","Tutors & education","Beauty & hair","Catering & chefs","Transport & removals","Security services","Events & entertainment","Tailors & fashion","Pet care & veterinary","Funeral services","Engineering & consulting","Other professional services","Doctors","Nurses","Mechanics","Gardeners",
"General practitioners (GPs)","Medical specialists","Dentists","Dental hygienists","Physiotherapists","Psychologists & counsellors","Optometrists","Pharmacists","Veterinarians",
"Home carers","Elderly care","Childcare & babysitters","Midwives",
"Auto electricians","Tyre fitters","Panel beaters & spray painters","Car washers & detailing","Motorcycle mechanics","Truck & diesel mechanics",
"Landscapers","Pool maintenance","Pest control","Tree services",
"Bricklayers","Plasterers","Tilers","Flooring installers","Glaziers & window fitters","Locksmiths","Solar installers","Air-conditioning & refrigeration","CCTV & alarm installers","Handymen","Quantity surveyors","Architects",
"Domestic workers","Laundry & ironing","Carpet & upholstery cleaning","Office cleaning","Waste removal",
"Computer repair","Mobile phone repair","Network technicians","Cybersecurity services","UX/UI designers","Video editors","Videographers","Translators & interpreters","Writers & editors",
"Consultants","Human resources & recruitment","Bookkeepers","Auditors","Mortgage brokers","Financial advisers","Insurance brokers","Estate agents","Property managers",
"Teachers","Exam tutors","Music teachers","Driving instructors","Training & coaching",
"Barbers","Hairdressers","Nail technicians","Make-up artists","Beauty therapists","Massage therapists","Personal trainers","Nutritionists",
"Chefs & private cooks","Bakers","Food vendors","Event planners","DJs & sound technicians","Musicians","MCs & entertainers","Florists","Wedding services",
"Fashion designers","Sewing & alterations","Upholstery","Delivery drivers","Moving & removals","Taxi & shuttle services","Tour guides","Courier services",
"Security guards","Private investigators","Fire safety services","Funeral directors","Cremation services",
"Civil engineers","Electrical engineers","Mechanical engineers","Environmental consultants","Surveyors","Interior designers","Signage & printing","Craftspeople","Pet groomers","Dog walkers","Animal trainers"
 ]
CATEGORY_ALIASES = {
    "Doctors": {"Private doctors & clinics"}, "General practitioners (GPs)": {"Private doctors & clinics"}, "Medical specialists": {"Private doctors & clinics"},
    "Nurses": {"Nurses & home care"}, "Home carers": {"Nurses & home care"}, "Elderly care": {"Nurses & home care"}, "Midwives": {"Nurses & home care"},
    "Mechanics": {"Mechanics & automotive"}, "Auto electricians": {"Mechanics & automotive"}, "Tyre fitters": {"Mechanics & automotive"}, "Panel beaters & spray painters": {"Mechanics & automotive"}, "Car washers & detailing": {"Mechanics & automotive"}, "Motorcycle mechanics": {"Mechanics & automotive"}, "Truck & diesel mechanics": {"Mechanics & automotive"},
    "Gardeners": {"Gardening & landscaping"}, "Landscapers": {"Gardening & landscaping"}, "Tree services": {"Gardening & landscaping"}, "Pool maintenance": {"Cleaning & housekeeping", "Gardening & landscaping"}, "Pest control": {"Cleaning & housekeeping"},
    "Dentists": {"Dentists & specialists"}, "Dental hygienists": {"Dentists & specialists"}, "Physiotherapists": {"Dentists & specialists"}, "Psychologists & counsellors": {"Private doctors & clinics"}, "Optometrists": {"Dentists & specialists"}, "Pharmacists": {"Private doctors & clinics"}, "Veterinarians": {"Pet care & veterinary"},
    "Bricklayers": {"Builders & construction"}, "Plasterers": {"Builders & construction"}, "Tilers": {"Builders & construction"}, "Flooring installers": {"Builders & construction"}, "Glaziers & window fitters": {"Builders & construction"}, "Locksmiths": {"Other professional services"}, "Solar installers": {"Electricians"}, "Air-conditioning & refrigeration": {"Appliance repairs", "Electricians"}, "CCTV & alarm installers": {"Security services", "Electricians"}, "Handymen": {"Builders & construction"}, "Quantity surveyors": {"Engineering & consulting"}, "Architects": {"Engineering & consulting"},
    "Domestic workers": {"Cleaning & housekeeping"}, "Laundry & ironing": {"Cleaning & housekeeping"}, "Carpet & upholstery cleaning": {"Cleaning & housekeeping"}, "Office cleaning": {"Cleaning & housekeeping"}, "Waste removal": {"Cleaning & housekeeping", "Transport & removals"},
    "Computer repair": {"IT & computer support"}, "Mobile phone repair": {"IT & computer support"}, "Network technicians": {"IT & computer support"}, "Cybersecurity services": {"IT & computer support"}, "UX/UI designers": {"Graphic designers", "Web & software developers"}, "Video editors": {"Artists & photographers"}, "Videographers": {"Artists & photographers"}, "Translators & interpreters": {"Other professional services"}, "Writers & editors": {"Marketing & advertising"},
    "Consultants": {"Engineering & consulting"}, "Human resources & recruitment": {"Other professional services"}, "Bookkeepers": {"Accountants & tax"}, "Auditors": {"Accountants & tax"}, "Mortgage brokers": {"Financial & insurance services"}, "Financial advisers": {"Financial & insurance services"}, "Insurance brokers": {"Financial & insurance services"}, "Estate agents": {"Real estate & property"}, "Property managers": {"Real estate & property"},
    "Teachers": {"Tutors & education"}, "Exam tutors": {"Tutors & education"}, "Music teachers": {"Tutors & education", "Events & entertainment"}, "Driving instructors": {"Tutors & education"}, "Training & coaching": {"Tutors & education"},
    "Barbers": {"Beauty & hair"}, "Hairdressers": {"Beauty & hair"}, "Nail technicians": {"Beauty & hair"}, "Make-up artists": {"Beauty & hair"}, "Beauty therapists": {"Beauty & hair"}, "Massage therapists": {"Beauty & hair"}, "Personal trainers": {"Other professional services"}, "Nutritionists": {"Other professional services"},
    "Chefs & private cooks": {"Catering & chefs"}, "Bakers": {"Catering & chefs"}, "Food vendors": {"Catering & chefs"}, "Event planners": {"Events & entertainment"}, "DJs & sound technicians": {"Events & entertainment"}, "Musicians": {"Events & entertainment"}, "MCs & entertainers": {"Events & entertainment"}, "Florists": {"Events & entertainment"}, "Wedding services": {"Events & entertainment"},
    "Fashion designers": {"Tailors & fashion"}, "Sewing & alterations": {"Tailors & fashion"}, "Upholstery": {"Carpenters & furniture"}, "Delivery drivers": {"Transport & removals"}, "Moving & removals": {"Transport & removals"}, "Taxi & shuttle services": {"Transport & removals"}, "Tour guides": {"Transport & removals"}, "Courier services": {"Transport & removals"},
    "Security guards": {"Security services"}, "Private investigators": {"Security services"}, "Fire safety services": {"Security services"}, "Funeral directors": {"Funeral services"}, "Cremation services": {"Funeral services"},
    "Civil engineers": {"Engineering & consulting"}, "Electrical engineers": {"Engineering & consulting", "Electricians"}, "Mechanical engineers": {"Engineering & consulting"}, "Environmental consultants": {"Engineering & consulting"}, "Surveyors": {"Engineering & consulting"}, "Interior designers": {"Painters & decorators", "Graphic designers"}, "Signage & printing": {"Graphic designers", "Marketing & advertising"}, "Craftspeople": {"Artists & photographers"}, "Pet groomers": {"Pet care & veterinary"}, "Dog walkers": {"Pet care & veterinary"}, "Animal trainers": {"Pet care & veterinary"},
}

def category_matches(requested, stored):
    return requested == "All categories" or stored == requested or stored in CATEGORY_ALIASES.get(requested, set())
def category_search_terms(stored):
    aliases = [name for name, targets in CATEGORY_ALIASES.items() if stored in targets]
    return " ".join([stored, *aliases])
PLANS = {"local":{"name":"Local","monthly":105},"priority":{"name":"Priority","monthly":210},"plus":{"name":"Business Plus","monthly":500},"spotlight":{"name":"Business Spotlight","monthly":1000}}
@contextmanager
def conn():
    c = connect_db()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
def init():
    # Public deployments must provide a dedicated owner identity and a strong password.
    # This prevents a fresh public database from having no way to authenticate its owner.
    if os.environ.get("PORT"):
        owner_email = os.environ.get("SKILLVAYA_OWNER_EMAIL", "").strip().lower()
        owner_password = os.environ.get("SKILLVAYA_OWNER_PASSWORD", "")
        if "@" not in owner_email or len(owner_password) < 14:
            raise RuntimeError("Public deployment blocked: set SKILLVAYA_OWNER_EMAIL and a unique SKILLVAYA_OWNER_PASSWORD of at least 14 characters before starting Skillvaya.")
    with conn() as c:
        execute_script(c, """
        CREATE TABLE IF NOT EXISTS users(id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'customer', created_at TEXT NOT NULL, phone TEXT DEFAULT '', accepted_terms_version TEXT NOT NULL DEFAULT '', accepted_terms_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS businesses(id BIGSERIAL PRIMARY KEY, user_id INTEGER, name TEXT NOT NULL, category TEXT NOT NULL, area TEXT NOT NULL, phone TEXT NOT NULL, email TEXT, website TEXT, description TEXT NOT NULL, photos TEXT DEFAULT '', plan TEXT NOT NULL DEFAULT 'local', billing TEXT NOT NULL DEFAULT 'monthly', status TEXT NOT NULL DEFAULT 'pending', payment_status TEXT NOT NULL DEFAULT 'unpaid', rating REAL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS enquiries(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, customer_id INTEGER NOT NULL, message TEXT NOT NULL, status TEXT DEFAULT 'new', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, customer_id INTEGER NOT NULL, sender_id INTEGER NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT);
        CREATE TABLE IF NOT EXISTS ratings(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, rater_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_user_id INTEGER NOT NULL, stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5), created_at TEXT NOT NULL, UNIQUE(business_id,rater_id,target_type,target_user_id));
        CREATE TABLE IF NOT EXISTS platform_ratings(id BIGSERIAL PRIMARY KEY, rater_id INTEGER NOT NULL UNIQUE, stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5), created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS complaints(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, customer_id INTEGER NOT NULL, reason TEXT NOT NULL, evidence TEXT DEFAULT '', status TEXT DEFAULT 'open', priority TEXT DEFAULT 'normal', created_at TEXT NOT NULL, admin_note TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS payments(id BIGSERIAL PRIMARY KEY, user_id INTEGER NOT NULL, business_id INTEGER, plan TEXT NOT NULL, billing TEXT NOT NULL, amount INTEGER NOT NULL, reference TEXT NOT NULL UNIQUE, status TEXT DEFAULT 'pending', created_at TEXT NOT NULL, verified_at TEXT, pf_payment_id TEXT, refunded_amount INTEGER NOT NULL DEFAULT 0, refund_status TEXT NOT NULL DEFAULT 'none');
        CREATE TABLE IF NOT EXISTS analytics(id BIGSERIAL PRIMARY KEY, event TEXT NOT NULL, user_id INTEGER, detail TEXT DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications(id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL, emailed_at TEXT, recipient TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS auth_sessions(token TEXT PRIMARY KEY, user_id BIGINT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS subscriptions(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, user_id INTEGER NOT NULL, plan TEXT NOT NULL, billing TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', started_at TEXT NOT NULL, expires_at TEXT NOT NULL, cancelled_at TEXT, UNIQUE(business_id));
        CREATE TABLE IF NOT EXISTS owner_promotions(
            id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'ad',
            business_name TEXT NOT NULL, title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Other professional services',
            description TEXT NOT NULL, target_url TEXT NOT NULL DEFAULT '',
            image_url TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
            owner_free INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """)
        # Safe schema migration for databases created by earlier local versions.
        usercols=table_columns(c, "users")
        if "phone" not in usercols:
            c.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
        if "accepted_terms_version" not in usercols:
            c.execute("ALTER TABLE users ADD COLUMN accepted_terms_version TEXT NOT NULL DEFAULT ''")
        if "accepted_terms_at" not in usercols:
            c.execute("ALTER TABLE users ADD COLUMN accepted_terms_at TEXT NOT NULL DEFAULT ''")
        if "profile_photo" not in usercols:
            c.execute("ALTER TABLE users ADD COLUMN profile_photo TEXT NOT NULL DEFAULT ''")
        ncols=table_columns(c, "notifications")
        if "recipient" not in ncols:
            c.execute("ALTER TABLE notifications ADD COLUMN recipient TEXT NOT NULL DEFAULT ''")
        cols=table_columns(c, "businesses")
        if "subscription_expires_at" not in cols:
            c.execute("ALTER TABLE businesses ADD COLUMN subscription_expires_at TEXT")
        if "whatsapp" not in cols:
            c.execute("ALTER TABLE businesses ADD COLUMN whatsapp TEXT NOT NULL DEFAULT ''")
        pcols=table_columns(c, "payments")
        if "pf_payment_id" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN pf_payment_id TEXT")
        if "refunded_amount" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN refunded_amount INTEGER NOT NULL DEFAULT 0")
        if "refund_status" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN refund_status TEXT NOT NULL DEFAULT 'none'")
        if "payment_gateway" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN payment_gateway TEXT NOT NULL DEFAULT 'paypal'")
        if "paypal_order_id" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN paypal_order_id TEXT")
        if "paypal_capture_id" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN paypal_capture_id TEXT")
        if not c.execute("SELECT 1 FROM settings WHERE key='owner_email'").fetchone():
            c.execute("INSERT INTO settings(key,value) VALUES('owner_email','skillvaya@gmail.com')")
        else:
            c.execute("UPDATE settings SET value='skillvaya@gmail.com' WHERE key='owner_email' AND (value IS NULL OR value='' OR value='owner@skillvaya.local')")
        c.execute("INSERT INTO settings(key,value) VALUES('terms_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(TERMS_VERSION,))
        # Create/update the dedicated owner account only when explicit host secrets exist.
        owner_email = os.environ.get("SKILLVAYA_OWNER_EMAIL", "").strip().lower()
        owner_password = os.environ.get("SKILLVAYA_OWNER_PASSWORD", "")
        if owner_email and owner_password and "@" in owner_email and len(owner_password) >= 14:
            existing = c.execute("SELECT id FROM users WHERE email=?", (owner_email,)).fetchone()
            if existing:
                c.execute("UPDATE users SET name='Skillvaya Owner', role='admin', password_hash=? WHERE id=?", (hashpw(owner_password), existing["id"]))
            else:
                c.execute("INSERT INTO users(name,email,password_hash,role,created_at,phone,accepted_terms_version,accepted_terms_at) VALUES(?,?,?,?,?,?,?,?)", ("Skillvaya Owner", owner_email, hashpw(owner_password), "admin", now(), "", "owner", now()))
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def hashpw(p):
    salt=secrets.token_hex(16)
    rounds=310000
    digest=hashlib.pbkdf2_hmac("sha256",p.encode(),salt.encode(),rounds).hex()
    return f"pbkdf2_sha256${rounds}${salt}${digest}"
def verify_password(stored,p):
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _,rounds,salt,digest=stored.split("$",3)
            actual=hashlib.pbkdf2_hmac("sha256",p.encode(),salt.encode(),int(rounds)).hex()
            return hmac.compare_digest(actual,digest)
        except (ValueError,TypeError):
            return False
    # Compatibility for existing accounts: upgrade legacy SHA-256 hashes after successful login.
    return hmac.compare_digest(stored,hashlib.sha256(p.encode()).hexdigest())
def setting(key, default=""):
    with conn() as c:
        row=c.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
    return row["value"] if row else default
def send_owner_email(subject, body, recipient=None):
    recipient=recipient or setting("owner_email")
    host=os.environ.get("SKILLVAYA_SMTP_HOST","")
    port=int(os.environ.get("SKILLVAYA_SMTP_PORT","587") or "587")
    user=os.environ.get("SKILLVAYA_SMTP_USER","")
    password=os.environ.get("SKILLVAYA_SMTP_PASSWORD","")
    sender=os.environ.get("SKILLVAYA_SMTP_FROM",user)
    if not (recipient and host and user and password and sender): return False
    try:
        import smtplib
        from email.message import EmailMessage
        m=EmailMessage(); m["Subject"]="[Skillvaya] "+subject; m["From"]=sender; m["To"]=recipient
        m.set_content(body)
        with smtplib.SMTP(host,port,timeout=12) as server:
            server.starttls(); server.login(user,password); server.send_message(m)
        return True
    except Exception:
        return False
def send_customer_receipt(payment, customer_name, customer_email, capture_id):
    """Email a customer receipt only after PayPal confirms a completed capture."""
    if not customer_email:
        return False
    subject = "Payment receipt " + str(payment["reference"])
    lines = [
        "Hello " + (customer_name or "Skillvaya customer") + ",",
        "",
        "Skillvaya has received confirmation of your PayPal payment.",
        "",
        "INVOICE / PAYMENT RECEIPT",
        "Invoice reference: " + str(payment["reference"]),
        "Payment status: PAID ? confirmed by PayPal",
        "Plan: " + str(payment["plan"]),
        "Billing period: " + str(payment["billing"]),
        "Amount paid: R" + format(float(payment["amount"]), ",.2f"),
        "Payment date (UTC): " + str(payment["verified_at"] or now()),
        "PayPal capture reference: " + str(capture_id),
        "",
        "Keep this email for your records. Your plan is activated only after provider confirmation.",
        "For billing questions, contact skillvaya@gmail.com.",
        "",
        "Thank you for using Skillvaya.",
    ]
    sent = send_owner_email(subject, "\n".join(lines), customer_email)
    if sent:
        with conn() as c:
            c.execute("INSERT INTO notifications(kind,subject,body,status,created_at,emailed_at,recipient) VALUES(?,?,?,?,?,?,?)",
                      ("payment_receipt", subject, "Receipt emailed for " + str(payment["reference"]), "emailed", now(), now(), customer_email))
    else:
        with conn() as c:
            c.execute("INSERT INTO notifications(kind,subject,body,status,created_at,recipient) VALUES(?,?,?,?,?,?)",
                      ("payment_receipt", subject, "Receipt pending email delivery for " + str(payment["reference"]), "email_pending", now(), customer_email))
    return sent

def notify(kind, subject, body, recipient=""):
    with conn() as c:
        cur=c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?) RETURNING id",(kind,subject,body,now(),recipient))
        nid=cur.fetchone()["id"]
    if send_owner_email(subject,body,recipient or None):
        with conn() as c: c.execute("UPDATE notifications SET emailed_at=?,status='emailed' WHERE id=?",(now(),nid))
        return True
    return False

def payfast_config():
    mode=os.environ.get("SKILLVAYA_PAYFAST_MODE","sandbox").strip().lower()
    sandbox=mode!="live"
    return {
        "mode":"sandbox" if sandbox else "live",
        "merchant_id":os.environ.get("SKILLVAYA_PAYFAST_MERCHANT_ID","10000100" if sandbox else "").strip(),
        "merchant_key":os.environ.get("SKILLVAYA_PAYFAST_MERCHANT_KEY","46f0cd694581a" if sandbox else "").strip(),
        "passphrase":os.environ.get("SKILLVAYA_PAYFAST_PASSPHRASE","jt7NOE43FZPn" if sandbox else ""),
        "public_url":os.environ.get("SKILLVAYA_PUBLIC_URL","").strip().rstrip("/"),
        "host":"sandbox.payfast.co.za" if sandbox else "www.payfast.co.za",
        "api_host":"https://api.sandbox.payfast.co.za" if sandbox else "https://api.payfast.co.za"
    }

def paypal_config():
    mode=os.environ.get("SKILLVAYA_PAYPAL_MODE","sandbox").strip().lower()
    sandbox=mode!="live"
    return {"mode":"sandbox" if sandbox else "live",
            "client_id":os.environ.get("SKILLVAYA_PAYPAL_CLIENT_ID","").strip(),
            "secret":os.environ.get("SKILLVAYA_PAYPAL_CLIENT_SECRET","").strip(),
            "base":"https://api-m.sandbox.paypal.com" if sandbox else "https://api-m.paypal.com",
            "public_url":os.environ.get("SKILLVAYA_PUBLIC_URL","https://skillvaya.onrender.com").strip().rstrip("/")}

_PAYPAL_TOKEN_CACHE = {"key": None, "token": None, "expires_at": 0}

def paypal_access_token():
    cfg=paypal_config()
    if not cfg["client_id"] or not cfg["secret"]:
        raise RuntimeError("PayPal client credentials are not configured in Render.")
    key=(cfg["base"],cfg["client_id"],hashlib.sha256(cfg["secret"].encode()).hexdigest())
    if _PAYPAL_TOKEN_CACHE["key"]==key and _PAYPAL_TOKEN_CACHE["token"] and _PAYPAL_TOKEN_CACHE["expires_at"]>time.time()+30:
        return _PAYPAL_TOKEN_CACHE["token"]
    auth=base64.b64encode((cfg["client_id"]+":"+cfg["secret"]).encode()).decode()
    req=urllib.request.Request(cfg["base"]+"/v1/oauth2/token",data=b"grant_type=client_credentials",
        headers={"Authorization":"Basic "+auth,"Content-Type":"application/x-www-form-urlencoded"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=20) as res: token_data=json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError("PayPal "+cfg["mode"].title()+" authentication failed (HTTP "+str(e.code)+"). Check the matching "+cfg["mode"].title()+" credentials and mode.")
    token=token_data.get("access_token")
    if not token: raise RuntimeError("PayPal did not return an access token.")
    lifetime=max(30,min(int(token_data.get("expires_in",300))-60,300))
    _PAYPAL_TOKEN_CACHE.update({"key":key,"token":token,"expires_at":time.time()+lifetime})
    return token

def paypal_api_request(method,path,payload=None):
    cfg=paypal_config()
    token=paypal_access_token()
    body=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(cfg["base"]+path,data=body,
        headers={"Authorization":"Bearer "+token,"Content-Type":"application/json","Accept":"application/json"},method=method)
    try:
        with urllib.request.urlopen(req,timeout=25) as res: return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail=e.read().decode(errors="replace")[:350]
        raise RuntimeError("PayPal API request failed (HTTP "+str(e.code)+"): "+detail)

def pf_form_signature(fields, passphrase):
    pairs=[]
    for key,value in fields.items():
        if value is None or str(value)=="" or key=="signature": continue
        pairs.append(str(key)+"="+urllib.parse.quote_plus(str(value).strip()))
    if passphrase: pairs.append("passphrase="+urllib.parse.quote_plus(passphrase.strip()))
    return hashlib.md5("&".join(pairs).encode()).hexdigest()

def pf_api_signature(values, passphrase):
    data={str(k):str(v) for k,v in values.items() if v is not None and str(v)!=""}
    if passphrase: data["passphrase"]=passphrase
    return hashlib.md5(urllib.parse.urlencode(sorted(data.items())).encode()).hexdigest()

def pf_api_request(method,path,body=None):
    cfg=payfast_config()
    if not all((cfg["merchant_id"],cfg["passphrase"])):
        raise RuntimeError("PayFast merchant ID and passphrase are not configured.")
    stamp=datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    headers={"merchant-id":cfg["merchant_id"],"version":"v1","timestamp":stamp}
    signed=dict(headers)
    if body: signed.update({k:str(v).lower() if isinstance(v,bool) else str(v) for k,v in body.items() if v is not None})
    headers["signature"]=pf_api_signature(signed,cfg["passphrase"])
    raw=json.dumps(body or {}).encode() if method in ("POST","PUT") else None
    if raw is not None: headers["Content-Type"]="application/json"
    req=urllib.request.Request(cfg["api_host"]+path,data=raw,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=20) as res: return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail=e.read().decode(errors="replace")[:1000]
        raise RuntimeError("PayFast API rejected the request ("+str(e.code)+"): "+detail)

def activate_payment(c, row, pfid):
    if row["status"]=="verified": return False
    c.execute("UPDATE payments SET status='verified',verified_at=?,pf_payment_id=? WHERE id=?",(now(),str(pfid),row["id"]))
    if row["business_id"]:
        days=365 if row["billing"]=="yearly" else 30
        expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=days)).isoformat()
        c.execute("UPDATE businesses SET plan=?,billing=?,payment_status='verified',status='active',subscription_expires_at=? WHERE id=?",(row["plan"],row["billing"],expires,row["business_id"]))
        c.execute("INSERT INTO subscriptions(business_id,user_id,plan,billing,status,started_at,expires_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(business_id) DO UPDATE SET user_id=excluded.user_id,plan=excluded.plan,billing=excluded.billing,status='active',started_at=excluded.started_at,expires_at=excluded.expires_at,cancelled_at=NULL",(row["business_id"],row["user_id"],row["plan"],row["billing"],"active",now(),expires))
    gateway="PayPal" if ("payment_gateway" in row.keys() and row["payment_gateway"]=="paypal") else "legacy gateway"
    c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("payment_verified",gateway+" payment verified","Payment reference "+row["reference"]+" was confirmed by "+gateway+". Amount: R"+str(row["amount"])+".",now(),setting("owner_email")))
    return True

def process_payfast_itn(raw):
    cfg=payfast_config()
    try: fields={k:v[-1] for k,v in urllib.parse.parse_qs(raw.decode("utf-8"),keep_blank_values=True).items()}
    except Exception: return False,"Malformed notification"
    signature=fields.get("signature","")
    signed_fields={k:v for k,v in fields.items() if k!="signature"}
    if not signature or not hmac.compare_digest(signature,pf_form_signature(signed_fields,cfg["passphrase"])):
        return False,"Invalid PayFast signature"
    if fields.get("merchant_id","")!=cfg["merchant_id"]:
        return False,"Merchant ID mismatch"
    if not fields.get("pf_payment_id","").strip(): return False,"Missing PayFast transaction ID"
    ref=fields.get("m_payment_id","")
    with conn() as c:
        row=c.execute("SELECT * FROM payments WHERE reference=?",(ref,)).fetchone()
    if not row: return False,"Unknown payment reference"
    try: gross=float(fields.get("amount_gross","-1"))
    except ValueError: return False,"Invalid amount"
    if abs(gross-float(row["amount"]))>0.01: return False,"Amount mismatch"
    # PayFast's server-side validation is required in addition to the signature.
    param_string="&".join(k+"="+urllib.parse.quote_plus(str(v).strip()) for k,v in signed_fields.items())
    validate_url="https://"+cfg["host"]+"/eng/query/validate"
    request=urllib.request.Request(validate_url,data=param_string.encode(),headers={"Content-Type":"application/x-www-form-urlencoded","User-Agent":"Skillvaya/1.0"},method="POST")
    try:
        with urllib.request.urlopen(request,timeout=15) as response: validation=response.read().decode().strip()
    except Exception: return False,"Could not validate notification with PayFast"
    if validation!="VALID": return False,"PayFast server validation failed"
    status=fields.get("payment_status","").upper()
    with conn() as c:
        row=c.execute("SELECT * FROM payments WHERE reference=?",(ref,)).fetchone()
        if not row: return False,"Payment disappeared"
        if row["status"]=="verified":
            if row["pf_payment_id"] and row["pf_payment_id"]!=fields.get("pf_payment_id",""): return False,"Duplicate reference with different transaction"
            return True,"Duplicate notification safely ignored"
        if status=="COMPLETE":
            activate_payment(c,row,fields.get("pf_payment_id",""))
        elif status in ("CANCELLED","FAILED"):
            c.execute("UPDATE payments SET status=? WHERE id=? AND status='pending'",(status.lower(),row["id"]))
    return True,"Notification processed"

def expire_subscriptions():
    with conn() as c:
        rows=c.execute("SELECT id,name,user_id,subscription_expires_at FROM businesses WHERE status='active' AND payment_status='verified' AND subscription_expires_at IS NOT NULL AND subscription_expires_at<=?",(now(),)).fetchall()
        for b in rows:
            c.execute("UPDATE businesses SET status='suspended',payment_status='overdue' WHERE id=?",(b["id"],))
            c.execute("UPDATE subscriptions SET status='expired',cancelled_at=? WHERE business_id=?",(now(),b["id"]))
            owner=c.execute("SELECT email,name FROM users WHERE id=?",(b["user_id"],)).fetchone() if b["user_id"] else None
            if owner:
                c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("subscription_overdue","Paid listing suspended: "+b["name"],"Hello "+owner["name"]+", your Skillvaya paid placement has expired because renewal payment was not confirmed. The listing is paused. Sign in and renew to request reactivation. Account email: "+owner["email"],now(),owner["email"]))
                c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("owner_alert","Subscription overdue: "+b["name"],"Provider account: "+owner["email"]+"; business: "+b["name"]+"; listing paused automatically.",now(),setting("owner_email")))
    # Cancel unpaid payment requests after a 7-day grace window.
    cutoff=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=7)).isoformat()
    with conn() as c:
        pending=c.execute("SELECT p.*,u.email,u.name,b.name business_name FROM payments p JOIN users u ON u.id=p.user_id LEFT JOIN businesses b ON b.id=p.business_id WHERE p.status='pending' AND p.created_at<=?",(cutoff,)).fetchall()
        for pay in pending:
            c.execute("UPDATE payments SET status='expired' WHERE id=?",(pay["id"],))
            if pay["business_id"]:
                c.execute("UPDATE businesses SET status='suspended',payment_status='overdue' WHERE id=? AND payment_status!='verified'",(pay["business_id"],))
            business=pay["business_name"] or "your provider listing"
            c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("payment_expired","Unpaid plan request cancelled","Hello "+pay["name"]+", your Skillvaya plan request ("+pay["reference"]+") for "+business+" expired because payment was not confirmed within 7 days. The paid placement is not active. Sign in to request a new plan when ready.",now(),pay["email"]))
            c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("owner_alert","Unpaid plan request expired","Account: "+pay["email"]+"; reference: "+pay["reference"]+"; amount: R"+str(pay["amount"])+"; business: "+business+". Request expired and listing was paused where applicable.",now(),setting("owner_email")))
    # Dispatch queued owner alerts without creating duplicate alert records.
    with conn() as c:
        pending=c.execute("SELECT id,subject,body,recipient FROM notifications WHERE status='new' ORDER BY id LIMIT 20").fetchall()
    for n in pending:
        if send_owner_email(n["subject"],n["body"],n["recipient"] or None):
            with conn() as c: c.execute("UPDATE notifications SET status='emailed',emailed_at=? WHERE id=?",(now(),n["id"]))
TERMS_PAGE_HTML = r"""<!doctype html><html lang="en-ZA"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><meta name="theme-color" content="#071426"><title>Skillvaya Terms & Conditions</title><style>*{box-sizing:border-box}body{margin:0;background:#f2f6fb;color:#17283d;font:16px/1.65 system-ui,Arial,sans-serif}.top{background:#071426;color:#fff;padding:28px 18px}.wrap{max-width:880px;margin:auto;padding:22px 18px}.paper{background:#fff;border:1px solid #dce5f0;border-radius:16px;padding:clamp(18px,4vw,36px)}h1{margin:0 0 8px;font-size:clamp(28px,4vw,40px)}h2{margin-top:28px;font-size:21px}a{color:#075f92}.warning{padding:14px;border-radius:10px;background:#fff5dd;color:#704b08}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}.btn{display:inline-block;border-radius:9px;padding:12px 16px;background:#087f8c;color:white;text-decoration:none;font-weight:700}.muted{color:#66758b;font-size:13px}</style></head><body><header class="top"><div class="wrap"><strong>Skillvaya</strong><h1>Terms, Conditions, Rules & Safety</h1><p>Version 1.2 · Effective 21 October 2026 · South Africa</p></div></header><main class="wrap"><article class="paper">
<p class="warning"><strong>Important:</strong> Read these terms before creating an account or signing in. You must actively tick the agreement box to continue. These terms do not remove consumer or privacy rights that cannot lawfully be excluded.</p>
<h2>1. Agreement, accounts and updates</h2><p>By ticking the agreement box and selecting Create account or Sign in, you confirm that you have had an opportunity to read these Terms, Conditions, Rules & Safety and agree to the current version. If you do not agree, do not create an account or use account-only features. We record the terms version and the date/time of acceptance. Material changes will be dated and presented for acceptance; you may stop using the service if you do not agree, subject to any outstanding lawful obligations.</p><p>Provide accurate information, protect your credentials, and notify us of suspected unauthorised use. You may not impersonate another person, evade a restriction, or access an account or information without permission. Keep email, phone, business details, prices and qualifications current.</p>
<h2>2. Skillvaya’s role and safety</h2><p>Skillvaya is a directory and introduction service intended to connect customers with service providers. Unless a separate written service says otherwise, Skillvaya is not the customer’s or provider’s agent, employer, insurer, contractor or guarantor, and is not a party to a contract between a customer and provider. A paid or featured placement is advertising, not an endorsement or certification. We do not guarantee identity, licensing, qualifications, availability, workmanship, service quality, price, completion, or outcomes. Check credentials, references, insurance, written quotations and work terms independently.</p>
<h2>3. Customer rules</h2><p>Customer directory browsing and ordinary contact are free unless a charge is clearly disclosed before the relevant transaction. Confirm scope, price, timing, cancellation terms and safety arrangements directly with a provider. Do not pay merely because a listing appears on Skillvaya. Never share passwords, one-time PINs or banking credentials. Use reporting tools honestly and promptly report suspected fraud or unsafe conduct.</p>
<h2>4. Provider rules and listings</h2><p>Providers must be legally entitled and suitably qualified for the services they advertise; must comply with applicable laws and professional rules; must provide honest descriptions, quotes and credentials; and must treat customers respectfully. Do not post unlawful, counterfeit, deceptive, discriminatory, threatening, fraudulent or unsafe listings, or another person’s private information without a lawful basis. Skillvaya may ask for evidence, moderate, limit, suspend or remove content or accounts where reasonably needed for safety, integrity, payment issues or legal compliance. Reports are allegations, not findings of guilt; decisions should be based on available evidence and applicable law.</p>
<h2>5. Plans, prices and increases</h2><p>Any paid placement or subscription must show the plan, included features, billing term, full amount payable, applicable taxes/fees, start/end or renewal date, cancellation terms and payment method before you approve purchase. The amount displayed at checkout and accepted for a paid term is the price for that term; a later price change will not retrospectively increase that already-paid term.</p><p><strong>Skillvaya’s plan and subscription prices may increase or otherwise change over time.</strong> Changes may reflect hosting, payment processing, operating costs, product features, taxes, inflation, or business decisions. Where legally required, and as a general service commitment, we will give reasonable advance notice of a material price increase—normally at least 30 days before it applies to a future renewal—and identify the new price and effective date. A change will not be applied mid-term to a term already paid for. You can cancel or choose not to renew before the new price takes effect. We will not charge the new amount or treat silence as permission for an undisclosed charge; the new price must be displayed before a new purchase or renewal is approved. If applicable law requires a different notice period or process, that law prevails.</p><p>Taxes, currency conversion and payment-provider charges, if any, will be disclosed where they can be determined before approval. Providers are responsible for any tax obligations applicable to their own business.</p>
<h2>6. Payments, confirmation and renewals</h2><p>At present, Skillvaya’s only enabled checkout provider is PayPal; PayFast is paused. We are working towards making additional payment-service providers available in the future, subject to technical integration, provider approval, security, and applicable compliance checks. Additional payment options will be announced when they are actually enabled; do not assume a future or unlisted provider is currently supported. The application may be in Sandbox/testing mode, in which case test transactions are not real payments and must not be treated as proof of a real charge. A payment or plan is treated as paid/active only after a successful payment-provider confirmation that matches the order reference, currency and amount. A pending order, browser redirect, screenshot or payment claim alone is not proof of payment. Do not retry a transaction if PayPal says it was completed; contact support with its transaction reference.</p><p>Unless a checkout clearly states otherwise and you expressly authorise recurring billing, plan renewals are not automatic. A plan may expire or paid placement may be paused when its paid period ends without a confirmed renewal. Before a new renewal or plan upgrade, the price and term will be shown again. Do not store, share or submit someone else’s payment credentials.</p>
<h2>7. Cancellation, refunds and disputes</h2><p>Cancellation stops a future renewal where renewal functionality exists; it does not automatically reverse a completed payment or erase amounts lawfully due for a term already supplied. Refund requests are reviewed under the displayed checkout terms and applicable law. Where a payment provider offers a refund mechanism, Skillvaya submits a refund only against the matching confirmed transaction; a request is not complete until the provider confirms its status. We will show pending, partial or completed refund status as accurately as practicable. Nothing in these terms removes non-excludable rights, including any applicable statutory cancellation or refund rights.</p><p>For billing errors, duplicate charges, non-delivery, unauthorised payment concerns or a disagreement about a provider’s service, contact us promptly with the order/payment reference and a factual description. Do not send card security codes, passwords, or one-time PINs in a support request.</p>
<h2>8. Privacy and communications</h2><p>Skillvaya may process your name, email address, phone number, account role, business/listing details, enquiries, complaints, payment references/status and technical usage information to operate the service, authenticate accounts, connect customers and providers, process and reconcile payments, maintain safety, prevent abuse and respond to support requests. Information may be shared with service providers such as hosting and payment processors only as reasonably necessary for those purposes or where law permits/requires. We aim to use reasonable safeguards, restrict access, keep information only as long as reasonably necessary or legally required, and respond to lawful requests to access or correct information. A complete business-specific privacy notice, retention schedule and data-subject request procedure should be maintained and made available before full public launch. No security measure can guarantee absolute security.</p>
<h2>9. Prohibited conduct</h2><p>No fraud, threats, harassment, unlawful discrimination, illegal services, stolen or counterfeit goods, deceptive claims, spam, scraping that breaches rules or law, malware, unauthorised access, payment manipulation, forged reviews, false reports, or publication of private information without a lawful basis. Skillvaya may preserve records, investigate and restrict activity when warranted.</p>
<h2>10. Availability, liability and changes</h2><p>Online services can be unavailable, delayed or interrupted, and third-party providers may have outages or errors. We will take reasonable care, but do not promise uninterrupted availability. To the extent permitted by law, Skillvaya is not responsible for independent contracts, acts or omissions of customers, providers, banks or payment processors. Nothing excludes liability or remedies that cannot legally be excluded, and nothing limits rights under applicable South African law. We may update these terms with a new version date and appropriate notice.</p>
<h2>11. Applicable law and contact</h2><p>These terms are intended to operate under the laws of the Republic of South Africa, subject to any mandatory law that applies to a user or transaction. For account, billing, safety or privacy concerns, email <a href="mailto:skillvaya@gmail.com">skillvaya@gmail.com</a> or use the in-app reporting feature.</p>
<p class="muted">This is a working business draft, not legal advice. Have a South African attorney review it—especially the consumer disclosures, recurring-payment model, refund policy and privacy/POPIA arrangements—before accepting real customer payments.</p>
<div class="actions"><a class="btn" href="/login">Return to sign in</a><a href="/website">Public website</a></div></article></main></body></html>"""

LOGIN_GATEWAY_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#10233f"><title>Sign in — Skillvaya</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(145deg,#071426,#102b49);font:16px/1.5 Arial,sans-serif;color:#eef5ff;padding:18px}.card{width:min(100%,440px);background:#fff;color:#17263b;border-radius:20px;padding:28px;box-shadow:0 22px 70px #0005}.brand{font-size:27px;font-weight:800;margin-bottom:5px}.brand span{color:#087f8c}.sub{color:#627188;margin:0 0 24px}label{display:block;font-weight:650;margin:14px 0 6px}input{display:block;width:100%;padding:13px;border:1px solid #cbd5e1;border-radius:9px;font-size:16px}button{width:100%;padding:13px;border:0;border-radius:9px;background:#087f8c;color:#fff;font-size:16px;font-weight:750;margin-top:20px;cursor:pointer}button:disabled{opacity:.65}#status{min-height:24px;color:#b42318;font-size:14px}.hint{font-size:12px;color:#65748a;margin-top:18px}.notice{background:#fff5dd;color:#704b08;border-radius:10px;padding:12px;font-size:13px}.agree{display:flex;align-items:flex-start;gap:9px;font-size:13px;font-weight:500}.agree input{width:auto;margin:4px 0 0;flex:0 0 auto}.agree a{color:#087f8c}</style></head><body><main class="card"><div class="brand">Skill<span>vaya</span></div><p class="sub">Sign in to open your Skillvaya workspace.</p><p class="notice">By signing in or creating an account, you confirm that you agree to Skillvaya’s current <a href="/terms" target="_blank" rel="noopener">Terms, Conditions, Rules & Safety</a>, including the payment and price-change rules.</p><form id="loginForm"><label for="email">Email address</label><input id="email" type="email" autocomplete="username" required autofocus><label for="password">Password</label><span style="position:relative;display:block"><input id="password" type="password" autocomplete="current-password" required style="padding-right:48px"><button type="button" aria-label="Show password" onclick="const p=document.getElementById('password');const s=p.type==='password';p.type=s?'text':'password';this.setAttribute('aria-label',s?'Hide password':'Show password')" style="position:absolute;right:5px;top:50%;transform:translateY(-50%);width:38px;height:36px;padding:7px;background:transparent;color:#52647b;display:grid;place-items:center"><svg viewBox="0 0 24 24" aria-hidden="true" style="width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg></button></span><label class="agree" for="agreeTerms"><input id="agreeTerms" type="checkbox" required> I have read and agree to the current <a href="/terms" target="_blank" rel="noopener">Terms & Conditions</a>.</label><button id="submit" type="submit">Sign in</button><p id="status" role="status" aria-live="polite"></p></form><p class="hint">Your account determines which workspace opens. The public marketing page is separate from the installed app.</p></main><script>const form=document.getElementById('loginForm'),statusEl=document.getElementById('status'),submit=document.getElementById('submit');form.addEventListener('submit',async e=>{e.preventDefault();statusEl.textContent='Signing in…';submit.disabled=true;try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value.trim(),password:document.getElementById('password').value,accept_terms:document.getElementById('agreeTerms').checked})});const d=await r.json();if(!r.ok||!d.token||!d.user){statusEl.textContent=d.error||'Sign-in failed. Check your details and try again.';return;}if(d.user.role==='admin'){localStorage.setItem('skillvaya_owner_token',d.token);localStorage.setItem('skillvaya_token',d.token);localStorage.removeItem('sv_token');location.replace('/owner-app');return;}localStorage.setItem('skillvaya_token',d.token);localStorage.setItem('sv_token',d.token);localStorage.setItem('skillvaya_user',JSON.stringify({id:d.user.id,name:d.user.name,email:d.user.email,role:d.user.role}));location.replace('/customer-app');}catch(err){statusEl.textContent='Could not connect. Please check your connection and try again.';}finally{submit.disabled=false;}});</script></body></html>"""

OWNER_APP_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#10233f"><title>Skillvaya — Owner App</title><style>
:root{font:15px/1.5 'Segoe UI',Arial;color:#eaf1fb;background:#071426}*{box-sizing:border-box}body{margin:0}.head{padding:18px 20px;background:#10233f;border-bottom:1px solid #274263}.brand{display:flex;align-items:center;gap:12px}.brand img{width:48px;height:48px;object-fit:contain;background:#071426;border-radius:10px}.wrap{max-width:1200px;margin:auto;padding:16px}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.tabs button,.action{border:1px solid #355477;border-radius:9px;background:#172b45;color:#eaf1fb;padding:11px 15px;font-weight:650;cursor:pointer}.tabs button.active,.action.primary{background:#087f8c;border-color:#25b8bf;color:white}.panel{background:#10213a;border:1px solid #29415f;border-radius:14px;padding:18px;margin:12px 0}.muted{color:#a8bad1}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.hero{padding:20px 0}.hero h1{margin:0 0 8px;font-size:clamp(28px,4vw,42px)}.framewrap{display:none}.framewrap.active{display:block}.framehead{display:flex;align-items:center;gap:10px;margin-bottom:12px}.framehead h2{margin:0 auto 0 0}.frame{width:100%;height:calc(100vh - 245px);min-height:520px;border:1px solid #355477;border-radius:12px;background:#f4f7fb}.big{font-size:22px;font-weight:750}.notice{background:#182e49;border-radius:10px;padding:12px;color:#d4e5fa}@media(max-width:600px){.wrap{padding:10px}.frame{height:75vh;min-height:480px}.head{padding:12px}}
</style></head><body><header class="head"><div class="brand"><img src="/sv-logo.jpeg" alt="Skillvaya logo"><div><div style="font-size:24px;font-weight:800">Skillvaya <span style="color:#42d3d0">Owner App</span></div><div class="muted">Your owner workspace · no customer sign-in required</div></div></div></header><main class="wrap"><section id="ownerLogin" class="panel" style="max-width:520px;margin:28px auto"><h1>Owner sign-in</h1><p class="muted">Sign in with your Skillvaya owner account to open your private workspace.</p><p class="notice">By signing in, you confirm that you agree to the current <a href="/terms" target="_blank" rel="noopener">Skillvaya Terms & Conditions</a>, including payment and price-change rules.</p><form id="ownerLoginForm"><label for="ownerLoginEmail">Owner email</label><input id="ownerLoginEmail" type="email" autocomplete="username" required style="display:block;width:100%;padding:12px;margin:6px 0 14px;border-radius:8px"><label for="ownerLoginPassword">Password</label><span style="position:relative;display:block"><input id="ownerLoginPassword" type="password" autocomplete="current-password" required style="display:block;width:100%;padding:12px 48px 12px 12px;margin:6px 0 14px;border-radius:8px"><button type="button" aria-label="Show password" onclick="const p=document.getElementById('ownerLoginPassword');const s=p.type==='password';p.type=s?'text':'password';this.setAttribute('aria-label',s?'Hide password':'Show password')" style="position:absolute;right:5px;top:50%;transform:translateY(-50%);width:38px;height:36px;padding:7px;background:transparent;color:#52647b;display:grid;place-items:center"><svg viewBox="0 0 24 24" aria-hidden="true" style="width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg></button></span><label for="ownerAgreeTerms" style="display:flex;gap:9px;align-items:flex-start;font-size:13px"><input id="ownerAgreeTerms" type="checkbox" required style="width:auto;margin-top:4px"> I have read and agree to the current <a href="/terms" target="_blank" rel="noopener">Terms & Conditions</a>.</label><button class="action primary" type="submit">Sign in to Owner App</button><p id="ownerLoginStatus" class="muted" role="status"></p></form></section><section id="home" style="display:none"><div class="hero"><h1>Welcome to your Skillvaya Owner App</h1><p class="muted">This is your owner-side app. You do not need to register as a customer or buy a plan to manage your own platform.</p></div><div class="tabs"><button class="active" data-tab="home" onclick="showTab('home')">Home</button><button data-tab="control" onclick="showTab('control')">Owner Control</button><button data-tab="payments" onclick="showTab('payments')">Payments & refunds</button><button data-tab="personal" onclick="openCustomer()">My Free App</button><button data-tab="customer" onclick="openCustomer()">Open customer app ↗</button></div><div class="grid"><div class="panel"><div class="big">Owner Control</div><p class="muted">Manage listings, accounts, reports, notifications, analytics and owner email from your private control screen.</p><button class="action primary" onclick="showTab('control')">Open Owner Control</button></div><div class="panel"><div class="big">My Skillvaya — Free Owner Listings</div><p class="muted">Create your own business/service listing, promotion or app entry here. Owner-created entries are marked owner-free and do not require a customer plan or advertising payment.</p><button class="action primary" onclick="openCustomer()">Open My Free App</button></div><div class="panel"><div class="big">Website & share link</div><p class="muted">Open the public-facing Skillvaya website from your owner app, or share its address with potential customers and service providers. Until hosting is configured, the address is local to this PC and cannot be opened by the public.</p><button class="action primary" onclick="openWebsite()">Open Skillvaya website</button> <button class="action" onclick="shareWebsite()">Share website link</button><p id="shareStatus" class="muted" aria-live="polite"></p></div></div><p class="notice">Owner workspace is protected by your owner account. Keep your password private.</p><button class="action" onclick="ownerLogout()">Sign out</button></section><section id="control" class="framewrap"><div class="tabs"><button onclick="showTab('home')">← Back to Owner App</button></div><div class="framehead"><h2>Owner Control</h2><button class="action" onclick="showTab('home')">← Back</button></div><iframe class="frame" src="/owner-control" title="Skillvaya Owner Control"></iframe></section><section id="payments" class="framewrap"><div class="framehead"><button class="action" onclick="showTab('home')">← Back</button><h2>Payments & refunds</h2></div><iframe class="frame" src="/owner-control#payments" title="Skillvaya payment controls"></iframe><p class="notice"><strong>PayPal checkout.</strong> Skillvaya activates a plan only after PayPal confirms the exact order, amount and currency.</p><p class="muted">Refunds are submitted against PayPal capture IDs and recorded according to PayPal's returned refund state. Confirm the configured PayPal mode and payment status before processing refunds.</p></section><section id="promotions" class="framewrap"><div class="framehead"><button class="action" onclick="showTab('home')">Back</button><h2>My Skillvaya — Free Owner App</h2></div><p class="muted">Create and publish your own business, services, promotions and app entries free. Preview the same public experience customers see below; your owner controls stay private.</p><div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0"><button class=\"action primary\" onclick=\"openCustomer()\">Open My Free App</button><button class="action" onclick="document.getElementById('ownerPreviewFrame').style.display='block';document.getElementById('ownerManageFrame').style.display='none';document.getElementById('ownerPreviewFrame').src='/customer'">Preview customer experience</button></div><iframe id="ownerManageFrame" class="frame" src="/owner-control#owner-promotions" title="Manage free owner listings"></iframe><iframe id="ownerPreviewFrame" class="frame" src="about:blank" title="Public Skillvaya preview" style="display:none"></iframe></section></main><script>function showTab(t){if(t==='personal'||t==='promotions'){openCustomer();return}document.getElementById('home').style.display=t==='home'?'block':'none';document.getElementById('control').classList.toggle('active',t==='control');document.getElementById('payments').classList.toggle('active',t==='payments');document.getElementById('promotions').classList.toggle('active',t==='promotions');document.querySelectorAll('button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===t));window.scrollTo(0,0)}function openCustomer(){const t=localStorage.getItem('skillvaya_owner_token')||localStorage.getItem('skillvaya_token')||localStorage.getItem('sv_token');if(t){localStorage.setItem('skillvaya_token',t);localStorage.setItem('sv_token',t)}location.href='/customer-app'}function openWebsite(){location.href='/'}async function shareWebsite(){const url=location.origin+'/';const data={title:'Skillvaya',text:'Find your people. Get it done. Discover local service providers and grow your business.',url};const status=document.getElementById('shareStatus');try{if(navigator.share){await navigator.share(data);if(status)status.textContent='Share sheet opened.';return;}if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(url);if(status)status.textContent='Website link copied: '+url;return;}window.prompt('Copy and share this website link:',url);if(status)status.textContent='Copy the link shown above. Public sharing works after hosting is connected.';}catch(e){if(e&&e.name!=='AbortError')window.prompt('Copy and share this website link:',url);}}async function ownerValidateToken(){const t=localStorage.getItem('skillvaya_owner_token');if(!t)return;try{const r=await fetch('/api/me',{headers:{Authorization:'Bearer '+t}});const d=await r.json();if(r.ok&&d.user&&d.user.role==='admin'){localStorage.setItem('skillvaya_token',t);localStorage.setItem('sv_token',t);localStorage.setItem('skillvaya_user',JSON.stringify({id:d.user.id,name:d.user.name,email:d.user.email,role:d.user.role}));document.getElementById('ownerLogin').style.display='none';document.getElementById('home').style.display='block';const f=document.querySelector('#control iframe');if(f)f.src='/owner-control';const pf=document.querySelector('#promotions iframe');if(pf)pf.src='/owner-control#owner-promotions';return;}localStorage.removeItem('skillvaya_owner_token');}catch(e){}}
document.getElementById('ownerLoginForm').addEventListener('submit',async e=>{e.preventDefault();const st=document.getElementById('ownerLoginStatus');st.textContent='Signing in…';try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('ownerLoginEmail').value,password:document.getElementById('ownerLoginPassword').value,accept_terms:document.getElementById('ownerAgreeTerms').checked})});const d=await r.json();if(!r.ok)throw Error(d.error||'Sign-in failed');if(!d.user||d.user.role!=='admin')throw Error('This account is not the Skillvaya owner account.');localStorage.setItem('skillvaya_owner_token',d.token);localStorage.setItem('skillvaya_token',d.token);localStorage.setItem('sv_token',d.token);localStorage.setItem('skillvaya_user',JSON.stringify({id:d.user.id,name:d.user.name,email:d.user.email,role:d.user.role}));document.getElementById('ownerLogin').style.display='none';document.getElementById('home').style.display='block';const f=document.querySelector('#control iframe');if(f)f.src='/owner-control';const pf=document.querySelector('#promotions iframe');if(pf)pf.src='/owner-control#owner-promotions';st.textContent='';}catch(err){st.textContent=err.message;}});
function ownerLogout(){localStorage.removeItem('skillvaya_owner_token');localStorage.removeItem('skillvaya_token');localStorage.removeItem('sv_token');location.replace('/');}
ownerValidateToken();if(location.hash==='#control')showTab('control');if(location.hash==='#payments')showTab('payments');if(location.hash==='#promotions')showTab('promotions');</script></body></html>"""
OWNER_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Skillvaya — Owner Control</title><style>
:root{font:15px/1.5 'Segoe UI',Arial;color:#19283b;background:#f4f7fb}*{box-sizing:border-box}body{margin:0}.head{background:#10233f;color:white;padding:20px}.owner-brand{display:flex;align-items:center;gap:12px}.owner-brand img{width:54px;height:54px;object-fit:contain;border-radius:10px;background:#08142b}.wrap{max-width:1100px;margin:auto;padding:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{background:white;border:1px solid #e1e8f1;border-radius:12px;padding:16px;margin-bottom:14px}button{border:0;border-radius:8px;padding:10px 13px;margin:3px;background:#2365d8;color:white;font-weight:650;cursor:pointer}.secondary{background:#eaf0f8;color:#10233f}.muted{color:#66758b}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:620px}td,th{text-align:left;padding:9px;border-bottom:1px solid #e1e8f1;vertical-align:top}.stat{font-size:28px;font-weight:800}.notice{padding:12px;border-radius:9px;background:#eaf7f0;color:#13714d;margin:10px 0}@media(max-width:600px){.wrap{padding:10px}}</style></head><body><header class="head"><div class="wrap"><div class="owner-brand"><img src="/sv-logo.jpeg" alt="SV Skillvaya logo"><div><h1 style="margin:0">Skillvaya - Owner Control</h1><div class="tiny">Owner workspace</div></div></div><div>Private developer console · local PC only · no owner sign-in</div><div style="margin-top:8px">Platform email: <span id="ownerEmailLabel">skillvaya@gmail.com</span></div></div></header><main class="wrap"><div class="notice">This control app is separate from the customer Skillvaya app. It works without an account only while the Skillvaya service is bound to this PC's loopback address. Keep the service local until a properly secured public deployment is configured.</div><div class="grid" id="stats"></div><section class="card"><h2>Workspace</h2><p class="muted">Choose one work area. Related tools are grouped together so the control screen is easier to navigate.</p><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));align-items:end"><div><label for="workspacePicker">Open a work area</label><select id="workspacePicker" style="width:100%;padding:12px;border:1px solid #cbd6e4;border-radius:8px;background:white;color:#19283b" onchange="if(this.value){load(this.value)}"><option value="">Select a task…</option><optgroup label="Marketplace"><option value="businesses">Business listings</option><option value="owner-promotions">My businesses & promotions (free)</option></optgroup><optgroup label="Platform operations"><option value="clients">Customer accounts</option><option value="complaints">Reports & complaints</option><option value="notifications">Alerts & notifications</option><option value="analytics">Usage & analytics</option></optgroup><optgroup label="Payments"><option value="payments">Payments & refunds</option></optgroup><optgroup label="Communications & settings"><option value="inbox">Owner inbox</option><option value="compose">Compose email</option><option value="settings">Email & platform settings</option></optgroup></select></div><div><button onclick="load('summary')">Refresh overview</button> <button onclick="location.href='/owner-app'" class="secondary">Back to Owner App</button></div></div></section><section class="card" id="panel"><h2>Overview</h2><p class="muted">Select a control above.</p></section></main><script>
async function api(path,opts={}){const ownerToken=localStorage.getItem('skillvaya_owner_token');opts.headers={'Content-Type':'application/json',...(ownerToken?{Authorization:'Bearer '+ownerToken}:{}),...(opts.headers||{})};let r=await fetch(path,opts);let d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function load(tab){let p=document.getElementById('panel');try{if(tab==='summary'){let d=await api('/api/admin/summary');document.getElementById('stats').innerHTML=Object.entries({Businesses:d.businesses,'Open complaints':d.complaints,'Payment requests':d.payments,'Pending listings':d.pending}).map(([k,v])=>'<div class="card"><div class="muted">'+k+'</div><div class="stat">'+v+'</div></div>').join('');p.innerHTML='<h2>Owner overview</h2><p>Local developer access is active. Customer accounts remain separate and are not automatically signed in.</p>';return}
 if(tab==='owner-promotions'){let d=await api('/api/admin/owner-promotions');let cats=['Builders & construction', 'Plumbers', 'Electricians', 'Painters & decorators', 'Mechanics & automotive', 'Cleaning & housekeeping', 'Gardening & landscaping', 'Roofing & waterproofing', 'Carpenters & furniture', 'Welders & fabricators', 'Appliance repairs', 'IT & computer support', 'Graphic designers', 'Artists & photographers', 'Marketing & advertising', 'Web & software developers', 'Lawyers & legal services', 'Private doctors & clinics', 'Dentists & specialists', 'Nurses & home care', 'Accountants & tax', 'Financial & insurance services', 'Real estate & property', 'Tutors & education', 'Beauty & hair', 'Catering & chefs', 'Transport & removals', 'Security services', 'Events & entertainment', 'Tailors & fashion', 'Pet care & veterinary', 'Funeral services', 'Engineering & consulting', 'Other professional services'];p.innerHTML='<h2>My Businesses & Promotions</h2><p>Owner-created business profiles, ads and apps are permanently exempt from Skillvaya listing and subscription fees.</p><form id="ownerPromoForm"><label>Type</label><select name="kind"><option value="business">My business</option><option value="ad">Advertisement / product / service</option><option value="app">App I created</option></select><label>Business / brand name</label><input name="business_name" required maxlength="120"><label>Listing title</label><input name="title" required maxlength="160"><label>Category</label><select name="category">'+cats.map(x=>'<option>'+esc(x)+'</option>').join('')+'</select><label>Description</label><textarea name="description" required maxlength="3000" rows="4"></textarea><label>Website / app download URL</label><input name="target_url" type="url" maxlength="500" placeholder="https://..."><label>Image URL (optional)</label><input name="image_url" type="url" maxlength="1000" placeholder="https://..."><p><button>Save & publish for free</button></p></form><div id="ownerPromoStatus" class="muted"></div><h3>Your entries</h3>'+table(['Type','Business','Title','Status','Fee exemption','Action'],(d.items||[]).map(x=>[x.kind,x.business_name,x.title,x.status,x.owner_free?'Free':'Review',x.status==='removed'?'Removed':'<button onclick="ownerPromoStatus('+x.id+',\''+(x.status==='active'?'paused':'active')+'\')">'+(x.status==='active'?'Pause':'Publish')+'</button> <button class="secondary" onclick="ownerPromoStatus('+x.id+',\'removed\')">Delete</button>']));document.getElementById('ownerPromoForm').onsubmit=async e=>{e.preventDefault();let st=document.getElementById('ownerPromoStatus');try{await api('/api/admin/owner-promotions',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});st.textContent='Saved and published. Owner fee exemption stored.';load('owner-promotions')}catch(x){st.textContent='Not saved: '+x.message}};return}
if(tab==='analytics'){let d=await api('/api/admin/analytics'),s=d.stats;p.innerHTML='<h2>Usage & payments</h2><div class="grid">'+Object.entries(s).map(([k,v])=>'<div class="card"><div class="muted">'+esc(k.replaceAll('_',' '))+'</div><div class="stat">'+esc(typeof v==='number'&&k==='revenue'?'R'+v.toLocaleString('en-ZA'):v)+'</div></div>').join('')+'</div><p class="muted">Local visit counts are not public website analytics or store-download totals.</p>';return}
if(tab==='compose'){let d=await api('/api/admin/clients');let items=d.items||[];p.innerHTML='<h2>Compose email</h2><p class="muted">Compose and send within Skillvaya. Delivery requires the server email connection to be configured.</p><form id="composeForm"><label>Recipient account</label><select name="client_id" required><option value="">Choose a customer or provider</option>'+items.map(x=>'<option value="'+x.id+'">'+esc(x.name)+' â€” '+esc(x.email)+' ('+esc(x.role)+')</option>').join('')+'</select><label>Subject</label><input name="subject" maxlength="180" required><label>Message</label><textarea name="body" rows="6" maxlength="10000" required></textarea><p><button class="primary">Send from Skillvaya</button></p><div id="composeStatus" class="muted"></div></form>';document.getElementById('composeForm').onsubmit=async e=>{e.preventDefault();let f=Object.fromEntries(new FormData(e.target));let st=document.getElementById('composeStatus');st.textContent='Sending through Skillvaya email serviceâ€¦';try{let r=await api('/api/admin/email-client',{method:'POST',body:JSON.stringify(f)});st.textContent='Sent to '+r.recipient+'.'}catch(err){st.textContent='Not sent: '+err.message;}};return}
if(tab==='inbox'){let d=await api('/api/admin/notifications');p.innerHTML='<h2>Skillvaya in-app inbox</h2><p class="muted">This inbox shows messages and system alerts recorded by Skillvaya. It is not a live mirror of Gmail; Gmail mailbox syncing requires Google OAuth authorization.</p>'+table(['Date','Type','Subject','Status','Recipient','Message'],(d.items||[]).map(x=>[x.created_at,x.kind,x.subject,x.status,x.recipient,x.body]));return}
if(tab==='settings'){let d=await api('/api/admin/settings');p.innerHTML='<h2>Owner email</h2><form id="email"><label>Notification email <input type="email" name="owner_email" value="'+esc(d.owner_email)+'" required></label><p><button>Save email</button><button type="button" class="secondary" onclick="testEmail()">Send test email</button></p></form><p><button type="button" class="secondary" onclick="load(&#39;compose&#39;)">Compose inside Skillvaya</button> <button type="button" class="secondary" onclick="load(&#39;inbox&#39;)">Open Skillvaya inbox</button></p><p class="muted">'+esc(d.note)+' '+(d.smtp_configured?'SMTP detected.':'SMTP not configured yet; app-triggered emails cannot be sent until Gmail SMTP credentials are configured securely on the server.')+'</p>';document.getElementById('email').onsubmit=async e=>{e.preventDefault();try{await api('/api/admin/settings',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});alert('Owner email saved');load('settings')}catch(x){alert(x.message)}};return}
let d=await api('/api/admin/'+tab);let items=d.items||[];if(tab==='clients'){p.innerHTML='<h2>Accounts</h2>'+table(['Name','Email','Role','Created','Listings','Paid'],items.map(x=>[x.name,x.email,x.role,x.created_at,x.businesses,x.paid]));return}
if(tab==='notifications'){p.innerHTML='<h2>Alerts</h2>'+table(['Date','Type','Subject','Status','Message'],items.map(x=>[x.created_at,x.kind,x.subject,x.status,x.body]));return}
if(tab==='businesses'){p.innerHTML='<h2>Listings</h2>'+table(['Name','Category','Area','Phone','Status','Plan'],items.map(x=>[x.name,x.category,x.area,x.phone,x.status,x.plan]));return}
if(tab==='payments'){let g=await api('/api/admin/paypal/status');p.innerHTML='<h2>PayPal payment requests & refunds</h2><p class="muted">Mode: <b>'+esc(g.mode)+'</b> · PayPal client credentials: '+(g.credentials_configured?'configured':'missing')+' · Sandbox OAuth: '+(g.oauth_valid?'verified':'not verified')+'</p><p class="muted">'+esc(g.message)+'</p><p>Paid plans activate only after PayPal confirms a completed capture matching the order reference, ZAR currency and amount. Refunds run against PayPal capture IDs.</p>'+table(['Reference','User','Amount','Plan','Status','Refund','Action'],items.map(x=>[x.reference,x.user_id,'R'+x.amount,x.plan,x.status,x.refund_status||'none',x.status==='verified'&&(x.paypal_capture_id||x.pf_payment_id)?'<button onclick="refund('+x.id+','+x.amount+','+(x.refunded_amount||0)+')">Refund</button>':x.status==='pending'?'Awaiting PayPal confirmation':'—']));return}
if(tab==='complaints'){p.innerHTML='<h2>Reports & complaints</h2>'+table(['Date','Business','Reason','Status'],items.map(x=>[x.created_at,x.business_name,x.reason,x.status]));return}
}catch(e){p.innerHTML='<h2>Could not load control data</h2><p>'+esc(e.message)+'</p>'}}
function table(headers,rows){return '<div class="tablewrap"><table><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr>'+rows.map(row=>'<tr>'+row.map((x,i)=>'<td>'+(i===row.length-1&&String(x).startsWith('<button')?x:esc(x))+'</td>').join('')+'</tr>').join('')+'</table></div>'}
async function refund(id,amount,already){let remaining=amount*100-Number(already||0);let value=prompt('Refund amount in Rands (maximum R'+(remaining/100).toFixed(2)+')',''+(remaining/100).toFixed(2));if(value===null)return;let cents=Math.round(Number(value)*100);if(!Number.isFinite(cents)||cents<1||cents>remaining){alert('Enter a valid amount within the remaining paid balance.');return}let reason=prompt('Reason for refund (at least 3 characters):');if(!reason||reason.trim().length<3)return;if(!confirm('Submit a PayPal refund request for R'+(cents/100).toFixed(2)+'?'))return;try{let d=await api('/api/admin/refunds/'+id,{method:'POST',body:JSON.stringify({amount:cents,reason})});alert(d.message||'PayPal response received for the refund request.');load('payments')}catch(e){alert(e.message)}}
async function ownerPromoStatus(id,status){try{await api('/api/admin/owner-promotions/'+id,{method:'POST',body:JSON.stringify({status})});load('owner-promotions')}catch(e){alert(e.message)}}
async function testEmail(){try{await api('/api/admin/test-email',{method:'POST',body:'{}'});alert('Test email sent')}catch(e){alert(e.message)}}
if(location.hash==='#payments')load('payments');else load('summary');
</script></body></html>"""
HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#10233f"><link rel="manifest" href="/manifest.json"><link rel="icon" href="/sv-logo.jpeg" type="image/jpeg"><title>Skillvaya</title><style>
:root{--navy:#10233f;--blue:#2365d8;--bg:#f4f7fb;--ink:#19283b;--muted:#66758b;--line:#e1e8f1;--red:#c83232}*{box-sizing:border-box}.sv-splash{animation:sv-splash-failsafe .25s ease 12s forwards;position:fixed;inset:0;z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;background:linear-gradient(145deg,#071426,#102b49);color:#f4f8ff;transition:opacity .28s ease,visibility .28s ease}.sv-splash.done{opacity:0;visibility:hidden;pointer-events:none}.sv-splash-brand{font-size:clamp(34px,7vw,52px);font-weight:850;letter-spacing:-1.5px}.sv-splash-brand span{color:#42d3d0}.sv-splash-caption{font-size:16px;color:#d3e2f4;letter-spacing:.3px}.sv-loading-dots{display:flex;gap:9px;align-items:center}.sv-loading-dots i{width:9px;height:9px;border-radius:50%;background:#42d3d0;opacity:.22;animation:sv-dot-pulse 1.05s infinite ease-in-out}.sv-loading-dots i:nth-child(2){animation-delay:.18s}.sv-loading-dots i:nth-child(3){animation-delay:.36s}@keyframes sv-dot-pulse{0%,65%,100%{opacity:.2;transform:scale(.82);filter:brightness(.7)}30%{opacity:1;transform:scale(1.12);filter:brightness(1.5)}}@keyframes sv-splash-failsafe{to{opacity:0;visibility:hidden;pointer-events:none}}.password-wrap{position:relative;display:flex;align-items:center;width:100%}.password-wrap input{padding-right:48px}.password-toggle{position:absolute;right:5px;top:50%;transform:translateY(-50%);width:38px;height:36px;padding:7px;background:transparent;color:#52647b;border-radius:8px;display:grid;place-items:center}.password-toggle:hover{background:#edf3fa}.password-toggle svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.photo-picker{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.photo-pick-wrap{position:relative;display:inline-flex;overflow:hidden;border-radius:10px;min-height:44px}.photo-pick-button{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:11px 15px;background:#edf4ff;color:#173e76;border:1px solid #c8d9f2;border-radius:10px;font-weight:700;cursor:pointer}.photo-pick-wrap input[type=file]{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer;z-index:2}.photo-pick-wrap:focus-within{outline:3px solid #8bbcff;outline-offset:2px}.photo-pick-button:hover{background:#dfeeff}.photo-file-name{font-size:13px;color:var(--muted);overflow-wrap:anywhere}.photo-input-hidden{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}.category-screen{padding:22px 0 55px;min-height:45vh}.category-screen-head{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:18px}.category-back{background:#edf3fa;color:#17365d;border:1px solid #d6e1ee}.category-results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}@media(max-width:800px){.category-results{grid-template-columns:1fr}}body{margin:0;font:15px/1.5 "Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--ink)}button,input,select,textarea{font:inherit}button{cursor:pointer;border:0;border-radius:10px;padding:10px 14px;font-weight:650}.primary{background:var(--blue);color:#fff}.ghost{background:#eef3fa;color:var(--navy)}.danger{background:#fff0f0;color:var(--red)}input,select,textarea{border:1px solid var(--line);border-radius:9px;padding:11px;width:100%;background:white}.wrap{max-width:1180px;margin:auto;padding:0 18px}.top{background:var(--navy);color:white}.nav{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:15px 0;flex-wrap:wrap}.brandlock{display:flex;align-items:center;gap:11px}.sv-logo{width:46px;height:46px;object-fit:contain;border-radius:10px;background:#08142b;box-shadow:0 2px 10px #0003;flex:0 0 auto}.brand{font-size:26px;font-weight:850}.brand span{color:#75b7ff}.switch{display:flex;gap:5px;background:#203652;padding:5px;border-radius:12px;flex-wrap:wrap}.switch button{color:#dbe7f7;background:transparent}.switch button.active{background:white;color:var(--navy)}.hero{background:linear-gradient(110deg,#10233f,#1c4b83);color:white;padding:34px 0}.hero h1{font-size:clamp(29px,4vw,44px);line-height:1.1;margin:12px 0}.hero p{color:#d7e7fa;max-width:670px}.search{display:flex;gap:8px;max-width:800px;flex-wrap:wrap}.search input{flex:1;min-width:180px}.hero-actions-wrap{background:var(--navy)}.hero-actions{display:flex;gap:8px;flex-wrap:wrap;margin:0;padding:14px 0 16px;border-top:1px solid #ffffff35}.hero-actions button{background:#ffffff16;color:white;border:1px solid #ffffff45}.hero-actions button.active,.hero-actions button:hover{background:white;color:var(--navy)}.layout{display:grid;grid-template-columns:235px 1fr;gap:18px;padding:24px 0 55px}.panel,.card{background:white;border:1px solid var(--line);border-radius:15px;padding:17px;box-shadow:0 4px 18px #17365d08}.results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.biz.spotlight{border:1px solid #78a9fa;background:linear-gradient(130deg,#fff,#f0f6ff)}.biz.plus{border:1px solid #bed8ff}.tag{display:inline-block;font-size:11px;font-weight:800;padding:4px 8px;border-radius:99px;background:#edf1f7;color:#4b5c73}.tag.plus{background:#e4f0ff;color:#1554b6}.tag.spotlight{background:#173b6c;color:white}.biz h3{margin:10px 0 3px}.muted{color:var(--muted)}.tiny{font-size:12px}.biz p{color:#5e6d82}.bizfoot{display:flex;gap:7px;flex-wrap:wrap}.catlist{display:grid;gap:4px;max-height:62vh;overflow-y:auto;overscroll-behavior:contain;padding-right:4px}.cat{background:transparent;color:#40516a;text-align:left;padding:8px}.cat.selected,.cat:hover{background:#eaf2ff;color:#164caa}.sectionhead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:22px 0 12px}.sectionhead h2{margin:0}.hidden{display:none!important}.formgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.full{grid-column:1/-1}.notice{background:#fff7e6;color:#805311;border-radius:9px;padding:12px;margin:12px 0}.good{background:#eaf7f0;color:#13714d}.bad{background:#fff0f0;color:#a32222}.pricegrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.price{border:1px solid var(--line);border-radius:12px;padding:13px}.price.featured{border:2px solid var(--blue);background:#f4f8ff}.amount{font-size:24px;font-weight:850}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.stat strong{display:block;font-size:26px}.tablewrap{overflow:auto}.table{border-collapse:collapse;width:100%;min-width:660px}.table td,.table th{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}.table th{font-size:12px;color:var(--muted)}.switchline{display:flex;gap:8px;flex-wrap:wrap;margin:15px 0}.footer{border-top:1px solid var(--line);padding:20px 0;color:var(--muted);font-size:12px}.pill{background:#eaf7f0;color:#13714d;padding:4px 8px;border-radius:20px;font-size:12px}.bottom-tabbar{position:fixed;z-index:5000;left:0;right:0;bottom:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:9px max(12px,env(safe-area-inset-left)) calc(9px + env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-right));background:#071426f5;border-top:1px solid #355477;box-shadow:0 -8px 24px #07142622}.bottom-tabbar button{min-width:0;min-height:62px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border:1px solid #355477;border-radius:13px;background:#172b45;color:#eaf1fb;padding:7px 4px;font-size:clamp(10px,2.8vw,13px);line-height:1.15}.bottom-tabbar button.active,.bottom-tabbar button:focus-visible{background:#087f8c;border-color:#42d3d0;color:white}.bottom-tab-icon{font-size:18px;line-height:1}.footer{padding-bottom:100px}.provider-open{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:14px}.provider-detail-contact{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.provider-detail-contact>*{flex:0 0 auto}.provider-detail-hero{border:1px solid #d5e3f5;background:linear-gradient(140deg,#fff,#f1f7ff);border-radius:18px;padding:clamp(18px,4vw,30px)}.provider-detail-hero h1{margin:12px 0 4px;font-size:clamp(26px,4vw,36px)}.biz[role=button]:focus-visible{outline:3px solid #70a6ff;outline-offset:3px}@media(max-width:480px){.bottom-tabbar{gap:6px;padding-left:8px;padding-right:8px}.bottom-tabbar button{min-height:58px;border-radius:11px}.provider-open{align-items:stretch;flex-direction:column}}
@media(max-width:800px){.layout{grid-template-columns:1fr}.results{grid-template-columns:1fr}.pricegrid{grid-template-columns:repeat(2,1fr)}.stats{grid-template-columns:repeat(2,1fr)}}@media(max-width:480px){.wrap{padding:0 12px}.formgrid{grid-template-columns:1fr}.full{grid-column:auto}.pricegrid{grid-template-columns:1fr}}
</style></head><body>
<div id="svSplash" class="sv-splash" role="status" aria-live="polite"><div class="sv-splash-brand">skill<span>vaya</span></div><div class="sv-splash-caption">Loading Skillvaya</div><div class="sv-loading-dots" aria-hidden="true"><i></i><i></i><i></i></div></div>
<header class="top"><div class="wrap nav"><div class="brandlock"><img class="sv-logo" src="/sv-logo.jpeg" alt="SV Skillvaya logo"><div><div class="brand">skill<span>vaya</span></div><div class="tiny" style="color:#cbd8e9">Good people. Great work. Near you.</div></div></div></div></header>
<section id="hero" class="hero"><div class="wrap"><span class="tag" style="background:#d9ebff;color:#174c91">FREE FOR CUSTOMERS</span><h1>Find the right people<br>to get the job done.</h1><p>Browse professionals by category and area, then contact providers free. Paid placements are labelled.</p><div class="search"><input id="q" placeholder="Search plumbers, lawyers, private doctors…"><input id="area" placeholder="Town or suburb"><button class="primary" onclick="loadBusinesses()">Search</button></div></div></section><div class="hero-actions-wrap"><div class="wrap"><div class="hero-actions" aria-label="Public directory"><button id="nav-customer" class="active" onclick="view('customer')">Find a service provider</button></div></div></div>
<main class="wrap">
<section id="customer" class="layout"><aside class="panel"><h3>All service categories</h3><div id="categories" class="catlist"><button class="cat selected" data-category="All categories">All categories</button><button class="cat" data-category="Builders &amp; construction">Builders &amp; construction</button><button class="cat" data-category="Plumbers">Plumbers</button><button class="cat" data-category="Electricians">Electricians</button><button class="cat" data-category="Painters &amp; decorators">Painters &amp; decorators</button><button class="cat" data-category="Mechanics &amp; automotive">Mechanics &amp; automotive</button><button class="cat" data-category="Cleaning &amp; housekeeping">Cleaning &amp; housekeeping</button><button class="cat" data-category="Gardening &amp; landscaping">Gardening &amp; landscaping</button><button class="cat" data-category="Roofing &amp; waterproofing">Roofing &amp; waterproofing</button><button class="cat" data-category="Carpenters &amp; furniture">Carpenters &amp; furniture</button><button class="cat" data-category="Welders &amp; fabricators">Welders &amp; fabricators</button><button class="cat" data-category="Appliance repairs">Appliance repairs</button><button class="cat" data-category="IT &amp; computer support">IT &amp; computer support</button><button class="cat" data-category="Graphic designers">Graphic designers</button><button class="cat" data-category="Artists &amp; photographers">Artists &amp; photographers</button><button class="cat" data-category="Marketing &amp; advertising">Marketing &amp; advertising</button><button class="cat" data-category="Web &amp; software developers">Web &amp; software developers</button><button class="cat" data-category="Lawyers &amp; legal services">Lawyers &amp; legal services</button><button class="cat" data-category="Private doctors &amp; clinics">Private doctors &amp; clinics</button><button class="cat" data-category="Dentists &amp; specialists">Dentists &amp; specialists</button><button class="cat" data-category="Nurses &amp; home care">Nurses &amp; home care</button><button class="cat" data-category="Accountants &amp; tax">Accountants &amp; tax</button><button class="cat" data-category="Financial &amp; insurance services">Financial &amp; insurance services</button><button class="cat" data-category="Real estate &amp; property">Real estate &amp; property</button><button class="cat" data-category="Tutors &amp; education">Tutors &amp; education</button><button class="cat" data-category="Beauty &amp; hair">Beauty &amp; hair</button><button class="cat" data-category="Catering &amp; chefs">Catering &amp; chefs</button><button class="cat" data-category="Transport &amp; removals">Transport &amp; removals</button><button class="cat" data-category="Security services">Security services</button><button class="cat" data-category="Events &amp; entertainment">Events &amp; entertainment</button><button class="cat" data-category="Tailors &amp; fashion">Tailors &amp; fashion</button><button class="cat" data-category="Pet care &amp; veterinary">Pet care &amp; veterinary</button><button class="cat" data-category="Funeral services">Funeral services</button><button class="cat" data-category="Engineering &amp; consulting">Engineering &amp; consulting</button><button class="cat" data-category="Other professional services">Other professional services</button><button class="cat" data-category="Doctors">Doctors</button><button class="cat" data-category="Nurses">Nurses</button><button class="cat" data-category="Mechanics">Mechanics</button><button class="cat" data-category="Gardeners">Gardeners</button><button class="cat" data-category="General practitioners (GPs)">General practitioners (GPs)</button><button class="cat" data-category="Medical specialists">Medical specialists</button><button class="cat" data-category="Dentists">Dentists</button><button class="cat" data-category="Dental hygienists">Dental hygienists</button><button class="cat" data-category="Physiotherapists">Physiotherapists</button><button class="cat" data-category="Psychologists &amp; counsellors">Psychologists &amp; counsellors</button><button class="cat" data-category="Optometrists">Optometrists</button><button class="cat" data-category="Pharmacists">Pharmacists</button><button class="cat" data-category="Veterinarians">Veterinarians</button><button class="cat" data-category="Home carers">Home carers</button><button class="cat" data-category="Elderly care">Elderly care</button><button class="cat" data-category="Childcare &amp; babysitters">Childcare &amp; babysitters</button><button class="cat" data-category="Midwives">Midwives</button><button class="cat" data-category="Auto electricians">Auto electricians</button><button class="cat" data-category="Tyre fitters">Tyre fitters</button><button class="cat" data-category="Panel beaters &amp; spray painters">Panel beaters &amp; spray painters</button><button class="cat" data-category="Car washers &amp; detailing">Car washers &amp; detailing</button><button class="cat" data-category="Motorcycle mechanics">Motorcycle mechanics</button><button class="cat" data-category="Truck &amp; diesel mechanics">Truck &amp; diesel mechanics</button><button class="cat" data-category="Landscapers">Landscapers</button><button class="cat" data-category="Pool maintenance">Pool maintenance</button><button class="cat" data-category="Pest control">Pest control</button><button class="cat" data-category="Tree services">Tree services</button><button class="cat" data-category="Bricklayers">Bricklayers</button><button class="cat" data-category="Plasterers">Plasterers</button><button class="cat" data-category="Tilers">Tilers</button><button class="cat" data-category="Flooring installers">Flooring installers</button><button class="cat" data-category="Glaziers &amp; window fitters">Glaziers &amp; window fitters</button><button class="cat" data-category="Locksmiths">Locksmiths</button><button class="cat" data-category="Solar installers">Solar installers</button><button class="cat" data-category="Air-conditioning &amp; refrigeration">Air-conditioning &amp; refrigeration</button><button class="cat" data-category="CCTV &amp; alarm installers">CCTV &amp; alarm installers</button><button class="cat" data-category="Handymen">Handymen</button><button class="cat" data-category="Quantity surveyors">Quantity surveyors</button><button class="cat" data-category="Architects">Architects</button><button class="cat" data-category="Domestic workers">Domestic workers</button><button class="cat" data-category="Laundry &amp; ironing">Laundry &amp; ironing</button><button class="cat" data-category="Carpet &amp; upholstery cleaning">Carpet &amp; upholstery cleaning</button><button class="cat" data-category="Office cleaning">Office cleaning</button><button class="cat" data-category="Waste removal">Waste removal</button><button class="cat" data-category="Computer repair">Computer repair</button><button class="cat" data-category="Mobile phone repair">Mobile phone repair</button><button class="cat" data-category="Network technicians">Network technicians</button><button class="cat" data-category="Cybersecurity services">Cybersecurity services</button><button class="cat" data-category="UX/UI designers">UX/UI designers</button><button class="cat" data-category="Video editors">Video editors</button><button class="cat" data-category="Videographers">Videographers</button><button class="cat" data-category="Translators &amp; interpreters">Translators &amp; interpreters</button><button class="cat" data-category="Writers &amp; editors">Writers &amp; editors</button><button class="cat" data-category="Consultants">Consultants</button><button class="cat" data-category="Human resources &amp; recruitment">Human resources &amp; recruitment</button><button class="cat" data-category="Bookkeepers">Bookkeepers</button><button class="cat" data-category="Auditors">Auditors</button><button class="cat" data-category="Mortgage brokers">Mortgage brokers</button><button class="cat" data-category="Financial advisers">Financial advisers</button><button class="cat" data-category="Insurance brokers">Insurance brokers</button><button class="cat" data-category="Estate agents">Estate agents</button><button class="cat" data-category="Property managers">Property managers</button><button class="cat" data-category="Teachers">Teachers</button><button class="cat" data-category="Exam tutors">Exam tutors</button><button class="cat" data-category="Music teachers">Music teachers</button><button class="cat" data-category="Driving instructors">Driving instructors</button><button class="cat" data-category="Training &amp; coaching">Training &amp; coaching</button><button class="cat" data-category="Barbers">Barbers</button><button class="cat" data-category="Hairdressers">Hairdressers</button><button class="cat" data-category="Nail technicians">Nail technicians</button><button class="cat" data-category="Make-up artists">Make-up artists</button><button class="cat" data-category="Beauty therapists">Beauty therapists</button><button class="cat" data-category="Massage therapists">Massage therapists</button><button class="cat" data-category="Personal trainers">Personal trainers</button><button class="cat" data-category="Nutritionists">Nutritionists</button><button class="cat" data-category="Chefs &amp; private cooks">Chefs &amp; private cooks</button><button class="cat" data-category="Bakers">Bakers</button><button class="cat" data-category="Food vendors">Food vendors</button><button class="cat" data-category="Event planners">Event planners</button><button class="cat" data-category="DJs &amp; sound technicians">DJs &amp; sound technicians</button><button class="cat" data-category="Musicians">Musicians</button><button class="cat" data-category="MCs &amp; entertainers">MCs &amp; entertainers</button><button class="cat" data-category="Florists">Florists</button><button class="cat" data-category="Wedding services">Wedding services</button><button class="cat" data-category="Fashion designers">Fashion designers</button><button class="cat" data-category="Sewing &amp; alterations">Sewing &amp; alterations</button><button class="cat" data-category="Upholstery">Upholstery</button><button class="cat" data-category="Delivery drivers">Delivery drivers</button><button class="cat" data-category="Moving &amp; removals">Moving &amp; removals</button><button class="cat" data-category="Taxi &amp; shuttle services">Taxi &amp; shuttle services</button><button class="cat" data-category="Tour guides">Tour guides</button><button class="cat" data-category="Courier services">Courier services</button><button class="cat" data-category="Security guards">Security guards</button><button class="cat" data-category="Private investigators">Private investigators</button><button class="cat" data-category="Fire safety services">Fire safety services</button><button class="cat" data-category="Funeral directors">Funeral directors</button><button class="cat" data-category="Cremation services">Cremation services</button><button class="cat" data-category="Civil engineers">Civil engineers</button><button class="cat" data-category="Electrical engineers">Electrical engineers</button><button class="cat" data-category="Mechanical engineers">Mechanical engineers</button><button class="cat" data-category="Environmental consultants">Environmental consultants</button><button class="cat" data-category="Surveyors">Surveyors</button><button class="cat" data-category="Interior designers">Interior designers</button><button class="cat" data-category="Signage &amp; printing">Signage &amp; printing</button><button class="cat" data-category="Craftspeople">Craftspeople</button><button class="cat" data-category="Pet groomers">Pet groomers</button><button class="cat" data-category="Dog walkers">Dog walkers</button><button class="cat" data-category="Animal trainers">Animal trainers</button></div></aside><section><div class="sectionhead"><div><h2 id="resTitle">Find a service</h2><span class="muted tiny" id="count"></span></div><select id="sort" style="max-width:180px" onchange="loadBusinesses()"><option value="featured">Featured first</option><option value="rating">Highest rated</option><option value="name">Name A–Z</option></select></div><div id="results" class="results"></div><div class="card" id="platformRatingCard" style="margin-top:18px;border:1px solid #d7e5f7;background:linear-gradient(135deg,#fff,#f1f7ff)"><h2 style="margin:0 0 4px">Rate Skillvaya</h2><p class="muted" style="margin:0 0 8px">Tell us how we're doing. Your rating is for the Skillvaya website and service, not an individual provider.</p><div id="platformRatingSummary" class="muted tiny">Loading Skillvaya ratings…</div><div id="platformRatingStars" aria-label="Rate Skillvaya from one to five stars" style="display:flex;gap:4px;flex-wrap:wrap;margin-top:6px"></div><div id="platformRatingMsg" class="muted tiny" aria-live="polite"></div></div></section></section>
<section id="providerDetailScreen" class="hidden" style="padding:20px 0 110px;max-width:900px;margin:auto"><button type="button" class="ghost" onclick="closeProviderDetail()">&#8592; Back to service providers</button><div id="providerDetailContent" style="margin-top:14px"></div></section>
<section id="categoryScreen" class="category-screen hidden"><div class="category-screen-head"><button type="button" class="category-back" onclick="backToCategories()">← Back to all service providers</button><div><h2 id="categoryScreenTitle" style="margin:0">Service providers</h2><span class="muted tiny" id="categoryScreenCount"></span></div><select id="categoryScreenSort" style="max-width:180px;margin-left:auto" onchange="document.getElementById('sort').value=this.value;loadBusinesses()"><option value="featured">Featured first</option><option value="rating">Highest rated</option><option value="name">Name A–Z</option></select></div><div id="categoryScreenResults" class="category-results"></div></section>
<section id="providerDetailScreen" class="hidden" style="padding:20px 0 110px;max-width:900px;margin:auto"><button type="button" class="ghost" onclick="closeProviderDetail()">← Back to service providers</button><div id="providerDetailContent" style="margin-top:14px"></div></section>
<section id="provider" class="hidden" style="padding:25px 0 110px"><div class="sectionhead"><div><h2>Provider studio</h2><p class="muted">Create your business profile and request an advertising plan.</p></div></div><div class="layout" style="padding-top:0"><div id="providerProfileCard" class="card hidden"><h3>Business profile</h3><p class="muted">Complete this after Skillvaya verifies your plan payment.</p><form id="bizForm"><div class="formgrid"><div><label>Business / professional name *</label><input name="name" required></div><div><label>Category *</label><select name="category" id="bizCat"></select></div><div><label>Town / service area *</label><input name="area" required></div><div><label>Business phone *</label><input name="phone" type="tel" required></div><div><label>WhatsApp number</label><input name="whatsapp" type="tel" placeholder="+27…"></div><div><label>Public contact email</label><input name="email" type="email"></div><div><label>Website</label><input name="website" type="url" placeholder="https://…"></div><div class="full"><label>Services description *</label><textarea name="description" required rows="4"></textarea></div><div class="full"><label>Portfolio photos / catalogue images</label><input id="providerPortfolioFiles" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" multiple><small class="muted">Choose photos or a PDF catalogue from your phone, tablet or computer. Maximum 2 MB combined. Files are saved with your provider profile.</small><div id="providerPortfolioPreview" class="photo-file-name" aria-live="polite">No files selected</div><input name="photos" id="providerPhotosData" type="hidden"></div></div><p><button class="primary">Save business profile</button></p></form><div id="bizMsg"></div><div id="providerProfileNotice" class="notice">Choose a plan and complete payment first. Business profile setup unlocks after Skillvaya verifies the payment.</div></div><div class="card" id="providerPlansCard"><h3>Advertising plans</h3><label>Billing term</label><select id="billing" onchange="drawPlans()"><option value="monthly">Monthly</option><option value="yearly">Yearly — one month free</option></select><div id="plans"></div><p class="muted tiny">Selecting a plan creates a payment request. Automatic activation occurs only after verified payment; gateway connection is not configured yet.</p></div></div></section>
<section id="account" class="hidden"></section>
<section id="settings" class="hidden" style="padding:25px 0 55px;max-width:920px;margin:auto">
 <div class="card" style="border-radius:20px;padding:clamp(16px,4vw,30px);box-shadow:0 12px 35px #142b4510">
  <div style="display:flex;align-items:center;gap:14px;margin-bottom:18px"><div style="width:54px;height:54px;border-radius:16px;background:#e6f0ff;display:grid;place-items:center;font-size:27px">👤</div><div><h2 style="margin:0">Your Profile</h2><p class="muted" style="margin:4px 0 0">Your details, photo and messages — all in one place.</p></div></div>
  <div id="profileAuthTabs" style="display:flex;gap:10px;margin:18px 0;flex-wrap:wrap"><button id="profileSigninTab" class="primary" type="button" onclick="profileAuthMode('signin')">Sign in</button><button id="profileSignupTab" class="ghost" type="button" onclick="profileAuthMode('signup')">Create profile</button></div>
  <div id="signinPane"><form id="login"><label>Email</label><input name="email" type="email" autocomplete="username" required><label>Password</label><input name="password" type="password" autocomplete="current-password" required><p><label style="display:flex;gap:9px;align-items:flex-start;font-weight:500"><input id="rememberMe" type="checkbox" checked style="width:auto;margin-top:5px;flex:0 0 auto"><span>Remember me on this device — stay signed in until I log out.</span></label></p><p><label style="display:flex;gap:9px;align-items:flex-start;font-weight:500"><input id="loginTerms" name="accept_terms" type="checkbox" required style="width:auto;margin-top:5px;flex:0 0 auto"><span>I have read and agree to the current <a href="/terms" target="_blank" rel="noopener">Skillvaya Terms, Conditions, Rules & Safety</a>.</span></label></p><button class="primary">Sign in securely</button></form><div id="loginMsg" aria-live="polite"></div></div>
  <div id="signupPane" class="hidden"><form id="signup"><label>Your name</label><input name="name" autocomplete="name" required><label>Email</label><input name="email" type="email" autocomplete="email" required><label>Phone / WhatsApp (optional)</label><input name="phone" type="tel" autocomplete="tel"><label>Password (minimum 8 characters)</label><input name="password" type="password" autocomplete="new-password" minlength="8" required><label>Account type</label><select name="role"><option value="customer">Customer — free</option><option value="provider">Service provider</option></select><p class="muted">You can update your picture and personal details after creating your profile.</p><p><label style="display:flex;gap:10px;align-items:flex-start;font-weight:500"><input name="accept_terms" type="checkbox" required style="width:auto;margin-top:5px;flex:0 0 auto"><span>I have read and agree to the <a href="/terms" target="_blank" rel="noopener">Skillvaya Terms, Conditions, Rules & Safety</a>.</span></label></p><button class="primary">Create my profile</button></form><div id="signupMsg" aria-live="polite"></div></div>
  <div id="profileSettingsCard" class="hidden">
   <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:16px 0"><img id="profilePhotoPreview" alt="Your profile picture" style="width:94px;height:94px;border-radius:50%;object-fit:cover;background:#e9eff7;border:3px solid white;box-shadow:0 0 0 1px #ccd7e5" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='50' fill='%23e5edf7'/%3E%3Ccircle cx='50' cy='37' r='18' fill='%238aa0bc'/%3E%3Cpath d='M15 95c2-23 17-34 35-34s33 11 35 34' fill='%238aa0bc'/%3E%3C/svg%3E"><div><h3 style="margin:0">Your picture</h3><p class="muted" style="margin:5px 0">Choose a JPG, PNG or WebP image (up to 2 MB).</p><div class="photo-picker"><span class="photo-pick-wrap"><input id="profilePhotoFile" class="photo-input-native" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Choose a profile picture"><span class="photo-pick-button" aria-hidden="true"><span>＋</span> Choose profile picture</span></span><span id="profilePhotoFileName" class="photo-file-name">Tap Choose profile picture to select an image from your device</span><button id="saveProfilePhotoButton" type="button" class="primary" onclick="saveProfilePhoto()">Upload picture</button></div><div id="photoMsg" aria-live="polite"></div></div></div>
   <h3>Personal details</h3><p id="profileIdentity" class="muted">Your account details</p><form id="profileForm"><label>Full name</label><input name="name" autocomplete="name" required minlength="2" maxlength="120"><label>Phone</label><input name="phone" type="tel" autocomplete="tel" maxlength="40"><p><button class="primary">Save profile</button></p></form><div id="profileMsg" aria-live="polite"></div>
   <h3>Password & security</h3><p class="muted">Your password is stored as a secure hash, not readable text.</p><form id="passwordForm"><label>Current password</label><input name="current_password" type="password" autocomplete="current-password" required><label>New password (at least 8 characters)</label><input name="new_password" type="password" autocomplete="new-password" minlength="8" required><label>Confirm new password</label><input name="confirm_password" type="password" autocomplete="new-password" minlength="8" required><p><button class="primary">Change password</button></p></form><div id="passwordMsg" aria-live="polite"></div>
   <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:20px"><button class="secondary" type="button" onclick="viewMessages()">My messages</button><button class="danger" type="button" onclick="logout()">Log out</button></div>
  </div>
 </div>
 <div id="messagesCard" class="card hidden" style="border-radius:18px"><h2>My messages</h2><p class="muted">Private enquiries between customers and service providers.</p><div id="messagesList">Loading messages…</div><div id="messagesStatus" aria-live="polite"></div></div>
</section>
<section id="terms" class="hidden" style="padding:25px 0 55px"><div class="card"><h2>Terms, conditions, rules & safety</h2><p class="muted">Version 1.2 · Effective 21 October 2026. The full current text is also available at <a href="/terms" target="_blank" rel="noopener">Skillvaya Terms & Conditions</a>.</p><div class="notice">By ticking the required agreement box to create an account or sign in, you agree to this current version. Customer browsing/contact is free unless a charge is clearly disclosed before you approve it.</div><h3>1. Agreement and accounts</h3><p>Provide accurate details, protect your login and accept the current terms before creating an account or signing in. Your accepted version and timestamp are recorded.</p><h3>2. Customers and providers</h3><p>Skillvaya is a directory and introduction service; paid placement is not an endorsement. Customers should independently check provider credentials and quotations. Providers must be lawful, honest and suitably qualified for advertised work. Fraud, harassment, misleading listings, unsafe services, unlawful content, privacy abuse and manipulation of ratings, reports or payments are prohibited.</p><h3>3. Paid plans, price changes and taxes</h3><p>Plan, features, billing term, full amount, tax/fees, renewal dates and cancellation terms must be displayed before purchase. Skillvaya may change plan prices in the future. A price change will not retrospectively increase a term already paid for or change its price mid-term. Where legally required, and as a general service commitment, material increases will be communicated in advance—normally at least 30 days before applying to a future renewal—with the new amount and date. You may cancel or not renew before it takes effect. The new price must be displayed before a new purchase or renewal is approved; silence does not authorise an undisclosed charge. Applicable law prevails.</p><h3>4. Payment, renewal and refund</h3><p>PayPal is the only enabled checkout provider for this release; PayFast is paused. Skillvaya is working towards offering additional payment services in future, but they will not be available until integration, testing, and any required approvals are complete. Sandbox transactions are tests, not real payments. A plan activates only when PayPal confirms a completed payment matching order reference, currency and amount. Unless the checkout clearly states otherwise and you expressly authorise recurring billing, renewals are not automatic. Refunds are subject to checkout disclosures and applicable law; a refund is recorded as completed only on provider confirmation.</p><h3>5. Privacy, moderation and service limits</h3><p>Account, listing, enquiry, complaint, payment-status and technical information may be used to operate the service, protect users and support payment reconciliation. Reasonable safeguards are used, but no service is perfectly secure. Reports are allegations, not findings of guilt. Skillvaya may moderate listings or restrict unsafe or unlawful activity. Nothing excludes rights or remedies that applicable South African law does not allow to be excluded.</p><h3>6. Contact and review</h3><p>Contact <a href="mailto:skillvaya@gmail.com">skillvaya@gmail.com</a> for billing, safety or privacy concerns. This is a working business draft, not legal advice; obtain South African legal review before accepting real customer payments.</p><p><a href="/terms" target="_blank" rel="noopener">Read the full Terms & Conditions (opens separately)</a></p>
</div></section>
<section id="admin" class="hidden" style="padding:25px 0 55px"><div class="sectionhead"><div><h2>Owner control centre</h2><p class="muted">Secure sign-in as owner is required to manage complaints and payments.</p></div></div><div id="adminMsg" class="notice">Sign in using the configured owner account. Default passwords must never be used in production.</div><div id="adminData" class="hidden"><div class="stats"><div class="card"><span class="tiny muted">BUSINESSES</span><strong id="sBiz">0</strong></div><div class="card"><span class="tiny muted">OPEN COMPLAINTS</span><strong id="sComplaints">0</strong></div><div class="card"><span class="tiny muted">PAYMENT REQUESTS</span><strong id="sPayments">0</strong></div><div class="card"><span class="tiny muted">PENDING LISTINGS</span><strong id="sPending">0</strong></div></div><div class="switchline"><button class="ghost" onclick="adminTab('complaints')">Reports & complaints</button><button class="ghost" onclick="adminTab('businesses')">Listings</button><button class="ghost" onclick="adminTab('payments')">Payments</button><button class="ghost" onclick="adminTab('clients')">Client accounts</button><button class="ghost" onclick="emailClientByAddress()">Email / warn a client</button><button class="ghost" onclick="adminTab('analytics')">Downloads & usage</button><button class="ghost" onclick="adminTab('notifications')">Alerts</button><button class="ghost" onclick="adminTab('settings')">Email settings</button></div><div id="adminTable" class="card"></div></div></section>
<section id="owner-promotions-public" class="wrap" style="padding:20px 0"><h2>Skillvaya owner businesses & apps</h2><div id="owner-promotions-public-list" class="results"><p class="muted">Loading owner promotions…</p></div></section><script>(async()=>{try{let r=await fetch('/api/owner-promotions');if(!r.ok)return;let d=await r.json();let root=document.getElementById('owner-promotions-public-list');root.innerHTML=(d.items||[]).map(x=>'<article class="card biz"><span class="tag">Owner '+String(x.kind).replace(/[&<>]/g,'')+'</span><h3>'+String(x.title).replace(/[&<>]/g,'')+'</h3><div class="muted tiny">'+String(x.business_name).replace(/[&<>]/g,'')+' · '+String(x.category).replace(/[&<>]/g,'')+'</div><p>'+String(x.description).replace(/[&<>]/g,'')+'</p>'+(x.image_url?'<img loading="lazy" alt="" style="max-width:100%;max-height:220px;object-fit:contain" src="'+String(x.image_url).replace(/"/g,'&quot;')+'">':'')+(x.target_url?'<p><a rel="noopener noreferrer" target="_blank" href="'+String(x.target_url).replace(/"/g,'&quot;')+'">Visit website / download app</a></p>':'')+'</article>').join('')||'<p class="muted">No owner promotions published yet.</p>'}catch(e){console.warn(e)}})();</script></main><nav class="bottom-tabbar" aria-label="Provider and account sections"><button id="nav-provider" type="button" onclick="view('provider')"><span class="bottom-tab-icon">▦</span><span>Provider Studio</span></button><button id="nav-settings" type="button" onclick="view('settings')"><span class="bottom-tab-icon">●</span><span>Profile</span></button><button id="nav-terms" type="button" onclick="view('terms')"><span class="bottom-tab-icon">§</span><span>Terms, Rules & Safety</span></button></nav><footer class="footer"><div class="wrap">Skillvaya local application · Customer search is free · Paid advertising is labelled · <span>skillvaya@gmail.com</span> · Manage email in Owner Control · Complaint reports are allegations requiring fair investigation.</div></footer>
<script>
let cats=[],chosen='All categories',token=localStorage.getItem('skillvaya_token')||localStorage.getItem('sv_token')||sessionStorage.getItem('skillvaya_token')||sessionStorage.getItem('sv_token')||'',me=null,allBusinesses=[];
const planInfo=[['local','Local',105,'Business profile, category listing, customer enquiries'],['priority','Priority',210,'Higher category placement and priority badge'],['plus','Business Plus',500,'Blue profile, featured category section, portfolio, basic insights'],['spotlight','Business Spotlight',1000,'Plus features, homepage rotation, enhanced portfolio, analytics, priority support']];
function view(v){if(v==='admin'){location.href='/owner-app';return}const profileView=v==='settings';['customer','provider','account','settings','terms','admin','providerDetailScreen'].forEach(x=>{const el=document.getElementById(x);if(el)el.classList.toggle('hidden',x!==v)});document.querySelectorAll('.bottom-tabbar button').forEach(n=>n.classList.toggle('active',profileView?n.id==='nav-settings':n.id==='nav-'+v));const categoryScreen=document.getElementById('categoryScreen');if(categoryScreen)categoryScreen.classList.add('hidden');const ownerPublic=document.getElementById('owner-promotions-public');if(ownerPublic)ownerPublic.classList.toggle('hidden',v!=='customer');document.getElementById('hero').classList.toggle('hidden',v!=='customer');const customerNav=document.getElementById('nav-customer');if(customerNav)customerNav.classList.toggle('active',v==='customer');if(profileView){sessionInfo()}if(v==='provider')refreshProviderGate();window.scrollTo(0,0)}
function profileAuthMode(mode){const signed=!!me;document.getElementById('profileAuthTabs').classList.toggle('hidden',signed);document.getElementById('signinPane').classList.toggle('hidden',signed||mode!=='signin');document.getElementById('signupPane').classList.toggle('hidden',signed||mode!=='signup');document.getElementById('profileSigninTab').className=mode==='signin'?'primary':'ghost';document.getElementById('profileSignupTab').className=mode==='signup'?'primary':'ghost';document.getElementById('profileSettingsCard').classList.toggle('hidden',!signed)}

async function api(path,opts={}){opts.headers={...(opts.headers||{}),'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})};const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),12000);let r;try{r=await fetch(path,{...opts,signal:controller.signal})}catch(e){if(e.name==='AbortError')throw Error('The server took too long to respond. Please try again.');throw e}finally{clearTimeout(timer)}let j=await r.json().catch(()=>({error:'Invalid server response'}));if(!r.ok)throw Error(j.error||'Request failed');return j}
function msg(id,text,good=false){let el=document.getElementById(id);el.className='notice '+(good?'good':'bad');el.textContent=text}
async function init(){
  try{
    // Authentication, categories and provider listings are independent initial requests.
    // Run them together so database latency doesn't stack up behind the loading screen.
    const [_,d]=await Promise.all([sessionInfo(),api('/api/categories'),loadBusinesses()]);
    if(me&&me.role==='admin'){
      document.body.insertAdjacentHTML('afterbegin','<div id="ownerEditionBar" style="position:sticky;top:0;z-index:999;background:#0b766e;color:white;padding:10px 14px;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap"><strong>SKILLVAYA OWNER EDITION — ALL FEATURES UNLOCKED FREE</strong><a href="/owner-app" style="color:white;font-weight:700">← Back to Owner / Controller</a></div>');
    }
    cats=d.categories;
    document.getElementById('categories').innerHTML='<button class="cat selected" data-category="All categories">All categories</button>'+cats.map(c=>'<button class="cat" data-category="'+esc(c)+'">'+esc(c)+'</button>').join('');
    document.getElementById('bizCat').innerHTML=cats.map(c=>'<option>'+esc(c)+'</option>').join('');
    drawPlans();refreshProviderGate().catch(e=>console.warn('Provider status unavailable during startup:',e));loadPlatformRating();
  }catch(e){console.warn('Skillvaya startup failed; saved session data has not been cleared unless the server rejected it:',e.message);}
}
function pickCat(c){chosen=c;document.querySelectorAll('.cat').forEach(x=>x.classList.toggle('selected',x.textContent===c));if(c==='All categories'){backToCategories();return}document.getElementById('customer').classList.add('hidden');document.getElementById('categoryScreen').classList.remove('hidden');document.getElementById('categoryScreenTitle').textContent=c;document.getElementById('categoryScreenCount').textContent='Loading service providers…';document.getElementById('categoryScreenSort').value=document.getElementById('sort').value;loadBusinesses()}
document.getElementById('categories').addEventListener('click',e=>{const b=e.target.closest('button[data-category]');if(b)pickCat(b.dataset.category)});
function backToCategories(){chosen='All categories';document.getElementById('categoryScreen').classList.add('hidden');document.getElementById('customer').classList.remove('hidden');document.getElementById('hero').classList.remove('hidden');document.getElementById('nav-customer').classList.add('active');document.getElementById('categoryScreenTitle').textContent='Service providers';document.querySelectorAll('.cat').forEach(x=>x.classList.toggle('selected',x.textContent==='All categories'));window.scrollTo(0,0);loadBusinesses()}
async function loadBusinesses(){try{let p=new URLSearchParams({q:document.getElementById('q').value,area:document.getElementById('area').value,category:chosen,sort:document.getElementById('sort').value});let d=await api('/api/businesses?'+p);allBusinesses=d.businesses;const categoryMode=!document.getElementById('categoryScreen').classList.contains('hidden');document.getElementById(categoryMode?'categoryScreenCount':'count').textContent=d.businesses.length+' matching businesses · contact for free';document.getElementById('categoryScreenTitle').textContent=chosen==='All categories'?'Service providers':chosen;document.getElementById('resTitle').textContent=chosen==='All categories'?'Providers you can contact':chosen;const markup=d.businesses.map(b=>'<article class="card biz '+b.plan+'" role="button" tabindex="0" aria-label="Open '+esc(b.name)+' provider profile" onclick="openProvider('+Number(b.id)+')" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();openProvider('+Number(b.id)+')}"><span class="tag '+(b.plan==='plus'?'plus':b.plan==='spotlight'?'spotlight':'')+'">'+(b.plan==='local'?'Local listing':b.plan==='priority'?'Priority · Sponsored':b.plan==='plus'?'Business Plus · Sponsored':'Spotlight · Sponsored')+'</span><h3>'+esc(b.name)+'</h3><div class="muted tiny">'+esc(b.category)+' · '+esc(b.area)+'</div><p>'+esc(b.description)+'</p>'+ratingMarkup(b.id,b.rating,b.rating_count,b.my_rating)+'<div class="provider-open"><span class="muted tiny">View details and contact options</span><button class="primary" type="button" onclick="event.stopPropagation();openProvider('+Number(b.id)+')">View provider</button></div></article>').join('')||'<div class="card"><h3>No active providers listed in this category yet</h3><p class="muted">The service categories remain available to the public. Please check back as providers publish their listings.</p><button type="button" class="ghost" onclick="backToCategories()">Browse all service categories</button></div>';document.getElementById(categoryMode?'categoryScreenResults':'results').innerHTML=markup;document.getElementById('results').setAttribute('aria-label','Public service provider directory');}catch(e){console.error(e)}}
function openProvider(id){const b=allBusinesses.find(x=>Number(x.id)===Number(id));if(!b)return;const contact=['<button type="button" class="primary" onclick="contact('+Number(b.id)+')">Message in Skillvaya</button>'];if(b.whatsapp)contact.push('<a class="ghost" style="display:inline-block;padding:10px 12px;border-radius:8px;text-decoration:none" target="_blank" rel="noopener noreferrer" href="https://wa.me/'+esc(String(b.whatsapp).replace(/\D/g,''))+'">WhatsApp</a>');if(b.email)contact.push('<a class="ghost" style="display:inline-block;padding:10px 12px;border-radius:8px;text-decoration:none" href="mailto:'+esc(b.email)+'">Email provider</a>');if(b.website&&/^https?:\/\//i.test(b.website))contact.push('<a class="ghost" style="display:inline-block;padding:10px 12px;border-radius:8px;text-decoration:none" target="_blank" rel="noopener noreferrer" href="'+esc(b.website)+'">Visit website</a>');contact.push('<button class="ghost" type="button" onclick="report('+Number(b.id)+')">Report business</button>');document.getElementById('providerDetailContent').innerHTML='<article class="provider-detail-hero"><span class="tag '+(b.plan==='plus'?'plus':b.plan==='spotlight'?'spotlight':'')+'">'+(b.plan==='local'?'Local listing':b.plan==='priority'?'Priority · Sponsored':b.plan==='plus'?'Business Plus · Sponsored':'Spotlight · Sponsored')+'</span><h1>'+esc(b.name)+'</h1><p class="muted">'+esc(b.category)+' · '+esc(b.area)+'</p><p>'+esc(b.description)+'</p>'+ratingMarkup(b.id,b.rating,b.rating_count,b.my_rating)+'<h3 style="margin-top:22px">Contact this service provider</h3><p class="muted">Choose how you would like to get in touch. Customer directory browsing is free.</p><div class="provider-detail-contact">'+contact.join('')+'</div></article>';['customer','provider','account','settings','terms','admin','categoryScreen'].forEach(x=>{const el=document.getElementById(x);if(el)el.classList.add('hidden')});document.getElementById('providerDetailScreen').classList.remove('hidden');document.getElementById('hero').classList.add('hidden');const ownerPublic=document.getElementById('owner-promotions-public');if(ownerPublic)ownerPublic.classList.add('hidden');document.querySelectorAll('.bottom-tabbar button').forEach(x=>x.classList.remove('active'));window.scrollTo(0,0)}
function closeProviderDetail(){document.getElementById('providerDetailScreen').classList.add('hidden');if(chosen&&chosen!=='All categories'){document.getElementById('categoryScreen').classList.remove('hidden')}else{document.getElementById('customer').classList.remove('hidden');document.getElementById('hero').classList.remove('hidden');const ownerPublic=document.getElementById('owner-promotions-public');if(ownerPublic)ownerPublic.classList.remove('hidden');const n=document.getElementById('nav-customer');if(n)n.classList.add('active')}window.scrollTo(0,0)}
function portfolioMarkup(raw){if(!raw)return '';let items=[];try{const v=JSON.parse(raw);if(Array.isArray(v))items=v}catch(e){if(/^https?:\/\//i.test(raw))return '<p><a href="'+esc(raw)+'" target="_blank" rel="noopener">View portfolio</a></p>'}if(!items.length)return '';return '<div>'+items.map(x=>x&&x.type==='application/pdf'?'<p><a href="'+x.data+'" download="'+esc(x.name)+'">Download catalogue: '+esc(x.name)+'</a></p>':x&&x.data&&x.data.indexOf('data:image/')===0?'<img loading="lazy" alt="'+esc(x.name||'Portfolio photo')+'" style="max-width:100%;max-height:220px;object-fit:contain;border-radius:10px;margin:6px" src="'+x.data+'">':'').join('')+'</div>'}
function ratingMarkup(id,average,count,mine){const chosen=Number(mine)||0;const avg=Number(average)||0;return '<div class="ratingbox"><div class="muted tiny">Customer rating: <strong>'+(count?avg.toFixed(1):'Not rated yet')+'</strong> ('+(Number(count)||0)+' rating'+(Number(count)===1?'':'s')+')</div><div aria-label="Rate this service provider from 1 to 5 stars">'+[1,2,3,4,5].map(n=>'<button type="button" class="starbtn" aria-label="Rate '+n+' out of 5 stars" title="Rate '+n+' stars" onclick="event.stopPropagation();rateProvider('+Number(id)+','+n+')" style="background:transparent;border:0;padding:2px 5px;font-size:1.5rem;line-height:1.3;cursor:pointer;color:'+(n<=(chosen||Math.round(avg))?'#e6a400':'#9aa7b5')+'">★</button>').join('')+'</div></div>'}
async function rateProvider(id,stars){if(!me){view('settings');profileAuthMode('signin');alert('Sign in with a free customer account to rate this provider.');return}if(me.role!=='customer'){alert('Provider ratings are available from a customer account.');return}try{await api('/api/ratings',{method:'POST',body:JSON.stringify({target_type:'provider',business_id:id,stars})});await loadBusinesses();alert('Your '+stars+'-star rating has been saved. You can change it any time.')}catch(e){alert(e.message)}}
async function rateCustomer(businessId,customerId,stars){if(!me||me.role!=='provider'){alert('Sign in with your service-provider account to rate a customer.');return}try{await api('/api/ratings',{method:'POST',body:JSON.stringify({target_type:'customer',business_id:businessId,customer_id:customerId,stars})});alert('Your '+stars+'-star customer rating has been saved. You can update it any time.')}catch(e){alert(e.message)}}
async function loadPlatformRating(){try{const d=await api('/api/platform-rating');const summary=document.getElementById('platformRatingSummary');if(!summary)return;summary.textContent=(d.count?('Skillvaya rating: '+Number(d.average).toFixed(1)+' / 5 from '+d.count+' rating'+(d.count===1?'':'s')):'No ratings yet — be the first to rate Skillvaya.');const root=document.getElementById('platformRatingStars');root.innerHTML=[1,2,3,4,5].map(n=>'<button type="button" aria-label="Rate Skillvaya '+n+' out of 5 stars" title="Rate Skillvaya '+n+' stars" onclick="submitPlatformRating('+n+')" style="background:transparent;border:0;padding:2px 5px;font-size:1.7rem;line-height:1.3;cursor:pointer;color:'+(n<=(Number(d.my_rating)||0)?'#e6a400':'#9aa7b5')+'">★</button>').join('')}catch(e){const s=document.getElementById('platformRatingSummary');if(s)s.textContent='Skillvaya ratings are temporarily unavailable.'}}
async function submitPlatformRating(stars){if(!me){view('settings');profileAuthMode('signin');document.getElementById('platformRatingMsg').textContent='Please sign in or create a free account to rate Skillvaya.';return}try{const d=await api('/api/platform-rating',{method:'POST',body:JSON.stringify({stars})});document.getElementById('platformRatingMsg').textContent='Thank you — your '+stars+'-star rating has been saved. You can change it any time.';await loadPlatformRating()}catch(e){document.getElementById('platformRatingMsg').textContent=e.message}}
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function contact(id){if(!me){view('settings');profileAuthMode('signin');alert('Please sign in or create a free customer profile to message this provider.');return}const b=allBusinesses.find(x=>Number(x.id)===Number(id));const message=prompt('Message '+(b?b.name:'this provider')+':');if(!message)return;try{await api('/api/messages/send',{method:'POST',body:JSON.stringify({business_id:id,message})});alert('Your private in-app message has been sent. You can follow replies in Profile → My messages.')}catch(e){alert(e.message)}}
async function report(id){if(!me){view('settings');profileAuthMode('signin');alert('Please create a free profile or sign in to report a business.');return}let reason=prompt('Describe the concern. Reports are investigated fairly; allegations are not treated as proven facts.');if(!reason)return;try{await api('/api/complaints',{method:'POST',body:JSON.stringify({business_id:id,reason})});alert('Report submitted to the safety review queue.')}catch(e){alert(e.message)}}
document.getElementById('signup').onsubmit=async e=>{e.preventDefault();try{let fd=new FormData(e.target);let data=Object.fromEntries(fd);data.accept_terms=document.querySelector('#signup input[name="accept_terms"]').checked;let d=await api('/api/signup',{method:'POST',body:JSON.stringify(data)});token=d.token;localStorage.setItem('sv_token',token);localStorage.setItem('skillvaya_token',token);sessionStorage.removeItem('sv_token');sessionStorage.removeItem('skillvaya_token');msg('signupMsg','Profile created. Welcome, '+d.user.name+'.',true);view('settings');await sessionInfo()}catch(x){msg('signupMsg',x.message)}};
document.getElementById('login').onsubmit=async e=>{e.preventDefault();try{let data=Object.fromEntries(new FormData(e.target));data.accept_terms=document.getElementById('loginTerms').checked;let d=await api('/api/login',{method:'POST',body:JSON.stringify(data)});token=d.token;me=d.user;localStorage.removeItem('sv_token');localStorage.removeItem('skillvaya_token');sessionStorage.removeItem('sv_token');sessionStorage.removeItem('skillvaya_token');if(document.getElementById('rememberMe').checked){localStorage.setItem('sv_token',token);localStorage.setItem('skillvaya_token',token)}else{sessionStorage.setItem('sv_token',token);sessionStorage.setItem('skillvaya_token',token)}msg('loginMsg','Signed in successfully.',true);view('settings');await sessionInfo();if(me.role==='provider')refreshProviderGate();if(me.role==='admin')view('admin')}catch(x){msg('loginMsg',x.message)}};
async function sessionInfo(){try{let d=await api('/api/me');me=d.user;document.getElementById('profileSettingsCard').classList.remove('hidden');document.getElementById('profileAuthTabs').classList.add('hidden');document.getElementById('signinPane').classList.add('hidden');document.getElementById('signupPane').classList.add('hidden');if(document.getElementById('profileForm')){document.getElementById('profileForm').elements.name.value=me.name||'';document.getElementById('profileForm').elements.phone.value=me.phone||'';document.getElementById('profileIdentity').textContent=me.email+' · '+me.role;document.getElementById('profilePhotoPreview').src=me.profile_photo||document.getElementById('profilePhotoPreview').src}return me}catch(e){if(token&&/sign in first|session|token/i.test(e.message)){token='';localStorage.removeItem('sv_token');localStorage.removeItem('skillvaya_token');localStorage.removeItem('skillvaya_user');sessionStorage.removeItem('sv_token');sessionStorage.removeItem('skillvaya_token');try{return await sessionInfo()}catch(_){}}me=null;const c=document.getElementById('profileSettingsCard');if(c)c.classList.add('hidden');document.getElementById('profileAuthTabs').classList.remove('hidden');profileAuthMode('signin');return null}}
async function saveProfilePhoto(){const file=document.getElementById('profilePhotoFile').files[0];if(!file){msg('photoMsg','Choose a picture first.');return}if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>2*1024*1024){msg('photoMsg','Choose a JPG, PNG or WebP image up to 2 MB.');return}const reader=new FileReader();reader.onload=async()=>{try{const d=await api('/api/account/profile',{method:'POST',body:JSON.stringify({name:me.name,phone:me.phone||'',profile_photo:reader.result})});me=d.user;document.getElementById('profilePhotoPreview').src=me.profile_photo;msg('photoMsg','Profile picture saved.',true)}catch(e){msg('photoMsg',e.message)}};reader.readAsDataURL(file)}
async function viewMessages(){view('settings');document.getElementById('messagesCard').classList.remove('hidden');const root=document.getElementById('messagesList');root.innerHTML='Loading messages…';try{const d=await api('/api/messages');root.innerHTML=(d.items||[]).map(m=>'<article class="card"><strong>'+esc(m.business_name)+'</strong><p class="muted tiny">'+esc(m.customer_name)+' · '+esc(m.created_at)+'</p><p>'+esc(m.message)+'</p>'+(me.role==='provider'&&m.customer_id?'<div class="ratingbox"><strong>Rate this customer</strong><div>'+[1,2,3,4,5].map(n=>'<button type="button" class="starbtn" aria-label="Rate customer '+n+' out of 5 stars" title="Rate customer '+n+' stars" onclick="rateCustomer('+m.business_id+','+m.customer_id+','+n+')" style="background:transparent;border:0;padding:2px 5px;font-size:1.5rem;line-height:1.3;cursor:pointer;color:#e6a400">★</button>').join('')+'</div></div>':'')+(me.role==='provider'&&m.customer_id?'<form onsubmit="replyMessage(event,'+m.business_id+','+m.customer_id+')"><textarea name="message" rows="2" required maxlength="4000" placeholder="Write a reply…"></textarea><button class="primary">Reply</button></form>':'')+'</article>').join('')||'<p class="muted">No messages yet. Contact a provider from Find a Service to start a conversation.</p>'}catch(e){root.textContent=e.message}}
async function replyMessage(e,business_id,customer_id){e.preventDefault();const f=e.target;try{await api('/api/messages/send',{method:'POST',body:JSON.stringify({business_id,customer_id,message:f.elements.message.value})});f.reset();msg('messagesStatus','Reply sent.',true);await viewMessages()}catch(x){msg('messagesStatus',x.message)}}
async function logout(){const t=token||localStorage.getItem('skillvaya_token')||localStorage.getItem('sv_token');try{if(t)await fetch('/api/logout',{method:'POST',headers:{'Authorization':'Bearer '+t,'Content-Type':'application/json'},body:'{}'})}catch(e){}token='';me=null;localStorage.removeItem('sv_token');localStorage.removeItem('skillvaya_token');localStorage.removeItem('skillvaya_owner_token');localStorage.removeItem('skillvaya_user');sessionStorage.removeItem('sv_token');sessionStorage.removeItem('skillvaya_token');location.replace('/');}
document.getElementById('profileForm').onsubmit=async e=>{e.preventDefault();try{let d=await api('/api/account/profile',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});me=d.user;document.getElementById('profileIdentity').textContent=me.email+' ? '+me.role;msg('profileMsg','Profile saved successfully.',true);await sessionInfo()}catch(x){msg('profileMsg',x.message)}};
document.getElementById('passwordForm').onsubmit=async e=>{e.preventDefault();let f=e.target;if(f.elements.new_password.value!==f.elements.confirm_password.value){msg('passwordMsg','The new password and confirmation do not match.');return}try{let d=await api('/api/account/password',{method:'POST',body:JSON.stringify({current_password:f.elements.current_password.value,new_password:f.elements.new_password.value})});f.reset();msg('passwordMsg',d.message||'Password changed successfully.',true)}catch(x){msg('passwordMsg',x.message)}};
document.getElementById('bizForm').onsubmit=async e=>{e.preventDefault();try{const f=Object.fromEntries(new FormData(e.target));const files=Array.from(document.getElementById('providerPortfolioFiles').files||[]);const total=files.reduce((n,x)=>n+x.size,0);if(total>2*1024*1024)throw Error('Portfolio photos/catalogue must be 2 MB or less combined.');f.photos=JSON.stringify(await Promise.all(files.map(file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve({name:file.name,type:file.type,data:reader.result});reader.onerror=()=>reject(Error('Could not read '+file.name));reader.readAsDataURL(file)}))));let d;if(me&&me.role==='admin'){const first=files[0];d=await api('/api/admin/owner-promotions',{method:'POST',body:JSON.stringify({kind:'business',business_name:f.name,title:f.name,category:f.category,description:f.description,target_url:f.website||'',image_url:first&&first.type!=='application/pdf'?(JSON.parse(f.photos)[0]||{}).data||'':'',area:f.area,phone:f.phone,whatsapp:f.whatsapp||f.phone,contact_email:f.email||''})});msg('bizMsg','Your free owner service listing has been published. No provider plan or payment was required.',true);e.target.reset()}else{d=await api('/api/businesses',{method:'POST',body:JSON.stringify(f)});msg('bizMsg','Payment verified. Your provider profile and portfolio files have been saved.',true)}await loadBusinesses();await refreshProviderGate()}catch(x){msg('bizMsg',x.message)}};
async function refreshProviderGate(){const card=document.getElementById('providerProfileCard'),notice=document.getElementById('providerProfileNotice'),plans=document.getElementById('providerPlansCard');if(!card||!notice)return;if(me&&me.role==='admin'){card.classList.remove('hidden');notice.textContent='OWNER FREE ACCESS: enter and publish your own services here. No subscription, plan selection, or payment is required.';notice.classList.remove('hidden');notice.classList.add('good');if(plans)plans.classList.add('hidden');return}if(plans)plans.classList.remove('hidden');notice.classList.remove('good');if(!me||me.role!=='provider'){card.classList.add('hidden');notice.textContent='Sign in or create a provider account in Profile / Sign in, then choose a plan. Business profile setup unlocks only after verified payment.';notice.classList.remove('hidden');return}try{const d=await api('/api/payment/status');const ready=(d.payments||[]).some(p=>p.status==='verified'&&p.business_id==null);const hasBusiness=(d.payments||[]).some(p=>p.status==='verified'&&p.business_id!=null);if(ready){card.classList.remove('hidden');notice.classList.add('hidden')}else{card.classList.add('hidden');notice.classList.remove('hidden');notice.textContent=hasBusiness?'A paid provider profile is already linked to your account. Manage your existing profile from Profile / Sign in.':'Choose a plan and complete PayPal checkout. Profile setup appears only after Skillvaya verifies the payment.'}}catch(e){card.classList.add('hidden');notice.classList.remove('hidden');notice.textContent='Sign in as a provider and complete a verified plan payment before setting up your business profile.'}}
function drawPlans(){if(me&&me.role==='admin'){document.getElementById('plans').innerHTML='<div class="price featured"><h3>Skillvaya Owner Edition</h3><div class="amount">FREE</div><p>All available app features unlocked for the owner account. No subscription or checkout required.</p><span class="pill">Top-tier owner access</span></div>';return}let y=document.getElementById('billing').value==='yearly';document.getElementById('plans').innerHTML=planInfo.map(p=>'<div class="price '+(p[0]==='spotlight'?'featured':'')+'"><h3>'+p[1]+'</h3><div class="amount">R'+(p[2]*(y?11:1)).toLocaleString('en-ZA')+'<span class="tiny muted"> / '+(y?'year':'month')+'</span></div>'+(y?'<span class="pill">12 months for price of 11</span>':'')+'<p class="muted tiny">'+p[3]+'</p><button class="primary" onclick="choosePlan(\''+p[0]+'\',\''+(y?'yearly':'monthly')+'\')">Choose plan</button></div>').join('')}
async function choosePlan(plan,billing){if(me&&me.role==='admin'){alert('Your Skillvaya Owner Edition is already unlocked for free. No payment is required.');return}if(!me){view('settings');profileAuthMode('signin');alert('Create a provider profile or sign in first.');return}try{const p=await api('/api/payment-provider');if(p.provider!=='paypal'||!p.checkout_ready)throw Error(p.message||'PayPal is not ready. Check the configured PayPal mode and matching credentials in Render.');const d=await api('/api/paypal/create-order',{method:'POST',body:JSON.stringify({plan,billing})});if(!d.checkout_ready||!d.approval_url)throw Error(d.error||'PayPal checkout is not ready.');location.assign(d.approval_url)}catch(e){alert(e.message)}}
async function loadAdmin(){try{let d=await api('/api/admin/summary');document.getElementById('adminData').classList.remove('hidden');document.getElementById('adminMsg').classList.add('hidden');document.getElementById('sBiz').textContent=d.businesses;document.getElementById('sComplaints').textContent=d.complaints;document.getElementById('sPayments').textContent=d.payments;document.getElementById('sPending').textContent=d.pending;adminTab('complaints')}catch(e){document.getElementById('adminData').classList.add('hidden');document.getElementById('adminMsg').textContent='Owner sign-in required. '+e.message}}
async function adminTab(tab){try{if(tab==='settings'){let d=await api('/api/admin/settings');document.getElementById('adminTable').innerHTML='<h3>Owner email & alerts</h3><p>Reports, new account notices, payment events and overdue subscription alerts can be emailed when SMTP is configured.</p><form id="ownerEmailForm"><label>Owner notification email</label><input name="owner_email" type="email" value="'+esc(d.owner_email)+'" placeholder="you@example.com" required><p><button class="primary">Save email</button> <button type="button" class="ghost" onclick="testOwnerEmail()">Send test email</button></p></form><div class="notice">'+(d.smtp_configured?'SMTP credentials detected.':'Email sending is not yet configured; events are saved to Alerts until SMTP is configured.')+'</div><p class="muted tiny">'+esc(d.note)+'</p>';document.getElementById('ownerEmailForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/admin/settings',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});alert('Owner email saved.');adminTab('settings')}catch(x){alert(x.message)}};return}
if(tab==='analytics'){let d=await api('/api/admin/analytics'),s=d.stats;document.getElementById('adminTable').innerHTML='<h3>Downloads & usage</h3><div class="stats">'+[['Page visits',s.visits],['PWA installs recorded',s.installs],['Accounts',s.accounts],['Provider accounts',s.providers],['Verified payments',s.verified_payments],['Verified payment total','R'+Number(s.revenue).toLocaleString('en-ZA')],['Desktop visits',s.desktop_visits],['Mobile visits',s.mobile_visits]].map(x=>'<div class="card"><span class="tiny muted">'+x[0]+'</span><strong>'+x[1]+'</strong></div>').join('')+'</div><p class="notice">These are events recorded by this running installation, not store download counts or unique people. Actual app-store downloads require store analytics; visits can include repeat visits.</p>';return}
let d=await api('/api/admin/'+tab);let h='';if(tab==='clients'){h='<h3>Client & provider accounts</h3><div class="tablewrap"><table class="table"><tr><th>Name</th><th>Email</th><th>Phone</th><th>Type</th><th>Created</th><th>Listings</th><th>Paid subscriptions</th></tr>'+d.items.map(x=>'<tr><td>'+esc(x.name)+'</td><td>'+esc(x.email)+'</td><td>'+esc(x.phone||'—')+'</td><td>'+esc(x.role)+'</td><td>'+esc(x.created_at)+'</td><td>'+x.businesses+'</td><td>'+x.paid+'</td></tr>').join('')+'</table></div>';document.getElementById('adminTable').innerHTML=h;return}
if(tab==='notifications'){h='<h3>Alert inbox</h3><div class="tablewrap"><table class="table"><tr><th>Date</th><th>Type</th><th>Subject</th><th>Status</th><th>Details</th></tr>'+d.items.map(x=>'<tr><td>'+esc(x.created_at)+'</td><td>'+esc(x.kind)+'</td><td>'+esc(x.subject)+'</td><td>'+esc(x.status)+'</td><td>'+esc(x.body)+'</td></tr>').join('')+'</table></div>';document.getElementById('adminTable').innerHTML=h;return}
if(tab==='complaints'){h='<h3>Safety & complaints</h3><p class="muted tiny">Review allegations, request evidence, and record outcomes. Suspension hides a listing pending review.</p><div class="tablewrap"><table class="table"><tr><th>ID</th><th>Business</th><th>Report</th><th>Status</th><th>Action</th></tr>'+d.items.map(x=>'<tr><td>#'+x.id+'</td><td>'+esc(x.business_name)+'</td><td>'+esc(x.reason)+'</td><td>'+esc(x.status)+'</td><td><button class="danger" onclick="resolveComplaint('+x.id+')">Resolve</button></td></tr>').join('')+'</table></div>'}else if(tab==='businesses'){h='<h3>Business listings</h3><div class="tablewrap"><table class="table"><tr><th>Business</th><th>Category</th><th>Plan</th><th>Status</th><th>Action</th></tr>'+d.items.map(x=>'<tr><td>'+esc(x.name)+'</td><td>'+esc(x.category)+'</td><td>'+esc(x.plan)+'</td><td>'+esc(x.status)+'</td><td><button class="ghost" onclick="setBusiness('+x.id+',\''+(x.status==='active'?'suspended':'active')+'\')">'+(x.status==='active'?'Suspend':'Activate')+'</button></td></tr>').join('')+'</table></div>'}else{h='<h3>Payment requests</h3><div class="tablewrap"><table class="table"><tr><th>Ref</th><th>Plan</th><th>Amount</th><th>Status</th><th>Action</th></tr>'+d.items.map(x=>'<tr><td>'+esc(x.reference)+'</td><td>'+esc(x.plan)+' / '+esc(x.billing)+'</td><td>R'+x.amount+'</td><td>'+esc(x.status)+'<br>'+esc(x.refund_status||'none')+'</td><td>'+(x.status==='verified'&&x.pf_payment_id?'<button class=\\"danger\\" onclick=\\"refundPayment('+x.id+','+x.amount+','+(x.refunded_amount||0)+')\\">Refund</button>':(x.status==='pending'?'Awaiting PayFast confirmation':'—'))+'</td></tr>').join('')+'</table></div>'}document.getElementById('adminTable').innerHTML=h}catch(e){alert(e.message)}}
async function emailClientByAddress(){let email=prompt("Enter the exact customer/provider account email address:");if(!email)return;let subject=prompt("Email subject (for a warning, include the reason):");if(!subject)return;let body=prompt("Message to send to this client:");if(!body)return;try{let d=await api("/api/admin/email-client",{method:"POST",body:JSON.stringify({client_email:email,subject,body})});alert("Email sent to "+d.recipient)}catch(e){alert(e.message)}}
async function testOwnerEmail(){try{await api('/api/admin/test-email',{method:'POST',body:'{}'});alert('Test email sent.')}catch(e){alert(e.message)}}
async function resolveComplaint(id){if(!confirm('Mark this complaint reviewed and resolved?'))return;try{await api('/api/admin/complaints/'+id,{method:'POST',body:'{}'});adminTab('complaints')}catch(e){alert(e.message)}}
async function setBusiness(id,status){try{await api('/api/admin/businesses/'+id,{method:'POST',body:JSON.stringify({status})});loadBusinesses();adminTab('businesses')}catch(e){alert(e.message)}}
async function verifyPayment(id){if(!confirm('Only confirm if payment has actually been received and checked in your bank/payment provider. Continue?'))return;try{await api('/api/admin/payments/'+id,{method:'POST',body:'{}'});adminTab('payments')}catch(e){alert(e.message)}}
async function refundPayment(id,amount,already){let remaining=amount*100-Number(already||0);let dollars=prompt('Refund amount in Rands (up to R'+(remaining/100).toFixed(2)+'). Partial refunds are supported.',''+(remaining/100).toFixed(2));if(dollars===null)return;let cents=Math.round(Number(dollars)*100);if(!Number.isFinite(cents)||cents<1||cents>remaining){alert('Enter a valid amount within the remaining paid balance.');return}let reason=prompt('Reason for the refund (required):');if(!reason||reason.trim().length<3)return; if(!confirm('Submit a real PayFast refund for R'+(cents/100).toFixed(2)+'?'))return;try{let d=await api('/api/admin/refunds/'+id,{method:'POST',body:JSON.stringify({amount:cents,reason})});alert(d.message||'Refund request accepted by PayFast.');adminTab('payments')}catch(e){alert(e.message)}}
function installPasswordVisibility(){document.querySelectorAll('input[type="password"]').forEach((input,index)=>{if(input.dataset.eyeReady)return;input.dataset.eyeReady='1';const wrap=document.createElement('span');wrap.className='password-wrap';input.parentNode.insertBefore(wrap,input);wrap.appendChild(input);const btn=document.createElement('button');btn.type='button';btn.className='password-toggle';btn.setAttribute('aria-label','Show password');btn.setAttribute('aria-pressed','false');btn.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';btn.addEventListener('click',()=>{const show=input.type==='password';input.type=show?'text':'password';btn.setAttribute('aria-label',show?'Hide password':'Show password');btn.setAttribute('aria-pressed',String(show));btn.innerHTML=show?'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m3 3 18 18M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.2A10.8 10.8 0 0 1 12 5c6.4 0 10 7 10 7a16 16 0 0 1-3.1 3.8M6.2 6.2C3.5 8 2 12 2 12s3.6 7 10 7a10 10 0 0 0 4-.8"/></svg>':'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';});wrap.appendChild(btn);});}
const photoInput=document.getElementById('profilePhotoFile');if(photoInput){photoInput.addEventListener('change',()=>{const f=photoInput.files&&photoInput.files[0];const name=document.getElementById('profilePhotoFileName');if(name)name.textContent=f?f.name+' · '+(f.size/1024).toFixed(0)+' KB':'Tap Choose profile picture to select an image from your device';if(f&&['image/jpeg','image/png','image/webp'].includes(f.type)&&f.size<=2*1024*1024){const preview=document.getElementById('profilePhotoPreview');if(preview)preview.src=URL.createObjectURL(f);msg('photoMsg','Image selected. Tap Upload picture to save it.',true)}else if(f){msg('photoMsg','Choose a JPG, PNG or WebP image up to 2 MB.')}});}
const portfolioInput=document.getElementById('providerPortfolioFiles');if(portfolioInput){portfolioInput.addEventListener('change',()=>{const files=Array.from(portfolioInput.files||[]),total=files.reduce((n,f)=>n+f.size,0),label=document.getElementById('providerPortfolioPreview');if(total>2*1024*1024){portfolioInput.value='';label.textContent='Selected files exceed 2 MB combined. Choose smaller files.';return}if(files.some(f=>!['image/jpeg','image/png','image/webp','application/pdf'].includes(f.type))){portfolioInput.value='';label.textContent='Choose JPG, PNG, WebP or PDF files only.';return}label.textContent=files.length?files.map(f=>f.name+' ('+(f.size/1024).toFixed(0)+' KB)').join(' · '):'No files selected';});}
installPasswordVisibility();
const splashFailsafe=setTimeout(()=>{const splash=document.getElementById('svSplash');if(splash)splash.classList.add('done');},10000);
init().finally(()=>{clearTimeout(splashFailsafe);const splash=document.getElementById('svSplash');if(splash)setTimeout(()=>splash.classList.add('done'),450)});
try{fetch('/api/analytics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event:'visit',detail:/Mobi|Android|iPhone/i.test(navigator.userAgent)?'mobile':'desktop'})})}catch(e){}
let installPrompt=null;window.addEventListener('beforeinstallprompt',e=>{installPrompt=e;});window.addEventListener('appinstalled',()=>{fetch('/api/analytics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event:'install',detail:'pwa'})}).catch(()=>{})});
if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'}).then(reg=>reg.update()).catch(console.warn);
</script></body></html>'''
SESSIONS={}
def issue_session(user):
    token=secrets.token_urlsafe(32)
    expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=3650)).isoformat()  # persistent sign-in; explicit logout revokes the token
    with conn() as c:
        c.execute("INSERT INTO auth_sessions(token,user_id,expires_at,created_at) VALUES(?,?,?,?)",(token,user["id"],expires,now()))
    SESSIONS[token]=user
    return token
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def sendj(self,obj,status=200):
        data=json.dumps(obj).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8")
        if isinstance(obj,dict) and obj.get("token"):
            self.send_header("Set-Cookie","skillvaya_session="+str(obj["token"])+"; Path=/; Max-Age=315360000; Secure; HttpOnly; SameSite=Lax")
        elif urlparse(getattr(self,"path","")).path=="/api/logout":
            self.send_header("Set-Cookie","skillvaya_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax")
        self.send_header("Content-Length",str(len(data))); self.send_header("Access-Control-Allow-Origin","null"); self.end_headers(); self.wfile.write(data)
    def body(self):
        n=int(self.headers.get("Content-Length","0"))
        if n>3_000_000: raise ValueError("Request too large")
        return json.loads(self.rfile.read(n) or b"{}")
    def user(self):
        t=self.headers.get("Authorization","").removeprefix("Bearer ").strip()
        if not t:
            for item in self.headers.get("Cookie","").split(";"):
                k,sep,v=item.strip().partition("=")
                if sep and k=="skillvaya_session":
                    t=v.strip()
                    break
        if not t: return None
        # Always validate the durable session and expiry, even if this worker has a cached user.
        # Sessions live in the database so a Render restart does not silently log users out.
        with conn() as c:
            row=c.execute("SELECT u.id,u.name,u.email,u.phone,u.role,s.expires_at FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",(t,)).fetchone()
        if not row: return None
        if row["expires_at"] <= now():
            with conn() as c: c.execute("DELETE FROM auth_sessions WHERE token=?",(t,))
            return None
        user={"id":row["id"],"name":row["name"],"email":row["email"],"phone":row["phone"] or "","role":row["role"]}
        SESSIONS[t]=user
        return user
    def require(self,role=None):
        u=self.user()
        local_only = (role == "admin" and self.client_address[0] in ("127.0.0.1", "::1")
                      and self.server.server_address[0] in ("127.0.0.1", "::1"))
        if not u and local_only:
            return {"id": 0, "name": "Local Developer", "email": "local-owner@skillvaya.local", "role": "admin"}
        if not u: raise PermissionError("Please sign in first.")
        if role and u["role"]!=role: raise PermissionError("This action requires a "+role+" account.")
        return u
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Headers","Content-Type, Authorization"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.end_headers()
    def _refund_list(self):
        with conn() as c:
            rows=c.execute("SELECT p.id,p.reference,p.plan,p.billing,p.amount,p.status,p.created_at,p.verified_at,p.pf_payment_id,p.payment_gateway,p.paypal_order_id,p.paypal_capture_id,p.refunded_amount,p.refund_status,u.email user_email FROM payments p JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC LIMIT 300").fetchall()
        return [dict(x) for x in rows]
    def do_HEAD(self):
        path=urlparse(self.path).path
        if path=="/healthz":
            b=json.dumps({"ok":True,"service":"skillvaya"}).encode()
            self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.end_headers(); return
        if path in ("/downloads/Skillvaya.apk","/downloads/Skillvaya.exe"):
            filename=path.rsplit("/",1)[-1]
            download_path=os.path.join(ROOT,"downloads",filename)
            if filename=="Skillvaya.exe" and os.environ.get("SKILLVAYA_EXE_PATH"):
                download_path=os.environ["SKILLVAYA_EXE_PATH"]
            if not os.path.isfile(download_path):
                self.send_response(404); self.end_headers(); return
            size=os.path.getsize(download_path)
            content_type="application/vnd.android.package-archive" if filename.endswith(".apk") else "application/vnd.microsoft.portable-executable"
            self.send_response(200); self.send_header("Content-Type",content_type); self.send_header("Content-Disposition",'attachment; filename="'+filename+'"'); self.send_header("Content-Length",str(size)); self.send_header("Cache-Control","no-store"); self.end_headers(); return
        self.send_response(404); self.end_headers()
    def do_GET(self):
        path=urlparse(self.path).path
        try:
            if path=="/payment/paypal-return":
                page="""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Confirm Skillvaya payment</title><style>body{font:16px system-ui;max-width:620px;margin:12vh auto;padding:24px;color:#14253b}button{padding:12px 18px;background:#087f80;color:#fff;border:0;border-radius:9px;font-weight:700}</style></head><body><h1>Confirming your payment</h1><p id="msg">Checking PayPal confirmation securely. Please keep this page open.</p><button id="back" hidden onclick="location.href='/customer'">Return to Skillvaya</button><script>(async()=>{const msg=document.getElementById('msg'),btn=document.getElementById('back'),order=new URLSearchParams(location.search).get('token'),auth=localStorage.getItem('skillvaya_token')||localStorage.getItem('sv_token');if(!order||!auth){msg.textContent='Return to Skillvaya and sign in with the same provider account used to start checkout, then check your plan status.';btn.hidden=false;return;}try{const r=await fetch('/api/paypal/capture',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+auth},body:JSON.stringify({order_id:order})}),d=await r.json();if(!r.ok)throw Error(d.error||'Payment confirmation could not be completed.');msg.textContent=d.already_verified?(d.profile_required?'Your payment was already confirmed. Return to Skillvaya and complete your provider profile to activate your listing.':'Your payment was already confirmed.'):(d.profile_required?'PayPal confirmed your payment. Return to Skillvaya, open Provider Studio, and complete your profile to activate your listing.':'PayPal confirmed your payment. Your Skillvaya plan is now active.');}catch(e){msg.textContent=e.message+' If PayPal charged you, do not pay again; sign in and contact Skillvaya support with the transaction details.';}btn.hidden=false;})();</script></body></html>"""
                data=page.encode()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
            if path=="/api/payment-provider":
                cfg=paypal_config()
                configured=bool(cfg["client_id"] and cfg["secret"] and cfg["public_url"].startswith("https://"))
                oauth_valid=False
                message="PayPal client credentials or the public HTTPS address are missing."
                if configured:
                    try:
                        paypal_access_token()
                        oauth_valid=True
                        message="PayPal "+cfg["mode"].title()+" OAuth authentication succeeded. Order creation and capture still need an approved checkout test."
                    except Exception as e:
                        message=str(e)[:220]
                return self.sendj({"provider":"paypal","paypal_ready":configured,"oauth_valid":oauth_valid,"checkout_ready":configured and oauth_valid,"mode":cfg["mode"],"message":message})
            if path=="/downloads":
                body = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#071426"><title>Official Skillvaya Downloads</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f6fa;color:#122238;font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,Arial}a{color:inherit}.top{background:linear-gradient(130deg,#071426,#10384b);color:#fff;padding:28px 20px 58px}.wrap{width:min(100% - 32px,1000px);margin:auto}.brand{font-weight:850;font-size:24px;letter-spacing:-.7px}.brand span{color:#42d3c8}.eyebrow{color:#78e7df;text-transform:uppercase;font-size:12px;font-weight:800;letter-spacing:1.5px;margin-top:32px}h1{font-size:clamp(34px,6vw,54px);line-height:1.08;letter-spacing:-1.5px;max-width:700px;margin:10px 0 12px}.lead{color:#cfdae6;max-width:690px;margin:0}.main{margin:-28px auto 50px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.card{background:#fff;border:1px solid #dbe5ee;border-radius:20px;padding:26px;box-shadow:0 12px 35px #18334a0b}.icon{width:52px;height:52px;display:grid;place-items:center;border-radius:15px;background:#e0f8f5;color:#087f80;font-size:25px;font-weight:900}.card h2{margin:16px 0 6px;font-size:24px}.muted{color:#596b7e;font-size:14px}.button{display:flex;justify-content:center;text-decoration:none;background:#087f80;color:#fff;border-radius:12px;padding:13px 18px;font-weight:800;margin:20px 0 12px}.button:hover{background:#066a6b}.sub{font-size:12px;color:#607185}.section{background:#fff;border:1px solid #dbe5ee;border-radius:18px;padding:24px;margin-top:18px}.section h2{margin:0 0 10px}.notice{background:#fff8e7;border:1px solid #f0d69a;border-radius:13px;padding:16px;margin-top:12px}.notice strong{color:#68470a}.steps{padding-left:22px}.steps li{margin:7px 0}.checks{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.check{background:#f4f8fb;border-radius:10px;padding:12px;font-size:14px}footer{padding:24px 0 40px;color:#607185;font-size:13px}footer a{color:#087f80}@media(max-width:650px){.grid,.checks{grid-template-columns:1fr}.top{padding-bottom:48px}.card{padding:21px}.section{padding:19px}}
</style></head><body><header class="top"><div class="wrap"><a class="brand" href="/customer" style="text-decoration:none">skill<span>vaya</span></a><div class="eyebrow">Official app downloads</div><h1>Get Skillvaya on your device.</h1><p class="lead">Choose the installer for your device. Download only from this official Skillvaya website, and review the installation notes before opening a downloaded file.</p></div></header><main class="wrap main"><div class="grid"><section class="card"><div class="icon" aria-hidden="true">A</div><h2>Android app</h2><p>For Android phones and tablets. The installer is an APK file downloaded directly from Skillvaya.</p><a class="button" href="/downloads/Skillvaya.apk" download>Download Android APK</a><p class="sub">File: Skillvaya.apk · Direct download from skillvaya.onrender.com</p><p class="muted">After downloading, open the file and follow Android's installation prompts. The exact prompts vary by Android version and browser.</p></section><section class="card"><div class="icon" aria-hidden="true">W</div><h2>Windows app</h2><p>For compatible Windows PCs. Download the Windows executable installer package from Skillvaya.</p><a class="button" href="/downloads/Skillvaya.exe" download>Download Windows EXE</a><p class="sub">File: Skillvaya.exe · Direct download from skillvaya.onrender.com</p><p class="muted">Save the file, then open it when the download finishes. Windows may show a reputation or publisher warning because this executable is not digitally signed.</p></section></div><section class="section"><h2>Why might Android show a safety warning?</h2><p>Android or your browser may display a message such as “This type of file can harm your device” when downloading an APK from a website. APK files are app installation packages, and installing one directly from a website is different from installing an app through Google Play. The warning is a general safety prompt; it does not by itself prove that a file is malicious, and it is not proof that a file is safe.</p><div class="notice"><strong>Stay in control of your security.</strong><br>Only download from the official Skillvaya domain shown in your browser. If the website address or filename looks different, cancel the download. Keep Android security protections enabled. Do not install a file you did not request or cannot verify.</div><ol class="steps"><li>Check that the address is <strong>https://skillvaya.onrender.com</strong>.</li><li>Use the Android APK button on this page.</li><li>Review the device's installer information before proceeding; cancel if anything looks unexpected.</li><li>For the most familiar app-store installation experience, use an official Google Play release if one becomes available.</li></ol></section><section class="section"><h2>Windows security and publisher prompts</h2><p>Windows may show Microsoft Defender SmartScreen or an unknown-publisher prompt for a downloaded EXE that has not been signed with a trusted code-signing certificate or does not yet have an established reputation. That prompt is not a malware verdict, but users should not ignore it automatically. Skillvaya's current Windows executable is not digitally signed, so Windows may display a warning.</p><p class="muted">We recommend keeping Windows security enabled. If you are unsure about a file, cancel and contact Skillvaya support rather than bypassing the warning.</p></section><section class="section"><h2>Before you install</h2><div class="checks"><div class="check">✓ Confirm you are on the official Skillvaya HTTPS website.</div><div class="check">✓ Choose Android APK for Android or EXE for Windows.</div><div class="check">✓ Keep your device's security protections enabled.</div><div class="check">✓ Contact support if a download fails or looks unexpected.</div></div><p style="margin:18px 0 0">Need help? Email <a href="mailto:skillvaya@gmail.com">skillvaya@gmail.com</a>. <a href="/customer">Return to Skillvaya</a>.</p></section></main><footer><div class="wrap">© 2026 Skillvaya. Download only from the official website. Installation prompts and device compatibility may vary.</div></footer></body></html>""".encode("utf-8")
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-cache"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
            if path=="/healthz":
                return self.sendj({"ok":True,"service":"skillvaya"})
            if path in ("/downloads/Skillvaya.apk","/downloads/Skillvaya.exe"):
                filename=path.rsplit("/",1)[-1]
                download_path=os.path.join(ROOT,"downloads",filename)
                if filename=="Skillvaya.exe" and os.environ.get("SKILLVAYA_EXE_PATH"):
                    download_path=os.environ["SKILLVAYA_EXE_PATH"]
                if not os.path.isfile(download_path):
                    return self.sendj({"error":"Installer is not available on this server yet"},404)
                with open(download_path,"rb") as f: b=f.read()
                content_type="application/vnd.android.package-archive" if filename.endswith(".apk") else "application/vnd.microsoft.portable-executable"
                self.send_response(200); self.send_header("Content-Type",content_type); self.send_header("Content-Disposition",'attachment; filename="'+filename+'"'); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(b); return
            if path=="/sv-logo.jpeg":
                logo_path=os.path.join(ROOT,"sv-logo.jpeg")
                with open(logo_path,"rb") as f: b=f.read()
                self.send_response(200); self.send_header("Content-Type","image/jpeg"); self.send_header("Cache-Control","no-cache"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            if path=="/manifest.json":
                manifest={"id":"/login","name":"Skillvaya","short_name":"Skillvaya","description":"Sign in to Skillvaya to open your workspace.","start_url":"/login?installed=1","scope":"/","display":"standalone","background_color":"#071426","theme_color":"#071426","categories":["business","shopping","lifestyle"],"icons":[{"src":"/icon-192.png","sizes":"192x192","type":"image/png","purpose":"any maskable"},{"src":"/icon-512.png","sizes":"512x512","type":"image/png","purpose":"any maskable"}]}
                b=json.dumps(manifest).encode()
                self.send_response(200); self.send_header("Content-Type","application/manifest+json; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            if path in ("/icon-192.png","/icon-512.png"):
                icon_path=os.path.join(ROOT,path.lstrip("/"))
                with open(icon_path,"rb") as f: b=f.read()
                self.send_response(200); self.send_header("Content-Type","image/png"); self.send_header("Cache-Control","public, max-age=86400"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            if path=="/icon.svg":
                logo_path=os.path.join(ROOT,"sv-logo.jpeg")
                with open(logo_path,"rb") as logo_file: logo_data=base64.b64encode(logo_file.read()).decode("ascii")
                svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="112" fill="#08142b"/><image href="data:image/jpeg;base64,'+logo_data+'" x="24" y="24" width="464" height="464" preserveAspectRatio="xMidYMid meet"/></svg>'
                b=svg.encode("utf-8"); self.send_response(200); self.send_header("Content-Type","image/svg+xml; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            if path=="/sw.js":
                worker=("const CACHE='skillvaya-shell-v3-login-sv';"
                "const ASSETS=['/manifest.json','/icon.svg','/icon-192.png','/icon-512.png','/sv-logo.jpeg'];"
                "const HTML_ROUTES=['/','/index.html','/login','/customer','/customer-app','/website','/terms'];"
                "self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())));"
                "self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));"
                "self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==location.origin||u.pathname.startsWith('/api/'))return;"
                "if(HTML_ROUTES.includes(u.pathname)){e.respondWith(fetch(e.request,{cache:'no-store'}).catch(()=>new Response('<!doctype html><meta name=viewport content=width=device-width,initial-scale=1><title>Skillvaya offline</title><main style=font:16px system-ui;margin:15vh auto;max-width:32rem;padding:1rem><h1>Skillvaya</h1><p>Connect to the internet to sign in and open your workspace.</p></main>',{headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}})));return;}"
                "e.respondWith(fetch(e.request).then(r=>{if(r&&r.ok&&ASSETS.includes(u.pathname)){const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy));}return r;}).catch(()=>caches.match(e.request)));});").encode("utf-8")
                self.send_response(200); self.send_header("Content-Type","application/javascript; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Service-Worker-Allowed","/"); self.send_header("Content-Length",str(len(worker))); self.end_headers(); self.wfile.write(worker); return
            if path=="/owner-app":
                owner_app_html = OWNER_APP_HTML.encode()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-cache"); self.send_header("Content-Length",str(len(owner_app_html))); self.end_headers(); self.wfile.write(owner_app_html); return
            if path=="/terms":
                b=TERMS_PAGE_HTML.encode("utf-8")
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            if path=="/website":
                with open(os.path.join(ROOT,"website.html"),"rb") as f: customer_html = f.read()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-cache"); self.send_header("Content-Length",str(len(customer_html))); self.end_headers(); self.wfile.write(customer_html); return
            if path in ("/customer","/customer-app"):
                # Customer browsing is public; account creation and sign-in live in Profile.
                customer_html = HTML.encode()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-cache"); self.send_header("Content-Length",str(len(customer_html))); self.end_headers(); self.wfile.write(customer_html); return
            if path=="/owner-control":
                owner_html = OWNER_HTML.encode()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(owner_html))); self.end_headers(); self.wfile.write(owner_html); return
            if path in ("/", "/index.html", "/login"):
                # The Android APK starts at /login. Serve the real app shell so saved sessions
                # can be restored instead of forcing the standalone login gateway on every launch.
                customer_html = HTML.encode()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-cache"); self.send_header("Content-Length", str(len(customer_html))); self.end_headers(); self.wfile.write(customer_html); return
            if path in ("/payment/return","/payment/cancel"):
                cancelled=path.endswith("cancel")
                body=("<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><title>Skillvaya payment</title><body style='font:16px Arial;background:#071426;color:#eef;padding:28px'><h1>"+("Payment cancelled" if cancelled else "Payment submitted")+"</h1><p>"+("No payment was taken by Skillvaya on this page. You can return to the customer app and try again." if cancelled else "Thank you. Skillvaya activates paid features only after PayPal confirms a completed capture. You can return to the customer app to check plan status.")+"</p><p><a style='color:#42d3d0' href='/customer'>Return to Skillvaya</a></p></body>").encode()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
            if path=="/api/payment/status":
                u=self.require()
                with conn() as c:
                    rows=c.execute("SELECT reference,plan,billing,amount,status,created_at,verified_at,refund_status,business_id FROM payments WHERE user_id=? ORDER BY id DESC LIMIT 20",(u["id"],)).fetchall()
                return self.sendj({"payments":[dict(x) for x in rows],"gateway":paypal_config()["mode"]})
            if path=="/api/admin/paypal/status":
                self.require("admin")
                cfg=paypal_config()
                public_https=cfg["public_url"].startswith("https://")
                credentials=bool(cfg["client_id"] and cfg["secret"])
                oauth_valid=False
                auth_message=""
                if credentials and public_https:
                    try:
                        paypal_access_token()
                        oauth_valid=True
                    except Exception as e:
                        auth_message=str(e)[:220]
                if oauth_valid and cfg["mode"]=="sandbox":
                    message="PayPal Sandbox credentials authenticated successfully. Complete a buyer-approved order/capture test before release."
                elif oauth_valid:
                    message="PayPal credentials authenticated successfully. Verify the approved checkout and capture before taking live payments."
                else:
                    message=auth_message or ("Add the PayPal client ID and secret in Render." if not credentials else "Configure SKILLVAYA_PUBLIC_URL as a public HTTPS URL.")
                return self.sendj({"provider":"paypal","mode":cfg["mode"],"credentials_configured":credentials,"public_https_configured":public_https,"oauth_valid":oauth_valid,"checkout_ready":bool(credentials and public_https and oauth_valid),"refund_api_ready":bool(credentials and oauth_valid),"message":message})
            if path=="/api/admin/payfast/status":
                return self.sendj({"error":"PayFast is paused. PayPal is the only supported checkout provider."},410)
            if path=="/api/owner-promotions":
                with conn() as c:
                    rows=c.execute("SELECT id,kind,business_name,title,category,description,target_url,image_url,status,owner_free,created_at FROM owner_promotions WHERE status='active' ORDER BY created_at DESC").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/messages":
                u=self.require()
                with conn() as c:
                    if u["role"]=="admin":
                        rows=c.execute("SELECT m.*,b.name business_name,cu.name customer_name,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id ORDER BY m.created_at DESC LIMIT 300").fetchall()
                    elif u["role"]=="provider":
                        rows=c.execute("SELECT m.*,b.name business_name,cu.name customer_name,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id WHERE b.user_id=? ORDER BY m.created_at DESC LIMIT 300",(u["id"],)).fetchall()
                    else:
                        rows=c.execute("SELECT m.*,b.name business_name,cu.name customer_name,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id WHERE m.customer_id=? ORDER BY m.created_at DESC LIMIT 300",(u["id"],)).fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/categories": return self.sendj({"categories":CATEGORIES})
            if path=="/api/platform-rating":
                viewer=self.user()
                with conn() as c:
                    agg=c.execute("SELECT COALESCE(AVG(stars),0) AS average,COUNT(*) AS total FROM platform_ratings").fetchone()
                    mine=c.execute("SELECT stars FROM platform_ratings WHERE rater_id=?",(viewer["id"] if viewer else -1,)).fetchone()
                return self.sendj({"average":round(float(agg["average"] or 0),1),"count":int(agg["total"] or 0),"my_rating":int(mine["stars"]) if mine else 0})
            if path=="/api/analytics/summary":
                self.require("admin")
                with conn() as c:
                    return self.sendj({"visits":c.execute("SELECT count(*) FROM analytics WHERE event='visit'").fetchone()[0],"installs":c.execute("SELECT count(*) FROM analytics WHERE event='install'").fetchone()[0],"visitors":c.execute("SELECT count(DISTINCT user_id) FROM analytics WHERE user_id IS NOT NULL").fetchone()[0],"users":c.execute("SELECT count(*) FROM users").fetchone()[0],"providers":c.execute("SELECT count(*) FROM users WHERE role='provider'").fetchone()[0],"paid":c.execute("SELECT count(*) FROM payments WHERE status='verified'").fetchone()[0],"revenue":c.execute("SELECT coalesce(sum(amount),0) FROM payments WHERE status='verified'").fetchone()[0],"desktop":c.execute("SELECT count(*) FROM analytics WHERE event='visit' AND detail='desktop'").fetchone()[0],"mobile":c.execute("SELECT count(*) FROM analytics WHERE event='visit' AND detail='mobile'").fetchone()[0]})
            if path=="/api/admin/clients":
                self.require("admin")
                with conn() as c:
                    rows=c.execute("SELECT u.id,u.name,u.email,u.phone,u.role,u.created_at,(SELECT count(*) FROM businesses b WHERE b.user_id=u.id) businesses,(SELECT count(*) FROM payments p WHERE p.user_id=u.id AND p.status='verified') paid FROM users u ORDER BY u.created_at DESC").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/admin/analytics":
                self.require("admin")
                with conn() as c:
                    stats={"visits":c.execute("SELECT count(*) FROM analytics WHERE event='visit'").fetchone()[0],"installs":c.execute("SELECT count(*) FROM analytics WHERE event='install'").fetchone()[0],"accounts":c.execute("SELECT count(*) FROM users").fetchone()[0],"providers":c.execute("SELECT count(*) FROM users WHERE role='provider'").fetchone()[0],"verified_payments":c.execute("SELECT count(*) FROM payments WHERE status='verified'").fetchone()[0],"revenue":c.execute("SELECT coalesce(sum(amount),0) FROM payments WHERE status='verified'").fetchone()[0],"desktop_visits":c.execute("SELECT count(*) FROM analytics WHERE event='visit' AND detail='desktop'").fetchone()[0],"mobile_visits":c.execute("SELECT count(*) FROM analytics WHERE event='visit' AND detail='mobile'").fetchone()[0]}
                return self.sendj({"stats":stats})
            if path=="/api/admin/notifications":
                self.require("admin")
                with conn() as c: rows=c.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 200").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/admin/settings":
                self.require("admin")
                return self.sendj({"owner_email":setting("owner_email"),"smtp_configured":bool(os.environ.get("SKILLVAYA_SMTP_HOST") and os.environ.get("SKILLVAYA_SMTP_USER") and os.environ.get("SKILLVAYA_SMTP_PASSWORD")),"note":"SMTP credentials must be configured in the server environment; secrets are not stored in the browser."})
            if path=="/api/businesses":
                from urllib.parse import parse_qs
                q=parse_qs(urlparse(self.path).query); term=q.get("q",[""])[0].lower(); area=q.get("area",[""])[0].lower(); cat=q.get("category",["All categories"])[0]; sort=q.get("sort",["featured"])[0]
                viewer=self.user()
                rater_id=viewer["id"] if viewer and viewer["role"]=="customer" else -1
                with conn() as c:
                    rows=c.execute("""SELECT b.*,
                        COALESCE(r.average,0) AS rating, COALESCE(r.rating_count,0) AS rating_count,
                        COALESCE(my.stars,0) AS my_rating
                        FROM businesses b
                        LEFT JOIN (SELECT business_id,AVG(stars) AS average,COUNT(*) AS rating_count
                                   FROM ratings WHERE target_type='provider' GROUP BY business_id) r ON r.business_id=b.id
                        LEFT JOIN ratings my ON my.business_id=b.id AND my.target_type='provider'
                             AND my.rater_id=? AND my.target_user_id=b.user_id
                        WHERE LOWER(TRIM(COALESCE(b.status,''))) IN ('active','approved','published')""",(rater_id,)).fetchall()
                items=[dict(x) for x in rows if category_matches(cat, x["category"]) and (not term or term in (x["name"]+" "+x["category"]+" "+x["description"]+" "+category_search_terms(x["category"])).lower()) and (not area or area in x["area"].lower())]
                for item in items:
                    item["rating"]=round(float(item["rating"] or 0),1); item["rating_count"]=int(item["rating_count"] or 0); item["my_rating"]=int(item["my_rating"] or 0)
                if sort=="rating": items.sort(key=lambda x:x["rating"] or 0,reverse=True)
                elif sort=="name": items.sort(key=lambda x:x["name"].lower())
                else: items.sort(key=lambda x:{"spotlight":0,"plus":1,"priority":2,"local":3}.get(x["plan"],4))
                for x in items:
                    x.pop("user_id",None); x.pop("photos",None)
                    # Email is intentionally shown only when the provider explicitly supplied it as public contact.
                    x["email"]=x.get("email") or ""
                    x["whatsapp"]=x.get("whatsapp") or x.get("phone") or ""
                return self.sendj({"businesses":items})
            if path=="/api/me":
                u=self.require()
                with conn() as c: row=c.execute("SELECT id,name,email,phone,role,profile_photo FROM users WHERE id=?",(u["id"],)).fetchone()
                return self.sendj({"user":dict(row) if row else u})
            if path=="/api/account/profile":
                u=self.require(); return self.sendj({"user":u})
            if path=="/api/admin/summary":
                self.require("admin")
                with conn() as c:
                    return self.sendj({"businesses":c.execute("SELECT count(*) FROM businesses").fetchone()[0],"complaints":c.execute("SELECT count(*) FROM complaints WHERE status='open'").fetchone()[0],"payments":c.execute("SELECT count(*) FROM payments WHERE status='pending'").fetchone()[0],"pending":c.execute("SELECT count(*) FROM businesses WHERE status='pending'").fetchone()[0]})
            if path=="/api/admin/owner-promotions":
                self.require("admin")
                with conn() as c:
                    rows=c.execute("SELECT * FROM owner_promotions ORDER BY created_at DESC").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path.startswith("/api/admin/"):
                self.require("admin")
                with conn() as c:
                    if path=="/api/admin/complaints":
                        rows=c.execute("SELECT complaints.*,businesses.name business_name FROM complaints JOIN businesses ON businesses.id=complaints.business_id ORDER BY complaints.created_at DESC").fetchall()
                    elif path=="/api/admin/businesses": rows=c.execute("SELECT * FROM businesses ORDER BY created_at DESC").fetchall()
                    elif path=="/api/admin/payments": rows=c.execute("SELECT * FROM payments ORDER BY created_at DESC").fetchall()
                    else: return self.sendj({"error":"Not found"},404)
                return self.sendj({"items":[dict(x) for x in rows]})
            return self.sendj({"error":"Not found"},404)
        except PermissionError as e: return self.sendj({"error":str(e)},401)
        except Exception as e: return self.sendj({"error":str(e)},400)
    def do_POST(self):
        path=urlparse(self.path).path
        try:
            if path=="/api/payfast/itn":
                self.rfile.read(int(self.headers.get("Content-Length","0")))
                return self.sendj({"error":"PayFast is paused. PayPal is the only supported checkout provider."},410)
            d=self.body()
            if path=="/api/paypal/create-order":
                u=self.require("provider"); plan=d.get("plan"); billing=d.get("billing")
                if plan not in PLANS or billing not in ("monthly","yearly"): return self.sendj({"error":"Choose a valid plan and billing term."},400)
                cfg=paypal_config()
                if not cfg["public_url"].startswith("https://"): return self.sendj({"error":"Set SKILLVAYA_PUBLIC_URL to the public HTTPS Skillvaya address in Render."},503)
                if not cfg["client_id"] or not cfg["secret"]: return self.sendj({"error":"PayPal credentials are not configured in Render."},503)
                amount=int(PLANS[plan]["monthly"]*(11 if billing=="yearly" else 1)); ref="SV-"+secrets.token_hex(4).upper()
                with conn() as c:
                    b=c.execute("SELECT id FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    c.execute("INSERT INTO payments(user_id,business_id,plan,billing,amount,reference,created_at,payment_gateway) VALUES(?,?,?,?,?,?,?,'paypal')",(u["id"],b["id"] if b else None,plan,billing,amount,ref,now()))
                try:
                    order=paypal_api_request("POST","/v2/checkout/orders",{"intent":"CAPTURE","purchase_units":[{"reference_id":ref,"custom_id":ref,"invoice_id":ref,"description":"Skillvaya "+PLANS[plan]["name"]+" "+billing,"amount":{"currency_code":"ZAR","value":format(amount,".2f")}}],"application_context":{"brand_name":"Skillvaya","user_action":"PAY_NOW","return_url":cfg["public_url"]+"/payment/paypal-return","cancel_url":cfg["public_url"]+"/payment/cancel"}})
                except Exception as e: return self.sendj({"error":"Could not start PayPal checkout: "+str(e),"reference":ref},502)
                approval=next((x.get("href") for x in order.get("links",[]) if x.get("rel")=="approve"),None); order_id=order.get("id")
                if not order_id or not approval: return self.sendj({"error":"PayPal did not return a checkout approval link.","reference":ref},502)
                with conn() as c: c.execute("UPDATE payments SET paypal_order_id=? WHERE reference=?",(order_id,ref))
                notify("payment_request","PayPal payment request created","Provider: "+u["email"]+"; plan: "+plan+"; billing: "+billing+"; amount: R"+str(amount)+"; reference: "+ref+". Payment is not confirmed.")
                return self.sendj({"ok":True,"checkout_ready":True,"reference":ref,"amount":amount,"mode":cfg["mode"],"order_id":order_id,"approval_url":approval})
            if path=="/api/paypal/capture":
                u=self.require("provider"); order_id=str(d.get("order_id","")).strip()
                if not order_id or len(order_id)>128: return self.sendj({"error":"A valid PayPal order ID is required."},400)
                with conn() as c: row=c.execute("SELECT * FROM payments WHERE paypal_order_id=? AND user_id=? LIMIT 1",(order_id,u["id"])).fetchone()
                if not row: return self.sendj({"error":"This PayPal order does not match a Skillvaya payment for your account."},404)
                if row["status"]=="verified": return self.sendj({"ok":True,"already_verified":True,"status":"verified","profile_required":row["business_id"] is None})
                try: result=paypal_api_request("POST","/v2/checkout/orders/"+urllib.parse.quote(order_id,safe="")+"/capture",{})
                except Exception as e:
                    try: result=paypal_api_request("GET","/v2/checkout/orders/"+urllib.parse.quote(order_id,safe=""))
                    except Exception: return self.sendj({"error":"PayPal capture could not be verified: "+str(e)},502)
                units=result.get("purchase_units") or []; unit=units[0] if units else {}
                captures=((unit.get("payments") or {}).get("captures") or []); capture=captures[0] if captures else {}
                cap_amount=capture.get("amount") or {}
                if result.get("status")!="COMPLETED" or capture.get("status")!="COMPLETED": return self.sendj({"error":"PayPal has not confirmed a completed payment. Your plan has not been activated."},409)
                if unit.get("custom_id")!=row["reference"] or cap_amount.get("currency_code")!="ZAR": return self.sendj({"error":"PayPal reference or currency did not match. The plan has not been activated."},409)
                try: paid=float(cap_amount.get("value","-1"))
                except (TypeError,ValueError): paid=-1
                if abs(paid-float(row["amount"]))>0.001: return self.sendj({"error":"The confirmed PayPal amount does not match the requested plan. The plan has not been activated."},409)
                capture_id=capture.get("id")
                if not capture_id: return self.sendj({"error":"PayPal did not provide a capture ID. The plan has not been activated."},409)
                with conn() as c:
                    fresh=c.execute("SELECT * FROM payments WHERE id=?",(row["id"],)).fetchone()
                    if fresh["status"]=="verified": return self.sendj({"ok":True,"already_verified":True,"status":"verified"})
                    activate_payment(c,fresh,capture_id)
                    c.execute("UPDATE payments SET payment_gateway='paypal',paypal_capture_id=?,pf_payment_id=? WHERE id=?",(capture_id,capture_id,row["id"]))
                    paid_payment=c.execute("SELECT * FROM payments WHERE id=?",(row["id"],)).fetchone()
                    customer=c.execute("SELECT name,email FROM users WHERE id=?",(row["user_id"],)).fetchone()
                notify("payment_verified","PayPal payment verified","Provider ID: "+str(u["id"])+"; plan: "+row["plan"]+"; amount: R"+str(row["amount"])+"; reference: "+row["reference"]+"; PayPal capture: "+capture_id+".")
                receipt_sent=send_customer_receipt(paid_payment,customer["name"] if customer else "",customer["email"] if customer else "",capture_id)
                return self.sendj({"ok":True,"status":"verified","reference":row["reference"],"plan":row["plan"],"profile_required":row["business_id"] is None,"receipt_email_sent":receipt_sent})
            if path=="/api/analytics":
                event=d.get("event","")
                if event not in ("visit","install"): return self.sendj({"error":"Unsupported event."},400)
                u=self.user()
                detail=str(d.get("detail",""))[:40]
                with conn() as c: c.execute("INSERT INTO analytics(event,user_id,detail,created_at) VALUES(?,?,?,?)",(event,u["id"] if u else None,detail,now()))
                return self.sendj({"ok":True},201)
            if path=="/api/admin/settings":
                self.require("admin")
                email=d.get("owner_email","").strip().lower()
                if email and ("@" not in email or len(email)>254): return self.sendj({"error":"Enter a valid owner email address."},400)
                with conn() as c: c.execute("INSERT INTO settings(key,value) VALUES('owner_email',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(email,))
                notify("settings","Skillvaya owner email updated","Owner notification destination is now "+(email or "(not configured)")+". SMTP still requires server environment settings.")
                return self.sendj({"ok":True,"owner_email":email})
            if path=="/api/admin/email-client":
                self.require("admin")
                client_id=int(d.get("client_id",0) or 0); client_email=str(d.get("client_email","")).strip().lower(); subject=str(d.get("subject","")).strip()[:180]; body=str(d.get("body","")).strip()[:10000]
                if not subject or not body: return self.sendj({"error":"Enter both a subject and message."},400)
                with conn() as c: client=c.execute("SELECT id,name,email FROM users WHERE id=?" if client_id else "SELECT id,name,email FROM users WHERE email=?",(client_id if client_id else client_email,)).fetchone()
                if not client: return self.sendj({"error":"Client account not found."},404)
                nid=None
                with conn() as c:
                    cur=c.execute("INSERT INTO notifications(kind,subject,body,status,created_at,recipient) VALUES(?,?,?,?,?,?) RETURNING id",("client_message",subject,"To: "+client["name"]+" <"+client["email"]+">\\n\\n"+body,"new",now(),client["email"]))
                    nid=cur.fetchone()["id"]
                if not send_owner_email(subject,body,client["email"]): return self.sendj({"error":"Message saved in Alerts but not sent. Configure SMTP in the server environment first."},503)
                with conn() as c: c.execute("UPDATE notifications SET status='emailed',emailed_at=? WHERE id=?",(now(),nid))
                return self.sendj({"ok":True,"recipient":client["email"]})
            if path=="/api/admin/test-email":
                self.require("admin")
                if not setting("owner_email"): return self.sendj({"error":"Save your owner email address first."},400)
                ok=notify("test","Test email","This is a Skillvaya test notification. If you received it, email delivery is working.")
                if not ok: return self.sendj({"error":"Email was queued locally but not sent. Configure SKILLVAYA_SMTP_HOST, SKILLVAYA_SMTP_PORT, SKILLVAYA_SMTP_USER, SKILLVAYA_SMTP_PASSWORD and SKILLVAYA_SMTP_FROM on the server."},503)
                return self.sendj({"ok":True})
            if path=="/api/account/profile":
                u=self.require()
                name=str(d.get("name","")).strip()[:120]; phone=str(d.get("phone","")).strip()[:40]
                photo=str(d.get("profile_photo","")).strip()
                if len(name)<2: return self.sendj({"error":"Enter a name of at least 2 characters."},400)
                if photo and (not photo.startswith(("data:image/png;base64,","data:image/jpeg;base64,","data:image/webp;base64,")) or len(photo)>2800000):
                    return self.sendj({"error":"Profile picture must be a PNG, JPG or WebP image no larger than 2 MB."},400)
                with conn() as c: c.execute("UPDATE users SET name=?,phone=?,profile_photo=? WHERE id=?",(name,phone,photo,u["id"]))
                return self.sendj({"ok":True,"user":{**u,"name":name,"phone":phone,"profile_photo":photo}})
            if path=="/api/account/password":
                u=self.require(); current=str(d.get("current_password", "")); new_password=str(d.get("new_password", ""))
                if len(new_password)<8: return self.sendj({"error":"Your new password must be at least 8 characters."},400)
                with conn() as c: row=c.execute("SELECT password_hash FROM users WHERE id=?",(u["id"],)).fetchone()
                if not row or not verify_password(row["password_hash"],current): return self.sendj({"error":"Your current password is incorrect."},401)
                with conn() as c: c.execute("UPDATE users SET password_hash=? WHERE id=?",(hashpw(new_password),u["id"]))
                return self.sendj({"ok":True,"message":"Password changed. You remain signed in on this device."})
            if path=="/api/logout":
                t=self.headers.get("Authorization","").removeprefix("Bearer ").strip()
                if t:
                    with conn() as c: c.execute("DELETE FROM auth_sessions WHERE token=?",(t,))
                    SESSIONS.pop(t,None)
                return self.sendj({"ok":True})
            if path=="/api/platform-rating":
                u=self.require()
                try: stars=int(d.get("stars",0))
                except (ValueError,TypeError): return self.sendj({"error":"Choose a rating from 1 to 5 stars."},400)
                if stars not in (1,2,3,4,5): return self.sendj({"error":"Choose a rating from 1 to 5 stars."},400)
                with conn() as c:
                    c.execute("INSERT INTO platform_ratings(rater_id,stars,created_at) VALUES(?,?,?) ON CONFLICT(rater_id) DO UPDATE SET stars=excluded.stars,created_at=excluded.created_at",(u["id"],stars,now()))
                    agg=c.execute("SELECT COALESCE(AVG(stars),0) AS average,COUNT(*) AS total FROM platform_ratings").fetchone()
                return self.sendj({"ok":True,"stars":stars,"average":round(float(agg["average"] or 0),1),"count":int(agg["total"] or 0)})
            if path=="/api/ratings":
                u=self.require()
                try:
                    stars=int(d.get("stars",0)); bid=int(d.get("business_id",0))
                except (ValueError,TypeError):
                    return self.sendj({"error":"Choose a valid rating and service provider."},400)
                if stars not in (1,2,3,4,5): return self.sendj({"error":"Choose a rating from 1 to 5 stars."},400)
                target_type=str(d.get("target_type",""))
                with conn() as c:
                    biz=c.execute("SELECT id,user_id FROM businesses WHERE id=? AND status='active'",(bid,)).fetchone()
                    if not biz: return self.sendj({"error":"This service provider is not available for rating."},404)
                    if target_type=="provider" and u["role"]=="customer":
                        target_id=int(biz["user_id"] or 0)
                    elif target_type=="customer" and u["role"]=="provider":
                        try: target_id=int(d.get("customer_id",0))
                        except (ValueError,TypeError): target_id=0
                        if biz["user_id"]!=u["id"]: return self.sendj({"error":"You can rate customers only for your own service listing."},403)
                        customer=c.execute("SELECT id FROM users WHERE id=? AND role='customer'",(target_id,)).fetchone()
                        if not customer: return self.sendj({"error":"Customer account not found."},404)
                        interaction=c.execute("SELECT 1 FROM enquiries WHERE business_id=? AND customer_id=? UNION SELECT 1 FROM messages WHERE business_id=? AND customer_id=? LIMIT 1",(bid,target_id,bid,target_id)).fetchone()
                        if not interaction: return self.sendj({"error":"You can rate a customer after you have interacted with them through Skillvaya."},403)
                    else:
                        return self.sendj({"error":"Customers rate providers and providers rate customers using their respective accounts."},403)
                    c.execute("INSERT INTO ratings(business_id,rater_id,target_type,target_user_id,stars,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(business_id,rater_id,target_type,target_user_id) DO UPDATE SET stars=excluded.stars,created_at=excluded.created_at",(bid,u["id"],target_type,target_id,stars,now()))
                    aggregate=c.execute("SELECT COALESCE(AVG(stars),0) average,COUNT(*) total FROM ratings WHERE business_id=? AND target_type='provider'",(bid,)).fetchone()
                return self.sendj({"ok":True,"stars":stars,"provider_average":round(float(aggregate["average"] or 0),1),"provider_rating_count":int(aggregate["total"] or 0)})
            if path=="/api/signup":
                name=d.get("name","").strip(); email=d.get("email","").strip().lower(); phone=d.get("phone","").strip()[:40]; pw=d.get("password",""); role=d.get("role","customer")
                terms_accepted = d.get("accept_terms") is True
                terms_version = setting("terms_version", TERMS_VERSION)
                if not terms_accepted: return self.sendj({"error":"You must read and accept the Skillvaya Terms, Conditions, Rules & Safety before creating an account."},400)
                if not name or "@" not in email or len(pw)<8 or role not in ("customer","provider"): return self.sendj({"error":"Enter a name, valid email, password of 8+ characters, and valid account type."},400)
                with conn() as c:
                    try: uid=c.execute("INSERT INTO users(name,email,password_hash,role,created_at,phone,accepted_terms_version,accepted_terms_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",(name,email,hashpw(pw),role,now(),phone,terms_version,now())).fetchone()["id"]
                    except DBIntegrityError: return self.sendj({"error":"An account with that email already exists."},409)
                u={"id":uid,"name":name,"email":email,"phone":phone,"role":role,"profile_photo":""}; t=issue_session(u)
                notify("new_account","New Skillvaya account","New "+role+" account created: "+name+" <"+email+">.")
                return self.sendj({"token":t,"user":u})
            if path=="/api/login":
                email=d.get("email","").lower().strip(); pw=d.get("password","")
                with conn() as c: row=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
                if not row or not verify_password(row["password_hash"],pw):return self.sendj({"error":"Email or password is incorrect."},401)
                if row["role"]!="admin" and d.get("accept_terms") is not True:
                    return self.sendj({"error":"Please read the current Terms, Conditions, Rules & Safety and tick the agreement box before signing in.","terms_required":True,"terms_url":"/terms"},400)
                if not row["password_hash"].startswith("pbkdf2_sha256$"):
                    with conn() as c: c.execute("UPDATE users SET password_hash=? WHERE id=?",(hashpw(pw),row["id"]))
                if d.get("accept_terms") is True:
                    terms_version=setting("terms_version",TERMS_VERSION)
                    with conn() as c: c.execute("UPDATE users SET accepted_terms_version=?,accepted_terms_at=? WHERE id=?",(terms_version,now(),row["id"]))
                u={"id":row["id"],"name":row["name"],"email":row["email"],"phone":row["phone"] if "phone" in row.keys() else "", "profile_photo":row["profile_photo"] if "profile_photo" in row.keys() else "", "role":row["role"]}; t=issue_session(u); return self.sendj({"token":t,"user":u})
            if path=="/api/businesses":
                u=self.require("provider")
                name=d.get("name","").strip(); category=d.get("category",""); area=d.get("area","").strip(); phone=d.get("phone","").strip(); desc=d.get("description","").strip()
                if not all([name,category in CATEGORIES,area,phone,desc]): return self.sendj({"error":"Please complete all required business fields and choose a valid category."},400)
                with conn() as c:
                    payment=c.execute("SELECT * FROM payments WHERE user_id=? AND status='verified' AND business_id IS NULL ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    if not payment:
                        return self.sendj({"error":"Complete a provider plan payment and wait for Skillvaya's verified confirmation before creating your business profile."},403)
                    days=365 if payment["billing"]=="yearly" else 30
                    expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=days)).isoformat()
                    cur=c.execute("INSERT INTO businesses(user_id,name,category,area,phone,whatsapp,email,website,description,photos,plan,billing,status,payment_status,subscription_expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'active','verified',?,?) RETURNING id",(u["id"],name,category,area,phone,d.get("whatsapp","").strip()[:40],d.get("email",""),d.get("website",""),desc,d.get("photos",""),payment["plan"],payment["billing"],expires,now()))
                    business_id=cur.fetchone()["id"]
                    c.execute("UPDATE payments SET business_id=? WHERE id=?",(business_id,payment["id"]))
                    c.execute("INSERT INTO subscriptions(business_id,user_id,plan,billing,status,started_at,expires_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(business_id) DO UPDATE SET user_id=excluded.user_id,plan=excluded.plan,billing=excluded.billing,status='active',started_at=excluded.started_at,expires_at=excluded.expires_at,cancelled_at=NULL",(business_id,u["id"],payment["plan"],payment["billing"],"active",now(),expires))
                return self.sendj({"ok":True,"message":"Payment verified. Your provider profile is active."},201)
            if path=="/api/enquiries":
                u=self.require("customer"); bid=int(d.get("business_id",0)); message=d.get("message","").strip()
                if not message:return self.sendj({"error":"Message cannot be empty."},400)
                with conn() as c:
                    if not c.execute("SELECT id FROM businesses WHERE id=? AND status='active'",(bid,)).fetchone():return self.sendj({"error":"Business not found or unavailable."},404)
                    c.execute("INSERT INTO enquiries(business_id,customer_id,message,created_at) VALUES(?,?,?,?)",(bid,u["id"],message,now()))
                    c.execute("INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)",(bid,u["id"],u["id"],message,now()))
                return self.sendj({"ok":True},201)
            if path=="/api/messages":
                u=self.require()
                with conn() as c:
                    if u["role"]=="admin":
                        rows=c.execute("SELECT m.*,b.name business_name,cu.name customer_name,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id ORDER BY m.created_at DESC LIMIT 300").fetchall()
                    elif u["role"]=="provider":
                        rows=c.execute("SELECT m.*,b.name business_name,cu.name customer_name,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id WHERE b.user_id=? ORDER BY m.created_at DESC LIMIT 300",(u["id"],)).fetchall()
                    else:
                        rows=c.execute("SELECT m.*,b.name business_name,cu.name customer_name,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id WHERE m.customer_id=? ORDER BY m.created_at DESC LIMIT 300",(u["id"],)).fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/messages/send":
                u=self.require()
                try: bid=int(d.get("business_id",0))
                except (ValueError,TypeError): return self.sendj({"error":"Choose a valid provider."},400)
                body=str(d.get("message","")).strip()[:4000]
                if not body:return self.sendj({"error":"Message cannot be empty."},400)
                with conn() as c:
                    biz=c.execute("SELECT id,user_id,name FROM businesses WHERE id=? AND status='active'",(bid,)).fetchone()
                    if not biz:return self.sendj({"error":"Provider listing not found."},404)
                    if u["role"]=="customer": customer_id=u["id"]
                    elif u["role"]=="provider" and biz["user_id"]==u["id"]:
                        try: customer_id=int(d.get("customer_id",0))
                        except (ValueError,TypeError): customer_id=0
                        if not c.execute("SELECT id FROM enquiries WHERE business_id=? AND customer_id=?",(bid,customer_id)).fetchone(): return self.sendj({"error":"You can reply only to a customer who has contacted this listing."},403)
                    elif u["role"]=="admin": customer_id=int(d.get("customer_id",u["id"]))
                    else:return self.sendj({"error":"You cannot message this listing."},403)
                    c.execute("INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)",(bid,customer_id,u["id"],body,now()))
                    if u["role"]=="customer":
                        c.execute("INSERT INTO enquiries(business_id,customer_id,message,created_at) VALUES(?,?,?,?)",(bid,customer_id,body,now()))
                return self.sendj({"ok":True},201)
            if path=="/api/complaints":
                u=self.require("customer"); bid=int(d.get("business_id",0)); reason=d.get("reason","").strip()
                if not reason:return self.sendj({"error":"Please describe the complaint."},400)
                with conn() as c:
                    if not c.execute("SELECT id FROM businesses WHERE id=?",(bid,)).fetchone():return self.sendj({"error":"Business not found."},404)
                    c.execute("INSERT INTO complaints(business_id,customer_id,reason,created_at,priority) VALUES(?,?,?,?,?)",(bid,u["id"],reason,now(),"high" if any(w in reason.lower() for w in ["deposit","stole","threat","fraud","ran away","unsafe"]) else "normal",))
                notify("complaint","New business report submitted","Business ID: "+str(bid)+"; customer ID: "+str(u["id"])+"; report: "+reason)
                return self.sendj({"ok":True},201)
            if path=="/api/payments":
                return self.sendj({"error":"PayFast checkout is paused. Select PayPal Sandbox instead."},410)
            if path=="/api/admin/refunds":
                self.require("admin")
                return self.sendj({"items":self._refund_list()})
            if path=="/api/admin/owner-promotions":
                owner=self.require("admin")
                kind=str(d.get("kind","ad")).strip().lower()
                business_name=str(d.get("business_name","")).strip()[:120]
                title=str(d.get("title","")).strip()[:160]
                category=str(d.get("category","Other professional services")).strip()
                description=str(d.get("description","")).strip()[:3000]
                target_url=str(d.get("target_url","")).strip()[:500]
                image_url=str(d.get("image_url","")).strip()[:1000]
                if kind not in ("business","ad","app"): return self.sendj({"error":"Choose business, ad or app."},400)
                if not business_name or not title or not description: return self.sendj({"error":"Business name, title and description are required."},400)
                if category not in CATEGORIES: return self.sendj({"error":"Choose a valid category."},400)
                if any(x and not x.startswith(("https://","http://")) for x in (target_url,image_url)): return self.sendj({"error":"Links must start with http:// or https://."},400)
                with conn() as c:
                    cur=c.execute("INSERT INTO owner_promotions(kind,business_name,title,category,description,target_url,image_url,status,owner_free,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'active',1,?,?) RETURNING id",(kind,business_name,title,category,description,target_url,image_url,now(),now()))
                    promotion_id=cur.fetchone()["id"]
                    # Owner business/service entries are also added to the public provider directory
                    # as free active basic listings. They do not create a payment request or subscription.
                    directory_id=None
                    if kind=="business":
                        directory_id=c.execute(
                            "INSERT INTO businesses(user_id,name,category,area,phone,whatsapp,email,website,description,photos,plan,billing,status,payment_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,'local','monthly','active','verified',?) RETURNING id",
                            (owner["id"],business_name,category,str(d.get("area","South Africa")).strip()[:120] or "South Africa",str(d.get("phone","")).strip()[:40],str(d.get("whatsapp","")).strip()[:40] or str(d.get("phone","")).strip()[:40],str(d.get("contact_email","")).strip().lower()[:254] or owner.get("email",""),target_url,description,image_url,now())
                        ).fetchone()["id"]
                return self.sendj({"ok":True,"id":promotion_id,"directory_business_id":directory_id,"owner_free":True,"payment_required":False},201)
            if path.startswith("/api/admin/owner-promotions/"):
                self.require("admin")
                try: pid=int(path.rsplit("/",1)[1])
                except ValueError: return self.sendj({"error":"Invalid promotion ID."},400)
                status=str(d.get("status","")).strip().lower()
                if status not in ("active","paused","removed"): return self.sendj({"error":"Invalid status."},400)
                with conn() as c:
                    cur=c.execute("UPDATE owner_promotions SET status=?,updated_at=? WHERE id=?",(status,now(),pid))
                if not cur.rowcount: return self.sendj({"error":"Promotion not found."},404)
                return self.sendj({"ok":True,"status":status})
            if path.startswith("/api/admin/refunds/"):
                self.require("admin")
                try: pid=int(path.rsplit("/",1)[1])
                except (ValueError,TypeError): return self.sendj({"error":"Invalid payment ID."},400)
                reason=str(d.get("reason","")).strip()[:255]
                try: amount=int(d.get("amount",0))
                except (ValueError,TypeError): return self.sendj({"error":"Refund amount must be entered in cents."},400)
                if amount<1 or len(reason)<3: return self.sendj({"error":"Enter a refund amount greater than zero and a reason of at least 3 characters."},400)
                with conn() as c: row=c.execute("SELECT * FROM payments WHERE id=?",(pid,)).fetchone()
                if not row: return self.sendj({"error":"Payment not found."},404)
                capture_id=row["paypal_capture_id"] or (row["pf_payment_id"] if row["payment_gateway"]=="paypal" else None)
                if row["status"]!="verified" or row["payment_gateway"]!="paypal" or not capture_id:
                    return self.sendj({"error":"Only PayPal-confirmed captures can be refunded."},400)
                if row["refund_status"]=="pending":
                    return self.sendj({"error":"A PayPal refund is already pending. Do not submit a duplicate."},409)
                if amount+int(row["refunded_amount"] or 0)>int(row["amount"])*100:
                    return self.sendj({"error":"Refund exceeds the remaining amount paid."},400)
                payload={"amount":{"value":format(amount/100,".2f"),"currency_code":"ZAR"},"note_to_payer":reason}
                try:
                    result=paypal_api_request("POST","/v2/payments/captures/"+urllib.parse.quote(str(capture_id),safe="")+"/refund",payload)
                except Exception as e:
                    return self.sendj({"error":"PayPal did not confirm the refund request: "+str(e)[:300]},502)
                refund_status=str(result.get("status","")).upper()
                if refund_status not in ("COMPLETED","PENDING"):
                    return self.sendj({"error":"PayPal did not confirm the refund. Status: "+(refund_status or "unknown")},502)
                with conn() as c:
                    total=int(row["refunded_amount"] or 0)+(amount if refund_status=="COMPLETED" else 0)
                    stored_status=("refunded" if total>=int(row["amount"])*100 else "partial") if refund_status=="COMPLETED" else "pending"
                    c.execute("UPDATE payments SET refunded_amount=?,refund_status=? WHERE id=?",(total,stored_status,pid))
                    c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("refund","PayPal refund "+stored_status,"Payment reference "+row["reference"]+"; refund amount R"+format(amount/100,".2f")+"; PayPal refund ID "+str(result.get("id","unknown"))+"; reason: "+reason,now(),setting("owner_email")))
                return self.sendj({"ok":True,"refund_status":stored_status,"refunded_amount":total,"paypal_refund_id":result.get("id"),"message":"PayPal confirmed the refund." if refund_status=="COMPLETED" else "PayPal accepted the refund as pending; do not submit it again."})
            if path.startswith("/api/admin/"):
                self.require("admin")
                bits=path.strip("/").split("/")
                with conn() as c:
                    if len(bits)==4 and bits[2]=="complaints":
                        c.execute("UPDATE complaints SET status='reviewed' WHERE id=?",(int(bits[3]),)); return self.sendj({"ok":True})
                    if len(bits)==4 and bits[2]=="businesses":
                        status=d.get("status")
                        if status not in ("active","suspended","pending","removed"):return self.sendj({"error":"Invalid listing status."},400)
                        c.execute("UPDATE businesses SET status=? WHERE id=?",(status,int(bits[3]))); return self.sendj({"ok":True})
                    if len(bits)==4 and bits[2]=="payments":
                        pid=int(bits[3]); row=c.execute("SELECT * FROM payments WHERE id=?",(pid,)).fetchone()
                        if not row:return self.sendj({"error":"Payment request not found."},404)
                        if row["status"]=="verified":
                            return self.sendj({"ok":True,"already_verified":True})
                        return self.sendj({"error":"Manual payment verification is disabled. Paid plans activate only after a valid PayFast notification."},409)
                return self.sendj({"error":"Not found"},404)
            return self.sendj({"error":"Not found"},404)
        except PermissionError as e: return self.sendj({"error":str(e)},401)
        except Exception as e: return self.sendj({"error":str(e)},400)
def main():
    init()
    expire_subscriptions()
    def expiry_loop():
        while True:
            threading.Event().wait(3600)
            try: expire_subscriptions()
            except Exception as e: print("Subscription expiry check failed:",e,flush=True)
    threading.Thread(target=expiry_loop,daemon=True).start()
    server=ThreadingHTTPServer((HOST,PORT),Handler)
    print("Skillvaya server listening on %s:%d"%(HOST,PORT),flush=True)
    server.serve_forever()
if __name__=="__main__": main()
