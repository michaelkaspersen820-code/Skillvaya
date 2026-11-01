"""Future Chat inside Skillvaya: conversations, messages, reactions, attachments and phone verification.

app.py calls bind(globals()) once, then routes /api/fc/*, /api/phone/* and /futurechat/* here.
All SQL uses '?' placeholders so it runs on both the hosted PostgreSQL and local SQLite.
"""
import base64, datetime, json, os, re, threading, time, urllib.parse

A = None  # app.py namespace (conn, now, fcm_send_to_user, setting, WF_ID_TYPE, DATABASE_URL ...)
ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static", "futurechat")
MAX_ATTACH = 16 * 1024 * 1024
TEXT_LIMIT = 6000
KINDS = {"text", "photo", "video", "file", "voice", "location", "contact", "quote", "stokvel", "system", "call"}
CHATMOJI_REACT = re.compile(r"^:[a-z0-9_]{2,30}:$")
CALLING_CODES = {"ZA": "27", "NA": "264", "BW": "267", "ZW": "263", "MZ": "258", "LS": "266", "SZ": "268", "ZM": "260", "MW": "265",
                 "KE": "254", "NG": "234", "GH": "233", "TZ": "255", "UG": "256", "GB": "44", "US": "1", "CA": "1", "AU": "61",
                 "NZ": "64", "IE": "353", "DE": "49", "FR": "33", "NL": "31", "PT": "351", "ES": "34", "IT": "39", "IN": "91",
                 "AE": "971", "SA": "966", "BR": "55", "KR": "82", "JP": "81", "CN": "86", "PK": "92", "PH": "63"}


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items():
        setattr(A, k, v)


# ---------------------------------------------------------------- schema
def init(c):
    pk = A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS fc_conversations(id %(pk)s, kind TEXT NOT NULL DEFAULT 'direct', title TEXT NOT NULL DEFAULT '',
            pair_key TEXT, business_id BIGINT NOT NULL DEFAULT 0, customer_id BIGINT NOT NULL DEFAULT 0, created_by BIGINT NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_message_id BIGINT NOT NULL DEFAULT 0);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fc_conv_pair ON fc_conversations(pair_key);
        CREATE TABLE IF NOT EXISTS fc_members(conversation_id BIGINT NOT NULL, user_id BIGINT NOT NULL, role TEXT NOT NULL DEFAULT 'member',
            last_read_id BIGINT NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, muted INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0,
            joined_at TEXT NOT NULL, PRIMARY KEY(conversation_id, user_id));
        CREATE INDEX IF NOT EXISTS idx_fc_members_user ON fc_members(user_id);
        CREATE TABLE IF NOT EXISTS fc_messages(id %(pk)s, conversation_id BIGINT NOT NULL, sender_id BIGINT NOT NULL, body TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'text', meta TEXT NOT NULL DEFAULT '{}', reply_to BIGINT NOT NULL DEFAULT 0, edited_at TEXT NOT NULL DEFAULT '',
            deleted_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, legacy_id BIGINT NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_fc_messages_conv ON fc_messages(conversation_id, id);
        CREATE INDEX IF NOT EXISTS idx_fc_messages_legacy ON fc_messages(legacy_id);
        CREATE TABLE IF NOT EXISTS fc_reactions(message_id BIGINT NOT NULL, user_id BIGINT NOT NULL, emoji TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(message_id, user_id));
        CREATE TABLE IF NOT EXISTS fc_stars(message_id BIGINT NOT NULL, user_id BIGINT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(message_id, user_id));
        CREATE TABLE IF NOT EXISTS fc_attachments(id %(pk)s, message_id BIGINT NOT NULL, conversation_id BIGINT NOT NULL, filename TEXT NOT NULL,
            mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, data_base64 TEXT NOT NULL, created_at TEXT NOT NULL, legacy_id BIGINT NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_fc_attachments_msg ON fc_attachments(message_id);
        CREATE TABLE IF NOT EXISTS fc_fetches(attachment_id BIGINT NOT NULL, user_id BIGINT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(attachment_id, user_id));
    """ % {"pk": pk})
    if "purged_at" not in _columns(c, "fc_attachments"): c.execute("ALTER TABLE fc_attachments ADD COLUMN purged_at TEXT NOT NULL DEFAULT ''")
    cols = _columns(c, "users")
    if "phone_e164" not in cols: c.execute("ALTER TABLE users ADD COLUMN phone_e164 TEXT DEFAULT ''")
    if "phone_verified_at" not in cols: c.execute("ALTER TABLE users ADD COLUMN phone_verified_at TEXT DEFAULT ''")
    try: c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_verified ON users(phone_e164) WHERE phone_verified_at<>''")
    except Exception as exc: print("Future Chat phone index skipped:", type(exc).__name__)


def _columns(c, table):
    return A.table_columns(c, table)


# ---------------------------------------------------------------- legacy Skillvaya messages -> Future Chat
_MIGRATE_LOCK = threading.Lock()
_MIGRATED_AT = [0.0]
_SWEPT_AT = [0.0]


def migrate_legacy(force=False):
    """Copy customer<->business messages (and attachments) into Future Chat. Idempotent and incremental."""
    if not force and time.monotonic() - _MIGRATED_AT[0] < 60: return 0
    if not _MIGRATE_LOCK.acquire(blocking=False): return 0
    copied = 0
    try:
        _MIGRATED_AT[0] = time.monotonic()
        with A.conn() as c:
            done = c.execute("SELECT COALESCE(MAX(legacy_id),0) AS m FROM fc_messages").fetchone()["m"] or 0
            rows = c.execute("SELECT m.id,m.business_id,m.customer_id,m.sender_id,m.message,m.created_at,m.read_at,b.user_id AS owner_id FROM messages m "
                             "JOIN businesses b ON b.id=m.business_id WHERE m.id>? ORDER BY m.id LIMIT 2000", (int(done),)).fetchall()
            for r in rows:
                if int(r["customer_id"] or 0) <= 0: continue
                cid = _business_conversation(c, int(r["business_id"]), int(r["customer_id"]), int(r["owner_id"] or 0), r["created_at"])
                body = str(r["message"] or "")
                atts = c.execute("SELECT id,filename,mime_type,size_bytes,data_base64,created_at FROM message_attachments WHERE message_id=?", (r["id"],)).fetchall()
                kind = _kind_for(atts[0]["mime_type"]) if atts else "text"
                if atts and re.fullmatch(r"\s*(\[(photo|video|image|file|attachment)\]|📷 ?photo|🎬 ?video|shared (a )?(photo|video|file))?\s*", body, re.I): body = ""
                mid = c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,meta,created_at,legacy_id) VALUES(?,?,?,?,?,?,?) RETURNING id",
                                (cid, int(r["sender_id"]), body, kind, "{}", r["created_at"], int(r["id"]))).fetchone()["id"]
                for a in atts:
                    c.execute("INSERT INTO fc_attachments(message_id,conversation_id,filename,mime_type,size_bytes,data_base64,created_at,legacy_id) VALUES(?,?,?,?,?,?,?,?)",
                              (mid, cid, a["filename"], a["mime_type"], int(a["size_bytes"] or 0), a["data_base64"], a["created_at"], int(a["id"])))
                c.execute("UPDATE fc_conversations SET last_message_id=?,updated_at=? WHERE id=? AND last_message_id<?", (mid, r["created_at"], cid, mid))
                if r["read_at"]:
                    reader = int(r["owner_id"] or 0) if int(r["sender_id"]) == int(r["customer_id"]) else int(r["customer_id"])
                    c.execute("UPDATE fc_members SET last_read_id=? WHERE conversation_id=? AND user_id=? AND last_read_id<?", (mid, cid, reader, mid))
                copied += 1
    except Exception as exc:
        print("Future Chat legacy migration paused:", type(exc).__name__, str(exc)[:200])
    finally:
        _MIGRATE_LOCK.release()
    return copied


def _kind_for(mime):
    mime = str(mime or "")
    if mime.startswith("image/"): return "photo"
    if mime.startswith("video/"): return "video"
    if mime.startswith("audio/"): return "voice"
    return "file"


def _business_conversation(c, business_id, customer_id, owner_id, stamp=None):
    key = "b:%d:%d" % (business_id, customer_id)
    row = c.execute("SELECT id FROM fc_conversations WHERE pair_key=?", (key,)).fetchone()
    if row: return int(row["id"])
    stamp = stamp or A.now()
    cid = c.execute("INSERT INTO fc_conversations(kind,title,pair_key,business_id,customer_id,created_by,created_at,updated_at) VALUES('business','',?,?,?,?,?,?) RETURNING id",
                    (key, business_id, customer_id, customer_id, stamp, stamp)).fetchone()["id"]
    for uid in {customer_id, owner_id}:
        if uid > 0:
            c.execute("INSERT INTO fc_members(conversation_id,user_id,joined_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (cid, uid, stamp))
    return int(cid)


# ---------------------------------------------------------------- helpers
def normalize_phone(raw, country="ZA"):
    s = re.sub(r"[^\d+]", "", str(raw or ""))
    if not s: return ""
    if s.startswith("00"): s = "+" + s[2:]
    if not s.startswith("+"):
        code = CALLING_CODES.get(str(country or "ZA").upper(), "27")
        s = "+" + code + s.lstrip("0")
    digits = s[1:]
    if not digits.isdigit() or not (8 <= len(digits) <= 15): return ""
    return s


def _member(c, conv_id, uid):
    return c.execute("SELECT * FROM fc_members WHERE conversation_id=? AND user_id=?", (conv_id, uid)).fetchone()


def _require_member(c, conv_id, u):
    m = _member(c, conv_id, int(u["id"]))
    if not m: raise PermissionError("You are not part of this conversation.")
    return m


def _snippet(row):
    kind = row["kind"]
    if row["deleted_at"]: return "Message deleted"
    labels = {"photo": "📷 Photo", "video": "🎬 Video", "file": "📎 Document", "voice": "🎤 Voice note", "location": "📍 Location",
              "contact": "👤 Contact", "quote": "🧾 Quote", "stokvel": "💰 Stokvel", "call": "📞 Call"}
    body = re.sub(r":([a-z0-9_]+):", "☺", str(row["body"] or "")).replace("\n", " ").strip()
    if kind in labels: return labels[kind] + ((" · " + body) if body else "")
    return body[:140]


def _title_for(c, conv, uid):
    if conv["kind"] == "group": return conv["title"] or "Group"
    if conv["kind"] == "business":
        b = c.execute("SELECT name,user_id FROM businesses WHERE id=?", (conv["business_id"],)).fetchone()
        if b and int(b["user_id"] or 0) == uid and int(conv["customer_id"]) != uid:
            cu = c.execute("SELECT name FROM users WHERE id=?", (conv["customer_id"],)).fetchone()
            return (cu["name"] if cu else "Customer"), "customer"
        return (b["name"] if b else "Business"), "business"
    other = c.execute("SELECT u.name FROM fc_members m JOIN users u ON u.id=m.user_id WHERE m.conversation_id=? AND m.user_id<>? LIMIT 1", (conv["id"], uid)).fetchone()
    return (other["name"] if other else "Conversation"), "person"


def _push(conv_id, sender, text, kind="message", extra=None):
    def run():
        try:
            with A.conn() as c:
                rows = c.execute("SELECT user_id,muted FROM fc_members WHERE conversation_id=? AND user_id<>?", (conv_id, int(sender["id"]))).fetchall()
            for r in rows:
                if int(r["muted"] or 0): continue
                data = {"type": kind, "conversation_id": str(conv_id), "url": "/customer-app?fc=%d" % conv_id}
                data.update(extra or {})
                send = getattr(A, "fcm_send_to_user", None)
                if send: send(int(r["user_id"]), sender["name"] or "Future Chat", text or "New message", data)
        except Exception as exc:
            print("Future Chat push skipped:", type(exc).__name__)
    threading.Thread(target=run, daemon=True).start()


def _public_user(r):
    return {"id": int(r["id"]), "name": r["name"], "role": r["role"]}


# ---------------------------------------------------------------- static files
STATIC_TYPES = {".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


def serve_static(h, path):
    name = path.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[a-z0-9_\-]+\.(js|css)", name): return h.sendj({"error": "Not found"}, 404)
    fp = os.path.join(STATIC, name)
    if not os.path.isfile(fp): return h.sendj({"error": "Not found"}, 404)
    with open(fp, "rb") as f: data = f.read()
    h.send_response(200)
    h.send_header("Content-Type", STATIC_TYPES[os.path.splitext(name)[1]])
    h.send_header("Cache-Control", "public, max-age=300")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers(); h.wfile.write(data)


# ---------------------------------------------------------------- GET
def handle_get(h, path):
    u = h.require()
    uid = int(u["id"])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    if path == "/api/fc/conversations":
        if time.monotonic() - _MIGRATED_AT[0] > 60:
            threading.Thread(target=migrate_legacy, daemon=True).start()
            if time.monotonic() - _SWEPT_AT[0] > 3600: _SWEPT_AT[0] = time.monotonic(); threading.Thread(target=purge_old_media, daemon=True).start()
        with A.conn() as c:
            rows = c.execute(
                "SELECT cv.id,cv.kind,cv.title,cv.business_id,cv.customer_id,cv.updated_at,m.archived,m.muted,m.pinned,"
                " lm.sender_id AS lm_sender,lm.body AS lm_body,lm.kind AS lm_kind,lm.deleted_at AS lm_deleted,lm.created_at AS lm_at,"
                " (SELECT COUNT(*) FROM fc_messages x WHERE x.conversation_id=cv.id AND x.id>m.last_read_id AND x.sender_id<>?) AS unread,"
                " b.name AS biz_name,b.user_id AS biz_owner,cu.name AS cust_name,"
                " (SELECT u2.name FROM fc_members o JOIN users u2 ON u2.id=o.user_id WHERE o.conversation_id=cv.id AND o.user_id<>? LIMIT 1) AS other_name,"
                " (SELECT u3.phone_verified_at FROM users u3 WHERE u3.id=?) AS my_verified"
                " FROM fc_members m JOIN fc_conversations cv ON cv.id=m.conversation_id"
                " LEFT JOIN fc_messages lm ON lm.id=cv.last_message_id LEFT JOIN businesses b ON b.id=cv.business_id LEFT JOIN users cu ON cu.id=cv.customer_id"
                " WHERE m.user_id=? ORDER BY cv.updated_at DESC LIMIT 400", (uid, uid, uid, uid)).fetchall()
        items, verified = [], False
        for r in rows:
            verified = bool(r["my_verified"])
            if r["kind"] == "group": title, who = r["title"] or "Group", "group"
            elif r["kind"] == "business":
                mine_biz = int(r["biz_owner"] or 0) == uid and int(r["customer_id"] or 0) != uid
                title, who = ((r["cust_name"] or "Customer"), "customer") if mine_biz else ((r["biz_name"] or "Business"), "business")
            else: title, who = r["other_name"] or "Conversation", "person"
            last = None
            if r["lm_at"]:
                last = {"text": _snippet({"kind": r["lm_kind"], "body": r["lm_body"], "deleted_at": r["lm_deleted"]}), "mine": int(r["lm_sender"]) == uid, "at": r["lm_at"]}
            items.append({"id": int(r["id"]), "kind": r["kind"], "title": title, "who": who, "business_id": int(r["business_id"] or 0),
                          "customer_id": int(r["customer_id"] or 0), "updated_at": r["updated_at"], "unread": int(r["unread"] or 0),
                          "archived": bool(r["archived"]), "muted": bool(r["muted"]), "pinned": bool(r["pinned"]), "last": last})
        if not rows: verified = _phone_verified(uid)
        return h.sendj({"items": items, "me": {"id": uid, "name": u["name"], "phone_verified": verified}})
    if path == "/api/fc/pulse":
        with A.conn() as c:
            row = c.execute("SELECT MAX(cv.last_message_id) AS latest FROM fc_members m JOIN fc_conversations cv ON cv.id=m.conversation_id WHERE m.user_id=?", (uid,)).fetchone()
            unread = c.execute("SELECT COUNT(*) AS n FROM fc_members m JOIN fc_messages x ON x.conversation_id=m.conversation_id "
                               "WHERE m.user_id=? AND m.archived=0 AND x.id>m.last_read_id AND x.sender_id<>?", (uid, uid)).fetchone()
        return h.sendj({"latest": int((row["latest"] if row else 0) or 0), "unread": int((unread["n"] if unread else 0) or 0)})
    if path == "/api/fc/messages":
        try: conv_id = int(q.get("c", ["0"])[0]); after = int(q.get("after", ["0"])[0]); before = int(q.get("before", ["0"])[0])
        except ValueError: return h.sendj({"error": "Invalid request."}, 400)
        with A.conn() as c:
            mem = _require_member(c, conv_id, u)
            conv = c.execute("SELECT * FROM fc_conversations WHERE id=?", (conv_id,)).fetchone()
            if before: rows = c.execute("SELECT * FROM fc_messages WHERE conversation_id=? AND id<? ORDER BY id DESC LIMIT 60", (conv_id, before)).fetchall()[::-1]
            elif after: rows = c.execute("SELECT * FROM fc_messages WHERE conversation_id=? AND id>? ORDER BY id LIMIT 200", (conv_id, after)).fetchall()
            else: rows = c.execute("SELECT * FROM fc_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 80", (conv_id,)).fetchall()[::-1]
            ids = [int(r["id"]) for r in rows]
            reacts, stars, atts, replies = {}, set(), {}, {}
            if ids:
                marks = ",".join("?" for _ in ids)
                for r in c.execute("SELECT message_id,user_id,emoji FROM fc_reactions WHERE message_id IN (" + marks + ")", tuple(ids)).fetchall():
                    reacts.setdefault(int(r["message_id"]), []).append({"user_id": int(r["user_id"]), "emoji": r["emoji"]})
                for r in c.execute("SELECT message_id FROM fc_stars WHERE user_id=? AND message_id IN (" + marks + ")", (uid,) + tuple(ids)).fetchall():
                    stars.add(int(r["message_id"]))
                for r in c.execute("SELECT id,message_id,filename,mime_type,size_bytes,purged_at FROM fc_attachments WHERE message_id IN (" + marks + ") ORDER BY id", tuple(ids)).fetchall():
                    atts.setdefault(int(r["message_id"]), []).append({"id": int(r["id"]), "filename": r["filename"], "mime_type": r["mime_type"], "size": int(r["size_bytes"]), "on_server": not r["purged_at"]})
                rids = sorted({int(r["reply_to"]) for r in rows if int(r["reply_to"] or 0)})
                if rids:
                    for r in c.execute("SELECT id,sender_id,body,kind,deleted_at FROM fc_messages WHERE conversation_id=? AND id IN (" + ",".join("?" for _ in rids) + ")", (conv_id,) + tuple(rids)).fetchall():
                        replies[int(r["id"])] = {"id": int(r["id"]), "sender_id": int(r["sender_id"]), "text": _snippet(r)}
            members = c.execute("SELECT u.id,u.name,u.role,m.last_read_id FROM fc_members m JOIN users u ON u.id=m.user_id WHERE m.conversation_id=?", (conv_id,)).fetchall()
            title, who = _title_for(c, conv, uid) if conv["kind"] != "group" else (conv["title"] or "Group", "group")
            dial = ""
            if conv["kind"] == "direct":
                o = c.execute("SELECT u.phone_e164 FROM fc_members m JOIN users u ON u.id=m.user_id WHERE m.conversation_id=? AND m.user_id<>? LIMIT 1", (conv_id, uid)).fetchone()
                dial = (o["phone_e164"] if o else "") or ""
            elif conv["kind"] == "business":
                if who == "business":
                    b = c.execute("SELECT phone FROM businesses WHERE id=?", (conv["business_id"],)).fetchone(); dial = (b["phone"] if b else "") or ""
                else:
                    o = c.execute("SELECT phone_e164,phone FROM users WHERE id=?", (conv["customer_id"],)).fetchone(); dial = ((o["phone_e164"] or o["phone"]) if o else "") or ""
        others_read = min([int(m["last_read_id"] or 0) for m in members if int(m["id"]) != uid] or [0])
        out = []
        for r in rows:
            d = {"id": int(r["id"]), "sender_id": int(r["sender_id"]), "mine": int(r["sender_id"]) == uid, "kind": r["kind"],
                 "body": "" if r["deleted_at"] else r["body"], "deleted": bool(r["deleted_at"]), "edited": bool(r["edited_at"]),
                 "created_at": r["created_at"], "reactions": reacts.get(int(r["id"]), []), "starred": int(r["id"]) in stars,
                 "attachments": [] if r["deleted_at"] else atts.get(int(r["id"]), []), "reply": replies.get(int(r["reply_to"] or 0)),
                 "read": int(r["id"]) <= others_read}
            try: d["meta"] = {} if r["deleted_at"] else json.loads(r["meta"] or "{}")
            except ValueError: d["meta"] = {}
            out.append(d)
        return h.sendj({"conversation": {"id": conv_id, "kind": conv["kind"], "title": title, "who": who, "business_id": int(conv["business_id"] or 0),
                                         "customer_id": int(conv["customer_id"] or 0), "muted": bool(mem["muted"]), "archived": bool(mem["archived"]),
                                         "pinned": bool(mem["pinned"]), "members": [_public_user(m) for m in members], "dial": re.sub(r"[^\d+]", "", str(dial or ""))},
                        "items": out})
    if path.startswith("/api/fc/file/"):
        try: att_id = int(path.rsplit("/", 1)[1])
        except ValueError: return h.sendj({"error": "Invalid file."}, 400)
        with A.conn() as c:
            a = c.execute("SELECT a.*,m.sender_id FROM fc_attachments a JOIN fc_messages m ON m.id=a.message_id WHERE a.id=?", (att_id,)).fetchone()
            if not a: return h.sendj({"error": "File not found."}, 404)
            _require_member(c, int(a["conversation_id"]), u)
            if a["purged_at"] or not a["data_base64"]:
                return h.sendj({"error": "This file is saved on the phones it was sent to.", "purged": True}, 410)
            if uid != int(a["sender_id"]):
                c.execute("INSERT INTO fc_fetches(attachment_id,user_id,created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (att_id, uid, A.now()))
        payload = base64.b64decode(a["data_base64"])
        threading.Thread(target=_maybe_purge, args=(att_id,), daemon=True).start()
        fname = str(a["filename"] or "file")
        safe = "".join(ch if ord(ch) < 128 and (ch.isalnum() or ch in "._-") else "_" for ch in fname)[:120] or "file"
        disp = "attachment" if q.get("download") else "inline"
        h.send_response(200)
        h.send_header("Content-Type", str(a["mime_type"]))
        h.send_header("Content-Disposition", disp + '; filename="' + safe + '"')
        h.send_header("X-Content-Type-Options", "nosniff")
        h.send_header("Cache-Control", "private, max-age=86400")
        h.send_header("Content-Length", str(len(payload)))
        h.end_headers(); h.wfile.write(payload); return
    if path == "/api/fc/search-people":
        term = str(q.get("q", [""])[0]).strip()
        with A.conn() as c:
            country = (c.execute("SELECT country FROM users WHERE id=?", (uid,)).fetchone() or {"country": "ZA"})["country"] or "ZA"
            phone = normalize_phone(term, country)
            people = []
            if phone:
                r = c.execute("SELECT id,name,role FROM users WHERE phone_e164=? AND phone_verified_at<>'' AND role NOT IN ('suspended')", (phone,)).fetchone()
                if r and int(r["id"]) != uid: people.append(_public_user(r))
            biz = []
            if len(term) >= 2 and not phone:
                like = "%" + term.lower() + "%"
                biz = [{"business_id": int(b["id"]), "name": b["name"], "category": b["category"], "area": b["area"]} for b in
                       c.execute("SELECT id,name,category,area FROM businesses WHERE status='approved' AND LOWER(name) LIKE ? ORDER BY name LIMIT 12", (like,)).fetchall()]
        return h.sendj({"phone": phone, "people": people, "businesses": biz})
    if path == "/api/phone/status":
        with A.conn() as c:
            r = c.execute("SELECT phone,phone_e164,phone_verified_at,country FROM users WHERE id=?", (uid,)).fetchone()
        return h.sendj({"phone": (r["phone_e164"] or r["phone"] or "") if r else "", "verified": bool(r and r["phone_verified_at"]),
                        "country": (r["country"] if r else "") or "ZA", "web_config": _web_config()})
    return h.sendj({"error": "Not found"}, 404)


MEDIA_DAYS = 30


def _maybe_purge(att_id):
    """Delete a photo/video/file from the server once every recipient's phone has it."""
    try:
        with A.conn() as c:
            a = c.execute("SELECT a.id,a.conversation_id,m.sender_id FROM fc_attachments a JOIN fc_messages m ON m.id=a.message_id WHERE a.id=? AND a.purged_at=''", (att_id,)).fetchone()
            if not a: return
            need = c.execute("SELECT COUNT(*) AS n FROM fc_members WHERE conversation_id=? AND user_id<>?", (a["conversation_id"], a["sender_id"])).fetchone()["n"]
            got = c.execute("SELECT COUNT(*) AS n FROM fc_fetches f JOIN fc_members mb ON mb.user_id=f.user_id AND mb.conversation_id=? WHERE f.attachment_id=?", (a["conversation_id"], att_id)).fetchone()["n"]
            if int(need or 0) > 0 and int(got or 0) >= int(need):
                c.execute("UPDATE fc_attachments SET data_base64='',purged_at=? WHERE id=?", (A.now(), att_id))
    except Exception as exc:
        print("Future Chat purge skipped:", type(exc).__name__)


def purge_old_media():
    """Files nobody collected within MEDIA_DAYS are removed; phones keep their own copies."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=MEDIA_DAYS)).isoformat()
    try:
        with A.conn() as c:
            n = c.execute("UPDATE fc_attachments SET data_base64='',purged_at=? WHERE purged_at='' AND created_at<? RETURNING id", (A.now(), cutoff)).fetchall()
        if n: print("Future Chat removed %d expired media files" % len(n))
    except Exception as exc:
        print("Future Chat media sweep skipped:", type(exc).__name__)


def _phone_verified(uid):
    with A.conn() as c:
        r = c.execute("SELECT phone_verified_at FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and r["phone_verified_at"])


def _web_config():
    raw = os.environ.get("FIREBASE_WEB_CONFIG", "").strip()
    if not raw: return None
    try:
        cfg = json.loads(raw)
        return {k: cfg[k] for k in ("apiKey", "authDomain", "projectId", "appId") if k in cfg}
    except ValueError:
        return None


# ---------------------------------------------------------------- POST
def handle_post(h, path, d):
    u = h.require()
    uid = int(u["id"])
    stamp = A.now()
    if path == "/api/fc/start":
        with A.conn() as c:
            if d.get("business_id"):
                b = c.execute("SELECT id,user_id,name FROM businesses WHERE id=?", (int(d["business_id"]),)).fetchone()
                if not b: return h.sendj({"error": "That business could not be found."}, 404)
                if int(b["user_id"] or 0) == uid: return h.sendj({"error": "This is your own business."}, 400)
                cid = _business_conversation(c, int(b["id"]), uid, int(b["user_id"] or 0), stamp)
                return h.sendj({"conversation_id": cid})
            if d.get("user_id") or d.get("phone"):
                if d.get("user_id"): other = c.execute("SELECT id,name FROM users WHERE id=? AND phone_verified_at<>''", (int(d["user_id"]),)).fetchone()
                else:
                    country = (c.execute("SELECT country FROM users WHERE id=?", (uid,)).fetchone() or {"country": "ZA"})["country"] or "ZA"
                    phone = normalize_phone(d.get("phone"), country)
                    if not phone: return h.sendj({"error": "Enter a valid phone number."}, 400)
                    other = c.execute("SELECT id,name FROM users WHERE phone_e164=? AND phone_verified_at<>''", (phone,)).fetchone()
                    if not other:
                        return h.sendj({"invite": True, "phone": phone, "error": "That number isn't on Future Chat yet.",
                                        "share_text": "Join me on Future Chat in Skillvaya — chat, Chatmoji and calls: https://skillvaya.onrender.com/download"}, 404)
                if not other: return h.sendj({"error": "That person can't be found."}, 404)
                if int(other["id"]) == uid: return h.sendj({"error": "That's your own number."}, 400)
                if not _phone_verified(uid): return h.sendj({"error": "Verify your phone number first.", "verify_required": True}, 403)
                lo, hi = sorted((uid, int(other["id"])))
                key = "d:%d:%d" % (lo, hi)
                row = c.execute("SELECT id FROM fc_conversations WHERE pair_key=?", (key,)).fetchone()
                if row: return h.sendj({"conversation_id": int(row["id"])})
                cid = c.execute("INSERT INTO fc_conversations(kind,title,pair_key,created_by,created_at,updated_at) VALUES('direct','',?,?,?,?) RETURNING id",
                                (key, uid, stamp, stamp)).fetchone()["id"]
                for m in (lo, hi): c.execute("INSERT INTO fc_members(conversation_id,user_id,joined_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (cid, m, stamp))
                return h.sendj({"conversation_id": int(cid)})
            if d.get("group_title"):
                title = str(d.get("group_title") or "").strip()[:60]
                if not title: return h.sendj({"error": "Give the group a name."}, 400)
                if not _phone_verified(uid): return h.sendj({"error": "Verify your phone number first.", "verify_required": True}, 403)
                ids = {uid}
                for p in (d.get("phones") or [])[:255]:
                    country = "ZA"
                    ph = normalize_phone(p, country)
                    r = c.execute("SELECT id FROM users WHERE phone_e164=? AND phone_verified_at<>''", (ph,)).fetchone() if ph else None
                    if r: ids.add(int(r["id"]))
                cid = c.execute("INSERT INTO fc_conversations(kind,title,pair_key,created_by,created_at,updated_at) VALUES('group',?,NULL,?,?,?) RETURNING id",
                                (title, uid, stamp, stamp)).fetchone()["id"]
                for m in ids: c.execute("INSERT INTO fc_members(conversation_id,user_id,role,joined_at) VALUES(?,?,?,?)", (cid, m, "admin" if m == uid else "member", stamp))
                mid = c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,created_at) VALUES(?,?,?,?,?) RETURNING id",
                                (cid, uid, "%s created the group “%s”" % (u["name"], title), "system", stamp)).fetchone()["id"]
                c.execute("UPDATE fc_conversations SET last_message_id=? WHERE id=?", (mid, cid))
                return h.sendj({"conversation_id": int(cid), "added": len(ids) - 1})
        return h.sendj({"error": "Choose who to chat with."}, 400)
    if path == "/api/fc/send":
        conv_id = int(d.get("c") or 0)
        kind = str(d.get("kind") or "text")
        if kind not in KINDS or kind in ("system", "call"): return h.sendj({"error": "Unsupported message type."}, 400)
        body = str(d.get("body") or "")[:TEXT_LIMIT]
        meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
        meta_s = json.dumps(meta)[:4000]
        files = d.get("files") if isinstance(d.get("files"), list) else []
        if not body.strip() and not files and kind == "text": return h.sendj({"error": "Type a message first."}, 400)
        decoded = []
        for f in files[:10]:
            try: raw = base64.b64decode(str(f.get("data_base64") or ""), validate=True)
            except Exception: return h.sendj({"error": "A file could not be read."}, 400)
            if not raw or len(raw) > MAX_ATTACH: return h.sendj({"error": "Each file must be 16 MB or smaller."}, 400)
            name = re.sub(r"[\\/\r\n]", "_", str(f.get("filename") or "file"))[:120]
            mime = str(f.get("mime_type") or "application/octet-stream")[:100]
            decoded.append((name, mime, len(raw), base64.b64encode(raw).decode()))
        reply_to = int(d.get("reply_to") or 0)
        with A.conn() as c:
            _require_member(c, conv_id, u)
            if reply_to and not c.execute("SELECT 1 FROM fc_messages WHERE id=? AND conversation_id=?", (reply_to, conv_id)).fetchone(): reply_to = 0
            mid = c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,meta,reply_to,created_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
                            (conv_id, uid, body, kind, meta_s, reply_to, stamp)).fetchone()["id"]
            att_ids = []
            for name, mime, size, b64 in decoded:
                att_ids.append(int(c.execute("INSERT INTO fc_attachments(message_id,conversation_id,filename,mime_type,size_bytes,data_base64,created_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
                          (mid, conv_id, name, mime, size, b64, stamp)).fetchone()["id"]))
            c.execute("UPDATE fc_conversations SET last_message_id=?,updated_at=? WHERE id=?", (mid, stamp, conv_id))
            c.execute("UPDATE fc_members SET last_read_id=?,archived=0 WHERE conversation_id=? AND user_id=?", (mid, conv_id, uid))
            c.execute("UPDATE fc_members SET archived=0 WHERE conversation_id=?", (conv_id,))
            snippet = _snippet({"kind": kind, "body": body, "deleted_at": ""})
        _push(conv_id, u, snippet)
        return h.sendj({"ok": True, "id": int(mid), "created_at": stamp, "attachments": att_ids})
    if path in ("/api/fc/react", "/api/fc/star", "/api/fc/edit", "/api/fc/delete"):
        mid = int(d.get("m") or 0)
        with A.conn() as c:
            msg = c.execute("SELECT * FROM fc_messages WHERE id=?", (mid,)).fetchone()
            if not msg: return h.sendj({"error": "Message not found."}, 404)
            _require_member(c, int(msg["conversation_id"]), u)
            if path == "/api/fc/react":
                emoji = str(d.get("emoji") or "")
                if emoji and not CHATMOJI_REACT.match(emoji): return h.sendj({"error": "Choose a Chatmoji."}, 400)
                c.execute("DELETE FROM fc_reactions WHERE message_id=? AND user_id=?", (mid, uid))
                if emoji: c.execute("INSERT INTO fc_reactions(message_id,user_id,emoji,created_at) VALUES(?,?,?,?)", (mid, uid, emoji, stamp))
                return h.sendj({"ok": True})
            if path == "/api/fc/star":
                c.execute("DELETE FROM fc_stars WHERE message_id=? AND user_id=?", (mid, uid))
                if d.get("on"): c.execute("INSERT INTO fc_stars(message_id,user_id,created_at) VALUES(?,?,?)", (mid, uid, stamp))
                return h.sendj({"ok": True})
            if int(msg["sender_id"]) != uid: return h.sendj({"error": "You can only change your own messages."}, 403)
            if msg["deleted_at"]: return h.sendj({"error": "This message was deleted."}, 400)
            if path == "/api/fc/edit":
                body = str(d.get("body") or "").strip()[:TEXT_LIMIT]
                if not body: return h.sendj({"error": "A message can't be empty."}, 400)
                if msg["kind"] != "text": return h.sendj({"error": "Only text messages can be edited."}, 400)
                c.execute("UPDATE fc_messages SET body=?,edited_at=? WHERE id=?", (body, stamp, mid))
                c.execute("UPDATE fc_conversations SET updated_at=? WHERE id=?", (stamp, msg["conversation_id"]))
                return h.sendj({"ok": True})
            c.execute("UPDATE fc_messages SET deleted_at=?,body='',meta='{}' WHERE id=?", (stamp, mid))
            c.execute("DELETE FROM fc_attachments WHERE message_id=?", (mid,))
            return h.sendj({"ok": True})
    if path == "/api/fc/read":
        conv_id = int(d.get("c") or 0); last = int(d.get("last") or 0)
        with A.conn() as c:
            _require_member(c, conv_id, u)
            c.execute("UPDATE fc_members SET last_read_id=? WHERE conversation_id=? AND user_id=? AND last_read_id<?", (last, conv_id, uid, last))
        return h.sendj({"ok": True})
    if path == "/api/fc/settings":
        conv_id = int(d.get("c") or 0)
        with A.conn() as c:
            _require_member(c, conv_id, u)
            for k in ("archived", "muted", "pinned"):
                if k in d: c.execute("UPDATE fc_members SET " + k + "=? WHERE conversation_id=? AND user_id=?", (1 if d[k] else 0, conv_id, uid))
            if "title" in d:
                conv = c.execute("SELECT kind FROM fc_conversations WHERE id=?", (conv_id,)).fetchone()
                t = str(d.get("title") or "").strip()[:60]
                if conv and conv["kind"] == "group" and t: c.execute("UPDATE fc_conversations SET title=? WHERE id=?", (t, conv_id))
            if d.get("leave"):
                conv = c.execute("SELECT kind FROM fc_conversations WHERE id=?", (conv_id,)).fetchone()
                if conv and conv["kind"] == "group":
                    c.execute("DELETE FROM fc_members WHERE conversation_id=? AND user_id=?", (conv_id, uid))
                    c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,created_at) VALUES(?,?,?,?,?)", (conv_id, uid, u["name"] + " left", "system", stamp))
        return h.sendj({"ok": True})
    if path == "/api/fc/add-members":
        conv_id = int(d.get("c") or 0)
        with A.conn() as c:
            m = _require_member(c, conv_id, u)
            conv = c.execute("SELECT kind FROM fc_conversations WHERE id=?", (conv_id,)).fetchone()
            if not conv or conv["kind"] != "group": return h.sendj({"error": "Only groups can have members added."}, 400)
            added = []
            for p in (d.get("phones") or [])[:100]:
                ph = normalize_phone(p)
                r = c.execute("SELECT id,name FROM users WHERE phone_e164=? AND phone_verified_at<>''", (ph,)).fetchone() if ph else None
                if r and not _member(c, conv_id, int(r["id"])):
                    c.execute("INSERT INTO fc_members(conversation_id,user_id,joined_at) VALUES(?,?,?)", (conv_id, int(r["id"]), stamp)); added.append(r["name"])
            if added:
                mid = c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,created_at) VALUES(?,?,?,?,?) RETURNING id",
                                (conv_id, uid, u["name"] + " added " + ", ".join(added), "system", stamp)).fetchone()["id"]
                c.execute("UPDATE fc_conversations SET last_message_id=?,updated_at=? WHERE id=?", (mid, stamp, conv_id))
        return h.sendj({"ok": True, "added": added})
    if path == "/api/fc/report":
        conv_id = int(d.get("c") or 0); reason = str(d.get("reason") or "Report")[:80]
        with A.conn() as c:
            _require_member(c, conv_id, u)
            rows = c.execute("SELECT m.sender_id,u2.name,m.body,m.kind,m.created_at FROM fc_messages m JOIN users u2 ON u2.id=m.sender_id WHERE m.conversation_id=? ORDER BY m.id DESC LIMIT 20", (conv_id,)).fetchall()[::-1]
        lines = "\n".join("[%s] %s (#%s): %s" % (r["created_at"][:16], r["name"], r["sender_id"], (r["body"] or r["kind"])[:300]) for r in rows)
        A.notify("complaint", "Future Chat report: " + reason, "Reported by %s (#%d) in conversation #%d.\n\nRecent messages:\n%s" % (u["name"], uid, conv_id, lines))
        return h.sendj({"ok": True})
    if path == "/api/phone/verify":
        return _verify_phone(h, u, d)
    return h.sendj({"error": "Not found"}, 404)


# ---------------------------------------------------------------- phone verification (Firebase Authentication)
def _firebase_app():
    import firebase_admin
    from firebase_admin import credentials
    try: return firebase_admin.get_app("skillvaya_fcm")
    except ValueError:
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw: raise RuntimeError("Phone verification is not configured on the server.")
        return firebase_admin.initialize_app(credentials.Certificate(json.loads(raw)), name="skillvaya_fcm")


def _verify_phone(h, u, d):
    token = str(d.get("id_token") or "").strip()
    if not token: return h.sendj({"error": "Verification code missing."}, 400)
    try:
        from firebase_admin import auth
        claims = auth.verify_id_token(token, app=_firebase_app(), check_revoked=False)
    except Exception as exc:
        print("Phone verification failed:", type(exc).__name__)
        return h.sendj({"error": "We couldn't confirm that code. Please request a new one."}, 400)
    phone = str(claims.get("phone_number") or "")
    if not phone.startswith("+"): return h.sendj({"error": "That verification wasn't for a phone number."}, 400)
    uid = int(u["id"])
    with A.conn() as c:
        other = c.execute("SELECT id FROM users WHERE phone_e164=? AND phone_verified_at<>'' AND id<>?", (phone, uid)).fetchone()
        if other: return h.sendj({"error": "This number is already linked to another Skillvaya account."}, 409)
        c.execute("UPDATE users SET phone=?,phone_e164=?,phone_verified_at=? WHERE id=?", (phone, phone, A.now(), uid))
    return h.sendj({"ok": True, "phone": phone, "verified": True})
