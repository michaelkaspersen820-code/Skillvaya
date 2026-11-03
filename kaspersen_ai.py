"""Kaspersen AI cloud brain for Kaspersen Pocket (KAI-20261102).

The phone app never holds the AI provider keys. It signs in with a Skillvaya / Future Chat account and sends its
chat request here; this server adds the key, forwards it to the GLM-5.3 provider and counts usage per account.

Routes (app.py dispatches /api/kai/* here):
  POST /api/kai/chat/completions  OpenAI-style chat request (signed-in, phone-verified accounts)
  GET  /api/kai/status            usage today, limits, whether the number is confirmed
  POST /api/kai/keys              store provider keys; must be signed by the owner's PC (Ed25519)
  PC Link (PCLINK-20261102) - the owner's phone uses his Windows PC through this relay:
  POST /api/kai/pc/job            owner account queues a PC job {kind, args}
  GET  /api/kai/pc/job?id=...     owner account reads the job's status/result
  GET  /api/kai/pc/status         is the PC online
  POST /api/kai/pc/poll           the PC collects jobs (long-poll); signed by the PC's key
  POST /api/kai/pc/result         the PC returns a result; signed by the PC's key
  Jobs live only in memory (nothing stored in the database, so polling costs no database time).

Keys come from environment variables (KASPERSEN_OPENROUTER_KEY, KASPERSEN_VERCEL_KEY, KASPERSEN_ORCA_KEY) or,
when those are absent, from the kai_secrets table filled through /api/kai/keys. Nothing secret lives in this file.
"""
import base64, datetime, hashlib, json, os, secrets, threading, time, urllib.error, urllib.parse, urllib.request

A = None
# Public half of the owner's signing key. Only the matching private key (kept on the owner's PC) can set keys.
ADMIN_PUBKEY = "vl6jF7ls6Nxonwurmz9MRQfN/x4Jib86DJyEarJYVwM="
PROVIDERS = [  # name, endpoint, model, env var, secret name
    ("OrcaRouter", "https://api.orcarouter.ai/v1/chat/completions", "z-ai/glm-5.3-flash-free", "KASPERSEN_ORCA_KEY", "orca"),
    ("OpenRouter", "https://openrouter.ai/api/v1/chat/completions", "z-ai/glm-5.3-flash", "KASPERSEN_OPENROUTER_KEY", "openrouter"),
    ("Vercel", "https://ai-gateway.vercel.sh/v1/chat/completions", "zai/glm-5.3-flash", "KASPERSEN_VERCEL_KEY", "vercel"),
]
MAX_TOKENS = 8000
# FREECHAIN-20261102: when the paid model fails (or the credit runs out) Kaspersen keeps working on OpenRouter's free
# models, one after another. The list is refreshed from OpenRouter every 6 hours (free models that can use tools),
# preferred ones first; models that refuse us are skipped for a day.
FREE_PREFERRED = ["nvidia/nemotron-3.5-super-vl:free", "nvidia/nemotron-3.5-lightning:free", "dots-studio/dots-3-note-preview:free",
                  "google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                  "nvidia/nemotron-3-ultra-550b-a55b:free"]  # tested 2 Nov 2026: fastest first, Ultra works but is slow
FREE_URL = "https://openrouter.ai/api/v1/chat/completions"
FREE_MAX = 5           # free models tried per request (each answers in a few seconds or fails fast)
_free = {"at": 0.0, "ids": list(FREE_PREFERRED), "vision": set()}
_bad = {}              # model id -> skip until (refused / not allowed)
_cool = {}
_cache = {"at": 0.0, "keys": {}}
_lock = threading.Lock()


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items():
        setattr(A, k, v)


def init(c):
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS kai_usage(user_id BIGINT NOT NULL, day TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
            tokens BIGINT NOT NULL DEFAULT 0, PRIMARY KEY(user_id, day));
        CREATE TABLE IF NOT EXISTS kai_secrets(name TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS kai_subs(user_id BIGINT PRIMARY KEY, paid_until TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '',
            trial_tasks INTEGER NOT NULL DEFAULT 0, trial_calls INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS kai_proofs(id %s, user_id BIGINT NOT NULL, created_at TEXT NOT NULL DEFAULT '', sha TEXT NOT NULL DEFAULT '',
            image TEXT NOT NULL DEFAULT '', amount REAL NOT NULL DEFAULT 0, months INTEGER NOT NULL DEFAULT 0, reference TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '', seen INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_kai_proofs_user ON kai_proofs(user_id);
        CREATE INDEX IF NOT EXISTS idx_kai_proofs_sha ON kai_proofs(sha);
    """ % (A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")))
    pk = A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS kai_pc_devices(id %s, user_id BIGINT NOT NULL, name TEXT NOT NULL DEFAULT '',
            token_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT '');
        CREATE UNIQUE INDEX IF NOT EXISTS idx_kai_pc_token ON kai_pc_devices(token_hash);
        CREATE INDEX IF NOT EXISTS idx_kai_pc_user ON kai_pc_devices(user_id);
    """ % pk)


def _env_int(name, default):
    try: return int(os.environ.get(name, "") or default)
    except ValueError: return default


def _today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=2)).strftime("%Y-%m-%d")  # South Africa day


def _unlimited(u):
    emails = os.environ.get("KASPERSEN_UNLIMITED_EMAILS", "michaelkaspersen820@gmail.com,mikekas92@gmail.com,kaspersenai@gmail.com")
    return u.get("role") == "admin" or str(u.get("email", "")).lower() in {e.strip().lower() for e in emails.split(",") if e.strip()}


def _keys():
    if time.time() - _cache["at"] < 60:
        return _cache["keys"]
    keys = {}
    try:
        with A.conn() as c:
            for r in c.execute("SELECT name,value FROM kai_secrets").fetchall():
                keys[r["name"]] = r["value"]
    except Exception as e:
        print("Kaspersen keys unavailable:", type(e).__name__)
    for _n, _u, _m, env, sec in PROVIDERS:
        if os.environ.get(env, "").strip():
            keys[sec] = os.environ[env].strip()
    _cache.update(at=time.time(), keys=keys)
    return keys


def _free_models():
    if time.time() - _free["at"] > 6 * 3600:
        _free["at"] = time.time()
        try:
            with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=20) as r:
                data = json.loads(r.read()).get("data") or []
            ok = {m["id"]: m for m in data if str(m.get("id", "")).endswith(":free") and "tools" in (m.get("supported_parameters") or [])}
            ids = [i for i in FREE_PREFERRED if i in ok] + sorted([i for i in ok if i not in FREE_PREFERRED],
                                                                  key=lambda i: -(ok[i].get("context_length") or 0))
            if ids:
                _free["ids"] = ids
                _free["vision"] = {i for i in ids if "image" in ((ok[i].get("architecture") or {}).get("input_modalities") or [])}
        except Exception as e:
            print("Free model list refresh failed:", type(e).__name__)
    now = time.time()
    return [i for i in _free["ids"] if _bad.get(i, 0) < now]


def _text_only(msgs):
    """Free models without eyes get a note instead of the photo."""
    out = []
    for m in msgs:
        c = m.get("content")
        if isinstance(c, list):
            txt = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
            if any(isinstance(p, dict) and p.get("type") == "image_url" for p in c):
                txt += " [A photo was attached, but this backup brain can't see photos - say so if it matters.]"
            m = dict(m, content=txt.strip())
        out.append(m)
    return out


def _usage(uid, day):
    with A.conn() as c:
        r = c.execute("SELECT calls,tokens FROM kai_usage WHERE user_id=? AND day=?", (uid, day)).fetchone()
        tot = c.execute("SELECT COALESCE(SUM(calls),0) n FROM kai_usage WHERE day=? AND user_id>0", (day,)).fetchone()
    return (int(r["calls"]) if r else 0), (int(r["tokens"]) if r else 0), int(tot["n"] or 0)


def _count(uid, day, tokens):
    with A.conn() as c:
        c.execute("INSERT INTO kai_usage(user_id,day,calls,tokens) VALUES(?,?,1,?) ON CONFLICT(user_id,day) DO UPDATE SET "
                  "calls=kai_usage.calls+1, tokens=kai_usage.tokens+excluded.tokens", (uid, day, int(tokens or 0)))


# SUBS-20261103: Kaspersen customers pay R150 a month (Kaspersen is its own product - customers never see Skillvaya).
# New customers get 3 free test tasks (a task = one request, however many steps she takes). After that, or when a
# paid month runs out, she answers only with a polite pay message. The owner switches a customer on for a month by
# telling his own Kaspersen "X paid" (POST /api/kai/subs).
def _trial_tasks():
    return _env_int("KASPERSEN_TRIAL_TASKS", 3)


def _sub_row(uid):
    try:
        with A.conn() as c:
            r = c.execute("SELECT paid_until,trial_tasks,trial_calls FROM kai_subs WHERE user_id=?", (uid,)).fetchone()
        if r:
            return {"paid_until": r["paid_until"] or "", "trial_tasks": int(r["trial_tasks"] or 0), "trial_calls": int(r["trial_calls"] or 0)}
    except Exception as e:
        print("kai_subs read failed:", type(e).__name__)
    return {"paid_until": "", "trial_tasks": 0, "trial_calls": 0}


def _paid_until(uid):
    return _sub_row(uid)["paid_until"]


def _price():
    return os.environ.get("KASPERSEN_PRICE", "R150")


def _pay_contact():
    return os.environ.get("KASPERSEN_PAY_CONTACT", "27837874569")


def _bank():
    return os.environ.get("KASPERSEN_BANK_DETAILS", "").strip()


def _pay_how():
    if os.environ.get("KASPERSEN_PAY_HOW"):
        return os.environ["KASPERSEN_PAY_HOW"]
    if _bank():
        return "Pay %s into this account: %s. Then send me a screenshot of your proof of payment and I'll switch on straight away." % (_price(), _bank())
    return "Tap Pay for the payment details, pay %s, then send me a screenshot of your proof of payment and I'll switch on straight away." % _price()


def _price_num():
    try: return float("".join(ch for ch in _price() if ch.isdigit() or ch == ".") or 150)
    except ValueError: return 150.0


def _sub_state(uid, unl):
    r = _sub_row(uid); today = _today()
    paid = unl or r["paid_until"] >= today
    left = max(0, _trial_tasks() - r["trial_tasks"])
    return {"subscribed": paid, "unlimited": unl, "paid_until": r["paid_until"], "trial_tasks": _trial_tasks(),
            "trial_left": 0 if r["paid_until"] else left, "price": _price(), "pay_contact": _pay_contact(), "pay_how": _pay_how(), "bank": _bank()}


def _paywall(uid, unl, new_task):
    """None when this account may use Kaspersen now, else (json, 402)."""
    if unl:
        return None
    r = _sub_row(uid); today = _today()
    if r["paid_until"] >= today:
        return None
    ended = bool(r["paid_until"])          # a paid month that ran out: no second trial
    trial_over = ended or r["trial_tasks"] >= _trial_tasks()
    if (new_task and trial_over) or r["trial_calls"] >= _trial_tasks() * 60:
        msg = ("Your Kaspersen month ended on %s. " % r["paid_until"] if ended else "Your 3 free test tasks are used up. ") + \
              "I'm sorry - you'll need to make the payment for this month (%s) before I can do anything for you. " % _price() + _pay_how()
        return ({"error": msg, "subscription": True, "paywall": True, "message": msg, "price": _price(),
                 "pay_contact": _pay_contact(), "paid_until": r["paid_until"]}, 402)
    return None


def _trial_count(uid, unl, new_task):
    """After a successful answer: count the trial task (first call of a request) and the call. Returns tasks left."""
    if unl:
        return None
    r = _sub_row(uid)
    if r["paid_until"] >= _today():
        return None
    try:
        with A.conn() as c:
            c.execute("INSERT INTO kai_subs(user_id,updated_at,trial_tasks,trial_calls) VALUES(?,?,?,1) ON CONFLICT(user_id) DO UPDATE SET "
                      "trial_tasks=kai_subs.trial_tasks+excluded.trial_tasks, trial_calls=kai_subs.trial_calls+1", (uid, _today(), 1 if new_task else 0))
    except Exception as e:
        print("kai_subs count failed:", type(e).__name__)
    return max(0, _trial_tasks() - r["trial_tasks"] - (1 if new_task else 0)) if not r["paid_until"] else 0


# PROOF-20261103: the customer sends Kaspersen a screenshot of their payment. She reads it; the server switches them on
# only when it really is a payment of at least the price, recent, (to the right account when KASPERSEN_PAY_TO is set),
# never seen before (same picture or same bank reference). Doubtful ones wait for the owner. Every proof reaches the
# owner's Kaspersen so he can check his bank and switch anyone off.
PROOF_PROMPT = ("You check proof-of-payment screenshots (South African bank apps, EFT, instant payment, PayShap, cash deposit, eWallet). "
                "Look ONLY at the picture. Reply with ONLY one JSON object, no other text: "
                '{"is_payment_proof": true/false, "amount_rand": number or null, "date": "YYYY-MM-DD" or null, "recipient": "who was paid (name/account) or empty", '
                '"reference": "payment reference or transaction id or empty", "status_text": "e.g. Successful / Pending / Failed / empty", '
                '"looks_edited": true/false, "notes": "one short sentence"}')


def _vision_check(b64):
    keys = _keys()
    order = [(n, u, m, sec) for n, u, m, _e, sec in PROVIDERS if keys.get(sec)]
    if keys.get("openrouter"):
        order += [("Free " + m, FREE_URL, m, "openrouter") for m in sorted(_free["vision"] or {"nvidia/nemotron-3.5-super-vl:free"})][:3]
    body = {"messages": [{"role": "user", "content": [{"type": "text", "text": PROOF_PROMPT},
                          {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}], "temperature": 0, "max_tokens": 600}
    for name, url, model, sec in order:
        try:
            req = urllib.request.Request(url, data=json.dumps(dict(body, model=model)).encode(), method="POST", headers={
                "Authorization": "Bearer " + keys[sec], "Content-Type": "application/json",
                "HTTP-Referer": "https://skillvaya.onrender.com", "X-Title": "Kaspersen Pocket"})
            with urllib.request.urlopen(req, timeout=90) as r:
                j = json.loads(r.read())
            t = (((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
            a, b = t.find("{"), t.rfind("}")
            if a >= 0 and b > a:
                return json.loads(t[a:b + 1])
        except Exception as e:
            print("proof check via %s failed: %s" % (name, type(e).__name__))
    return None


def _proof(h, d):
    u = h.require()
    uid = int(u["id"]); today = _today()
    b64 = str((d or {}).get("image") or "")
    if b64.startswith("data:"): b64 = b64.split(",", 1)[-1]
    if len(b64) < 2000:
        return h.sendj({"error": "Please send a clear screenshot of your proof of payment."}, 400)
    import hashlib
    sha = hashlib.sha256(b64.encode()).hexdigest()
    first = (u.get("name") or "").split(" ")[0] or "there"
    with A.conn() as c:
        if c.execute("SELECT COUNT(*) n FROM kai_proofs WHERE user_id=? AND created_at LIKE ?", (uid, today + "%")).fetchone()["n"] >= 6:
            return h.sendj({"ok": False, "message": "You've sent a few proofs today already. Michael will look at them and switch you on - you don't need to send more."})
        if c.execute("SELECT 1 FROM kai_proofs WHERE sha=?", (sha,)).fetchone():
            return h.sendj({"ok": False, "message": "I've already received this exact proof of payment before, so I can't use it again. If you made a new payment, please send the new proof."})
    v = _vision_check(b64) or {}
    price = _price_num()
    try: amount = float(v.get("amount_rand") or 0)
    except (TypeError, ValueError): amount = 0.0
    ref = str(v.get("reference") or "").strip()[:80]
    reasons = []
    if not v:
        reasons.append("I couldn't read the screenshot right now")
    elif not v.get("is_payment_proof"):
        status = "rejected"
    if v and v.get("is_payment_proof"):
        if amount < price - 0.5: reasons.append("the amount I can see is R%s, and Kaspersen is %s" % (("%.2f" % amount).rstrip("0").rstrip("."), _price()))
        dt = str(v.get("date") or "")
        try:
            age = (datetime.datetime.strptime(today, "%Y-%m-%d") - datetime.datetime.strptime(dt[:10], "%Y-%m-%d")).days
            if age > 10 or age < -1: reasons.append("the payment date (%s) isn't recent" % dt[:10])
        except ValueError:
            reasons.append("I can't see the payment date")
        st = str(v.get("status_text") or "").lower()
        if any(w in st for w in ("pending", "fail", "declin", "cancel", "reject")): reasons.append("the payment shows as '%s'" % v.get("status_text"))
        if v.get("looks_edited"): reasons.append("parts of the screenshot look edited")
        pay_to = os.environ.get("KASPERSEN_PAY_TO", "").strip().lower()
        if pay_to and not any(p.strip() and p.strip() in str(v.get("recipient") or "").lower() for p in pay_to.split(",")):
            reasons.append("I can't see that it was paid to Michael Kaspersen's account")
        if ref:
            with A.conn() as c:
                if c.execute("SELECT 1 FROM kai_proofs WHERE reference=? AND status IN ('auto_ok','confirmed','pending') AND ABS(amount-?)<1", (ref, amount)).fetchone():
                    reasons.append("this payment reference was already used")
        status = "pending" if reasons else "auto_ok"
    elif not v:
        status = "pending"
    months = max(1, min(12, int(amount // price))) if status == "auto_ok" else 0
    new = ""
    with A.conn() as c:
        c.execute("INSERT INTO kai_proofs(user_id,created_at,sha,image,amount,months,reference,status,reason,seen) VALUES(?,?,?,?,?,?,?,?,?,0)",
                  (uid, datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M"), sha, b64, amount, months, ref, status,
                   "; ".join(reasons) or (str(v.get("notes") or "")[:200] if v else "")))
        if status == "auto_ok":
            cur = _paid_until(uid)
            base = datetime.datetime.strptime(max(cur, today), "%Y-%m-%d")
            new = (base + datetime.timedelta(days=30 * months)).strftime("%Y-%m-%d")
            if c.execute("SELECT 1 FROM kai_subs WHERE user_id=?", (uid,)).fetchone():
                c.execute("UPDATE kai_subs SET paid_until=?, note=?, updated_at=? WHERE user_id=?", (new, "proof of payment R%g" % amount, today, uid))
            else:
                c.execute("INSERT INTO kai_subs(user_id,paid_until,note,updated_at) VALUES(?,?,?,?)", (uid, new, "proof of payment R%g" % amount, today))
    if status == "auto_ok":
        msg = ("Thank you, %s! I can see your payment of R%g - you're switched on until **%s**. " % (first, amount, new)) + \
              ("That covers %d months. " % months if months > 1 else "") + "What can I do for you?"
        return h.sendj({"ok": True, "active": True, "paid_until": new, "message": msg})
    if status == "rejected":
        return h.sendj({"ok": False, "message": "That doesn't look like a proof of payment to me. Please send a screenshot of the payment confirmation from your banking app (it shows the amount, the date and that it was successful)."})
    return h.sendj({"ok": False, "pending": True, "message": "Thank you, %s - I've received your proof of payment, but I can't confirm it myself because %s. I've sent it to Michael Kaspersen to check, and you'll be switched on as soon as he confirms." % (first, " and ".join(reasons) if reasons else "I couldn't read it clearly")})


def _proofs(h):
    u = h.require()
    if not _unlimited(u):
        return h.sendj({"error": "Only the owner can do this."}, 403)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    with A.conn() as c:
        if q.get("id"):
            r = c.execute("SELECT image FROM kai_proofs WHERE id=?", (int(q["id"][0]),)).fetchone()
            return h.sendj({"ok": bool(r), "image": r["image"] if r else ""})
        rows = c.execute("SELECT p.id,p.created_at,p.amount,p.months,p.reference,p.status,p.reason,p.seen,u.name,u.email,u.phone FROM kai_proofs p "
                         "JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 30").fetchall()
        unseen = [r for r in rows if not r["seen"]]
        if q.get("mark_seen"):
            c.execute("UPDATE kai_proofs SET seen=1 WHERE seen=0")
    return h.sendj({"ok": True, "unseen": len(unseen), "proofs": [{"id": r["id"], "when": r["created_at"], "name": r["name"], "email": r["email"], "phone": r["phone"],
                    "amount": r["amount"], "months": r["months"], "reference": r["reference"], "status": r["status"], "reason": r["reason"], "new": not r["seen"]} for r in rows]})


def _find_user(c, who):
    who = str(who or "").strip()
    if not who:
        return None
    if "@" in who:
        return c.execute("SELECT id,name,email,phone FROM users WHERE LOWER(email)=?", (who.lower(),)).fetchone()
    digits = "".join(ch for ch in who if ch.isdigit())
    if len(digits) >= 9:
        tail = digits[-9:]
        for r in c.execute("SELECT id,name,email,phone FROM users WHERE phone<>''").fetchall():
            if "".join(ch for ch in str(r["phone"]) if ch.isdigit()).endswith(tail):
                return r
        return None
    rows = c.execute("SELECT id,name,email,phone FROM users WHERE LOWER(name) LIKE ?", ("%" + who.lower() + "%",)).fetchall()
    return rows[0] if len(rows) == 1 else ("many" if rows else None)


def _subs(h, d):
    u = h.require()
    if not _unlimited(u):
        return h.sendj({"error": "Only the owner can do this."}, 403)
    with A.conn() as c:
        if d is None:   # list
            rows = c.execute("SELECT s.user_id,s.paid_until,s.note,s.trial_tasks,u.name,u.email,u.phone FROM kai_subs s JOIN users u ON u.id=s.user_id ORDER BY s.paid_until DESC, s.updated_at DESC").fetchall()
            today = _today()
            return h.sendj({"ok": True, "today": today, "price": _price(), "customers": [{"name": r["name"], "email": r["email"], "phone": r["phone"],
                            "paid_until": r["paid_until"], "active": r["paid_until"] >= today, "free_tasks_used": int(r["trial_tasks"] or 0), "note": r["note"]} for r in rows]})
        r = _find_user(c, d.get("who"))
        if r == "many":
            return h.sendj({"error": "More than one account matches that name - use their email or phone number."}, 400)
        if not r:
            return h.sendj({"error": "No Kaspersen account found for '" + str(d.get("who", "")) + "'. They must sign up in the Kaspersen app first."}, 404)
        uid = int(r["id"]); cur = _paid_until(uid); today = _today()
        try: months = max(-12, min(12, int(d.get("months", 1))))
        except (TypeError, ValueError): months = 1
        if months == 0:
            new = ""   # switch off now
        else:
            base = datetime.datetime.strptime(max(cur, today) if months > 0 else (cur or today), "%Y-%m-%d")
            new = (base + datetime.timedelta(days=30 * months)).strftime("%Y-%m-%d")
        note = str(d.get("note") or "")[:200]
        try:
            if months > 0: c.execute("UPDATE kai_proofs SET status='confirmed', seen=1 WHERE user_id=? AND status='pending'", (uid,))
            elif months == 0: c.execute("UPDATE kai_proofs SET status='revoked' WHERE user_id=? AND status='auto_ok'", (uid,))
        except Exception as e:
            print("kai_proofs settle failed:", type(e).__name__)
        if c.execute("SELECT 1 FROM kai_subs WHERE user_id=?", (uid,)).fetchone():
            c.execute("UPDATE kai_subs SET paid_until=?, note=?, updated_at=? WHERE user_id=?", (new, note, today, uid))
        else:
            c.execute("INSERT INTO kai_subs(user_id,paid_until,note,updated_at) VALUES(?,?,?,?)", (uid, new, note, today))
        return h.sendj({"ok": True, "name": r["name"], "email": r["email"], "paid_until": new, "active": new >= today if new else False})


def _phone_ok(uid):
    with A.conn() as c:
        r = c.execute("SELECT phone_verified_at FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and r["phone_verified_at"])


# ---------------------------------------------------------------- PC Link relay (multi-user)
# Every Kaspersen user can link their own Windows PC: the phone shows a pairing code, the person types it into
# "Kaspersen PC Link" on their PC, and that PC gets a device token. A phone's jobs only ever go to PCs linked to
# the same account. The owner's own PC may instead sign with the Ed25519 key (it serves the owner accounts).
# Jobs, queues and "last seen" live only in memory, so polling never touches the database.
PC = {"cv": threading.Condition(), "jobs": {}, "queues": {}, "seen": {}, "serves": {}, "last_ts": 0.0,
      "pair": {}, "tok": {}, "revoked": set(), "owner_ids": (0.0, []), "fails": {}}
OWNER_DEV = "owner-pc"
DOWNLOAD = "https://skillvaya.onrender.com/downloads/KaspersenPCLink.exe"
PAIR_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _pc_owner(u):
    emails = os.environ.get("KASPERSEN_PC_OWNERS", "michaelkaspersen820@gmail.com,mikekas92@gmail.com,kaspersenai@gmail.com")
    return u.get("role") == "admin" or str(u.get("email", "")).lower() in {e.strip().lower() for e in emails.split(",") if e.strip()}


def _owner_ids():
    at, ids = PC["owner_ids"]
    if time.time() - at < 600 and ids:
        return ids
    emails = [e.strip().lower() for e in os.environ.get("KASPERSEN_PC_OWNERS", "michaelkaspersen820@gmail.com,mikekas92@gmail.com,kaspersenai@gmail.com").split(",") if e.strip()]
    with A.conn() as c:
        rows = c.execute("SELECT id FROM users WHERE lower(email) IN (%s)" % ",".join("?" * len(emails)), emails).fetchall()
    ids = [int(r["id"]) for r in rows]
    PC["owner_ids"] = (time.time(), ids)
    return ids


def _verify(d, max_age=600):
    """Return the signed payload (dict) if it was signed by the owner's PC key, else None."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        payload = base64.b64decode(str(d.get("payload", "")))
        Ed25519PublicKey.from_public_bytes(base64.b64decode(ADMIN_PUBKEY)).verify(base64.b64decode(str(d.get("sig", ""))), payload)
        data = json.loads(payload)
        return data if abs(time.time() - float(data.get("ts", 0))) <= max_age else None
    except Exception:
        return None


def _hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


def _device_from_token(h):
    t = (h.headers.get("X-PC-Token") or "").strip()
    if len(t) < 20:
        return None
    th = _hash(t)
    hit = PC["tok"].get(th)
    if hit and hit[3] > time.time() and hit[0] not in PC["revoked"]:
        return hit
    with A.conn() as c:
        r = c.execute("SELECT id,user_id,name FROM kai_pc_devices WHERE token_hash=?", (th,)).fetchone()
    if not r:
        PC["tok"].pop(th, None)
        return None
    hit = ("d" + str(r["id"]), int(r["user_id"]), r["name"], time.time() + 900)
    PC["revoked"].discard(hit[0]); PC["tok"][th] = hit
    return hit


def _pc_auth(h, d):
    """Who is polling: (device id, [user ids it serves], payload) or None."""
    dev = _device_from_token(h)
    if dev:
        return dev[0], [dev[1]], d
    data = _verify(d, 120)
    if data:
        with PC["cv"]:
            if float(data["ts"]) <= PC["last_ts"]:
                return None
            PC["last_ts"] = float(data["ts"])
        return OWNER_DEV, _owner_ids(), data
    return None


def _online_for(uid):
    now = time.time()
    return [dv for dv, seen in PC["seen"].items() if now - seen < 60 and uid in PC["serves"].get(dv, [])]


def _pc_gc():
    now = time.time()
    for k in [k for k, j in PC["jobs"].items() if j["created"] < now - 900]:
        PC["jobs"].pop(k, None)
    for code in [c for c, v in PC["pair"].items() if v[1] < now]:
        PC["pair"].pop(code, None)


def _pc_post(h, path, d):
    if path == "/api/kai/pc/job":
        u = h.require(); uid = int(u["id"])
        kind = str(d.get("kind", ""))[:30]
        args = d.get("args") if isinstance(d.get("args"), dict) else {}
        if not kind:
            return h.sendj({"error": "No job."}, 400)
        if not _online_for(uid):
            with A.conn() as c:
                linked = c.execute("SELECT 1 FROM kai_pc_devices WHERE user_id=? LIMIT 1", (uid,)).fetchone()
            if not linked and not _pc_owner(u):
                return h.sendj({"error": "No computer is linked yet. In Kaspersen open Settings > Link my computer, then run Kaspersen PC Link on the PC and type the code.", "not_linked": True}, 409)
            return h.sendj({"error": "The computer is offline (switched off, asleep, or Kaspersen PC Link isn't running).", "offline": True}, 409)
        jid = secrets.token_hex(8)
        with PC["cv"]:
            _pc_gc()
            PC["jobs"][jid] = {"kind": kind, "args": args, "status": "queued", "result": None, "created": time.time(), "owner": uid}
            PC["queues"].setdefault(uid, []).append(jid)
            PC["cv"].notify_all()
        return h.sendj({"ok": True, "id": jid})
    if path == "/api/kai/pc/pair-code":
        u = h.require()
        code = "".join(secrets.choice(PAIR_ALPHABET) for _ in range(8))
        with PC["cv"]:
            _pc_gc()
            PC["pair"][code] = (int(u["id"]), time.time() + 600)
        return h.sendj({"ok": True, "code": code[:4] + "-" + code[4:], "expires_in": 600, "download": DOWNLOAD})
    if path == "/api/kai/pc/pair":
        ip = (h.headers.get("X-Forwarded-For") or h.client_address[0]).split(",")[0].strip()
        f = [t for t in PC["fails"].get(ip, []) if t > time.time() - 600]
        if len(f) >= 15:
            return h.sendj({"error": "Too many wrong codes. Wait 10 minutes and try again."}, 429)
        code = "".join(ch for ch in str(d.get("code", "")).upper() if ch.isalnum())
        with PC["cv"]:
            _pc_gc()
            hit = PC["pair"].pop(code, None)
        if not hit:
            PC["fails"][ip] = f + [time.time()]
            return h.sendj({"error": "That code is wrong or has expired. Get a new one in Kaspersen: Settings > Link my computer."}, 400)
        uid = hit[0]; token = secrets.token_urlsafe(32)
        name = " ".join(str(d.get("name") or "My PC").split())[:60]
        with A.conn() as c:
            c.execute("INSERT INTO kai_pc_devices(user_id,name,token_hash,created_at) VALUES(?,?,?,?)", (uid, name, _hash(token), A.now()))
            r = c.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
        return h.sendj({"ok": True, "token": token, "account": (r["name"] if r else "") or ""})
    if path == "/api/kai/pc/unlink":
        u = h.require()
        did = str(d.get("id", "")).lstrip("d")
        with A.conn() as c:
            c.execute("DELETE FROM kai_pc_devices WHERE id=? AND user_id=?", (int(did) if did.isdigit() else -1, int(u["id"])))
        PC["revoked"].add("d" + did); PC["seen"].pop("d" + did, None)
        return h.sendj({"ok": True})
    if path == "/api/kai/pc/forget":   # the PC unlinks itself (button in PC Link)
        dev = _device_from_token(h)
        if not dev:
            return h.sendj({"ok": True})
        with A.conn() as c:
            c.execute("DELETE FROM kai_pc_devices WHERE id=?", (int(dev[0][1:]),))
        PC["revoked"].add(dev[0]); PC["seen"].pop(dev[0], None)
        return h.sendj({"ok": True})
    if path == "/api/kai/pc/poll":
        who = _pc_auth(h, d)
        if not who:
            return h.sendj({"error": "Not authorised.", "unlinked": True}, 401)
        dev, uids, _ = who
        deadline = time.time() + 25
        with PC["cv"]:
            PC["seen"][dev] = time.time(); PC["serves"][dev] = uids
            while not any(PC["queues"].get(x) for x in uids) and time.time() < deadline:
                PC["cv"].wait(max(0.1, deadline - time.time()))
                if dev in PC["revoked"]:
                    break
            PC["seen"][dev] = time.time()
            out = []
            for x in uids:
                q = PC["queues"].get(x) or []
                while q and len(out) < 3:
                    jid = q.pop(0); j = PC["jobs"].get(jid)
                    if j:
                        j["status"] = "running"; j["device"] = dev; out.append({"id": jid, "kind": j["kind"], "args": j["args"]})
        return h.sendj({"jobs": out})
    if path == "/api/kai/pc/result":
        who = _pc_auth(h, d)
        if not who:
            return h.sendj({"error": "Not authorised.", "unlinked": True}, 401)
        dev, uids, data = who
        with PC["cv"]:
            PC["seen"][dev] = time.time()
            j = PC["jobs"].get(str(data.get("id", "")))
            ok = bool(j and j.get("device") == dev)
            if ok:
                j["status"] = "done"; j["result"] = data.get("result")
        return h.sendj({"ok": ok})
    return h.sendj({"error": "Not found"}, 404)


def serve_pclink(h, path):
    """/pclink -> the download; /downloads/KaspersenPCLink.exe -> the Windows program."""
    if path == "/pclink":
        h.send_response(302); h.send_header("Location", "/downloads/KaspersenPCLink.exe"); h.end_headers(); return
    if path == "/downloads/KaspersenPCLink.json":   # UPDATE-20261103: PC Link checks this to update itself
        f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads", "KaspersenPCLink.json")
        try:
            b = open(f, "rb").read()
        except OSError:
            return h.sendj({"error": "No update info."}, 404)
        h.send_response(200); h.send_header("Content-Type", "application/json"); h.send_header("Content-Length", str(len(b)))
        h.send_header("Cache-Control", "no-cache"); h.end_headers(); h.wfile.write(b); return
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads", "KaspersenPCLink.exe")
    if not os.path.isfile(f):
        return h.sendj({"error": "Kaspersen PC Link is not available for download yet."}, 404)
    with open(f, "rb") as fh:
        b = fh.read()
    h.send_response(200); h.send_header("Content-Type", "application/vnd.microsoft.portable-executable")
    h.send_header("Content-Disposition", 'attachment; filename="KaspersenPCLink.exe"'); h.send_header("Content-Length", str(len(b)))
    h.send_header("Cache-Control", "no-cache"); h.end_headers(); h.wfile.write(b)


def handle_get(h, path):
    if path == "/api/kai/pc/status":
        u = h.require(); uid = int(u["id"]); now = time.time()
        with A.conn() as c:
            rows = c.execute("SELECT id,name,created_at FROM kai_pc_devices WHERE user_id=? ORDER BY id", (uid,)).fetchall()
        devs = [{"id": "d" + str(r["id"]), "name": r["name"], "online": now - PC["seen"].get("d" + str(r["id"]), 0) < 60} for r in rows]
        if _pc_owner(u) and OWNER_DEV in PC["seen"]:
            devs.insert(0, {"id": OWNER_DEV, "name": "Owner PC (signed)", "online": now - PC["seen"][OWNER_DEV] < 60})
        return h.sendj({"has_pc": bool(devs), "online": any(x["online"] for x in devs), "devices": devs, "download": DOWNLOAD})
    if path == "/api/kai/pc/job":
        u = h.require()
        jid = (urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query).get("id") or [""])[0]
        j = PC["jobs"].get(jid)
        if not j or j["owner"] != int(u["id"]):
            return h.sendj({"error": "No such job."}, 404)
        # BUSY-20261103: say whether the PC is still checking in, so a long job reads as "busy", never "asleep"
        seen = PC["seen"].get(j.get("device") or "", 0) or max([PC["seen"].get(x, 0) for x in PC["seen"]] or [0])
        return h.sendj({"status": j["status"], "result": j["result"], "pc_online": time.time() - seen < 60,
                        "running_for": int(time.time() - j.get("created", time.time()))})
    if path == "/api/kai/subs":
        return _subs(h, None)
    if path == "/api/kai/proofs":
        return _proofs(h)
    if path != "/api/kai/status":
        return h.sendj({"error": "Not found"}, 404)
    u = h.require()
    uid = int(u["id"]); unl = _unlimited(u)
    used, tokens, _ = _usage(uid, _today())
    return h.sendj({"ok": True, "name": u.get("name", ""), "email": u.get("email", ""), "used_today": used, "tokens_today": tokens,
                    "daily_limit": None if unl else _env_int("KASPERSEN_DAILY_CALLS", 200), "unlimited": unl,
                    "phone_verified": unl or _phone_ok(uid), "ready": bool([1 for p in PROVIDERS if _keys().get(p[4])]),
                    "sub": _sub_state(uid, unl)})


def handle_post(h, path, d):
    if path == "/api/kai/keys":
        return _set_keys(h, d)
    if path.startswith("/api/kai/pc/"):
        return _pc_post(h, path, d)
    if path == "/api/kai/subs":
        return _subs(h, d if isinstance(d, dict) else {})
    if path == "/api/kai/proof":
        return _proof(h, d if isinstance(d, dict) else {})
    if path == "/api/kai/image":
        return _image(h, d)
    if path == "/api/kai/transcribe":
        return _transcribe(h, d)
    if path != "/api/kai/chat/completions":
        return h.sendj({"error": "Not found"}, 404)
    u = h.require()
    uid = int(u["id"]); unl = _unlimited(u); day = _today()
    if not unl and not _phone_ok(uid):
        return h.sendj({"error": "Confirm your mobile number for Future Chat to use Kaspersen.", "verify_phone": True}, 403)
    used, _t, total = _usage(uid, day)
    new_task = bool(d.get("new_task"))
    blk = _paywall(uid, unl, new_task)
    if blk:
        return h.sendj(*blk)
    if not unl:
        if used >= _env_int("KASPERSEN_DAILY_CALLS", 200):
            return h.sendj({"error": "You've reached today's Kaspersen limit. It resets at midnight.", "limit": True}, 429)
        if total >= _env_int("KASPERSEN_GLOBAL_DAILY_CALLS", 5000):
            return h.sendj({"error": "Kaspersen is very busy today. Please try again later.", "limit": True}, 429)
    msgs = d.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return h.sendj({"error": "No messages."}, 400)
    body = {"messages": msgs, "temperature": d.get("temperature", 0.6)}
    try: body["max_tokens"] = max(64, min(int(d.get("max_tokens") or MAX_TOKENS), MAX_TOKENS))
    except (TypeError, ValueError): body["max_tokens"] = MAX_TOKENS
    if isinstance(d.get("tools"), list) and d["tools"]:
        body["tools"] = d["tools"]; body["tool_choice"] = d.get("tool_choice", "auto")
    # RELIABLE-20261102: every provider that has a key gets a real try (cool-downs only reorder them), short
    # hiccups (rate limits, 5xx, timeouts) get one quick retry, and the person sees the real reason if all fail.
    keys = _keys(); last = "No AI provider key is set on the server."
    order = sorted([p for p in PROVIDERS if keys.get(p[4])], key=lambda p: _cool.get(p[0], 0) > time.time())
    if keys.get("openrouter"):
        has_img = any(isinstance(m.get("content"), list) for m in body["messages"])
        for mid in _free_models()[:FREE_MAX + 3]:
            order.append(("Free " + mid.split("/")[-1].replace(":free", ""), FREE_URL,
                          mid, "", "openrouter"))
        order = order[:len([p for p in PROVIDERS if keys.get(p[4])]) + FREE_MAX]
    for name, url, model, _env, sec in order:
        free = model.endswith(":free")
        b = dict(body, model=model)
        if free:
            b["max_tokens"] = min(b.get("max_tokens", MAX_TOKENS), 6000)
            if has_img and model not in _free["vision"]:
                b["messages"] = _text_only(b["messages"])
        payload = json.dumps(b).encode()
        for attempt in (1, 2):
            req = urllib.request.Request(url, data=payload, method="POST", headers={
                "Authorization": "Bearer " + keys[sec], "Content-Type": "application/json",
                "HTTP-Referer": "https://skillvaya.onrender.com", "X-Title": "Kaspersen Pocket"})
            retry = False
            try:
                with urllib.request.urlopen(req, timeout=170) as r:
                    j = json.loads(r.read())
                if j.get("choices"):
                    _count(uid, day, (j.get("usage") or {}).get("total_tokens", 0))
                    _cool.pop(name, None)
                    j["provider"] = name
                    left = _trial_count(uid, unl, new_task)
                    if left is not None: j["trial_left"] = left
                    return h.sendj(j)
                err = j.get("error") or {}
                last = "%s: %s" % (name, (err.get("message") if isinstance(err, dict) else err) or "empty answer")
                retry = True
            except urllib.error.HTTPError as e:
                try: msg = json.loads(e.read()).get("error")
                except Exception: msg = ""
                msg = (msg.get("message") if isinstance(msg, dict) else msg) or ("HTTP %s" % e.code)
                last = "%s: %s" % (name, str(msg)[:200])
                if e.code == 400 and body.get("tools") and ("tool" in str(msg).lower() or "function" in str(msg).lower()):
                    return h.sendj({"error": {"message": last}}, 400)  # let the phone retry without tools
                if e.code in (401, 402, 403):
                    _cool[name] = time.time() + 120
                    if free:
                        _bad[model] = time.time() + 24 * 3600
                else:
                    retry = e.code == 429 or e.code >= 500
            except Exception as e:
                last = "%s: %s" % (name, type(e).__name__); retry = True
            if not (retry and attempt == 1) or free:
                break
            time.sleep(1.5)
        _cool.setdefault(name, time.time() + 30)
    return h.sendj({"error": {"message": "Kaspersen's brain is unavailable right now. " + last}}, 502)


# STUDIO-20261102: pictures for Kaspersen Pocket (same image models as PC Kaspersen's Studio). About half a US cent each.
IMAGE_MODELS = ["google/gemini-3.1-flash-image", "google/gemini-2.5-flash-image"]
ASPECTS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
_img_used = {}


def _image(h, d):
    u = h.require()
    uid = int(u["id"]); unl = _unlimited(u); day = _today()
    if not unl and not _phone_ok(uid):
        return h.sendj({"error": "Confirm your mobile number for Future Chat to use Kaspersen.", "verify_phone": True}, 403)
    blk = _paywall(uid, unl, False)
    if blk:
        return h.sendj(*blk)
    if not unl and _img_used.get((uid, day), 0) >= _env_int("KASPERSEN_DAILY_IMAGES", 15):
        return h.sendj({"error": "You've made today's limit of pictures. It resets at midnight.", "limit": True}, 429)
    prompt = str(d.get("prompt") or "").strip()[:3000]
    if not prompt:
        return h.sendj({"error": "Describe the picture."}, 400)
    key = _keys().get("openrouter")
    if not key:
        return h.sendj({"error": "Pictures aren't set up on the server yet."}, 503)
    content = [{"type": "text", "text": prompt}]
    src = str(d.get("source_image") or "")
    if src:
        content.append({"type": "image_url", "image_url": {"url": src if src.startswith("data:") else "data:image/jpeg;base64," + src}})
    aspect = str(d.get("aspect_ratio") or "")
    errors = []
    for model in IMAGE_MODELS:
        body = {"model": model, "modalities": ["image", "text"], "messages": [{"role": "user", "content": content}]}
        if aspect in ASPECTS:
            body["image_config"] = {"aspect_ratio": aspect}
        req = urllib.request.Request(FREE_URL, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "HTTP-Referer": "https://skillvaya.onrender.com", "X-Title": "Kaspersen Pocket"})
        try:
            with urllib.request.urlopen(req, timeout=170) as r:
                j = json.loads(r.read())
        except urllib.error.HTTPError as e:
            try: msg = json.loads(e.read()).get("error")
            except Exception: msg = ""
            msg = (msg.get("message") if isinstance(msg, dict) else msg) or ("HTTP %s" % e.code)
            if e.code == 402:
                return h.sendj({"error": "The picture service has run out of credit (OpenRouter). Top it up and try again."}, 402)
            errors.append("%s: %s" % (model, str(msg)[:160])); continue
        except Exception as e:
            errors.append("%s: %s" % (model, type(e).__name__)); continue
        msg = ((j.get("choices") or [{}])[0].get("message") or {})
        imgs = msg.get("images") or []
        url = imgs[0].get("image_url", {}).get("url", "") if imgs else ""
        if not url.startswith("data:image"):
            errors.append("%s: no picture came back" % model); continue
        _img_used[(uid, day)] = _img_used.get((uid, day), 0) + 1
        _count(uid, day, (j.get("usage") or {}).get("total_tokens", 0))
        return h.sendj({"ok": True, "image": url, "model": model, "note": str(msg.get("content") or "")[:300],
                        "cost_usd": (j.get("usage") or {}).get("cost")})
    return h.sendj({"error": "Couldn't make the picture: " + " | ".join(errors)}, 502)


# NOISEPROOF-20261102: speech to text that copes with background noise (Pocket's noise-proof microphone).
# Tested 2 Nov 2026 with loud hum + hiss + beeps over speech: full sentence right, ~3-4 s, ~$0.00015.
STT_MODELS = ["google/gemini-3.5-flash-lite", "google/gemini-3.6-flash"]  # SPEED-20261102: lite ~2 s (3.6-flash took 4-6 s)
_stt_used = {}


def _transcribe(h, d):
    u = h.require()
    uid = int(u["id"]); unl = _unlimited(u); day = _today()
    if not unl and not _phone_ok(uid):
        return h.sendj({"error": "Confirm your mobile number for Future Chat to use Kaspersen.", "verify_phone": True}, 403)
    blk = _paywall(uid, unl, False)
    if blk:
        return h.sendj(*blk)
    if not unl and _stt_used.get((uid, day), 0) >= _env_int("KASPERSEN_DAILY_VOICE", 400):
        return h.sendj({"error": "You've used today's voice limit. Type your message instead - it resets at midnight.", "limit": True}, 429)
    audio = str(d.get("audio") or "")
    fmt = str(d.get("format") or "wav").lower()
    if not audio or fmt not in {"wav", "mp3", "ogg", "flac", "aac", "m4a"}:
        return h.sendj({"error": "No recording came through."}, 400)
    key = _keys().get("openrouter")
    if not key:
        return h.sendj({"error": "Voice isn't set up on the server yet."}, 503)
    name = str(d.get("name") or "").strip()[:40]
    # NPFIX-20261102: naming the assistant up front made the model answer "Kaspersen" when it couldn't hear - now it's only a spelling hint
    prompt = ("Transcribe exactly what the person says in this recording (usually South African English). Ignore background noise, "
              "music, TV and other distant voices. Write ONLY words that were actually spoken - never guess or fill in. "
              "Reply with ONLY the words, with normal punctuation - no quotes, labels or notes. If you can't make out any words, reply with nothing. "
              "(Spelling help only: if the speaker says the assistant's name it is written 'Kaspersen'"
              + ("; the speaker is " + name if name else "") + ".)")
    errors = []
    for model in STT_MODELS:
        body = {"model": model, "temperature": 0, "max_tokens": 1500, "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt}, {"type": "input_audio", "input_audio": {"data": audio, "format": fmt}}]}]}
        req = urllib.request.Request(FREE_URL, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "HTTP-Referer": "https://skillvaya.onrender.com", "X-Title": "Kaspersen Pocket"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 402:
                return h.sendj({"error": "Voice has run out of credit (OpenRouter). Top it up, or type for now."}, 402)
            errors.append("%s: HTTP %s" % (model, e.code)); continue
        except Exception as e:
            errors.append("%s: %s" % (model, type(e).__name__)); continue
        msg = ((j.get("choices") or [{}])[0].get("message") or {})
        if not j.get("choices"):
            errors.append("%s: empty" % model); continue
        text = str(msg.get("content") or "").strip().strip('"').strip("'").strip()
        if text.lower().strip(" .!?,") in {"nothing", "(nothing)", "[silence]", "(silence)", "no speech", "[no speech]", "kaspersen", "casperson", "kasperson"}:
            text = ""   # just the name on its own = it didn't really hear anything
        _stt_used[(uid, day)] = _stt_used.get((uid, day), 0) + 1
        return h.sendj({"ok": True, "text": text, "model": model})
    return h.sendj({"error": "Couldn't write down what you said - please try again. (" + " | ".join(errors)[:200] + ")"}, 502)


def _set_keys(h, d):
    data = _verify(d)
    if not data:
        return h.sendj({"error": "Not authorised."}, 403)
    stored = []
    with _lock, A.conn() as c:
        last = c.execute("SELECT value FROM kai_secrets WHERE name='_last_ts'").fetchone()
        if last and float(last["value"] or 0) >= float(data["ts"]):
            return h.sendj({"error": "Replayed request."}, 403)
        stamp = A.now()
        rows = [(k, str(v).strip()) for k, v in (data.get("keys") or {}).items() if k in {p[4] for p in PROVIDERS}]
        rows.append(("_last_ts", str(data["ts"])))
        for k, v in rows:
            c.execute("INSERT INTO kai_secrets(name,value,updated_at) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET "
                      "value=excluded.value, updated_at=excluded.updated_at", (k, v, stamp))
            if not k.startswith("_"): stored.append(k + (" (cleared)" if not v else ""))
    _cache["at"] = 0; _cool.clear()
    return h.sendj({"ok": True, "stored": stored})
