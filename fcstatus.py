"""FCSTATUS-01: Future Chat Status.

* Everyone can post a text or photo/video status that disappears after 24 hours (media is wiped from the server then).
* Statuses are shown to the people you chat with (members of your Future Chat conversations).
* ONE "Sponsored" status in everyone's list rotates through the approved, paid business ads (home_ads, bought through
  Google Play and approved by the owner), so ads never clog the status list. Ads are the same for everyone: no tracking.
"""
import base64, datetime, json, re, urllib.parse

A = None
MAX_MEDIA = 3 * 1024 * 1024
MAX_ACTIVE = 30
HOURS = 24
MIMES = {"image/jpeg", "image/png", "image/webp", "video/mp4", "video/webm"}
BGS = {"#0b2447", "#0d6f86", "#7b2cbf", "#c2185b", "#2e7d32", "#ef6c00", "#263238"}


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)


def init(c):
    pk = A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS fc_statuses(id %(pk)s, user_id BIGINT NOT NULL, kind TEXT NOT NULL DEFAULT 'text',
            body TEXT NOT NULL DEFAULT '', bg TEXT NOT NULL DEFAULT '#0b2447', media_mime TEXT NOT NULL DEFAULT '', media_b64 TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL, deleted_at TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS idx_fc_status_user ON fc_statuses(user_id, expires_at);
        CREATE INDEX IF NOT EXISTS idx_fc_status_exp ON fc_statuses(expires_at);
        CREATE TABLE IF NOT EXISTS fc_status_views(status_id BIGINT NOT NULL, user_id BIGINT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(status_id, user_id));
    """ % {"pk": pk})


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _sweep(c):
    # Expired or deleted statuses lose their photo/video straight away; the row itself goes after a week.
    now = _now().isoformat()
    c.execute("UPDATE fc_statuses SET media_b64='' WHERE media_b64<>'' AND (expires_at<? OR deleted_at<>'')", (now,))
    old = (_now() - datetime.timedelta(days=7)).isoformat()
    c.execute("DELETE FROM fc_status_views WHERE status_id IN (SELECT id FROM fc_statuses WHERE expires_at<?)", (old,))
    c.execute("DELETE FROM fc_statuses WHERE expires_at<?", (old,))


def _contacts(c, uid):
    rows = c.execute("SELECT DISTINCT o.user_id AS uid FROM fc_members m JOIN fc_members o ON o.conversation_id=m.conversation_id "
                     "WHERE m.user_id=? AND o.user_id<>?", (uid, uid)).fetchall()
    return {int(r["uid"]) for r in rows}


def _item(r, mine=False, viewed=False, views=0):
    d = {"id": int(r["id"]), "kind": r["kind"], "body": r["body"], "bg": r["bg"], "at": r["created_at"], "expires_at": r["expires_at"],
         "media": ("/api/fc/status/media/%d" % int(r["id"])) if r["media_mime"] else "", "mime": r["media_mime"], "viewed": bool(viewed)}
    if mine: d["views"] = int(views)
    return d


def _sponsored():
    try:
        import homeads as HA
        with A.conn() as c:
            HA._expire(c)
            rows = c.execute("SELECT " + HA.COLS + " FROM home_ads WHERE status='active' ORDER BY starts_at DESC LIMIT 20").fetchall()
        return [HA._public(r) for r in rows]
    except Exception as exc:
        print("Future Chat sponsored status skipped:", type(exc).__name__)
        return []


def handle_get(h, path):
    u = h.require(); uid = int(u["id"])
    if path == "/api/fc/statuses":
        now = _now().isoformat()
        with A.conn() as c:
            _sweep(c)
            friends = _contacts(c, uid)
            ids = sorted(friends | {uid})
            rows = []
            if ids:
                marks = ",".join("?" * len(ids))
                rows = c.execute("SELECT s.id,s.user_id,s.kind,s.body,s.bg,s.media_mime,s.created_at,s.expires_at,u.name,"
                                 " (SELECT COUNT(*) FROM fc_status_views v WHERE v.status_id=s.id) AS views,"
                                 " (SELECT COUNT(*) FROM fc_status_views v WHERE v.status_id=s.id AND v.user_id=?) AS seen"
                                 " FROM fc_statuses s JOIN users u ON u.id=s.user_id"
                                 " WHERE s.user_id IN (" + marks + ") AND s.deleted_at='' AND s.expires_at>? ORDER BY s.created_at",
                                 [uid] + ids + [now]).fetchall()
        mine, people = [], {}
        try:
            import fcextras as FX   # FCX-01: people who chose "nobody sees my status", and blocked people
            with A.conn() as c:
                hide = FX.hidden_status_owners(c, [i for i in ids if i != uid])
                hide |= {i for i in ids if i != uid and FX.blocked_between(c, uid, i)}
        except Exception:
            hide = set()
        for r in rows:
            if int(r["user_id"]) == uid: mine.append(_item(r, True, True, r["views"])); continue
            if int(r["user_id"]) in hide: continue
            p = people.setdefault(int(r["user_id"]), {"user_id": int(r["user_id"]), "name": r["name"] or "Future Chat friend", "items": [], "unseen": 0, "latest": ""})
            p["items"].append(_item(r, False, int(r["seen"] or 0) > 0))
            if not int(r["seen"] or 0): p["unseen"] += 1
            p["latest"] = max(p["latest"], r["created_at"])
        others = sorted(people.values(), key=lambda p: p["latest"], reverse=True)   # newest first
        others.sort(key=lambda p: p["unseen"] == 0)                                  # then unseen before seen (stable)
        return h.sendj({"me": {"id": uid, "name": u["name"]}, "mine": mine, "others": others, "sponsored": _sponsored()})
    m = re.fullmatch(r"/api/fc/status/media/(\d+)", path)
    if m:
        sid = int(m.group(1))
        with A.conn() as c:
            r = c.execute("SELECT user_id,media_mime,media_b64,expires_at,deleted_at FROM fc_statuses WHERE id=?", (sid,)).fetchone()
            ok = bool(r) and r["deleted_at"] == "" and r["expires_at"] > _now().isoformat() and r["media_b64"] != "" and \
                 (int(r["user_id"]) == uid or int(r["user_id"]) in _contacts(c, uid))
        if not ok: return h.sendj({"error": "This status has ended."}, 404)
        data = base64.b64decode(r["media_b64"])
        h.send_response(200); h.send_header("Content-Type", r["media_mime"]); h.send_header("Cache-Control", "private, max-age=3600")
        h.send_header("Content-Length", str(len(data))); h.end_headers(); h.wfile.write(data); return
    return h.sendj({"error": "Not found"}, 404)


def handle_post(h, path, d):
    u = h.require(); uid = int(u["id"])
    if path == "/api/fc/status":
        body = str(d.get("body") or "").strip()[:700]
        bg = str(d.get("bg") or "#0b2447")
        if bg not in BGS: bg = "#0b2447"
        mime, b64 = "", ""
        media = str(d.get("media") or "")
        if media:
            mm = re.fullmatch(r"data:([a-z]+/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)", media, re.S)
            if not mm or mm.group(1) not in MIMES: return h.sendj({"error": "Choose a photo (JPG, PNG, WebP) or a short video (MP4)."}, 400)
            mime, b64 = mm.group(1), re.sub(r"\s+", "", mm.group(2))
            try: raw = base64.b64decode(b64, validate=True)
            except Exception: return h.sendj({"error": "That file could not be read. Please try another one."}, 400)
            if len(raw) > MAX_MEDIA: return h.sendj({"error": "That file is too big for a status (3 MB maximum). Try a shorter video or a smaller photo."}, 413)
        if not body and not mime: return h.sendj({"error": "Type something or choose a photo or video for your status."}, 400)
        kind = "video" if mime.startswith("video/") else ("image" if mime else "text")
        now = _now()
        with A.conn() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM fc_statuses WHERE user_id=? AND deleted_at='' AND expires_at>?", (uid, now.isoformat())).fetchone()["n"]
            if int(n or 0) >= MAX_ACTIVE: return h.sendj({"error": "You have %d statuses showing. Delete one or wait for an older one to end." % MAX_ACTIVE}, 429)
            sid = c.execute("INSERT INTO fc_statuses(user_id,kind,body,bg,media_mime,media_b64,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",
                            (uid, kind, body, bg, mime, b64, now.isoformat(), (now + datetime.timedelta(hours=HOURS)).isoformat())).fetchone()["id"]
        return h.sendj({"ok": True, "id": int(sid)})
    if path == "/api/fc/status/view":
        try: sid = int(d.get("id") or 0)
        except (TypeError, ValueError): sid = 0
        with A.conn() as c:
            r = c.execute("SELECT user_id FROM fc_statuses WHERE id=? AND deleted_at=''", (sid,)).fetchone()
            if r and int(r["user_id"]) != uid and int(r["user_id"]) in _contacts(c, uid):
                if not c.execute("SELECT 1 FROM fc_status_views WHERE status_id=? AND user_id=?", (sid, uid)).fetchone():
                    c.execute("INSERT INTO fc_status_views(status_id,user_id,created_at) VALUES(?,?,?)", (sid, uid, _now().isoformat()))
        return h.sendj({"ok": True})
    if path == "/api/fc/status/delete":
        try: sid = int(d.get("id") or 0)
        except (TypeError, ValueError): sid = 0
        with A.conn() as c:
            c.execute("UPDATE fc_statuses SET deleted_at=?,media_b64='' WHERE id=? AND user_id=?", (_now().isoformat(), sid, uid))
        return h.sendj({"ok": True})
    return h.sendj({"error": "Not found"}, 404)
