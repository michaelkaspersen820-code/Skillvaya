"""Kaspersen AI cloud brain for Kaspersen Pocket (KAI-20261102).

The phone app never holds the AI provider keys. It signs in with a Skillvaya / Future Chat account and sends its
chat request here; this server adds the key, forwards it to the GLM-5.3 provider and counts usage per account.

Routes (app.py dispatches /api/kai/* here):
  POST /api/kai/chat/completions  OpenAI-style chat request (signed-in, phone-verified accounts)
  GET  /api/kai/status            usage today, limits, whether the number is confirmed
  POST /api/kai/keys              store provider keys; must be signed by the owner's PC (Ed25519)

Keys come from environment variables (KASPERSEN_OPENROUTER_KEY, KASPERSEN_VERCEL_KEY, KASPERSEN_ORCA_KEY) or,
when those are absent, from the kai_secrets table filled through /api/kai/keys. Nothing secret lives in this file.
"""
import base64, datetime, json, os, threading, time, urllib.error, urllib.request

A = None
# Public half of the owner's signing key. Only the matching private key (kept on the owner's PC) can set keys.
ADMIN_PUBKEY = "vl6jF7ls6Nxonwurmz9MRQfN/x4Jib86DJyEarJYVwM="
PROVIDERS = [  # name, endpoint, model, env var, secret name
    ("OrcaRouter", "https://api.orcarouter.ai/v1/chat/completions", "z-ai/glm-5.3-flash-free", "KASPERSEN_ORCA_KEY", "orca"),
    ("OpenRouter", "https://openrouter.ai/api/v1/chat/completions", "z-ai/glm-5.3-flash", "KASPERSEN_OPENROUTER_KEY", "openrouter"),
    ("Vercel", "https://ai-gateway.vercel.sh/v1/chat/completions", "zai/glm-5.3-flash", "KASPERSEN_VERCEL_KEY", "vercel"),
]
MAX_TOKENS = 8000
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
    """)


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


def _usage(uid, day):
    with A.conn() as c:
        r = c.execute("SELECT calls,tokens FROM kai_usage WHERE user_id=? AND day=?", (uid, day)).fetchone()
        tot = c.execute("SELECT COALESCE(SUM(calls),0) n FROM kai_usage WHERE day=? AND user_id>0", (day,)).fetchone()
    return (int(r["calls"]) if r else 0), (int(r["tokens"]) if r else 0), int(tot["n"] or 0)


def _count(uid, day, tokens):
    with A.conn() as c:
        c.execute("INSERT INTO kai_usage(user_id,day,calls,tokens) VALUES(?,?,1,?) ON CONFLICT(user_id,day) DO UPDATE SET "
                  "calls=kai_usage.calls+1, tokens=kai_usage.tokens+excluded.tokens", (uid, day, int(tokens or 0)))


def _phone_ok(uid):
    with A.conn() as c:
        r = c.execute("SELECT phone_verified_at FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and r["phone_verified_at"])


def handle_get(h, path):
    if path != "/api/kai/status":
        return h.sendj({"error": "Not found"}, 404)
    u = h.require()
    uid = int(u["id"]); unl = _unlimited(u)
    used, tokens, _ = _usage(uid, _today())
    return h.sendj({"ok": True, "name": u.get("name", ""), "email": u.get("email", ""), "used_today": used, "tokens_today": tokens,
                    "daily_limit": None if unl else _env_int("KASPERSEN_DAILY_CALLS", 200), "unlimited": unl,
                    "phone_verified": unl or _phone_ok(uid), "ready": bool([1 for p in PROVIDERS if _keys().get(p[4])])})


def handle_post(h, path, d):
    if path == "/api/kai/keys":
        return _set_keys(h, d)
    if path != "/api/kai/chat/completions":
        return h.sendj({"error": "Not found"}, 404)
    u = h.require()
    uid = int(u["id"]); unl = _unlimited(u); day = _today()
    if not unl and not _phone_ok(uid):
        return h.sendj({"error": "Confirm your mobile number for Future Chat to use Kaspersen.", "verify_phone": True}, 403)
    used, _t, total = _usage(uid, day)
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
    keys = _keys(); last = "No AI provider is configured on the server yet."
    for name, url, model, _env, sec in PROVIDERS:
        key = keys.get(sec)
        if not key or _cool.get(name, 0) > time.time():
            continue
        payload = json.dumps(dict(body, model=model)).encode()
        req = urllib.request.Request(url, data=payload, method="POST", headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "HTTP-Referer": "https://skillvaya.onrender.com", "X-Title": "Kaspersen Pocket"})
        try:
            with urllib.request.urlopen(req, timeout=170) as r:
                j = json.loads(r.read())
            if j.get("choices"):
                _count(uid, day, (j.get("usage") or {}).get("total_tokens", 0))
                j["provider"] = name
                return h.sendj(j)
            last = name + ": empty answer"
        except urllib.error.HTTPError as e:
            try: msg = json.loads(e.read()).get("error")
            except Exception: msg = ""
            msg = (msg.get("message") if isinstance(msg, dict) else msg) or ("HTTP %s" % e.code)
            last = "%s: %s" % (name, str(msg)[:200])
            if e.code == 400 and body.get("tools") and ("tool" in str(msg).lower() or "function" in str(msg).lower()):
                return h.sendj({"error": {"message": last}}, 400)  # let the phone retry without tools
            if e.code in (401, 402, 403, 429) or e.code >= 500:
                _cool[name] = time.time() + (600 if e.code in (401, 402, 403) else 60)
        except Exception as e:
            last = "%s: %s" % (name, type(e).__name__)
            _cool[name] = time.time() + 30
    return h.sendj({"error": {"message": "Kaspersen's brain is unavailable right now. " + last}}, 502)


def _set_keys(h, d):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        payload = base64.b64decode(str(d.get("payload", "")))
        Ed25519PublicKey.from_public_bytes(base64.b64decode(ADMIN_PUBKEY)).verify(base64.b64decode(str(d.get("sig", ""))), payload)
        data = json.loads(payload)
    except Exception:
        return h.sendj({"error": "Not authorised."}, 403)
    if abs(time.time() - float(data.get("ts", 0))) > 600:
        return h.sendj({"error": "Request expired."}, 403)
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
