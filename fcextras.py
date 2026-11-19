"""FCX-01: everything the stand-alone Future Chat app adds around the chats (owner list 2026-11-18 "full original app").

Profile (picture, name, about), settings that the server enforces (who sees my last seen / profile photo / status,
notifications, blocked people), call history, tasks / reminders / meeting proposals / polls (personal or shared in a
chat or Circle), translation, linked devices, business profile and creator broadcasts. Same accounts as Skillvaya.
Routes live under /api/fcx/ so they never clash with /api/fc/ (Future Chat core) or /api/fc/status (fcstatus.py).
"""
import base64
import datetime
import hashlib
import json
import re
import threading
import time
import urllib.parse
import urllib.request

A = None
PREF_DEFAULTS = {
    "about": "", "last_seen": "contacts", "photo": "contacts", "status": "contacts",
    "notify_messages": True, "notify_groups": True, "notify_calls": True, "notify_previews": True,
    "data_saver": False, "language": "English", "translate": True, "biz": {}, "app_lang": "en",
    "birthday": {}, "birthday_vis": "contacts", "celebrate": ["*"], "notify_celeb": True,
    "sos": [], "gogo": False, "teen_safe": False, "gogo_people": [],
}
CHOICES = {"last_seen": ("contacts", "nobody"), "photo": ("contacts", "nobody"), "status": ("contacts", "nobody"), "birthday_vis": ("contacts", "nobody")}
BOOLS = ("notify_messages", "notify_groups", "notify_calls", "notify_previews", "data_saver", "translate", "notify_celeb", "gogo", "teen_safe")
LANGS = ["English", "Afrikaans", "isiZulu", "isiXhosa", "Sesotho", "Setswana", "Sepedi", "Xitsonga", "French", "Portuguese",
         "Spanish", "German", "Swahili", "Arabic", "Hindi", "Chinese"]
ITEM_KINDS = ("task", "reminder", "event", "poll")
_LAST_SEEN = {}          # uid -> monotonic time of the last ping (cheap; written to the database at most once a minute)
_SEEN_WRITTEN = {}
_TR_CACHE = {}


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)


def init(c):
    pk = A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS fcx_prefs(user_id BIGINT PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}', last_seen TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS fcx_blocks(user_id BIGINT NOT NULL, blocked_id BIGINT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id, blocked_id));
        CREATE TABLE IF NOT EXISTS fcx_items(id %(pk)s, owner_id BIGINT NOT NULL, conversation_id BIGINT NOT NULL DEFAULT 0, kind TEXT NOT NULL,
            title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', due_at TEXT NOT NULL DEFAULT '', place TEXT NOT NULL DEFAULT '',
            options TEXT NOT NULL DEFAULT '[]', done INTEGER NOT NULL DEFAULT 0, done_by BIGINT NOT NULL DEFAULT 0, reminded INTEGER NOT NULL DEFAULT 0,
            message_id BIGINT NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS idx_fcx_items_owner ON fcx_items(owner_id, conversation_id);
        CREATE INDEX IF NOT EXISTS idx_fcx_items_conv ON fcx_items(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_fcx_items_due ON fcx_items(reminded, due_at);
        CREATE TABLE IF NOT EXISTS fcx_votes(item_id BIGINT NOT NULL, user_id BIGINT NOT NULL, choice INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(item_id, user_id));
        CREATE TABLE IF NOT EXISTS fcx_rsvps(item_id BIGINT NOT NULL, user_id BIGINT NOT NULL, answer TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(item_id, user_id));
        CREATE TABLE IF NOT EXISTS fcx_i18n(lang TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(lang, src));
        CREATE TABLE IF NOT EXISTS fcx_bday_sent(user_id BIGINT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY(user_id, day, kind));
        CREATE TABLE IF NOT EXISTS fcx_scheduled(id %(pk)s, user_id BIGINT NOT NULL, conversation_id BIGINT NOT NULL, body TEXT NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}', send_at TEXT NOT NULL, sent_at TEXT NOT NULL DEFAULT '', cancelled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_fcx_sched_due ON fcx_scheduled(sent_at, send_at);
        CREATE TABLE IF NOT EXISTS fcx_reports(id %(pk)s, user_id BIGINT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
    """ % {"pk": pk})
    # Call history needs the moment a call was answered (ended_at - answered_at = how long people talked).
    try:
        cols = A.FC._columns(c, "video_calls") if hasattr(A, "FC") else set()
    except Exception:
        cols = set()
    if "answered_at" not in cols:
        try: c.execute("ALTER TABLE video_calls ADD COLUMN answered_at TEXT NOT NULL DEFAULT ''")
        except Exception: pass
    # FCX-CLEAR-01: "Clear chat" / "Clear all chats" hide older messages for one person; the backup can bring them back.
    try:
        mcols = A.FC._columns(c, "fc_members") if hasattr(A, "FC") else set()
    except Exception:
        mcols = set()
    for col, ddl in (("cleared_id", "BIGINT NOT NULL DEFAULT 0"), ("cleared_at", "TEXT NOT NULL DEFAULT ''")):
        if col not in mcols:
            try: c.execute("ALTER TABLE fc_members ADD COLUMN " + col + " " + ddl)
            except Exception: pass
    threading.Thread(target=_reminder_loop, name="FutureChatReminders", daemon=True).start()


# ---------------------------------------------------------------- helpers
def _now():
    return datetime.datetime.now(datetime.timezone.utc)


# FCF-KINDS: family items (list/chore/reward/game) live in fcfamily.py
def _iso(v):
    """Client times arrive as ISO strings (toISOString). Store them as UTC isoformat, or '' when missing/bad."""
    s = str(v or "").strip()
    if not s: return ""
    try:
        d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None: d = d.replace(tzinfo=datetime.timezone.utc)
        return d.astimezone(datetime.timezone.utc).isoformat()
    except ValueError:
        return ""


def prefs(c, uid):
    r = c.execute("SELECT data FROM fcx_prefs WHERE user_id=?", (int(uid),)).fetchone()
    d = dict(PREF_DEFAULTS)
    if r:
        try: d.update(json.loads(r["data"] or "{}"))
        except ValueError: pass
    return d


def _save_prefs(c, uid, d):
    data = json.dumps({k: d[k] for k in PREF_DEFAULTS if k in d})[:20000]
    stamp = A.now()
    if c.execute("SELECT 1 FROM fcx_prefs WHERE user_id=?", (uid,)).fetchone():
        c.execute("UPDATE fcx_prefs SET data=?,updated_at=? WHERE user_id=?", (data, stamp, uid))
    else:
        c.execute("INSERT INTO fcx_prefs(user_id,data,updated_at) VALUES(?,?,?)", (uid, data, stamp))


def contacts(c, uid):
    """People who share at least one Future Chat conversation with uid."""
    rows = c.execute("SELECT DISTINCT o.user_id AS uid FROM fc_members m JOIN fc_members o ON o.conversation_id=m.conversation_id "
                     "WHERE m.user_id=? AND o.user_id<>?", (uid, uid)).fetchall()
    return {int(r["uid"]) for r in rows}


def blocked_between(c, a, b):
    return bool(c.execute("SELECT 1 FROM fcx_blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)", (a, b, b, a)).fetchone())


def direct_block(c, conv_id, uid):
    """For Future Chat core: True when this is a one-to-one chat and either person has blocked the other."""
    try:
        conv = c.execute("SELECT kind FROM fc_conversations WHERE id=?", (conv_id,)).fetchone()
        if not conv or conv["kind"] == "group": return False
        for r in c.execute("SELECT user_id FROM fc_members WHERE conversation_id=? AND user_id<>?", (conv_id, uid)).fetchall():
            if blocked_between(c, uid, int(r["user_id"])): return True
    except Exception as exc:
        print("Future Chat block check skipped:", type(exc).__name__)
    return False


def allow_push(uid, kind, group=False):
    """kind: 'message' or 'call'. Returns (allowed, show_preview)."""
    try:
        with A.conn() as c: p = prefs(c, uid)
    except Exception:
        return True, True
    if kind == "call": return bool(p.get("notify_calls", True)), True
    if group and not p.get("notify_groups", True): return False, False
    return bool(p.get("notify_messages", True)), bool(p.get("notify_previews", True))


def hidden_status_owners(c, ids):
    """Status owners (from ids) who chose that nobody sees their status."""
    ids = [int(i) for i in ids]
    if not ids: return set()
    marks = ",".join("?" * len(ids))
    out = set()
    for r in c.execute("SELECT user_id,data FROM fcx_prefs WHERE user_id IN (" + marks + ")", ids).fetchall():
        try:
            if json.loads(r["data"] or "{}").get("status") == "nobody": out.add(int(r["user_id"]))
        except ValueError: pass
    return out


def _photo_version(photo):
    return hashlib.sha1(photo[-200:].encode()).hexdigest()[:10] if photo else ""


def _seen_text(iso):
    if not iso: return ""
    try: d = datetime.datetime.fromisoformat(iso)
    except ValueError: return ""
    mins = int((_now() - d).total_seconds() // 60)
    return "online" if mins < 2 else "last seen " + (str(mins) + " min ago" if mins < 60 else str(mins // 60) + " h ago" if mins < 1440 else str(mins // 1440) + " d ago")


def _touch(uid):
    _LAST_SEEN[uid] = time.monotonic()
    if time.monotonic() - _SEEN_WRITTEN.get(uid, 0) < 50: return
    _SEEN_WRITTEN[uid] = time.monotonic()
    try:
        with A.conn() as c:
            stamp = A.now()
            if c.execute("SELECT 1 FROM fcx_prefs WHERE user_id=?", (uid,)).fetchone():
                c.execute("UPDATE fcx_prefs SET last_seen=? WHERE user_id=?", (stamp, uid))
            else:
                c.execute("INSERT INTO fcx_prefs(user_id,data,last_seen,updated_at) VALUES(?,?,?,?)", (uid, "{}", stamp, stamp))
    except Exception as exc:
        print("Future Chat last seen skipped:", type(exc).__name__)


def _member(c, conv_id, uid):
    return bool(c.execute("SELECT 1 FROM fc_members WHERE conversation_id=? AND user_id=?", (conv_id, uid)).fetchone())


def _post_in_chat(c, conv_id, u, body, meta):
    stamp = A.now()
    mid = c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,meta,created_at) VALUES(?,?,?,?,?,?) RETURNING id",
                    (conv_id, int(u["id"]), body, "text", json.dumps(meta), stamp)).fetchone()["id"]
    c.execute("UPDATE fc_conversations SET last_message_id=?,updated_at=? WHERE id=?", (mid, stamp, conv_id))
    c.execute("UPDATE fc_members SET last_read_id=? WHERE conversation_id=? AND user_id=?", (mid, conv_id, int(u["id"])))
    c.execute("UPDATE fc_members SET archived=0 WHERE conversation_id=?", (conv_id,))
    return int(mid)


def _push_conv(conv_id, sender, text):
    try:
        if hasattr(A, "FC"): A.FC._push(conv_id, sender, text)
    except Exception as exc:
        print("Future Chat item push skipped:", type(exc).__name__)


ICONS = {"task": "✅", "reminder": "⏰", "event": "\U0001f4c5", "poll": "\U0001f4ca"}
LABEL = {"task": "Task", "reminder": "Reminder", "event": "Meeting proposal", "poll": "Poll"}


def _item_out(c, r, uid):
    d = {"id": int(r["id"]), "kind": r["kind"], "title": r["title"], "notes": r["notes"], "due_at": r["due_at"], "place": r["place"],
         "done": bool(r["done"]), "conversation_id": int(r["conversation_id"] or 0), "mine": int(r["owner_id"]) == uid,
         "owner_id": int(r["owner_id"]), "created_at": r["created_at"], "message_id": int(r["message_id"] or 0)}
    try: opts = json.loads(r["options"] or "[]")
    except ValueError: opts = []
    if r["kind"] == "poll":
        counts = [0] * len(opts); mine = -1; total = 0
        for v in c.execute("SELECT user_id,choice FROM fcx_votes WHERE item_id=?", (int(r["id"]),)).fetchall():
            ch = int(v["choice"])
            if 0 <= ch < len(opts): counts[ch] += 1; total += 1
            if int(v["user_id"]) == uid: mine = ch
        d.update(options=opts, counts=counts, my_vote=mine, votes=total)
    if r["kind"] == "event":
        ans = {"yes": 0, "maybe": 0, "no": 0}; mine = ""
        for v in c.execute("SELECT user_id,answer FROM fcx_rsvps WHERE item_id=?", (int(r["id"]),)).fetchall():
            if v["answer"] in ans: ans[v["answer"]] += 1
            if int(v["user_id"]) == uid: mine = v["answer"]
        d.update(rsvp=ans, my_rsvp=mine)
    if d["done"] and int(r["done_by"] or 0):
        w = c.execute("SELECT name FROM users WHERE id=?", (int(r["done_by"]),)).fetchone()
        d["done_by"] = w["name"] if w else ""
    return d


def _can_see_item(c, r, uid):
    if not r or r["deleted_at"]: return False
    if int(r["conversation_id"] or 0): return _member(c, int(r["conversation_id"]), uid)
    return int(r["owner_id"]) == uid


# ---------------------------------------------------------------- reminders (push when due, even with the app closed)
def _reminder_loop():
    time.sleep(30)
    while True:
        try: _send_due()
        except Exception as exc: print("Future Chat reminders skipped:", type(exc).__name__)
        try: _birthdays_job()
        except Exception as exc: print("Future Chat birthdays skipped:", type(exc).__name__)
        try: _send_scheduled()
        except Exception as exc: print("Future Chat scheduled messages skipped:", type(exc).__name__)
        try: _celeb_job()
        except Exception as exc: print("Future Chat special-day greetings skipped:", type(exc).__name__)
        time.sleep(60)


# ---------------------------------------------------------------- scheduled messages (FCX-SCHED-01): "send at midnight on her birthday"
def _send_scheduled():
    now = _now().isoformat()
    done = []
    with A.conn() as c:
        rows = c.execute("SELECT s.*,u.name FROM fcx_scheduled s JOIN users u ON u.id=s.user_id WHERE s.sent_at='' AND s.cancelled=0 AND s.send_at<=? LIMIT 50", (now,)).fetchall()
        for r in rows:
            c.execute("UPDATE fcx_scheduled SET sent_at=? WHERE id=?", (now, int(r["id"])))
            cid, uid = int(r["conversation_id"]), int(r["user_id"])
            if not _member(c, cid, uid) or direct_block(c, cid, uid): continue
            try: meta = json.loads(r["meta"] or "{}")
            except ValueError: meta = {}
            meta["scheduled"] = 1
            u = {"id": uid, "name": r["name"] or "Future Chat"}
            _post_in_chat(c, cid, u, r["body"], meta); done.append((cid, u, r["body"]))
    for cid, u, body in done: _push_conv(cid, u, body[:120])


# ---------------------------------------------------------------- special-day greetings (FCX-CELEB-02)
# static/futurechat/fc_holidays.json: day -> special days (made from the same rules the app uses, Hebrew/Islamic/Chinese calendars included).
# At 08:00 South African time people get one friendly nudge for their special days. Religious days only for people who chose them;
# everyone else gets New Year and their own country's days.
COUNTRY_DAYS = {"ZA": ["humanrights", "freedom", "workers", "africa", "youth", "mandela", "womensdaysa", "heritage", "reconciliation", "goodwill"],
                "US": ["usindependence", "thanksgiving"], "DE": ["germanunity"], "IN": ["indiaday"], "NG": ["nigeriaday", "africa"], "CA": ["canadaday"], "AU": ["australiaday"]}
_HOL = {"data": None}


def _holidays():
    if _HOL["data"] is None:
        try: _HOL["data"] = json.load(open(_os.path.join(_STATIC, "fc_holidays.json"), encoding="utf-8"))
        except Exception: _HOL["data"] = {"days": {}, "info": {}}
    return _HOL["data"]


def _celeb_job():
    now_sa = _now() + datetime.timedelta(hours=2)
    if now_sa.hour < 8: return
    day = now_sa.date().isoformat()
    H = _holidays(); ids = H.get("days", {}).get(day) or []
    if not ids: return
    send = getattr(A, "fcm_send_to_user", None)
    jobs = []
    with A.conn() as c:
        users = c.execute("SELECT DISTINCT m.user_id AS uid,p.data AS pdata,u.country AS country FROM fc_members m JOIN users u ON u.id=m.user_id "
                          "LEFT JOIN fcx_prefs p ON p.user_id=m.user_id").fetchall()
        for r in users:
            uid = int(r["uid"])
            try: pd = json.loads(r["pdata"] or "{}")
            except ValueError: pd = {}
            if pd.get("notify_celeb") is False: continue
            lst = pd.get("celebrate") or ["*"]
            if "*" in lst:
                mine = {"newyear"} | set(COUNTRY_DAYS.get(str(r["country"] or "ZA").upper(), []))
                mine -= {x[1:] for x in lst if x.startswith("-")}
            else:
                mine = set(lst)
            for hid in ids:
                if hid not in mine: continue
                if c.execute("SELECT 1 FROM fcx_bday_sent WHERE user_id=? AND day=? AND kind=?", (uid, day, "celeb:" + hid)).fetchone(): continue
                c.execute("INSERT INTO fcx_bday_sent(user_id,day,kind) VALUES(?,?,?)", (uid, day, "celeb:" + hid))
                jobs.append((uid, hid))
    if not send: return
    for uid, hid in jobs:
        info = H.get("info", {}).get(hid) or ["\U0001f389", "Special day"]
        if not allow_push(uid, "message")[0]: continue
        try: send(uid, info[0] + " " + info[1], "Tap to send greetings to your people on Future Chat", {"type": "fc_celeb", "id": hid, "url": "/futurechat-app?fcx=celeb&id=" + hid})
        except Exception as exc: print("Future Chat special-day push failed:", type(exc).__name__)


# ---------------------------------------------------------------- birthdays (FCX-BDAY-01)
# Birthdays are day + month (year optional and never shown to others). At 07:00 South African time the people a person
# chats with get "It's Kelly's birthday today" (and "tomorrow" the day before), and every group they're in gets a note.
def _sa_today():
    return (_now() + datetime.timedelta(hours=2)).date()


def _bday_people(c):
    out = []
    for r in c.execute("SELECT p.user_id,p.data,u.name FROM fcx_prefs p JOIN users u ON u.id=p.user_id WHERE p.data LIKE '%%\"birthday\": {\"d\"%%'").fetchall():
        try: d = json.loads(r["data"] or "{}")
        except ValueError: continue
        b = d.get("birthday") or {}
        if b.get("d") and b.get("m") and d.get("birthday_vis", "contacts") != "nobody":
            out.append((int(r["user_id"]), r["name"] or "Your friend", int(b["d"]), int(b["m"])))
    return out


def _is_day(dd, mm, day):
    if mm == 2 and dd == 29 and not (day.year % 4 == 0 and (day.year % 100 != 0 or day.year % 400 == 0)): return day.month == 2 and day.day == 28
    return day.day == dd and day.month == mm


def _birthdays_job():
    now_sa = _now() + datetime.timedelta(hours=2)
    if now_sa.hour < 7: return
    today = now_sa.date(); tomorrow = today + datetime.timedelta(days=1)
    send = getattr(A, "fcm_send_to_user", None)
    with A.conn() as c:
        people = _bday_people(c)
        jobs = []
        for uid, name, dd, mm in people:
            for kind, day in (("today", today), ("tomorrow", tomorrow)):
                if not _is_day(dd, mm, day): continue
                if c.execute("SELECT 1 FROM fcx_bday_sent WHERE user_id=? AND day=? AND kind=?", (uid, today.isoformat(), kind)).fetchone(): continue
                c.execute("INSERT INTO fcx_bday_sent(user_id,day,kind) VALUES(?,?,?)", (uid, today.isoformat(), kind))
                friends = [f for f in contacts(c, uid) if not blocked_between(c, uid, f)]
                jobs.append((uid, name, kind, friends))
                if kind == "today":
                    stamp = A.now()
                    for g in c.execute("SELECT m.conversation_id FROM fc_members m JOIN fc_conversations cv ON cv.id=m.conversation_id WHERE m.user_id=? AND cv.kind='group'", (uid,)).fetchall():
                        cid = int(g["conversation_id"])
                        mid = c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,meta,created_at) VALUES(?,?,?,?,?,?) RETURNING id",
                                        (cid, uid, "\U0001f382 It's " + name + "'s birthday today! Send your wishes \U0001f389", "system", json.dumps({"bday": uid}), stamp)).fetchone()["id"]
                        c.execute("UPDATE fc_conversations SET last_message_id=?,updated_at=? WHERE id=?", (mid, stamp, cid))
    if not send: return
    for uid, name, kind, friends in jobs:
        title = "\U0001f382 " + (name + "'s birthday today" if kind == "today" else name + "'s birthday is tomorrow")
        body = "Send " + name.split(" ")[0] + " a birthday wish on Future Chat" if kind == "today" else "Don't forget to wish " + name.split(" ")[0] + " tomorrow"
        for f in friends:
            ok, _pv = allow_push(f, "message")
            if not ok: continue
            try: send(f, title, body, {"type": "fc_birthday", "user_id": str(uid), "url": "/futurechat-app?fcx=bday&u=%d" % uid})
            except Exception as exc: print("Future Chat birthday push failed:", type(exc).__name__)


def _send_due():
    now = _now().isoformat()
    with A.conn() as c:
        rows = c.execute("SELECT * FROM fcx_items WHERE reminded=0 AND deleted_at='' AND done=0 AND due_at<>'' AND due_at<=? AND kind IN ('task','reminder','event') LIMIT 50", (now,)).fetchall()
        for r in rows: c.execute("UPDATE fcx_items SET reminded=1 WHERE id=?", (int(r["id"]),))
    send = getattr(A, "fcm_send_to_user", None)
    if not send: return
    for r in rows:
        title = ICONS.get(r["kind"], "") + " " + LABEL.get(r["kind"], "Reminder")
        text = r["title"] + ((" · " + r["place"]) if r["place"] else "")
        conv = int(r["conversation_id"] or 0)
        data = {"type": "fc_reminder", "item_id": str(r["id"]), "url": "/futurechat-app?fcx=item&id=%d" % int(r["id"])}
        if conv:
            with A.conn() as c:
                people = [int(x["user_id"]) for x in c.execute("SELECT user_id FROM fc_members WHERE conversation_id=?", (conv,)).fetchall()]
        else:
            people = [int(r["owner_id"])]
        for p in people:
            try: send(p, title, text, data)
            except Exception as exc: print("Future Chat reminder push failed:", type(exc).__name__)


# ---------------------------------------------------------------- translation (free: Argos when installed, else free open models)
def _translate(text, to):
    key = (text, to)
    if key in _TR_CACHE: return _TR_CACHE[key]
    out = None
    try:
        import argostranslate.translate as AT   # optional: works when the Argos models are installed on the server
        codes = {"English": "en", "Afrikaans": "af", "isiZulu": "zu", "isiXhosa": "xh", "French": "fr", "Portuguese": "pt", "Spanish": "es",
                 "German": "de", "Swahili": "sw", "Arabic": "ar", "Hindi": "hi", "Chinese": "zh"}
        if to in codes:
            for src in ("en", "af", "fr", "pt", "es", "de"):
                try:
                    t = AT.translate(text, src, codes[to])
                    if t and t.strip() and t.strip() != text.strip(): out = t; break
                except Exception: continue
    except ImportError:
        pass
    if not out:
        try:
            import kaspersen_ai as KAI
            keys = KAI._keys(); k = keys.get("openrouter")
            if k:
                try: KAI._free_models()
                except Exception: pass
                models = [m for m in (KAI._free.get("ids") or []) if m.endswith(":free")][:4] or list(KAI.FREE_PREFERRED)[:3]
                prompt = ("Translate the message below into " + to + ". Reply with ONLY the translation, no notes, no quotes. "
                          "Keep :chatmoji_names: like :smile: exactly as they are.\n\n" + text)
                for m in models:
                    try:
                        req = urllib.request.Request(KAI.FREE_URL, method="POST", data=json.dumps({"model": m, "temperature": 0, "max_tokens": 800,
                                                     "messages": [{"role": "user", "content": prompt}]}).encode(),
                                                     headers={"Authorization": "Bearer " + k, "Content-Type": "application/json",
                                                              "HTTP-Referer": "https://skillvaya.onrender.com", "X-Title": "Future Chat"})
                        with urllib.request.urlopen(req, timeout=40) as resp: j = json.loads(resp.read())
                        t = (((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
                        t = re.sub(r"(?s)<think>.*?</think>", "", t).strip()
                        if t: out = t; break
                    except Exception as exc:
                        print("Future Chat translate via %s failed: %s" % (m, type(exc).__name__))
        except Exception as exc:
            print("Future Chat translate unavailable:", type(exc).__name__)
    if out:
        if len(_TR_CACHE) > 500: _TR_CACHE.clear()
        _TR_CACHE[key] = out
    return out


# ---------------------------------------------------------------- app wording in any language (FCX-I18N-01)
# Prepared languages ship in static/futurechat/fc_i18n_seed.json (made once: Argos offline + checked wording);
# any other language is translated once with the free translator, saved in fcx_i18n, then served instantly to everyone.
import os as _os
_STATIC = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "static", "futurechat")
_I18N = {"seed": None, "catalog": None, "filling": set(), "lock": threading.Lock()}


def _i18n_files():
    if _I18N["seed"] is None:
        try: _I18N["seed"] = json.load(open(_os.path.join(_STATIC, "fc_i18n_seed.json"), encoding="utf-8"))
        except Exception: _I18N["seed"] = {}
        try: _I18N["catalog"] = json.load(open(_os.path.join(_STATIC, "fc_strings.json"), encoding="utf-8"))
        except Exception: _I18N["catalog"] = []
    return _I18N["seed"], _I18N["catalog"]


def _ai_batch(items, lang_name):
    import kaspersen_ai as KAI
    keys = KAI._keys(); k = keys.get("openrouter")
    if not k: return {}
    try: KAI._free_models()
    except Exception: pass
    models = [m for m in (KAI._free.get("ids") or []) if m.endswith(":free")][:4] or list(KAI.FREE_PREFERRED)[:3]
    prompt = ("You translate the buttons and screens of a messaging app called Future Chat into " + lang_name + ". "
              "Translate every English string in the JSON list. Keep these unchanged: Future Chat, Chatmoji, Skillvaya, Google Play, Wi-Fi, "
              "prices like R149, numbers, emoji and symbols. Use short, natural, everyday wording a phone app would use. "
              "Reply with ONLY a JSON object that maps each English string exactly to its translation.\n\n" + json.dumps(items, ensure_ascii=False))
    for m in models:
        try:
            req = urllib.request.Request(KAI.FREE_URL, method="POST", data=json.dumps({"model": m, "temperature": 0, "max_tokens": 6000,
                                         "messages": [{"role": "user", "content": prompt}]}).encode(),
                                         headers={"Authorization": "Bearer " + k, "Content-Type": "application/json",
                                                  "HTTP-Referer": "https://skillvaya.onrender.com", "X-Title": "Future Chat"})
            with urllib.request.urlopen(req, timeout=120) as resp: j = json.loads(resp.read())
            t = (((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
            t = re.sub(r"(?s)<think>.*?</think>", "", t)
            a, b = t.find("{"), t.rfind("}")
            if a < 0 or b <= a: continue
            d = json.loads(t[a:b + 1])
            out = {str(x): str(y).strip() for x, y in d.items() if x in items and isinstance(y, str) and y.strip()}
            if out: return out
        except Exception as exc:
            print("Future Chat wording translate via %s failed: %s" % (m, type(exc).__name__))
    return {}


def _fill(lang, lang_name, missing):
    try:
        for i in range(0, len(missing), 50):
            got = _ai_batch(missing[i:i + 50], lang_name)
            if got:
                with A.conn() as c:
                    stamp = A.now()
                    for src, dst in got.items():
                        if not c.execute("SELECT 1 FROM fcx_i18n WHERE lang=? AND src=?", (lang, src)).fetchone():
                            c.execute("INSERT INTO fcx_i18n(lang,src,dst,created_at) VALUES(?,?,?,?)", (lang, src, dst[:600], stamp))
            time.sleep(3)
    except Exception as exc:
        print("Future Chat wording fill stopped:", type(exc).__name__)
    finally:
        with _I18N["lock"]: _I18N["filling"].discard(lang)


def _i18n(h):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    lang = str((q.get("lang") or [""])[0]).strip()
    name = re.sub(r"[^\w \-()]", "", str((q.get("name") or [""])[0]), flags=re.UNICODE)[:40] or lang
    if not re.fullmatch(r"[a-z]{2,3}(-[A-Za-z]{2,4})?", lang) or lang == "en": return h.sendj({"lang": "en", "strings": {}, "complete": True})
    seed, catalog = _i18n_files()
    strings = {}
    try:
        sv = getattr(A, "sv_i18n", None)
        if sv: strings.update(sv(lang)[1] or {})
    except Exception: pass
    strings.update(seed.get(lang) or {})
    with A.conn() as c:
        for r in c.execute("SELECT src,dst FROM fcx_i18n WHERE lang=?", (lang,)).fetchall(): strings.setdefault(r["src"], r["dst"])
    missing = [x for x in catalog if x not in strings]
    filling = False
    if missing:
        with _I18N["lock"]:
            if lang not in _I18N["filling"] and len(_I18N["filling"]) < 3:
                _I18N["filling"].add(lang); filling = True
                threading.Thread(target=_fill, args=(lang, name, missing), name="FutureChatWording-" + lang, daemon=True).start()
            elif lang in _I18N["filling"]: filling = True
    return h.sendj({"lang": lang, "strings": strings, "complete": not missing, "filling": filling, "missing": len(missing)})


# ---------------------------------------------------------------- GET
def handle_get(h, path):
    if path == "/api/fcx/i18n": return _i18n(h)   # open before sign-in: the language is chosen on the sign-up screen
    u = h.require(); uid = int(u["id"])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    if path == "/api/fcx/me":
        _touch(uid)
        with A.conn() as c:
            r = c.execute("SELECT id,name,email,phone,profile_photo,phone_verified_at FROM users WHERE id=?", (uid,)).fetchone()
            p = prefs(c, uid)
            n_chats = c.execute("SELECT COUNT(*) AS n FROM fc_members WHERE user_id=?", (uid,)).fetchone()["n"]
            n_msgs = c.execute("SELECT COUNT(*) AS n FROM fc_messages WHERE sender_id=?", (uid,)).fetchone()["n"]
            n_items = c.execute("SELECT COUNT(*) AS n FROM fcx_items WHERE owner_id=? AND deleted_at=''", (uid,)).fetchone()["n"]
            n_blocked = c.execute("SELECT COUNT(*) AS n FROM fcx_blocks WHERE user_id=?", (uid,)).fetchone()["n"]
        photo = (r["profile_photo"] if r else "") or ""
        return h.sendj({"me": {"id": uid, "name": r["name"] if r else u["name"], "email": r["email"] if r else u["email"],
                               "phone": (r["phone"] if r else "") or "", "phone_verified": bool(r and r["phone_verified_at"]),
                               "photo": ("/api/fcx/avatar/%d?v=%s" % (uid, _photo_version(photo))) if photo else ""},
                        "prefs": p, "languages": LANGS,
                        "counts": {"chats": int(n_chats), "sent": int(n_msgs), "items": int(n_items), "blocked": int(n_blocked)}})
    m = re.fullmatch(r"/api/fcx/avatar/(\d+)", path)
    if m:
        other = int(m.group(1))
        with A.conn() as c:
            r = c.execute("SELECT profile_photo FROM users WHERE id=?", (other,)).fetchone()
            ok = bool(r and r["profile_photo"])
            if ok and other != uid:
                ok = prefs(c, other).get("photo") != "nobody" and other in contacts(c, uid) and not blocked_between(c, uid, other)
        if not ok: return h.sendj({"error": "No picture"}, 404)
        head, _, b64 = r["profile_photo"].partition(",")
        mime = head[5:].split(";")[0] if head.startswith("data:") else "image/jpeg"
        try: data = base64.b64decode(b64)
        except Exception: return h.sendj({"error": "No picture"}, 404)
        h.send_response(200); h.send_header("Content-Type", mime); h.send_header("Cache-Control", "private, max-age=86400")
        h.send_header("Content-Length", str(len(data))); h.end_headers(); h.wfile.write(data); return
    if path == "/api/fcx/peers":
        # For the chat list / chat header: the other person's picture and (if both share it) online / last seen.
        _touch(uid)
        with A.conn() as c:
            mine = prefs(c, uid)
            rows = c.execute("SELECT m.conversation_id AS cid,o.user_id AS uid,u.profile_photo AS photo,p.data AS pdata,p.last_seen AS seen "
                             "FROM fc_members m JOIN fc_conversations cv ON cv.id=m.conversation_id AND cv.kind<>'group' "
                             "JOIN fc_members o ON o.conversation_id=m.conversation_id AND o.user_id<>m.user_id "
                             "JOIN users u ON u.id=o.user_id LEFT JOIN fcx_prefs p ON p.user_id=o.user_id WHERE m.user_id=?", (uid,)).fetchall()
            blocked = {int(r["blocked_id"]) for r in c.execute("SELECT blocked_id FROM fcx_blocks WHERE user_id=?", (uid,)).fetchall()}
            blocked_me = {int(r["user_id"]) for r in c.execute("SELECT user_id FROM fcx_blocks WHERE blocked_id=?", (uid,)).fetchall()}
        out = {}
        for r in rows:
            try: pd = json.loads(r["pdata"] or "{}")
            except ValueError: pd = {}
            o = int(r["uid"]); hide = o in blocked or o in blocked_me
            item = {"user_id": o, "blocked": o in blocked}
            if r["photo"] and pd.get("photo") != "nobody" and not hide:
                item["photo"] = "/api/fcx/avatar/%d?v=%s" % (o, _photo_version(r["photo"]))
            if not hide and pd.get("last_seen", "contacts") != "nobody" and mine.get("last_seen") != "nobody":
                live = time.monotonic() - _LAST_SEEN.get(o, -1e9) < 70
                item["seen"] = "online" if live else _seen_text(r["seen"] or "")
            if (pd.get("biz") or {}).get("name"): item["biz"] = True
            out[str(int(r["cid"]))] = item
        return h.sendj({"peers": out})
    m = re.fullmatch(r"/api/fcx/profile/(\d+)", path)
    if m:
        other = int(m.group(1))
        with A.conn() as c:
            if other != uid and other not in contacts(c, uid): return h.sendj({"error": "You can only see the profile of people you chat with."}, 403)
            r = c.execute("SELECT id,name,phone,profile_photo,phone_verified_at FROM users WHERE id=?", (other,)).fetchone()
            if not r: return h.sendj({"error": "Not found"}, 404)
            p = prefs(c, other); seen = c.execute("SELECT last_seen FROM fcx_prefs WHERE user_id=?", (other,)).fetchone()
            iblocked = bool(c.execute("SELECT 1 FROM fcx_blocks WHERE user_id=? AND blocked_id=?", (uid, other)).fetchone())
            hidden = blocked_between(c, uid, other)
            common = c.execute("SELECT cv.id,cv.title FROM fc_members a JOIN fc_members b ON b.conversation_id=a.conversation_id "
                               "JOIN fc_conversations cv ON cv.id=a.conversation_id WHERE a.user_id=? AND b.user_id=? AND cv.kind='group' LIMIT 20", (uid, other)).fetchall()
            mine = prefs(c, uid)
        out = {"id": other, "name": r["name"], "about": "" if hidden else p.get("about", ""), "blocked": iblocked,
               "phone": r["phone"] if r["phone_verified_at"] else "", "groups": [{"id": int(g["id"]), "title": g["title"]} for g in common]}
        if r["profile_photo"] and p.get("photo") != "nobody" and not hidden:
            out["photo"] = "/api/fcx/avatar/%d?v=%s" % (other, _photo_version(r["profile_photo"]))
        if not hidden and p.get("last_seen") != "nobody" and mine.get("last_seen") != "nobody":
            out["seen"] = "online" if time.monotonic() - _LAST_SEEN.get(other, -1e9) < 70 else _seen_text(seen["last_seen"] if seen else "")
        biz = p.get("biz") or {}
        if biz.get("name"): out["biz"] = {k: biz.get(k, "") for k in ("name", "category", "about", "hours", "address", "website", "email")}
        return h.sendj({"profile": out})
    if path == "/api/fcx/birthdays":
        with A.conn() as c:
            mine = contacts(c, uid)
            rows = []
            for o, name, dd, mm in _bday_people(c):
                if o not in mine or blocked_between(c, uid, o): continue
                conv = c.execute("SELECT a.conversation_id FROM fc_members a JOIN fc_members b ON b.conversation_id=a.conversation_id "
                                 "JOIN fc_conversations cv ON cv.id=a.conversation_id WHERE a.user_id=? AND b.user_id=? AND cv.kind<>'group' LIMIT 1", (uid, o)).fetchone()
                ph = c.execute("SELECT profile_photo FROM users WHERE id=?", (o,)).fetchone()
                pp = prefs(c, o)
                rows.append({"user_id": o, "name": name, "d": dd, "m": mm, "conversation_id": int(conv["conversation_id"]) if conv else 0,
                             "photo": ("/api/fcx/avatar/%d?v=%s" % (o, _photo_version(ph["profile_photo"]))) if ph and ph["profile_photo"] and pp.get("photo") != "nobody" else ""})
        t = _sa_today()
        return h.sendj({"items": rows, "today": t.isoformat()})
    if path == "/api/fcx/scheduled":
        with A.conn() as c:
            rows = c.execute("SELECT s.id,s.conversation_id,s.body,s.send_at,cv.kind,cv.title FROM fcx_scheduled s JOIN fc_conversations cv ON cv.id=s.conversation_id "
                             "WHERE s.user_id=? AND s.sent_at='' AND s.cancelled=0 ORDER BY s.send_at LIMIT 100", (uid,)).fetchall()
            out = []
            for r in rows:
                t = r["title"] if r["kind"] == "group" else ""
                if not t:
                    o = c.execute("SELECT u.name FROM fc_members o JOIN users u ON u.id=o.user_id WHERE o.conversation_id=? AND o.user_id<>? LIMIT 1", (int(r["conversation_id"]), uid)).fetchone()
                    t = (o["name"] if o else "") or "Chat"
                out.append({"id": int(r["id"]), "conversation_id": int(r["conversation_id"]), "title": t, "body": r["body"], "send_at": r["send_at"]})
        return h.sendj({"items": out})
    if path == "/api/fcx/blocks":
        with A.conn() as c:
            rows = c.execute("SELECT b.blocked_id,u.name,b.created_at FROM fcx_blocks b JOIN users u ON u.id=b.blocked_id WHERE b.user_id=? ORDER BY b.created_at DESC", (uid,)).fetchall()
        return h.sendj({"items": [{"user_id": int(r["blocked_id"]), "name": r["name"], "at": r["created_at"]} for r in rows]})
    if path == "/api/fcx/calls":
        with A.conn() as c:
            rows = c.execute("SELECT vc.id,vc.caller_id,vc.callee_id,vc.status,vc.created_at,vc.ended_at,vc.answered_at,vc.conversation_id,"
                             " CASE WHEN vc.offer_sdp LIKE '%%m=video%%' THEN 1 ELSE 0 END AS video,"
                             " cu.name AS caller_name,ce.name AS callee_name FROM video_calls vc"
                             " LEFT JOIN users cu ON cu.id=vc.caller_id LEFT JOIN users ce ON ce.id=vc.callee_id"
                             " WHERE vc.caller_id=? OR vc.callee_id=? ORDER BY vc.created_at DESC LIMIT 150", (uid, uid)).fetchall()
        items = []
        for r in rows:
            out = int(r["caller_id"]) == uid
            secs = 0
            if r["answered_at"] and r["ended_at"]:
                try: secs = max(0, int((datetime.datetime.fromisoformat(r["ended_at"]) - datetime.datetime.fromisoformat(r["answered_at"])).total_seconds()))
                except ValueError: secs = 0
            st = r["status"]
            items.append({"id": r["id"], "outgoing": out, "video": bool(r["video"]), "status": st,
                          "missed": st in ("missed", "rejected") or (st == "ringing" and not out),
                          "answered": bool(r["answered_at"]) or st == "accepted",
                          "other_id": int(r["callee_id"] if out else r["caller_id"]),
                          "name": (r["callee_name"] if out else r["caller_name"]) or "Future Chat",
                          "conversation_id": int(r["conversation_id"] or 0), "at": r["created_at"], "seconds": secs})
        return h.sendj({"items": items})
    if path == "/api/fcx/items":
        conv = int((q.get("c") or ["0"])[0] or 0)
        with A.conn() as c:
            if conv:
                if not _member(c, conv, uid): return h.sendj({"error": "You are not part of this chat."}, 403)
                rows = c.execute("SELECT * FROM fcx_items WHERE conversation_id=? AND kind IN ('task','reminder','event','poll') AND deleted_at='' ORDER BY done, CASE WHEN due_at='' THEN 1 ELSE 0 END, due_at, id DESC LIMIT 300", (conv,)).fetchall()
            elif (q.get("all") or [""])[0]:
                # Everything I can see: my own list plus items in the chats / Circles I'm in.
                rows = c.execute("SELECT i.* FROM fcx_items i WHERE i.kind IN ('task','reminder','event','poll') AND i.deleted_at='' AND ((i.conversation_id=0 AND i.owner_id=?) OR "
                                 "i.conversation_id IN (SELECT conversation_id FROM fc_members WHERE user_id=?)) "
                                 "ORDER BY i.done, CASE WHEN i.due_at='' THEN 1 ELSE 0 END, i.due_at, i.id DESC LIMIT 400", (uid, uid)).fetchall()
            else:
                rows = c.execute("SELECT * FROM fcx_items WHERE conversation_id=0 AND owner_id=? AND kind IN ('task','reminder','event','poll') AND deleted_at='' ORDER BY done, CASE WHEN due_at='' THEN 1 ELSE 0 END, due_at, id DESC LIMIT 300", (uid,)).fetchall()
            items = [_item_out(c, r, uid) for r in rows]
            titles = {}
            for it in items:
                cid = it["conversation_id"]
                if cid and cid not in titles:
                    t = c.execute("SELECT title,kind FROM fc_conversations WHERE id=?", (cid,)).fetchone()
                    titles[cid] = (t["title"] if t and t["kind"] == "group" else "") or "Chat"
                it["where"] = titles.get(cid, "")
        return h.sendj({"items": items})
    m = re.fullmatch(r"/api/fcx/item/(\d+)", path)
    if m:
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcx_items WHERE id=?", (int(m.group(1)),)).fetchone()
            if not _can_see_item(c, r, uid): return h.sendj({"error": "This item was removed or isn't shared with you."}, 404)
            return h.sendj({"item": _item_out(c, r, uid)})
    if path == "/api/fcx/backup/info":
        with A.conn() as c:
            n_conv = c.execute("SELECT COUNT(*) AS n FROM fc_members WHERE user_id=?", (uid,)).fetchone()["n"]
            n_msg = c.execute("SELECT COUNT(*) AS n FROM fc_members m JOIN fc_messages x ON x.conversation_id=m.conversation_id "
                              "WHERE m.user_id=? AND x.id>m.cleared_id AND x.deleted_at=''", (uid,)).fetchone()["n"]
            n_hidden = c.execute("SELECT COUNT(*) AS n FROM fc_members m JOIN fc_messages x ON x.conversation_id=m.conversation_id "
                                 "WHERE m.user_id=? AND x.id<=m.cleared_id AND x.deleted_at=''", (uid,)).fetchone()["n"]
            last = c.execute("SELECT MAX(x.created_at) AS t FROM fc_members m JOIN fc_messages x ON x.conversation_id=m.conversation_id WHERE m.user_id=?", (uid,)).fetchone()["t"]
        return h.sendj({"chats": int(n_conv), "messages": int(n_msg), "cleared": int(n_hidden), "backed_up_at": last or A.now()})
    if path == "/api/fcx/backup":
        cid = int((q.get("c") or ["0"])[0] or 0)
        out = []
        with A.conn() as c:
            mems = c.execute("SELECT m.conversation_id,m.cleared_id,cv.kind,cv.title FROM fc_members m JOIN fc_conversations cv ON cv.id=m.conversation_id "
                             "WHERE m.user_id=?" + (" AND m.conversation_id=?" if cid else "") + " ORDER BY cv.updated_at DESC", (uid, cid) if cid else (uid,)).fetchall()
            for mm in mems:
                conv = int(mm["conversation_id"])
                if mm["kind"] == "group": title = mm["title"] or "Group"
                else:
                    o = c.execute("SELECT u.name FROM fc_members o JOIN users u ON u.id=o.user_id WHERE o.conversation_id=? AND o.user_id<>? LIMIT 1", (conv, uid)).fetchone()
                    title = (o["name"] if o else "") or mm["title"] or "Chat"
                rows = c.execute("SELECT x.id,x.sender_id,x.body,x.kind,x.meta,x.created_at,x.deleted_at,u.name FROM fc_messages x LEFT JOIN users u ON u.id=x.sender_id "
                                 "WHERE x.conversation_id=? AND x.id>? ORDER BY x.id LIMIT 20000", (conv, int(mm["cleared_id"] or 0))).fetchall()
                msgs = []
                for r in rows:
                    if r["deleted_at"]: continue
                    att = [a["filename"] for a in c.execute("SELECT filename FROM fc_attachments WHERE message_id=?", (int(r["id"]),)).fetchall()]
                    text = r["body"] or ""
                    if r["kind"] not in ("text", "system", "call") and not text: text = "[" + r["kind"] + "]"
                    msgs.append({"at": r["created_at"], "from": "You" if int(r["sender_id"]) == uid else (r["name"] or "Someone"), "text": text, "files": att})
                out.append({"chat": title, "kind": mm["kind"], "messages": msgs})
        return h.sendj({"exported_at": A.now(), "account": u["email"], "chats": out})
    if path == "/api/fcx/sessions":
        t = _token(h)
        with A.conn() as c:
            rows = c.execute("SELECT token,created_at,expires_at FROM auth_sessions WHERE user_id=? AND expires_at>? ORDER BY created_at DESC LIMIT 30", (uid, A.now())).fetchall()
        return h.sendj({"items": [{"id": hashlib.sha1(r["token"].encode()).hexdigest()[:10], "created_at": r["created_at"], "expires_at": r["expires_at"], "current": r["token"] == t} for r in rows]})
    return h.sendj({"error": "Not found"}, 404)


def _token(h):
    a = h.headers.get("Authorization", "") or ""
    return a[7:].strip() if a.lower().startswith("bearer ") else ""


# ---------------------------------------------------------------- POST
def handle_post(h, path, d):
    u = h.require(); uid = int(u["id"]); d = d or {}
    if path == "/api/fcx/ping":
        _touch(uid); return h.sendj({"ok": True})
    if path == "/api/fcx/profile":
        name = str(d.get("name", u["name"]) or "").strip()[:60]
        if len(name) < 2: return h.sendj({"error": "Your name needs at least 2 letters."}, 400)
        about = str(d.get("about", "") or "").strip()[:140]
        with A.conn() as c:
            if "photo" in d:
                photo = str(d.get("photo") or "")
                if photo and (not photo.startswith(("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")) or len(photo) > 2_800_000):
                    return h.sendj({"error": "Choose a JPG, PNG or WebP picture up to 2 MB."}, 400)
                c.execute("UPDATE users SET name=?,profile_photo=? WHERE id=?", (name, photo, uid))
            else:
                c.execute("UPDATE users SET name=? WHERE id=?", (name, uid))
            p = prefs(c, uid); p["about"] = about; _save_prefs(c, uid, p)
        return h.sendj({"ok": True})
    if path == "/api/fcx/prefs":
        with A.conn() as c:
            p = prefs(c, uid)
            for k, v in d.items():
                if k in CHOICES and v in CHOICES[k]: p[k] = v
                elif k in BOOLS: p[k] = bool(v)
                elif k == "language" and v in LANGS: p[k] = v
                elif k == "app_lang" and isinstance(v, str) and re.fullmatch(r"[a-z]{2,3}", v): p[k] = v
                elif k == "birthday" and isinstance(v, dict):
                    try:
                        dd, mm = int(v.get("d") or 0), int(v.get("m") or 0); yy = int(v.get("y") or 0)
                        if not (1 <= mm <= 12 and 1 <= dd <= 31): p["birthday"] = {}
                        else:
                            datetime.date(2000, mm, dd)   # valid day for that month (29 Feb allowed)
                            p["birthday"] = {"d": dd, "m": mm, "y": yy if 1900 <= yy <= _now().year else 0}
                    except (ValueError, TypeError): pass
                elif k in ("sos", "gogo_people") and isinstance(v, list):
                    p[k] = [int(x) for x in v if str(x).isdigit()][:12]
                elif k == "celebrate" and isinstance(v, list):
                    p["celebrate"] = [str(x)[:24] for x in v if re.fullmatch(r"[\w*-]{1,24}", str(x))][:80]
                elif k == "biz" and isinstance(v, dict):
                    p["biz"] = {f: str(v.get(f) or "").strip()[:300 if f == "about" else 120] for f in ("name", "category", "about", "hours", "address", "website", "email")}
            _save_prefs(c, uid, p)
        return h.sendj({"ok": True, "prefs": p})
    if path == "/api/fcx/block":
        other = int(d.get("user_id") or 0)
        if not other and d.get("c"):
            with A.conn() as c:
                r = c.execute("SELECT o.user_id FROM fc_members o JOIN fc_conversations cv ON cv.id=o.conversation_id WHERE o.conversation_id=? AND o.user_id<>? AND cv.kind<>'group' LIMIT 1", (int(d["c"]), uid)).fetchone()
                other = int(r["user_id"]) if r else 0
        if not other or other == uid: return h.sendj({"error": "Choose someone to block."}, 400)
        with A.conn() as c:
            if d.get("on", True):
                if not c.execute("SELECT 1 FROM fcx_blocks WHERE user_id=? AND blocked_id=?", (uid, other)).fetchone():
                    c.execute("INSERT INTO fcx_blocks(user_id,blocked_id,created_at) VALUES(?,?,?)", (uid, other, A.now()))
            else:
                c.execute("DELETE FROM fcx_blocks WHERE user_id=? AND blocked_id=?", (uid, other))
        return h.sendj({"ok": True})
    if path == "/api/fcx/item":
        kind = str(d.get("kind") or "")
        if kind not in ITEM_KINDS: return h.sendj({"error": "Unknown item type."}, 400)
        title = str(d.get("title") or "").strip()[:200]
        if not title: return h.sendj({"error": "Give it a title first." if kind != "poll" else "Type your question first."}, 400)
        conv = int(d.get("c") or 0)
        opts = []
        if kind == "poll":
            opts = [str(o).strip()[:80] for o in (d.get("options") or []) if str(o).strip()][:10]
            if len(opts) < 2: return h.sendj({"error": "A poll needs at least two answers."}, 400)
            if not conv: return h.sendj({"error": "Polls are shared in a chat or Circle."}, 400)
        due = _iso(d.get("due_at"))
        if kind == "reminder" and not due: return h.sendj({"error": "Choose when to remind you."}, 400)
        stamp = A.now()
        with A.conn() as c:
            if conv and not _member(c, conv, uid): return h.sendj({"error": "You are not part of this chat."}, 403)
            if conv and direct_block(c, conv, uid): return h.sendj({"error": "You can't share with this person."}, 403)
            iid = int(c.execute("INSERT INTO fcx_items(owner_id,conversation_id,kind,title,notes,due_at,place,options,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) RETURNING id",
                                (uid, conv, kind, title, str(d.get("notes") or "").strip()[:1000], due, str(d.get("place") or "").strip()[:160],
                                 json.dumps(opts), stamp, stamp)).fetchone()["id"])
            if conv:
                body = ICONS[kind] + " " + LABEL[kind] + ": " + title
                mid = _post_in_chat(c, conv, u, body, {"fcx": iid, "fcx_kind": kind})
                c.execute("UPDATE fcx_items SET message_id=? WHERE id=?", (mid, iid))
            r = c.execute("SELECT * FROM fcx_items WHERE id=?", (iid,)).fetchone()
            out = _item_out(c, r, uid)
        if conv: _push_conv(conv, u, ICONS[kind] + " " + LABEL[kind] + ": " + title)
        return h.sendj({"ok": True, "item": out})
    if path in ("/api/fcx/item/update", "/api/fcx/item/delete", "/api/fcx/vote", "/api/fcx/rsvp"):
        iid = int(d.get("id") or 0)
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcx_items WHERE id=?", (iid,)).fetchone()
            if not _can_see_item(c, r, uid): return h.sendj({"error": "This item was removed or isn't shared with you."}, 404)
            stamp = A.now()
            if path == "/api/fcx/vote":
                if r["kind"] != "poll": return h.sendj({"error": "That isn't a poll."}, 400)
                ch = int(d.get("choice", -1))
                n = len(json.loads(r["options"] or "[]"))
                c.execute("DELETE FROM fcx_votes WHERE item_id=? AND user_id=?", (iid, uid))
                if 0 <= ch < n: c.execute("INSERT INTO fcx_votes(item_id,user_id,choice,created_at) VALUES(?,?,?,?)", (iid, uid, ch, stamp))
            elif path == "/api/fcx/rsvp":
                ans = str(d.get("answer") or "")
                c.execute("DELETE FROM fcx_rsvps WHERE item_id=? AND user_id=?", (iid, uid))
                if ans in ("yes", "maybe", "no"): c.execute("INSERT INTO fcx_rsvps(item_id,user_id,answer,created_at) VALUES(?,?,?,?)", (iid, uid, ans, stamp))
            elif path == "/api/fcx/item/delete":
                if int(r["owner_id"]) != uid: return h.sendj({"error": "Only the person who made it can delete it."}, 403)
                c.execute("UPDATE fcx_items SET deleted_at=?,updated_at=? WHERE id=?", (stamp, stamp, iid))
                return h.sendj({"ok": True})
            else:
                sets, vals = [], []
                if "done" in d: sets += ["done=?", "done_by=?"]; vals += [1 if d.get("done") else 0, uid if d.get("done") else 0]
                if int(r["owner_id"]) == uid:
                    if "title" in d and str(d.get("title") or "").strip(): sets.append("title=?"); vals.append(str(d["title"]).strip()[:200])
                    if "notes" in d: sets.append("notes=?"); vals.append(str(d.get("notes") or "").strip()[:1000])
                    if "place" in d: sets.append("place=?"); vals.append(str(d.get("place") or "").strip()[:160])
                    if "due_at" in d: sets += ["due_at=?", "reminded=0"]; vals.append(_iso(d.get("due_at")))
                if sets:
                    c.execute("UPDATE fcx_items SET " + ",".join(sets) + ",updated_at=? WHERE id=?", vals + [stamp, iid])
            r = c.execute("SELECT * FROM fcx_items WHERE id=?", (iid,)).fetchone()
            return h.sendj({"ok": True, "item": _item_out(c, r, uid)})
    if path == "/api/fcx/translate":
        text = str(d.get("text") or "").strip()[:2000]
        to = str(d.get("to") or "English")
        if to not in LANGS: to = "English"
        if not text: return h.sendj({"error": "Nothing to translate."}, 400)
        out = _translate(text, to)
        if not out: return h.sendj({"error": "Translation isn't available right now. Please try again in a minute."}, 503)
        return h.sendj({"text": out, "to": to})
    if path == "/api/fcx/broadcast":
        body = str(d.get("body") or "").strip()[:4000]
        ids = [int(x) for x in (d.get("conversations") or []) if str(x).isdigit()][:100]
        if not body: return h.sendj({"error": "Type your message first."}, 400)
        if not ids: return h.sendj({"error": "Choose at least one chat."}, 400)
        sent = []
        with A.conn() as c:
            for cid in ids:
                if not _member(c, cid, uid) or direct_block(c, cid, uid): continue
                _post_in_chat(c, cid, u, body, {"broadcast": 1}); sent.append(cid)
        for cid in sent: _push_conv(cid, u, body[:120])
        return h.sendj({"ok": True, "sent": len(sent)})
    if path == "/api/fcx/report":
        body = str(d.get("body") or "").strip()[:3000]
        if len(body) < 5: return h.sendj({"error": "Tell us a little more about the problem."}, 400)
        with A.conn() as c:
            c.execute("INSERT INTO fcx_reports(user_id,body,created_at) VALUES(?,?,?)", (uid, body, A.now()))
        try:
            notify = getattr(A, "sv_notify_owner", None)
            if notify: notify("Future Chat problem report", (u.get("name") or "") + " <" + (u.get("email") or "") + ">\n\n" + body)
        except Exception: pass
        return h.sendj({"ok": True, "message": "Thank you. Your report reached the Future Chat team."})
    if path == "/api/fcx/schedule":
        cid = int(d.get("c") or 0); body = str(d.get("body") or "").strip()[:4000]
        meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
        when = _iso(d.get("send_at"))
        if not body: return h.sendj({"error": "Type your message first."}, 400)
        if not when: return h.sendj({"error": "Choose when to send it."}, 400)
        if when <= _now().isoformat(): return h.sendj({"error": "Choose a time in the future."}, 400)
        if when > (_now() + datetime.timedelta(days=370)).isoformat(): return h.sendj({"error": "You can schedule up to a year ahead."}, 400)
        with A.conn() as c:
            if not _member(c, cid, uid): return h.sendj({"error": "You are not part of this chat."}, 403)
            import fcpay as FP
            lim = FP.scheduled_limit(c, uid)
            if c.execute("SELECT COUNT(*) AS n FROM fcx_scheduled WHERE user_id=? AND sent_at='' AND cancelled=0", (uid,)).fetchone()["n"] >= lim:
                return h.sendj({"error": "You already have %d messages waiting to be sent." % lim + (" Get Future Chat Plus to schedule as many as you like." if lim < 50 else ""), "plus": lim < 50}, 400)
            sid = c.execute("INSERT INTO fcx_scheduled(user_id,conversation_id,body,meta,send_at,created_at) VALUES(?,?,?,?,?,?) RETURNING id",
                            (uid, cid, body, json.dumps(meta)[:4000], when, A.now())).fetchone()["id"]
        return h.sendj({"ok": True, "id": int(sid), "send_at": when})
    if path == "/api/fcx/schedule/cancel":
        with A.conn() as c:
            c.execute("UPDATE fcx_scheduled SET cancelled=1 WHERE id=? AND user_id=? AND sent_at=''", (int(d.get("id") or 0), uid))
        return h.sendj({"ok": True})
    if path == "/api/fcx/clear":
        stamp = A.now(); cid = int(d.get("c") or 0)
        with A.conn() as c:
            if d.get("all"):
                mems = [int(r["conversation_id"]) for r in c.execute("SELECT conversation_id FROM fc_members WHERE user_id=?", (uid,)).fetchall()]
            else:
                if not cid or not _member(c, cid, uid): return h.sendj({"error": "Choose a chat to clear."}, 400)
                mems = [cid]
            n = 0
            for conv in mems:
                r = c.execute("SELECT last_message_id FROM fc_conversations WHERE id=?", (conv,)).fetchone()
                last = int((r["last_message_id"] if r else 0) or 0)
                if not last: continue
                c.execute("UPDATE fc_members SET cleared_id=?,cleared_at=?,last_read_id=CASE WHEN last_read_id<? THEN ? ELSE last_read_id END WHERE conversation_id=? AND user_id=?",
                          (last, stamp, last, last, conv, uid)); n += 1
        return h.sendj({"ok": True, "cleared": n})
    if path == "/api/fcx/restore":
        with A.conn() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM fc_members WHERE user_id=? AND cleared_id>0", (uid,)).fetchone()["n"]
            c.execute("UPDATE fc_members SET cleared_id=0,cleared_at='' WHERE user_id=?", (uid,))
        return h.sendj({"ok": True, "restored": int(n)})
    if path == "/api/fcx/sessions/logout-others":
        t = _token(h)
        with A.conn() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM auth_sessions WHERE user_id=? AND token<>?", (uid, t)).fetchone()["n"]
            c.execute("DELETE FROM auth_sessions WHERE user_id=? AND token<>?", (uid, t))
        return h.sendj({"ok": True, "signed_out": int(n)})
    return h.sendj({"error": "Not found"}, 404)
