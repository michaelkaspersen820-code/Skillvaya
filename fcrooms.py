"""FCR-01 (owner 2026-11-19): Future Chat Game Rooms - talk by voice with your squad while you play, without leaving the game.

- A Game Room is a voice room for up to 6 people (WebRTC mesh: every phone sends its voice straight to every other phone,
  through the TURN relay when a network blocks direct connections). Voice only, mono Opus around 24 kbps (low data).
- Rooms are kept (your squad's room stays in your list) and anyone with the room code / invite link can join while
  there is space. The person who made the room can remove someone or close the room.
- Signalling (offer / answer / ICE candidates) goes through this server, the same way Future Chat calls do; the voice
  itself never touches the server and nothing is recorded.
- Safety: the existing rules apply - banned accounts can't create rooms or send invites, people who blocked each other
  can't be in the same room, and a teen can only join a room made by someone they already chat with one-to-one
  (same rule as being added to a group).
app.py: bind(globals()); init(c); routes /api/fcr/*.  Client: static/futurechat/fcrooms.js. Android: GameVoiceService.
"""
import datetime, json, re, secrets, threading, time, urllib.parse

A = None
MAX_PEOPLE = 6
PRESENT = 45            # seconds without a heartbeat before someone counts as gone
SIGNAL_TTL = 180
OWN_ROOMS_MAX = 20
INVITE_CHATS_MAX = 10
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
GAMES = ["Free Fire", "PUBG Mobile", "Call of Duty Mobile", "Roblox", "Minecraft", "EA FC", "Fortnite", "Mobile Legends",
         "Clash Royale", "Among Us", "eFootball", "Genshin Impact", "Brawl Stars", "Other"]


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)


def init(c):
    pk = A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS fcr_rooms(id %(pk)s, code TEXT NOT NULL UNIQUE, title TEXT NOT NULL, game TEXT NOT NULL DEFAULT '',
            owner_id BIGINT NOT NULL, created_at TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0, last_active DOUBLE PRECISION NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_fcr_rooms_owner ON fcr_rooms(owner_id);
        CREATE TABLE IF NOT EXISTS fcr_members(room_id BIGINT NOT NULL, user_id BIGINT NOT NULL, joined_at TEXT NOT NULL, seen DOUBLE PRECISION NOT NULL DEFAULT 0,
            muted INTEGER NOT NULL DEFAULT 0, talking INTEGER NOT NULL DEFAULT 0, removed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(room_id, user_id));
        CREATE INDEX IF NOT EXISTS idx_fcr_members_user ON fcr_members(user_id);
        CREATE TABLE IF NOT EXISTS fcr_signals(id %(pk)s, room_id BIGINT NOT NULL, from_id BIGINT NOT NULL, to_id BIGINT NOT NULL, kind TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '', at DOUBLE PRECISION NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_fcr_signals_to ON fcr_signals(room_id, to_id, id);
    """ % {"pk": pk})
    threading.Thread(target=_loop, name="FutureChatRooms", daemon=True).start()


def _loop():
    while True:
        time.sleep(60)
        try:
            with A.conn() as c:
                c.execute("DELETE FROM fcr_signals WHERE at<?", (time.time() - SIGNAL_TTL,))
        except Exception as exc:
            print("Future Chat rooms sweep skipped:", type(exc).__name__)


# ---------------------------------------------------------------- helpers
def _FX():
    import fcextras; return fcextras


def _site():
    try:
        import fcgive; return fcgive.SITE
    except Exception: return "https://futurechat-v5lx.onrender.com"


def _code(c):
    for _ in range(40):
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(6))
        if not c.execute("SELECT 1 FROM fcr_rooms WHERE code=?", (code,)).fetchone(): return code
    raise RuntimeError("no free room code")


def _clean_code(v):
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())[:8]


def _room(c, code):
    return c.execute("SELECT * FROM fcr_rooms WHERE code=?", (_clean_code(code),)).fetchone()


def _banned(c, uid):
    try:
        import fcadmin
        b = fcadmin.ban_of(c, uid)
        return fcadmin._ban_msg(b) if b else ""
    except Exception: return ""


def _present(c, room_id, now=None):
    now = now or time.time()
    return c.execute("SELECT m.user_id,m.muted,m.talking,m.seen,u.name,u.profile_photo FROM fcr_members m JOIN users u ON u.id=m.user_id"
                     " WHERE m.room_id=? AND m.removed=0 AND m.seen>? ORDER BY m.joined_at", (room_id, now - PRESENT)).fetchall()


def _person(c, r, me):
    uid = int(r["user_id"]); photo = ""
    try:
        if r["profile_photo"] and _FX().prefs(c, uid).get("photo") != "nobody":
            photo = "/api/fcx/avatar/%d?v=%s" % (uid, _FX()._photo_version(r["profile_photo"]))
    except Exception: pass
    return {"id": uid, "name": r["name"] or "Someone", "photo": photo, "muted": bool(r["muted"]), "talking": bool(r["talking"]), "me": uid == me}


def _room_out(c, room, uid, now=None):
    live = _present(c, int(room["id"]), now)
    owner = c.execute("SELECT name FROM users WHERE id=?", (int(room["owner_id"]),)).fetchone()
    return {"code": room["code"], "title": room["title"], "game": room["game"], "owner_id": int(room["owner_id"]),
            "owner": owner["name"] if owner else "", "mine": int(room["owner_id"]) == uid, "closed": bool(room["closed"]),
            "live": [_person(c, r, uid) for r in live], "count": len(live), "max": MAX_PEOPLE,
            "link": _site() + "/?room=" + room["code"], "last_active": float(room["last_active"] or 0)}


def _can_enter(c, room, uid):
    """Why this person can't be in the room right now, or '' when they can."""
    if room["closed"]: return "This game room was closed by the person who made it."
    m = c.execute("SELECT removed FROM fcr_members WHERE room_id=? AND user_id=?", (int(room["id"]), uid)).fetchone()
    if m and m["removed"]: return "You were removed from this game room."
    owner = int(room["owner_id"])
    try:
        import fcfamily
        if not fcfamily.can_add(c, owner, uid):
            return "For your safety, you can only join game rooms made by people you already chat with."
    except Exception: pass
    FX = _FX()
    for r in _present(c, int(room["id"])):
        o = int(r["user_id"])
        if o != uid and FX.blocked_between(c, uid, o): return "You can't join this game room."
    return ""


# ---------------------------------------------------------------- GET
def handle_get(h, path):
    u = h.require(); uid = int(u["id"])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    if path == "/api/fcr/rooms":
        with A.conn() as c:
            rows = c.execute("SELECT r.* FROM fcr_rooms r JOIN fcr_members m ON m.room_id=r.id AND m.user_id=? AND m.removed=0"
                             " WHERE r.closed=0 ORDER BY r.last_active DESC LIMIT 30", (uid,)).fetchall()
            now = time.time()
            rooms = [_room_out(c, r, uid, now) for r in rows]
        rooms.sort(key=lambda r: (-(r["count"] > 0), -r["last_active"]))
        return h.sendj({"rooms": rooms, "max": MAX_PEOPLE, "games": GAMES})
    if path == "/api/fcr/room":
        with A.conn() as c:
            room = _room(c, (q.get("code") or [""])[0])
            if not room: return h.sendj({"error": "We couldn't find that game room. Check the code."}, 404)
            out = _room_out(c, room, uid)
            out["why_not"] = _can_enter(c, room, uid)
        return h.sendj({"room": out})
    return h.sendj({"error": "Not found"}, 404)


# ---------------------------------------------------------------- POST
def handle_post(h, path, d):
    d = d or {}
    u = h.require(); uid = int(u["id"]); now = time.time()
    if path == "/api/fcr/create":
        title = re.sub(r"\s+", " ", str(d.get("title") or "")).strip()[:40]
        game = re.sub(r"\s+", " ", str(d.get("game") or "")).strip()[:30]
        if not title: title = ((u.get("name") or "My").split(" ")[0] + "'s squad")[:40]
        with A.conn() as c:
            why = _banned(c, uid)
            if why: return h.sendj({"error": why}, 403)
            n = c.execute("SELECT COUNT(*) AS n FROM fcr_rooms WHERE owner_id=? AND closed=0", (uid,)).fetchone()["n"]
            if int(n) >= OWN_ROOMS_MAX: return h.sendj({"error": "You already have %d game rooms. Close one you don't use any more first." % OWN_ROOMS_MAX}, 400)
            code = _code(c); stamp = A.now()
            rid = c.execute("INSERT INTO fcr_rooms(code,title,game,owner_id,created_at,last_active) VALUES(?,?,?,?,?,?) RETURNING id",
                            (code, title, game, uid, stamp, now)).fetchone()["id"]
            c.execute("INSERT INTO fcr_members(room_id,user_id,joined_at,seen) VALUES(?,?,?,0)", (rid, uid, stamp))
            room = _room(c, code)
            return h.sendj({"ok": True, "room": _room_out(c, room, uid, now)})

    code = _clean_code(d.get("code"))
    with A.conn() as c:
        room = _room(c, code)
        if not room: return h.sendj({"error": "We couldn't find that game room. Check the code.", "gone": True}, 404)
        rid = int(room["id"]); owner = int(room["owner_id"])
        mem = c.execute("SELECT * FROM fcr_members WHERE room_id=? AND user_id=?", (rid, uid)).fetchone()

        if path == "/api/fcr/join":
            why = _can_enter(c, room, uid)
            if why: return h.sendj({"error": why, "gone": True}, 403)
            live = [r for r in _present(c, rid, now) if int(r["user_id"]) != uid]
            if len(live) >= MAX_PEOPLE:
                return h.sendj({"error": "This game room is full (%d people). Try again when someone leaves." % MAX_PEOPLE, "full": True}, 409)
            c.execute("DELETE FROM fcr_signals WHERE room_id=? AND (to_id=? OR from_id=?)", (rid, uid, uid))
            if mem:
                c.execute("UPDATE fcr_members SET seen=?,muted=?,talking=0 WHERE room_id=? AND user_id=?", (now, 1 if d.get("muted") else 0, rid, uid))
            else:
                c.execute("INSERT INTO fcr_members(room_id,user_id,joined_at,seen,muted) VALUES(?,?,?,?,?)", (rid, uid, A.now(), now, 1 if d.get("muted") else 0))
            c.execute("UPDATE fcr_rooms SET last_active=? WHERE id=?", (now, rid))
            last = c.execute("SELECT MAX(id) AS m FROM fcr_signals").fetchone()["m"] or 0
            out = _room_out(c, room, uid, now)
            return h.sendj({"ok": True, "room": out, "me": uid, "after": int(last), "iceServers": A.build_ice_servers(u)})

        if not mem or mem["removed"]:
            return h.sendj({"error": "You're not in this game room any more.", "gone": True}, 403 if mem else 404)

        if path == "/api/fcr/beat":
            if room["closed"]: return h.sendj({"gone": True, "closed": True, "error": "The game room was closed."})
            c.execute("UPDATE fcr_members SET seen=?,muted=?,talking=? WHERE room_id=? AND user_id=?",
                      (now, 1 if d.get("muted") else 0, 1 if d.get("talking") else 0, rid, uid))
            c.execute("UPDATE fcr_rooms SET last_active=? WHERE id=?", (now, rid))
            after = int(d.get("after") or 0)
            sig = c.execute("SELECT id,from_id,kind,body FROM fcr_signals WHERE room_id=? AND to_id=? AND id>? ORDER BY id LIMIT 200", (rid, uid, after)).fetchall()
            live = _present(c, rid, now)
            return h.sendj({"ok": True, "members": [_person(c, r, uid) for r in live], "title": room["title"], "game": room["game"],
                            "signals": [{"id": int(s["id"]), "from": int(s["from_id"]), "kind": s["kind"], "body": s["body"]} for s in sig]})

        if path == "/api/fcr/signal":
            items = d.get("items") if isinstance(d.get("items"), list) else [d]
            live = {int(r["user_id"]) for r in _present(c, rid, now)}
            n = 0
            for it in items[:60]:
                to = int((it or {}).get("to") or 0); kind = str((it or {}).get("kind") or "")
                body = (it or {}).get("body"); body = body if isinstance(body, str) else json.dumps(body or {})
                if kind not in ("offer", "answer", "cand", "bye") or to == uid or to not in live or len(body) > 30000: continue
                c.execute("INSERT INTO fcr_signals(room_id,from_id,to_id,kind,body,at) VALUES(?,?,?,?,?,?)", (rid, uid, to, kind, body, now)); n += 1
            return h.sendj({"ok": True, "sent": n})

        if path == "/api/fcr/leave":
            c.execute("UPDATE fcr_members SET seen=0,talking=0 WHERE room_id=? AND user_id=?", (rid, uid))
            for r in _present(c, rid, now):
                o = int(r["user_id"])
                if o != uid: c.execute("INSERT INTO fcr_signals(room_id,from_id,to_id,kind,body,at) VALUES(?,?,?,?,?,?)", (rid, uid, o, "bye", "{}", now))
            if d.get("forget") and owner != uid:   # "Remove from my list"
                c.execute("DELETE FROM fcr_members WHERE room_id=? AND user_id=?", (rid, uid))
            return h.sendj({"ok": True})

        if path == "/api/fcr/invite":
            why = _banned(c, uid)
            if why: return h.sendj({"error": why}, 403)
            chats = [int(x) for x in (d.get("chats") or []) if str(x).isdigit()][:INVITE_CHATS_MAX]
            if not chats: return h.sendj({"error": "Choose who to invite."}, 400)
            first = (u.get("name") or "").split(" ")[0]
            link = _site() + "/?room=" + room["code"] + ("&n=" + urllib.parse.quote(first) if first else "")
            body = "🎮 Join my game room \"%s\"%s on Future Chat. Talk while we play: %s" % (room["title"], (" (" + room["game"] + ")") if room["game"] else "", link)
            meta = {"room": {"code": room["code"], "title": room["title"], "game": room["game"]}}
            sent = []; stamp = A.now()
            for cid in chats:
                if not c.execute("SELECT 1 FROM fc_members WHERE conversation_id=? AND user_id=?", (cid, uid)).fetchone(): continue
                mid = c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,meta,created_at) VALUES(?,?,?,?,?,?) RETURNING id",
                                (cid, uid, body, "text", json.dumps(meta), stamp)).fetchone()["id"]
                c.execute("UPDATE fc_conversations SET last_message_id=?,updated_at=? WHERE id=?", (mid, stamp, cid))
                c.execute("UPDATE fc_members SET archived=0 WHERE conversation_id=?", (cid,))
                try: c.execute("UPDATE fc_members SET hidden=0 WHERE conversation_id=?", (cid,))
                except Exception: pass
                c.execute("UPDATE fc_members SET last_read_id=? WHERE conversation_id=? AND user_id=?", (mid, cid, uid))
                sent.append(cid)
        if path == "/api/fcr/invite":
            try:
                import futurechat as FCm
                for cid in sent: FCm._push(cid, u, "🎮 Join my game room: " + room["title"])
            except Exception: pass
            return h.sendj({"ok": True, "sent": len(sent)})

        if owner != uid and path in ("/api/fcr/remove", "/api/fcr/close", "/api/fcr/rename"):
            return h.sendj({"error": "Only the person who made the room can do that."}, 403)
        if path == "/api/fcr/remove":
            who = int(d.get("user") or 0)
            if who == uid: return h.sendj({"error": "You can't remove yourself. Close the room instead."}, 400)
            c.execute("UPDATE fcr_members SET removed=1,seen=0,talking=0 WHERE room_id=? AND user_id=?", (rid, who))
            for r in _present(c, rid, now):
                o = int(r["user_id"])
                if o != who: c.execute("INSERT INTO fcr_signals(room_id,from_id,to_id,kind,body,at) VALUES(?,?,?,?,?,?)", (rid, who, o, "bye", "{}", now))
            return h.sendj({"ok": True})
        if path == "/api/fcr/close":
            c.execute("UPDATE fcr_rooms SET closed=1 WHERE id=?", (rid,))
            return h.sendj({"ok": True})
        if path == "/api/fcr/rename":
            title = re.sub(r"\s+", " ", str(d.get("title") or "")).strip()[:40]
            game = re.sub(r"\s+", " ", str(d.get("game") or "")).strip()[:30]
            if not title: return h.sendj({"error": "Give the room a name."}, 400)
            c.execute("UPDATE fcr_rooms SET title=?,game=? WHERE id=?", (title, game, rid))
            return h.sendj({"ok": True})
    return h.sendj({"error": "Not found"}, 404)
