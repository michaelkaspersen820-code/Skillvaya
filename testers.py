"""TST-01 (owner 2026-11-19): see who is really testing Skillvaya and Future Chat.

Google Play only shows the owner HOW MANY testers opted in, never who. This keeps the owner's own list of tester
emails and matches each one to an account here, plus when that person last opened the Skillvaya app and the
Future Chat app (from the phone app's User-Agent), which app version they have, and - once the apps report it -
whether the app was installed from Google Play. Owner only (role 'admin'): GET /api/tst/list, POST /api/tst/add,
POST /api/tst/remove. app.py: bind(globals()); init(c); Handler.require() calls touch(); routes /api/tst/*.
"""
import datetime, re, threading, time

A = None
SEED = ["28martie@gmail.com", "Jlensly@gmail.com", "amaa672017@gmail.com", "chanteldp25@gmail.com", "hayleighkaspersen820@gmail.com",
        "info@laika.web.za", "laikasonday@gmail.com", "michaelkaspersen820@gmail.com", "mikekas92@gmail.com", "qn.havenga@gmail.com",
        "sahnz.m223@gmail.com", "samanthawolff4@gmail.com", "shelleyfin.services@gmail.com", "staanweerop@gmail.com", "willemwolff10@gmail.com"]
TOUCH_EVERY = 300          # write "last opened" at most once per 5 minutes per person per app
_recent, _lock = {}, threading.Lock()


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)


def init(c):
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS tst_testers(email TEXT PRIMARY KEY, added_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tst_seen(user_id BIGINT NOT NULL, app TEXT NOT NULL, version TEXT NOT NULL DEFAULT '',
            installer TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, PRIMARY KEY(user_id, app));
        CREATE TABLE IF NOT EXISTS tst_meta(k TEXT PRIMARY KEY, v TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS tst_days(user_id BIGINT NOT NULL, app TEXT NOT NULL, day TEXT NOT NULL, minutes INTEGER NOT NULL DEFAULT 0,
            actions INTEGER NOT NULL DEFAULT 0, first_at TEXT NOT NULL DEFAULT '', last_at TEXT NOT NULL DEFAULT '', PRIMARY KEY(user_id, app, day));
    """)
    if not c.execute("SELECT 1 FROM tst_meta WHERE k='seeded'").fetchone():
        stamp = A.now()
        for e in SEED: c.execute("INSERT INTO tst_testers(email,added_at) VALUES(?,?) ON CONFLICT DO NOTHING", (e.strip().lower(), stamp))
        c.execute("INSERT INTO tst_meta(k,v) VALUES('seeded',?) ON CONFLICT DO NOTHING", (stamp,))


def norm(email):
    """Gmail ignores dots and +tags, so j.smith+test@gmail.com is the same inbox as jsmith@gmail.com."""
    e = str(email or "").strip().lower()
    local, _, dom = e.partition("@")
    if dom in ("gmail.com", "googlemail.com"): local, dom = local.split("+")[0].replace(".", ""), "gmail.com"
    return local + "@" + dom if dom else e


def app_of(ua):
    ua = ua or ""
    inst = re.search(r"\bInstaller/([\w.\-]+)", ua)
    inst = inst.group(1)[:80] if inst else ""
    m = re.search(r"\bFutureChatApp/([\w.\-]+)", ua)
    if m or "FutureChatNative" in ua: return "futurechat", (m.group(1)[:30] if m else ""), inst
    if "SkillvayaNative" in ua:
        m = re.search(r"\bSkillvayaApp/([\w.\-]+)", ua)
        return "skillvaya", (m.group(1)[:30] if m else ""), inst
    return None


_minute = {}   # (user, app) -> (minute number, actions not yet written)


def _sa_day(ts=None):
    return (datetime.datetime.fromtimestamp(ts or time.time(), datetime.timezone.utc) + datetime.timedelta(hours=2)).strftime("%Y-%m-%d")


def _time_on(h, uid, app, now):
    """OWN-TIME-01 (owner 2026-11-20): time on each app per day = minutes in which the app talked to the server while open
    (the apps check for new messages every few seconds while on screen), plus actions = things people did (send, like, post ...)."""
    try:
        minute = int(now // 60)
        action = getattr(h, "command", "GET") == "POST"
        write = None
        with _lock:
            m, acts = _minute.get((uid, app), (0, 0))
            if action: acts += 1
            if minute != m: write = acts; _minute[(uid, app)] = (minute, 0)
            else: _minute[(uid, app)] = (m, acts)
            if len(_minute) > 20000: _minute.clear()
        if write is None: return
        stamp = A.now()
        with A.conn() as c:
            c.execute("INSERT INTO tst_days(user_id,app,day,minutes,actions,first_at,last_at) VALUES(?,?,?,1,?,?,?) ON CONFLICT(user_id,app,day) DO UPDATE SET"
                      " minutes=tst_days.minutes+1, actions=tst_days.actions+excluded.actions, last_at=excluded.last_at",
                      (uid, app, _sa_day(now), int(write), stamp, stamp))
    except Exception:
        pass   # tracking must never break a request


def touch(h, u):
    """Called for every signed-in request; records which phone app the person is using (web visits are ignored)."""
    try:
        uid = int((u or {}).get("id") or 0)
        if uid <= 0: return
        a = app_of(h.headers.get("User-Agent", ""))
        if not a: return
        app, ver, inst = a
        now = time.time()
        _time_on(h, uid, app, now)
        with _lock:
            if now - _recent.get((uid, app), 0) < TOUCH_EVERY: return
            _recent[(uid, app)] = now
        stamp = A.now()
        with A.conn() as c:
            c.execute("INSERT INTO tst_seen(user_id,app,version,installer,first_seen,last_seen) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,app) DO UPDATE SET"
                      " version=CASE WHEN excluded.version<>'' THEN excluded.version ELSE tst_seen.version END,"
                      " installer=CASE WHEN excluded.installer<>'' THEN excluded.installer ELSE tst_seen.installer END, last_seen=excluded.last_seen",
                      (uid, app, ver, inst, stamp, stamp))
    except Exception:
        pass   # tracking must never break a request


def _owner(h):
    u = h.require()
    if u.get("role") != "admin": raise PermissionError("Owner only.")
    return u


def _seen_out(r):
    if not r: return None
    inst = r["installer"] or ""
    return {"last_seen": r["last_seen"], "first_seen": r["first_seen"], "version": r["version"] or "",
            "installer": inst, "from_play": inst == "com.android.vending"}


def handle_get(h, path):
    _owner(h)
    if path == "/api/tst/list":
        with A.conn() as c:
            testers = [dict(r) for r in c.execute("SELECT email,added_at FROM tst_testers ORDER BY added_at, email").fetchall()]
            users = c.execute("SELECT id,name,email,phone_e164,phone,created_at,role FROM users WHERE email LIKE '%@%'").fetchall()
            seen = {}
            for r in c.execute("SELECT user_id,app,version,installer,first_seen,last_seen FROM tst_seen").fetchall():
                seen.setdefault(int(r["user_id"]), {})[r["app"]] = r
        by_email = {}
        for u in users:
            k = norm(u["email"])
            if k not in by_email or u["role"] != "suspended": by_email[k] = u
        listed, items = set(), []
        for t in testers:
            u = by_email.get(norm(t["email"]))
            acc, apps = None, {"futurechat": None, "skillvaya": None}
            if u:
                listed.add(int(u["id"]))
                acc = {"id": int(u["id"]), "name": u["name"], "email": u["email"], "phone": u["phone_e164"] or u["phone"] or "",
                       "joined": (u["created_at"] or "")[:10], "suspended": u["role"] == "suspended"}
                s = seen.get(int(u["id"]), {})
                apps = {"futurechat": _seen_out(s.get("futurechat")), "skillvaya": _seen_out(s.get("skillvaya"))}
            items.append({"email": t["email"], "added": (t["added_at"] or "")[:10], "account": acc, "apps": apps})
        others = []
        for u in users:
            uid = int(u["id"])
            if uid in listed or uid not in seen or u["role"] == "admin": continue
            s = seen[uid]
            others.append({"account": {"id": uid, "name": u["name"], "email": u["email"], "phone": u["phone_e164"] or u["phone"] or "",
                                       "joined": (u["created_at"] or "")[:10]},
                           "apps": {"futurechat": _seen_out(s.get("futurechat")), "skillvaya": _seen_out(s.get("skillvaya"))},
                           "last": max(r["last_seen"] for r in s.values())})
        others.sort(key=lambda x: x["last"], reverse=True)
        return h.sendj({"items": items, "others": others[:200], "now": A.now()})
    if path == "/api/tst/people":   # OWN-PEOPLE-01 (owner 2026-11-20): every account, with which phone app(s) it uses
        with A.conn() as c:
            users = c.execute("SELECT u.id,u.name,u.email,u.phone_e164,u.phone,u.role,u.created_at,u.phone_verified_at,"
                              " (SELECT count(*) FROM businesses b WHERE b.user_id=u.id) AS businesses,"
                              " (SELECT count(*) FROM payments p WHERE p.user_id=u.id AND p.status='verified') AS paid"
                              " FROM users u ORDER BY u.created_at DESC").fetchall()
            seen = {}
            for r in c.execute("SELECT user_id,app,version,installer,first_seen,last_seen FROM tst_seen").fetchall():
                seen.setdefault(int(r["user_id"]), {})[r["app"]] = r
            try: fcl = {int(r["user_id"]): (r["last_seen"] or "") for r in c.execute("SELECT user_id,last_seen FROM fcx_prefs").fetchall()}
            except Exception: fcl = {}
            since = _sa_day(time.time() - 40 * 86400)
            days = {}   # OWN-TIME-01: {user: {app: {day: [minutes, actions]}}}
            for r in c.execute("SELECT user_id,app,day,minutes,actions FROM tst_days WHERE day>=?", (since,)).fetchall():
                days.setdefault(int(r["user_id"]), {}).setdefault(r["app"], {})[r["day"]] = [int(r["minutes"] or 0), int(r["actions"] or 0)]
            try:   # Future Chat already kept a list of the days each person used it
                for r in c.execute("SELECT user_id,day FROM fca_days WHERE day>=?", (since,)).fetchall():
                    days.setdefault(int(r["user_id"]), {}).setdefault("futurechat", {}).setdefault(r["day"], [0, 0])
            except Exception: pass
            testers = [r["email"] for r in c.execute("SELECT email FROM tst_testers ORDER BY added_at, email").fetchall()]
        by_email = {norm(u["email"]): int(u["id"]) for u in users if u["email"] and u["role"] != "suspended"}
        out = []
        for u in users:
            uid = int(u["id"]); s = seen.get(uid, {})
            out.append({"id": uid, "name": u["name"] or "", "email": u["email"] or "", "phone": u["phone_e164"] or u["phone"] or "",
                        "role": u["role"], "joined": u["created_at"] or "", "fc_joined": u["phone_verified_at"] or "", "fc_last": fcl.get(uid, ""),
                        "businesses": int(u["businesses"] or 0), "paid": int(u["paid"] or 0), "days": days.get(uid, {}),
                        "apps": {"skillvaya": _seen_out(s.get("skillvaya")), "futurechat": _seen_out(s.get("futurechat"))}})
        return h.sendj({"items": out, "now": A.now(), "today": _sa_day(), "testers": [{"email": e, "user_id": by_email.get(norm(e))} for e in testers]})
    return h.sendj({"error": "Not found"}, 404)


def handle_post(h, path, d):
    _owner(h)
    d = d or {}
    if path == "/api/tst/add":
        raw = re.split(r"[\s,;]+", str(d.get("emails") or ""))
        emails = [e.strip().lower() for e in raw if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e.strip())][:200]
        if not emails: return h.sendj({"error": "Type one or more email addresses (separate them with commas or new lines)."}, 400)
        added, stamp = 0, A.now()
        with A.conn() as c:
            have = {norm(r["email"]) for r in c.execute("SELECT email FROM tst_testers").fetchall()}
            for e in emails:
                if norm(e) in have: continue
                c.execute("INSERT INTO tst_testers(email,added_at) VALUES(?,?) ON CONFLICT DO NOTHING", (e, stamp)); have.add(norm(e)); added += 1
        return h.sendj({"ok": True, "added": added, "skipped": len(emails) - added})
    if path == "/api/tst/remove":
        e = str(d.get("email") or "").strip().lower()
        with A.conn() as c: c.execute("DELETE FROM tst_testers WHERE email=?", (e,))
        return h.sendj({"ok": True})
    return h.sendj({"error": "Not found"}, 404)
