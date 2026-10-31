from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, sqlite3, hashlib, hmac, secrets, os, datetime, threading, webbrowser, urllib.parse, urllib.request, urllib.error, base64, time
from contextlib import contextmanager

ROOT = os.path.dirname(os.path.abspath(__file__))
TERMS_VERSION = "2026-10-21-v1.2"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
WF_ID_TYPE = "BIGSERIAL" if DATABASE_URL else "INTEGER"
DB = os.environ.get("SKILLVAYA_DB_PATH", os.path.join(ROOT, "skillvaya.sqlite3"))

# Never allow a hosted service to silently fall back to ephemeral SQLite.
if os.environ.get("PORT") and not DATABASE_URL and os.environ.get("SKILLVAYA_ALLOW_EPHEMERAL_STAGING_SQLITE", "").lower() != "true":
    raise RuntimeError("Hosted Skillvaya startup blocked: set DATABASE_URL to the PostgreSQL connection string. SQLite is allowed on a hosted service only when the explicit isolated-staging flag is enabled.")

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

    # Opening a hosted-PostgreSQL connection costs a full network/TLS handshake (about a second from a
    # distant region), and every request used to open several. Keep a few warm connections and reuse them.
    _PG_POOL = []
    _PG_POOL_LOCK = threading.Lock()
    _PG_POOL_MAX = 6
    _PG_POOL_ENABLED = os.environ.get("SKILLVAYA_DB_POOL", "on").strip().lower() != "off"

    _PG_IDLE = psycopg.pq.TransactionStatus.IDLE
    try: _PG_PIPELINE = bool(psycopg.Pipeline.is_supported())
    except Exception: _PG_PIPELINE = False
    def _pg_is_read(sql):
        head = sql.lstrip()[:12].upper()
        return head.startswith(("SELECT", "SHOW ", "EXPLAIN"))

    class PgConnection:
        def __init__(self, raw, pooled=False):
            self.raw = raw
            self._pooled = pooled
            self._released = False
            self._used = False
        def _run(self, sql, params):
            # SV76-PERF-01: the connection is in autocommit mode, so a plain SELECT is exactly one network round trip
            # (psycopg's implicit BEGIN and COMMIT used to add two more, each costing a full trip to the hosted database).
            # The first write opens an explicit transaction that stays open until commit()/rollback()/close().
            if self.raw.info.transaction_status == _PG_IDLE and not _pg_is_read(sql):
                self.raw.execute("BEGIN")
            return self.raw.execute(sql, params)
        def execute(self, sql, params=()):
            sql = sql.replace("?", "%s")
            try:
                return self._run(sql, params)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                # A pooled connection the server dropped while idle (compute suspend/restart): the very first
                # statement is safe to replay on a fresh connection. Never retry mid-transaction.
                if not (self._pooled and _PG_POOL_ENABLED) or self._used:
                    raise
                try: self.raw.close()
                except Exception: pass
                self.raw = _new_pg_connection()
                return self._run(sql, params)
            finally:
                self._used = True
        def commit(self):
            if self.raw.info.transaction_status != _PG_IDLE: return self.raw.commit()
        def rollback(self):
            if self.raw.info.transaction_status != _PG_IDLE: return self.raw.rollback()
        def _redo(self, fn):
            try:
                return fn()
            except (psycopg.OperationalError, psycopg.InterfaceError):
                if not (self._pooled and _PG_POOL_ENABLED) or self._used: raise
                try: self.raw.close()
                except Exception: pass
                self.raw = _new_pg_connection()
                return fn()
            finally:
                self._used = True
        def execute_atomic(self, sql, params=()):
            # SV76-PERF-02: one statement = one round trip, atomic on its own (no BEGIN/COMMIT). Only for single writes.
            sql = sql.replace("?", "%s")
            return self._redo(lambda: self.raw.execute(sql, params))
        def execute_batch(self, statements):
            # SV76-PERF-02: several independent READ statements in ONE network round trip (psycopg pipeline mode).
            stmts = [(s.replace("?", "%s"), p) for s, p in statements]
            def run():
                if not _PG_PIPELINE:
                    return [self.raw.execute(s, p).fetchall() for s, p in stmts]
                with self.raw.pipeline():
                    cursors = [self.raw.execute(s, p) for s, p in stmts]
                return [cur.fetchall() for cur in cursors]
            return self._redo(run)
        def close(self):
            if self._released: return None
            self._released = True
            raw = self.raw
            if not (self._pooled and _PG_POOL_ENABLED):
                return raw.close()
            try:
                if raw.closed or raw.broken:
                    return raw.close()
                if raw.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                    raw.rollback()
                with _PG_POOL_LOCK:
                    if len(_PG_POOL) < _PG_POOL_MAX:
                        _PG_POOL.append((raw, time.monotonic()))
                        return None
            except Exception:
                pass
            try: raw.close()
            except Exception: pass
            return None

    def _new_pg_connection():
        raw = psycopg.connect(DATABASE_URL, row_factory=hybrid_row, connect_timeout=15, autocommit=True,
                              keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)
        # Long-lived connections must not auto-prepare statements (breaks behind PgBouncer-style poolers).
        raw.prepare_threshold = None
        return raw

    def connect_db():
        if not _PG_POOL_ENABLED:
            return PgConnection(psycopg.connect(DATABASE_URL, row_factory=hybrid_row, autocommit=True))
        while True:
            with _PG_POOL_LOCK:
                item = _PG_POOL.pop() if _PG_POOL else None
            if item is None:
                return PgConnection(_new_pg_connection(), pooled=True)
            raw, idle_since = item
            try:
                if raw.closed or raw.broken: continue
                if time.monotonic() - idle_since > 20:
                    raw.execute("SELECT 1"); raw.rollback()
                return PgConnection(raw, pooled=True)
            except Exception:
                try: raw.close()
                except Exception: pass
else:
    DBIntegrityError = sqlite3.IntegrityError
    def connect_db():
        c = sqlite3.connect(DB, timeout=15)
        c.row_factory = sqlite3.Row
        return c

def db_atomic(c, sql, params=()):
    """Run ONE write as a single round trip on PostgreSQL (autocommit); plain execute on SQLite."""
    f = getattr(c, "execute_atomic", None)
    return f(sql, params) if f else c.execute(sql, params)

def db_batch(c, statements):
    """Run independent read statements in one round trip on PostgreSQL; sequentially on SQLite. Returns one row list per statement."""
    f = getattr(c, "execute_batch", None)
    if f: return f(statements)
    return [c.execute(s, p).fetchall() for s, p in statements]

def fcm_send_to_user(user_id, title, body, data=None):
    """Send a visible high-priority Android call notification; never block call signalling."""
    # SV78-WEBPUSH-01: browsers (iPhone home-screen app, computers, other phones) get the same alert.
    try: webpush_send_async(user_id, title, body, data)
    except Exception as exc: print("Web push scheduling failed:", type(exc).__name__)
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        print("FCM unavailable: FIREBASE_SERVICE_ACCOUNT_JSON is not configured")
        return 0
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
        try:
            firebase_admin.get_app("skillvaya_fcm")
        except ValueError:
            info = json.loads(raw)
            firebase_admin.initialize_app(credentials.Certificate(info), name="skillvaya_fcm")
        app = firebase_admin.get_app("skillvaya_fcm")
        with conn() as c:
            rows = c.execute(
                "SELECT token FROM push_device_tokens WHERE user_id=? AND enabled=1",
                (int(user_id),)
            ).fetchall()
    except Exception as exc:
        print("FCM initialization/token lookup failed:", type(exc).__name__)
        return 0

    is_call = (data or {}).get("type") == "incoming_call"
    if not rows:
        print("FCM no active device tokens for user", int(user_id), "type", "call" if is_call else "message")
        return 0

    sent = 0
    for row in rows:
        token = str(row["token"] or "").strip()
        if not token:
            continue
        payload = {str(k): str(v)[:500] for k, v in (data or {}).items() if v is not None}
        payload["title"] = str(title)[:100]
        payload["body"] = str(body)[:220]
        try:
            if is_call:
                # Combined notification + data is intentional: when Skillvaya is backgrounded,
                # Android itself places the call alert in the system tray even if the app
                # process is sleeping. The dedicated native channel supplies the ringtone.
                message = messaging.Message(
                    token=token,
                    notification=messaging.Notification(title=str(title)[:100], body=str(body)[:220]),
                    data=payload,
                    android=messaging.AndroidConfig(
                        priority="high",
                        ttl=datetime.timedelta(seconds=30),
                        notification=messaging.AndroidNotification(
                            channel_id="skillvaya_incoming_calls_v2",
                            priority="max",
                            default_sound=True,
                            default_vibrate_timings=True,
                            visibility="public",
                        ),
                    ),
                )
            else:
                # Preserve the existing chat-push behavior.
                message = messaging.Message(
                    token=token,
                    data=payload,
                    android=messaging.AndroidConfig(priority="high", ttl=datetime.timedelta(seconds=300)),
                )
            message_id = messaging.send(message, app=app)
            sent += 1
            print("FCM accepted", "call" if is_call else "message", "push for user", int(user_id), "message_id", message_id)
        except messaging.UnregisteredError:
            with conn() as c:
                c.execute(
                    "UPDATE push_device_tokens SET enabled=0,updated_at=? WHERE token=?",
                    (now(), token)
                )
            print("FCM removed unregistered device token for user", int(user_id))
        except Exception as exc:
            # Never log credentials or tokens. Keep enough detail to diagnose Firebase rejects.
            print("FCM send failed", "call" if is_call else "message", "user", int(user_id), type(exc).__name__)
    if sent == 0:
        print("FCM delivered no messages for user", int(user_id), "type", "call" if is_call else "message")
    return sent

def fcm_send_async(user_id, title, body, data=None):
    """Push in the background so the sender's request never waits on Firebase."""
    def run():
        try: fcm_send_to_user(user_id, title, body, data)
        except Exception as exc: print("FCM background send failed:", type(exc).__name__)
    threading.Thread(target=run, name="skillvaya-fcm-send", daemon=True).start()
def fcm_prewarm():
    """Import and initialise Firebase once at startup so the first real push is not slow."""
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw: return
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
        try: firebase_admin.get_app("skillvaya_fcm")
        except ValueError: firebase_admin.initialize_app(credentials.Certificate(json.loads(raw)), name="skillvaya_fcm")
        print("FCM ready", flush=True)
    except Exception as exc:
        print("FCM prewarm skipped:", type(exc).__name__, flush=True)
def ensure_push_token_table():
    with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS push_device_tokens (token TEXT PRIMARY KEY, user_id BIGINT NOT NULL, platform TEXT NOT NULL DEFAULT 'android', enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")

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
"Builders & construction","Plumbers","Electricians","Painters & decorators","Mechanics & automotive","Cleaning & housekeeping","Gardening & landscaping","Roofing & waterproofing","Carpenters & furniture","Welders & fabricators","Appliance repairs","IT & computer support","Graphic designers","Artists & photographers","Marketing & advertising","Web & software developers","Lawyers & legal services","Private doctors & clinics","Dentists & specialists","Nurses & home care","Accountants & tax","Financial & insurance services","Real estate & property","Tutors & education","Beauty & hair","Catering & chefs","Transport & removals","Security services","Events & entertainment","Tailors & fashion","Arts & crafts","Pet care & veterinary","Funeral services","Engineering & consulting","Other professional services","Doctors","Nurses","Mechanics","Gardeners",
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
"Civil engineers","Electrical engineers","Mechanical engineers","Environmental consultants","Surveyors","Interior designers","Signage & printing","Craftspeople","Handmade crafts & gifts","Pottery & ceramics","Jewellery makers","Textile arts & weaving","Knitting & crochet","Woodcraft & carving","Leathercraft","Candle & soap makers","Artisan makers","Art & craft workshops","Pet groomers","Dog walkers","Animal trainers"
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
    "Civil engineers": {"Engineering & consulting"}, "Electrical engineers": {"Engineering & consulting", "Electricians"}, "Mechanical engineers": {"Engineering & consulting"}, "Environmental consultants": {"Engineering & consulting"}, "Surveyors": {"Engineering & consulting"}, "Interior designers": {"Painters & decorators", "Graphic designers"}, "Signage & printing": {"Graphic designers", "Marketing & advertising"}, "Craftspeople": {"Arts & crafts", "Artists & photographers"}, "Handmade crafts & gifts": {"Arts & crafts"}, "Pottery & ceramics": {"Arts & crafts"}, "Jewellery makers": {"Arts & crafts"}, "Textile arts & weaving": {"Arts & crafts"}, "Knitting & crochet": {"Arts & crafts"}, "Woodcraft & carving": {"Arts & crafts"}, "Leathercraft": {"Arts & crafts"}, "Candle & soap makers": {"Arts & crafts"}, "Artisan makers": {"Arts & crafts"}, "Art & craft workshops": {"Arts & crafts"}, "Pet groomers": {"Pet care & veterinary"}, "Dog walkers": {"Pet care & veterinary"}, "Animal trainers": {"Pet care & veterinary"},
}

SKILLVAYA_CATEGORY_SERVICES = {
    "Graphic designers": {"Graphic Design", "Branding & Identity", "UI/UX Design"},
    "Artists & photographers": {"Graphic Design", "Branding & Identity", "UI/UX Design"},
    "Marketing & advertising": {"Branding & Identity", "Graphic Design", "Web Design"},
    "Web & software developers": {"Web Design", "Website Development", "Coding & Custom Software", "Android Apps", "AI Solutions", "UI/UX Design", "Testing & Debugging"},
    "IT & computer support": {"IT Support & Troubleshooting", "Testing & Debugging", "Coding & Custom Software", "Android Apps", "AI Solutions"},
    "Other professional services": {"IT Support & Troubleshooting", "Testing & Debugging", "AI Solutions", "Coding & Custom Software"},
}
def category_matches(requested, stored):
    return requested == "All categories" or stored == requested or stored in CATEGORY_ALIASES.get(requested, set())
def skillvaya_matches_category(requested, business):
    if requested == "All categories":
        return False
    name = str(business.get("name") or "").strip().casefold()
    if name != "skillvaya digital & creative studio".casefold():
        return False
    return requested in SKILLVAYA_CATEGORY_SERVICES
def category_search_terms(stored):
    aliases = [name for name, targets in CATEGORY_ALIASES.items() if stored in targets]
    return " ".join([stored, *aliases])
PLANS = {"local":{"name":"Local","monthly":105},"priority":{"name":"Priority","monthly":210},"plus":{"name":"Business Plus","monthly":500},"spotlight":{"name":"Business Spotlight","monthly":1000}}
PROVIDER_TIER_RANKS = {"local":0,"priority":1,"plus":2,"spotlight":3}
def subscription_test_tier(user, query=None, data=None):
    """Resolve an explicit owner-only tier preview; public provider roles cannot override entitlements."""
    if not user or user.get("role") != "admin":
        return None
    q=query or {}
    candidate=None
    if "test_tier" in q:
        value=q.get("test_tier")
        candidate=value[0] if isinstance(value,(list,tuple)) and value else value
    if not candidate:
        candidate=(data or {}).get("test_tier")
    candidate=str(candidate or "").strip().lower()
    return candidate if candidate in PROVIDER_TIER_RANKS else None
def subscription_test_business_id(owner_user_id, tier):
    return -(abs(int(owner_user_id))*1000 + PROVIDER_TIER_RANKS[str(tier).lower()] + 1)
def subscription_test_user_id(owner_user_id, tier):
    return -(abs(int(owner_user_id))*1000 + 101 + PROVIDER_TIER_RANKS[str(tier).lower()])
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
def delete_account_data(c, user_id, request_id=None):
    """Delete account-linked personal data transactionally; retain only minimized financial/audit records."""
    user_id = int(user_id)
    user = c.execute("SELECT id, role FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        raise ValueError("Account no longer exists.")
    if user["role"] == "admin":
        raise PermissionError("Owner/admin accounts are protected from account deletion.")
    business_ids = [int(r["id"]) for r in c.execute("SELECT id FROM businesses WHERE user_id=?", (user_id,)).fetchall()]
    bids = business_ids
    def delete_where(table, where, params):
        try:
            cols = table_columns(c, table)
        except Exception:
            return
        if cols:
            c.execute("DELETE FROM " + table + " WHERE " + where, tuple(params))
    def update_where(table, sql, params):
        try:
            cols = table_columns(c, table)
        except Exception:
            return
        if cols:
            c.execute(sql, tuple(params))
    def anonymize_payments(condition, params):
        try:
            cols = set(table_columns(c, "payments"))
        except Exception:
            return
        assignments=[]
        if "user_id" in cols: assignments.append("user_id=0")
        if "business_id" in cols: assignments.append("business_id=NULL")
        for col in ("pf_payment_id","paypal_order_id","paypal_capture_id"):
            if col in cols: assignments.append(col+"=NULL")
        if assignments:
            c.execute("UPDATE payments SET "+",".join(assignments)+" WHERE "+condition, tuple(params))
    # Remove content created by, addressed to, or stored for this account.
    delete_where("analytics", "user_id=?", [user_id])
    delete_where("password_reset_tokens", "user_id=?", [user_id])
    delete_where("auth_sessions", "user_id=?", [user_id])
    delete_where("customer_marketing_preferences", "user_id=?", [user_id])
    delete_where("platform_ratings", "rater_id=?", [user_id])
    delete_where("webpush_subscriptions", "user_id=?", [user_id])
    delete_where("futurechat_waitlist", "user_id=?", [user_id])
    delete_where("favorites", "customer_id=?", [user_id])
    delete_where("contacts", "customer_id=?", [user_id])
    delete_where("ratings", "rater_id=? OR target_user_id=?", [user_id, user_id])
    delete_where("provider_quote_templates", "user_id=?", [user_id])
    delete_where("provider_campaigns", "user_id=?", [user_id])
    delete_where("provider_bookings", "user_id=? OR customer_id=?", [user_id, user_id])
    delete_where("provider_invoices", "user_id=? OR customer_id=?", [user_id, user_id])
    delete_where("provider_customer_notes", "user_id=? OR customer_id=?", [user_id, user_id])
    delete_where("provider_followups", "user_id=? OR customer_id=?", [user_id, user_id])
    delete_where("provider_review_replies", "user_id=?", [user_id])
    delete_where("provider_service_packages", "user_id=?", [user_id])
    delete_where("provider_team_members", "owner_user_id=? OR user_id=?", [user_id, user_id])
    delete_where("provider_job_assignments", "owner_user_id=?", [user_id])
    delete_where("provider_offers", "user_id=?", [user_id])
    delete_where("provider_marketing_events", "user_id=? OR customer_id=?", [user_id, user_id])
    delete_where("provider_announcements", "user_id=?", [user_id])
    delete_where("provider_automation_rules", "user_id=?", [user_id])
    delete_where("provider_notifications", "user_id=?", [user_id])
    # Remove conversations and their media, including every conversation attached to a deleted provider listing.
    if bids:
        marks = ",".join("?" for _ in bids)
        calls = c.execute("SELECT id FROM video_calls WHERE caller_id=? OR callee_id=? OR customer_id=? OR business_id IN ("+marks+")",
                          tuple([user_id, user_id, user_id] + bids)).fetchall()
    else:
        calls = c.execute("SELECT id FROM video_calls WHERE caller_id=? OR callee_id=? OR customer_id=?", (user_id, user_id, user_id)).fetchall()
    call_ids = [str(r["id"]) for r in calls]
    if call_ids:
        marks = ",".join("?" for _ in call_ids)
        delete_where("video_call_signals", "call_id IN ("+marks+")", call_ids)
        delete_where("video_calls", "id IN ("+marks+")", call_ids)
    if bids:
        marks = ",".join("?" for _ in bids)
        where = "customer_id=? OR sender_id=? OR business_id IN ("+marks+")"
        params = [user_id, user_id] + bids
        msgrows = c.execute("SELECT id FROM messages WHERE "+where, tuple(params)).fetchall()
        msgids = [int(r["id"]) for r in msgrows]
        if msgids:
            imarks = ",".join("?" for _ in msgids)
            delete_where("message_attachments", "message_id IN ("+imarks+") OR customer_id=? OR sender_id=? OR business_id IN ("+marks+")", msgids+[user_id,user_id]+bids)
        else:
            delete_where("message_attachments", "customer_id=? OR sender_id=? OR business_id IN ("+marks+")", [user_id,user_id]+bids)
        delete_where("messages", where, params)
        delete_where("enquiries", "customer_id=? OR business_id IN ("+marks+")", [user_id]+bids)
        jobrows = c.execute("SELECT id FROM job_requests WHERE customer_id=? OR business_id IN ("+marks+")", tuple([user_id]+bids)).fetchall()
        jobids = [int(r["id"]) for r in jobrows]
        if jobids:
            jmarks = ",".join("?" for _ in jobids)
            delete_where("job_quotes", "job_id IN ("+jmarks+") OR business_id IN ("+marks+") OR provider_id=?", jobids+bids+[user_id])
        else:
            delete_where("job_quotes", "business_id IN ("+marks+") OR provider_id=?", bids+[user_id])
        delete_where("job_requests", "customer_id=? OR business_id IN ("+marks+")", [user_id]+bids)
        delete_where("complaints", "customer_id=? OR business_id IN ("+marks+")", [user_id]+bids)
        delete_where("subscriptions", "user_id=? OR business_id IN ("+marks+")", [user_id]+bids)
        delete_where("contacts", "business_id IN ("+marks+")", bids)
        delete_where("favorites", "business_id IN ("+marks+")", bids)
        delete_where("ratings", "business_id IN ("+marks+")", bids)
        # Purchase tokens are account-linked credentials for subscription management; remove them with the deleted account.
        delete_where("google_play_subscriptions", "user_id=? OR business_id IN ("+marks+")", [user_id]+bids)
        # Keep bookkeeping rows only where needed, but remove direct account/business linkage and gateway identifiers.
        anonymize_payments("user_id=? OR business_id IN ("+marks+")", [user_id]+bids)
        update_where("owner_promotions", "UPDATE owner_promotions SET directory_business_id=NULL WHERE directory_business_id IN ("+marks+")", bids)
        delete_where("businesses", "user_id=?", [user_id])
    else:
        delete_where("message_attachments", "customer_id=? OR sender_id=?", [user_id, user_id])
        delete_where("enquiries", "customer_id=?", [user_id])
        delete_where("messages", "customer_id=? OR sender_id=?", [user_id, user_id])
        delete_where("job_requests", "customer_id=?", [user_id])
        delete_where("job_quotes", "provider_id=?", [user_id])
        delete_where("complaints", "customer_id=?", [user_id])
        delete_where("subscriptions", "user_id=?", [user_id])
        delete_where("google_play_subscriptions", "user_id=?", [user_id])
        anonymize_payments("user_id=?", [user_id])
    if request_id is not None:
        delete_where("notifications", "kind='account_deletion_request' AND body LIKE ?", ["%Request ID: "+str(int(request_id))+".%"])
        cur = c.execute("UPDATE account_deletion_requests SET status='completed',user_email='',reason='',reviewed_at=?,review_notes='Account and associated app data deleted; minimized payment ledger retained where required.' WHERE id=? AND user_id=? AND status='pending'", (now(), int(request_id), user_id))
        if getattr(cur, "rowcount", 1) == 0:
            raise ValueError("Deletion request is not pending; no account data was deleted.")
    else:
        delete_where("account_deletion_requests", "user_id=?", [user_id])
    delete_where("owner_account_access", "user_id=?", [user_id])
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    return {"businesses_removed": len(bids), "payment_records_retained_minimized": True}


def init():
    # Public deployments must provide a dedicated owner identity and a strong password.
    # This prevents a fresh public database from having no way to authenticate its owner.
    if os.environ.get("PORT"):
        owner_email = os.environ.get("SKILLVAYA_OWNER_EMAIL", "").strip().lower()
        owner_password = os.environ.get("SKILLVAYA_OWNER_PASSWORD", "")
        if "@" not in owner_email or len(owner_password) < 14:
            raise RuntimeError("Public deployment blocked: set SKILLVAYA_OWNER_EMAIL and a unique SKILLVAYA_OWNER_PASSWORD of at least 14 characters before starting Skillvaya.")
    expected_database = os.environ.get("SKILLVAYA_EXPECTED_DATABASE", "").strip()
    if expected_database:
        if not DATABASE_URL:
            raise RuntimeError("Database safety check failed: an expected PostgreSQL database was configured, but DATABASE_URL is missing.")
        with conn() as guard_conn:
            actual_database = str(guard_conn.execute("SELECT current_database() AS name").fetchone()["name"])
        if actual_database != expected_database:
            raise RuntimeError("Database safety check failed: this service is connected to a database other than its configured isolated staging database. No schema initialization was performed.")
    with conn() as c:
        execute_script(c, """
        CREATE TABLE IF NOT EXISTS users(id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'customer', created_at TEXT NOT NULL, phone TEXT DEFAULT '', accepted_terms_version TEXT NOT NULL DEFAULT '', accepted_terms_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS password_reset_tokens(id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS businesses(id BIGSERIAL PRIMARY KEY, user_id INTEGER, name TEXT NOT NULL, category TEXT NOT NULL, area TEXT NOT NULL, phone TEXT NOT NULL, email TEXT, website TEXT, description TEXT NOT NULL, photos TEXT DEFAULT '', plan TEXT NOT NULL DEFAULT 'local', billing TEXT NOT NULL DEFAULT 'monthly', status TEXT NOT NULL DEFAULT 'pending', payment_status TEXT NOT NULL DEFAULT 'unpaid', rating REAL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS enquiries(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, customer_id INTEGER NOT NULL, message TEXT NOT NULL, status TEXT DEFAULT 'new', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, customer_id INTEGER NOT NULL, sender_id INTEGER NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT);
        CREATE TABLE IF NOT EXISTS message_attachments(
            id BIGSERIAL PRIMARY KEY, message_id BIGINT NOT NULL, business_id BIGINT NOT NULL,
            customer_id BIGINT NOT NULL, sender_id BIGINT NOT NULL, filename TEXT NOT NULL,
            mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, data_base64 TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS video_calls(
            id TEXT PRIMARY KEY, business_id BIGINT NOT NULL, customer_id BIGINT NOT NULL,
            caller_id BIGINT NOT NULL, callee_id BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'ringing',
            offer_sdp TEXT NOT NULL DEFAULT '', answer_sdp TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, ended_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS video_call_signals(
            id BIGSERIAL PRIMARY KEY, call_id TEXT NOT NULL, sender_id BIGINT NOT NULL,
            kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_quote_templates(
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, name TEXT NOT NULL,
            eta TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_campaigns(
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, business_id BIGINT NOT NULL DEFAULT 0,
            title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            starts_on TEXT NOT NULL DEFAULT '', ends_on TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_bookings(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            customer_id BIGINT, customer_name TEXT NOT NULL DEFAULT '', customer_contact TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', starts_at TEXT NOT NULL, ends_at TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'scheduled', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_invoices(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            job_id BIGINT, customer_id BIGINT, invoice_number TEXT NOT NULL UNIQUE,
            customer_name TEXT NOT NULL, customer_email TEXT NOT NULL DEFAULT '', description TEXT NOT NULL,
            amount_cents BIGINT NOT NULL, amount_paid_cents BIGINT NOT NULL DEFAULT 0,
            due_date TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, paid_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS provider_customer_notes(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL, customer_id BIGINT NOT NULL,
            notes TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(business_id,customer_id)
        );
        CREATE TABLE IF NOT EXISTS provider_followups(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            job_id BIGINT NOT NULL, customer_id BIGINT NOT NULL, remind_at TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_review_replies(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            rating_id BIGINT NOT NULL UNIQUE, reply TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_service_packages(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', price_cents BIGINT NOT NULL,
            add_ons TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_team_members(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, owner_user_id BIGINT NOT NULL,
            user_id BIGINT, name TEXT NOT NULL, email TEXT NOT NULL, team_role TEXT NOT NULL DEFAULT 'staff',
            permissions TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'invited',
            invite_code TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(business_id,email)
        );
        CREATE TABLE IF NOT EXISTS provider_job_assignments(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, owner_user_id BIGINT NOT NULL,
            job_id BIGINT NOT NULL, team_member_id BIGINT NOT NULL, note TEXT NOT NULL DEFAULT '',
            due_date TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'assigned',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(job_id,team_member_id)
        );
        CREATE TABLE IF NOT EXISTS provider_offers(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            title TEXT NOT NULL, code TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            discount_type TEXT NOT NULL DEFAULT 'percent', discount_value NUMERIC NOT NULL DEFAULT 0,
            starts_on TEXT NOT NULL DEFAULT '', ends_on TEXT NOT NULL DEFAULT '',
            usage_limit INTEGER NOT NULL DEFAULT 0, usage_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(business_id,code)
        );
        CREATE TABLE IF NOT EXISTS provider_marketing_events(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            campaign_id BIGINT, event_type TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'directory',
            customer_id BIGINT, visitor_key TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_announcements(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            title TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
            recipient_count INTEGER NOT NULL DEFAULT 0, published_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS customer_marketing_preferences(
            user_id BIGINT PRIMARY KEY, opted_in INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_automation_rules(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            rule_key TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, config_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL, UNIQUE(business_id,rule_key)
        );
        CREATE TABLE IF NOT EXISTS provider_notifications(
            id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
            reference_key TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL, read_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS contacts(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, customer_id INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(business_id,customer_id));
        CREATE TABLE IF NOT EXISTS ratings(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, rater_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_user_id INTEGER NOT NULL, stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5), created_at TEXT NOT NULL, UNIQUE(business_id,rater_id,target_type,target_user_id));
        CREATE TABLE IF NOT EXISTS webpush_subscriptions(endpoint TEXT PRIMARY KEY, user_id BIGINT NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL, user_agent TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS webpush_keys(id INTEGER PRIMARY KEY, private_pem TEXT NOT NULL, public_key TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS futurechat_waitlist(user_id BIGINT PRIMARY KEY, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS geo_cache(q TEXT PRIMARY KEY, lat REAL, lng REAL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS platform_ratings(id BIGSERIAL PRIMARY KEY, rater_id INTEGER NOT NULL UNIQUE, stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5), created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS complaints(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, customer_id INTEGER NOT NULL, reason TEXT NOT NULL, evidence TEXT DEFAULT '', status TEXT DEFAULT 'open', priority TEXT DEFAULT 'normal', created_at TEXT NOT NULL, admin_note TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS payments(id BIGSERIAL PRIMARY KEY, user_id INTEGER NOT NULL, business_id INTEGER, plan TEXT NOT NULL, billing TEXT NOT NULL, amount INTEGER NOT NULL, reference TEXT NOT NULL UNIQUE, status TEXT DEFAULT 'pending', created_at TEXT NOT NULL, verified_at TEXT, pf_payment_id TEXT, refunded_amount INTEGER NOT NULL DEFAULT 0, refund_status TEXT NOT NULL DEFAULT 'none');
        CREATE TABLE IF NOT EXISTS analytics(id BIGSERIAL PRIMARY KEY, event TEXT NOT NULL, user_id INTEGER, detail TEXT DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS account_deletion_requests(id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, user_email TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', requested_at TEXT NOT NULL, reviewed_at TEXT DEFAULT '', review_notes TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS notifications(id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL, emailed_at TEXT, recipient TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS broadcast_notifications(id BIGSERIAL PRIMARY KEY, subject TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, created_by BIGINT, active BOOLEAN NOT NULL DEFAULT TRUE);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS auth_sessions(token TEXT PRIMARY KEY, user_id BIGINT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS google_play_subscriptions(purchase_token TEXT PRIMARY KEY,user_id BIGINT NOT NULL,business_id BIGINT,product_id TEXT NOT NULL,base_plan_id TEXT NOT NULL,order_id TEXT,state TEXT NOT NULL,expiry_time TEXT NOT NULL,auto_renew_enabled BOOLEAN NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS subscriptions(id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, user_id INTEGER NOT NULL, plan TEXT NOT NULL, billing TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', started_at TEXT NOT NULL, expires_at TEXT NOT NULL, cancelled_at TEXT, UNIQUE(business_id));
        CREATE TABLE IF NOT EXISTS job_requests(
            id BIGSERIAL PRIMARY KEY, customer_id INTEGER NOT NULL, business_id INTEGER NOT NULL,
            title TEXT NOT NULL, description TEXT NOT NULL, area TEXT NOT NULL DEFAULT '',
            preferred_date TEXT NOT NULL DEFAULT '', budget_cents INTEGER, status TEXT NOT NULL DEFAULT 'requested',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_quotes(
            id BIGSERIAL PRIMARY KEY, job_id INTEGER NOT NULL, business_id INTEGER NOT NULL,
            provider_id INTEGER NOT NULL, amount_cents INTEGER NOT NULL, eta TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
            UNIQUE(job_id,business_id)
        );
        CREATE TABLE IF NOT EXISTS favorites(
            id BIGSERIAL PRIMARY KEY, customer_id INTEGER NOT NULL, business_id INTEGER NOT NULL,
            created_at TEXT NOT NULL, UNIQUE(customer_id,business_id)
        );
        CREATE TABLE IF NOT EXISTS owner_promotions(
            id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'ad',
            business_name TEXT NOT NULL, title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Other professional services',
            description TEXT NOT NULL, target_url TEXT NOT NULL DEFAULT '',
            image_url TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
            owner_free INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            directory_business_id BIGINT
        );
        """)
        opcols=table_columns(c, "owner_promotions")
        if "directory_business_id" not in opcols:
            c.execute("ALTER TABLE owner_promotions ADD COLUMN directory_business_id BIGINT")
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
        # SV79: town-level location (never returned to customers), availability and owner verification.
        for _col,_ddl in (("lat","REAL"),("lng","REAL"),("available_on","TEXT NOT NULL DEFAULT ''"),("verified_at","TEXT NOT NULL DEFAULT ''"),("verify_requested_at","TEXT NOT NULL DEFAULT ''")):
            if _col not in cols: c.execute("ALTER TABLE businesses ADD COLUMN "+_col+" "+_ddl)
        # SV81-WORLD: every listing and account has a country; existing ones are South African.
        if "country" not in cols: c.execute("ALTER TABLE businesses ADD COLUMN country TEXT NOT NULL DEFAULT 'ZA'")
        if "country" not in table_columns(c, "users"): c.execute("ALTER TABLE users ADD COLUMN country TEXT NOT NULL DEFAULT ''")
        pcols=table_columns(c, "payments")
        if "pf_payment_id" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN pf_payment_id TEXT")
        if "refunded_amount" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN refunded_amount INTEGER NOT NULL DEFAULT 0")
        if "refund_status" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN refund_status TEXT NOT NULL DEFAULT 'none'")
        if "paypal_currency" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN paypal_currency TEXT NOT NULL DEFAULT 'USD'")
        if "paypal_amount" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN paypal_amount TEXT")
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
        # Link legacy owner business promotions to their directory listing so Pause/Delete
        # applies to both records instead of leaving a supposedly paused listing public.
        admin_row=c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
        admin_id=admin_row["id"] if admin_row else 0
        legacy_promos=c.execute("SELECT id,business_name,category,status FROM owner_promotions WHERE kind='business' AND directory_business_id IS NULL ORDER BY id").fetchall()
        for promo in legacy_promos:
            linked=c.execute("SELECT b.id FROM businesses b WHERE b.user_id IN (?,?) AND b.name=? AND b.category=? AND NOT EXISTS (SELECT 1 FROM owner_promotions op WHERE op.directory_business_id=b.id) ORDER BY CASE WHEN b.user_id=? THEN 0 ELSE 1 END,b.id DESC LIMIT 1",(admin_id,0,promo["business_name"],promo["category"],admin_id)).fetchone()
            if linked:
                c.execute("UPDATE owner_promotions SET directory_business_id=? WHERE id=?",(linked["id"],promo["id"]))
                directory_status={"active":"active","paused":"suspended","removed":"removed"}.get(promo["status"],"active")
                c.execute("UPDATE businesses SET status=? WHERE id=?",(directory_status,linked["id"]))

        # Owner-authorized, fee-exempt public studio listing. Idempotent across restarts.
        studio_name = "Skillvaya Digital & Creative Studio"
        studio_description = "Skillvaya Digital & Creative Studio helps individuals, entrepreneurs and businesses turn ideas into practical digital solutions. We design and develop websites, mobile applications, custom software, AI-powered tools and creative branding. Services include graphic design, logo design, branding and identity, website design and development, Android apps, coding, custom business software, AI solutions and integrations, UI/UX design, digital products, software testing, debugging, troubleshooting, technical planning and IT support. We focus on clear communication and practical solutions tailored to each client's needs."
        studio = c.execute("SELECT id FROM businesses WHERE name=? AND category=? ORDER BY id LIMIT 1", (studio_name, "Web & software developers")).fetchone()
        if not studio:
            cur = c.execute("INSERT INTO businesses(user_id,name,category,area,phone,email,website,description,photos,plan,billing,status,payment_status,rating,created_at,whatsapp) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (admin_id, studio_name, "Web & software developers", "Worldwide (Online & Remote)", "+27 83 787 45 69", "Skillvaya@gmail.com", "", studio_description, "", "local", "monthly", "active", "verified", 0, now(), "+27 83 787 45 69"))
            studio_id = cur.fetchone()["id"]
            c.execute("INSERT INTO owner_promotions(kind,business_name,title,category,description,target_url,image_url,status,owner_free,created_at,updated_at,directory_business_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("business", studio_name, studio_name, "Web & software developers", studio_description, "", "", "active", 1, now(), now(), studio_id))
        else:
            studio_id = studio["id"]
            # Keep owner-edited public profile fields intact across Render restarts.
            # Only reassert the owner's fee-exempt basic plan; never reset area, contacts,
            # website, description, or a deliberately paused/removed listing.
            c.execute("UPDATE businesses SET payment_status='verified',plan='local',billing='monthly' WHERE id=?", (studio_id,))
            promo = c.execute("SELECT id FROM owner_promotions WHERE directory_business_id=? LIMIT 1", (studio_id,)).fetchone()
            if not promo:
                c.execute("INSERT INTO owner_promotions(kind,business_name,title,category,description,target_url,image_url,status,owner_free,created_at,updated_at,directory_business_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("business", studio_name, studio_name, "Web & software developers", studio_description, "", "", "active", 1, now(), now(), studio_id))

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
# SV77-RESPONSE-01: "usually replies within ..." badge, from how fast a provider answers a customer's first unanswered message.
_SV_RESP_CACHE={"at":0.0,"data":{}}
_SV_NON_CHAT=("Video call invitation","Missed voice call","Missed video call")
def provider_response_labels(force=False):
    stamp=datetime.datetime.now(datetime.timezone.utc).timestamp()
    if not force and stamp-_SV_RESP_CACHE["at"]<600: return _SV_RESP_CACHE["data"]
    data={}
    try:
        since=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=90)).isoformat()
        with conn() as c:
            rows=c.execute("SELECT m.business_id,m.customer_id,m.sender_id,m.message,m.created_at,b.user_id AS owner_id FROM messages m JOIN businesses b ON b.id=m.business_id WHERE m.created_at>=? ORDER BY m.business_id,m.customer_id,m.created_at LIMIT 50000",(since,)).fetchall()
        waits={};pending={}
        for r in rows:
            if str(r["message"] or "") in _SV_NON_CHAT: continue
            key=(int(r["business_id"]),int(r["customer_id"]))
            try:
                t=datetime.datetime.fromisoformat(str(r["created_at"]))
                if t.tzinfo is None: t=t.replace(tzinfo=datetime.timezone.utc)
            except Exception: continue
            if int(r["sender_id"])==int(r["owner_id"] or 0):
                if key in pending: waits.setdefault(key[0],[]).append(max(0.0,(t-pending.pop(key)).total_seconds()))
            elif key not in pending: pending[key]=t
        for bid,xs in waits.items():
            if len(xs)<3: continue
            xs.sort(); med=xs[len(xs)//2]
            label="Usually replies within an hour" if med<=3600 else "Usually replies within a few hours" if med<=4*3600 else "Usually replies within a day" if med<=86400 else ""
            if label: data[bid]=label
    except Exception as exc:
        print("Response-time stats failed:", type(exc).__name__)
        return _SV_RESP_CACHE["data"]
    _SV_RESP_CACHE["at"]=stamp;_SV_RESP_CACHE["data"]=data
    return data
# SV77-MISSED-CALL-01: a call nobody answered is recorded in the chat and the person called gets a call-back reminder.
def sv_missed_call_notice(c, call):
    try:
        kind="video" if "m=video" in str(call.get("offer_sdp") or "") else "voice"
        caller=c.execute("SELECT name FROM users WHERE id=?",(int(call["caller_id"]),)).fetchone()
        name=(caller["name"] if caller else "") or "Your contact"
        q="INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)"
        p=(int(call["business_id"]),int(call["customer_id"]),int(call["caller_id"]),"Missed %s call"%kind,now())
        if "db_atomic" in globals(): db_atomic(c,q,p)
        else: c.execute(q,p)
        push=globals().get("fcm_send_async")
        if push: push(int(call["callee_id"]),"Missed call","Missed %s call from %s. Open Skillvaya to call back."%(kind,name),{"type":"missed_call","business_id":int(call["business_id"]),"customer_id":int(call["customer_id"])})
    except Exception as exc:
        print("Missed-call notice failed:", type(exc).__name__)
# SV78-WEBPUSH-01: browser push (iPhone home-screen app, computers, other phones) next to Firebase for the Android app.
# The server makes its own VAPID key pair once and keeps it in the database, so no secret is ever configured by hand.
_SV_WP={"vapid":None,"public":""}
_SV_WP_LOCK=threading.Lock()
def _sv_wp_host_ok(endpoint):
    try: u=urlparse(str(endpoint))
    except Exception: return False
    host=(u.hostname or "").lower()
    extra=[h.strip().lower() for h in os.environ.get("SKILLVAYA_WEBPUSH_TEST_HOSTS","").split(",") if h.strip()]
    if host and host in extra: return u.scheme in ("http","https")
    if u.scheme!="https": return False
    return host in ("fcm.googleapis.com","updates.push.services.mozilla.com","web.push.apple.com") or host.endswith(".push.services.mozilla.com") or host.endswith(".push.apple.com") or host.endswith(".notify.windows.com")
def webpush_keys():
    """(Vapid02, public key base64url) or (None,'') when web push is unavailable on this server."""
    if _SV_WP["vapid"] is not None: return _SV_WP["vapid"],_SV_WP["public"]
    try:
        from py_vapid import Vapid02
        from cryptography.hazmat.primitives import serialization
    except Exception:
        return None,""
    with _SV_WP_LOCK:
        if _SV_WP["vapid"] is not None: return _SV_WP["vapid"],_SV_WP["public"]
        try:
            with conn() as c:
                row=c.execute("SELECT private_pem,public_key FROM webpush_keys WHERE id=1").fetchone()
                if not row:
                    v=Vapid02(); v.generate_keys()
                    pem=v.private_pem().decode("ascii")
                    raw=v.public_key.public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
                    pub=base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
                    c.execute("INSERT INTO webpush_keys(id,private_pem,public_key,created_at) VALUES(1,?,?,?) ON CONFLICT(id) DO NOTHING",(pem,pub,now()))
                    row=c.execute("SELECT private_pem,public_key FROM webpush_keys WHERE id=1").fetchone()
            _SV_WP["vapid"]=Vapid02.from_pem(str(row["private_pem"]).encode("ascii"));_SV_WP["public"]=str(row["public_key"])
        except Exception as exc:
            print("Web push key setup failed:", type(exc).__name__)
            return None,""
    return _SV_WP["vapid"],_SV_WP["public"]
def webpush_send_to_user(user_id, title, body, data=None):
    """Visible notification to every browser where this user turned notifications on. Never raises."""
    try:
        from pywebpush import webpush, WebPushException
    except Exception:
        return 0
    vapid,_pub=webpush_keys()
    if not vapid: return 0
    try:
        with conn() as c:
            rows=c.execute("SELECT endpoint,p256dh,auth FROM webpush_subscriptions WHERE user_id=? AND enabled=1",(int(user_id),)).fetchall()
    except Exception as exc:
        print("Web push lookup failed:", type(exc).__name__); return 0
    payload={str(k):str(v)[:500] for k,v in (data or {}).items() if v is not None}
    payload["title"]=str(title)[:100]; payload["body"]=str(body)[:220]
    is_call=payload.get("type")=="incoming_call"
    sent=0
    for r in rows:
        ep=str(r["endpoint"])
        if not _sv_wp_host_ok(ep): continue
        try:
            webpush(subscription_info={"endpoint":ep,"keys":{"p256dh":str(r["p256dh"]),"auth":str(r["auth"])}},data=json.dumps(payload),
                    vapid_private_key=vapid,vapid_claims={"sub":"mailto:skillvaya@gmail.com"},ttl=30 if is_call else 3600,headers={"Urgency":"high"},timeout=10)
            sent+=1
        except WebPushException as exc:
            code=getattr(getattr(exc,"response",None),"status_code",0) or 0
            if code in (404,410):
                try:
                    with conn() as c: c.execute("UPDATE webpush_subscriptions SET enabled=0,updated_at=? WHERE endpoint=?",(now(),ep))
                except Exception: pass
            print("Web push rejected", code)
        except Exception as exc:
            print("Web push send failed:", type(exc).__name__)
    return sent
def webpush_send_async(user_id, title, body, data=None):
    threading.Thread(target=lambda: webpush_send_to_user(user_id,title,body,data),name="skillvaya-webpush",daemon=True).start()
# SV79: trust badges, near-me, availability, share links and the Future Chat launch list.
def sa_today():
    return (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=2)).date().isoformat()
# SV81-WORLD: countries, local currencies, local dates and same-value prices.
# Every paid plan is worth its rand price everywhere: abroad it is charged in local money at the day's exchange rate.
SV_COUNTRIES={
    "ZA":("South Africa","ZAR","27","Africa/Johannesburg",2),
    "GB":("United Kingdom","GBP","44","Europe/London",0),
    "US":("United States","USD","1","America/New_York",-5),
    "CA":("Canada","CAD","1","America/Toronto",-5),
    "AU":("Australia","AUD","61","Australia/Sydney",10),
    "IE":("Ireland","EUR","353","Europe/Dublin",0),
    "NZ":("New Zealand","NZD","64","Pacific/Auckland",12),
    "NA":("Namibia","NAD","264","Africa/Windhoek",2),
    "BW":("Botswana","BWP","267","Africa/Gaborone",2),
    "ZW":("Zimbabwe","USD","263","Africa/Harare",2),
    "ZM":("Zambia","ZMW","260","Africa/Lusaka",2),
    "MZ":("Mozambique","MZN","258","Africa/Maputo",2),
    "LS":("Lesotho","LSL","266","Africa/Maseru",2),
    "SZ":("Eswatini","SZL","268","Africa/Mbabane",2),
    "MW":("Malawi","MWK","265","Africa/Blantyre",2),
    "KE":("Kenya","KES","254","Africa/Nairobi",3),
    "NG":("Nigeria","NGN","234","Africa/Lagos",1),
    "GH":("Ghana","GHS","233","Africa/Accra",0),
    "UG":("Uganda","UGX","256","Africa/Kampala",3),
    "TZ":("Tanzania","TZS","255","Africa/Dar_es_Salaam",3),
    "RW":("Rwanda","RWF","250","Africa/Kigali",2),
    "ET":("Ethiopia","ETB","251","Africa/Addis_Ababa",3),
    "EG":("Egypt","EGP","20","Africa/Cairo",2),
    "MA":("Morocco","MAD","212","Africa/Casablanca",1),
    "SN":("Senegal","XOF","221","Africa/Dakar",0),
    "CI":("Ivory Coast","XOF","225","Africa/Abidjan",0),
    "CM":("Cameroon","XAF","237","Africa/Douala",1),
    "AO":("Angola","AOA","244","Africa/Luanda",1),
    "DE":("Germany","EUR","49","Europe/Berlin",1),
    "FR":("France","EUR","33","Europe/Paris",1),
    "ES":("Spain","EUR","34","Europe/Madrid",1),
    "PT":("Portugal","EUR","351","Europe/Lisbon",0),
    "IT":("Italy","EUR","39","Europe/Rome",1),
    "NL":("Netherlands","EUR","31","Europe/Amsterdam",1),
    "BE":("Belgium","EUR","32","Europe/Brussels",1),
    "CH":("Switzerland","CHF","41","Europe/Zurich",1),
    "AT":("Austria","EUR","43","Europe/Vienna",1),
    "SE":("Sweden","SEK","46","Europe/Stockholm",1),
    "NO":("Norway","NOK","47","Europe/Oslo",1),
    "DK":("Denmark","DKK","45","Europe/Copenhagen",1),
    "PL":("Poland","PLN","48","Europe/Warsaw",1),
    "IN":("India","INR","91","Asia/Kolkata",5.5),
    "PK":("Pakistan","PKR","92","Asia/Karachi",5),
    "PH":("Philippines","PHP","63","Asia/Manila",8),
    "SG":("Singapore","SGD","65","Asia/Singapore",8),
    "MY":("Malaysia","MYR","60","Asia/Kuala_Lumpur",8),
    "AE":("United Arab Emirates","AED","971","Asia/Dubai",4),
    "SA":("Saudi Arabia","SAR","966","Asia/Riyadh",3),
    "QA":("Qatar","QAR","974","Asia/Qatar",3),
    "BR":("Brazil","BRL","55","America/Sao_Paulo",-3),
    "MX":("Mexico","MXN","52","America/Mexico_City",-6),
    "AR":("Argentina","ARS","54","America/Argentina/Buenos_Aires",-3),
    "CO":("Colombia","COP","57","America/Bogota",-5),
    "CL":("Chile","CLP","56","America/Santiago",-4),
    "JP":("Japan","JPY","81","Asia/Tokyo",9),
    "HK":("Hong Kong","HKD","852","Asia/Hong_Kong",8),
    "ID":("Indonesia","IDR","62","Asia/Jakarta",7),
    "TR":("Turkey","TRY","90","Europe/Istanbul",3),
    "IL":("Israel","ILS","972","Asia/Jerusalem",2),
}
SV_PAYPAL_CURRENCIES={"AUD","BRL","CAD","CZK","DKK","EUR","HKD","HUF","ILS","JPY","MYR","MXN","TWD","NZD","NOK","PHP","PLN","GBP","SGD","SEK","CHF","THB","USD"}
SV_PLAY_ONLY="Provider plans are bought only in the Skillvaya Android app through Google Play."  # SV82-PLAY-ONLY
SV_ZERO_DECIMAL={"JPY","HUF","TWD"}
def sv_country(code):
    c=str(code or "").strip().upper()[:2]
    return c if c in SV_COUNTRIES else ""
def sv_currency(code):
    return SV_COUNTRIES[sv_country(code) or "ZA"][1]
def sv_user_country(user_id):
    try:
        with conn() as c:
            r=c.execute("SELECT country FROM users WHERE id=?",(int(user_id),)).fetchone()
        return sv_country(r["country"]) if r else ""
    except Exception: return ""
def sv_local_today(code):
    info=SV_COUNTRIES[sv_country(code) or "ZA"]
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(info[3])).date().isoformat()
    except Exception:
        return (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=info[4])).date().isoformat()
_SV_FX={"rates":None,"expires_at":0}
def sv_fx_rates():
    """Units of each currency per 1 US dollar (cached for an hour). SKILLVAYA_FX_RATES_JSON overrides for testing."""
    fixed=os.environ.get("SKILLVAYA_FX_RATES_JSON","").strip()
    if fixed: return {str(k).upper():float(v) for k,v in json.loads(fixed).items()}
    if _SV_FX["rates"] and _SV_FX["expires_at"]>time.time(): return _SV_FX["rates"]
    req=urllib.request.Request("https://open.er-api.com/v6/latest/USD",headers={"User-Agent":"Skillvaya/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=8) as res: fx=json.loads(res.read().decode() or "{}")
    rates={str(k).upper():float(v) for k,v in (fx.get("rates") or {}).items()}
    if fx.get("result")!="success" or rates.get("ZAR",0)<=0: raise ValueError("No exchange rates")
    _SV_FX.update({"rates":rates,"expires_at":time.time()+3600})
    return rates
def sv_zar_to(amount_zar, currency):
    """The same value as a rand amount, in another currency."""
    cur=str(currency or "ZAR").upper()
    if cur=="ZAR": return float(amount_zar)
    try:
        rates=sv_fx_rates(); zar=float(rates.get("ZAR") or 0); other=float(rates.get(cur) or 0)
    except Exception: zar=other=0
    if zar<=0 or other<=0: raise RuntimeError("Today's exchange rate for "+cur+" is unavailable; no payment has been started. Please try again shortly.")
    return float(amount_zar)*other/zar
def sv_paypal_currency(code):
    cur=sv_currency(code)
    return cur if cur in SV_PAYPAL_CURRENCIES else "USD"
def sv_paypal_amount(amount_zar, currency):
    cur=str(currency).upper(); dec=0 if cur in SV_ZERO_DECIMAL else 2
    if cur=="USD" and not os.environ.get("SKILLVAYA_FX_RATES_JSON","").strip(): value=float(amount_zar)/paypal_zar_per_usd()
    else: value=sv_zar_to(amount_zar,cur)
    return format(round(value+1e-9,dec),"."+str(dec)+"f")
def sv_i18n(lang):
    """SV82-I18N: on-screen wording for one language (i18n_data.py, built from the translation files)."""
    try:
        import i18n_data
        return i18n_data.VERSION, i18n_data.I18N.get(str(lang or "").lower()[:5], {})
    except Exception:
        return "none", {}
def _sv_km(a,b):
    import math
    la1,lo1,la2,lo2=map(math.radians,(a[0],a[1],b[0],b[1]))
    h=math.sin((la2-la1)/2)**2+math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 6371.0*2*math.asin(min(1.0,math.sqrt(h)))
_SV_GEO_LOCK=threading.Lock(); _SV_GEO_LAST=[0.0]
_SV_NO_GEO=("online","remote","worldwide","nationwide","anywhere")
def sv_geocode(area, country="ZA"):
    """Town-level coordinates for a service area (OpenStreetMap, cached in geo_cache). Never raises; None when unknown."""
    q=" ".join(str(area or "").split())[:120]
    if len(q)<2 or any(w in q.lower() for w in _SV_NO_GEO): return None
    cc=(sv_country(country) or "ZA").lower()
    key=q.lower() if cc=="za" else cc+":"+q.lower()
    try:
        with conn() as c:
            row=c.execute("SELECT lat,lng FROM geo_cache WHERE q=?",(key,)).fetchone()
        if row: return (float(row["lat"]),float(row["lng"])) if row["lat"] is not None else None
    except Exception: pass
    if os.environ.get("SKILLVAYA_GEOCODE","on").strip().lower()=="off": return None
    found=None
    for params in ({"q":q,"format":"json","limit":"1","countrycodes":cc},{"q":q,"format":"json","limit":"1"}):
        try:
            with _SV_GEO_LOCK:
                wait=1.1-(time.time()-_SV_GEO_LAST[0])
                if wait>0: time.sleep(wait)
                req=urllib.request.Request("https://nominatim.openstreetmap.org/search?"+urllib.parse.urlencode(params),headers={"User-Agent":"Skillvaya/1.0 (skillvaya@gmail.com)","Accept-Language":"en"})
                try:
                    with urllib.request.urlopen(req,timeout=8) as r: data=json.loads(r.read().decode() or "[]")
                finally: _SV_GEO_LAST[0]=time.time()
            if data:
                found=(round(float(data[0]["lat"]),2),round(float(data[0]["lon"]),2)); break
        except Exception as exc:
            print("Geocode failed:", type(exc).__name__); return None
    try:
        with conn() as c:
            c.execute("INSERT INTO geo_cache(q,lat,lng,created_at) VALUES(?,?,?,?) ON CONFLICT(q) DO UPDATE SET lat=excluded.lat,lng=excluded.lng,created_at=excluded.created_at",(key,found[0] if found else None,found[1] if found else None,now()))
    except Exception: pass
    return found
def sv_set_business_location(bid, area):
    cc="ZA"
    try:
        with conn() as c:
            r=c.execute("SELECT country FROM businesses WHERE id=?",(int(bid),)).fetchone()
        if r: cc=sv_country(r["country"]) or "ZA"
    except Exception: pass
    pos=sv_geocode(area,cc)
    try:
        with conn() as c: c.execute("UPDATE businesses SET lat=?,lng=? WHERE id=?",(pos[0] if pos else None,pos[1] if pos else None,int(bid)))
    except Exception as exc: print("Location save failed:", type(exc).__name__)
    return pos
def sv_set_business_location_async(bid, area):
    threading.Thread(target=lambda: sv_set_business_location(bid,area),name="skillvaya-geocode",daemon=True).start()
def sv_owner_alert(subject, body):
    try:
        with conn() as c: c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("owner_alert",subject,body,now(),setting("owner_email")))
    except Exception as exc: print("Owner alert failed:", type(exc).__name__)
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
def _google_play_credentials_json():
    # The host variable has been saved as GOOGLE_PLAY-SERVICE_ACCOUNT_JSON (hyphen); accept both spellings so
    # Google Play purchase checks are never silently disabled by a typo.
    return os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON","") or os.environ.get("GOOGLE_PLAY-SERVICE_ACCOUNT_JSON","")
_SETTING_CACHE={}
def setting(key, default=""):
    # Read on every authenticated request, so keep it for a few seconds; owner changes clear the cache.
    hit=_SETTING_CACHE.get(key)
    if hit is not None and time.monotonic()-hit[1]<5:
        val=hit[0]
    else:
        with conn() as c:
            row=c.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
        val=row["value"] if row else None
        _SETTING_CACHE[key]=(val,time.monotonic())
    return val if val is not None else default
_SWEEP_AT={}
def _sweep_due(name,seconds):
    """True at most once per `seconds` for housekeeping that does not need to run on every poll."""
    t=time.monotonic()
    if t-_SWEEP_AT.get(name,-1e9)>=seconds:
        _SWEEP_AT[name]=t
        return True
    return False
PERFORMANCE_INDEXES=(
    "CREATE INDEX IF NOT EXISTS idx_sv_messages_customer ON messages(customer_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_sv_messages_business ON messages(business_id, customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_messages_sender ON messages(sender_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_attachments_message ON message_attachments(message_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_contacts_customer ON contacts(customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_businesses_user ON businesses(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_businesses_status ON businesses(status)",
    "CREATE INDEX IF NOT EXISTS idx_sv_calls_status_created ON video_calls(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_sv_calls_callee ON video_calls(callee_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_sv_calls_caller ON video_calls(caller_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_sv_calls_customer ON video_calls(customer_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_sv_calls_business ON video_calls(business_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_push_user ON push_device_tokens(user_id, enabled)",
    "CREATE INDEX IF NOT EXISTS idx_sv_sessions_user ON auth_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_sessions_expires ON auth_sessions(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_sv_payments_user ON payments(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_sv_gps_user ON google_play_subscriptions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_favorites_customer ON favorites(customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_ratings_business ON ratings(business_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_enquiries_conv ON enquiries(business_id, customer_id)",
)
def ensure_performance_indexes():
    if "ensure_push_token_table" in globals():
        try: ensure_push_token_table()
        except Exception: pass
    made=0
    for stmt in PERFORMANCE_INDEXES:
        try:
            with conn() as c: c.execute(stmt)
            made+=1
        except Exception as exc:
            print("Index skipped:",stmt.split(" ON ")[-1][:48],type(exc).__name__,flush=True)
    print("Performance indexes ready (%d/%d)"%(made,len(PERFORMANCE_INDEXES)),flush=True)
def build_ice_servers(user=None):
    """STUN always; a TURN relay when the host provides one, so calls connect across mobile-carrier NATs."""
    servers=[{"urls":["stun:stun.l.google.com:19302","stun:stun1.l.google.com:19302"]}]
    urls=[x.strip() for x in os.environ.get("SKILLVAYA_TURN_URLS","").split(",") if x.strip()]
    if urls:
        secret=os.environ.get("SKILLVAYA_TURN_SECRET","")
        static_user=os.environ.get("SKILLVAYA_TURN_USERNAME","")
        static_cred=os.environ.get("SKILLVAYA_TURN_CREDENTIAL","")
        if secret:
            username="%d:%d"%(int(time.time())+6*3600,int((user or {}).get("id",0) or 0))
            credential=base64.b64encode(hmac.new(secret.encode(),username.encode(),hashlib.sha1).digest()).decode()
            servers.append({"urls":urls,"username":username,"credential":credential})
        elif static_user and static_cred:
            servers.append({"urls":urls,"username":static_user,"credential":static_cred})
    return servers
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
        "Payment status: PAID - confirmed by PayPal",
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

# PayPal Checkout Orders do not accept ZAR. Keep displayed/accounting prices in ZAR,
# but present a converted USD amount to PayPal and persist that exact quote per order.
_PAYPAL_FX_CACHE = {"rate": None, "expires_at": 0}
def paypal_zar_per_usd():
    configured = os.environ.get("SKILLVAYA_PAYPAL_ZAR_PER_USD", "").strip()
    if configured:
        try:
            rate = float(configured)
            if rate > 0:
                return rate
        except ValueError:
            pass
    if _PAYPAL_FX_CACHE["rate"] and _PAYPAL_FX_CACHE["expires_at"] > time.time():
        return _PAYPAL_FX_CACHE["rate"]
    try:
        req = urllib.request.Request("https://open.er-api.com/v6/latest/USD",
            headers={"User-Agent": "Skillvaya/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as res:
            fx = json.loads(res.read().decode() or "{}")
        rate = float((fx.get("rates") or {}).get("ZAR", 0))
        if fx.get("result") != "success" or rate <= 0:
            raise ValueError("FX provider did not return a valid USD/ZAR rate")
        _PAYPAL_FX_CACHE.update({"rate": rate, "expires_at": time.time() + 1800})
        return rate
    except Exception:
        raise RuntimeError("PayPal requires USD checkout. The current ZAR-to-USD exchange rate is unavailable; no payment has been started. Please try again shortly.")

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
    gateway="Google Play" if ("payment_gateway" in row.keys() and row["payment_gateway"]=="google_play") else ("PayPal" if ("payment_gateway" in row.keys() and row["payment_gateway"]=="paypal") else "legacy gateway")
    c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("payment_verified",gateway+" payment verified","Payment reference "+row["reference"]+" was confirmed by "+gateway+". Amount: R"+str(row["amount"])+".",now(),setting("owner_email")))
    return True

_GP_REFRESH_AT={}
def refresh_google_play_subscription_for_user(user_id):
    """Refresh Google Play subscription state lazily, without requiring Pub/Sub/RTDN."""
    # This runs on every authenticated provider request (including the 1-second call poll); once a
    # minute per account is plenty because Google is only asked when the stored state is 10+ minutes old.
    try:
        _last=_GP_REFRESH_AT.get(int(user_id))
        if _last is not None and time.monotonic()-_last<60: return
        _GP_REFRESH_AT[int(user_id)]=time.monotonic()
    except Exception:
        pass
    try:
        with conn() as c:
            latest=c.execute("SELECT reference,payment_gateway FROM payments WHERE user_id=? ORDER BY created_at DESC LIMIT 1",(user_id,)).fetchone()
            if not latest: return
            latest_gateway=str(latest["payment_gateway"] or "").lower() if "payment_gateway" in latest.keys() else ""
            latest_reference=str(latest["reference"] or "")
            if latest_gateway!="google_play" and not latest_reference.startswith("GP-"): return
            rows=c.execute("SELECT purchase_token,business_id,product_id,base_plan_id,state,expiry_time,auto_renew_enabled,updated_at FROM google_play_subscriptions WHERE user_id=? AND state<>'REPLACED'",(user_id,)).fetchall()
        if not rows: return
        current_time=datetime.datetime.now(datetime.timezone.utc)
        stale=[]
        for row in rows:
            try:
                checked=datetime.datetime.fromisoformat(str(row["updated_at"]).replace("Z","+00:00"))
                if checked.tzinfo is None: checked=checked.replace(tzinfo=datetime.timezone.utc)
            except Exception: checked=current_time-datetime.timedelta(days=1)
            try:
                recorded_expiry=datetime.datetime.fromisoformat(str(row["expiry_time"]).replace("Z","+00:00"))
                if recorded_expiry.tzinfo is None: recorded_expiry=recorded_expiry.replace(tzinfo=datetime.timezone.utc)
            except Exception: recorded_expiry=None
            still_entitled_state=row["state"] in ("SUBSCRIPTION_STATE_ACTIVE","SUBSCRIPTION_STATE_IN_GRACE_PERIOD","SUBSCRIPTION_STATE_CANCELED")
            if (current_time-checked).total_seconds()>=600 or (still_entitled_state and recorded_expiry and recorded_expiry<=current_time): stale.append(row)
        if stale:
            raw_creds=_google_play_credentials_json().strip()
            creds_path=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS","").strip()
            if raw_creds or creds_path:
                from google.oauth2 import service_account
                from googleapiclient.discovery import build
                scopes=["https://www.googleapis.com/auth/androidpublisher"]
                creds=service_account.Credentials.from_service_account_info(json.loads(raw_creds),scopes=scopes) if raw_creds else service_account.Credentials.from_service_account_file(creds_path,scopes=scopes)
                publisher=build("androidpublisher","v3",credentials=creds,cache_discovery=False)
                package_name=os.environ.get("GOOGLE_PLAY_PACKAGE_NAME","za.co.skillvaya.app").strip()
                for row in stale:
                    try:
                        current=publisher.purchases().subscriptionsv2().get(packageName=package_name,token=row["purchase_token"]).execute()
                        lines=current.get("lineItems") or []
                        line=next((item for item in lines if item.get("productId")==row["product_id"]),None)
                        expiry=str(line.get("expiryTime", "")) if line else ""
                        try: expiry_dt=datetime.datetime.fromisoformat(expiry.replace("Z","+00:00"))
                        except Exception: expiry_dt=None
                        state=str(current.get("subscriptionState", "UNKNOWN"))
                        auto_renew=bool((line or {}).get("autoRenewingPlan",{}).get("autoRenewEnabled",False))
                        with conn() as c:
                            c.execute("UPDATE google_play_subscriptions SET state=?,expiry_time=?,auto_renew_enabled=?,order_id=?,updated_at=? WHERE purchase_token=?",(state,expiry_dt.isoformat() if expiry_dt else expiry,auto_renew,str(current.get("latestOrderId", ""))[:160],now(),row["purchase_token"]))
                    except Exception:
                        continue
        with conn() as c:
            rows=c.execute("SELECT purchase_token,business_id,product_id,base_plan_id,state,expiry_time,updated_at FROM google_play_subscriptions WHERE user_id=? AND state<>'REPLACED'",(user_id,)).fetchall()
            entitled=[]
            for row in rows:
                if row["state"] not in ("SUBSCRIPTION_STATE_ACTIVE","SUBSCRIPTION_STATE_IN_GRACE_PERIOD","SUBSCRIPTION_STATE_CANCELED"): continue
                try: exp=datetime.datetime.fromisoformat(str(row["expiry_time"]).replace("Z","+00:00"))
                except Exception: continue
                if exp.tzinfo is None: exp=exp.replace(tzinfo=datetime.timezone.utc)
                if exp>current_time: entitled.append((row,exp))
            if entitled:
                chosen=max(entitled,key=lambda pair:str(pair[0]["updated_at"] or ""))[0]
                expiry_dt=max(exp for _,exp in entitled)
                plan_by_product={"skillvaya_local":"local","skillvaya_priority":"priority","skillvaya_business_plus":"plus","skillvaya_business_spotlight":"spotlight"}
                plan=plan_by_product.get(str(chosen["product_id"]))
                billing="yearly" if str(chosen["base_plan_id"])=="annual" else "monthly"
                biz_id=chosen["business_id"]
                if not biz_id:
                    biz=c.execute("SELECT id FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(user_id,)).fetchone()
                    biz_id=int(biz["id"]) if biz else None
                    if biz_id: c.execute("UPDATE google_play_subscriptions SET business_id=? WHERE purchase_token=?",(biz_id,chosen["purchase_token"]))
                if biz_id and plan:
                    c.execute("UPDATE businesses SET plan=?,billing=?,payment_status='verified',status='active',subscription_expires_at=? WHERE id=? AND user_id=?",(plan,billing,expiry_dt.isoformat(),biz_id,user_id))
                    c.execute("UPDATE subscriptions SET plan=?,billing=?,status='active',expires_at=?,cancelled_at=NULL WHERE business_id=? AND user_id=?",(plan,billing,expiry_dt.isoformat(),biz_id,user_id))
            else:
                c.execute("UPDATE businesses SET payment_status='expired',status='suspended' WHERE user_id=?",(user_id,))
                c.execute("UPDATE subscriptions SET status='expired' WHERE user_id=?",(user_id,))
    except Exception:
        # A transient Google API outage must not break unrelated provider screens. Existing expiry checks remain authoritative.
        return

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
    try:
        with conn() as c:
            play_users=c.execute("SELECT p.user_id FROM payments p WHERE p.payment_gateway='google_play' AND p.id=(SELECT p2.id FROM payments p2 WHERE p2.user_id=p.user_id ORDER BY p2.created_at DESC,p2.id DESC LIMIT 1)").fetchall()
        for play_user in play_users:
            refresh_google_play_subscription_for_user(int(play_user["user_id"]))
    except Exception as e:
        print("Google Play subscription reconciliation failed:",str(e)[:200],flush=True)
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
def evaluate_provider_automation_due():
    """Run enabled provider reminders for verified Plus/Spotlight businesses. Returns count of new in-app alerts."""
    stamp=now()
    cutoff=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=24)).isoformat()
    today=datetime.date.today().isoformat()
    tomorrow=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=24)).isoformat()
    created=0
    ranks=PROVIDER_TIER_RANKS
    with conn() as c:
        businesses=c.execute("SELECT id,user_id FROM businesses WHERE status='active' AND payment_status='verified' AND LOWER(COALESCE(plan,'local')) IN ('plus','spotlight') ORDER BY id").fetchall()
        for biz in businesses:
            bid=int(biz["id"]);uid=int(biz["user_id"] or 0)
            if not uid:continue
            rules={str(r["rule_key"]):bool(r["enabled"]) for r in c.execute("SELECT rule_key,enabled FROM provider_automation_rules WHERE business_id=?",(bid,)).fetchall()}
            if not rules:continue
            candidates=[]
            if rules.get("quote_followup"):
                rows=c.execute("""SELECT f.id,f.remind_at,f.note,j.title,cu.name customer_name FROM provider_followups f
                    JOIN job_requests j ON j.id=f.job_id JOIN users cu ON cu.id=f.customer_id
                    WHERE f.business_id=? AND f.status='pending' AND f.remind_at<=? LIMIT 100""",(bid,stamp)).fetchall()
                for r in rows:candidates.append(("quote_followup","Quote follow-up due",str(r["customer_name"])+": "+str(r["title"])+". "+str(r["note"]),"followup:"+str(r["id"])))
            if rules.get("booking_reminder"):
                rows=c.execute("SELECT id,title,customer_name,starts_at FROM provider_bookings WHERE business_id=? AND status='scheduled' AND starts_at>=? AND starts_at<=? LIMIT 100",(bid,stamp,tomorrow)).fetchall()
                for r in rows:candidates.append(("booking_reminder","Upcoming booking",str(r["title"])+" for "+str(r["customer_name"])+" starts "+str(r["starts_at"]),"booking:"+str(r["id"])))
            if rules.get("invoice_overdue"):
                rows=c.execute("SELECT id,invoice_number,customer_name,amount_cents,amount_paid_cents,due_date FROM provider_invoices WHERE business_id=? AND status NOT IN ('paid','cancelled') AND due_date<>'' AND due_date<? LIMIT 100",(bid,today)).fetchall()
                for r in rows:
                    if int(r["amount_paid_cents"] or 0)<int(r["amount_cents"] or 0):candidates.append(("invoice_overdue","Invoice overdue",str(r["invoice_number"])+" for "+str(r["customer_name"])+" has an outstanding balance.","invoice:"+str(r["id"])))
            for kind,title,body_text,ref in candidates:
                exists=c.execute("SELECT id FROM provider_notifications WHERE business_id=? AND reference_key=? AND created_at>? LIMIT 1",(bid,ref,cutoff)).fetchone()
                if exists:continue
                c.execute("INSERT INTO provider_notifications(business_id,user_id,kind,title,body,reference_key,status,created_at) VALUES(?,?,?,?,?,?, 'new',?)",(bid,uid,kind,title,body_text,ref,stamp))
                created+=1
    return created

TERMS_PAGE_HTML = r"""<!doctype html><html lang="en-ZA"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><meta name="theme-color" content="#071426"><title>Skillvaya Terms & Conditions</title><style>*{box-sizing:border-box}body{margin:0;background:#f2f6fb;color:#17283d;font:16px/1.65 system-ui,Arial,sans-serif}.top{background:#071426;color:#fff;padding:28px 18px}.wrap{max-width:880px;margin:auto;padding:22px 18px}.paper{background:#fff;border:1px solid #dce5f0;border-radius:16px;padding:clamp(18px,4vw,36px)}h1{margin:0 0 8px;font-size:clamp(28px,4vw,40px)}h2{margin-top:28px;font-size:21px}a{color:#075f92}.warning{padding:14px;border-radius:10px;background:#fff5dd;color:#704b08}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}.btn{display:inline-block;border-radius:9px;padding:12px 16px;background:#087f8c;color:white;text-decoration:none;font-weight:700}.muted{color:#66758b;font-size:13px}.message-thread{padding:0!important;overflow:hidden}.conversation-list-item{width:100%;display:flex;align-items:center;gap:12px;padding:15px 16px;border:0;border-bottom:1px solid var(--line);background:var(--card,#fff);text-align:left;cursor:pointer;color:inherit}.conversation-list-item:hover{background:var(--surface,#f4f7fb)}.conversation-avatar{width:46px;height:46px;flex:0 0 46px;border-radius:50%;display:grid;place-items:center;background:linear-gradient(145deg,#087f80,#24b8ae);color:#fff;font-size:19px;font-weight:800}.conversation-avatar.large{width:64px;height:64px;font-size:26px;margin:0 auto}.conversation-summary{min-width:0;flex:1;display:grid;gap:5px}.conversation-summary strong{font-size:15px}.conversation-summary span{font-size:13px;color:var(--muted,#64748b);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:58vw}.conversation-meta{display:grid;justify-items:end;gap:8px;color:var(--muted,#64748b);font-size:11px}.conversation-count{border-radius:20px;background:#e1f8f5;color:#087f80;padding:2px 7px;font-weight:800}.message-conversation-screen{display:flex;flex-direction:column;min-height:60vh;background:var(--surface,#f5f8fb);border:1px solid var(--line);border-radius:18px;overflow:hidden;padding:12px}.message-conversation-header{display:flex;gap:12px;align-items:center;padding:14px 4px;border-bottom:1px solid var(--line);background:var(--card,#fff)}.message-conversation-header h2{margin:0;font-size:19px}.message-conversation-header p{margin:4px 0 0}.message-bubbles{display:flex;flex-direction:column;gap:9px;flex:1;max-height:55vh;overflow:auto;padding:18px 4px}.message-row{display:flex;width:100%}.message-row.mine{justify-content:flex-end}.message-row.theirs{justify-content:flex-start}.message-bubble{max-width:min(82%,520px);padding:10px 13px;border-radius:16px;background:var(--card,#fff);box-shadow:0 1px 2px #10203012;overflow-wrap:anywhere;white-space:pre-wrap}.message-row.mine .message-bubble{background:#d8f8ee;border-bottom-right-radius:5px}.message-row.theirs .message-bubble{border-bottom-left-radius:5px}.message-time{font-size:10px;color:#637487;text-align:right;margin-top:5px}.message-compose{display:flex;align-items:flex-end;gap:8px;padding:10px 0 0}.message-compose textarea{flex:1;resize:vertical;min-height:46px;max-height:130px;border:1px solid var(--line);border-radius:14px;padding:12px;font:inherit}.message-compose button{min-height:44px;border-radius:13px}.messages-empty-state{text-align:center;padding:38px 20px;color:var(--muted,#64748b)}.messages-empty-state h3{color:var(--text,#172b42)}



/* Provider profile is a dedicated viewport, not content appended to Home or Services. */
body.provider-detail-mode{overflow:hidden!important}
body.provider-detail-mode #providerDetailScreen:not(.hidden){position:fixed!important;inset:0!important;z-index:7000!important;display:block!important;width:100%!important;max-width:none!important;height:100dvh!important;min-height:100dvh!important;overflow-y:auto!important;overscroll-behavior:contain!important;margin:0!important;padding:calc(16px + env(safe-area-inset-top)) 16px calc(96px + env(safe-area-inset-bottom))!important;background:var(--bg,#f4f7fb)!important;box-sizing:border-box!important}
body.provider-detail-mode #providerDetailScreen>.ghost{position:sticky;top:0;z-index:2;margin-bottom:10px;box-shadow:0 2px 10px #17365d12}
body.provider-detail-mode #providerDetailContent{max-width:900px;margin:14px auto 0!important}
/* Scroll-tail fix: avoid double-counting the fixed tab bar and the footer bottom spacer. */
@media(max-width:800px){main.wrap,.wrap{padding-bottom:calc(82px + env(safe-area-inset-bottom))!important}.footer{padding-bottom:20px!important;margin-bottom:0!important}body{padding-bottom:0!important}}

/* Business Plus & Business Spotlight tools: consistent Skillvaya navy / white / blue system. */
.sv-growth-section{margin:16px 0;padding:18px;border:1px solid var(--line,#dbe6f4);border-radius:18px;background:var(--card,#fff)}
.sv-growth-intro{margin:0 0 14px;color:var(--muted,#61758f);font-size:13px;line-height:1.6}
.sv-growth-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.sv-growth-item{min-width:0;border:1px solid var(--line,#dbe6f4);border-radius:14px;background:#fff;padding:14px}
.sv-growth-item h3{margin:0 0 6px;color:var(--navy,#12345a);font-size:15px}
.sv-growth-item p{color:var(--muted,#61758f);font-size:12px;line-height:1.5;margin:5px 0 10px;overflow-wrap:anywhere}
.sv-growth-pill{display:inline-flex;align-items:center;gap:5px;padding:5px 9px;background:#eaf3ff;border:1px solid #d2e3fb;border-radius:999px;color:#1b4c83;font-size:10px;font-weight:850;letter-spacing:.4px}
.sv-growth-row{display:flex;gap:9px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.sv-growth-small{color:var(--muted,#61758f);font-size:11px;line-height:1.5}
.sv-growth-money{color:#174e91;font-size:20px;font-weight:900;letter-spacing:-.4px}
.sv-growth-kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:12px 0}
.sv-growth-kpi{padding:14px;border:1px solid #d8e6f8;border-radius:14px;background:linear-gradient(135deg,#fff,#f3f8ff)}
.sv-growth-kpi strong{display:block;color:#164b8a;font-size:24px;line-height:1.15}.sv-growth-kpi span{display:block;color:#61758f;font-size:11px;margin-top:5px}
.sv-growth-tag{display:inline-flex;padding:4px 8px;border-radius:8px;background:#e9f5f1;color:#176d5e;font-size:10px;font-weight:850;text-transform:uppercase}
.sv-growth-tag.warn{background:#fff3df;color:#8b5d12}.sv-growth-tag.muted{background:#eef2f7;color:#63748a}
.sv-growth-empty{padding:20px;border:1px dashed #bfd1e7;border-radius:13px;background:#f8fbff;color:#637892;text-align:center;font-size:13px}
.sv-growth-form{margin:12px 0;padding:16px;border:1px solid var(--line,#dbe6f4);border-radius:15px;background:#f8fbff}
.sv-growth-form input,.sv-growth-form textarea,.sv-growth-form select{width:100%;box-sizing:border-box;min-height:42px;border:1px solid #cad9ec;border-radius:10px;padding:10px 11px;background:#fff;color:#203c5d;font:inherit;font-size:13px}
.sv-growth-form textarea{min-height:82px;resize:vertical}
.sv-growth-form label{display:block;color:#2d4766;font-size:12px;font-weight:800;margin:0 0 5px}
.sv-growth-form .sv-tool-fields{margin:10px 0}
.sv-growth-inline-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}
.sv-growth-inline-actions button{min-height:36px;padding:7px 11px!important;font-size:12px!important}
.sv-growth-tablewrap{max-width:100%;overflow-x:auto;border:1px solid var(--line,#dbe6f4);border-radius:12px}
.sv-growth-table{border-collapse:collapse;width:100%;font-size:12px;background:#fff}.sv-growth-table th,.sv-growth-table td{padding:10px 12px;border-bottom:1px solid #e5edf7;text-align:left;vertical-align:top}.sv-growth-table th{background:#f2f7fe;color:#294a70;font-weight:850;white-space:nowrap}
.sv-growth-table td{color:#324a67}.sv-growth-table tr:last-child td{border-bottom:0}
.sv-growth-check{display:flex;align-items:flex-start;gap:9px;font-size:12px;line-height:1.5;color:#304a68;margin:8px 0}
.sv-growth-check input{margin-top:3px}
.sv-growth-muted-alert{padding:10px 12px;border:1px solid #d7e4f5;border-radius:10px;background:#f1f7ff;color:#28517f;font-size:12px;line-height:1.55;margin:10px 0}
.sv-growth-success{padding:10px 12px;border:1px solid #bfe6d8;border-radius:10px;background:#edf9f4;color:#126b59;font-size:12px;line-height:1.5;margin:10px 0}
@media(max-width:620px){.sv-growth-grid{grid-template-columns:1fr}.sv-growth-section{padding:14px}.sv-growth-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.sv-growth-table{min-width:520px}}

/* Public tier benefits are neat add-ons using the Skillvaya navy / white / light-blue palette. */
.sv-growth-public-banner{margin:10px 0;padding:12px 14px;border:1px solid #cfe0f6;border-radius:12px;background:linear-gradient(120deg,#edf5ff,#fff);color:#183f70}
.sv-growth-public-banner span{display:block;color:#2161ad;font-size:9px;font-weight:900;letter-spacing:1.2px}
.sv-growth-public-banner strong{display:block;margin:4px 0;color:#153a67;font-size:14px}
.sv-growth-public-banner p{margin:0;color:#4c6481;font-size:12px;line-height:1.5}
.sv-growth-public-offers{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.sv-growth-public-packages{margin:8px 0;padding:10px 12px;border:1px solid #dfe9f5;border-radius:11px;background:#f8fbff;color:#2b4f78;font-size:12px}
.sv-growth-public-packages p{margin:4px 0 0;color:#637892;font-size:11px}
#teamAssignmentsScreen:not(.hidden){display:block!important;position:fixed!important;inset:0!important;z-index:2147483500!important;width:100vw!important;height:100dvh!important;box-sizing:border-box!important;overflow:auto!important;overflow-x:hidden!important;background:#f3f7fc!important;color:#172b47!important;padding:calc(12px + env(safe-area-inset-top)) 14px calc(22px + env(safe-area-inset-bottom))!important}


.wf-showcase{background:linear-gradient(130deg,#08152d,#123b69 72%,#174d78);color:#fff;overflow:hidden}
.wf-showcase>p{color:#d5e5fa;max-width:760px}.wf-kicker{display:inline-block;color:#b9d5ff;font-size:11px;font-weight:850;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px}
.wf-showcase h2{font-size:clamp(25px,4vw,36px);line-height:1.12;letter-spacing:-.7px}
.wf-preview-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:20px}
.wf-preview{background:#fff;color:#122238;border:1px solid #dce7f5;border-radius:16px;overflow:hidden;min-width:0;box-shadow:0 12px 28px #020b1a25}
.wf-preview-body{padding:14px}.wf-preview h3{font-size:16px;margin:0 0 5px;color:#10233f}.wf-preview p{font-size:13px;line-height:1.5;color:#62748b;margin:0}
.wf-screen{min-height:205px;padding:14px;background:#f2f7ff;color:#13284a}.wf-screen-head{display:flex;justify-content:space-between;align-items:center;font-size:11px;font-weight:850;padding-bottom:11px;border-bottom:1px solid #dce7f5}.wf-screen-head b{color:#2864f5}
.wf-chip{display:inline-block;background:#e2edff;color:#2858a5;border-radius:99px;padding:4px 7px;font-size:9px;font-weight:800}
.wf-person{display:flex;gap:10px;align-items:center;background:white;border:1px solid #e0e8f4;border-radius:12px;padding:10px;margin-top:10px}
.wf-avatar{width:42px;height:42px;border-radius:50%;flex:none;display:grid;place-items:center;color:#fff;font-size:12px;font-weight:900;background:linear-gradient(140deg,#2864f5,#7655f4)}
.wf-avatar.alt{background:linear-gradient(140deg,#0b7e86,#44c9bf)}.wf-avatar.gold{background:linear-gradient(140deg,#a16b31,#e9bd67)}
.wf-person strong{display:block;font-size:11px}.wf-person small{display:block;color:#718098;font-size:9px;margin-top:3px}
.wf-mini-lines{height:6px;border-radius:8px;background:#e1eaf7;margin-top:8px}.wf-mini-lines.short{width:65%}
.wf-message{padding:9px 10px;background:#e5efff;border-radius:10px;font-size:10px;margin:12px 0 0;max-width:85%}.wf-message.mine{margin-left:auto;background:#163a68;color:white}
.wf-portfolio-tile{display:flex;gap:8px;margin-top:12px}.wf-portfolio-tile span{height:72px;flex:1;border-radius:10px;background:linear-gradient(145deg,#d9e7ff,#a9c7f7);border:1px solid #c5d7f1}
.wf-portfolio-tile span:nth-child(2){background:linear-gradient(145deg,#d6f6f0,#85d9ce)}.wf-portfolio-tile span:nth-child(3){background:linear-gradient(145deg,#eee5ff,#bba8f3)}
.wf-showcase-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:22px}.wf-showcase-actions a{display:inline-flex;justify-content:center;align-items:center;padding:12px 16px;border-radius:11px;text-decoration:none;font-weight:800;font-size:14px}
.wf-showcase-actions .wf-primary{background:#2864f5;color:#fff}.wf-showcase-actions .wf-secondary{border:1px solid #ffffff55;color:#fff}
@media(max-width:720px){.wf-preview-grid{grid-template-columns:1fr 1fr}.wf-screen{min-height:190px}}@media(max-width:460px){.wf-preview-grid{grid-template-columns:1fr}.wf-screen{min-height:185px}}
:root{--sv-screen-header-top:76px}
body.provider-detail-mode,body.messages-conversation-open,body.subscription-test-screen-mode{--sv-screen-header-top:0px}
#providerStudioHeading{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:900!important;display:flex!important;align-items:center!important;min-height:76px!important;margin:0 0 14px!important;padding:14px 18px!important;border:1px solid #244c80!important;border-radius:0 0 15px 15px!important;background:linear-gradient(112deg,#102f60,#174f86 68%,#2365d8)!important;color:#fff!important;box-shadow:0 8px 22px #102f6026!important}
#providerStudioHeading h2{color:#fff!important;font-size:clamp(22px,4vw,29px)!important;line-height:1.2!important;margin:0!important}
#providerStudioHeading p,#providerStudioHeading .muted{color:#e1edff!important;margin:4px 0 0!important;font-size:12px!important}
.category-screen-head,.message-conversation-topbar,.sv-subtest-topbar{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:900!important;background:linear-gradient(112deg,#102f60,#174f86)!important;color:#fff!important;border-radius:0 0 13px 13px!important;padding:11px 13px!important;box-shadow:0 7px 20px #102f6024!important}
.category-screen-head h2,.message-conversation-topbar h1,.message-conversation-topbar h2{color:#fff!important}
.category-screen-head .muted{color:#e1edff!important}.category-screen-head .category-back{background:#fff!important;color:#174578!important}
.destination-hero,.sv-workstation-hero,.sv-subtest-profile-hero{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:850!important;border-radius:0 0 16px 16px!important;box-shadow:0 8px 22px #102f6020!important}
#providerDetailScreen>.ghost{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:900!important}
#plans{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:12px!important;align-items:stretch!important}
#plans>.muted{grid-column:1/-1!important;margin:0 0 2px!important;line-height:1.55!important}
#plans>.price{display:flex!important;flex-direction:column!important;min-width:0!important;height:100%!important;padding:16px!important;border:1px solid #d7e5f7!important;border-radius:15px!important;background:#fff!important;box-shadow:0 5px 18px #17365d0a!important;overflow-wrap:anywhere!important}
#plans>.price.featured{border:2px solid #2365d8!important;background:linear-gradient(145deg,#fff,#f0f6ff)!important}
#plans>.price h3{color:#143c70!important;font-size:18px!important;line-height:1.25!important;margin:0 0 8px!important}
#plans>.price .amount{color:#164f9a!important;font-size:clamp(22px,4vw,28px)!important;line-height:1.2!important;overflow-wrap:anywhere!important}
#plans>.price .amount .tiny{font-size:12px!important}#plans>.price p{line-height:1.5!important}
#plans>.price .sv-plan-feature-list{flex:1 0 auto!important}
#plans>.price button{width:100%!important;min-height:44px!important;margin-top:12px!important;background:linear-gradient(110deg,#1c63c7,#377fe0)!important;color:#fff!important}
#providerPlansCard>h3{color:#143c70!important;font-size:22px!important}
#providerPlansCard>label{display:block!important;color:#234d7b!important;font-weight:800!important;margin:10px 0 4px!important}
#billing{display:block!important;width:100%!important;min-height:46px!important;border:1px solid #b8d0ed!important;background:#f7fbff!important;color:#153a67!important;font-weight:700!important}
@media(max-width:560px){#plans{grid-template-columns:minmax(0,1fr)!important}#providerStudioHeading{min-height:68px!important;padding:12px 14px!important}#plans>.price{padding:15px!important}}
body.account-screen-mode,body.messages-screen-mode,body.provider-screen-mode{--sv-screen-header-top:0px}
#settings .profile-heading{position:sticky!important;top:0!important;z-index:950!important;margin:0 -2px 14px!important;padding:13px 14px!important;border:1px solid #244c80!important;border-radius:0 0 14px 14px!important;background:linear-gradient(112deg,#102f60,#174f86 70%,#2365d8)!important;color:#fff!important;box-shadow:0 8px 22px #102f6026!important}
#settings .profile-heading h2,#settings .profile-heading .account-eyebrow{color:#fff!important}#settings .profile-heading p{color:#e1edff!important}
#messagesScreen .messages-app-header{position:sticky!important;top:0!important;z-index:950!important;background:linear-gradient(112deg,#102f60,#174f86 70%,#2365d8)!important;color:#fff!important;box-shadow:0 8px 22px #102f6026!important}
#messagesScreen .messages-app-header h1,#messagesScreen .messages-app-header p{color:#fff!important}
#teamAssignmentsScreen>header,#teamAssignmentsScreen>.sectionhead,#teamAssignmentsScreen>.sv-subtest-topbar{position:sticky!important;top:0!important;z-index:950!important;background:linear-gradient(112deg,#102f60,#174f86)!important;color:#fff!important}
#svWorkstationToolScreen .sv-workstation-tool-screen>header,#svWorkstationToolScreen .sv-workstation-tool-screen>.sectionhead{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:900!important;background:linear-gradient(112deg,#102f60,#174f86)!important;color:#fff!important}
#terms .card>h2{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:850!important;margin:0 -17px 14px!important;padding:14px 17px!important;border-radius:0 0 12px 12px!important;background:linear-gradient(112deg,#102f60,#174f86)!important;color:#fff!important}

/* SV57-ACCOUNT-HEADER-01: keep the Account identity heading fixed within its scroll viewport. */
body.account-screen-mode #settings .profile-heading{position:fixed!important;top:8px!important;left:14px!important;right:14px!important;width:auto!important;z-index:12000!important;background:linear-gradient(115deg,#102f60,#174f86 72%,#2365d8)!important;color:#fff!important;border-radius:14px!important;padding:14px!important;margin:0 0 14px!important;box-shadow:0 8px 22px #102f6026!important;isolation:isolate!important}
body.account-screen-mode #settings .profile-heading h2,body.account-screen-mode #settings .profile-heading p,body.account-screen-mode #settings .profile-heading .account-eyebrow{color:#fff!important}
/* SV75-HEADERS-01 terms page: compact sticky header */
.top{position:sticky;top:0;z-index:50;padding:10px 18px!important;box-shadow:0 6px 18px #0a1c3830}.top .wrap{padding:0 18px!important}.top strong{display:block;font-size:11px;letter-spacing:.6px;text-transform:uppercase;opacity:.85}.top h1{font-size:20px!important;line-height:1.2!important;margin:2px 0 0!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.top p{font-size:12px!important;margin:2px 0 0!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:.9}
</style></head><body><header class="top"><div class="wrap"><strong>Skillvaya</strong><h1>Terms, Conditions, Rules & Safety</h1><p>Version 1.2 · Effective 21 October 2026 · South Africa</p></div></header><main class="wrap"><article class="paper">
<p class="warning"><strong>Important:</strong> Read these terms before creating an account or signing in. You must actively tick the agreement box to continue. These terms do not remove consumer or privacy rights that cannot lawfully be excluded.</p>
<h2>1. Agreement, accounts and updates</h2><p>By ticking the agreement box and selecting Create account or Sign in, you confirm that you have had an opportunity to read these Terms, Conditions, Rules & Safety and agree to the current version. If you do not agree, do not create an account or use account-only features. We record the terms version and the date/time of acceptance. Material changes will be dated and presented for acceptance; you may stop using the service if you do not agree, subject to any outstanding lawful obligations.</p><p>Provide accurate information, protect your credentials, and notify us of suspected unauthorised use. You may not impersonate another person, evade a restriction, or access an account or information without permission. Keep email, phone, business details, prices and qualifications current.</p>
<h2>2. Skillvaya’s role and safety</h2><p>Skillvaya is a directory and introduction service intended to connect customers with service providers. Unless a separate written service says otherwise, Skillvaya is not the customer’s or provider’s agent, employer, insurer, contractor or guarantor, and is not a party to a contract between a customer and provider. A paid or featured placement is advertising, not an endorsement or certification. We do not guarantee identity, licensing, qualifications, availability, workmanship, service quality, price, completion, or outcomes. Check credentials, references, insurance, written quotations and work terms independently.</p>
<h3>Advertising, owner-owned businesses and apps</h3><p>Paid or featured placements are advertising and are labelled as sponsored or featured where shown. A paid placement is not an endorsement, certification, or guarantee by Skillvaya. The platform owner may also own, operate, submit or publish businesses, services, software or apps in the directory. Owner-related listings should be identified as owner listings where displayed and remain subject to the same applicable content, safety and legal rules. The public app interface is designed to focus on finding providers, provider profiles and account functions; ownership disclosures and advertising policy are described in these Terms.</p><h2>3. Customer rules</h2><p>Customer directory browsing and ordinary contact are free unless a charge is clearly disclosed before the relevant transaction. Confirm scope, price, timing, cancellation terms and safety arrangements directly with a provider. Do not pay merely because a listing appears on Skillvaya. Never share passwords, one-time PINs or banking credentials. Use reporting tools honestly and promptly report suspected fraud or unsafe conduct.</p>
<h2>4. Provider rules and listings</h2><p>Providers must be legally entitled and suitably qualified for the services they advertise; must comply with applicable laws and professional rules; must provide honest descriptions, quotes and credentials; and must treat customers respectfully. Do not post unlawful, counterfeit, deceptive, discriminatory, threatening, fraudulent or unsafe listings, or another person’s private information without a lawful basis. Skillvaya may ask for evidence, moderate, limit, suspend or remove content or accounts where reasonably needed for safety, integrity, payment issues or legal compliance. Reports are allegations, not findings of guilt; decisions should be based on available evidence and applicable law.</p>
<h2>5. Plans, prices and increases</h2><p>Any paid placement or subscription must show the plan, included features, billing term, full amount payable, applicable taxes/fees, start/end or renewal date, cancellation terms and payment method before you approve purchase. The amount displayed at checkout and accepted for a paid term is the price for that term; a later price change will not retrospectively increase that already-paid term.</p><p><strong>Skillvaya’s plan and subscription prices may increase or otherwise change over time.</strong> Changes may reflect hosting, payment processing, operating costs, product features, taxes, inflation, or business decisions. Where legally required, and as a general service commitment, we will give reasonable advance notice of a material price increase—normally at least 30 days before it applies to a future renewal—and identify the new price and effective date. A change will not be applied mid-term to a term already paid for. You can cancel or choose not to renew before the new price takes effect. We will not charge the new amount or treat silence as permission for an undisclosed charge; the new price must be displayed before a new purchase or renewal is approved. If applicable law requires a different notice period or process, that law prevails.</p><p>Taxes, currency conversion and payment-provider charges, if any, will be disclosed where they can be determined before approval. Providers are responsible for any tax obligations applicable to their own business.</p>
<h2>6. Payments, confirmation and renewals</h2><p>All provider-plan payments are made through Google Play. Provider plans use Google Play Billing as prepaid monthly or annual periods and do not renew automatically. The user must make a separate purchase to extend the period. Google Play processes the payment, and Skillvaya activates paid access only after secure server-side purchase verification. The plan, amount, duration and prepaid/no-automatic-renewal terms must be shown before the user approves a purchase. A plan is treated as paid/active only after Google Play confirms the purchase. Pending, failed or cancelled orders, browser redirects, screenshots or payment claims alone are not proof of payment. Sandbox/test transactions used in a separate test environment are not real payments and must never be treated as proof of a real charge. Do not retry a purchase if Google Play says it was completed; contact support with its order number.</p><p>Unless a checkout clearly states otherwise and you expressly authorise recurring billing, plan renewals are not automatic. A plan may expire or paid placement may be paused when its paid period ends without a confirmed renewal. Before a new renewal or plan upgrade, the price and term will be shown again. Do not store, share or submit someone else’s payment credentials.</p>
<h2>7. Cancellation, refunds and disputes</h2><p>Cancellation stops a future renewal where renewal functionality exists; it does not automatically reverse a completed payment or erase amounts lawfully due for a term already supplied. Refund requests are reviewed under the displayed checkout terms and applicable law. Where a payment provider offers a refund mechanism, Skillvaya submits a refund only against the matching confirmed transaction; a request is not complete until the provider confirms its status. We will show pending, partial or completed refund status as accurately as practicable. Nothing in these terms removes non-excludable rights, including any applicable statutory cancellation or refund rights.</p><p>For billing errors, duplicate charges, non-delivery, unauthorised payment concerns or a disagreement about a provider’s service, contact us promptly with the order/payment reference and a factual description. Do not send card security codes, passwords, or one-time PINs in a support request.</p>
<h2>8. Privacy and communications</h2><p>Skillvaya may process your name, email address, phone number, account role, business/listing details, enquiries, complaints, payment references/status and technical usage information to operate the service, authenticate accounts, connect customers and providers, process and reconcile payments, maintain safety, prevent abuse and respond to support requests. Information may be shared with service providers such as hosting and payment processors only as reasonably necessary for those purposes or where law permits/requires. We aim to use reasonable safeguards, restrict access, keep information only as long as reasonably necessary or legally required, and respond to lawful requests to access or correct information. A complete business-specific privacy notice, retention schedule and data-subject request procedure should be maintained and made available before full public launch. No security measure can guarantee absolute security.</p>
<h2>9. Prohibited conduct</h2><p>No fraud, threats, harassment, unlawful discrimination, illegal services, stolen or counterfeit goods, deceptive claims, spam, scraping that breaches rules or law, malware, unauthorised access, payment manipulation, forged reviews, false reports, or publication of private information without a lawful basis. Skillvaya may preserve records, investigate and restrict activity when warranted.</p>
<h2>10. Availability, liability and changes</h2><p>Online services can be unavailable, delayed or interrupted, and third-party providers may have outages or errors. We will take reasonable care, but do not promise uninterrupted availability. To the extent permitted by law, Skillvaya is not responsible for independent contracts, acts or omissions of customers, providers, banks or payment processors. Nothing excludes liability or remedies that cannot legally be excluded, and nothing limits rights under applicable South African law. We may update these terms with a new version date and appropriate notice.</p>
<h2>11. Applicable law and contact</h2><p>These terms are intended to operate under the laws of the Republic of South Africa, subject to any mandatory law that applies to a user or transaction. For account, billing, safety or privacy concerns, email <a href="mailto:skillvaya@gmail.com">skillvaya@gmail.com</a> or use the in-app reporting feature.</p>
<p class="muted">This is a working business draft, not legal advice. Have a South African attorney review it—especially the consumer disclosures, recurring-payment model, refund policy and privacy/POPIA arrangements—before accepting real customer payments.</p>
<div class="actions"><a class="btn" href="/login">Return to sign in</a><a href="/website">Public website</a></div></article></main></body></html>"""

LOGIN_GATEWAY_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#10233f"><title>Sign in — Skillvaya</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(145deg,#071426,#102b49);font:16px/1.5 Arial,sans-serif;color:#eef5ff;padding:18px}.card{width:min(100%,440px);background:#fff;color:#17263b;border-radius:20px;padding:28px;box-shadow:0 22px 70px #0005}.brand{font-size:27px;font-weight:800;margin-bottom:5px}.brand span{color:#087f8c}.sub{color:#627188;margin:0 0 24px}label{display:block;font-weight:650;margin:14px 0 6px}input{display:block;width:100%;padding:13px;border:1px solid #cbd5e1;border-radius:9px;font-size:16px}button{width:100%;padding:13px;border:0;border-radius:9px;background:#087f8c;color:#fff;font-size:16px;font-weight:750;margin-top:20px;cursor:pointer}button:disabled{opacity:.65}#status{min-height:24px;color:#b42318;font-size:14px}.hint{font-size:12px;color:#65748a;margin-top:18px}.notice{background:#fff5dd;color:#704b08;border-radius:10px;padding:12px;font-size:13px}.agree{display:flex;align-items:flex-start;gap:9px;font-size:13px;font-weight:500}.agree input{width:auto;margin:4px 0 0;flex:0 0 auto}.agree a{color:#087f8c}

/* Accessible, polished sign-in screen */
body{background:radial-gradient(ellipse at 85% 12%,rgba(32,200,193,.22),transparent 34%),radial-gradient(ellipse at 12% 90%,rgba(36,89,211,.22),transparent 40%),linear-gradient(145deg,#061221,#102b49);-webkit-font-smoothing:antialiased}
.card{border:1px solid rgba(255,255,255,.65);border-radius:24px;padding:clamp(24px,5vw,36px);box-shadow:0 32px 100px rgba(0,0,0,.32)}
.brand{letter-spacing:-1px}.sub{line-height:1.65}.notice{border:1px solid #f0d9a5;border-radius:13px;line-height:1.6}
input{min-height:48px;border-radius:11px;border:1px solid #d2dfec;transition:box-shadow .15s,border-color .15s}input:focus{outline:0;border-color:#18a6a4;box-shadow:0 0 0 4px rgba(24,166,164,.14)}
button{border-radius:12px!important;min-height:48px;background:linear-gradient(135deg,#087f83,#0b9e9e)!important;box-shadow:0 8px 18px rgba(8,127,131,.2)}
button:focus-visible,a:focus-visible,input:focus-visible{outline:3px solid #23bebb;outline-offset:3px}

</style></head><body><main class="card"><div class="brand">Skill<span>vaya</span></div><p class="sub">Sign in to open your Skillvaya workspace.</p><p class="notice">By signing in or creating an account, you confirm that you agree to Skillvaya’s current <a href="/terms" target="_blank" rel="noopener">Terms, Conditions, Rules & Safety</a>, including the payment and price-change rules.</p><form id="loginForm"><label for="email">Email address</label><input id="email" type="email" autocomplete="username" required autofocus><label for="password">Password</label><span style="position:relative;display:block"><input id="password" type="password" autocomplete="current-password" required style="padding-right:48px"><button type="button" aria-label="Show password" onclick="const p=document.getElementById('password');const s=p.type==='password';p.type=s?'text':'password';this.setAttribute('aria-label',s?'Hide password':'Show password')" style="position:absolute;right:5px;top:50%;transform:translateY(-50%);width:38px;height:36px;padding:7px;background:transparent;color:#52647b;display:grid;place-items:center"><svg viewBox="0 0 24 24" aria-hidden="true" style="width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg></button></span><label class="agree" for="agreeTerms"><input id="agreeTerms" type="checkbox" required> I have read and agree to the current <a href="/terms" target="_blank" rel="noopener">Terms & Conditions</a> and <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.</label><button id="submit" type="submit">Sign in</button><p style="text-align:right;margin:8px 0"><a href="/forgot-password">Forgot password?</a></p><p id="status" role="status" aria-live="polite"></p></form><p class="hint">Your account determines which workspace opens. The public marketing page is separate from the installed app.</p></main><script>const form=document.getElementById('loginForm'),statusEl=document.getElementById('status'),submit=document.getElementById('submit');form.addEventListener('submit',async e=>{e.preventDefault();statusEl.textContent='Signing in…';submit.disabled=true;try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value.trim(),password:document.getElementById('password').value,accept_terms:document.getElementById('agreeTerms').checked})});const d=await r.json();if(!r.ok||!d.token||!d.user){statusEl.textContent=d.error||'Sign-in failed. Check your details and try again.';return;}if(d.user.role==='admin'){localStorage.setItem('skillvaya_owner_token',d.token);localStorage.setItem('skillvaya_token',d.token);localStorage.removeItem('sv_token');location.replace('/owner-app');return;}localStorage.setItem('skillvaya_token',d.token);localStorage.setItem('sv_token',d.token);localStorage.setItem('skillvaya_user',JSON.stringify({id:d.user.id,name:d.user.name,email:d.user.email,role:d.user.role}));location.replace('/customer-app');}catch(err){statusEl.textContent='Could not connect. Please check your connection and try again.';}finally{submit.disabled=false;}});</script></body></html>"""

OWNER_APP_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#071426"><title>Skillvaya | Owner App</title>
<style>
:root{color-scheme:dark;font:15px/1.5 Inter,"Segoe UI",Arial,sans-serif;--bg:#071426;--panel:#10213a;--panel2:#142b47;--line:#294766;--ink:#edf5ff;--muted:#a8bdd5;--blue:#147df5;--cyan:#27d5ce;--red:#ef476f}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 80% -10%,#17436b 0,transparent 42%),var(--bg);color:var(--ink)}button,input,select,textarea{font:inherit}button{cursor:pointer;border:1px solid var(--line);border-radius:9px;background:#183451;color:var(--ink);padding:10px 13px;font-weight:650}button:hover{border-color:var(--cyan)}button:disabled{opacity:.5;cursor:wait}button.primary{background:linear-gradient(110deg,#087af2,#08a8c2);border:0;color:white}button.danger{background:#8d1f3e;border-color:#e34a70}input,select,textarea{width:100%;padding:11px;border:1px solid var(--line);border-radius:8px;background:#08182a;color:white;margin:5px 0 14px}label{display:block;color:#d6e6f7;font-size:13px;font-weight:650}.muted{color:var(--muted)}.hidden{display:none!important}.login-wrap{min-height:100dvh;display:grid;place-items:center;padding:20px}.login-card{width:min(100%,480px);padding:28px;border:1px solid var(--line);border-radius:20px;background:rgba(13,31,52,.96);box-shadow:0 24px 80px #0008}.brand{display:flex;gap:12px;align-items:center;font-size:25px;font-weight:850}.brand img{width:48px;height:48px;object-fit:contain}.crown{color:#f5c66b}.layout{min-height:100dvh;display:grid;grid-template-columns:250px minmax(0,1fr)}aside{padding:18px 14px;background:#08182a;border-right:1px solid var(--line);display:flex;flex-direction:column;gap:8px}aside .brand{font-size:20px;padding:6px 8px 18px}nav{display:grid;gap:6px}nav button{text-align:left;background:transparent;border-color:transparent}nav button.active{background:#0b4e82;border-color:#176ca8;color:#fff}main{min-width:0;padding:22px;max-width:1600px;width:100%;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.top h1{margin:0;font-size:clamp(24px,3vw,34px)}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:20px 0}.stat,.panel{border:1px solid var(--line);border-radius:14px;background:linear-gradient(145deg,#10243b,#0d1c30);padding:16px}.stat strong{display:block;font-size:23px;margin-top:5px}.hero{padding:22px;border:1px solid #245177;border-radius:16px;background:linear-gradient(115deg,#102d4c,#103b50);margin:18px 0}.hero h2{margin:0 0 6px}.quick{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:14px 0 22px}.quick button{min-height:92px;text-align:left;display:flex;flex-direction:column;justify-content:center;gap:4px}.quick small{color:var(--muted);font-weight:400}.notice{border:1px solid #295779;border-radius:10px;padding:12px;background:#102942;color:#d8eaff}.status{min-height:24px;margin:8px 0;color:#9be7d4}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:14px 0}.toolbar input{max-width:380px;margin:0}.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;min-width:680px;background:#0b1b2e}th,td{text-align:left;padding:11px 12px;border-bottom:1px solid #213a54;vertical-align:top}th{color:#a9c8e7;background:#10243a;font-size:12px;text-transform:uppercase;letter-spacing:.04em}tr:hover td{background:#10253b}.pill{display:inline-block;padding:3px 8px;border-radius:99px;background:#183e59;color:#cce8ff;font-size:12px}.pill.red{background:#61223b;color:#ffd3df}.formgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.formgrid label input,.formgrid label select{margin-bottom:4px}.empty{padding:25px;text-align:center;color:var(--muted)}@media(max-width:1050px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.quick{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:720px){.layout{grid-template-columns:1fr}aside{position:sticky;top:0;z-index:10;border-right:0;border-bottom:1px solid var(--line);padding:8px}aside .brand{padding:4px 6px 8px}nav{display:flex;overflow-x:auto;gap:5px}nav button{white-space:nowrap;padding:9px 11px}main{padding:13px}.cards{gap:8px}.stat{padding:12px}.stat strong{font-size:19px}.quick{grid-template-columns:1fr 1fr}.formgrid{grid-template-columns:1fr}}@media(max-width:420px){.quick{grid-template-columns:1fr}.cards{grid-template-columns:1fr 1fr}}
#zoomTools{position:fixed;right:10px;bottom:12px;z-index:9999;display:none;align-items:center;gap:5px;padding:6px;border:1px solid #3c6586;border-radius:12px;background:#071426ee;box-shadow:0 6px 24px #0008}#zoomTools button{min-width:38px;min-height:38px;padding:6px 10px;font-size:18px}#zoomTools span{min-width:48px;text-align:center;font-size:12px;font-weight:700}body.owner-app-active #zoomTools{display:flex}body{zoom:var(--ui-zoom,1)}@media(max-width:480px){#zoomTools{right:6px;bottom:6px;gap:3px;padding:4px}#zoomTools button{min-width:34px;min-height:34px;padding:4px 8px}}
/* SV75-HEADERS-01 owner dashboard: the page title bar stays on screen while the dashboard scrolls */
main>.top:first-child{position:sticky;top:0;z-index:40;background:var(--bg);padding:10px 0;margin:0 0 10px;box-shadow:0 8px 14px -12px #000}main>.top:first-child h1{font-size:22px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}main>.top:first-child .muted{font-size:12px}
/* SV80-OWNER-MOBILE: the owner app fits phone screens (Galaxy A14 = 384px wide) with the same layout. */
@media(max-width:720px){
.layout{grid-template-columns:minmax(0,1fr)!important}
aside,main,nav,#panel{min-width:0;max-width:100%}
aside{padding:8px 8px 6px;gap:6px}
aside .brand{font-size:17px;padding:2px 4px 4px}aside .brand img{width:34px;height:34px}
nav{-webkit-overflow-scrolling:touch;scrollbar-width:none;padding-bottom:2px}nav::-webkit-scrollbar{display:none}
nav button{font-size:13px;padding:8px 10px}
aside>div.muted:last-child{position:absolute;top:10px;right:10px;margin:0!important;font-size:0}
aside>div.muted:last-child button{width:auto!important;margin:0!important;font-size:12px;padding:6px 10px}
main{padding:10px 12px 80px}
main>.top:first-child{padding:8px 0;margin:0 0 6px}main>.top:first-child h1{font-size:19px}main>.top:first-child .muted{display:none}main>.top:first-child button{padding:7px 10px;font-size:13px}
.hero{padding:14px;margin:10px 0}.hero h2{font-size:18px}.hero p{font-size:14px}.hero button{margin:4px 0}
h2{font-size:18px}h3{font-size:16px}
.panel{padding:12px;margin:0 0 10px}
.cards{margin:12px 0}.stat{padding:10px}.stat strong{font-size:18px}.stat .muted{font-size:12px}
.quick{gap:8px}.quick button{min-height:62px;padding:10px 12px}
.toolbar input{max-width:none;flex:1 1 100%}
.tablewrap{overflow:visible;border:0;border-radius:0}
table{min-width:0!important;background:transparent}
thead{display:none}
tr{display:block;border:1px solid var(--line);border-radius:12px;margin:0 0 10px;background:#0b1b2e;padding:4px 12px}
tr:hover td{background:transparent}
td{display:grid;grid-template-columns:minmax(84px,32%) minmax(0,1fr);gap:10px;padding:8px 0;border-bottom:1px solid #1a3149;overflow-wrap:anywhere;font-size:14px}
td:last-child{border-bottom:0}
td::before{content:attr(data-label);color:#a9c8e7;font-size:11px;text-transform:uppercase;letter-spacing:.04em;font-weight:700;padding-top:2px}
td.empty{display:block}td.empty::before{content:none}
td button{margin:2px 4px 2px 0;padding:8px 11px;font-size:13px}td .cell{min-width:0}td .pill{margin:0 4px 4px 0}
#zoomTools{left:50%;right:auto;transform:translateX(-50%);bottom:8px;padding:3px;gap:2px;opacity:.92}#zoomTools button{min-width:30px;min-height:30px;padding:2px 8px;font-size:14px}#zoomTools span{min-width:38px;font-size:11px}
input,select,textarea{font-size:16px}
}
</style></head><body><div id="zoomTools" aria-label="Screen zoom controls"><button type="button" onclick="changeUiZoom(-0.1)" aria-label="Zoom out">−</button><span id="zoomValue">100%</span><button type="button" onclick="changeUiZoom(0.1)" aria-label="Zoom in">+</button><button type="button" onclick="resetUiZoom()" aria-label="Reset zoom">Reset</button></div>
<section id="loginScreen" class="login-wrap"><div class="login-card"><div class="brand"><img src="/sv-logo.jpeg" alt="Skillvaya"><div>Skillvaya <span class="crown">♛</span><div class="muted" style="font-size:14px;font-weight:600">Owner App · Full Platform Control</div></div></div><div class="hero"><h2>Complete control. A stronger platform.</h2><p class="muted">Manage users, providers, reports, subscriptions, payments, promotions and settings from one protected console.</p></div><form id="ownerLoginForm"><label for="ownerEmail">Owner email</label><input id="ownerEmail" type="email" autocomplete="username" required><label for="ownerPassword">Password</label><input id="ownerPassword" type="password" autocomplete="current-password" required><label><input id="ownerAgree" type="checkbox" style="width:auto;margin-right:8px">I agree to the current Skillvaya Terms & Conditions.</label><button class="primary" type="submit" style="width:100%;margin-top:12px">Sign in to Owner App</button><p id="loginStatus" class="status" role="status"></p><p class="muted">Only the authorised owner account can access these controls.</p></form></div></section>
<div id="appShell" class="layout hidden"><aside><div class="brand"><img src="/sv-logo.jpeg" alt=""><div>Skillvaya <span class="crown">♛</span><div class="muted" style="font-size:12px">OWNER APP</div></div></div><nav id="ownerNav"><button class="active" data-area="dashboard" onclick="showArea('dashboard')">▦ Dashboard</button><button data-area="clients" onclick="showArea('clients')">♙ Customers & Providers</button><button data-area="inbox" onclick="showArea('inbox')">✉ Email Centre & Inbox</button><button data-area="complaints" onclick="showArea('complaints')">⚑ Reports & Complaints</button><button data-area="payments" onclick="showArea('payments')">▤ Payments & Subscriptions</button><button data-area="owner-promotions" onclick="showArea('owner-promotions')">✧ Advertising & Promotions</button><button data-area="listings" onclick="showArea('listings')">✔ Listings & Verification</button><button data-area="futurechat" onclick="showArea('futurechat')">💬 Future Chat Launch</button><button data-area="account-deletions" onclick="showArea(\'account-deletions\')">Account deletion requests</button><button data-area="accessControl" onclick="showArea('accessControl')">🔒 Customer & Provider Access</button><button data-area="settings" onclick="showArea('settings')">⚙ Platform Settings</button></nav><div style="margin-top:auto" class="muted">Private owner access<br><button onclick="ownerLogout()" style="width:100%;margin-top:10px">Sign out</button></div></aside>
<main><div class="top"><div><h1 id="pageTitle">Owner Dashboard</h1><div class="muted">Your platform, your oversight — with protected, auditable controls.</div></div><button onclick="refreshCurrent()">↻ Refresh</button></div><div id="globalStatus" class="status" role="status"></div><section id="panel"></section></main></div>
<script>
const titles={accessControl:'Customer & Provider Access',dashboard:'Owner Dashboard',clients:'Customers & Providers',inbox:'Email Centre & Inbox',complaints:'Reports, Warnings & Complaints',payments:'Payments & Subscriptions','owner-promotions':'Advertising & Promotions','account-deletions':'Account deletion requests',settings:'Platform Settings',listings:'Listings & Verification',futurechat:'Future Chat Launch'};
let currentArea='dashboard',ownerToken='';
const $=id=>document.getElementById(id);
let uiZoom=1;
function applyUiZoom(){document.documentElement.style.setProperty('--ui-zoom',String(uiZoom));$('zoomValue').textContent=Math.round(uiZoom*100)+'%'}
function changeUiZoom(delta){uiZoom=Math.max(0.6,Math.min(1.4,Math.round((uiZoom+delta)*10)/10));applyUiZoom()}
function resetUiZoom(){uiZoom=1;applyUiZoom()}
applyUiZoom();
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function api(path,opts={}){const token=ownerToken||localStorage.getItem('skillvaya_owner_token')||localStorage.getItem('skillvaya_token')||localStorage.getItem('sv_token')||sessionStorage.getItem('skillvaya_token')||sessionStorage.getItem('sv_token');const headers={'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{}),...(opts.headers||{})};const r=await fetch(path,{...opts,headers,cache:opts.cache||'no-store'});let d={};try{d=await r.json()}catch(e){}if(!r.ok)throw Error(d.error||'Request failed ('+r.status+')');return d}
function status(msg){$('globalStatus').textContent=msg||''}
async function activateShell(){try{document.body.classList.add('owner-app-active');$('loginScreen').classList.add('hidden');$('appShell').classList.remove('hidden');$('pageTitle').textContent='Owner Dashboard';$('panel').innerHTML='<div class="hero"><h2>Opening Owner Dashboard…</h2><p class="muted">Loading your platform controls. Please wait.</p></div>';window.scrollTo(0,0);await showArea('dashboard')}catch(e){const p=$('panel');if(p)p.innerHTML='<div class="hero"><h2>Welcome to Skillvaya Owner Control</h2><p class="muted">Your owner workspace is open. Dashboard statistics could not be loaded yet.</p><button class="primary" onclick="showArea(\'dashboard\')">Retry dashboard</button> <button onclick="showArea(\'clients\')">Manage users & providers</button></div>';console.error('Owner dashboard activation failed:',e)}}
async function showArea(area){currentArea=area;$('pageTitle').textContent=titles[area]||area;document.querySelectorAll('#ownerNav button').forEach(b=>b.classList.toggle('active',b.dataset.area===area));status('');$('panel').innerHTML='<div class="panel">Loading '+esc(titles[area]||area)+'…</div>';try{if(area==='dashboard')await renderDashboard();else if(area==='clients')await renderClients();else if(area==='inbox')await renderInbox();else if(area==='complaints')await renderComplaints();else if(area==='payments')await renderPayments();else if(area==='owner-promotions')await renderPromotions();else if(area==='account-deletions')await renderAccountDeletions();else if(area==='settings')await renderSettings();else if(area==='accessControl')await renderAccessControl();else if(area==='listings')await renderListings();else if(area==='futurechat')await renderFutureChat()}catch(e){$('panel').innerHTML='<div class="panel"><h2>Could not load this section</h2><p>'+esc(e.message)+'</p><button onclick="showArea(currentArea)">Try again</button></div>'}window.scrollTo(0,0)}
function metric(label,value,note=''){return '<div class="stat"><span class="muted">'+esc(label)+'</span><strong>'+esc(value)+'</strong><span class="muted">'+esc(note)+'</span></div>'}
function table(headers,rows){return '<div class="tablewrap"><table><thead><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+(rows.length?rows.map(row=>'<tr>'+row.map((x,i)=>'<td data-label="'+esc(headers[i]||'')+'"><div class="cell">'+x+'</div></td>').join('')+'</tr>').join(''):'<tr><td colspan="'+headers.length+'" class="empty">No records found.</td></tr>')+'</tbody></table></div>'}
async function renderDashboard(){
 const dashboardMarkup=(x={},s={},warning='')=>{
  $('panel').innerHTML=(warning?'<div class="notice">Dashboard is open; some statistics could not be loaded. '+esc(warning)+'</div>':'')+
  '<div class="hero"><h2>Welcome to Skillvaya Owner Control</h2><p class="muted">Your owner dashboard is ready. Statistics will fill in as the server responds.</p><button class="primary" onclick="showArea(\'clients\')">Manage users & providers</button> <button class="danger" onclick="showArea(\'clients\')">Ban / Suspend Accounts</button></div>'+
  '<div class="cards">'+metric('Total accounts',x.accounts??'—')+metric('Providers',x.providers??'—')+metric('Open complaints',s.complaints??'—')+metric('Pending payments',s.payments??'—')+metric('Verified payments',x.verified_payments??'—')+metric('Verified revenue','R'+Number(x.revenue||0).toLocaleString('en-ZA'))+metric('Listings',s.businesses??'—')+metric('Pending listings',s.pending??'—')+'</div>'+
  '<div class="cards" id="ownerGrowthCards"></div><h2>Control shortcuts</h2><div class="quick"><button onclick="showArea(\'listings\')">✔ Listings & Verification<small>Approve verified badges, suspend or restore listings</small></button><button onclick="showArea(\'futurechat\')">💬 Future Chat Launch<small>See who is waiting and announce the launch</small></button><button onclick="location.href=\'/customer-app\'">👁 View the customer app<small>See Skillvaya the way customers see it</small></button><button onclick="showArea(\'clients\')">♙ Customers & Providers<small>Search accounts, inspect roles and manage access</small></button><button class="danger" onclick="showArea(\'clients\')">⛨ Ban / Suspend Users<small>Reasoned actions with a record</small></button><button onclick="showArea(\'complaints\')">⚑ Reports & Complaints<small>Review and resolve reports</small></button><button onclick="showArea(\'payments\')">▤ Payments & Subscriptions<small>Live PayPal status and payment records</small></button><button onclick="showArea(\'inbox\')">✉ Email Centre & Inbox<small>Notifications and compose email</small></button><button onclick="showArea(\'owner-promotions\')">✧ Advertising & Promotions<small>Manage listings, ads and campaigns</small></button></div><div class="notice">High-impact account actions require a reason and confirmation. Account records and payment history are retained.</div>';
 };
 // Paint the usable dashboard immediately; never leave the owner trapped on a loading screen while statistics load.
 dashboardMarkup();
 const timeout=(label)=>new Promise(resolve=>setTimeout(()=>resolve({error:label}),7000));
 const [s,a]=await Promise.all([
  Promise.race([api('/api/admin/summary').catch(e=>({error:e.message})),timeout('Summary request timed out.')]),
  Promise.race([api('/api/admin/analytics').catch(e=>({stats:{},error:e.message})),timeout('Analytics request timed out.')])
 ]);
 dashboardMarkup(a.stats||{},s,[s.error,a.error].filter(Boolean).join(' · '));ownerGrowthStats();
}
let cachedUsers=[];
async function renderClients(){const d=await api('/api/admin/clients');cachedUsers=d.items||[];$('panel').innerHTML='<div class="panel"><h2>Customers & Providers</h2><p class="muted">Search every account. Ban/suspend blocks sign-in and revokes active sessions; restore returns an account to its original role.</p><div class="toolbar"><input id="userSearch" placeholder="Search name, email, role or account ID" oninput="filterUsers()"><button onclick="renderClients()">Refresh accounts</button></div><div id="usersTable"></div></div><div class="panel"><h3>Moderation audit trail</h3><p class="muted">Recent account-access decisions are recorded in Skillvaya alerts with the actor, account, action and reason.</p><button onclick="showArea(\'inbox\')">View audit records in Email Centre & Inbox</button></div>';filterUsers()}
function filterUsers(){const q=($('userSearch')?.value||'').toLowerCase();const items=cachedUsers.filter(u=>[u.id,u.name,u.email,u.role].some(v=>String(v||'').toLowerCase().includes(q)));$('usersTable').innerHTML=table(['Account','Email / ID','Role / Status','Listings','Verified payments','Access control'],items.map(u=>{let action=u.role==='admin'?'<span class="pill">Protected owner</span>':u.role==='suspended'?'<button class="primary" onclick="accountAccess('+Number(u.id)+',\'restore\')">Restore access</button>':'<button class="danger" onclick="accountAccess('+Number(u.id)+',\'suspend\')">Ban / Suspend</button>';return ['<strong>'+esc(u.name)+'</strong><br><span class="muted">'+esc(u.created_at||'')+'</span>',esc(u.email)+'<br><span class="muted">#'+esc(u.id)+'</span>','<span class="pill '+(u.role==='suspended'?'red':'')+'">'+esc(u.role)+'</span>',esc(u.businesses??0),esc(u.paid??0),action]}))}
async function accountAccess(id,action){const user=cachedUsers.find(u=>Number(u.id)===Number(id));if(!user)return;let reason='';if(action==='suspend'){reason=prompt('Enter the reason for banning/suspending '+user.name+' (required and recorded):','');if(reason===null)return;if(reason.trim().length<3){alert('Please provide a reason of at least 3 characters.');return}if(!confirm('Suspend '+user.name+' ('+user.email+') and revoke active sessions? Their records and payments will be preserved.'))return}else if(!confirm('Restore sign-in access for '+user.name+'?'))return;try{const d=await api('/api/admin/accounts/'+id+'/access',{method:'POST',body:JSON.stringify({action,reason})});status(d.message||'Account access updated.');await renderClients()}catch(e){alert(e.message)}}
async function renderComplaints(){const d=await api('/api/admin/complaints');const items=d.items||[];$('panel').innerHTML='<div class="panel"><h2>Reports, Warnings & Complaints</h2><p class="muted">Review the submitted concern and record resolution. For an account ban, use Customers & Providers.</p>'+table(['Report','Business','Reason','Status','Action'],items.map(x=>[esc(x.id)+'<br>'+esc(x.created_at||''),esc(x.business_name||'Listing #'+x.business_id),esc(x.reason),'<span class="pill">'+esc(x.status)+'</span>',(x.status==='reviewed'?'<span class="muted">Reviewed</span>':'<button onclick="resolveComplaint('+Number(x.id)+')">Mark reviewed</button>')+' <button class="danger" onclick="ownerSuspendFromReport('+Number(x.business_id)+')">Suspend listing</button>']))+'</div>'}
async function resolveComplaint(id){if(!confirm('Mark report #'+id+' as reviewed?'))return;try{await api('/api/admin/complaints/'+id,{method:'POST',body:'{}'});status('Report marked reviewed.');await renderComplaints()}catch(e){alert(e.message)}}
async function renderPayments(){
 const [d,g]=await Promise.all([api('/api/admin/payments'),api('/api/admin/paypal/status')]);
 const rows=(d.items||[]).map(x=>{
  let action='<span class="muted">No manual action</span>';
  if(x.status==='pending'&&String(x.reference||'').startsWith('BT-SV-')) action='<button class="primary" onclick="confirmBankTransfer('+Number(x.id)+',&quot;'+esc(x.reference)+'&quot;)">Accept after funds received</button>';
  else if(x.status==='verified') action='<span class="muted">Confirmed</span>';
  return [esc(x.reference),esc(x.user_id),'R'+esc(x.amount),esc(x.plan)+' / '+esc(x.billing),'<span class="pill">'+esc(x.status)+'</span>',esc(x.refund_status||'none'),action];
 });
 $('panel').innerHTML='<div class="hero"><h2>Payments & Subscriptions</h2><p>PayPal mode: <strong>'+esc(g.mode||'unknown')+'</strong> · Credentials: '+(g.credentials_configured?'configured':'missing')+' · OAuth: '+(g.oauth_valid?'verified':'not verified')+'</p><p class="muted">'+esc(g.message||'')+'</p><p class="muted">Pending bank transfers can be confirmed here only after you have checked that the money has cleared in your bank account. PayPal payments must still be verified by PayPal.</p></div><div class="panel">'+table(['Reference','Account ID','Amount','Plan','Status','Refund status','Action'],rows)+'</div>';
}
async function confirmBankTransfer(id,reference){if(!confirm('Have you checked your bank account and confirmed that the full amount for '+reference+' has cleared? Only accept if the funds are actually received.'))return;try{const d=await api('/api/admin/payments/'+Number(id),{method:'POST',body:'{}'});status(d.already_verified?'This payment was already confirmed.':'Bank transfer confirmed and subscription activated.');await renderPayments()}catch(e){alert('Could not confirm bank transfer: '+e.message)}}
async function renderInbox(){const d=await api('/api/admin/notifications');$('panel').innerHTML='<div class="panel"><h2>Email Centre & Inbox</h2><p class="muted">System alerts, sent-message records and moderation notes stored in Skillvaya. This is not a live Gmail mirror.</p><div class="toolbar"><button class="primary" onclick="composeEmail()">Compose email</button><button onclick="renderInbox()">Refresh inbox</button></div>'+table(['Date','Type','Subject','Status','Recipient','Message'],(d.items||[]).map(x=>[esc(x.created_at),esc(x.kind),esc(x.subject),esc(x.status),esc(x.recipient),esc(x.body)]))+'</div>'}
async function composeEmail(){const d=await api('/api/admin/clients');const items=d.items||[];$('panel').innerHTML='<div class="panel"><h2>Compose email</h2><form id="composeForm"><label>Recipient account</label><select name="client_id" required><option value="">Choose a customer or provider</option>'+items.map(x=>'<option value="'+Number(x.id)+'">'+esc(x.name)+' — '+esc(x.email)+' ('+esc(x.role)+')</option>').join('')+'</select><label>Subject</label><input name="subject" maxlength="180" required><label>Message</label><textarea name="body" rows="6" maxlength="10000" required></textarea><button class="primary">Send email</button> <button type="button" onclick="renderInbox()">Cancel</button><p id="composeStatus" class="status"></p></form></div>';$('composeForm').onsubmit=async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.target));$('composeStatus').textContent='Sending…';try{const r=await api('/api/admin/email-client',{method:'POST',body:JSON.stringify(f)});$('composeStatus').textContent='Sent to '+r.recipient; }catch(err){$('composeStatus').textContent='Not sent: '+err.message}}}
async function renderPromotions(){const d=await api('/api/admin/owner-promotions');const items=d.items||[];window.ownerPromotionItems=items;const cats=['Builders & construction','Plumbers','Electricians','Painters & decorators','Mechanics & automotive','Cleaning & housekeeping','Gardening & landscaping','Roofing & waterproofing','Carpenters & furniture','Welders & fabricators','Appliance repairs','IT & computer support','Graphic designers','Artists & photographers','Marketing & advertising','Web & software developers','Lawyers & legal services','Private doctors & clinics','Dentists & specialists','Nurses & home care','Accountants & tax','Financial & insurance services','Real estate & property','Tutors & education','Beauty & hair','Catering & chefs','Transport & removals','Security services','Events & entertainment','Tailors & fashion','Arts & crafts','Pet care & veterinary','Funeral services','Engineering & consulting','Other professional services'];$('panel').innerHTML='<div class="panel"><h2>Advertising & Promotions</h2><p class="muted">Create and manage owner listings, advertisements, products, services and apps. Owner-created entries retain the existing fee exemption.</p><form id="promoForm"><input type="hidden" name="promotion_id"><div class="formgrid"><label>Entry type<select name="kind"><option value="business">Business</option><option value="ad">Advertisement / product / service</option><option value="app">App</option></select></label><label>Business / brand name<input name="business_name" maxlength="120" required></label><label>Listing title<input name="title" maxlength="160" required></label><label>Category<select name="category">'+cats.map(c=>'<option>'+esc(c)+'</option>').join('')+'</select></label><label>Website / target URL<input name="target_url" type="url" maxlength="500"></label><label>Image URL<input name="image_url" type="url" maxlength="1000"></label></div><label>Description<textarea name="description" maxlength="3000" rows="3" required></textarea></label><div class="formgrid"><label>Service area<input name="area" maxlength="120"></label><label>Public phone<input name="phone" maxlength="40"></label><label>WhatsApp<input name="whatsapp" maxlength="40"></label><label>Contact email<input name="contact_email" type="email" maxlength="254"></label></div><button class="primary">Save & publish</button> <button type="button" onclick="resetPromo()">Clear form</button><p id="promoStatus" class="status"></p></form></div><div class="panel"><h2>Current entries</h2>'+table(['Type','Name','Title','Status','Action'],items.map(x=>[esc(x.kind),esc(x.business_name),esc(x.title),'<span class="pill">'+esc(x.status)+'</span>','<button onclick="editPromo('+Number(x.id)+')">Edit</button> <button onclick="promoStatus('+Number(x.id)+',\''+(x.status==='active'?'paused':'active')+'\')">'+(x.status==='active'?'Pause':'Publish')+'</button> <button class="danger" onclick="promoStatus('+Number(x.id)+',\'removed\')">Remove</button>']))+'</div>';$('promoForm').onsubmit=async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.target)),id=f.promotion_id;delete f.promotion_id;if(id)f.action='update';try{await api(id?'/api/admin/owner-promotions/'+id:'/api/admin/owner-promotions',{method:'POST',body:JSON.stringify(f)});status('Promotion saved.');await renderPromotions()}catch(err){$('promoStatus').textContent='Could not save: '+err.message}}}
function resetPromo(){$('promoForm').reset();$('promoForm').elements.promotion_id.value='';$('promoStatus').textContent=''}
function editPromo(id){const x=(window.ownerPromotionItems||[]).find(v=>Number(v.id)===id),f=$('promoForm');if(!x)return;for(const k of ['promotion_id','kind','business_name','title','category','target_url','image_url','description','area','phone','whatsapp'])if(f.elements[k])f.elements[k].value=x[k]||'';if(f.elements.contact_email)f.elements.contact_email.value=x.contact_email||'';$('promoStatus').textContent='Editing '+x.business_name}
async function promoStatus(id,st){if(st==='removed'&&!confirm('Remove this promotion from public listings?'))return;try{await api('/api/admin/owner-promotions/'+id,{method:'POST',body:JSON.stringify({status:st})});status('Promotion status updated.');await renderPromotions()}catch(e){alert(e.message)}}
async function renderAccessControl(){const d=await api('/api/admin/access-control');$('panel').innerHTML='<div class="panel"><h2>Customer & Service Provider Access</h2><p class="muted">Owner access always stays available. Notify both customer and Work Finder/provider sides before switching access off.</p><div class="notice"><strong>Current status: '+(d.enabled?'ON — customers and providers can use Skillvaya':'OFF — customer and provider access is paused')+'</strong></div><h3>Send an in-app notification first</h3><form id="broadcastForm"><label>Notification title<input name="subject" maxlength="160" required placeholder="Important Skillvaya notice"></label><label>Message<textarea name="body" maxlength="5000" rows="5" required placeholder="Type the notice customers and service providers should receive…"></textarea></label><button class="primary">Send to customers and providers</button><p class="muted">Saved for both customer and provider/Work Finder sides.</p></form><hr><h3>Access switch</h3><p>Turning access off does not disable this Owner Control panel or owner payment approval.</p><button class="primary" id="accessOn" '+(d.enabled?'disabled':'')+'>Turn customer/provider access ON</button> <button id="accessOff" '+(!d.enabled?'disabled':'')+'>Turn customer/provider access OFF</button><p id="accessStatus" class="status"></p><h3>Recent notices</h3>'+table(['Sent','Title','Message'],(d.notices||[]).map(x=>[esc(x.created_at),esc(x.subject),esc(x.body)]))+'</div>';document.getElementById('broadcastForm').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.currentTarget);if(!confirm('Send this notification to both customers and service providers?'))return;try{await api('/api/admin/broadcast-notification',{method:'POST',body:JSON.stringify({subject:f.get('subject'),body:f.get('body')})});$('accessStatus').textContent='Notification saved for both sides.';await renderAccessControl()}catch(err){$('accessStatus').textContent=err.message}};async function setAccess(enabled){if(!confirm(enabled?'Restore customer and service provider access now?':'Switch customer and service provider access OFF? The owner panel will remain available.'))return;try{await api('/api/admin/access-control',{method:'POST',body:JSON.stringify({enabled})});await renderAccessControl()}catch(err){$('accessStatus').textContent=err.message}}document.getElementById('accessOn').onclick=()=>setAccess(true);document.getElementById('accessOff').onclick=()=>setAccess(false)}
async function renderAccountDeletions(){const d=await api('/api/admin/account-deletion-requests');const items=d.items||[];$('panel').innerHTML='<div class="panel"><h2>Account deletion requests</h2><p class="muted">Verify each request before completing it. Completion permanently deletes the account and associated app personal data; limited financial or security records may be retained where required. This cannot be undone.</p><div class="toolbar"><span>'+items.length+' pending request(s)</span><button onclick="renderAccountDeletions()">Refresh</button></div>'+table(['Request','Account','Reason','Requested','Action'],items.map(x=>['#'+Number(x.id),esc(x.user_name||'Account unavailable')+'<br>'+esc(x.user_email||'')+'<br>User ID '+Number(x.user_id),esc(x.reason||'No reason supplied'),esc(x.requested_at||''),'<button class="danger" onclick="completeAccountDeletion('+Number(x.id)+')">Verify & delete</button>']))+'</div>'}
async function completeAccountDeletion(id){if(!confirm('FINAL CONFIRMATION: permanently delete the account and associated Skillvaya personal data for request #'+id+'? Verify the requester first. This cannot be undone.'))return;try{const d=await api('/api/admin/account-deletion-requests/'+encodeURIComponent(id)+'/complete',{method:'POST',body:JSON.stringify({confirm:true})});alert((d.message||'Deletion completed.')+'\nCompletion acknowledgement email confirmed: '+(d.acknowledgement_email_sent?'Yes':'No'));await renderAccountDeletions()}catch(e){alert('Deletion not completed: '+e.message)}}
async function renderSettings(){const d=await api('/api/admin/settings');$('panel').innerHTML='<div class="panel"><h2>Platform Settings</h2><p class="muted">Owner notifications and email delivery status. Existing live payment settings are not changed here.</p><form id="settingsForm"><label>Owner notification email<input type="email" name="owner_email" value="'+esc(d.owner_email)+'" maxlength="254" required></label><button class="primary">Save notification email</button> <button type="button" onclick="testEmail()">Send test email</button><p id="settingsStatus" class="status"></p></form><div class="notice">'+(d.smtp_configured?'SMTP credentials detected.':'SMTP is not configured on the server; messages may be recorded but cannot be delivered.')+' '+esc(d.note||'')+'</div><h3>Security</h3><p class="muted">Admin API requests are authenticated server-side. Do not share owner credentials.</p></div>';$('settingsForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/admin/settings',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});$('settingsStatus').textContent='Owner email saved.'}catch(err){$('settingsStatus').textContent=err.message}}}
async function testEmail(){try{await api('/api/admin/test-email',{method:'POST',body:'{}'});alert('Test email sent.')}catch(e){alert(e.message)}}
/* SV80: listings & verification, Future Chat launch, growth stats. */
async function ownerGrowthStats(){try{const [b,f]=await Promise.all([api('/api/admin/businesses').catch(()=>({items:[]})),api('/api/futurechat/status').catch(()=>({}))]);const items=b.items||[];const req=items.filter(x=>x.verify_requested_at&&!x.verified_at).length,ver=items.filter(x=>x.verified_at).length;const el=$('ownerGrowthCards');if(el)el.innerHTML=metric('Verification requests',req,req?'Waiting for you':'')+metric('Verified providers',ver)+metric('Future Chat waitlist',f.count??'—')+metric('Active listings',items.filter(x=>x.status==='active').length)}catch(_){}}
let cachedListings=[];
async function renderListings(){const d=await api('/api/admin/businesses');cachedListings=(d.items||[]).slice().sort((a,b)=>((b.verify_requested_at&&!b.verified_at)?1:0)-((a.verify_requested_at&&!a.verified_at)?1:0));const req=cachedListings.filter(x=>x.verify_requested_at&&!x.verified_at).length;$('panel').innerHTML='<div class="panel"><h2>Listings & Verification</h2><p class="muted">Providers ask for the verified badge from their app. Check who they are (call them, see their ID and business) before you verify. Suspending a listing hides it from customers until you restore it.</p>'+(req?'<div class="notice"><strong>'+req+' verification request'+(req===1?'':'s')+' waiting.</strong> They are listed first.</div>':'')+'<div class="toolbar"><input id="listingSearch" placeholder="Search name, category, area or phone" oninput="filterListings()"><button onclick="renderListings()">Refresh</button></div><div id="listingsTable"></div></div>';filterListings()}
function filterListings(){const q=($('listingSearch')?.value||'').toLowerCase();const items=cachedListings.filter(x=>[x.id,x.name,x.category,x.area,x.phone,x.email].some(v=>String(v||'').toLowerCase().includes(q)));$('listingsTable').innerHTML=table(['Listing','Contact','Plan / Status','Verified','Actions'],items.map(x=>{const v=x.verified_at?'<span class="pill">✔ Verified</span>':(x.verify_requested_at?'<span class="pill red">Requested</span>':'<span class="muted">No</span>');const act=(x.verified_at?'<button onclick="ownerVerify('+Number(x.id)+',false)">Remove badge</button>':'<button class="primary" onclick="ownerVerify('+Number(x.id)+',true)">✔ Verify</button>')+' '+(x.status==='active'?'<button class="danger" onclick="ownerListingStatus('+Number(x.id)+',\'suspended\')">Suspend</button>':'<button onclick="ownerListingStatus('+Number(x.id)+',\'active\')">Restore</button>');return ['<strong>'+esc(x.name)+'</strong><br><span class="muted">'+esc(x.category)+' · '+esc(x.area)+'</span>',esc(x.phone||'')+'<br><span class="muted">'+esc(x.email||'')+'</span>','<span class="pill">'+esc(x.plan||'local')+'</span> <span class="pill '+(x.status==='active'?'':'red')+'">'+esc(x.status)+'</span>',v,act]}))}
async function ownerVerify(id,on){const x=cachedListings.find(v=>Number(v.id)===Number(id));if(!x)return;if(!confirm(on?'Give '+x.name+' the "Verified by Skillvaya" badge? Only do this after you have checked who they are.':'Remove the verified badge from '+x.name+'?'))return;try{await api('/api/admin/businesses-verify',{method:'POST',body:JSON.stringify({business_id:Number(id),verified:!!on})});status(on?'Verified badge given.':'Verified badge removed.');await renderListings()}catch(e){alert(e.message)}}
async function ownerListingStatus(id,st){const x=cachedListings.find(v=>Number(v.id)===Number(id));if(!x)return;if(!confirm(st==='active'?'Restore '+x.name+' to the public directory?':'Suspend '+x.name+'? It will be hidden from customers until you restore it.'))return;try{await api('/api/admin/businesses/'+Number(id),{method:'POST',body:JSON.stringify({status:st})});status('Listing updated.');await renderListings()}catch(e){alert(e.message)}}
async function ownerSuspendFromReport(bid){if(!bid)return;if(!confirm('Suspend this listing? It will be hidden from customers until you restore it in Listings & Verification.'))return;try{await api('/api/admin/businesses/'+Number(bid),{method:'POST',body:JSON.stringify({status:'suspended'})});status('Listing suspended. Restore it any time in Listings & Verification.')}catch(e){alert(e.message)}}
async function renderFutureChat(){const d=await api('/api/futurechat/status');const n=Number(d.count||0);$('panel').innerHTML='<div class="hero"><h2>💬 Future Chat launch list</h2><p style="font-size:32px;font-weight:850;margin:6px 0">'+n+'</p><p class="muted">'+(n===1?'person is':'people are')+' waiting for Future Chat. They signed up from the "Notify me" card and the Share button in Skillvaya.</p></div><div class="panel"><h3>Announce the launch</h3><p class="muted">Sends an alert to everyone on the list: Android app, iPhone home-screen app and browsers with alerts switched on.</p><form id="fcForm"><label>Alert message<textarea name="message" rows="3" maxlength="200" required>Future Chat is here! Download it now and start chatting.</textarea></label><button class="primary">Send launch alert</button><p id="fcStatus" class="status"></p></form></div>';$('fcForm').onsubmit=async e=>{e.preventDefault();const m=new FormData(e.target).get('message');if(!confirm('Send this alert to '+n+' '+(n===1?'person':'people')+' now?'))return;try{const r=await api('/api/admin/futurechat',{method:'POST',body:JSON.stringify({action:'announce',message:m})});$('fcStatus').textContent='Sending to '+r.sent+' '+(r.sent===1?'person':'people')+'.'}catch(err){$('fcStatus').textContent=err.message}}}
function refreshCurrent(){showArea(currentArea)}
function ownerLogout(){localStorage.removeItem('skillvaya_owner_token');localStorage.removeItem('skillvaya_token');localStorage.removeItem('sv_token');location.replace('/')}
async function ownerLogin(token){ownerToken=token;localStorage.setItem('skillvaya_owner_token',token);localStorage.setItem('skillvaya_token',token);$('loginStatus').textContent='';await activateShell()}
async function validateOwner(){const candidates=[localStorage.getItem('skillvaya_owner_token'),localStorage.getItem('skillvaya_token'),localStorage.getItem('sv_token'),sessionStorage.getItem('skillvaya_token'),sessionStorage.getItem('sv_token')].filter(Boolean);if(!candidates.length)return;let lastError='';for(const t of [...new Set(candidates)]){try{const r=await fetch('/api/me',{headers:{Authorization:'Bearer '+t},cache:'no-store'});let d={};try{d=await r.json()}catch(e){}if(r.ok&&d.user&&d.user.role==='admin'){await ownerLogin(t);return}if(!r.ok)lastError=d.error||'Your owner session could not be verified.';else if(d.user&&d.user.role!=='admin')lastError='A saved session belongs to a customer or provider, not the owner account.'}catch(e){lastError='Could not verify the saved session. Check your connection.'}}localStorage.removeItem('skillvaya_owner_token');if(lastError)$('loginStatus').textContent=lastError+' Please sign in with the authorised owner account.'}
$('ownerLoginForm').addEventListener('submit',async e=>{e.preventDefault();$('loginStatus').textContent='Signing in…';try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:$('ownerEmail').value.trim(),password:$('ownerPassword').value,accept_terms:$('ownerAgree').checked})});const d=await r.json();if(!r.ok||!d.token||!d.user)throw Error(d.error||'Sign-in failed');if(d.user.role!=='admin')throw Error('This account is not authorised for the owner console.');await ownerLogin(d.token)}catch(err){$('loginStatus').textContent=err.message}});
validateOwner();
</script></body></html>"""
OWNER_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Skillvaya — Owner Control</title><style>
:root{font:15px/1.5 'Segoe UI',Arial;color:#19283b;background:#f4f7fb}*{box-sizing:border-box}body{margin:0}.head{background:#10233f;color:white;padding:20px}.owner-brand{display:flex;align-items:center;gap:12px}.owner-brand img{width:54px;height:54px;object-fit:contain;border-radius:10px;background:#08142b}.wrap{max-width:1100px;margin:auto;padding:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{background:white;border:1px solid #e1e8f1;border-radius:12px;padding:16px;margin-bottom:14px}button{border:0;border-radius:8px;padding:10px 13px;margin:3px;background:#2365d8;color:white;font-weight:650;cursor:pointer}.secondary{background:#eaf0f8;color:#10233f}.muted{color:#66758b}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:620px}td,th{text-align:left;padding:9px;border-bottom:1px solid #e1e8f1;vertical-align:top}.stat{font-size:28px;font-weight:800}.notice{padding:12px;border-radius:9px;background:#eaf7f0;color:#13714d;margin:10px 0}@media(max-width:600px){.wrap{padding:10px}}

/* Premium owner workspace finish */
body{background:radial-gradient(ellipse at 92% 0%,rgba(32,200,193,.08),transparent 32%),#f3f6fb;color:#14263e;-webkit-font-smoothing:antialiased}
.head{background:radial-gradient(ellipse at 90% 0%,#1c5263,#10233f 60%);box-shadow:0 8px 28px rgba(7,20,38,.16);padding:22px 20px}
.owner-brand img{border:1px solid #2e7180;box-shadow:0 8px 20px #06132755}.wrap{max-width:1220px;padding:22px}
.card{border:1px solid #dce6f1;border-radius:17px;padding:20px;box-shadow:0 12px 34px rgba(18,43,76,.065);transition:box-shadow .18s,transform .18s}.card:hover{box-shadow:0 16px 40px rgba(18,43,76,.1)}
button{border-radius:11px;padding:11px 15px;box-shadow:0 3px 9px rgba(16,35,63,.08)}button:hover{transform:translateY(-1px);filter:brightness(1.03)}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid rgba(32,200,193,.6);outline-offset:2px}
input,select,textarea{border:1px solid #d3dfec;border-radius:10px;padding:12px;min-height:44px;width:100%}label{display:block;font-weight:650;margin-top:12px}h1,h2,h3{letter-spacing:-.45px}.stat{font-size:32px;color:#0d6672}.notice{border:1px solid #bfe4d4;border-radius:12px;padding:14px}.tablewrap{border:1px solid #dce6f1;border-radius:14px;overflow:auto}table{border-collapse:separate;border-spacing:0}th{background:#f0f5fa;position:sticky;top:0}td,th{padding:12px;border-bottom:1px solid #e5ecf4}
@media(max-width:600px){.wrap{padding:12px}.head{padding:14px}.card{padding:15px}}/* Mobile-first owner control: compact the existing console without changing its handlers or APIs. */
@media(max-width:700px){
  .head{padding:10px 12px!important}.head>.wrap{padding:0!important}.owner-brand{gap:9px;align-items:center}.owner-brand img{width:38px;height:38px}.head h1{font-size:19px;line-height:1.2}.head .tiny{font-size:12px}.head .wrap>div:nth-child(2){font-size:12px;margin-top:5px!important}.head .wrap>div:nth-child(3){font-size:12px;margin-top:4px!important;overflow-wrap:anywhere}
  .wrap{padding:10px!important;max-width:100%;width:100%}.grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:8px}.card{padding:12px!important;margin-bottom:9px;border-radius:12px}.card h2{font-size:18px;margin:3px 0 8px}.card h3{font-size:16px}.card p{margin:7px 0}.stat{font-size:23px!important;overflow-wrap:anywhere}.muted{font-size:13px}
  #workspacePicker{font-size:16px!important;min-height:44px}.card .grid[style*="align-items:end"]{grid-template-columns:minmax(0,1fr)!important}.card .grid[style*="align-items:end"] button{width:100%;margin:3px 0}.card button{min-height:42px;max-width:100%;white-space:normal;overflow-wrap:anywhere}.tablewrap{max-width:100%;-webkit-overflow-scrolling:touch}.tablewrap table{min-width:600px}input,select,textarea{font-size:16px;max-width:100%}label{font-size:14px}.notice{padding:10px;font-size:13px}
}
@media(max-width:380px){.grid{grid-template-columns:minmax(0,1fr)!important}.head h1{font-size:17px}.stat{font-size:21px!important}}

</style></head><body><header class="head"><div class="wrap"><div class="owner-brand"><img src="/sv-logo.jpeg" alt="SV Skillvaya logo"><div><h1 style="margin:0">Skillvaya - Owner Control</h1><div class="tiny">Owner workspace</div></div></div><div>Private owner console · authenticated access required</div><div style="margin-top:8px">Platform email: <span id="ownerEmailLabel">skillvaya@gmail.com</span></div></div></header><main class="wrap"><div class="notice">This control area is separate from the customer app. Owner data and actions require an authenticated owner session. Local loopback development is the only no-login exception.</div><div class="grid" id="stats"></div><section class="card"><h2>Workspace</h2><p class="muted">Choose one work area. Related tools are grouped together so the control screen is easier to navigate.</p><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));align-items:end"><div><label for="workspacePicker">Open a work area</label><select id="workspacePicker" style="width:100%;padding:12px;border:1px solid #cbd6e4;border-radius:8px;background:white;color:#19283b" onchange="if(this.value){load(this.value)}"><option value="">Select a task…</option><optgroup label="Marketplace"><option value="businesses">Business listings</option><option value="owner-promotions">My businesses & promotions (free)</option></optgroup><optgroup label="Platform operations"><option value="clients">Customer accounts</option><option value="account-deletions">Account deletion requests</option><option value="owner-statistics">Owner statistics</option><option value="owner-subscribers">Paid subscribers</option><option value="owner-accounts">Account access control</option><option value="complaints">Reports & complaints</option><option value="notifications">Alerts & notifications</option><option value="analytics">Usage & analytics</option></optgroup><optgroup label="Payments"><option value="payments">Payments & refunds</option></optgroup><optgroup label="Communications & settings"><option value="inbox">Owner inbox</option><option value="compose">Compose email</option><option value="settings">Email & platform settings</option></optgroup></select></div><div><button onclick="load('summary')">Refresh overview</button> <button onclick="location.href='/owner-app'" class="secondary">Back to Owner App</button></div></div></section><section class="card" id="panel"><h2>Overview</h2><p class="muted">Select a control above.</p></section></main><script>
async function api(path,opts={}){const ownerToken=localStorage.getItem('skillvaya_owner_token');opts.headers={'Content-Type':'application/json',...(ownerToken?{Authorization:'Bearer '+ownerToken}:{}),...(opts.headers||{})};let r=await fetch(path,opts);let d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function load(tab){let p=document.getElementById('panel');try{if(tab==='account-deletions'){const d=await api('/api/admin/account-deletion-requests'),items=d.items||[];p.innerHTML='<h2>Account deletion requests</h2><p class="muted">Verify each request before completing it. Completion permanently deletes the account and associated app personal data; limited financial/security records may be retained where required. This cannot be undone.</p><p>'+items.length+' pending request(s).</p>'+(items.length?'<div class="tablewrap"><table><tr><th>Request</th><th>Account</th><th>Reason</th><th>Requested</th><th>Action</th></tr>'+items.map(x=>'<tr><td>#'+Number(x.id)+'</td><td>'+esc(x.user_name||'Account unavailable')+'<br>'+esc(x.user_email||'')+'<br>User ID '+Number(x.user_id)+'</td><td>'+esc(x.reason||'No reason supplied')+'</td><td>'+esc(x.requested_at||'')+'</td><td><button class="danger" onclick="completeAccountDeletion('+Number(x.id)+')">Verify & delete</button></td></tr>').join('')+'</table></div>':'<p>No pending requests.</p>')+'<p><button class="secondary" onclick="load(\'account-deletions\')">Refresh</button></p>';return}if(tab==='summary'){let d=await api('/api/admin/summary');document.getElementById('stats').innerHTML=Object.entries({Businesses:d.businesses,'Open complaints':d.complaints,'Payment requests':d.payments,'Pending listings':d.pending}).map(([k,v])=>'<div class="card"><div class="muted">'+k+'</div><div class="stat">'+v+'</div></div>').join('');p.innerHTML='<h2>Owner overview</h2><p>Local developer access is active. Customer accounts remain separate and are not automatically signed in.</p>';return}

 if(tab==='owner-statistics'){
 const a=await api('/api/admin/analytics'),s=a.stats||{};
 const c=await api('/api/admin/clients'),users=c.items||[];
 const payResp=await api('/api/admin/payments'),payments=payResp.items||[];
 const paidUsers=new Set(payments.filter(x=>x.status==='verified').map(x=>String(x.user_id)));
 const metrics={'Total accounts':s.accounts||0,'Customers':users.filter(x=>x.role==='customer').length,'Providers':s.providers||0,'Paid accounts':paidUsers.size,'Verified payments':s.verified_payments||0,'Verified revenue':'R'+Number(s.revenue||0).toLocaleString('en-ZA')};
 document.getElementById('stats').innerHTML=Object.entries(metrics).map(([k,v])=>'<div class="card"><div class="muted">'+esc(k)+'</div><div class="stat">'+esc(v)+'</div></div>').join('');
 p.innerHTML='<h2>Owner statistics</h2><p class="muted">Live counts from Skillvaya account and verified-payment records. A paid account is counted once even if it has multiple verified payments.</p><div class="grid">'+Object.entries(metrics).map(([k,v])=>'<div class="card"><div class="muted">'+esc(k)+'</div><div class="stat">'+esc(v)+'</div></div>').join('')+'</div>';
 return;
 }
 if(tab==='owner-subscribers'){
 const [c,payResp]=await Promise.all([api('/api/admin/clients'),api('/api/admin/payments')]);
 const users=c.items||[],payments=payResp.items||[];
 const paid=users.filter(u=>payments.some(x=>String(x.user_id)===String(u.id)&&x.status==='verified'));
 p.innerHTML='<h2>Paid subscribers</h2><p class="muted">Accounts with at least one verified payment. Payment status comes from the existing verified-payment records.</p>'+table(['Account','Email','Role','Verified payments','Paid amount','Account status'],paid.map(u=>{const ps=payments.filter(x=>String(x.user_id)===String(u.id)&&x.status==='verified');return [u.name,u.email,u.role,ps.length,'R'+ps.reduce((n,x)=>n+Number(x.amount||0),0),u.role==='suspended'?'Suspended':'Active']}))+'<p><button onclick="load(\'owner-accounts\')">Manage account access</button></p>';
 return;
 }
 if(tab==='owner-accounts'){
 const d=await api('/api/admin/clients'),items=d.items||[];
 p.innerHTML='<h2>Account access control</h2><p class="muted">Kick out ends existing sessions and suspends the selected paid customer/provider account. Admin accounts cannot be suspended. Restore returns the account to its recorded customer/provider role.</p>'+table(['Name','Email','Role','Paid records','Access action'],items.map(u=>[u.name,u.email,u.role,u.paid, u.role==='admin'?'Protected':u.role==='suspended'?'<button onclick="ownerAccountAccess('+Number(u.id)+',\'restore\')">Restore access</button>':Number(u.paid)>0?'<button class="secondary" onclick="ownerAccountAccess('+Number(u.id)+',\'suspend\')">Kick out subscriber</button>':'Paid subscriber only']));
 return;
 }
 if(tab==='owner-promotions'){
 const d=await api('/api/admin/owner-promotions');window.ownerPromotionItems=d.items||[];
 const cats=['Builders & construction','Plumbers','Electricians','Painters & decorators','Mechanics & automotive','Cleaning & housekeeping','Gardening & landscaping','Roofing & waterproofing','Carpenters & furniture','Welders & fabricators','Appliance repairs','IT & computer support','Graphic designers','Artists & photographers','Marketing & advertising','Web & software developers','Lawyers & legal services','Private doctors & clinics','Dentists & specialists','Nurses & home care','Accountants & tax','Financial & insurance services','Real estate & property','Tutors & education','Beauty & hair','Catering & chefs','Transport & removals','Security services','Events & entertainment','Tailors & fashion','Arts & crafts','Pet care & veterinary','Funeral services','Engineering & consulting','Other professional services'];
 const actions=x=>{const id=Number(x.id),status=x.status==='active'?'paused':'active',label=x.status==='active'?'Pause':'Publish';return `<button class="secondary" onclick="editOwnerPromotion(${id})">Edit</button> <button onclick="ownerPromoStatus(${id}, '${status}')">${label}</button> <button class="secondary" onclick="ownerPromoStatus(${id}, 'removed')">Delete</button>`};
 p.innerHTML=`<h2>My Businesses & Promotions</h2><p>Owner-created business profiles, ads and apps are permanently exempt from Skillvaya listing and subscription fees.</p><form id="ownerPromoForm"><input type="hidden" name="promotion_id" value=""><label>Type</label><select id="ownerPromoKind" name="kind"><option value="business">My business</option><option value="ad">Advertisement / product / service</option><option value="app">App I created</option></select><label>Business / brand name</label><input name="business_name" required maxlength="120"><label>Listing title</label><input name="title" required maxlength="160"><label>Category</label><select name="category">${cats.map(x=>'<option>'+esc(x)+'</option>').join('')}</select><label>Description</label><textarea name="description" required maxlength="3000" rows="4"></textarea><label>Website / app download URL</label><input name="target_url" type="url" maxlength="500" placeholder="https://..."><label>Image URL (optional)</label><input name="image_url" type="url" maxlength="1000" placeholder="https://..."><div id="ownerBusinessContactFields" class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:12px 0"><label>Service area / town<input name="area" maxlength="120" placeholder="e.g. Johannesburg"></label><label>Public phone<input name="phone" type="tel" maxlength="40" placeholder="+27..."></label><label>WhatsApp (optional)<input name="whatsapp" type="tel" maxlength="40" placeholder="+27..."></label><label>Public contact email (optional)<input name="contact_email" type="email" maxlength="254" placeholder="you@example.com"></label></div><p><button id="ownerPromoSubmit" type="submit">Save & publish for free</button> <button id="ownerPromoCancelEdit" type="button" class="secondary" hidden onclick="cancelOwnerPromoEdit()">Cancel edit</button></p></form><div id="ownerPromoStatus" class="muted" aria-live="polite"></div><h3>Your entries</h3>${table(['Type','Business','Title','Status','Fee exemption','Action'],(d.items||[]).map(x=>[x.kind,x.business_name,x.title,x.status,x.owner_free?'Free':'Review',actions(x)]))}`;
 const form=document.getElementById('ownerPromoForm'),kindSelect=form.elements.kind,contactFields=document.getElementById('ownerBusinessContactFields');
 const syncContactFields=()=>{const business=kindSelect.value==='business';contactFields.style.display=business?'grid':'none';form.elements.area.required=business;form.elements.phone.required=business};kindSelect.addEventListener('change',syncContactFields);syncContactFields();
 form.onsubmit=async e=>{e.preventDefault();const st=document.getElementById('ownerPromoStatus'),payload=Object.fromEntries(new FormData(form)),id=payload.promotion_id;delete payload.promotion_id;if(id)payload.action='update';try{await api(id?'/api/admin/owner-promotions/'+id:'/api/admin/owner-promotions',{method:'POST',body:JSON.stringify(payload)});await load('owner-promotions');const status=document.getElementById('ownerPromoStatus');if(status)status.textContent=id?'Changes saved. Directory details are synchronized.':'Saved and published. Owner fee exemption stored.'}catch(x){st.textContent='Not saved: '+x.message}};
 return;
 }
 if(tab==='analytics'){let d=await api('/api/admin/analytics'),s=d.stats;p.innerHTML='<h2>Usage & payments</h2><div class="grid">'+Object.entries(s).map(([k,v])=>'<div class="card"><div class="muted">'+esc(k.replaceAll('_',' '))+'</div><div class="stat">'+esc(typeof v==='number'&&k==='revenue'?'R'+v.toLocaleString('en-ZA'):v)+'</div></div>').join('')+'</div><p class="muted">Local visit counts are not public website analytics or store-download totals.</p>';return}
if(tab==='compose'){let d=await api('/api/admin/clients');let items=d.items||[];p.innerHTML='<h2>Compose email</h2><p class="muted">Compose and send within Skillvaya. Delivery requires the server email connection to be configured.</p><form id="composeForm"><label>Recipient account</label><select name="client_id" required><option value="">Choose a customer or provider</option>'+items.map(x=>'<option value="'+x.id+'">'+esc(x.name)+' — '+esc(x.email)+' ('+esc(x.role)+')</option>').join('')+'</select><label>Subject</label><input name="subject" maxlength="180" required><label>Message</label><textarea name="body" rows="6" maxlength="10000" required></textarea><p><button class="primary">Send from Skillvaya</button></p><div id="composeStatus" class="muted"></div></form>';document.getElementById('composeForm').onsubmit=async e=>{e.preventDefault();let f=Object.fromEntries(new FormData(e.target));let st=document.getElementById('composeStatus');st.textContent='Sending through Skillvaya email service…';try{let r=await api('/api/admin/email-client',{method:'POST',body:JSON.stringify(f)});st.textContent='Sent to '+r.recipient+'.'}catch(err){st.textContent='Not sent: '+err.message;}};return}
if(tab==='inbox'){let d=await api('/api/admin/notifications');p.innerHTML='<h2>Skillvaya in-app inbox</h2><p class="muted">This inbox shows messages and system alerts recorded by Skillvaya. It is not a live mirror of Gmail; Gmail mailbox syncing requires Google OAuth authorization.</p>'+table(['Date','Type','Subject','Status','Recipient','Message'],(d.items||[]).map(x=>[x.created_at,x.kind,x.subject,x.status,x.recipient,x.body]));return}
if(tab==='settings'){let d=await api('/api/admin/settings');p.innerHTML='<h2>Owner email</h2><form id="email"><label>Notification email <input type="email" name="owner_email" value="'+esc(d.owner_email)+'" required></label><p><button>Save email</button><button type="button" class="secondary" onclick="testEmail()">Send test email</button></p></form><p><button type="button" class="secondary" onclick="load(&#39;compose&#39;)">Compose inside Skillvaya</button> <button type="button" class="secondary" onclick="load(&#39;inbox&#39;)">Open Skillvaya inbox</button></p><p class="muted">'+esc(d.note)+' '+(d.smtp_configured?'SMTP detected.':'SMTP not configured yet; app-triggered emails cannot be sent until Gmail SMTP credentials are configured securely on the server.')+'</p>';document.getElementById('email').onsubmit=async e=>{e.preventDefault();try{await api('/api/admin/settings',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});alert('Owner email saved');load('settings')}catch(x){alert(x.message)}};return}
let d=await api('/api/admin/'+tab);let items=d.items||[];if(tab==='clients'){p.innerHTML='<h2>Accounts</h2>'+table(['Name','Email','Role','Created','Listings','Paid'],items.map(x=>[x.name,x.email,x.role,x.created_at,x.businesses,x.paid]));return}
if(tab==='notifications'){p.innerHTML='<h2>Alerts</h2>'+table(['Date','Type','Subject','Status','Message'],items.map(x=>[x.created_at,x.kind,x.subject,x.status,x.body]));return}
if(tab==='businesses'){p.innerHTML='<h2>Listings</h2>'+table(['Name','Category','Area','Phone','Status','Plan'],items.map(x=>[x.name,x.category,x.area,x.phone,x.status,x.plan]));return}
if(tab==='payments'){let g=await api('/api/admin/paypal/status');p.innerHTML='<h2>PayPal payment requests & refunds</h2><p class="muted">Mode: <b>'+esc(g.mode)+'</b> · PayPal client credentials: '+(g.credentials_configured?'configured':'missing')+' · '+(g.mode==='live'?'Live OAuth':'Sandbox OAuth')+': '+(g.oauth_valid?'verified':'not verified')+'</p><p class="muted">'+esc(g.message)+'</p><p>Paid plans activate only after PayPal confirms a completed capture matching the order reference, ZAR currency and amount. Refunds run against PayPal capture IDs.</p>'+table(['Reference','User','Amount','Plan','Status','Refund','Action'],items.map(x=>[x.reference,x.user_id,'R'+x.amount,x.plan,x.status,x.refund_status||'none',x.status==='verified'&&(x.paypal_capture_id||x.pf_payment_id)&&!String(x.pf_payment_id||'').startsWith('BANK-TRANSFER:')?'<button onclick="refund('+x.id+','+x.amount+','+(x.refunded_amount||0)+')">Refund</button>':x.status==='pending'&&String(x.reference).startsWith('BT-SV-')?'<button onclick="verifyPayment('+x.id+')">Confirm bank funds received</button>':x.status==='pending'?'Awaiting PayPal confirmation':'—']));return}
if(tab==='complaints'){p.innerHTML='<h2>Reports & complaints</h2>'+table(['Date','Business','Reason','Status'],items.map(x=>[x.created_at,x.business_name,x.reason,x.status]));return}
}catch(e){p.innerHTML='<h2>Could not load control data</h2><p>'+esc(e.message)+'</p>'}}
function table(headers,rows){return '<div class="tablewrap"><table><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr>'+rows.map(row=>'<tr>'+row.map((x,i)=>'<td>'+(i===row.length-1&&String(x).startsWith('<button')?x:esc(x))+'</td>').join('')+'</tr>').join('')+'</table></div>'}
async function completeAccountDeletion(id){if(!confirm('FINAL CONFIRMATION: permanently delete the account and associated Skillvaya personal data for request #'+id+'? This cannot be undone. Verify the request holder first.'))return;try{const d=await api('/api/admin/account-deletion-requests/'+encodeURIComponent(id)+'/complete',{method:'POST',body:JSON.stringify({confirm:true})});alert((d.message||'Deletion completed.')+'\nCompletion acknowledgement email confirmed: '+(d.acknowledgement_email_sent?'Yes':'No'));await load('account-deletions')}catch(e){alert('Deletion not completed: '+e.message)}}
async function ownerAccountAccess(id,action){const msg=action==='suspend'?'Kick out this paid subscriber and suspend access on all active sessions?':'Restore this account to its previous customer/provider role?';if(!confirm(msg))return;try{const d=await api('/api/admin/accounts/'+id+'/access',{method:'POST',body:JSON.stringify({action})});alert(d.message||'Account access updated.');await load('owner-accounts')}catch(e){alert(e.message)}}
async function refund(id,amount,already){let remaining=amount*100-Number(already||0);let value=prompt('Refund amount in Rands (maximum R'+(remaining/100).toFixed(2)+')',''+(remaining/100).toFixed(2));if(value===null)return;let cents=Math.round(Number(value)*100);if(!Number.isFinite(cents)||cents<1||cents>remaining){alert('Enter a valid amount within the remaining paid balance.');return}let reason=prompt('Reason for refund (at least 3 characters):');if(!reason||reason.trim().length<3)return;if(!confirm('Submit a PayPal refund request for R'+(cents/100).toFixed(2)+'?'))return;try{let d=await api('/api/admin/refunds/'+id,{method:'POST',body:JSON.stringify({amount:cents,reason})});alert(d.message||'PayPal response received for the refund request.');load('payments')}catch(e){alert(e.message)}}
async function ownerPromoStatus(id,status){try{await api('/api/admin/owner-promotions/'+id,{method:'POST',body:JSON.stringify({status})});await load('owner-promotions');const st=document.getElementById('ownerPromoStatus');if(st)st.textContent=status==='paused'?'Promotion and directory listing paused.':status==='removed'?'Promotion removed from public listings.':'Promotion republished.'}catch(e){alert(e.message)}}
function editOwnerPromotion(id){const x=(window.ownerPromotionItems||[]).find(v=>Number(v.id)===Number(id)),f=document.getElementById('ownerPromoForm');if(!x||!f)return;f.elements.promotion_id.value=String(x.id);f.elements.kind.value=x.kind||'ad';f.elements.business_name.value=x.business_name||'';f.elements.title.value=x.title||'';if(x.category&&!Array.from(f.elements.category.options).some(o=>o.value===x.category)){f.elements.category.add(new Option(x.category,x.category))}f.elements.category.value=x.category||'Other professional services';f.elements.description.value=x.description||'';f.elements.target_url.value=x.target_url||'';f.elements.image_url.value=x.image_url||'';f.elements.area.value=x.area||'';f.elements.phone.value=x.phone||'';f.elements.whatsapp.value=x.whatsapp||'';f.elements.contact_email.value=x.contact_email||'';f.elements.kind.dispatchEvent(new Event('change'));document.getElementById('ownerPromoSubmit').textContent='Save changes';document.getElementById('ownerPromoCancelEdit').hidden=false;document.getElementById('ownerPromoStatus').textContent='Editing '+x.business_name+'. Save to update the promotion and linked directory listing.';f.scrollIntoView({behavior:'smooth',block:'start'})}
function cancelOwnerPromoEdit(){const f=document.getElementById('ownerPromoForm');if(!f)return;f.reset();f.elements.promotion_id.value='';f.elements.kind.dispatchEvent(new Event('change'));document.getElementById('ownerPromoSubmit').textContent='Save & publish for free';document.getElementById('ownerPromoCancelEdit').hidden=true;document.getElementById('ownerPromoStatus').textContent=''}
async function testEmail(){try{await api('/api/admin/test-email',{method:'POST',body:'{}'});alert('Test email sent')}catch(e){alert(e.message)}}
if(location.hash==='#payments')load('payments');else load('summary');
</script></body></html>"""
HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#10233f"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="Skillvaya"><link rel="manifest" href="/manifest.json"><link rel="apple-touch-icon" href="/icon-192.png"><link rel="icon" href="/sv-logo.jpeg" type="image/jpeg"><title>Skillvaya</title><style>
:root{--navy:#10233f;--blue:#2365d8;--bg:#f4f7fb;--ink:#19283b;--muted:#66758b;--line:#e1e8f1;--red:#c83232}*{box-sizing:border-box}.sv-splash{animation:sv-splash-failsafe .25s ease 12s forwards;position:fixed;inset:0;z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;background:linear-gradient(145deg,#071426,#102b49);color:#f4f8ff;transition:opacity .28s ease,visibility .28s ease}.sv-splash.done{opacity:0;visibility:hidden;pointer-events:none}.sv-splash-brand{font-size:clamp(34px,7vw,52px);font-weight:850;letter-spacing:-1.5px}.sv-splash-brand span{color:#42d3d0}.sv-splash-caption{font-size:16px;color:#d3e2f4;letter-spacing:.3px}.sv-loading-dots{display:flex;gap:9px;align-items:center}.sv-loading-dots i{width:9px;height:9px;border-radius:50%;background:#42d3d0;opacity:.22;animation:sv-dot-pulse 1.05s infinite ease-in-out}.sv-loading-dots i:nth-child(2){animation-delay:.18s}.sv-loading-dots i:nth-child(3){animation-delay:.36s}@keyframes sv-dot-pulse{0%,65%,100%{opacity:.2;transform:scale(.82);filter:brightness(.7)}30%{opacity:1;transform:scale(1.12);filter:brightness(1.5)}}@keyframes sv-splash-failsafe{to{opacity:0;visibility:hidden;pointer-events:none}}.password-wrap{position:relative;display:flex;align-items:center;width:100%}.password-wrap input{padding-right:48px}.password-toggle{position:absolute;right:5px;top:50%;transform:translateY(-50%);width:38px;height:36px;padding:7px;background:transparent;color:#52647b;border-radius:8px;display:grid;place-items:center}.password-toggle:hover{background:#edf3fa}.password-toggle svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.photo-picker{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.profile-heading{display:flex;align-items:center;gap:16px;margin:0 0 12px;padding:0 0 8px}.profile-heading h2{margin:0;font-size:clamp(25px,5vw,34px);letter-spacing:-.6px}.profile-heading img{width:100px;height:100px;flex:0 0 100px;object-fit:cover;border-radius:50%;border:2px solid #d6e2ef;background:#e9eff7}.profile-photo-secondary{display:none!important}.catlist{display:none!important}.photo-pick-wrap{position:relative;display:inline-flex;overflow:hidden;border-radius:10px;min-height:44px}.photo-pick-button{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:11px 15px;background:#edf4ff;color:#173e76;border:1px solid #c8d9f2;border-radius:10px;font-weight:700;cursor:pointer}.photo-pick-wrap input[type=file]{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer;z-index:2}.photo-pick-button:focus-visible{outline:3px solid #8bbcff;outline-offset:2px}.photo-pick-button:hover{background:#dfeeff}.photo-file-name{font-size:13px;color:var(--muted);overflow-wrap:anywhere}.photo-input-hidden{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}.category-screen{padding:22px 0 55px;min-height:45vh}.category-screen-head{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:18px}.category-back{background:#edf3fa;color:#17365d;border:1px solid #d6e1ee}.category-results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}@media(max-width:800px){.category-results{grid-template-columns:1fr}}.account-field-label,.account-role-choice{font-weight:800!important;color:#172b45}.account-field-label{display:block;margin-top:10px}.account-role-choice{border:2px solid #9eb5d1;background:#fff}body{margin:0;font:15px/1.5 "Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--ink)}button,input,select,textarea{font:inherit}button{cursor:pointer;border:0;border-radius:10px;padding:10px 14px;font-weight:650}.primary{background:var(--blue);color:#fff}.ghost{background:#eef3fa;color:var(--navy)}.danger{background:#fff0f0;color:var(--red)}input,select,textarea{border:1px solid var(--line);border-radius:9px;padding:11px;width:100%;background:white}.wrap{max-width:1180px;margin:auto;padding:0 18px 110px}.top{background:var(--navy);color:white}.nav{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:15px 0;flex-wrap:wrap}.brandlock{display:flex;align-items:center;gap:11px}.sv-logo{width:46px;height:46px;object-fit:contain;border-radius:10px;background:#08142b;box-shadow:0 2px 10px #0003;flex:0 0 auto}.brand{font-size:26px;font-weight:850}.brand span{color:#75b7ff}.switch{display:flex;gap:5px;background:#203652;padding:5px;border-radius:12px;flex-wrap:wrap}.switch button{color:#dbe7f7;background:transparent}.switch button.active{background:white;color:var(--navy)}.hero{background:linear-gradient(110deg,#10233f,#1c4b83);color:white;padding:34px 0}.hero h1{font-size:clamp(29px,4vw,44px);line-height:1.1;margin:12px 0}.hero p{color:#d7e7fa;max-width:670px}.search{display:flex;gap:8px;max-width:800px;flex-wrap:wrap}.search input{flex:1;min-width:180px}.hero-actions-wrap{background:var(--navy)}.hero-actions{display:flex;gap:8px;flex-wrap:wrap;margin:0;padding:14px 0 16px;border-top:1px solid #ffffff35}.hero-actions button{background:#ffffff16;color:white;border:1px solid #ffffff45}.hero-actions button.active,.hero-actions button:hover{background:white;color:var(--navy)}.layout{display:grid;grid-template-columns:235px 1fr;gap:18px;padding:24px 0 55px}.panel,.card{background:white;border:1px solid var(--line);border-radius:15px;padding:17px;box-shadow:0 4px 18px #17365d08}.results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.biz.spotlight{border:1px solid #78a9fa;background:linear-gradient(130deg,#fff,#f0f6ff)}.biz.plus{border:1px solid #bed8ff}.tag{display:inline-block;font-size:11px;font-weight:800;padding:4px 8px;border-radius:99px;background:#edf1f7;color:#4b5c73}.tag.plus{background:#e4f0ff;color:#1554b6}.tag.spotlight{background:#173b6c;color:white}.biz h3{margin:10px 0 3px}.muted{color:var(--muted)}.tiny{font-size:12px}.biz p{color:#5e6d82}.bizfoot{display:flex;gap:7px;flex-wrap:wrap}.catlist{display:grid;gap:4px;max-height:62vh;overflow-y:auto;overscroll-behavior:contain;padding-right:4px;padding-bottom:88px}.cat{background:transparent;color:#40516a;text-align:left;padding:8px}.cat.selected,.cat:hover{background:#eaf2ff;color:#164caa}.sectionhead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:22px 0 12px}.sectionhead h2{margin:0}.hidden{display:none!important}.formgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.full{grid-column:1/-1}.notice{background:#fff7e6;color:#805311;border-radius:9px;padding:12px;margin:12px 0}.good{background:#eaf7f0;color:#13714d}.bad{background:#fff0f0;color:#a32222}.pricegrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.price{border:1px solid var(--line);border-radius:12px;padding:13px}.price.featured{border:2px solid var(--blue);background:#f4f8ff}.amount{font-size:24px;font-weight:850}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.stat strong{display:block;font-size:26px}.tablewrap{overflow:auto}.table{border-collapse:collapse;width:100%;min-width:660px}.table td,.table th{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}.table th{font-size:12px;color:var(--muted)}.switchline{display:flex;gap:8px;flex-wrap:wrap;margin:15px 0}.footer{border-top:1px solid var(--line);padding:20px 0;color:var(--muted);font-size:12px}.pill{background:#eaf7f0;color:#13714d;padding:4px 8px;border-radius:20px;font-size:12px}.bottom-tabbar{position:fixed;z-index:20000;pointer-events:auto;isolation:isolate;left:0;right:0;bottom:0;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));visibility:visible!important;opacity:1!important;gap:8px;padding:9px max(12px,env(safe-area-inset-left)) calc(9px + env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-right));background:#071426f5;border-top:1px solid #355477;box-shadow:0 -8px 24px #07142622}.bottom-tabbar button{position:relative;z-index:20001;pointer-events:auto;touch-action:manipulation;min-width:0;min-height:62px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border:1px solid #355477;border-radius:13px;background:#172b45;color:#eaf1fb;padding:7px 4px;font-size:clamp(10px,2.8vw,13px);line-height:1.15}.bottom-tabbar button.active,.bottom-tabbar button:focus-visible{background:#087f8c;border-color:#42d3d0;color:white}.bottom-tab-icon{font-size:18px;line-height:1}.footer{padding-bottom:100px}.provider-open{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:14px}.provider-detail-contact{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.provider-detail-contact>*{flex:0 0 auto}
.studio-profile{margin:0 auto;max-width:1040px;background:#07111e;color:#eaf2ff;border:1px solid #17314b;border-radius:22px;overflow:hidden;box-shadow:0 22px 60px #0613272b;font-family:Inter,"Segoe UI",Arial,sans-serif}
.studio-banner{min-height:230px;display:grid;grid-template-columns:140px minmax(0,1fr) 165px;gap:24px;align-items:center;padding:28px 30px;background:radial-gradient(ellipse at 82% 45%,#0c5dba55,transparent 45%),linear-gradient(120deg,#071426,#031b39 70%,#052a61);border-bottom:1px solid #193754}
.studio-logo{width:136px;height:136px;border:5px solid #087cff;border-radius:50%;display:grid;place-items:center;font-size:78px;line-height:1;font-weight:950;font-style:italic;color:#eaf5ff;text-shadow:5px 5px 0 #087cff}
.studio-brand h1{font-size:clamp(32px,5vw,52px);line-height:1;margin:0;letter-spacing:-2px;color:#f5f8ff}.studio-brand h2{font-size:clamp(20px,3vw,34px);line-height:1.1;color:#169dff;margin:8px 0 12px}.studio-brand p{margin:0;color:#c5d5ef;font-size:clamp(12px,1.7vw,18px);white-space:nowrap}.studio-brand p b{padding:0 5px;color:#238eff}.studio-slogan{font-size:clamp(16px,2.1vw,24px);line-height:1.35;color:#f2f6ff}
.studio-facts{display:grid;grid-template-columns:1fr 1fr;gap:0;padding:22px 30px 18px;border-bottom:1px solid #1c324b}.studio-facts>div{display:flex;align-items:center;gap:18px;padding:0 14px}.studio-facts>div:first-child{border-right:1px solid #294057}.studio-facts>div>span{font-size:38px;color:#087cff}.studio-facts small,.studio-contactfacts small{display:block;color:#91b1dc;font-size:14px}.studio-facts strong{display:block;font-size:17px;font-weight:650;color:#e8f0ff}
.studio-contactfacts{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px 30px}.studio-contactfacts a{min-width:0;display:flex;align-items:center;gap:15px;padding:12px;border:1px solid #213b59;border-radius:18px;background:#0b1929;color:#f1f6ff;text-decoration:none}.studio-contactfacts a>span{flex:0 0 64px;width:64px;height:64px;display:grid;place-items:center;border-radius:14px;background:#092d5b;color:#128eff;font-size:32px}.studio-contactfacts strong{display:block;font-size:clamp(15px,2vw,23px);overflow-wrap:anywhere}
.studio-sectiontitle{font-size:27px;line-height:1.2;margin:20px 30px 14px;color:#f3f7ff}.studio-services{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;padding:0 30px}.studio-service{min-height:86px;display:flex;align-items:center;gap:12px;padding:12px;border:1px solid #203a57;border-radius:18px;background:linear-gradient(135deg,#0d1e31,#0a1726);font-size:15px;line-height:1.35}.studio-service-icon{flex:0 0 56px;width:56px;height:56px;border-radius:15px;display:grid;place-items:center;background:#091f43;color:#168cff;font-size:27px;font-weight:900}.studio-service .icon-0{color:#ad45ff}.studio-service .icon-1{color:#126bff}.studio-service .icon-2{color:#13d7bd}.studio-service .icon-3{color:#9a46ff}.studio-service .icon-4{color:#ffb42f}.studio-service .icon-5{color:#12db78}.studio-service .icon-6{color:#f02aa8}.studio-service .icon-7{color:#00d5ec}.studio-service .icon-8{color:#ff466a}.studio-service .icon-9{color:#8bc4ff}
.studio-about{margin:0 30px 18px;color:#cbd9f0;font-size:17px;line-height:1.65}.studio-motto{display:flex;align-items:center;gap:20px;margin:18px 30px 22px;padding:16px 20px;border:1px solid #21446c;border-radius:18px;background:linear-gradient(100deg,#0b2038,#0b192b);font-size:17px}.studio-motto>span{flex:0 0 64px;width:64px;height:64px;border-radius:16px;background:#092b54;color:#168eff;display:grid;place-items:center;font-size:45px}.studio-motto strong{display:block;color:#159dff;font-size:20px}.studio-actions,.studio-extra-actions{display:flex;gap:10px;flex-wrap:wrap;padding:0 30px 20px}.studio-actions .primary,.studio-action{border:1px solid #215184;background:#0c2744;color:#e7f2ff;border-radius:12px;padding:12px 16px;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;font-weight:750}.studio-actions .primary{background:#087cff;border-color:#087cff;color:white}.studio-extra-actions{border-top:1px solid #19314b;padding-top:15px}
@media(max-width:720px){.studio-banner{grid-template-columns:82px minmax(0,1fr);gap:16px;padding:22px 18px;min-height:0}.studio-logo{width:78px;height:78px;border-width:3px;font-size:46px}.studio-slogan{grid-column:2;font-size:15px;margin-top:-7px}.studio-brand h1{font-size:31px;letter-spacing:-1px}.studio-brand h2{font-size:20px}.studio-brand p{white-space:normal;font-size:12px}.studio-facts{padding:16px 10px;gap:4px}.studio-facts>div{padding:0 7px;gap:8px}.studio-facts>div>span{font-size:27px}.studio-facts strong{font-size:13px}.studio-facts small,.studio-contactfacts small{font-size:12px}.studio-contactfacts{padding:12px;gap:8px}.studio-contactfacts a{padding:9px;gap:8px}.studio-contactfacts a>span{flex-basis:42px;width:42px;height:42px;font-size:23px}.studio-contactfacts strong{font-size:13px}.studio-sectiontitle{font-size:23px;margin:18px 16px 12px}.studio-services{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding:0 12px}.studio-service{min-height:72px;padding:8px;gap:8px;font-size:12px;border-radius:13px}.studio-service-icon{flex-basis:38px;width:38px;height:38px;border-radius:11px;font-size:20px}.studio-about{margin:0 16px 15px;font-size:15px}.studio-motto{margin:14px 12px 18px;padding:12px;gap:12px;font-size:14px}.studio-motto>span{flex-basis:48px;width:48px;height:48px;font-size:32px}.studio-motto strong{font-size:16px}.studio-actions,.studio-extra-actions{padding-left:12px;padding-right:12px}.studio-actions>*{flex:1 1 130px}.studio-profile{border-radius:16px}}
@media(max-width:380px){.studio-services{grid-template-columns:1fr}.studio-contactfacts{grid-template-columns:1fr}.studio-facts{grid-template-columns:1fr;gap:12px}.studio-facts>div:first-child{border-right:0}.studio-slogan{font-size:13px}}
.provider-detail-hero{border:1px solid #d5e3f5;background:linear-gradient(140deg,#fff,#f1f7ff);border-radius:18px;padding:clamp(18px,4vw,30px)}.provider-detail-hero h1{margin:12px 0 4px;font-size:clamp(26px,4vw,36px)}.biz[role=button]:focus-visible{outline:3px solid #70a6ff;outline-offset:3px}@media(max-width:480px){.bottom-tabbar{gap:6px;padding-left:8px;padding-right:8px}.bottom-tabbar button{min-height:58px;border-radius:11px}.provider-open{align-items:stretch;flex-direction:column}}
@media(max-width:800px){.layout{grid-template-columns:1fr}.results{grid-template-columns:1fr}.pricegrid{grid-template-columns:repeat(2,1fr)}.stats{grid-template-columns:repeat(2,1fr)}}@media(max-width:480px){.wrap{padding:0 12px}.formgrid{grid-template-columns:1fr}.full{grid-column:auto}.pricegrid{grid-template-columns:1fr}}


/* Skillvaya 1.1 visual finishing layer: consistent premium design without changing workflows */
:root{--sv-ink:#14263e;--sv-muted:#61748c;--sv-line:#dce6f1;--sv-teal:#20c8c1;--sv-teal-dark:#087f83;--sv-blue:#2459d3;--sv-radius:18px;--sv-shadow:0 14px 38px rgba(18,43,76,.08)}
html{scroll-behavior:smooth;scroll-padding-top:24px}body{color:var(--sv-ink);background:radial-gradient(ellipse at 5% 0%,rgba(32,200,193,.055),transparent 34%),var(--bg);-webkit-font-smoothing:antialiased}
button,a,input,select,textarea{transition:background-color .16s ease,border-color .16s ease,box-shadow .16s ease,transform .16s ease}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid rgba(32,200,193,.65);outline-offset:2px}
button:hover{filter:brightness(1.025)}button:active{transform:translateY(1px)}
.top{box-shadow:0 4px 22px rgba(5,20,42,.12)}.nav{min-height:76px}.brand{letter-spacing:-.7px}.sv-logo{border:1px solid rgba(255,255,255,.12)}
.hero{position:relative;overflow:hidden;background:radial-gradient(ellipse at 88% 8%,rgba(32,200,193,.2),transparent 32%),linear-gradient(125deg,#071426 0%,#102b49 58%,#155366 120%);padding:clamp(34px,6vw,70px) 0}
.hero:after{content:"";position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(90deg,transparent,#000)}
.hero>.wrap{position:relative;z-index:1}.hero h1{letter-spacing:-1.8px;max-width:760px}.hero p{font-size:clamp(15px,2vw,18px);line-height:1.75}
.search{margin-top:22px;padding:9px;background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.2);border-radius:18px;box-shadow:0 18px 40px rgba(0,0,0,.12);backdrop-filter:blur(12px)}.search input{min-height:48px;border:1px solid #dbe5f0}.search button{min-width:116px;min-height:48px}
.hero-actions-wrap{position:sticky;top:0;z-index:40;box-shadow:0 8px 24px rgba(7,20,38,.12)}.hero-actions{padding:12px 0}.hero-actions button{border-radius:12px;padding:11px 16px}
.layout{gap:22px;padding-top:24px;padding-bottom:30px}.panel,.card,.feature,.price,.step{border:1px solid var(--sv-line);border-radius:var(--sv-radius);box-shadow:var(--sv-shadow);background:rgba(255,255,255,.96)}.panel{padding:19px}.panel h3{letter-spacing:-.3px}.sectionhead{margin:18px 0 15px}.sectionhead h2{letter-spacing:-.7px}.results,.category-results{gap:16px}.biz{border-radius:18px;padding:20px;box-shadow:0 10px 30px rgba(20,48,83,.06);transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}.biz:hover{transform:translateY(-2px);box-shadow:0 18px 40px rgba(20,48,83,.12);border-color:#b9d0e8}.biz h3{font-size:19px;letter-spacing:-.35px}.tag{padding:5px 10px;letter-spacing:.15px}.tag.spotlight{background:linear-gradient(135deg,#10233f,#087f83)}.primary{background:linear-gradient(135deg,#2459d3,#177caa);box-shadow:0 5px 13px rgba(36,89,211,.17)}.primary:hover{box-shadow:0 8px 18px rgba(36,89,211,.24);transform:translateY(-1px)}.ghost,.secondary{border:1px solid #d6e2ef}.ghost:hover,.secondary:hover{background:#e5effa}.catlist{max-height:68vh;padding:4px}.cat{border-radius:10px;padding:9px 11px}.cat.selected,.cat:hover{background:linear-gradient(90deg,#e3f8f6,#edf4ff);color:#075e69}.cat.selected{font-weight:800;box-shadow:inset 3px 0 #16b9b2}
input,select,textarea{border-color:#d3dfec;min-height:44px}input:focus,select:focus,textarea:focus{border-color:#48bdbb;box-shadow:0 0 0 3px rgba(32,200,193,.12);outline:0}textarea{resize:vertical}
.formgrid{gap:16px}.formgrid label,label{font-weight:650}.pricegrid{gap:14px}.price{padding:18px}.price.featured{border-color:#2459d3;background:linear-gradient(145deg,#fff,#edf5ff);box-shadow:0 12px 32px rgba(36,89,211,.12)}.amount{letter-spacing:-.8px}.stats .card{padding:17px}.stats .stat strong{color:#12365b}.tablewrap{border:1px solid var(--sv-line);border-radius:14px;background:white}.table{border-collapse:separate;border-spacing:0}.table th{background:#f3f7fb;position:sticky;top:0}.table td,.table th{padding:12px}.notice{border:1px solid #f0d8a5;border-radius:13px}.good{border-color:#b8e6d0}.bad{border-color:#f1c6c6}
#settings>.card,#messagesCard,#jobsCard,#favoritesCard{box-shadow:0 16px 42px rgba(18,43,76,.075)}#settings h2,#settings h3,#jobsCard h2,#favoritesCard h2,#messagesCard h2{letter-spacing:-.55px}
.bottom-tabbar{backdrop-filter:blur(18px);background:rgba(7,20,38,.96);border-top:1px solid rgba(255,255,255,.12);box-shadow:0 -12px 36px rgba(7,20,38,.13)}.bottom-tabbar button{border-color:rgba(255,255,255,.1);font-weight:700}.bottom-tabbar button.active{background:linear-gradient(135deg,#087f83,#0c9c9d);box-shadow:0 4px 14px rgba(32,200,193,.18)}
.footer{border-top-color:#dbe5ef}.provider-detail-hero{box-shadow:0 20px 50px rgba(18,43,76,.09)}
@media(min-width:1000px){.layout{grid-template-columns:270px minmax(0,1fr)}.catlist{max-height:calc(100vh - 170px)}}
@media(max-width:800px){.hero{padding:36px 0}.hero h1{letter-spacing:-1.1px}.layout{padding-top:14px}.panel{padding:15px}.hero-actions-wrap{position:sticky}.hero-actions{gap:7px}.hero-actions button{flex:1 1 auto}}
@media(max-width:480px){.hero{padding:30px 0}.search{padding:8px;border-radius:15px}.search input{min-width:100%;flex-basis:100%}.search button{width:100%}.hero-actions button{font-size:12px;padding:10px 8px}.biz{padding:16px}.sectionhead{align-items:flex-start}.bottom-tabbar button{box-shadow:0 3px 12px rgba(0,0,0,.1)}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
#accountSubspace{position:fixed;inset:0;z-index:10000;background:#f4f7fb;overflow:hidden;overscroll-behavior:contain;padding:clamp(14px,3vw,30px);padding-bottom:calc(28px + env(safe-area-inset-bottom))}#jobsCard.account-subspace-card,#favoritesCard.account-subspace-card,#messagesCard.account-subspace-card{display:block!important;position:fixed;z-index:10001;top:clamp(145px,19vh,180px);bottom:calc(14px + env(safe-area-inset-bottom));left:50%;transform:translateX(-50%);width:min(960px,calc(100vw - 28px));max-width:960px;overflow-y:auto;overscroll-behavior:contain;margin:0!important;box-shadow:0 20px 65px rgba(7,20,38,.2);border-radius:20px}#accountSubspace .account-subspace-top{max-width:960px;margin:0 auto 18px;display:flex;align-items:flex-start;gap:18px;flex-wrap:wrap;padding:8px 0 16px;border-bottom:1px solid #dce6f1}#accountSubspace .account-subspace-top>div{flex:1;min-width:190px}#accountSubspace h1{margin:8px 0 2px;font-size:clamp(25px,4vw,36px);letter-spacing:-.8px}#accountSubspace .account-subspace-content{max-width:960px;margin:0 auto}#accountSubspace .account-subspace-content>.card{margin:0!important;padding:clamp(16px,3vw,28px);border-radius:20px}#accountSubspace .account-subspace-content #jobsCard,#accountSubspace .account-subspace-content #favoritesCard,#accountSubspace .account-subspace-content #messagesCard{display:block!important}#accountSubspace .account-subspace-content #jobsCard.hidden,#accountSubspace .account-subspace-content #favoritesCard.hidden,#accountSubspace .account-subspace-content #messagesCard.hidden{display:none!important}body.account-subspace-open{overflow:hidden}#accountSubspaceBack{min-height:44px;flex:0 0 auto}@media(max-width:480px){#accountSubspace{padding:12px;padding-bottom:calc(24px + env(safe-area-inset-bottom))}#accountSubspace .account-subspace-top{gap:10px}#accountSubspace .account-subspace-content>.card{padding:15px}}
.provider-directory-dropdown{margin:0 0 18px;border:1px solid var(--sv-line);border-radius:17px;background:#fff;box-shadow:var(--sv-shadow);overflow:hidden}.provider-directory-dropdown>summary{list-style:none;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:17px 18px;cursor:pointer;background:linear-gradient(115deg,#f5fbff,#edf9f8);border-bottom:1px solid transparent}.provider-directory-dropdown>summary::-webkit-details-marker{display:none}.provider-directory-dropdown>summary:after{content:"⌄";font-size:22px;font-weight:800;color:#087f83;order:3;transition:transform .16s ease}.provider-directory-dropdown[open]>summary{border-bottom-color:var(--sv-line)}.provider-directory-dropdown[open]>summary:after{transform:rotate(180deg)}.provider-directory-dropdown>summary>span:first-child{display:flex;flex-direction:column;gap:2px}.provider-directory-dropdown>summary strong{font-size:16px;color:#14263e}.provider-directory-dropdown #results{padding:15px}.provider-directory-dropdown #results:empty{padding:0}.provider-directory-dropdown .biz{box-shadow:0 7px 22px rgba(20,48,83,.055)}@media(max-width:480px){.provider-directory-dropdown>summary{padding:14px}.provider-directory-dropdown #results{padding:10px;gap:10px}}


/* Skillvaya cohesive app redesign — October 2026 */
:root{--sv-navy:#0b1730;--sv-blue:#1768f5;--sv-cyan:#17c8d2;--sv-purple:#8658f5;--sv-bg:#f4f7fc;--sv-card:#fff;--sv-ink:#18243a;--sv-muted:#697891;--sv-line:#e2e9f4;--sv-radius:20px;--sv-shadow:0 12px 34px rgba(19,42,78,.09);color-scheme:light}
html{scroll-behavior:smooth;background:var(--sv-bg)}body{background:var(--sv-bg);color:var(--sv-ink);font-family:Inter,"Segoe UI",system-ui,-apple-system,sans-serif;line-height:1.55;-webkit-font-smoothing:antialiased}
button,input,select,textarea{font:inherit}button{cursor:pointer;transition:transform .16s ease,box-shadow .16s ease,background .16s ease}button:active{transform:scale(.985)}button:disabled{opacity:.55;cursor:not-allowed}
a{color:var(--sv-blue)}.wrap{max-width:1240px}.head{background:linear-gradient(115deg,#08152d,#112c53 68%,#174a78);box-shadow:0 8px 30px rgba(7,21,45,.16);padding:clamp(14px,2.8vw,24px)}.brand{gap:13px}.brand img{border-radius:15px;object-fit:cover}.hero{padding:clamp(30px,6vw,70px) 0;background:radial-gradient(ellipse at 80% 0%,rgba(23,200,210,.15),transparent 45%),linear-gradient(145deg,#f7faff,#edf3ff)}.hero h1{font-size:clamp(2rem,5vw,3.65rem);line-height:1.08;letter-spacing:-.045em;max-width:780px}.hero p{max-width:680px;color:#53637d;font-size:clamp(1rem,1.5vw,1.15rem)}
.card,.panel,.frame,.price,.feature,.step,.provider-detail-hero,.studio-profile{border-radius:var(--sv-radius);box-shadow:var(--sv-shadow)}.card{border:1px solid var(--sv-line);background:var(--sv-card);padding:clamp(16px,3vw,25px)}.panel{background:#fff;color:var(--sv-ink);border:1px solid var(--sv-line);box-shadow:var(--sv-shadow)}.panel .muted{color:var(--sv-muted)}.sectionhead{gap:14px;align-items:center}.sectionhead h2,h2{letter-spacing:-.025em}.muted{color:var(--sv-muted)}
.primary,.action.primary,.search button{background:linear-gradient(120deg,var(--sv-blue),#4387ff);border:1px solid #1768f5;color:white;border-radius:13px;font-weight:700;box-shadow:0 7px 17px rgba(23,104,245,.18)}.secondary,.ghost,.tabs button,.hero-actions button,.studio-action{border-radius:13px}.secondary,.ghost{background:#fff;border:1px solid #d7e2f2;color:#1b4f9d}.primary:hover,.action.primary:hover,.search button:hover{box-shadow:0 10px 24px rgba(23,104,245,.26);transform:translateY(-1px)}
input:not([type=checkbox]):not([type=radio]):not([type=file]),select,textarea{border:1px solid #d8e2f0;border-radius:12px;background:#fff;color:var(--sv-ink);min-height:44px;padding:11px 13px;max-width:100%;transition:border-color .15s,box-shadow .15s}input:focus,select:focus,textarea:focus{border-color:#4387ff!important;box-shadow:0 0 0 3px rgba(23,104,245,.12);outline:none}label{font-weight:650;color:#34445e}form button[type=submit]{min-height:44px}
.results,.category-results{gap:14px}.results>*,.category-results>*{border-radius:17px!important;border:1px solid var(--sv-line)!important;box-shadow:0 6px 20px rgba(20,44,80,.055);transition:transform .18s,box-shadow .18s}.results>*:hover,.category-results>*:hover{transform:translateY(-2px);box-shadow:var(--sv-shadow)}.tag{border-radius:999px;padding:5px 10px;font-weight:700}
.provider-directory-dropdown{border-radius:16px;border-color:var(--sv-line);box-shadow:0 5px 18px rgba(19,42,78,.04)}.provider-directory-dropdown>summary{padding:14px 16px}.notice{border-radius:14px;padding:13px 15px}.layout{gap:22px}
#settings>.card,#messagesCard,#jobsCard,#favoritesCard{border-radius:22px;border-color:var(--sv-line)}#settings h2,#jobsCard h2,#favoritesCard h2,#messagesCard h2{letter-spacing:-.04em}
.sv-notification-bell{-webkit-appearance:none;appearance:none;-webkit-tap-highlight-color:transparent;touch-action:manipulation;outline:none;position:relative;top:auto;right:auto;z-index:10001;flex:0 0 46px;width:46px;height:46px;margin-left:auto;border:1px solid #d8e2f0;border-radius:50%;background:#fff;color:#152b4e;box-shadow:0 5px 18px rgba(19,42,78,.16);display:none;align-items:center;justify-content:center;cursor:pointer}.sv-notification-bell:focus,.sv-notification-bell:focus-visible,.sv-notification-bell:active{background:#fff!important;color:#152b4e!important;outline:none!important;box-shadow:0 5px 18px rgba(19,42,78,.16)!important;filter:none!important}.sv-notification-bell.is-visible{display:flex}.sv-notification-bell svg{width:23px;height:23px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}.sv-notification-badge{position:absolute;top:-3px;right:-3px;min-width:19px;height:19px;padding:0 4px;border-radius:999px;background:#1768f5;color:#fff;font:700 11px/19px system-ui;text-align:center;border:2px solid #fff}
/* Stable mobile chat composer: give the message field the remaining width and keep voice as an icon button. */
body.messages-conversation-open .message-compose{display:flex!important;align-items:flex-end!important;gap:8px!important;width:100%!important;box-sizing:border-box!important;}
body.messages-conversation-open .message-compose textarea{display:block!important;flex:1 1 0!important;width:0!important;min-width:0!important;box-sizing:border-box!important;}
body.messages-conversation-open .message-compose .sv-voice-controls{display:flex!important;flex:0 0 48px!important;width:48px!important;min-width:48px!important;margin:0!important;gap:0!important;align-self:flex-end!important;}
body.messages-conversation-open .message-compose .sv-voice-button{display:inline-flex!important;align-items:center!important;justify-content:center!important;flex:0 0 48px!important;width:48px!important;min-width:48px!important;max-width:48px!important;padding:0!important;font-size:23px!important;white-space:nowrap!important;overflow:hidden!important;}
body.messages-conversation-open .message-compose .sv-voice-status{display:none!important}
@media(max-width:390px){body.messages-conversation-open .message-compose{gap:6px!important;padding-left:8px!important;padding-right:8px!important}body.messages-conversation-open .message-compose .sv-voice-controls,body.messages-conversation-open .message-compose .sv-voice-button{flex-basis:44px!important;width:44px!important;min-width:44px!important;max-width:44px!important}}
.sv-voice-controls{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:7px 0}.sv-voice-button{min-height:38px;touch-action:manipulation}.sv-voice-button.is-listening{background:#fff0f0!important;border-color:#d53f4f!important;color:#a51f2b!important}.sv-voice-status{font-size:12px;color:#52627a}.sv-voice-status:empty{display:none}
#messagesList{display:grid;gap:10px}.message-thread-item,.message-inbox-item,.conversation-row{border:1px solid var(--sv-line);border-radius:16px;background:#fff;padding:14px;box-shadow:0 4px 16px rgba(19,42,78,.04)}
/* SV58-CHAT-VIEWPORT-01: keep the open conversation between the app header and fixed bottom tabs. */
body.messages-conversation-open #messagesList{position:fixed!important;top:76px!important;left:0!important;right:0!important;bottom:calc(82px + env(safe-area-inset-bottom))!important;z-index:998!important;display:block!important;overflow:hidden!important;box-sizing:border-box!important;margin:0!important;padding:8px!important;background:var(--bg,#f4f7fb)!important}
body.messages-conversation-open .message-conversation-screen{height:100%!important;min-height:0!important;max-height:100%!important;display:flex!important;flex-direction:column!important;box-sizing:border-box!important;padding:8px!important;overflow:hidden!important}
body.messages-conversation-open .message-bubbles{flex:1 1 auto!important;min-height:0!important;height:auto!important;max-height:none!important;overflow-y:auto!important;overscroll-behavior:contain!important}
body.messages-conversation-open .message-compose{flex:0 0 auto!important;position:relative!important;margin-top:0!important;padding-bottom:calc(8px + env(safe-area-inset-bottom))!important;background:var(--bg,#f4f7fb)!important}
.message-conversation-screen,.message-conversation-panel{border-radius:20px;overflow:hidden}.message-bubble{max-width:min(82%,560px);border-radius:18px;padding:11px 14px;overflow-wrap:anywhere}.message-bubble.outgoing{margin-left:auto;background:#1768f5;color:#fff;border-bottom-right-radius:5px}.message-bubble.incoming{margin-right:auto;background:#edf2f9;color:#18243a;border-bottom-left-radius:5px}
.bottom-tabbar{position:fixed;z-index:999;left:0;right:0;bottom:0;display:flex;justify-content:space-around;gap:4px;padding:8px max(8px,env(safe-area-inset-left)) calc(8px + env(safe-area-inset-bottom));background:rgba(255,255,255,.94);backdrop-filter:blur(18px);border-top:1px solid rgba(216,226,240,.9);box-shadow:0 -8px 28px rgba(15,35,67,.08)}.bottom-tabbar button{flex:1;min-width:0;display:flex;align-items:center;justify-content:center;gap:5px;border:0;border-radius:12px;background:transparent;color:#687891;padding:9px 5px;font-size:12px;font-weight:700}.bottom-tabbar button.active{background:#eaf1ff;color:#1768f5}
#accountSubspace{display:none!important;position:fixed!important;inset:0!important;z-index:2147483000!important;width:100vw!important;height:100dvh!important;box-sizing:border-box!important;background:var(--sv-bg,#f4f7fb)!important;overflow-y:auto!important;overflow-x:hidden!important;overscroll-behavior:contain!important;padding:calc(14px + env(safe-area-inset-top)) 14px calc(34px + env(safe-area-inset-bottom))!important}#accountSubspace:not(.hidden){display:block!important;visibility:visible!important;pointer-events:auto!important}#accountSubspace .account-subspace-top{position:relative!important;z-index:1!important;background:#071a33!important;color:#fff!important;border:0!important;border-radius:20px;padding:18px 18px 16px!important;box-shadow:0 10px 28px rgba(7,26,51,.18)}#accountSubspace .account-subspace-top h1{color:#fff!important}#accountSubspace .account-subspace-top p{color:#d9e4f3!important}#accountSubspace .account-subspace-top .tag{background:#17385f!important;color:#fff!important}#accountSubspaceBack{background:#fff!important;color:#071a33!important;border:1px solid #d6e1ef!important;border-radius:12px!important;font-weight:750!important}#accountSubspace:after{content:'';position:fixed;z-index:10002;left:0;right:0;bottom:0;height:calc(12px + env(safe-area-inset-bottom));background:#071a33;pointer-events:none}#accountSubspace .card{position:relative!important;top:auto!important;right:auto!important;bottom:auto!important;left:auto!important;transform:none!important;width:100%!important;max-width:960px!important;max-height:none!important;box-sizing:border-box!important;margin:0 auto 18px!important;border-radius:22px!important;z-index:1!important}#accountSubspace .account-subspace-content{position:relative!important;z-index:1!important;min-height:1px!important}#accountSubspace .account-subspace-content #jobsCard.account-subspace-card,#accountSubspace .account-subspace-content #favoritesCard.account-subspace-card,#accountSubspace .account-subspace-content #messagesCard.account-subspace-card{position:relative!important;top:auto!important;bottom:auto!important;left:auto!important;transform:none!important;width:100%!important;max-width:960px!important;max-height:none!important;overflow:visible!important;margin:0 auto!important}
@media(min-width:1000px){.layout{grid-template-columns:260px minmax(0,1fr)}}
@media(max-width:800px){body{padding-bottom:0!important}main.wrap{padding-bottom:calc(82px + env(safe-area-inset-bottom))!important}.footer{padding-bottom:20px!important;margin-bottom:0!important}.wrap{padding:14px}.hero{padding:32px 0}.layout{grid-template-columns:1fr;gap:14px}.panel{padding:16px}.sectionhead{align-items:flex-start;flex-wrap:wrap}.sectionhead select{width:100%;max-width:none!important}.results,.category-results{grid-template-columns:1fr}.bottom-tabbar button{font-size:11px;padding:9px 2px}.provider-detail-hero{padding:18px}.profile-heading{gap:12px}}
@media(max-width:380px){.hero h1{font-size:1.9rem}.wrap{padding:11px}.card{padding:14px}.bottom-tabbar button{font-size:10px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{transition:none!important;animation:none!important}}

/* Contrast correction for the light customer-app hero in the new design. */
.hero{color:#18243a;background:radial-gradient(ellipse at 82% 0%,rgba(23,200,210,.13),transparent 44%),linear-gradient(145deg,#f8fbff,#eaf1ff)}
.hero h1,.hero h2{color:#17243b!important;text-shadow:none!important}
.hero p{color:#53637d!important}
.hero .eyebrow,.hero .kicker{color:#2454bd!important;background:#e7efff;border-color:#d3e2ff}
.hero .primary,.hero button.primary,.hero .search button{color:#fff!important;background:linear-gradient(120deg,#1768f5,#7657f6)!important}
.hero .hero-note,.hero .muted{color:#5c6b83!important}

/* Skillvaya live customer app: visible rating stars and pinned brand header. */
#platformRatingStars{display:flex!important;align-items:center;gap:6px;flex-wrap:wrap}#platformRatingStars button.platform-rating-star{display:inline-flex!important;align-items:center!important;justify-content:center!important;min-width:42px!important;min-height:46px!important;padding:2px 5px!important;background:transparent!important;background-image:none!important;border:0!important;box-shadow:none!important;border-radius:8px!important;font-size:32px!important;line-height:1!important;cursor:pointer!important;color:#9aa7b5}#platformRatingStars button.platform-rating-star:hover,#platformRatingStars button.platform-rating-star:focus-visible{background:#e7f0ff!important;outline:2px solid #2365d8!important;outline-offset:1px!important}
header.top{position:fixed!important;top:0!important;left:0!important;right:0!important;width:100%!important;z-index:10000!important;isolation:isolate}body{padding-top:78px!important}body.account-screen-mode,body.category-screen-mode,body.messages-screen-mode,body.messages-conversation-open,body.provider-detail-mode,body.provider-screen-mode,body.provider-workstation-mode,body.subscription-test-screen-mode{padding-top:0!important}
/* Approved Skillvaya Digital & Creative Studio screen system — additive, existing actions retained. */
:root{--design-navy:#080f2b;--design-navy2:#111d49;--design-blue:#2864f5;--design-cyan:#20d7e8;--design-violet:#7655f4;--design-surface:#f4f6fc;--design-ink:#17213b}
body{background:var(--design-surface);color:var(--design-ink)}
.top{background:linear-gradient(118deg,var(--design-navy),var(--design-navy2) 70%,#182a63);color:#fff;border-bottom:1px solid rgba(255,255,255,.1);box-shadow:0 10px 28px rgba(8,15,43,.18)}
.top .wrap{padding-top:13px;padding-bottom:13px}.brandlock{align-items:center;gap:13px}.brandlock .sv-logo{width:48px;height:48px;border-radius:13px;object-fit:cover;background:#fff}.brandlock .brand{font-size:clamp(23px,4vw,30px);font-weight:850;letter-spacing:-.7px;color:#fff}.studio-header-subtitle{font-size:13px;font-weight:750;color:#dbe5ff;letter-spacing:.1px}.studio-header-tagline{color:#9eb3e8!important;font-size:11px;letter-spacing:.3px}
#hero{position:relative;overflow:hidden;background:radial-gradient(ellipse at 83% 4%,rgba(32,215,232,.17),transparent 38%),linear-gradient(135deg,#080f2b,#111d49 75%,#16265a);color:#fff;padding:clamp(25px,4vw,44px) 0}
#hero:after{content:"";position:absolute;right:-80px;bottom:-170px;width:320px;height:320px;border:1px solid rgba(106,139,255,.17);border-radius:50%;box-shadow:0 0 0 30px rgba(106,139,255,.035),0 0 0 65px rgba(106,139,255,.025);pointer-events:none}
#hero .wrap{position:relative;z-index:1}#hero h1{color:#fff!important;font-size:clamp(29px,4.5vw,48px);max-width:700px;letter-spacing:-1.2px}#hero p{color:#c7d3ef!important;max-width:660px}#hero .tag{background:rgba(43,106,255,.18)!important;color:#bcd5ff!important;border:1px solid rgba(127,164,255,.35);border-radius:999px;padding:6px 11px}
.search{max-width:920px;display:flex;gap:8px;padding:8px;background:#fff;border:1px solid rgba(255,255,255,.32);border-radius:16px;box-shadow:0 14px 36px rgba(0,0,0,.2)}.search input{flex:1;min-width:0;background:#fff!important;color:#17213b!important;border:0!important;box-shadow:none!important}.search button{min-width:112px;background:linear-gradient(115deg,var(--design-blue),var(--design-violet))!important;border:0!important;color:#fff!important}
.hero-actions-wrap{background:var(--design-surface);border:0}.hero-actions{padding:15px 0 2px}.hero-actions button{border:1px solid #dce4f6;background:#fff;color:#263a65;font-weight:750}.hero-actions button.active{background:#e9efff;color:var(--design-blue);border-color:#cbd9ff}
.design-category-panel{margin:18px 0 24px!important;padding:clamp(17px,3vw,25px)!important;border:1px solid #e0e7f6!important;background:#fff!important;border-radius:22px!important;box-shadow:0 12px 32px rgba(24,44,91,.07)!important}
.design-section-heading{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:16px}.design-section-heading h2{font-size:clamp(22px,3vw,28px);margin:3px 0;color:#17213b}.design-section-heading p{margin:0}.design-eyebrow{font-size:10px;font-weight:850;letter-spacing:1.5px;color:#4268d9}.design-category-tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.design-category-tile{display:flex;align-items:center;gap:10px;min-width:0;min-height:82px;text-align:left;padding:13px 12px;border:1px solid #e1e8f6;border-radius:15px;background:linear-gradient(145deg,#fff,#f8faff);color:#17213b;box-shadow:0 4px 13px rgba(23,46,91,.035)}.design-category-tile:hover{border-color:#b9ccff;box-shadow:0 8px 22px rgba(40,100,245,.1);transform:translateY(-1px)}.design-category-icon{width:39px;height:39px;display:grid;place-items:center;flex:0 0 39px;border-radius:12px;background:linear-gradient(145deg,#eaf0ff,#e8faff);color:#315ee4;font-size:21px;font-weight:850}.design-category-copy{display:flex;flex-direction:column;gap:3px;min-width:0;flex:1}.design-category-copy strong{font-size:12px;line-height:1.3;overflow-wrap:anywhere}.design-category-copy small{font-size:10px;color:#7a87a3}.design-category-arrow{color:#6d7ca3;font-size:23px}.design-category-loading{padding:14px;color:#7a87a3}
#customer{display:block!important}#customer>aside{display:none!important}#customer>section{min-width:0}.sectionhead{margin-bottom:12px}.sectionhead h2{font-size:clamp(23px,3vw,29px)}.provider-directory-dropdown{border-radius:18px}.provider-directory-dropdown>summary{background:linear-gradient(120deg,#f4f7ff,#edfaff);padding:17px}.provider-directory-dropdown>summary strong{font-size:16px}
.biz{background:#fff;border-radius:18px!important}.biz h3{color:#182544}.provider-open button,.primary{background:linear-gradient(115deg,var(--design-blue),var(--design-violet))!important;color:#fff!important;border:0!important}
.bottom-tabbar{background:rgba(255,255,255,.96)!important;border-top:1px solid #e0e6f2!important;box-shadow:0 -8px 28px rgba(9,24,60,.08)!important}.bottom-tabbar button{color:#687797!important;border-radius:13px!important;min-height:52px}.bottom-tabbar button.active{background:#eaf0ff!important;color:var(--design-blue)!important;box-shadow:none!important}
#settings .card,#provider .card,#accountSubspace .card{border-radius:22px!important}
@media(max-width:850px){.design-category-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.design-category-tile{min-height:75px}.search{flex-wrap:wrap}.search input{flex:1 1 40%;min-width:130px}.search button{flex:1 1 100%;width:100%}}
@media(max-width:480px){.brandlock .sv-logo{width:43px;height:43px}.top .wrap{padding-top:10px;padding-bottom:10px}#hero{padding:24px 0 28px}#hero h1{font-size:29px;letter-spacing:-.7px}.design-category-panel{margin:13px 0 18px!important}.design-category-tiles{gap:8px}.design-category-tile{padding:10px 8px;gap:8px}.design-category-icon{width:34px;height:34px;flex-basis:34px;font-size:18px}.design-category-copy strong{font-size:11px}.design-category-copy small{font-size:9px}.design-category-arrow{font-size:20px}.design-section-heading{align-items:flex-start}.design-section-heading .ghost{white-space:nowrap}.bottom-tabbar{gap:3px}.bottom-tabbar button{font-size:10px!important;padding:7px 2px!important}}


/* Mobile layout refinement: keep search and the first category cards visible without scrolling through a tall hero. */
@media(max-width:480px){
 #hero{padding:17px 0 19px}
 #hero h1{font-size:25px;line-height:1.13;letter-spacing:-.55px;margin:9px 0}
 #hero p{font-size:13px;line-height:1.45;margin:8px 0 12px;max-width:100%}
 #hero .tag{font-size:10px;padding:5px 9px}
 .search{padding:6px;gap:6px;border-radius:14px}
 .search input{flex:1 1 100%;width:100%;min-height:38px!important;font-size:13px;padding:8px 10px!important}
 .search button{flex:1 1 100%;min-height:42px!important;font-size:14px}
 .hero-actions-wrap .wrap{padding-top:8px;padding-bottom:0}
 .hero-actions{padding:0}
 .hero-actions button{min-height:40px;font-size:12px}
 .design-category-panel{margin:10px 0 16px!important;padding:15px!important}
 .design-section-heading{margin-bottom:12px}
 .design-section-heading h2{font-size:22px}
}


/* Remove the legacy redundant directory tab on mobile; the new Home tab provides that route. */
@media(max-width:800px){.hero-actions-wrap{display:none!important}}
@media(max-width:480px){
 #hero{padding:12px 0 14px}
 #hero h1{font-size:23px;line-height:1.1;margin:7px 0}
 #hero p{font-size:12px;line-height:1.4;margin:6px 0 9px}
 .search{gap:4px;padding:5px}
 .search input{min-height:34px!important;padding:6px 9px!important}
 .search button{min-height:36px!important}
 .design-section-heading h2{font-size:20px}
 .design-section-heading p{font-size:11px;white-space:nowrap}
 .design-category-panel{padding:13px!important}
}


/* Featured studio card from the approved home dashboard; CTA routes to the live studio listing or graphic-design search. */
.design-promo-card.hidden,.design-category-panel.hidden,#hero.hidden{display:none!important}.design-promo-card{display:flex;align-items:center;gap:13px;margin-top:15px;margin-bottom:3px;padding:14px 16px;border-radius:18px;background:linear-gradient(115deg,#101b43,#17285c);border:1px solid #273c78;box-shadow:0 10px 26px rgba(8,15,43,.13);color:#fff}
.design-promo-icon{width:42px;height:42px;display:grid;place-items:center;flex:0 0 42px;border-radius:13px;background:linear-gradient(140deg,#2864f5,#7655f4);color:#fff;font-size:23px}
.design-promo-copy{display:flex;flex:1;min-width:0;flex-direction:column;gap:3px}.design-promo-copy strong{font-size:14px;color:#fff}.design-promo-copy span{font-size:12px;line-height:1.35;color:#c7d5f8}
.design-promo-button{display:flex;align-items:center;gap:6px;flex:0 0 auto;border:0;border-radius:11px;padding:11px 13px;background:linear-gradient(115deg,#2864f5,#7655f4);color:#fff;font-weight:800;font-size:12px}
@media(max-width:480px){.design-promo-card{gap:9px;margin-top:10px;padding:10px;border-radius:14px}.design-promo-icon{width:34px;height:34px;flex-basis:34px;font-size:18px}.design-promo-copy strong{font-size:12px}.design-promo-copy span{font-size:10px}.design-promo-button{padding:10px 9px;font-size:11px}}


/* Distinct full-page destinations: Services, Contact and Account remain part of the same branded app. */
.app-destination{max-width:1000px;margin:0 auto;padding:24px 0 0}.app-destination.hidden{display:none!important}
.destination-hero{padding:28px clamp(18px,4vw,34px);border-radius:22px;background:radial-gradient(ellipse at 90% 0%,#244d94 0,transparent 54%),linear-gradient(125deg,#07142e,#122b5b);color:#fff;margin-bottom:18px}
.destination-hero h1{font-size:clamp(27px,4vw,38px);line-height:1.12;margin:12px 0}.destination-hero p{color:#d2def6;line-height:1.55;max-width:650px}
.destination-search{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.destination-search input{flex:1;min-width:220px}
.destination-card{padding:clamp(16px,3vw,26px);margin:16px 0;border-radius:20px;background:#fff;border:1px solid #e1e9f5;box-shadow:0 10px 30px rgba(12,35,77,.06)}
.destination-section-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.destination-section-heading h2{margin:5px 0;font-size:clamp(21px,3vw,28px)}
.services-provider-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.services-provider-card{display:flex;text-align:left;align-items:center;gap:12px;width:100%;padding:15px;border-radius:16px;background:#f8faff;border:1px solid #dfe8f6;color:#142345;cursor:pointer}
.services-provider-avatar{width:46px;height:46px;flex:0 0 46px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(135deg,#2563eb,#7655f4);color:white;font-size:20px;font-weight:800}
.services-provider-info{display:flex;flex-direction:column;gap:5px;min-width:0;flex:1}.services-provider-info strong{overflow-wrap:anywhere}.services-provider-info small{color:#597096}.services-provider-info span{font-size:12px;color:#64748b;line-height:1.4}.services-provider-card> b{font-size:23px;color:#4f6fa7}
.contact-destination-hero{margin-bottom:16px}.contact-method-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.contact-method-card{display:flex;align-items:center;gap:12px;padding:16px;border-radius:17px;border:1px solid #dce7f7;background:#fff;color:#162748;text-decoration:none;box-shadow:0 7px 22px rgba(12,35,77,.05);min-width:0}
.contact-method-icon{width:42px;height:42px;flex:0 0 42px;border-radius:13px;background:#eaf1ff;color:#2864e8;display:grid;place-items:center;font-size:22px}.contact-method-card>span:nth-child(2){display:flex;flex:1;min-width:0;flex-direction:column;gap:5px}.contact-method-card strong{font-size:14px}.contact-method-card small{font-size:12px;color:#64748b;overflow-wrap:anywhere}.contact-method-card>b{color:#5978ad;font-size:22px}
.contact-form-card{max-width:760px}.contact-form-card form{display:flex;flex-direction:column;gap:9px}.contact-form-card label{font-size:13px;font-weight:700;margin-top:5px}.contact-form-card input,.contact-form-card select,.contact-form-card textarea{width:100%;border:1px solid #d4deed;border-radius:12px;padding:12px;background:#fbfcff;color:#142345}.contact-form-card textarea{resize:vertical}.contact-form-card button{align-self:flex-start;margin-top:8px}
@media(max-width:620px){.app-destination{padding-top:14px}.destination-hero{padding:22px 17px;border-radius:17px}.services-provider-grid{grid-template-columns:1fr}.contact-method-grid{grid-template-columns:1fr}.contact-method-card{padding:13px}.destination-search{display:grid}.destination-search input,.destination-search button{width:100%;min-width:0}.destination-section-heading{align-items:flex-start}}


/* Profile/settings visual hierarchy matching the navy-and-blue Skillvaya screens. */
#settings>.card{background:linear-gradient(180deg,#f7faff 0,#fff 220px);border:1px solid #dce6f5}
.profile-heading{display:flex;align-items:center;gap:15px;padding:16px 17px;border-radius:17px;background:linear-gradient(120deg,#091833,#17376c);color:#fff}
.profile-heading h2{margin:0;color:#fff;font-size:clamp(23px,4vw,30px)}
.profile-heading img{width:64px;height:64px;border-radius:50%;object-fit:cover;border:3px solid #d7e5ff;box-shadow:0 0 0 3px rgba(75,126,235,.28)}
#profileAuthTabs{padding:7px;border-radius:14px;background:#eaf1ff}
#profileAuthTabs button{flex:1;min-height:43px;border-radius:11px}
#profileSettingsCard>h3{margin-top:22px;padding-bottom:8px;border-bottom:1px solid #e4ebf5;color:#14264a}
#profileSettingsCard .card{border:1px solid #dfe8f6;background:#f8faff;box-shadow:none}
#profileSettingsCard input:not([type=checkbox]),#profileSettingsCard select{border-radius:11px;border:1px solid #d5e0f0}
@media(max-width:480px){.profile-heading{padding:13px;gap:12px}.profile-heading img{width:54px;height:54px}#profileSettingsCard .photo-picker{display:flex;flex-wrap:wrap;gap:8px}}


/* Account v2: distinct dashboard, not a repeated Home/provider layout. */
#settings{max-width:980px!important;padding:18px 0 90px!important}
#settings>.card{padding:0!important;overflow:hidden;border:1px solid #dce6f5!important;border-radius:24px!important;background:#fff!important;box-shadow:0 18px 48px rgba(16,35,63,.10)!important}
#settings .profile-heading{position:relative;isolation:isolate;min-height:164px;padding:28px clamp(18px,4vw,34px)!important;border-radius:0!important;background:radial-gradient(ellipse at 95% 0%,rgba(40,112,229,.52),transparent 45%),linear-gradient(125deg,#09172e 0%,#102d55 65%,#164b86 100%)!important;gap:20px!important}
#settings .profile-heading:after{content:"";position:absolute;z-index:-1;right:-44px;bottom:-96px;width:245px;height:245px;border:1px solid rgba(255,255,255,.13);border-radius:50%;box-shadow:0 0 0 24px rgba(255,255,255,.035),0 0 0 50px rgba(255,255,255,.025)}
#settings .profile-heading img{width:82px!important;height:82px!important;flex:0 0 82px;border:3px solid rgba(255,255,255,.8)!important;box-shadow:0 0 0 5px rgba(255,255,255,.1)!important}
#settings .profile-heading-copy{position:relative;z-index:1;min-width:0}
#settings .account-eyebrow{display:block;margin-bottom:8px;color:#9fc8ff;font-size:10px;letter-spacing:2px;font-weight:850}
#settings .profile-heading h2{font-size:clamp(27px,5vw,36px)!important;letter-spacing:-.8px}
#settings #accountHeroSubtitle{margin:7px 0 0;color:#d5e5fb;font-size:13px;line-height:1.55;max-width:460px}
#settings .account-dashboard-links{position:relative;z-index:20010;pointer-events:auto;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;padding:16px clamp(14px,3vw,26px);border-bottom:1px solid #e7edf6;background:#f8faff}
#settings .account-link{display:flex;flex-direction:column;align-items:flex-start;gap:5px;min-width:0;text-align:left;padding:13px 12px;border:1px solid #e0e8f4;border-radius:15px;background:#fff;color:#1b2e4c;box-shadow:0 3px 10px rgba(16,35,63,.025)}
#settings .account-link>span{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:#edf3ff;color:#245dcc;font-size:18px}
#settings .account-link strong{font-size:12px}
#settings .account-link small{font-size:10px;line-height:1.35;color:#73819a}
#settings .account-link.active,#settings .account-link:hover{border-color:#9ebdf4;background:#f0f5ff}
#settings #profileAuthTabs,#settings #signinPane,#settings #signupPane,#settings #profileSettingsCard{margin-left:clamp(14px,3vw,26px);margin-right:clamp(14px,3vw,26px)}
#settings #profileAuthTabs{margin-top:20px!important}
#settings #signinPane,#settings #signupPane{padding:22px;margin-top:20px;border:1px solid #e1e9f5;border-radius:18px;background:linear-gradient(150deg,#f8faff,#fff)}
#settings #profileSettingsCard{padding:20px 0 28px}
#settings #profileSettingsCard>h3{margin-top:26px;padding-bottom:10px;border-bottom:1px solid #e5ebf4;color:#13294a;font-size:18px}
#settings #profileSettingsCard .card{border:1px solid #e0e8f4;background:#f8faff;box-shadow:none}
#settings #profileSettingsCard input:not([type=checkbox]),#settings #profileSettingsCard select{min-height:45px;border-radius:11px;border:1px solid #d4dfef;background:#fff}
#settings #profileSettingsCard .photo-picker{gap:8px}
#settings #profileSettingsCard .photo-pick-button{border-radius:11px}
#settings #profileSettingsCard form#profileForm{padding:16px;border:1px solid #e1e9f5;border-radius:16px;background:#fbfcff}
#settings #profileSettingsCard form#passwordForm{padding:18px;border:1px solid #e1e9f5;border-radius:16px;background:#fbfcff}
#settings #profileSettingsCard>div:last-child{margin-bottom:8px}
@media(max-width:700px){#settings .account-dashboard-links{grid-template-columns:repeat(2,minmax(0,1fr))}#settings .account-link{min-height:92px}#settings .account-link:last-child{grid-column:1/-1}#settings .profile-heading{min-height:142px;padding:22px 17px!important;gap:14px!important}#settings .profile-heading img{width:62px!important;height:62px!important;flex-basis:62px}#settings #profileSettingsCard{padding-top:12px}}
@media(max-width:380px){#settings .account-dashboard-links{gap:7px;padding:12px}#settings .account-link{padding:10px}#settings .profile-heading img{width:52px!important;height:52px!important;flex-basis:52px}}
body.provider-detail-mode{overflow:hidden!important}
body.provider-detail-mode #providerDetailScreen:not(.hidden){position:fixed!important;inset:0!important;z-index:10000!important;display:block!important;width:100%!important;max-width:none!important;height:100dvh!important;min-height:100dvh!important;overflow-y:auto!important;overscroll-behavior:contain!important;margin:0!important;padding:calc(16px + env(safe-area-inset-top)) 16px calc(28px + env(safe-area-inset-bottom))!important;background:var(--paper,#f5f8fc)!important;box-sizing:border-box!important}
body.provider-detail-mode .top,body.provider-detail-mode .bottom-tabbar{display:none!important}
body.provider-detail-mode main.wrap{padding-top:0!important}
body.provider-detail-mode #providerDetailScreen>.ghost{position:sticky;top:0;z-index:2;margin-bottom:10px}
body.provider-detail-mode #providerDetailContent{max-width:900px;margin:14px auto 0!important}

/* Hard isolation: each destination owns its viewport; directory content never bleeds into Account/Profile. */
body.account-screen-mode #hero,body.account-screen-mode .top,body.account-screen-mode #customer,body.account-screen-mode #categoryScreen,body.account-screen-mode #designCategoryPanel,body.account-screen-mode #designPromoCard,body.account-screen-mode #hero-actions-wrap,body.account-screen-mode #owner-promotions-public,body.account-screen-mode #platformRatingCard,body.account-screen-mode #servicesTabScreen,body.account-screen-mode #provider,body.account-screen-mode #contactUsScreen{display:none!important}
body.category-screen-mode #hero,body.category-screen-mode .top,body.category-screen-mode #customer,body.category-screen-mode #designCategoryPanel,body.category-screen-mode #designPromoCard,body.category-screen-mode #hero-actions-wrap,body.category-screen-mode #owner-promotions-public,body.category-screen-mode #platformRatingCard,body.category-screen-mode #servicesTabScreen,body.category-screen-mode #settings,body.category-screen-mode #provider,body.category-screen-mode #contactUsScreen{display:none!important}
body.messages-screen-mode #hero,body.messages-screen-mode .top,body.messages-screen-mode #customer,body.messages-screen-mode #categoryScreen,body.messages-screen-mode #designCategoryPanel,body.messages-screen-mode #designPromoCard,body.messages-screen-mode #hero-actions-wrap,body.messages-screen-mode #owner-promotions-public,body.messages-screen-mode #platformRatingCard,body.messages-screen-mode #servicesTabScreen,body.messages-screen-mode #settings,body.messages-screen-mode #provider,body.messages-screen-mode #contactUsScreen{display:none!important}body.messages-screen-mode #messagesScreen{display:block!important;visibility:visible!important}body.messages-screen-mode #messagesScreen .messages-workspace-card{display:block!important}body.provider-screen-mode #hero,body.provider-screen-mode .top,body.provider-screen-mode #customer,body.provider-screen-mode #categoryScreen,body.provider-screen-mode #designCategoryPanel,body.provider-screen-mode #designPromoCard,body.provider-screen-mode #hero-actions-wrap,body.provider-screen-mode #owner-promotions-public,body.provider-screen-mode #platformRatingCard,body.provider-screen-mode #servicesTabScreen,body.provider-screen-mode #settings,body.provider-screen-mode #contactUsScreen{display:none!important}body.provider-screen-mode #provider{display:block!important}#messagesScreen .destination-hero{background:linear-gradient(135deg,#071426,#123b56 72%,#087f80);color:#fff;border-radius:24px;padding:clamp(22px,4vw,34px);margin-bottom:18px}#messagesScreen .destination-hero h1{font-size:clamp(30px,5vw,42px);letter-spacing:-1px;margin:8px 0}#messagesScreen .destination-hero p{color:#d7e7f1;max-width:720px}#messagesScreen .destination-card{border:1px solid #dce6ef;border-radius:22px;padding:clamp(14px,3vw,24px);background:#fff;box-shadow:0 14px 38px #0a25400d}#messagesScreen .messages-workspace-card{margin-top:0!important}#messagesScreen #messagesCard>h2{font-size:24px;margin:0 0 6px}#messagesScreen #messagesCard>p{margin-top:0}#messagesScreen #messagesList{border:1px solid #e1e9f1;border-radius:16px;overflow:hidden;background:#fff}#messagesScreen .conversation-list-item{min-height:78px;padding:16px;transition:background .15s}#messagesScreen .conversation-list-item:active{background:#edf8f7}#messagesScreen .conversation-avatar{box-shadow:0 0 0 3px #e5f7f5}#messagesScreen .contacts-shortcuts{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 18px}#messagesScreen .contacts-shortcuts button{border-radius:12px;min-height:42px}#messagesScreen .contacts-subheading{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:22px 0 10px}#messagesScreen .contacts-subheading h3{margin:0;font-size:17px}#messagesScreen .message-conversation-screen{min-height:55vh}#messagesScreen .message-conversation-header{border-radius:12px;padding:12px}#messagesScreen .message-compose{position:sticky;bottom:0;background:#f5f8fb;padding:10px;border-radius:14px}@media(max-width:520px){#messagesScreen .destination-hero{border-radius:18px;margin:0 0 12px}#messagesScreen .destination-card{border-radius:18px;padding:12px}#messagesScreen .conversation-list-item{padding:13px 11px;gap:10px}#messagesScreen .conversation-summary span{max-width:52vw}}/* Messages uses Skillvaya blue styling; contact list and individual chats stay in their own destination. */
#messagesScreen{padding:clamp(14px,3vw,28px) 0 100px;min-height:65vh}#messagesScreen .contacts-workspace{max-width:900px;margin:0 auto}#messagesScreen #messagesCard{border:1px solid #d8e5f5;border-radius:22px;padding:clamp(14px,3vw,24px);background:#fff;box-shadow:0 14px 36px #0b2c5210}#messagesScreen #messagesCard>h2{color:#123b70;font-size:clamp(23px,4vw,30px);margin:0 0 14px}#messagesScreen .conversation-list-item{width:100%;display:flex;align-items:center;text-align:left;gap:14px;border:0;border-bottom:1px solid #e8eef7;background:#fff;color:#132b48;cursor:pointer}#messagesScreen .conversation-list-item:last-child{border-bottom:0}#messagesScreen .conversation-list-item:hover{background:#f3f8ff}#messagesScreen .conversation-avatar{width:48px;height:48px;min-width:48px;border-radius:50%;display:grid;place-items:center;background:linear-gradient(145deg,#0d6efd,#154b9b);color:white;font-weight:800;box-shadow:0 0 0 3px #e8f1ff}#messagesScreen .conversation-summary{display:flex;flex:1;min-width:0;flex-direction:column;gap:5px}#messagesScreen .conversation-summary strong{color:#123b70;font-size:15px}#messagesScreen .conversation-summary span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#61738a;font-size:13px}#messagesScreen .conversation-meta{display:flex;flex-direction:column;align-items:flex-end;gap:7px;color:#7a8ba0;font-size:11px}#messagesScreen .message-conversation-screen{display:flex;flex-direction:column;min-height:58vh;background:#f5f8fd;border:1px solid #dce7f5;border-radius:18px;overflow:hidden}#messagesScreen .message-conversation-screen>.ghost{align-self:flex-start;margin:12px;color:#1358ad}#messagesScreen .message-conversation-header{display:flex;align-items:center;gap:12px;background:#fff;border-top:1px solid #e1eaf5;border-bottom:1px solid #e1eaf5;padding:14px}#messagesScreen .message-conversation-header h2{font-size:18px;margin:0;color:#123b70}#messagesScreen .message-conversation-header p{margin:4px 0 0}#messagesScreen .message-bubbles{display:flex;flex:1;flex-direction:column;gap:10px;padding:16px;overflow-y:auto;max-height:55vh;background:linear-gradient(#f6f9fe,#edf4fc)}#messagesScreen .message-row{display:flex;width:100%}#messagesScreen .message-row.mine{justify-content:flex-end}#messagesScreen .message-row.theirs{justify-content:flex-start}#messagesScreen .message-bubble{max-width:min(82%,560px);padding:10px 13px;border-radius:16px;background:#fff;color:#20334c;box-shadow:0 2px 8px #173b650c;overflow-wrap:anywhere;white-space:pre-wrap}#messagesScreen .message-row.mine .message-bubble{background:#dbeafe;border:1px solid #bfdbfe;border-bottom-right-radius:5px}#messagesScreen .message-row.theirs .message-bubble{border:1px solid #e1e9f3;border-bottom-left-radius:5px}#messagesScreen .message-time{margin-top:5px;text-align:right;color:#708198;font-size:10px}#messagesScreen .message-compose{display:flex;gap:10px;align-items:flex-end;position:sticky;bottom:0;background:#fff;border-top:1px solid #dce7f5;padding:12px}#messagesScreen .message-compose textarea{flex:1;min-width:0;resize:vertical;border:1px solid #cfdded;border-radius:14px;padding:12px;background:#f8fbff;color:#162d49}#messagesScreen .message-compose button{min-height:44px;min-width:90px;background:#1264d8;color:#fff;border-radius:12px}@media(max-width:520px){#messagesScreen .message-compose{gap:7px;padding:9px}#messagesScreen .message-compose button{min-width:76px}#messagesScreen .message-bubbles{padding:12px}}
/* Dedicated WhatsApp-style messaging workspace: it lives only inside Messages, never Account/Home. *//* Contacts viewport fit: prevent page-level scrolling; only the conversation list/chat history scrolls. *//* Skillvaya brand finish: compact contact rows, teal/navy surfaces, less empty white space. */
body.messages-screen-mode #messagesScreen{background:#edf4f5!important;color:#102c3b!important}
body.messages-screen-mode #messagesScreen #messagesCard.messages-app-card{background:#f4f8f8!important;border-color:#c9dedc!important;box-shadow:0 8px 26px #063b4018!important}
body.messages-screen-mode #messagesScreen .messages-app-header{min-height:68px!important;padding:12px 15px!important;background:linear-gradient(125deg,#10233f 0%,#174f86 100%)!important}
body.messages-screen-mode #messagesScreen .messages-app-mark{width:40px!important;height:40px!important;flex-basis:40px!important;background:#d7f5ed!important;color:#075b5d!important}
body.messages-screen-mode #messagesScreen .messages-app-title h1{font-size:19px!important;letter-spacing:-.3px!important}
body.messages-screen-mode #messagesScreen .messages-app-title p{font-size:11px!important;color:#d3f0ec!important}
body.messages-screen-mode #messagesScreen .messages-search-wrap{margin:9px 12px 4px!important;min-height:42px!important;border-color:#c8dfdc!important;border-radius:12px!important;background:#e5f1ef!important}
body.messages-screen-mode #messagesScreen .messages-search-wrap input{padding:9px 0!important}
body.messages-screen-mode #messagesScreen .messages-list-heading{padding:8px 15px!important;color:#075b5d!important}
body.messages-screen-mode #messagesScreen #messagesList{background:#f4f8f8!important}
body.messages-screen-mode #messagesScreen .conversation-list-item{min-height:66px!important;padding:9px 13px!important;gap:10px!important;border-bottom:1px solid #dce9e7!important;background:#f8fbfb!important}
body.messages-screen-mode #messagesScreen .conversation-list-item:hover,body.messages-screen-mode #messagesScreen .conversation-list-item:focus-visible{background:#e6f5f1!important}
body.messages-screen-mode #messagesScreen .conversation-avatar{width:42px!important;height:42px!important;flex-basis:42px!important;background:linear-gradient(145deg,#b9e7dc,#72c7b8)!important;color:#075b5d!important;font-size:16px!important}
body.messages-screen-mode #messagesScreen .conversation-summary{gap:3px!important}
body.messages-screen-mode #messagesScreen .conversation-summary strong{font-size:14px!important;color:#123e43!important}
body.messages-screen-mode #messagesScreen .conversation-summary span{font-size:12px!important;color:#607d7d!important}
body.messages-screen-mode #messagesScreen .conversation-count{background:#087f80!important;color:#fff!important}
body.messages-screen-mode #messagesScreen .messages-empty-state{padding:32px 18px!important;color:#587576!important}
body.messages-screen-mode #messagesScreen .messages-empty-state h3{font-size:18px!important;color:#075b5d!important}
body.messages-screen-mode #messagesScreen .message-conversation-screen{background:#e5f0ed!important}
body.messages-screen-mode #messagesScreen .message-conversation-header{padding:10px 13px!important;background:#f8fbfa!important;border-color:#cfe0dc!important}
body.messages-screen-mode #messagesScreen .message-conversation-header h2{color:#104b4b!important}
body.messages-screen-mode #messagesScreen .message-bubbles{padding:12px 10px!important;background-color:#e5f0ed!important;background-image:radial-gradient(#c8ded8 .65px,transparent .65px)!important}
body.messages-screen-mode #messagesScreen .message-row.mine .message-bubble{background:#c9f2df!important;color:#163e35!important}
body.messages-screen-mode #messagesScreen .message-row.theirs .message-bubble{background:#fff!important;color:#203a3a!important}
body.messages-screen-mode #messagesScreen .message-compose{background:#f4f8f7!important;border-color:#cbded9!important}
body.messages-screen-mode #messagesScreen .message-compose textarea{background:#fff!important;border-color:#bfd8d2!important}
body.messages-screen-mode #messagesScreen .message-compose button{background:#087f80!important;color:#fff!important}
body.messages-screen-mode #messagesScreen .message-conversation-screen>.ghost{background:#dff3ed!important;color:#075b5d!important}
@media(max-width:520px){body.messages-screen-mode #messagesScreen .messages-app-header{padding:10px 13px!important}body.messages-screen-mode #messagesScreen .conversation-list-item{min-height:62px!important;padding:8px 11px!important}body.messages-screen-mode #messagesScreen .conversation-avatar{width:38px!important;height:38px!important;flex-basis:38px!important}}
html:has(body.messages-screen-mode),body.messages-screen-mode{height:100%;max-height:100dvh;overflow:hidden!important;overscroll-behavior:none}
body.messages-screen-mode main.wrap{height:100dvh!important;max-height:100dvh!important;overflow:hidden!important;padding-top:0!important;padding-bottom:0!important;margin:0!important}
body.messages-screen-mode #messagesScreen:not(.hidden){position:fixed!important;inset:0 0 calc(82px + env(safe-area-inset-bottom)) 0!important;z-index:4500!important;width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;overflow:hidden!important;padding:0!important;margin:0!important;display:flex!important;flex-direction:column!important;background:#f4f7fb!important;overscroll-behavior:none!important}
body.messages-screen-mode #messagesScreen .contacts-workspace{display:flex!important;flex:1!important;flex-direction:column!important;width:100%!important;height:100%!important;min-height:0!important;max-height:100%!important;overflow:hidden!important;padding:0!important;margin:0 auto!important}
body.messages-screen-mode #messagesScreen #messagesCard.messages-app-card{flex:1!important;height:100%!important;min-height:0!important;max-height:100%!important;overflow:hidden!important;border-radius:0!important}
body.messages-screen-mode #messagesScreen #messagesList{flex:1!important;min-height:0!important;overflow-y:auto!important;overscroll-behavior:contain!important;-webkit-overflow-scrolling:touch}
body.messages-screen-mode #messagesScreen .message-conversation-screen{flex:1!important;height:100%!important;min-height:0!important;max-height:100%!important;overflow:hidden!important}
body.messages-screen-mode #messagesScreen .message-bubbles{min-height:0!important;overscroll-behavior:contain!important;-webkit-overflow-scrolling:touch}
body.messages-screen-mode #messagesScreen .message-compose{position:relative!important;bottom:auto!important;flex:0 0 auto!important;padding-bottom:calc(9px + env(safe-area-inset-bottom))!important}
body.messages-screen-mode .bottom-tabbar{position:fixed!important;bottom:0!important;left:0!important;right:0!important;z-index:5000!important}
#messagesScreen{padding:0 0 calc(90px + env(safe-area-inset-bottom))!important;min-height:calc(100dvh - 80px);background:#f4f7fb}
#messagesScreen .contacts-workspace{width:100%;max-width:860px;margin:0 auto;padding:0 0 12px}
#messagesScreen #messagesCard.messages-app-card{display:flex;flex-direction:column;min-height:calc(100dvh - 150px);margin:0;background:#fff;border:1px solid #dce5ef;border-radius:0 0 22px 22px;padding:0;overflow:hidden;box-shadow:0 8px 30px #17365d0d}
#messagesScreen .messages-app-header{display:flex;align-items:center;gap:13px;padding:18px 20px;background:linear-gradient(125deg,#10233f,#174f86);color:#fff}
#messagesScreen .messages-app-mark{width:46px;height:46px;display:grid;place-items:center;flex:0 0 46px;border-radius:50%;background:#e4f1ff;color:#174f86;font-size:15px;font-weight:900;letter-spacing:-.5px}
#messagesScreen .messages-app-title{flex:1;min-width:0}
#messagesScreen .messages-app-title h1{margin:0;font-size:22px;line-height:1.2;color:#fff;letter-spacing:-.4px}
#messagesScreen .messages-app-title p{margin:4px 0 0;color:#d7e8f9;font-size:13px}
#messagesScreen .messages-online-dot{width:10px;height:10px;border-radius:50%;background:#5ee0b1;box-shadow:0 0 0 4px #ffffff1f}
#messagesScreen .messages-search-wrap{display:flex;align-items:center;gap:10px;margin:15px 16px 10px;padding:0 14px;border:1px solid #e0e8f0;border-radius:14px;background:#f4f7fa;color:#6c7b8c}
#messagesScreen .messages-search-wrap>span{font-size:25px;line-height:1}
#messagesScreen .messages-search-wrap input{width:100%;min-width:0;border:0;outline:0;box-shadow:none;background:transparent;padding:13px 0;color:#1b2e45}
#messagesScreen .messages-list-heading{display:flex;align-items:center;justify-content:space-between;padding:10px 20px;color:#173b63}
#messagesScreen .messages-list-heading strong{font-size:15px}
#messagesScreen #messagesCount{font-size:12px;color:#718198}
#messagesScreen #messagesList{flex:1;min-height:220px;background:#fff}
#messagesScreen .conversation-list-item{width:100%;min-height:82px;display:flex;align-items:center;gap:13px;padding:13px 18px;border:0;border-bottom:1px solid #edf1f5;border-radius:0;background:#fff;text-align:left;color:#172b43;transition:background .15s}
#messagesScreen .conversation-list-item:hover,#messagesScreen .conversation-list-item:focus-visible{background:#f1f7ff;outline:none}
#messagesScreen .conversation-avatar{width:52px;height:52px;flex:0 0 52px;display:grid;place-items:center;border-radius:50%;background:linear-gradient(145deg,#dbeafe,#bcd8fb);color:#174f86;font-size:19px;font-weight:800;box-shadow:none}
#messagesScreen .conversation-summary{display:flex;flex:1;min-width:0;flex-direction:column;gap:5px}
#messagesScreen .conversation-summary strong{font-size:15px;font-weight:750;color:#172b43}
#messagesScreen .conversation-summary span{font-size:13px;color:#748195;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#messagesScreen .conversation-meta{display:flex;flex-direction:column;align-items:flex-end;gap:7px;color:#8a96a5;font-size:11px}
#messagesScreen .conversation-count{min-width:20px;height:20px;padding:0 5px;display:grid;place-items:center;border-radius:20px;background:#e5effd;color:#1856a0;font-weight:800}
#messagesScreen .messages-empty-state{padding:50px 24px;text-align:center;color:#6b7c90}
#messagesScreen .messages-empty-state h3{margin:0 0 8px;color:#173b63;font-size:20px}
#messagesScreen .messages-loading{display:flex;align-items:center;justify-content:center;gap:10px;padding:45px 18px;color:#6c7b8c}
#messagesScreen .messages-loading-dot{width:8px;height:8px;border-radius:50%;background:#2365d8;box-shadow:14px 0 #9bbce9,28px 0 #d4e2f4;margin-right:24px}
#messagesScreen .message-conversation-screen{min-height:calc(100dvh - 150px);height:calc(100dvh - 150px);max-height:900px;display:flex;flex-direction:column;background:#eaf0f6;border:0;border-radius:0;overflow:hidden}
#messagesScreen .message-conversation-screen>.ghost{align-self:flex-start;margin:9px 12px 0;border-radius:20px;background:#fff;color:#174f86}
#messagesScreen .message-conversation-header{display:flex;align-items:center;gap:12px;padding:13px 16px;background:#fff;border-top:0;border-bottom:1px solid #e3eaf1}
#messagesScreen .message-conversation-header h2{font-size:16px;font-weight:750;color:#172b43}
#messagesScreen .message-conversation-header p{font-size:12px;color:#748195}
#messagesScreen .message-bubbles{flex:1;min-height:180px;max-height:none;overflow-y:auto;gap:8px;padding:18px 13px;background-color:#eaf0f6;background-image:radial-gradient(#d8e1eb 0.65px,transparent 0.65px);background-size:14px 14px}
#messagesScreen .message-row{display:flex;width:100%}
#messagesScreen .message-bubble{max-width:min(84%,560px);padding:10px 12px;border-radius:14px;background:#fff;color:#24364a;box-shadow:0 1px 2px #172b4310;font-size:14px;line-height:1.45}
#messagesScreen .message-row.mine .message-bubble{background:#d9fdd3;border:0;border-bottom-right-radius:4px}
#messagesScreen .message-row.theirs .message-bubble{background:#fff;border:0;border-bottom-left-radius:4px}
#messagesScreen .message-time{font-size:10px;color:#718198}
#messagesScreen .message-compose{display:flex;align-items:flex-end;gap:9px;position:sticky;bottom:0;margin:0;padding:11px;background:#f7f9fb;border-top:1px solid #e0e7ef}
#messagesScreen .message-compose textarea{min-height:44px;max-height:120px;resize:vertical;flex:1;min-width:0;border:1px solid #d8e2ec;border-radius:22px;background:#fff;padding:11px 15px}
#messagesScreen .message-compose button{min-width:72px;min-height:44px;border-radius:22px;background:#1764c0;color:#fff}
#messagesScreen #messagesStatus{padding:0 14px;color:#63748a;font-size:12px}
@media(min-width:700px){#messagesScreen .contacts-workspace{padding:18px 16px}#messagesScreen #messagesCard.messages-app-card{border:1px solid #dce5ef;border-radius:22px;min-height:calc(100dvh - 180px)}#messagesScreen .message-conversation-screen{min-height:calc(100dvh - 180px);height:calc(100dvh - 180px);border-radius:18px}}
@media(max-width:520px){#messagesScreen .contacts-workspace{padding:0}#messagesScreen #messagesCard.messages-app-card{min-height:calc(100dvh - 138px);border-radius:0;border-left:0;border-right:0}#messagesScreen .messages-app-header{padding:15px 16px}#messagesScreen .messages-app-title h1{font-size:20px}#messagesScreen .conversation-list-item{padding:12px 14px;min-height:76px}#messagesScreen .conversation-avatar{width:48px;height:48px;flex-basis:48px}#messagesScreen .message-conversation-screen{height:calc(100dvh - 138px);min-height:calc(100dvh - 138px)}#messagesScreen .message-bubbles{padding:12px 9px}}
/* Contacts-only promo card isolation: verified against Samsung wireless screenshot. */
.design-promo-card{display:none!important}
body.messages-screen-mode #designPromoCard{display:flex!important}
/* Contacts conversation: viewport-locked chat with a fixed composer and local back navigation only. */
body.messages-conversation-open{overflow:hidden!important;overscroll-behavior:none}
body.messages-conversation-open .bottom-tabbar{display:none!important}
body.messages-conversation-open #messagesScreen{position:fixed!important;inset:env(safe-area-inset-top,0px) 0 0!important;z-index:9000!important;width:100vw;height:100dvh!important;min-height:0!important;overflow:hidden!important;padding:0!important;margin:0!important;background:#f4f8fb!important}
body.messages-conversation-open #messagesScreen .messages-workspace-card,body.messages-conversation-open #messagesScreen #messagesCard{position:absolute!important;inset:0!important;width:100%!important;max-width:none!important;height:100%!important;min-height:0!important;max-height:none!important;margin:0!important;padding:0!important;border:0!important;border-radius:0!important;box-shadow:none!important;overflow:hidden!important;background:#f4f8fb!important}
body.messages-conversation-open #messagesScreen #messagesCard>h2,body.messages-conversation-open #messagesScreen #messagesCard>p,body.messages-conversation-open #messagesScreen .contacts-shortcuts,body.messages-conversation-open #messagesScreen .contacts-subheading{display:none!important}
body.messages-conversation-open #messagesScreen #messagesList{position:absolute!important;inset:0!important;height:100%!important;min-height:0!important;overflow:hidden!important;border:0!important;border-radius:0!important;background:#f4f8fb!important}
body.messages-conversation-open .message-conversation-screen{position:absolute!important;inset:0!important;display:flex!important;flex-direction:column!important;width:100%!important;height:100%!important;min-height:0!important;max-height:none!important;margin:0!important;padding:0!important;border:0!important;border-radius:0!important;overflow:hidden!important;background:#f4f8fb!important}
body.messages-conversation-open .message-back-button{flex:0 0 auto!important;align-self:flex-start!important;min-height:44px!important;margin:8px 12px!important;padding:8px 14px!important;border-radius:999px!important;background:#e8f1ff!important;color:#174a91!important;border:1px solid #b8d0f3!important;font-weight:700!important}
body.messages-conversation-open .message-conversation-header{display:none!important;flex:0 0 auto!important;min-height:76px!important;padding:10px 16px!important;border-radius:0!important;border-top:1px solid #dce7f5!important;border-bottom:1px solid #dce7f5!important}
body.messages-conversation-open .message-bubbles{flex:1 1 0!important;min-height:0!important;height:auto!important;max-height:none!important;overflow-y:auto!important;overscroll-behavior:contain!important;padding:14px 12px!important;background:#e8f1ff!important;background-image:linear-gradient(180deg,#eaf3ff 0%,#dbeafe 100%)!important}body.messages-conversation-open .message-row.mine .message-bubble{background:#c6dcff!important;border:1px solid #a8c7fa!important;color:#102b52!important}body.messages-conversation-open .message-row.theirs .message-bubble{background:#f4f8ff!important;border:1px solid #c9dcfa!important;color:#17365e!important}
body.messages-conversation-open .message-compose{position:relative!important;inset:auto!important;flex:0 0 auto!important;display:flex!important;align-items:flex-end!important;gap:8px!important;margin:0!important;padding:5px 12px calc(3px + env(safe-area-inset-bottom))!important;border-top:1px solid #173e78!important;border-radius:0!important;background:#102f60!important}
body.messages-conversation-open .message-compose textarea{flex:1 1 auto!important;min-width:0!important;width:0!important;min-height:48px!important;max-height:150px!important;resize:none!important;overflow-y:auto!important;border:1px solid #3766a8!important;border-radius:18px!important;padding:10px 12px!important;line-height:1.35!important;background:#e8f1ff!important;color:#102b52!important;caret-color:#102b52!important}body.messages-conversation-open .message-compose textarea::placeholder{color:#536f98!important}
body.messages-conversation-open .message-compose button{flex:0 0 auto!important;min-width:82px!important;min-height:48px!important;border-radius:999px!important;background:#2f72d6!important;color:#fff!important;border:1px solid #78a7f0!important}
/* Final high-specificity chat palette: must win over legacy messages-screen !important rules. */
body.messages-screen-mode.messages-conversation-open #messagesScreen,
body.messages-screen-mode.messages-conversation-open #messagesScreen #messagesCard,
body.messages-screen-mode.messages-conversation-open #messagesScreen #messagesList,
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-conversation-screen{background:#eaf3ff!important;color:#17365e!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-bubbles{background:#eaf3ff!important;background-image:linear-gradient(180deg,#eaf3ff 0%,#dbeafe 100%)!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-row.mine .message-bubble{background:#c6dcff!important;border:1px solid #a8c7fa!important;color:#102b52!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-row.theirs .message-bubble{background:#f4f8ff!important;border:1px solid #c9dcfa!important;color:#17365e!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-compose{background:#102f60!important;border-top:1px solid #173e78!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-compose textarea{background:#e8f1ff!important;border:1px solid #3766a8!important;color:#102b52!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-compose button{background:#2f72d6!important;color:#fff!important;border:1px solid #78a7f0!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-back-button{background:#e8f1ff!important;color:#174a91!important;border:1px solid #b8d0f3!important}
/* Full-bleed chat chrome: match the top navigation strip to the navy composer and remove the white bottom gutter. */
html:has(body.messages-conversation-open),body.messages-conversation-open{background:#102f60!important;min-height:100%!important;margin:0!important;padding:0!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen{inset:0!important;bottom:0!important;height:100dvh!important;min-height:100dvh!important;padding:0!important;margin:0!important;background:#102f60!important;overflow:hidden!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen #messagesCard,
body.messages-screen-mode.messages-conversation-open #messagesScreen #messagesList{inset:0!important;bottom:0!important;height:100%!important;min-height:0!important;background:#eaf3ff!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-conversation-screen{inset:0!important;bottom:0!important;height:100%!important;min-height:0!important;max-height:none!important;padding:0!important;margin:0!important;display:flex!important;flex-direction:column!important;gap:0!important;background:#eaf3ff!important;overflow:hidden!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-back-button{display:flex!important;align-items:center!important;align-self:stretch!important;justify-content:flex-start!important;flex:0 0 58px!important;width:100%!important;min-height:58px!important;height:58px!important;margin:0!important;padding:8px 16px!important;border:0!important;border-bottom:1px solid #244c80!important;border-radius:0!important;background:linear-gradient(110deg,#102f60 0%,#174f86 100%)!important;color:#fff!important;text-align:left!important;box-shadow:none!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-bubbles{flex:1 1 0!important;min-height:0!important;height:auto!important;max-height:none!important;margin:0!important;padding:14px 12px!important;background:#eaf3ff!important;background-image:linear-gradient(180deg,#eaf3ff 0%,#dbeafe 100%)!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-compose{position:relative!important;bottom:auto!important;inset:auto!important;flex:0 0 auto!important;width:100%!important;min-height:58px!important;box-sizing:border-box!important;margin:0!important;padding:6px 12px calc(6px + env(safe-area-inset-bottom,0px))!important;border:0!important;border-top:1px solid #244c80!important;border-radius:0!important;background:#102f60!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-compose textarea{min-height:46px!important;margin:0!important;background:#e8f1ff!important;color:#102b52!important}
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-compose button{min-height:46px!important;margin:0!important;background:#2f72d6!important;color:#fff!important}
body.messages-conversation-open .message-conversation-screen>*{box-sizing:border-box}
/* SV56-ACCOUNT-SCROLL-01: account content scrolls inside the viewport and reserves the fixed bottom navigation. */
body.account-screen-mode{height:100dvh!important;max-height:100dvh!important;overflow:hidden!important;overscroll-behavior:none!important}
body.account-screen-mode main.wrap{height:100dvh!important;max-height:100dvh!important;overflow-y:auto!important;overflow-x:hidden!important;overscroll-behavior:contain!important;-webkit-overflow-scrolling:touch!important;padding-top:178px!important;padding-bottom:calc(112px + env(safe-area-inset-bottom))!important;box-sizing:border-box!important}
body.account-screen-mode .bottom-tabbar{position:fixed!important;left:0!important;right:0!important;bottom:0!important;z-index:2147483600!important}
/* Scroll recovery guard: normal pages scroll normally; dedicated chat and account overlays own their own scroll area. */
html,body{overscroll-behavior-y:auto}body:not(.messages-conversation-open):not(.account-subspace-open):not(.provider-detail-mode){overflow-y:auto!important}body:not(.messages-conversation-open) #messagesScreen{overscroll-behavior:contain}
/* Keep real content scrollable while removing stacked bottom padding that created a blank tail. */
main.wrap{padding-bottom:calc(82px + env(safe-area-inset-bottom))!important}main.wrap>.footer{padding-bottom:20px!important;margin-bottom:0!important}body{padding-bottom:0!important}
/* Consistent Skillvaya blue chrome on every screen; preserve existing handlers and layout. */
.bottom-tabbar{background:linear-gradient(110deg,#102f60 0%,#174f86 100%)!important;border-top:1px solid #244c80!important;box-shadow:0 -8px 24px #102f6026!important}
.bottom-tabbar button{background:#174578!important;border:1px solid #3766a8!important;color:#eaf3ff!important;border-radius:12px!important}
.bottom-tabbar button.active,.bottom-tabbar button:focus-visible{background:#2f72d6!important;border-color:#78a7f0!important;color:#fff!important;box-shadow:0 3px 12px #071f4933!important}
#messagesScreen .messages-app-header{background:linear-gradient(110deg,#102f60 0%,#174f86 100%)!important;color:#fff!important}
#messagesScreen .messages-app-header .messages-app-title h1{color:#fff!important}
#messagesScreen .messages-app-header .messages-app-title p{color:#d7e8ff!important}
#messagesScreen .messages-app-header .messages-online-dot{background:#9fc5ff!important;box-shadow:0 0 0 4px #ffffff1f!important}

@media(max-width:520px){body.messages-conversation-open .message-conversation-header{padding:8px 12px!important}body.messages-conversation-open .message-bubbles{padding:12px 10px!important}body.messages-conversation-open .message-compose{gap:7px!important;padding-left:10px!important;padding-right:10px!important;padding-bottom:calc(2px + env(safe-area-inset-bottom))!important}}

/* Provider-only Services workspace: navy, white and light-blue, with independent tool screens. */
/* Isolate the provider workstation from the public directory and other existing screens. */
body.provider-workstation-mode .hero-actions-wrap,
body.provider-workstation-mode #hero,
body.provider-workstation-mode .top,
body.provider-workstation-mode #customer,
body.provider-workstation-mode #categoryScreen,
body.provider-workstation-mode #designCategoryPanel,
body.provider-workstation-mode #designPromoCard,
body.provider-workstation-mode #owner-promotions-public,
body.provider-workstation-mode #platformRatingCard,
body.provider-workstation-mode #provider,
body.provider-workstation-mode #providerDetailScreen,
body.provider-workstation-mode #settings,
body.provider-workstation-mode #messagesScreen,
body.provider-workstation-mode #contactUsScreen {display:none!important}
body.provider-workstation-mode #servicesTabScreen:not(.hidden),
body.provider-workstation-mode #svWorkstationToolScreen:not(.hidden){display:block!important;visibility:visible!important}
body.provider-workstation-mode .bottom-tabbar{display:grid!important;visibility:visible!important}

.sv-workstation{max-width:1160px;margin:0 auto;padding:0 clamp(12px,2vw,20px);color:#10233f;box-sizing:border-box}
body.provider-workstation-mode main.wrap{padding:0!important}
#servicesTabScreen:not(.hidden){height:calc(100dvh - 76px);margin:0!important;padding:0!important;overflow:hidden;overscroll-behavior:none}
#servicesTabScreen:not(.hidden) .sv-workstation{height:100%;display:flex;flex-direction:column;overflow:hidden}
#servicesTabScreen:not(.hidden) .sv-workstation-hero{position:relative!important;top:auto!important;z-index:2!important;flex:0 0 auto;isolation:isolate;background:linear-gradient(135deg,#071426,#102b49)!important;border-radius:0 0 16px 16px!important;box-shadow:0 8px 22px #102f6020!important}
#servicesTabScreen:not(.hidden) .sv-workstation-scroll{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;-webkit-overflow-scrolling:touch;padding-bottom:110px}
.sv-workstation-hero{padding:clamp(20px,3.4vw,34px);border-radius:22px;background:linear-gradient(135deg,#071426,#102b49);color:#fff;box-shadow:0 18px 44px rgba(16,35,63,.14)}
.sv-workstation-hero h1{font-size:clamp(27px,4vw,38px);letter-spacing:-.8px;margin:10px 0}
.sv-workstation-hero p{color:#d4e4f5;max-width:700px;line-height:1.6}
.sv-workstation-eyebrow{font-size:11px;letter-spacing:1.1px;font-weight:900;color:#a9d2fb;text-transform:uppercase}
.sv-workstation-plan{display:inline-flex;padding:7px 11px;border:1px solid #7fb6ef;border-radius:999px;background:#173c68;color:#fff;font-size:12px;font-weight:800;margin-top:8px}
.sv-workstation-tools{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px;margin-top:18px}
.sv-workstation-tool{display:flex;flex-direction:column;min-height:180px;background:#fff;border:1px solid #d9e7f7;border-radius:17px;padding:17px;text-align:left;box-shadow:0 8px 24px rgba(16,35,63,.06)}
.sv-workstation-tool h3{margin:10px 0 6px;font-size:18px;color:#10233f}
.sv-workstation-tool p{color:#5c708a;font-size:13px;line-height:1.5;margin:0 0 14px}
.sv-workstation-icon{display:grid;place-items:center;width:42px;height:42px;border-radius:13px;background:#e8f2ff;color:#1f5b98;font-size:22px;font-weight:900}
.sv-workstation-tool .sv-workstation-open{margin-top:auto;align-self:flex-start;background:#10233f;border:0;border-radius:10px;color:#fff;padding:10px 12px;font-weight:800;cursor:pointer}
.sv-workstation-locked{border-style:dashed;background:#f8fbff}
.sv-workstation-locked .sv-workstation-open{background:#eaf1f9;color:#526b88}
.sv-workstation-banner{margin-top:14px;padding:13px 15px;border-radius:13px;background:#eaf3ff;border:1px solid #c9def7;color:#284868;font-size:13px;line-height:1.55}
.sv-workstation-activity{margin-top:18px;border:1px solid #d9e7f7;border-radius:17px;background:#fff;padding:17px}
.sv-workstation-activity h3{margin:0 0 8px}
.sv-workstation-tool-screen{max-width:1000px;margin:0 auto;padding:18px 14px 110px}
.sv-tool-back{background:#e8f2ff;border:1px solid #c5dbf5;color:#10233f;padding:10px 13px;border-radius:10px;font-weight:800}
.sv-tool-heading{margin:17px 0;padding:19px;border-radius:17px;background:linear-gradient(135deg,#10233f,#214f7e);color:#fff}
.sv-tool-heading h1{margin:0 0 6px;color:#fff;font-size:27px}.sv-tool-heading p{margin:0;color:#d5e6f8;line-height:1.55}
.sv-tool-card{background:#fff;border:1px solid #dce8f5;border-radius:15px;padding:16px;margin:12px 0;box-shadow:0 8px 22px rgba(16,35,63,.05)}
.sv-tool-card h3{margin:0 0 8px;color:#10233f}.sv-tool-muted{font-size:13px;color:#5b7088;line-height:1.55}
.sv-tool-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.sv-tool-fields .sv-full{grid-column:1/-1}
.sv-tool-fields label{display:block;font-size:13px;font-weight:800;color:#274664;margin-bottom:6px}
.sv-tool-fields input,.sv-tool-fields textarea,.sv-tool-fields select{width:100%;border:1px solid #cbdced;border-radius:10px;background:#fff;color:#10233f;padding:11px 12px;font:inherit}
.sv-tool-submit{background:#10233f;color:#fff;border:0;padding:12px 16px;border-radius:10px;font-weight:800;cursor:pointer}
.sv-tool-outline{background:#e8f2ff;color:#10233f;border:1px solid #c6dcf5;padding:10px 13px;border-radius:10px;font-weight:800;cursor:pointer}
.sv-tool-row{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.sv-tool-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.sv-tool-metric{background:#f4f9ff;border:1px solid #d6e7f9;border-radius:14px;padding:15px}
.sv-tool-metric strong{display:block;font-size:27px;color:#10233f}.sv-tool-metric span{display:block;font-size:12px;color:#566f8c;margin-top:5px}
.sv-tool-status{font-size:12px;color:#456381;margin-top:10px;min-height:18px}
@media(max-width:850px){.sv-workstation-tools{grid-template-columns:repeat(2,minmax(0,1fr))}.sv-tool-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:520px){.sv-workstation-tools{grid-template-columns:1fr}.sv-tool-fields{grid-template-columns:1fr}.sv-tool-fields .sv-full{grid-column:auto}.sv-tool-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.sv-workstation-tool{min-height:150px}}

/* Additive in-chat media and WebRTC call UI; isolated from the existing layout. */
/* Place the video-call action in the existing message header, aligned top-right. */
.message-conversation-header{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.message-conversation-header .sv-chat-call-button,.message-conversation-topbar .sv-chat-call-button,.message-conversation-header .sv-chat-voice-call-button,.message-conversation-topbar .sv-chat-voice-call-button{margin-left:auto;flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;min-height:42px;padding:9px 13px;border:1px solid #c5dbf5;border-radius:11px;background:#10233f;color:#fff;font-size:13px;font-weight:800;cursor:pointer;box-shadow:0 4px 12px rgba(16,35,63,.13)}
.message-conversation-header .sv-chat-call-button:hover,.message-conversation-topbar .sv-chat-call-button:hover,.message-conversation-header .sv-chat-voice-call-button:hover,.message-conversation-topbar .sv-chat-voice-call-button:hover{background:#173c68;border-color:#9fc6f2}
.message-conversation-header .sv-chat-call-button:focus-visible,.message-conversation-topbar .sv-chat-call-button:focus-visible,.message-conversation-header .sv-chat-voice-call-button:focus-visible,.message-conversation-topbar .sv-chat-voice-call-button:focus-visible{outline:3px solid #9cc7f4;outline-offset:2px}
.message-conversation-header .sv-chat-phone-call-button,.message-conversation-topbar .sv-chat-phone-call-button{display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;min-height:42px;padding:9px 13px;border:1px solid #bfd8f6;border-radius:11px;background:#e8f2ff;color:#173d68;font-size:13px;font-weight:800;text-decoration:none;cursor:pointer}
.message-conversation-header .sv-chat-phone-call-button:hover,.message-conversation-topbar .sv-chat-phone-call-button:hover{background:#d9eaff;border-color:#9fc6ee}
.message-conversation-header .sv-chat-phone-call-button:focus-visible,.message-conversation-topbar .sv-chat-phone-call-button:focus-visible{outline:3px solid #9cc7f4;outline-offset:2px}
@media(max-width:420px){.message-conversation-header .sv-chat-call-button,.message-conversation-topbar .sv-chat-call-button,.message-conversation-header .sv-chat-voice-call-button,.message-conversation-topbar .sv-chat-voice-call-button,.message-conversation-header .sv-chat-phone-call-button,.message-conversation-topbar .sv-chat-phone-call-button{padding:8px 9px;min-height:38px;font-size:12px}}
.message-conversation-topbar{display:flex;align-items:center;gap:10px;width:100%;margin:0 0 8px;min-width:0}
.message-conversation-topbar .message-back-button{flex:0 1 auto;min-width:0}

.sv-chat-media-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:11px 12px;margin:0 0 10px;border:1px solid #d9e8f8;border-radius:14px;background:#f4f9ff}
.sv-chat-media-toolbar button{border:1px solid #bad4f2;border-radius:10px;background:#fff;color:#10233f;font-size:13px;font-weight:800;padding:10px 12px;cursor:pointer}
.sv-chat-media-toolbar .sv-call-start{background:#10233f;color:#fff;border-color:#10233f}
.sv-chat-media-toolbar .sv-media-upload{background:#e8f2ff;color:#173d68;border-color:#bfd8f6}
.sv-chat-media-status{flex:1 1 100%;font-size:12px;color:#526b88}
.sv-chat-attachment{display:grid;gap:6px;margin-top:8px;max-width:min(420px,75vw)}
.sv-chat-attachment video{width:100%;max-height:340px;border-radius:10px;background:#071426}
.sv-chat-attachment img{display:block;max-width:100%;max-height:320px;object-fit:contain;border-radius:10px;background:#eaf2fb}
.sv-chat-attachment a{font-size:12px;font-weight:700;color:#23558e;overflow-wrap:anywhere}
.sv-call-overlay{position:fixed;inset:0;z-index:15000;background:rgba(5,16,32,.88);display:flex;align-items:center;justify-content:center;padding:12px}
.sv-call-overlay.hidden{display:none!important}
.sv-call-voice-only:not(.hidden) .sv-call-videos{display:none!important}.sv-call-audio-only{display:none}.sv-call-voice-only:not(.hidden) .sv-call-audio-only{display:flex;flex:1 1 auto;min-height:0;align-items:center;justify-content:center;flex-direction:column;gap:12px;color:#fff;text-align:center}.sv-call-audio-avatar{display:grid;place-items:center;width:112px;height:112px;border-radius:50%;background:linear-gradient(145deg,#1d5d9c,#3a8ad2);font-size:42px;box-shadow:0 0 0 12px #1c5a9633}.sv-call-audio-only strong{font-size:20px}.sv-call-audio-only span{font-size:13px;color:#c3d2e7}
.sv-call-panel{width:min(920px,100%);max-height:96dvh;overflow:auto;background:#fff;border-radius:22px;box-shadow:0 30px 90px rgba(0,0,0,.35);color:#10233f;padding:clamp(14px,3vw,24px)}
.sv-call-header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}
.sv-call-header h2{margin:0;font-size:22px;color:#10233f}
.sv-call-state{font-size:13px;color:#4e6682;margin:4px 0 0}
.sv-call-videos{position:relative;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,.34fr);gap:10px;min-height:250px}.sv-call-local-wrap{position:absolute!important;right:12px;bottom:12px;left:auto;top:auto;width:clamp(104px,25vw,190px);height:clamp(82px,22vw,142px);min-height:0!important;z-index:4;cursor:grab;touch-action:none;box-shadow:0 5px 22px rgba(0,0,0,.35);border:2px solid rgba(255,255,255,.9)}.sv-call-local-wrap:active{cursor:grabbing}.sv-call-local-wrap video{width:100%;height:100%;min-height:0!important;max-height:none!important;object-fit:cover;pointer-events:none}
.sv-call-remote-wrap,.sv-call-local-wrap{position:relative;overflow:hidden;min-height:155px;border-radius:16px;background:#071426}
.sv-call-videos video{display:block;width:100%;height:100%;min-height:155px;max-height:58vh;object-fit:cover}
.sv-call-local-wrap video{max-height:30vh}
.sv-call-video-label{position:absolute;left:10px;bottom:10px;border-radius:7px;padding:4px 7px;background:rgba(7,20,38,.8);color:#fff;font-size:11px}
.sv-call-actions{display:flex;justify-content:center;align-items:center;gap:9px;flex-wrap:wrap;padding-top:16px}
.sv-call-actions button{border:0;border-radius:12px;padding:12px 16px;font-weight:800;background:#e8f2ff;color:#10233f;cursor:pointer}
.sv-call-actions .sv-call-end{background:#bd2d3c;color:#fff}
.sv-call-note{font-size:12px;line-height:1.5;color:#5b7088;margin:12px 0 0;text-align:center}
/* Video-call-only layout: fullscreen remote video with an anchored control dock. */
.sv-call-overlay:not(.hidden){inset:0!important;padding:0!important;align-items:stretch!important;justify-content:stretch!important;background:#030914!important}
.sv-call-overlay:not(.hidden) .sv-call-panel{display:flex!important;flex-direction:column!important;gap:0!important;width:100%!important;height:100dvh!important;max-height:100dvh!important;min-height:0!important;overflow:hidden!important;box-sizing:border-box!important;border-radius:0!important;padding:calc(env(safe-area-inset-top) + 10px) 12px calc(env(safe-area-inset-bottom) + 12px)!important;background:#030914!important;color:#fff!important}
.sv-call-overlay:not(.hidden) .sv-call-header{flex:0 0 auto!important;gap:8px!important;margin:0 0 8px!important;padding:4px 2px 10px!important;border-bottom:1px solid #24334a!important}
.sv-call-overlay:not(.hidden) .sv-call-header h2{color:#fff!important;font-size:18px!important}
.sv-call-overlay:not(.hidden) .sv-call-state{color:#c3d2e7!important}
.sv-call-overlay:not(.hidden) .sv-call-header .sv-tool-outline{flex:0 0 auto!important}
.sv-call-overlay:not(.hidden) .sv-call-videos{position:relative!important;display:block!important;flex:1 1 auto!important;min-height:0!important;height:auto!important;overflow:hidden!important;border-radius:16px!important;background:#030914!important}
.sv-call-overlay:not(.hidden) .sv-call-remote-wrap{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;min-height:0!important;border-radius:16px!important;background:#030914!important}
.sv-call-overlay:not(.hidden) #svCallRemoteVideo{display:block!important;width:100%!important;height:100%!important;min-height:0!important;max-height:none!important;object-fit:cover!important;background:#030914!important}
.sv-call-overlay:not(.hidden) .sv-call-local-wrap{position:absolute!important;right:12px!important;bottom:12px!important;left:auto!important;top:auto!important;width:clamp(100px,28vw,150px)!important;height:clamp(126px,22vh,190px)!important;min-height:0!important;max-height:none!important;z-index:4!important;cursor:grab!important;touch-action:none!important}
.sv-call-overlay:not(.hidden) #svCallLocalVideo{width:100%!important;height:100%!important;min-height:0!important;max-height:none!important;object-fit:cover!important;pointer-events:none!important}
.sv-call-overlay:not(.hidden) .sv-call-actions{flex:0 0 auto!important;display:grid!important;grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)!important;align-items:center!important;gap:10px!important;width:100%!important;padding:14px 0 8px!important}
.sv-call-overlay:not(.hidden) .sv-call-actions button{min-width:0!important;min-height:52px!important;padding:10px 5px!important;border-radius:16px!important;font-size:12px!important;line-height:1.2!important;white-space:normal!important}
.sv-call-overlay:not(.hidden) .sv-call-actions .sv-call-end{background:#c5283d!important;color:#fff!important}
.sv-call-overlay:not(.hidden) .sv-call-note{display:none!important}
.sv-call-overlay.sv-call-voice-only:not(.hidden) .sv-call-videos{display:none!important}.sv-call-overlay.sv-call-voice-only:not(.hidden) .sv-call-audio-only{display:flex!important} .sv-call-overlay.sv-call-voice-only:not(.hidden) .sv-call-actions{grid-template-columns:minmax(0,1fr) minmax(0,1fr)!important}
@media(min-width:700px){.sv-call-overlay:not(.hidden) .sv-call-panel{padding:calc(env(safe-area-inset-top) + 14px) 24px calc(env(safe-area-inset-bottom) + 18px)!important}.sv-call-overlay:not(.hidden) .sv-call-actions{max-width:620px!important;margin:0 auto!important}.sv-call-overlay:not(.hidden) .sv-call-actions button{font-size:14px!important}}
.sv-incoming-panel{position:fixed;z-index:16000;left:12px;right:12px;top:calc(12px + env(safe-area-inset-top));max-width:460px;margin:auto;border:1px solid #c7ddf7;border-radius:18px;padding:16px;background:#fff;box-shadow:0 18px 50px rgba(7,20,38,.28);color:#10233f}
.sv-incoming-panel[hidden]{display:none}
.sv-incoming-panel.sv-call-ringing{border:2px solid #1c67b7;box-shadow:0 0 0 5px rgba(28,103,183,.16),0 18px 50px rgba(7,20,38,.32)}
.sv-incoming-actions{display:flex;gap:8px;margin-top:12px}
.sv-incoming-actions button{flex:1;border:0;border-radius:10px;padding:11px 14px;font-weight:800;cursor:pointer}
.sv-call-accept{background:#10233f;color:white}.sv-call-decline{background:#eef4fb;color:#10233f}
@media(max-width:560px){.sv-call-videos{grid-template-columns:1fr}.sv-call-remote-wrap{min-height:220px}.sv-call-local-wrap{min-height:100px;max-width:150px;margin-left:auto}.sv-call-videos video{max-height:45vh}.sv-call-local-wrap video{max-height:20vh}.sv-chat-media-toolbar button{flex:1 1 auto}}

/* Surgical mobile chat-header fix: keep Back + Video call on one continuous navy row. */
body.messages-conversation-open #messagesScreen .message-conversation-topbar,
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-conversation-topbar{
 display:flex!important;flex-direction:row!important;flex-wrap:nowrap!important;align-items:center!important;justify-content:space-between!important;gap:8px!important;
 position:relative!important;z-index:2!important;width:100%!important;min-width:0!important;box-sizing:border-box!important;
 margin:0!important;padding:8px 12px!important;min-height:64px!important;height:auto!important;border:0!important;border-bottom:1px solid #244c80!important;border-radius:0!important;
 background:linear-gradient(110deg,#102f60 0%,#174f86 100%)!important;color:#fff!important;box-shadow:none!important;
}
body.messages-conversation-open #messagesScreen .message-conversation-topbar .message-back-button,
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-conversation-topbar .message-back-button{
 display:flex!important;flex:1 1 auto!important;align-items:center!important;justify-content:flex-start!important;width:auto!important;min-width:0!important;max-width:100%!important;
 height:46px!important;min-height:46px!important;margin:0!important;padding:8px 10px!important;border:0!important;border-radius:8px!important;
 background:transparent!important;color:#fff!important;font-size:13px!important;font-weight:750!important;line-height:1.2!important;text-align:left!important;
 white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;box-shadow:none!important;
}
body.messages-conversation-open #messagesScreen .message-conversation-topbar .sv-chat-call-button,
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-conversation-topbar .sv-chat-call-button,
body.messages-conversation-open #messagesScreen .message-conversation-topbar .sv-chat-voice-call-button,
body.messages-screen-mode.messages-conversation-open #messagesScreen .message-conversation-topbar .sv-chat-voice-call-button{
 flex:0 0 auto!important;width:auto!important;min-width:0!important;min-height:44px!important;height:44px!important;margin:0!important;padding:8px 10px!important;
 border:1px solid #78a7f0!important;border-radius:10px!important;background:#10233f!important;color:#fff!important;font-size:13px!important;font-weight:800!important;
 white-space:nowrap!important;box-shadow:0 4px 12px rgba(16,35,63,.13)!important;
}

/* Subscription Test Lab layout: isolated entry screen; it hands off to the actual provider tools. */
#subscriptionTestApp:not(.hidden){display:block!important;position:fixed!important;inset:0!important;z-index:2147483500!important;width:100vw!important;height:100dvh!important;min-height:100dvh!important;box-sizing:border-box!important;overflow-y:auto!important;overflow-x:hidden!important;overscroll-behavior:contain!important;background:#f3f7fc!important;color:#172b47!important;padding:calc(12px + env(safe-area-inset-top)) 14px calc(22px + env(safe-area-inset-bottom))!important}
body.subscription-test-screen-mode{overflow:hidden!important;background:#f3f7fc!important}
body.subscription-test-screen-mode .top,body.subscription-test-screen-mode .bottom-tabbar{display:none!important}
.sv-subtest-shell{width:min(100%,1120px);margin:0 auto;padding-bottom:18px}
.sv-subtest-topbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:0 0 16px}
.sv-subtest-back{border:1px solid #c9d9ef!important;border-radius:12px!important;min-height:42px!important;padding:9px 13px!important;background:#fff!important;color:#173c68!important;font-size:13px!important;font-weight:800!important}
.sv-subtest-mode{display:inline-flex;align-items:center;gap:7px;padding:8px 11px;border:1px solid #c8dbf4;border-radius:999px;background:#eaf3ff;color:#1e4c80;font-size:10px;font-weight:900;letter-spacing:.7px}
.sv-subtest-mode i{width:7px;height:7px;border-radius:50%;background:#179a82}
.sv-subtest-hero{padding:clamp(22px,4vw,38px);border-radius:24px;background:radial-gradient(ellipse at 100% 0%,#3b78c766,transparent 38%),linear-gradient(125deg,#091a33,#123a69 68%,#1a548d);color:#fff}
.sv-subtest-eyebrow{display:block;color:#a8ceff;font-size:10px;font-weight:900;letter-spacing:2px;text-transform:uppercase}
.sv-subtest-hero h1{margin:9px 0 8px;font-size:clamp(27px,5vw,40px);line-height:1.12;color:#fff}
.sv-subtest-hero p{max-width:760px;margin:0;color:#d7e6fa;font-size:14px;line-height:1.65}
.sv-subtest-notice{margin:14px 0;padding:13px 15px;border:1px solid #cfe0f4;border-radius:14px;background:#eaf3ff;color:#244b78;font-size:12px;line-height:1.6}
.sv-subtest-notice strong{color:#173c68}
.sv-subtest-plan-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:16px}
.sv-subtest-plan{display:flex;flex-direction:column;min-width:0;padding:20px;border:1px solid #dbe6f4;border-radius:19px;background:#fff;box-shadow:0 8px 24px #12375d0a}
.sv-subtest-plan-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.sv-subtest-plan h2{margin:0;color:#153a67;font-size:20px;line-height:1.25}
.sv-subtest-price{font-size:18px;font-weight:900;color:#153a67;white-space:nowrap}.sv-subtest-price small{display:block;color:#71829b;font-size:10px;font-weight:600;text-align:right}
.sv-subtest-plan p{margin:9px 0;color:#62758f;font-size:12px;line-height:1.55}
.sv-subtest-mini-list{display:grid;gap:7px;flex:1;margin:9px 0 17px;padding:0;list-style:none}
.sv-subtest-mini-list li{display:flex;gap:8px;color:#314c6d;font-size:12px;line-height:1.4}.sv-subtest-mini-list li:before{content:'✓';color:#148a76;font-weight:900}
.sv-subtest-plan-action,.sv-subtest-primary,.sv-subtest-secondary{min-height:43px;padding:10px 14px!important;border-radius:11px!important;font-size:13px!important;font-weight:850!important}
.sv-subtest-plan-action,.sv-subtest-primary{border:1px solid #1959aa!important;background:linear-gradient(110deg,#1c63c7,#377fe0)!important;color:#fff!important}
.sv-subtest-secondary{border:1px solid #cbdcf1!important;background:#fff!important;color:#214f83!important}.sv-subtest-plan-action{width:100%;margin-top:auto}
.sv-subtest-progress{margin-top:10px;color:#72829a;font-size:11px}
.sv-subtest-feature-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.sv-subtest-feature{min-width:0;padding:17px;border:1px solid #dbe6f4;border-radius:17px;background:#fff}
.sv-subtest-feature h3{margin:0 0 6px;color:#193b65;font-size:16px;line-height:1.3}.sv-subtest-feature p{margin:0 0 12px;color:#61758f;font-size:12px;line-height:1.55}
.sv-subtest-feature button{width:100%}.sv-subtest-tier-tag{display:inline-block;margin-top:7px;padding:5px 9px;border-radius:8px;background:#eaf3ff;color:#1e4e86;font-size:10px;font-weight:900}
.sv-subtest-plan-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:16px 0}.sv-subtest-plan-header h2{margin:0;color:#173a66;font-size:clamp(24px,4vw,32px)}
.sv-subtest-lock-note{padding:10px 12px;border:1px dashed #c6d2e0;border-radius:10px;background:#f5f7fa;color:#69788d;font-size:12px}
.sv-subtest-testbar{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:0 0 14px;padding:11px 12px;border:1px solid #8cb6ea;border-radius:13px;background:#e9f3ff;color:#173f70;font-size:12px}
.sv-subtest-testbar strong{font-weight:900}.sv-subtest-testbar select{min-height:36px;max-width:220px;border:1px solid #c5d8f0;border-radius:8px;padding:6px 9px;background:white;color:#173f70}.sv-subtest-testbar button{min-height:36px;border:1px solid #c5d8f0!important;border-radius:8px!important;padding:6px 10px!important;background:white!important;color:#173f70!important;font-size:12px!important;font-weight:800!important}
body.subscription-test-screen-mode #providerPlansCard,body.subscription-test-screen-mode #providerPlansCard *{display:none!important}
body.subscription-test-screen-mode #ownerEditionBar{display:none!important}
/* SANDBOX PROFILE ISOLATION */

#subscriptionTestProfileScreen:not(.hidden){display:block!important;position:fixed!important;inset:0!important;z-index:2147483600!important;width:100vw!important;height:100dvh!important;min-height:100dvh!important;box-sizing:border-box!important;overflow-y:auto!important;overflow-x:hidden!important;overscroll-behavior:contain!important;background:#f3f7fc!important;color:#172b47!important;padding:calc(12px + env(safe-area-inset-top)) 14px calc(22px + env(safe-area-inset-bottom))!important}
.sv-subtest-profile-hero{display:flex;flex-direction:column;align-items:flex-start;gap:10px;margin:0 0 14px;padding:clamp(22px,4vw,34px);border-radius:22px;background:linear-gradient(125deg,#091a33,#123a69 68%,#1a548d);color:#fff}
.sv-subtest-profile-hero h1{margin:2px 0 0;color:#fff;font-size:clamp(27px,5vw,38px);line-height:1.15;overflow-wrap:anywhere}
.sv-subtest-profile-hero p{margin:0;color:#d7e6fa;font-size:14px;line-height:1.5}
.sv-subtest-profile-card{margin:14px 0;padding:clamp(16px,3vw,25px);border:1px solid #dbe6f4;border-radius:20px;background:#fff;box-shadow:0 10px 30px #12375d0a}
.sv-subtest-profile-section+.sv-subtest-profile-section{margin-top:24px;padding-top:22px;border-top:1px solid #e4edf7}
.sv-subtest-profile-section h2{margin:5px 0 13px;color:#153a67;font-size:23px}
.sv-subtest-empty-portfolio{display:flex;align-items:center;justify-content:center;min-height:120px;padding:22px;border:1px dashed #b6cae3;border-radius:15px;background:#f7faff;color:#637892;font-size:13px;text-align:center}
.sv-subtest-test-portfolio-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(115px,1fr));gap:10px;margin:12px 0}
.sv-subtest-test-portfolio-item{min-width:0;padding:8px;border:1px solid #d7e4f4;border-radius:12px;background:#f8fbff;overflow:hidden}
.sv-subtest-test-portfolio-item img{display:block;width:100%;height:100px;object-fit:cover;border-radius:8px;background:#e9f1fc}
.sv-subtest-test-portfolio-item strong{display:block;margin-top:7px;font-size:11px;overflow-wrap:anywhere;color:#1e416d}
.sv-subtest-test-portfolio-item small{display:block;margin-top:4px;color:#6a7e96;font-size:10px}
.sv-subtest-file-label{display:block;margin:14px 0 7px;color:#2d4766;font-size:12px;font-weight:850}
#svTestPortfolioFiles{display:block;width:100%;box-sizing:border-box;padding:12px;border:1px dashed #b6cae3;border-radius:11px;background:#f7faff;color:#284b74;font-size:12px}

/* Style the native picker control to match Skillvaya while retaining the actual system file chooser. */
#svTestPortfolioFiles::file-selector-button,#svTestPortfolioFiles::-webkit-file-upload-button{-webkit-appearance:none;appearance:none;margin:0 12px 0 0;padding:10px 15px;min-height:42px;border:1px solid #1959aa;border-radius:10px;background:linear-gradient(110deg,#1c63c7,#377fe0);color:#fff;font-family:inherit;font-size:13px;font-weight:850;line-height:1.2;cursor:pointer}
#svTestPortfolioFiles::file-selector-button:hover,#svTestPortfolioFiles::-webkit-file-upload-button:hover{background:linear-gradient(110deg,#174f9f,#286ac4)}
#svTestPortfolioFiles::file-selector-button:focus-visible,#svTestPortfolioFiles::-webkit-file-upload-button:focus-visible{outline:3px solid #9fc5ff;outline-offset:2px}
@media(max-width:640px){.sv-subtest-profile-hero{padding:22px 18px;border-radius:18px}.sv-subtest-test-portfolio-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}

@media(max-width:640px){.sv-subtest-plan-grid,.sv-subtest-feature-grid{grid-template-columns:1fr}.sv-subtest-plan{padding:16px}.sv-subtest-hero{border-radius:18px;padding:22px 18px}.sv-subtest-plan-header{margin:14px 0}.sv-subtest-testbar select{max-width:100%;flex:1 1 160px}}


/* Subscription feature comparison: consistent with Skillvaya's navy, white and light-blue system. */
.sv-plan-feature-list{list-style:none;display:grid;gap:7px;margin:12px 0 17px;padding:0;text-align:left}
.sv-plan-feature-list li{display:flex;align-items:flex-start;gap:8px;color:#435c79;font-size:12px;line-height:1.45}
.sv-plan-feature-list li:before{content:'✓';display:inline-grid;place-items:center;flex:0 0 17px;width:17px;height:17px;margin-top:1px;border-radius:50%;background:#e6f2ff;color:#175da3;font-size:11px;font-weight:900}
.price{display:flex;flex-direction:column}
.price .sv-plan-feature-list{flex:1}
.sv-growth-public-content{display:grid;gap:13px;margin:18px 0}
.sv-growth-public-content:empty{display:none;margin:0}
.sv-growth-public-banner{padding:16px 18px;border:1px solid #cfe0f6;border-radius:15px;background:linear-gradient(120deg,#edf5ff,#fff);color:#183f70}
.sv-growth-public-banner span{display:block;color:#2161ad;font-size:9px;font-weight:900;letter-spacing:1.2px}
.sv-growth-public-banner strong{display:block;margin:4px 0;color:#153a67;font-size:17px}
.sv-growth-public-banner p{margin:0;color:#4c6481;font-size:12px;line-height:1.55}
.sv-growth-public-section{padding:16px;border:1px solid #d9e7f7;border-radius:16px;background:#fff;box-shadow:0 7px 22px rgba(16,35,63,.05)}
.sv-growth-public-section>h3{margin:0 0 12px;color:#102b4c;font-size:18px}
.sv-growth-public-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.sv-growth-public-card{min-width:0;padding:13px;border:1px solid #dce8f6;border-radius:12px;background:#f8fbff}
.sv-growth-public-card h4{margin:0 0 6px;color:#153a67;font-size:15px;overflow-wrap:anywhere}
.sv-growth-public-card p{margin:6px 0;color:#5c708a;font-size:12px;line-height:1.5;overflow-wrap:anywhere}
.sv-growth-public-price{color:#174f8f;font-weight:900;font-size:17px}
.sv-growth-public-code{display:inline-block;padding:5px 8px;border-radius:7px;background:#e5f1ff;color:#174f8f;font-size:11px;font-weight:900;letter-spacing:.5px}
.sv-growth-public-actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}
.sv-growth-public-actions button{border:0;border-radius:9px;padding:9px 11px;background:#10233f;color:#fff;font-size:12px;font-weight:800}
.sv-growth-public-actions button:hover{background:#1b4a7d}
.sv-growth-public-note{margin:10px 0 0;color:#6a7f98;font-size:11px;line-height:1.5}
@media(max-width:560px){.sv-plan-feature-list li{font-size:11px}.sv-growth-public-section{padding:13px}.sv-growth-public-grid{grid-template-columns:1fr}.sv-growth-public-card{padding:12px}}

.sv-launch-gate{position:fixed;inset:0;z-index:9998;display:none;align-items:center;justify-content:center;padding:22px;background:radial-gradient(ellipse at 85% 15%,#1b5b8550,transparent 42%),linear-gradient(145deg,#071426,#102b49);color:#f4f8ff}.sv-launch-card{width:min(100%,440px);padding:clamp(24px,6vw,38px);border:1px solid #8ab8e955;border-radius:24px;background:#0b1d33f5;box-shadow:0 25px 80px #0006;text-align:center}.sv-launch-mark{width:64px;height:64px;margin:0 auto 16px;border-radius:18px;display:grid;place-items:center;background:#143e5c;border:1px solid #42d3d077;color:#42d3d0;font-size:29px;font-weight:900}.sv-launch-card h1{margin:0 0 9px;color:#fff;font-size:clamp(27px,6vw,36px);line-height:1.12}.sv-launch-card p{margin:0 auto 24px;max-width:340px;color:#cadbed;line-height:1.6}.sv-launch-actions{display:grid;grid-template-columns:1fr;gap:11px}.sv-launch-actions button{min-height:50px;border-radius:12px;font-weight:800;font-size:15px;padding:12px 16px}.sv-launch-signin{background:#2365d8;border:1px solid #6ea1f3;color:#fff}.sv-launch-create{background:#dbeafe;border:1px solid #b9d6ff;color:#10233f}.sv-launch-note{display:block;margin-top:17px;color:#9fb7d1;font-size:12px;line-height:1.5}@media(min-width:380px){.sv-launch-actions{grid-template-columns:1fr 1fr}}
/* RELEASE 1.3.5 / code 36: persistent Skillvaya screen headers and readable plan cards. */
header.top{position:fixed!important;top:0!important;left:0!important;right:0!important;width:100%!important;z-index:10000!important;isolation:isolate}
:root{--sv-screen-header-top:76px}
body.provider-detail-mode,body.messages-conversation-open,body.subscription-test-screen-mode{--sv-screen-header-top:0px}
#providerStudioHeading{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:900!important;display:flex!important;align-items:center!important;min-height:76px!important;margin:0 0 14px!important;padding:14px 18px!important;border:1px solid #244c80!important;border-radius:0 0 15px 15px!important;background:linear-gradient(112deg,#102f60 0%,#174f86 68%,#2365d8 100%)!important;color:#fff!important;box-shadow:0 8px 22px #102f6026!important}
#providerStudioHeading h2{color:#fff!important;font-size:clamp(22px,4vw,29px)!important;line-height:1.2!important;margin:0!important}
#providerStudioHeading p,#providerStudioHeading .muted{color:#e1edff!important;margin:4px 0 0!important;font-size:12px!important}
.category-screen-head,.message-conversation-topbar,.sv-subtest-topbar{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:900!important;background:linear-gradient(112deg,#102f60,#174f86)!important;color:#fff!important;border-radius:0 0 13px 13px!important;padding:11px 13px!important;box-shadow:0 7px 20px #102f6024!important}
.category-screen-head h2,.message-conversation-topbar h1,.message-conversation-topbar h2{color:#fff!important}
.category-screen-head .muted{color:#e1edff!important}.category-screen-head .category-back{background:#fff!important;color:#174578!important}
.destination-hero,.sv-workstation-hero,.sv-subtest-profile-hero{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:850!important;border-radius:0 0 16px 16px!important;box-shadow:0 8px 22px #102f6020!important}
#providerDetailScreen>.ghost{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:900!important}
#plans{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:12px!important;align-items:stretch!important}
#plans>.muted{grid-column:1/-1!important;margin:0 0 2px!important;line-height:1.55!important}
#plans>.price{display:flex!important;flex-direction:column!important;min-width:0!important;height:100%!important;padding:16px!important;border:1px solid #d7e5f7!important;border-radius:15px!important;background:#fff!important;box-shadow:0 5px 18px #17365d0a!important;overflow-wrap:anywhere!important}
#plans>.price.featured{border:2px solid #2365d8!important;background:linear-gradient(145deg,#fff,#f0f6ff)!important}
#plans>.price h3{color:#143c70!important;font-size:18px!important;line-height:1.25!important;margin:0 0 8px!important}
#plans>.price .amount{color:#164f9a!important;font-size:clamp(22px,4vw,28px)!important;line-height:1.2!important;overflow-wrap:anywhere!important}
#plans>.price .amount .tiny{font-size:12px!important}#plans>.price p{line-height:1.5!important}
#plans>.price .sv-plan-feature-list{flex:1 0 auto!important}
#plans>.price button{width:100%!important;min-height:44px!important;margin-top:12px!important;background:linear-gradient(110deg,#1c63c7,#377fe0)!important;color:#fff!important}
#providerPlansCard>h3{color:#143c70!important;font-size:22px!important}
#providerPlansCard>label{display:block!important;color:#234d7b!important;font-weight:800!important;margin:10px 0 4px!important}
#billing{display:block!important;width:100%!important;min-height:46px!important;border:1px solid #b8d0ed!important;background:#f7fbff!important;color:#153a67!important;font-weight:700!important}
@media(max-width:560px){#plans{grid-template-columns:minmax(0,1fr)!important}#providerStudioHeading{min-height:68px!important;padding:12px 14px!important}#plans>.price{padding:15px!important}}


/* Account, contacts and other destinations that intentionally hide the global masthead. */
body.account-screen-mode,body.messages-screen-mode,body.provider-screen-mode{--sv-screen-header-top:0px}
#settings .profile-heading{position:sticky!important;top:0!important;z-index:950!important;margin:0 -2px 14px!important;padding:13px 14px!important;border:1px solid #244c80!important;border-radius:0 0 14px 14px!important;background:linear-gradient(112deg,#102f60,#174f86 70%,#2365d8)!important;color:#fff!important;box-shadow:0 8px 22px #102f6026!important}
#settings .profile-heading h2,#settings .profile-heading .account-eyebrow{color:#fff!important}
#settings .profile-heading p{color:#e1edff!important}
#messagesScreen .messages-app-header{position:sticky!important;top:0!important;z-index:950!important;background:linear-gradient(112deg,#102f60,#174f86 70%,#2365d8)!important;color:#fff!important;box-shadow:0 8px 22px #102f6026!important}
#messagesScreen .messages-app-header h1,#messagesScreen .messages-app-header p{color:#fff!important}
#teamAssignmentsScreen>header,#teamAssignmentsScreen>.sectionhead,#teamAssignmentsScreen>.sv-subtest-topbar{position:sticky!important;top:0!important;z-index:950!important;background:linear-gradient(112deg,#102f60,#174f86)!important;color:#fff!important}
#svWorkstationToolScreen .sv-workstation-tool-screen>header,#svWorkstationToolScreen .sv-workstation-tool-screen>.sectionhead{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:900!important;background:linear-gradient(112deg,#102f60,#174f86)!important;color:#fff!important}
#terms .card>h2{position:sticky!important;top:var(--sv-screen-header-top,76px)!important;z-index:850!important;margin:0 -17px 14px!important;padding:14px 17px!important;border-radius:0 0 12px 12px!important;background:linear-gradient(112deg,#102f60,#174f86)!important;color:#fff!important}

/* SV57-ACCOUNT-HEADER-01: keep the Account identity heading pinned within its scroll viewport. */
body.account-screen-mode #settings .profile-heading{position:fixed!important;top:8px!important;left:14px!important;right:14px!important;width:auto!important;z-index:12000!important;background:linear-gradient(115deg,#102f60,#174f86 72%,#2365d8)!important;color:#fff!important;border-radius:14px!important;padding:14px!important;margin:0 0 14px!important;box-shadow:0 8px 22px #102f6026!important;isolation:isolate!important}
body.account-screen-mode #settings .profile-heading h2,body.account-screen-mode #settings .profile-heading p,body.account-screen-mode #settings .profile-heading .account-eyebrow{color:#fff!important}
/* SV58-CHAT-FOOTER-02: empty and populated conversations share the same bottom-anchored composer. */
body.messages-conversation-open #messagesList{display:block!important;overflow:hidden!important}
body.messages-conversation-open #messagesList .message-conversation-screen{display:flex!important;flex-direction:column!important;height:100%!important;min-height:0!important;max-height:100%!important;overflow:hidden!important}
body.messages-conversation-open #messagesList .message-bubbles{display:flex!important;flex:1 1 auto!important;flex-direction:column!important;min-height:0!important;overflow-y:auto!important}
body.messages-conversation-open #messagesList .message-compose{display:flex!important;flex:0 0 auto!important;position:relative!important;margin-top:auto!important;align-items:flex-end!important}
body.messages-conversation-open #messagesList .message-compose .sv-voice-controls{display:flex!important;flex:0 0 48px!important;width:48px!important;min-width:48px!important}
body.messages-conversation-open #messagesList .message-compose .sv-voice-button{display:inline-flex!important;flex:0 0 48px!important;width:48px!important;min-width:48px!important;max-width:48px!important;min-height:48px!important;align-items:center!important;justify-content:center!important;padding:0!important;font-size:23px!important;white-space:nowrap!important}
@media(max-width:390px){body.messages-conversation-open #messagesList .message-compose .sv-voice-controls,body.messages-conversation-open #messagesList .message-compose .sv-voice-button{flex-basis:44px!important;width:44px!important;min-width:44px!important;max-width:44px!important}}
/* SV75-HEADERS-01: one compact, sticky header standard on every screen - same height, same title size, text kept inside the bar. */
:root{--sv-hdr-bg:linear-gradient(112deg,#102f60,#174f86 70%,#2365d8);--sv-hdr-min:62px;--sv-hdr-title:20px;--sv-hdr-sub:12px}
:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading,#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar):not(#z):not(#z){position:sticky!important;top:var(--sv-screen-header-top,0px)!important;z-index:900!important;box-sizing:border-box!important;min-height:var(--sv-hdr-min)!important;max-height:84px!important;height:auto!important;margin:0 0 12px!important;padding:10px 14px!important;border:0!important;border-radius:0 0 14px 14px!important;background:var(--sv-hdr-bg)!important;color:#fff!important;box-shadow:0 6px 18px #102f6026!important;overflow:hidden!important;text-align:left!important;display:flex!important;gap:0!important}
:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading):not(#z):not(#z){flex-direction:column!important;justify-content:center!important;align-items:stretch!important}
:is(#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar):not(#z):not(#z){flex-direction:row!important;flex-wrap:nowrap!important;align-items:center!important;justify-content:flex-start!important;gap:10px!important}
:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading,#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar):not(#z):not(#z) h1,:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading,#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar):not(#z):not(#z) h2{font-size:var(--sv-hdr-title)!important;line-height:1.2!important;font-weight:800!important;letter-spacing:0!important;margin:0!important;padding:0!important;color:#fff!important;text-shadow:none!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;max-width:100%!important}
:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading,#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar):not(#z):not(#z) p,:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading,#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar):not(#z):not(#z) .muted,:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading,#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar):not(#z):not(#z) .tiny,:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading,#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar):not(#z):not(#z) small{font-size:var(--sv-hdr-sub)!important;line-height:1.3!important;margin:2px 0 0!important;padding:0!important;color:#dce9ff!important;max-width:100%!important;display:-webkit-box!important;-webkit-line-clamp:1!important;-webkit-box-orient:vertical!important;overflow:hidden!important;font-weight:500!important}
:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading,#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar):not(#z):not(#z) :is(.sv-workstation-eyebrow,.sv-subtest-eyebrow,.account-eyebrow,.tag,.sv-workstation-plan,.sv-subtest-tier-tag){display:none!important}
:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading,#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar):not(#z):not(#z)>div:not(.messages-app-mark):not(.conversation-avatar){min-width:0!important;flex:1 1 auto!important}
#terms .card>h2:not(#z):not(#z){position:sticky!important;top:var(--sv-screen-header-top,0px)!important;z-index:900!important;box-sizing:border-box!important;display:block!important;height:var(--sv-hdr-min)!important;min-height:var(--sv-hdr-min)!important;margin:0 0 12px!important;padding:0 14px!important;line-height:var(--sv-hdr-min)!important;border:0!important;border-radius:0 0 14px 14px!important;background:var(--sv-hdr-bg)!important;color:#fff!important;box-shadow:0 6px 18px #102f6026!important;font-size:var(--sv-hdr-title)!important;font-weight:800!important;letter-spacing:0!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}
:is(.sv-subtest-hero,.sv-subtest-profile-hero):not(#z):not(#z){position:relative!important;top:auto!important;box-sizing:border-box!important;margin:0 0 12px!important;padding:12px 14px!important;border-radius:14px!important;background:var(--sv-hdr-bg)!important;color:#fff!important;box-shadow:0 6px 18px #102f6026!important;overflow:hidden!important}
:is(.sv-subtest-hero,.sv-subtest-profile-hero):not(#z):not(#z) h1{font-size:var(--sv-hdr-title)!important;line-height:1.2!important;font-weight:800!important;letter-spacing:0!important;margin:0!important;color:#fff!important;overflow-wrap:anywhere!important}
:is(.sv-subtest-hero,.sv-subtest-profile-hero):not(#z):not(#z) p{font-size:var(--sv-hdr-sub)!important;line-height:1.35!important;margin:3px 0 0!important;color:#dce9ff!important}
:is(.sv-subtest-hero,.sv-subtest-profile-hero):not(#z):not(#z) :is(.sv-subtest-eyebrow,.sv-subtest-tier-tag){display:none!important}
:is(.category-back,#accountSubspaceBack,.sv-subtest-back):not(#z):not(#z){font-size:0!important;line-height:0!important;flex:0 0 40px!important;width:40px!important;min-width:40px!important;height:40px!important;min-height:40px!important;padding:0!important;margin:0!important;border-radius:12px!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;background:#fff!important;color:#174578!important;border:0!important}
:is(.category-back,#accountSubspaceBack,.sv-subtest-back):not(#z):not(#z)::before{content:"\2190";font-size:20px;line-height:1;font-weight:800}
#categoryScreenSort:not(#z):not(#z){flex:0 1 132px!important;max-width:132px!important;min-width:0!important;min-height:38px!important;margin-left:auto!important;padding:6px 8px!important;font-size:13px!important}
.sv-subtest-topbar:not(#z):not(#z) .sv-subtest-mode{flex:0 1 auto!important;min-width:0!important;max-width:60%!important;font-size:10px!important;padding:6px 10px!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}
#messagesScreen .messages-app-header:not(#z):not(#z) .messages-app-mark{flex:0 0 38px!important;width:38px!important;height:38px!important;font-size:13px!important}
#messagesScreen .messages-app-header:not(#z):not(#z) .messages-online-dot{flex:0 0 auto!important;margin-left:auto!important}
#settings .profile-heading:not(#z):not(#z) img{width:42px!important;height:42px!important;flex:0 0 42px!important;border-width:2px!important;box-shadow:none!important}
#settings .profile-heading:not(#z):not(#z):after{display:none!important}
body.account-screen-mode #settings .profile-heading:not(#z):not(#z){position:fixed!important;left:0!important;right:0!important;top:var(--sv-screen-header-top,0px)!important;width:auto!important;margin:0!important;z-index:12000!important;border-radius:0 0 14px 14px!important}
body.account-screen-mode main.wrap:not(#z):not(#z){padding-top:calc(var(--sv-hdr-min) + 14px)!important}
#accountSubspace:not(#z):not(#z){padding:0 0 calc(24px + env(safe-area-inset-bottom))!important}
#accountSubspace .account-subspace-content:not(#z):not(#z){padding:0 12px!important}
:is(#jobsCard,#favoritesCard,#messagesCard).account-subspace-card:not(#z):not(#z){top:calc(var(--sv-hdr-min) + 12px)!important}
#messagesScreen .messages-app-header:not(#z):not(#z){margin-top:-1px!important}
#providerDetailScreen>.ghost:not(#z):not(#z){position:sticky!important;top:var(--sv-screen-header-top,0px)!important;z-index:900!important;box-sizing:border-box!important;display:flex!important;align-items:center!important;justify-content:flex-start!important;width:100%!important;min-height:56px!important;margin:0 0 12px!important;padding:0 14px!important;border:0!important;border-radius:0 0 14px 14px!important;background:var(--sv-hdr-bg)!important;color:#fff!important;font-size:15px!important;font-weight:800!important;box-shadow:0 6px 18px #102f6026!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}
@media(max-width:800px){
header.top:not(#z):not(#z) .studio-header-tagline{display:none!important}
header.top:not(#z):not(#z) .nav{min-height:62px!important;padding-top:8px!important;padding-bottom:8px!important;flex-wrap:nowrap!important}
header.top:not(#z):not(#z) .brandlock{min-width:0!important}
header.top:not(#z):not(#z) .brand{font-size:22px!important;line-height:1.1!important}
header.top:not(#z):not(#z) .studio-header-subtitle{font-size:12px!important;line-height:1.2!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}
:is(#providerStudioHeading,.destination-hero,.sv-workstation-hero,.sv-tool-heading,#settings .profile-heading,#messagesScreen .messages-app-header,.category-screen-head,#accountSubspace .account-subspace-top,.sv-subtest-topbar,#providerDetailScreen>.ghost,#terms .card>h2):not(#z):not(#z){width:100vw!important;max-width:100vw!important;margin-left:calc(50% - 50vw)!important;margin-right:0!important}
}
@media(max-width:380px){:root{--sv-hdr-title:18px;--sv-hdr-sub:11px}}
</style><style id="svRtlCss">/* SV82-I18N-FIT: longer words in other languages wrap instead of widening the phone screen */html[lang]:not([lang=en]),html[lang]:not([lang=en]) body{overflow-x:hidden;max-width:100%}html[lang]:not([lang=en]) .nav{flex-wrap:nowrap}html[lang]:not([lang=en]) header.top .brandlock{flex:1 1 0!important;min-width:0!important;max-width:calc(100% - 52px)}html[lang]:not([lang=en]) .studio-header-subtitle{font-size:12px!important}html[lang]:not([lang=en]) .design-section-heading,html[lang]:not([lang=en]) .sectionhead{flex-wrap:wrap}html[lang]:not([lang=en]) .design-section-heading h2,html[lang]:not([lang=en]) .sectionhead h2{white-space:normal!important;min-width:0}html[lang]:not([lang=en]) .design-section-heading .ghost{white-space:normal!important}html[lang]:not([lang=en]) .bottom-tabbar span{min-width:0;max-width:100%;overflow-wrap:anywhere}html[lang]:not([lang=en]) .brandlock{min-width:0;flex:1 1 auto}html[lang]:not([lang=en]) .brandlock>div{min-width:0}html[lang]:not([lang=en]) .studio-header-subtitle,html[lang]:not([lang=en]) .studio-header-tagline{white-space:normal!important;overflow-wrap:anywhere}html[lang]:not([lang=en]) #toggleDesignCategories{white-space:normal!important;max-width:42vw;text-align:center}html[lang]:not([lang=en]) .bottom-tabbar button{min-width:0;overflow:hidden}html[lang]:not([lang=en]) .bottom-tabbar button>span:not(.bottom-tab-icon){display:block;max-width:100%;font-size:clamp(9px,2.5vw,12px);line-height:1.1;overflow-wrap:anywhere;hyphens:auto;text-align:center}html[lang]:not([lang=en]) button,html[lang]:not([lang=en]) .tag,html[lang]:not([lang=en]) label,html[lang]:not([lang=en]) h1,html[lang]:not([lang=en]) h2,html[lang]:not([lang=en]) h3{overflow-wrap:anywhere}/* SV82-I18N right-to-left (Arabic) */body.sv-rtl{text-align:right}body.sv-rtl .cat,body.sv-rtl .conversation-list-item,body.sv-rtl .contact-method-card,body.sv-rtl nav button{text-align:right}body.sv-rtl .message-row.mine{justify-content:flex-start}body.sv-rtl .message-row.theirs{justify-content:flex-end}body.sv-rtl input,body.sv-rtl textarea,body.sv-rtl select{text-align:right}body.sv-rtl input[type=email],body.sv-rtl input[type=tel],body.sv-rtl input[type=url]{direction:ltr;text-align:right}</style></head><body>
<div id="svSplash" class="sv-splash" role="status" aria-live="polite"><div class="sv-splash-brand">Skillvaya</div><div class="sv-splash-caption">Digital &amp; Creative Studio</div><div class="sv-loading-dots" aria-hidden="true"><i></i><i></i><i></i></div></div>
<div id="firstLaunchGate" class="sv-launch-gate" role="dialog" aria-modal="true" aria-labelledby="svLaunchTitle"><div class="sv-launch-card"><div class="sv-launch-mark" aria-hidden="true">SV</div><h1 id="svLaunchTitle">Welcome to Skillvaya</h1><p>Find trusted professionals, connect with service providers, or create your profile to get started.</p><div class="sv-launch-actions"><button type="button" class="sv-launch-signin" onclick="enterLaunchAuth('signin')">Sign in</button><button type="button" class="sv-launch-create" onclick="enterLaunchAuth('signup')">Create profile</button></div><small class="sv-launch-note">Customer accounts are free. You can browse services and choose your next step after signing in.</small></div></div>
<header class="top"><div class="wrap nav"><div class="brandlock"><img class="sv-logo" src="/sv-logo.jpeg" alt="SV Skillvaya logo"><div><div class="brand">Skillvaya</div><div class="studio-header-subtitle">Digital &amp; Creative Studio</div><div class="tiny studio-header-tagline">Professional. Simple. Powerful.</div></div></div><button type="button" id="svNotificationBell" class="sv-notification-bell" aria-label="Notifications" title="Notifications"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"></path><path d="M10 21h4"></path></svg><span class="sv-notification-badge" id="svNotificationBadge" hidden>0</span></button></div></header>
<section id="hero" class="hero"><div class="wrap"><span class="tag" style="background:#d9ebff;color:#174c91">WELCOME TO SKILLVAYA</span><h1>Find the perfect service for your needs.</h1><p>Search services, explore categories, and connect with trusted professionals near you.</p><div class="search"><input id="q" placeholder="Search plumbers, lawyers, private doctors…"><input id="area" placeholder="Town or suburb"><button class="primary" onclick="searchDirectory()">Search</button></div></div></section><section id="designPromoCard" class="design-promo-card wrap" aria-label="Featured Skillvaya studio"><div class="design-promo-icon" aria-hidden="true">✦</div><div class="design-promo-copy"><strong>Need something creative?</strong><span>Get a quote from Skillvaya Digital &amp; Creative Studio.</span></div><button type="button" class="design-promo-button" onclick="view('contact')">Contact Us <span aria-hidden="true">›</span></button></section><div class="hero-actions-wrap"><div class="wrap"><div class="hero-actions" aria-label="Public directory"><button id="nav-customer" class="active" onclick="view('customer')">Find a service provider</button></div></div></div>
<main class="wrap">
<section id="designCategoryPanel" class="design-category-panel card" aria-labelledby="designCategoryTitle">
<div class="design-section-heading"><div><span class="design-eyebrow">EXPLORE SKILLVAYA</span><h2 id="designCategoryTitle">Service categories</h2><p class="muted">Find the right specialist for your next project.</p></div><button type="button" class="ghost" id="toggleDesignCategories" onclick="toggleDesignCategories()">View all</button></div>
<div id="designCategoryTiles" class="design-category-tiles" aria-live="polite"><div class="design-category-loading">Loading service categories…</div></div>
</section>
<section id="customer" class="layout"><aside class="panel"><h3>All service categories</h3><select id="categories" aria-label="Choose a service category" style="width:100%;margin-top:12px"><option value="All categories">All categories</option></select></aside><section><div class="sectionhead"><div><h2 id="resTitle">Find a service</h2><span class="muted tiny" id="count"></span></div><select id="sort" style="max-width:180px" onchange="loadBusinesses()"><option value="featured">Featured first</option><option value="near">Near me</option><option value="available">Available today</option><option value="rating">Highest rated</option><option value="name">Name A–Z</option></select></div><div id="results" class="results hidden" aria-hidden="true"></div><div class="card" id="svFutureChatCard" style="margin-top:18px;border:1px solid #1d4f7c;background:linear-gradient(135deg,#0d2440,#14406b);color:#eef6ff"><div style="display:flex;gap:14px;align-items:flex-start"><div style="font-size:34px;line-height:1" aria-hidden="true">💬</div><div style="flex:1;min-width:0"><div style="font-size:12px;font-weight:800;letter-spacing:.08em;color:#7fe3f0;text-transform:uppercase">Coming soon</div><h2 style="margin:2px 0 6px;color:#fff">Future Chat</h2><p style="margin:0 0 12px;color:#cfe0f5">Skillvaya's own messenger. Chat, call and share with family, friends and the providers you use, all in one place.</p><button type="button" id="svFcNotifyBtn" onclick="svFutureChatNotify()" style="background:#19c3d6;color:#04202a;border:0;border-radius:12px;padding:10px 16px;font-weight:800;cursor:pointer">Notify me when it launches</button><div id="svFcState" class="tiny" style="margin-top:8px;color:#a9f0f8"></div></div></div></div><div class="card" id="platformRatingCard" style="margin-top:18px;border:1px solid #d7e5f7;background:linear-gradient(135deg,#fff,#f1f7ff)"><h2 style="margin:0 0 4px">Rate Skillvaya</h2><p class="muted" style="margin:0 0 8px">Tell us how we're doing. Your rating is for the Skillvaya website and service, not an individual provider.</p><div id="platformRatingSummary" class="muted tiny">Loading Skillvaya ratings…</div><div id="platformRatingStars" aria-label="Rate Skillvaya from one to five stars" style="display:flex;gap:4px;flex-wrap:wrap;margin-top:6px"></div><div id="platformRatingMsg" class="muted tiny" aria-live="polite"></div></div></section></section>

<section id="categoryScreen" class="category-screen hidden"><div class="category-screen-head"><button type="button" class="category-back" onclick="backToCategories()">← Back to all service providers</button><div><h2 id="categoryScreenTitle" style="margin:0">Service providers</h2><span class="muted tiny" id="categoryScreenCount"></span></div><select id="categoryScreenSort" style="max-width:180px;margin-left:auto" onchange="document.getElementById('sort').value=this.value;loadBusinesses()"><option value="featured">Featured first</option><option value="near">Near me</option><option value="available">Available today</option><option value="rating">Highest rated</option><option value="name">Name A–Z</option></select></div><div id="categoryScreenResults" class="category-results"></div></section>
<section id="servicesTabScreen" class="hidden app-destination">
 <div class="sv-workstation">
  <header class="sv-workstation-hero"><span class="sv-workstation-eyebrow">SERVICE PROVIDER WORKSPACE</span><h1>Your Service Workstation</h1><p>Manage customer requests, quotations, your profile and the tools included with your verified provider plan. Customers keep free access to Home and Contacts.</p><span id="svWorkstationPlan" class="sv-workstation-plan">Checking provider plan…</span></header>
  <div class="sv-workstation-scroll"><div id="svWorkstationStatus" class="sv-workstation-banner" aria-live="polite">Loading verified plan entitlements…</div>
  <div id="svWorkstationTools" class="sv-workstation-tools"><div class="sv-workstation-banner">Loading your tools…</div></div>
  <div id="svWorkstationActivity" class="sv-workstation-activity"><h3>Workspace guide</h3><p class="sv-tool-muted">Tools open as separate screens. Your existing customer chats stay in Contacts.</p></div></div>
 </div>
</section>
<section id="svWorkstationToolScreen" class="hidden app-destination"><div id="svWorkstationToolContent" class="sv-workstation-tool-screen"></div></section>

<section id="contactUsScreen" class="hidden app-destination"><div class="destination-hero contact-destination-hero"><span class="tag">WE’RE HERE TO HELP</span><h1>Contact Skillvaya</h1><p>Questions about the platform, your account, a listing, billing or safety? Reach our team directly.</p></div><div class="contact-method-grid"><a class="contact-method-card" href="mailto:skillvaya@gmail.com"><span class="contact-method-icon">✉</span><span><strong>Email our team</strong><small>skillvaya@gmail.com</small></span><b>›</b></a><a class="contact-method-card" href="https://wa.me/27837874569" target="_blank" rel="noopener"><span class="contact-method-icon">◉</span><span><strong>WhatsApp</strong><small>Chat with Skillvaya</small></span><b>›</b></a><a class="contact-method-card" href="tel:+27837874569"><span class="contact-method-icon">☎</span><span><strong>Call us</strong><small>+27 83 787 45 69</small></span><b>›</b></a></div><div class="destination-card contact-form-card"><h2>Send us an enquiry</h2><p class="muted">Complete the form and your email app will open with the message ready to send.</p><form id="platformContactForm" onsubmit="submitPlatformContact(event)"><label for="platformContactName">Your name</label><input id="platformContactName" name="name" autocomplete="name" required maxlength="120"><label for="platformContactEmail">Your email</label><input id="platformContactEmail" name="email" type="email" autocomplete="email" required maxlength="200"><label for="platformContactTopic">What can we help with?</label><select id="platformContactTopic" name="topic"><option>General enquiry</option><option>Account or profile</option><option>Contacting a service provider</option><option>Billing or subscription</option><option>Safety or report</option><option>Technical problem</option></select><label for="platformContactMessage">Message</label><textarea id="platformContactMessage" name="message" rows="5" minlength="5" maxlength="4000" required placeholder="Tell us how we can help…"></textarea><button class="primary" type="submit">Continue to email</button><p id="platformContactStatus" class="muted" aria-live="polite"></p></form></div></section>
<section id="providerDetailScreen" class="hidden" style="padding:20px 0 110px;max-width:900px;margin:auto"><button type="button" class="ghost" onclick="closeProviderDetail()">← Back to service providers</button><div id="providerDetailContent" style="margin-top:14px"></div></section>
<section id="provider" class="hidden" style="padding:0 0 110px"><div class="sectionhead" id="providerStudioHeading"><div><h2>Provider studio</h2><p class="muted">Create your business profile and request an advertising plan.</p></div></div><div class="layout" id="providerStudioLayout" style="padding-top:0"><div id="providerProfileCard" class="hidden" style="width:100%;max-width:100%;margin:0;padding:0;border:0;border-radius:0;box-shadow:none;background:transparent">
<div id="studioBrandPreview" style="overflow:hidden;border-radius:18px;background:#071426;color:#eef6ff;margin:-2px -2px 22px">
<div style="padding:24px 20px;background:radial-gradient(ellipse at 85% 10%,#073d79 0,transparent 50%),linear-gradient(125deg,#06101f,#0b2341);border-bottom:1px solid #183b62">
<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
<div style="width:78px;height:78px;border:3px solid #087cff;border-radius:50%;display:grid;place-items:center;font-size:36px;font-weight:900;color:#1496ff;flex-shrink:0">S</div>
<div style="flex:1;min-width:180px"><div style="font-size:clamp(22px,4vw,32px);font-weight:800;line-height:1.12">Skillvaya</div><div style="font-size:clamp(17px,3vw,24px);font-weight:750;color:#16a4ff">Digital &amp; Creative Studio</div><div style="color:#b9cce8;margin-top:8px;font-size:13px">Ideas&nbsp; · &nbsp;Design&nbsp; · &nbsp;Code&nbsp; · &nbsp;Build&nbsp; · &nbsp;Support</div></div>
<div style="font-size:16px;line-height:1.35;font-weight:650">Your Vision.<br>Our Skills.<br>Real Results.</div>
</div></div>
<div style="padding:18px 16px 20px">
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:22px">
<div style="border:1px solid #294566;border-radius:12px;padding:13px">🔹 <span style="color:#9db8db">Business Type</span><br><strong>Digital &amp; Creative Studio</strong></div>
<div style="border:1px solid #294566;border-radius:12px;padding:13px">📍 <span style="color:#9db8db">Service Area</span><br><strong>Online &amp; Remote</strong></div>
<div style="border:1px solid #294566;border-radius:12px;padding:13px">☎️ <span style="color:#9db8db">Phone / WhatsApp</span><br><strong>+27 83 787 45 69</strong></div>
<div style="border:1px solid #294566;border-radius:12px;padding:13px">✉️ <span style="color:#9db8db">Email</span><br><strong>Skillvaya@gmail.com</strong></div>
</div>
<h3 style="margin:0 0 12px;color:#eef6ff">Our Services</h3>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:9px;margin-bottom:22px">
<div style="border:1px solid #294566;background:#0b1b30;border-radius:12px;padding:13px 11px;min-height:56px;display:flex;align-items:center;gap:8px"><span style="font-size:20px">✎</span><strong style="font-size:13px">Graphic Design</strong></div><div style="border:1px solid #294566;background:#0b1b30;border-radius:12px;padding:13px 11px;min-height:56px;display:flex;align-items:center;gap:8px"><span style="font-size:20px">◇</span><strong style="font-size:13px">Branding & Identity</strong></div><div style="border:1px solid #294566;background:#0b1b30;border-radius:12px;padding:13px 11px;min-height:56px;display:flex;align-items:center;gap:8px"><span style="font-size:20px">▣</span><strong style="font-size:13px">Web Design</strong></div><div style="border:1px solid #294566;background:#0b1b30;border-radius:12px;padding:13px 11px;min-height:56px;display:flex;align-items:center;gap:8px"><span style="font-size:20px">⌘</span><strong style="font-size:13px">Website Development</strong></div><div style="border:1px solid #294566;background:#0b1b30;border-radius:12px;padding:13px 11px;min-height:56px;display:flex;align-items:center;gap:8px"><span style="font-size:20px">⚙</span><strong style="font-size:13px">Coding & Custom Software</strong></div><div style="border:1px solid #294566;background:#0b1b30;border-radius:12px;padding:13px 11px;min-height:56px;display:flex;align-items:center;gap:8px"><span style="font-size:20px">▯</span><strong style="font-size:13px">Android Apps</strong></div><div style="border:1px solid #294566;background:#0b1b30;border-radius:12px;padding:13px 11px;min-height:56px;display:flex;align-items:center;gap:8px"><span style="font-size:20px">✺</span><strong style="font-size:13px">AI Solutions</strong></div><div style="border:1px solid #294566;background:#0b1b30;border-radius:12px;padding:13px 11px;min-height:56px;display:flex;align-items:center;gap:8px"><span style="font-size:20px">▤</span><strong style="font-size:13px">UI/UX Design</strong></div><div style="border:1px solid #294566;background:#0b1b30;border-radius:12px;padding:13px 11px;min-height:56px;display:flex;align-items:center;gap:8px"><span style="font-size:20px">◉</span><strong style="font-size:13px">Testing & Debugging</strong></div><div style="border:1px solid #294566;background:#0b1b30;border-radius:12px;padding:13px 11px;min-height:56px;display:flex;align-items:center;gap:8px"><span style="font-size:20px">🔧</span><strong style="font-size:13px">IT Support & Troubleshooting</strong></div>
</div>
<h3 style="margin:0 0 8px;color:#eef6ff">About Us</h3>
<p style="color:#d3e0f4;line-height:1.6;margin:0 0 16px">Skillvaya Digital &amp; Creative Studio is a full-service digital solutions provider focused on helping individuals and businesses bring their ideas to life. We combine creativity, technology and practical problem-solving to deliver high-quality, reliable and affordable solutions. Whether you need a stunning design, a professional website, a custom app, or advanced AI solutions, we’ve got you covered. We also offer ongoing support and troubleshooting to keep your systems running smoothly.</p>
<div style="border:1px solid #245184;background:#0b1d33;border-radius:12px;padding:14px;font-weight:700">🎯 Our goal is simple: <span style="color:#16a4ff">Your success is our success.</span></div>
<p style="color:#d3e0f4;line-height:1.6;margin:16px 0 0">Please contact us if you would like any of these services rendered to you.</p>
<button type="button" class="primary" style="width:100%;margin-top:18px" onclick="openStudioEditor()">✎ Edit My Existing Profile</button>
</div></div>
<h3>Manage business details</h3><p class="muted">Your profile design appears above. Use the form below to update the business information saved to Skillvaya.</p><form id="bizForm" class="hidden"><input type="hidden" name="promotion_id"><div class="formgrid"><div id="ownerTaglineField" class="full hidden"><label>Profile tagline</label><input name="tagline" maxlength="160" placeholder="Your Vision. Our Skills. Real Results."></div><div><label>Business / professional name *</label><input name="name" required></div><div><label>Category *</label><select name="category" id="bizCat"></select></div><div><label>Town / service area *</label><input name="area" required></div><div><label>Country *</label><select name="country" class="sv-country-select"></select></div><div><label>Business phone *</label><input name="phone" type="tel" required></div><div><label>WhatsApp number</label><input name="whatsapp" type="tel" placeholder="+…"></div><div><label>Public contact email</label><input name="email" type="email"></div><div><label>Website</label><input name="website" type="url" placeholder="https://…"></div><div class="full"><label>Services description *</label><textarea name="description" required rows="4"></textarea></div><div class="full"><label>Portfolio photos / catalogue images</label><input id="providerPortfolioFiles" class="photo-input-hidden" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" multiple aria-label="Select portfolio photos or PDF catalogue"><button type="button" class="photo-pick-button" onclick="document.getElementById('providerPortfolioFiles').click()">＋ Choose portfolio files</button><small class="muted" style="display:block;margin-top:8px">Opens your device’s file picker. Select photos or a PDF from your phone, tablet, or computer. Maximum 2 MB combined.</small><div id="providerPortfolioPreview" class="photo-file-name" aria-live="polite">No files selected</div><input name="photos" id="providerPhotosData" type="hidden"></div></div><p><button class="primary">Save business profile</button></p></form><div id="bizMsg"></div><div id="providerProfileNotice" class="notice">Choose a plan and complete payment first. Business profile setup unlocks after Skillvaya verifies the payment.</div></div><div class="card" id="providerPlansCard"><h3>Provider subscription plans</h3><p class="muted">Choose your subscription category, then select monthly or annual billing.</p><label for="billing">Choose billing term</label><select id="billing" onchange="drawPlans()"><option value="monthly">Monthly</option><option value="yearly">Yearly — one month free</option></select><p class="muted tiny" style="margin:8px 0 12px">Choose one of the four advertising plans below. Changing the billing term updates the price on every plan.</p><div id="plans"></div><p class="muted tiny">Choose a plan to continue. Android app purchases use Google Play; website purchases use the available website checkout. Access activates only after payment verification.</p></div></div></section>
<section id="account" class="hidden"></section>
<section id="settings" class="hidden" style="padding:25px 0 55px;max-width:920px;margin:auto">
 <div class="card" style="border-radius:20px;padding:clamp(16px,4vw,30px);box-shadow:0 12px 35px #142b4510">
  <div class="profile-heading"><img id="profileHeadingPhoto" alt="Profile picture" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='50' fill='%23e5edf7'/%3E%3Ccircle cx='50' cy='37' r='18' fill='%238aa0bc'/%3E%3Cpath d='M15 95c2-23 17-34 35-34s33 11 35 34' fill='%238aa0bc'/%3E%3C/svg%3E"><div class="profile-heading-copy"><span class="account-eyebrow">SKILLVAYA ACCOUNT</span><h2 id="accountMainTitle">Your account</h2><p id="accountHeroSubtitle">Manage your profile, privacy and preferences in one place.</p></div></div>
   <div class="account-dashboard-links" aria-label="Account sections"><button type="button" class="account-link active" onclick="scrollAccountSection('profileSettingsCard')"><span>👤</span><strong>Profile</strong><small>Your details &amp; photo</small></button><button type="button" class="account-link" onclick="openProviderOnboarding()"><span>🧰</span><strong>Become a Provider</strong><small>Offer your services</small></button><button type="button" class="account-link" onclick="event.preventDefault();event.stopPropagation();showMessagesScreen(true)"><span>💬</span><strong>Chats</strong><small>Providers &amp; conversations</small></button><button type="button" class="account-link" onclick="viewJobs()"><span>📋</span><strong>My jobs</strong><small>Requests &amp; quotes</small></button><button type="button" class="account-link" onclick="viewFavorites()"><span>☆</span><strong>Saved</strong><small>Favourite providers</small></button><button type="button" class="account-link hidden" id="openMyTeamAssignmentsLink" onclick="openMyTeamAssignments()"><span>▣</span><strong>My Team Assignments</strong><small>Jobs assigned to you</small></button><button type="button" class="account-link hidden" id="openSubscriptionTesterLink" onclick="openSubscriptionTestApp()"><span>⌘</span><strong>Subscription Test Lab</strong><small>Test each subscription tier</small></button></div>
  <div id="profileAuthTabs" style="display:flex;gap:10px;margin:18px 0;flex-wrap:wrap"><button id="profileSigninTab" class="primary" type="button" onclick="profileAuthMode('signin')">Sign in</button><button id="profileSignupTab" class="ghost" type="button" onclick="profileAuthMode('signup')">Create profile</button></div>
  <div id="signinPane"><form id="login"><label class="account-field-label">Email</label><input name="email" type="email" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" required><label class="account-field-label">Password</label><input name="password" type="password" autocomplete="current-password" autocapitalize="none" autocorrect="off" spellcheck="false" required><p><label style="display:flex;gap:9px;align-items:flex-start;font-weight:500"><input id="rememberMe" type="checkbox" checked style="width:auto;margin-top:5px;flex:0 0 auto"><span>Remember me on this device — stay signed in until I log out.</span></label></p><p><label style="display:flex;gap:9px;align-items:flex-start;font-weight:500"><input id="loginTerms" name="accept_terms" type="checkbox" required style="width:auto;margin-top:5px;flex:0 0 auto"><span>I have read and agree to the current <a href="/terms" target="_blank" rel="noopener">Skillvaya Terms, Conditions, Rules & Safety</a> and the <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.</span></label></p><button class="primary">Sign in securely</button></form><div id="loginMsg" aria-live="polite"></div></div>
  <div id="signupPane" class="hidden"><form id="signup"><label>Your name</label><input name="name" autocomplete="name" required><label class="account-field-label" for="signupCountry">Country</label><select name="country" id="signupCountry" class="sv-country-select"></select><label class="account-field-label">Email</label><input name="email" type="email" autocomplete="email" autocapitalize="none" autocorrect="off" spellcheck="false" required><label>Phone / WhatsApp (optional)</label><input name="phone" type="tel" autocomplete="tel"><label class="account-field-label">Password (minimum 8 characters)</label><input name="password" type="password" autocomplete="new-password" autocapitalize="none" autocorrect="off" spellcheck="false" minlength="8" required><label class="account-field-label">Confirm password</label><input name="confirm_password" type="password" autocomplete="new-password" autocapitalize="none" autocorrect="off" spellcheck="false" minlength="8" required><label class="account-field-label">Account type</label><select class="account-role-choice" name="role"><option value="customer">Customer — free</option><option value="provider">Service provider</option></select><p class="muted">You can update your picture and personal details after creating your profile.</p><p><label style="display:flex;gap:10px;align-items:flex-start;font-weight:500"><input name="accept_terms" type="checkbox" required style="width:auto;margin-top:5px;flex:0 0 auto"><span>I have read and agree to the <a href="/terms" target="_blank" rel="noopener">Skillvaya Terms, Conditions, Rules & Safety</a> and the <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.</span></label></p><button class="primary">Create my profile</button></form><div id="signupMsg" aria-live="polite"></div></div>
  <div id="profileSettingsCard" class="hidden">
   <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:16px 0"><img id="profilePhotoPreview" class="profile-photo-secondary" alt="Your profile picture" style="width:94px;height:94px;border-radius:50%;object-fit:cover;background:#e9eff7;border:3px solid white;box-shadow:0 0 0 1px #ccd7e5" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='50' fill='%23e5edf7'/%3E%3Ccircle cx='50' cy='37' r='18' fill='%238aa0bc'/%3E%3Cpath d='M15 95c2-23 17-34 35-34s33 11 35 34' fill='%238aa0bc'/%3E%3C/svg%3E"><div><h3 style="margin:0">Your picture</h3><p class="muted" style="margin:5px 0">Choose a JPG, PNG or WebP image (up to 2 MB).</p><div class="photo-picker"><input id="profilePhotoFile" class="photo-input-hidden" type="file" accept="image/*" aria-label="Choose a profile picture"><button id="chooseProfilePhotoButton" type="button" class="photo-pick-button" onclick="document.getElementById('profilePhotoFile').click()">＋ Choose profile picture</button><input id="profileCameraFile" class="photo-input-hidden" type="file" accept="image/*" capture="environment" aria-label="Take a profile picture with the camera"><button id="takeProfilePhotoButton" type="button" class="photo-pick-button" onclick="document.getElementById('profileCameraFile').click()">📷 Take photo</button><span id="profilePhotoFileName" class="photo-file-name">Choose an image or take a photo</span><button id="saveProfilePhotoButton" type="button" class="primary" onclick="saveProfilePhoto()">Upload picture</button></div><div id="photoMsg" aria-live="polite"></div></div></div>
   <h3>Personal details</h3><p id="profileIdentity" class="muted">Your account details</p><button id="editProfileButton" type="button" class="ghost" onclick="setProfileEditing(true)">Edit details</button><form id="profileForm"><label>Full name</label><input name="name" autocomplete="name" required minlength="2" maxlength="120" readonly><label>Phone</label><input name="phone" type="tel" autocomplete="tel" maxlength="40" readonly><p id="profileSaveActions" class="hidden"><button class="primary">Save changes</button><button class="ghost" type="button" onclick="setProfileEditing(false)">Cancel</button></p></form><div id="profileMsg" aria-live="polite"></div>
   <h3>Password & security</h3><p class="muted">Your password is stored as a secure hash, not readable text.</p><form id="passwordForm"><label>Current password</label><input name="current_password" type="password" autocomplete="current-password" required><label>New password (at least 8 characters)</label><input name="new_password" type="password" autocomplete="new-password" minlength="8" required><label>Confirm new password</label><input name="confirm_password" type="password" autocomplete="new-password" minlength="8" required><p><button class="primary">Change password</button></p></form><div id="passwordMsg" aria-live="polite"></div>
   <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:20px"><button class="secondary" type="button" onclick="event.preventDefault();event.stopPropagation();showMessagesScreen(true)">Chats</button><button class="secondary" type="button" onclick="viewJobs()">My Jobs & Quotes</button><button id="workerSideButton" class="primary hidden" type="button" onclick="openWorkerSide()">My Worker Side</button><button class="secondary" type="button" onclick="viewFavorites()">Saved providers</button><button class="danger" type="button" onclick="requestAccountDeletion()">Request account deletion</button><a class="secondary" href="/account-deletion" target="_blank" rel="noopener">Deletion information</a><a class="secondary" href="/privacy">Privacy policy</a><button class="danger" type="button" onclick="logout()">Log out</button></div>
  </div>
 </div>

 <div id="jobsCard" class="card hidden" style="border-radius:18px;margin-top:14px"><h2>My Jobs & Quotes</h2><p class="muted">Send a work request, review a provider's quote, and track the job through completion.</p><div id="jobCreateArea" class="hidden"><form id="jobRequestForm"><label>Service provider</label><select id="jobBusinessId" name="business_id" required></select><label>Job title</label><input name="title" required minlength="3" maxlength="160" placeholder="e.g. Repair a leaking kitchen pipe"><label>Describe the work</label><textarea name="description" required minlength="10" maxlength="4000" rows="3" placeholder="Explain what needs doing, relevant details, and any photos to send in My messages."></textarea><label>Your area / address details (avoid sharing more than needed)</label><input name="area" maxlength="160" placeholder="Suburb or town"><label>Preferred date (optional)</label><input name="preferred_date" maxlength="40" placeholder="e.g. 2026-11-02 or flexible"><label id="svJobBudgetLabel">Budget (optional)</label><input name="budget_rands" type="number" min="0" max="10000000" step="0.01" placeholder="Amount"><p><button class="primary">Send job request</button></p><div id="jobRequestStatus" aria-live="polite"></div></form></div><div id="jobsList" aria-live="polite">Sign in to view jobs and quotes.</div><div id="jobsStatus" aria-live="polite"></div></div><div id="favoritesCard" class="card hidden" style="border-radius:18px;margin-top:14px"><h2>Saved providers</h2><p class="muted">Keep trusted providers handy for your next job.</p><div id="favoritesList" aria-live="polite">Loading saved providers…</div></div>

<div id="customerMarketingPreferenceCard" class="card hidden" style="margin:16px 0;border:1px solid var(--line);border-radius:18px;padding:20px">
 <span class="sv-workstation-eyebrow">OPTIONAL CUSTOMER PREFERENCE</span><h2 style="margin:5px 0 8px">Offers &amp; service announcements</h2>
 <p class="muted">Choose whether providers you contact may send you occasional offers or service announcements through your existing Skillvaya chat. This is optional and can be turned off at any time.</p>
 <label style="display:flex;align-items:flex-start;gap:10px;line-height:1.5"><input id="customerMarketingOptIn" type="checkbox" style="margin-top:4px"><span>Yes, I agree to receive relevant offers and service announcements from providers I have contacted.</span></label>
 <div id="customerMarketingPreferenceStatus" class="sv-tool-status" aria-live="polite"></div><button class="sv-tool-submit" type="button" onclick="saveCustomerMarketingPreference()">Save preference</button>
</div>
</section>
<section id="terms" class="hidden" style="padding:25px 0 55px"><div class="card"><h2>Terms, conditions, rules & safety</h2><p class="muted">Version 1.2 · Effective 21 October 2026. The full current text is also available at <a href="/terms" target="_blank" rel="noopener">Skillvaya Terms & Conditions</a>.</p><div class="notice">By ticking the required agreement box to create an account or sign in, you agree to this current version. Customer browsing/contact is free unless a charge is clearly disclosed before you approve it.</div><h3>1. Agreement and accounts</h3><p>Provide accurate details, protect your login and accept the current terms before creating an account or signing in. Your accepted version and timestamp are recorded.</p><h3>2. Customers and providers</h3><p>Skillvaya is a directory and introduction service; paid placement is not an endorsement. Customers should independently check provider credentials and quotations. Providers must be lawful, honest and suitably qualified for advertised work. Fraud, harassment, misleading listings, unsafe services, unlawful content, privacy abuse and manipulation of ratings, reports or payments are prohibited.</p><h3>3. Paid plans, price changes and taxes</h3><p>Plan, features, billing term, full amount, tax/fees, renewal dates and cancellation terms must be displayed before purchase. Skillvaya may change plan prices in the future. A price change will not retrospectively increase a term already paid for or change its price mid-term. Where legally required, and as a general service commitment, material increases will be communicated in advance—normally at least 30 days before applying to a future renewal—with the new amount and date. You may cancel or not renew before it takes effect. The new price must be displayed before a new purchase or renewal is approved; silence does not authorise an undisclosed charge. Applicable law prevails.</p><h3>4. Payment, renewal and refund</h3><p>All provider-plan payments are made through Google Play. Purchases use prepaid monthly or annual periods and do not renew automatically; a separate purchase is required to extend access. Google Play handles payment, and Skillvaya activates provider benefits only after server-side verification. Sandbox transactions are tests, not real payments. A plan activates only when Google Play confirms the purchase. Unless the checkout clearly states otherwise and you expressly authorise recurring billing, renewals are not automatic. Refunds are subject to checkout disclosures and applicable law; a refund is recorded as completed only on provider confirmation.</p><h3>5. Privacy, moderation and service limits</h3><p>Account, listing, enquiry, complaint, payment-status and technical information may be used to operate the service, protect users and support payment reconciliation. Reasonable safeguards are used, but no service is perfectly secure. Reports are allegations, not findings of guilt. Skillvaya may moderate listings or restrict unsafe or unlawful activity. Nothing excludes rights or remedies that applicable South African law does not allow to be excluded.</p><h3>6. Contact and review</h3><p>Contact <a href="mailto:skillvaya@gmail.com">skillvaya@gmail.com</a> for billing, safety or privacy concerns. This is a working business draft, not legal advice; obtain South African legal review before accepting real customer payments.</p><p><a href="/terms" target="_blank" rel="noopener">Read the full Terms & Conditions (opens separately)</a></p>
<h3>Advertising, owner-owned businesses and apps</h3><p>Paid or featured provider placements are advertising and are labelled in the directory; placement is not an endorsement, qualification check or guarantee by Skillvaya. Skillvaya may also publish or link to businesses, services or apps owned, operated or submitted by the platform owner. Such owner-related listings are disclosed as owner listings where displayed and are subject to the same applicable listing, safety and legal rules. The public app interface is intended to focus on customer search, provider listings and account features; platform ownership disclosures and advertising rules are explained here in these Terms.</p><h3>App operation and support</h3><p>Skillvaya is a local service-provider directory and introduction application. Customer search and ordinary contact are free unless a charge is clearly shown before approval. Email contact is skillvaya@gmail.com; owner email settings are managed in Owner Control. Complaint reports are allegations and are reviewed fairly; a report alone is not proof of misconduct.</p></div></section>
<section id="admin" class="hidden" style="padding:25px 0 55px"><div class="sectionhead"><div><h2>Owner control centre</h2><p class="muted">Secure sign-in as owner is required to manage complaints and payments.</p></div></div><div id="adminMsg" class="notice">Sign in using the configured owner account. Default passwords must never be used in production.</div><div id="adminData" class="hidden"><div class="stats"><div class="card"><span class="tiny muted">BUSINESSES</span><strong id="sBiz">0</strong></div><div class="card"><span class="tiny muted">OPEN COMPLAINTS</span><strong id="sComplaints">0</strong></div><div class="card"><span class="tiny muted">PAYMENT REQUESTS</span><strong id="sPayments">0</strong></div><div class="card"><span class="tiny muted">PENDING LISTINGS</span><strong id="sPending">0</strong></div></div><div class="switchline"><button class="ghost" onclick="adminTab('complaints')">Reports & complaints</button><button class="ghost" onclick="adminTab('businesses')">Listings</button><button class="ghost" onclick="adminTab('payments')">Payments</button><button class="ghost" onclick="adminTab('clients')">Client accounts</button><button class="ghost" onclick="emailClientByAddress()">Email / warn a client</button><button class="ghost" onclick="adminTab('analytics')">Downloads & usage</button><button class="ghost" onclick="adminTab('notifications')">Alerts</button><button class="ghost" onclick="adminTab('settings')">Email settings</button></div><div id="adminTable" class="card"></div></div></section>
 </main><section id="subscriptionTestApp" class="hidden" aria-label="Skillvaya Subscription Test Lab">
 <div class="sv-subtest-shell">
  <div class="sv-subtest-topbar"><button type="button" class="sv-subtest-back" onclick="subscriptionTestGoBack()">← Return to Account</button><span class="sv-subtest-mode"><i aria-hidden="true"></i> OWNER ONLY · TEST MODE</span></div>
  <div id="subscriptionTestContent" aria-live="polite"></div>
 </div>
</section>
<section id="subscriptionTestProfileScreen" class="hidden app-destination" aria-label="Sandbox provider profile and portfolio">
 <div class="sv-subtest-shell">
  <div class="sv-subtest-testbar" data-sv-subtest-toolbar></div>
  <div class="sv-subtest-profile-hero"><button type="button" class="sv-subtest-secondary" onclick="view('services')">← Back to this tier's workstation</button><span class="sv-subtest-eyebrow">SANDBOX PROVIDER PROFILE</span><h1 id="svTestProfileHeroName">Test Provider</h1><p id="svTestProfileHeroCategory">Test category · Sample area</p><span id="svTestProfileTierTag" class="sv-subtest-tier-tag"></span></div>
  <div class="sv-subtest-notice"><strong>Isolated test profile:</strong> this page does not load your real Skillvaya studio listing or portfolio. Profile edits and selected files stay in this test session; nothing is uploaded or saved to the live provider account.</div>
  <form id="svSubscriptionTestProfileForm" class="sv-subtest-profile-card" onsubmit="saveSubscriptionTestProfile(event)">
   <div class="sv-subtest-profile-section"><span class="sv-subtest-eyebrow">TEST ACCOUNT DETAILS</span><h2>Business profile</h2><div class="sv-subtest-fields"><div><label for="svTestProfileName">Business name</label><input id="svTestProfileName" name="name" required maxlength="120"></div><div><label for="svTestProfileCategory">Service category</label><input id="svTestProfileCategory" name="category" required maxlength="120" placeholder="e.g. Plumbers"></div><div><label for="svTestProfileArea">Town or service area</label><input id="svTestProfileArea" name="area" maxlength="160" placeholder="Sample suburb"></div><div><label for="svTestProfileEmail">Test contact email</label><input id="svTestProfileEmail" name="email" type="email" maxlength="160" placeholder="Leave blank for no contact"></div><div class="full"><label for="svTestProfileDescription">Business description</label><textarea id="svTestProfileDescription" name="description" rows="4" maxlength="2000" placeholder="Describe the example provider's services"></textarea></div></div></div>
   <div class="sv-subtest-profile-section"><span class="sv-subtest-eyebrow">PORTFOLIO PREVIEW</span><h2>Portfolio &amp; catalogue</h2><p class="sv-subtest-progress">This test account begins with an empty portfolio. Choose sample JPG, PNG, WebP or PDF files to preview how this tier's portfolio area behaves. The files remain local and are not sent to Skillvaya.</p><div id="svTestPortfolioEmpty" class="sv-subtest-empty-portfolio">No portfolio items in this test account yet.</div><div id="svTestPortfolioGrid" class="sv-subtest-test-portfolio-grid"></div><label class="sv-subtest-file-label" for="svTestPortfolioFiles">Select sample portfolio files (maximum 2 MB combined)</label><input id="svTestPortfolioFiles" type="file" multiple accept="image/jpeg,image/png,image/webp,application/pdf" onchange="selectSubscriptionTestPortfolioFiles(this)"><div id="svTestPortfolioStatus" class="sv-subtest-progress">No files selected. Nothing has been uploaded.</div></div>
   <div class="sv-subtest-actions"><button class="sv-subtest-primary" type="submit">Save test profile in this session</button><button class="sv-subtest-secondary" type="button" onclick="previewSubscriptionTestProfile()">Preview this test profile</button><button class="sv-subtest-secondary" type="button" onclick="clearSubscriptionTestPortfolio()">Clear sample portfolio</button></div><div id="svTestProfileResult" class="sv-subtest-result" aria-live="polite">Your live profile and portfolio are not connected to this screen.</div>
  </form>
  <div id="svTestPublicProfilePreview" class="sv-subtest-profile-card hidden"></div>
 </div>
</section>
<section id="teamAssignmentsScreen" class="hidden app-destination" aria-label="My team assignments">
 <div class="sv-subtest-shell">
  <div class="sv-subtest-topbar"><button type="button" class="sv-subtest-back" onclick="view('settings')">← Return to Account</button><span class="sv-subtest-mode">SKILLVAYA · TEAM WORK</span></div>
  <div class="sv-subtest-hero"><span class="sv-subtest-eyebrow">MY WORKSPACE</span><h1>My Team Assignments</h1><p>Review jobs assigned to you by a Skillvaya provider and update your work progress.</p></div>
  <div id="teamAssignmentsContent" aria-live="polite"></div>
 </div>
</section>
<section id="messagesScreen" class="hidden app-destination" aria-label="Skillvaya Messages"><div id="messagesWorkspaceMount" class="contacts-workspace"><div id="messagesCard" class="messages-app-card hidden"><header class="messages-app-header"><div class="messages-app-mark">SV</div><div class="messages-app-title"><h1>Messages</h1><p>Private conversations</p></div><span class="messages-online-dot" aria-label="Private messaging"></span></header><div class="messages-list-heading"><strong>Chats</strong><span id="messagesCount" aria-live="polite"></span></div><div id="messagesList" aria-live="polite"><div class="messages-loading"><span class="messages-loading-dot"></span> Loading chats…</div></div><div id="messagesStatus" aria-live="polite"></div></div></div></section>
<section id="accountSubspace" class="hidden" role="dialog" aria-modal="true" aria-labelledby="accountSubspaceTitle"><div class="account-subspace-top"><button type="button" id="accountSubspaceBack" class="ghost">← Back to Profile</button><div><span class="tag">YOUR ACCOUNT</span><h1 id="accountSubspaceTitle">My account</h1><p id="accountSubspaceSubtitle" class="muted">Your saved information and activity.</p></div></div><div id="accountSubspaceContent" class="account-subspace-content"></div></section><nav class="bottom-tabbar" aria-label="Main app navigation"><button id="nav-customer-bottom" type="button" onclick="view('customer')"><span class="bottom-tab-icon">⌂</span><span>Home</span></button><button id="nav-messages" type="button" onclick="showMessagesScreen()"><span class="bottom-tab-icon">▤</span><span>Contacts</span></button><button id="nav-provider" type="button" onclick="view('services')"><span class="bottom-tab-icon">✦</span><span>Services</span></button><button id="nav-settings" type="button" onclick="view('settings')"><span class="bottom-tab-icon">●</span><span>Account</span></button><button id="nav-workfinder" type="button" onclick="location.href='/workfinder'"><span class="bottom-tab-icon">◆</span><span>Work Finder</span></button></nav><script>/* SV75-HEADERS-01: keep every sticky header exactly under the visible masthead (0px when the masthead is hidden). */
(function(){function sync(){try{var h=document.querySelector('header.top'),off=0;if(h){var cs=getComputedStyle(h);if(cs.display!=='none'&&cs.visibility!=='hidden'&&h.offsetHeight>0&&(cs.position==='fixed'||cs.position==='sticky')){off=Math.max(0,Math.round(h.getBoundingClientRect().bottom))}}var v=off+'px';if(document.body&&document.body.style.getPropertyValue('--sv-screen-header-top')!==v)document.body.style.setProperty('--sv-screen-header-top',v)}catch(e){}}
var raf=0;function later(){if(raf)return;raf=requestAnimationFrame(function(){raf=0;sync()})}window.svSyncHeaderOffset=sync;
function start(){sync();try{var mo=new MutationObserver(later);mo.observe(document.body,{attributes:true,attributeFilter:['class']});var t=document.querySelector('header.top');if(t)mo.observe(t,{attributes:true,attributeFilter:['class','style','hidden']})}catch(e){}window.addEventListener('resize',later);window.addEventListener('orientationchange',later);window.addEventListener('load',later);setTimeout(sync,500);setTimeout(sync,1500)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start()})();
</script><script>
let providerDetailReturnView='customer',categoryReturnView='customer';
// Preserve the Contacts card's original Account location so it cannot leak across screens.
let messagesCardHomeParent=null,messagesCardHomeNext=null;
function restoreMessagesCardHome(){const card=document.getElementById('messagesCard');if(!card||!messagesCardHomeParent)return;card.classList.remove('messages-workspace-card');if(messagesCardHomeNext&&messagesCardHomeNext.parentNode===messagesCardHomeParent)messagesCardHomeParent.insertBefore(card,messagesCardHomeNext);else messagesCardHomeParent.appendChild(card);card.classList.add('hidden');card.style.removeProperty('display');card.style.removeProperty('visibility');messagesCardHomeParent=null;messagesCardHomeNext=null;}
const DEFAULT_CATEGORIES=["Builders & construction","Plumbers","Electricians","Painters & decorators","Mechanics & automotive","Cleaning & housekeeping","Gardening & landscaping","Roofing & waterproofing","Carpenters & furniture","Welders & fabricators","Appliance repairs","IT & computer support","Graphic designers","Artists & photographers","Marketing & advertising","Web & software developers","Lawyers & legal services","Private doctors & clinics","Dentists & specialists","Nurses & home care","Accountants & tax","Financial & insurance services","Real estate & property","Tutors & education","Beauty & hair","Catering & chefs","Transport & removals","Security services","Events & entertainment","Tailors & fashion","Arts & crafts","Pet care & veterinary","Funeral services","Engineering & consulting","Other professional services","Doctors","Nurses","Mechanics","Gardeners","General practitioners (GPs)","Medical specialists","Dentists","Dental hygienists","Physiotherapists","Psychologists & counsellors","Optometrists","Pharmacists","Veterinarians","Home carers","Elderly care","Childcare & babysitters","Midwives","Auto electricians","Tyre fitters","Panel beaters & spray painters","Car washers & detailing","Motorcycle mechanics","Truck & diesel mechanics","Landscapers","Pool maintenance","Pest control","Tree services","Bricklayers","Plasterers","Tilers","Flooring installers","Glaziers & window fitters","Locksmiths","Solar installers","Air-conditioning & refrigeration","CCTV & alarm installers","Handymen","Quantity surveyors","Architects","Domestic workers","Laundry & ironing","Carpet & upholstery cleaning","Office cleaning","Waste removal","Computer repair","Mobile phone repair","Network technicians","Cybersecurity services","UX/UI designers","Video editors","Videographers","Translators & interpreters","Writers & editors","Consultants","Human resources & recruitment","Bookkeepers","Auditors","Mortgage brokers","Financial advisers","Insurance brokers","Estate agents","Property managers","Teachers","Exam tutors","Music teachers","Driving instructors","Training & coaching","Barbers","Hairdressers","Nail technicians","Make-up artists","Beauty therapists","Massage therapists","Personal trainers","Nutritionists","Chefs & private cooks","Bakers","Food vendors","Event planners","DJs & sound technicians","Musicians","MCs & entertainers","Florists","Wedding services","Fashion designers","Sewing & alterations","Upholstery","Delivery drivers","Moving & removals","Taxi & shuttle services","Tour guides","Courier services","Security guards","Private investigators","Fire safety services","Funeral directors","Cremation services","Civil engineers","Electrical engineers","Mechanical engineers","Environmental consultants","Surveyors","Interior designers","Signage & printing","Craftspeople","Handmade crafts & gifts","Pottery & ceramics","Jewellery makers","Textile arts & weaving","Knitting & crochet","Woodcraft & carving","Leathercraft","Candle & soap makers","Artisan makers","Art & craft workshops","Pet groomers","Dog walkers","Animal trainers"];
let cats=DEFAULT_CATEGORIES.slice(),chosen='All categories',directorySearchActive=false,token=localStorage.getItem('skillvaya_token')||localStorage.getItem('sv_token')||sessionStorage.getItem('skillvaya_token')||sessionStorage.getItem('sv_token')||'',me=null,allBusinesses=[],favoriteIds=[];
const planInfo=[
 ['local','Local',105,'Get listed and manage customer enquiries.',['Business profile and category listing','Customer requests and quotations','Private messages, photo/video sharing and video calls']],
 ['priority','Priority',210,'Improve discovery and quote turnaround.',['Everything in Local','Higher category placement and priority badge','Reusable quotation templates']],
 ['plus','Business Plus',500,'Run your daily business from Skillvaya.',['Everything in Priority','Lead/job pipeline and booking calendar','Customer CRM with private notes and tags','Quote follow-up reminders','Invoice and payment-status tracking','Review replies and service packages with add-ons','Performance insights from real activity']],
 ['spotlight','Business Spotlight',1000,'Promote your services and coordinate a growing team.',['Everything in Business Plus','Featured placement plus public offers/vouchers','Team invitations and job assignments','Campaign planner and marketing analytics','Lead-source and campaign interaction tracking','Announcements to opted-in customers through Skillvaya chat','Automation rules and in-app alerts']]
];
// Capture-phase fallback for the Account dashboard shortcut, in case nested account overlays swallow inline clicks.
document.addEventListener('click',function(e){
  const button=e.target&&e.target.closest?e.target.closest('#settings .account-dashboard-links .account-link'):null;
  if(!button)return;
  // Route by the button's actual heading, not its supporting description.
  // The Chats card mentions 'Providers & conversations', which must never match Become a Provider.
  const label=(button.querySelector('strong')?.textContent||button.innerText||button.textContent||'').trim().toLowerCase();
  if(label==='become a provider'){
    e.preventDefault();e.stopPropagation();
    openProviderOnboarding();
  }else if(label==='chats'||label==='messages'){
    e.preventDefault();e.stopPropagation();
    showMessagesScreen(true);
  }
},true);
async function openProviderOnboarding(){
  // Resolve the persisted session before deciding whether this person needs checkout.
  // The owner must never be sent to plan selection while /api/me is still loading.
  const overlay=document.getElementById('accountSubspace');
  if(overlay)overlay.classList.add('hidden');
  document.body.classList.remove('account-subspace-open','account-screen-mode','messages-screen-mode','category-screen-mode');
  if(!me){
    view('provider');
    const loadingHeading=document.getElementById('providerStudioHeading');if(loadingHeading)loadingHeading.classList.remove('hidden');
    const loadingNotice=document.getElementById('providerProfileNotice');if(loadingNotice){loadingNotice.classList.remove('hidden');loadingNotice.textContent='Loading your Provider Studio?';}
    const loadingPlans=document.getElementById('providerPlansCard');if(loadingPlans)loadingPlans.classList.add('hidden');
    await sessionInfo();
  }
  if(!me){
    view('settings');
    profileAuthMode('signin');
    const identity=document.getElementById('loginMsg');
    if(identity){identity.className='notice';identity.textContent='Sign in to open your existing provider studio, or create an account if you are a new provider.';}
    window.scrollTo({top:0,behavior:'auto'});
    return;
  }
  providerOnboardingPlanFirst=false;
  const banner=document.getElementById('providerFlowProgress');if(banner)banner.remove();
  view('provider');
  if(me.role==='admin'){
    // Owner's existing studio profile: no payment, no new listing.
    await refreshProviderGate();
    const heading=document.getElementById('providerStudioHeading');if(heading)heading.classList.add('hidden');
    const plans=document.getElementById('providerPlansCard');if(plans)plans.classList.add('hidden');
    const card=document.getElementById('providerProfileCard');if(card)card.classList.remove('hidden');
    const notice=document.getElementById('providerProfileNotice');
    if(notice){notice.classList.remove('hidden');notice.classList.add('good');notice.textContent='OWNER FREE ACCESS: manage your existing Skillvaya Digital & Creative Studio profile here. No subscription or payment is required.';}
    window.scrollTo({top:0,behavior:'auto'});
    return;
  }
  if(me.role==='provider'){
    // Render plan choices immediately; refresh provider eligibility without blocking first paint.
    drawPlans();
    refreshProviderGate().then(()=>drawPlans()).catch(e=>console.warn('Provider status refresh failed:',e.message));
    const planRoot=document.getElementById('plans');
    const planCard=document.getElementById('providerPlansCard');
    if(planRoot&&planCard&&!planRoot.querySelector('[data-plan]')){
      planCard.classList.remove('hidden');
      drawPlans();
    }
    window.scrollTo({top:0,behavior:'auto'});
    return;
  }
  // A signed-in customer must explicitly opt into provider status before checkout.
  const card=document.getElementById('providerProfileCard');if(card)card.classList.add('hidden');
  const plans=document.getElementById('providerPlansCard');if(plans)plans.classList.add('hidden');
  const heading=document.getElementById('providerStudioHeading');if(heading)heading.classList.remove('hidden');
  const notice=document.getElementById('providerProfileNotice');
  if(notice){notice.classList.remove('hidden','good');notice.textContent='To offer services, first activate provider access. Then choose a plan and complete verified payment before creating your profile.';}
  await becomeServiceProvider();
  if(me&&me.role==='provider')await refreshProviderGate();
  window.scrollTo({top:0,behavior:'auto'});
}
function scrollAccountSection(id){const target=document.getElementById(id);if(!target)return;document.querySelectorAll('#settings .account-link').forEach(b=>b.classList.toggle('active',b.getAttribute('onclick')&&b.getAttribute('onclick').includes(id)));if(id==='passwordForm'){target.scrollIntoView({behavior:'smooth',block:'center'});target.querySelector('input')?.focus({preventScroll:true});return}target.scrollIntoView({behavior:'smooth',block:'start'})}
function profileAuthMode(mode){const signed=!!me;document.getElementById('profileAuthTabs').classList.toggle('hidden',signed);document.getElementById('signinPane').classList.toggle('hidden',signed||mode!=='signin');document.getElementById('signupPane').classList.toggle('hidden',signed||mode!=='signup');document.getElementById('profileSigninTab').className=mode==='signin'?'primary':'ghost';document.getElementById('profileSignupTab').className=mode==='signup'?'primary':'ghost';document.getElementById('profileSettingsCard').classList.toggle('hidden',!signed)}

async function api(path,opts={}){/* SV76-SPEED-01: anything that adds a message (send, attachment, call invitation) discards the in-memory inbox so a chat never opens without it */if(opts&&/^POST$/i.test(String(opts.method||''))&&((String(path).indexOf('/api/messages')===0&&String(path).indexOf('/api/messages/read')!==0)||String(path).indexOf('/api/video-calls')===0))window.svMessagesItems=null;opts.headers={...(opts.headers||{}),'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})};const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),60000);let r;try{r=await fetch(path,{...opts,signal:controller.signal})}catch(e){if(e.name==='AbortError')throw Error('The server took too long to respond. Please try again.');throw e}finally{clearTimeout(timer)}let j=await r.json().catch(()=>({error:'Invalid server response'}));if(!r.ok)throw Error(j.error||'Request failed');return j}
function msg(id,text,good=false){let el=document.getElementById(id);if(!el)return;el.className='notice '+(good?'good':'bad');el.textContent=text}
function submitPlatformContact(e){if(e&&e.preventDefault)e.preventDefault();const f=document.getElementById('platformContactForm'),st=document.getElementById('platformContactStatus');const val=id=>{const el=document.getElementById(id);return el?String(el.value||'').trim():''};const name=val('platformContactName'),email=val('platformContactEmail'),topic=val('platformContactTopic')||'General enquiry',message=val('platformContactMessage');if(f&&f.checkValidity&&!f.checkValidity()){if(f.reportValidity)f.reportValidity();return false}if(!name||email.indexOf('@')<1||message.length<5){if(st){st.className='notice bad';st.textContent='Please enter your name, a valid email and a message of at least 5 characters.'}return false}const subject='Skillvaya enquiry: '+topic;const body='Name: '+name+'\nEmail: '+email+'\nTopic: '+topic+'\n\n'+message;if(st){st.className='notice good';st.textContent='Opening your email app. If nothing opens, email skillvaya@gmail.com directly.'}window.location.href='mailto:skillvaya@gmail.com?subject='+encodeURIComponent(subject)+'&body='+encodeURIComponent(body);return false}
function applyLaunchGate(user){const gate=document.getElementById('firstLaunchGate');if(!gate)return;const nativeApp=/SkillvayaNative/i.test(navigator.userAgent),hasSavedSession=!!(token||localStorage.getItem('skillvaya_token')||localStorage.getItem('sv_token')||sessionStorage.getItem('skillvaya_token')||sessionStorage.getItem('sv_token'));if(nativeApp&&!user&&!hasSavedSession){gate.style.display='flex';document.body.style.overflow='hidden'}else{gate.style.display='none';document.body.style.overflow=''}}function enterLaunchAuth(mode){const gate=document.getElementById('firstLaunchGate');if(gate)gate.style.display='none';document.body.style.overflow='';view('settings');profileAuthMode(mode);const target=document.getElementById(mode==='signup'?'signupPane':'signinPane');if(target)target.scrollIntoView({behavior:'auto',block:'start'});const field=target?.querySelector('input:not([type=checkbox])');if(field)field.focus({preventScroll:true})}
async function init(){
  // Restore the saved customer/provider session before dismissing the launch splash.
  // Do not expose the first-launch sign-in gate while an existing session is still being checked.
  // SV76-SPEED-01: nothing at start-up waits for anything else. Paint the last directory at once, then run the session
  // check, directory, rating and categories in parallel. A saved session never needs the launch gate, so do not wait for it.
  try{svPaintCachedDirectory()}catch(e){}
  applyLaunchGate(null);
  const svSessionP=sessionInfo().then(user=>{applyLaunchGate(user);if(user&&user.role==='customer')svRefreshFavorites().catch(()=>{});return user},e=>{console.warn('Session check failed:',e.message);applyLaunchGate(null);return null});
  const svDirectoryP=loadBusinesses();
  loadPlatformRating();
  const svCategoriesP=api('/api/categories').then(d=>d,()=>null);
  const renderCategoryOptions=()=>{
    const categorySelect=document.getElementById('categories');
    if(categorySelect){categorySelect.innerHTML='<option value="All categories">All categories</option>'+cats.map(c=>'<option value="'+esc(c)+'">'+esc(c)+'</option>').join('');categorySelect.value=cats.includes(chosen)?chosen:'All categories';}
    const businessCategory=document.getElementById('bizCat');
    if(businessCategory){const previous=businessCategory.value;businessCategory.innerHTML=cats.map(c=>'<option value="'+esc(c)+'">'+esc(c)+'</option>').join('');if(cats.includes(previous))businessCategory.value=previous;}
    renderDesignCategoryTiles();
  };
  cats=DEFAULT_CATEGORIES.slice();renderCategoryOptions();
  svCategoriesP.then(d=>{if(d&&Array.isArray(d.categories)&&d.categories.length){cats=d.categories;renderCategoryOptions();}else console.warn('Using built-in service categories while the server responds')});
  svSessionP.then(()=>{if(me&&me.role==='admin'&&!document.getElementById('ownerEditionBar')){
    document.body.insertAdjacentHTML('afterbegin','<div id="ownerEditionBar" style="position:sticky;top:0;z-index:999;background:#0b766e;color:white;padding:10px 14px;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap"><strong>SKILLVAYA OWNER EDITION — ALL FEATURES UNLOCKED FREE</strong><a href="/owner-app" style="color:white;font-weight:700">← Back to Owner / Controller</a></div>');
  }});
  try{drawPlans();}catch(e){}
  svSessionP.then(()=>refreshProviderGate()).catch(e=>console.warn('Provider status unavailable during startup:',e.message));
  // Only hold the splash for the directory when there is nothing cached to show (never longer than 1.5 s).
  if(!svDirectoryHadCache)await Promise.race([svDirectoryP,new Promise(r=>setTimeout(r,1500))]);
}
let designCategoriesExpanded=false;
function designCategoryIcon(name){const n=String(name||'').toLowerCase();if(/graphic|artist|photo|design|creative|brand/.test(n))return '✦';if(/web|software|coding|computer|it support|app|ai|digital/.test(n))return '⌘';if(/doctor|dentist|nurse|clinic|health|care/.test(n))return '✚';if(/law|legal|account|finance|tax/.test(n))return '§';if(/builder|construction|roof|carpenter|weld|plumb|electric|paint/.test(n))return '⌂';if(/clean|garden|landscap|housekeep/.test(n))return '✧';if(/mechanic|automotive|appliance|repair/.test(n))return '⚙';return '◈'}
function renderDesignCategoryTiles(){const root=document.getElementById('designCategoryTiles');if(!root)return;const all=Array.isArray(cats)?cats:[];const items=designCategoriesExpanded?all:all.slice(0,8);root.innerHTML=items.map((c,i)=>'<button type="button" class="design-category-tile" onclick="pickCat('+JSON.stringify(c).replace(/</g,'\\u003c').replace(/\"/g,'&quot;')+')" aria-label="Browse '+esc(c)+'"><span class="design-category-icon" aria-hidden="true">'+designCategoryIcon(c)+'</span><span class="design-category-copy"><strong>'+esc(c)+'</strong><small>View services</small></span><span class="design-category-arrow" aria-hidden="true">›</span></button>').join('')||'<p class="muted">Categories are temporarily unavailable.</p>';const btn=document.getElementById('toggleDesignCategories');if(btn){btn.textContent=designCategoriesExpanded?'Show featured':'View all';btn.setAttribute('aria-expanded',String(designCategoriesExpanded))}}
function toggleDesignCategories(){designCategoriesExpanded=!designCategoriesExpanded;renderDesignCategoryTiles()}
function contactFeaturedStudio(){const studio=(allBusinesses||[]).find(b=>String(b.name||'').trim()==='Skillvaya Digital & Creative Studio');if(studio){openProvider(studio.id);return}const q=document.getElementById('q');if(q)q.value='Graphic designers';searchDirectory()}

// Defensive shared layout helpers: these are called by every main navigation route.
function setHomeChrome(isHome){
  const top=document.querySelector('.top');if(top)top.classList.toggle('hidden',!isHome);
  const hero=document.getElementById('hero');if(hero)hero.classList.toggle('hidden',!isHome);
}
function renderServicesTab(){
  const host=document.getElementById('servicesTabProviders');if(!host)return;
  const list=Array.isArray(allBusinesses)?allBusinesses:[];
  if(!list.length){host.innerHTML='<div class="card"><h3>No providers to show yet</h3><p class="muted">Search the Home directory or check back as providers publish their profiles.</p><button type="button" class="primary" onclick="view(\'customer\')">Browse Home directory</button></div>';return;}
  host.innerHTML=list.map(b=>'<article class="card biz '+esc(b.plan||'local')+'" role="button" tabindex="0" onclick="openProvider('+Number(b.id)+')" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();openProvider('+Number(b.id)+')}"><h3>'+esc(b.name||'Service provider')+'</h3><p class="muted tiny">'+esc(b.category||'Services')+' · '+esc(b.area||'South Africa')+'</p><p>'+esc(b.description||'View this provider profile and contact options.')+'</p><button type="button" class="primary" onclick="event.stopPropagation();openProvider('+Number(b.id)+')">View provider</button></article>').join('');
}


async function maybeAcceptSkillvayaTeamInvite(){
 const params=new URLSearchParams(location.search),code=params.get('team_invite');
 if(!code||!me)return;
 const marker='svTeamInviteSeen:'+code;
 if(sessionStorage.getItem(marker))return;
 sessionStorage.setItem(marker,'1');
 if(!confirm('You were invited to join a Skillvaya provider team. Accept this invitation using your signed-in email?'))return;
 try{
  const d=await api('/api/provider/growth/team',{method:'POST',body:JSON.stringify({action:'accept_invite',invite_code:code})});
  const clean=new URL(location.href);clean.searchParams.delete('team_invite');history.replaceState(null,'',clean.pathname+clean.search+clean.hash);
  alert(d.message||'Team invitation accepted. Open Account → My Team Assignments to see your assigned work.');
  await loadMyTeamAccess();
 }catch(e){sessionStorage.removeItem(marker);alert('Could not accept invitation: '+e.message);}
}
async function loadMyTeamAccess(){
 const link=document.getElementById('openMyTeamAssignmentsLink');if(!link||!me)return;
 try{const d=await api('/api/team/my-assignments');link.classList.toggle('hidden',!d.active);if(d.active)window.svTeamAccess={active:true,business_ids:d.business_ids||[]};else window.svTeamAccess={active:false};}
 catch(e){link.classList.add('hidden');window.svTeamAccess={active:false};}
}
async function openMyTeamAssignments(){
 if(!me){view('settings');profileAuthMode('signin');return;}
 view('teamAssignmentsScreen');const root=document.getElementById('teamAssignmentsContent');if(!root)return;root.innerHTML='<div class="sv-subtest-notice">Loading assigned work…</div>';
 try{const d=await api('/api/team/my-assignments');if(!d.active){root.innerHTML='<div class="sv-growth-empty">No active team invitation is linked to this account.</div>';return;}
 root.innerHTML=d.items.length?d.items.map(a=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(a.title||'Assigned job')+'</h3><span class="sv-growth-tag">'+esc(String(a.assignment_status||'assigned').replaceAll('_',' '))+'</span></div><p><strong>'+esc(a.business_name)+'</strong> · Job #'+Number(a.job_id)+' · '+esc(a.area||'Area not supplied')+'</p><p>'+esc(a.description||'')+'</p><p class="sv-growth-small">Due '+esc(a.due_date||'No due date')+' · '+esc(a.note||'No assignment notes')+'</p><div class="sv-growth-inline-actions">'+(a.assignment_status==='assigned'?'<button type="button" class="sv-tool-outline" onclick="updateMyTeamAssignment(this.dataset.id,this.dataset.status)" data-id="'+Number(a.assignment_id)+'" data-status="completed">Mark complete</button>':'')+'</div></article>').join(''):'<div class="sv-growth-empty">No jobs have been assigned to you yet. Your provider manager will assign work here.</div>';}
 catch(e){root.innerHTML='<div class="sv-growth-muted-alert">'+esc(e.message)+'</div>';}
}
async function updateMyTeamAssignment(id,status){try{await api('/api/team/my-assignments',{method:'POST',body:JSON.stringify({assignment_id:Number(id),status})});await openMyTeamAssignments();}catch(e){alert(e.message);}}

function updateSkillvayaProviderTab(){const nav=document.getElementById('nav-provider');if(nav){nav.classList.remove('hidden');nav.style.removeProperty('display');nav.style.removeProperty('visibility');}} updateSkillvayaProviderTab();
function openProviderWorkstation(){Promise.resolve(me?me:sessionInfo()).then(user=>{if(!user){view('settings');profileAuthMode('signin');return;}if(user.role==='customer'){view('customer');return;}view('services');});} let svWorkspacePlan='local',svWorkspaceRank=0,svWorkspaceBusiness=null,svWorkspaceTemplates=[];
const svWorkspaceRanks={local:0,priority:1,plus:2,spotlight:3};
function svProviderTierName(plan){return ({local:'Local',priority:'Priority',plus:'Business Plus',spotlight:'Business Spotlight'})[plan]||'Local';}
function svWorkstationCard(icon,title,description,button,onclick,locked){
 return '<article class="sv-workstation-tool '+(locked?'sv-workstation-locked':'')+'"><span class="sv-workstation-icon">'+icon+'</span><h3>'+esc(title)+'</h3><p>'+esc(description)+'</p><button type="button" class="sv-workstation-open" onclick="'+onclick+'">'+esc(button)+'</button></article>';
}
async function loadProviderWorkstation(){
 updateSkillvayaProviderTab();
 const root=document.getElementById('servicesTabScreen');if(!root)return;
 const cards=document.getElementById('svWorkstationTools');if(!cards)return;
 if(!me||!(me.role==='provider'||me.role==='admin')){root.innerHTML='<div class="sv-workstation"><div class="sv-workstation-hero"><h1>Provider-only workstation</h1><p>Sign in with a service-provider account to open the business tools. Customers can continue browsing and chatting for free.</p><button type="button" class="sv-tool-outline" onclick="view(\'settings\')">Open Account</button></div></div>';return;}
 svWorkspacePlan=me.role==='admin'?(window.svSubscriptionTestMode?window.svSubscriptionTestTier:'spotlight'):'local';svWorkspaceRank=me.role==='admin'?(svWorkspaceRanks[svWorkspacePlan]??3):0;svWorkspaceBusiness=null;
 if(me.role==='provider'){
  // SV76-SPEED-01: show the tools from the last verified plan at once, then confirm it quietly (re-render only if the plan changed).
  const wsKey='sv_ws_profile_v1_'+String(me.id);let wsCached=null;try{wsCached=JSON.parse(svCacheGet(wsKey)||'null')}catch(_){}
  const wsSlim=(b)=>b?{id:b.id,plan:b.plan,status:b.status,payment_status:b.payment_status}:null;
  const wsApply=(b)=>{svWorkspaceBusiness=b||null;if(svWorkspaceBusiness){svWorkspacePlan=String(svWorkspaceBusiness.plan||'local').toLowerCase();svWorkspaceRank=svWorkspaceRanks[svWorkspacePlan]??0;}};
  const wsSig=(b)=>b?String(b.plan||'')+'|'+String(b.status||'')+'|'+String(b.payment_status||''):'none';
  if(wsCached&&wsCached.business){
   wsApply(wsCached.business);
   const wsUser=me.id;
   api('/api/provider/profile').then(d=>{const nb=wsSlim(d.business||null);svCacheSet(wsKey,JSON.stringify({business:nb}));if(wsSig(nb)!==wsSig(wsCached.business)&&me&&me.id===wsUser)loadProviderWorkstation().catch(()=>{})}).catch(()=>{});
  }else{
   try{const d=await api('/api/provider/profile');wsApply(d.business||null);svCacheSet(wsKey,JSON.stringify({business:wsSlim(d.business||null)}));}
   catch(e){cards.innerHTML='<div class="sv-workstation-banner">Could not verify your provider plan: '+esc(e.message)+'. Retry after your connection returns.</div>';return;}
  }
 }
 const planLabel=window.svSubscriptionTestMode?'TEST PREVIEW: '+svProviderTierName(svWorkspacePlan).toUpperCase()+' - NO SUBSCRIPTION':me.role==='admin'?'OWNER EDITION - SPOTLIGHT TOOLS - FREE':svProviderTierName(svWorkspacePlan).toUpperCase()+' PLAN';
 const badge=document.getElementById('svWorkstationPlan');if(badge)badge.textContent=planLabel;
 if(me.role==='provider'&&!svWorkspaceBusiness){
  cards.innerHTML='<article class="sv-workstation-tool"><span class="sv-workstation-icon">↗</span><h3>Finish provider setup</h3><p>Your workstation opens after Skillvaya verifies your plan and provider profile.</p><button type="button" class="sv-workstation-open" onclick="view(\'provider\')">Open Provider Studio</button></article>';return;
 }
 const tools=[
  svWorkstationCard('▣','Requests & Quotations','Review customer job requests, prepare a quotation, and send the quote back into the existing customer chat.','Open requests',"openProviderTool('requests')",false),
  svWorkstationCard('▤','Messages & Video Calls','Open your existing private chats. Video calls and photo/video uploads are included for every chat and every plan.','Open messages',"showMessagesScreen(true)",false),
  svWorkstationCard('▧','Profile & Portfolio','Edit your business details and use the existing upload control for portfolio photos and catalogues.','Manage profile',"view('provider')",false)
 ];
 if(svWorkspaceRank>=1)tools.push(svWorkstationCard('✎','Quotation Templates','Save reusable quotation wording and estimated timelines.','Manage templates',"openProviderTool('templates')",false));
 if(svWorkspaceRank>=2)tools.push(svWorkstationCard('▥','Performance Insights','See real request, quote, messaging, media-sharing and customer-rating totals for your listing.','View insights',"openProviderTool('insights')",false));

  if(svWorkspaceRank>=2){
   tools.push(svWorkstationCard('▦','Lead & Job Pipeline','Track real requests from new enquiry through quote, accepted work, scheduling, progress and completion.','Open pipeline',"openProviderTool('pipeline')",false));
   tools.push(svWorkstationCard('▣','Bookings & Calendar','Schedule customer appointments and jobs, check upcoming work and update booking status.','Manage bookings',"openProviderTool('bookings')",false));
   tools.push(svWorkstationCard('◎','Customer CRM','Review customers you have interacted with, their jobs and quote history, and save private notes and tags.','Open customers',"openProviderTool('crm')",false));
   tools.push(svWorkstationCard('◷','Quote Follow-ups','Create reminders for pending quotations so enquiries do not quietly go cold.','View follow-ups',"openProviderTool('followups')",false));
   tools.push(svWorkstationCard('▤','Invoices & Payment Tracker','Issue invoice records, track due dates and record full or partial payments. This does not process card payments.','Track invoices',"openProviderTool('invoices')",false));
   tools.push(svWorkstationCard('★','Reviews & Reputation','Read actual customer ratings, reply professionally and request reviews through existing chats.','Manage reviews',"openProviderTool('reviews')",false));
   tools.push(svWorkstationCard('◇','Service Packages & Add-ons','Build service packages with clear prices and optional extras for your public provider profile.','Manage packages',"openProviderTool('packages')",false));
  }
  if(svWorkspaceRank>=3){
   tools.push(svWorkstationCard('✦','Featured Placement & Offers','Manage public offer codes and view exposure and engagement for your Spotlight listing.','Manage offers',"openProviderTool('offers')",false));
   tools.push(svWorkstationCard('♙','Team & Staff','Keep a team roster, invite staff and assign existing customer jobs to an accountable team member.','Manage team',"openProviderTool('team')",false));
   tools.push(svWorkstationCard('▥','Marketing Analytics','Track directory visibility, campaign interactions, enquiry sources and lead conversions.','View marketing',"openProviderTool('marketing')",false));
   tools.push(svWorkstationCard('✉','Customer Announcements','Prepare announcements and send them through existing chats only to customers who opted in.','Manage announcements',"openProviderTool('announcements')",false));
   tools.push(svWorkstationCard('⚡','Automation & Alerts','Control in-app alerts for due follow-ups, upcoming bookings and overdue invoices.','Configure alerts',"openProviderTool('automation')",false));
  }

if(svWorkspaceRank>=3)tools.push(svWorkstationCard('◇','Campaign Planner','Create private advertising campaign drafts, with optional dates. Drafts are not automatically published to customers.','Plan a campaign',"openProviderTool('campaigns')",false));
 const next=svWorkspaceRank===0?'Priority':svWorkspaceRank===1?'Business Plus':svWorkspaceRank===2?'Business Spotlight':'';
 if(next&&!window.svSubscriptionTestMode)tools.push(svWorkstationCard('＋','More tools with '+next,'Your current plan stays active. Higher plans unlock additional workstation tools; no feature is charged without your explicit checkout.','View upgrade options',"view('provider')",true));
 cards.innerHTML=tools.join('');
 const notice=document.getElementById('svWorkstationStatus');
 if(notice)notice.textContent=window.svSubscriptionTestMode?'TEST MODE: '+svProviderTierName(svWorkspacePlan)+' tools only. Subscription checkout and upgrade actions are disabled.':me.role==='admin'?'Owner Edition: full workstation access is free.':('Verified '+svProviderTierName(svWorkspacePlan)+' plan. Core enquiries, quotations, messages, calls, and chat-media sharing remain available.');
 if(window.svSubscriptionTestMode)mountSubscriptionTestToolbar(document.getElementById('servicesTabScreen'));const activity=document.getElementById('svWorkstationActivity');if(activity)activity.innerHTML='<h3>Your workspace</h3><p class="sv-tool-muted">Use each card to open a dedicated screen. Customer chat remains in Contacts; quotations use the existing job/quote records. Video calls and in-chat media are plan-independent.</p>';
}

// Owner-only test mode switches the client-side plan preview; it never creates subscriptions or invokes checkout.
window.svSubscriptionTestMode=false;window.svSubscriptionTestTier='local';
const svSubscriptionTestTiers=[{key:'local',name:'Local',price:105,rank:0},{key:'priority',name:'Priority',price:210,rank:1},{key:'plus',name:'Business Plus',price:500,rank:2},{key:'spotlight',name:'Business Spotlight',price:1000,rank:3}];
function updateSubscriptionTesterAccess(){const b=document.getElementById('openSubscriptionTesterLink');if(b)b.classList.toggle('hidden',!(me&&me.role==='admin'));}
function svSubscriptionTestToolbarHTML(){const selected=window.svSubscriptionTestTier||'local';return '<div class="sv-subtest-testbar" data-sv-subtest-toolbar><strong>OWNER TEST MODE</strong><span>Preview tier:</span><select aria-label="Choose subscription tier for testing" onchange="switchSubscriptionTestTier(this.value)">'+svSubscriptionTestTiers.map(p=>'<option value="'+p.key+'" '+(p.key===selected?'selected':'')+'>'+svTestEscape(p.name)+' — R'+p.price+'/mo</option>').join('')+'</select><span>No subscription or payment is created.</span><button type="button" onclick="exitSubscriptionTestMode()">Exit test</button></div>';}
function svTestEscape(v){return typeof esc==='function'?esc(String(v==null?'':v)):String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function mountSubscriptionTestToolbar(target){if(!window.svSubscriptionTestMode||!target)return;let bar=target.querySelector(':scope > [data-sv-subtest-toolbar]');if(!bar){target.insertAdjacentHTML('afterbegin',svSubscriptionTestToolbarHTML());bar=target.querySelector(':scope > [data-sv-subtest-toolbar]');}else{bar.outerHTML=svSubscriptionTestToolbarHTML();}}
async function openSubscriptionTestApp(){if(!me)await sessionInfo().catch(()=>null);if(!me||me.role!=='admin'){alert('The Subscription Test Lab is available only to the Skillvaya owner account.');return;}window.svSubscriptionTestMode=false;view('subscriptionTestApp');renderSubscriptionTestChooser();}
function subscriptionTestGoBack(){view('settings');}
function renderSubscriptionTestChooser(){const root=document.getElementById('subscriptionTestContent');if(!root)return;root.innerHTML='<div class="sv-subtest-hero"><span class="sv-subtest-eyebrow">SKILLVAYA · OWNER TEST STUDIO</span><h1>Subscription Test Lab</h1><p>Open the real provider workstation under each plan tier, using its existing screens and functions. Switching tiers here is only a preview: it will not change the owner account, create a subscription or open checkout.</p></div><div class="sv-subtest-notice"><strong>Live-function testing:</strong> The screens and controls below are the real Skillvaya provider tools, not mock replacements. Real tool actions use the current owner session and may update real requests, quotations, templates, insights or campaign drafts. Use test records when checking changes. Subscription purchase and upgrade controls are disabled in this mode.</div><div class="sv-subtest-plan-grid">'+svSubscriptionTestTiers.map(p=>{const includes=['Provider profile and portfolio','Requests and quotations','Messages, video calls and chat media',...(p.rank>=1?['Quotation templates']:[]),...(p.rank>=2?['Performance insights']:[]),...(p.rank>=3?['Campaign planner']:[])];return '<article class="sv-subtest-plan"><div class="sv-subtest-plan-head"><h2>'+svTestEscape(p.name)+'</h2><div class="sv-subtest-price">R'+p.price.toLocaleString('en-ZA')+'<small>per month · preview only</small></div></div><p>Opens the real workstation in the same tier configuration used by provider accounts.</p><ul class="sv-subtest-mini-list">'+includes.map(n=>'<li>'+svTestEscape(n)+'</li>').join('')+'</ul><div class="sv-subtest-lock-note">'+(p.rank===0?'Templates, insights and campaigns are not included.':p.rank===1?'Insights and campaigns are not included.':p.rank===2?'Campaign planner is not included.':'All provider tools included.')+'</div><button type="button" class="sv-subtest-plan-action" style="margin-top:14px" onclick="activateSubscriptionTestTier(this.dataset.tier)" data-tier="'+p.key+'">Open real '+svTestEscape(p.name)+' account view</button></article>';}).join('')+'</div>';}
function activateSubscriptionTestTier(plan){if(!me||me.role!=='admin'){alert('Owner access is required.');return;}if(!svSubscriptionTestTiers.some(p=>p.key===plan))return;window.svSubscriptionTestTier=plan;window.svSubscriptionTestMode=true;view('services');mountSubscriptionTestToolbar(document.getElementById('servicesTabScreen'));}
function switchSubscriptionTestTier(plan){if(!window.svSubscriptionTestMode)return;const current=window.svSubscriptionTestTier;if(!svSubscriptionTestTiers.some(p=>p.key===plan))return;window.svSubscriptionTestTier=plan;if(current===plan)return;view('services');mountSubscriptionTestToolbar(document.getElementById('servicesTabScreen'));}

// Per-tier portfolio sandboxes: no owner-profile APIs, no server uploads, and no live profile writes.
window.svSubscriptionTestProfiles=window.svSubscriptionTestProfiles||{};
function svCurrentTestProfile(){const key=window.svSubscriptionTestTier||'local';if(!window.svSubscriptionTestProfiles[key])window.svSubscriptionTestProfiles[key]={name:'Test Provider - '+svProviderTierName(key),category:'General Services',area:'Sample suburb',email:'',description:'Example provider profile for checking how this subscription tier displays business details and portfolio items.',portfolio:[]};return window.svSubscriptionTestProfiles[key];}
function openSubscriptionTestProfile(){if(!window.svSubscriptionTestMode||!me||me.role!=='admin'){view('provider');return;}view('subscriptionTestProfileScreen');renderSubscriptionTestProfile();}
function renderSubscriptionTestProfile(){const root=document.getElementById('subscriptionTestProfileScreen');if(!root||root.classList.contains('hidden'))return;const st=svCurrentTestProfile(),tier=svSubscriptionTestTiers.find(x=>x.key===window.svSubscriptionTestTier)||svSubscriptionTestTiers[0];mountSubscriptionTestToolbar(root.querySelector('.sv-subtest-shell'));const set=(id,v)=>{const el=document.getElementById(id);if(el)el.value=v||'';};set('svTestProfileName',st.name);set('svTestProfileCategory',st.category);set('svTestProfileArea',st.area);set('svTestProfileEmail',st.email);set('svTestProfileDescription',st.description);const h=document.getElementById('svTestProfileHeroName');if(h)h.textContent=st.name||'Test Provider';const sub=document.getElementById('svTestProfileHeroCategory');if(sub)sub.textContent=(st.category||'No category selected')+' · '+(st.area||'No area selected');const tag=document.getElementById('svTestProfileTierTag');if(tag)tag.textContent=tier.name+' · R'+tier.price+'/month · TEST PREVIEW';renderSubscriptionTestPortfolio();const result=document.getElementById('svTestProfileResult');if(result)result.textContent='Sandbox profile for '+tier.name+'. Your real studio portfolio is not connected to this screen.';}
function renderSubscriptionTestPortfolio(){const st=svCurrentTestProfile(),grid=document.getElementById('svTestPortfolioGrid'),empty=document.getElementById('svTestPortfolioEmpty');if(!grid||!empty)return;empty.classList.toggle('hidden',!!st.portfolio.length);grid.innerHTML=st.portfolio.map((f,i)=>'<div class="sv-subtest-test-portfolio-item">'+(f.type&&f.type.startsWith('image/')&&f.url?'<img src="'+f.url+'" alt="Local sample portfolio preview '+(i+1)+'">':'<div class="sv-subtest-empty-portfolio" style="min-height:100px">PDF<br>Sample catalogue</div>')+'<strong>'+svTestEscape(f.name)+'</strong><small>'+Math.round(f.size/1024)+' KB · local preview</small><button type="button" class="sv-subtest-secondary" style="margin-top:7px;width:100%" onclick="removeSubscriptionTestPortfolio('+i+')">Remove</button></div>').join('');}
function selectSubscriptionTestPortfolioFiles(input){const st=svCurrentTestProfile(),files=Array.from(input.files||[]),status=document.getElementById('svTestPortfolioStatus');if(!files.length)return;const total=files.reduce((n,f)=>n+f.size,0);if(total>2*1024*1024){input.value='';if(status)status.textContent='Selection exceeds the 2 MB combined test limit. No files were added.';return;}const allowed=['image/jpeg','image/png','image/webp','application/pdf'];if(files.some(f=>!allowed.includes(f.type))){input.value='';if(status)status.textContent='Use JPG, PNG, WebP or PDF files. No files were added.';return;}files.forEach(f=>st.portfolio.push({name:f.name,type:f.type,size:f.size,file:f,url:f.type.startsWith('image/')?URL.createObjectURL(f):''}));input.value='';renderSubscriptionTestPortfolio();if(status)status.textContent=files.length+' sample file(s) selected for local preview only. Nothing was uploaded.';const result=document.getElementById('svTestProfileResult');if(result)result.textContent='Portfolio preview updated in this '+svProviderTierName(window.svSubscriptionTestTier)+' test session only. No API request or live profile update occurred.';}
function removeSubscriptionTestPortfolio(index){const st=svCurrentTestProfile(),item=st.portfolio[index];if(item&&item.url)URL.revokeObjectURL(item.url);st.portfolio.splice(index,1);renderSubscriptionTestPortfolio();const status=document.getElementById('svTestPortfolioStatus');if(status)status.textContent='Sample portfolio item removed from this test session.';}
function clearSubscriptionTestPortfolio(){const st=svCurrentTestProfile();st.portfolio.forEach(f=>{if(f.url)URL.revokeObjectURL(f.url)});st.portfolio=[];renderSubscriptionTestPortfolio();const input=document.getElementById('svTestPortfolioFiles');if(input)input.value='';const status=document.getElementById('svTestPortfolioStatus');if(status)status.textContent='Test portfolio is empty. No live files were changed.';}
function saveSubscriptionTestProfile(event){event.preventDefault();const form=event.currentTarget,fd=new FormData(form),st=svCurrentTestProfile();st.name=String(fd.get('name')||'').trim();st.category=String(fd.get('category')||'').trim();st.area=String(fd.get('area')||'').trim();st.email=String(fd.get('email')||'').trim();st.description=String(fd.get('description')||'').trim();const h=document.getElementById('svTestProfileHeroName');if(h)h.textContent=st.name;const sub=document.getElementById('svTestProfileHeroCategory');if(sub)sub.textContent=st.category+' · '+(st.area||'No area selected');const result=document.getElementById('svTestProfileResult');if(result)result.textContent='Test profile saved in temporary session memory for '+svProviderTierName(window.svSubscriptionTestTier)+'. It was not sent to the server.';}
function previewSubscriptionTestProfile(){const st=svCurrentTestProfile(),box=document.getElementById('svTestPublicProfilePreview'),tier=svProviderTierName(window.svSubscriptionTestTier);if(!box)return;box.classList.remove('hidden');box.innerHTML='<span class="sv-subtest-eyebrow">PUBLIC PROFILE MOCK PREVIEW · '+svTestEscape(tier)+'</span><h2>'+svTestEscape(st.name)+'</h2><p>'+svTestEscape(st.category)+' · '+svTestEscape(st.area||'')+'</p><p>'+svTestEscape(st.description||'')+'</p><h3>Portfolio</h3>'+(st.portfolio.length?'<div class="sv-subtest-test-portfolio-grid">'+st.portfolio.map(f=>'<div class="sv-subtest-test-portfolio-item">'+(f.type.startsWith('image/')&&f.url?'<img src="'+f.url+'" alt="Sample portfolio">':'PDF sample catalogue')+'<strong>'+svTestEscape(f.name)+'</strong></div>').join('')+'</div>':'<div class="sv-subtest-empty-portfolio">No portfolio items in this test profile.</div>');box.scrollIntoView({behavior:'smooth',block:'start'});}

function exitSubscriptionTestMode(){window.svSubscriptionTestMode=false;document.body.classList.remove('subscription-test-screen-mode');document.querySelectorAll('[data-sv-subtest-toolbar]').forEach(x=>x.remove());view('settings');}

function svWorkstationHeader(title,description){
 return (window.svSubscriptionTestMode?svSubscriptionTestToolbarHTML():'')+'<button type="button" class="sv-tool-back" onclick="view(\'services\')">← Back to Services workstation</button><div class="sv-tool-heading"><span class="sv-workstation-eyebrow">SKILLVAYA PROVIDER TOOLS</span><h1>'+esc(title)+'</h1><p>'+esc(description)+'</p></div><div id="svWorkToolStatus" class="sv-tool-status" aria-live="polite"></div><div id="svWorkToolBody"></div>';
}
function openProviderTool(tool,jobId){
 if(!me||!(me.role==='provider'||me.role==='admin')){openProviderWorkstation();return;}
 window.svSelectedJobId=jobId?Number(jobId):0;
 view('svWorkstationTool');renderProviderTool(tool).catch(e=>{const el=document.getElementById('svWorkToolStatus');if(el)el.textContent=e.message;});
}
async function renderProviderTool(tool){
 const root=document.getElementById('svWorkstationToolContent');if(!root)return;
 const titles={requests:['Requests & Quotations','Review work requests and return complete quotes to the customer chat.'],quote:['Quotation Builder','Create a quotation for a real customer request and optionally attach a document or video to the chat.'],templates:['Quotation Templates','Save reusable quotation terms and timelines.'],insights:['Performance Insights','These totals are computed from actual Skillvaya requests, quotes, messages, shared media, and ratings.'],campaigns:['Campaign Planner','Manage private drafts and publish Spotlight campaigns with trackable links.'],pipeline:['Lead & Job Pipeline','Review live requests, outstanding quotes and work stages using your existing job records.'],bookings:['Bookings & Calendar','Create and manage job appointments in your business calendar.'],crm:['Customer CRM','See interaction history and keep private notes about customers.'],followups:['Quote Follow-ups','Set reminders for live requests and quotations waiting for a response.'],invoices:['Invoices & Payment Tracker','Maintain an invoice ledger and record payment status without taking payments.'],reviews:['Reviews & Reputation','Review customer feedback, reply, and request feedback through existing chats.'],packages:['Service Packages & Add-ons','Create priced service packages and publish them to your Skillvaya profile.'],offers:['Featured Placement & Offers','Create discount codes and review your listing reach and promotion activity.'],team:['Team & Staff','Manage a staff roster, send invitations and assign existing requests.'],marketing:['Marketing Analytics','Measure listing exposure, campaign engagement and lead sources.'],announcements:['Customer Announcements','Send service updates to customers who explicitly opted in.'],automation:['Automation & Alerts','Configure in-app reminders for quotations, bookings and invoices.']};
 const spec=titles[tool];if(!spec){root.innerHTML=svWorkstationHeader('Provider tools','Choose a tool from the workstation.');return;}
 root.innerHTML=svWorkstationHeader(spec[0],spec[1]);
 const body=document.getElementById('svWorkToolBody');
 if(tool==='requests'){await svRenderRequests(body);return;}
 if(tool==='quote'){await svRenderQuoteBuilder(body,window.svSelectedJobId);return;}
 if(tool==='templates'){await svRenderTemplates(body);return;}
 if(tool==='insights'){await svRenderInsights(body);return;}

  if(tool==='campaigns'){await svRenderCampaigns(body);return;}
  if(tool==='pipeline'){await svRenderGrowthPipeline(body);return;}
  if(tool==='bookings'){await svRenderBookings(body);return;}
  if(tool==='crm'){await svRenderCRM(body);return;}
  if(tool==='followups'){await svRenderFollowups(body);return;}
  if(tool==='invoices'){await svRenderInvoices(body);return;}
  if(tool==='reviews'){await svRenderReviews(body);return;}
  if(tool==='packages'){await svRenderPackages(body);return;}
  if(tool==='offers'){await svRenderOffers(body);return;}
  if(tool==='team'){await svRenderTeam(body);return;}
  if(tool==='marketing'){await svRenderMarketing(body);return;}
  if(tool==='announcements'){await svRenderAnnouncements(body);return;}
  if(tool==='automation'){await svRenderAutomation(body);return;}
}
async function svRenderRequests(body){
 const d=await api('/api/jobs'),items=(d.items||[]).filter(j=>me.role==='admin'||Number(j.business_id)>0);
 if(!items.length){body.innerHTML='<div class="sv-tool-card"><h3>No customer requests yet</h3><p class="sv-tool-muted">When a customer requests work from your provider listing, the request will appear here.</p><button class="sv-tool-outline" onclick="showMessagesScreen(true)">Open messages</button></div>';return;}
 body.innerHTML=items.map(j=>{
  const budget=j.budget_cents==null?'Not specified':svMoney(j.budget_cents,svCurOf(j.business_country));
  const quotes=(j.quotes||[]).map(q=>'<div class="sv-tool-card"><strong>Quote '+svMoney(q.amount_cents,svCurOf(j.business_country))+'</strong><p class="sv-tool-muted">Timeline: '+esc(q.eta||'')+' · Status: '+esc(q.status||'pending')+'</p><p>'+esc(q.message||'')+'</p></div>').join('');
  const canQuote=['requested','quoted'].includes(String(j.status||'').toLowerCase());
  const statusButtons=j.status==='accepted'||j.status==='scheduled'||j.status==='in_progress'?'<div class="sv-tool-row">'+(j.status==='accepted'?'<button class="sv-tool-outline" onclick="updateProviderJobStatus('+Number(j.id)+',\'scheduled\')">Schedule work</button>':'')+(j.status==='accepted'||j.status==='scheduled'?'<button class="sv-tool-outline" onclick="updateProviderJobStatus('+Number(j.id)+',\'in_progress\')">Mark in progress</button>':'')+(j.status==='in_progress'?'<button class="sv-tool-submit" onclick="updateProviderJobStatus('+Number(j.id)+',\'completed\')">Mark completed</button>':'')+'</div>':'';
  return '<article class="sv-tool-card"><div class="sv-tool-row"><h3>'+esc(j.title||'Customer request')+'</h3><span class="sv-workstation-plan">'+esc(j.status||'requested')+'</span></div><p class="sv-tool-muted">'+esc(j.business_name||'Your listing')+' · '+esc(j.area||j.business_area||'')+' · Budget: '+budget+'</p><p>'+esc(j.description||'')+'</p><p class="sv-tool-muted">Preferred date: '+esc(j.preferred_date||'Not supplied')+'</p>'+(canQuote?'<button class="sv-tool-submit" onclick="openProviderTool(\'quote\','+Number(j.id)+')">Create / update quotation</button>':'')+statusButtons+quotes+'<button class="sv-tool-outline" onclick="openMessageConversation('+Number(j.business_id)+','+Number(j.customer_id)+')">Open customer chat</button></article>';
 }).join('');
}
async function svRenderQuoteBuilder(body,jobId){
 const d=await api('/api/jobs');const items=(d.items||[]).filter(j=>['requested','quoted'].includes(String(j.status||'').toLowerCase()));
 if(!jobId||!items.some(x=>Number(x.id)===Number(jobId))){
  body.innerHTML='<div class="sv-tool-card"><h3>Select a customer request</h3><p class="sv-tool-muted">A quotation must be connected to an existing job request so it reaches the correct customer.</p>'+(items.length?items.map(j=>'<article class="sv-tool-card"><h3>'+esc(j.title||'Request')+'</h3><p class="sv-tool-muted">'+esc(j.area||'')+' · '+esc(j.status||'requested')+'</p><p>'+esc(j.description||'')+'</p><button class="sv-tool-submit" onclick="openProviderTool(\'quote\','+Number(j.id)+')">Prepare quote</button></article>').join(''):'<p>No requests are currently accepting quotations. Open Requests & Quotations to review active jobs.</p>')+'</div>';return;
 }
 const job=items.find(x=>Number(x.id)===Number(jobId));
 const templates=svWorkspaceRank>=1?await svTierPreviewApi('/api/provider/quote-templates').then(x=>x.items||[]).catch(()=>[]):[];
 window.svWorkspaceTemplates=templates;
 body.innerHTML='<form id="svQuoteBuilderForm" class="sv-tool-card"><div class="sv-tool-row"><h3>Quote for: '+esc(job.title||'Customer request')+'</h3><span class="sv-workstation-plan">Job #'+Number(job.id)+'</span></div><p class="sv-tool-muted">Recipient: '+esc(job.customer_name||'Customer')+' · Provider: '+esc(job.business_name||'Your business')+'</p>'+
 (templates.length?'<label for="svQuoteTemplateSelect">Use a saved template</label><select id="svQuoteTemplateSelect" onchange="applySkillvayaQuoteTemplate(this.value)"><option value="">Start with a blank quotation</option>'+templates.map(t=>'<option value="'+Number(t.id)+'">'+esc(t.name)+'</option>').join('')+'</select>':'')+
 '<div class="sv-tool-fields"><div><label for="svQuoteAmount">Total price ('+svProvCur()+')</label><input id="svQuoteAmount" name="amount_rands" type="number" min="0.01" max="10000000" step="0.01" required placeholder="e.g. 1250.00"></div><div><label for="svQuoteEta">Estimated timeline</label><input id="svQuoteEta" name="eta" required maxlength="160" placeholder="e.g. 3 working days"></div><div class="sv-full"><label for="svQuoteMessage">What is included in this quote?</label><textarea id="svQuoteMessage" name="message" required minlength="5" maxlength="2000" rows="5" placeholder="Describe labour, materials, deliverables, exclusions and any conditions."></textarea></div><div class="sv-full"><label for="svQuoteAttachment">Optional quotation file (PDF/photo)</label><input id="svQuoteAttachment" type="file" accept="application/pdf,image/jpeg,image/png,image/webp"><p class="sv-tool-muted">Any selected file is sent as a separate attachment in the same customer chat (maximum 12 MB where supported).</p></div></div><p class="sv-tool-muted">When saved, the quote is recorded against the job and its details are also sent through Skillvaya Messages.</p><button type="submit" class="sv-tool-submit">Save & send quotation</button><div id="svQuoteStatus" class="sv-tool-status" aria-live="polite"></div></form>';
 const form=document.getElementById('svQuoteBuilderForm');
 form.addEventListener('submit',async e=>{
  e.preventDefault();const btn=form.querySelector('button[type=submit]'),status=document.getElementById('svQuoteStatus'),amount=form.elements.amount_rands.value,eta=form.elements.eta.value.trim(),message=form.elements.message.value.trim(),file=document.getElementById('svQuoteAttachment').files[0];btn.disabled=true;status.textContent='Saving quotation…';
  try{
   await api('/api/jobs/'+Number(job.id)+'/quote',{method:'POST',body:JSON.stringify({amount_rands:amount,eta:eta,message:message})});
   const text='Quotation for '+(job.title||'your request')+': '+svMoney(Math.round(Number(amount)*100),svProvCur())+'. Estimated timeline: '+eta+'. Details: '+message;
   await api('/api/messages/send',{method:'POST',body:JSON.stringify({business_id:Number(job.business_id),customer_id:Number(job.customer_id),message:text})});
   if(file)await svUploadMediaToChat(Number(job.business_id),Number(job.customer_id),file,status);
   status.textContent='Quotation saved and sent to the customer chat.';alert('Quotation sent. The customer can see it in My Jobs and in this chat.');await renderProviderTool('requests');
  }catch(err){status.textContent='Could not complete every step: '+err.message+' If the quote was saved before the error, check Requests & Quotations before submitting it again.';}
  finally{btn.disabled=false;}
 });
}
function applySkillvayaQuoteTemplate(templateId){const t=(window.svWorkspaceTemplates||[]).find(x=>Number(x.id)===Number(templateId));if(!t)return;const eta=document.getElementById('svQuoteEta'),msg=document.getElementById('svQuoteMessage');if(eta)eta.value=t.eta||'';if(msg)msg.value=t.message||'';}
async function updateProviderJobStatus(jobId,status){try{await api('/api/jobs/'+Number(jobId)+'/status',{method:'POST',body:JSON.stringify({status:status})});await renderProviderTool('requests');}catch(e){alert('Job status was not changed: '+e.message);}}
async function svRenderTemplates(body){
 const query=window.svSubscriptionTestMode?'?test_tier='+encodeURIComponent(window.svSubscriptionTestTier||'local'):'';
 const d=await svTierPreviewApi('/api/provider/quote-templates'+query),items=d.items||[];
 body.innerHTML='<form id="svTemplateForm" class="sv-tool-card"><h3>Create a reusable quote template</h3><div class="sv-tool-fields"><div class="sv-full"><label>Template name</label><input name="name" required maxlength="120" placeholder="e.g. Standard call-out quote"></div><div><label>Default timeline</label><input name="eta" required maxlength="160" placeholder="e.g. 2–3 working days"></div><div class="sv-full"><label>Reusable quotation wording</label><textarea name="message" required minlength="5" maxlength="2000" rows="4" placeholder="Describe your normal inclusions and exclusions."></textarea></div></div><button class="sv-tool-submit" type="submit">Save template</button><div id="svTemplateStatus" class="sv-tool-status"></div></form><div class="sv-tool-card"><h3>Saved templates</h3>'+(items.length?items.map(t=>'<article class="sv-tool-card"><div class="sv-tool-row"><strong>'+esc(t.name)+'</strong><button class="sv-tool-outline" onclick="useSkillvayaQuoteTemplate('+Number(t.id)+')">Use in quotation</button></div><p class="sv-tool-muted">Timeline: '+esc(t.eta)+'</p><p>'+esc(t.message)+'</p></article>').join(''):'<p class="sv-tool-muted">No saved quotation templates yet.</p>')+'</div>';
 document.getElementById('svTemplateForm').addEventListener('submit',async e=>{e.preventDefault();const f=e.target,s=document.getElementById('svTemplateStatus'),b=f.querySelector('button[type=submit]');b.disabled=true;try{await svTierPreviewApi('/api/provider/quote-templates',{method:'POST',body:JSON.stringify({...Object.fromEntries(new FormData(f)),...(window.svSubscriptionTestMode?{test_tier:window.svSubscriptionTestTier||'local'}:{})})});await svRenderTemplates(body);const status=document.getElementById('svWorkToolStatus');if(status)status.textContent='Template saved.';}catch(x){s.textContent=x.message;}finally{b.disabled=false;}});
}
async function useSkillvayaQuoteTemplate(id){if(svWorkspaceRank<1){alert('This tool requires Priority or above.');return;}const d=await svTierPreviewApi('/api/provider/quote-templates');window.svWorkspaceTemplates=d.items||[];window.svPendingTemplateId=Number(id);openProviderTool('quote',0);}
async function svRenderInsights(body){
 const query=window.svSubscriptionTestMode?'?test_tier='+encodeURIComponent(window.svSubscriptionTestTier||'local'):'';
 const d=await svTierPreviewApi('/api/provider/insights'+query);
 const stats=[['Customer requests',d.job_requests],['Active jobs',d.active_jobs],['Quotes sent',d.quotes_sent],['Quotes accepted',d.quotes_accepted],['Messages',d.messages],['Photos/videos shared',d.media_shared],['Average rating',d.average_rating],['Rating count',d.rating_count]];
 body.innerHTML='<div class="sv-tool-metrics">'+stats.map(x=>'<div class="sv-tool-metric"><strong>'+esc(String(x[1]??0))+'</strong><span>'+esc(x[0])+'</span></div>').join('')+'</div><div class="sv-tool-card"><h3>What these numbers mean</h3><p class="sv-tool-muted">These are counts currently stored in Skillvaya. They are operational statistics, not guaranteed leads, earnings or conversion forecasts.</p><button class="sv-tool-outline" onclick="renderProviderTool(\'requests\')">Review requests</button></div>';
}
async function svRenderCampaigns(body){
 const query=window.svSubscriptionTestMode?'?test_tier='+encodeURIComponent(window.svSubscriptionTestTier||'local'):'';
 const d=await svTierPreviewApi('/api/provider/campaigns'+query),items=d.items||[];
 let html='<form id="svCampaignForm" class="sv-tool-card"><h3>Create a campaign draft</h3><div class="sv-tool-fields"><div class="sv-full"><label>Campaign title</label><input name="title" maxlength="120" required placeholder="e.g. Summer maintenance special"></div><div class="sv-full"><label>Campaign message / offer</label><textarea name="description" rows="4" minlength="10" maxlength="2000" required placeholder="Describe the offer, audience and conditions."></textarea></div><div><label>Planned start date</label><input name="starts_on" type="date"></div><div><label>Planned end date</label><input name="ends_on" type="date"></div></div><p class="sv-tool-muted">Saving creates a private draft. Publish makes it visible on your public provider listing; it does not purchase ads or guarantee homepage placement.</p><button type="submit" class="sv-tool-submit">Save campaign draft</button><div id="svCampaignStatus" class="sv-tool-status"></div></form><div class="sv-tool-card"><h3>Your campaigns</h3>';
 html+=items.length?items.map(x=>'<article class="sv-tool-card"><div class="sv-tool-row"><strong>'+esc(x.title)+'</strong><span class="sv-workstation-plan">'+esc(String(x.status||'draft').toUpperCase())+'</span></div><p>'+esc(x.description)+'</p><p class="sv-tool-muted">'+esc(x.starts_on||'No start date')+' – '+esc(x.ends_on||'No end date')+'</p>'+(x.status==='active'?'<p class="sv-growth-success">Published on your provider listing.</p>':'')+'<div class="sv-growth-inline-actions">'+(x.status==='active'?'<button class="sv-tool-outline" type="button" data-id="'+Number(x.id)+'" data-action="pause" onclick="svCampaignAction(this.dataset.id,this.dataset.action)">Pause campaign</button>':'<button class="sv-tool-submit" type="button" data-id="'+Number(x.id)+'" data-action="publish" onclick="svCampaignAction(this.dataset.id,this.dataset.action)">Publish campaign</button>')+'<button class="sv-tool-outline" type="button" data-id="'+Number(x.id)+'" data-action="delete" onclick="svCampaignAction(this.dataset.id,this.dataset.action)">Delete</button></div></article>').join(''):'<p class="sv-tool-muted">No campaign drafts yet.</p>';
 html+='</div>';body.innerHTML=html;
 document.getElementById('svCampaignForm').addEventListener('submit',async e=>{e.preventDefault();const f=e.target,b=f.querySelector('button[type=submit]'),status=document.getElementById('svCampaignStatus');b.disabled=true;try{await svTierPreviewApi('/api/provider/campaigns',{method:'POST',body:JSON.stringify({...Object.fromEntries(new FormData(f)),...(window.svSubscriptionTestMode?{test_tier:window.svSubscriptionTestTier||'local'}:{})})});await svRenderCampaigns(body);const el=document.getElementById('svWorkToolStatus');if(el)el.textContent='Campaign draft saved.';}catch(x){status.textContent=x.message;}finally{b.disabled=false;}});
}
async function svCampaignAction(id,action){if(action==='publish'&&!confirm('Publish this campaign to your public Skillvaya provider listing?'))return;if(action==='delete'&&!confirm('Delete this campaign?'))return;try{await svTierPreviewApi('/api/provider/campaigns',{method:'POST',body:JSON.stringify({action,id:Number(id),...(window.svSubscriptionTestMode?{test_tier:window.svSubscriptionTestTier||'local'}:{})})});await svRenderCampaigns(document.getElementById('svWorkToolBody'));}catch(e){alert(e.message);}}


// Keep owner tier-preview data isolated on the existing templates, campaigns and insights endpoints.
function svTierPreviewApi(path,options){
 options=options||{};const method=String(options.method||'GET').toUpperCase();
 if(!window.svSubscriptionTestMode||!me||me.role!=='admin')return api(path,options);
 const tier=window.svSubscriptionTestTier||'local';let url=path,body=options.body;
 if(method==='GET'||method==='HEAD'){url+=(url.includes('?')?'&':'?')+'test_tier='+encodeURIComponent(tier);}
 else{let data={};try{data=body?JSON.parse(body):{}}catch(e){}data.test_tier=tier;body=JSON.stringify(data);}
 return api(url,{...options,method,body});
}
// Business Plus and Spotlight tools call authenticated, plan-gated APIs and reuse the existing job/chat records.
async function svGrowthCall(feature,options){
 options=options||{};
 const method=String(options.method||'GET').toUpperCase();
 const query=new URLSearchParams();
 if(window.svSubscriptionTestMode&&me&&me.role==='admin')query.set('test_tier',window.svSubscriptionTestTier||'local');
 let body=options.body;
 if(method!=='GET'&&method!=='HEAD'){
  let obj={};try{obj=body?JSON.parse(body):{}}catch(e){}
  if(window.svSubscriptionTestMode&&me&&me.role==='admin')obj.test_tier=window.svSubscriptionTestTier||'local';
  body=JSON.stringify(obj);
 }
 const url='/api/provider/growth/'+encodeURIComponent(feature)+(method==='GET'&&query.size?'?'+query.toString():'');
 return api(url,{...options,method,body});
}
function svGrowthMoney(cents){return svMoney(cents,svProvCur());}
function svGrowthDate(value){if(!value)return 'Not set';const d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleString(undefined,{dateStyle:'medium',timeStyle:value.includes(':')?'short':undefined});}
function svGrowthStatus(status){const s=String(status||'draft').replaceAll('_',' ');const cl=['paid','completed','active','published','accepted','sent','issued'].includes(String(status||'').toLowerCase())?'':' warn';return '<span class="sv-growth-tag'+cl+'">'+esc(s)+'</span>';}
function svGrowthResult(id,message,ok=true){const el=document.getElementById(id);if(!el)return;el.className=ok?'sv-growth-success':'sv-growth-muted-alert';el.textContent=message;}
function svGrowthEmpty(message){return '<div class="sv-growth-empty">'+esc(message)+'</div>';}
function svGrowthActions(buttons){return '<div class="sv-growth-inline-actions">'+buttons.join('')+'</div>';}
async function svRenderGrowthPipeline(body){
 const d=await svGrowthCall('pipeline'),items=d.items||[],stages=['requested','quoted','accepted','scheduled','in_progress','completed'];
 body.innerHTML='<p class="sv-growth-intro">This view uses the existing customer requests and quotation records. Advancing a stage updates the same job your customer sees.</p><div class="sv-growth-kpis">'+stages.slice(0,4).map(k=>'<div class="sv-growth-kpi"><strong>'+items.filter(x=>String(x.status)===k).length+'</strong><span>'+esc(k.replaceAll('_',' '))+'</span></div>').join('')+'</div>'+(items.length?items.map(j=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(j.title||'Customer request')+'</h3>'+svGrowthStatus(j.status)+'</div><p>'+esc(j.customer_name||'Customer')+' · '+esc(j.business_name||'Your listing')+' · '+esc(j.area||'Area not supplied')+'</p><p>'+esc(j.description||'')+'</p><p class="sv-growth-small">Created '+esc(svGrowthDate(j.created_at))+' · '+(j.quotes||[]).length+' quote(s)</p>'+svGrowthActions([...(String(j.status)==='accepted'?[ '<button type="button" class="sv-tool-outline" onclick="svGrowthSetJobStatus('+Number(j.id)+',\'scheduled\')">Schedule</button>']:[]),...(String(j.status)==='scheduled'?[ '<button type="button" class="sv-tool-outline" onclick="svGrowthSetJobStatus('+Number(j.id)+',\'in_progress\')">Start work</button>']:[]),...(String(j.status)==='in_progress'?[ '<button type="button" class="sv-tool-submit" onclick="svGrowthSetJobStatus('+Number(j.id)+',\'completed\')">Mark completed</button>']:[]),...(String(j.status)==='requested'||String(j.status)==='quoted'?[ '<button type="button" class="sv-tool-submit" onclick="openProviderTool(\'quote\','+Number(j.id)+')">Prepare quotation</button>']:[]),'<button type="button" class="sv-tool-outline" onclick="openMessageConversation('+Number(j.business_id)+','+Number(j.customer_id)+')">Open customer chat</button>'])+'</article>').join(''):svGrowthEmpty('No requests are available in this pipeline yet.'))+'<div id="svGrowthPipelineStatus"></div>';
}
async function svGrowthSetJobStatus(jobId,status){try{await api('/api/jobs/'+Number(jobId)+'/status',{method:'POST',body:JSON.stringify({status})});const el=document.getElementById('svWorkToolStatus');if(el)el.textContent='Job status updated.';await svRenderGrowthPipeline(document.getElementById('svWorkToolBody'));}catch(e){svGrowthResult('svGrowthPipelineStatus',e.message,false);}}
async function svRenderBookings(body){
 const d=await svGrowthCall('bookings'),items=d.items||[];
 body.innerHTML='<p class="sv-growth-intro">Appointments are saved against your provider listing. Dates are shown in the device/browser time zone; use the customer details to coordinate changes.</p><form id="svBookingForm" class="sv-growth-form"><h3>Schedule an appointment</h3><div class="sv-tool-fields"><div><label>Booking / job title</label><input name="title" required maxlength="160" placeholder="e.g. Kitchen tap repair"></div><div><label>Customer name</label><input name="customer_name" maxlength="120" placeholder="Customer name"></div><div><label>Customer email or phone</label><input name="customer_contact" maxlength="200" placeholder="Optional contact details"></div><div><label>Start date & time</label><input name="starts_at" type="datetime-local" required></div><div><label>End date & time</label><input name="ends_at" type="datetime-local"></div><div class="sv-full"><label>Notes / address / preparation</label><textarea name="notes" maxlength="2000" placeholder="Useful visit notes"></textarea></div></div><button class="sv-tool-submit" type="submit">Save booking</button><div id="svBookingStatus" aria-live="polite"></div></form><h3>Upcoming & previous bookings</h3>'+(items.length?items.map(b=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(b.title)+'</h3>'+svGrowthStatus(b.status)+'</div><p>'+esc(b.customer_name||'Customer not named')+' · '+esc(b.customer_contact||'No contact supplied')+'</p><p><strong>Starts:</strong> '+esc(svGrowthDate(b.starts_at))+(b.ends_at?' · <strong>Ends:</strong> '+esc(svGrowthDate(b.ends_at)):'')+'</p><p>'+esc(b.notes||'')+'</p>'+svGrowthActions([...(b.status==='scheduled'?[ '<button class="sv-tool-outline" type="button" onclick="svGrowthBookingAction('+b.id+',\'completed\')">Mark completed</button>','<button class="sv-tool-outline" type="button" onclick="svGrowthBookingAction('+b.id+',\'cancelled\')">Cancel</button>']:[]),...(b.status==='completed'?[ '<button class="sv-tool-outline" type="button" onclick="svGrowthRequestReview('+Number(b.business_id)+','+Number(b.customer_id||0)+')">Request a review</button>']:[])])+'</article>').join(''):svGrowthEmpty('No bookings scheduled yet.')) ;
 const form=document.getElementById('svBookingForm');form.addEventListener('submit',async e=>{e.preventDefault();const btn=form.querySelector('button[type=submit]');btn.disabled=true;try{const d=Object.fromEntries(new FormData(form));await svGrowthCall('bookings',{method:'POST',body:JSON.stringify({action:'create',...d})});await svRenderBookings(body);svGrowthResult('svBookingStatus','Booking saved.');}catch(err){svGrowthResult('svBookingStatus',err.message,false);}finally{btn.disabled=false;}});
}
async function svGrowthBookingAction(id,status){if(status==='cancelled'&&!confirm('Cancel this booking?'))return;try{await svGrowthCall('bookings',{method:'POST',body:JSON.stringify({action:'status',id,status})});await svRenderBookings(document.getElementById('svWorkToolBody'));}catch(e){alert(e.message);}}
async function svRenderCRM(body){
 const d=await svGrowthCall('crm'),items=d.items||[];
 body.innerHTML='<p class="sv-growth-intro">CRM records are derived from real interactions in Skillvaya—messages, contacts, requests and quotations. Notes and tags are private to your provider team.</p><div class="sv-growth-grid">'+(items.length?items.map(c=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(c.name||'Customer')+'</h3><span class="sv-growth-pill">'+Number(c.request_count||0)+' requests</span></div><p>'+esc(c.email||'No email')+' · '+esc(c.phone||'No phone')+'</p><p class="sv-growth-small">Last interaction: '+esc(svGrowthDate(c.last_activity))+' · '+Number(c.message_count||0)+' messages · '+Number(c.quote_count||0)+' quotes</p><form class="sv-growth-form" onsubmit="svGrowthSaveCustomerNote(event,'+Number(c.customer_id)+')"><label>Private customer notes</label><textarea name="notes" rows="3" maxlength="3000" placeholder="Preferences, agreed details, service reminders">'+esc(c.notes||'')+'</textarea><label>Tags (comma-separated)</label><input name="tags" maxlength="400" value="'+esc(c.tags||'')+'" placeholder="repeat customer, urgent, maintenance"><button class="sv-tool-submit" style="margin-top:10px" type="submit">Save CRM notes</button><div id="svCrmStatus'+Number(c.customer_id)+'"></div></form><button class="sv-tool-outline" type="button" onclick="openMessageConversation('+Number(c.business_id)+','+Number(c.customer_id)+')">Open chat</button></article>').join(''):svGrowthEmpty('Customer history will appear here after contacts, messages or job requests.'))+'</div>';
}
async function svGrowthSaveCustomerNote(event,customerId){event.preventDefault();const f=event.currentTarget,d=Object.fromEntries(new FormData(f));try{await svGrowthCall('crm',{method:'POST',body:JSON.stringify({action:'save_note',customer_id:customerId,...d})});svGrowthResult('svCrmStatus'+customerId,'Customer notes saved.');}catch(e){svGrowthResult('svCrmStatus'+customerId,e.message,false);}}
async function svRenderFollowups(body){
 const d=await svGrowthCall('followups'),items=d.items||[],scheduled=d.followups||[];
 body.innerHTML='<p class="sv-growth-intro">Reminders are stored in Skillvaya. Creating a reminder does not send an automatic message; use the existing customer chat when you decide to follow up.</p><form id="svFollowupForm" class="sv-growth-form"><h3>Schedule a quote follow-up</h3><div class="sv-tool-fields"><div><label>Request / quotation</label><select name="job_id" required><option value="">Choose a pending quotation</option>'+items.map(x=>'<option value="'+Number(x.job_id)+'">#'+Number(x.job_id)+' · '+esc(x.title)+' — '+esc(x.customer_name||'Customer')+'</option>').join('')+'</select></div><div><label>Remind me on</label><input name="remind_at" type="datetime-local" required></div><div class="sv-full"><label>Private reminder note</label><input name="note" maxlength="300" placeholder="e.g. Ask if the customer needs clarification"></div></div><button type="submit" class="sv-tool-submit">Save reminder</button><div id="svFollowupStatus"></div></form><h3>Reminder list</h3>'+(scheduled.length?scheduled.map(f=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(f.title||'Quote follow-up')+'</h3>'+svGrowthStatus(f.status)+'</div><p>'+esc(f.customer_name||'Customer')+' · Remind at '+esc(svGrowthDate(f.remind_at))+'</p><p>'+esc(f.note||'')+'</p>'+ (f.status==='pending'?'<button type="button" class="sv-tool-outline" onclick="svGrowthFollowupAction('+f.id+',\'completed\')">Mark handled</button>':'')+'</article>').join(''):svGrowthEmpty('No follow-up reminders. Pending quotes are listed above when available.'))+(items.length?'<details class="sv-growth-section"><summary>Pending quotations ('+items.length+')</summary>'+items.map(x=>'<p class="sv-growth-small">#'+Number(x.job_id)+' · '+esc(x.title)+' · '+esc(x.customer_name)+' · '+esc(svGrowthDate(x.quote_created_at))+'</p>').join('')+'</details>':'');
 const form=document.getElementById('svFollowupForm');form.addEventListener('submit',async e=>{e.preventDefault();try{await svGrowthCall('followups',{method:'POST',body:JSON.stringify({action:'create',...Object.fromEntries(new FormData(form))})});await svRenderFollowups(body);svGrowthResult('svFollowupStatus','Reminder saved.');}catch(err){svGrowthResult('svFollowupStatus',err.message,false);}});
}
async function svGrowthFollowupAction(id,status){try{await svGrowthCall('followups',{method:'POST',body:JSON.stringify({action:'status',id,status})});await svRenderFollowups(document.getElementById('svWorkToolBody'));}catch(e){alert(e.message);}}
async function svRenderInvoices(body){
 const d=await svGrowthCall('invoices'),items=d.items||[],totals=d.totals||{};
 let html='<p class="sv-growth-intro">Invoice ledger and payment-status tracking. This does not collect money or replace a payment provider.</p>';
 html+='<div class="sv-growth-kpis"><div class="sv-growth-kpi"><strong>'+svGrowthMoney(totals.outstanding_cents||0)+'</strong><span>Outstanding balance</span></div><div class="sv-growth-kpi"><strong>'+Number(totals.overdue||0)+'</strong><span>Overdue invoices</span></div></div>';
 html+='<form id="svInvoiceForm" class="sv-growth-form"><h3>Create an invoice record</h3><div class="sv-tool-fields"><div><label>Customer name</label><input name="customer_name" required maxlength="120"></div><div><label>Customer email</label><input name="customer_email" type="email" maxlength="254"></div><div><label>Amount ('+svProvCur()+')</label><input name="amount_rands" type="number" min="0.01" step="0.01" max="10000000" required></div><div><label>Due date</label><input name="due_date" type="date"></div><div><label>Related request (optional job ID)</label><input name="job_id" type="number" min="1" placeholder="Job ID"></div><div class="sv-full"><label>Invoice description</label><textarea name="description" minlength="3" maxlength="2000" required placeholder="Work completed or supplied"></textarea></div></div><button class="sv-tool-submit" type="submit">Create invoice</button><div id="svInvoiceStatus"></div></form><h3>Invoice register</h3>';
 if(items.length){
  html+=items.map(function(i){
   let row='<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(i.invoice_number)+'</h3>'+svGrowthStatus(i.status)+'</div><p><strong>'+esc(i.customer_name)+'</strong> · '+esc(i.customer_email||'No email')+'</p><p>'+esc(i.description)+'</p>';
   row+='<div class="sv-growth-row"><span class="sv-growth-money">'+svGrowthMoney(i.amount_cents)+'</span><span class="sv-growth-small">Paid '+svGrowthMoney(i.amount_paid_cents)+' · Due '+esc(i.due_date||'not set')+'</span></div>';
   row+='<form class="sv-growth-form" onsubmit="svGrowthRecordInvoicePayment(event, '+Number(i.id)+')"><label>Record an additional payment ('+svProvCur()+')</label><div class="sv-growth-row"><input name="amount_rands" type="number" min="0.01" step="0.01" max="10000000" required style="max-width:200px"><button class="sv-tool-outline" type="submit">Record payment</button>';
   row+='<button class="sv-tool-outline" type="button" data-growth-action="invoice-status" data-id="'+Number(i.id)+'" data-status="issued" onclick="svGrowthAction(this)">Mark issued</button>';
   if(i.status!=='paid')row+='<button class="sv-tool-outline" type="button" data-growth-action="invoice-status" data-id="'+Number(i.id)+'" data-status="cancelled" onclick="svGrowthAction(this)">Cancel</button>';
   row+='</div><div id="svInvoiceItemStatus'+Number(i.id)+'"></div></form></article>';return row;
  }).join('');
 } else html+=svGrowthEmpty('No invoices recorded yet.');
 body.innerHTML=html;
 const form=document.getElementById('svInvoiceForm');
 form.addEventListener('submit',async function(e){e.preventDefault();const values=Object.fromEntries(new FormData(form));try{await svGrowthCall('invoices',{method:'POST',body:JSON.stringify({action:'create',...values})});await svRenderInvoices(body);}catch(err){svGrowthResult('svInvoiceStatus',err.message,false);}});
}
function svGrowthAction(button){const id=Number(button.dataset.id),status=String(button.dataset.status||'');if(button.dataset.growthAction==='invoice-status')svGrowthInvoiceAction(id,status);else if(button.dataset.growthAction==='package-status')svGrowthPackageAction(id,status);else if(button.dataset.growthAction==='offer-status')svGrowthOfferAction(id,status);}
async function svGrowthRecordInvoicePayment(event,id){event.preventDefault();const amount=event.currentTarget.elements.amount_rands.value;try{await svGrowthCall('invoices',{method:'POST',body:JSON.stringify({action:'record_payment',id,amount_rands:amount})});await svRenderInvoices(document.getElementById('svWorkToolBody'));}catch(e){svGrowthResult('svInvoiceItemStatus'+id,e.message,false);}}
async function svGrowthInvoiceAction(id,status){if(status==='cancelled'&&!confirm('Cancel this invoice record?'))return;try{await svGrowthCall('invoices',{method:'POST',body:JSON.stringify({action:'status',id,status})});await svRenderInvoices(document.getElementById('svWorkToolBody'));}catch(e){alert(e.message);}}
async function svRenderReviews(body){
 const d=await svGrowthCall('reviews'),items=d.items||[];
 body.innerHTML='<p class="sv-growth-intro">Reviews displayed here come from actual Skillvaya ratings. Replies are public-facing professional responses saved against the original rating. The review-request button sends through the existing chat.</p>'+(items.length?items.map(r=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(r.customer_name||'Customer')+'</h3><span class="sv-growth-pill">'+Number(r.stars)+'/5 ★</span></div><p class="sv-growth-small">Received '+esc(svGrowthDate(r.created_at))+'</p><p class="sv-growth-small">'+(r.reply?'Your reply: '+esc(r.reply):'No public reply yet.')+'</p><form class="sv-growth-form" onsubmit="svGrowthReplyReview(event,'+Number(r.id)+')"><label>Reply to review</label><textarea name="reply" minlength="3" maxlength="1500" required placeholder="Thank the customer and respond professionally">'+esc(r.reply||'')+'</textarea><button type="submit" class="sv-tool-submit">'+(r.reply?'Update reply':'Save reply')+'</button><div id="svReviewReplyStatus'+Number(r.id)+'"></div></form>'+ (Number(r.customer_id)?'<button type="button" class="sv-tool-outline" onclick="svGrowthRequestReview('+Number(r.business_id)+','+Number(r.customer_id)+')">Send review follow-up via chat</button>':'')+'</article>').join(''):svGrowthEmpty('No customer reviews have been recorded for this provider yet.'))+'<div id="svReviewStatus"></div>';
}
async function svGrowthReplyReview(event,id){event.preventDefault();const reply=event.currentTarget.elements.reply.value;try{await svGrowthCall('reviews',{method:'POST',body:JSON.stringify({action:'reply',rating_id:id,reply})});await svRenderReviews(document.getElementById('svWorkToolBody'));svGrowthResult('svReviewStatus','Review reply saved.');}catch(e){svGrowthResult('svReviewReplyStatus'+id,e.message,false);}}
async function svGrowthRequestReview(businessId,customerId){if(!businessId||!customerId){alert('A customer conversation is required to send a review request.');return;}const message='Thank you for working with us through Skillvaya. When you have a moment, we would appreciate an honest review of your experience. Your feedback helps customers make informed decisions.';if(!confirm('Send this review request to the customer in their existing Skillvaya chat?'))return;try{await api('/api/messages/send',{method:'POST',body:JSON.stringify({business_id:Number(businessId),customer_id:Number(customerId),message})});alert('Review request sent in the existing chat.');}catch(e){alert(e.message);}}
async function svRenderPackages(body){
 const d=await svGrowthCall('packages'),items=d.items||[];
 body.innerHTML='<p class="sv-growth-intro">Active packages are included in your public Skillvaya provider profile. Draft packages stay private; add-ons are presented as optional extras, not automatically charged.</p><form id="svPackageForm" class="sv-growth-form"><h3>Add a service package</h3><div class="sv-tool-fields"><div><label>Package name</label><input name="name" maxlength="120" required placeholder="e.g. Home maintenance basic"></div><div><label>Base price ('+svProvCur()+')</label><input name="price_rands" type="number" min="0.01" step="0.01" max="10000000" required></div><div class="sv-full"><label>Description</label><textarea name="description" minlength="3" maxlength="1500" required placeholder="What the package includes"></textarea></div><div class="sv-full"><label>Optional add-ons (one per line, format Name | Price)</label><textarea name="add_ons" maxlength="2000" placeholder="Emergency call-out | 250&#10;Extra item | 120"></textarea></div><div><label>Visibility</label><select name="status"><option value="active">Show on public profile</option><option value="draft">Keep as draft</option></select></div></div><button class="sv-tool-submit" type="submit">Save service package</button><div id="svPackageStatus"></div></form><div class="sv-growth-grid">'+(items.length?items.map(x=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(x.name)+'</h3>'+svGrowthStatus(x.status)+'</div><div class="sv-growth-money">'+svGrowthMoney(x.price_cents)+'</div><p>'+esc(x.description)+'</p>'+(x.add_ons||[]).map(a=>'<span class="sv-growth-pill">'+esc(a.name)+' · '+svGrowthMoney(a.price_cents)+'</span> ').join('')+svGrowthActions(['<button type="button" class="sv-tool-outline" onclick="svGrowthPackageAction('+x.id+',\''+(x.status==='active'?'draft':'active')+'\')">'+(x.status==='active'?'Unpublish':'Publish')+'</button>','<button type="button" class="sv-tool-outline" onclick="svGrowthPackageAction('+x.id+',\'delete\')">Delete</button>'])+'</article>').join(''):svGrowthEmpty('No service packages yet.'))+'</div>';
 const form=document.getElementById('svPackageForm');form.addEventListener('submit',async e=>{e.preventDefault();const v=Object.fromEntries(new FormData(form));try{await svGrowthCall('packages',{method:'POST',body:JSON.stringify({action:'create',...v})});await svRenderPackages(body);svGrowthResult('svPackageStatus','Package saved.');}catch(err){svGrowthResult('svPackageStatus',err.message,false);}});
}
async function svGrowthPackageAction(id,action){if(action==='delete'&&!confirm('Delete this service package?'))return;try{await svGrowthCall('packages',{method:'POST',body:JSON.stringify({action,id,status:action})});await svRenderPackages(document.getElementById('svWorkToolBody'));}catch(e){alert(e.message);}}
async function svRenderOffers(body){
 const d=await svGrowthCall('offers'),items=d.items||[],stats=d.stats||{};
 body.innerHTML='<p class="sv-growth-intro">Spotlight includes enhanced placement in Skillvaya’s directory, plus trackable offers. A promo code describes an offer; Skillvaya does not collect or deduct the discount at checkout.</p><div class="sv-growth-kpis"><div class="sv-growth-kpi"><strong>'+Number(stats.profile_views||0)+'</strong><span>Profile views</span></div><div class="sv-growth-kpi"><strong>'+Number(stats.leads||0)+'</strong><span>Tracked enquiries</span></div></div><form id="svOfferForm" class="sv-growth-form"><h3>Create an offer / voucher</h3><div class="sv-tool-fields"><div><label>Offer title</label><input name="title" maxlength="120" required></div><div><label>Voucher code</label><input name="code" maxlength="32" required placeholder="WELCOME10"></div><div class="sv-full"><label>Description &amp; conditions</label><textarea name="description" maxlength="1200" minlength="3" required></textarea></div><div><label>Discount type</label><select name="discount_type"><option value="percent">Percentage discount</option><option value="amount">Fixed amount ('+svProvCur()+')</option></select></div><div><label>Discount value</label><input name="discount_value" type="number" min="0.01" step="0.01" max="100000" required></div><div><label>Start date (optional)</label><input name="starts_on" type="date"></div><div><label>End date (optional)</label><input name="ends_on" type="date"></div><div><label>Use limit (0 = no stated limit)</label><input name="usage_limit" type="number" min="0" max="1000000" value="0"></div></div><button class="sv-tool-submit" type="submit">Save offer</button><div id="svOfferStatus"></div></form><div class="sv-growth-grid">'+(items.length?items.map(o=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(o.title)+'</h3>'+svGrowthStatus(o.status)+'</div><div class="sv-growth-money">'+(o.discount_type==='percent'?Number(o.discount_value)+'%':svMoney(Math.round(Number(o.discount_value)*100),svProvCur()))+' off</div><p>'+esc(o.description)+'</p><p><span class="sv-growth-pill">'+esc(o.code)+'</span> · '+Number(o.usage_count)+' uses'+(Number(o.usage_limit)>0?' / '+Number(o.usage_limit):'')+'</p><p class="sv-growth-small">'+esc(o.starts_on||'No start')+' – '+esc(o.ends_on||'No end')+'</p>'+svGrowthActions(['<button class="sv-tool-outline" type="button" onclick="svGrowthOfferAction('+o.id+',\''+(o.status==='active'?'paused':'active')+'\')">'+(o.status==='active'?'Pause':'Activate')+'</button>',...(o.status==='active'&&(!o.ends_on||o.ends_on>=new Date().toISOString().slice(0,10))?[ '<button class="sv-tool-outline" type="button" onclick="svGrowthOfferAction('+o.id+',\'redeem\')">Record redemption</button>']:[])])+'</article>').join(''):svGrowthEmpty('No offers or vouchers created yet.'))+'</div>';
 const form=document.getElementById('svOfferForm');form.addEventListener('submit',async e=>{e.preventDefault();try{const v=Object.fromEntries(new FormData(form));await svGrowthCall('offers',{method:'POST',body:JSON.stringify({action:'create',...v})});await svRenderOffers(body);svGrowthResult('svOfferStatus','Offer saved.');}catch(err){svGrowthResult('svOfferStatus',err.message,false);}});
}
async function svGrowthOfferAction(id,action){try{await svGrowthCall('offers',{method:'POST',body:JSON.stringify({action,id})});await svRenderOffers(document.getElementById('svWorkToolBody'));}catch(e){alert(e.message);}}
async function svRenderTeam(body){
 const d=await svGrowthCall('team'),members=d.items||[],jobs=d.jobs||[],assignments=d.assignments||[];
 body.innerHTML='<p class="sv-growth-intro">Invite staff by email, share the private invite link when email delivery is not configured, and assign actual Skillvaya job requests to active team members. Only accepted team members can be assigned.</p><form id="svTeamInviteForm" class="sv-growth-form"><h3>Invite a team member</h3><div class="sv-tool-fields"><div><label>Team member name</label><input name="name" maxlength="120" required></div><div><label>Email address</label><input name="email" type="email" maxlength="254" required></div><div><label>Team role</label><select name="team_role"><option value="staff">Staff member</option><option value="manager">Team manager</option></select></div></div><button class="sv-tool-submit" type="submit">Create invitation</button><div id="svTeamInviteStatus"></div></form><h3>Team roster</h3>'+(members.length?members.map(m=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(m.name)+'</h3>'+svGrowthStatus(m.status)+'</div><p>'+esc(m.email)+' · '+esc(m.team_role)+'</p>'+(m.status==='invited'?'<p class="sv-growth-small">Invite link: <code>'+esc(m.invite_url||'Open Copy Invite Link')+'</code></p><button class="sv-tool-outline" type="button" onclick="svCopyTeamInvite('+m.id+')">Copy invite link</button>':'')+'</article>').join(''):svGrowthEmpty('No team members yet.'))+'<form id="svTeamAssignmentForm" class="sv-growth-form"><h3>Assign a job request</h3><div class="sv-tool-fields"><div><label>Job request</label><select name="job_id" required><option value="">Choose a live request</option>'+jobs.map(j=>'<option value="'+j.id+'">#'+j.id+' · '+esc(j.title)+'</option>').join('')+'</select></div><div><label>Active team member</label><select name="team_member_id" required><option value="">Choose staff</option>'+members.filter(m=>m.status==='active').map(m=>'<option value="'+m.id+'">'+esc(m.name)+'</option>').join('')+'</select></div><div><label>Due date (optional)</label><input name="due_date" type="date"></div><div class="sv-full"><label>Assignment notes</label><textarea name="note" maxlength="1000"></textarea></div></div><button class="sv-tool-submit" type="submit">Save assignment</button><div id="svTeamAssignStatus"></div></form><h3>Assignments</h3>'+(assignments.length?assignments.map(a=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(a.job_title||'Job #'+a.job_id)+'</h3>'+svGrowthStatus(a.status)+'</div><p>'+esc(a.member_name||'Team member')+' · '+esc(a.due_date||'No due date')+'</p><p>'+esc(a.note||'')+'</p><button type="button" class="sv-tool-outline" onclick="svGrowthAssignmentAction('+a.id+',\'completed\')">Mark complete</button></article>').join(''):svGrowthEmpty('No jobs assigned yet.'));
 const inv=document.getElementById('svTeamInviteForm');inv.addEventListener('submit',async e=>{e.preventDefault();try{const d=await svGrowthCall('team',{method:'POST',body:JSON.stringify({action:'invite',...Object.fromEntries(new FormData(inv))})});await svRenderTeam(body);svGrowthResult('svTeamInviteStatus',d.email_sent?'Invitation sent by email.':'Invitation created. Copy and share its private link. '+(d.email_error||''));}catch(err){svGrowthResult('svTeamInviteStatus',err.message,false);}});
 const as=document.getElementById('svTeamAssignmentForm');as.addEventListener('submit',async e=>{e.preventDefault();try{await svGrowthCall('team',{method:'POST',body:JSON.stringify({action:'assign',...Object.fromEntries(new FormData(as))})});await svRenderTeam(body);svGrowthResult('svTeamAssignStatus','Job assignment saved.');}catch(err){svGrowthResult('svTeamAssignStatus',err.message,false);}});
}
async function svCopyTeamInvite(id){try{const d=await svGrowthCall('team',{method:'POST',body:JSON.stringify({action:'get_invite_link',id})});if(navigator.clipboard&&navigator.clipboard.writeText){await navigator.clipboard.writeText(d.invite_url);alert('Private invitation link copied.')}else prompt('Copy this private invitation link:',d.invite_url);}catch(e){alert(e.message);}}
async function svGrowthAssignmentAction(id,status){try{await svGrowthCall('team',{method:'POST',body:JSON.stringify({action:'assignment_status',id,status})});await svRenderTeam(document.getElementById('svWorkToolBody'));}catch(e){alert(e.message);}}
async function svRenderMarketing(body){
 const d=await svGrowthCall('marketing'),stats=d.stats||{},sources=d.sources||[],campaigns=d.campaigns||[];
 body.innerHTML='<p class="sv-growth-intro">Marketing counts come from recorded Skillvaya directory visits, campaign opens, contact actions and requests. They measure tracked activity, not guaranteed sales; visits before tracking was deployed are not retroactively counted.</p><div class="sv-growth-kpis">'+[['Listing views',stats.profile_views||0],['Campaign views',stats.campaign_views||0],['Campaign clicks',stats.campaign_clicks||0],['Tracked leads',stats.leads||0],['Requests',stats.requests||0],['Offer interactions',stats.offer_views||0]].map(x=>'<div class="sv-growth-kpi"><strong>'+Number(x[1])+'</strong><span>'+esc(x[0])+'</span></div>').join('')+'</div><div class="sv-growth-section"><h3>Lead sources</h3>'+(sources.length?'<div class="sv-growth-tablewrap"><table class="sv-growth-table"><thead><tr><th>Source</th><th>Visits</th><th>Clicks</th><th>Leads</th></tr></thead><tbody>'+sources.map(x=>'<tr><td>'+esc(x.source)+'</td><td>'+Number(x.visits||0)+'</td><td>'+Number(x.clicks||0)+'</td><td>'+Number(x.leads||0)+'</td></tr>').join('')+'</tbody></table></div>':svGrowthEmpty('No tracked lead-source events yet. Share a published campaign link or allow a visitor to open your directory profile.'))+'</div><div class="sv-growth-section"><h3>Campaign performance</h3>'+(campaigns.length?'<div class="sv-growth-tablewrap"><table class="sv-growth-table"><thead><tr><th>Campaign</th><th>Status</th><th>Views</th><th>Clicks</th><th>Leads</th></tr></thead><tbody>'+campaigns.map(c=>'<tr><td>'+esc(c.title)+'</td><td>'+esc(c.status)+'</td><td>'+Number(c.views||0)+'</td><td>'+Number(c.clicks||0)+'</td><td>'+Number(c.leads||0)+'</td></tr>').join('')+'</tbody></table></div>':svGrowthEmpty('No campaign statistics yet. Create a Spotlight campaign and publish it to begin measuring activity.'))+'</div>';
}
async function svRenderAnnouncements(body){
 const d=await svGrowthCall('announcements'),items=d.items||[];
 body.innerHTML='<p class="sv-growth-intro">Announcements are delivered through the existing Skillvaya chat, and only to customers who opted in and have a saved contact with this provider. Publish is a separate, confirmed action.</p><div class="sv-growth-muted-alert">Customer opt-in count: <strong>'+Number(d.opted_in_customers||0)+'</strong> · Customers who have not opted in are excluded.</div><form id="svAnnouncementForm" class="sv-growth-form"><h3>Draft a customer announcement</h3><div class="sv-tool-fields"><div class="sv-full"><label>Announcement title</label><input name="title" required maxlength="160"></div><div class="sv-full"><label>Message</label><textarea name="body" required minlength="10" maxlength="2000" rows="5" placeholder="A useful service update, special offer or seasonal reminder"></textarea></div></div><button type="submit" class="sv-tool-submit">Save draft</button><div id="svAnnouncementStatus"></div></form><h3>Previous announcements</h3>'+(items.length?items.map(a=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(a.title)+'</h3>'+svGrowthStatus(a.status)+'</div><p>'+esc(a.body)+'</p><p class="sv-growth-small">Recipients: '+Number(a.recipient_count||0)+' · Updated '+esc(svGrowthDate(a.updated_at))+'</p>'+(a.status==='draft'?'<button class="sv-tool-submit" type="button" onclick="svGrowthPublishAnnouncement('+a.id+')">Review & publish</button>':'')+'</article>').join(''):svGrowthEmpty('No announcements drafted yet.'));
 const f=document.getElementById('svAnnouncementForm');f.addEventListener('submit',async e=>{e.preventDefault();try{await svGrowthCall('announcements',{method:'POST',body:JSON.stringify({action:'create',...Object.fromEntries(new FormData(f))})});await svRenderAnnouncements(body);svGrowthResult('svAnnouncementStatus','Draft saved.');}catch(err){svGrowthResult('svAnnouncementStatus',err.message,false);}});
}
async function svGrowthPublishAnnouncement(id){if(!confirm('Publish this announcement to existing contacts who explicitly opted in? It will create messages in those customers’ existing chats.'))return;try{const d=await svGrowthCall('announcements',{method:'POST',body:JSON.stringify({action:'publish',id})});await svRenderAnnouncements(document.getElementById('svWorkToolBody'));alert('Announcement published to '+Number(d.recipient_count||0)+' opted-in customer(s).');}catch(e){alert(e.message);}}
async function loadCustomerMarketingPreference(){const card=document.getElementById('customerMarketingPreferenceCard');if(!card||!me||me.role!=='customer')return;try{const d=await api('/api/customer/marketing-preferences');document.getElementById('customerMarketingOptIn').checked=!!d.opted_in;card.classList.remove('hidden');}catch(e){card.classList.remove('hidden');const s=document.getElementById('customerMarketingPreferenceStatus');if(s)s.textContent='Could not load preference: '+e.message;}}
async function saveCustomerMarketingPreference(){const value=!!document.getElementById('customerMarketingOptIn').checked,status=document.getElementById('customerMarketingPreferenceStatus');try{const d=await api('/api/customer/marketing-preferences',{method:'POST',body:JSON.stringify({opted_in:value})});if(status)status.textContent=d.opted_in?'You opted in to relevant provider announcements. You can opt out at any time.':'Preference saved. You will not receive provider announcements.';}catch(e){if(status)status.textContent=e.message;}}
async function svRenderAutomation(body){
 const d=await svGrowthCall('automation'),rules=d.rules||[],alerts=d.alerts||[];
 body.innerHTML='<p class="sv-growth-intro">Enabled reminders are evaluated automatically about once an hour and can also be checked manually here. Alerts are in-app only; this does not send push notifications, email or customer messages.</p><div class="sv-growth-section"><h3>Automation rules</h3>'+rules.map(r=>'<label class="sv-growth-check"><input type="checkbox" '+(r.enabled?'checked':'')+' onchange="svGrowthToggleAutomation(\''+esc(r.rule_key)+'\',this.checked)"> <span><strong>'+esc(r.title)+'</strong><br>'+esc(r.description)+'</span></label>').join('')+'<div id="svAutomationStatus"></div><button type="button" class="sv-tool-submit" onclick="svGrowthEvaluateAutomation()">Check now &amp; refresh alerts</button></div><div class="sv-growth-section"><h3>In-app alerts</h3>'+(alerts.length?alerts.map(a=>'<article class="sv-growth-item"><div class="sv-growth-row"><h3>'+esc(a.title)+'</h3>'+svGrowthStatus(a.status)+'</div><p>'+esc(a.body)+'</p><p class="sv-growth-small">'+esc(svGrowthDate(a.created_at))+'</p></article>').join(''):svGrowthEmpty('No alerts right now. Alerts are evaluated from due quotes, bookings and invoice records.'))+'</div>';
}
async function svGrowthToggleAutomation(rule_key,enabled){try{await svGrowthCall('automation',{method:'POST',body:JSON.stringify({action:'toggle',rule_key,enabled})});svGrowthResult('svAutomationStatus','Rule preference saved.');}catch(e){svGrowthResult('svAutomationStatus',e.message,false);}}
async function svGrowthEvaluateAutomation(){try{await svGrowthCall('automation',{method:'POST',body:JSON.stringify({action:'evaluate'})});await svRenderAutomation(document.getElementById('svWorkToolBody'));}catch(e){alert(e.message);}}

function searchFromServices(){
  const field=document.getElementById('servicesSearchInput'),q=document.getElementById('q');
  if(q&&field)q.value=field.value.trim();
  const cat=document.getElementById('categories');if(cat)cat.value='All categories';chosen='All categories';
  loadBusinesses().then(()=>{renderServicesTab();}).catch(e=>console.warn('Service search failed',e));
}
function toggleServicesCategories(){
  // Global category browsing belongs to Home only; keep this directory category-free.
  const card=document.getElementById('servicesCategoriesCard');if(card){card.classList.add('hidden');card.style.display='none';}
}

function view(v){if(v==='services'&&(!me||(me.role!=='provider'&&me.role!=='admin'))){view('customer');return;}if(v==='provider'&&window.svSubscriptionTestMode){openSubscriptionTestProfile();return;}if(v==='settings'&&window.svSubscriptionTestMode){window.svSubscriptionTestMode=false;document.body.classList.remove('subscription-test-screen-mode');document.querySelectorAll('[data-sv-subtest-toolbar]').forEach(x=>x.remove());}
 // Release stale viewport locks before changing destinations; keep normal document scrolling enabled.
 if(v!=='messages'){if(typeof accountSubspaceCurrent!=='undefined'&&accountSubspaceCurrent)closeAccountSubspace();document.body.classList.remove('messages-conversation-open','account-subspace-open');document.body.style.removeProperty('overflow');}
 // Restore Contacts to its Account location whenever the user navigates elsewhere.
 if(v!=='messages')restoreMessagesCardHome();
 // Switching destinations must close any account subspace overlay first, or it can cover every bottom tab.
 if(typeof accountSubspaceCurrent!=='undefined'&&accountSubspaceCurrent)closeAccountSubspace();
 if(v==='admin'){location.href='/owner-app';return}
 const valid=['customer','provider','account','settings','messages','terms','providerDetailScreen','servicesTabScreen','svWorkstationTool','svWorkstationToolScreen','contactUsScreen','subscriptionTestApp','subscriptionTestProfileScreen','teamAssignmentsScreen','services','contact'];
 if(!valid.includes(v))v='customer';
 const screenIds=['customer','categoryScreen','provider','account','settings','messagesScreen','terms','providerDetailScreen','servicesTabScreen','svWorkstationToolScreen','contactUsScreen','subscriptionTestApp','subscriptionTestProfileScreen','teamAssignmentsScreen'];
 screenIds.forEach(id=>{const el=document.getElementById(id);if(el)el.classList.add('hidden')});
 const targetId=({services:'servicesTabScreen',svWorkstationTool:'svWorkstationToolScreen',contact:'contactUsScreen',messages:'messagesScreen'})[v]||v;
 // Keep inactive full-page destinations out of layout even if a later screen-specific CSS rule changes display.
 const destinationIds=['servicesTabScreen','contactUsScreen','messagesScreen'];
 destinationIds.forEach(id=>{const node=document.getElementById(id);if(node){const active=id===targetId;node.classList.toggle('hidden',!active);if(active){node.style.removeProperty('display');node.style.removeProperty('visibility');}else{node.style.setProperty('display','none','important');node.style.setProperty('visibility','hidden','important');}}});
 const target=document.getElementById(targetId);if(target){target.classList.remove('hidden');target.style.removeProperty('display');target.style.removeProperty('visibility');}
 document.body.classList.remove('category-screen-mode','account-screen-mode','messages-screen-mode','provider-detail-mode','provider-screen-mode');['platformRatingCard','platform-rating-card','rateSkillvayaCard'].forEach(id=>{const el=document.getElementById(id);if(el)el.classList.toggle('hidden',v!=='customer')});if(v==='settings')document.body.classList.add('account-screen-mode');if(v==='provider')document.body.classList.add('provider-screen-mode');const profileView=v==='settings';const customerDirectory=document.getElementById('customer');if(customerDirectory)customerDirectory.classList.toggle('hidden',v!=='customer');const categoryDirectory=document.getElementById('categoryScreen');if(categoryDirectory)categoryDirectory.classList.add('hidden');
  setHomeChrome(v==='customer');
  // Home alone owns the global category tiles and promotional directory panels.
  for(const id of ['designCategoryPanel','designPromoCard','hero-actions-wrap']){const el=document.getElementById(id);if(el)el.classList.toggle('hidden',v!=='customer');}
  const servicesCategoryBlock=document.getElementById('servicesTabCategories');if(servicesCategoryBlock){const block=servicesCategoryBlock.closest('.destination-card');if(block){block.classList.add('hidden');block.style.display='none';}}
  const servicesView=v==='services'||v==='svWorkstationTool'||v==='svWorkstationToolScreen';document.body.classList.toggle('provider-workstation-mode',servicesView);if(window.svSubscriptionTestMode)document.body.classList.add('subscription-test-screen-mode');
  const contactView=v==='contact';
  const sectionForView={services:'servicesTabScreen',svWorkstationTool:'svWorkstationToolScreen',contact:'contactUsScreen'};
  for(const [route,id] of Object.entries(sectionForView)){const node=document.getElementById(id);if(node)node.classList.toggle('hidden',v!==route);}
 document.querySelectorAll('.bottom-tabbar button').forEach(n=>n.classList.toggle('active',profileView?n.id==='nav-settings':v==='customer'?n.id==='nav-customer-bottom':v==='messages'?n.id==='nav-messages':v==='settings'?n.id==='nav-settings':servicesView?n.id==='nav-provider':false));
 const categoryScreen=document.getElementById('categoryScreen');if(categoryScreen)categoryScreen.classList.add('hidden');
 const ownerPublic=document.getElementById('owner-promotions-public');if(ownerPublic)ownerPublic.classList.toggle('hidden',v!=='customer');
  document.querySelectorAll('[id*=platformRating],[id*=platform-rating],[id*=rateSkillvaya]').forEach(rating=>{if(document.getElementById('settings').contains(rating))rating.classList.add('hidden');else rating.classList.toggle('hidden',v!=='customer')});
  for(const id of ['platformRatingCard','platform-rating-card','rateSkillvayaCard']){const rating=document.getElementById(id);if(rating)rating.classList.toggle('hidden',v!=='customer')}
 const hero=document.getElementById('hero');if(hero)hero.classList.toggle('hidden',v!=='customer');
 const customerNav=document.getElementById('nav-customer');if(customerNav)customerNav.classList.toggle('active',v==='customer');
 if(profileView)sessionInfo().catch(e=>console.warn('Profile refresh failed:',e.message));
 if(v==='provider')refreshProviderGate().catch(e=>console.warn('Provider studio refresh failed:',e.message));if(window.svSubscriptionTestMode&&v==='provider')mountSubscriptionTestToolbar(document.getElementById('provider'));
  if(servicesView&&v==='services'){loadProviderWorkstation().catch(e=>console.warn('Provider workspace load failed',e.message));}
  if(contactView){const status=document.getElementById('platformContactStatus');if(status)status.textContent='';}
 // Normalize scroll after the destination DOM and async layout settle. Contacts can change
 // document height; a single immediate scrollTo can run before that change completes.
 const resetDestinationScroll=()=>{window.scrollTo({top:0,left:0,behavior:'instant'});document.documentElement.scrollTop=0;document.body.scrollTop=0;};
 resetDestinationScroll();
 requestAnimationFrame(()=>{resetDestinationScroll();requestAnimationFrame(resetDestinationScroll);});
 setTimeout(resetDestinationScroll,80);
 setTimeout(resetDestinationScroll,260);
}


// Fix only the Home-tab return path: a delayed destination/layout callback can restore the old scroll offset after view('customer').
document.addEventListener('click',function(e){
  const home=e.target&&e.target.closest?e.target.closest('#nav-customer-bottom'):null;
  if(!home)return;
  const resetHomeScroll=()=>{
    const html=document.documentElement,body=document.body;
    const oldBehavior=html.style.scrollBehavior;
    html.style.scrollBehavior='auto';
    window.scrollTo(0,0);
    if(html)html.scrollTop=0;
    if(body)body.scrollTop=0;
    requestAnimationFrame(()=>{window.scrollTo(0,0);if(html)html.scrollTop=0;if(body)body.scrollTop=0;html.style.scrollBehavior=oldBehavior;});
  };
  resetHomeScroll();
  setTimeout(resetHomeScroll,80);
  setTimeout(resetHomeScroll,320);
},true);

function pickCat(c){const priorServices=document.getElementById('servicesTabScreen');categoryReturnView=priorServices&&!priorServices.classList.contains('hidden')?'services':'customer';document.body.classList.remove('account-screen-mode','messages-screen-mode');document.body.classList.add('category-screen-mode');['platformRatingCard','platform-rating-card','rateSkillvayaCard','owner-promotions-public'].forEach(id=>{const el=document.getElementById(id);if(el)el.classList.add('hidden')});directorySearchActive=false;const raw=String(c||'All categories').trim();const canonical=(cats||[]).find(x=>String(x).toLocaleLowerCase()===raw.toLocaleLowerCase())||raw;chosen=canonical;const select=document.getElementById('categories');if(select)select.value=canonical;if(canonical==='All categories'){backToCategories();return}setHomeChrome(false);for(const id of ['customer','servicesTabScreen','contactUsScreen','providerDetailScreen','provider','account','settings','terms','admin','services','contact']){const el=document.getElementById(id);if(el)el.classList.add('hidden')}const category=document.getElementById('categoryScreen');if(category)category.classList.remove('hidden');const title=document.getElementById('categoryScreenTitle');if(title)title.textContent=canonical;const count=document.getElementById('categoryScreenCount');if(count)count.textContent='Loading service providers.';const sort=document.getElementById('categoryScreenSort'),homeSort=document.getElementById('sort');if(sort&&homeSort)sort.value=homeSort.value;window.scrollTo(0,0);if(svFullDirectory){allBusinesses=svFullDirectory.filter(b=>String(b.category||'').toLowerCase()===String(canonical).toLowerCase());svRenderDirectory({businesses:allBusinesses});}loadBusinesses()}
function searchDirectory(){document.body.classList.remove('account-screen-mode','messages-screen-mode');document.body.classList.add('category-screen-mode');setHomeChrome(false);directorySearchActive=true;const field=document.getElementById('q'),raw=(field.value||'').trim(),key=raw.toLocaleLowerCase().replace(/[^a-z0-9]+/g,' ').trim();const aliases={'plumber':'Plumbers','plumbing':'Plumbers','electrician':'Electricians','doctor':'Doctors','private doctor':'Private doctors & clinics','private doctors':'Private doctors & clinics','clinic':'Private doctors & clinics','nurse':'Nurses','mechanic':'Mechanics','gardener':'Gardeners','gardeners':'Gardeners','landscaper':'Landscapers','lawyer':'Lawyers & legal services','lawyers':'Lawyers & legal services','graphic designer':'Graphic designers','builder':'Builders & construction','painter':'Painters & decorators','dentist':'Dentists','carpenter':'Carpenters & furniture'};const exact=(cats||[]).find(c=>c.toLocaleLowerCase().replace(/[^a-z0-9]+/g,' ').trim()===key);const service=exact||aliases[key];if(service){chosen=service;field.value='';}else{chosen='All categories';}document.getElementById('categories').value=chosen;document.getElementById('customer').classList.add('hidden');document.getElementById('categoryScreen').classList.remove('hidden');document.getElementById('categoryScreenSort').value=document.getElementById('sort').value;const area=(document.getElementById('area').value||'').trim();document.getElementById('categoryScreenTitle').textContent=service?service+(area?' in '+area:''):(raw?(area?'Search results for '+raw+' in '+area:'Search results for '+raw):(area?'Service providers in '+area:'All service providers'));document.getElementById('categoryScreenCount').textContent='Searching…';loadBusinesses();window.scrollTo(0,0)}
document.getElementById('categories').addEventListener('change',e=>pickCat(e.target.value));
function backToCategories(){directorySearchActive=false;chosen='All categories';const category=document.getElementById('categoryScreen');if(category)category.classList.add('hidden');document.getElementById('categoryScreenTitle').textContent='Service providers';document.getElementById('categories').value='All categories';if(categoryReturnView==='services'){view('services');return}view('customer');window.scrollTo(0,0);loadBusinesses()}
/* SV76-SPEED-01: caches that let every screen paint at once and refresh in the background. */
var svDirectoryHadCache=false,svFullDirectory=null;
function svCacheGet(k){try{return localStorage.getItem(k)||sessionStorage.getItem(k)}catch(_){return null}}
function svCacheSet(k,v){try{localStorage.setItem(k,v)}catch(_){try{sessionStorage.setItem(k,v)}catch(__){}}}
function svClearUserCaches(){try{window.svMessagesItems=null;[localStorage,sessionStorage].forEach(s=>{const del=[];for(let i=0;i<s.length;i++){const k=s.key(i);if(k&&(k.indexOf('sv_message_cache_v54_')===0||k.indexOf('sv_ws_profile_v1_')===0))del.push(k)}del.forEach(k=>s.removeItem(k))})}catch(_){}}
function svSaveDirectoryCache(p,d){try{if(!document.getElementById('q').value&&!document.getElementById('area').value&&chosen==='All categories'&&document.getElementById('sort').value==='featured'){svFullDirectory=d.businesses;localStorage.setItem('sv_dir_cache_v1',JSON.stringify({t:Date.now(),businesses:d.businesses.slice(0,80).map(b=>{const c=Object.assign({},b);delete c.my_rating;return c})}))}}catch(_){}}
function svPaintCachedDirectory(){try{const c=JSON.parse(localStorage.getItem('sv_dir_cache_v1')||'null');if(c&&Array.isArray(c.businesses)&&c.businesses.length&&Date.now()-Number(c.t||0)<6048e5){allBusinesses=c.businesses;svFullDirectory=c.businesses;svDirectoryHadCache=true;svRenderDirectory({businesses:c.businesses})}}catch(_){}}
async function svRefreshFavorites(){if(!(me&&me.role==='customer'))return;const f=await api('/api/favorites');favoriteIds=(f.items||[]).map(x=>Number(x.id));const cs=document.getElementById('categoryScreen');if(allBusinesses&&allBusinesses.length&&cs&&cs.classList.contains('hidden'))svRenderDirectory({businesses:allBusinesses})}
function svRenderDirectory(d){const categoryMode=!document.getElementById('categoryScreen').classList.contains('hidden');document.getElementById(categoryMode?'categoryScreenCount':'count').textContent=d.businesses.length+' matching businesses · contact for free';const dropdownCount=document.getElementById('providerDropdownCount'),dropdownHint=document.getElementById('providerDropdownHint'),dropdown=document.getElementById('providerDirectoryDropdown');if(dropdownCount)dropdownCount.textContent=d.businesses.length+' provider'+(d.businesses.length===1?'':'s');if(dropdownHint)dropdownHint.textContent=d.businesses.length?' Choose a provider below to view details':' No providers match this search yet';if(dropdown&&d.businesses.length===0)dropdown.open=true;if(!directorySearchActive)document.getElementById('categoryScreenTitle').textContent=chosen==='All categories'?'Service providers':chosen;document.getElementById('resTitle').textContent=chosen==='All categories'?'Providers you can contact':chosen;const markup=d.businesses.map(b=>'<article class="card biz '+b.plan+'" role="button" tabindex="0" aria-label="Open '+esc(b.name)+' provider profile" onclick="openProvider('+Number(b.id)+')" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();openProvider('+Number(b.id)+')}"><span class="tag '+(b.plan==='plus'?'plus':b.plan==='spotlight'?'spotlight':'')+'">'+(b.plan==='local'?'Local listing':b.plan==='priority'?'Priority · Sponsored':b.plan==='plus'?'Business Plus · Sponsored':'Spotlight · Sponsored')+'</span><h3>'+esc(b.name)+'</h3><div class="muted tiny">'+esc(b.category)+' · '+esc(b.area)+'</div><p>'+esc(b.description)+'</p>'+svTrustBadges(b)+svResponseBadge(b)+ratingMarkup(b.id,b.rating,b.rating_count,b.my_rating)+'<div style="margin-top:8px"><button class="ghost" type="button" onclick="event.stopPropagation();toggleFavorite('+Number(b.id)+')">'+(favoriteIds.includes(Number(b.id))?'♥ Saved provider':'♡ Save provider')+'</button></div><div class="provider-open"><span class="muted tiny">View details and contact options</span><button class="primary" type="button" onclick="event.stopPropagation();openProvider('+Number(b.id)+')">View provider</button></div></article>').join('')||'<div class="card"><h3>'+(document.getElementById('area').value.trim()?'No service providers found in '+esc(document.getElementById('area').value.trim()):'No active providers listed in this category yet')+'</h3><p class="muted">'+(document.getElementById('area').value.trim()?'There are currently no active '+esc(chosen==='All categories'?'matching service providers':chosen.toLowerCase())+' listed for this area. Try another town or suburb.':'This category is available, but no matching active provider profiles are published yet.')+'</p><button type="button" class="ghost" onclick="backToCategories()">Browse all service categories</button>'+(svCountryFilter()?' <button type="button" class="ghost" onclick="svShowAllCountries()">Show providers in all countries</button>':'')+'</div>';document.getElementById(categoryMode?'categoryScreenResults':'results').innerHTML=markup;document.getElementById('results').setAttribute('aria-label','Public service provider directory');}
async function loadBusinesses(){try{let p=new URLSearchParams({q:document.getElementById('q').value,area:document.getElementById('area').value,category:chosen,sort:document.getElementById('sort').value});p.set('country',svCountry());if(!svCountryFilter())p.delete('country');const svFavP=(me&&me.role==='customer')?api('/api/favorites').then(f=>(f.items||[]).map(x=>Number(x.id)),()=>[]):Promise.resolve([]);if(p.get('sort')==='near'){const pos=await svGetPosition();if(pos){p.set('lat',pos.lat);p.set('lng',pos.lng)}else{const a=(document.getElementById('area').value||'').trim();if(a){p.set('near_area',a);p.set('area','')}else{svNote('Turn on location, or type your town in the area box, to sort providers by distance.')}}}let d=await api('/api/businesses?'+p);allBusinesses=d.businesses;favoriteIds=await svFavP;svSaveDirectoryCache(p,d);svRenderDirectory(d);svOpenPendingProvider();}catch(e){
 console.error('Provider directory failed to load:',e);
 const message=e&&e.message?e.message:'Check your connection and try again.';
 const categoryScreen=document.getElementById('categoryScreen');
 const categoryMode=!!categoryScreen&&!categoryScreen.classList.contains('hidden');
 const results=document.getElementById(categoryMode?'categoryScreenResults':'results');
 if(results)results.innerHTML='<div class="card" role="alert"><h3>Service providers are temporarily unavailable</h3><p class="muted">'+esc(message)+'</p><button type="button" class="primary" onclick="loadBusinesses()">Try again</button></div>';
 const count=document.getElementById('providerDropdownCount');if(count)count.textContent='Retry needed';
 const hint=document.getElementById('providerDropdownHint');if(hint)hint.textContent='The list failed to load. Tap Try again.';
 const countText=document.getElementById('count');if(countText)countText.textContent='Could not load providers. Please retry.';
 const catCount=document.getElementById('categoryScreenCount');if(catCount)catCount.textContent='Could not load providers. Please retry.';
 }}
function openProvider(id){document.body.classList.remove('category-screen-mode','account-screen-mode','messages-screen-mode');
  const serviceScreen=document.getElementById('servicesTabScreen'),categoryScreenNow=document.getElementById('categoryScreen');
  providerDetailReturnView=serviceScreen&&!serviceScreen.classList.contains('hidden')?'services':categoryScreenNow&&!categoryScreenNow.classList.contains('hidden')?'category':'customer';
  setHomeChrome(false);
 const b=allBusinesses.find(x=>Number(x.id)===Number(id));if(!b)return;
 svTrackMarketingEvent(b.id,'profile_view',0,'directory');
 const studio=Boolean(b.owner_studio);
 const contact=['<button type="button" class="primary" onclick="contact('+Number(b.id)+')">＋ Make contact</button>'];
 if(b.email)contact.push('<a class="studio-action" href="mailto:'+esc(b.email)+'">✉ Email</a>');
 if(b.website&&(String(b.website).toLowerCase().indexOf('http://')===0||String(b.website).toLowerCase().indexOf('https://')===0))contact.push('<a class="studio-action" target="_blank" rel="noopener noreferrer" href="'+esc(b.website)+'">↗ Website</a>');
 contact.push('<button class="studio-action" type="button" onclick="svShareProvider('+Number(b.id)+')">↗ Share</button>');contact.push('<button class="studio-action" type="button" onclick="report('+Number(b.id)+')">⚑ Report listing</button>');
 const services=['Graphic Design','Branding & Identity','Web Design','Website Development','Coding & Custom Software','Android Apps','AI Solutions','UI/UX Design','Testing & Debugging','IT Support & Troubleshooting'];
 const icons=['✎','◇','▣','</>','⚙','▯','✺','▤','⌕','🔧'];
 const about=String(b.description||'').trim();
 if(studio){
 document.getElementById('providerDetailContent').innerHTML='<article class="studio-profile"><div class="studio-banner"><div class="studio-logo">S</div><div class="studio-brand"><h1>Skillvaya</h1><h2>Digital &amp; Creative Studio</h2><p>Ideas <b>·</b> Design <b>·</b> Code <b>·</b> Build <b>·</b> Support</p></div><div class="studio-slogan">Your Vision.<br>Our Skills.<br>Real Results.</div></div><div class="studio-facts"><div><span>▣</span><div><small>Business Type</small><strong>Digital &amp; Creative Studio</strong></div></div><div><span>📍</span><div><small>Service Area</small><strong>Online &amp; Remote</strong></div></div></div><div class="studio-contactfacts"><a href="tel:'+esc(String(b.phone||'+27 83 787 45 69').replace(/[^+0-9]/g,''))+'"><span>☎</span><div><small>Phone</small><strong>'+esc(b.phone||'+27 83 787 45 69')+'</strong></div></a><a href="mailto:'+esc(b.email||'Skillvaya@gmail.com')+'"><span>✉</span><div><small>Email</small><strong>'+esc(b.email||'Skillvaya@gmail.com')+'</strong></div></a></div><h2 class="studio-sectiontitle">Our Services</h2><div class="studio-services">'+services.map((x,i)=>'<div class="studio-service"><span class="studio-service-icon icon-'+i+'">'+icons[i]+'</span><strong>'+esc(x)+'</strong></div>').join('')+'</div><h2 class="studio-sectiontitle">About Us</h2><p class="studio-about">'+about+'</p><div id="providerGrowthPublicContent" class="sv-growth-public-content"></div><div class="studio-motto"><span>◎</span><div>Our goal is simple:<strong>Your success is our success.</strong></div></div><div class="studio-actions">'+contact.join('')+'</div><div class="studio-extra-actions"><button type="button" class="studio-action" onclick="toggleFavorite('+Number(b.id)+')">♡ Save provider</button><button type="button" class="studio-action" onclick="contact('+Number(b.id)+')">✉ Request a service</button>'+svTrustBadges(b)+svResponseBadge(b)+ratingMarkup(b.id,b.rating,b.rating_count,b.my_rating)+'</div></article>';
 }else{
 document.getElementById('providerDetailContent').innerHTML='<article class="provider-detail-hero"><span class="tag '+(b.plan==='plus'?'plus':b.plan==='spotlight'?'spotlight':'')+'">'+(b.plan==='local'?'Local listing':b.plan==='priority'?'Priority · Sponsored':b.plan==='plus'?'Business Plus · Sponsored':'Spotlight · Sponsored')+'</span><h1>'+esc(b.name)+'</h1><p class="muted">'+esc(b.category)+' · '+esc(b.area)+'</p><p>'+esc(b.description)+'</p><div id="svPortfolioSlot"></div><div id="providerGrowthPublicContent" class="sv-growth-public-content"></div>'+svTrustBadges(b)+svResponseBadge(b)+ratingMarkup(b.id,b.rating,b.rating_count,b.my_rating)+'<h3 style="margin-top:22px">Contact this service provider</h3><p class="muted">Choose how you would like to get in touch. Customer directory browsing is free.</p><div class="provider-detail-contact">'+contact.join('')+'</div></article>';svLoadPortfolio(Number(b.id),!!b.has_photos);
 }
 ['customer','provider','account','settings','terms','admin','categoryScreen','servicesTabScreen','contactUsScreen','services','contact'].forEach(x=>{const el=document.getElementById(x);if(el)el.classList.add('hidden')});setHomeChrome(false);document.getElementById('hero').classList.add('hidden');document.body.classList.add('provider-detail-mode');document.getElementById('providerDetailScreen').classList.remove('hidden');
 loadPublicProviderGrowth(Number(b.id));
 const ownerPublic=document.getElementById('owner-promotions-public');if(ownerPublic)ownerPublic.classList.add('hidden');
 document.querySelectorAll('.bottom-tabbar button').forEach(x=>x.classList.remove('active'));window.scrollTo(0,0)
}
function closeProviderDetail(){document.body.classList.remove('provider-detail-mode');const detail=document.getElementById('providerDetailScreen');if(detail)detail.classList.add('hidden');if(providerDetailReturnView==='category'){document.body.classList.add('category-screen-mode');const ids=['customer','provider','account','settings','terms','admin','servicesTabScreen','contactUsScreen','services','contact'];ids.forEach(id=>{const el=document.getElementById(id);if(el)el.classList.add('hidden')});setHomeChrome(false);const category=document.getElementById('categoryScreen');if(category)category.classList.remove('hidden');const hero=document.getElementById('hero');if(hero)hero.classList.add('hidden');const owner=document.getElementById('owner-promotions-public');if(owner)owner.classList.add('hidden');window.scrollTo(0,0);return}document.body.classList.remove('category-screen-mode');if(providerDetailReturnView==='services'){view('services');return}view('customer');window.scrollTo(0,0)}
function portfolioMarkup(raw){if(!raw)return '';let items=[];try{const v=JSON.parse(raw);if(Array.isArray(v))items=v}catch(e){if(/^https?:\/\//i.test(raw))return '<p><a href="'+esc(raw)+'" target="_blank" rel="noopener">View portfolio</a></p>'}if(!items.length)return '';return '<div>'+items.map(x=>x&&x.type==='application/pdf'?'<p><a href="'+x.data+'" download="'+esc(x.name)+'">Download catalogue: '+esc(x.name)+'</a></p>':x&&x.data&&x.data.indexOf('data:image/')===0?'<img loading="lazy" alt="'+esc(x.name||'Portfolio photo')+'" style="max-width:100%;max-height:220px;object-fit:contain;border-radius:10px;margin:6px" src="'+x.data+'">':'').join('')+'</div>'}
function svResponseBadge(b){return b&&b.response_label?'<div class="muted tiny sv-response-badge" style="margin:6px 0 2px;font-weight:600">⚡ '+esc(b.response_label)+'</div>':''}
function ratingMarkup(id,average,count,mine){const chosen=Number(mine)||0;const avg=Number(average)||0;return '<div class="ratingbox"><div class="muted tiny">Customer rating: <strong>'+(count?avg.toFixed(1):'Not rated yet')+'</strong> ('+(Number(count)||0)+' rating'+(Number(count)===1?'':'s')+')</div><div aria-label="Rate this service provider from 1 to 5 stars">'+[1,2,3,4,5].map(n=>'<button type="button" class="starbtn" aria-label="Rate '+n+' out of 5 stars" title="Rate '+n+' stars" onclick="event.stopPropagation();rateProvider('+Number(id)+','+n+')" style="background:transparent;border:0;padding:2px 5px;font-size:1.5rem;line-height:1.3;cursor:pointer;color:'+(n<=(chosen||Math.round(avg))?'#e6a400':'#9aa7b5')+'">★</button>').join('')+'</div></div>'}
async function rateProvider(id,stars){if(!me){view('settings');profileAuthMode('signin');alert('Sign in with a free customer account to rate this provider.');return}if(me.role!=='customer'){alert('Provider ratings are available from a customer account.');return}try{await api('/api/ratings',{method:'POST',body:JSON.stringify({target_type:'provider',business_id:id,stars})});await loadBusinesses();alert('Your '+stars+'-star rating has been saved. You can change it any time.')}catch(e){alert(e.message)}}
async function rateCustomer(businessId,customerId,stars){if(!me||me.role!=='provider'){alert('Sign in with your service-provider account to rate a customer.');return}try{await api('/api/ratings',{method:'POST',body:JSON.stringify({target_type:'customer',business_id:businessId,customer_id:customerId,stars})});alert('Your '+stars+'-star customer rating has been saved. You can update it any time.')}catch(e){alert(e.message)}}
function renderPlatformRatingStars(myRating=0){const root=document.getElementById('platformRatingStars');if(!root)return;root.innerHTML=[1,2,3,4,5].map(n=>'<button type="button" class="platform-rating-star" aria-label="Rate Skillvaya '+n+' out of 5 stars" title="Rate Skillvaya '+n+' stars" onclick="submitPlatformRating('+n+')" style="background:transparent;border:0;padding:2px 5px;font-size:1.7rem;line-height:1.3;cursor:pointer;color:'+(n<=(Number(myRating)||0)?'#e6a400':'#9aa7b5')+'">★</button>').join('')}
async function loadPlatformRating(){const summary=document.getElementById('platformRatingSummary');renderPlatformRatingStars(0);if(summary)summary.textContent='Loading Skillvaya ratings.';try{const d=await api('/api/platform-rating');if(summary)summary.textContent=(d.count?('Skillvaya rating: '+Number(d.average).toFixed(1)+' / 5 from '+d.count+' rating'+(d.count===1?'':'s')):'No ratings yet — be the first to rate Skillvaya.');renderPlatformRatingStars(d.my_rating||0)}catch(e){if(summary)summary.textContent='Stars are ready — the rating summary will retry when the connection is available.'}}
async function submitPlatformRating(stars){if(!me){view('settings');profileAuthMode('signin');document.getElementById('platformRatingMsg').textContent='Please sign in or create a free account to rate Skillvaya.';return}const msgEl=document.getElementById('platformRatingMsg'),summary=document.getElementById('platformRatingSummary');renderPlatformRatingStars(stars);if(msgEl)msgEl.textContent='Saving your rating?';try{const d=await api('/api/platform-rating',{method:'POST',body:JSON.stringify({stars})});renderPlatformRatingStars(d.my_rating||stars);if(summary&&Number.isFinite(Number(d.average))&&Number.isFinite(Number(d.count)))summary.textContent=d.count?('Skillvaya rating: '+Number(d.average).toFixed(1)+' / 5 from '+d.count+' rating'+(d.count===1?'':'s')):'No ratings yet — be the first to rate Skillvaya.';if(msgEl)msgEl.textContent='Thank you — your '+stars+'-star rating has been saved. You can change it any time.'}catch(e){if(msgEl)msgEl.textContent=e.message;loadPlatformRating().catch(()=>{})}}
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function svTrackMarketingEvent(businessId,eventType,campaignId=0,source='directory'){
 try{
  const key='sv_visit_key';let visitor=sessionStorage.getItem(key);
  if(!visitor){visitor=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+'-'+Math.random().toString(36).slice(2);sessionStorage.setItem(key,visitor);}
  fetch('/api/marketing/track',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({business_id:Number(businessId),event_type:eventType,campaign_id:Number(campaignId||0),source:String(source||'directory').slice(0,80),visitor_key:visitor})}).catch(()=>{});
 }catch(e){}
}
function svPublicGrowthMarkup(b,businessId){
 const campaigns=b.active_campaigns||[],offers=b.offers||[],packages=b.packages||[];
 let out='';
 if(campaigns.length){
  out+='<section class="sv-growth-public-section"><span class="sv-workstation-eyebrow">BUSINESS SPOTLIGHT</span><h3>Current promotion</h3><div class="sv-growth-public-banner"><span>FEATURED CAMPAIGN</span><strong>'+esc(campaigns[0].title)+'</strong><p>'+esc(campaigns[0].description)+'</p></div><div class="sv-growth-public-actions"><button type="button" onclick="svGrowthPublicContact('+Number(businessId)+',\'campaign\','+Number(campaigns[0].id)+')">Ask about this promotion</button></div></section>';
  campaigns.forEach(c=>svTrackMarketingEvent(Number(businessId),'campaign_view',Number(c.id),'provider-profile'));
 }
 if(offers.length){
  out+='<section class="sv-growth-public-section"><h3>Special offers &amp; vouchers</h3><div class="sv-growth-public-grid">'+offers.map(o=>'<article class="sv-growth-public-card"><h4>'+esc(o.title)+'</h4><div class="sv-growth-public-price">'+(o.discount_type==='percent'?Number(o.discount_value)+'% off':svMoney(Math.round(Number(o.discount_value)*100),svBizCur(businessId))+' off')+'</div><p>'+esc(o.description)+'</p><span class="sv-growth-public-code">'+esc(o.code)+'</span><p class="sv-growth-public-note">Ask this provider about the offer and its conditions. Skillvaya does not automatically deduct discounts or collect payment.</p><div class="sv-growth-public-actions"><button type="button" onclick="svGrowthPublicContact('+Number(businessId)+',\'offer\','+Number(o.id)+')">Ask about offer</button></div></article>').join('')+'</div></section>';
 }
 if(packages.length){
  out+='<section class="sv-growth-public-section"><h3>Service packages &amp; optional extras</h3><div class="sv-growth-public-grid">'+packages.map(p=>'<article class="sv-growth-public-card"><h4>'+esc(p.name)+'</h4><div class="sv-growth-public-price">'+svMoney(p.price_cents,svBizCur(businessId))+'</div><p>'+esc(p.description)+'</p>'+((p.add_ons||[]).length?'<p><strong>Optional add-ons</strong></p>'+p.add_ons.map(a=>'<p>＋ '+esc(a.name)+' · '+svMoney(a.price_cents,svBizCur(businessId))+'</p>').join(''):'')+'<div class="sv-growth-public-actions"><button type="button" onclick="svGrowthPublicContact('+Number(businessId)+',\'package\','+Number(p.id)+')">Request this package</button></div></article>').join('')+'</div><p class="sv-growth-public-note">Prices and scope are supplied by the provider. Confirm availability, add-ons and final quotation in chat before agreeing to work.</p></section>';
 }
 return out;
}
async function loadPublicProviderGrowth(businessId){
 const host=document.getElementById('providerGrowthPublicContent');if(!host)return;
 host.innerHTML='<div class="sv-growth-public-section"><p class="sv-growth-public-note">Checking current offers and service packages…</p></div>';
 try{
  const d=await api('/api/businesses/'+Number(businessId)+'/growth');
  if(!host.isConnected)return;
  host.innerHTML=svPublicGrowthMarkup(d,Number(businessId));
 }catch(e){if(host.isConnected)host.innerHTML='';}
}
function svGrowthPublicContact(businessId,kind,referenceId){
 if(kind==='campaign')svTrackMarketingEvent(Number(businessId),'campaign_click',Number(referenceId),'provider-profile');
 else if(kind==='offer')svTrackMarketingEvent(Number(businessId),'offer_view',0,'offer:'+Number(referenceId));
 else svTrackMarketingEvent(Number(businessId),'package_click',0,'package:'+Number(referenceId));
 contact(Number(businessId));
}
async function contact(id){if(!token||!me){view('settings');profileAuthMode('signin');alert('Please sign in to your Skillvaya account to message this provider.');return}if(!['customer','provider','admin'].includes(me.role)){alert('Please sign in with an active customer or service-provider account to contact this listing.');return}const b=allBusinesses.find(x=>Number(x.id)===Number(id));if(!b){alert('Provider listing is not available.');return}if(['customer','provider'].includes(me.role)&&Number(b.user_id)===Number(me.id)){alert('You cannot message your own provider listing. Choose another provider.');return}api('/api/contacts',{method:'POST',body:JSON.stringify({business_id:Number(id)})}).catch(e=>console.warn('Contact history will retry on refresh:',e.message));svTrackMarketingEvent(Number(id),'lead',0,'contact');showMessagesScreen(false);const root=document.getElementById('messagesList');if(!root)return;document.body.classList.add('messages-conversation-open');root.innerHTML='<div class="message-conversation-screen"><button type="button" class="ghost message-back-button" onclick="loadMessageThreads()">&#8592; Back to conversations</button><header class="message-conversation-header"><div class="conversation-avatar">'+esc(String(b.name||'S').slice(0,1).toUpperCase())+'</div><div><h2>'+esc(b.name)+'</h2><p class="muted tiny">Private conversation — only you and this provider can see your messages.</p></div></header><div class="message-bubbles" aria-live="polite"></div><form class="message-compose" onsubmit="sendInitialProviderMessage(event,'+Number(id)+')"><textarea name="message" required maxlength=4000 rows=3 placeholder="Write your message to this provider…"></textarea><div class="sv-voice-controls"><button type="button" class="ghost sv-voice-button" onclick="svToggleVoiceInput(this)" aria-pressed="false" title="Start voice typing" aria-label="Start voice typing">&#127908;</button><span class="sv-voice-status" aria-live="polite"></span></div><button class="primary" type="submit">Send message</button></form></div>';const field=root.querySelector('textarea');if(field)field.focus({preventScroll:true})}
async function sendInitialProviderMessage(e,businessId){e.preventDefault();const form=e.target,field=form.elements.message,message=field.value.trim(),button=form.querySelector('button[type=submit]');if(!message)return;const root=document.getElementById('messagesList');document.body.classList.add('messages-conversation-open');root.innerHTML='<div class="message-conversation-screen"><button type="button" class="ghost message-back-button" onclick="loadMessageThreads()">&#8592; Back to conversations</button><div class="message-bubbles"><div class="message-row mine"><div class="message-bubble">'+esc(message)+'<div class="message-time">Sending…</div></div></div></div><form class="message-compose" onsubmit="sendConversationReply(event,'+Number(businessId)+','+Number(me.id)+')"><textarea name="message" required maxlength="4000" rows="2" placeholder="Write a message…"></textarea><div class="sv-voice-controls"><button type="button" class="ghost sv-voice-button" onclick="svToggleVoiceInput(this)" aria-pressed="false" title="Start voice typing" aria-label="Start voice typing">&#127908;</button><span class="sv-voice-status" aria-live="polite"></span></div><button class="primary" type="submit">Send</button></form></div>';const bubbles=root.querySelector('.message-bubbles'),stamp=root.querySelector('.message-time'),next=root.querySelector('textarea');if(bubbles)bubbles.scrollTop=bubbles.scrollHeight;if(button)button.disabled=true;try{await api('/api/messages/send',{method:'POST',body:JSON.stringify({business_id:Number(businessId),message})});if(stamp)stamp.textContent=formatMessageDate(new Date().toISOString());if(next)next.focus({preventScroll:true});}catch(err){if(stamp)stamp.textContent='Not sent — '+err.message;if(next)next.value=message;}finally{if(button)button.disabled=false}}async function report(id){if(!me){view('settings');profileAuthMode('signin');alert('Please create a free profile or sign in to report a business.');return}let reason=prompt('Describe the concern. Reports are investigated fairly; allegations are not treated as proven facts.');if(!reason)return;try{await api('/api/complaints',{method:'POST',body:JSON.stringify({business_id:id,reason})});alert('Report submitted to the safety review queue.')}catch(e){alert(e.message)}}
document.getElementById('signup').onsubmit=async e=>{e.preventDefault();try{let fd=new FormData(e.target);let data=Object.fromEntries(fd);if(data.password!==data.confirm_password){msg('signupMsg','Passwords do not match. Please enter the same password in both fields.');return}delete data.confirm_password;data.accept_terms=document.querySelector('#signup input[name="accept_terms"]').checked;let d=await api('/api/signup',{method:'POST',body:JSON.stringify(data)});token=d.token;try{localStorage.setItem('skillvaya_user',JSON.stringify(d.user));sessionStorage.setItem('skillvaya_user',JSON.stringify(d.user))}catch(_){}localStorage.setItem('sv_token',token);localStorage.setItem('skillvaya_token',token);sessionStorage.removeItem('sv_token');sessionStorage.removeItem('skillvaya_token');msg('signupMsg','Profile created. Welcome, '+d.user.name+'.',true);view('settings');await sessionInfo(d.user)}catch(x){msg('signupMsg',x.message)}};
document.getElementById('login').onsubmit=async e=>{e.preventDefault();try{let data=Object.fromEntries(new FormData(e.target));data.accept_terms=document.getElementById('loginTerms').checked;let d=await api('/api/login',{method:'POST',body:JSON.stringify(data)});token=d.token;me=d.user;try{localStorage.setItem('skillvaya_user',JSON.stringify(me));sessionStorage.setItem('skillvaya_user',JSON.stringify(me))}catch(_){}maybeAcceptSkillvayaTeamInvite().catch(()=>{});loadMyTeamAccess().catch(()=>{});localStorage.removeItem('sv_token');localStorage.removeItem('skillvaya_token');sessionStorage.removeItem('sv_token');sessionStorage.removeItem('skillvaya_token');localStorage.setItem('sv_token',token);localStorage.setItem('skillvaya_token',token);sessionStorage.setItem('sv_token',token);sessionStorage.setItem('skillvaya_token',token);msg('loginMsg','Signed in successfully.',true);view('settings');await sessionInfo(d.user);if(me.role==='provider')refreshProviderGate();if(me.role==='admin'){const workerButton=document.getElementById('workerSideButton');if(workerButton)workerButton.classList.remove('hidden')}}catch(x){msg('loginMsg',x.message)}};
function setProfileEditing(enabled){const form=document.getElementById('profileForm');if(!form)return;['name','phone'].forEach(n=>{const el=form.elements[n];if(el)el.readOnly=!enabled});const save=document.getElementById('profileSaveActions'),edit=document.getElementById('editProfileButton');if(save)save.classList.toggle('hidden',!enabled);if(edit)edit.classList.toggle('hidden',!!enabled)}
function providerOptInNotice(text,good=false){const el=document.getElementById('providerOptInMsg')||document.getElementById('providerProfileNotice');if(!el)return;el.className='notice '+(good?'good':'bad');el.textContent=text}
async function becomeServiceProvider(){if(!me){view('settings');profileAuthMode('signin');return}if(me.role==='admin'){providerOptInNotice('Your owner account already has free provider access. Open Provider Studio to edit your existing Skillvaya profile.',true);view('provider');return}if(me.role==='provider'){providerOptInNotice('Your account is already set as a service provider.',true);view('provider');return}const b=document.getElementById('becomeProviderButton');if(b){b.disabled=true;b.textContent='Setting up provider access…'}try{const d=await api('/api/account/become-provider',{method:'POST',body:JSON.stringify({})});me=d.user;document.getElementById('profileIdentity').textContent=me.email+' · '+me.role;providerOptInNotice('Provider access is ready. Choose a plan to publish your service profile.',true);if(b){b.textContent='Provider access ready';b.disabled=true}await refreshProviderGate();drawPlans();const planRoot=document.getElementById('plans');const planCard=document.getElementById('providerPlansCard');if(planRoot&&planCard&&me&&me.role==='provider'&&!planRoot.querySelector('[data-plan]')){planCard.classList.remove('hidden');drawPlans()}view('provider')}catch(e){providerOptInNotice(e.message)}finally{if(b&&(!me||me.role!=='provider')){b.disabled=false;b.textContent='Become a Provider'}}}
function openWorkerSide(){if(!me||me.role!=='admin'){alert('This private workspace is available only to the authorised owner account.');return}const handoffToken=token||localStorage.getItem('skillvaya_token')||localStorage.getItem('sv_token')||sessionStorage.getItem('skillvaya_token')||sessionStorage.getItem('sv_token');if(!handoffToken){alert('Please sign in again to open your worker workspace.');profileAuthMode('signin');return}localStorage.setItem('skillvaya_owner_token',handoffToken);localStorage.setItem('skillvaya_token',handoffToken);localStorage.setItem('sv_token',handoffToken);sessionStorage.setItem('skillvaya_token',handoffToken);sessionStorage.setItem('sv_token',handoffToken);location.assign('/owner-app')}
async function sessionInfo(knownUser=null){try{let d=knownUser?{user:knownUser}:await api('/api/me');me=d.user;const bell=svEnsureNotificationBell();if(bell)bell.classList.toggle('is-visible',!!me);try{if(me&&svW()[me.country])localStorage.setItem('sv_country',me.country);else if(me&&token)api('/api/me/country',{method:'POST',body:JSON.stringify({country:svCountry()})}).then(()=>{me.country=svCountry()}).catch(()=>{})}catch(_){}try{svWorldInit()}catch(_){}if(me)svStartMessageLiveUpdates();try{if(token){localStorage.setItem('sv_token',token);localStorage.setItem('skillvaya_token',token)}}catch(_){}const workerButton=document.getElementById('workerSideButton');if(workerButton)workerButton.classList.toggle('hidden',me.role!=='admin');if(me.role==='admin'&&token)localStorage.setItem('skillvaya_owner_token',token);updateSkillvayaProviderTab();if(me.role==='customer')loadCustomerMarketingPreference().catch(()=>{});loadMyTeamAccess().catch(()=>{});maybeAcceptSkillvayaTeamInvite().catch(()=>{});updateSubscriptionTesterAccess();if(me&&typeof loadMessageThreads==='function')Promise.resolve().then(()=>loadMessageThreads().catch(()=>{}));document.getElementById('profileSettingsCard').classList.remove('hidden');document.getElementById('profileAuthTabs').classList.add('hidden');document.getElementById('signinPane').classList.add('hidden');document.getElementById('signupPane').classList.add('hidden');if(document.getElementById('profileForm')){document.getElementById('profileForm').elements.name.value=me.name||'';document.getElementById('profileForm').elements.phone.value=me.phone||'';document.getElementById('profileIdentity').textContent=me.email+' · '+me.role;setProfileEditing(false);const opt=document.getElementById('providerOptInCard');if(opt)opt.classList.toggle('hidden',me.role!=='customer');document.getElementById('profilePhotoPreview').src=me.profile_photo||document.getElementById('profilePhotoPreview').src;const headingPhoto=document.getElementById('profileHeadingPhoto');if(headingPhoto)headingPhoto.src=me.profile_photo||headingPhoto.src}return me}catch(e){if(token&&/sign in first|session|token/i.test(e.message)){token='';localStorage.removeItem('sv_token');localStorage.removeItem('skillvaya_token');localStorage.removeItem('skillvaya_user');sessionStorage.removeItem('sv_token');sessionStorage.removeItem('skillvaya_token');try{return await sessionInfo()}catch(_){}}me=null;updateSubscriptionTesterAccess();const c=document.getElementById('profileSettingsCard');if(c)c.classList.add('hidden');document.getElementById('profileAuthTabs').classList.remove('hidden');profileAuthMode('signin');return null}}
async function saveProfilePhoto(){const photoInput=document.getElementById('profilePhotoFile'),cameraInput=document.getElementById('profileCameraFile');const file=(photoInput&&photoInput.files&&photoInput.files[0])||(cameraInput&&cameraInput.files&&cameraInput.files[0]);if(!file){msg('photoMsg','Choose a picture or take a photo first.');return}if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>2*1024*1024){msg('photoMsg','Choose a JPG, PNG or WebP image up to 2 MB.');return}const button=document.getElementById('saveProfilePhotoButton');button.disabled=true;button.textContent='Uploading…';const reader=new FileReader();reader.onerror=()=>{button.disabled=false;button.textContent='Upload picture';msg('photoMsg','The selected image could not be read. Please choose it again.')};reader.onload=async()=>{try{const d=await api('/api/account/profile',{method:'POST',body:JSON.stringify({name:me.name,phone:me.phone||'',profile_photo:reader.result})});me=d.user;document.getElementById('profilePhotoPreview').src=me.profile_photo;const headingPhoto=document.getElementById('profileHeadingPhoto');if(headingPhoto)headingPhoto.src=me.profile_photo;if(photoInput)photoInput.value='';if(cameraInput)cameraInput.value='';document.getElementById('profilePhotoFileName').textContent='Profile picture uploaded successfully';msg('photoMsg','Profile picture saved.',true)}catch(e){msg('photoMsg',e.message)}finally{button.disabled=false;button.textContent='Upload picture'}};reader.readAsDataURL(file)}
function previewProfilePhotoInput(input){const otherInput=document.getElementById(input&&input.id==='profileCameraFile'?'profilePhotoFile':'profileCameraFile');if(otherInput)otherInput.value='';const file=input&&input.files&&input.files[0];if(!file)return;document.getElementById('profilePhotoFileName').textContent=file.name+' ('+(file.size/1024).toFixed(0)+' KB)';if(file.size<=2*1024*1024&&['image/jpeg','image/png','image/webp'].includes(file.type)){const r=new FileReader();r.onload=()=>document.getElementById('profilePhotoPreview').src=r.result;r.readAsDataURL(file)}else{msg('photoMsg','Choose a JPG, PNG or WebP image up to 2 MB.')}}
document.getElementById('profilePhotoFile').addEventListener('change',e=>previewProfilePhotoInput(e.target));document.getElementById('profileCameraFile').addEventListener('change',e=>previewProfilePhotoInput(e.target));
document.getElementById('providerPortfolioFiles').addEventListener('change',e=>{const files=Array.from(e.target.files||[]),total=files.reduce((n,f)=>n+f.size,0),out=document.getElementById('providerPortfolioPreview');if(!files.length){out.textContent='No files selected';return}out.textContent=files.map(f=>f.name+' ('+(f.size/1024).toFixed(0)+' KB)').join(' · ');if(total>2*1024*1024){out.textContent+=' — too large: maximum 2 MB combined';out.style.color='var(--red)'}else{out.style.color='var(--muted)'}});
let accountSubspaceReturnY=0,accountSubspaceCurrent='',accountSubspaceOriginalStyles=null,accountSubspacePlaceholder=null,accountSubspaceOriginalParent=null;function openAccountSubspace(which){const overlay=document.getElementById('accountSubspace'),content=document.getElementById('accountSubspaceContent'),card=document.getElementById(which==='favorites'?'favoritesCard':which==='messages'?'messagesCard':'jobsCard');if(!overlay||!content||!card)return;if(accountSubspaceCurrent)closeAccountSubspace();for(const id of ['messagesCard','jobsCard','favoritesCard']){const item=document.getElementById(id);if(item&&item!==card){item.classList.add('hidden');item.classList.remove('account-subspace-card')}}accountSubspaceOriginalParent=card.parentNode;if(!accountSubspaceOriginalParent)return;accountSubspacePlaceholder=document.createComment('account-subspace-placeholder');accountSubspaceOriginalParent.insertBefore(accountSubspacePlaceholder,card);content.replaceChildren();content.appendChild(card);card.classList.remove('hidden');card.classList.add('account-subspace-card');accountSubspaceCurrent=which;const title=document.getElementById('accountSubspaceTitle'),subtitle=document.getElementById('accountSubspaceSubtitle');if(title)title.textContent=which==='favorites'?'Saved providers':which==='messages'?'Messages & comments':'My Jobs & Quotes';if(subtitle)subtitle.textContent=which==='favorites'?'Your saved providers, ready when you need them.':which==='messages'?'Private conversations and follow-up comments between you and service providers.':'Review requests, quotes and job progress in one place.';document.querySelectorAll('#settings .account-link').forEach(n=>n.classList.toggle('active',which==='jobs'?n.textContent.toLowerCase().includes('my jobs'):which==='favorites'?n.textContent.toLowerCase().includes('saved'):n.textContent.toLowerCase().includes('chats')));accountSubspaceReturnY=window.scrollY||window.pageYOffset||0;accountSubspaceOriginalStyles={overflow:document.body.style.overflow};document.body.style.overflow='hidden';document.body.classList.add('account-subspace-open');overlay.classList.remove('hidden');overlay.style.display='block';overlay.setAttribute('aria-hidden','false');overlay.scrollTop=0;requestAnimationFrame(()=>{overlay.scrollTop=0;const back=document.getElementById('accountSubspaceBack');if(back)back.focus({preventScroll:true})})}function closeAccountSubspace(){const overlay=document.getElementById('accountSubspace');if(!overlay){document.body.classList.remove('account-subspace-open');document.body.style.removeProperty('overflow');accountSubspaceCurrent='';return;}if(overlay.classList.contains('hidden')){document.body.classList.remove('account-subspace-open');document.body.style.removeProperty('overflow');accountSubspaceCurrent='';return;}for(const id of ['messagesCard','jobsCard','favoritesCard']){const card=document.getElementById(id);if(card){card.classList.remove('account-subspace-card');card.classList.add('hidden')}}if(accountSubspacePlaceholder&&accountSubspaceOriginalParent){const movingCard=document.getElementById(accountSubspaceCurrent==='favorites'?'favoritesCard':accountSubspaceCurrent==='messages'?'messagesCard':'jobsCard');if(movingCard)accountSubspaceOriginalParent.insertBefore(movingCard,accountSubspacePlaceholder);accountSubspacePlaceholder.remove()}accountSubspacePlaceholder=null;accountSubspaceOriginalParent=null;overlay.classList.add('hidden');overlay.style.display='none';overlay.setAttribute('aria-hidden','true');document.body.classList.remove('account-subspace-open');if(accountSubspaceOriginalStyles){for(const [k,v] of Object.entries(accountSubspaceOriginalStyles))document.body.style[k]=v}accountSubspaceCurrent='';document.querySelectorAll('#settings .account-link').forEach(n=>n.classList.toggle('active',n.textContent.toLowerCase().includes('profile')));const back=document.getElementById('nav-settings');if(back)back.focus({preventScroll:true})}document.getElementById('accountSubspaceBack').addEventListener('click',closeAccountSubspace);document.addEventListener('keydown',e=>{if(e.key==='Escape'&&accountSubspaceCurrent)closeAccountSubspace()});
/* Skillvaya account hub: split profile, photo, and password into separate screens. */
(function(){
 const settings=document.getElementById('settings'),profile=document.getElementById('profileSettingsCard'),overlay=document.getElementById('accountSubspace'),content=document.getElementById('accountSubspaceContent');
 if(!settings||!profile||!overlay||!content)return;
 const findHeading=t=>Array.from(profile.querySelectorAll('h3')).find(n=>n.textContent.trim().toLowerCase()===t.toLowerCase());
 const ph=findHeading('Personal details'),sh=findHeading('Password & security');if(!ph||!sh)return;
 function wrapRange(start,stop,id){const w=document.createElement('div');w.id=id;w.className='card sv-account-detail-card';start.parentNode.insertBefore(w,start);let n=start;while(n&&n!==stop){const next=n.nextSibling;w.appendChild(n);n=next;}return w;}
 const first=profile.firstElementChild,photo=document.createElement('div');photo.id='svAccountPhotoSection';photo.className='card sv-account-detail-card';if(first){profile.insertBefore(photo,first);photo.appendChild(first);}
 const personal=wrapRange(ph,sh,'svAccountProfileSection');
 const actionRow=Array.from(profile.children).find(n=>n.querySelector&&n.querySelector('button[onclick*="logout()"]'));
 const security=document.createElement('div');security.id='svAccountSecuritySection';security.className='card sv-account-detail-card';profile.insertBefore(security,actionRow||null);
 let n=sh;while(n&&n!==actionRow){const next=n.nextSibling;if(n!==security)security.appendChild(n);n=next;}if(actionRow)actionRow.classList.add('hidden');
 profile.classList.add('sv-account-sections-separated');
 const dashboard=settings.querySelector('.account-dashboard-links');
 if(dashboard){
   const links=Array.from(dashboard.querySelectorAll('.account-link'));
   if(links[0]){links[0].removeAttribute('onclick');links[0].addEventListener('click',()=>openAccountSettingsScreen('profile'));}
   const make=(icon,title,sub,fn)=>{const b=document.createElement('button');b.type='button';b.className='account-link';b.innerHTML='<span>'+icon+'</span><strong>'+title+'</strong><small>'+sub+'</small>';b.addEventListener('click',fn);dashboard.appendChild(b);};
   make('📷','Profile picture','Update your photo',()=>openAccountSettingsScreen('photo'));
   make('🔐','Password & security','Change your password',()=>openAccountSettingsScreen('security'));
   make('↪','Log out','Sign out of Skillvaya',()=>{if(!me){profileAuthMode('signin');return;}if(typeof logout==='function')logout();});
   const logoutLink=Array.from(dashboard.querySelectorAll('.account-link')).find(n=>n.querySelector('strong')&&n.querySelector('strong').textContent==='Log out');if(logoutLink){logoutLink.id='svAccountLogoutLink';logoutLink.classList.add('hidden');}
   const originalSessionInfo=window.sessionInfo;if(typeof originalSessionInfo==='function')window.sessionInfo=async function(){const user=await originalSessionInfo();const b=document.getElementById('svAccountLogoutLink');if(b)b.classList.toggle('hidden',!user);return user;};
 }
 let moved=null,oldParent=null,oldNext=null;const originalClose=closeAccountSubspace;
 window.openAccountSettingsScreen=function(which){
   if(!me){profileAuthMode('signin');return;}
   const section=which==='photo'?photo:which==='security'?security:personal;if(!section)return;
   if(accountSubspaceCurrent)closeAccountSubspace();
   oldParent=section.parentNode;oldNext=section.nextSibling;moved=section;content.replaceChildren(section);
   document.getElementById('accountSubspaceTitle').textContent=which==='photo'?'Profile picture':which==='security'?'Password & security':'Profile & personal details';
   document.getElementById('accountSubspaceSubtitle').textContent=which==='photo'?'Choose or take a picture for your account.':which==='security'?'Update your password securely.':'Manage your personal details and contact information.';
   accountSubspaceCurrent='sv-account-detail';accountSubspaceOriginalStyles={overflow:document.body.style.overflow};document.body.style.overflow='hidden';document.body.classList.add('account-subspace-open');overlay.classList.remove('hidden');overlay.style.display='block';overlay.setAttribute('aria-hidden','false');overlay.scrollTop=0;
 };
 window.closeAccountSubspace=function(){
   if(moved){if(oldParent){if(oldNext&&oldNext.parentNode===oldParent)oldParent.insertBefore(moved,oldNext);else oldParent.appendChild(moved);}moved=null;oldParent=null;oldNext=null;content.replaceChildren();overlay.classList.add('hidden');overlay.style.display='none';overlay.setAttribute('aria-hidden','true');document.body.classList.remove('account-subspace-open');document.body.style.removeProperty('overflow');accountSubspaceCurrent='';return;}
   originalClose();
 };
 /* The original back-button listener captured the old handler; restore moved sections after it fires. */
 document.getElementById('accountSubspaceBack').addEventListener('click',()=>{if(!moved)return;if(oldParent){if(oldNext&&oldNext.parentNode===oldParent)oldParent.insertBefore(moved,oldNext);else oldParent.appendChild(moved);}moved=null;oldParent=null;oldNext=null;content.replaceChildren();accountSubspaceCurrent='';});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&moved)window.closeAccountSubspace()});
 const st=document.createElement('style');st.textContent='#settings .account-dashboard-links{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:22px 0}#settings .account-link{min-height:108px;text-align:left;display:grid;grid-template-columns:40px 1fr;grid-template-rows:auto auto;align-content:center;column-gap:11px;row-gap:4px;padding:15px;border:1px solid #dfe7f4;border-radius:17px;background:linear-gradient(145deg,#fff,#f7f9ff);box-shadow:0 7px 20px rgba(20,44,80,.055);color:#17213b}#settings .account-link>span{grid-row:1/3;width:40px;height:40px;display:grid;place-items:center;border-radius:13px;background:#eaf0ff;color:#2864f5;font-size:20px}#settings .account-link strong{font-size:14px;align-self:end}#settings .account-link small{font-size:12px;color:#6a7891;line-height:1.35}#settings #profileSettingsCard.sv-account-sections-separated{display:none!important}#accountSubspace .sv-account-detail-card{display:block!important;padding:clamp(16px,3vw,26px);margin:0!important;border:1px solid #e0e7f3;border-radius:20px;background:#fff}#accountSubspace .sv-account-detail-card h3{margin-top:0}@media(max-width:380px){#settings .account-dashboard-links{gap:8px}#settings .account-link{padding:12px;min-height:100px;grid-template-columns:34px 1fr;column-gap:8px}#settings .account-link>span{width:34px;height:34px;font-size:18px}#settings .account-link strong{font-size:12px}#settings .account-link small{font-size:10px}}';document.head.appendChild(st);
})();async function viewFavorites(){openAccountSubspace('favorites');const list=document.getElementById('favoritesList');list.textContent='Loading saved providers...';await loadFavorites()}
async function loadFavorites(){const list=document.getElementById('favoritesList');if(!me||!['customer','provider','admin'].includes(me.role)){list.textContent='Sign in with an active Skillvaya account to save providers.';return}try{const d=await api('/api/favorites');favoriteIds=(d.items||[]).map(b=>Number(b.id));list.innerHTML=(d.items||[]).map(b=>'<article class="card" style="margin:10px 0"><h3>'+esc(b.name)+'</h3><p class="muted">'+esc(b.category)+' · '+esc(b.area)+'</p><p>'+esc(b.description)+'</p>'+ratingMarkup(b.id,b.rating,b.rating_count,0)+'<div style="display:flex;gap:8px;flex-wrap:wrap"><button class="primary" onclick="view(\'home\');openProvider('+Number(b.id)+')">View provider</button><button class="ghost" onclick="toggleFavorite('+Number(b.id)+')">Remove saved provider</button></div></article>').join('')||'<p class="muted">No saved providers yet. Browse the directory and choose “Save provider” on a listing.</p>'}catch(e){list.textContent='Could not load saved providers: '+e.message}}
async function toggleFavorite(id){if(!token){view('settings');profileAuthMode('signin');alert('Sign in to your Skillvaya account to save providers.');return}try{const fresh=await api('/api/me');if(fresh&&fresh.user)me=fresh.user}catch(e){alert('Could not verify your account. Please sign in again.');return}if(!['customer','provider','admin'].includes(me.role)){alert('Sign in with an active Skillvaya account to save providers.');return}try{const d=await api('/api/favorites',{method:'POST',body:JSON.stringify({business_id:Number(id)})});favoriteIds=favoriteIds.filter(x=>x!==Number(id));if(d.saved)favoriteIds.push(Number(id));await loadBusinesses();const card=document.getElementById('favoritesCard');if(card&&!card.classList.contains('hidden'))await loadFavorites()}catch(e){alert(e.message)}}
async function viewJobs(){openAccountSubspace('jobs');const card=document.getElementById('jobsCard');const area=document.getElementById('jobCreateArea');area.classList.toggle('hidden',!me||!['customer','provider'].includes(me.role));const select=document.getElementById('jobBusinessId');if(me&&['customer','provider'].includes(me.role)){select.innerHTML='<option value="">Choose an active service provider</option>'+allBusinesses.filter(b=>b.status==='active'&&Number(b.user_id)!==Number(me.id)).map(b=>'<option value="'+Number(b.id)+'">'+esc(b.name)+' — '+esc(b.category)+' ('+esc(b.area)+')</option>').join('')}else{select.innerHTML=''}await loadJobs()}
async function loadJobs(){const list=document.getElementById('jobsList');if(!list)return;if(!me){list.textContent='Sign in to view jobs and quotes.';return}list.textContent='Loading your jobs…';try{const d=await api('/api/jobs');const items=d.items||[];if(!items.length){list.innerHTML='<p class="muted">No jobs yet. Customers can create a request above; provider job requests appear here when customers contact your listing.</p>';return}list.innerHTML=items.map(j=>'<article class="card" style="margin:12px 0;border:1px solid var(--line)"><div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><h3 style="margin:0">'+esc(j.title)+'</h3><span class="tag">'+esc(j.status.replaceAll('_',' '))+'</span></div><p class="muted">'+esc(j.business_name)+' · '+esc(j.area||j.business_area||'Area not specified')+' · '+esc(j.created_at.slice(0,10))+'</p><p>'+esc(j.description)+'</p>'+(j.preferred_date?'<p><b>Preferred date:</b> '+esc(j.preferred_date)+'</p>':'')+(j.budget_cents!==null&&j.budget_cents!==undefined?'<p><b>Budget:</b> R'+(Number(j.budget_cents)/100).toFixed(2)+'</p>':'')+(me.role==='provider'&&Number(j.provider_id)===Number(me.id)&&['requested','quoted'].includes(j.status)?'<button class="primary" onclick="sendJobQuote('+j.id+')">Create / update quote</button>':'')+(j.quotes||[]).map(q=>'<div class="notice '+(q.status==='accepted'?'good':'')+'" style="margin-top:10px"><b>Quote · R'+(Number(q.amount_cents)/100).toFixed(2)+'</b> · '+esc(q.status)+'<br><b>Timeline:</b> '+esc(q.eta)+'<br>'+esc(q.message)+(['customer','provider'].includes(me.role)&&Number(j.customer_id)===Number(me.id)&&q.status==='pending'&&['requested','quoted'].includes(j.status)?'<p><button class="primary" onclick="acceptJobQuote('+j.id+','+q.id+')">Accept quote</button></p>':'')+'</div>').join('')+(me.role==='provider'&&Number(j.provider_id)===Number(me.id)&&j.status==='accepted'?'<p><button class="ghost" onclick="updateJobStatus('+j.id+',\'scheduled\')">Schedule job</button></p>':'')+(me.role==='provider'&&Number(j.provider_id)===Number(me.id)&&j.status==='scheduled'?'<p><button class="ghost" onclick="updateJobStatus('+j.id+',\'in_progress\')">Mark in progress</button></p>':'')+(me.role==='provider'&&Number(j.provider_id)===Number(me.id)&&j.status==='in_progress'?'<p><button class="primary" onclick="updateJobStatus('+j.id+',\'completed\')">Mark completed</button></p>':'')+(['customer','provider'].includes(me.role)&&Number(j.customer_id)===Number(me.id)&&!['completed','cancelled'].includes(j.status)?'<p><button class="danger" onclick="updateJobStatus('+j.id+',\'cancelled\')">Cancel job request</button></p>':'')+'</article>').join('')}catch(e){list.textContent='Could not load jobs: '+e.message}}
async function sendJobQuote(id){const amount=prompt('Quote amount in '+svProvCur()+' (e.g. 850.00):');if(amount===null)return;const eta=prompt('Estimated timeline (e.g. 2 days; can start 3 November):');if(!eta)return;const message=prompt('What work and materials does this quote cover?');if(!message)return;try{await api('/api/jobs/'+id+'/quote',{method:'POST',body:JSON.stringify({amount_rands:amount,eta,message})});await loadJobs();alert('Quote sent to the customer.')}catch(e){alert(e.message)}}
async function acceptJobQuote(jobId,quoteId){if(!confirm('Accept this quote? The other quotes for this job will be declined.'))return;try{await api('/api/jobs/'+jobId+'/accept',{method:'POST',body:JSON.stringify({quote_id:quoteId})});await loadJobs()}catch(e){alert(e.message)}}
async function updateJobStatus(id,status){if(!confirm('Change job status to '+status.replaceAll('_',' ')+'?'))return;try{await api('/api/jobs/'+id+'/status',{method:'POST',body:JSON.stringify({status})});await loadJobs()}catch(e){alert(e.message)}}
document.getElementById('jobRequestForm').onsubmit=async e=>{e.preventDefault();const st=document.getElementById('jobRequestStatus');const d=Object.fromEntries(new FormData(e.target));st.textContent='Sending job request…';try{const result=await api('/api/jobs',{method:'POST',body:JSON.stringify(d)});st.textContent=result.message||'Job request sent.';e.target.reset();await loadJobs()}catch(err){st.textContent='Request not sent: '+err.message}};
function showMessagesScreen(loadThreads=true){
  document.body.classList.remove('messages-conversation-open');
  // Clear every modal/subspace before routing, then force the destination state.
  if(typeof accountSubspaceCurrent!=='undefined'&&accountSubspaceCurrent)closeAccountSubspace();
  const subspace=document.getElementById('accountSubspace');
  if(subspace)subspace.classList.add('hidden');
  view('messages');
  document.body.classList.remove('category-screen-mode','account-screen-mode','provider-detail-mode','provider-screen-mode');
  document.body.classList.add('messages-screen-mode');
  const screen=document.getElementById('messagesScreen');
  if(screen){screen.classList.remove('hidden');screen.removeAttribute('hidden');screen.style.setProperty('display','block','important');screen.style.setProperty('visibility','visible','important');}if(window.svSubscriptionTestMode)mountSubscriptionTestToolbar(screen);
  // Keep the bottom navigation available above the workspace.
  const nav=document.querySelector('.bottom-tabbar');
  if(nav){nav.style.display='grid';nav.style.zIndex='5000';}
  const mount=document.getElementById('messagesWorkspaceMount');
  const card=document.getElementById('messagesCard');
  if(mount&&card){if(!messagesCardHomeParent){messagesCardHomeParent=card.parentNode;messagesCardHomeNext=card.nextSibling;}mount.appendChild(card);card.classList.remove('hidden');card.classList.add('messages-workspace-card');card.style.removeProperty('display');card.style.removeProperty('visibility');}
  const root=document.getElementById('messagesList');
  if(!me){
    if(root)root.innerHTML='<div class="messages-empty-state"><h3>Contacts</h3><p>Your contacts will appear here when your account session is ready.</p></div>';
    window.scrollTo({top:0,behavior:'auto'});
    return;
  }
  if(loadThreads)loadMessageThreads().catch(e=>{if(root)root.textContent='Could not load conversations: '+e.message;});
}
function openSkillvayaStudioContact(){const b=(allBusinesses||[]).find(x=>String(x.name||'').toLowerCase().includes('skillvaya digital')&&String(x.category||'').toLowerCase().includes('software'));if(b){openProvider(b.id);return;}view('services');const search=document.getElementById('search');if(search){search.value='Skillvaya Digital & Creative Studio';if(typeof loadBusinesses==='function')loadBusinesses();}}
function viewMessages(){showMessagesScreen();}

let svActiveVideoCall=null,svIncomingVideoCall=null,svIncomingCallPoll=null,svVideoCallPollingStarted=false,svIncomingPollBusy=false,svIncomingWakeHandlersRegistered=false,svIncomingAcceptingCallId=null,svProcessedIncomingCalls=new Set();
function svEnsureCallOverlays(){
 let modal=document.getElementById('svVideoCallModal');
 if(!modal){
  modal=document.createElement('div');modal.id='svVideoCallModal';modal.className='sv-call-overlay hidden';modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');modal.setAttribute('aria-label','Skillvaya video call');
  modal.innerHTML='<div class="sv-call-panel"><header class="sv-call-header"><div><h2 id="svCallTitle">Skillvaya video call</h2><p id="svCallState" class="sv-call-state">Preparing your camera and microphone…</p></div><button type="button" class="sv-tool-outline" onclick="closeSkillvayaVideoCall(true)">Close</button></header><div class="sv-call-videos"><div class="sv-call-remote-wrap"><video id="svCallRemoteVideo" autoplay playsinline></video><span class="sv-call-video-label">Other participant</span></div><div class="sv-call-local-wrap"><video id="svCallLocalVideo" autoplay playsinline muted></video><span class="sv-call-video-label">You</span></div></div><div class="sv-call-actions"><button type="button" onclick="toggleSkillvayaCallMic()" aria-label="Mute or unmute call microphone">Mute / unmute</button><button type="button" class="sv-call-end" onclick="closeSkillvayaVideoCall(true)" aria-label="End call">End call</button><button type="button" onclick="toggleSkillvayaCallCamera()" aria-label="Turn call camera on or off">Camera on / off</button></div><p class="sv-call-note">The call uses your device camera and microphone. Skillvaya exchanges connection signals; media travels peer-to-peer when the network allows it. Some networks may require TURN relay configuration.</p></div>';
  document.body.appendChild(modal);
 }
   if(!modal.querySelector('.sv-call-audio-only')){const audioOnly=document.createElement('div');audioOnly.className='sv-call-audio-only';audioOnly.innerHTML='<div class="sv-call-audio-avatar">☎</div><strong>Skillvaya voice call</strong><span>Audio only</span>';const actions=modal.querySelector('.sv-call-actions');if(actions)modal.querySelector('.sv-call-panel').insertBefore(audioOnly,actions);}
   const localPreview=modal.querySelector('.sv-call-local-wrap');
  if(localPreview&&!localPreview.dataset.dragReady){localPreview.dataset.dragReady='1';localPreview.addEventListener('pointerdown',e=>{if(e.button!==undefined&&e.button!==0)return;const r=localPreview.getBoundingClientRect();localPreview.setPointerCapture&&localPreview.setPointerCapture(e.pointerId);localPreview.dataset.dragX=String(e.clientX-r.left);localPreview.dataset.dragY=String(e.clientY-r.top);e.preventDefault();});localPreview.addEventListener('pointermove',e=>{if(!localPreview.hasPointerCapture||!localPreview.hasPointerCapture(e.pointerId))return;const area=localPreview.parentElement,ar=area.getBoundingClientRect(),r=localPreview.getBoundingClientRect(),x=e.clientX-ar.left-Number(localPreview.dataset.dragX||0),y=e.clientY-ar.top-Number(localPreview.dataset.dragY||0);localPreview.style.left=Math.max(0,Math.min(Math.max(0,ar.width-r.width),x))+'px';localPreview.style.top=Math.max(0,Math.min(Math.max(0,ar.height-r.height),y))+'px';localPreview.style.right='auto';localPreview.style.bottom='auto';});}
if(!document.getElementById('svIncomingVideoCall')){
  const incoming=document.createElement('div');incoming.id='svIncomingVideoCall';incoming.className='sv-incoming-panel';incoming.hidden=true;
  incoming.innerHTML='<div class="sv-workstation-eyebrow">Incoming Skillvaya call</div><h3 id="svIncomingTitle">Video call</h3><p id="svIncomingDetail" class="sv-tool-muted">A contact is calling you.</p><div class="sv-incoming-actions"><button class="sv-call-accept" type="button" onclick="acceptSkillvayaVideoCall()">Accept</button><button class="sv-call-decline" type="button" onclick="declineSkillvayaVideoCall()">Decline</button></div>';
  document.body.appendChild(incoming);
 }
}
function svSetCallState(text){const el=document.getElementById('svCallState');if(el)el.textContent=text;}
let svIncomingAlertTimer=null,svIncomingAlertAudio=null,svIncomingAlertId='';
function svPlayIncomingCallTone(){try{const AudioCtx=window.AudioContext||window.webkitAudioContext;if(!AudioCtx)return;if(!svIncomingAlertAudio)svIncomingAlertAudio=new AudioCtx();if(svIncomingAlertAudio.state==='suspended')svIncomingAlertAudio.resume().catch(()=>{});const ctx=svIncomingAlertAudio,osc=ctx.createOscillator(),gain=ctx.createGain();osc.type='sine';osc.frequency.value=760;gain.gain.setValueAtTime(0.0001,ctx.currentTime);gain.gain.exponentialRampToValueAtTime(0.055,ctx.currentTime+0.025);gain.gain.setValueAtTime(0.055,ctx.currentTime+0.22);gain.gain.exponentialRampToValueAtTime(0.0001,ctx.currentTime+0.32);osc.connect(gain);gain.connect(ctx.destination);osc.start();osc.stop(ctx.currentTime+0.34);}catch(_){}}
function svStopIncomingCallAlert(){if(svIncomingAlertTimer){clearInterval(svIncomingAlertTimer);svIncomingAlertTimer=null;}try{if(window.SkillvayaCallRinger&&typeof window.SkillvayaCallRinger.stop==='function')window.SkillvayaCallRinger.stop()}catch(_){}try{if(navigator.vibrate)navigator.vibrate(0)}catch(_){}const p=document.getElementById('svIncomingVideoCall');if(p)p.classList.remove('sv-call-ringing');svIncomingAlertId='';}
function svStartIncomingCallAlert(incoming){const id=String(incoming&&incoming.id||'');if(!id||svIncomingAlertId===id)return;svStopIncomingCallAlert();svIncomingAlertId=id;const p=document.getElementById('svIncomingVideoCall');if(p)p.classList.add('sv-call-ringing');let nativeRinger=false;try{if(window.SkillvayaCallRinger&&typeof window.SkillvayaCallRinger.start==='function'){window.SkillvayaCallRinger.start(String(incoming.caller_name||'Skillvaya contact'));nativeRinger=true;}}catch(_){}if(!nativeRinger)svPlayIncomingCallTone();try{if(!nativeRinger&&navigator.vibrate)navigator.vibrate([350,180,350,850])}catch(_){}if('Notification'in window&&Notification.permission==='granted'){try{const n=new Notification('Skillvaya calling',{body:(incoming.caller_name||'Your contact')+' is calling you.',tag:'skillvaya-call-'+id,requireInteraction:true});n.onclick=()=>{try{window.focus()}catch(_){}n.close()}}catch(_){}}svIncomingAlertTimer=setInterval(()=>{if(!svIncomingAlertId)return;if(!nativeRinger&&document.visibilityState==='visible')svPlayIncomingCallTone();try{if(!nativeRinger&&navigator.vibrate)navigator.vibrate([350,180,350,850])}catch(_){}},1900);}
function svShowCallModal(title,state,mode){svEnsureCallOverlays();const modal=document.getElementById('svVideoCallModal');modal.classList.toggle('sv-call-voice-only',mode==='voice');modal.setAttribute('aria-label',mode==='voice'?'Skillvaya voice call':'Skillvaya video call');const camera=modal.querySelector('.sv-call-actions button[aria-label="Turn call camera on or off"]');if(camera)camera.hidden=mode==='voice';modal.classList.remove('hidden');const t=document.getElementById('svCallTitle');if(t)t.textContent=title||(mode==='voice'?'Skillvaya voice call':'Skillvaya video call');svSetCallState(state||'Connecting…');}
function svSetLocalStream(stream){const v=document.getElementById('svCallLocalVideo');if(v){v.srcObject=stream;v.play().catch(()=>{});}}
function svSetRemoteStream(stream){const v=document.getElementById('svCallRemoteVideo');if(v){v.srcObject=stream;v.play().catch(()=>{});}}
let svIceCache=null,svIceCacheAt=0;
async function svGetIceServers(){const fallback=[{urls:'stun:stun.l.google.com:19302'},{urls:'stun:stun1.l.google.com:19302'}];if(svIceCache&&Date.now()-svIceCacheAt<300000)return svIceCache;try{const d=await Promise.race([api('/api/ice-servers'),new Promise((_,rej)=>setTimeout(()=>rej(new Error('timeout')),2500))]);if(d&&Array.isArray(d.iceServers)&&d.iceServers.length){svIceCache=d.iceServers;svIceCacheAt=Date.now();return svIceCache}}catch(_){}return fallback}
async function svCreatePeer(call){
  const pc=new RTCPeerConnection({iceServers:await svGetIceServers(),iceCandidatePoolSize:10,bundlePolicy:'max-bundle'});
  call.pc=pc;call.remoteStream=new MediaStream();svSetRemoteStream(call.remoteStream);
  // Reserve audio/video media lines before camera permissions finish, so the recipient can be rung immediately.
  // SV77-CALL-MEDIA-01: only the CALLER creates transceivers. The answerer must reuse the transceivers created by the offer
  // (addTransceiver() ones are never matched to offer m-lines, which made every answer receive-only = one-way audio/video).
  if(call.isCaller){call.audioSender=pc.addTransceiver('audio',{direction:'sendrecv'}).sender;
  call.videoSender=call.mediaMode==='video'?pc.addTransceiver('video',{direction:'sendrecv'}).sender:null;}
  pc.ontrack=e=>{if(e.streams&&e.streams[0])e.streams[0].getTracks().forEach(t=>{if(!call.remoteStream.getTracks().some(x=>x.id===t.id))call.remoteStream.addTrack(t);});else if(e.track&&!call.remoteStream.getTracks().some(x=>x.id===e.track.id))call.remoteStream.addTrack(e.track);};
  pc.onicecandidate=e=>{if(!e.candidate)return;const c=e.candidate.toJSON?e.candidate.toJSON():{candidate:e.candidate.candidate,sdpMid:e.candidate.sdpMid,sdpMLineIndex:e.candidate.sdpMLineIndex,usernameFragment:e.candidate.usernameFragment};if(!call.callId){call.pendingCandidates.push(c);return;}api('/api/video-calls',{method:'POST',body:JSON.stringify({action:'candidate',call_id:call.callId,candidate:c})}).catch(err=>svSetCallState('Network candidate could not be sent: '+err.message));};
  pc.onconnectionstatechange=()=>{if(!svActiveVideoCall||svActiveVideoCall.callId!==call.callId)return;const state=pc.connectionState;if(state==='connected')svSetCallState(call.mediaMode==='voice'?'Voice call connected — microphone is live':'Connected — camera and microphone are live');else if(state==='connecting')svSetCallState('Connecting to the other participant…');else if(state==='disconnected')svSetCallState('Connection interrupted; attempting to reconnect…');else if(state==='failed')svSetCallState('Could not connect directly. This network may require TURN relay configuration.');};
  return pc;
}
function svBindAnswerSenders(call){
  // SV77-CALL-MEDIA-01: take the offer's own transceivers and make them send as well as receive.
  const trs=call.pc.getTransceivers();const pick=k=>trs.find(t=>t.receiver&&t.receiver.track&&t.receiver.track.kind===k&&!t.stopped);
  const ta=pick('audio');if(ta){ta.direction='sendrecv';call.audioSender=ta.sender;}else call.audioSender=call.pc.addTransceiver('audio',{direction:'sendrecv'}).sender;
  if(call.mediaMode==='video'){const tv=pick('video');if(tv){tv.direction='sendrecv';call.videoSender=tv.sender;}else call.videoSender=call.pc.addTransceiver('video',{direction:'sendrecv'}).sender;}else call.videoSender=null;
}
async function svAttachCallMedia(call,stream){
  if(svActiveVideoCall!==call){stream.getTracks().forEach(t=>{try{t.stop()}catch(_){}});return false;}
  call.localStream=stream;svSetLocalStream(stream);
  const audio=stream.getAudioTracks()[0]||null,video=stream.getVideoTracks()[0]||null;
  const replacements=[call.audioSender.replaceTrack(audio)];if(call.videoSender)replacements.push(call.videoSender.replaceTrack(video));await Promise.all(replacements);
  return true;
}
async function svSendPendingCandidates(call){const list=call.pendingCandidates.splice(0);for(const c of list){try{await api('/api/video-calls',{method:'POST',body:JSON.stringify({action:'candidate',call_id:call.callId,candidate:c})})}catch(e){svSetCallState('Could not send connection candidate: '+e.message)}}}
function svStartCallPolling(call){if(call.pollTimer)clearInterval(call.pollTimer);svSyncVideoCall(call).catch(e=>svSetCallState('Call signalling interrupted: '+e.message));call.pollTimer=setInterval(()=>svSyncVideoCall(call).catch(e=>svSetCallState('Call signalling interrupted: '+e.message)),650);}
async function svSyncVideoCall(call){
 if(!svActiveVideoCall||svActiveVideoCall.callId!==call.callId||call.syncing)return;call.syncing=true;
 try{
  const d=await api('/api/video-calls/'+encodeURIComponent(call.callId)+'?after='+call.lastSignalId);const state=d.call;
  if(['ended','rejected','missed'].includes(state.status)){svSetCallState(state.status==='rejected'?'The call was declined.':state.status==='missed'?'No answer.':'The call has ended.');closeSkillvayaVideoCall(false);return;}
  if(call.isCaller&&state.answer_sdp&&!call.remoteDescriptionSet){await call.pc.setRemoteDescription(new RTCSessionDescription(JSON.parse(state.answer_sdp)));call.remoteDescriptionSet=true;for(const c of call.queuedRemoteCandidates.splice(0)){try{await call.pc.addIceCandidate(new RTCIceCandidate(c))}catch(_){}}svSetCallState('Answer received; connecting…');}
  for(const event of (state.signals||[])){
   call.lastSignalId=Math.max(call.lastSignalId,Number(event.id)||0);
   if(Number(event.sender_id)===Number(me&&me.id)||event.kind!=='candidate')continue;
   let candidate;try{candidate=JSON.parse(event.payload)}catch(_){continue;}
   if(!call.remoteDescriptionSet){call.queuedRemoteCandidates.push(candidate);continue;}
   try{await call.pc.addIceCandidate(new RTCIceCandidate(candidate))}catch(err){console.warn('Could not apply remote ICE candidate',err.message)}
  }
 }finally{call.syncing=false;}
}
async function startSkillvayaVideoCall(businessId,customerId,mode='video'){
  // Preserve the existing background incoming-call notification permission flow.
  try { if (window.SkillvayaNotifications && typeof window.SkillvayaNotifications.ensureForCall === 'function') window.SkillvayaNotifications.ensureForCall(); } catch (e) { console.warn('Notification permission prompt unavailable', e); }
  mode=mode==='voice'?'voice':'video';
  if(me&&me.role==='customer')customerId=Number(me.id);businessId=Number(businessId);customerId=Number(customerId);if(!businessId||!customerId){alert('Open the existing contact conversation before starting a call.');return;}
  if(svActiveVideoCall){alert('A call is already open. End that call before starting another.');return;}
  if(!me){view('settings');profileAuthMode('signin');alert('Sign in before starting a call.');return;}
  if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia||typeof RTCPeerConnection==='undefined'){alert('This browser or WebView does not support Skillvaya calls. Update your browser/app and try again.');return;}
  let call=null,mediaPromise=null;
  const constraints=mode==='voice'?{audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false}:{audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:{facingMode:{ideal:'user'},width:{ideal:640},height:{ideal:480},frameRate:{ideal:24,max:30}}};
  try{
    svShowCallModal(mode==='voice'?'Skillvaya voice call':'Skillvaya video call','Requesting microphone permission…',mode);
    mediaPromise=navigator.mediaDevices.getUserMedia(constraints).then(stream=>({stream}),error=>({error}));
    call={callId:'',businessId:Number(businessId),customerId:Number(customerId),mediaMode:mode,isCaller:true,localStream:new MediaStream(),remoteStream:null,pc:null,audioSender:null,videoSender:null,pendingCandidates:[],queuedRemoteCandidates:[],lastSignalId:0,remoteDescriptionSet:false,syncing:false,pollTimer:null};
    await svCreatePeer(call);
    const offer=await call.pc.createOffer();await call.pc.setLocalDescription(offer);
    const created=await api('/api/video-calls',{method:'POST',body:JSON.stringify({action:'start',business_id:call.businessId,customer_id:call.customerId,offer_sdp:JSON.stringify(call.pc.localDescription)})});
    call.callId=created.call_id;svActiveVideoCall=call;svStartCallPolling(call);svSetCallState('Calling… waiting for the other participant to answer.');
    svSendPendingCandidates(call).catch(err=>svSetCallState('Call started; network setup is retrying: '+err.message));
    const mediaResult=await mediaPromise;if(mediaResult.error)throw mediaResult.error;
    if(svActiveVideoCall!==call){mediaResult.stream.getTracks().forEach(t=>{try{t.stop()}catch(_){}});return;}
    await svAttachCallMedia(call,mediaResult.stream);
    if(svActiveVideoCall===call)svSetCallState('Calling… waiting for the other participant to answer.');
  }catch(e){
    if(call&&svActiveVideoCall===call)await closeSkillvayaVideoCall(true);
    else{if(call&&call.pc)try{call.pc.close()}catch(_){}if(call&&call.localStream)call.localStream.getTracks().forEach(t=>{try{t.stop()}catch(_){}});const modal=document.getElementById('svVideoCallModal');if(modal)modal.classList.add('hidden');}
    if(mediaPromise)mediaPromise.then(result=>{if(result&&result.stream)result.stream.getTracks().forEach(t=>{try{t.stop()}catch(_){}})}).catch(()=>{});
    alert('Could not start the call: '+(e.message||'Microphone/camera permission was not granted.'));
  }
}
async function acceptSkillvayaVideoCall(){
  const incoming=svIncomingVideoCall;const incomingId=String(incoming&&incoming.id||'');if(!incoming||!incomingId||svIncomingAcceptingCallId===incomingId)return;svStopIncomingCallAlert();const panel=document.getElementById('svIncomingVideoCall');if(panel)panel.hidden=true;svIncomingVideoCall=null;
  if(svActiveVideoCall){alert('End your current call before accepting another.');return;}
  if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia||typeof RTCPeerConnection==='undefined'){alert('This browser or WebView cannot access the microphone for Skillvaya calls.');return;}
  svIncomingAcceptingCallId=incomingId;svProcessedIncomingCalls.add(incomingId);
  const mode=incoming.media_type==='voice'?'voice':'video';
  let call=null,mediaPromise=null;
  const constraints=mode==='voice'?{audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false}:{audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:{facingMode:{ideal:'user'},width:{ideal:640},height:{ideal:480},frameRate:{ideal:24,max:30}}};
  try{
    svShowCallModal(mode==='voice'?'Skillvaya voice call':'Skillvaya video call','Preparing microphone and connection…',mode);
    mediaPromise=navigator.mediaDevices.getUserMedia(constraints).then(stream=>({stream}),error=>({error}));
    view('messages');showMessagesScreen(false);openMessageConversation(Number(incoming.business_id),Number(incoming.customer_id)).catch(e=>console.warn('Call contact view refresh was delayed:',e&&e.message||e));
    call={callId:String(incoming.id),businessId:Number(incoming.business_id),customerId:Number(incoming.customer_id),mediaMode:mode,isCaller:false,localStream:new MediaStream(),remoteStream:null,pc:null,audioSender:null,videoSender:null,pendingCandidates:[],queuedRemoteCandidates:[],lastSignalId:0,remoteDescriptionSet:false,syncing:false,pollTimer:null};
    svActiveVideoCall=call;
    await svCreatePeer(call);
    const got=await api('/api/video-calls/'+encodeURIComponent(call.callId)+'?after=0');const remote=got.call;if(remote.status!=='ringing')throw Error('This call is no longer available.');
    await call.pc.setRemoteDescription(new RTCSessionDescription(JSON.parse(remote.offer_sdp)));call.remoteDescriptionSet=true;
    svBindAnswerSenders(call);
    // Attach the recipient's real media tracks BEFORE creating/sending the SDP answer.
    // This ensures the answer advertises the correct send/receive media directions.
    const mediaResult=await mediaPromise;if(mediaResult.error)throw mediaResult.error;
    if(svActiveVideoCall!==call){mediaResult.stream.getTracks().forEach(t=>{try{t.stop()}catch(_){}});return;}
    await svAttachCallMedia(call,mediaResult.stream);
    const answer=await call.pc.createAnswer();await call.pc.setLocalDescription(answer);
    await api('/api/video-calls',{method:'POST',body:JSON.stringify({action:'accept',call_id:call.callId,answer_sdp:JSON.stringify(call.pc.localDescription)})});svIncomingAcceptingCallId=null;
    call.lastSignalId=(remote.signals||[]).reduce((n,x)=>Math.max(n,Number(x.id)||0),0);
    for(const event of (remote.signals||[])){if(Number(event.sender_id)===Number(me.id)||event.kind!=='candidate')continue;try{await call.pc.addIceCandidate(new RTCIceCandidate(JSON.parse(event.payload)))}catch(_){}}
    svSendPendingCandidates(call).catch(err=>svSetCallState('Call accepted; network setup is retrying: '+err.message));svStartCallPolling(call);svSetCallState(mode==='voice'?'Voice call accepted; connecting…':'Video call accepted; connecting…');
  }catch(e){
    if(call&&svActiveVideoCall===call)await closeSkillvayaVideoCall(true);
    else{if(call&&call.pc)try{call.pc.close()}catch(_){}if(call&&call.localStream)call.localStream.getTracks().forEach(t=>{try{t.stop()}catch(_){}});const modal=document.getElementById('svVideoCallModal');if(modal)modal.classList.add('hidden');}
    if(mediaPromise)mediaPromise.then(result=>{if(result&&result.stream)result.stream.getTracks().forEach(t=>{try{t.stop()}catch(_){}})}).catch(()=>{});
    alert('Could not accept the call: '+(e.message||'Please check microphone/camera permissions.'));
    try{await api('/api/video-calls',{method:'POST',body:JSON.stringify({action:'reject',call_id:String(incoming.id)})})}catch(_){svProcessedIncomingCalls.delete(incomingId);}finally{if(svIncomingAcceptingCallId===incomingId)svIncomingAcceptingCallId=null;}
  }
}
async function declineSkillvayaVideoCall(){const incoming=svIncomingVideoCall;svStopIncomingCallAlert();svIncomingVideoCall=null;const p=document.getElementById('svIncomingVideoCall');if(p)p.hidden=true;if(incoming)try{await api('/api/video-calls',{method:'POST',body:JSON.stringify({action:'reject',call_id:String(incoming.id)})})}catch(e){alert('The call could not be declined on the server: '+e.message)}}
async function closeSkillvayaVideoCall(sendEnd){
 const call=svActiveVideoCall;svActiveVideoCall=null;
 if(call){
  if(call.pollTimer)clearInterval(call.pollTimer);
  if(call.pc)try{call.pc.onicecandidate=null;call.pc.ontrack=null;call.pc.close()}catch(_){}
  for(const stream of [call.localStream,call.remoteStream])if(stream)stream.getTracks().forEach(t=>{try{t.stop()}catch(_){}});
 }
 const modal=document.getElementById('svVideoCallModal');if(modal)modal.classList.add('hidden');const rv=document.getElementById('svCallRemoteVideo'),lv=document.getElementById('svCallLocalVideo');if(rv)rv.srcObject=null;if(lv)lv.srcObject=null;if(modal)modal.classList.remove('sv-call-voice-only');
 // Tear down the local call immediately. Do not make the End button wait for a slow mobile/database request.
 if(sendEnd&&call&&call.callId){
  api('/api/video-calls',{method:'POST',body:JSON.stringify({action:'end',call_id:call.callId})})
   .then(ended=>{if(!ended||!['ended','rejected','missed'].includes(ended.status))throw new Error('The server did not confirm that the call ended.');})
   .catch(e=>svSetCallState('Call ended on this phone; server notification is still pending. '+(e.message||'')));
 }
}
function toggleSkillvayaCallMic(){const c=svActiveVideoCall;if(!c)return;const tracks=c.localStream.getAudioTracks();const next=tracks.some(t=>t.enabled);tracks.forEach(t=>t.enabled=!next);svSetCallState(next?'Microphone muted':'Microphone enabled');}
function toggleSkillvayaCallCamera(){const c=svActiveVideoCall;if(!c)return;const tracks=c.localStream.getVideoTracks();const next=tracks.some(t=>t.enabled);tracks.forEach(t=>t.enabled=!next);svSetCallState(next?'Camera turned off':'Camera enabled');}
async function pollSkillvayaIncomingCalls(){if(!me||svActiveVideoCall||svIncomingAcceptingCallId||svIncomingPollBusy)return;svIncomingPollBusy=true;try{const d=await api('/api/video-calls');if(svIncomingVideoCall){const stillRinging=(d.items||[]).some(x=>String(x.id)===String(svIncomingVideoCall.id)&&x.status==='ringing');if(!stillRinging){svIncomingVideoCall=null;const p=document.getElementById('svIncomingVideoCall');if(p)p.hidden=true;svStopIncomingCallAlert();}return;}const incoming=(d.items||[]).find(x=>Number(x.callee_id)===Number(me.id)&&Number(x.caller_id)!==Number(me.id)&&x.status==='ringing'&&!svProcessedIncomingCalls.has(String(x.id)));if(!incoming)return;svIncomingVideoCall=incoming;svEnsureCallOverlays();const p=document.getElementById('svIncomingVideoCall');const title=document.getElementById('svIncomingTitle'),detail=document.getElementById('svIncomingDetail');if(title)title.textContent=(incoming.caller_name||'Your contact')+' is calling';if(detail)detail.textContent=(incoming.business_name||'Skillvaya chat')+' — incoming '+(incoming.media_type==='voice'?'voice call':'video call');if(p)p.hidden=false;svStartIncomingCallAlert(incoming);}catch(e){/* Messaging remains usable if call polling is temporarily unavailable. */}finally{svIncomingPollBusy=false;}}
function startSkillvayaVideoCallPolling(){if(svVideoCallPollingStarted)return;svVideoCallPollingStarted=true;svEnsureCallOverlays();pollSkillvayaIncomingCalls();svIncomingCallPoll=setInterval(pollSkillvayaIncomingCalls,900);svGetIceServers();if(!svIncomingWakeHandlersRegistered){svIncomingWakeHandlersRegistered=true;document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')pollSkillvayaIncomingCalls()});window.addEventListener('focus',()=>pollSkillvayaIncomingCalls());}}
function renderSkillvayaChatMessage(m){
 const own=Number(m.sender_id)===Number(me&&me.id);
 const atts=(m.attachments||[]).map(a=>{
  const url='/api/messages/attachments/'+Number(a.id),name=esc(a.filename||'Shared media');
  if(String(a.mime_type||'').startsWith('video/'))return '<div class="sv-chat-attachment"><video controls playsinline preload="'+(svDataSaver()?'none':'metadata')+'" src="'+url+'"></video><a href="'+url+'" target="_blank" rel="noopener">Open / download '+name+'</a></div>';
  if(String(a.mime_type||'').startsWith('image/'))return '<div class="sv-chat-attachment"><a href="'+url+'" target="_blank" rel="noopener">'+(svDataSaver()?'📷 Photo - tap to view':'<img loading="lazy" alt="'+name+'" src="'+url+'">')+'</a><a href="'+url+'" download="'+name+'">Download '+name+'</a></div>';
  return '<div class="sv-chat-attachment"><a href="'+url+'" download="'+name+'">'+name+'</a></div>';
 }).join('');
 return '<div class="message-row '+(own?'mine':'theirs')+'"><div class="message-bubble">'+esc(m.message||'')+atts+'<div class="message-time">'+esc(formatMessageDate(m.created_at||''))+'</div></div></div>';
}
function ensureSkillvayaChatMediaToolbar(root,businessId,customerId,phoneNumber){
 const screen=root&&root.querySelector('.message-conversation-screen');if(!screen)return;
 if(screen.querySelector('.sv-chat-media-toolbar'))return;
 const header=screen.querySelector('.message-conversation-header');
 const back=screen.querySelector('.message-back-button');
 const voiceCall=document.createElement('button');voiceCall.type='button';voiceCall.className='sv-chat-voice-call-button';voiceCall.setAttribute('aria-label','Start voice call');voiceCall.title='Start a voice call with this contact';voiceCall.textContent='Call';voiceCall.addEventListener('click',()=>startSkillvayaVideoCall(businessId,customerId,'voice'));
 const videoCall=document.createElement('button');videoCall.type='button';videoCall.className='sv-chat-call-button';videoCall.setAttribute('aria-label','Start video call');videoCall.title='Start a video call with this contact';videoCall.textContent='Video call';videoCall.addEventListener('click',()=>startSkillvayaVideoCall(businessId,customerId,'video'));
 const normalizedPhone=String(phoneNumber||'').trim().replace(/[^\d+]/g,'').replace(/(?!^)\+/g,'');
 const phoneDigits=normalizedPhone.replace(/\D/g,'');
 let phoneCall=null;
 if(phoneDigits.length>=7){phoneCall=document.createElement('a');phoneCall.className='sv-chat-phone-call-button';phoneCall.href='tel:'+normalizedPhone;phoneCall.textContent='Phone';phoneCall.setAttribute('aria-label','Call this contact using your phone network');phoneCall.title='Call using your phone network';}
 const toolbar=document.createElement('div');toolbar.className='sv-chat-media-toolbar';
 const upload=document.createElement('button');upload.type='button';upload.className='sv-media-upload';upload.textContent='\uFF0B Send photo / video';upload.setAttribute('aria-label','Send photo or video to this chat');upload.addEventListener('click',()=>screen.querySelector('#svChatMediaInput')?.click());
 const input=document.createElement('input');input.id='svChatMediaInput';input.type='file';input.accept='image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime,video/3gpp';input.hidden=true;input.addEventListener('change',e=>sendSkillvayaChatAttachment(e,businessId,customerId));
 const status=document.createElement('div');status.id='svChatMediaStatus';status.className='sv-chat-media-status';status.setAttribute('aria-live','polite');status.textContent='Voice calls, video calls and photo/video sharing are available in every chat.';
 if(header){header.appendChild(voiceCall);header.appendChild(videoCall);}
 else if(back){let topbar=screen.querySelector('.message-conversation-topbar');if(!topbar){topbar=document.createElement('div');topbar.className='message-conversation-topbar';screen.insertBefore(topbar,back);}topbar.append(back);topbar.appendChild(voiceCall);topbar.appendChild(videoCall);}
 else{toolbar.appendChild(voiceCall);toolbar.appendChild(videoCall);}
 if(phoneCall)toolbar.appendChild(phoneCall);
 toolbar.append(upload,input,status);
 const bubbles=screen.querySelector('.message-bubbles');if(bubbles)screen.insertBefore(toolbar,bubbles);else screen.appendChild(toolbar);
}
function svReadFileAsDataUrl(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onerror=()=>reject(new Error('The selected file could not be read.'));reader.onload=()=>resolve(String(reader.result||''));reader.readAsDataURL(file);});}
async function svUploadMediaToChat(businessId,customerId,file,statusNode){
 if(!file)throw new Error('Choose a photo or video first.');
 if(file.size>12*1024*1024)throw new Error('Photos and videos must be 12 MB or smaller.');
 const dataUrl=await svReadFileAsDataUrl(file),base64=dataUrl.split(',',2)[1];
 return api('/api/messages/attachments',{method:'POST',body:JSON.stringify({business_id:Number(businessId),customer_id:Number(customerId),filename:file.name,mime_type:file.type,base64:base64})});
}
async function sendSkillvayaChatAttachment(e,businessId,customerId){
 const input=e.target,file=input.files&&input.files[0],root=document.getElementById('messagesList');
 const status=document.getElementById('svChatMediaStatus');if(!file)return;
 if(status)status.textContent='Uploading '+file.name+'…';
 try{await svUploadMediaToChat(businessId,customerId,file,status);await openMessageConversation(businessId,customerId);}
 catch(err){if(status)status.textContent='Upload failed: '+err.message;else alert('Upload failed: '+err.message);}
 finally{if(input)input.value='';}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',startSkillvayaVideoCallPolling,{once:true});else startSkillvayaVideoCallPolling();

async function openMessageConversation(businessId,customerId){
 if(!me)return;
 const navVersion=++svMessagesNavigationVersion;
 const root=document.getElementById('messagesList');if(!root)return;
 document.body.classList.add('messages-conversation-open');
 // SV76-SPEED-01: when the inbox was loaded a moment ago, open the conversation from memory at once and confirm it with the
 // server in the background (new messages are patched into the open chat); otherwise show the loading note and fetch.
 let svWarm=(window.svMessagesItems&&window.svMessagesItems.userId===Number(me.id)&&Date.now()-window.svMessagesItems.at<120000)?window.svMessagesItems.items:null;
 if(svWarm&&!svWarm.some(m=>Number(m.business_id)===Number(businessId)))svWarm=null;
 if(!svWarm)root.innerHTML='<div class="message-conversation-screen"><button type="button" class="ghost message-back-button" onclick="loadMessageThreads()">&#8592; Back to conversations</button><div class="notice">Loading conversation&#8230;</div></div>';
 try{
  // Without a warm copy always fetch the server copy, so a message received after the inbox was opened is never hidden.
  const d=svWarm?{items:svWarm}:await api('/api/messages');
  if(navVersion!==svMessagesNavigationVersion)return;
  const items=d.items||[];
  svLastKnownMessageIds=new Set(items.map(m=>String(m.id)));svMessagePollInitialized=true;
  try{const key=svMessageCacheKey(),cached=JSON.parse(svCacheGet(key)||'null');if(cached){cached.messages=items;cached.messagesLoaded=true;cached.savedAt=Date.now();svCacheSet(key,JSON.stringify(cached));}}catch(_){}
  const buildThread=(its)=>{const own=me.role==='provider'||(me.role==='admin'&&its.some(m=>Number(m.business_id)===Number(businessId)&&Number(m.business_owner_id)===Number(me.id)));const th=its.filter(m=>Number(m.business_id)===Number(businessId)&&(own?Number(m.customer_id)===Number(customerId):Number(m.customer_id)===Number(me.id)));th.sort((a,b)=>String(a.created_at).localeCompare(String(b.created_at))||Number(a.id)-Number(b.id));return th};
  const thread=buildThread(items);
  const first=thread[0];
  let contactInfo=first||null;
  if(!contactInfo){
   try{
    const contacts=await api('/api/contacts');
    if(navVersion!==svMessagesNavigationVersion)return;
    contactInfo=(contacts.items||[]).find(c=>Number(c.business_id)===Number(businessId)&&Number(c.customer_id)===Number(customerId))||null;
   }catch(_){}
  }
  if(navVersion!==svMessagesNavigationVersion)return;
  const isProviderSide=(me.role==='provider'&&Number(contactInfo&&contactInfo.business_owner_id)===Number(me.id))||(me.role==='admin'&&Number(contactInfo&&contactInfo.business_owner_id)===Number(me.id));
  const phoneNumber=isProviderSide?(contactInfo&&contactInfo.customer_phone):(contactInfo&&contactInfo.business_phone);
  if(!first){
   root.innerHTML='<div class="message-conversation-screen"><button type="button" class="ghost message-back-button" onclick="loadMessageThreads()">&#8592; Back to conversations</button><div class="notice">No messages in this conversation yet. You can send the first message below.</div><div class="message-bubbles" aria-live="polite"></div><form class="message-compose" onsubmit="sendConversationReply(event,'+Number(businessId)+','+Number(customerId)+')"><textarea name="message" required maxlength="4000" rows="2" placeholder="Write a message"></textarea><div class="sv-voice-controls"><button type="button" class="ghost sv-voice-button" onclick="svToggleVoiceInput(this)" aria-pressed="false" title="Start voice typing" aria-label="Start voice typing">&#127908;</button></div><button class="primary" type="submit">Send</button></form></div>';
   ensureSkillvayaChatMediaToolbar(root,Number(businessId),Number(customerId),phoneNumber);
   return;
  }
  const title=isProviderSide?(first.customer_name||'Contact'):(first.business_name||'Service provider');
  root.innerHTML='<div class="message-conversation-screen"><button type="button" class="ghost message-back-button" onclick="loadMessageThreads()">\u2190 Back to conversations</button><div class="message-bubbles">'+thread.map(m=>renderSkillvayaChatMessage(m)).join('')+'</div><form class="message-compose" onsubmit="sendConversationReply(event,'+Number(businessId)+','+Number(first.customer_id)+')"><textarea name="message" required maxlength="4000" rows="2" placeholder="Write a message\u2026"></textarea><div class="sv-voice-controls"><button type="button" class="ghost sv-voice-button" onclick="svToggleVoiceInput(this)" aria-pressed="false" title="Start voice typing" aria-label="Start voice typing">&#127908;</button><span class="sv-voice-status" aria-live="polite"></span></div><button class="primary" type="submit">Send</button></form></div>';
  ensureSkillvayaChatMediaToolbar(root,Number(businessId),Number(first.customer_id),phoneNumber);
  const bubbles=root.querySelector('.message-bubbles');if(bubbles)bubbles.scrollTop=bubbles.scrollHeight;
  const field=root.querySelector('.message-compose textarea');
  if(field){const resize=()=>{field.style.height="auto";field.style.height=Math.min(field.scrollHeight,150)+"px";if(bubbles)bubbles.scrollTop=bubbles.scrollHeight;};field.addEventListener("input",resize);field.addEventListener("focus",()=>setTimeout(resize,50));resize();}
  if(svWarm){api('/api/messages').then(fresh=>{if(navVersion!==svMessagesNavigationVersion)return;const fi=fresh.items||[];window.svMessagesItems={userId:Number(me.id),items:fi,at:Date.now()};const sig=a=>a.length+':'+a.reduce((m,x)=>Math.max(m,Number(x.id)||0),0);if(sig(fi)===sig(svWarm))return;const bb=root.querySelector('.message-bubbles');if(!bb)return;const near=bb.scrollHeight-bb.scrollTop-bb.clientHeight<140;bb.innerHTML=buildThread(fi).map(m=>renderSkillvayaChatMessage(m)).join('');if(near)bb.scrollTop=bb.scrollHeight}).catch(()=>{})}
  try{await api("/api/messages/read",{method:"POST",body:JSON.stringify({business_id:Number(businessId),customer_id:Number(first.customer_id)})});}catch(_){}
 }catch(e){if(navVersion===svMessagesNavigationVersion)root.textContent='Could not open conversation: '+e.message;}
}
async function sendConversationReply(e,businessId,customerId){e.preventDefault();const form=e.target,field=form.elements.message,body=field.value.trim();if(!body)return;const btn=form.querySelector('button[type=submit]'),bubbles=form.closest('.message-conversation-screen')?.querySelector('.message-bubbles');if(btn)btn.disabled=true;const row=document.createElement('div');row.className='message-row mine';const bubble=document.createElement('div');bubble.className='message-bubble';bubble.appendChild(document.createTextNode(body));const stamp=document.createElement('div');stamp.className='message-time';stamp.textContent='Sending…';bubble.appendChild(stamp);row.appendChild(bubble);if(bubbles){bubbles.appendChild(row);bubbles.scrollTop=bubbles.scrollHeight;}field.value='';field.style.height='';try{await api('/api/messages/send',{method:'POST',body:JSON.stringify({business_id:businessId,customer_id:customerId,message:body})});stamp.textContent=formatMessageDate(new Date().toISOString());}catch(err){row.classList.add('message-send-failed');stamp.textContent='Not sent — tap to retry';row.title=err.message;field.value=body;}finally{if(btn)btn.disabled=false;field.focus({preventScroll:true})}}

// Recipient-only unread-message bell and lightweight in-app live refresh.
let svMessagesNavigationVersion=0,svMessagePollInitialized=false;
let svMessageLiveTimer=null,svMessageLiveBusy=false,svLastKnownMessageIds=new Set(),svVoiceRecognition=null,svVoiceTarget=null;
function svRecipientUnreadMessages(items){if(!me)return [];return (items||[]).filter(m=>{if(Number(m.sender_id)===Number(me.id)||m.read_at)return false;const customerRecipient=Number(m.customer_id)===Number(me.id),providerRecipient=Number(m.business_owner_id)===Number(me.id);if(me.role==='customer')return customerRecipient;if(me.role==='provider')return providerRecipient;return customerRecipient||providerRecipient;});}
function svEnsureNotificationBell(){const b=document.getElementById('svNotificationBell');if(!b)return null;if(b.dataset.handlerBound!=='true'){b.addEventListener('click',()=>{if(typeof showMessagesScreen==='function')showMessagesScreen(true);Promise.resolve().then(()=>api('/api/notifications')).then(nd=>{const items=nd.items||[];if(items.length)alert('SKILLVAYA NOTIFICATIONS\n\n'+items.slice(0,10).map(x=>x.subject+'\n'+x.body).join('\n\n'));}).catch(()=>{});});b.dataset.handlerBound='true';}return b;}
function svSetNotificationCount(n){const b=svEnsureNotificationBell();if(!b)return;const badge=document.getElementById('svNotificationBadge');b.classList.toggle('is-visible',!!me);if(badge){badge.hidden=!n;badge.textContent=n>99?'99+':String(n);b.setAttribute('aria-label',n+' unread message'+(n===1?'':'s'));b.title=n+' unread message'+(n===1?'':'s');}}
async function svRefreshOpenConversation(items){const root=document.getElementById('messagesList');if(!root||!document.body.classList.contains('messages-conversation-open'))return;const form=root.querySelector('.message-compose'),bubbles=root.querySelector('.message-bubbles');if(!form||!bubbles)return;const send=form.getAttribute('onsubmit')||'',nums=send.match(/sendConversationReply\(event,\s*(\d+),\s*(\d+)\)/);if(!nums)return;const businessId=Number(nums[1]),customerId=Number(nums[2]);const thread=(items||[]).filter(m=>Number(m.business_id)===businessId&&Number(m.customer_id)===customerId).sort((a,b)=>String(a.created_at).localeCompare(String(b.created_at))||Number(a.id)-Number(b.id));const wasNearBottom=bubbles.scrollHeight-bubbles.scrollTop-bubbles.clientHeight<90;for(const m of thread){const id=String(m.id);if(svLastKnownMessageIds.has(id))continue;svLastKnownMessageIds.add(id);const holder=document.createElement('div');holder.innerHTML=renderSkillvayaChatMessage(m);const rendered=holder.firstElementChild;if(rendered)bubbles.appendChild(rendered);}if(wasNearBottom)bubbles.scrollTop=bubbles.scrollHeight;try{await api('/api/messages/read',{method:'POST',body:JSON.stringify({business_id:businessId,customer_id:customerId})});}catch(_){}}
let svPulseKey=null,svPulseBusy=false;
async function svMessagePulse(){if(svPulseBusy||!me||document.visibilityState==='hidden')return;svPulseBusy=true;try{const d=await api('/api/messages/pulse');const key=String(d.latest_id||0)+':'+String(d.unread||0);const changed=svPulseKey!==null&&key!==svPulseKey;svPulseKey=key;if(changed)await svPollMessageNotifications();}catch(_){}finally{svPulseBusy=false;}}
async function svPollMessageNotifications(){if(svMessageLiveBusy||!me||document.visibilityState==='hidden')return;svMessageLiveBusy=true;try{const d=await api('/api/messages'),items=d.items||[],previous=svLastKnownMessageIds;const hasNewIncoming=svMessagePollInitialized&&items.some(m=>!previous.has(String(m.id))&&Number(m.sender_id)!==Number(me.id));svSetNotificationCount(svRecipientUnreadMessages(items).length);svMessagePollInitialized=true;if(document.body.classList.contains('messages-conversation-open'))await svRefreshOpenConversation(items);else if(document.body.classList.contains('messages-screen-mode')&&hasNewIncoming)await loadMessageThreads();svLastKnownMessageIds=new Set(items.map(m=>String(m.id)));}catch(_){/* Temporary network errors must not disrupt other screens. */}finally{svMessageLiveBusy=false;}}
function svStartMessageLiveUpdates(){svEnsureNotificationBell();try{svWebPushSync()}catch(_){};try{svAfterLogin()}catch(_){};if(svMessageLiveTimer)clearInterval(svMessageLiveTimer);svMessageLiveTimer=setInterval(svPollMessageNotifications,10000);if(window.svMessagePulseTimer)clearInterval(window.svMessagePulseTimer);window.svPulseTick=0;window.svMessagePulseTimer=setInterval(()=>{window.svPulseTick++;if(document.body.classList.contains('messages-conversation-open')||(window.svPulseTick%2===0&&document.body.classList.contains('messages-screen-mode')))svMessagePulse();},1500);svPollMessageNotifications();}
let svVoiceManualStop=false,svNativeVoiceForm=null,svNativeVoiceButton=null,svNativeVoiceStartText='',svNativeVoiceLastFinal='',svNativeVoiceAccumulated='',svNativeVoiceInterim='';
window.svNativeVoiceReady=function(){if(svNativeVoiceButton){svNativeVoiceButton.classList.add('is-listening');svNativeVoiceButton.setAttribute('aria-pressed','true');svNativeVoiceButton.innerHTML='&#127908;';svNativeVoiceButton.setAttribute('aria-label','Stop voice typing');svNativeVoiceButton.title='Stop voice typing';}const st=svNativeVoiceForm&&svNativeVoiceForm.querySelector('.sv-voice-status');if(st)st.textContent='Listening… tap the microphone once to stop.';};
function svNativeVoiceCommitText(clean){
 const form=svNativeVoiceForm,field=form&&form.elements.message;if(!field||!clean)return;
 const norm=clean.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();
 if(!norm)return;
 svNativeVoiceLastFinal=norm;
 const words=clean.split(/\s+/),prior=svNativeVoiceAccumulated.split(/\s+/);let overlap=0;
 // Never discard an entire repeated phrase as "overlap": people can intentionally repeat words.
 for(let k=Math.min(prior.length,Math.max(0,words.length-1));k>0;k--){
  const a=prior.slice(-k).join(' ').toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();
  const b=words.slice(0,k).join(' ').toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();
  if(a&&a===b){overlap=k;break;}
 }
 const add=words.slice(overlap).join(' ');if(add)svNativeVoiceAccumulated+=(svNativeVoiceAccumulated?' ':'')+add;
 field.value=(svNativeVoiceStartText?svNativeVoiceStartText+' ':'')+svNativeVoiceAccumulated;
 field.dispatchEvent(new Event('input',{bubbles:true}));
}
window.svNativeVoiceFlushInterim=function(){
 const pending=svNativeVoiceInterim;svNativeVoiceInterim='';
 if(pending)svNativeVoiceCommitText(pending);
 const form=svNativeVoiceForm,field=form&&form.elements.message;
 if(field){field.value=(svNativeVoiceStartText?svNativeVoiceStartText+' ':'')+svNativeVoiceAccumulated;field.dispatchEvent(new Event('input',{bubbles:true}));}
};
window.svNativeVoiceResult=function(text,isFinal){
 const form=svNativeVoiceForm,field=form&&form.elements.message;if(!field||!text)return;
 let clean=String(text).replace(/\s+/g,' ').trim();if(!clean)return;
 const status=form.querySelector('.sv-voice-status');
 if(!isFinal){
  svNativeVoiceInterim=clean;
  field.value=(svNativeVoiceStartText?svNativeVoiceStartText+' ':'')+svNativeVoiceAccumulated+(svNativeVoiceAccumulated&&svNativeVoiceInterim?' ':'')+svNativeVoiceInterim;
  field.dispatchEvent(new Event('input',{bubbles:true}));if(status)status.textContent='Listening.';return;
 }
 // Some Android speech services return a shorter final than their last partial. Keep the longer
 // prefix-compatible transcript so words already heard are not thrown away at a session boundary.
 const interim=svNativeVoiceInterim;svNativeVoiceInterim='';
 if(interim){
  const finalCount=clean.split(/\s+/).length,interimCount=interim.split(/\s+/).length;
  if(interim.toLocaleLowerCase().startsWith(clean.toLocaleLowerCase())||interimCount>finalCount)clean=interim;
 }
 svNativeVoiceCommitText(clean);
 if(status)status.textContent='Listening. recognised words are being kept. Tap the microphone to stop.';
};
window.svNativeVoiceEnded=function(manual){const b=svNativeVoiceButton,form=svNativeVoiceForm;if(b){b.classList.remove('is-listening');b.setAttribute('aria-pressed','false');b.innerHTML='&#127908;';b.setAttribute('aria-label','Start voice typing');b.title='Start voice typing';}const st=form&&form.querySelector('.sv-voice-status');if(st&&manual)st.textContent='Stopped. Review your message, then press Send.';else if(st&&!manual)st.textContent='Speech service ended listening. Tap the microphone to start again.';if(manual){svNativeVoiceForm=null;svNativeVoiceButton=null;}};
window.svNativeVoiceError=function(message){const b=svNativeVoiceButton;if(b){b.classList.remove('is-listening');b.setAttribute('aria-pressed','false');b.setAttribute('aria-label','Start voice typing');b.title='Start voice typing';}const st=svNativeVoiceForm&&svNativeVoiceForm.querySelector('.sv-voice-status');if(st)st.textContent=message||'Voice recognition stopped.';};
function svToggleVoiceInput(button){const form=button&&button.closest('form'),field=form&&form.elements.message,status=form&&form.querySelector('.sv-voice-status');if(!field)return;
if(window.SkillvayaVoice){if(svNativeVoiceForm===form){svVoiceManualStop=true;try{window.SkillvayaVoice.stop();}catch(_){}return;}if(svNativeVoiceForm){try{window.SkillvayaVoice.stop();}catch(_){}}
svVoiceManualStop=false;svNativeVoiceForm=form;svNativeVoiceButton=button;svNativeVoiceStartText=field.value.trim();svNativeVoiceLastFinal='';svNativeVoiceAccumulated='';svNativeVoiceInterim='';if(status)status.textContent='Starting microphone…';try{window.SkillvayaVoice.start();}catch(e){if(status)status.textContent='Could not start Android voice recognition.';}return;}
if(svVoiceRecognition&&svVoiceTarget===form){svVoiceManualStop=true;try{svVoiceRecognition.stop();}catch(_){}return;}
if(svVoiceRecognition){svVoiceManualStop=true;try{svVoiceRecognition.abort();}catch(_){}svVoiceRecognition=null;svVoiceTarget=null;}
const SpeechAPI=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SpeechAPI){if(status)status.textContent='Voice input is unavailable. Try your keyboard microphone.';return;}
svVoiceManualStop=false;let finalText='',startingText=field.value.trim(),recognition;
try{recognition=new SpeechAPI();recognition.lang=navigator.language||'en-ZA';recognition.continuous=true;recognition.interimResults=true;svVoiceRecognition=recognition;svVoiceTarget=form;
recognition.onstart=()=>{button.classList.add('is-listening');button.setAttribute('aria-pressed','true');button.innerHTML='&#127908;';button.setAttribute('aria-label','Stop voice typing');button.title='Stop voice typing';if(status)status.textContent='Listening… tap the microphone once to stop.';};
recognition.onresult=event=>{let interim='';for(let i=event.resultIndex;i<event.results.length;i++){const t=event.results[i][0].transcript;if(event.results[i].isFinal)finalText+=t.trim()+' ';else interim+=t;}field.value=(startingText?startingText+' ':'')+(finalText+interim).trim();field.dispatchEvent(new Event('input',{bubbles:true}));};
recognition.onerror=event=>{if(event.error!=='aborted'&&status)status.textContent='Voice service ended ('+event.error+'). Tap the microphone to try again.';};
recognition.onend=()=>{if(svVoiceRecognition===recognition)svVoiceRecognition=null;if(svVoiceTarget===form)svVoiceTarget=null;button.classList.remove('is-listening');button.setAttribute('aria-pressed','false');button.innerHTML='&#127908;';button.setAttribute('aria-label','Start voice typing');button.title='Start voice typing';if(status)status.textContent=svVoiceManualStop?'Stopped. Review your message, then press Send.':'Speech service ended listening. Tap the microphone to start again.';};
recognition.start();}catch(e){svVoiceRecognition=null;svVoiceTarget=null;if(status)status.textContent='Could not start voice input. Check microphone permission and retry.';}}
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')svPollMessageNotifications();});
function filterMessageThreads(query){const q=String(query||'').trim().toLowerCase();document.querySelectorAll('#messagesList .conversation-list-item').forEach(row=>{row.classList.toggle('hidden',!!q&&!row.textContent.toLowerCase().includes(q))});}
function formatMessageDate(value){if(!value)return '';const d=new Date(value);if(Number.isNaN(d.getTime()))return String(value);const now=new Date();const same=d.toDateString()===now.toDateString();return same?d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):d.toLocaleDateString([], {day:'2-digit',month:'short'});}
function svMessageCacheKey(){return 'sv_message_cache_v54_'+String(me&&me.id||'')+'_'+String(me&&me.role||'');}
async function loadMessageThreads(){
 const navVersion=++svMessagesNavigationVersion;
 document.body.classList.remove('messages-conversation-open');
 const root=document.getElementById('messagesList'),count=document.getElementById('messagesCount');if(!root)return;
 if(!me){root.innerHTML='<div class="messages-empty-state"><h3>Sign in to view contacts</h3><p>Your private conversations appear here after you sign in.</p></div>';if(count)count.textContent='';return;}
 const key=svMessageCacheKey();let cached=null;try{cached=JSON.parse(svCacheGet(key)||'null')}catch(_){}
 if(cached&&cached.html){root.innerHTML=cached.html;if(count)count.textContent=cached.count||'';}else{root.innerHTML='<div class="messages-loading"><span class="messages-loading-dot"></span>Loading conversations.</div>';if(count)count.textContent='';}
 try{
  const results=await Promise.allSettled([api('/api/messages'),api('/api/contacts')]);
  // A tap on a cached conversation can happen before these requests finish. Never
  // let this older inbox request replace the conversation that the user just opened.
  if(navVersion!==svMessagesNavigationVersion||document.body.classList.contains('messages-conversation-open'))return;
  if(results[0].status==='rejected'&&results[1].status==='rejected')throw results[0].reason||results[1].reason;
  const d=results[0].status==='fulfilled'?results[0].value:{items:[]},contactData=results[1].status==='fulfilled'?results[1].value:{items:[]};
  svLastKnownMessageIds=new Set((d.items||[]).map(m=>String(m.id)));svMessagePollInitialized=true;window.svMessagesItems={userId:Number(me.id),items:d.items||[],at:Date.now()};
  const items=(d.items||[]).filter(m=>me.role!=='admin'||Number(m.customer_id)===Number(me.id)||Number(m.business_owner_id)===Number(me.id)),contacts=contactData.items||[],threads=new Map();
  for(const c of contacts){const k=String(c.business_id)+'|'+String(c.customer_id);if(!threads.has(k))threads.set(k,{business_id:Number(c.business_id),customer_id:Number(c.customer_id),business_name:c.business_name,business_owner_id:Number(c.business_owner_id||0),customer_name:c.customer_name,created_at:c.created_at,messages:[]});}
  for(const m of items){const k=String(m.business_id)+'|'+String(m.customer_id);if(!threads.has(k))threads.set(k,{business_id:Number(m.business_id),customer_id:Number(m.customer_id),business_name:m.business_name,business_owner_id:Number(m.business_owner_id||0),customer_name:m.customer_name,created_at:m.created_at,messages:[]});else{const x=threads.get(k);x.business_owner_id=Number(m.business_owner_id||x.business_owner_id||0);x.business_name=m.business_name||x.business_name;x.customer_name=m.customer_name||x.customer_name;}threads.get(k).messages.push(m);}
  const grouped=Array.from(threads.values()).sort((a,b)=>String((b.messages[b.messages.length-1]||{}).created_at||b.created_at||'').localeCompare(String((a.messages[a.messages.length-1]||{}).created_at||a.created_at||'')));
  if(count)count.textContent=grouped.length+' conversation'+(grouped.length===1?'':'s');
  root.innerHTML=grouped.map(t=>{t.messages.sort((a,b)=>String(a.created_at).localeCompare(String(b.created_at))||Number(a.id)-Number(b.id));const last=t.messages[t.messages.length-1],title=((me.role==='provider'&&Number(t.business_owner_id)===Number(me.id))||(me.role==='admin'&&t.messages.some(m=>Number(m.business_owner_id)===Number(me.id))))?t.customer_name:t.business_name,preview=last?last.message:'Tap to start a conversation',when=last?.created_at||t.created_at||'',unread=t.messages.filter(m=>Number(m.sender_id)!==Number(me.id)&&!m.read_at).length;return '<button type="button" class="conversation-list-item" onclick="openMessageConversation('+t.business_id+','+t.customer_id+')"><span class="conversation-avatar">'+esc(String(title||'?').slice(0,1).toUpperCase())+'</span><span class="conversation-summary"><strong>'+esc(title||'Conversation')+'</strong><span>'+esc(preview)+'</span></span><span class="conversation-meta"><small>'+esc(formatMessageDate(when))+'</small>'+(unread?'<span class="conversation-count">'+unread+'</span>':'')+'</span></button>';}).join('')||'<div class="messages-empty-state"><h3>No conversations yet</h3><p>When you contact a service provider, your conversations will appear here.</p></div>';
  const search=document.getElementById('messageSearch');if(search&&search.value)filterMessageThreads(search.value);
  try{svCacheSet(key,JSON.stringify({html:root.innerHTML,count:count?count.textContent:'',messages:d.items||[],messagesLoaded:results[0].status==='fulfilled',contacts:contactData.items||[],savedAt:Date.now()}));}catch(_){}
 }catch(e){if(navVersion===svMessagesNavigationVersion&&!cached)root.innerHTML='<div class="messages-empty-state"><h3>Could not load conversations</h3><p>'+esc(e&&e.message?e.message:'Please check your connection and try again.')+'</p><button type="button" class="ghost" onclick="loadMessageThreads()">Try again</button></div>';}
}
async function replyMessage(e,business_id,customer_id){e.preventDefault();const f=e.target,field=f.elements.message,body=field.value.trim();if(!body)return;const button=f.querySelector('button[type=submit]');if(button){button.disabled=true;button.textContent='Sending...'}try{await api('/api/messages/send',{method:'POST',body:JSON.stringify({business_id,customer_id,message:body})});f.reset();msg('messagesStatus','Reply sent and saved to this conversation.',true);await loadMessageThreads()}catch(x){msg('messagesStatus','Reply not sent: '+x.message)}finally{if(button){button.disabled=false;button.textContent='Send reply'}}}
async function requestAccountDeletion(){if(!me||!token){alert('Please sign in to request account deletion.');return}if(me.role==='admin'){alert('The owner account cannot be deleted through the public account-deletion flow.');return}const reason=prompt('Optional reason for your account-deletion request:')||'';if(!confirm('Submit an account-deletion request for '+(me.email||'this account')+'? Your account is not deleted immediately. Skillvaya will verify the request and review lawful retention requirements. Google Play provider plans are prepaid and do not renew automatically. A new purchase is required to extend the paid period; deleting your Skillvaya account does not automatically refund an already-paid period.'))return;try{const d=await api('/api/account/delete-request',{method:'POST',body:JSON.stringify({reason})});alert(d.message||('Your request #'+d.request_id+' has been recorded.'));}catch(e){alert('Could not submit your deletion request: '+e.message+'\nYou can use the public deletion information page to contact Skillvaya.')}}
async function logout(){try{await svWebPushForget()}catch(_){}const t=token||localStorage.getItem('skillvaya_token')||localStorage.getItem('sv_token');try{if(t)await fetch('/api/logout',{method:'POST',headers:{'Authorization':'Bearer '+t,'Content-Type':'application/json'},body:'{}'})}catch(e){}try{svClearUserCaches()}catch(e){}token='';me=null;localStorage.removeItem('sv_token');localStorage.removeItem('skillvaya_token');localStorage.removeItem('skillvaya_owner_token');localStorage.removeItem('skillvaya_user');sessionStorage.removeItem('sv_token');sessionStorage.removeItem('skillvaya_token');location.replace('/');}
document.getElementById('profileForm').onsubmit=async e=>{e.preventDefault();try{let d=await api('/api/account/profile',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});me=d.user;document.getElementById('profileIdentity').textContent=me.email+' · '+me.role;msg('profileMsg','Profile saved successfully.',true);await sessionInfo();setProfileEditing(false)}catch(x){msg('profileMsg',x.message)}};
document.getElementById('passwordForm').onsubmit=async e=>{e.preventDefault();let f=e.target;if(f.elements.new_password.value!==f.elements.confirm_password.value){msg('passwordMsg','The new password and confirmation do not match.');return}try{let d=await api('/api/account/password',{method:'POST',body:JSON.stringify({current_password:f.elements.current_password.value,new_password:f.elements.new_password.value})});f.reset();msg('passwordMsg',d.message||'Password changed successfully.',true)}catch(x){msg('passwordMsg',x.message)}};
async function openStudioEditor(){const form=document.getElementById('bizForm');if(!form)return;try{const d=await api('/api/admin/owner-promotions');const item=(d.items||[]).find(x=>x.kind==='business'&&String(x.business_name||'').trim()==='Skillvaya Digital & Creative Studio'&&x.status==='active')||(d.items||[]).find(x=>x.kind==='business'&&String(x.business_name||'').trim()==='Skillvaya Digital & Creative Studio');if(item){form.elements.promotion_id.value=item.id;form.elements.name.value=item.business_name||'Skillvaya Digital & Creative Studio';form.elements.category.value=item.category||'Graphic designers';form.elements.area.value=item.area||'Worldwide (Online & Remote)';form.elements.phone.value=item.phone||'+27 83 787 45 69';form.elements.whatsapp.value=item.whatsapp||'+27 83 787 45 69';form.elements.email.value=item.contact_email||'Skillvaya@gmail.com';form.elements.website.value=item.target_url||'';form.elements.description.value=item.description||'';form.elements.tagline.value=item.title||'Your Vision. Our Skills. Real Results.';window.skillvayaStudioPromotion=item;}else{msg('bizMsg','Your published owner listing could not be found, so no changes were made.');return;}form.classList.remove('hidden');form.scrollIntoView({behavior:'smooth',block:'start'});}catch(e){msg('bizMsg','Could not load your saved profile for editing: '+e.message);}}
function closeStudioEditor(){const f=document.getElementById('bizForm');if(f)f.classList.add('hidden');document.getElementById('studioBrandPreview').scrollIntoView({behavior:'smooth',block:'start'});}
document.getElementById('bizForm').onsubmit=async e=>{
 e.preventDefault();const form=e.target,button=form.querySelector('button[type=submit],button:not([type])');
 if(button){button.disabled=true;button.textContent='Saving…'}
 try{
  const f=Object.fromEntries(new FormData(form));
  const files=Array.from(document.getElementById('providerPortfolioFiles').files||[]);
  const total=files.reduce((n,x)=>n+x.size,0);
  if(total>2*1024*1024)throw Error('Portfolio photos/catalogue must be 2 MB or less combined.');
  if(me&&me.role==='admin'){
   const existing=window.skillvayaStudioPromotion;
   if(!existing||!f.promotion_id)throw Error('Open Edit My Existing Profile again to load the current saved listing before saving.');
   let image=existing.image_url||'';
   if(files.length&&files[0].type!=='application/pdf')image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('Could not read '+files[0].name));reader.readAsDataURL(files[0])});
   const payload={action:'update',kind:'business',business_name:f.name,title:(f.tagline||'Your Vision. Our Skills. Real Results.').trim(),category:f.category,description:f.description,target_url:f.website||'',image_url:image,area:f.area,phone:f.phone,whatsapp:f.whatsapp||f.phone,contact_email:f.email||''};
   const d=await api('/api/admin/owner-promotions/'+encodeURIComponent(f.promotion_id),{method:'POST',body:JSON.stringify(payload)});
   window.skillvayaStudioPromotion={...existing,...payload,id:d.id||existing.id};
   msg('bizMsg','Saved. Your existing public Skillvaya studio listing has been updated; no duplicate was created.',true);
   form.classList.add('hidden');await loadBusinesses();document.getElementById('studioBrandPreview').scrollIntoView({behavior:'smooth',block:'start'});
  }else if(me&&me.role==='provider'){
   let photos=f.photos||'';
   if(files.length){
    photos=JSON.stringify(await Promise.all(files.map(file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve({name:file.name,type:file.type,data:reader.result});reader.onerror=()=>reject(Error('Could not read '+file.name));reader.readAsDataURL(file)}))));
   }
   const payload={country:f.country||svCountry(),name:f.name,category:f.category,area:f.area,phone:f.phone,whatsapp:f.whatsapp||f.phone,email:f.email||'',website:f.website||'',description:f.description,photos};
   if(window.skillvayaProviderBusinessId)await api('/api/provider/profile',{method:'POST',body:JSON.stringify(payload)});
   else await api('/api/businesses',{method:'POST',body:JSON.stringify(payload)});
   msg('bizMsg',window.skillvayaProviderBusinessId?'Your existing provider profile has been updated.':'Your provider profile has been created and published.',true);
   if(files.length)document.getElementById('providerPortfolioFiles').value='';
   await refreshProviderGate();await loadBusinesses();
  }else throw Error('Please sign in with the account that owns this provider profile.');
 }catch(x){msg('bizMsg','Changes were not saved: '+x.message)}
 finally{if(button){button.disabled=false;button.textContent=me&&me.role==='admin'?'Save changes to my public profile':window.skillvayaProviderBusinessId?'Save changes to my provider profile':'Create my provider profile'}}
};
async function refreshProviderGate(){
 const card=document.getElementById('providerProfileCard'),notice=document.getElementById('providerProfileNotice'),plans=document.getElementById('providerPlansCard'),preview=document.getElementById('studioBrandPreview'),form=document.getElementById('bizForm'),heading=document.getElementById('providerStudioHeading');
 if(!card||!notice)return;
 if(me&&me.role==='admin'){
  const taglineField=document.getElementById('ownerTaglineField');if(taglineField)taglineField.classList.remove('hidden');
  card.classList.remove('hidden');if(heading)heading.classList.add('hidden');if(preview)preview.classList.remove('hidden');if(form)form.classList.add('hidden');
  notice.textContent='OWNER FREE ACCESS: manage your existing Skillvaya Digital & Creative Studio profile here. No subscription or payment is required.';notice.classList.remove('hidden');notice.classList.add('good');if(plans)plans.classList.add('hidden');return;
 }
 const taglineField=document.getElementById('ownerTaglineField');if(taglineField)taglineField.classList.add('hidden');
 if(preview)preview.classList.add('hidden');
 if(heading)heading.classList.remove('hidden');
 notice.classList.remove('good');
 if(!me||me.role!=='provider'){
  card.classList.add('hidden');if(plans)plans.classList.remove('hidden');notice.textContent='Sign in or create a provider account in Profile / Sign in, then choose a plan. Your profile form unlocks after verified payment.';notice.classList.remove('hidden');return;
 }
 try{
  const d=await api('/api/provider/profile');
  const business=d.business||null;
  if(!business&&!d.payment_verified){
   card.classList.add('hidden');if(plans)plans.classList.remove('hidden');notice.classList.remove('hidden');notice.textContent='Choose a plan in the Skillvaya Android app (Google Play). Your provider profile form unlocks after Google Play confirms the purchase.';return;
  }
  card.classList.remove('hidden');if(plans)plans.classList.add('hidden');notice.classList.add('hidden');notice.classList.remove('good');
  if(form){
   form.classList.remove('hidden');window.skillvayaProviderBusinessId=business?Number(business.id):null;
   const fields={name:business?.name||me.name||'',category:business?.category||'',area:business?.area||'',phone:business?.phone||me.phone||'',whatsapp:business?.whatsapp||business?.phone||'',email:business?.email||me.email||'',website:business?.website||'',description:business?.description||''};
   for(const [key,value] of Object.entries(fields)){if(form.elements[key])form.elements[key].value=value}svFillCountrySelects();if(form.elements.country){form.elements.country.value=(business&&business.country)||(me&&me.country)||svCountry();form.elements.country.dataset.touched='1'}window.svProviderCur=svCurOf((business&&business.country)||(me&&me.country)||svCountry());
   if(form.elements.photos)form.elements.photos.value=business?.photos||'';
   const submit=form.querySelector('button[type=submit],button:not([type])');if(submit)submit.textContent=business?'Save changes to my provider profile':'Create my provider profile';
   const title=form.parentElement?.querySelector('h3');if(title)title.textContent=business?'Edit your provider profile':'Create your provider profile';
  }
 }catch(e){card.classList.add('hidden');if(plans)plans.classList.remove('hidden');notice.classList.remove('hidden');notice.textContent='Could not load your provider profile. Please retry after checking your connection.'}
}
function drawPlans(){const root=document.getElementById('plans'),billingControl=document.getElementById('billing');if(!root||!billingControl)return;if(me&&me.role==='admin'){root.innerHTML='<div class="price featured"><h3>Skillvaya Owner Edition</h3><div class="amount">FREE</div><p>All available app features unlocked for the owner account. No subscription or checkout is required.</p><span class="pill">Top-tier owner access</span></div>';return}const y=billingControl.value==='yearly';root.innerHTML='<p class="muted tiny">All four provider plans are listed below. '+svPlanNote()+' '+(y?'Annual billing costs 11 monthly payments for 12 months of access.':'Monthly billing covers one month of access.')+' Google Play will show the final price before you approve a purchase.</p>'+planInfo.map(p=>'<article class="price '+(p[0]==='spotlight'?'featured':'')+'" data-plan="'+p[0]+'"><h3>'+p[1]+'</h3><div class="amount">'+svPlanPrice(p[2]*(y?11:1))+'<span class="tiny muted"> / '+(y?'year':'month')+'</span></div>'+(y?'<span class="pill">12 months for price of 11</span>':'')+'<p class="muted tiny">'+p[3]+'</p><ul class="sv-plan-feature-list">'+p[4].map(f=>'<li>'+esc(f)+'</li>').join('')+'</ul><button class="primary" type="button" data-plan-choice="'+p[0]+'" data-billing-choice="'+(y?'yearly':'monthly')+'">Choose '+p[1]+'</button></article>').join('')}
document.addEventListener('click',function(e){const b=e.target&&e.target.closest?e.target.closest('[data-plan-choice]'):null;if(b)choosePlan(b.dataset.planChoice,b.dataset.billingChoice)});
function showBankTransferDetails(b){
let overlay=document.getElementById('svBankTransferDialog');
if(!overlay){
 overlay=document.createElement('div');overlay.id='svBankTransferDialog';
 overlay.style.cssText='position:fixed;inset:0;z-index:100001;background:#071426cc;display:flex;align-items:center;justify-content:center;padding:16px;overflow:auto';
 const panel=document.createElement('section');panel.id='svBankTransferPanel';
 panel.style.cssText='width:min(100%,480px);background:#fff;color:#17263b;border-radius:18px;padding:22px;box-shadow:0 20px 70px #0006;font:15px/1.5 Arial,sans-serif';
 overlay.appendChild(panel);document.body.appendChild(overlay);
 overlay.addEventListener('click',e=>{if(e.target===overlay)overlay.remove()});
}
const panel=overlay.querySelector('#svBankTransferPanel');
if(!b){
 panel.innerHTML='<h2 style="margin:0 0 8px;color:#102b49">Banking details</h2><p style="margin:0;color:#52647a">Loading banking details…</p><div style="height:5px;margin-top:18px;background:#e6edf5;border-radius:8px;overflow:hidden"><div style="height:100%;width:40%;background:#2876b8;animation:svBankLoad 0.7s ease-in-out infinite alternate"></div></div><style>@keyframes svBankLoad{from{transform:translateX(0)}to{transform:translateX(140%)}}</style>';
 return;
}
const fields=[['Account number',b.bank.account_number],['Account name',b.bank.account_holder],['Bank','Capitec']];
panel.innerHTML='<h2 style="margin:0 0 8px;color:#102b49">Banking details</h2><p style="margin:0 0 14px;color:#52647a">Please enter these details to make the payment in your own banking app.</p><div id="svBankFields" style="display:grid;gap:10px"></div><button id="svCloseBank" style="width:100%;margin-top:18px;background:#102b49;color:#fff;border:0;border-radius:9px;padding:12px 14px;font-weight:700">Close</button><p id="svBankStatus" role="status" style="min-height:18px;color:#146c43;margin:8px 0 0"></p>';
const fieldsEl=panel.querySelector('#svBankFields');
fields.forEach(([label,value])=>{
 const row=document.createElement('div');row.style.cssText='padding:11px 12px;border:1px solid #d8e2ed;border-radius:10px;background:#f8fbff';
 const name=document.createElement('div');name.style.cssText='font-size:12px;color:#65758a;margin-bottom:4px';name.textContent=label;
 const line=document.createElement('div');line.style.cssText='display:flex;align-items:center;justify-content:space-between;gap:10px';
 const val=document.createElement('strong');val.style.cssText='min-width:0;overflow-wrap:anywhere;color:#102b49;font-size:16px';val.textContent=value;
 const btn=document.createElement('button');btn.type='button';btn.textContent='Copy';btn.style.cssText='flex-shrink:0;border:1px solid #b9c9dc;background:#fff;border-radius:8px;padding:7px 10px;color:#102b49';
 btn.onclick=async()=>{try{if(navigator.clipboard&&navigator.clipboard.writeText)await navigator.clipboard.writeText(String(value));else{const t=document.createElement('textarea');t.value=String(value);t.style.position='fixed';t.style.opacity='0';document.body.appendChild(t);t.select();const ok=document.execCommand('copy');t.remove();if(!ok)throw Error('Copy unavailable')}const s=panel.querySelector('#svBankStatus');if(s)s.textContent=label+' copied.'}catch(e){const s=panel.querySelector('#svBankStatus');if(s)s.textContent='Copy unavailable. Please select and copy the details manually.'}};
 line.append(val,btn);row.append(name,line);fieldsEl.appendChild(row);
});
panel.querySelector('#svCloseBank').onclick=()=>overlay.remove();
}
function showGooglePlayCheckout(plan,billing){
 const ids={local:'skillvaya_local',priority:'skillvaya_priority',plus:'skillvaya_business_plus',spotlight:'skillvaya_business_spotlight'},productId=ids[plan];
 const old=document.getElementById('svPlayCheckout');if(old)old.remove();
 const overlay=document.createElement('div');overlay.id='svPlayCheckout';overlay.style.cssText='position:fixed;inset:0;z-index:100002;background:#071426cc;display:flex;align-items:center;justify-content:center;padding:18px';
 const panel=document.createElement('section');panel.style.cssText='width:min(100%,460px);background:#fff;color:#15253b;border-radius:18px;padding:24px;box-shadow:0 20px 70px #0006';
 panel.innerHTML='<h2 style="margin:0 0 8px;color:#102b49">Google Play subscription</h2><p id="svPlayPrice">Checking Google Play prices…</p><p style="font-size:13px;color:#60738a">This is a prepaid plan and will not renew automatically. The paid period ends on the expiry date shown unless you choose and approve another purchase. Skillvaya activates paid access only after server verification.</p><p id="svPlayError" role="status" style="color:#a12b2b"></p><button id="svPlayBuy" class="primary" disabled>Continue with Google Play</button> <button id="svPlayRestore" class="ghost">Restore purchases</button> <button id="svPlayCancel" class="ghost">Close</button>';
 overlay.appendChild(panel);document.body.appendChild(overlay);panel.querySelector('#svPlayCancel').onclick=()=>overlay.remove();panel.querySelector('#svPlayRestore').onclick=()=>{if(!me||me.role!=='provider'||!token){panel.querySelector('#svPlayError').textContent='Sign in with your provider account to restore purchases.';return}panel.querySelector('#svPlayError').textContent='Checking your Google Play subscriptions…';window.SkillvayaBilling.restorePurchases(String(me.id),token)};
 window.svPlayBillingProducts=(json,code)=>{let items=[];try{items=JSON.parse(json||'[]')}catch(e){}const product=items.find(x=>x.productId===productId);const wanted=billing==='yearly'?'annual':'monthly';const offer=product?.offers?.find(x=>x.basePlanId===wanted);if(!product||!offer){panel.querySelector('#svPlayPrice').textContent='This plan is not available in Google Play yet.';panel.querySelector('#svPlayError').textContent='The product and base plan must be created and activated in Play Console.';return}panel.querySelector('#svPlayPrice').textContent=product.title+' · '+offer.price+' / '+(billing==='yearly'?'year':'month');const buy=panel.querySelector('#svPlayBuy');buy.disabled=false;buy.onclick=()=>{if(!me||me.role!=='provider'||!token){panel.querySelector('#svPlayError').textContent='Please sign in with your provider account before purchasing.';return}buy.disabled=true;panel.querySelector('#svPlayError').textContent='Opening Google Play checkout…';window.SkillvayaBilling.purchaseSubscription(productId,offer.offerToken,String(me.id),token)}};
 window.svPlayBillingResult=(json)=>{let d={};try{d=typeof json==='string'?JSON.parse(json):json||{}}catch(e){}if(d.ok){panel.querySelector('#svPlayError').style.color='#146c43';panel.querySelector('#svPlayError').textContent=d.message||'Purchase verified. Refreshing provider access…';setTimeout(()=>{refreshProviderGate().catch(()=>{});if(!panel.querySelector('#svManageSubscription'))panel.querySelector('#svPlayError').insertAdjacentHTML('afterend','<p id="svManageSubscription"><a href="https://play.google.com/store/account/subscriptions?package=za.co.skillvaya.app" style="color:#155ca8;font-weight:700">Manage Google Play plan</a></p>')},900)}else{panel.querySelector('#svPlayError').textContent=d.message||'Purchase was not completed.';panel.querySelector('#svPlayBuy').disabled=false}};
 window.svPlayBillingError=(message)=>{panel.querySelector('#svPlayError').textContent=String(message||'Google Play could not complete this purchase.');panel.querySelector('#svPlayBuy').disabled=false};
 window.SkillvayaBilling.querySubscriptions();
 if(me&&me.role==='provider'&&token)window.SkillvayaBilling.restorePurchases(String(me.id),token);
}
function showPaymentChoice(plan,billing){
 if(/SkillvayaNative/i.test(navigator.userAgent)&&window.SkillvayaBilling){showGooglePlayCheckout(plan,billing);return}
 svPlayOnlyNotice();return;
 const old=document.getElementById('svPaymentChoice');if(old)old.remove();
 const overlay=document.createElement('div');overlay.id='svPaymentChoice';overlay.style.cssText='position:fixed;inset:0;z-index:100000;background:rgba(5,18,38,.72);display:flex;align-items:center;justify-content:center;padding:18px;overflow:auto';
 const card=document.createElement('section');card.style.cssText='width:min(100%,480px);background:#fff;color:#17263b;border-radius:22px;overflow:hidden;box-shadow:0 24px 80px #0005;font:15px/1.5 Arial,sans-serif';
 card.innerHTML='<div style="background:linear-gradient(135deg,#071b35,#123d68);padding:24px;color:white"><div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#b9d9f5;font-weight:700">SKILLVAYA SECURE CHECKOUT</div><h2 style="margin:8px 0 4px;font-size:25px">Choose your payment method</h2><p style="margin:0;color:#d8e8f7">Select how you would like to pay for your subscription.</p></div><div style="padding:20px;display:grid;gap:12px"><button id="svPayPalChoice" style="display:flex;align-items:center;gap:14px;text-align:left;padding:16px;border:1px solid #cbd8e6;border-radius:14px;background:#fff;color:#102b49;cursor:pointer"><span style="font-weight:800;font-size:22px;font-style:italic;color:#003087">PayPal</span><span><strong style="display:block;font-size:16px">Pay with PayPal</strong><span style="display:block;color:#61748a;font-size:13px">Continue to secure PayPal checkout</span></span><span style="margin-left:auto;font-size:22px">›</span></button><button id="svBankChoice" style="display:flex;align-items:center;gap:14px;text-align:left;padding:16px;border:1px solid #cbd8e6;border-radius:14px;background:#f4f8fd;color:#102b49;cursor:pointer"><span style="width:42px;height:42px;display:grid;place-items:center;border-radius:12px;background:#dcecff;font-size:22px">↗</span><span><strong style="display:block;font-size:16px">Direct bank transfer</strong><span style="display:block;color:#61748a;font-size:13px">View bank details and payment reference</span></span><span style="margin-left:auto;font-size:22px">›</span></button><p style="margin:0;color:#6b7c90;font-size:12px">Bank transfers remain pending until SkillVaya confirms that the funds have cleared. PayPal payments are verified through PayPal.</p><button id="svCancelChoice" style="border:0;background:transparent;padding:10px;color:#53657a;font-weight:700;cursor:pointer">Cancel</button><p id="svPayChoiceStatus" role="status" style="margin:0;color:#a12b2b"></p></div>';
 overlay.appendChild(card);document.body.appendChild(overlay);
 card.querySelector('#svCancelChoice').onclick=()=>overlay.remove();
 overlay.addEventListener('click',e=>{if(e.target===overlay)overlay.remove()});
 card.querySelector('#svBankChoice').onclick=async()=>{const btn=card.querySelector('#svBankChoice');btn.disabled=true;btn.style.opacity='.65';overlay.remove();showBankTransferDetails(null);try{const b=await api('/api/bank-transfer',{method:'POST',body:JSON.stringify({plan,billing})});showBankTransferDetails(b)}catch(e){const wait=document.getElementById('svBankTransferDialog');if(wait)wait.remove();card.querySelector('#svPayChoiceStatus').textContent=e.message;btn.disabled=false;btn.style.opacity='1'}};
 card.querySelector('#svPayPalChoice').onclick=async()=>{const btn=card.querySelector('#svPayPalChoice');btn.disabled=true;btn.style.opacity='.65';card.querySelector('#svPayChoiceStatus').textContent='Connecting to PayPal…';try{const p=await api('/api/payment-provider');if(p.provider!=='paypal'||!p.checkout_ready)throw Error(p.message||'PayPal checkout is not ready.');const d=await api('/api/paypal/create-order',{method:'POST',body:JSON.stringify({plan,billing})});if(!d.checkout_ready||!d.approval_url)throw Error(d.error||'PayPal checkout is not ready.');location.assign(d.approval_url)}catch(e){card.querySelector('#svPayChoiceStatus').textContent=e.message;btn.disabled=false;btn.style.opacity='1'}};
}
async function choosePlan(plan,billing){if(me&&me.role==='admin'){alert('Your Skillvaya Owner Edition is already unlocked for free. No payment is required.');return}if(!me){view('settings');profileAuthMode('signin');alert('Create a provider profile or sign in first.');return}showPaymentChoice(plan,billing)}
async function loadAdmin(){try{let d=await api('/api/admin/summary');document.getElementById('adminData').classList.remove('hidden');document.getElementById('adminMsg').classList.add('hidden');document.getElementById('sBiz').textContent=d.businesses;document.getElementById('sComplaints').textContent=d.complaints;document.getElementById('sPayments').textContent=d.payments;document.getElementById('sPending').textContent=d.pending;adminTab('complaints')}catch(e){document.getElementById('adminData').classList.add('hidden');document.getElementById('adminMsg').textContent='Owner sign-in required. '+e.message}}
async function adminTab(tab){try{if(tab==='settings'){let d=await api('/api/admin/settings');document.getElementById('adminTable').innerHTML='<h3>Owner email & alerts</h3><p>Reports, new account notices, payment events and overdue subscription alerts can be emailed when SMTP is configured.</p><form id="ownerEmailForm"><label>Owner notification email</label><input name="owner_email" type="email" value="'+esc(d.owner_email)+'" placeholder="you@example.com" required><p><button class="primary">Save email</button> <button type="button" class="ghost" onclick="testOwnerEmail()">Send test email</button></p></form><div class="notice">'+(d.smtp_configured?'SMTP credentials detected.':'Email sending is not yet configured; events are saved to Alerts until SMTP is configured.')+'</div><p class="muted tiny">'+esc(d.note)+'</p>';document.getElementById('ownerEmailForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/admin/settings',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});alert('Owner email saved.');adminTab('settings')}catch(x){alert(x.message)}};return}
if(tab==='analytics'){let d=await api('/api/admin/analytics'),s=d.stats;document.getElementById('adminTable').innerHTML='<h3>Downloads & usage</h3><div class="stats">'+[['Page visits',s.visits],['PWA installs recorded',s.installs],['Accounts',s.accounts],['Provider accounts',s.providers],['Verified payments',s.verified_payments],['Verified payment total','R'+Number(s.revenue).toLocaleString('en-ZA')],['Desktop visits',s.desktop_visits],['Mobile visits',s.mobile_visits]].map(x=>'<div class="card"><span class="tiny muted">'+x[0]+'</span><strong>'+x[1]+'</strong></div>').join('')+'</div><p class="notice">These are events recorded by this running installation, not store download counts or unique people. Actual app-store downloads require store analytics; visits can include repeat visits.</p>';return}
let d=await api('/api/admin/'+tab);let h='';if(tab==='clients'){h='<h3>Client & provider accounts</h3><div class="tablewrap"><table class="table"><tr><th>Name</th><th>Email</th><th>Phone</th><th>Type</th><th>Created</th><th>Listings</th><th>Paid subscriptions</th></tr>'+d.items.map(x=>'<tr><td>'+esc(x.name)+'</td><td>'+esc(x.email)+'</td><td>'+esc(x.phone||'—')+'</td><td>'+esc(x.role)+'</td><td>'+esc(x.created_at)+'</td><td>'+x.businesses+'</td><td>'+x.paid+'</td></tr>').join('')+'</table></div>';document.getElementById('adminTable').innerHTML=h;return}
if(tab==='notifications'){h='<h3>Alert inbox</h3><div class="tablewrap"><table class="table"><tr><th>Date</th><th>Type</th><th>Subject</th><th>Status</th><th>Details</th></tr>'+d.items.map(x=>'<tr><td>'+esc(x.created_at)+'</td><td>'+esc(x.kind)+'</td><td>'+esc(x.subject)+'</td><td>'+esc(x.status)+'</td><td>'+esc(x.body)+'</td></tr>').join('')+'</table></div>';document.getElementById('adminTable').innerHTML=h;return}
if(tab==='complaints'){h='<h3>Safety & complaints</h3><p class="muted tiny">Review allegations, request evidence, and record outcomes. Suspension hides a listing pending review.</p><div class="tablewrap"><table class="table"><tr><th>ID</th><th>Business</th><th>Report</th><th>Status</th><th>Action</th></tr>'+d.items.map(x=>'<tr><td>#'+x.id+'</td><td>'+esc(x.business_name)+'</td><td>'+esc(x.reason)+'</td><td>'+esc(x.status)+'</td><td><button class="danger" onclick="resolveComplaint('+x.id+')">Resolve</button></td></tr>').join('')+'</table></div>'}else if(tab==='businesses'){setTimeout(svAdminFutureChat,0);h='<div id="svFcAdmin" class="notice" style="margin-bottom:12px"></div><h3>Business listings</h3><div class="tablewrap"><table class="table"><tr><th>Business</th><th>Category</th><th>Plan</th><th>Status</th><th>Action</th></tr>'+d.items.map(x=>'<tr><td>'+esc(x.name)+'</td><td>'+esc(x.category)+'</td><td>'+esc(x.plan)+'</td><td>'+esc(x.status)+'</td><td><button class="ghost" onclick="setBusiness('+x.id+',\''+(x.status==='active'?'suspended':'active')+'\')">'+(x.status==='active'?'Suspend':'Activate')+'</button> <button class="ghost" onclick="svAdminVerify('+x.id+','+(x.verified_at?0:1)+')">'+(x.verified_at?'Remove verified':(x.verify_requested_at?'Verify (requested)':'Verify'))+'</button></td></tr>').join('')+'</table></div>'}else{h='<h3>Payment requests</h3><div class="tablewrap"><table class="table"><tr><th>Ref</th><th>Plan</th><th>Amount</th><th>Status</th><th>Action</th></tr>'+d.items.map(x=>'<tr><td>'+esc(x.reference)+'</td><td>'+esc(x.plan)+' / '+esc(x.billing)+'</td><td>R'+x.amount+'</td><td>'+esc(x.status)+'<br>'+esc(x.refund_status||'none')+'</td><td>'+(x.status==='verified'&&x.pf_payment_id?'<button class=\\"danger\\" onclick=\\"refundPayment('+x.id+','+x.amount+','+(x.refunded_amount||0)+')\\">Refund</button>':(x.status==='pending'?'Awaiting PayPal confirmation':'—'))+'</td></tr>').join('')+'</table></div>'}document.getElementById('adminTable').innerHTML=h}catch(e){alert(e.message)}}
async function emailClientByAddress(){let email=prompt("Enter the exact customer/provider account email address:");if(!email)return;let subject=prompt("Email subject (for a warning, include the reason):");if(!subject)return;let body=prompt("Message to send to this client:");if(!body)return;try{let d=await api("/api/admin/email-client",{method:"POST",body:JSON.stringify({client_email:email,subject,body})});alert("Email sent to "+d.recipient)}catch(e){alert(e.message)}}
async function testOwnerEmail(){try{await api('/api/admin/test-email',{method:'POST',body:'{}'});alert('Test email sent.')}catch(e){alert(e.message)}}
async function resolveComplaint(id){if(!confirm('Mark this complaint reviewed and resolved?'))return;try{await api('/api/admin/complaints/'+id,{method:'POST',body:'{}'});adminTab('complaints')}catch(e){alert(e.message)}}
async function setBusiness(id,status){try{await api('/api/admin/businesses/'+id,{method:'POST',body:JSON.stringify({status})});loadBusinesses();adminTab('businesses')}catch(e){alert(e.message)}}
async function verifyPayment(id){if(!confirm('Only confirm if payment has actually been received and checked in your bank/payment provider. Continue?'))return;try{await api('/api/admin/payments/'+id,{method:'POST',body:'{}'});adminTab('payments')}catch(e){alert(e.message)}}
async function refundPayment(id,amount,already){let remaining=amount*100-Number(already||0);let dollars=prompt('Refund amount in Rands (up to R'+(remaining/100).toFixed(2)+'). Partial refunds are supported.',''+(remaining/100).toFixed(2));if(dollars===null)return;let cents=Math.round(Number(dollars)*100);if(!Number.isFinite(cents)||cents<1||cents>remaining){alert('Enter a valid amount within the remaining paid balance.');return}let reason=prompt('Reason for the refund (required):');if(!reason||reason.trim().length<3)return; if(!confirm('Submit a PayPal refund for R'+(cents/100).toFixed(2)+'?'))return;try{let d=await api('/api/admin/refunds/'+id,{method:'POST',body:JSON.stringify({amount:cents,reason})});alert(d.message||'Refund request accepted by PayPal.');adminTab('payments')}catch(e){alert(e.message)}}
function installPasswordVisibility(){document.querySelectorAll('input[type="password"]').forEach((input,index)=>{if(input.dataset.eyeReady)return;input.dataset.eyeReady='1';const wrap=document.createElement('span');wrap.className='password-wrap';input.parentNode.insertBefore(wrap,input);wrap.appendChild(input);const btn=document.createElement('button');btn.type='button';btn.className='password-toggle';btn.setAttribute('aria-label','Show password');btn.setAttribute('aria-pressed','false');btn.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';btn.addEventListener('click',()=>{const show=input.type==='password';input.type=show?'text':'password';btn.setAttribute('aria-label',show?'Hide password':'Show password');btn.setAttribute('aria-pressed',String(show));btn.innerHTML=show?'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m3 3 18 18M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.2A10.8 10.8 0 0 1 12 5c6.4 0 10 7 10 7a16 16 0 0 1-3.1 3.8M6.2 6.2C3.5 8 2 12 2 12s3.6 7 10 7a10 10 0 0 0 4-.8"/></svg>':'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';});wrap.appendChild(btn);});}
const photoInput=document.getElementById('profilePhotoFile');if(photoInput){photoInput.addEventListener('change',()=>{const f=photoInput.files&&photoInput.files[0];const name=document.getElementById('profilePhotoFileName');if(name)name.textContent=f?f.name+' · '+(f.size/1024).toFixed(0)+' KB':'Tap Choose profile picture to select an image from your device';if(f&&['image/jpeg','image/png','image/webp'].includes(f.type)&&f.size<=2*1024*1024){const preview=document.getElementById('profilePhotoPreview');if(preview)preview.src=URL.createObjectURL(f);msg('photoMsg','Image selected. Tap Upload picture to save it.',true)}else if(f){msg('photoMsg','Choose a JPG, PNG or WebP image up to 2 MB.')}});}
const portfolioInput=document.getElementById('providerPortfolioFiles');if(portfolioInput){portfolioInput.addEventListener('change',()=>{const files=Array.from(portfolioInput.files||[]),total=files.reduce((n,f)=>n+f.size,0),label=document.getElementById('providerPortfolioPreview');if(total>2*1024*1024){portfolioInput.value='';label.textContent='Selected files exceed 2 MB combined. Choose smaller files.';return}if(files.some(f=>!['image/jpeg','image/png','image/webp','application/pdf'].includes(f.type))){portfolioInput.value='';label.textContent='Choose JPG, PNG, WebP or PDF files only.';return}label.textContent=files.length?files.map(f=>f.name+' ('+(f.size/1024).toFixed(0)+' KB)').join(' · '):'No files selected';});}
installPasswordVisibility();
const splashFailsafe=setTimeout(()=>{const splash=document.getElementById('svSplash');if(splash)splash.classList.add('done');},10000);
init().finally(()=>{clearTimeout(splashFailsafe);const splash=document.getElementById('svSplash');if(splash)setTimeout(()=>splash.classList.add('done'),450)});
try{fetch('/api/analytics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event:'visit',detail:/Mobi|Android|iPhone/i.test(navigator.userAgent)?'mobile':'desktop'})})}catch(e){}
let installPrompt=null;window.addEventListener('beforeinstallprompt',e=>{installPrompt=e;});window.addEventListener('appinstalled',()=>{fetch('/api/analytics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event:'install',detail:'pwa'})}).catch(()=>{})});
if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'}).then(reg=>reg.update()).catch(console.warn);
/* SV78-WEBPUSH-01: alerts for the iPhone home-screen app, computers and other browsers (the Android app keeps using Firebase). */
function svIsNativeApp(){return /SkillvayaNative/.test(navigator.userAgent||'')||!!window.SkillvayaNotifications}
function svIsIOS(){return /iPad|iPhone|iPod/.test(navigator.userAgent||'')||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1)}
function svIsStandalone(){try{return window.matchMedia('(display-mode: standalone)').matches||navigator.standalone===true}catch(_){return false}}
function svWebPushSupported(){return !svIsNativeApp()&&('serviceWorker' in navigator)&&('PushManager' in window)&&('Notification' in window)}
function svB64ToBytes(s){const p='='.repeat((4-s.length%4)%4),b=atob((s+p).replace(/-/g,'+').replace(/_/g,'/'));const a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a}
function svSwReady(){return Promise.race([navigator.serviceWorker.ready,new Promise((_,rej)=>setTimeout(()=>rej(new Error('The app is still loading. Try again in a moment.')),8000))])}
async function svWebPushSubscribe(){const k=await api('/api/webpush/key');if(!k||!k.publicKey)throw new Error('Notifications are not available right now.');const reg=await svSwReady();let sub=await reg.pushManager.getSubscription();if(sub){try{const cur=sub.options&&sub.options.applicationServerKey;if(cur){const a=new Uint8Array(cur),b=svB64ToBytes(k.publicKey);if(a.length!==b.length||a.some((x,i)=>x!==b[i])){await sub.unsubscribe();sub=null}}}catch(_){}}if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:svB64ToBytes(k.publicKey)});await api('/api/webpush/subscribe',{method:'POST',body:JSON.stringify({subscription:sub.toJSON()})});return sub}
async function svEnableWebPush(){if(!svWebPushSupported())return false;try{const p=await Notification.requestPermission();if(p!=='granted'){svHidePushBanner();return false}await svWebPushSubscribe();svHidePushBanner();try{await api('/api/webpush/test',{method:'POST',body:'{}'})}catch(_){}return true}catch(e){alert('Could not turn on notifications: '+(e&&e.message||e));return false}}
async function svWebPushSync(){try{if(!me)return;if(svWebPushSupported()&&Notification.permission==='granted'){await svWebPushSubscribe();return}svMaybeShowPushBanner()}catch(e){console.warn('Web push sync',e&&e.message||e)}}
async function svWebPushForget(){try{if(!svWebPushSupported())return;const reg=await svSwReady();const sub=await reg.pushManager.getSubscription();if(sub)await api('/api/webpush/unsubscribe',{method:'POST',body:JSON.stringify({endpoint:sub.endpoint})})}catch(_){}}
function svHidePushBanner(){const b=document.getElementById('svPushBanner');if(b)b.remove()}
function svMaybeShowPushBanner(){try{if(!me||svIsNativeApp()||document.getElementById('svPushBanner'))return;let dismissed=false;try{dismissed=localStorage.getItem('sv_push_banner_dismissed')==='1'}catch(_){}if(dismissed)return;let html='';if(svWebPushSupported()&&Notification.permission==='default')html='<span>Get alerts for new messages and calls.</span><button type="button" id="svPushOn">Turn on</button>';else if(svIsIOS()&&!svIsStandalone())html='<span>On iPhone, tap <b>Share</b> then <b>Add to Home Screen</b> to get message and call alerts.</span>';else return;const bar=document.createElement('div');bar.id='svPushBanner';bar.setAttribute('role','status');bar.style.cssText='position:fixed;left:12px;right:12px;bottom:calc(84px + env(safe-area-inset-bottom,0px));z-index:12500;display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 14px;border-radius:14px;background:#10233f;color:#eef6ff;box-shadow:0 10px 30px #0006;font-size:14px;line-height:1.4;max-width:560px;margin:0 auto';bar.innerHTML=html+'<button type="button" id="svPushX" aria-label="Dismiss" style="margin-left:auto;background:transparent;border:0;color:#9fb3cc;font-size:20px;cursor:pointer">\u00d7</button>';document.body.appendChild(bar);const on=document.getElementById('svPushOn');if(on){on.style.cssText='background:#19c3d6;color:#04202a;border:0;border-radius:10px;padding:8px 14px;font-weight:700;cursor:pointer';on.onclick=()=>svEnableWebPush()}document.getElementById('svPushX').onclick=()=>{try{localStorage.setItem('sv_push_banner_dismissed','1')}catch(_){}svHidePushBanner()}}catch(_){}}
if('serviceWorker' in navigator){try{navigator.serviceWorker.addEventListener('message',ev=>{if(ev.data&&ev.data.type==='sv-push-open'){try{svPollMessageNotifications()}catch(_){}}})}catch(_){}}
/* SV79: trust badges, near me, availability, sharing (Future Chat first), data saver and the Future Chat launch list. */
function svNote(msg){try{let n=document.getElementById('svNote');if(n)n.remove();n=document.createElement('div');n.id='svNote';n.setAttribute('role','status');n.textContent=msg;n.style.cssText='position:fixed;left:50%;transform:translateX(-50%);bottom:calc(150px + env(safe-area-inset-bottom,0px));z-index:21500;background:#10233f;color:#fff;padding:10px 16px;border-radius:12px;font-size:14px;line-height:1.4;box-shadow:0 8px 24px #0005;max-width:90vw;text-align:center';document.body.appendChild(n);setTimeout(()=>{try{n.remove()}catch(_){}},4000)}catch(_){}}
/* SV81-WORLD: country, currency and local-time helpers for customers and providers anywhere. */
function svW(){return window.__svW||(window.__svW={"AO":["Angola","AOA","244"],"AR":["Argentina","ARS","54"],"AU":["Australia","AUD","61"],"AT":["Austria","EUR","43"],"BE":["Belgium","EUR","32"],"BW":["Botswana","BWP","267"],"BR":["Brazil","BRL","55"],"CM":["Cameroon","XAF","237"],"CA":["Canada","CAD","1"],"CL":["Chile","CLP","56"],"CO":["Colombia","COP","57"],"DK":["Denmark","DKK","45"],"EG":["Egypt","EGP","20"],"SZ":["Eswatini","SZL","268"],"ET":["Ethiopia","ETB","251"],"FR":["France","EUR","33"],"DE":["Germany","EUR","49"],"GH":["Ghana","GHS","233"],"HK":["Hong Kong","HKD","852"],"IN":["India","INR","91"],"ID":["Indonesia","IDR","62"],"IE":["Ireland","EUR","353"],"IL":["Israel","ILS","972"],"IT":["Italy","EUR","39"],"CI":["Ivory Coast","XOF","225"],"JP":["Japan","JPY","81"],"KE":["Kenya","KES","254"],"LS":["Lesotho","LSL","266"],"MW":["Malawi","MWK","265"],"MY":["Malaysia","MYR","60"],"MX":["Mexico","MXN","52"],"MA":["Morocco","MAD","212"],"MZ":["Mozambique","MZN","258"],"NA":["Namibia","NAD","264"],"NL":["Netherlands","EUR","31"],"NZ":["New Zealand","NZD","64"],"NG":["Nigeria","NGN","234"],"NO":["Norway","NOK","47"],"PK":["Pakistan","PKR","92"],"PH":["Philippines","PHP","63"],"PL":["Poland","PLN","48"],"PT":["Portugal","EUR","351"],"QA":["Qatar","QAR","974"],"RW":["Rwanda","RWF","250"],"SA":["Saudi Arabia","SAR","966"],"SN":["Senegal","XOF","221"],"SG":["Singapore","SGD","65"],"ZA":["South Africa","ZAR","27"],"ES":["Spain","EUR","34"],"SE":["Sweden","SEK","46"],"CH":["Switzerland","CHF","41"],"TZ":["Tanzania","TZS","255"],"TR":["Turkey","TRY","90"],"UG":["Uganda","UGX","256"],"AE":["United Arab Emirates","AED","971"],"GB":["United Kingdom","GBP","44"],"US":["United States","USD","1"],"ZM":["Zambia","ZMW","260"],"ZW":["Zimbabwe","USD","263"]})}
function svT(){return window.__svT||(window.__svT={"Africa/Johannesburg":"ZA","Europe/London":"GB","America/New_York":"US","America/Toronto":"CA","Australia/Sydney":"AU","Europe/Dublin":"IE","Pacific/Auckland":"NZ","Africa/Windhoek":"NA","Africa/Gaborone":"BW","Africa/Harare":"ZW","Africa/Lusaka":"ZM","Africa/Maputo":"MZ","Africa/Maseru":"LS","Africa/Mbabane":"SZ","Africa/Blantyre":"MW","Africa/Nairobi":"KE","Africa/Lagos":"NG","Africa/Accra":"GH","Africa/Kampala":"UG","Africa/Dar_es_Salaam":"TZ","Africa/Kigali":"RW","Africa/Addis_Ababa":"ET","Africa/Cairo":"EG","Africa/Casablanca":"MA","Africa/Dakar":"SN","Africa/Abidjan":"CI","Africa/Douala":"CM","Africa/Luanda":"AO","Europe/Berlin":"DE","Europe/Paris":"FR","Europe/Madrid":"ES","Europe/Lisbon":"PT","Europe/Rome":"IT","Europe/Amsterdam":"NL","Europe/Brussels":"BE","Europe/Zurich":"CH","Europe/Vienna":"AT","Europe/Stockholm":"SE","Europe/Oslo":"NO","Europe/Copenhagen":"DK","Europe/Warsaw":"PL","Asia/Kolkata":"IN","Asia/Karachi":"PK","Asia/Manila":"PH","Asia/Singapore":"SG","Asia/Kuala_Lumpur":"MY","Asia/Dubai":"AE","Asia/Riyadh":"SA","Asia/Qatar":"QA","America/Sao_Paulo":"BR","America/Mexico_City":"MX","America/Argentina/Buenos_Aires":"AR","America/Bogota":"CO","America/Santiago":"CL","Asia/Tokyo":"JP","Asia/Hong_Kong":"HK","Asia/Jakarta":"ID","Europe/Istanbul":"TR","Asia/Jerusalem":"IL","America/Chicago":"US","America/Denver":"US","America/Los_Angeles":"US","America/Phoenix":"US","America/Anchorage":"US","America/Detroit":"US","Pacific/Honolulu":"US","America/Indiana/Indianapolis":"US","America/Boise":"US","America/Vancouver":"CA","America/Edmonton":"CA","America/Winnipeg":"CA","America/Halifax":"CA","America/St_Johns":"CA","America/Regina":"CA","America/Montreal":"CA","Australia/Melbourne":"AU","Australia/Brisbane":"AU","Australia/Perth":"AU","Australia/Adelaide":"AU","Australia/Hobart":"AU","Australia/Darwin":"AU","Australia/Canberra":"AU","Europe/Belfast":"GB","Europe/Guernsey":"GB","Europe/Jersey":"GB","Europe/Isle_of_Man":"GB","Asia/Calcutta":"IN"})}
function svGuessCountry(){try{const z=Intl.DateTimeFormat().resolvedOptions().timeZone||'';if(svT()[z])return svT()[z]}catch(_){}try{for(const l of (navigator.languages||[navigator.language||''])){const r=(String(l).split('-')[1]||'').toUpperCase();if(svW()[r])return r}}catch(_){}return 'ZA'}
function svCountry(){try{if(typeof me!=='undefined'&&me&&svW()[me.country])return me.country}catch(_){}try{const s=localStorage.getItem('sv_country');if(svW()[s])return s}catch(_){}return svGuessCountry()}
function svCurOf(cc){return (svW()[cc]||svW().ZA)[1]}
function svMyCur(){return svCurOf(svCountry())}
function svProvCur(){if(window.svProviderCur)return window.svProviderCur;try{if(typeof me!=='undefined'&&me&&svW()[me.country])return svCurOf(me.country)}catch(_){}return svMyCur()}
function svBizCur(id){try{const b=(typeof allBusinesses!=='undefined'&&allBusinesses||[]).find(x=>Number(x.id)===Number(id));if(b)return b.currency||svCurOf(b.country)}catch(_){}return svMyCur()}
function svMoney(cents,cur){const v=Number(cents||0)/100;cur=cur||'ZAR';if(cur==='ZAR')return 'R'+v.toLocaleString('en-ZA',{minimumFractionDigits:2,maximumFractionDigits:2});try{return new Intl.NumberFormat(undefined,{style:'currency',currency:cur,currencyDisplay:'narrowSymbol'}).format(v)}catch(_){try{return new Intl.NumberFormat(undefined,{style:'currency',currency:cur}).format(v)}catch(__){return cur+' '+v.toFixed(2)}}}
function svCountryFilter(){try{return localStorage.getItem('sv_all_countries')!=='1'}catch(_){return true}}
function svShowAllCountries(){try{localStorage.setItem('sv_all_countries','1')}catch(_){}const t=document.getElementById('svCountryOnly');if(t)t.checked=false;try{loadBusinesses()}catch(_){}}
function svPlanPrice(zar){const cur=svMyCur(),r=window.svPlanRate;if(cur==='ZAR'||!r||r.currency!==cur)return 'R'+Number(zar).toLocaleString('en-ZA');return svMoney(Math.round(zar*r.rate*100),cur)+' <span class="tiny muted">= R'+Number(zar).toLocaleString('en-ZA')+'</span>'}
function svPlanNote(){const cur=svMyCur(),r=window.svPlanRate;if(cur==='ZAR'||!r||r.currency!==cur)return 'Prices are in South African rand (ZAR).';return 'Prices are shown in '+cur+' at today&#39;s exchange rate, worth exactly the same as the rand price.'}
async function svLoadRates(){const cc=svCountry();if(svCurOf(cc)==='ZAR'){window.svPlanRate=null;return}try{const r=await fetch('/api/prices?country='+encodeURIComponent(cc));const d=await r.json();if(d&&d.currency&&!d.fallback){window.svPlanRate={currency:d.currency,rate:Number(d.rate)};if(document.getElementById('plans')&&typeof drawPlans==='function')drawPlans()}}catch(_){}}
function svFillCountrySelects(){const cc=svCountry();document.querySelectorAll('select.sv-country-select').forEach(s=>{if(!s.options.length)s.innerHTML=Object.entries(svW()).map(([k,v])=>'<option value="'+k+'">'+v[0]+' ('+v[1]+')</option>').join('');if(!s.dataset.touched)s.value=s.dataset.value||cc;s.onchange=()=>{s.dataset.touched='1'}})}
function svPhoneHints(){const dial=(svW()[svCountry()]||svW().ZA)[2];document.querySelectorAll('input[type=tel]').forEach(i=>{if(!i.placeholder||i.placeholder==='+…'||i.dataset.svDial){i.placeholder='+'+dial+' …';i.dataset.svDial='1'}})}
async function svSetCountry(cc){if(!svW()[cc])return;try{localStorage.setItem('sv_country',cc)}catch(_){}try{if(typeof me!=='undefined'&&me&&token){await api('/api/me/country',{method:'POST',body:JSON.stringify({country:cc})});me.country=cc}}catch(_){}window.svPlanRate=null;svWorldInit();try{loadBusinesses()}catch(_){}}
async function svDownloadMyData(){const st=document.getElementById('svExportState');try{if(st)st.textContent='Preparing your file…';const d=await api('/api/account/export');const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='skillvaya-my-data.json';document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},2000);if(st)st.textContent='Downloaded: skillvaya-my-data.json'}catch(e){if(st)st.textContent='Could not download: '+e.message}}
function svInjectCountryCard(s){if(!s||document.getElementById('svCountryCard'))return;const c=document.createElement('div');c.id='svCountryCard';c.className='card';c.style.cssText='margin:16px 0;border-radius:16px;padding:14px 16px;background:#fff;border:1px solid #dce7f5;color:#122238';c.innerHTML='<label for="svLangPick" style="display:block"><strong>Language</strong></label><select id="svLangPick" style="margin:8px 0 14px"></select><label for="svCountryPick" style="display:block"><strong>Country</strong><span class="muted tiny" style="display:block">Sets your currency, phone code and which providers you see first.</span></label><select id="svCountryPick" class="sv-country-select" style="margin-top:8px"></select><label style="display:flex;align-items:center;gap:10px;margin-top:12px;cursor:pointer"><input type="checkbox" id="svCountryOnly" style="width:20px;height:20px;flex:none"><span>Only show providers in my country (online providers always show)</span></label><div style="margin-top:14px"><button type="button" class="ghost" onclick="svDownloadMyData()">⬇ Download my data</button><span id="svExportState" class="muted tiny" style="display:block;margin-top:6px">A copy of your account, listings, jobs and messages. Sign in first.</span></div>';s.appendChild(c);const lp=document.getElementById('svLangPick');lp.innerHTML=Object.entries(svLangs()).map(([k,v])=>'<option value="'+k+'">'+v+'</option>').join('');lp.value=svI().lang||svLang();lp.setAttribute('data-no-tr','1');lp.onchange=()=>svSetLang(lp.value);svFillCountrySelects();const p=document.getElementById('svCountryPick');p.value=svCountry();p.onchange=()=>svSetCountry(p.value);const o=document.getElementById('svCountryOnly');o.checked=svCountryFilter();o.onchange=()=>{try{localStorage.setItem('sv_all_countries',o.checked?'0':'1')}catch(_){}try{loadBusinesses()}catch(_){}}}
function svJobBudgetLabel(){const sel=document.getElementById('jobBusinessId'),l=document.getElementById('svJobBudgetLabel');if(l)l.textContent='Budget in '+(sel&&sel.value?svBizCur(sel.value):svMyCur())+' (optional)'}
document.addEventListener('change',e=>{if(e.target&&e.target.id==='jobBusinessId')svJobBudgetLabel()});
function svPlayOnlyNotice(){const old=document.getElementById('svPlayOnly');if(old)old.remove();const o=document.createElement('div');o.id='svPlayOnly';o.style.cssText='position:fixed;inset:0;z-index:100000;background:rgba(5,18,38,.72);display:flex;align-items:center;justify-content:center;padding:18px';o.innerHTML='<section style="width:min(100%,440px);background:#fff;color:#17263b;border-radius:22px;padding:24px;box-shadow:0 24px 80px #0005;font:15px/1.5 Arial,sans-serif"><h2 style="margin:0 0 8px;font-size:22px">Subscribe in the Android app</h2><p style="margin:0 0 16px;color:#4b5d72">Provider plans are bought only in the Skillvaya Android app through Google Play. Google Play shows the final price in your currency and handles any taxes.</p><a href="https://play.google.com/store/apps/details?id=za.co.skillvaya.app" target="_blank" rel="noopener" style="display:block;text-align:center;background:#087f8c;color:#fff;border-radius:12px;padding:13px;font-weight:800;text-decoration:none">Get Skillvaya on Google Play</a><button type="button" id="svPlayOnlyClose" style="display:block;width:100%;margin-top:10px;border:0;background:transparent;padding:10px;color:#53657a;font-weight:700;cursor:pointer">Close</button></section>';document.body.appendChild(o);o.onclick=e=>{if(e.target===o)o.remove()};document.getElementById('svPlayOnlyClose').onclick=()=>o.remove()}
/* SV82-I18N: the app's on-screen wording in the chosen language. Text people type (chats, names, descriptions in inputs) is never changed. */
function svLangs(){return {en:'English',af:'Afrikaans',zu:'isiZulu',xh:'isiXhosa',st:'Sesotho',fr:'Français',pt:'Português',es:'Español',de:'Deutsch',sw:'Kiswahili',tn:'Setswana',hi:'हिन्दी',zh:'中文',ar:'العربية'}}
function svI(){return window.__svI||(window.__svI={lang:'en',dict:null,orig:new WeakMap(),last:new WeakMap(),attr:new WeakMap(),obs:null,started:false})}
function svExtraWords(){return {'Language':{af:'Taal',zu:'Ulimi',xh:'Ulwimi',st:'Puo',fr:'Langue',pt:'Idioma',es:'Idioma',de:'Sprache',sw:'Lugha',tn:'Puo',hi:'भाषा',zh:'语言',ar:'اللغة'},'Legal documents are shown in English.':{af:'Regsdokumente word in Engels gewys.',zu:'Imibhalo yezomthetho ikhonjiswa ngesiNgisi.',xh:'Amaxwebhu asemthethweni aboniswa ngesiNgesi.',st:'Ditokomane tsa molao di bontshwa ka Senyesemane.',fr:'Les documents juridiques sont affichés en anglais.',pt:'Os documentos legais são apresentados em inglês.',es:'Los documentos legales se muestran en inglés.',de:'Rechtliche Dokumente werden auf Englisch angezeigt.',sw:'Nyaraka za kisheria zinaonyeshwa kwa Kiingereza.',tn:'Dikwalo tsa molao di bontshiwa ka Seesimane.',hi:'कानूनी दस्तावेज़ अंग्रेज़ी में दिखाए जाते हैं।',zh:'法律文件以英文显示。',ar:'تُعرض المستندات القانونية باللغة الإنجليزية.'}}}
function svLang(){const L=svLangs();try{const s=localStorage.getItem('sv_lang');if(L[s])return s}catch(_){}try{for(const l of (navigator.languages||[navigator.language||''])){const c=String(l).slice(0,2).toLowerCase();if(L[c])return c}}catch(_){}return 'en'}
function svTrText(s){const I=svI();if(!I.dict||s==null)return s;s=String(s);const k=s.replace(/\s+/g,' ').trim();const t=I.dict[k];if(!t)return s;return s.match(/^\s*/)[0]+t+s.match(/\s*$/)[0]}
function svTrSkip(el){return !el||/^(SCRIPT|STYLE|TEXTAREA|CODE|NOSCRIPT|INPUT)$/.test(el.tagName)||!!el.closest('[data-no-tr],.message-bubble,.sv-chat-attachment,.conversation-summary,.message-conversation-header,#ownerApp')}
function svTrNode(n){const I=svI();const p=n.parentElement;if(svTrSkip(p))return;const cur=n.nodeValue;let o=I.orig.get(n);if(o===undefined||cur!==I.last.get(n)){o=cur;I.orig.set(n,o)}const out=svTrText(o);if(out!==cur)n.nodeValue=out;I.last.set(n,out)}
function svTrAttrs(el){if(!el||!el.getAttribute||svTrSkip(el.closest?(el.tagName==='INPUT'||el.tagName==='TEXTAREA'?el.parentElement:el):el))return;const I=svI();let m=I.attr.get(el);if(!m){m={};I.attr.set(el,m)}for(const a of ['placeholder','title','aria-label']){const cur=el.getAttribute(a);if(cur==null)continue;const rec=m[a];if(!rec||cur!==rec.last){m[a]={orig:cur,last:cur}}const out=svTrText(m[a].orig);if(out!==cur)el.setAttribute(a,out);m[a].last=out}}
function svTrApply(root){root=root||document.body;if(!root)return;if(root.nodeType===3){svTrNode(root);return}if(root.nodeType!==1)return;const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let n;while((n=w.nextNode()))svTrNode(n);svTrAttrs(root);root.querySelectorAll('[placeholder],[title],[aria-label]').forEach(svTrAttrs)}
function svTrWatch(){const I=svI();if(I.obs||!document.body)return;let q=[],t=0;const run=()=>{t=0;const items=q;q=[];for(const x of items){if(x.type==='childList')x.added.forEach(svTrApply);else if(x.type==='characterData')svTrNode(x.target);else svTrAttrs(x.target)}};I.obs=new MutationObserver(ms=>{const I2=svI();if(!I2.dict&&I2.lang==='en'&&!I2.started)return;for(const m of ms){if(m.type==='childList'){if(m.addedNodes.length)q.push({type:'childList',added:[...m.addedNodes]})}else q.push({type:m.type,target:m.target})}if(!t)t=setTimeout(run,0)});I.obs.observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['placeholder','title','aria-label']})}
function svTrDialogs(){if(window.__svTrDlg)return;window.__svTrDlg=1;const a=window.alert,c=window.confirm,p=window.prompt;window.alert=m=>a.call(window,svTrText(m));window.confirm=m=>c.call(window,svTrText(m));window.prompt=(m,d)=>p.call(window,svTrText(m),d)}
function svLangDir(l){const h=document.documentElement;h.lang=l;h.dir=l==='ar'?'rtl':'ltr';document.body&&document.body.classList.toggle('sv-rtl',l==='ar')}
function svUseDict(l,strings){const I=svI();const d=Object.assign({},strings||{});const x=svExtraWords();for(const k in x)if(x[k][l])d[k]=x[k][l];I.lang=l;I.dict=l==='en'?null:d;I.started=true;svLangDir(l);svTrApply(document.body);svTrDialogs();svTrWatch();const pick=document.getElementById('svLangPick');if(pick)pick.value=l}
async function svLoadLang(l){if(!svLangs()[l])l='en';if(l==='en'){svUseDict('en',null);return}const key='sv_i18n_'+l;let cached=null;try{cached=JSON.parse(localStorage.getItem(key)||'null')}catch(_){}if(cached&&cached.strings)svUseDict(l,cached.strings);try{const r=await fetch('/api/i18n?lang='+encodeURIComponent(l));const d=await r.json();if(d&&d.strings&&(!cached||cached.version!==d.version)){try{localStorage.setItem(key,JSON.stringify({version:d.version,strings:d.strings}))}catch(_){}if(svI().lang===l||!cached)svUseDict(l,d.strings)}}catch(_){}}
function svSetLang(l){try{localStorage.setItem('sv_lang',l)}catch(_){}svLoadLang(l)}
function svInitLang(){const I=svI();if(I.init)return;I.init=1;const l=svLang();if(l!=='en')svLoadLang(l)}
function svWorldInit(){try{svInitLang();svFillCountrySelects();svPhoneHints();svJobBudgetLabel();svLoadRates();const p=document.getElementById('svCountryPick');if(p)p.value=svCountry()}catch(_){}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',svWorldInit);else setTimeout(svWorldInit,0);
function svDataSaver(){try{const v=localStorage.getItem('sv_data_saver');if(v==='1')return true;if(v==='0')return false}catch(_){}try{return !!(navigator.connection&&navigator.connection.saveData)}catch(_){return false}}
function svDataSaverText(){const s=document.getElementById('svDataSaverState');if(s)s.textContent=svDataSaver()?'On: photos and videos load only when you tap them.':'Off: photos load automatically.'}
function svApplyDataSaver(){try{document.body.classList.toggle('sv-data-saver',svDataSaver())}catch(_){}svDataSaverText()}
function svSetDataSaver(on){try{localStorage.setItem('sv_data_saver',on?'1':'0')}catch(_){}svApplyDataSaver()}
function svTrustBadges(b){if(!b)return '';const chip=(t,bg,fg)=>'<span class="sv-chip" style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700;line-height:1.6;background:'+bg+';color:'+fg+';margin:6px 6px 0 0">'+t+'</span>';let h='';if(b.verified)h+=chip('✔ Verified by Skillvaya','#e3f6ec','#11683d');if(b.available_today)h+=chip('● Available today','#e6f4ff','#0b5a9c');if(b.distance_km!==null&&b.distance_km!==undefined)h+=chip('📍 '+(Number(b.distance_km)<1?'Under 1':Math.round(Number(b.distance_km)))+' km away','#f2f0ff','#4b3aa8');const j=Number(b.jobs_done)||0;if(j>0)h+=chip('🧰 '+(j>=10?'10+':j)+' job'+(j===1?'':'s')+' done','#fff4e0','#8a5200');return h?'<div class="sv-trust" style="margin:4px 0 2px">'+h+'</div>':''}
let svPosCache=null;
function svGetPosition(){return new Promise(res=>{if(svPosCache&&Date.now()-svPosCache.t<6e5)return res(svPosCache);if(!navigator.geolocation)return res(null);let done=false;const t=setTimeout(()=>{if(!done){done=true;res(null)}},12000);try{navigator.geolocation.getCurrentPosition(p=>{if(done)return;done=true;clearTimeout(t);svPosCache={lat:p.coords.latitude.toFixed(3),lng:p.coords.longitude.toFixed(3),t:Date.now()};res(svPosCache)},()=>{if(done)return;done=true;clearTimeout(t);res(null)},{enableHighAccuracy:false,timeout:10000,maximumAge:600000})}catch(_){done=true;clearTimeout(t);res(null)}})}
let svPendingProvider=(()=>{try{return Number(new URLSearchParams(location.search).get('provider'))||0}catch(_){return 0}})();
function svOpenPendingProvider(){if(!svPendingProvider)return;const id=svPendingProvider;if(typeof allBusinesses==='undefined'||!allBusinesses||!allBusinesses.some(x=>Number(x.id)===id))return;svPendingProvider=0;try{const u=new URL(location.href);u.searchParams.delete('provider');history.replaceState(null,'',u.pathname+u.search+u.hash)}catch(_){}setTimeout(()=>openProvider(id),60)}
function svProviderLink(id){return location.origin+'/p/'+Number(id)}
function svShareSheet(title,text,url){const old=document.getElementById('svShareSheet');if(old)old.remove();const w=document.createElement('div');w.id='svShareSheet';w.style.cssText='position:fixed;inset:0;z-index:21000;background:#0008;display:flex;align-items:flex-end;justify-content:center';w.addEventListener('click',e=>{if(e.target===w)w.remove()});const btn='display:flex;align-items:center;gap:12px;width:100%;text-align:left;padding:14px 16px;border:1px solid #dce7f5;border-radius:14px;background:#fff;color:#122238;font-size:15px;font-weight:600;cursor:pointer;margin-top:10px';w.innerHTML='<div role="dialog" aria-label="Share" style="background:#f4f8ff;width:100%;max-width:520px;border-radius:20px 20px 0 0;padding:18px 16px calc(18px + env(safe-area-inset-bottom,0px));box-shadow:0 -10px 40px #0004"><div style="display:flex;justify-content:space-between;align-items:center"><strong style="font-size:17px;color:#10233f">Share</strong><button type="button" id="svShareX" aria-label="Close" style="background:transparent;border:0;font-size:24px;color:#5b6b80;cursor:pointer">\u00d7</button></div><button type="button" id="svShareFC" style="'+btn+';border:2px solid #19c3d6"><span style="font-size:24px">💬</span><span><span style="display:block">Future Chat</span><small style="font-weight:500;color:#5b6b80">Skillvaya\'s own messenger, coming soon. Tap to be notified at launch.</small></span></button><button type="button" id="svShareOther" style="'+btn+'"><span style="font-size:22px">↗</span><span>Share another way</span></button><button type="button" id="svShareCopy" style="'+btn+'"><span style="font-size:22px">⧉</span><span>Copy link</span></button></div>';document.body.appendChild(w);const close=()=>{try{w.remove()}catch(_){}};const copy=()=>{const done=()=>{close();svNote('Link copied. Paste it anywhere to share.')};try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(url).then(done,()=>{close();window.prompt('Copy this link:',url)});return}}catch(_){}close();window.prompt('Copy this link:',url)};document.getElementById('svShareX').onclick=close;document.getElementById('svShareCopy').onclick=copy;document.getElementById('svShareFC').onclick=()=>{close();svFutureChatNotify()};document.getElementById('svShareOther').onclick=()=>{if(navigator.share){navigator.share({title:title,text:text,url:url}).then(close,()=>{})}else copy()}}
function svShareProvider(id){const b=(typeof allBusinesses!=='undefined'&&allBusinesses||[]).find(x=>Number(x.id)===Number(id));const name=b?b.name:'This provider';svShareSheet(name+' on Skillvaya','Have a look at '+name+(b?' ('+b.category+', '+b.area+')':'')+' on Skillvaya:',svProviderLink(id))}
function svLoadPortfolio(id,has){const slot=document.getElementById('svPortfolioSlot');if(!slot||!has)return;const go=()=>{slot.innerHTML='<p class="muted tiny">Loading work photos…</p>';fetch('/api/businesses/'+Number(id)+'/photos').then(r=>r.ok?r.json():{photos:''}).then(d=>{const s=document.getElementById('svPortfolioSlot');if(s)s.innerHTML=portfolioMarkup(d.photos||'')}).catch(()=>{const s=document.getElementById('svPortfolioSlot');if(s)s.innerHTML=''})};if(svDataSaver()){slot.innerHTML='<button type="button" class="ghost" style="margin:8px 0">📷 Show work photos (uses data)</button>';slot.firstChild.onclick=go}else go()}
async function svFutureChatStatus(){const st=document.getElementById('svFcState'),btn=document.getElementById('svFcNotifyBtn');if(!st)return;if(typeof me==='undefined'||!me){st.textContent='';return}try{const d=await api('/api/futurechat/status');if(d.joined){st.textContent="You're on the launch list. We'll alert you the moment Future Chat is out.";if(btn){btn.disabled=true;btn.textContent='On the launch list ✓';btn.style.opacity='.85'}}}catch(_){}}
async function svFutureChatNotify(){if(typeof me==='undefined'||!me){try{view('settings');profileAuthMode('signin')}catch(_){}alert("Sign in (it's free) so we can alert you the moment Future Chat launches.");return}try{await api('/api/futurechat/notify',{method:'POST',body:'{}'});svNote("You're on the Future Chat launch list ✓");svFutureChatStatus();try{if(svWebPushSupported()&&Notification.permission==='default')svMaybeShowPushBanner()}catch(_){}}catch(e){alert(e.message||e)}}
async function svRefreshProviderTools(){if(typeof me==='undefined'||!me||me.role!=='provider')return;const form=document.getElementById('bizForm');if(!form||!form.parentNode)return;let d;try{d=await api('/api/provider/tools')}catch(_){return}let box=document.getElementById('svProviderTools');if(!d||!d.business_id){if(box)box.remove();return}if(!box){box=document.createElement('div');box.id='svProviderTools';box.style.cssText='margin:0 0 16px;border:1px solid #d7e5f7;border-radius:16px;padding:16px;background:#f7fbff;color:#122238';form.parentNode.insertBefore(box,form)}const row='display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-top:1px solid #e3ecf7;flex-wrap:wrap';const b2='background:#10233f;color:#fff;border:0;border-radius:10px;padding:9px 14px;font-weight:700;cursor:pointer;white-space:nowrap';box.innerHTML='<h3 style="margin:0 0 4px">Grow your business</h3><p class="muted tiny" style="margin:0 0 4px">These show on your profile and help customers choose you.</p><div style="'+row+';border-top:0"><div style="flex:1;min-width:200px"><strong>Available today</strong><div class="muted tiny">Customers searching today see a blue "Available today" badge.</div></div><button type="button" id="svAvailBtn" style="'+b2+'">'+(d.available_today?'✓ On (tap to switch off)':'Switch on for today')+'</button></div><div style="'+row+'"><div style="flex:1;min-width:200px"><strong>Verified by Skillvaya</strong><div class="muted tiny">'+(d.verified?'Your profile shows the verified badge.':(d.verify_requested?'Request received. Skillvaya will contact you to confirm your identity and business.':'Ask Skillvaya to confirm your identity and business. Verified providers win more customers.'))+'</div></div>'+(d.verified?'<span style="color:#11683d;font-weight:800">✔ Verified</span>':(d.verify_requested?'<span class="muted">Requested</span>':'<button type="button" id="svVerifyBtn" style="'+b2+'">Get verified</button>'))+'</div><div style="'+row+'"><div style="flex:1;min-width:200px"><strong>Share your profile</strong><div class="muted tiny">Post your Skillvaya link on your status, social media and business cards.</div></div><button type="button" id="svShareMeBtn" style="'+b2+'">Share my profile</button></div><div style="'+row+'"><div style="flex:1;min-width:200px"><strong>Near me searches</strong><div class="muted tiny">'+(d.has_location?'Nearby customers see roughly how far away you are, worked out from your town (never your exact address).':'Keep your town / service area up to date below so nearby customers can find you.')+'</div></div></div>';document.getElementById('svAvailBtn').onclick=async()=>{try{await api('/api/provider/presence',{method:'POST',body:JSON.stringify({available_today:!d.available_today})});svNote(d.available_today?'Available today switched off':'You show as available today ✓');svRefreshProviderTools()}catch(e){alert(e.message)}};const vb=document.getElementById('svVerifyBtn');if(vb)vb.onclick=async()=>{try{await api('/api/provider/verification-request',{method:'POST',body:'{}'});svNote('Verification requested ✓');svRefreshProviderTools()}catch(e){alert(e.message)}};document.getElementById('svShareMeBtn').onclick=()=>svShareSheet((d.name||'My business')+' on Skillvaya','Find '+(d.name||'me')+(d.category?' ('+d.category+')':'')+' on Skillvaya:',svProviderLink(d.business_id))}
function svInjectSettingsCards(){const s=document.getElementById('settings');if(!s||document.getElementById('svDataSaverCard'))return;const c=document.createElement('div');c.id='svDataSaverCard';c.className='card';c.style.cssText='margin:16px 0;border-radius:16px;padding:14px 16px;background:#fff;border:1px solid #dce7f5;color:#122238';c.innerHTML='<label style="display:flex;align-items:center;justify-content:space-between;gap:12px;cursor:pointer"><span><strong>Data saver</strong><span id="svDataSaverState" class="muted tiny" style="display:block"></span></span><input type="checkbox" id="svDataSaverToggle" style="width:22px;height:22px;flex:none"></label>';s.appendChild(c);const t=document.getElementById('svDataSaverToggle');t.checked=svDataSaver();t.onchange=()=>svSetDataSaver(t.checked);svDataSaverText();svInjectCountryCard(s)}
async function svAdminVerify(id,on){try{await api('/api/admin/businesses-verify',{method:'POST',body:JSON.stringify({business_id:id,verified:!!on})});adminTab('businesses')}catch(e){alert(e.message)}}
async function svAdminFutureChat(){const box=document.getElementById('svFcAdmin');if(!box)return;try{const d=await api('/api/futurechat/status');const n=Number(d.count||0);box.innerHTML='<strong>Future Chat launch list:</strong> '+n+' '+(n===1?'person':'people')+' waiting. <button type="button" class="ghost" id="svFcAnnounce">Announce launch</button>';document.getElementById('svFcAnnounce').onclick=async()=>{const m=prompt('Alert to send to everyone on the list:','Future Chat is here! Download it now and start chatting.');if(!m)return;if(!confirm('Send this alert to '+n+' '+(n===1?'person':'people')+' now?'))return;try{const r=await api('/api/admin/futurechat',{method:'POST',body:JSON.stringify({action:'announce',message:m})});alert('Sending to '+r.sent+' '+(r.sent===1?'person':'people')+'.')}catch(e){alert(e.message)}}}catch(_){box.textContent=''}}
function svAfterLogin(){svFutureChatStatus();svRefreshProviderTools()}
(function(){const go=()=>{try{svApplyDataSaver();svInjectSettingsCards()}catch(_){}};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',go);else go()})();
</script></body></html>'''
SESSIONS={}
def issue_session(user):
    token=secrets.token_urlsafe(32)
    expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=3650)).isoformat()  # persistent sign-in; explicit logout revokes the token
    with conn() as c:
        c.execute("INSERT INTO auth_sessions(token,user_id,expires_at,created_at) VALUES(?,?,?,?)",(token,user["id"],expires,now()))
    SESSIONS[token]=user
    return token
def seo_robots_body():
    # Public discovery is allowed; private APIs and owner-only screens are not search content.
    return ("""User-agent: *
Allow: /
Disallow: /api/
Disallow: /owner-control
Disallow: /owner-app
Disallow: /login

User-agent: OAI-SearchBot
Allow: /
Disallow: /api/
Disallow: /owner-control
Disallow: /owner-app
Disallow: /login

Sitemap: https://skillvaya.onrender.com/sitemap.xml
""").encode("utf-8")


def seo_sitemap_body():
    today = datetime.date.today().isoformat()
    pages = [
        ("/", "weekly", "1.0"),
        ("/customer", "daily", "0.9"),
        ("/downloads", "weekly", "0.8"),
        ("/workfinder", "weekly", "0.7"),
        ("/terms", "monthly", "0.3"),
        ("/privacy", "monthly", "0.3"),
        ("/refund", "monthly", "0.3"),
        ("/cancellation", "monthly", "0.3"),
        ("/delivery", "monthly", "0.3"),
    ]
    entries = "".join(
        "<url><loc>https://skillvaya.onrender.com" + path +
        "</loc><lastmod>" + today + "</lastmod><changefreq>" + freq +
        "</changefreq><priority>" + priority + "</priority></url>"
        for path, freq, priority in pages
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
            entries + '</urlset>').encode("utf-8")


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
        path=urlparse(getattr(self,"path","")).path
        # Allow larger JSON only for the explicitly bounded in-chat image/video upload endpoint.
        max_bytes=20_000_000 if path=="/api/messages/attachments" else 3_000_000
        if n<0 or n>max_bytes: raise ValueError("Request too large")
        return json.loads(self.rfile.read(n) or b"{}")
    def user(self,want_photo=False):
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
            row=c.execute("SELECT u.id,u.name,u.email,u.phone,u.role,s.expires_at"+(",u.profile_photo" if want_photo else "")+" FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",(t,)).fetchone()
        if not row: return None
        if row["expires_at"] <= now():
            with conn() as c: c.execute("DELETE FROM auth_sessions WHERE token=?",(t,))
            return None
        user={"id":row["id"],"name":row["name"],"email":row["email"],"phone":row["phone"] or "","role":row["role"]}
        SESSIONS[t]=user
        if want_photo: return dict(user,profile_photo=row["profile_photo"])
        return user
    def require(self,role=None,want_photo=False):
        u=self.user(want_photo)
        local_only = (role == "admin" and self.client_address[0] in ("127.0.0.1", "::1")
                      and self.server.server_address[0] in ("127.0.0.1", "::1"))
        if not u and local_only:
            return {"id": 0, "name": "Local Developer", "email": "local-owner@skillvaya.local", "role": "admin"}
        if not u: raise PermissionError("Please sign in first.")
        if u.get("role")=="suspended": raise PermissionError("This account has been suspended.")
        if role and u["role"]!=role: raise PermissionError("This action requires a "+role+" account.")
        if u.get("role") in ("customer","provider") and setting("customer_provider_access","on")=="off" and urlparse(getattr(self,"path","/")).path!="/api/notifications":
            raise PermissionError("Customer and service provider access is temporarily paused by Skillvaya. Please try again later.")
        if u.get("role")=="provider": refresh_google_play_subscription_for_user(int(u["id"]))
        return u
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Headers","Content-Type, Authorization"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.end_headers()
    def _refund_list(self):
        with conn() as c:
            rows=c.execute("SELECT p.id,p.reference,p.plan,p.billing,p.amount,p.status,p.created_at,p.verified_at,p.pf_payment_id,p.payment_gateway,p.paypal_order_id,p.paypal_capture_id,p.refunded_amount,p.refund_status,u.email user_email FROM payments p JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC LIMIT 300").fetchall()
        return [dict(x) for x in rows]
    def handle_provider_growth(self, method, path, data=None):
        feature=path.rsplit("/",1)[-1]
        allowed={
            "pipeline":2,"bookings":2,"crm":2,"followups":2,"invoices":2,"reviews":2,"packages":2,
            "offers":3,"team":3,"marketing":3,"announcements":3,"automation":3
        }
        if feature not in allowed:
            return self.sendj({"error":"Growth tool not found."},404)
        u=self.require()
        d=data or {}
        if feature=="team" and method=="POST" and str(d.get("action",""))=="accept_invite":
            if u.get("role") not in ("customer","provider","admin"):
                return self.sendj({"error":"Sign in with the invited account to accept this invitation."},403)
            code=str(d.get("invite_code","")).strip()[:100]
            with conn() as c:
                invite=c.execute("SELECT * FROM provider_team_members WHERE invite_code=? AND status='invited'",(code,)).fetchone()
                if not invite:return self.sendj({"error":"This invitation is invalid, expired or already accepted."},404)
                if str(invite["email"]).lower()!=str(u.get("email","")).lower():return self.sendj({"error":"Sign in with the email address that received this invitation."},403)
                c.execute("UPDATE provider_team_members SET user_id=?,status='active',updated_at=? WHERE id=?",(u["id"],now(),invite["id"]))
                return self.sendj({"ok":True,"business_id":int(invite["business_id"]),"team_member_id":int(invite["id"]),"message":"Your team invitation was accepted."})
        if u.get("role") not in ("provider","admin"):
            return self.sendj({"error":"Only provider accounts can use this tool."},403)
        query=urllib.parse.parse_qs(urlparse(self.path).query)
        ranks=PROVIDER_TIER_RANKS
        test_tier=subscription_test_tier(u,query,d)
        with conn() as c:
            biz=c.execute("SELECT id,user_id,name,plan,payment_status,status FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
        if u["role"]=="provider":
            if not biz or str(biz["payment_status"] or "")!="verified":
                return self.sendj({"error":"A verified provider profile is required to use business growth tools."},403)
            business_id=int(biz["id"]); plan=str(biz["plan"] or "local").lower()
        else:
            if not biz:
                with conn() as c:
                    biz=c.execute("SELECT id,user_id,name,plan,payment_status,status FROM businesses WHERE LOWER(TRIM(name))='skillvaya digital & creative studio' ORDER BY id DESC LIMIT 1").fetchone()
            business_id=int(biz["id"]) if biz else 0
            plan="spotlight"
            if test_tier:
                plan=test_tier
                business_id=subscription_test_business_id(u["id"],test_tier)
        rank=ranks.get(plan,0)
        if rank<allowed[feature]:
            need="Business Plus" if allowed[feature]==2 else "Business Spotlight"
            return self.sendj({"error":feature.replace("_"," ").title()+" requires "+need+" or above."},403)
        uid=int(u["id"]); stamp=now()
        try:
            with conn() as c:
                if feature=="pipeline":
                    rows=c.execute("""SELECT j.*,COALESCE(b.name,?) business_name,cu.name customer_name
                        FROM job_requests j LEFT JOIN businesses b ON b.id=j.business_id
                        JOIN users cu ON cu.id=j.customer_id
                        WHERE j.business_id=? ORDER BY j.updated_at DESC,j.id DESC LIMIT 200""",("Sandbox "+plan.title()+" test account",business_id)).fetchall()
                    items=[]
                    for r in rows:
                        item=dict(r)
                        item["quotes"]=[dict(q) for q in c.execute("SELECT id,amount_cents,eta,message,status,created_at FROM job_quotes WHERE job_id=? ORDER BY created_at",(r["id"],)).fetchall()]
                        items.append(item)
                    return self.sendj({"items":items,"plan":plan})
                if feature=="bookings":
                    if method=="GET":
                        rows=c.execute("SELECT * FROM provider_bookings WHERE business_id=? ORDER BY starts_at DESC,id DESC LIMIT 300",(business_id,)).fetchall()
                        return self.sendj({"items":[dict(x) for x in rows],"plan":plan})
                    action=str(d.get("action","create"))
                    if action=="create":
                        title=str(d.get("title","")).strip()[:160]
                        customer_name=str(d.get("customer_name","")).strip()[:120]
                        customer_contact=str(d.get("customer_contact","")).strip()[:200]
                        starts=str(d.get("starts_at","")).strip()[:40]; ends=str(d.get("ends_at","")).strip()[:40]
                        notes=str(d.get("notes","")).strip()[:2000]
                        if len(title)<2 or not starts: return self.sendj({"error":"Enter a title and start date/time."},400)
                        if ends and ends<starts: return self.sendj({"error":"End time must be on or after the start time."},400)
                        cur=c.execute("INSERT INTO provider_bookings(business_id,user_id,customer_name,customer_contact,title,notes,starts_at,ends_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'scheduled',?,?) RETURNING id",(business_id,uid,customer_name,customer_contact,title,notes,starts,ends,stamp,stamp))
                        return self.sendj({"ok":True,"id":cur.fetchone()["id"],"message":"Booking saved."},201)
                    if action=="status":
                        try: bid=int(d.get("id",0))
                        except (TypeError,ValueError): return self.sendj({"error":"Invalid booking."},400)
                        status=str(d.get("status",""))
                        if status not in ("scheduled","completed","cancelled"): return self.sendj({"error":"Invalid booking status."},400)
                        cur=c.execute("UPDATE provider_bookings SET status=?,updated_at=? WHERE id=? AND business_id=?",(status,stamp,bid,business_id))
                        if cur.rowcount!=1:return self.sendj({"error":"Booking not found."},404)
                        return self.sendj({"ok":True,"status":status})
                if feature=="crm":
                    if method=="GET":
                        rows=c.execute("""SELECT DISTINCT u.id customer_id,u.name,u.email,u.phone
                            FROM users u WHERE
                            EXISTS(SELECT 1 FROM job_requests j WHERE j.business_id=? AND j.customer_id=u.id)
                            OR EXISTS(SELECT 1 FROM messages m WHERE m.business_id=? AND m.customer_id=u.id)
                            OR EXISTS(SELECT 1 FROM contacts ct WHERE ct.business_id=? AND ct.customer_id=u.id)
                            OR EXISTS(SELECT 1 FROM enquiries e WHERE e.business_id=? AND e.customer_id=u.id)
                            ORDER BY u.name LIMIT 500""",(business_id,business_id,business_id,business_id)).fetchall()
                        items=[]
                        for r in rows:
                            cid=int(r["customer_id"])
                            requests=c.execute("SELECT count(*) FROM job_requests WHERE business_id=? AND customer_id=?",(business_id,cid)).fetchone()[0]
                            quotes=c.execute("SELECT count(*) FROM job_quotes WHERE business_id=? AND job_id IN (SELECT id FROM job_requests WHERE business_id=? AND customer_id=?)",(business_id,business_id,cid)).fetchone()[0]
                            messages=c.execute("SELECT count(*),max(created_at) FROM messages WHERE business_id=? AND customer_id=?",(business_id,cid)).fetchone()
                            note=c.execute("SELECT notes,tags FROM provider_customer_notes WHERE business_id=? AND customer_id=?",(business_id,cid)).fetchone()
                            items.append({**dict(r),"request_count":int(requests),"quote_count":int(quotes),"message_count":int(messages[0] or 0),"last_activity":messages[1] or "","notes":note["notes"] if note else "","tags":note["tags"] if note else ""})
                        return self.sendj({"items":items})
                    if str(d.get("action",""))!="save_note":return self.sendj({"error":"Unsupported CRM action."},400)
                    try: cid=int(d.get("customer_id",0))
                    except (TypeError,ValueError):return self.sendj({"error":"Invalid customer."},400)
                    interaction=c.execute("SELECT 1 FROM contacts WHERE business_id=? AND customer_id=? UNION SELECT 1 FROM messages WHERE business_id=? AND customer_id=? UNION SELECT 1 FROM job_requests WHERE business_id=? AND customer_id=? LIMIT 1",(business_id,cid,business_id,cid,business_id,cid)).fetchone()
                    if not interaction:return self.sendj({"error":"CRM notes are limited to customers you have interacted with through Skillvaya."},403)
                    notes=str(d.get("notes","")).strip()[:3000];tags=str(d.get("tags","")).strip()[:400]
                    c.execute("INSERT INTO provider_customer_notes(business_id,user_id,customer_id,notes,tags,created_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(business_id,customer_id) DO UPDATE SET notes=excluded.notes,tags=excluded.tags,updated_at=excluded.updated_at",(business_id,uid,cid,notes,tags,stamp,stamp))
                    return self.sendj({"ok":True})
                if feature=="followups":
                    if method=="GET":
                        q=c.execute("""SELECT j.id job_id,j.title,j.customer_id,cu.name customer_name,q.created_at quote_created_at
                            FROM job_quotes q JOIN job_requests j ON j.id=q.job_id JOIN users cu ON cu.id=j.customer_id
                            WHERE j.business_id=? AND q.business_id=? AND q.status='pending'
                            ORDER BY q.created_at DESC LIMIT 200""",(business_id,business_id)).fetchall()
                        f=c.execute("SELECT * FROM provider_followups WHERE business_id=? ORDER BY remind_at ASC,id DESC LIMIT 300",(business_id,)).fetchall()
                        return self.sendj({"items":[dict(x) for x in q],"followups":[dict(x) for x in f]})
                    action=str(d.get("action","create"))
                    if action=="create":
                        try: jid=int(d.get("job_id",0))
                        except (TypeError,ValueError): return self.sendj({"error":"Choose a valid quote request."},400)
                        remind=str(d.get("remind_at","")).strip()[:40];note=str(d.get("note","")).strip()[:300]
                        job=c.execute("SELECT id,customer_id FROM job_requests WHERE id=? AND business_id=? AND status IN ('requested','quoted')",(jid,business_id)).fetchone()
                        quote=c.execute("SELECT id FROM job_quotes WHERE job_id=? AND business_id=? AND status='pending' LIMIT 1",(jid,business_id)).fetchone()
                        if not job or not quote:return self.sendj({"error":"Choose a request with a pending quotation."},400)
                        if not remind:return self.sendj({"error":"Choose a reminder date and time."},400)
                        cur=c.execute("INSERT INTO provider_followups(business_id,user_id,job_id,customer_id,remind_at,note,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending',?,?) RETURNING id",(business_id,uid,jid,job["customer_id"],remind,note,stamp,stamp))
                        return self.sendj({"ok":True,"id":cur.fetchone()["id"]},201)
                    if action=="status":
                        try: fid=int(d.get("id",0))
                        except (ValueError,TypeError):return self.sendj({"error":"Invalid follow-up."},400)
                        status=str(d.get("status",""))
                        if status not in ("pending","completed","cancelled"):return self.sendj({"error":"Invalid reminder status."},400)
                        cur=c.execute("UPDATE provider_followups SET status=?,updated_at=? WHERE id=? AND business_id=?",(status,stamp,fid,business_id))
                        if cur.rowcount!=1:return self.sendj({"error":"Reminder not found."},404)
                        return self.sendj({"ok":True})
                if feature=="invoices":
                    if method=="GET":
                        rows=c.execute("SELECT * FROM provider_invoices WHERE business_id=? ORDER BY created_at DESC,id DESC LIMIT 300",(business_id,)).fetchall()
                        items=[dict(r) for r in rows]
                        outstanding=sum(max(0,int(r["amount_cents"])-int(r["amount_paid_cents"])) for r in items if r["status"] not in ("cancelled","paid"))
                        today=datetime.date.today().isoformat()
                        overdue=sum(1 for r in items if r["status"] not in ("cancelled","paid") and r["due_date"] and r["due_date"]<today and int(r["amount_paid_cents"])<int(r["amount_cents"]))
                        return self.sendj({"items":items,"totals":{"outstanding_cents":outstanding,"overdue":overdue}})
                    action=str(d.get("action","create"))
                    if action=="create":
                        customer=str(d.get("customer_name","")).strip()[:120]; email=str(d.get("customer_email","")).strip().lower()[:254]
                        desc=str(d.get("description","")).strip()[:2000];due=str(d.get("due_date","")).strip()[:20]
                        try: amount=round(float(d.get("amount_rands",0))*100);jid=int(d.get("job_id",0) or 0)
                        except (ValueError,TypeError):return self.sendj({"error":"Enter a valid amount and request ID."},400)
                        if not customer or len(desc)<3 or amount<=0 or amount>1_000_000_000:return self.sendj({"error":"Enter customer name, description and a positive invoice amount."},400)
                        if jid and not c.execute("SELECT id FROM job_requests WHERE id=? AND business_id=?",(jid,business_id)).fetchone():return self.sendj({"error":"The selected job request does not belong to this business."},400)
                        number="SVI-"+secrets.token_hex(4).upper()
                        cur=c.execute("INSERT INTO provider_invoices(business_id,user_id,job_id,invoice_number,customer_name,customer_email,description,amount_cents,due_date,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'draft',?,?) RETURNING id",(business_id,uid,jid or None,number,customer,email,desc,amount,due,stamp,stamp))
                        return self.sendj({"ok":True,"id":cur.fetchone()["id"],"invoice_number":number,"message":"Invoice record created; no payment was taken."},201)
                    try:iid=int(d.get("id",0))
                    except (ValueError,TypeError):return self.sendj({"error":"Invalid invoice."},400)
                    inv=c.execute("SELECT * FROM provider_invoices WHERE id=? AND business_id=?",(iid,business_id)).fetchone()
                    if not inv:return self.sendj({"error":"Invoice not found."},404)
                    if action=="record_payment":
                        try: amount=round(float(d.get("amount_rands",0))*100)
                        except (ValueError,TypeError):return self.sendj({"error":"Enter a valid payment amount."},400)
                        remaining=int(inv["amount_cents"])-int(inv["amount_paid_cents"])
                        if amount<=0 or amount>remaining or inv["status"]=="cancelled":return self.sendj({"error":"Payment amount must be positive and no greater than the remaining invoice balance."},400)
                        paid=int(inv["amount_paid_cents"])+amount;status="paid" if paid>=int(inv["amount_cents"]) else inv["status"]
                        c.execute("UPDATE provider_invoices SET amount_paid_cents=?,status=?,paid_at=?,updated_at=? WHERE id=? AND business_id=?",(paid,status,stamp if status=="paid" else inv["paid_at"],stamp,iid,business_id))
                        return self.sendj({"ok":True,"status":status,"amount_paid_cents":paid,"message":"Payment entry recorded in the ledger only."})
                    if action=="status":
                        status=str(d.get("status",""))
                        if status not in ("issued","cancelled") or inv["status"]=="paid":return self.sendj({"error":"Invalid invoice status change."},400)
                        c.execute("UPDATE provider_invoices SET status=?,updated_at=? WHERE id=? AND business_id=?",(status,stamp,iid,business_id))
                        return self.sendj({"ok":True,"status":status})
                if feature=="reviews":
                    if method=="GET":
                        rows=c.execute("""SELECT r.id,r.business_id,r.rater_id AS customer_id,r.stars,r.created_at,u.name customer_name
                            FROM ratings r JOIN users u ON u.id=r.rater_id
                            WHERE r.business_id=? AND r.target_type='provider' ORDER BY r.created_at DESC LIMIT 300""",(business_id,)).fetchall()
                        items=[]
                        for r in rows:
                            x=dict(r); reply=c.execute("SELECT reply FROM provider_review_replies WHERE rating_id=? AND business_id=?",(r["id"],business_id)).fetchone();x["reply"]=reply["reply"] if reply else "";items.append(x)
                        return self.sendj({"items":items})
                    if str(d.get("action"))!="reply":return self.sendj({"error":"Unsupported review action."},400)
                    try:rid=int(d.get("rating_id",0))
                    except (ValueError,TypeError):return self.sendj({"error":"Invalid review."},400)
                    if not c.execute("SELECT id FROM ratings WHERE id=? AND business_id=? AND target_type='provider'",(rid,business_id)).fetchone():return self.sendj({"error":"Review not found for this business."},404)
                    reply=str(d.get("reply","")).strip()[:1500]
                    if len(reply)<3:return self.sendj({"error":"Reply must contain at least three characters."},400)
                    updated=c.execute("UPDATE provider_review_replies SET reply=?,updated_at=? WHERE rating_id=? AND business_id=?",(reply,stamp,rid,business_id))
                    if updated.rowcount==0:
                        c.execute("INSERT INTO provider_review_replies(business_id,user_id,rating_id,reply,created_at,updated_at) VALUES(?,?,?,?,?,?)",(business_id,uid,rid,reply,stamp,stamp))
                    saved=c.execute("SELECT id FROM provider_review_replies WHERE rating_id=? AND business_id=? AND reply=?",(rid,business_id,reply)).fetchone()
                    if not saved:return self.sendj({"error":"Review reply could not be persisted."},500)
                    return self.sendj({"ok":True,"id":int(saved["id"]),"rating_id":rid})
                if feature=="packages":
                    if method=="GET":
                        rows=c.execute("SELECT * FROM provider_service_packages WHERE business_id=? ORDER BY created_at DESC,id DESC LIMIT 200",(business_id,)).fetchall()
                        items=[]
                        for r in rows:
                            x=dict(r)
                            try:x["add_ons"]=json.loads(x["add_ons"] or "[]")
                            except Exception:x["add_ons"]=[]
                            items.append(x)
                        return self.sendj({"items":items})
                    action=str(d.get("action","create"))
                    if action=="create":
                        name=str(d.get("name","")).strip()[:120];desc=str(d.get("description","")).strip()[:1500];status=str(d.get("status","draft"))
                        try:price=round(float(d.get("price_rands",0))*100)
                        except (ValueError,TypeError):return self.sendj({"error":"Enter a valid package price."},400)
                        if len(name)<2 or len(desc)<3 or price<=0 or price>1_000_000_000 or status not in ("active","draft"):return self.sendj({"error":"Enter package name, description, price and a valid visibility."},400)
                        add_ons=[]
                        for line in str(d.get("add_ons","")).splitlines()[:20]:
                            if "|" not in line:continue
                            n,pr=line.split("|",1)
                            try: cents=round(float(pr.strip().replace("R",""))*100)
                            except ValueError:continue
                            if n.strip() and 0<cents<=1_000_000_000:add_ons.append({"name":n.strip()[:100],"price_cents":cents})
                        cur=c.execute("INSERT INTO provider_service_packages(business_id,user_id,name,description,price_cents,add_ons,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) RETURNING id",(business_id,uid,name,desc,price,json.dumps(add_ons),status,stamp,stamp))
                        return self.sendj({"ok":True,"id":cur.fetchone()["id"]},201)
                    try:pid=int(d.get("id",0))
                    except (ValueError,TypeError):return self.sendj({"error":"Invalid package."},400)
                    row=c.execute("SELECT id FROM provider_service_packages WHERE id=? AND business_id=?",(pid,business_id)).fetchone()
                    if not row:return self.sendj({"error":"Package not found."},404)
                    if action=="delete":c.execute("DELETE FROM provider_service_packages WHERE id=? AND business_id=?",(pid,business_id));return self.sendj({"ok":True})
                    status=str(d.get("status",""))
                    if status not in ("active","draft"):return self.sendj({"error":"Invalid package status."},400)
                    c.execute("UPDATE provider_service_packages SET status=?,updated_at=? WHERE id=? AND business_id=?",(status,stamp,pid,business_id));return self.sendj({"ok":True})
                if feature=="offers":
                    if method=="GET":
                        rows=c.execute("SELECT * FROM provider_offers WHERE business_id=? ORDER BY created_at DESC,id DESC LIMIT 200",(business_id,)).fetchall()
                        stats={}
                        for et in ("profile_view","lead"):
                            stats["profile_views" if et=="profile_view" else "leads"]=int(c.execute("SELECT count(*) FROM provider_marketing_events WHERE business_id=? AND event_type=?",(business_id,et)).fetchone()[0])
                        return self.sendj({"items":[dict(x) for x in rows],"stats":stats})
                    action=str(d.get("action","create"))
                    try:oid=int(d.get("id",0) or 0)
                    except (ValueError,TypeError):return self.sendj({"error":"Invalid offer."},400)
                    if action=="create":
                        title=str(d.get("title","")).strip()[:120];code=str(d.get("code","")).strip().upper()[:32];desc=str(d.get("description","")).strip()[:1200]
                        typ=str(d.get("discount_type","percent"));starts=str(d.get("starts_on","")).strip()[:20];ends=str(d.get("ends_on","")).strip()[:20]
                        try:value=float(d.get("discount_value",0));limit=int(d.get("usage_limit",0) or 0)
                        except (ValueError,TypeError):return self.sendj({"error":"Enter a valid offer value and use limit."},400)
                        if len(title)<2 or len(code)<3 or len(desc)<3 or not all(ch.isalnum() or ch in "-_" for ch in code) or typ not in ("percent","amount") or value<=0 or value>100000 or limit<0:return self.sendj({"error":"Check the title, code, description, discount and limit."},400)
                        if typ=="percent" and value>100:return self.sendj({"error":"Percentage discount cannot exceed 100%."},400)
                        if starts and ends and ends<starts:return self.sendj({"error":"Offer end date must be on or after the start date."},400)
                        try:
                            cur=c.execute("INSERT INTO provider_offers(business_id,user_id,title,code,description,discount_type,discount_value,starts_on,ends_on,usage_limit,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'draft',?,?) RETURNING id",(business_id,uid,title,code,desc,typ,value,starts,ends,limit,stamp,stamp))
                            return self.sendj({"ok":True,"id":cur.fetchone()["id"],"status":"draft"},201)
                        except DBIntegrityError:return self.sendj({"error":"That offer code already exists for this business."},409)
                    row=c.execute("SELECT * FROM provider_offers WHERE id=? AND business_id=?",(oid,business_id)).fetchone()
                    if not row:return self.sendj({"error":"Offer not found."},404)
                    if action in ("active","paused"):
                        c.execute("UPDATE provider_offers SET status=?,updated_at=? WHERE id=? AND business_id=?",(action,stamp,oid,business_id));return self.sendj({"ok":True,"status":action})
                    if action=="redeem":
                        if row["status"]!="active" or (int(row["usage_limit"] or 0)>0 and int(row["usage_count"])>=int(row["usage_limit"])):return self.sendj({"error":"This offer is inactive or its usage limit has been reached."},409)
                        c.execute("UPDATE provider_offers SET usage_count=usage_count+1,updated_at=? WHERE id=? AND business_id=?",(stamp,oid,business_id))
                        return self.sendj({"ok":True,"usage_count":int(row["usage_count"])+1,"message":"Redemption counted for tracking. No payment was processed."})
                if feature=="team":
                    if method=="GET":
                        members=c.execute("SELECT id,business_id,name,email,team_role,permissions,status,invite_code,created_at,updated_at FROM provider_team_members WHERE business_id=? ORDER BY created_at DESC LIMIT 200",(business_id,)).fetchall()
                        items=[]
                        base=os.environ.get("SKILLVAYA_PUBLIC_URL","https://skillvaya.onrender.com").rstrip("/")
                        for m in members:
                            x=dict(m);x["invite_url"]=base+"/customer-app?team_invite="+urllib.parse.quote(str(x["invite_code"]),safe="")
                            items.append(x)
                        jobs=c.execute("SELECT id,title,status FROM job_requests WHERE business_id=? AND status NOT IN ('completed','cancelled') ORDER BY created_at DESC LIMIT 200",(business_id,)).fetchall()
                        assigns=c.execute("""SELECT a.*,j.title job_title,t.name member_name FROM provider_job_assignments a
                            JOIN job_requests j ON j.id=a.job_id JOIN provider_team_members t ON t.id=a.team_member_id
                            WHERE a.business_id=? ORDER BY a.created_at DESC LIMIT 200""",(business_id,)).fetchall()
                        return self.sendj({"items":items,"jobs":[dict(x) for x in jobs],"assignments":[dict(x) for x in assigns]})
                    action=str(d.get("action","invite"))
                    if action=="accept_invite":
                        code=str(d.get("invite_code","")).strip()[:100]
                        row=c.execute("SELECT * FROM provider_team_members WHERE invite_code=? AND status='invited'",(code,)).fetchone()
                        if not row:return self.sendj({"error":"This invitation is invalid, expired or already accepted."},404)
                        if str(row["email"]).lower()!=str(u.get("email","")).lower():return self.sendj({"error":"Sign in with the email address that received this invitation."},403)
                        c.execute("UPDATE provider_team_members SET user_id=?,status='active',updated_at=? WHERE id=?",(uid,stamp,row["id"]))
                        return self.sendj({"ok":True,"business_id":int(row["business_id"]),"team_member_id":int(row["id"])})
                    if action=="invite":
                        name=str(d.get("name","")).strip()[:120];email=str(d.get("email","")).strip().lower()[:254];team_role=str(d.get("team_role","staff"))
                        if len(name)<2 or "@" not in email or team_role not in ("staff","manager"):return self.sendj({"error":"Enter a valid name, email address and team role."},400)
                        code=secrets.token_urlsafe(24)
                        try:
                            cur=c.execute("INSERT INTO provider_team_members(business_id,owner_user_id,name,email,team_role,permissions,status,invite_code,created_at,updated_at) VALUES(?,?,?,?,?,'[]','invited',?,?,?) RETURNING id",(business_id,uid,name,email,team_role,code,stamp,stamp))
                            mid=cur.fetchone()["id"]
                        except DBIntegrityError:return self.sendj({"error":"This email already belongs to a team record."},409)
                        base=os.environ.get("SKILLVAYA_PUBLIC_URL","https://skillvaya.onrender.com").rstrip("/")
                        invite_url=base+"/customer-app?team_invite="+urllib.parse.quote(code,safe="")
                        email_sent=False
                        email_error="Test mode: no email was sent. Copy this sandbox invitation link to test acceptance." if test_tier else "Email delivery is not configured; copy the private invitation link."
                        if not test_tier:
                            email_sent=send_owner_email("Skillvaya team invitation","You have been invited by "+str(u.get("name") or "a Skillvaya provider")+" to join their provider team. Sign in to Skillvaya with "+email+" and open this private invitation link:\n\n"+invite_url,email)
                            email_error="" if email_sent else "Email delivery is not configured; copy the private invitation link."
                        return self.sendj({"ok":True,"id":mid,"invite_url":invite_url,"email_sent":bool(email_sent),"email_error":email_error,"test_mode":bool(test_tier)},201)
                    if action=="get_invite_link":
                        try:mid=int(d.get("id",0))
                        except (TypeError,ValueError):return self.sendj({"error":"Invalid team invitation."},400)
                        row=c.execute("SELECT id,invite_code,email FROM provider_team_members WHERE id=? AND business_id=? AND status='invited'",(mid,business_id)).fetchone()
                        if not row:return self.sendj({"error":"Invitation not found."},404)
                        return self.sendj({"ok":True,"invite_url":os.environ.get("SKILLVAYA_PUBLIC_URL","https://skillvaya.onrender.com").rstrip("/")+"/customer-app?team_invite="+urllib.parse.quote(row["invite_code"],safe="")})
                    if action=="assign":
                        try:jid=int(d.get("job_id",0));mid=int(d.get("team_member_id",0))
                        except (TypeError,ValueError):return self.sendj({"error":"Choose a job and team member."},400)
                        job=c.execute("SELECT id FROM job_requests WHERE id=? AND business_id=?",(jid,business_id)).fetchone()
                        member=c.execute("SELECT id FROM provider_team_members WHERE id=? AND business_id=? AND status='active'",(mid,business_id)).fetchone()
                        if not job or not member:return self.sendj({"error":"Choose a job belonging to this business and an active team member."},400)
                        due=str(d.get("due_date","")).strip()[:20];note=str(d.get("note","")).strip()[:1000]
                        c.execute("INSERT INTO provider_job_assignments(business_id,owner_user_id,job_id,team_member_id,note,due_date,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'assigned',?,?) ON CONFLICT(job_id,team_member_id) DO UPDATE SET note=excluded.note,due_date=excluded.due_date,status='assigned',updated_at=excluded.updated_at",(business_id,uid,jid,mid,note,due,stamp,stamp))
                        return self.sendj({"ok":True})
                    if action=="assignment_status":
                        try:aid=int(d.get("id",0))
                        except (TypeError,ValueError):return self.sendj({"error":"Invalid assignment."},400)
                        status=str(d.get("status",""))
                        if status not in ("assigned","in_progress","completed","cancelled"):return self.sendj({"error":"Invalid assignment status."},400)
                        cur=c.execute("UPDATE provider_job_assignments SET status=?,updated_at=? WHERE id=? AND business_id=?",(status,stamp,aid,business_id))
                        if cur.rowcount!=1:return self.sendj({"error":"Assignment not found."},404)
                        return self.sendj({"ok":True})
                if feature=="marketing":
                    if method=="GET":
                        rows=c.execute("SELECT event_type,source,count(*) total FROM provider_marketing_events WHERE business_id=? GROUP BY event_type,source ORDER BY total DESC",(business_id,)).fetchall()
                        stats={}
                        mapping={"profile_view":"profile_views","campaign_view":"campaign_views","campaign_click":"campaign_clicks","package_click":"package_clicks","lead":"leads","offer_view":"offer_views"}
                        for key,out in mapping.items():stats[out]=int(c.execute("SELECT count(*) FROM provider_marketing_events WHERE business_id=? AND event_type=?",(business_id,key)).fetchone()[0])
                        stats["requests"]=int(c.execute("SELECT count(*) FROM job_requests WHERE business_id=?",(business_id,)).fetchone()[0])
                        sources=[]
                        for r in rows:
                            src=str(r["source"] or "directory");item=next((x for x in sources if x["source"]==src),None)
                            if not item:item={"source":src,"visits":0,"clicks":0,"leads":0};sources.append(item)
                            et=str(r["event_type"])
                            if et in ("profile_view","campaign_view"):item["visits"]+=int(r["total"])
                            elif et in ("campaign_click","package_click"):item["clicks"]+=int(r["total"])
                            elif et=="lead":item["leads"]+=int(r["total"])
                        camps=c.execute("SELECT * FROM provider_campaigns WHERE business_id=? ORDER BY created_at DESC LIMIT 100",(business_id,)).fetchall();campaigns=[]
                        for camp in camps:
                            x=dict(camp);x["views"]=int(c.execute("SELECT count(*) FROM provider_marketing_events WHERE campaign_id=? AND event_type='campaign_view'",(camp["id"],)).fetchone()[0]);x["clicks"]=int(c.execute("SELECT count(*) FROM provider_marketing_events WHERE campaign_id=? AND event_type='campaign_click'",(camp["id"],)).fetchone()[0]);x["leads"]=int(c.execute("SELECT count(*) FROM provider_marketing_events WHERE campaign_id=? AND event_type='lead'",(camp["id"],)).fetchone()[0]);campaigns.append(x)
                        return self.sendj({"stats":stats,"sources":sources,"campaigns":campaigns})
                    if str(d.get("action",""))!="track":return self.sendj({"error":"Unsupported marketing action."},400)
                    event=str(d.get("event_type",""));source=str(d.get("source","directory"))[:80];visitor=str(d.get("visitor_key",""))[:100];details=str(d.get("details",""))[:500]
                    if event not in ("profile_view","campaign_view","campaign_click","package_click","lead","offer_view"):return self.sendj({"error":"Unsupported tracking event."},400)
                    try:cid=int(d.get("campaign_id",0) or 0);customer=int(d.get("customer_id",0) or 0)
                    except (ValueError,TypeError):cid=customer=0
                    if cid and not c.execute("SELECT id FROM provider_campaigns WHERE id=? AND business_id=?",(cid,business_id)).fetchone():cid=0
                    c.execute("INSERT INTO provider_marketing_events(business_id,user_id,campaign_id,event_type,source,customer_id,visitor_key,details,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(business_id,uid,cid or None,event,source,customer or None,visitor,details,stamp))
                    return self.sendj({"ok":True},201)
                if feature=="announcements":
                    if method=="GET":
                        rows=c.execute("SELECT * FROM provider_announcements WHERE business_id=? ORDER BY created_at DESC LIMIT 100",(business_id,)).fetchall()
                        count=c.execute("SELECT count(DISTINCT ct.customer_id) FROM contacts ct JOIN customer_marketing_preferences mp ON mp.user_id=ct.customer_id WHERE ct.business_id=? AND mp.opted_in=1",(business_id,)).fetchone()[0]
                        return self.sendj({"items":[dict(x) for x in rows],"opted_in_customers":int(count)})
                    action=str(d.get("action","create"))
                    if action=="create":
                        title=str(d.get("title","")).strip()[:160];body=str(d.get("body","")).strip()[:2000]
                        if len(title)<2 or len(body)<10:return self.sendj({"error":"Enter a title and at least 10 characters for the message."},400)
                        cur=c.execute("INSERT INTO provider_announcements(business_id,user_id,title,body,status,created_at,updated_at) VALUES(?,?,?,?,'draft',?,?) RETURNING id",(business_id,uid,title,body,stamp,stamp))
                        return self.sendj({"ok":True,"id":cur.fetchone()["id"],"status":"draft"},201)
                    if action=="publish":
                        if test_tier:
                            return self.sendj({"error":"Publishing customer announcements is disabled in Subscription Test Lab. Drafts remain available for testing."},409)
                        try:aid=int(d.get("id",0))
                        except (ValueError,TypeError):return self.sendj({"error":"Invalid announcement."},400)
                        ann=c.execute("SELECT * FROM provider_announcements WHERE id=? AND business_id=? AND status='draft'",(aid,business_id)).fetchone()
                        if not ann:return self.sendj({"error":"Draft announcement not found."},404)
                        recipients=c.execute("SELECT DISTINCT ct.customer_id FROM contacts ct JOIN customer_marketing_preferences mp ON mp.user_id=ct.customer_id WHERE ct.business_id=? AND mp.opted_in=1",(business_id,)).fetchall()
                        sent=0
                        for recipient in recipients:
                            c.execute("INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)",(business_id,recipient["customer_id"],uid,"Service announcement: "+str(ann["title"])+"\n\n"+str(ann["body"]),stamp));sent+=1
                        c.execute("UPDATE provider_announcements SET status='published',recipient_count=?,published_at=?,updated_at=? WHERE id=? AND business_id=?",(sent,stamp,stamp,aid,business_id))
                        return self.sendj({"ok":True,"recipient_count":sent,"status":"published"})
                if feature=="automation":
                    defaults=[
                        ("quote_followup","Quotation follow-up reminders","Alert when a quote follow-up is due."),
                        ("booking_reminder","Upcoming booking reminders","Alert about bookings starting within the next 24 hours."),
                        ("invoice_overdue","Overdue invoice reminders","Alert about unpaid invoice balances past their due date.")]
                    for key,title,desc in defaults:
                        c.execute("INSERT INTO provider_automation_rules(business_id,user_id,rule_key,enabled,config_json,updated_at) VALUES(?,?,?,1,?,?) ON CONFLICT(business_id,rule_key) DO NOTHING",(business_id,uid,key,json.dumps({"title":title,"description":desc}),stamp))
                    action=str(d.get("action",""))
                    if method=="POST" and action=="toggle":
                        key=str(d.get("rule_key",""))
                        if key not in ("quote_followup","booking_reminder","invoice_overdue"):return self.sendj({"error":"Unknown automation rule."},400)
                        enabled=1 if d.get("enabled") else 0
                        c.execute("UPDATE provider_automation_rules SET enabled=?,updated_at=? WHERE business_id=? AND rule_key=?",(enabled,stamp,business_id,key))
                        return self.sendj({"ok":True,"enabled":bool(enabled)})
                    if method=="POST" and action=="evaluate":
                        rules={x["rule_key"]:bool(x["enabled"]) for x in c.execute("SELECT rule_key,enabled FROM provider_automation_rules WHERE business_id=?",(business_id,)).fetchall()}
                        candidates=[]
                        if rules.get("quote_followup"):
                            for r in c.execute("""SELECT f.id,f.remind_at,f.note,j.title,cu.name customer_name FROM provider_followups f JOIN job_requests j ON j.id=f.job_id JOIN users cu ON cu.id=f.customer_id WHERE f.business_id=? AND f.status='pending' AND f.remind_at<=? LIMIT 100""",(business_id,stamp)).fetchall():
                                candidates.append(("quote_followup","Quote follow-up due",str(r["customer_name"])+": "+str(r["title"])+". "+str(r["note"]), "followup:"+str(r["id"])))
                        if rules.get("booking_reminder"):
                            tomorrow=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=24)).isoformat()
                            for r in c.execute("SELECT id,title,customer_name,starts_at FROM provider_bookings WHERE business_id=? AND status='scheduled' AND starts_at>=? AND starts_at<=? LIMIT 100",(business_id,stamp,tomorrow)).fetchall():
                                candidates.append(("booking_reminder","Upcoming booking",str(r["title"])+" for "+str(r["customer_name"])+" starts "+str(r["starts_at"]), "booking:"+str(r["id"])))
                        if rules.get("invoice_overdue"):
                            today=datetime.date.today().isoformat()
                            for r in c.execute("SELECT id,invoice_number,customer_name,amount_cents,amount_paid_cents,due_date FROM provider_invoices WHERE business_id=? AND status NOT IN ('paid','cancelled') AND due_date<>'' AND due_date<? LIMIT 100",(business_id,today)).fetchall():
                                candidates.append(("invoice_overdue","Invoice overdue",str(r["invoice_number"])+" for "+str(r["customer_name"])+" has an outstanding balance.", "invoice:"+str(r["id"])))
                        for kind,title,body_text,ref in candidates:
                            exists=c.execute("SELECT id FROM provider_notifications WHERE business_id=? AND reference_key=? AND created_at>? LIMIT 1",(business_id,ref,(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=24)).isoformat())).fetchone()
                            if not exists:c.execute("INSERT INTO provider_notifications(business_id,user_id,kind,title,body,reference_key,status,created_at) VALUES(?,?,?,?,?,?, 'new',?)",(business_id,uid,kind,title,body_text,ref,stamp))
                    rules_rows=c.execute("SELECT rule_key,enabled,config_json FROM provider_automation_rules WHERE business_id=?",(business_id,)).fetchall()
                    rule_items=[]
                    for r in rules_rows:
                        try:cfg=json.loads(r["config_json"] or "{}")
                        except Exception:cfg={}
                        rule_items.append({"rule_key":r["rule_key"],"enabled":bool(r["enabled"]),"title":cfg.get("title",r["rule_key"]),"description":cfg.get("description","")})
                    alerts=c.execute("SELECT * FROM provider_notifications WHERE business_id=? ORDER BY created_at DESC LIMIT 100",(business_id,)).fetchall()
                    return self.sendj({"rules":rule_items,"alerts":[dict(x) for x in alerts]})
        except PermissionError as e:
            return self.sendj({"error":str(e)},401)
        except Exception as e:
            return self.sendj({"error":str(e)},400)
        return self.sendj({"error":"Unsupported growth tool action."},400)
    def handle_customer_marketing_preferences(self, method, data=None):
        try:
            u=self.require("customer")
            stamp=now()
            with conn() as c:
                if method=="GET":
                    row=c.execute("SELECT opted_in FROM customer_marketing_preferences WHERE user_id=?",(u["id"],)).fetchone()
                    return self.sendj({"opted_in":bool(row["opted_in"]) if row else False})
                if method=="POST":
                    opted=1 if (data or {}).get("opted_in") is True else 0
                    c.execute("INSERT INTO customer_marketing_preferences(user_id,opted_in,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET opted_in=excluded.opted_in,updated_at=excluded.updated_at",(u["id"],opted,stamp))
                    return self.sendj({"ok":True,"opted_in":bool(opted)})
        except PermissionError as e:return self.sendj({"error":str(e)},401)
        except Exception as e:return self.sendj({"error":str(e)},400)
        return self.sendj({"error":"Unsupported preference action."},400)
    def handle_my_team_assignments(self, method, data=None):
        try:
            u=self.require()
            if u.get("role") not in ("customer","provider","admin"):return self.sendj({"error":"Sign in to view team work."},403)
            with conn() as c:
                members=c.execute("SELECT * FROM provider_team_members WHERE user_id=? AND status='active' ORDER BY id DESC",(u["id"],)).fetchall()
                if not members:
                    if method=="GET":return self.sendj({"active":False,"items":[],"message":"No accepted team invitation was found for this account."})
                    return self.sendj({"error":"No accepted team assignment is linked to this account."},403)
                business_ids=[int(m["business_id"]) for m in members]
                if method=="GET":
                    items=[]
                    for m in members:
                        rows=c.execute("""SELECT a.id assignment_id,a.status assignment_status,a.note,a.due_date,
                            j.id job_id,j.title,j.description,j.area,j.status job_status,j.created_at,
                            b.name business_name,t.name member_name,t.team_role
                            FROM provider_job_assignments a JOIN job_requests j ON j.id=a.job_id
                            JOIN businesses b ON b.id=a.business_id JOIN provider_team_members t ON t.id=a.team_member_id
                            WHERE a.business_id=? AND a.team_member_id=? ORDER BY a.created_at DESC LIMIT 200""",(m["business_id"],m["id"])).fetchall()
                        for r in rows:items.append(dict(r))
                    return self.sendj({"active":True,"items":items,"business_ids":business_ids})
                d=data or {}
                try:aid=int(d.get("assignment_id",0))
                except (TypeError,ValueError):return self.sendj({"error":"Invalid assignment."},400)
                status=str(d.get("status",""))
                if status not in ("assigned","in_progress","completed"):return self.sendj({"error":"Invalid assignment status."},400)
                marks=",".join("?" for _ in members)
                ids=[int(m["id"]) for m in members]
                cur=c.execute("UPDATE provider_job_assignments SET status=?,updated_at=? WHERE id=? AND team_member_id IN ("+marks+")",(status,now(),aid,*ids))
                if cur.rowcount!=1:return self.sendj({"error":"This assignment is not assigned to your account."},403)
                return self.sendj({"ok":True,"status":status})
        except PermissionError as e:return self.sendj({"error":str(e)},401)
        except Exception as e:return self.sendj({"error":str(e)},400)

    def handle_public_marketing_track(self, data):
        try:
            d=data or {}
            try:bid=int(d.get("business_id",0));cid=int(d.get("campaign_id",0) or 0)
            except (TypeError,ValueError):return self.sendj({"error":"Invalid tracking reference."},400)
            event=str(d.get("event_type",""));source=str(d.get("source","directory"))[:80]
            if event not in ("profile_view","campaign_view","campaign_click","package_click","lead","offer_view"):return self.sendj({"error":"Invalid event type."},400)
            with conn() as c:
                biz=c.execute("SELECT id,user_id FROM businesses WHERE id=? AND status IN ('active','approved','published')",(bid,)).fetchone()
                if not biz:return self.sendj({"error":"Provider listing not found."},404)
                if cid and not c.execute("SELECT id FROM provider_campaigns WHERE id=? AND business_id=? AND status='active'",(cid,bid)).fetchone():cid=0
                viewer=self.user();customer=int(viewer["id"]) if viewer and viewer["role"]=="customer" else None
                visitor=str(d.get("visitor_key",""))[:100]
                c.execute("INSERT INTO provider_marketing_events(business_id,user_id,campaign_id,event_type,source,customer_id,visitor_key,details,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(bid,int(biz["user_id"]),cid or None,event,source,customer,visitor,"",now()))
            return self.sendj({"ok":True},201)
        except Exception:
            # Tracking is optional and must never break directory browsing or contact flow.
            return self.sendj({"ok":False,"tracking":"unavailable"})

    def do_HEAD(self):
        path=urlparse(self.path).path
        if path == "/account-deletion":
            page_path=os.path.join(ROOT,"account_deletion.html")
            if os.path.isfile(page_path):
                size=os.path.getsize(page_path); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(size)); self.send_header("Cache-Control","no-store"); self.end_headers(); return

        if path in ("/terms", "/privacy", "/refund", "/cancellation", "/delivery"):
            page_path=os.path.join(ROOT,"policies.html")
            if os.path.isfile(page_path):
                size=os.path.getsize(page_path); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(size)); self.send_header("Cache-Control","no-store"); self.end_headers(); return
            try:
                from policy_page import POLICY_PAGE_HTML
                size=len(POLICY_PAGE_HTML.encode("utf-8")); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(size)); self.send_header("Cache-Control","no-store"); self.end_headers(); return
            except Exception:
                self.send_response(503); self.end_headers(); return
        if path in ("/robots.txt", "/sitemap.xml"):
            body = seo_robots_body() if path == "/robots.txt" else seo_sitemap_body()
            content_type = "text/plain; charset=utf-8" if path == "/robots.txt" else "application/xml; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            return
        if path=="/healthz":
            b=json.dumps({"ok":True,"service":"skillvaya"}).encode()
            self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.end_headers(); return
        if path.startswith("/static/images/skillvaya-"):
            filename=os.path.basename(path)
            if filename not in {"skillvaya-app-home.png","skillvaya-app-screen-2.png","skillvaya-app-screen-3.png","skillvaya-provider-workspace.png","skillvaya-quotation-builder.png","skillvaya-mobile-chat-calls.png","skillvaya-download-page-ad.jpg"}:
                self.send_response(404); self.end_headers(); return
            image_path=os.path.join(ROOT,"static","images",filename)
            if not os.path.isfile(image_path): self.send_response(404); self.end_headers(); return
            self.send_response(200); self.send_header("Content-Type","image/png"); self.send_header("Content-Length",str(os.path.getsize(image_path))); self.send_header("Cache-Control","public, max-age=86400"); self.end_headers(); return
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
        if path == "/forgot-password":
            page = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Forgot Skillvaya password</title><style>body{font:16px system-ui;background:#f2f6fb;color:#142b4a;min-height:100vh;display:grid;place-items:center;margin:0;padding:18px}.card{background:white;width:min(100%,440px);padding:28px;border-radius:16px;box-shadow:0 10px 32px #10294b18}h1{font-size:24px}label{display:block;margin:16px 0 6px}input,button{box-sizing:border-box;width:100%;padding:13px;border-radius:9px;font:inherit}input{border:1px solid #c8d5e5}button{margin-top:16px;background:#102f5a;color:white;border:0;font-weight:700}a{color:#1b5d99}#status{min-height:24px}</style></head><body><main class="card"><h1>Reset your Skillvaya password</h1><p>Enter your registered email. If an account matches, a secure reset link will be sent.</p><form id="f"><label>Email address</label><input id="email" type="email" autocomplete="email" maxlength="254" required><button>Send reset link</button><p id="status" role="status"></p></form><a href="/">Back to sign in</a></main><script>document.getElementById('f').onsubmit=async e=>{e.preventDefault();let s=document.getElementById('status');try{let r=await fetch('/api/password-reset/request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value.trim()})});let d=await r.json();s.textContent=d.message||'If an account matches, a reset link will be sent shortly.'}catch(_){s.textContent='Could not connect. Please try again.'}};</script></body></html>"""
            data=page.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        if path == "/reset-password":
            page = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Choose a new password</title><style>body{font:16px system-ui;background:#f2f6fb;color:#142b4a;min-height:100vh;display:grid;place-items:center;margin:0;padding:18px}.card{background:white;width:min(100%,440px);padding:28px;border-radius:16px}label{display:block;margin:16px 0 6px}input,button{box-sizing:border-box;width:100%;padding:13px;border-radius:9px;font:inherit}input{border:1px solid #c8d5e5}button{margin-top:16px;background:#102f5a;color:white;border:0;font-weight:700}a{color:#1b5d99}#status{min-height:24px}</style></head><body><main class="card"><h1>Choose a new password</h1><p>Use at least 12 characters. The link expires after 30 minutes and works once.</p><form id="f"><label>New password</label><input id="pw" type="password" minlength="12" maxlength="256" autocomplete="new-password" required><label>Confirm password</label><input id="confirm" type="password" minlength="12" maxlength="256" autocomplete="new-password" required><button>Update password</button><p id="status" role="status"></p></form><a href="/">Back to sign in</a></main><script>document.getElementById('f').onsubmit=async e=>{e.preventDefault();let s=document.getElementById('status'),p=document.getElementById('pw').value,c=document.getElementById('confirm').value;if(p!==c){s.textContent='Passwords do not match.';return}let token=new URLSearchParams(location.search).get('token');if(!token){s.textContent='Invalid link. Request another.';return}try{let r=await fetch('/api/password-reset/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,password:p})}),d=await r.json();if(!r.ok)throw Error(d.error||'Could not reset password');s.textContent='Password updated. You can now sign in.';e.target.reset()}catch(x){s.textContent=x.message}};</script></body></html>"""
            data=page.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        if path == "/account-deletion":
            page_path=os.path.join(ROOT,"account_deletion.html")
            if not os.path.isfile(page_path): return self.sendj({"error":"Deletion information is unavailable."},404)
            with open(page_path,"rb") as f: page=f.read()
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(page))); self.end_headers(); self.wfile.write(page); return

        if path == "/robots.txt":
            body = seo_robots_body()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/sitemap.xml":
            body = seo_sitemap_body()
            self.send_response(200)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/api/provider/growth/"):
            return self.handle_provider_growth("GET",path,{})
        if path=="/api/customer/marketing-preferences":
            return self.handle_customer_marketing_preferences("GET",{})
        if path=="/api/team/my-assignments":
            return self.handle_my_team_assignments("GET",{})
        try:
            if path=="/payment/paypal-return":
                page="""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Confirm Skillvaya payment</title><style>body{font:16px system-ui;max-width:620px;margin:12vh auto;padding:24px;color:#14253b}button{padding:12px 18px;background:#087f80;color:#fff;border:0;border-radius:9px;font-weight:700}</style></head><body><h1>Confirming your payment</h1><p id="msg">Checking PayPal confirmation securely. Please keep this page open.</p><button id="back" hidden onclick="location.href='/customer'">Return to Skillvaya</button><script>(async()=>{const msg=document.getElementById('msg'),btn=document.getElementById('back'),order=new URLSearchParams(location.search).get('token'),auth=localStorage.getItem('skillvaya_token')||localStorage.getItem('sv_token');if(!order||!auth){msg.textContent='Return to Skillvaya and sign in with the same provider account used to start checkout, then check your plan status.';btn.hidden=false;return;}try{const r=await fetch('/api/paypal/capture',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+auth},body:JSON.stringify({order_id:order})}),d=await r.json();if(!r.ok)throw Error(d.error||'Payment confirmation could not be completed.');msg.textContent=d.already_verified?(d.profile_required?'Your payment was already confirmed. Return to Skillvaya and complete your provider profile to activate your listing.':'Your payment was already confirmed.'):(d.profile_required?'PayPal confirmed your payment. Return to Skillvaya, open Provider Studio, and complete your profile to activate your listing.':'PayPal confirmed your payment. Your Skillvaya plan is now active.');}catch(e){msg.textContent=e.message+' If PayPal charged you, do not pay again; sign in and contact Skillvaya support with the transaction details.';}btn.hidden=false;})();
function installUniversalEditControls(){
 const targets=Array.from(document.querySelectorAll('form')).filter(f=>!['login','signup','passwordForm'].includes(f.id)&&/save|update|profile|details|business|settings/i.test((f.querySelector('button[type=submit],button:not([type]),input[type=submit]')||{}).textContent||((f.querySelector('button[type=submit],button:not([type]),input[type=submit]')||{}).value||'')));
 const lockable=el=>el&&el.matches('input:not([type=hidden]):not([type=file]):not([type=password]):not([type=checkbox]):not([type=radio]),textarea,select');
 function attach(form){if(!form||form.dataset.editControlReady==='1')return;form.dataset.editControlReady='1';const fields=Array.from(form.elements).filter(lockable);if(!fields.length)return;
 const hasSaved=fields.some(f=>String(f.value||'').trim()!=='');if(!hasSaved)return;
 const bar=document.createElement('div');bar.className='universal-edit-toolbar';bar.style.cssText='display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0 12px';
 const edit=document.createElement('button');edit.type='button';edit.className='ghost';edit.textContent='✎ Edit details';
 const cancel=document.createElement('button');cancel.type='button';cancel.className='ghost';cancel.textContent='Cancel';cancel.hidden=true;
 const state=new Map(fields.map(f=>[f,{value:f.value,readOnly:!!f.readOnly,disabled:!!f.disabled}]));
 function setEditing(on){fields.forEach(f=>{if(f.tagName==='SELECT')f.disabled=!on;else f.readOnly=!on});edit.hidden=on;cancel.hidden=!on;if(on){fields[0]?.focus()}else{fields.forEach(f=>{const old=state.get(f);if(old){f.value=old.value;f.readOnly=old.readOnly;f.disabled=old.disabled}})}}
 edit.addEventListener('click',()=>setEditing(true));cancel.addEventListener('click',()=>setEditing(false));bar.append(edit,cancel);form.parentNode.insertBefore(bar,form);
 form.addEventListener('submit',()=>{fields.forEach(f=>{if(f.tagName==='SELECT')f.disabled=false;else f.readOnly=false});setTimeout(()=>{const box=form.parentElement;const good=box&&box.querySelector('.notice.good');if(good){fields.forEach(f=>{state.set(f,{value:f.value,readOnly:true,disabled:f.tagName==='SELECT'});if(f.tagName==='SELECT')f.disabled=true;else f.readOnly=true});edit.hidden=false;cancel.hidden=true}},700)});
 }
 targets.forEach(attach);
 // Owner/admin forms are rendered dynamically; attach edit affordances without affecting action-only forms.
 const admin=document.getElementById('adminTable');if(admin)admin.querySelectorAll('form').forEach(attach);
}
const _skillvayaEditObserver=new MutationObserver(()=>installUniversalEditControls());
function startUniversalEditControls(){installUniversalEditControls();if(document.body)_skillvayaEditObserver.observe(document.body,{childList:true,subtree:true});}
document.addEventListener('DOMContentLoaded',startUniversalEditControls);setTimeout(startUniversalEditControls,800);
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',svStartMessageLiveUpdates,{once:true});else svStartMessageLiveUpdates();
</script></body></html>"""
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
                        if cfg["mode"]=="live":
                            message="PayPal Live OAuth authentication succeeded. Live checkout is enabled; paid plans activate only after PayPal confirms a completed capture matching the order reference, currency and amount."
                        else:
                            message="PayPal Sandbox OAuth authentication succeeded. Sandbox is for testing only; its transactions are not real payments."
                    except Exception as e:
                        message=str(e)[:220]
                return self.sendj({"provider":"paypal","paypal_ready":configured,"oauth_valid":oauth_valid,"checkout_ready":configured and oauth_valid,"mode":cfg["mode"],"message":message})
            if path=="/downloads":
                body = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#071426"><title>Official Skillvaya Downloads</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f6fa;color:#122238;font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,Arial}a{color:inherit}.top{background:linear-gradient(130deg,#071426,#10384b);color:#fff;padding:28px 20px 58px}.wrap{width:min(100% - 32px,1000px);margin:auto}.brand{font-weight:850;font-size:24px;letter-spacing:-.7px}.brand span{color:#42d3c8}.eyebrow{color:#78e7df;text-transform:uppercase;font-size:12px;font-weight:800;letter-spacing:1.5px;margin-top:32px}h1{font-size:clamp(34px,6vw,54px);line-height:1.08;letter-spacing:-1.5px;max-width:700px;margin:10px 0 12px}.lead{color:#cfdae6;max-width:690px;margin:0}.sv-download-ad{margin:0 0 18px;border:1px solid #dbe5ee;border-radius:18px;overflow:hidden;background:#fff;box-shadow:0 12px 35px #18334a0b}.sv-download-ad img{display:block;width:100%;height:auto;max-height:520px;object-fit:contain}.main{margin:-28px auto 50px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.card{background:#fff;border:1px solid #dbe5ee;border-radius:20px;padding:26px;box-shadow:0 12px 35px #18334a0b}.icon{width:52px;height:52px;display:grid;place-items:center;border-radius:15px;background:#e0f8f5;color:#087f80;font-size:25px;font-weight:900}.card h2{margin:16px 0 6px;font-size:24px}.muted{color:#596b7e;font-size:14px}.button{display:flex;justify-content:center;text-decoration:none;background:#087f80;color:#fff;border-radius:12px;padding:13px 18px;font-weight:800;margin:20px 0 12px}.button:hover{background:#066a6b}.sub{font-size:12px;color:#607185}.section{background:#fff;border:1px solid #dbe5ee;border-radius:18px;padding:24px;margin-top:18px}.section h2{margin:0 0 10px}.notice{background:#fff8e7;border:1px solid #f0d69a;border-radius:13px;padding:16px;margin-top:12px}.notice strong{color:#68470a}.steps{padding-left:22px}.steps li{margin:7px 0}.checks{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.check{background:#f4f8fb;border-radius:10px;padding:12px;font-size:14px}footer{padding:24px 0 40px;color:#607185;font-size:13px}footer a{color:#087f80}.planlist{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:16px}.planlist article{border:1px solid #dbe5ee;border-radius:14px;padding:16px;background:#fbfdff}.planlist h3{margin:0 0 8px;color:#10233f;font-size:17px}.planlist ul{padding-left:19px;margin:0;font-size:14px;color:#596b7e}.planlist li{margin:6px 0}.policy-links{display:flex;flex-wrap:wrap;gap:12px}.policy-links a{font-weight:700}@media(max-width:650px){.grid,.checks,.planlist{grid-template-columns:1fr}.top{padding-bottom:48px}.card{padding:21px}.section{padding:19px}}


.sv-download-gallery{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:16px}.sv-download-gallery article{border:1px solid #dbe5ee;border-radius:14px;overflow:hidden;background:#fbfdff}.sv-download-gallery img{display:block;width:100%;height:auto;max-height:430px;object-fit:contain;background:#edf2f8}.sv-download-gallery h3{font-size:15px;margin:10px 12px 14px;color:#10233f}@media(max-width:650px){.sv-download-gallery{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style></head><body><header class="top"><div class="wrap"><a class="brand" href="/customer" style="text-decoration:none">skill<span>vaya</span></a><div class="eyebrow">Official app downloads</div><h1>Get Skillvaya on your device.</h1><p class="lead">Choose the installer for your device. Download only from this official Skillvaya website, and review the installation notes before opening a downloaded file.</p></div></header><main class="wrap main"><section class="sv-download-ad" aria-label="Skillvaya advertisement"><img src="/static/images/skillvaya-download-page-ad.jpg" alt="Skillvaya promotional advert" loading="eager"></section><div class="grid"><section class="card"><div class="icon" aria-hidden="true">A</div><h2>Android app</h2><p>For Android phones and tablets. The installer is an APK file downloaded directly from Skillvaya.</p><a class="button" href="/downloads/Skillvaya.apk" download>Download Android APK</a><p class="sub">File: Skillvaya.apk · Direct download from skillvaya.onrender.com</p><p class="muted">After downloading, open the file and follow Android's installation prompts. The exact prompts vary by Android version and browser.</p></section><section class="card"><div class="icon" aria-hidden="true">W</div><h2>Windows app</h2><p>For compatible Windows PCs. Download the Windows executable installer package from Skillvaya.</p><a class="button" href="/downloads/Skillvaya.exe" download>Download Windows EXE</a><p class="sub">File: Skillvaya.exe · Direct download from skillvaya.onrender.com</p><p class="muted">Save the file, then open it when the download finishes. Windows may show a reputation or publisher warning because this executable is not digitally signed.</p></section></div><section class="section"><h2>Skillvaya plans and included services</h2><p>Customers can browse and contact providers free. Paid provider plans are monthly, with an annual option priced at 11 months for 12 months.</p><div class="planlist"><article><h3>Local — R105/month</h3><ul><li>Business profile and category listing</li><li>Customer requests and quotations</li><li>Private messages, photo/video sharing and video calls</li></ul></article><article><h3>Priority — R210/month</h3><ul><li>Everything in Local</li><li>Higher category placement and priority badge</li><li>Reusable quotation templates</li></ul></article><article><h3>Business Plus — R500/month</h3><ul><li>Everything in Priority</li><li>Lead/job pipeline and booking calendar</li><li>Customer CRM, private notes and tags</li><li>Quote follow-up reminders</li><li>Invoice/payment-status tracking, review replies, service packages and real-activity insights</li></ul></article><article><h3>Business Spotlight — R1,000/month</h3><ul><li>Everything in Business Plus</li><li>Featured placement and public offers/vouchers</li><li>Team invitations and job assignments</li><li>Campaign planner, marketing analytics and lead-source tracking</li><li>Announcements to opted-in customers, automation rules and in-app alerts</li><li>Planned website-led growth-marketing add-ons; not yet available and subject to a separate confirmed offer</li></ul></article></div><p class="notice"><strong>Payments and renewals:</strong> Plans do not automatically renew. You must manually choose to renew and complete a new payment. Plans are bought in the Skillvaya Android app through Google Play, which shows the final price in your local currency (worth the same as the rand price) and handles taxes such as VAT.</p><p class="policy-links"><a href="/terms">Terms &amp; Conditions</a><a href="/privacy">Privacy Policy</a><a href="/refund">Refund Policy</a><a href="/cancellation">Cancellation Policy</a><a href="/delivery">Delivery Policy</a></p></section><section class="section" id="spotlight-growth"><h2>Business Spotlight: planned growth-marketing services</h2><p>We are planning an optional website-led promotion package for eligible Business Spotlight providers. It will be advertised here first and introduced in stages; it does not require adding new screens to the SkillVaya app.</p><div class="planlist"><article><h3>Promotional graphics</h3><p class="muted">Potential professionally prepared creative to help present a provider's business and services.</p></article><article><h3>Featured business story</h3><p class="muted">Potential website features introducing a provider and their approved portfolio.</p></article><article><h3>Local and category spotlight</h3><p class="muted">Potential clearly labelled sponsored visibility for a relevant service category.</p></article><article><h3>Campaign support</h3><p class="muted">Potential promotional planning and reporting as the offer develops.</p></article></div><div class="notice"><strong>Coming later — not currently for sale.</strong><br>These add-ons are planned, not live deliverables. We will publish the exact scope, price and availability before accepting payment. Paid promotion can improve visibility but cannot guarantee customers, enquiries or jobs.</div><p><a href="/">Back to the SkillVaya website</a> · <a href="/customer">Open SkillVaya</a></p></section><section class="section wf-showcase" id="workfinder-showcase"><span class="wf-kicker">Meet the new WorkFinder</span><h2>Find work. Show your skills. Build your future.</h2><p>Explore the WorkFinder experience before you install SkillVaya: worker profiles, professional portfolios and private WorkFinder conversations in a clean, mobile-first layout.</p><div class="wf-preview-grid"><article class="wf-preview"><div class="wf-screen"><div class="wf-screen-head"><span>WorkFinder <b>●</b></span><span class="wf-chip">JOBS</span></div><div class="wf-person"><div class="wf-avatar">AM</div><div><strong>Available opportunities</strong><small>Browse by role and location</small><div class="wf-mini-lines"></div><div class="wf-mini-lines short"></div></div></div><div class="wf-person"><div class="wf-avatar alt">JT</div><div><strong>Track your applications</strong><small>Keep your next steps organised</small></div></div></div><div class="wf-preview-body"><h3>Find opportunities</h3><p>Discover jobs, save listings and keep applications organised.</p></div></article><article class="wf-preview"><div class="wf-screen"><div class="wf-screen-head"><span>My profile <b>●</b></span><span class="wf-chip">PROFILE</span></div><div class="wf-person"><div class="wf-avatar gold">PRO</div><div><strong>Your professional profile</strong><small>Headline · skills · experience</small><div class="wf-mini-lines"></div></div></div><div class="wf-portfolio-tile"><span></span><span></span><span></span></div><div style="font-size:9px;color:#61748c;margin-top:8px">Portfolio · CV · supporting documents</div></div><div class="wf-preview-body"><h3>Showcase your work</h3><p>Build your profile and present your portfolio, CV and documents.</p></div></article><article class="wf-preview"><div class="wf-screen"><div class="wf-screen-head"><span>Messages <b>●</b></span><span class="wf-chip">PRIVATE</span></div><div class="wf-message">Hi, I would like to discuss the role.</div><div class="wf-message mine">Thanks — I can share my experience.</div><div class="wf-person"><div class="wf-avatar alt">WF</div><div><strong>WorkFinder messages</strong><small>Private conversations in one place</small></div></div></div><div class="wf-preview-body"><h3>Connect directly</h3><p>Keep WorkFinder conversations separate from service-provider enquiries.</p></div></article></div><div class="wf-showcase-actions"><a class="wf-primary" href="/workfinder">Explore WorkFinder →</a><a class="wf-secondary" href="/downloads/Skillvaya.apk" download>Download Android APK</a><a class="wf-secondary" href="/downloads/Skillvaya.exe" download>Download Windows EXE</a></div><p style="font-size:12px;margin-top:16px;color:#c5d8f0">Preview cards are illustrative UI designs, not screenshots of a live user account. Personal profile and portfolio content is supplied by each user.</p></section><section class="section"><h2>The latest Skillvaya app designs</h2><p>Preview the current mobile app and updated provider tools before you install.</p><div class="sv-download-gallery"><article><img src="/static/images/skillvaya-app-home.png" alt="Current Skillvaya mobile app screen" loading="lazy"><h3>Mobile app</h3></article><article><img src="/static/images/skillvaya-app-screen-2.png" alt="Skillvaya mobile app screen two" loading="lazy"><h3>App screens</h3></article><article><img src="/static/images/skillvaya-app-screen-3.png" alt="Skillvaya mobile app screen three" loading="lazy"><h3>App features</h3></article><article><img src="/static/images/skillvaya-provider-workspace.png" alt="Updated Skillvaya provider workspace" loading="lazy"><h3>Provider workspace</h3></article><article><img src="/static/images/skillvaya-quotation-builder.png" alt="Updated Skillvaya quotation builder" loading="lazy"><h3>Quotation builder</h3></article><article><img src="/static/images/skillvaya-mobile-chat-calls.png" alt="Skillvaya mobile chat and call controls" loading="lazy"><h3>Chat and calls</h3></article></div></section><section class="section"><h2>Why might Android show a safety warning?</h2><p>Android or your browser may display a message such as “This type of file can harm your device” when downloading an APK from a website. APK files are app installation packages, and installing one directly from a website is different from installing an app through Google Play. The warning is a general safety prompt; it does not by itself prove that a file is malicious, and it is not proof that a file is safe.</p><div class="notice"><strong>Stay in control of your security.</strong><br>Only download from the official Skillvaya domain shown in your browser. If the website address or filename looks different, cancel the download. Keep Android security protections enabled. Do not install a file you did not request or cannot verify.</div><ol class="steps"><li>Check that the address is <strong>https://skillvaya.onrender.com</strong>.</li><li>Use the Android APK button on this page.</li><li>Review the device's installer information before proceeding; cancel if anything looks unexpected.</li><li>For the most familiar app-store installation experience, use an official Google Play release if one becomes available.</li></ol></section><section class="section"><h2>Windows security and publisher prompts</h2><p>Windows may show Microsoft Defender SmartScreen or an unknown-publisher prompt for a downloaded EXE that has not been signed with a trusted code-signing certificate or does not yet have an established reputation. That prompt is not a malware verdict, but users should not ignore it automatically. Skillvaya's current Windows executable is not digitally signed, so Windows may display a warning.</p><p class="muted">We recommend keeping Windows security enabled. If you are unsure about a file, cancel and contact Skillvaya support rather than bypassing the warning.</p></section><section class="section"><h2>Before you install</h2><div class="checks"><div class="check">✓ Confirm you are on the official Skillvaya HTTPS website.</div><div class="check">✓ Choose Android APK for Android or EXE for Windows.</div><div class="check">✓ Keep your device's security protections enabled.</div><div class="check">✓ Contact support if a download fails or looks unexpected.</div></div><p style="margin:18px 0 0">Need help? Email <a href="mailto:skillvaya@gmail.com">skillvaya@gmail.com</a>. <a href="/customer">Return to Skillvaya</a>.</p></section></main><footer><div class="wrap">© 2026 Skillvaya. Download only from the official website. Installation prompts and device compatibility may vary.</div></footer></body></html>""".encode("utf-8")
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-cache"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
            if path=="/healthz":
                return self.sendj({"ok":True,"service":"skillvaya"})
            if path.startswith("/static/images/skillvaya-"):
                filename=os.path.basename(path)
                if filename not in {"skillvaya-app-home.png","skillvaya-app-screen-2.png","skillvaya-app-screen-3.png","skillvaya-provider-workspace.png","skillvaya-quotation-builder.png","skillvaya-mobile-chat-calls.png"}:
                    self.send_response(404); self.end_headers(); return
                image_path=os.path.join(ROOT,"static","images",filename)
                if not os.path.isfile(image_path): self.send_response(404); self.end_headers(); return
                with open(image_path,"rb") as f: b=f.read()
                self.send_response(200); self.send_header("Content-Type","image/jpeg" if filename.lower().endswith((".jpg",".jpeg")) else "image/png"); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","public, max-age=86400"); self.end_headers(); self.wfile.write(b); return
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
                self.send_response(200); self.send_header("Content-Type","image/jpeg"); self.send_header("Cache-Control","public, max-age=86400"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
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
                b=svg.encode("utf-8"); self.send_response(200); self.send_header("Content-Type","image/svg+xml; charset=utf-8"); self.send_header("Cache-Control","public, max-age=86400"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            if path.startswith("/p/"):
                # SV79: share link for a provider profile, with a preview card for chat apps; opens the profile in the app.
                import html as _h
                try: bid=int(path[3:].strip("/"))
                except ValueError: bid=0
                row=None
                if bid:
                    with conn() as c: row=c.execute("SELECT id,name,category,area,description FROM businesses WHERE id=? AND LOWER(TRIM(COALESCE(status,''))) IN ('active','approved','published')",(bid,)).fetchone()
                target="/customer-app"+("?provider=%d"%bid if row else "")
                title=(str(row["name"])+" - "+str(row["category"])+" on Skillvaya") if row else "Skillvaya"
                desc=(str(row["area"] or "")+" | "+str(row["description"] or "")[:180]) if row else "Find trusted local service providers on Skillvaya."
                base=os.environ.get("SKILLVAYA_PUBLIC_URL","https://skillvaya.onrender.com").strip().rstrip("/")
                page=('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                      '<title>%s</title><meta property="og:title" content="%s"><meta property="og:description" content="%s"><meta property="og:type" content="website">'
                      '<meta property="og:image" content="%s/icon-512.png"><meta name="description" content="%s"><meta http-equiv="refresh" content="0;url=%s"></head>'
                      '<body style="font:16px system-ui;padding:24px"><p>Opening <a href="%s">%s</a>...</p><script>location.replace(%s)</script></body></html>') % (
                      _h.escape(title),_h.escape(title),_h.escape(desc),_h.escape(base),_h.escape(desc),_h.escape(target),_h.escape(target),_h.escape(title),json.dumps(target))
                b=page.encode("utf-8"); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","public, max-age=300"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            if path=="/sw.js":
                # SV76-PERF-03: network first, but a saved copy of the app opens after 2.5 s so a sleeping server never blanks the app.
                worker=("const CACHE='skillvaya-shell-v4-fast';"
                "const ASSETS=['/manifest.json','/icon.svg','/icon-192.png','/icon-512.png','/sv-logo.jpeg'];"
                "const HTML_ROUTES=['/','/index.html','/login','/customer','/customer-app','/website','/terms','/workfinder'];"
                "self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())));"
                "self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));"
                "self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==location.origin||u.pathname.startsWith('/api/'))return;"
                "if(HTML_ROUTES.includes(u.pathname)){e.respondWith((async()=>{const cache=await caches.open(CACHE),key=u.pathname;const offline=()=>new Response('<!doctype html><meta name=viewport content=width=device-width,initial-scale=1><title>Skillvaya offline</title><main style=font:16px system-ui;margin:15vh auto;max-width:32rem;padding:1rem><h1>Skillvaya</h1><p>Connect to the internet to sign in and open your workspace.</p></main>',{headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}});"
                "const net=fetch(e.request,{cache:'no-cache'}).then(r=>{if(r&&r.ok&&r.status===200)cache.put(key,r.clone());return r});const cached=await cache.match(key);if(!cached)return net.catch(offline);try{e.waitUntil(net.catch(()=>{}))}catch(_){}"
                "return Promise.race([net.then(r=>r&&r.ok?r:cached),new Promise(res=>setTimeout(()=>res(cached),2500))]).catch(()=>cached);})());return;}"
                "e.respondWith(fetch(e.request).then(r=>{if(r&&r.ok&&ASSETS.includes(u.pathname)){const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy));}return r;}).catch(()=>caches.match(e.request)));});"
                # SV78-WEBPUSH-01: show pushed alerts and open the app when one is tapped.
                "self.addEventListener('push',e=>{let d={};try{d=e.data?e.data.json():{}}catch(_){d={body:e.data?e.data.text():''}}const call=d.type==='incoming_call';"
                "const tag=call?'sv-call-'+(d.call_id||''):(d.type==='missed_call'?'sv-missed':'sv-msg-'+(d.business_id||'')+'-'+(d.customer_id||''));"
                "e.waitUntil(self.registration.showNotification(d.title||'Skillvaya',{body:d.body||'',icon:'/icon-192.png',badge:'/icon-192.png',tag:tag,renotify:true,requireInteraction:call,vibrate:call?[400,200,400,200,400]:[200],data:{url:'/customer-app'}}));});"
                "self.addEventListener('notificationclick',e=>{e.notification.close();const url=(e.notification.data&&e.notification.data.url)||'/customer-app';"
                "e.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(list=>{for(const c of list){if(new URL(c.url).origin===location.origin&&'focus' in c){try{c.postMessage({type:'sv-push-open'})}catch(_){}return c.focus();}}return self.clients.openWindow(url);}));});").encode("utf-8")
                self.send_response(200); self.send_header("Content-Type","application/javascript; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Service-Worker-Allowed","/"); self.send_header("Content-Length",str(len(worker))); self.end_headers(); self.wfile.write(worker); return
            if path=="/owner-app":
                owner_app_html = OWNER_APP_HTML.encode()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-cache"); self.send_header("Content-Length",str(len(owner_app_html))); self.end_headers(); self.wfile.write(owner_app_html); return
            if path in ("/terms","/privacy","/refund","/cancellation","/delivery"):
                try:
                    with open(os.path.join(ROOT,"policies.html"),"rb") as f: b=f.read()
                except OSError:
                    try:
                        from policy_page import POLICY_PAGE_HTML
                        b=POLICY_PAGE_HTML.encode("utf-8")
                    except Exception:
                        return self.sendj({"error":"Policy pages are temporarily unavailable"},503)
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            if path=="/website":
                with open(os.path.join(ROOT,"website.html"),"rb") as f: customer_html = f.read()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-cache"); self.send_header("Content-Length",str(len(customer_html))); self.end_headers(); self.wfile.write(customer_html); return
            if path == "/workfinder":
                try:
                    with open(os.path.join(ROOT, "static", "workfinder.html"), "rb") as f:
                        workfinder_html = f.read()
                except OSError:
                    return self.sendj({"error": "WorkFinder is temporarily unavailable."}, 503)
                wf_etag = '"' + hashlib.sha1(workfinder_html).hexdigest()[:24] + '"'
                if self.headers.get("If-None-Match", "").replace("W/", "").strip() == wf_etag:
                    self.send_response(304); self.send_header("ETag", wf_etag); self.send_header("Cache-Control", "no-cache"); self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("ETag", wf_etag)
                self.send_header("Content-Length", str(len(workfinder_html)))
                self.end_headers()
                self.wfile.write(workfinder_html)
                return
            # WF_STANDALONE_MESSAGING_V1: private WorkFinder user-to-user conversations, separate from provider enquiries.
            if path in ("/api/workfinder/conversations", "/api/workfinder/messages"):
                u=self.require()
                if u.get("role") not in ("customer","provider"):
                    return self.sendj({"error":"Use a customer or provider account to message in WorkFinder."},403)
                with conn() as c:
                    c.execute(f"""CREATE TABLE IF NOT EXISTS workfinder_conversations (
                        id {WF_ID_TYPE} PRIMARY KEY, user_a_id BIGINT NOT NULL, user_b_id BIGINT NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        UNIQUE(user_a_id,user_b_id))""")
                    c.execute(f"""CREATE TABLE IF NOT EXISTS workfinder_messages (
                        id {WF_ID_TYPE} PRIMARY KEY, conversation_id BIGINT NOT NULL,
                        sender_id BIGINT NOT NULL, recipient_id BIGINT NOT NULL,
                        message TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT)""")
                    if path.endswith("/conversations"):
                        rows=c.execute("""SELECT wc.id,wc.updated_at,
                            CASE WHEN wc.user_a_id=? THEN ub.id ELSE ua.id END AS partner_id,
                            CASE WHEN wc.user_a_id=? THEN ub.name ELSE ua.name END AS partner_name,
                            CASE WHEN wc.user_a_id=? THEN ub.email ELSE ua.email END AS partner_email,
                            (SELECT wm.message FROM workfinder_messages wm WHERE wm.conversation_id=wc.id ORDER BY wm.id DESC LIMIT 1) AS last_message,
                            (SELECT wm.sender_id FROM workfinder_messages wm WHERE wm.conversation_id=wc.id ORDER BY wm.id DESC LIMIT 1) AS last_sender_id,
                            (SELECT COUNT(*) FROM workfinder_messages wm WHERE wm.conversation_id=wc.id AND wm.recipient_id=? AND wm.read_at IS NULL) AS unread
                            FROM workfinder_conversations wc
                            JOIN users ua ON ua.id=wc.user_a_id JOIN users ub ON ub.id=wc.user_b_id
                            WHERE wc.user_a_id=? OR wc.user_b_id=? ORDER BY wc.updated_at DESC LIMIT 200""",
                            (u["id"],u["id"],u["id"],u["id"],u["id"],u["id"])).fetchall()
                        return self.sendj({"items":[dict(r) for r in rows]})
                    query=urllib.parse.parse_qs(urlparse(self.path).query)
                    try: cid=int((query.get("conversation_id") or ["0"])[0])
                    except (ValueError,TypeError): cid=0
                    convo=c.execute("SELECT * FROM workfinder_conversations WHERE id=? AND (user_a_id=? OR user_b_id=?)",(cid,u["id"],u["id"])).fetchone()
                    if not convo:return self.sendj({"error":"Conversation not found."},404)
                    c.execute("UPDATE workfinder_messages SET read_at=? WHERE conversation_id=? AND recipient_id=? AND read_at IS NULL",(now(),cid,u["id"]))
                    c.execute(f"""CREATE TABLE IF NOT EXISTS workfinder_message_attachments (id {WF_ID_TYPE} PRIMARY KEY, message_id BIGINT NOT NULL UNIQUE, filename TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes BIGINT NOT NULL, data_base64 TEXT NOT NULL)""")
                    rows=c.execute("SELECT id,conversation_id,sender_id,recipient_id,message,created_at,read_at FROM workfinder_messages WHERE conversation_id=? ORDER BY id ASC LIMIT 1000",(cid,)).fetchall()
                    out=[]
                    for row in rows:
                        item=dict(row)
                        att=c.execute("SELECT filename,mime_type,size_bytes,data_base64 FROM workfinder_message_attachments WHERE message_id=?",(row["id"],)).fetchone()
                        if att:item["attachment"]={"filename":att["filename"],"mime_type":att["mime_type"],"size_bytes":att["size_bytes"],"url":"data:"+att["mime_type"]+";base64,"+att["data_base64"]}
                        out.append(item)
                    return self.sendj({"items":out})
                    return self.sendj({"items":[dict(r) for r in rows],"conversation_id":cid})
            if path.startswith("/api/workfinder/"):
                u=self.require(); kind=path.rsplit("/",1)[-1]
                if kind not in ("profile","saved","searches","workwanted","reports","blocked","messages","jobs","applications"): return self.sendj({"error":"Unknown WorkFinder resource."},404)
                with conn() as c:
                    c.execute("""CREATE TABLE IF NOT EXISTS workfinder_records (
                        user_id INTEGER NOT NULL, kind TEXT NOT NULL,
                        record_key TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL, UNIQUE(user_id,kind,record_key))""")
                    rows=c.execute("SELECT record_key,payload FROM workfinder_records WHERE user_id=? AND kind=? ORDER BY updated_at DESC LIMIT 500",(u["id"],kind)).fetchall()
                return self.sendj({"items":[{"key":r["record_key"],**json.loads(r["payload"])} for r in rows if not (kind=="saved" and json.loads(r["payload"]).get("removed"))]})
            if path in ("/customer","/customer-app"):
                # Customer browsing is public; account creation and sign-in live in Profile.
                customer_page = HTML
                if path == "/customer":
                    customer_page = customer_page.replace(
                        "<title>Skillvaya</title>",
                        '<title>Find Trusted Service Providers Near You | Skillvaya</title>'
                        '<meta name="description" content="Find tradespeople, professionals and local businesses near you with Skillvaya, wherever you live. Browse service providers and contact them free, without downloading an app.">'
                        '<link rel="canonical" href="https://skillvaya.onrender.com/customer">'
                    )
                customer_html = customer_page.encode("utf-8")
                # SV76-PERF-03: validators let the phone reuse its saved copy (304, no body) when nothing changed.
                etag='"'+hashlib.sha1(customer_html).hexdigest()[:24]+'"'
                if self.headers.get("If-None-Match","").replace("W/","").strip()==etag:
                    self.send_response(304); self.send_header("ETag",etag); self.send_header("Cache-Control","no-cache"); self.end_headers(); return
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-cache"); self.send_header("ETag",etag); self.send_header("Content-Length",str(len(customer_html))); self.end_headers(); self.wfile.write(customer_html); return
            if path=="/owner-control":
                try:
                    self.require("admin")
                except PermissionError:
                    self.send_response(302); self.send_header("Location","/owner-app"); self.send_header("Cache-Control","no-store"); self.end_headers(); return
                owner_html = OWNER_HTML.encode()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(owner_html))); self.end_headers(); self.wfile.write(owner_html); return
            if path in ("/", "/index.html") and "SkillvayaNative" in self.headers.get("User-Agent", ""):
                # Older installed Android builds open the configured base URL (/) directly.
                # Keep the public website unchanged for browsers, but route the native WebView
                # into the real customer app so existing installations recover without reinstalling.
                self.send_response(302); self.send_header("Location", "/customer-app"); self.send_header("Cache-Control", "no-store"); self.end_headers(); return
            if path in ("/", "/index.html"):
                # Public root is the informational/download website; do not expose the working app shell here.
                with open(os.path.join(ROOT, "website.html"), "rb") as f: public_site = f.read()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-cache"); self.send_header("Content-Length", str(len(public_site))); self.end_headers(); self.wfile.write(public_site); return
            if path == "/login":
                # Installed app entry remains separate so existing app sessions continue to work.
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
                    message="PayPal Sandbox credentials are authenticated for testing only. Sandbox transactions are not real payments and must not be used to activate real paid plans."
                elif oauth_valid:
                    message="PayPal Live credentials authenticated successfully. Live checkout is configured; paid plans activate only after PayPal confirms a completed capture matching the order reference, currency and amount."
                else:
                    message=auth_message or ("Add the PayPal client ID and secret in Render." if not credentials else "Configure SKILLVAYA_PUBLIC_URL as a public HTTPS URL.")
                return self.sendj({"provider":"paypal","mode":cfg["mode"],"credentials_configured":credentials,"public_https_configured":public_https,"oauth_valid":oauth_valid,"checkout_ready":bool(credentials and public_https and oauth_valid),"refund_api_ready":bool(credentials and oauth_valid),"message":message})
            if path=="/api/admin/payfast/status":
                return self.sendj({"error":"PayFast is paused. PayPal is the only supported checkout provider."},410)
            if path=="/api/owner-promotions":
                with conn() as c:
                    rows=c.execute("SELECT id,kind,business_name,title,category,description,target_url,image_url,status,owner_free,created_at FROM owner_promotions WHERE status='active' ORDER BY created_at DESC").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/jobs":
                u=self.require()
                with conn() as c:
                    if u["role"]=="customer":
                        rows=c.execute("SELECT j.*,b.name business_name,b.category,b.area business_area,b.user_id provider_id,b.country business_country FROM job_requests j JOIN businesses b ON b.id=j.business_id WHERE j.customer_id=? ORDER BY j.updated_at DESC,j.id DESC LIMIT 200",(u["id"],)).fetchall()
                    elif u["role"]=="provider":
                        rows=c.execute("SELECT j.*,b.name business_name,b.category,b.area business_area,b.user_id provider_id,b.country business_country FROM job_requests j JOIN businesses b ON b.id=j.business_id WHERE b.user_id=? OR j.customer_id=? ORDER BY j.updated_at DESC,j.id DESC LIMIT 200",(u["id"],u["id"])).fetchall()
                    else:
                        rows=c.execute("SELECT j.*,b.name business_name,b.category,b.area business_area,b.user_id provider_id,b.country business_country FROM job_requests j JOIN businesses b ON b.id=j.business_id ORDER BY j.updated_at DESC,j.id DESC LIMIT 200").fetchall()
                    items=[]
                    for row in rows:
                        item=dict(row)
                        quotes=c.execute("SELECT q.*,u.name provider_name FROM job_quotes q JOIN users u ON u.id=q.provider_id WHERE q.job_id=? ORDER BY q.created_at",(row["id"],)).fetchall()
                        item["quotes"]=[dict(q) for q in quotes]
                        items.append(item)
                return self.sendj({"items":items,"role":u["role"]})
            if path=="/api/contacts":
                u=self.require()
                with conn() as c:
                    if u["role"]=="admin":
                        own=c.execute("SELECT id FROM businesses WHERE user_id=? AND name='Skillvaya Digital & Creative Studio' AND status='active' ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                        if own: c.execute("INSERT INTO contacts(business_id,customer_id,created_at) VALUES(?,?,?) ON CONFLICT(business_id,customer_id) DO NOTHING",(own["id"],u["id"],now()))
                        rows=c.execute("SELECT ct.*,b.name business_name,b.phone business_phone,b.user_id business_owner_id,cu.name customer_name,cu.phone customer_phone FROM contacts ct JOIN businesses b ON b.id=ct.business_id JOIN users cu ON cu.id=ct.customer_id WHERE ct.customer_id=? ORDER BY ct.created_at DESC LIMIT 500",(u["id"],)).fetchall()
                    elif u["role"]=="provider":
                        rows=c.execute("SELECT ct.*,b.name business_name,b.phone business_phone,b.user_id business_owner_id,cu.name customer_name,cu.phone customer_phone FROM contacts ct JOIN businesses b ON b.id=ct.business_id JOIN users cu ON cu.id=ct.customer_id WHERE b.user_id=? OR ct.customer_id=? ORDER BY ct.created_at DESC LIMIT 500",(u["id"],u["id"])).fetchall()
                    else:
                        rows=c.execute("SELECT ct.*,b.name business_name,b.phone business_phone,b.user_id business_owner_id,cu.name customer_name,cu.phone customer_phone FROM contacts ct JOIN businesses b ON b.id=ct.business_id JOIN users cu ON cu.id=ct.customer_id WHERE ct.customer_id=? ORDER BY ct.created_at DESC LIMIT 500",(u["id"],)).fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/webpush/key":
                _v,pub=webpush_keys()
                return self.sendj({"publicKey":pub,"enabled":bool(pub)})
            if path=="/api/ice-servers":
                u=self.require()
                return self.sendj({"iceServers":build_ice_servers(u)})
            if path=="/api/messages/pulse":
                u=self.require()
                agg="MAX(m.id) AS latest, SUM(CASE WHEN m.sender_id<>? AND m.read_at IS NULL THEN 1 ELSE 0 END) AS unread FROM messages m"
                with conn() as c:
                    if u["role"]=="admin":
                        row=c.execute("SELECT "+agg,(u["id"],)).fetchone()
                    elif u["role"]=="provider":
                        row=c.execute("SELECT "+agg+" JOIN businesses b ON b.id=m.business_id WHERE b.user_id=? OR m.sender_id=?",(u["id"],u["id"],u["id"])).fetchone()
                    else:
                        row=c.execute("SELECT "+agg+" WHERE m.customer_id=?",(u["id"],u["id"])).fetchone()
                return self.sendj({"latest_id":int((row["latest"] if row else 0) or 0),"unread":int((row["unread"] if row else 0) or 0)})
            if path=="/api/messages":
                u=self.require()
                with conn() as c:
                    if u["role"]=="admin":
                        rows=c.execute("SELECT m.*,b.name business_name,b.phone business_phone,b.user_id business_owner_id,cu.name customer_name,cu.phone customer_phone,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id ORDER BY m.created_at DESC LIMIT 300").fetchall()
                    elif u["role"]=="provider":
                        rows=c.execute("SELECT m.*,b.name business_name,b.phone business_phone,b.user_id business_owner_id,cu.name customer_name,cu.phone customer_phone,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id WHERE b.user_id=? OR m.sender_id=? ORDER BY m.created_at DESC LIMIT 300",(u["id"],u["id"])).fetchall()
                    else:
                        rows=c.execute("SELECT m.*,b.name business_name,b.phone business_phone,b.user_id business_owner_id,cu.name customer_name,cu.phone customer_phone,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id WHERE m.customer_id=? ORDER BY m.created_at DESC LIMIT 300",(u["id"],)).fetchall()
                items=[dict(x) for x in rows]
                if items:
                    ids=[int(x["id"]) for x in items]
                    placeholders=",".join("?" for _ in ids)
                    with conn() as c:
                        att_rows=c.execute("SELECT id,message_id,filename,mime_type,size_bytes,created_at FROM message_attachments WHERE message_id IN ("+placeholders+") ORDER BY id",tuple(ids)).fetchall()
                    grouped={}
                    for a in att_rows: grouped.setdefault(int(a["message_id"]),[]).append(dict(a))
                    for item in items: item["attachments"]=grouped.get(int(item["id"]),[])
                return self.sendj({"items":items})
            if path.startswith("/api/messages/attachments/"):
                u=self.require()
                try: attachment_id=int(path.rsplit("/",1)[1])
                except (ValueError,IndexError): return self.sendj({"error":"Invalid attachment ID."},400)
                with conn() as c:
                    a=c.execute("SELECT a.*,b.user_id AS provider_owner_id FROM message_attachments a JOIN businesses b ON b.id=a.business_id WHERE a.id=?",(attachment_id,)).fetchone()
                if not a: return self.sendj({"error":"Attachment not found."},404)
                allowed=(u["role"]=="admin" or (u["role"] in ("customer","provider") and int(u["id"])==int(a["customer_id"])) or (u["role"]=="provider" and int(u["id"])==int(a["provider_owner_id"])))
                if not allowed: return self.sendj({"error":"You cannot access this conversation attachment."},403)
                try: payload=base64.b64decode(a["data_base64"],validate=True)
                except Exception: return self.sendj({"error":"Attachment data could not be read."},500)
                filename=str(a["filename"] or "shared-media")
                fallback="".join(ch if ord(ch)<128 and (ch.isalnum() or ch in "._-") else "_" for ch in filename)[:120] or "shared-media"
                encoded=urllib.parse.quote(filename,safe="")
                self.send_response(200)
                self.send_header("Content-Type",str(a["mime_type"]))
                self.send_header("Content-Disposition",'inline; filename="'+fallback+'"')
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Cache-Control","private, no-store")
                self.send_header("Content-Length",str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if path=="/api/video-calls":
                u=self.require()
                cutoff=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=5)).isoformat()
                stamp=now()
                with conn() as c:
                    if _sweep_due("video_calls_missed",15):
                        swept=c.execute("UPDATE video_calls SET status='missed',updated_at=?,ended_at=? WHERE status='ringing' AND created_at<? RETURNING id,business_id,customer_id,caller_id,callee_id,offer_sdp",(stamp,stamp,cutoff)).fetchall()
                        for row in swept: sv_missed_call_notice(c,dict(row))
                    base_query="""SELECT vc.id,vc.business_id,vc.customer_id,vc.caller_id,vc.callee_id,vc.status,CASE WHEN vc.offer_sdp LIKE '%%m=video%%' THEN 'video' ELSE 'voice' END AS media_type,vc.created_at,vc.updated_at,
                        b.name business_name,cu.name customer_name,caller.name caller_name,callee.name callee_name
                        FROM video_calls vc JOIN businesses b ON b.id=vc.business_id
                        JOIN users cu ON cu.id=vc.customer_id JOIN users caller ON caller.id=vc.caller_id
                        JOIN users callee ON callee.id=vc.callee_id """
                    if u["role"]=="provider":
                        # Include calls where this provider is a direct caller/callee as well
                        # as calls on their own listing. Provider accounts can message other
                        # providers as customer-side participants in the existing chat model.
                        rows=c.execute(base_query+"WHERE (b.user_id=? OR vc.caller_id=? OR vc.callee_id=?) AND vc.status IN ('ringing','accepted') ORDER BY vc.created_at DESC LIMIT 30",(u["id"],u["id"],u["id"])).fetchall()
                    elif u["role"]=="customer":
                        rows=c.execute(base_query+"WHERE (vc.callee_id=? OR vc.customer_id=?) AND vc.status IN ('ringing','accepted') ORDER BY vc.created_at DESC LIMIT 30",(u["id"],u["id"])).fetchall()
                    else:
                        rows=c.execute(base_query+"WHERE vc.status IN ('ringing','accepted') ORDER BY vc.created_at DESC LIMIT 30").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path.startswith("/api/video-calls/"):
                u=self.require()
                call_id=path.rsplit("/",1)[1]
                query=urllib.parse.parse_qs(urlparse(self.path).query)
                try: after=max(0,int(query.get("after",["0"])[0]))
                except (TypeError,ValueError): after=0
                with conn() as c:
                    call_rows,signals=db_batch(c,[("SELECT vc.*,b.user_id AS provider_owner_id,b.name business_name,cu.name customer_name,caller.name caller_name,callee.name callee_name FROM video_calls vc JOIN businesses b ON b.id=vc.business_id JOIN users cu ON cu.id=vc.customer_id JOIN users caller ON caller.id=vc.caller_id JOIN users callee ON callee.id=vc.callee_id WHERE vc.id=?",(call_id,)),("SELECT id,sender_id,kind,payload,created_at FROM video_call_signals WHERE call_id=? AND id>? ORDER BY id ASC LIMIT 300",(call_id,after))])
                    call=call_rows[0] if call_rows else None
                    if not call: return self.sendj({"error":"Video call not found."},404)
                    allowed=(u["role"]=="admin" or int(u["id"]) in (int(call["caller_id"]),int(call["callee_id"])) or (u["role"]=="provider" and int(u["id"])==int(call["provider_owner_id"])))
                    if not allowed: return self.sendj({"error":"You cannot access this video call."},403)
                result=dict(call);result["signals"]=[dict(x) for x in signals]
                return self.sendj({"call":result})
            if path in ("/api/provider/quote-templates","/api/provider/campaigns"):
                u=self.require()
                if u["role"] not in ("provider","admin"): return self.sendj({"error":"Only service providers can use this workspace tool."},403)
                template_path=path.endswith("quote-templates")
                need_rank=1 if template_path else 3
                ranks=PROVIDER_TIER_RANKS
                url_query=urllib.parse.parse_qs(urlparse(self.path).query)
                test_tier=subscription_test_tier(u,url_query,{})
                with conn() as c:
                    biz=c.execute("SELECT id,plan,payment_status,status FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    if u["role"]=="provider":
                        if not biz or biz["payment_status"]!="verified": return self.sendj({"error":"Complete a verified provider subscription and profile first."},403)
                        tier=ranks.get(str(biz["plan"] or "local").lower(),0)
                        business_id=int(biz["id"]);record_user_id=int(u["id"])
                    else:
                        tier=ranks[test_tier] if test_tier else 3
                        business_id=subscription_test_business_id(u["id"],test_tier) if test_tier else (int(biz["id"]) if biz else 0)
                        record_user_id=subscription_test_user_id(u["id"],test_tier) if test_tier else int(u["id"])
                    if tier<need_rank: return self.sendj({"error":"This tool unlocks with the "+("Priority" if need_rank==1 else "Business Spotlight")+" provider plan."},403)
                    if template_path:
                        rows=c.execute("SELECT id,name,eta,message,created_at,updated_at FROM provider_quote_templates WHERE user_id=? ORDER BY updated_at DESC,id DESC LIMIT 100",(record_user_id,)).fetchall()
                    elif test_tier:
                        rows=c.execute("SELECT id,title,description,starts_on,ends_on,status,created_at,updated_at FROM provider_campaigns WHERE user_id=? AND business_id=? ORDER BY updated_at DESC,id DESC LIMIT 100",(record_user_id,business_id)).fetchall()
                    else:
                        rows=c.execute("SELECT id,title,description,starts_on,ends_on,status,created_at,updated_at FROM provider_campaigns WHERE user_id=? ORDER BY updated_at DESC,id DESC LIMIT 100",(record_user_id,)).fetchall()
                return self.sendj({"items":[dict(x) for x in rows],"plan":test_tier or ("spotlight" if u["role"]=="admin" else str(biz["plan"]))})
            if path=="/api/provider/insights":
                u=self.require()
                ranks={"local":0,"priority":1,"plus":2,"spotlight":3}
                with conn() as c:
                    if u["role"]=="provider":
                        biz=c.execute("SELECT id,plan,payment_status FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                        if not biz or biz["payment_status"]!="verified": return self.sendj({"error":"Complete a verified provider profile first."},403)
                        if ranks.get(str(biz["plan"] or "local").lower(),0)<2: return self.sendj({"error":"Performance insights unlock with Business Plus."},403)
                        biz_ids=[int(biz["id"])]
                        plan=str(biz["plan"])
                    elif u["role"]=="admin":
                        q=urllib.parse.parse_qs(urlparse(self.path).query)
                        requested=str((q.get("test_tier") or ["spotlight"])[0]).lower()
                        if ranks.get(requested,3)<2:return self.sendj({"error":"Performance insights unlock with Business Plus."},403)
                        test_tier=subscription_test_tier(u,q,{})
                        if test_tier:
                            biz_ids=[subscription_test_business_id(u["id"],test_tier)]
                            plan=test_tier
                        else:
                            biz_ids=[int(x["id"]) for x in c.execute("SELECT id FROM businesses WHERE user_id=?",(u["id"],)).fetchall()]
                            plan="spotlight"
                    else: return self.sendj({"error":"Only service providers can view this report."},403)
                    if biz_ids:
                        ph=",".join("?" for _ in biz_ids); where="business_id IN ("+ph+")"; args=tuple(biz_ids)
                        job_count=c.execute("SELECT count(*) FROM job_requests WHERE "+where,args).fetchone()[0]
                        active_jobs=c.execute("SELECT count(*) FROM job_requests WHERE "+where+" AND status IN ('requested','quoted','accepted','scheduled','in_progress')",args).fetchone()[0]
                        quotes_sent=c.execute("SELECT count(*) FROM job_quotes WHERE "+where,args).fetchone()[0]
                        quotes_accepted=c.execute("SELECT count(*) FROM job_quotes WHERE "+where+" AND status='accepted'",args).fetchone()[0]
                        messages=c.execute("SELECT count(*) FROM messages WHERE "+where,args).fetchone()[0]
                        media=c.execute("SELECT count(*) FROM message_attachments WHERE "+where,args).fetchone()[0]
                        ratings=c.execute("SELECT COALESCE(AVG(stars),0) average,COUNT(*) total FROM ratings WHERE "+where+" AND target_type='provider'",args).fetchone()
                    else: job_count=active_jobs=quotes_sent=quotes_accepted=messages=media=0;ratings={"average":0,"total":0}
                return self.sendj({"plan":plan,"job_requests":int(job_count),"active_jobs":int(active_jobs),"quotes_sent":int(quotes_sent),"quotes_accepted":int(quotes_accepted),"messages":int(messages),"media_shared":int(media),"average_rating":round(float(ratings["average"] or 0),1),"rating_count":int(ratings["total"] or 0)})
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
            if path=="/api/admin/access-control":
                self.require("admin")
                enabled=setting("customer_provider_access","on")!="off"
                with conn() as c: notices=c.execute("SELECT id,subject,body,created_at FROM broadcast_notifications WHERE active=TRUE ORDER BY created_at DESC LIMIT 30").fetchall()
                return self.sendj({"enabled":enabled,"notices":[dict(x) for x in notices]})
            if path=="/api/notifications":
                u=self.user()
                if not u or u.get("role") not in ("customer","provider"): return self.sendj({"items":[]},401)
                with conn() as c: rows=c.execute("SELECT id,subject,body,created_at FROM broadcast_notifications WHERE active=TRUE ORDER BY created_at DESC LIMIT 30").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/admin/notifications":
                self.require("admin")
                with conn() as c: rows=c.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 200").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/admin/settings":
                self.require("admin")
                return self.sendj({"owner_email":setting("owner_email"),"smtp_configured":bool(os.environ.get("SKILLVAYA_SMTP_HOST") and os.environ.get("SKILLVAYA_SMTP_USER") and os.environ.get("SKILLVAYA_SMTP_PASSWORD")),"note":"SMTP credentials must be configured in the server environment; secrets are not stored in the browser."})
            if path=="/api/favorites":
                u=self.require()
                if u["role"] not in ("customer","provider","admin"): return self.sendj({"error":"Use an active customer or service-provider account to save providers."},403)
                with conn() as c:
                    rows=c.execute("""SELECT b.*,COALESCE(r.average,0) AS rating,COALESCE(r.rating_count,0) AS rating_count,f.created_at AS saved_at
                        FROM favorites f JOIN businesses b ON b.id=f.business_id
                        LEFT JOIN (SELECT business_id,AVG(stars) average,COUNT(*) rating_count FROM ratings WHERE target_type='provider' GROUP BY business_id) r ON r.business_id=b.id
                        WHERE f.customer_id=? AND LOWER(TRIM(COALESCE(b.status,''))) IN ('active','approved','published')
                        ORDER BY f.created_at DESC""",(u["id"],)).fetchall()
                items=[]
                for row in rows:
                    item=dict(row); item["rating"]=round(float(item["rating"] or 0),1); item["rating_count"]=int(item["rating_count"] or 0)
                    item.pop("user_id",None); item.pop("photos",None); item.pop("lat",None); item.pop("lng",None); item["email"]=item.get("email") or ""; item["whatsapp"]=item.get("whatsapp") or item.get("phone") or ""
                    items.append(item)
                return self.sendj({"items":items})
            if path=="/api/provider/profile":
                u=self.require("provider")
                with conn() as c:
                    row=c.execute("SELECT id,user_id,name,category,area,phone,whatsapp,email,website,description,photos,plan,billing,status,payment_status,subscription_expires_at,created_at FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    payment=c.execute("SELECT id FROM payments WHERE user_id=? AND status='verified' AND (business_id IS NULL OR business_id=?) ORDER BY id DESC LIMIT 1",(u["id"],row["id"] if row else -1)).fetchone()
                return self.sendj({"business":dict(row) if row else None,"payment_verified":bool(payment)})
            if path.startswith("/api/businesses/") and path.endswith("/photos"):
                try: bid=int(path.split("/")[3])
                except (ValueError,IndexError): return self.sendj({"error":"Unknown provider."},404)
                with conn() as c:
                    row=c.execute("SELECT photos FROM businesses WHERE id=? AND LOWER(TRIM(COALESCE(status,''))) IN ('active','approved','published')",(bid,)).fetchone()
                if not row: return self.sendj({"error":"Unknown provider."},404)
                return self.sendj({"photos":row["photos"] or ""})
            if path=="/api/provider/tools":
                u=self.require("provider")
                with conn() as c:
                    row=c.execute("SELECT id,name,category,area,lat,available_on,verified_at,verify_requested_at,country FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                if not row: return self.sendj({"business_id":None})
                return self.sendj({"business_id":row["id"],"name":row["name"],"category":row["category"],"available_today":str(row["available_on"] or "")==sv_local_today(row["country"]),"country":sv_country(row["country"]) or "ZA","currency":sv_currency(row["country"]),
                                   "verified":bool(str(row["verified_at"] or "").strip()),"verify_requested":bool(str(row["verify_requested_at"] or "").strip()),"has_location":row["lat"] is not None})
            if path=="/api/futurechat/status":
                u=self.user()
                with conn() as c:
                    joined=bool(u and c.execute("SELECT 1 FROM futurechat_waitlist WHERE user_id=?",(int(u["id"]),)).fetchone())
                    count=int(c.execute("SELECT COUNT(*) AS n FROM futurechat_waitlist").fetchone()["n"]) if (u and u.get("role")=="admin") else None
                out={"joined":joined}
                if count is not None: out["count"]=count
                return self.sendj(out)
            if path.startswith("/api/businesses/") and path.endswith("/growth"):
                bits=path.strip("/").split("/")
                try: business_id=int(bits[2]) if len(bits)==4 and bits[0]=="api" and bits[1]=="businesses" and bits[3]=="growth" else 0
                except (TypeError,ValueError): business_id=0
                if business_id<=0:return self.sendj({"error":"Provider listing not found."},404)
                today=datetime.date.today().isoformat()
                with conn() as c:
                    biz=c.execute("SELECT id,user_id,name FROM businesses WHERE id=? AND LOWER(TRIM(COALESCE(status,''))) IN ('active','approved','published')",(business_id,)).fetchone()
                    if not biz:return self.sendj({"error":"Provider listing not found."},404)
                    if biz["name"].strip().casefold()=="skillvaya digital & creative studio":
                        owner=c.execute("SELECT role FROM users WHERE id=?",(biz["user_id"],)).fetchone()
                        if owner and owner["role"]=="admin":
                            c.execute("UPDATE provider_campaigns SET business_id=? WHERE user_id=? AND business_id=0",(business_id,biz["user_id"]))
                    package_rows=c.execute("SELECT id,name,description,price_cents,add_ons FROM provider_service_packages WHERE business_id=? AND status='active' ORDER BY created_at DESC,id DESC LIMIT 12",(business_id,)).fetchall()
                    offer_rows=c.execute("SELECT id,title,code,description,discount_type,discount_value,starts_on,ends_on FROM provider_offers WHERE business_id=? AND status='active' AND (starts_on='' OR starts_on<=?) AND (ends_on='' OR ends_on>=?) AND (usage_limit=0 OR usage_count<usage_limit) ORDER BY created_at DESC,id DESC LIMIT 8",(business_id,today,today)).fetchall()
                    campaign_rows=c.execute("SELECT id,title,description,starts_on,ends_on FROM provider_campaigns WHERE business_id=? AND status='active' AND (starts_on='' OR starts_on<=?) AND (ends_on='' OR ends_on>=?) ORDER BY updated_at DESC,id DESC LIMIT 3",(business_id,today,today)).fetchall()
                packages=[]
                for row in package_rows:
                    item=dict(row)
                    try:item["add_ons"]=json.loads(item.get("add_ons") or "[]")
                    except Exception:item["add_ons"]=[]
                    packages.append(item)
                return self.sendj({"packages":packages,"offers":[dict(x) for x in offer_rows],"active_campaigns":[dict(x) for x in campaign_rows]})
            if path=="/api/businesses":
                from urllib.parse import parse_qs
                q=parse_qs(urlparse(self.path).query); term=q.get("q",[""])[0].lower(); area=q.get("area",[""])[0].lower(); cat=q.get("category",["All categories"])[0]; sort=q.get("sort",["featured"])[0]
                origin=None
                try:
                    if q.get("lat") and q.get("lng"):
                        _la=float(q["lat"][0]); _lo=float(q["lng"][0])
                        if -90<=_la<=90 and -180<=_lo<=180: origin=(_la,_lo)
                except (ValueError,TypeError): origin=None
                if origin is None and q.get("near_area",[""])[0].strip(): origin=sv_geocode(q["near_area"][0],q.get("country",["ZA"])[0] or "ZA")
                viewer=self.user()
                rater_id=viewer["id"] if viewer and viewer["role"]=="customer" else -1
                with conn() as c:
                    rows=c.execute("""SELECT b.*,
                        CASE WHEN LOWER(TRIM(COALESCE(b.name,'')))='skillvaya digital & creative studio' AND EXISTS (SELECT 1 FROM users owner_user WHERE owner_user.id=b.user_id AND owner_user.role='admin') THEN 1 ELSE 0 END AS owner_studio,
                        COALESCE(r.average,0) AS rating, COALESCE(r.rating_count,0) AS rating_count,
                        COALESCE(my.stars,0) AS my_rating, COALESCE(jd.jobs_done,0) AS jobs_done
                        FROM businesses b
                        LEFT JOIN (SELECT business_id,AVG(stars) AS average,COUNT(*) AS rating_count
                                   FROM ratings WHERE target_type='provider' GROUP BY business_id) r ON r.business_id=b.id
                        LEFT JOIN ratings my ON my.business_id=b.id AND my.target_type='provider'
                             AND my.rater_id=? AND my.target_user_id=b.user_id
                        LEFT JOIN (SELECT business_id,COUNT(*) AS jobs_done FROM job_requests WHERE status='completed' GROUP BY business_id) jd ON jd.business_id=b.id
                        WHERE LOWER(TRIM(COALESCE(b.status,''))) IN ('active','approved','published')""",(rater_id,)).fetchall()
                items=[dict(x) for x in rows if (category_matches(cat, x["category"]) or skillvaya_matches_category(cat, dict(x))) and (not term or term in (x["name"]+" "+x["category"]+" "+x["description"]+" "+category_search_terms(x["category"])).lower()) and (not area or area in x["area"].lower())]
                ranks={"local":0,"priority":1,"plus":2,"spotlight":3}
                _sv_cc=sv_country(q.get("country",[""])[0])
                if _sv_cc: items=[x for x in items if (sv_country(x.get("country")) or "ZA")==_sv_cc or any(w in str(x.get("area") or "").lower() for w in _SV_NO_GEO)]
                today=datetime.date.today().isoformat()
                with conn() as growth_c:
                    for item in items:
                        tier=ranks.get(str(item.get("plan") or "local").lower(),0)
                        item["packages"]=[];item["offers"]=[];item["active_campaigns"]=[]
                        if tier>=2:
                            pkgs=growth_c.execute("SELECT id,name,description,price_cents,add_ons FROM provider_service_packages WHERE business_id=? AND status='active' ORDER BY created_at DESC LIMIT 30",(item["id"],)).fetchall()
                            for pkg in pkgs:
                                z=dict(pkg)
                                try:z["add_ons"]=json.loads(z.get("add_ons") or "[]")
                                except Exception:z["add_ons"]=[]
                                item["packages"].append(z)
                        if tier>=3:
                            offers=growth_c.execute("SELECT id,title,code,description,discount_type,discount_value,starts_on,ends_on,usage_limit,usage_count FROM provider_offers WHERE business_id=? AND status='active' AND (starts_on='' OR starts_on<=?) AND (ends_on='' OR ends_on>=?) AND (usage_limit=0 OR usage_count<usage_limit) ORDER BY created_at DESC LIMIT 20",(item["id"],today,today)).fetchall()
                            item["offers"]=[dict(o) for o in offers]
                            campaigns=growth_c.execute("SELECT id,title,description,starts_on,ends_on FROM provider_campaigns WHERE business_id=? AND status='active' AND (starts_on='' OR starts_on<=?) AND (ends_on='' OR ends_on>=?) ORDER BY created_at DESC LIMIT 10",(item["id"],today,today)).fetchall()
                            item["active_campaigns"]=[dict(x) for x in campaigns]

                labels=provider_response_labels()
                _sv_days={}; missing=0
                for item in items:
                    item["rating"]=round(float(item["rating"] or 0),1); item["rating_count"]=int(item["rating_count"] or 0); item["my_rating"]=int(item["my_rating"] or 0)
                    item["response_label"]=labels.get(int(item["id"]),"")
                    item["jobs_done"]=int(item.get("jobs_done") or 0)
                    item["verified"]=bool(str(item.get("verified_at") or "").strip())
                    item["country"]=sv_country(item.get("country")) or "ZA"; item["currency"]=sv_currency(item["country"])
                    if item["country"] not in _sv_days: _sv_days[item["country"]]=sv_local_today(item["country"])
                    item["available_today"]=str(item.get("available_on") or "")==_sv_days[item["country"]]
                    item["has_photos"]=bool(str(item.get("photos") or "").strip())
                    if origin and item.get("lat") is not None and item.get("lng") is not None:
                        try: item["distance_km"]=round(_sv_km(origin,(float(item["lat"]),float(item["lng"]))),1)
                        except Exception: pass
                    elif origin and item.get("lat") is None and str(item.get("area") or "").strip() and missing<3:
                        missing+=1; sv_set_business_location_async(int(item["id"]),item["area"])
                    for _k in ("lat","lng","verified_at","verify_requested_at","available_on"): item.pop(_k,None)
                if sort=="rating": items.sort(key=lambda x:x["rating"] or 0,reverse=True)
                elif sort=="name": items.sort(key=lambda x:x["name"].lower())
                else:
                    items.sort(key=lambda x:{"spotlight":0,"plus":1,"priority":2,"local":3}.get(str(x["plan"] or "local").lower(),4))
                    day_index=int(datetime.date.today().strftime("%j"))
                    start=0
                    while start<len(items):
                        current_rank={"spotlight":0,"plus":1,"priority":2,"local":3}.get(str(items[start]["plan"] or "local").lower(),4)
                        end=start+1
                        while end<len(items) and {"spotlight":0,"plus":1,"priority":2,"local":3}.get(str(items[end]["plan"] or "local").lower(),4)==current_rank:
                            end+=1
                        cohort=items[start:end]
                        if len(cohort)>1:
                            offset=day_index%len(cohort)
                            cohort=cohort[offset:]+cohort[:offset]
                            items[start:end]=cohort
                        start=end
                if sort=="near" and origin: items.sort(key=lambda x:(x.get("distance_km") is None, x.get("distance_km") if x.get("distance_km") is not None else 0))
                elif sort=="available": items.sort(key=lambda x:not x.get("available_today"))
                for x in items:
                    x.pop("user_id",None); x.pop("photos",None)
                    # Email is intentionally shown only when the provider explicitly supplied it as public contact.
                    x["email"]=x.get("email") or ""
                    x["whatsapp"]=x.get("whatsapp") or x.get("phone") or ""
                return self.sendj({"businesses":items})
            if path=="/api/prices":
                # SV81-WORLD: provider plans at the same value as their rand price, in the visitor's currency.
                cc=sv_country(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("country",[""])[0]) or "ZA"
                cur=sv_currency(cc)
                try: rate=sv_zar_to(1.0,cur)
                except Exception: return self.sendj({"country":cc,"currency":"ZAR","rate":1.0,"fallback":True,"plans":{k:{"name":v["name"],"monthly_zar":v["monthly"],"monthly":v["monthly"],"yearly":v["monthly"]*11} for k,v in PLANS.items()}})
                return self.sendj({"country":cc,"currency":cur,"rate":rate,"plans":{k:{"name":v["name"],"monthly_zar":v["monthly"],"monthly":round(v["monthly"]*rate,2),"yearly":round(v["monthly"]*11*rate,2)} for k,v in PLANS.items()}})
            if path=="/api/i18n":
                ver,strings=sv_i18n(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("lang",[""])[0])
                return self.sendj({"version":ver,"strings":strings})
            if path=="/api/account/export":
                # SV81-WORLD: "Download my data" (GDPR / CCPA / POPIA access requests).
                u=self.require(); uid=int(u["id"])
                out={"exported_at":now(),"about":"Your Skillvaya data. Keep this file private."}
                hidden={"password_hash","data_base64","token","token_hash","purchase_token","lat","lng"}
                with conn() as c:
                    for name,sql,params in (
                        ("account","SELECT id,name,email,phone,role,country,created_at,accepted_terms_version,accepted_terms_at FROM users WHERE id=?",(uid,)),
                        ("business_listings","SELECT * FROM businesses WHERE user_id=?",(uid,)),
                        ("payments","SELECT plan,billing,amount,reference,status,created_at,verified_at,paypal_currency,paypal_amount,refunded_amount,refund_status FROM payments WHERE user_id=?",(uid,)),
                        ("job_requests","SELECT * FROM job_requests WHERE customer_id=? OR business_id IN (SELECT id FROM businesses WHERE user_id=?)",(uid,uid)),
                        ("quotes","SELECT * FROM job_quotes WHERE provider_id=? OR job_id IN (SELECT id FROM job_requests WHERE customer_id=?)",(uid,uid)),
                        ("messages","SELECT id,business_id,customer_id,sender_id,message,created_at,read_at FROM messages WHERE customer_id=? OR sender_id=? OR business_id IN (SELECT id FROM businesses WHERE user_id=?) ORDER BY id LIMIT 20000",(uid,uid,uid)),
                        ("saved_providers","SELECT business_id,created_at FROM favorites WHERE customer_id=?",(uid,)),
                        ("ratings_given","SELECT business_id,target_type,stars,created_at FROM ratings WHERE rater_id=?",(uid,))):
                        try: out[name]=[{k:v for k,v in dict(r).items() if k not in hidden} for r in c.execute(sql,params).fetchall()]
                        except Exception:
                            try: c.rollback()
                            except Exception: pass
                            out[name]=[]
                return self.sendj(out)
            if path=="/api/me":
                u=self.require(want_photo=True)
                if "profile_photo" not in u:
                    with conn() as c: row=c.execute("SELECT id,name,email,phone,role,profile_photo,country FROM users WHERE id=?",(u["id"],)).fetchone()
                    return self.sendj({"user":dict(row) if row else u})
                return self.sendj({"user":{"id":u["id"],"name":u["name"],"email":u["email"],"phone":u["phone"],"role":u["role"],"profile_photo":u["profile_photo"],"country":sv_user_country(u["id"])}})
            if path=="/api/account/profile":
                u=self.require(); return self.sendj({"user":u})
            if path=="/api/admin/summary":
                self.require("admin")
                with conn() as c:
                    return self.sendj({"businesses":c.execute("SELECT count(*) FROM businesses").fetchone()[0],"complaints":c.execute("SELECT count(*) FROM complaints WHERE status='open'").fetchone()[0],"payments":c.execute("SELECT count(*) FROM payments WHERE status='pending'").fetchone()[0],"pending":c.execute("SELECT count(*) FROM businesses WHERE status='pending'").fetchone()[0]})
            if path=="/api/admin/owner-promotions":
                self.require("admin")
                with conn() as c:
                    rows=c.execute("SELECT op.*,b.area AS area,b.phone AS phone,b.whatsapp AS whatsapp,b.email AS contact_email FROM owner_promotions op LEFT JOIN businesses b ON b.id=op.directory_business_id ORDER BY op.created_at DESC").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path == "/api/admin/account-deletion-requests":
                self.require("admin")
                with conn() as c:
                    rows=c.execute("SELECT r.id,r.user_id,r.user_email,r.reason,r.status,r.requested_at,r.reviewed_at,u.name AS user_name FROM account_deletion_requests r LEFT JOIN users u ON u.id=r.user_id WHERE r.status='pending' ORDER BY r.requested_at ASC").fetchall()
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

            if path=="/api/me/country":
                u=self.require(); cc=sv_country(d.get("country"))
                if not cc: return self.sendj({"error":"Choose a country from the list."},400)
                with conn() as c: c.execute("UPDATE users SET country=? WHERE id=?",(cc,u["id"]))
                return self.sendj({"ok":True,"country":cc,"currency":sv_currency(cc)})
            if path=="/api/provider/presence":
                u=self.require("provider")
                with conn() as c:
                    row=c.execute("SELECT id,area,country FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    if not row: return self.sendj({"error":"Create your provider profile first."},404)
                    if "available_today" in d:
                        c.execute("UPDATE businesses SET available_on=? WHERE id=?",(sv_local_today(row["country"]) if d.get("available_today") else "",row["id"]))
                if d.get("refresh_location"): sv_set_business_location_async(int(row["id"]),row["area"])
                return self.sendj({"ok":True,"available_today":bool(d.get("available_today"))})
            if path=="/api/provider/verification-request":
                u=self.require("provider")
                with conn() as c:
                    row=c.execute("SELECT id,name,phone,verified_at FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    if not row: return self.sendj({"error":"Create your provider profile first."},404)
                    if str(row["verified_at"] or "").strip(): return self.sendj({"ok":True,"verified":True})
                    c.execute("UPDATE businesses SET verify_requested_at=? WHERE id=?",(now(),row["id"]))
                sv_owner_alert("Verification request: "+str(row["name"]),"Provider "+str(row["name"])+" (account "+str(u.get("email",""))+", phone "+str(row["phone"] or "")+") asked to be verified. Check their identity and business, then press Verify in Admin > Business listings.")
                return self.sendj({"ok":True,"verified":False,"requested":True})
            if path=="/api/admin/businesses-verify":
                u=self.require()
                if u.get("role")!="admin": return self.sendj({"error":"Only the Skillvaya owner can verify providers."},403)
                try: bid=int(d.get("business_id",0))
                except (ValueError,TypeError): bid=0
                on=bool(d.get("verified"))
                with conn() as c:
                    c.execute("UPDATE businesses SET verified_at=?,verify_requested_at=? WHERE id=?",(now() if on else "","",bid))
                return self.sendj({"ok":True,"verified":on})
            if path=="/api/futurechat/notify":
                u=self.require()
                with conn() as c:
                    c.execute("INSERT INTO futurechat_waitlist(user_id,created_at) VALUES(?,?) ON CONFLICT(user_id) DO NOTHING",(int(u["id"]),now()))
                return self.sendj({"ok":True,"joined":True})
            if path=="/api/admin/futurechat":
                u=self.require()
                if u.get("role")!="admin": return self.sendj({"error":"Only the Skillvaya owner can do this."},403)
                msg=" ".join(str(d.get("message","")).split())[:200]
                if not msg: return self.sendj({"error":"Write the launch message first."},400)
                with conn() as c: ids=[int(r["user_id"]) for r in c.execute("SELECT user_id FROM futurechat_waitlist").fetchall()]
                def _announce():
                    send=globals().get("fcm_send_to_user") or globals().get("webpush_send_to_user")
                    for uid in ids:
                        try: send(uid,"Future Chat is here",msg,{"type":"futurechat_launch"})
                        except Exception: pass
                threading.Thread(target=_announce,name="skillvaya-fc-announce",daemon=True).start()
                return self.sendj({"ok":True,"sent":len(ids)})
            if path in ("/api/webpush/subscribe","/api/webpush/unsubscribe","/api/webpush/test"):
                u=self.require()
                if path.endswith("/test"):
                    n=webpush_send_to_user(int(u["id"]),"Skillvaya notifications are on","You will be alerted here about new messages and calls.",{"type":"test"})
                    return self.sendj({"ok":True,"sent":n})
                sub=d.get("subscription") if isinstance(d.get("subscription"),dict) else {}
                endpoint=str(sub.get("endpoint") or d.get("endpoint") or "").strip()
                if not endpoint or len(endpoint)>1000 or not _sv_wp_host_ok(endpoint): return self.sendj({"error":"This browser's notification service is not supported."},400)
                if path.endswith("/unsubscribe"):
                    with conn() as c: c.execute("UPDATE webpush_subscriptions SET enabled=0,updated_at=? WHERE endpoint=? AND user_id=?",(now(),endpoint,int(u["id"])))
                    return self.sendj({"ok":True})
                keys=sub.get("keys") if isinstance(sub.get("keys"),dict) else {}
                p256dh=str(keys.get("p256dh") or "").strip(); auth=str(keys.get("auth") or "").strip()
                if not (40<=len(p256dh)<=200 and 10<=len(auth)<=100): return self.sendj({"error":"Invalid notification keys."},400)
                stamp=now(); ua=str(self.headers.get("User-Agent",""))[:200]
                with conn() as c:
                    c.execute("INSERT INTO webpush_subscriptions(endpoint,user_id,p256dh,auth,user_agent,enabled,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id,p256dh=excluded.p256dh,auth=excluded.auth,user_agent=excluded.user_agent,enabled=1,updated_at=excluded.updated_at",(endpoint,int(u["id"]),p256dh,auth,ua,stamp,stamp))
                return self.sendj({"ok":True})
            if path == "/api/push/register":
                u = self.require()
                token = str(d.get("token", "")).strip()
                if len(token) < 40 or len(token) > 4096:
                    return self.sendj({"error":"Invalid device token."},400)
                ensure_push_token_table()
                stamp = now()
                with conn() as c:
                    c.execute("INSERT INTO push_device_tokens(token,user_id,platform,enabled,created_at,updated_at) VALUES(?,?,?,1,?,?) ON CONFLICT(token) DO UPDATE SET user_id=excluded.user_id,platform=excluded.platform,enabled=1,updated_at=excluded.updated_at",
                              (token,int(u["id"]),str(d.get("platform","android"))[:20],stamp,stamp))
                return self.sendj({"ok":True})
            if path == "/api/push/unregister":
                u = self.require()
                token = str(d.get("token", "")).strip()
                if token:
                    ensure_push_token_table()
                    with conn() as c:
                        c.execute("UPDATE push_device_tokens SET enabled=0,updated_at=? WHERE token=? AND user_id=?", (now(),token,int(u["id"])))
                return self.sendj({"ok":True})
            if path == "/api/google-play/rtdn":
                expected_audience=os.environ.get("GOOGLE_PLAY_RTDN_AUDIENCE","").strip()
                expected_email=os.environ.get("GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL","").strip()
                auth=self.headers.get("Authorization","").removeprefix("Bearer ").strip()
                if not expected_audience or not expected_email or not auth: return self.sendj({"error":"Authenticated Pub/Sub push is not configured."},401)
                try:
                    from google.auth.transport.requests import Request as GoogleAuthRequest
                    from google.oauth2 import id_token
                    claims=id_token.verify_oauth2_token(auth,GoogleAuthRequest(),audience=expected_audience)
                    if expected_email and claims.get("email")!=expected_email: return self.sendj({"error":"Pub/Sub identity did not match the configured service account."},403)
                    message=d.get("message") or {}; event=json.loads(base64.b64decode(message.get("data","")).decode("utf-8"))
                    notice_data=event.get("subscriptionNotification") or {}; purchase_token=str(notice_data.get("purchaseToken", ""))
                    if purchase_token:
                        with conn() as c:
                            c.execute("CREATE TABLE IF NOT EXISTS google_play_subscriptions (purchase_token TEXT PRIMARY KEY,user_id BIGINT NOT NULL,business_id BIGINT,product_id TEXT NOT NULL,base_plan_id TEXT NOT NULL,order_id TEXT,state TEXT NOT NULL,expiry_time TEXT NOT NULL,auto_renew_enabled BOOLEAN NOT NULL,updated_at TEXT NOT NULL)")
                            record=c.execute("SELECT user_id,business_id,product_id,state FROM google_play_subscriptions WHERE purchase_token=?",(purchase_token,)).fetchone()
                        if record and record["state"]=="REPLACED": return self.sendj({"ok":True,"ignored":"replaced_purchase"})
                        if record:
                            raw_creds=_google_play_credentials_json().strip(); creds_path=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS","").strip()
                            if not raw_creds and not creds_path: return self.sendj({"error":"Google Play verification credentials are missing."},503)
                            from google.oauth2 import service_account
                            from googleapiclient.discovery import build
                            scopes=["https://www.googleapis.com/auth/androidpublisher"]
                            creds=service_account.Credentials.from_service_account_info(json.loads(raw_creds),scopes=scopes) if raw_creds else service_account.Credentials.from_service_account_file(creds_path,scopes=scopes)
                            publisher=build("androidpublisher","v3",credentials=creds,cache_discovery=False)
                            current=publisher.purchases().subscriptionsv2().get(packageName=os.environ.get("GOOGLE_PLAY_PACKAGE_NAME","za.co.skillvaya.app"),token=purchase_token).execute()
                            lines=current.get("lineItems") or []; line=next((x for x in lines if x.get("productId")==record["product_id"]),None)
                            expiry=str(line.get("expiryTime", "")) if line else ""
                            try: expiry_dt=datetime.datetime.fromisoformat(expiry.replace("Z","+00:00"))
                            except Exception: expiry_dt=None
                            state=str(current.get("subscriptionState", "UNKNOWN")); valid=bool(expiry_dt and expiry_dt>datetime.datetime.now(datetime.timezone.utc) and state in ("SUBSCRIPTION_STATE_ACTIVE","SUBSCRIPTION_STATE_IN_GRACE_PERIOD","SUBSCRIPTION_STATE_CANCELED"))
                            with conn() as c:
                                c.execute("UPDATE google_play_subscriptions SET state=?,expiry_time=?,auto_renew_enabled=?,order_id=?,updated_at=? WHERE purchase_token=?",(state,expiry_dt.isoformat() if expiry_dt else expiry,bool((line or {}).get("autoRenewingPlan",{}).get("autoRenewEnabled",False)),str(current.get("latestOrderId", ""))[:160],now(),purchase_token))
                                if record["business_id"]:
                                    if valid: c.execute("UPDATE businesses SET subscription_expires_at=? WHERE id=? AND user_id=?",(expiry_dt.isoformat(),record["business_id"],record["user_id"]))
                                    else:
                                        c.execute("UPDATE businesses SET payment_status='expired',status='suspended' WHERE id=? AND user_id=?",(record["business_id"],record["user_id"]))
                                        c.execute("UPDATE subscriptions SET status='expired' WHERE business_id=? AND user_id=?",(record["business_id"],record["user_id"]))
                except Exception:
                    return self.sendj({"error":"Pub/Sub event could not be authenticated or reconciled."},503)
                return self.sendj({"ok":True})

            if path == "/api/password-reset/request":
                email=str(d.get("email","")).strip().lower()[:254]
                generic={"ok":True,"message":"If an account matches that email, a secure password-reset link will be sent shortly."}
                if not email or "@" not in email: return self.sendj(generic,202)
                with conn() as c:
                    user=c.execute("SELECT id,email,name FROM users WHERE lower(email)=?",(email,)).fetchone()
                    if not user: return self.sendj(generic,202)
                    recent=c.execute("SELECT created_at FROM password_reset_tokens WHERE user_id=? ORDER BY id DESC LIMIT 1",(user["id"],)).fetchone()
                    if recent:
                        try:
                            last=datetime.datetime.fromisoformat(recent["created_at"])
                            if (datetime.datetime.now(datetime.timezone.utc)-last).total_seconds()<60: return self.sendj(generic,202)
                        except (ValueError,TypeError): pass
                    c.execute("UPDATE password_reset_tokens SET used_at=? WHERE user_id=? AND used_at=''",(now(),user["id"]))
                    raw=secrets.token_urlsafe(32); th=hashlib.sha256(raw.encode()).hexdigest()
                    created=now(); expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=30)).isoformat()
                    c.execute("INSERT INTO password_reset_tokens(user_id,token_hash,created_at,expires_at,used_at) VALUES(?,?,?,?, '')",(user["id"],th,created,expires))
                base=os.environ.get("SKILLVAYA_PUBLIC_URL","https://skillvaya.onrender.com").strip().rstrip("/")
                link=base+"/reset-password?token="+urllib.parse.quote(raw,safe="")
                body="Hello "+str(user["name"] or "Skillvaya user")+",\n\nWe received a request to reset your Skillvaya password. Open this one-time link within 30 minutes:\n\n"+link+"\n\nIf you did not request this, ignore this email. Your current password remains unchanged. Do not share this link."
                if not send_owner_email("Reset your password",body,recipient=email):
                    with conn() as c: c.execute("UPDATE password_reset_tokens SET used_at=? WHERE token_hash=? AND used_at=''",(now(),th))
                return self.sendj(generic,202)
            if path == "/api/password-reset/confirm":
                raw=str(d.get("token","")).strip(); password=d.get("password","")
                if not isinstance(password,str) or len(password)<12 or len(password)>256: return self.sendj({"error":"Choose a password between 12 and 256 characters."},400)
                if len(raw)<30 or len(raw)>200: return self.sendj({"error":"This reset link is invalid or expired. Request a new one."},400)
                th=hashlib.sha256(raw.encode()).hexdigest(); current=datetime.datetime.now(datetime.timezone.utc)
                with conn() as c:
                    row=c.execute("SELECT id,user_id,expires_at,used_at FROM password_reset_tokens WHERE token_hash=?",(th,)).fetchone()
                    if not row or row["used_at"]: return self.sendj({"error":"This reset link is invalid, expired, or already used. Request a new one."},400)
                    try: expires=datetime.datetime.fromisoformat(row["expires_at"])
                    except (ValueError,TypeError): expires=current-datetime.timedelta(seconds=1)
                    if expires.tzinfo is None: expires=expires.replace(tzinfo=datetime.timezone.utc)
                    if expires<=current:
                        c.execute("UPDATE password_reset_tokens SET used_at=? WHERE id=? AND used_at='' ",(now(),row["id"]))
                        return self.sendj({"error":"This reset link has expired. Request a new one."},400)
                    changed=c.execute("UPDATE password_reset_tokens SET used_at=? WHERE id=? AND used_at='' ",(now(),row["id"]))
                    if getattr(changed,"rowcount",1)==0: return self.sendj({"error":"This reset link has already been used. Request a new one."},400)
                    user=c.execute("SELECT id FROM users WHERE id=?",(row["user_id"],)).fetchone()
                    if not user: return self.sendj({"error":"This account no longer exists."},400)
                    c.execute("UPDATE users SET password_hash=? WHERE id=?",(hashpw(password),row["user_id"]))
                    c.execute("UPDATE password_reset_tokens SET used_at=? WHERE user_id=? AND id<>? AND used_at=''",(now(),row["user_id"],row["id"]))
                # Force re-authentication on every session after a password reset.
                for session_token, session_user in list(SESSIONS.items()):
                    if int(session_user.get("id", 0)) == int(row["user_id"]):
                        SESSIONS.pop(session_token, None)
                return self.sendj({"ok":True,"message":"Password updated. You can now sign in with your new password."})

            if path == "/api/account/delete-request":
                u=self.require()
                if u.get("role")=="admin": return self.sendj({"error":"The owner account cannot be deleted through this flow."},403)
                reason=str(d.get("reason","")).strip()[:1000]
                with conn() as c:
                    existing=c.execute("SELECT id FROM account_deletion_requests WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    if existing: request_id=int(existing["id"]); already=True
                    else:
                        cur=c.execute("INSERT INTO account_deletion_requests(user_id,user_email,reason,status,requested_at) VALUES(?,?,?,'pending',?) RETURNING id",(u["id"],u["email"],reason,now()))
                        request_id=int(cur.fetchone()["id"]); already=False
                if not already: notify("account_deletion_request","Account deletion request received","Request ID: "+str(request_id)+". Account email: "+str(u["email"])+". Review and verify before processing.")
                return self.sendj({"ok":True,"request_id":request_id,"already_pending":already,"message":"Your account-deletion request has been recorded. Your account has not yet been deleted; the request will be verified and records subject to legal retention reviewed."},202)
            if path.startswith("/api/provider/growth/"):
                return self.handle_provider_growth("POST",path,d)
            # WF_STANDALONE_MESSAGING_V1: start or send in a WorkFinder-only thread.
            if path in ("/api/workfinder/conversations", "/api/workfinder/messages", "/api/workfinder/attachments"):
                u=self.require()
                if u.get("role") not in ("customer","provider"):
                    return self.sendj({"error":"Use a customer or provider account to message in WorkFinder."},403)
                if path.endswith("/conversations"):
                    email=str(d.get("recipient_email","")).strip().lower()[:254]
                    if not email or "@" not in email:return self.sendj({"error":"Enter the other person's registered email address."},400)
                    with conn() as c:
                        c.execute(f"""CREATE TABLE IF NOT EXISTS workfinder_conversations (
                            id {WF_ID_TYPE} PRIMARY KEY, user_a_id BIGINT NOT NULL, user_b_id BIGINT NOT NULL,
                            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_a_id,user_b_id))""")
                        c.execute(f"""CREATE TABLE IF NOT EXISTS workfinder_messages (
                            id {WF_ID_TYPE} PRIMARY KEY, conversation_id BIGINT NOT NULL,
                            sender_id BIGINT NOT NULL, recipient_id BIGINT NOT NULL,
                            message TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT)""")
                        partner=c.execute("SELECT id,name,email,role FROM users WHERE lower(email)=?",(email,)).fetchone()
                        if not partner:return self.sendj({"error":"No SkillVaya account was found for that email."},404)
                        if int(partner["id"])==int(u["id"]):return self.sendj({"error":"You cannot start a conversation with your own account."},400)
                        if partner["role"] not in ("customer","provider"):return self.sendj({"error":"That account cannot receive WorkFinder messages."},403)
                        a,b=sorted((int(u["id"]),int(partner["id"])))
                        stamp=now()
                        c.execute("INSERT INTO workfinder_conversations(user_a_id,user_b_id,created_at,updated_at) VALUES(?,?,?,?) ON CONFLICT(user_a_id,user_b_id) DO NOTHING",(a,b,stamp,stamp))
                        row=c.execute("SELECT id FROM workfinder_conversations WHERE user_a_id=? AND user_b_id=?",(a,b)).fetchone()
                        return self.sendj({"ok":True,"conversation_id":row["id"],"partner":{"id":partner["id"],"name":partner["name"],"email":partner["email"]}},201)
                if path.endswith("/attachments"):
                    try: cid=int(d.get("conversation_id",0))
                    except (ValueError,TypeError): return self.sendj({"error":"Choose a valid conversation."},400)
                    filename=str(d.get("filename","attachment")).replace("\\\\","/").split("/")[-1].strip()[:160]
                    filename="".join(ch for ch in filename if ch.isprintable() and ch not in '<>:"/\\\\|?*') or "attachment"
                    mime=str(d.get("mime_type","")).strip().lower()[:100]
                    allowed={"image/jpeg","image/png","image/webp","application/pdf","application/msword","application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
                    if mime not in allowed:return self.sendj({"error":"Choose a JPG, PNG, WebP, PDF, DOC or DOCX file."},400)
                    encoded=str(d.get("data","")).strip()
                    if encoded.startswith("data:") and "," in encoded:encoded=encoded.split(",",1)[1]
                    try: payload=base64.b64decode(encoded,validate=True)
                    except Exception:return self.sendj({"error":"The selected attachment could not be read."},400)
                    if not payload or len(payload)>1572864:return self.sendj({"error":"Attachments must be 1.5 MB or smaller."},413)
                    with conn() as c:
                        c.execute(f"""CREATE TABLE IF NOT EXISTS workfinder_conversations (id {WF_ID_TYPE} PRIMARY KEY, user_a_id BIGINT NOT NULL, user_b_id BIGINT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_a_id,user_b_id))""")
                        c.execute(f"""CREATE TABLE IF NOT EXISTS workfinder_messages (id {WF_ID_TYPE} PRIMARY KEY, conversation_id BIGINT NOT NULL, sender_id BIGINT NOT NULL, recipient_id BIGINT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT)""")
                        c.execute(f"""CREATE TABLE IF NOT EXISTS workfinder_message_attachments (id {WF_ID_TYPE} PRIMARY KEY, message_id BIGINT NOT NULL UNIQUE, filename TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes BIGINT NOT NULL, data_base64 TEXT NOT NULL)""")
                        convo=c.execute("SELECT * FROM workfinder_conversations WHERE id=? AND (user_a_id=? OR user_b_id=?)",(cid,u["id"],u["id"])).fetchone()
                        if not convo:return self.sendj({"error":"Conversation not found."},404)
                        recipient=int(convo["user_b_id"] if int(convo["user_a_id"])==int(u["id"]) else convo["user_a_id"])
                        stamp=now();cur=c.execute("INSERT INTO workfinder_messages(conversation_id,sender_id,recipient_id,message,created_at) VALUES(?,?,?,?,?) RETURNING id",(cid,u["id"],recipient,"Shared file: "+filename,stamp));mid=cur.fetchone()["id"]
                        c.execute("INSERT INTO workfinder_message_attachments(message_id,filename,mime_type,size_bytes,data_base64) VALUES(?,?,?,?,?)",(mid,filename,mime,len(payload),base64.b64encode(payload).decode("ascii")))
                        c.execute("UPDATE workfinder_conversations SET updated_at=? WHERE id=?",(stamp,cid))
                    return self.sendj({"ok":True,"message_id":mid,"filename":filename},201)
                try: cid=int(d.get("conversation_id",0))
                except (ValueError,TypeError): return self.sendj({"error":"Choose a valid conversation."},400)
                body=str(d.get("message","")).strip()[:4000]
                if not body:return self.sendj({"error":"Type a message before sending."},400)
                with conn() as c:
                    c.execute(f"""CREATE TABLE IF NOT EXISTS workfinder_conversations (
                        id {WF_ID_TYPE} PRIMARY KEY, user_a_id BIGINT NOT NULL, user_b_id BIGINT NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_a_id,user_b_id))""")
                    c.execute(f"""CREATE TABLE IF NOT EXISTS workfinder_messages (
                        id {WF_ID_TYPE} PRIMARY KEY, conversation_id BIGINT NOT NULL,
                        sender_id BIGINT NOT NULL, recipient_id BIGINT NOT NULL,
                        message TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT)""")
                    convo=c.execute("SELECT * FROM workfinder_conversations WHERE id=? AND (user_a_id=? OR user_b_id=?)",(cid,u["id"],u["id"])).fetchone()
                    if not convo:return self.sendj({"error":"Conversation not found."},404)
                    recipient=int(convo["user_b_id"] if int(convo["user_a_id"])==int(u["id"]) else convo["user_a_id"])
                    stamp=now()
                    cur=c.execute("INSERT INTO workfinder_messages(conversation_id,sender_id,recipient_id,message,created_at) VALUES(?,?,?,?,?) RETURNING id",(cid,u["id"],recipient,body,stamp))
                    mid=cur.fetchone()["id"]
                    c.execute("UPDATE workfinder_conversations SET updated_at=? WHERE id=?",(stamp,cid))
                    return self.sendj({"ok":True,"item":{"id":mid,"conversation_id":cid,"sender_id":u["id"],"recipient_id":recipient,"message":body,"created_at":stamp}},201)
            if path.startswith("/api/workfinder/"):
                u=self.require()
                kind=path.rsplit("/",1)[-1]
                with conn() as c:
                    c.execute("""CREATE TABLE IF NOT EXISTS workfinder_records (
                        user_id INTEGER NOT NULL, kind TEXT NOT NULL,
                        record_key TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL, UNIQUE(user_id,kind,record_key))""")
                    if kind=="applications":
                        if u["role"] not in ("customer","provider","admin"): return self.sendj({"error":"Sign in required."},403)
                        action=str(d.get("action","create"))
                        if action=="create":
                            title=str(d.get("title","")).strip()[:180]; company=str(d.get("company","")).strip()[:180]
                            if not title or not company: return self.sendj({"error":"Job title and employer are required."},400)
                            key=str(d.get("job_id") or (title+"|"+company))[:240]
                            payload={"title":title,"company":company,"cover_note":str(d.get("cover_note",""))[:5000],"status":"Applied","followUp":"","note":"","job_id":d.get("job_id")}
                            stamp=now()
                            c.execute("INSERT INTO workfinder_records(user_id,kind,record_key,payload,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,kind,record_key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",(u["id"],kind,key,json.dumps(payload),stamp,stamp))
                            return self.sendj({"ok":True,"item":payload},201)
                        key=str(d.get("key",""))[:240]
                        row=c.execute("SELECT payload FROM workfinder_records WHERE user_id=? AND kind=? AND record_key=?",(u["id"],kind,key)).fetchone()
                        if not row:return self.sendj({"error":"Application not found."},404)
                        payload=json.loads(row["payload"]); payload.update({k:d[k] for k in ("status","followUp","note") if k in d})
                        c.execute("UPDATE workfinder_records SET payload=?,updated_at=? WHERE user_id=? AND kind=? AND record_key=?",(json.dumps(payload),now(),u["id"],kind,key))
                        return self.sendj({"ok":True,"item":payload})
                    if kind not in ("profile","saved","searches","workwanted","reports","blocked","messages","jobs"):
                        return self.sendj({"error":"Unknown WorkFinder resource."},404)
                    if self.command=="GET":
                        rows=c.execute("SELECT record_key,payload FROM workfinder_records WHERE user_id=? AND kind=? ORDER BY updated_at DESC LIMIT 500",(u["id"],kind)).fetchall()
                        return self.sendj({"items":[{"key":r["record_key"],**json.loads(r["payload"])} for r in rows if not (kind=="saved" and json.loads(r["payload"]).get("removed"))]})
                    key=str(d.get("key","default"))[:240]
                    payload=d.get("payload",d)
                    if not isinstance(payload,dict):return self.sendj({"error":"Invalid record."},400)
                    raw=json.dumps(payload,ensure_ascii=False)
                    record_limit=2_500_000 if kind=="profile" and key in ("portfolio_files","documents","business_files") else 200000
                    if len(raw)>record_limit:return self.sendj({"error":"Record is too large. Choose files within the 1.5 MB combined upload limit." if record_limit>200000 else "Record is too large."},413)
                    stamp=now()
                    c.execute("INSERT INTO workfinder_records(user_id,kind,record_key,payload,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,kind,record_key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",(u["id"],kind,key,raw,stamp,stamp))
                return self.sendj({"ok":True,"key":key},201)
            if path=="/api/customer/marketing-preferences":
                return self.handle_customer_marketing_preferences("POST",d)
            if path=="/api/team/my-assignments":
                return self.handle_my_team_assignments("POST",d)
            if path=="/api/marketing/track":
                return self.handle_public_marketing_track(d)
            if path=="/api/messages/attachments":
                u=self.require()
                if u["role"] not in ("customer","provider","admin"): return self.sendj({"error":"Only account holders can share chat media."},403)
                try:
                    bid=int(d.get("business_id",0)); customer_id=int(d.get("customer_id",0))
                except (ValueError,TypeError): return self.sendj({"error":"Choose a valid conversation."},400)
                filename=str(d.get("filename","shared-media")).replace("\\\\","/").split("/")[-1].strip()[:160]
                filename="".join(ch for ch in filename if ch.isprintable() and ch not in '<>:"/\\\\|?*') or "shared-media"
                mime=str(d.get("mime_type","")).strip().lower()[:100]
                allowed_mimes={"image/jpeg","image/png","image/webp","image/gif","video/mp4","video/webm","video/quicktime","video/3gpp","video/x-m4v","video/x-msvideo","video/ogg"}
                if mime not in allowed_mimes: return self.sendj({"error":"Choose a supported photo or video (JPG, PNG, WebP, GIF, MP4, WebM or MOV)."},400)
                encoded=str(d.get("base64","")).strip()
                if "," in encoded and encoded.startswith("data:"): encoded=encoded.split(",",1)[1]
                if not encoded or len(encoded)>17_100_000: return self.sendj({"error":"Choose a video smaller than 12 MB."},413)
                try: payload=base64.b64decode(encoded,validate=True)
                except Exception: return self.sendj({"error":"The selected file could not be read. Please choose it again."},400)
                if not payload or len(payload)>12*1024*1024: return self.sendj({"error":"Photos and videos must be 12 MB or smaller."},413)
                with conn() as c:
                    biz=c.execute("SELECT id,user_id,name,status FROM businesses WHERE id=?",(bid,)).fetchone()
                    customer=c.execute("SELECT id,role FROM users WHERE id=?",(customer_id,)).fetchone()
                    if not biz or biz["status"] not in ("active","approved","published"): return self.sendj({"error":"The provider listing is not available."},404)
                    if not customer or customer["role"]!="customer": return self.sendj({"error":"The customer conversation was not found."},404)
                    if u["role"]=="customer":
                        if int(u["id"])!=customer_id or int(biz["user_id"] or 0)==int(u["id"]): return self.sendj({"error":"You cannot upload to this conversation."},403)
                    elif u["role"]=="provider":
                        if int(biz["user_id"] or 0)!=int(u["id"]): return self.sendj({"error":"You can upload only to your own provider conversations."},403)
                    # A chat must already exist: a provider may not start unsolicited media messages.
                    interaction=c.execute("SELECT 1 FROM messages WHERE business_id=? AND customer_id=? UNION SELECT 1 FROM enquiries WHERE business_id=? AND customer_id=? UNION SELECT 1 FROM contacts WHERE business_id=? AND customer_id=? LIMIT 1",(bid,customer_id,bid,customer_id,bid,customer_id)).fetchone()
                    if not interaction and u["role"]!="admin": return self.sendj({"error":"Send or receive a text message before sharing media in this chat."},403)
                    label="Video shared: " if mime.startswith("video/") else "Photo shared: "
                    message_id=c.execute("INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?) RETURNING id",(bid,customer_id,u["id"],label+filename,now())).fetchone()["id"]
                    cur=c.execute("INSERT INTO message_attachments(message_id,business_id,customer_id,sender_id,filename,mime_type,size_bytes,data_base64,created_at) VALUES(?,?,?,?,?,?,?,?,?) RETURNING id",(message_id,bid,customer_id,u["id"],filename,mime,len(payload),base64.b64encode(payload).decode("ascii"),now()))
                    attachment_id=cur.fetchone()["id"]
                return self.sendj({"ok":True,"message_id":message_id,"attachment_id":attachment_id,"filename":filename,"mime_type":mime,"size_bytes":len(payload)},201)
            if path=="/api/video-calls":
                u=self.require()
                action=str(d.get("action","")).strip().lower()
                if action=="start":
                    if u["role"] not in ("customer","provider","admin"): return self.sendj({"error":"Sign in to start a video call."},401)
                    try: bid=int(d.get("business_id",0)); customer_id=int(d.get("customer_id",0))
                    except (ValueError,TypeError): return self.sendj({"error":"Choose a valid chat."},400)
                    if u['role']=='customer': customer_id=int(u['id'])
                    offer=d.get("offer_sdp","")
                    if isinstance(offer,dict): offer=json.dumps(offer)
                    if not isinstance(offer,str) or len(offer)>100000: return self.sendj({"error":"Video call offer was too large."},413)
                    try:
                        offer_obj=json.loads(offer)
                        if offer_obj.get("type")!="offer" or not offer_obj.get("sdp"): raise ValueError()
                    except Exception: return self.sendj({"error":"A valid camera/microphone call offer is required."},400)
                    with conn() as c:
                        biz=c.execute("SELECT id,user_id,name,status FROM businesses WHERE id=?",(bid,)).fetchone()
                        if not biz or biz["status"] not in ("active","approved","published"): return self.sendj({"error":"The provider listing is not available."},404)
                        # `customer_id` is the legacy name for the customer-side chat participant.
                        # Existing chat routes also let provider accounts contact another provider,
                        # where that participant is a provider-role user rather than a customer-role user.
                        if u["role"]=="customer": customer_id=int(u["id"])
                        elif u["role"]=="provider" and int(biz["user_id"] or 0)!=int(u["id"]): customer_id=int(u["id"])
                        customer=c.execute("SELECT id,role FROM users WHERE id=?",(customer_id,)).fetchone()
                        if not customer or customer["role"] not in ("customer","provider","admin"): return self.sendj({"error":"The conversation participant was not found."},404)
                        if u["role"]=="customer":
                            if int(u["id"])!=customer_id or int(biz["user_id"] or 0)==int(u["id"]): return self.sendj({"error":"You cannot call this chat."},403)
                            callee_id=int(biz["user_id"])
                        elif u["role"]=="provider":
                            if int(biz["user_id"] or 0)==int(u["id"]):
                                if customer_id==int(u["id"]): return self.sendj({"error":"You cannot call your own listing."},403)
                                callee_id=customer_id
                            else:
                                # This provider is the customer-side participant in another provider's chat.
                                customer_id=int(u["id"])
                                callee_id=int(biz["user_id"] or 0)
                        else:
                            callee_id=customer_id if customer_id!=int(u["id"]) else int(biz["user_id"] or 0)
                            if callee_id<=0: return self.sendj({"error":"Choose a valid call recipient."},400)
                        interaction=c.execute("SELECT 1 FROM messages WHERE business_id=? AND customer_id=? UNION SELECT 1 FROM enquiries WHERE business_id=? AND customer_id=? UNION SELECT 1 FROM contacts WHERE business_id=? AND customer_id=? LIMIT 1",(bid,customer_id,bid,customer_id,bid,customer_id)).fetchone()
                        if not interaction: return self.sendj({"error":"Start a chat with a text message before calling."},403)
                        call_id=secrets.token_urlsafe(18);stamp=now()
                        if hasattr(c,"execute_atomic"):
                            # SV76-PERF-02: the call row and its chat invitation are written by ONE statement (one round trip, atomic).
                            c.execute_atomic("WITH vc AS (INSERT INTO video_calls(id,business_id,customer_id,caller_id,callee_id,status,offer_sdp,answer_sdp,created_at,updated_at,ended_at) VALUES(?,?,?,?,?,'ringing',?,'',?,?, '')) INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)",(call_id,bid,customer_id,u["id"],callee_id,offer_obj and json.dumps(offer_obj),stamp,stamp,bid,customer_id,u["id"],"Video call invitation",stamp))
                        else:
                            c.execute("INSERT INTO video_calls(id,business_id,customer_id,caller_id,callee_id,status,offer_sdp,answer_sdp,created_at,updated_at,ended_at) VALUES(?,?,?,?,?,'ringing',?,'',?,?, '')",(call_id,bid,customer_id,u["id"],callee_id,offer_obj and json.dumps(offer_obj),stamp,stamp))
                            # Save a call-invitation event in the existing chat so both sides have a durable record.
                            c.execute("INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)",(bid,customer_id,u["id"],"Video call invitation",stamp))
                    # The call row is already committed. Dispatch push outside the request path so
                    # Firebase network latency cannot delay the caller's immediate "ringing" response.
                    try:
                        threading.Thread(
                            target=fcm_send_to_user,
                            args=(callee_id, "Skillvaya calling", (u.get("name") or "Your contact") + " is calling you",
                                  {"type":"incoming_call","call_id":call_id,"business_id":bid,"customer_id":customer_id}),
                            name="SkillvayaIncomingCallPush",
                            daemon=True,
                        ).start()
                    except Exception as exc:
                        print("FCM call-push scheduling failed:", type(exc).__name__)
                    return self.sendj({"ok":True,"call_id":call_id,"status":"ringing"},201)
                try: call_id=str(d.get("call_id","")).strip()
                except Exception: call_id=""
                if not call_id or len(call_id)>100: return self.sendj({"error":"Choose a valid call."},400)
                with conn() as c:
                    call=c.execute("SELECT vc.*,b.user_id AS provider_owner_id FROM video_calls vc JOIN businesses b ON b.id=vc.business_id WHERE vc.id=?",(call_id,)).fetchone()
                    if not call: return self.sendj({"error":"Video call not found."},404)
                    allowed=(u["role"]=="admin" or int(u["id"]) in (int(call["caller_id"]),int(call["callee_id"])) or (u["role"]=="provider" and int(u["id"])==int(call["provider_owner_id"])))
                    if not allowed: return self.sendj({"error":"You cannot control this video call."},403)
                    if action=="accept":
                        if int(u["id"])!=int(call["callee_id"]) and u["role"]!="admin": return self.sendj({"error":"Only the person being called can accept this call."},403)
                        answer=d.get("answer_sdp","")
                        if isinstance(answer,dict): answer=json.dumps(answer)
                        try:
                            ans_obj=json.loads(answer) if isinstance(answer,str) else {}
                            if ans_obj.get("type")!="answer" or not ans_obj.get("sdp") or len(answer)>100000: raise ValueError()
                        except Exception: return self.sendj({"error":"A valid video call answer is required."},400)
                        if call["status"]!="ringing": return self.sendj({"error":"This call is no longer ringing."},409)
                        db_atomic(c,"UPDATE video_calls SET status='accepted',answer_sdp=?,updated_at=? WHERE id=?",(json.dumps(ans_obj),now(),call_id))
                        return self.sendj({"ok":True,"status":"accepted"})
                    if action=="candidate":
                        if call["status"] not in ("ringing","accepted"): return self.sendj({"error":"This call is no longer active."},409)
                        candidate=d.get("candidate")
                        if not isinstance(candidate,dict) or len(json.dumps(candidate))>8000: return self.sendj({"error":"Invalid network candidate."},400)
                        row=db_atomic(c,"INSERT INTO video_call_signals(call_id,sender_id,kind,payload,created_at) VALUES(?,?,'candidate',?,?) RETURNING id",(call_id,u["id"],json.dumps(candidate),now())).fetchone()
                        return self.sendj({"ok":True,"signal_id":row["id"]},201)
                    if action in ("reject","end"):
                        if action=="reject" and int(u["id"])!=int(call["callee_id"]) and u["role"]!="admin": return self.sendj({"error":"Only the person receiving the call can decline it."},403)
                        status="rejected" if action=="reject" else "ended";stamp=now()
                        if call["status"] in ("ended","rejected","missed"): return self.sendj({"ok":True,"status":call["status"]})
                        # SV77-MISSED-CALL-01: the caller hung up before anyone answered.
                        if action=="end" and call["status"]=="ringing" and int(u["id"])==int(call["caller_id"]): status="missed"
                        db_atomic(c,"UPDATE video_calls SET status=?,updated_at=?,ended_at=? WHERE id=?",(status,stamp,stamp,call_id))
                        if status=="missed": sv_missed_call_notice(c,dict(call))
                        return self.sendj({"ok":True,"status":status})
                return self.sendj({"error":"Unsupported video call action."},400)
            if path in ("/api/provider/quote-templates","/api/provider/campaigns"):
                u=self.require()
                if u["role"] not in ("provider","admin"): return self.sendj({"error":"Only service providers can use this workspace tool."},403)
                template_path=path.endswith("quote-templates")
                need_rank=1 if template_path else 3
                ranks=PROVIDER_TIER_RANKS
                url_query=urllib.parse.parse_qs(urlparse(self.path).query)
                test_tier=subscription_test_tier(u,url_query,d)
                with conn() as c:
                    biz=c.execute("SELECT id,plan,payment_status,status FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    if u["role"]=="provider":
                        if not biz or biz["payment_status"]!="verified": return self.sendj({"error":"Complete a verified provider subscription and profile first."},403)
                        tier=ranks.get(str(biz["plan"] or "local").lower(),0)
                        business_id=int(biz["id"]);record_user_id=int(u["id"])
                    else:
                        tier=ranks[test_tier] if test_tier else 3
                        business_id=subscription_test_business_id(u["id"],test_tier) if test_tier else int(d.get("business_id",biz["id"] if biz else 0) or 0)
                        record_user_id=subscription_test_user_id(u["id"],test_tier) if test_tier else int(u["id"])
                    if tier<need_rank: return self.sendj({"error":"This tool unlocks with the "+("Priority" if need_rank==1 else "Business Spotlight")+" provider plan."},403)
                    if self.command=="GET":
                        if template_path:
                            rows=c.execute("SELECT id,name,eta,message,created_at,updated_at FROM provider_quote_templates WHERE user_id=? ORDER BY updated_at DESC,id DESC LIMIT 100",(record_user_id,)).fetchall()
                        else:
                            rows=c.execute("SELECT id,title,description,starts_on,ends_on,status,created_at,updated_at FROM provider_campaigns WHERE user_id=? ORDER BY updated_at DESC,id DESC LIMIT 100",(record_user_id,)).fetchall()
                        return self.sendj({"items":[dict(x) for x in rows],"plan":test_tier or ("spotlight" if u["role"]=="admin" else str(biz["plan"]))})
                    if template_path:
                        name=str(d.get("name","")).strip()[:120];eta=str(d.get("eta","")).strip()[:160];message=str(d.get("message","")).strip()[:2000]
                        if len(name)<2 or not eta or len(message)<5: return self.sendj({"error":"Enter a template name, estimated timeline and quotation wording."},400)
                        cur=c.execute("INSERT INTO provider_quote_templates(user_id,name,eta,message,created_at,updated_at) VALUES(?,?,?,?,?,?) RETURNING id",(record_user_id,name,eta,message,now(),now()))
                        return self.sendj({"ok":True,"id":cur.fetchone()["id"],"message":"Quotation template saved."},201)
                    action=str(d.get("action","create"))
                    if action in ("publish","pause","delete"):
                        try: campaign_id=int(d.get("id",0))
                        except (TypeError,ValueError): return self.sendj({"error":"Choose a valid campaign."},400)
                        existing=c.execute("SELECT * FROM provider_campaigns WHERE id=? AND user_id=? AND business_id=?",(campaign_id,record_user_id,business_id)).fetchone()
                        if not existing:return self.sendj({"error":"Campaign draft not found for this provider."},404)
                        if action=="delete":
                            c.execute("DELETE FROM provider_campaigns WHERE id=? AND user_id=? AND business_id=?",(campaign_id,record_user_id,business_id))
                            return self.sendj({"ok":True,"message":"Campaign removed."})
                        if action=="publish":
                            title=str(existing["title"] or "").strip();description=str(existing["description"] or "").strip()
                            starts=str(existing["starts_on"] or "").strip();ends=str(existing["ends_on"] or "").strip()
                            today=datetime.date.today().isoformat()
                            if len(title)<3 or len(description)<10:return self.sendj({"error":"Campaign title and description are required before publishing."},400)
                            if starts and ends and ends<starts:return self.sendj({"error":"Campaign end date must be on or after the start date."},400)
                            if ends and ends<today:return self.sendj({"error":"This campaign's end date has passed. Edit the dates before publishing."},400)
                            c.execute("UPDATE provider_campaigns SET status='active',updated_at=? WHERE id=? AND user_id=? AND business_id=?",(now(),campaign_id,record_user_id,business_id))
                            return self.sendj({"ok":True,"status":"active","message":"Campaign is now visible on your public provider listing."})
                        c.execute("UPDATE provider_campaigns SET status='paused',updated_at=? WHERE id=? AND user_id=? AND business_id=?",(now(),campaign_id,record_user_id,business_id))
                        return self.sendj({"ok":True,"status":"paused"})
                    title=str(d.get("title","")).strip()[:120];description=str(d.get("description","")).strip()[:2000]
                    starts_on=str(d.get("starts_on","")).strip()[:20];ends_on=str(d.get("ends_on","")).strip()[:20]
                    if len(title)<3 or len(description)<10: return self.sendj({"error":"Enter a campaign title and at least 10 characters describing the promotion."},400)
                    cur=c.execute("INSERT INTO provider_campaigns(user_id,business_id,title,description,starts_on,ends_on,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'draft',?,?) RETURNING id",(record_user_id,business_id,title,description,starts_on,ends_on,now(),now()))
                    return self.sendj({"ok":True,"id":cur.fetchone()["id"],"status":"draft","message":"Campaign saved as a private draft. It has not been published to customers."},201)
            if path=="/api/provider/insights":
                u=self.require()
                ranks={"local":0,"priority":1,"plus":2,"spotlight":3}
                with conn() as c:
                    if u["role"]=="provider":
                        biz=c.execute("SELECT id,plan,payment_status FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                        if not biz or biz["payment_status"]!="verified": return self.sendj({"error":"Complete a verified provider profile first."},403)
                        if ranks.get(str(biz["plan"] or "local").lower(),0)<2: return self.sendj({"error":"Performance insights unlock with Business Plus."},403)
                        biz_ids=[int(biz["id"])]
                        plan=str(biz["plan"])
                    elif u["role"]=="admin":
                        biz_ids=[int(x["id"]) for x in c.execute("SELECT id FROM businesses").fetchall()]
                        plan="spotlight"
                    else: return self.sendj({"error":"Only service providers can view this report."},403)
                    if biz_ids:
                        ph=",".join("?" for _ in biz_ids)
                        where="business_id IN ("+ph+")"
                        args=tuple(biz_ids)
                        job_count=c.execute("SELECT count(*) FROM job_requests WHERE "+where,args).fetchone()[0]
                        active_jobs=c.execute("SELECT count(*) FROM job_requests WHERE "+where+" AND status IN ('requested','quoted','accepted','scheduled','in_progress')",args).fetchone()[0]
                        quotes_sent=c.execute("SELECT count(*) FROM job_quotes WHERE "+where,args).fetchone()[0]
                        quotes_accepted=c.execute("SELECT count(*) FROM job_quotes WHERE "+where+" AND status='accepted'",args).fetchone()[0]
                        messages=c.execute("SELECT count(*) FROM messages WHERE "+where,args).fetchone()[0]
                        media=c.execute("SELECT count(*) FROM message_attachments WHERE "+where,args).fetchone()[0]
                        ratings=c.execute("SELECT COALESCE(AVG(stars),0) average,COUNT(*) total FROM ratings WHERE "+where+" AND target_type='provider'",args).fetchone()
                    else: job_count=active_jobs=quotes_sent=quotes_accepted=messages=media=0;ratings={"average":0,"total":0}
                return self.sendj({"plan":plan,"job_requests":int(job_count),"active_jobs":int(active_jobs),"quotes_sent":int(quotes_sent),"quotes_accepted":int(quotes_accepted),"messages":int(messages),"media_shared":int(media),"average_rating":round(float(ratings["average"] or 0),1),"rating_count":int(ratings["total"] or 0)})

            if path=="/api/account/become-provider":
                u=self.require()
                if u["role"]=="admin":
                    return self.sendj({"error":"The owner account already has full provider access."},409)
                if u["role"]=="provider":
                    return self.sendj({"ok":True,"user":u,"already_provider":True})
                if u["role"]!="customer":
                    return self.sendj({"error":"This account cannot be converted to a provider."},403)
                with conn() as c:
                    c.execute("UPDATE users SET role='provider' WHERE id=? AND role='customer'",(u["id"],))
                    row=c.execute("SELECT id,name,email,phone,role,profile_photo FROM users WHERE id=?",(u["id"],)).fetchone()
                if not row or row["role"]!="provider":
                    return self.sendj({"error":"Provider access could not be activated. Please sign in again and retry."},409)
                return self.sendj({"ok":True,"user":dict(row)})
            if path=="/api/google-play/verify":
                u=self.require("provider")
                purchase_token=str(d.get("purchase_token","")).strip()
                if not purchase_token or len(purchase_token)>4096: return self.sendj({"error":"A valid Google Play purchase token is required."},400)
                raw_creds=_google_play_credentials_json().strip()
                creds_path=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS","").strip()
                package_name=os.environ.get("GOOGLE_PLAY_PACKAGE_NAME","za.co.skillvaya.app").strip()
                if not raw_creds and not creds_path: return self.sendj({"error":"Google Play purchase verification is not configured on the server yet. No paid access was granted."},503)
                try:
                    from google.oauth2 import service_account
                    from googleapiclient.discovery import build
                    scopes=["https://www.googleapis.com/auth/androidpublisher"]
                    creds=service_account.Credentials.from_service_account_info(json.loads(raw_creds),scopes=scopes) if raw_creds else service_account.Credentials.from_service_account_file(creds_path,scopes=scopes)
                    publisher=build("androidpublisher","v3",credentials=creds,cache_discovery=False)
                    verified=publisher.purchases().subscriptionsv2().get(packageName=package_name,token=purchase_token).execute()
                except Exception as e:
                    return self.sendj({"error":"Google Play could not verify this purchase. No paid access was granted. Check the Android Publisher API service-account access."},503)
                state=str(verified.get("subscriptionState", ""))
                lines=verified.get("lineItems") or []
                line=next((x for x in lines if x.get("productId") in ("skillvaya_local","skillvaya_priority","skillvaya_business_plus","skillvaya_business_spotlight")),None)
                if not line: return self.sendj({"error":"The verified purchase is not a Skillvaya subscription product."},409)
                if not isinstance(line.get("prepaidPlan"),dict) or line.get("autoRenewingPlan"):
                    return self.sendj({"error":"Google Play products must use prepaid base plans. Automatic-renewal plans are not supported; no paid access was granted."},409)
                plan_by_product={"skillvaya_local":"local","skillvaya_priority":"priority","skillvaya_business_plus":"plus","skillvaya_business_spotlight":"spotlight"}
                plan=plan_by_product[line["productId"]]
                expiry=str(line.get("expiryTime", ""))
                try: expiry_dt=datetime.datetime.fromisoformat(expiry.replace("Z","+00:00"))
                except Exception: expiry_dt=None
                now_dt=datetime.datetime.now(datetime.timezone.utc)
                if state not in ("SUBSCRIPTION_STATE_ACTIVE","SUBSCRIPTION_STATE_IN_GRACE_PERIOD","SUBSCRIPTION_STATE_CANCELED") or not expiry_dt or expiry_dt<=now_dt:
                    return self.sendj({"error":"This Google Play subscription is not currently entitled to paid access."},409)
                offer=line.get("offerDetails") or {}
                base_plan=str(offer.get("basePlanId", "")).strip()
                if base_plan not in ("monthly","annual"): return self.sendj({"error":"The verified Google Play subscription has an unsupported base plan. No paid access was granted."},409)
                billing="yearly" if base_plan=="annual" else "monthly"
                amount=int(PLANS[plan]["monthly"]*(11 if billing=="yearly" else 1))
                order_id=str(verified.get("latestOrderId", d.get("order_id", "")))[:160]
                auto_renew=bool((line.get("autoRenewingPlan") or {}).get("autoRenewEnabled",False))
                with conn() as c:
                    c.execute("CREATE TABLE IF NOT EXISTS google_play_subscriptions (purchase_token TEXT PRIMARY KEY,user_id BIGINT NOT NULL,business_id BIGINT,product_id TEXT NOT NULL,base_plan_id TEXT NOT NULL,order_id TEXT,state TEXT NOT NULL,expiry_time TEXT NOT NULL,auto_renew_enabled BOOLEAN NOT NULL,updated_at TEXT NOT NULL)")
                    existing=c.execute("SELECT user_id,business_id FROM google_play_subscriptions WHERE purchase_token=?",(purchase_token,)).fetchone()
                    if existing and int(existing["user_id"])!=int(u["id"]): return self.sendj({"error":"This Google Play purchase is already linked to a different Skillvaya account."},409)
                    external_ids=verified.get("externalAccountIdentifiers") or {}
                    external_id=str(external_ids.get("obfuscatedExternalAccountId", ""))
                    expected_external=base64.urlsafe_b64encode(hashlib.sha256(str(u["id"]).encode()).digest()).decode().rstrip("=")[:64]
                    if external_id and not hmac.compare_digest(external_id,expected_external): return self.sendj({"error":"The Google Play purchase account does not match this Skillvaya account."},409)
                    if not existing and not external_id: return self.sendj({"error":"This purchase is not linked to the signed-in Skillvaya account. Please start checkout again from this app."},409)
                    linked_token=str(verified.get("linkedPurchaseToken", "")).strip()
                    if linked_token and linked_token!=purchase_token:
                        linked=c.execute("SELECT user_id FROM google_play_subscriptions WHERE purchase_token=?",(linked_token,)).fetchone()
                        if linked and int(linked["user_id"])!=int(u["id"]): return self.sendj({"error":"The replaced Google Play subscription belongs to a different Skillvaya account."},409)
                        if linked: c.execute("UPDATE google_play_subscriptions SET state='REPLACED',auto_renew_enabled=FALSE,updated_at=? WHERE purchase_token=?",(now(),linked_token))
                    biz=c.execute("SELECT id FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    business_id=int(biz["id"]) if biz else (int(existing["business_id"]) if existing and existing["business_id"] else None)
                    reference="GP-"+hashlib.sha256(purchase_token.encode()).hexdigest()[:20].upper()
                    payment=c.execute("SELECT * FROM payments WHERE reference=?",(reference,)).fetchone()
                    if not payment:
                        cur=c.execute("INSERT INTO payments(user_id,business_id,plan,billing,amount,reference,created_at,payment_gateway) VALUES(?,?,?,?,?,?,?,'google_play') RETURNING id",(u["id"],business_id,plan,billing,amount,reference,now()))
                        payment=c.execute("SELECT * FROM payments WHERE id=?",(cur.fetchone()["id"],)).fetchone()
                    if payment["status"]!="verified": activate_payment(c,payment,order_id or reference)
                    if business_id:
                        c.execute("UPDATE businesses SET plan=?,billing=?,payment_status='verified',status='active',subscription_expires_at=? WHERE id=? AND user_id=?",(plan,billing,expiry_dt.isoformat(),business_id,u["id"]))
                        c.execute("INSERT INTO subscriptions(business_id,user_id,plan,billing,status,started_at,expires_at,cancelled_at) VALUES(?,?,?,?,?,?,?,NULL) ON CONFLICT(business_id) DO UPDATE SET user_id=excluded.user_id,plan=excluded.plan,billing=excluded.billing,status='active',expires_at=excluded.expires_at,cancelled_at=NULL",(business_id,u["id"],plan,billing,"active",now(),expiry_dt.isoformat()))
                    c.execute("INSERT INTO google_play_subscriptions(purchase_token,user_id,business_id,product_id,base_plan_id,order_id,state,expiry_time,auto_renew_enabled,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(purchase_token) DO UPDATE SET business_id=excluded.business_id,product_id=excluded.product_id,base_plan_id=excluded.base_plan_id,order_id=excluded.order_id,state=excluded.state,expiry_time=excluded.expiry_time,auto_renew_enabled=excluded.auto_renew_enabled,updated_at=excluded.updated_at",(purchase_token,u["id"],business_id,line["productId"],base_plan,order_id,state,expiry_dt.isoformat(),auto_renew,now()))
                return self.sendj({"ok":True,"status":"verified","plan":plan,"billing":billing,"expires_at":expiry_dt.isoformat(),"auto_renew_enabled":auto_renew,"profile_required":business_id is None,"message":"Google Play subscription verified. Your Skillvaya access has been updated."})
            if path=="/api/paypal/create-order":
                u=self.require("provider"); plan=d.get("plan"); billing=d.get("billing")
                return self.sendj({"error":SV_PLAY_ONLY,"play_only":True},410)  # SV82-PLAY-ONLY: every plan is paid through Google Play
                if plan not in PLANS or billing not in ("monthly","yearly"): return self.sendj({"error":"Choose a valid plan and billing term."},400)
                cfg=paypal_config()
                if not cfg["public_url"].startswith("https://"): return self.sendj({"error":"Set SKILLVAYA_PUBLIC_URL to the public HTTPS Skillvaya address in Render."},503)
                if not cfg["client_id"] or not cfg["secret"]: return self.sendj({"error":"PayPal credentials are not configured in Render."},503)
                amount=int(PLANS[plan]["monthly"]*(11 if billing=="yearly" else 1)); ref="SV-"+secrets.token_hex(4).upper()
                with conn() as c:
                    _bz=c.execute("SELECT country FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                paypal_currency=sv_paypal_currency(sv_country(_bz["country"] if _bz else "") or sv_user_country(u["id"]) or "ZA")
                try:
                    paypal_amount=sv_paypal_amount(amount,paypal_currency)
                except Exception as e:
                    return self.sendj({"error":str(e)},503)
                with conn() as c:
                    b=c.execute("SELECT id FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    c.execute("INSERT INTO payments(user_id,business_id,plan,billing,amount,reference,created_at,payment_gateway,paypal_currency,paypal_amount) VALUES(?,?,?,?,?,?,?,'paypal',?,?)",(u["id"],b["id"] if b else None,plan,billing,amount,ref,now(),paypal_currency,paypal_amount))
                try:
                    order=paypal_api_request("POST","/v2/checkout/orders",{"intent":"CAPTURE","purchase_units":[{"reference_id":ref,"custom_id":ref,"invoice_id":ref,"description":"Skillvaya "+PLANS[plan]["name"]+" "+billing,"amount":{"currency_code":paypal_currency,"value":paypal_amount}}],"application_context":{"brand_name":"Skillvaya","user_action":"PAY_NOW","return_url":cfg["public_url"]+"/payment/paypal-return","cancel_url":cfg["public_url"]+"/payment/cancel"}})
                except Exception as e: return self.sendj({"error":"Could not start PayPal checkout: "+str(e),"reference":ref},502)
                approval=next((x.get("href") for x in order.get("links",[]) if x.get("rel")=="approve"),None); order_id=order.get("id")
                if not order_id or not approval: return self.sendj({"error":"PayPal did not return a checkout approval link.","reference":ref},502)
                with conn() as c: c.execute("UPDATE payments SET paypal_order_id=? WHERE reference=?",(order_id,ref))
                notify("payment_request","PayPal payment request created","Provider: "+u["email"]+"; plan: "+plan+"; billing: "+billing+"; amount: R"+str(amount)+"; reference: "+ref+". Payment is not confirmed.")
                return self.sendj({"ok":True,"checkout_ready":True,"reference":ref,"amount":amount,"currency":"ZAR","paypal_amount":paypal_amount,"paypal_currency":paypal_currency,"mode":cfg["mode"],"order_id":order_id,"approval_url":approval})
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
                expected_currency=(row["paypal_currency"] or "USD") if "paypal_currency" in row.keys() else "USD"
                expected_amount=(row["paypal_amount"] or "") if "paypal_amount" in row.keys() else ""
                if unit.get("custom_id")!=row["reference"] or cap_amount.get("currency_code")!=expected_currency or not expected_amount: return self.sendj({"error":"PayPal reference or checkout currency/amount record did not match. The plan has not been activated."},409)
                try: paid=float(cap_amount.get("value","-1")); expected_paid=float(expected_amount)
                except (TypeError,ValueError): paid=-1; expected_paid=-2
                if abs(paid-expected_paid)>0.001: return self.sendj({"error":"The confirmed PayPal amount does not match the exact checkout quote. The plan has not been activated."},409)
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
            if path=="/api/admin/access-control":
                self.require("admin")
                enabled=d.get("enabled")
                if not isinstance(enabled,bool): return self.sendj({"error":"Access state must be true or false."},400)
                with conn() as c: c.execute("INSERT INTO settings(key,value) VALUES('customer_provider_access',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",("on" if enabled else "off",))
                _SETTING_CACHE.clear()
                return self.sendj({"ok":True,"enabled":enabled})
            if path=="/api/admin/broadcast-notification":
                u=self.require("admin")
                subject=str(d.get("subject","")).strip()[:160]; body=str(d.get("body","")).strip()[:5000]
                if not subject or not body: return self.sendj({"error":"Enter a notification title and message."},400)
                with conn() as c: c.execute("INSERT INTO broadcast_notifications(subject,body,created_at,created_by,active) VALUES(?,?,?,?,TRUE)",(subject,body,now(),u.get("id")))
                notify("broadcast","Skillvaya notice: "+subject,body)
                return self.sendj({"ok":True,"message":"Notification saved for customer and provider/Work Finder sides."},201)
            if path=="/api/admin/settings":
                self.require("admin")
                email=d.get("owner_email","").strip().lower()
                if email and ("@" not in email or len(email)>254): return self.sendj({"error":"Enter a valid owner email address."},400)
                with conn() as c: c.execute("INSERT INTO settings(key,value) VALUES('owner_email',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(email,))
                _SETTING_CACHE.clear()
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
                    cur=c.execute("INSERT INTO notifications(kind,subject,body,status,created_at,recipient) VALUES(?,?,?,?,?,?) RETURNING id",("client_message",subject,"To: "+client["name"]+" <"+client["email"]+">\
\
"+body,"new",now(),client["email"]))
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
                name=str(d.get("name",u.get("name", ""))).strip()[:120]; phone=str(d.get("phone",u.get("phone", ""))).strip()[:40]
                photo=str(d.get("profile_photo",u.get("profile_photo", ""))).strip()
                # Profile edits must never change account privileges. The profile UI can
                # submit a stale/default role value; ignore it and preserve the authenticated
                # account's existing role. Role changes require a separate authorized workflow.
                if len(name)<2: return self.sendj({"error":"Enter a name of at least 2 characters."},400)
                if photo and (not photo.startswith(("data:image/png;base64,","data:image/jpeg;base64,","data:image/webp;base64,")) or len(photo)>2800000):
                    return self.sendj({"error":"Profile picture must be a PNG, JPG or WebP image no larger than 2 MB."},400)
                with conn() as c:
                    c.execute("UPDATE users SET name=?,phone=?,profile_photo=? WHERE id=?",(name,phone,photo,u["id"]))
                    row=c.execute("SELECT id,name,email,phone,role,profile_photo FROM users WHERE id=?",(u["id"],)).fetchone()
                return self.sendj({"ok":True,"user":dict(row) if row else {**u,"name":name,"phone":phone,"profile_photo":photo}})
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
                name=d.get("name","").strip(); email=d.get("email","").strip().lower(); phone=d.get("phone","").strip()[:40]; pw=d.get("password",""); role=d.get("role","customer"); country=sv_country(d.get("country"))
                terms_accepted = d.get("accept_terms") is True
                terms_version = setting("terms_version", TERMS_VERSION)
                if not terms_accepted: return self.sendj({"error":"You must read and accept the Skillvaya Terms, Conditions, Rules & Safety before creating an account."},400)
                if not name or "@" not in email or len(pw)<8 or role not in ("customer","provider"): return self.sendj({"error":"Enter a name, valid email, password of 8+ characters, and valid account type."},400)
                with conn() as c:
                    try: uid=c.execute("INSERT INTO users(name,email,password_hash,role,created_at,phone,accepted_terms_version,accepted_terms_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",(name,email,hashpw(pw),role,now(),phone,terms_version,now())).fetchone()["id"]
                    except DBIntegrityError: return self.sendj({"error":"An account with that email already exists."},409)
                    if country: c.execute("UPDATE users SET country=? WHERE id=?",(country,uid))
                u={"id":uid,"name":name,"email":email,"phone":phone,"role":role,"profile_photo":"","country":country}; t=issue_session(u)
                notify("new_account","New Skillvaya account","New "+role+" account created: "+name+" <"+email+">.")
                return self.sendj({"token":t,"user":u})
            if path=="/api/login":
                email=d.get("email","").lower().strip(); pw=d.get("password","")
                with conn() as c: row=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
                if not row or not verify_password(row["password_hash"],pw):return self.sendj({"error":"Email or password is incorrect."},401)
                if row["role"]=="suspended": return self.sendj({"error":"This account is suspended. Contact Skillvaya support if you believe this is a mistake."},403)
                if row["role"]!="admin" and d.get("accept_terms") is not True:
                    return self.sendj({"error":"Please read the current Terms, Conditions, Rules & Safety and tick the agreement box before signing in.","terms_required":True,"terms_url":"/terms"},400)
                if not row["password_hash"].startswith("pbkdf2_sha256$"):
                    with conn() as c: c.execute("UPDATE users SET password_hash=? WHERE id=?",(hashpw(pw),row["id"]))
                if d.get("accept_terms") is True:
                    terms_version=setting("terms_version",TERMS_VERSION)
                    with conn() as c: c.execute("UPDATE users SET accepted_terms_version=?,accepted_terms_at=? WHERE id=?",(terms_version,now(),row["id"]))
                u={"id":row["id"],"name":row["name"],"email":row["email"],"phone":row["phone"] if "phone" in row.keys() else "", "profile_photo":row["profile_photo"] if "profile_photo" in row.keys() else "", "role":row["role"]}; t=issue_session(u); u["country"]=sv_country(row["country"]) if "country" in row.keys() else ""; return self.sendj({"token":t,"user":u})
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
                    c.execute("UPDATE businesses SET country=? WHERE id=?",(sv_country(d.get("country")) or sv_user_country(u["id"]) or "ZA",business_id))
                    c.execute("UPDATE payments SET business_id=? WHERE id=?",(business_id,payment["id"]))
                    c.execute("INSERT INTO subscriptions(business_id,user_id,plan,billing,status,started_at,expires_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(business_id) DO UPDATE SET user_id=excluded.user_id,plan=excluded.plan,billing=excluded.billing,status='active',started_at=excluded.started_at,expires_at=excluded.expires_at,cancelled_at=NULL",(business_id,u["id"],payment["plan"],payment["billing"],"active",now(),expires))
                return self.sendj({"ok":True,"message":"Payment verified. Your provider profile is active."},201)
            if path=="/api/provider/profile":
                u=self.require("provider")
                name=str(d.get("name","")).strip()[:120]; category=str(d.get("category","")).strip(); area=str(d.get("area","")).strip()[:160]
                phone=str(d.get("phone","")).strip()[:40]; whatsapp=str(d.get("whatsapp","")).strip()[:40] or phone
                email=str(d.get("email","")).strip().lower()[:254]; website=str(d.get("website","")).strip()[:500]
                desc=str(d.get("description","")).strip()[:4000]; photos=str(d.get("photos","")).strip()
                if not all([name,category in CATEGORIES,area,phone,desc]): return self.sendj({"error":"Complete the business name, valid category, service area, phone and service description."},400)
                if any(x and not x.startswith(("https://","http://")) for x in (website,)): return self.sendj({"error":"Website links must start with http:// or https://."},400)
                if len(photos)>2800000: return self.sendj({"error":"Portfolio files are too large. Choose files within the 2 MB combined limit."},400)
                with conn() as c:
                    row=c.execute("SELECT id FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    if not row: return self.sendj({"error":"No existing provider profile was found. Create your profile after verified payment first."},404)
                    c.execute("UPDATE businesses SET name=?,category=?,area=?,phone=?,whatsapp=?,email=?,website=?,description=?,photos=? WHERE id=? AND user_id=?",(name,category,area,phone,whatsapp,email,website,desc,photos,row["id"],u["id"]))
                    if sv_country(d.get("country")): c.execute("UPDATE businesses SET country=? WHERE id=? AND user_id=?",(sv_country(d.get("country")),row["id"],u["id"]))
                    saved=c.execute("SELECT id,user_id,name,category,area,phone,whatsapp,email,website,description,photos,plan,billing,status,payment_status,subscription_expires_at,created_at FROM businesses WHERE id=? AND user_id=?",(row["id"],u["id"])).fetchone()
                sv_set_business_location_async(int(saved["id"]),area)
                return self.sendj({"ok":True,"business":dict(saved),"message":"Your existing provider profile has been updated."})
            if path=="/api/favorites":
                u=self.require("customer")
                try: bid=int(d.get("business_id",0))
                except (ValueError,TypeError): return self.sendj({"error":"Choose a valid service provider."},400)
                with conn() as c:
                    biz=c.execute("SELECT id,user_id FROM businesses WHERE id=? AND LOWER(TRIM(COALESCE(status,''))) IN ('active','approved','published')",(bid,)).fetchone()
                    if not biz: return self.sendj({"error":"This provider is not currently available."},404)
                    if biz["user_id"]==u["id"]: return self.sendj({"error":"You cannot save your own service listing."},403)
                    existing=c.execute("SELECT id FROM favorites WHERE customer_id=? AND business_id=?",(u["id"],bid)).fetchone()
                    if existing:
                        c.execute("DELETE FROM favorites WHERE customer_id=? AND business_id=?",(u["id"],bid))
                        saved=False
                    else:
                        c.execute("INSERT INTO favorites(customer_id,business_id,created_at) VALUES(?,?,?) ON CONFLICT(customer_id,business_id) DO NOTHING",(u["id"],bid,now()))
                        saved=True
                return self.sendj({"ok":True,"saved":saved,"business_id":bid})
            if path=="/api/jobs":
                u=self.require()
                if u["role"] not in ("customer","provider"): return self.sendj({"error":"Use a customer or service-provider account to request a service."},403)
                try: bid=int(d.get("business_id",0))
                except (ValueError,TypeError): return self.sendj({"error":"Choose a service provider."},400)
                title=str(d.get("title","")).strip()[:160]
                description=str(d.get("description","")).strip()[:4000]
                area=str(d.get("area","")).strip()[:160]
                preferred_date=str(d.get("preferred_date","")).strip()[:40]
                budget=d.get("budget_rands","")
                if len(title)<3 or len(description)<10: return self.sendj({"error":"Add a clear job title and at least 10 characters describing the work."},400)
                budget_cents=None
                if budget not in ("",None):
                    try: budget_cents=round(float(budget)*100)
                    except (ValueError,TypeError): return self.sendj({"error":"Enter a valid optional budget amount."},400)
                    if budget_cents<0 or budget_cents>1000000000: return self.sendj({"error":"The budget must be between R0 and R10,000,000."},400)
                with conn() as c:
                    biz=c.execute("SELECT id,user_id,name FROM businesses WHERE id=? AND status='active'",(bid,)).fetchone()
                    if not biz: return self.sendj({"error":"This provider is not currently available."},404)
                    if biz["user_id"]==u["id"]: return self.sendj({"error":"You cannot request a job from your own listing."},403)
                    stamp=now()
                    cur=c.execute("INSERT INTO job_requests(customer_id,business_id,title,description,area,preferred_date,budget_cents,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'requested',?,?) RETURNING id",(u["id"],bid,title,description,area,preferred_date,budget_cents,stamp,stamp))
                    job_id=cur.fetchone()["id"]
                    c.execute("INSERT INTO enquiries(business_id,customer_id,message,status,created_at) VALUES(?,?,?,'new',?)",(bid,u["id"],title+" — "+description,stamp))
                    c.execute("INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)",(bid,u["id"],u["id"],title+" — "+description,stamp))
                notify("job_request","New Skillvaya job request", "Job #"+str(job_id)+" for "+biz["name"]+"; requester "+u["email"]+".")
                return self.sendj({"ok":True,"job_id":job_id,"status":"requested","message":"Job request sent to "+biz["name"]+"."},201)
            if path.startswith("/api/jobs/"):
                u=self.require()
                parts=path.strip("/").split("/")
                try: job_id=int(parts[2])
                except (IndexError,ValueError): return self.sendj({"error":"Invalid job ID."},400)
                action=parts[3] if len(parts)>3 else ""
                with conn() as c:
                    job=c.execute("SELECT j.*,b.user_id provider_id,b.name business_name FROM job_requests j JOIN businesses b ON b.id=j.business_id WHERE j.id=?",(job_id,)).fetchone()
                    if not job: return self.sendj({"error":"Job not found."},404)
                    is_customer=u["role"] in ("customer","provider") and job["customer_id"]==u["id"]
                    is_provider=u["role"]=="provider" and job["provider_id"]==u["id"]
                    if not (is_customer or is_provider or u["role"]=="admin"): return self.sendj({"error":"You do not have access to this job."},403)
                    if action=="quote":
                        if not is_provider: return self.sendj({"error":"Only the assigned provider can submit a quote."},403)
                        if job["status"] not in ("requested","quoted"): return self.sendj({"error":"This job is no longer accepting quotes."},409)
                        try: amount_cents=round(float(d.get("amount_rands",0))*100)
                        except (ValueError,TypeError): return self.sendj({"error":"Enter a valid quote amount."},400)
                        eta=str(d.get("eta","")).strip()[:160]
                        message=str(d.get("message","")).strip()[:2000]
                        if amount_cents<1 or amount_cents>1000000000: return self.sendj({"error":"Quote amount must be between R0.01 and R10,000,000."},400)
                        if not eta or not message: return self.sendj({"error":"Include an estimated timeline and what the quote covers."},400)
                        existing=c.execute("SELECT id,status FROM job_quotes WHERE job_id=? AND business_id=?",(job_id,job["business_id"])).fetchone()
                        if existing and existing["status"]=="accepted": return self.sendj({"error":"An accepted quote cannot be overwritten."},409)
                        c.execute("INSERT INTO job_quotes(job_id,business_id,provider_id,amount_cents,eta,message,status,created_at) VALUES(?,?,?,?,?,?,'pending',?) ON CONFLICT(job_id,business_id) DO UPDATE SET amount_cents=excluded.amount_cents,eta=excluded.eta,message=excluded.message,status='pending',created_at=excluded.created_at",(job_id,job["business_id"],u["id"],amount_cents,eta,message,now()))
                        c.execute("UPDATE job_requests SET status='quoted',updated_at=? WHERE id=?",(now(),job_id))
                        return self.sendj({"ok":True,"status":"quoted","message":"Quote saved and sent to the customer."},201)
                    if action=="accept":
                        if not is_customer: return self.sendj({"error":"Only the customer who requested the job can accept a quote."},403)
                        if job["status"] not in ("requested","quoted"): return self.sendj({"error":"This job is no longer accepting quote decisions."},409)
                        try: quote_id=int(d.get("quote_id",0))
                        except (ValueError,TypeError): quote_id=0
                        quote=c.execute("SELECT id FROM job_quotes WHERE id=? AND job_id=? AND status='pending'",(quote_id,job_id)).fetchone()
                        if not quote: return self.sendj({"error":"That quote is not available to accept."},404)
                        c.execute("UPDATE job_quotes SET status=CASE WHEN id=? THEN 'accepted' ELSE 'declined' END WHERE job_id=?",(quote_id,job_id))
                        c.execute("UPDATE job_requests SET status='accepted',updated_at=? WHERE id=?",(now(),job_id))
                        return self.sendj({"ok":True,"status":"accepted","message":"Quote accepted. The provider can now schedule and update the job."})
                    if action=="status":
                        status=str(d.get("status","")).strip().lower()
                        allowed_provider={"scheduled","in_progress","completed"}
                        if is_provider and status not in allowed_provider: return self.sendj({"error":"Providers can move an accepted job to scheduled, in progress, or completed."},400)
                        if is_provider and job["status"] not in ("accepted","scheduled","in_progress"): return self.sendj({"error":"A quote must be accepted before the provider can progress the job."},409)
                        if is_customer and status!="cancelled": return self.sendj({"error":"Customers may cancel a job; only the provider can update work progress."},403)
                        if is_customer and job["status"] in ("completed","cancelled"): return self.sendj({"error":"A completed or cancelled job cannot be cancelled again."},409)
                        if status=="cancelled" and job["status"] in ("completed","cancelled"): return self.sendj({"error":"A completed or cancelled job cannot be cancelled."},409)
                        if status not in ({"cancelled"} if is_customer else allowed_provider|{"cancelled"}): return self.sendj({"error":"Unsupported job status."},400)
                        c.execute("UPDATE job_requests SET status=?,updated_at=? WHERE id=?",(status,now(),job_id))
                        return self.sendj({"ok":True,"status":status})
                return self.sendj({"error":"Unknown job action."},404)
            if path=="/api/enquiries":
                u=self.require()
                if u.get("role") not in ("customer","provider","admin"):
                    return self.sendj({"error":"Sign in with an active Skillvaya account to contact a provider."},403)
                try: bid=int(d.get("business_id",0))
                except (TypeError,ValueError): return self.sendj({"error":"Choose a valid provider."},400)
                message=str(d.get("message","")).strip()[:4000]
                if not message:return self.sendj({"error":"Message cannot be empty."},400)
                with conn() as c:
                    biz=c.execute("SELECT id,user_id FROM businesses WHERE id=? AND status='active'",(bid,)).fetchone()
                    if not biz:return self.sendj({"error":"Business not found or unavailable."},404)
                    if u.get("role") in ("customer","provider") and int(biz["user_id"])==int(u["id"]):
                        return self.sendj({"error":"You cannot contact your own listing."},403)
                    c.execute("INSERT INTO enquiries(business_id,customer_id,message,created_at) VALUES(?,?,?,?)",(bid,u["id"],message,now()))
                    c.execute("INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)",(bid,u["id"],u["id"],message,now()))
                return self.sendj({"ok":True},201)
            if path=="/api/messages":
                u=self.require()
                with conn() as c:
                    if u["role"]=="admin":
                        rows=c.execute("SELECT m.*,b.name business_name,b.phone business_phone,b.user_id business_owner_id,cu.name customer_name,cu.phone customer_phone,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id ORDER BY m.created_at DESC LIMIT 300").fetchall()
                    elif u["role"]=="provider":
                        rows=c.execute("SELECT m.*,b.name business_name,b.phone business_phone,b.user_id business_owner_id,cu.name customer_name,cu.phone customer_phone,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id WHERE b.user_id=? OR m.customer_id=? ORDER BY m.created_at DESC LIMIT 300",(u["id"],u["id"])).fetchall()
                    else:
                        rows=c.execute("SELECT m.*,b.name business_name,b.phone business_phone,cu.name customer_name,cu.phone customer_phone,cu.email customer_email FROM messages m JOIN businesses b ON b.id=m.business_id JOIN users cu ON cu.id=m.customer_id WHERE m.customer_id=? ORDER BY m.created_at DESC LIMIT 300",(u["id"],)).fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/contacts":
                u=self.require()
                if u["role"] not in ("customer","provider","admin"): return self.sendj({"error":"Use an active customer or service-provider account to contact this listing."},403)
                try: bid=int(d.get("business_id",0))
                except (ValueError,TypeError): return self.sendj({"error":"Choose a valid provider."},400)
                with conn() as c:
                    biz=c.execute("SELECT id,user_id FROM businesses WHERE id=? AND status='active'",(bid,)).fetchone()
                    if not biz: return self.sendj({"error":"Provider listing not found."},404)
                    if u["role"] in ("customer","provider") and int(biz["user_id"])==int(u["id"]): return self.sendj({"error":"You cannot make a contact with your own listing."},403)
                    c.execute("INSERT INTO contacts(business_id,customer_id,created_at) VALUES(?,?,?) ON CONFLICT(business_id,customer_id) DO NOTHING",(bid,u["id"],now()))
                    row=c.execute("SELECT ct.*,b.name business_name,b.phone business_phone,b.user_id business_owner_id,cu.name customer_name,cu.phone customer_phone FROM contacts ct JOIN businesses b ON b.id=ct.business_id JOIN users cu ON cu.id=ct.customer_id WHERE ct.business_id=? AND ct.customer_id=?",(bid,u["id"])).fetchone()
                return self.sendj({"ok":True,"contact":dict(row)},201)
            if path=="/api/messages/read":
                u=self.require()
                try: bid=int(d.get("business_id",0)); customer_id=int(d.get("customer_id",0))
                except (ValueError,TypeError): return self.sendj({"error":"Invalid conversation."},400)
                with conn() as c:
                    if u["role"]=="provider":
                        allowed=(customer_id==int(u["id"])) or c.execute("SELECT 1 FROM businesses WHERE id=? AND user_id=?",(bid,u["id"])).fetchone()
                    else:
                        allowed=(customer_id==int(u["id"]) and u["role"] in ("customer","admin")) or (u["role"]=="admin" and c.execute("SELECT 1 FROM businesses WHERE id=? AND user_id=?",(bid,u["id"])).fetchone())
                    if not allowed:return self.sendj({"error":"Conversation not found."},404)
                    db_atomic(c,"UPDATE messages SET read_at=? WHERE business_id=? AND customer_id=? AND sender_id<>? AND read_at IS NULL",(now(),bid,customer_id,u["id"]))
                return self.sendj({"ok":True})
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
                        if not c.execute("SELECT 1 FROM enquiries WHERE business_id=? AND customer_id=? UNION SELECT 1 FROM messages WHERE business_id=? AND customer_id=? LIMIT 1",(bid,customer_id,bid,customer_id)).fetchone(): return self.sendj({"error":"You can reply only in a conversation started by that customer."},403)
                    elif u["role"] in ("customer","provider"):
                        if biz["user_id"]==u["id"]: return self.sendj({"error":"You cannot message your own listing."},403)
                        customer_id=u["id"]
                    elif u["role"]=="admin": customer_id=int(d.get("customer_id",u["id"]))
                    else:return self.sendj({"error":"You cannot message this listing."},403)
                    if hasattr(c,"execute_atomic") and u["role"]=="customer":
                        # SV76-PERF-02: message + enquiry in ONE statement (one round trip, atomic) instead of BEGIN + 2 inserts + COMMIT.
                        stamp=now()
                        c.execute_atomic("WITH m AS (INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)) INSERT INTO enquiries(business_id,customer_id,message,created_at) VALUES(?,?,?,?)",(bid,customer_id,u["id"],body,stamp,bid,customer_id,body,stamp))
                    elif hasattr(c,"execute_atomic"):
                        c.execute_atomic("INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)",(bid,customer_id,u["id"],body,now()))
                    else:
                        c.execute("INSERT INTO messages(business_id,customer_id,sender_id,message,created_at) VALUES(?,?,?,?,?)",(bid,customer_id,u["id"],body,now()))
                        if u["role"]=="customer":
                            c.execute("INSERT INTO enquiries(business_id,customer_id,message,created_at) VALUES(?,?,?,?)",(bid,customer_id,body,now()))
                    recipient_id = int(biz["user_id"]) if int(biz["user_id"] or 0) != int(u["id"]) else int(customer_id)
                try:
                    fcm_send_async(recipient_id, "Skillvaya message", (u.get("name") or "Your contact") + ": " + body,
                                   {"type":"message","business_id":bid,"customer_id":customer_id})
                except Exception:
                    pass
                return self.sendj({"ok":True},201)
            if path=="/api/complaints":
                u=self.require("customer"); bid=int(d.get("business_id",0)); reason=d.get("reason","").strip()
                if not reason:return self.sendj({"error":"Please describe the complaint."},400)
                with conn() as c:
                    if not c.execute("SELECT id FROM businesses WHERE id=?",(bid,)).fetchone():return self.sendj({"error":"Business not found."},404)
                    c.execute("INSERT INTO complaints(business_id,customer_id,reason,created_at,priority) VALUES(?,?,?,?,?)",(bid,u["id"],reason,now(),"high" if any(w in reason.lower() for w in ["deposit","stole","threat","fraud","ran away","unsafe"]) else "normal",))
                notify("complaint","New business report submitted","Business ID: "+str(bid)+"; customer ID: "+str(u["id"])+"; report: "+reason)
                return self.sendj({"ok":True},201)
            if path=="/api/bank-transfer":
                u=self.require("provider"); plan=d.get("plan"); billing=d.get("billing")
                return self.sendj({"error":SV_PLAY_ONLY,"play_only":True},410)  # SV82-PLAY-ONLY
                if plan not in PLANS or billing not in ("monthly","yearly"): return self.sendj({"error":"Choose a valid plan and billing term."},400)
                if u.get("role")=="admin": return self.sendj({"error":"Owner accounts already have free access."},400)
                amount=PLANS[plan]["monthly"]*(11 if billing=="yearly" else 1)
                ref="BT-SV-"+secrets.token_hex(5).upper()
                with conn() as c:
                    b=c.execute("SELECT id FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    c.execute("INSERT INTO payments(user_id,business_id,plan,billing,amount,reference,created_at) VALUES(?,?,?,?,?,?,?)",(u["id"],b["id"] if b else None,plan,billing,amount,ref,now()))
                body="A provider requested bank-transfer payment. Provider: "+u.get("email","")+"; user ID: "+str(u["id"])+"; plan: "+str(plan)+"; billing: "+str(billing)+"; amount: R"+str(amount)+"; unique reference: "+ref+". Check the Capitec account and confirm only after funds are received."
                notify("bank_transfer_pending","Bank transfer awaiting confirmation",body,setting("owner_email"))
                return self.sendj({"ok":True,"reference":ref,"amount":amount,"status":"pending","payment_method":"bank_transfer","bank":{"name":"Capitec Bank","account_holder":"A M Kaspersen","account_number":"1454116380"},"message":"Transfer the exact amount and use the unique reference. Your subscription remains pending until the owner confirms the funds have cleared."},201)
            if path=="/api/payments":
                return self.sendj({"error":"PayFast checkout is paused. PayPal is the only supported checkout provider; use the PayPal checkout option in Skillvaya."},410)
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
                        c.execute("UPDATE owner_promotions SET directory_business_id=? WHERE id=?",(directory_id,promotion_id))
                return self.sendj({"ok":True,"id":promotion_id,"directory_business_id":directory_id,"owner_free":True,"payment_required":False},201)
            if path.startswith("/api/admin/account-deletion-requests/") and path.endswith("/complete"):
                self.require("admin")
                try: request_id=int(path.split("/")[-2])
                except (ValueError,TypeError): return self.sendj({"error":"Invalid deletion request ID."},400)
                with conn() as c:
                    req=c.execute("SELECT id,user_id,status FROM account_deletion_requests WHERE id=?",(request_id,)).fetchone()
                    if not req: return self.sendj({"error":"Deletion request not found."},404)
                    if req["status"]!="pending": return self.sendj({"error":"This deletion request is not pending."},409)
                    target=c.execute("SELECT id,name,email,role FROM users WHERE id=?",(req["user_id"],)).fetchone()
                    if not target:
                        c.execute("UPDATE account_deletion_requests SET status='completed',user_email='',reason='',reviewed_at=?,review_notes='Account was already absent; request closed.' WHERE id=?",(now(),request_id))
                        return self.sendj({"ok":True,"message":"Account was already absent; request closed.","acknowledgement_email_sent":False})
                    if target["role"]=="admin": return self.sendj({"error":"Owner/admin accounts cannot be deleted through this workflow."},403)
                    deleted_email=str(target["email"] or ""); deleted_name=str(target["name"] or "Skillvaya customer")
                    result=delete_account_data(c,int(req["user_id"]),request_id=request_id)
                email_sent=send_owner_email("Account deletion completed","Hello "+deleted_name+",\n\nSkillvaya has completed your verified account-deletion request #"+str(request_id)+". Your account and associated app personal data have been deleted. Limited payment/accounting or security records may be retained where required by law; external payment-provider records may be governed separately.\n\nFor questions, contact skillvaya@gmail.com.\n\nSkillvaya",deleted_email) if deleted_email else False
                return self.sendj({"ok":True,"request_id":request_id,"message":"Account and associated Skillvaya data were deleted. Minimized payment records may be retained where required.","details":result,"acknowledgement_email_sent":bool(email_sent)})
            if path.startswith("/api/admin/accounts/") and path.endswith("/access"):
                self.require("admin")
                try: account_id=int(path.split("/")[-2])
                except (ValueError,TypeError): return self.sendj({"error":"Invalid account ID."},400)
                action=str(d.get("action","")).strip().lower()
                reason=str(d.get("reason","")).strip()[:1000]
                if action not in ("suspend","restore"): return self.sendj({"error":"Choose suspend or restore."},400)
                if action=="suspend" and len(reason)<3: return self.sendj({"error":"A reason of at least 3 characters is required for suspension."},400)
                actor=self.require("admin")
                with conn() as c:
                    c.execute("CREATE TABLE IF NOT EXISTS owner_account_access (user_id BIGINT PRIMARY KEY, original_role TEXT NOT NULL, suspended_at TEXT NOT NULL)")
                    row=c.execute("SELECT id,name,email,role FROM users WHERE id=?",(account_id,)).fetchone()
                    if not row: return self.sendj({"error":"Account not found."},404)
                    if row["role"]=="admin": return self.sendj({"error":"Owner/admin accounts are protected from suspension."},403)
                    if action=="suspend":
                        if row["role"]=="suspended": return self.sendj({"ok":True,"message":"Account is already suspended."})
                        if row["role"] not in ("customer","provider"): return self.sendj({"error":"Only customer/provider accounts can be suspended."},400)
                        c.execute("INSERT INTO owner_account_access(user_id,original_role,suspended_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET original_role=excluded.original_role,suspended_at=excluded.suspended_at",(account_id,row["role"],now()))
                        c.execute("UPDATE users SET role='suspended' WHERE id=?",(account_id,))
                        c.execute("DELETE FROM auth_sessions WHERE user_id=?",(account_id,))
                        action_message="ACCOUNT SUSPENDED: "+str(row["name"])+" <"+str(row["email"])+"> (ID "+str(account_id)+"). Reason: "+reason+". Actor: "+str(actor.get("email","admin"))+". Active sessions revoked; account and payment records preserved."
                        c.execute("INSERT INTO notifications(kind,subject,body,status,created_at,recipient) VALUES(?,?,?,?,?,?)",("account_moderation","Account suspended",action_message,"recorded",now(),setting("owner_email")))
                        return self.sendj({"ok":True,"message":"Account suspended and active sessions revoked. Reason recorded in the owner inbox."})
                    prior=c.execute("SELECT original_role FROM owner_account_access WHERE user_id=?",(account_id,)).fetchone()
                    if row["role"]!="suspended" or not prior: return self.sendj({"error":"No recorded suspension exists for this account."},400)
                    if prior["original_role"] not in ("customer","provider"): return self.sendj({"error":"Stored original role is invalid; account was not changed."},409)
                    c.execute("UPDATE users SET role=? WHERE id=?",(prior["original_role"],account_id))
                    c.execute("DELETE FROM owner_account_access WHERE user_id=?",(account_id,))
                    action_message="ACCOUNT ACCESS RESTORED: "+str(row["name"])+" <"+str(row["email"])+"> (ID "+str(account_id)+"). Actor: "+str(actor.get("email","admin"))+"."
                    c.execute("INSERT INTO notifications(kind,subject,body,status,created_at,recipient) VALUES(?,?,?,?,?,?)",("account_moderation","Account access restored",action_message,"recorded",now(),setting("owner_email")))
                return self.sendj({"ok":True,"message":"Account access restored. The user can sign in again; the decision was recorded."})
            if path.startswith("/api/admin/owner-promotions/"):
                owner=self.require("admin")
                try: pid=int(path.rsplit("/",1)[1])
                except ValueError: return self.sendj({"error":"Invalid promotion ID."},400)
                if str(d.get("action","")).strip().lower()=="update":
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
                        old=c.execute("SELECT * FROM owner_promotions WHERE id=?",(pid,)).fetchone()
                        if not old: return self.sendj({"error":"Promotion not found."},404)
                        directory_id=old["directory_business_id"]
                        if old["kind"]=="business" and kind!="business" and directory_id:
                            c.execute("UPDATE businesses SET status='removed' WHERE id=?",(directory_id,))
                            directory_id=None
                        if kind=="business" and not directory_id:
                            directory_id=c.execute("INSERT INTO businesses(user_id,name,category,area,phone,whatsapp,email,website,description,photos,plan,billing,status,payment_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,'local','monthly',?,'verified',?) RETURNING id",(owner["id"],business_name,category,str(d.get("area","South Africa")).strip()[:120] or "South Africa",str(d.get("phone","")).strip()[:40],str(d.get("whatsapp","")).strip()[:40] or str(d.get("phone","")).strip()[:40],str(d.get("contact_email","")).strip().lower()[:254] or owner.get("email",""),target_url,description,image_url,{"active":"active","paused":"suspended","removed":"removed"}.get(old["status"],"active"),now())).fetchone()["id"]
                        elif kind=="business" and directory_id:
                            c.execute("UPDATE businesses SET name=?,category=?,area=?,phone=?,whatsapp=?,email=?,website=?,description=?,photos=?,status=? WHERE id=?",(business_name,category,str(d.get("area","South Africa")).strip()[:120] or "South Africa",str(d.get("phone","")).strip()[:40],str(d.get("whatsapp","")).strip()[:40] or str(d.get("phone","")).strip()[:40],str(d.get("contact_email","")).strip().lower()[:254] or owner.get("email",""),target_url,description,image_url,{"active":"active","paused":"suspended","removed":"removed"}.get(old["status"],"active"),directory_id))
                        c.execute("UPDATE owner_promotions SET kind=?,business_name=?,title=?,category=?,description=?,target_url=?,image_url=?,directory_business_id=?,updated_at=? WHERE id=?",(kind,business_name,title,category,description,target_url,image_url,directory_id,now(),pid))
                    return self.sendj({"ok":True,"id":pid,"directory_business_id":directory_id,"status":old["status"],"owner_free":True,"payment_required":False})
                status=str(d.get("status","")).strip().lower()
                if status not in ("active","paused","removed"): return self.sendj({"error":"Invalid status."},400)
                with conn() as c:
                    row=c.execute("SELECT directory_business_id FROM owner_promotions WHERE id=?",(pid,)).fetchone()
                    if not row: return self.sendj({"error":"Promotion not found."},404)
                    c.execute("UPDATE owner_promotions SET status=?,updated_at=? WHERE id=?",(status,now(),pid))
                    if row["directory_business_id"]:
                        directory_status={"active":"active","paused":"suspended","removed":"removed"}[status]
                        c.execute("UPDATE businesses SET status=? WHERE id=?",(directory_status,row["directory_business_id"]))
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
                capture_id=row["paypal_capture_id"] or (row["pf_payment_id"] if row["payment_gateway"]=="paypal" and not str(row["reference"]).startswith("BT-SV-") else None)
                if str(row["reference"]).startswith("BT-SV-"):
                    return self.sendj({"error":"Bank-transfer refunds must be handled separately through the bank, not through PayPal."},400)
                if row["status"]!="verified" or row["payment_gateway"]!="paypal" or not capture_id:
                    return self.sendj({"error":"Only PayPal-confirmed captures can be refunded."},400)
                if row["refund_status"]=="pending":
                    return self.sendj({"error":"A PayPal refund is already pending. Do not submit a duplicate."},409)
                if amount+int(row["refunded_amount"] or 0)>int(row["amount"])*100:
                    return self.sendj({"error":"Refund exceeds the remaining amount paid."},400)
                # SV81-WORLD: refund in the currency PayPal actually charged, in proportion to the rand amount.
                _pcur=str((row["paypal_currency"] if "paypal_currency" in row.keys() else "") or "USD").upper()
                try: _paid=float(row["paypal_amount"] or 0)
                except (TypeError,ValueError): _paid=0.0
                if _paid<=0: return self.sendj({"error":"This payment has no recorded PayPal amount, so the refund cannot be calculated here. Refund it in PayPal directly."},400)
                _dec=0 if _pcur in SV_ZERO_DECIMAL else 2
                payload={"amount":{"value":format(round(_paid*amount/(int(row["amount"])*100),_dec),"."+str(_dec)+"f"),"currency_code":_pcur},"note_to_payer":reason}
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
                        if not str(row["reference"]).startswith("BT-SV-"):
                            return self.sendj({"error":"PayPal payments must be confirmed by a valid PayPal capture. Manual confirmation is only allowed for bank-transfer references."},409)
                        activate_payment(c,row,"BANK-TRANSFER:"+row["reference"])
                        return self.sendj({"ok":True,"status":"verified","payment_method":"bank_transfer"})
                return self.sendj({"error":"Not found"},404)
            return self.sendj({"error":"Not found"},404)
        except PermissionError as e: return self.sendj({"error":str(e)},401)
        except Exception as e: return self.sendj({"error":str(e)},400)
def main():
    init()
    print("Skillvaya database initialized; starting HTTP server",flush=True)
    # Off the startup path so the HTTP port binds immediately (Render detects it); indexes build in the background.
    threading.Thread(target=ensure_performance_indexes,name="skillvaya-indexes",daemon=True).start()
    if "fcm_prewarm" in globals(): threading.Thread(target=fcm_prewarm,name="skillvaya-fcm-prewarm",daemon=True).start()
    # Subscription expiry can send multiple SMTP notifications. Run it off the
    # startup path so Render can detect the bound HTTP port immediately.
    def expiry_loop():
        while True:
            try: expire_subscriptions()
            except Exception as e: print("Subscription expiry check failed:",e,flush=True)
            try: evaluate_provider_automation_due()
            except Exception as e: print("Provider automation check failed:",e,flush=True)
            threading.Event().wait(3600)
    threading.Thread(target=expiry_loop,daemon=True).start()
    server=ThreadingHTTPServer((HOST,PORT),Handler)
    print("Skillvaya server listening on %s:%d"%(HOST,PORT),flush=True)
    server.serve_forever()
if __name__=="__main__": main()
