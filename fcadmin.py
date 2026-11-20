"""FCA-01 (owner 2026-11-19): Future Chat Control for the owner, anti-spam protection and business client lists.

- Control (owner only, role 'admin'): people joined, sign-ups per day, daily/monthly active people, online now and who,
  messages per day, complaints (reply to the person who reported, mark resolved), problem reports, bans (24 h, 7 days,
  for good) and deleting accounts (same full deletion as the account-deletion page).
- Anti-spam: normal chatting stays unlimited. Forwarding: a message can go to at most 5 chats; a message forwarded 5+
  times ("forwarded many times") only to 1 chat at a time. The same message to 15+ chats in 10 minutes, messages to
  20+ people who never replied within an hour, or 40+ messages in a minute (bots / AI tools) -> sending is stopped and
  the account is automatically banned from sending for 24 hours; the owner gets an alert and can lift it or make it
  permanent. Bans only stop Future Chat sending/starting chats; the account can still sign in and read.
- Business client lists: businesses (Skillvaya providers / owner) keep a client list and can broadcast one message to
  all clients (sent as a private message to each, max 5 broadcasts a day). Broadcasts never trigger the spam ban.
  Every broadcast shows "Stop messages from this business"; someone who opts out can't be added back by that business.
app.py: bind(globals()); init(c); routes /api/fca/*.  futurechat.py calls check_send()/log_send()/add_report().
"""
import datetime, hashlib, json, re, threading, time, urllib.parse

A = None
FWD_MAX, FWD_MANY = 5, 5
SAME_MSG_CHATS, SAME_MSG_WINDOW = 15, 600
COLD_PEOPLE, COLD_WINDOW = 20, 3600
RATE_MSGS, RATE_WINDOW = 40, 60
AUTO_BAN_HOURS = 24
BCAST_PER_DAY = 5
ADDS_PER_DAY = 300
ONLINE_SECONDS = 150


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)


def init(c):
    pk = A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS fca_days(day TEXT NOT NULL, user_id BIGINT NOT NULL, PRIMARY KEY(day, user_id));
        CREATE TABLE IF NOT EXISTS fca_sends(user_id BIGINT NOT NULL, conversation_id BIGINT NOT NULL, h TEXT NOT NULL, fwd INTEGER NOT NULL DEFAULT 0,
            cold INTEGER NOT NULL DEFAULT 0, at DOUBLE PRECISION NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_fca_sends_user ON fca_sends(user_id, at);
        CREATE TABLE IF NOT EXISTS fca_bans(user_id BIGINT PRIMARY KEY, until TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', auto INTEGER NOT NULL DEFAULT 0,
            by_id BIGINT NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fca_ban_log(id %(pk)s, user_id BIGINT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fca_reports(id %(pk)s, reporter_id BIGINT NOT NULL, conversation_id BIGINT NOT NULL DEFAULT 0, reported_id BIGINT NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '', snapshot TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open', reply TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, resolved_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS fca_clients(biz_id BIGINT NOT NULL, client_id BIGINT NOT NULL, added_at TEXT NOT NULL, opted_out INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(biz_id, client_id));
        CREATE INDEX IF NOT EXISTS idx_fca_clients_client ON fca_clients(client_id);
        CREATE TABLE IF NOT EXISTS fca_bcasts(id %(pk)s, biz_id BIGINT NOT NULL, body TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
    """ % {"pk": pk})
    if "hidden" not in A.table_columns(c, "fc_members"): c.execute("ALTER TABLE fc_members ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")   # FCA-02
    threading.Thread(target=_loop, name="FutureChatControl", daemon=True).start()


def _utc(): return datetime.datetime.now(datetime.timezone.utc)
def _iso(dt): return dt.isoformat()
def _sa_day(dt=None): return ((dt or _utc()) + datetime.timedelta(hours=2)).strftime("%Y-%m-%d")


def _loop():
    while True:
        time.sleep(300)
        try:
            with A.conn() as c:
                c.execute("DELETE FROM fca_sends WHERE at<?", (time.time() - 2 * 86400,))
                stamp = A.now()
                for r in c.execute("SELECT user_id FROM fca_bans WHERE until<>'' AND until<?", (stamp,)).fetchall():
                    c.execute("DELETE FROM fca_bans WHERE user_id=?", (int(r["user_id"]),))
                    c.execute("INSERT INTO fca_ban_log(user_id,action,detail,created_at) VALUES(?,?,?,?)", (int(r["user_id"]), "expired", "", stamp))
        except Exception as exc:
            print("Future Chat control sweep skipped:", type(exc).__name__)


# ---------------------------------------------------------------- activity (called by fcextras._touch)
def day(c, uid):
    try: c.execute("INSERT INTO fca_days(day,user_id) VALUES(?,?) ON CONFLICT DO NOTHING", (_sa_day(), int(uid)))
    except Exception: pass


# ---------------------------------------------------------------- bans
def ban_of(c, uid):
    r = c.execute("SELECT * FROM fca_bans WHERE user_id=?", (int(uid),)).fetchone()
    if not r: return None
    if r["until"] and r["until"] < A.now(): return None
    return r


def _ban_msg(r):
    if not r["until"]: return "Your Future Chat account can't send messages because it broke the rules. Contact skillvaya@gmail.com if you think this is a mistake."
    try:
        t = datetime.datetime.fromisoformat(r["until"]) + datetime.timedelta(hours=2)
        when = t.strftime("%d %b at %H:%M")
    except Exception: when = "later"
    return "You can't send messages until %s because your account sent too many messages to many people at once. This protects everyone from spam." % when


def ban(c, uid, hours, reason, auto=False, by_id=0):
    until = _iso(_utc() + datetime.timedelta(hours=hours)) if hours else ""
    stamp = A.now()
    c.execute("INSERT INTO fca_bans(user_id,until,reason,auto,by_id,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET until=excluded.until,"
              "reason=excluded.reason,auto=excluded.auto,by_id=excluded.by_id,created_at=excluded.created_at", (int(uid), until, reason[:300], 1 if auto else 0, int(by_id), stamp))
    c.execute("INSERT INTO fca_ban_log(user_id,action,detail,created_at) VALUES(?,?,?,?)", (int(uid), "auto-ban" if auto else "ban", ("%sh " % hours if hours else "permanent ") + reason[:300], stamp))


def _auto_ban(c, u, why):
    uid = int(u["id"])
    ban(c, uid, AUTO_BAN_HOURS, why, auto=True)
    try:
        A.notify("complaint", "Future Chat: %s auto-banned for 24 hours" % (u.get("name") or "#%d" % uid),
                 "%s (#%d) was stopped and banned from sending for 24 hours.\nReason: %s\n\nOpen Future Chat > You > Future Chat Control > Bans to lift it or make it permanent." % (u.get("name") or "", uid, why))
    except Exception: pass
    _push_owner("🛡️ Spam stopped", "%s was banned for 24 hours: %s" % (u.get("name") or "Someone", why))


def _push_owner(title, text):
    def run():
        try:
            with A.conn() as c:
                owners = [int(r["id"]) for r in c.execute("SELECT id FROM users WHERE role='admin'").fetchall()]
            send = getattr(A, "fcm_send_to_user", None)
            for o in owners:
                if send: send(o, title, text, {"type": "fca", "url": "/customer-app?fca=1"})
        except Exception: pass
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- anti-spam (called from /api/fc/send and /api/fcx broadcast)
def _hash(body, kind, nfiles):
    t = re.sub(r"\s+", " ", (body or "").strip().lower())
    t = re.sub(r"https?://\S+", "<link>", t)
    return hashlib.sha1(("%s|%s|%d" % (kind, t, nfiles)).encode("utf-8", "ignore")).hexdigest()[:20]


def _is_cold(c, conv_id, uid):
    cv = c.execute("SELECT kind FROM fc_conversations WHERE id=?", (conv_id,)).fetchone()
    if not cv or cv["kind"] != "direct": return 0
    other = c.execute("SELECT 1 FROM fc_messages WHERE conversation_id=? AND sender_id<>? AND kind<>'system' LIMIT 1", (conv_id, uid)).fetchone()
    return 0 if other else 1


def check_send(c, u, conv_id, body, kind, meta, nfiles):
    """Return (payload, status) to refuse the message, or None to allow it. Owner/admin is never limited."""
    uid = int(u["id"])
    if u.get("role") == "admin": return None
    b = ban_of(c, uid)
    if b: return {"error": _ban_msg(b), "banned": True, "until": b["until"]}, 403
    now = time.time()
    h = _hash(body, kind, nfiles)
    fwd = 0
    try: fwd = int((meta or {}).get("fwd") or 0)
    except Exception: fwd = 0
    if fwd:
        n = c.execute("SELECT COUNT(DISTINCT conversation_id) AS n FROM fca_sends WHERE user_id=? AND h=? AND fwd>0 AND at>? AND conversation_id<>?",
                      (uid, h, now - SAME_MSG_WINDOW, conv_id)).fetchone()["n"]
        limit = 1 if fwd > FWD_MANY else FWD_MAX
        if n >= limit:
            return {"error": ("This message was forwarded many times, so it can only be sent to one chat at a time." if limit == 1
                              else "You can forward a message to up to %d chats at a time." % FWD_MAX), "forward_limit": True}, 429
    rate = c.execute("SELECT COUNT(*) AS n FROM fca_sends WHERE user_id=? AND at>?", (uid, now - RATE_WINDOW)).fetchone()["n"]
    if rate >= RATE_MSGS:
        _auto_ban(c, u, "sent %d+ messages in one minute (automatic sending)" % RATE_MSGS)
        return {"error": _ban_msg(ban_of(c, uid)), "banned": True}, 403
    meaningful = len((body or "").strip()) >= 4 or nfiles
    if meaningful:
        same = c.execute("SELECT COUNT(DISTINCT conversation_id) AS n FROM fca_sends WHERE user_id=? AND h=? AND at>? AND conversation_id<>?",
                         (uid, h, now - SAME_MSG_WINDOW, conv_id)).fetchone()["n"]
        if same + 1 >= SAME_MSG_CHATS:
            _auto_ban(c, u, "sent the same message to %d+ chats within 10 minutes" % SAME_MSG_CHATS)
            return {"error": _ban_msg(ban_of(c, uid)), "banned": True}, 403
    if _is_cold(c, conv_id, uid):
        cold = c.execute("SELECT COUNT(DISTINCT conversation_id) AS n FROM fca_sends WHERE user_id=? AND cold=1 AND at>? AND conversation_id<>?",
                         (uid, now - COLD_WINDOW, conv_id)).fetchone()["n"]
        if cold + 1 >= COLD_PEOPLE:
            _auto_ban(c, u, "messaged %d+ people who never replied within an hour" % COLD_PEOPLE)
            return {"error": _ban_msg(ban_of(c, uid)), "banned": True}, 403
    return None


def log_send(c, uid, conv_id, body, kind, meta, nfiles):
    try:
        fwd = int((meta or {}).get("fwd") or 0)
    except Exception: fwd = 0
    try:
        c.execute("INSERT INTO fca_sends(user_id,conversation_id,h,fwd,cold,at) VALUES(?,?,?,?,?,?)",
                  (int(uid), int(conv_id), _hash(body, kind, nfiles), fwd, _is_cold(c, conv_id, int(uid)), time.time()))
    except Exception as exc:
        print("Future Chat send log skipped:", type(exc).__name__)


def can_start(c, u):
    """Starting new chats/groups is also blocked while banned."""
    if u.get("role") == "admin": return None
    b = ban_of(c, int(u["id"]))
    return ({"error": _ban_msg(b), "banned": True}, 403) if b else None


# ---------------------------------------------------------------- complaints (called from /api/fc/report)
def add_report(c, reporter_id, conv_id, reason, snapshot, reported_id=0):
    if not reported_id:
        cv = c.execute("SELECT kind FROM fc_conversations WHERE id=?", (conv_id,)).fetchone()
        if cv and cv["kind"] == "direct":
            o = c.execute("SELECT user_id FROM fc_members WHERE conversation_id=? AND user_id<>?", (conv_id, reporter_id)).fetchone()
            if o: reported_id = int(o["user_id"])
    c.execute("INSERT INTO fca_reports(reporter_id,conversation_id,reported_id,reason,snapshot,created_at) VALUES(?,?,?,?,?,?)",
              (int(reporter_id), int(conv_id), int(reported_id), reason[:200], snapshot[:8000], A.now()))
    _push_owner("⚑ New Future Chat report", reason[:120])


# ---------------------------------------------------------------- helpers
def _owner(h):
    u = h.require()
    if u.get("role") != "admin": raise PermissionError("Owner only.")
    return u


def _is_business(c, u):
    if u.get("role") in ("provider", "admin"): return True
    return bool(c.execute("SELECT 1 FROM businesses WHERE user_id=? LIMIT 1", (int(u["id"]),)).fetchone())


def _direct(c, a, b, stamp):
    lo, hi = sorted((int(a), int(b)))
    key = "d:%d:%d" % (lo, hi)
    row = c.execute("SELECT id FROM fc_conversations WHERE pair_key=?", (key,)).fetchone()
    if row: return int(row["id"])
    cid = c.execute("INSERT INTO fc_conversations(kind,title,pair_key,created_by,created_at,updated_at) VALUES('direct','',?,?,?,?) RETURNING id",
                    (key, int(a), stamp, stamp)).fetchone()["id"]
    for m in (lo, hi): c.execute("INSERT INTO fc_members(conversation_id,user_id,joined_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (cid, m, stamp))
    return int(cid)


def _post(c, cid, sender_id, body, meta):
    stamp = A.now()
    mid = c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,meta,created_at) VALUES(?,?,?,?,?,?) RETURNING id",
                    (cid, int(sender_id), body, "text", json.dumps(meta), stamp)).fetchone()["id"]
    c.execute("UPDATE fc_conversations SET last_message_id=?,updated_at=? WHERE id=?", (mid, stamp, cid))
    c.execute("UPDATE fc_members SET archived=0 WHERE conversation_id=?", (cid,))
    c.execute("UPDATE fc_members SET last_read_id=? WHERE conversation_id=? AND user_id=?", (mid, cid, int(sender_id)))
    return int(mid)


def _push_conv(cid, sender, text):
    try:
        import futurechat as FCm
        FCm._push(cid, sender, text)
    except Exception: pass


def _last_seen(c, ids):
    if not ids: return {}
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 400):
        part = ids[i:i + 400]
        for r in c.execute("SELECT user_id,last_seen FROM fcx_prefs WHERE user_id IN (" + ",".join("?" * len(part)) + ")", tuple(part)).fetchall():
            out[int(r["user_id"])] = r["last_seen"] or ""
    return out


def _person(r, seen="", banned=None):
    return {"id": int(r["id"]), "name": r["name"], "phone": r["phone"] or "", "email": r["email"] or "", "role": r["role"],
            "joined": (r["created_at"] or "")[:10], "last_seen": seen,
            "banned": ({"until": banned["until"], "reason": banned["reason"], "auto": bool(banned["auto"])} if banned else None)}


# ---------------------------------------------------------------- GET
def handle_get(h, path):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    if path == "/api/fca/me":
        u = h.require()
        with A.conn() as c:
            b = ban_of(c, int(u["id"]))
            return h.sendj({"owner": u.get("role") == "admin", "business": _is_business(c, u),
                            "banned": ({"until": b["until"], "message": _ban_msg(b)} if b else None)})
    if path == "/api/fca/biz/clients":
        u = h.require(); uid = int(u["id"])
        with A.conn() as c:
            if not _is_business(c, u): return h.sendj({"error": "Client lists are for business accounts."}, 403)
            rows = c.execute("SELECT u.id,u.name,u.phone_e164 AS phone,cl.added_at,cl.opted_out FROM fca_clients cl JOIN users u ON u.id=cl.client_id"
                             " WHERE cl.biz_id=? ORDER BY cl.opted_out, LOWER(u.name)", (uid,)).fetchall()
            mine = {int(r["id"]) for r in rows}
            sugg = c.execute("SELECT DISTINCT u.id,u.name,u.phone_e164 AS phone FROM fc_members me JOIN fc_conversations cv ON cv.id=me.conversation_id AND cv.kind='direct'"
                             " JOIN fc_members o ON o.conversation_id=cv.id AND o.user_id<>me.user_id JOIN users u ON u.id=o.user_id"
                             " WHERE me.user_id=? AND u.phone_verified_at<>'' LIMIT 500", (uid,)).fetchall()
            today = _sa_day()
            sent_today = c.execute("SELECT COUNT(*) AS n FROM fca_bcasts WHERE biz_id=? AND created_at>?", (uid, _iso(_utc() - datetime.timedelta(hours=24)))).fetchone()["n"]
            past = c.execute("SELECT body,sent,created_at FROM fca_bcasts WHERE biz_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
        return h.sendj({"clients": [{"id": int(r["id"]), "name": r["name"], "phone": r["phone"] or "", "added": (r["added_at"] or "")[:10], "opted_out": bool(r["opted_out"])} for r in rows],
                        "suggest": [{"id": int(r["id"]), "name": r["name"], "phone": r["phone"] or ""} for r in sugg if int(r["id"]) not in mine][:200],
                        "left_today": max(0, BCAST_PER_DAY - int(sent_today)), "per_day": BCAST_PER_DAY,
                        "past": [{"body": r["body"][:200], "sent": int(r["sent"]), "at": r["created_at"]} for r in past]})
    _owner(h)
    if path == "/api/fca/admin/stats":
        days = max(7, min(90, int((q.get("days") or ["30"])[0] or 30)))
        start = _utc() - datetime.timedelta(days=days - 1)
        labels = [_sa_day(start + datetime.timedelta(days=i)) for i in range(days)]
        with A.conn() as c:
            total = c.execute("SELECT COUNT(*) AS n FROM users WHERE role<>'suspended'").fetchone()["n"]
            fc_total = c.execute("SELECT COUNT(*) AS n FROM users WHERE phone_verified_at<>''").fetchone()["n"]
            joined = {l: 0 for l in labels}
            for r in c.execute("SELECT created_at FROM users WHERE created_at>=?", (_iso(start - datetime.timedelta(hours=2)),)).fetchall():
                try: d = _sa_day(datetime.datetime.fromisoformat(r["created_at"]))
                except Exception: continue
                if d in joined: joined[d] += 1
            active = {l: 0 for l in labels}
            for r in c.execute("SELECT day,COUNT(*) AS n FROM fca_days WHERE day>=? GROUP BY day", (labels[0],)).fetchall():
                if r["day"] in active: active[r["day"]] = int(r["n"])
            msgs = {l: 0 for l in labels}
            for r in c.execute("SELECT created_at FROM fc_messages WHERE created_at>=? AND kind<>'system'", (_iso(start - datetime.timedelta(hours=2)),)).fetchall():
                try: d = _sa_day(datetime.datetime.fromisoformat(r["created_at"]))
                except Exception: continue
                if d in msgs: msgs[d] += 1
            mau = c.execute("SELECT COUNT(DISTINCT user_id) AS n FROM fca_days WHERE day>=?", (_sa_day(_utc() - datetime.timedelta(days=29)),)).fetchone()["n"]
            wau = c.execute("SELECT COUNT(DISTINCT user_id) AS n FROM fca_days WHERE day>=?", (_sa_day(_utc() - datetime.timedelta(days=6)),)).fetchone()["n"]
            cut = _iso(_utc() - datetime.timedelta(seconds=ONLINE_SECONDS))
            online = c.execute("SELECT u.id,u.name,u.phone_e164 AS phone,u.email,u.role,u.created_at,p.last_seen FROM fcx_prefs p JOIN users u ON u.id=p.user_id"
                               " WHERE p.last_seen>=? ORDER BY p.last_seen DESC LIMIT 300", (cut,)).fetchall()
            open_reports = c.execute("SELECT COUNT(*) AS n FROM fca_reports WHERE status='open'").fetchone()["n"]
            bans = c.execute("SELECT COUNT(*) AS n FROM fca_bans WHERE until='' OR until>?", (A.now(),)).fetchone()["n"]
        return h.sendj({"total": int(total), "fc_total": int(fc_total), "today_active": active.get(labels[-1], 0), "wau": int(wau), "mau": int(mau),
                        "online_now": len(online), "open_reports": int(open_reports), "active_bans": int(bans),
                        "labels": labels, "joined": [joined[l] for l in labels], "active": [active[l] for l in labels], "messages": [msgs[l] for l in labels],
                        "online": [_person(r, r["last_seen"]) for r in online]})
    if path == "/api/fca/admin/list":   # FCA-LIST-01 (owner 2026-11-20): the people behind every number and chart bar in Control
        kind = (q.get("kind") or ["active"])[0]
        day = (q.get("day") or [""])[0]
        try: days = max(0, min(90, int((q.get("days") or ["0"])[0] or 0)))
        except ValueError: days = 0
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day or ""): day = _sa_day()
        d0 = datetime.datetime.fromisoformat(day + "T00:00:00+02:00").astimezone(datetime.timezone.utc)
        lo, hi = _iso(d0), _iso(d0 + datetime.timedelta(days=1))
        with A.conn() as c:
            counts = {}
            if kind == "active":
                if days > 1:
                    for r in c.execute("SELECT user_id,COUNT(*) AS n FROM fca_days WHERE day>=? GROUP BY user_id", (_sa_day(_utc() - datetime.timedelta(days=days - 1)),)).fetchall(): counts[int(r["user_id"])] = int(r["n"])
                else:
                    for r in c.execute("SELECT user_id FROM fca_days WHERE day=?", (day,)).fetchall(): counts[int(r["user_id"])] = 1
            elif kind == "joined":
                for r in c.execute("SELECT id FROM users WHERE created_at>=? AND created_at<?", (lo, hi)).fetchall(): counts[int(r["id"])] = 1
            elif kind == "msgs":
                for r in c.execute("SELECT sender_id,COUNT(*) AS n FROM fc_messages WHERE created_at>=? AND created_at<? AND kind<>'system' GROUP BY sender_id", (lo, hi)).fetchall(): counts[int(r["sender_id"])] = int(r["n"])
            else:
                return h.sendj({"error": "Unknown list."}, 400)
            ids = list(counts)
            rows = []
            for i in range(0, len(ids), 400):
                part = ids[i:i + 400]
                rows += c.execute("SELECT id,name,phone_e164 AS phone,email,role,created_at FROM users WHERE id IN (" + ",".join("?" * len(part)) + ")", tuple(part)).fetchall()
            seen = _last_seen(c, ids)
            apps = {}
            try:
                for i in range(0, len(ids), 400):
                    part = ids[i:i + 400]
                    for r in c.execute("SELECT user_id,app,last_seen FROM tst_seen WHERE user_id IN (" + ",".join("?" * len(part)) + ")", tuple(part)).fetchall():
                        apps.setdefault(int(r["user_id"]), {})[r["app"]] = r["last_seen"]
            except Exception: pass
            out = []
            for r in rows:
                p = _person(r, seen.get(int(r["id"]), ""), ban_of(c, int(r["id"])))
                p["n"] = counts.get(int(r["id"]), 0); p["apps"] = apps.get(int(r["id"]), {})
                out.append(p)
        out.sort(key=lambda p: (-p["n"], p["last_seen"] or ""), reverse=False)
        if kind != "msgs" and days <= 1: out.sort(key=lambda p: p["last_seen"] or "", reverse=True)
        return h.sendj({"items": out, "kind": kind, "day": day, "days": days})
    if path == "/api/fca/admin/users":
        term = (q.get("q") or [""])[0].strip()[:80]
        with A.conn() as c:
            if (q.get("fc") or [""])[0]:   # FCA-03: everyone who joined Future Chat (confirmed number), newest first
                rows = c.execute("SELECT id,name,phone_e164 AS phone,email,role,phone_verified_at AS created_at FROM users WHERE phone_verified_at<>''"
                                 " ORDER BY phone_verified_at DESC LIMIT 1000").fetchall()
            elif term:
                like = "%" + term.lower() + "%"
                digits = re.sub(r"\D", "", term)
                rows = c.execute("SELECT id,name,phone_e164 AS phone,email,role,created_at FROM users WHERE LOWER(name) LIKE ? OR LOWER(email) LIKE ?"
                                 + (" OR phone_e164 LIKE ?" if digits else "") + " ORDER BY id DESC LIMIT 60",
                                 (like, like, "%" + digits[-9:] + "%") if digits else (like, like)).fetchall()
            else:
                rows = c.execute("SELECT id,name,phone_e164 AS phone,email,role,created_at FROM users ORDER BY id DESC LIMIT 60").fetchall()
            seen = _last_seen(c, [int(r["id"]) for r in rows])
            out = [_person(r, seen.get(int(r["id"]), ""), ban_of(c, int(r["id"]))) for r in rows]
        return h.sendj({"items": out})
    if path == "/api/fca/admin/reports":
        with A.conn() as c:
            rows = c.execute("SELECT r.*,a.name AS reporter,b.name AS reported FROM fca_reports r LEFT JOIN users a ON a.id=r.reporter_id LEFT JOIN users b ON b.id=r.reported_id"
                             " ORDER BY CASE WHEN r.status='open' THEN 0 ELSE 1 END, r.id DESC LIMIT 200").fetchall()
            probs = c.execute("SELECT p.id,p.user_id,p.body,p.created_at,u.name FROM fcx_reports p LEFT JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 100").fetchall()
        return h.sendj({"items": [{"id": int(r["id"]), "reporter_id": int(r["reporter_id"]), "reporter": r["reporter"] or "Deleted account",
                                   "reported_id": int(r["reported_id"] or 0), "reported": r["reported"] or "", "reason": r["reason"], "snapshot": r["snapshot"],
                                   "status": r["status"], "reply": r["reply"], "at": r["created_at"]} for r in rows],
                        "problems": [{"id": int(p["id"]), "user_id": int(p["user_id"]), "name": p["name"] or "Deleted account", "body": p["body"], "at": p["created_at"]} for p in probs]})
    if path == "/api/fca/admin/bans":
        with A.conn() as c:
            rows = c.execute("SELECT b.*,u.name,u.phone_e164 AS phone FROM fca_bans b LEFT JOIN users u ON u.id=b.user_id WHERE b.until='' OR b.until>? ORDER BY b.created_at DESC", (A.now(),)).fetchall()
            log = c.execute("SELECT l.*,u.name FROM fca_ban_log l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT 50").fetchall()
        return h.sendj({"items": [{"user_id": int(r["user_id"]), "name": r["name"] or "Deleted account", "phone": r["phone"] or "", "until": r["until"], "reason": r["reason"],
                                   "auto": bool(r["auto"]), "at": r["created_at"]} for r in rows],
                        "log": [{"name": l["name"] or "#%d" % int(l["user_id"]), "action": l["action"], "detail": l["detail"], "at": l["created_at"]} for l in log]})
    return h.sendj({"error": "Not found"}, 404)


# ---------------------------------------------------------------- POST
def handle_post(h, path, d):
    d = d or {}
    u = h.require(); uid = int(u["id"])
    if path == "/api/fca/chat/delete":
        # FCA-02 (WhatsApp-style "Delete chat" from the chat list): only for this person. Direct chats are cleared and hidden
        # until someone sends a new message; groups: you leave the group and it disappears.
        cid = int(d.get("c") or 0); stamp = A.now()
        with A.conn() as c:
            if not c.execute("SELECT 1 FROM fc_members WHERE conversation_id=? AND user_id=?", (cid, uid)).fetchone():
                return h.sendj({"error": "Chat not found."}, 404)
            cv = c.execute("SELECT kind,last_message_id FROM fc_conversations WHERE id=?", (cid,)).fetchone()
            if cv["kind"] == "group":
                c.execute("DELETE FROM fc_members WHERE conversation_id=? AND user_id=?", (cid, uid))
                c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,created_at) VALUES(?,?,?,?,?)", (cid, uid, (u.get("name") or "Someone") + " left", "system", stamp))
                return h.sendj({"ok": True, "left": True})
            last = int(cv["last_message_id"] or 0)
            c.execute("UPDATE fc_members SET hidden=1,cleared_id=?,cleared_at=?,archived=0,pinned=0,last_read_id=CASE WHEN last_read_id<? THEN ? ELSE last_read_id END"
                      " WHERE conversation_id=? AND user_id=?", (last, stamp, last, last, cid, uid))
        return h.sendj({"ok": True})
    if path == "/api/fca/optout":
        biz = int(d.get("biz") or 0)
        if not biz: return h.sendj({"error": "Which business?"}, 400)
        with A.conn() as c:
            c.execute("INSERT INTO fca_clients(biz_id,client_id,added_at,opted_out) VALUES(?,?,?,1) ON CONFLICT(biz_id,client_id) DO UPDATE SET opted_out=1", (biz, uid, A.now()))
        return h.sendj({"ok": True, "message": "Done. This business can't send you broadcast messages any more. You can still chat with them normally."})
    if path.startswith("/api/fca/biz/"):
        with A.conn() as c:
            if not _is_business(c, u): return h.sendj({"error": "Client lists are for business accounts."}, 403)
            stamp = A.now()
            if path == "/api/fca/biz/add":
                added, skipped, notfound = 0, 0, 0
                done_today = c.execute("SELECT COUNT(*) AS n FROM fca_clients WHERE biz_id=? AND added_at>?", (uid, _iso(_utc() - datetime.timedelta(hours=24)))).fetchone()["n"]
                cands = []
                for x in (d.get("user_ids") or [])[:500]:
                    try: cands.append(int(x))
                    except Exception: pass
                if d.get("phones"):
                    import futurechat as FCm
                    country = (c.execute("SELECT country FROM users WHERE id=?", (uid,)).fetchone() or {"country": "ZA"})["country"] or "ZA"
                    for p in (d.get("phones") or [])[:500]:
                        ph = FCm.normalize_phone(p, country)
                        r = c.execute("SELECT id FROM users WHERE phone_e164=? AND phone_verified_at<>''", (ph,)).fetchone() if ph else None
                        if r: cands.append(int(r["id"]))
                        else: notfound += 1
                for cid in cands:
                    if cid == uid: continue
                    if done_today + added >= ADDS_PER_DAY: skipped += 1; continue
                    ex = c.execute("SELECT opted_out FROM fca_clients WHERE biz_id=? AND client_id=?", (uid, cid)).fetchone()
                    if ex: skipped += 1; continue
                    c.execute("INSERT INTO fca_clients(biz_id,client_id,added_at) VALUES(?,?,?)", (uid, cid, stamp)); added += 1
                return h.sendj({"ok": True, "added": added, "skipped": skipped, "not_on_app": notfound})
            if path == "/api/fca/biz/remove":
                c.execute("DELETE FROM fca_clients WHERE biz_id=? AND client_id=? AND opted_out=0", (uid, int(d.get("user_id") or 0)))
                return h.sendj({"ok": True})
            if path == "/api/fca/biz/broadcast":
                body = str(d.get("body") or "").strip()[:2000]
                if len(body) < 2: return h.sendj({"error": "Type your message first."}, 400)
                b = ban_of(c, uid)
                if b and u.get("role") != "admin": return h.sendj({"error": _ban_msg(b), "banned": True}, 403)
                n24 = c.execute("SELECT COUNT(*) AS n FROM fca_bcasts WHERE biz_id=? AND created_at>?", (uid, _iso(_utc() - datetime.timedelta(hours=24)))).fetchone()["n"]
                if n24 >= BCAST_PER_DAY and u.get("role") != "admin":
                    return h.sendj({"error": "You can send %d broadcasts a day. Try again tomorrow." % BCAST_PER_DAY}, 429)
                clients = [int(r["client_id"]) for r in c.execute("SELECT client_id FROM fca_clients WHERE biz_id=? AND opted_out=0", (uid,)).fetchall()]
                if not clients: return h.sendj({"error": "Add clients to your list first."}, 400)
                import futurechat as FCm
                meta = {"bc": {"biz": uid, "name": u.get("name") or "Business"}}
                sent = []
                for cid_user in clients:
                    conv = _direct(c, uid, cid_user, stamp)
                    if FCm._blocked(c, conv, uid): continue
                    _post(c, conv, uid, body, meta); sent.append(conv)
                c.execute("INSERT INTO fca_bcasts(biz_id,body,sent,created_at) VALUES(?,?,?,?)", (uid, body, len(sent), stamp))
            else:
                return h.sendj({"error": "Not found"}, 404)
        for conv in sent: _push_conv(conv, u, body[:120])
        return h.sendj({"ok": True, "sent": len(sent)})
    if u.get("role") != "admin": return h.sendj({"error": "Owner only."}, 403)
    stamp = A.now()
    if path == "/api/fca/admin/reply":
        rid = int(d.get("report_id") or 0); text = str(d.get("text") or "").strip()[:2000]
        if not text: return h.sendj({"error": "Type your reply first."}, 400)
        with A.conn() as c:
            r = c.execute("SELECT reporter_id FROM fca_reports WHERE id=?", (rid,)).fetchone()
            if not r: return h.sendj({"error": "Report not found."}, 404)
            to = int(r["reporter_id"])
            if not c.execute("SELECT 1 FROM users WHERE id=?", (to,)).fetchone(): return h.sendj({"error": "That person deleted their account."}, 404)
            conv = _direct(c, uid, to, stamp)
            _post(c, conv, uid, "🛡️ Future Chat support: " + text, {"support": rid})
            c.execute("UPDATE fca_reports SET reply=? WHERE id=?", (text, rid))
        _push_conv(conv, u, text[:120])
        return h.sendj({"ok": True, "conversation_id": conv})
    if path == "/api/fca/admin/resolve":
        with A.conn() as c:
            c.execute("UPDATE fca_reports SET status=?,resolved_at=? WHERE id=?", ("open" if d.get("reopen") else "resolved", "" if d.get("reopen") else stamp, int(d.get("report_id") or 0)))
        return h.sendj({"ok": True})
    if path == "/api/fca/admin/message":
        # FCA-04: owner sends an update to everyone on Future Chat, or to the people ticked; each gets a private message.
        body = str(d.get("body") or "").strip()[:4000]
        if len(body) < 2: return h.sendj({"error": "Type your message first."}, 400)
        with A.conn() as c:
            if d.get("all"):
                ids = [int(r["id"]) for r in c.execute("SELECT id FROM users WHERE phone_verified_at<>'' AND role<>'suspended'").fetchall()]
            else:
                ids = []
                for x in (d.get("user_ids") or [])[:5000]:
                    try: ids.append(int(x))
                    except Exception: pass
            ids = [i for i in dict.fromkeys(ids) if i != uid]
            if not ids: return h.sendj({"error": "Choose who to message."}, 400)
            sent = []
            for to in ids:
                if not c.execute("SELECT 1 FROM users WHERE id=?", (to,)).fetchone(): continue
                conv = _direct(c, uid, to, stamp)
                _post(c, conv, uid, body, {"owner_update": 1})
                sent.append(conv)
        for conv in sent: _push_conv(conv, u, body[:120])
        return h.sendj({"ok": True, "sent": len(sent)})
    target = int(d.get("user_id") or 0)
    with A.conn() as c:
        t = c.execute("SELECT id,name,email,role FROM users WHERE id=?", (target,)).fetchone()
        if not t: return h.sendj({"error": "Account not found."}, 404)
        if t["role"] == "admin": return h.sendj({"error": "Owner accounts are protected."}, 403)
        if path == "/api/fca/admin/ban":
            hours = int(d.get("hours") or 0)
            if hours not in (0, 24, 168, 720): return h.sendj({"error": "Choose 24 hours, 7 days, 30 days or for good."}, 400)
            reason = str(d.get("reason") or "Broke the Future Chat rules").strip()[:300]
            ban(c, target, hours, reason, by_id=uid)
            return h.sendj({"ok": True, "message": "%s is banned %s." % (t["name"], "for good" if not hours else "for %s" % {24: "24 hours", 168: "7 days", 720: "30 days"}[hours])})
        if path == "/api/fca/admin/unban":
            c.execute("DELETE FROM fca_bans WHERE user_id=?", (target,))
            c.execute("INSERT INTO fca_ban_log(user_id,action,detail,created_at) VALUES(?,?,?,?)", (target, "unban", "by owner", stamp))
            return h.sendj({"ok": True, "message": "%s can send messages again." % t["name"]})
        if path == "/api/fca/admin/delete":
            if str(d.get("confirm") or "") != "DELETE": return h.sendj({"error": "Type DELETE to confirm."}, 400)
            email, name = t["email"], t["name"]
            result = A.delete_account_data(c, target)
            c.execute("DELETE FROM fca_bans WHERE user_id=?", (target,))
            c.execute("DELETE FROM fca_clients WHERE biz_id=? OR client_id=?", (target, target))
            c.execute("INSERT INTO fca_ban_log(user_id,action,detail,created_at) VALUES(?,?,?,?)", (target, "deleted", "%s <%s> deleted by owner" % (name, email), stamp))
            return h.sendj({"ok": True, "message": "%s's account and data were deleted." % name, "details": result if isinstance(result, (dict, list)) else None})
    return h.sendj({"error": "Not found"}, 404)
