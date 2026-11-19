"""FCV-01: prove a phone number with ONE normal SMS sent from the person's own SIM (owner 2026-11-19).

The app opens the person's SMS app with a short code (e.g. "FC 482913") addressed to the Future Chat
verification number. They tap Send and pay for one normal SMS. A small forwarder app on the phone that owns
the verification number passes every SMS that contains an FC code to /api/fcv/inbox. The server sees which
number the SMS really came from, so the person must have that SIM in their hand. No SMS company, no fees.

Methods on users.phone_verify_method: 'sim' (this), 'sms' (Firebase) and '' (old SMS) are CONFIRMED.
'self' (typed in only) and 'email' are not: a confirmed number takes the number back from them.
Routes: POST /api/fcv/start, POST /api/fcv/inbox (forwarder only), GET /api/fcv/status.
"""
import datetime, hashlib, hmac, os, re, secrets

A = None
# The Future Chat verification number (the SIM in the forwarder phone).
NUMBER = os.environ.get("FCV_NUMBER", "+27837874569").strip()
# sha256 of the forwarder's private key. The key itself only lives inside the forwarder APK on the owner's phone.
KEY_SHA256 = os.environ.get("FCV_KEY_SHA256", "9652551390483254cef0821de0d7d2c8ed4ca498d69390431790453c3dc9a35f").strip().lower()
CODE_MINUTES = 30
CODE_RE = re.compile(r"\bFC[\s\-]?(\d{6})\b", re.I)


def on():
    return os.environ.get("FCV_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on") and bool(NUMBER)   # FCV-03: off -> email codes


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)


def init(c):
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS fcv_codes(code TEXT PRIMARY KEY, user_id BIGINT NOT NULL, phone TEXT NOT NULL, created_at TEXT NOT NULL,
            done_at TEXT NOT NULL DEFAULT '', got_from TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS idx_fcv_codes_user ON fcv_codes(user_id);
        CREATE TABLE IF NOT EXISTS fcv_state(k TEXT PRIMARY KEY, v TEXT NOT NULL);
    """)


def pretty(e164):
    """+27837874569 -> 083 787 4569 (other countries stay in + form)."""
    e = str(e164 or "")
    if e.startswith("+27") and len(e) == 12: d = "0" + e[3:]; return "%s %s %s" % (d[:3], d[3:6], d[6:])
    return e


def confirmed_holder(c, phone, not_uid=0):
    """Another account that has PROVEN this number (by SIM SMS or Firebase SMS)."""
    return c.execute("SELECT id FROM users WHERE phone_e164=? AND phone_verified_at<>'' AND id<>? AND role<>'suspended' "
                     "AND COALESCE(phone_verify_method,'')<>'self'", (phone, int(not_uid or 0))).fetchone()   # FCV-03: email counts


def is_confirmed(row):
    return bool(row and row["phone_verified_at"] and str(row["phone_verify_method"] or "") != "self")   # FCV-03: email-confirmed counts


def _expired(created):
    try: return datetime.datetime.fromisoformat(str(created)) < datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=CODE_MINUTES)
    except ValueError: return True


def _start(h, u, d):
    uid = int(u["id"])
    with A.conn() as c:
        r = c.execute("SELECT phone,phone_e164,country FROM users WHERE id=?", (uid,)).fetchone()
        raw = str(d.get("phone") or "").strip() or (r["phone_e164"] or r["phone"] or "")
        phone = A.FC.normalize_phone(raw, (r["country"] or "ZA") if r else "ZA")
        if not phone: return h.sendj({"error": "Enter your full phone number, e.g. 082 123 4567."}, 400)
        if confirmed_holder(c, phone, uid):
            return h.sendj({"error": "This phone number already has a Future Chat account. Sign in to that account instead.", "phone_taken": True}, 409)
        old = c.execute("SELECT code,created_at,phone FROM fcv_codes WHERE user_id=? AND done_at='' ORDER BY created_at DESC LIMIT 1", (uid,)).fetchone()
        if old and old["phone"] == phone and not _expired(old["created_at"]):
            code = old["code"]                     # same number again: keep the same code (an SMS may already be on its way)
        else:
            c.execute("DELETE FROM fcv_codes WHERE user_id=? AND done_at=''", (uid,))
            for _ in range(20):
                code = "%06d" % secrets.randbelow(1000000)
                if not c.execute("SELECT 1 FROM fcv_codes WHERE code=?", (code,)).fetchone(): break
            c.execute("INSERT INTO fcv_codes(code,user_id,phone,created_at) VALUES(?,?,?,?)", (code, uid, phone, A.now()))
        c.execute("UPDATE users SET phone=? WHERE id=? AND COALESCE(phone_e164,'')=''", (phone, uid))
    body = "Future Chat code FC %s" % code
    return h.sendj({"ok": True, "phone": phone, "code": "FC " + code, "to": NUMBER, "to_pretty": pretty(NUMBER), "body": body,
                    "minutes": CODE_MINUTES})


def _key_ok(h, d):
    k = str(h.headers.get("X-FCV-Key") or d.get("key") or "").strip()
    return bool(k) and hmac.compare_digest(hashlib.sha256(k.encode()).hexdigest(), KEY_SHA256)


def confirm(c, code, sender):
    """One SMS arrived. Returns (ok, message). Safe to call twice with the same SMS."""
    row = c.execute("SELECT * FROM fcv_codes WHERE code=?", (code,)).fetchone()
    if not row: return False, "unknown code"
    if row["done_at"]: return True, "already done"
    if _expired(row["created_at"]): return False, "code expired"
    uid = int(row["user_id"])
    u = c.execute("SELECT country FROM users WHERE id=?", (uid,)).fetchone()
    phone = A.FC.normalize_phone(sender, (u["country"] if u else "") or "ZA")
    if not phone: return False, "sender number not readable"
    # The SMS proves the number it came FROM. Usually that's the number they typed; if they sent it from
    # another SIM, that other number is the one they've proven.
    if confirmed_holder(c, phone, uid): return False, "number already belongs to another account"
    c.execute("UPDATE users SET phone_e164='',phone_verified_at='',phone_verify_method='' WHERE phone_e164=? AND id<>? "
              "AND (phone_verified_at='' OR COALESCE(phone_verify_method,'') IN ('self','email'))", (phone, uid))
    c.execute("UPDATE users SET phone=?,phone_e164=?,phone_verified_at=?,phone_verify_method='sim' WHERE id=?", (phone, phone, A.now(), uid))
    c.execute("UPDATE fcv_codes SET done_at=?,got_from=? WHERE code=?", (A.now(), phone, code))
    return True, "verified"


def _inbox(h, d):
    if not _key_ok(h, d): return h.sendj({"error": "Not allowed."}, 403)
    sender = str(d.get("from") or "")[:40]; body = str(d.get("body") or "")[:600]
    with A.conn() as c:
        c.execute("INSERT INTO fcv_state(k,v) VALUES('last_seen',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (A.now(),))
        m = CODE_RE.search(body)
        if not m: return h.sendj({"ok": True, "ignored": True})
        ok, why = confirm(c, m.group(1), sender)
    return h.sendj({"ok": ok, "result": why})


def handle_post(h, path, d):
    d = d or {}
    if path == "/api/fcv/inbox": return _inbox(h, d)
    if path == "/api/fcv/ping":
        if not _key_ok(h, d): return h.sendj({"error": "Not allowed."}, 403)
        with A.conn() as c: c.execute("INSERT INTO fcv_state(k,v) VALUES('last_seen',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (A.now(),))
        return h.sendj({"ok": True})
    u = h.require()
    if path == "/api/fcv/start": return _start(h, u, d)
    return h.sendj({"error": "Not found"}, 404)


def handle_get(h, path):
    u = h.require(); uid = int(u["id"])
    if path == "/api/fcv/status":
        with A.conn() as c:
            r = c.execute("SELECT phone,phone_e164,phone_verified_at,phone_verify_method FROM users WHERE id=?", (uid,)).fetchone()
            seen = c.execute("SELECT v FROM fcv_state WHERE k='last_seen'").fetchone()
            out = {"confirmed": is_confirmed(r), "phone": (r["phone_e164"] or r["phone"] or "") if r else "", "method": (r["phone_verify_method"] or "") if r else ""}
            if str(u.get("role") if hasattr(u, "get") else u["role"]) == "admin": out["forwarder_last_seen"] = seen["v"] if seen else ""
        return h.sendj(out)
    return h.sendj({"error": "Not found"}, 404)
