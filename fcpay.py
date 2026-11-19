"""FCP-01: Future Chat shop for everyone (owner 2026-11-19): small payments for individual people.

- Premium greeting cards (R5 each, animated, optional voice message)
- Event invitations (R15 each: RSVP with guest count, reminders, map)
- Chat theme packs (R10 each, or all for R39) and quiz packs (R5 each)  - kept for good
- Future Chat Plus (R20 a month): HD video calls, files up to 48 MB, unlimited scheduled messages, stokvel record export, Plus themes
- Shout-outs (R5/R15) and proposals (R29) run in Sponsored status through homeads.py (same fair turns as ads)
Payments go through Google Play in the Future Chat app; this server checks every purchase with Google before granting it.
The owner (admin) gets everything free. Routes: /api/fcp/*.
"""
import base64, csv, datetime, io, json, os, re, threading, time, urllib.parse, uuid

A = None
PKG = lambda: os.environ.get("FUTURECHAT_PLAY_PACKAGE_NAME", "za.co.futurechat.app").strip()

THEME_PACKS = ["ocean", "sunset", "nature", "heritage", "faith", "love", "neon", "kids", "galaxy", "festive", "sport", "luxury"]
QUIZ_PACKS = ["bible", "soccer", "science", "world", "animals", "history"]
CATALOG = {
    # product id: (type, price cents, what it gives, title)
    "futurechat_card_premium": ("consumable", 500, "card", "Premium greeting card"),
    "futurechat_event_invite": ("consumable", 1500, "event", "Event invitation"),
    "futurechat_themes_all": ("unlock", 3900, "themes:*", "Every theme pack"),
    "futurechat_plus_monthly": ("sub", 2000, "plus", "Future Chat Plus"),
}
for _p in THEME_PACKS: CATALOG["futurechat_theme_" + _p] = ("unlock", 1000, "theme:" + _p, "Theme pack")
for _p in QUIZ_PACKS: CATALOG["futurechat_quiz_" + _p] = ("unlock", 500, "quiz:" + _p, "Quiz pack")

FREE_FILE = 16 * 1024 * 1024
PLUS_FILE = 48 * 1024 * 1024
FREE_SCHEDULED, PLUS_SCHEDULED = 5, 200
UPLOAD_DIR = os.path.join(os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp", "fcp_uploads")


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)


def init(c):
    pk = A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS fcp_owned(id %(pk)s, user_id BIGINT NOT NULL, product_id TEXT NOT NULL, token TEXT NOT NULL, order_id TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fcp_owned_token ON fcp_owned(token);
        CREATE INDEX IF NOT EXISTS idx_fcp_owned_user ON fcp_owned(user_id);
        CREATE TABLE IF NOT EXISTS fcp_credits(user_id BIGINT NOT NULL, what TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, what));
        CREATE TABLE IF NOT EXISTS fcp_events(id %(pk)s, owner_id BIGINT NOT NULL, title TEXT NOT NULL, starts_at TEXT NOT NULL, place TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '', design TEXT NOT NULL DEFAULT 'party', reminded INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS fcp_event_chats(event_id BIGINT NOT NULL, conversation_id BIGINT NOT NULL, PRIMARY KEY(event_id, conversation_id));
        CREATE TABLE IF NOT EXISTS fcp_rsvp(event_id BIGINT NOT NULL, user_id BIGINT NOT NULL, answer TEXT NOT NULL, guests INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL, PRIMARY KEY(event_id, user_id));
        CREATE TABLE IF NOT EXISTS fcp_uploads(id TEXT PRIMARY KEY, user_id BIGINT NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL, size BIGINT NOT NULL, got BIGINT NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
    """ % {"pk": pk})
    try: c.execute("ALTER TABLE home_ads ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'")
    except Exception: pass
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    threading.Thread(target=_loop, name="FutureChatShop", daemon=True).start()


def _now(): return datetime.datetime.now(datetime.timezone.utc)


def _is_owner(c, uid):
    r = c.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and r["role"] == "admin")


def entitlements(c, uid):
    owner = _is_owner(c, uid)
    now = _now().isoformat()
    rows = c.execute("SELECT product_id,expires_at FROM fcp_owned WHERE user_id=?", (uid,)).fetchall()
    unlocks, plus_until = set(), ""
    for r in rows:
        t = CATALOG.get(r["product_id"])
        if not t: continue
        if t[0] == "unlock": unlocks.add(t[2])
        if t[0] == "sub" and r["expires_at"] > now: plus_until = max(plus_until, r["expires_at"])
    if "themes:*" in unlocks: unlocks |= {"theme:" + p for p in THEME_PACKS}
    if owner: unlocks |= {"theme:" + p for p in THEME_PACKS} | {"quiz:" + p for p in QUIZ_PACKS}
    credits = {r["what"]: int(r["n"]) for r in c.execute("SELECT what,n FROM fcp_credits WHERE user_id=?", (uid,)).fetchall()}
    plus = owner or bool(plus_until)
    return {"owner": owner, "plus": plus, "plus_until": plus_until, "unlocks": sorted(unlocks),
            "credits": {"card": 999 if owner else credits.get("card", 0), "event": 999 if owner else credits.get("event", 0)},
            "file_limit": PLUS_FILE if plus else FREE_FILE, "scheduled_limit": PLUS_SCHEDULED if plus else FREE_SCHEDULED}


def is_plus(c, uid):
    try: return entitlements(c, uid)["plus"]
    except Exception: return False


def has_unlock(c, uid, what):
    try: return what in entitlements(c, uid)["unlocks"]
    except Exception: return True


def scheduled_limit(c, uid):
    try: return entitlements(c, uid)["scheduled_limit"]
    except Exception: return 50


def _use_credit(c, uid, what):
    if _is_owner(c, uid): return True
    r = c.execute("SELECT n FROM fcp_credits WHERE user_id=? AND what=?", (uid, what)).fetchone()
    if not r or int(r["n"]) <= 0: return False
    c.execute("UPDATE fcp_credits SET n=n-1 WHERE user_id=? AND what=?", (uid, what))
    return True


def _add_credit(c, uid, what, n=1):
    if c.execute("SELECT 1 FROM fcp_credits WHERE user_id=? AND what=?", (uid, what)).fetchone():
        c.execute("UPDATE fcp_credits SET n=n+? WHERE user_id=? AND what=?", (n, uid, what))
    else:
        c.execute("INSERT INTO fcp_credits(user_id,what,n) VALUES(?,?,?)", (uid, what, n))


def _member(c, cid, uid): return bool(c.execute("SELECT 1 FROM fc_members WHERE conversation_id=? AND user_id=?", (cid, uid)).fetchone())


def _post(c, cid, u, body, meta, kind="text", att=None):
    stamp = A.now()
    mid = int(c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,meta,created_at) VALUES(?,?,?,?,?,?) RETURNING id",
                        (cid, int(u["id"]), body, kind, json.dumps(meta), stamp)).fetchone()["id"])
    if att:
        c.execute("INSERT INTO fc_attachments(message_id,conversation_id,filename,mime_type,size_bytes,data_base64,created_at) VALUES(?,?,?,?,?,?,?)",
                  (mid, cid, att[0], att[1], att[2], att[3], stamp))
    c.execute("UPDATE fc_conversations SET last_message_id=?,updated_at=? WHERE id=?", (mid, stamp, cid))
    c.execute("UPDATE fc_members SET last_read_id=? WHERE conversation_id=? AND user_id=?", (mid, cid, int(u["id"])))
    c.execute("UPDATE fc_members SET archived=0 WHERE conversation_id=?", (cid,))
    return mid


def _push(cid, u, text):
    try: A.FC._push(cid, u, text)
    except Exception as exc: print("Future Chat shop push skipped:", type(exc).__name__)


def _publisher():
    import homeads as HA
    return HA._publisher()


# ---------------------------------------------------------------- event reminders
def _loop():
    time.sleep(60)
    while True:
        try: _remind()
        except Exception as exc: print("Future Chat event reminders skipped:", type(exc).__name__)
        time.sleep(300)


def _remind():
    send = getattr(A, "fcm_send_to_user", None)
    now = _now()
    jobs = []
    with A.conn() as c:
        for r in c.execute("SELECT * FROM fcp_events WHERE cancelled=0 AND reminded<2 AND starts_at>? AND starts_at<?",
                           (now.isoformat(), (now + datetime.timedelta(hours=26)).isoformat())).fetchall():
            hours = (datetime.datetime.fromisoformat(r["starts_at"]) - now).total_seconds() / 3600
            stage = 2 if hours <= 2.2 else 1 if hours <= 24.5 else 0
            if stage <= int(r["reminded"]): continue
            c.execute("UPDATE fcp_events SET reminded=? WHERE id=?", (stage, int(r["id"])))
            people = {int(r["owner_id"])} | {int(x["user_id"]) for x in c.execute("SELECT user_id FROM fcp_rsvp WHERE event_id=? AND answer IN ('yes','maybe')", (int(r["id"]),)).fetchall()}
            for p in people: jobs.append((p, r["title"], "Today, in about 2 hours" if stage == 2 else "Tomorrow", int(r["id"])))
    if not send: return
    for p, title, when, eid in jobs:
        try: send(p, "\U0001f4c5 " + title, when + (" — see you there!"), {"type": "fc_event", "url": "/futurechat-app?fcx=event&id=%d" % eid})
        except Exception: pass


# ---------------------------------------------------------------- GET
def _event_out(c, r, uid):
    rs = c.execute("SELECT r.*,u.name FROM fcp_rsvp r JOIN users u ON u.id=r.user_id WHERE r.event_id=? ORDER BY r.updated_at", (int(r["id"]),)).fetchall()
    mine = next((x for x in rs if int(x["user_id"]) == uid), None)
    owner = int(r["owner_id"]) == uid
    cnt = {"yes": 0, "maybe": 0, "no": 0}; people = 0
    for x in rs:
        if x["answer"] in cnt: cnt[x["answer"]] += 1
        if x["answer"] == "yes": people += 1 + int(x["guests"] or 0)
    host = c.execute("SELECT name FROM users WHERE id=?", (int(r["owner_id"]),)).fetchone()
    d = {"id": int(r["id"]), "title": r["title"], "starts_at": r["starts_at"], "place": r["place"], "note": r["note"], "design": r["design"], "cancelled": bool(r["cancelled"]),
         "host": host["name"] if host else "", "mine": owner, "counts": cnt, "coming": people,
         "my_answer": mine["answer"] if mine else "", "my_guests": int(mine["guests"]) if mine else 0}
    if owner: d["guests"] = [{"name": x["name"], "answer": x["answer"], "guests": int(x["guests"] or 0), "note": x["note"]} for x in rs]
    return d


def _can_see_event(c, eid, uid):
    return bool(c.execute("SELECT 1 FROM fcp_events e WHERE e.id=? AND (e.owner_id=? OR EXISTS (SELECT 1 FROM fcp_event_chats x JOIN fc_members m ON m.conversation_id=x.conversation_id WHERE x.event_id=e.id AND m.user_id=?))",
                          (eid, uid, uid)).fetchone())


def handle_get(h, path):
    u = h.require(); uid = int(u["id"])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    if path == "/api/fcp/me":
        with A.conn() as c: e = entitlements(c, uid)
        e["catalog"] = [{"product_id": k, "type": v[0], "price": "R%d" % (v[1] // 100), "gives": v[2], "title": v[3]} for k, v in CATALOG.items()]
        e["theme_packs"], e["quiz_packs"] = THEME_PACKS, QUIZ_PACKS
        return h.sendj(e)
    m = re.fullmatch(r"/api/fcp/event/(\d+)", path)
    if m:
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcp_events WHERE id=?", (int(m.group(1)),)).fetchone()
            if not r or not _can_see_event(c, int(r["id"]), uid): return h.sendj({"error": "This invitation is no longer available."}, 404)
            return h.sendj({"event": _event_out(c, r, uid)})
    if path == "/api/fcp/events":
        with A.conn() as c:
            rows = c.execute("SELECT DISTINCT e.* FROM fcp_events e LEFT JOIN fcp_event_chats x ON x.event_id=e.id LEFT JOIN fc_members m ON m.conversation_id=x.conversation_id "
                             "WHERE (e.owner_id=? OR m.user_id=?) AND e.starts_at>? ORDER BY e.starts_at LIMIT 50", (uid, uid, (_now() - datetime.timedelta(days=1)).isoformat())).fetchall()
            return h.sendj({"items": [_event_out(c, r, uid) for r in rows]})
    if path == "/api/fcp/stokvel.csv":
        cid = int((q.get("c") or ["0"])[0] or 0)
        with A.conn() as c:
            if not _member(c, cid, uid): return h.sendj({"error": "You are not in this group."}, 403)
            if not is_plus(c, uid): return h.sendj({"error": "Saving the stokvel record is part of Future Chat Plus.", "plus": True}, 402)
            st = c.execute("SELECT * FROM fc_stokvels WHERE conversation_id=?", (cid,)).fetchone()
            if not st: return h.sendj({"error": "This group has no stokvel yet."}, 404)
            pays = c.execute("SELECT p.*,u.name FROM fc_stokvel_payments p JOIN users u ON u.id=p.user_id WHERE p.stokvel_id=? ORDER BY p.period, u.name", (int(st["id"]),)).fetchall()
        out = io.StringIO(); w = csv.writer(out)
        w.writerow(["Stokvel", st["name"]]); w.writerow(["Amount each round", "%s %.2f" % (st["currency"], int(st["amount_cents"]) / 100)]); w.writerow(["How often", st["frequency"]]); w.writerow([])
        w.writerow(["Round", "Member", "Amount", "Note", "Marked paid", "Confirmed"])
        for p in pays: w.writerow([p["period"], p["name"], "%.2f" % (int(p["amount_cents"]) / 100), p["note"], p["marked_at"][:16].replace("T", " "), "yes" if p["confirmed_at"] else "no"])
        data = out.getvalue().encode("utf-8-sig")
        h.send_response(200); h.send_header("Content-Type", "text/csv; charset=utf-8")
        h.send_header("Content-Disposition", 'attachment; filename="%s.csv"' % re.sub(r"[^\w -]", "", st["name"] or "stokvel")[:40])
        h.send_header("Content-Length", str(len(data))); h.end_headers(); h.wfile.write(data); return
    return h.sendj({"error": "Not found"}, 404)


# ---------------------------------------------------------------- POST
def handle_post(h, path, d):
    u = h.require(); uid = int(u["id"]); d = d or {}
    if path == "/api/fcp/verify":
        pid = str(d.get("product_id") or ""); token = str(d.get("purchase_token") or "").strip()
        item = CATALOG.get(pid)
        if not item or not token or len(token) > 4096: return h.sendj({"error": "A valid Google Play purchase is required."}, 400)
        with A.conn() as c:
            done = c.execute("SELECT user_id FROM fcp_owned WHERE token=?", (token,)).fetchone()
        if done:
            if int(done["user_id"]) != uid: return h.sendj({"error": "This purchase belongs to another account."}, 403)
            return h.sendj({"ok": True, "already": True, "consume": item[0] == "consumable", "acknowledge": item[0] != "consumable"})
        expires = ""
        try:
            pub = _publisher()
            if pub is None: return h.sendj({"error": "Google Play has your payment, but we couldn't confirm it yet. Keep the app open; it will retry."}, 503)
            if item[0] == "sub":
                v = pub.purchases().subscriptionsv2().get(packageName=PKG(), token=token).execute()
                if v.get("subscriptionState") not in ("SUBSCRIPTION_STATE_ACTIVE", "SUBSCRIPTION_STATE_IN_GRACE_PERIOD"): return h.sendj({"error": "This subscription is not active."}, 409)
                expires = max((li.get("expiryTime") or "") for li in (v.get("lineItems") or [{}]))
                expires = A_iso(expires)
                acct = ((v.get("externalAccountIdentifiers") or {}).get("obfuscatedExternalAccountId") or "")
                order = str(v.get("latestOrderId") or "")
            else:
                v = pub.purchases().products().get(packageName=PKG(), productId=pid, token=token).execute()
                if int(v.get("purchaseState", 1)) != 0: return h.sendj({"error": "This Google Play payment is not complete yet."}, 409)
                acct = str(v.get("obfuscatedExternalAccountId") or ""); order = str(v.get("orderId") or "")
        except Exception:
            return h.sendj({"error": "Google Play could not confirm this payment yet. Keep the app open; it will retry."}, 503)
        import homeads as HA
        if acct and acct != HA._account_hash(uid): return h.sendj({"error": "This payment belongs to a different account."}, 403)
        with A.conn() as c:
            c.execute("INSERT INTO fcp_owned(user_id,product_id,token,order_id,expires_at,created_at) VALUES(?,?,?,?,?,?)", (uid, pid, token, order, expires, A.now()))
            if item[0] == "consumable": _add_credit(c, uid, item[2])
            e = entitlements(c, uid)
        return h.sendj({"ok": True, "consume": item[0] == "consumable", "acknowledge": item[0] != "consumable", "me": e,
                        "message": {"card": "Card ready to send \U0001f389", "event": "Invitation ready — fill in the details \U0001f4c5"}.get(item[2], "Thank you! It's yours ✨")})
    if path == "/api/fcp/card":   # a premium card (uses one card credit), optional short voice message
        cid = int(d.get("c") or 0); design = str(d.get("design") or "")[:24]; title = str(d.get("title") or "").strip()[:80]; words = str(d.get("body") or "").strip()[:600]
        if not re.fullmatch(r"[a-z0-9_-]{2,24}", design): return h.sendj({"error": "Choose a card design."}, 400)
        att = None
        v = d.get("voice")
        if isinstance(v, dict) and v.get("data_base64"):
            try: raw = base64.b64decode(str(v["data_base64"]).split(",")[-1], validate=False)
            except Exception: return h.sendj({"error": "The voice message could not be read."}, 400)
            if len(raw) > 5 * 1024 * 1024: return h.sendj({"error": "Keep the voice message under about 2 minutes."}, 400)
            att = ("card-voice.webm", str(v.get("mime") or "audio/webm")[:60], len(raw), base64.b64encode(raw).decode())
        with A.conn() as c:
            if not _member(c, cid, uid): return h.sendj({"error": "You are not part of this chat."}, 403)
            if not _use_credit(c, uid, "card"): return h.sendj({"error": "Buy a premium card first.", "buy": "futurechat_card_premium"}, 402)
            mid = _post(c, cid, u, (title + " " + words).strip(), {"card": {"k": d.get("k") or "bday", "t": title, "premium": design}}, "voice" if att else "text", att)
        _push(cid, u, "\U0001f381 " + (title or "A card for you"))
        return h.sendj({"ok": True, "id": mid})
    if path == "/api/fcp/event":
        title = str(d.get("title") or "").strip()[:90]; place = str(d.get("place") or "").strip()[:160]; note = str(d.get("note") or "").strip()[:800]
        design = str(d.get("design") or "party")[:20]
        import fcextras as FX
        when = FX._iso(d.get("starts_at"))
        chats = [int(x) for x in (d.get("chats") or []) if str(x).isdigit()][:30]
        if len(title) < 3: return h.sendj({"error": "Give your event a name."}, 400)
        if not when or when < _now().isoformat(): return h.sendj({"error": "Choose a date and time in the future."}, 400)
        if not chats: return h.sendj({"error": "Choose who to invite."}, 400)
        with A.conn() as c:
            chats = [x for x in chats if _member(c, x, uid)]
            if not chats: return h.sendj({"error": "Choose who to invite."}, 400)
            if not _use_credit(c, uid, "event"): return h.sendj({"error": "Buy an event invitation first.", "buy": "futurechat_event_invite"}, 402)
            eid = int(c.execute("INSERT INTO fcp_events(owner_id,title,starts_at,place,note,design,created_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
                                (uid, title, when, place, note, design, A.now())).fetchone()["id"])
            for x in chats:
                c.execute("INSERT INTO fcp_event_chats(event_id,conversation_id) VALUES(?,?)", (eid, x))
                _post(c, x, u, "\U0001f48c You're invited: " + title, {"invite": eid, "design": design})
            c.execute("INSERT INTO fcp_rsvp(event_id,user_id,answer,guests,updated_at) VALUES(?,?,?,?,?)", (eid, uid, "yes", 0, A.now()))
        for x in chats: _push(x, u, "\U0001f48c You're invited: " + title)
        return h.sendj({"ok": True, "id": eid})
    if path == "/api/fcp/rsvp":
        eid = int(d.get("id") or 0); ans = str(d.get("answer") or "")
        if ans not in ("yes", "maybe", "no"): return h.sendj({"error": "Choose an answer."}, 400)
        guests = max(0, min(20, int(d.get("guests") or 0))); note = str(d.get("note") or "").strip()[:200]
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcp_events WHERE id=? AND cancelled=0", (eid,)).fetchone()
            if not r or not _can_see_event(c, eid, uid): return h.sendj({"error": "This invitation is no longer available."}, 404)
            if c.execute("SELECT 1 FROM fcp_rsvp WHERE event_id=? AND user_id=?", (eid, uid)).fetchone():
                c.execute("UPDATE fcp_rsvp SET answer=?,guests=?,note=?,updated_at=? WHERE event_id=? AND user_id=?", (ans, guests, note, A.now(), eid, uid))
            else:
                c.execute("INSERT INTO fcp_rsvp(event_id,user_id,answer,guests,note,updated_at) VALUES(?,?,?,?,?,?)", (eid, uid, ans, guests, note, A.now()))
            owner = int(r["owner_id"]); title = r["title"]
        if owner != uid:
            send = getattr(A, "fcm_send_to_user", None)
            word = {"yes": "is coming" + (" (+%d)" % guests if guests else ""), "maybe": "might come", "no": "can't make it"}[ans]
            try:
                if send: send(owner, "\U0001f48c " + title, (u["name"] or "Someone").split(" ")[0] + " " + word, {"type": "fc_event", "url": "/futurechat-app?fcx=event&id=%d" % eid})
            except Exception: pass
        return h.sendj({"ok": True})
    if path == "/api/fcp/event/cancel":
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcp_events WHERE id=? AND owner_id=?", (int(d.get("id") or 0), uid)).fetchone()
            if not r: return h.sendj({"error": "Not found"}, 404)
            c.execute("UPDATE fcp_events SET cancelled=1 WHERE id=?", (int(r["id"]),))
            for x in c.execute("SELECT conversation_id FROM fcp_event_chats WHERE event_id=?", (int(r["id"]),)).fetchall():
                _post(c, int(x["conversation_id"]), u, "❌ Cancelled: " + r["title"], {"invite": int(r["id"]), "cancelled": 1})
        return h.sendj({"ok": True})
    # ---- big files for Plus: sent in pieces so phones on weak networks and the server never hold a huge request
    if path == "/api/fcp/upload/start":
        size = int(d.get("size") or 0); name = re.sub(r"[\\/\r\n]", "_", str(d.get("name") or "file"))[:120]; mime = str(d.get("mime") or "application/octet-stream")[:100]
        with A.conn() as c:
            lim = entitlements(c, uid)["file_limit"]
            if size <= 0: return h.sendj({"error": "That file is empty."}, 400)
            if size > lim: return h.sendj({"error": "Files can be up to %d MB%s." % (lim // 1048576, "" if lim > FREE_FILE else " (48 MB with Future Chat Plus)"), "plus": lim <= FREE_FILE}, 413)
            up = uuid.uuid4().hex
            c.execute("INSERT INTO fcp_uploads(id,user_id,name,mime,size,created_at) VALUES(?,?,?,?,?,?)", (up, uid, name, mime, size, A.now()))
        open(os.path.join(UPLOAD_DIR, up), "wb").close()
        return h.sendj({"ok": True, "id": up, "chunk": 3 * 1024 * 1024})
    if path == "/api/fcp/upload/chunk":
        up = str(d.get("id") or ""); off = int(d.get("offset") or 0)
        if not re.fullmatch(r"[0-9a-f]{32}", up): return h.sendj({"error": "Upload not found."}, 404)
        try: raw = base64.b64decode(str(d.get("data_base64") or ""), validate=True)
        except Exception: return h.sendj({"error": "A piece of the file could not be read."}, 400)
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcp_uploads WHERE id=? AND user_id=?", (up, uid)).fetchone()
            if not r: return h.sendj({"error": "Upload not found."}, 404)
            if off != int(r["got"]): return h.sendj({"ok": True, "got": int(r["got"])})        # resend from where the server is
            if off + len(raw) > int(r["size"]): return h.sendj({"error": "The file is bigger than expected."}, 400)
            with open(os.path.join(UPLOAD_DIR, up), "ab") as f: f.write(raw)
            c.execute("UPDATE fcp_uploads SET got=? WHERE id=?", (off + len(raw), up))
        return h.sendj({"ok": True, "got": off + len(raw)})
    if path == "/api/fcp/upload/finish":
        up = str(d.get("id") or ""); cid = int(d.get("c") or 0); kind = str(d.get("kind") or "file"); body = str(d.get("body") or "")[:6000]
        if kind not in ("photo", "video", "voice", "file"): kind = "file"
        if not re.fullmatch(r"[0-9a-f]{32}", up): return h.sendj({"error": "Upload not found."}, 404)
        with A.conn() as c:
            r = c.execute("SELECT * FROM fcp_uploads WHERE id=? AND user_id=?", (up, uid)).fetchone()
            if not r or int(r["got"]) != int(r["size"]): return h.sendj({"error": "The file didn't finish uploading. Try again."}, 409)
            A.FC._require_member(c, cid, u)
            if A.FC._blocked(c, cid, uid): return h.sendj({"error": "You can't send messages in this chat."}, 403)
            p = os.path.join(UPLOAD_DIR, up)
            with open(p, "rb") as f: b64 = base64.b64encode(f.read()).decode()
            stamp = A.now()
            mid = int(c.execute("INSERT INTO fc_messages(conversation_id,sender_id,body,kind,meta,created_at) VALUES(?,?,?,?,?,?) RETURNING id", (cid, uid, body, kind, "{}", stamp)).fetchone()["id"])
            aid = int(c.execute("INSERT INTO fc_attachments(message_id,conversation_id,filename,mime_type,size_bytes,data_base64,created_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
                                (mid, cid, r["name"], r["mime"], int(r["size"]), b64, stamp)).fetchone()["id"])
            c.execute("UPDATE fc_conversations SET last_message_id=?,updated_at=? WHERE id=?", (mid, stamp, cid))
            c.execute("UPDATE fc_members SET last_read_id=?,archived=0 WHERE conversation_id=? AND user_id=?", (mid, cid, uid))
            c.execute("UPDATE fc_members SET archived=0 WHERE conversation_id=?", (cid,))
            c.execute("DELETE FROM fcp_uploads WHERE id=?", (up,))
        try: os.remove(p)
        except OSError: pass
        _push(cid, u, {"photo": "\U0001f4f7 Photo", "video": "\U0001f3a5 Video", "voice": "\U0001f3a4 Voice note"}.get(kind, "\U0001f4ce " + r["name"]))
        return h.sendj({"ok": True, "id": mid, "attachments": [aid], "created_at": stamp})
    # ---- proposals: the person being asked answers in the chat
    if path == "/api/fcp/proposal/answer":
        ad_id = int(d.get("id") or 0); ans = str(d.get("answer") or "")
        if ans not in ("yes", "moment"): return h.sendj({"error": "Choose an answer."}, 400)
        with A.conn() as c:
            ad = c.execute("SELECT * FROM home_ads WHERE id=?", (ad_id,)).fetchone()
            if not ad: return h.sendj({"error": "Not found"}, 404)
            ex = _extra(ad)
            if int(ex.get("to") or 0) != uid: return h.sendj({"error": "Only the person being asked can answer."}, 403)
            ex["answer"] = ans; ex["answered_at"] = A.now()
            c.execute("UPDATE home_ads SET extra=?,updated_at=? WHERE id=?", (json.dumps(ex), A.now(), ad_id))
            conv = int(ex.get("conv") or 0)
            if conv and ans == "yes": _post(c, conv, u, "\U0001f48d YES! \U0001f496", {"proposal_answer": ad_id, "answer": "yes"})
            elif conv: _post(c, conv, u, "\U0001f497 I need a moment… let's talk", {"proposal_answer": ad_id, "answer": "moment"})
        if conv: _push(conv, u, "\U0001f48d YES! \U0001f496" if ans == "yes" else "\U0001f497 Let's talk")
        return h.sendj({"ok": True})
    return h.sendj({"error": "Not found"}, 404)


def _extra(ad):
    try: return json.loads(ad["extra"] or "{}")
    except (ValueError, KeyError, IndexError, TypeError): return {}


def A_iso(s):
    try:
        dt = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt.astimezone(datetime.timezone.utc).isoformat()
    except ValueError:
        return (_now() + datetime.timedelta(days=31)).isoformat()


def proposal_live(ad_id):
    """Called when a proposal goes live: the person being asked gets a special card in their chat with the proposer."""
    try:
        with A.conn() as c:
            ad = c.execute("SELECT * FROM home_ads WHERE id=?", (ad_id,)).fetchone()
            ex = _extra(ad) if ad else {}
            to = int(ex.get("to") or 0)
            if not to or ex.get("conv"): return
            frm = c.execute("SELECT id,name FROM users WHERE id=?", (int(ad["user_id"]),)).fetchone()
            lo, hi = sorted((int(ad["user_id"]), to)); key = "d:%d:%d" % (lo, hi)
            row = c.execute("SELECT id FROM fc_conversations WHERE pair_key=?", (key,)).fetchone()
            stamp = A.now()
            if row: conv = int(row["id"])
            else:
                conv = int(c.execute("INSERT INTO fc_conversations(kind,title,pair_key,created_by,created_at,updated_at) VALUES('direct','',?,?,?,?) RETURNING id", (key, lo, stamp, stamp)).fetchone()["id"])
                for m in (lo, hi): c.execute("INSERT INTO fc_members(conversation_id,user_id,joined_at) VALUES(?,?,?)", (conv, m, stamp))
            ex["conv"] = conv
            c.execute("UPDATE home_ads SET extra=? WHERE id=?", (json.dumps(ex), ad_id))
            _post(c, conv, frm, "\U0001f48d " + (ad["headline"] or "Will you marry me?"), {"proposal": ad_id, "words": ad["body"] or ""})
        _push(conv, frm, "\U0001f48d " + (ad["headline"] or "Will you marry me?"))
    except Exception as exc:
        print("Future Chat proposal card skipped:", type(exc).__name__)
