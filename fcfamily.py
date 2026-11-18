"""FCF-01: Future Chat for families (owner 2026-11-19 "add all of that").

Family Circle home (notice board, coming up, lists, chores + stars + rewards, album, bedtime stories, games),
"I'm home safe" / "Where are you?" check-ins, emergency (SOS) alerts, family dates (anniversaries, remembrance),
and teen safety (strangers can't add 13-17 year olds to groups; parents can link to see which Circles a teen is in,
never the messages). Everything works on group chats ("Circles"). Routes: /api/fcf/*.
"""
import datetime
import json
import random
import re
import threading
import time
import urllib.parse

A = None
FX = None


def bind(ns):
    global A, FX
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)
    import fcextras as _fx
    FX = _fx


def init(c):
    pk = A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS fcf_circle(conversation_id BIGINT PRIMARY KEY, notice TEXT NOT NULL DEFAULT '', notice_by BIGINT NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS fcf_list_entries(id %(pk)s, item_id BIGINT NOT NULL, text TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, done_by BIGINT NOT NULL DEFAULT 0,
            added_by BIGINT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_fcf_list_item ON fcf_list_entries(item_id);
        CREATE TABLE IF NOT EXISTS fcf_stars(conversation_id BIGINT NOT NULL, user_id BIGINT NOT NULL, points INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(conversation_id, user_id));
        CREATE TABLE IF NOT EXISTS fcf_game_scores(item_id BIGINT NOT NULL, user_id BIGINT NOT NULL, score INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(item_id, user_id));
        CREATE TABLE IF NOT EXISTS fcf_dates(id %(pk)s, user_id BIGINT NOT NULL, conversation_id BIGINT NOT NULL DEFAULT 0, kind TEXT NOT NULL, title TEXT NOT NULL,
            d INTEGER NOT NULL, m INTEGER NOT NULL, y INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fcf_links(id %(pk)s, parent_id BIGINT NOT NULL, teen_id BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fcf_sent(user_id BIGINT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY(user_id, day, kind));
    """ % {"pk": pk})
    threading.Thread(target=_loop, name="FutureChatFamily", daemon=True).start()


# ---------------------------------------------------------------- helpers
def _now(): return datetime.datetime.now(datetime.timezone.utc)
def _member(c, cid, uid): return bool(c.execute("SELECT 1 FROM fc_members WHERE conversation_id=? AND user_id=?", (cid, uid)).fetchone())


def _members(c, cid):
    rows = c.execute("SELECT u.id,u.name,u.profile_photo FROM fc_members m JOIN users u ON u.id=m.user_id WHERE m.conversation_id=? ORDER BY u.name", (cid,)).fetchall()
    out = []
    for r in rows:
        p = FX.prefs(c, int(r["id"]))
        out.append({"id": int(r["id"]), "name": r["name"] or "Member",
                    "photo": ("/api/fcx/avatar/%d?v=%s" % (int(r["id"]), FX._photo_version(r["profile_photo"]))) if r["profile_photo"] and p.get("photo") != "nobody" else "",
                    "birthday": {"d": p["birthday"]["d"], "m": p["birthday"]["m"]} if (p.get("birthday") or {}).get("d") and p.get("birthday_vis") != "nobody" else None})
    return out


def _post(c, cid, u, body, meta, kind="text"):
    stamp = A.now()
    mid = c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,meta,created_at) VALUES(?,?,?,?,?,?) RETURNING id",
                    (cid, int(u["id"]), body, kind, json.dumps(meta), stamp)).fetchone()["id"]
    c.execute("UPDATE fc_conversations SET last_message_id=?,updated_at=? WHERE id=?", (mid, stamp, cid))
    c.execute("UPDATE fc_members SET last_read_id=? WHERE conversation_id=? AND user_id=?", (mid, cid, int(u["id"])))
    c.execute("UPDATE fc_members SET archived=0 WHERE conversation_id=?", (cid,))
    return int(mid)


def _push(cid, u, text):
    try: A.FC._push(cid, u, text)
    except Exception as exc: print("Future Chat family push skipped:", type(exc).__name__)


def _age(c, uid):
    b = FX.prefs(c, uid).get("birthday") or {}
    if not b.get("y"): return None
    t = _now().date()
    return t.year - int(b["y"]) - ((t.month, t.day) < (int(b["m"]), int(b["d"])))


def is_teen(c, uid):
    if FX.prefs(c, uid).get("teen_safe") is True: return True
    a = _age(c, uid)
    if a is not None and a < 18: return True
    return bool(c.execute("SELECT 1 FROM fcf_links WHERE teen_id=? AND status='active'", (uid,)).fetchone())


def can_add(c, adder, target):
    """Teen safety: a 13-17 year old can only be added to a group by someone they already chat with one-to-one."""
    try:
        if adder == target or not is_teen(c, target): return True
        if c.execute("SELECT 1 FROM fcf_links WHERE parent_id=? AND teen_id=? AND status='active'", (adder, target)).fetchone(): return True
        return bool(c.execute("SELECT 1 FROM fc_members a JOIN fc_members b ON b.conversation_id=a.conversation_id JOIN fc_conversations cv ON cv.id=a.conversation_id "
                              "WHERE a.user_id=? AND b.user_id=? AND cv.kind<>'group' LIMIT 1", (adder, target)).fetchone())
    except Exception as exc:
        print("Future Chat teen check skipped:", type(exc).__name__)
        return True


def _direct(c, a, b):
    r = c.execute("SELECT a.conversation_id FROM fc_members a JOIN fc_members b ON b.conversation_id=a.conversation_id JOIN fc_conversations cv ON cv.id=a.conversation_id "
                  "WHERE a.user_id=? AND b.user_id=? AND cv.kind<>'group' LIMIT 1", (a, b)).fetchone()
    return int(r["conversation_id"]) if r else 0


def _items(c, cid, kinds):
    marks = ",".join("?" * len(kinds))
    return c.execute("SELECT * FROM fcx_items WHERE conversation_id=? AND deleted_at='' AND kind IN (" + marks + ") ORDER BY done, id DESC LIMIT 100", [cid] + list(kinds)).fetchall()


def _opt(r):
    try: return json.loads(r["options"] or "{}") if str(r["options"] or "").startswith("{") else {}
    except ValueError: return {}


def _stars(c, cid, uid, delta):
    if c.execute("SELECT 1 FROM fcf_stars WHERE conversation_id=? AND user_id=?", (cid, uid)).fetchone():
        c.execute("UPDATE fcf_stars SET points=points+? WHERE conversation_id=? AND user_id=?", (delta, cid, uid))
    else:
        c.execute("INSERT INTO fcf_stars(conversation_id,user_id,points) VALUES(?,?,?)", (cid, uid, max(0, delta)))
    c.execute("UPDATE fcf_stars SET points=0 WHERE points<0")


# ---------------------------------------------------------------- daily: family dates (anniversaries, remembrance)
def _loop():
    time.sleep(45)
    while True:
        try: _dates_job()
        except Exception as exc: print("Future Chat family dates skipped:", type(exc).__name__)
        time.sleep(120)


def _dates_job():
    now_sa = _now() + datetime.timedelta(hours=2)
    if now_sa.hour < 8: return
    t = now_sa.date(); day = t.isoformat()
    send = getattr(A, "fcm_send_to_user", None)
    jobs = []
    with A.conn() as c:
        for r in c.execute("SELECT * FROM fcf_dates WHERE d=? AND m=?", (t.day, t.month)).fetchall():
            people = {int(r["user_id"])}
            if int(r["conversation_id"] or 0):
                people |= {int(x["user_id"]) for x in c.execute("SELECT user_id FROM fc_members WHERE conversation_id=?", (int(r["conversation_id"]),)).fetchall()}
            for p in people:
                key = "date:%d" % int(r["id"])
                if c.execute("SELECT 1 FROM fcf_sent WHERE user_id=? AND day=? AND kind=?", (p, day, key)).fetchone(): continue
                c.execute("INSERT INTO fcf_sent(user_id,day,kind) VALUES(?,?,?)", (p, day, key))
                jobs.append((p, r["kind"], r["title"], int(r["conversation_id"] or 0)))
    if not send: return
    for p, kind, title, cid in jobs:
        if not FX.allow_push(p, "message")[0]: continue
        head = {"anniversary": "\U0001f48d ", "remembrance": "\U0001f56f️ "}.get(kind, "\U0001f389 ")
        body = "Remembering today. Share a memory with your family." if kind == "remembrance" else "A special day today — send your love on Future Chat."
        try: send(p, head + title, body, {"type": "fc_date", "conversation_id": str(cid) if cid else "", "url": "/futurechat-app" + ("?fc=%d" % cid if cid else "")})
        except Exception as exc: print("Future Chat family date push failed:", type(exc).__name__)


# ---------------------------------------------------------------- GET
def handle_get(h, path):
    u = h.require(); uid = int(u["id"])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    cid = int((q.get("c") or ["0"])[0] or 0)
    if path == "/api/fcf/circle":
        with A.conn() as c:
            if not _member(c, cid, uid): return h.sendj({"error": "You are not part of this Circle."}, 403)
            cv = c.execute("SELECT title,kind FROM fc_conversations WHERE id=?", (cid,)).fetchone()
            members = _members(c, cid)
            nb = c.execute("SELECT notice,notice_by,updated_at FROM fcf_circle WHERE conversation_id=?", (cid,)).fetchone()
            lists = []
            for r in _items(c, cid, ("list",)):
                es = c.execute("SELECT COUNT(*) AS n, SUM(done) AS d FROM fcf_list_entries WHERE item_id=?", (int(r["id"]),)).fetchone()
                lists.append({"id": int(r["id"]), "title": r["title"], "count": int(es["n"] or 0), "done": int(es["d"] or 0)})
            names = {m["id"]: m["name"] for m in members}
            chores = []
            for r in _items(c, cid, ("chore",)):
                o = _opt(r); chores.append({"id": int(r["id"]), "title": r["title"], "done": bool(r["done"]), "stars": int(o.get("stars") or 1),
                                            "assignee": int(o.get("assignee") or 0), "assignee_name": names.get(int(o.get("assignee") or 0), "Anyone"), "due_at": r["due_at"]})
            rewards = [{"id": int(r["id"]), "title": r["title"], "cost": int(_opt(r).get("cost") or 5)} for r in _items(c, cid, ("reward",)) if not r["done"]]
            board = {int(r["user_id"]): int(r["points"]) for r in c.execute("SELECT user_id,points FROM fcf_stars WHERE conversation_id=?", (cid,)).fetchall()}
            coming = [FX._item_out(c, r, uid) for r in c.execute("SELECT * FROM fcx_items WHERE conversation_id=? AND deleted_at='' AND done=0 AND due_at<>'' AND due_at>=? AND kind IN ('event','reminder','task','chore') ORDER BY due_at LIMIT 8",
                                                                (cid, (_now() - datetime.timedelta(hours=12)).isoformat())).fetchall()]
            dates = [{"id": int(r["id"]), "kind": r["kind"], "title": r["title"], "d": int(r["d"]), "m": int(r["m"])} for r in c.execute("SELECT * FROM fcf_dates WHERE conversation_id=?", (cid,)).fetchall()]
            games = [{"id": int(r["id"]), "title": r["title"], "at": r["created_at"]} for r in _items(c, cid, ("game",))][:5]
            stories = [{"id": int(r["id"]), "title": (json.loads(r["meta"] or "{}").get("story") or {}).get("t") or "Story", "by": r["name"], "at": r["created_at"],
                        "att": [int(a["id"]) for a in c.execute("SELECT id FROM fc_attachments WHERE message_id=?", (int(r["id"]),)).fetchall()]}
                       for r in c.execute("SELECT x.id,x.meta,x.created_at,u.name FROM fc_messages x JOIN users u ON u.id=x.sender_id WHERE x.conversation_id=? AND x.deleted_at='' "
                                          "AND x.meta LIKE '%%\"story\"%%' ORDER BY x.id DESC LIMIT 30", (cid,)).fetchall()]
        return h.sendj({"id": cid, "title": cv["title"] if cv else "", "group": bool(cv and cv["kind"] == "group"), "members": members,
                        "notice": {"text": nb["notice"], "by": names.get(int(nb["notice_by"] or 0), ""), "at": nb["updated_at"]} if nb and nb["notice"] else None,
                        "lists": lists, "chores": chores, "rewards": rewards, "stars": [{"user_id": k, "name": names.get(k, "Member"), "points": v} for k, v in sorted(board.items(), key=lambda x: -x[1])],
                        "my_stars": board.get(uid, 0), "coming": coming, "dates": dates, "games": games, "stories": stories})
    m = re.fullmatch(r"/api/fcf/list/(\d+)", path)
    if m:
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcx_items WHERE id=? AND kind='list' AND deleted_at=''", (int(m.group(1)),)).fetchone()
            if not r or not _member(c, int(r["conversation_id"]), uid): return h.sendj({"error": "This list was removed."}, 404)
            es = c.execute("SELECT e.*,u.name FROM fcf_list_entries e LEFT JOIN users u ON u.id=e.added_by WHERE e.item_id=? ORDER BY e.done, e.id", (int(r["id"]),)).fetchall()
        return h.sendj({"id": int(r["id"]), "title": r["title"], "conversation_id": int(r["conversation_id"]), "mine": int(r["owner_id"]) == uid,
                        "entries": [{"id": int(e["id"]), "text": e["text"], "done": bool(e["done"]), "by": e["name"] or ""} for e in es]})
    m = re.fullmatch(r"/api/fcf/game/(\d+)", path)
    if m:
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcx_items WHERE id=? AND kind='game'", (int(m.group(1)),)).fetchone()
            if not r or not _member(c, int(r["conversation_id"]), uid): return h.sendj({"error": "This game has ended."}, 404)
            sc = c.execute("SELECT s.user_id,s.score,u.name FROM fcf_game_scores s JOIN users u ON u.id=s.user_id WHERE s.item_id=? ORDER BY s.score DESC", (int(r["id"]),)).fetchall()
        o = _opt(r)
        return h.sendj({"id": int(r["id"]), "pack": o.get("pack", "gk"), "qs": o.get("qs", []), "scores": [{"name": s["name"], "score": int(s["score"]), "me": int(s["user_id"]) == uid} for s in sc],
                        "played": any(int(s["user_id"]) == uid for s in sc)})
    if path == "/api/fcf/album":
        with A.conn() as c:
            if not _member(c, cid, uid): return h.sendj({"error": "You are not part of this chat."}, 403)
            rows = c.execute("SELECT a.id,a.mime_type,a.message_id,m.created_at,u.name FROM fc_attachments a JOIN fc_messages m ON m.id=a.message_id JOIN users u ON u.id=m.sender_id "
                             "WHERE a.conversation_id=? AND m.deleted_at='' AND (a.mime_type LIKE 'image/%%' OR a.mime_type LIKE 'video/%%') ORDER BY a.id DESC LIMIT 400", (cid,)).fetchall()
        return h.sendj({"items": [{"id": int(r["id"]), "video": str(r["mime_type"]).startswith("video/"), "message_id": int(r["message_id"]), "at": r["created_at"], "by": r["name"] or ""} for r in rows]})
    if path == "/api/fcf/dates":
        with A.conn() as c:
            rows = c.execute("SELECT d.*,cv.title AS ctitle FROM fcf_dates d LEFT JOIN fc_conversations cv ON cv.id=d.conversation_id WHERE d.user_id=? OR d.conversation_id IN "
                             "(SELECT conversation_id FROM fc_members WHERE user_id=?) ORDER BY d.m, d.d", (uid, uid)).fetchall()
        return h.sendj({"items": [{"id": int(r["id"]), "kind": r["kind"], "title": r["title"], "d": int(r["d"]), "m": int(r["m"]), "y": int(r["y"] or 0) if int(r["user_id"]) == uid else 0,
                                   "conversation_id": int(r["conversation_id"] or 0), "circle": r["ctitle"] or "", "mine": int(r["user_id"]) == uid} for r in rows]})
    if path == "/api/fcf/guardian":
        with A.conn() as c:
            as_parent = c.execute("SELECT l.*,u.name FROM fcf_links l JOIN users u ON u.id=l.teen_id WHERE l.parent_id=? AND l.status IN ('pending','active') ORDER BY l.id DESC", (uid,)).fetchall()
            as_teen = c.execute("SELECT l.*,u.name FROM fcf_links l JOIN users u ON u.id=l.parent_id WHERE l.teen_id=? AND l.status IN ('pending','active') ORDER BY l.id DESC", (uid,)).fetchall()
            teens = []
            for l in as_parent:
                circles = []
                if l["status"] == "active":
                    circles = [{"title": g["title"], "members": int(g["n"])} for g in c.execute(
                        "SELECT cv.title,(SELECT COUNT(*) FROM fc_members x WHERE x.conversation_id=cv.id) AS n FROM fc_members m JOIN fc_conversations cv ON cv.id=m.conversation_id "
                        "WHERE m.user_id=? AND cv.kind='group' ORDER BY cv.updated_at DESC LIMIT 50", (int(l["teen_id"]),)).fetchall()]
                teens.append({"id": int(l["id"]), "name": l["name"], "status": l["status"], "circles": circles})
            me_teen = is_teen(c, uid); p = FX.prefs(c, uid); u18 = (_age(c, uid) or 99) < 18
        return h.sendj({"teens": teens, "parents": [{"id": int(l["id"]), "name": l["name"], "status": l["status"]} for l in as_teen],
                        "i_am_teen": me_teen, "teen_safe": bool(p.get("teen_safe")), "under18": u18})
    return h.sendj({"error": "Not found"}, 404)


# ---------------------------------------------------------------- POST
def handle_post(h, path, d):
    u = h.require(); uid = int(u["id"]); d = d or {}
    cid = int(d.get("c") or 0)
    if path == "/api/fcf/notice":
        text = str(d.get("text") or "").strip()[:1000]
        with A.conn() as c:
            if not _member(c, cid, uid): return h.sendj({"error": "You are not part of this Circle."}, 403)
            if c.execute("SELECT 1 FROM fcf_circle WHERE conversation_id=?", (cid,)).fetchone():
                c.execute("UPDATE fcf_circle SET notice=?,notice_by=?,updated_at=? WHERE conversation_id=?", (text, uid, A.now(), cid))
            else:
                c.execute("INSERT INTO fcf_circle(conversation_id,notice,notice_by,updated_at) VALUES(?,?,?,?)", (cid, text, uid, A.now()))
            if text: _post(c, cid, u, "\U0001f4cc Notice board: " + text[:300], {"notice": 1})
        if text: _push(cid, u, "\U0001f4cc " + text[:120])
        return h.sendj({"ok": True})
    if path in ("/api/fcf/list", "/api/fcf/chore", "/api/fcf/reward", "/api/fcf/game"):
        kind = path.rsplit("/", 1)[1]
        title = str(d.get("title") or "").strip()[:120]
        if kind == "game": title = title or "Family quiz"
        if not title: return h.sendj({"error": "Give it a name first."}, 400)
        opts = {}
        if kind == "chore": opts = {"assignee": int(d.get("assignee") or 0), "stars": max(1, min(20, int(d.get("stars") or 1)))}
        if kind == "reward": opts = {"cost": max(1, min(500, int(d.get("cost") or 5)))}
        if kind == "game":
            qs = [int(x) for x in (d.get("qs") or []) if str(x).isdigit()][:10]
            if len(qs) < 3: return h.sendj({"error": "Choose some questions."}, 400)
            opts = {"pack": str(d.get("pack") or "gk")[:12], "qs": qs}
        due = FX._iso(d.get("due_at")) if kind == "chore" else ""
        with A.conn() as c:
            if not _member(c, cid, uid): return h.sendj({"error": "You are not part of this Circle."}, 403)
            stamp = A.now()
            iid = int(c.execute("INSERT INTO fcx_items(owner_id,conversation_id,kind,title,due_at,options,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",
                                (uid, cid, kind, title, due, json.dumps(opts), stamp, stamp)).fetchone()["id"])
            names = {m["id"]: m["name"] for m in _members(c, cid)}
            if kind == "list": body = "\U0001f6d2 New list: " + title
            elif kind == "chore": body = "\U0001f9f9 Chore for " + names.get(opts["assignee"], "anyone") + ": " + title + " (" + str(opts["stars"]) + " ⭐)"
            elif kind == "reward": body = "\U0001f381 New reward: " + title + " (" + str(opts["cost"]) + " ⭐)"
            else: body = "\U0001f3ae " + u["name"].split(" ")[0] + " started a family quiz! Tap Play"
            _post(c, cid, u, body, {"fcf": iid, "fcf_kind": kind})
        _push(cid, u, body)
        return h.sendj({"ok": True, "id": iid})
    if path == "/api/fcf/list/add" or path == "/api/fcf/list/toggle" or path == "/api/fcf/list/remove":
        with A.conn() as c:
            if path == "/api/fcf/list/add":
                r = c.execute("SELECT * FROM fcx_items WHERE id=? AND kind='list' AND deleted_at=''", (int(d.get("id") or 0),)).fetchone()
                if not r or not _member(c, int(r["conversation_id"]), uid): return h.sendj({"error": "This list was removed."}, 404)
                text = str(d.get("text") or "").strip()[:200]
                if not text: return h.sendj({"error": "Type something first."}, 400)
                c.execute("INSERT INTO fcf_list_entries(item_id,text,added_by,created_at) VALUES(?,?,?,?)", (int(r["id"]), text, uid, A.now()))
                cidl = int(r["conversation_id"]); note = u["name"].split(" ")[0] + " added " + text + " to " + r["title"]
            else:
                e = c.execute("SELECT e.*,i.conversation_id FROM fcf_list_entries e JOIN fcx_items i ON i.id=e.item_id WHERE e.id=?", (int(d.get("entry") or 0),)).fetchone()
                if not e or not _member(c, int(e["conversation_id"]), uid): return h.sendj({"error": "Not found"}, 404)
                if path.endswith("toggle"): c.execute("UPDATE fcf_list_entries SET done=?,done_by=? WHERE id=?", (0 if e["done"] else 1, uid, int(e["id"])))
                else: c.execute("DELETE FROM fcf_list_entries WHERE id=?", (int(e["id"]),))
                note = ""
        if note: _push(cidl, u, "\U0001f6d2 " + note)
        return h.sendj({"ok": True})
    if path == "/api/fcf/chore/done":
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcx_items WHERE id=? AND kind='chore' AND deleted_at=''", (int(d.get("id") or 0),)).fetchone()
            if not r or not _member(c, int(r["conversation_id"]), uid): return h.sendj({"error": "This chore was removed."}, 404)
            o = _opt(r); who = int(o.get("assignee") or 0) or uid; pts = int(o.get("stars") or 1)
            done = not bool(r["done"])
            c.execute("UPDATE fcx_items SET done=?,done_by=?,updated_at=? WHERE id=?", (1 if done else 0, uid if done else 0, A.now(), int(r["id"])))
            _stars(c, int(r["conversation_id"]), who, pts if done else -pts)
            if done:
                name = c.execute("SELECT name FROM users WHERE id=?", (who,)).fetchone()["name"]
                _post(c, int(r["conversation_id"]), u, "✅ " + (name or "Someone").split(" ")[0] + " did: " + r["title"] + " (+" + str(pts) + " ⭐)", {"fcf_done": int(r["id"])}, "system")
        return h.sendj({"ok": True, "done": done})
    if path == "/api/fcf/reward/redeem":
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcx_items WHERE id=? AND kind='reward' AND deleted_at='' AND done=0", (int(d.get("id") or 0),)).fetchone()
            if not r or not _member(c, int(r["conversation_id"]), uid): return h.sendj({"error": "This reward is no longer available."}, 404)
            cost = int(_opt(r).get("cost") or 5); conv = int(r["conversation_id"])
            have = c.execute("SELECT points FROM fcf_stars WHERE conversation_id=? AND user_id=?", (conv, uid)).fetchone()
            if not have or int(have["points"]) < cost: return h.sendj({"error": "You need " + str(cost) + " ⭐ for this. Keep going!"}, 400)
            _stars(c, conv, uid, -cost)
            _post(c, conv, u, "\U0001f381 " + u["name"].split(" ")[0] + " used " + str(cost) + " ⭐ for: " + r["title"], {"fcf_reward": int(r["id"])}, "system")
        _push(conv, u, "\U0001f381 " + u["name"].split(" ")[0] + " claimed: " + r["title"])
        return h.sendj({"ok": True})
    if path == "/api/fcf/game/score":
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcx_items WHERE id=? AND kind='game'", (int(d.get("id") or 0),)).fetchone()
            if not r or not _member(c, int(r["conversation_id"]), uid): return h.sendj({"error": "This game has ended."}, 404)
            n = len(_opt(r).get("qs") or []); score = max(0, min(n, int(d.get("score") or 0)))
            if c.execute("SELECT 1 FROM fcf_game_scores WHERE item_id=? AND user_id=?", (int(r["id"]), uid)).fetchone(): return h.sendj({"error": "You already played this quiz."}, 400)
            c.execute("INSERT INTO fcf_game_scores(item_id,user_id,score,created_at) VALUES(?,?,?,?)", (int(r["id"]), uid, score, A.now()))
            _post(c, int(r["conversation_id"]), u, "\U0001f3ae " + u["name"].split(" ")[0] + " scored " + str(score) + "/" + str(n) + " in the family quiz", {"fcf_score": int(r["id"])}, "system")
        return h.sendj({"ok": True})
    if path == "/api/fcf/checkin":
        kind = str(d.get("kind") or "safe")
        if kind not in ("safe", "ask", "here"): return h.sendj({"error": "Unknown check-in."}, 400)
        lat, lng = d.get("lat"), d.get("lng")
        try: loc = {"lat": round(float(lat), 5), "lng": round(float(lng), 5)} if lat is not None and lng is not None else None
        except (TypeError, ValueError): loc = None
        first = (u["name"] or "Someone").split(" ")[0]
        body = {"safe": "✅ " + first + " is home safe", "ask": "\U0001f4cd " + first + " asks: where is everyone? Tap I'm safe", "here": "\U0001f4cd " + first + " shared where they are"}[kind]
        with A.conn() as c:
            if not _member(c, cid, uid): return h.sendj({"error": "You are not part of this chat."}, 403)
            _post(c, cid, u, body, {"checkin": kind, "loc": loc, "at": A.now()})
        _push(cid, u, body)
        return h.sendj({"ok": True})
    if path == "/api/fcf/sos":
        lat, lng = d.get("lat"), d.get("lng")
        try: loc = {"lat": round(float(lat), 5), "lng": round(float(lng), 5)} if lat is not None and lng is not None else None
        except (TypeError, ValueError): loc = None
        with A.conn() as c:
            p = FX.prefs(c, uid)
            people = [int(x) for x in (p.get("sos") or []) if str(x).isdigit()]
            if not people:   # nobody chosen yet: everyone in my family Circles
                people = sorted({int(r["user_id"]) for r in c.execute("SELECT DISTINCT o.user_id FROM fc_members m JOIN fc_conversations cv ON cv.id=m.conversation_id AND cv.kind='group' "
                                                                      "JOIN fc_members o ON o.conversation_id=m.conversation_id WHERE m.user_id=? AND o.user_id<>?", (uid, uid)).fetchall()})[:30]
            me = c.execute("SELECT phone,phone_verified_at FROM users WHERE id=?", (uid,)).fetchone()
            phone = me["phone"] if me and me["phone_verified_at"] else ""
            sent = []
            for o in people:
                conv = _direct(c, uid, o)
                if not conv: continue
                _post(c, conv, u, "\U0001f198 " + (u["name"] or "Someone") + " needs help!", {"sos": 1, "loc": loc, "phone": phone, "at": A.now()})
                sent.append((o, conv))
        send = getattr(A, "fcm_send_to_user", None)
        for o, conv in sent:
            try:
                if send: send(o, "\U0001f198 " + (u["name"] or "Someone") + " needs help", "Tap to see where they are and call them", {"type": "fc_sos", "conversation_id": str(conv), "url": "/futurechat-app?fc=%d" % conv})
            except Exception as exc: print("Future Chat SOS push failed:", type(exc).__name__)
        return h.sendj({"ok": True, "sent": len(sent)})
    if path == "/api/fcf/date":
        kind = str(d.get("kind") or "anniversary")
        if kind not in ("anniversary", "remembrance", "other"): kind = "other"
        title = str(d.get("title") or "").strip()[:120]
        try: dd, mm, yy = int(d.get("d") or 0), int(d.get("m") or 0), int(d.get("y") or 0); datetime.date(2000, mm, dd)
        except (ValueError, TypeError): return h.sendj({"error": "Choose the day and month."}, 400)
        if not title: return h.sendj({"error": "Give it a name, e.g. Our wedding anniversary."}, 400)
        with A.conn() as c:
            if cid and not _member(c, cid, uid): return h.sendj({"error": "You are not part of this Circle."}, 403)
            c.execute("INSERT INTO fcf_dates(user_id,conversation_id,kind,title,d,m,y,created_at) VALUES(?,?,?,?,?,?,?,?)", (uid, cid, kind, title, dd, mm, yy if 1900 <= yy <= 2100 else 0, A.now()))
        return h.sendj({"ok": True})
    if path == "/api/fcf/date/delete":
        with A.conn() as c: c.execute("DELETE FROM fcf_dates WHERE id=? AND user_id=?", (int(d.get("id") or 0), uid))
        return h.sendj({"ok": True})
    if path == "/api/fcf/guardian/request":
        with A.conn() as c:
            ph = A.FC.normalize_phone(str(d.get("phone") or ""))
            t = c.execute("SELECT id,name FROM users WHERE phone_e164=? AND phone_verified_at<>''", (ph,)).fetchone() if ph else None
            if not t: return h.sendj({"error": "We couldn't find that number on Future Chat. Ask your teen to sign up and confirm their number first."}, 404)
            if int(t["id"]) == uid: return h.sendj({"error": "That's your own number."}, 400)
            if c.execute("SELECT 1 FROM fcf_links WHERE parent_id=? AND teen_id=? AND status IN ('pending','active')", (uid, int(t["id"]))).fetchone():
                return h.sendj({"ok": True, "message": "Already linked or waiting for " + t["name"] + " to accept."})
            c.execute("INSERT INTO fcf_links(parent_id,teen_id,status,created_at,updated_at) VALUES(?,?,'pending',?,?)", (uid, int(t["id"]), A.now(), A.now()))
        try:
            send = getattr(A, "fcm_send_to_user", None)
            if send: send(int(t["id"]), "\U0001f46a " + u["name"] + " wants to link as your parent", "Open You → Family safety to accept or decline", {"type": "fc_guardian", "url": "/futurechat-app?fcx=guardian"})
        except Exception: pass
        return h.sendj({"ok": True, "message": "Request sent to " + t["name"] + ". They need to accept it on their phone."})
    if path == "/api/fcf/guardian/answer":
        lid = int(d.get("id") or 0); act = str(d.get("action") or "")
        with A.conn() as c:
            l = c.execute("SELECT * FROM fcf_links WHERE id=? AND (teen_id=? OR parent_id=?)", (lid, uid, uid)).fetchone()
            if not l: return h.sendj({"error": "Not found"}, 404)
            if act == "accept" and int(l["teen_id"]) == uid: st = "active"
            elif act in ("decline", "unlink"): st = "ended"
            else: return h.sendj({"error": "Not allowed."}, 403)
            c.execute("UPDATE fcf_links SET status=?,updated_at=? WHERE id=?", (st, A.now(), lid))
            other = int(l["parent_id"]) if int(l["teen_id"]) == uid else int(l["teen_id"])
        try:
            send = getattr(A, "fcm_send_to_user", None)
            if send: send(other, "\U0001f46a Family safety", u["name"] + (" accepted your link" if st == "active" else " ended the family link"), {"type": "fc_guardian", "url": "/futurechat-app?fcx=guardian"})
        except Exception: pass
        return h.sendj({"ok": True, "status": st})
    return h.sendj({"error": "Not found"}, 404)
