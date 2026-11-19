"""FCG-01: Future Chat monthly giveaway (owner 2026-11-19). Free to enter: the ONLY way to get a ticket is to invite a
friend who joins and starts using Future Chat (one ticket per friend). A winner is drawn automatically on the 1st of each
month (SA time) for the month before; the prize is paid by the owner (EFT) after a quick check. No purchase can buy a
ticket (Consumer Protection Act s36 promotional competition; Google Play contests policy).

How a friend is linked to the person who invited them, without hassle:
  1. Invite link /fc/i/<code> -> Google Play install referrer (fcref=<code>) -> the app claims it after sign-up, or
  2. The inviter shared to (or tried to chat with) the friend's phone number -> matched when the friend saves that number.
A friend counts once they have a phone number on their account and have sent at least 3 messages, chatting with at least 2 different people, within 30 days.
Routes: /api/fcg/*, landing page /fc/i/<code>, rules /giveaway-rules.
"""
import datetime, hashlib, html, json, os, re, secrets, threading, time, urllib.parse

A = None
MIN_MESSAGES = 3
SA = datetime.timedelta(hours=2)
PLAY_URL = "https://play.google.com/store/apps/details?id=za.co.futurechat.app"
# The giveaway starts after the Play Store launch: friends who join before this month never count.
START = os.environ.get("FCG_START", "2026-12").strip()
# Future Chat's own website (invite links, rules) - not the Skillvaya site.
SITE = os.environ.get("FUTURECHAT_SITE", "https://futurechat-v5lx.onrender.com").strip().rstrip("/")
def _ref_month(): m = _month(); return m if m >= START else "pre"


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)


def init(c):
    pk = A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS fcg_invites(id %(pk)s, inviter_id BIGINT NOT NULL, phone TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_fcg_inv_phone ON fcg_invites(phone);
        CREATE TABLE IF NOT EXISTS fcg_refs(user_id BIGINT PRIMARY KEY, inviter_id BIGINT NOT NULL, how TEXT NOT NULL, month TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_fcg_refs_inviter ON fcg_refs(inviter_id, month);
        CREATE TABLE IF NOT EXISTS fcg_draws(month TEXT PRIMARY KEY, prize TEXT NOT NULL, winner_id BIGINT NOT NULL DEFAULT 0, tickets INTEGER NOT NULL DEFAULT 0,
            people INTEGER NOT NULL DEFAULT 0, proof TEXT NOT NULL DEFAULT '', drawn_at TEXT NOT NULL, paid_at TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS fcg_settings(k TEXT PRIMARY KEY, v TEXT NOT NULL);
    """ % {"pk": pk})
    threading.Thread(target=_loop, name="FutureChatGiveaway", daemon=True).start()


def _now(): return datetime.datetime.now(datetime.timezone.utc)
def _sa(): return _now() + SA
def _month(dt=None): return (dt or _sa()).strftime("%Y-%m")
def _month_label(m): return datetime.date(int(m[:4]), int(m[5:]), 1).strftime("%B %Y")


def _prize(c):
    r = c.execute("SELECT v FROM fcg_settings WHERE k='prize'").fetchone()
    return r["v"] if r else "R500"


def code_for(uid):
    """Short, stable invite code for a person (no lookups needed to make it)."""
    secret = os.environ.get("SKILLVAYA_SECRET_KEY", "sv")
    h = hashlib.sha256(("fcg|%d|%s" % (uid, secret)).encode()).hexdigest()[:4]
    return _b36(uid) + h


def _b36(n):
    s = ""
    while True:
        n, r = divmod(n, 36); s = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + s
        if not n: return s


def user_for(code):
    code = str(code or "").strip().lower()
    if not re.fullmatch(r"[0-9a-z]{5,14}", code): return 0
    try: uid = int(code[:-4], 36)
    except ValueError: return 0
    return uid if code_for(uid) == code else 0


def record_invite(inviter_id, phone):
    """Remember that someone invited this phone number (from the invite screen, or by trying to chat with it)."""
    try:
        if not phone: return
        with A.conn() as c:
            if c.execute("SELECT 1 FROM users WHERE phone_e164=? AND phone_verified_at<>''", (phone,)).fetchone(): return
            if c.execute("SELECT 1 FROM fcg_invites WHERE inviter_id=? AND phone=?", (int(inviter_id), phone)).fetchone(): return
            c.execute("INSERT INTO fcg_invites(inviter_id,phone,created_at) VALUES(?,?,?)", (int(inviter_id), phone, A.now()))
    except Exception as exc:
        print("Future Chat invite not recorded:", type(exc).__name__)


def _link_by_phone():
    """New people whose number someone invited get linked to the FIRST person who invited them."""
    since = (_now() - datetime.timedelta(days=30)).isoformat()
    with A.conn() as c:
        rows = c.execute("SELECT u.id,u.phone_e164,u.created_at FROM users u WHERE u.created_at>=? AND u.phone_e164<>'' AND u.phone_verified_at<>'' "
                         "AND NOT EXISTS (SELECT 1 FROM fcg_refs r WHERE r.user_id=u.id)", (since,)).fetchall()
        for u in rows:
            inv = c.execute("SELECT inviter_id,created_at FROM fcg_invites WHERE phone=? AND inviter_id<>? AND created_at<=? ORDER BY created_at LIMIT 1",
                            (u["phone_e164"], int(u["id"]), u["created_at"])).fetchone()
            if not inv: continue
            c.execute("INSERT INTO fcg_refs(user_id,inviter_id,how,month,created_at) VALUES(?,?,?,?,?)", (int(u["id"]), int(inv["inviter_id"]), "phone", _ref_month(), A.now()))


def _qualifies(c, friend_id):
    u = c.execute("SELECT phone_verified_at,phone_verify_method,created_at FROM users WHERE id=?", (friend_id,)).fetchone()
    if not u or not u["phone_verified_at"]: return False, "needs to add their phone number"
    if not A.FV.is_confirmed(u): return False, "needs to confirm their phone number"
    n = int(c.execute("SELECT COUNT(*) AS n FROM fc_messages WHERE sender_id=? AND kind NOT IN ('system','call') AND deleted_at=''", (friend_id,)).fetchone()["n"])
    if n < MIN_MESSAGES: return False, "needs to send %d more message%s" % (MIN_MESSAGES - n, "" if MIN_MESSAGES - n == 1 else "s")
    # a real person talks to more than one person: chats with at least 2 different people count
    partners = int(c.execute("SELECT COUNT(DISTINCT o.user_id) AS n FROM fc_members m JOIN fc_members o ON o.conversation_id=m.conversation_id AND o.user_id<>m.user_id "
                             "WHERE m.user_id=? AND EXISTS (SELECT 1 FROM fc_messages x WHERE x.conversation_id=m.conversation_id AND x.sender_id=m.user_id)", (friend_id,)).fetchone()["n"])
    if partners < 2: return False, "needs to chat with one more person"
    return True, ""


def tickets(c, month):
    """{inviter_id: number of tickets} for a month."""
    out = {}
    for r in c.execute("SELECT user_id,inviter_id FROM fcg_refs WHERE month=?", (month,)).fetchall():
        if _qualifies(c, int(r["user_id"]))[0]: out[int(r["inviter_id"])] = out.get(int(r["inviter_id"]), 0) + 1
    return out


# ---------------------------------------------------------------- the monthly draw
def _loop():
    time.sleep(90)
    while True:
        try: _link_by_phone()
        except Exception as exc: print("Future Chat invite matching skipped:", type(exc).__name__)
        try: _draw_due()
        except Exception as exc: print("Future Chat giveaway draw skipped:", type(exc).__name__)
        time.sleep(600)


def _draw_due():
    now = _sa()
    if now.hour < 8: return
    prev = _month(now.replace(day=1) - datetime.timedelta(days=1))
    if prev >= START: draw(prev)


def draw(month):
    with A.conn() as c:
        if c.execute("SELECT 1 FROM fcg_draws WHERE month=?", (month,)).fetchone(): return None
        t = tickets(c, month)
        owners = {int(r["id"]) for r in c.execute("SELECT id FROM users WHERE role='admin'").fetchall()}
        t = {k: v for k, v in t.items() if k not in owners}            # the owner and staff can't win
        total = sum(t.values())
        winner = 0
        if total:
            pick = secrets.randbelow(total)
            for uid in sorted(t):
                if pick < t[uid]: winner = uid; break
                pick -= t[uid]
        proof = hashlib.sha256(json.dumps({"month": month, "tickets": sorted(t.items()), "winner": winner}).encode()).hexdigest()
        prize = _prize(c)
        c.execute("INSERT INTO fcg_draws(month,prize,winner_id,tickets,people,proof,drawn_at) VALUES(?,?,?,?,?,?,?)", (month, prize, winner, total, len(t), proof, A.now()))
        wname = ""
        if winner:
            w = c.execute("SELECT name FROM users WHERE id=?", (winner,)).fetchone(); wname = (w["name"] if w else "") or "Someone"
    send = getattr(A, "fcm_send_to_user", None)
    if winner and send:
        try: send(winner, "\U0001f389 You won the Future Chat giveaway!", "You won %s for %s. We'll message you in Future Chat to arrange payment." % (prize, _month_label(month)), {"type": "fc_give", "url": "/futurechat-app?fcx=give"})
        except Exception: pass
        for o in owners:
            try: send(o, "Giveaway winner: " + wname, "%s won %s for %s (%d tickets). Check their friends are real, then pay." % (wname, prize, _month_label(month), total), {"type": "fc_give", "url": "/futurechat-app?fcx=give"})
            except Exception: pass
    if winner: _announce(month, wname, prize)
    return winner


def _announce(month, name, prize):
    """A free Shout-out so everyone sees there was a real winner (first name + first letter of the surname only)."""
    try:
        parts = name.split(); short = parts[0] + (" " + parts[-1][0] + "." if len(parts) > 1 else "")
        start = _now()
        with A.conn() as c:
            owner = c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
            if not owner: return
            c.execute("INSERT INTO home_ads(user_id,kind,headline,body,cta,target,advertiser,media_mime,media_b64,product_id,status,paid_at,note,created_at,updated_at,starts_at,ends_at,extra) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (int(owner["id"]), "word", "\U0001f389 %s won %s!" % (short, prize), "The %s Future Chat giveaway. Invite friends to Future Chat for your chance next month — 1 friend who joins = 1 ticket." % _month_label(month),
                       "", "", "Future Chat", "", "", "futurechat_shout_3d", "active", A.now(), "Giveaway winner", A.now(), A.now(), start.isoformat(), (start + datetime.timedelta(days=3)).isoformat(),
                       json.dumps({"design": "congrats", "audience": "all"})))
    except Exception as exc:
        print("Future Chat giveaway announcement skipped:", type(exc).__name__)


# ---------------------------------------------------------------- pages
def _base(h):
    host = h.headers.get("Host") or "skillvaya.onrender.com"
    return ("https://" if "localhost" not in host and "127.0.0.1" not in host else "http://") + host


def landing(h, path):
    """Old-style links on this server go to Future Chat's own website."""
    code = path.rsplit("/", 1)[-1]
    uid = user_for(code)
    name = ""
    if uid:
        with A.conn() as c:
            r = c.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
            name = ((r["name"] if r else "") or "").split(" ")[0]
    h.send_response(302); h.send_header("Location", invite_link(code, name)); h.send_header("Content-Length", "0"); h.end_headers()


def invite_link(code, first_name=""):
    return SITE + "/?i=" + code + ("&n=" + urllib.parse.quote(first_name) if first_name else "")


def _old_landing(h, path):
    code = path.rsplit("/", 1)[-1]
    uid = user_for(code)
    name = ""
    if uid:
        with A.conn() as c:
            r = c.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
            name = ((r["name"] if r else "") or "").split(" ")[0]
    play = PLAY_URL + "&referrer=" + urllib.parse.quote("fcref=" + code) if uid else PLAY_URL
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Join me on Future Chat</title><meta property="og:title" content="%(t)s"><meta property="og:description" content="Free chats, calls, Chatmoji and Lenses. Stay close, wherever life takes you.">
<style>body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:linear-gradient(180deg,#0a1f33,#0f3150 55%%,#11506a);color:#eaf4ff;min-height:100vh;display:flex;align-items:center;justify-content:center}
.w{max-width:420px;padding:32px 24px;text-align:center}.mk{width:84px;height:84px;border-radius:50%%;background:linear-gradient(135deg,#5ff0e2,#12a8d0);display:grid;place-items:center;margin:0 auto 14px;font-size:40px}
h1{font-size:26px;margin:8px 0}p{color:#cfe3f2;line-height:1.5}.b{display:block;margin:22px 0 10px;padding:16px;border-radius:16px;background:linear-gradient(90deg,#1ed6c8,#5fc4ff);color:#05283a;font-weight:800;text-decoration:none;font-size:17px}
.s{font-size:13px;color:#9cb7cc}.code{display:inline-block;margin-top:6px;padding:6px 12px;border-radius:10px;background:rgba(255,255,255,.1);font-family:monospace;font-size:16px;letter-spacing:2px}</style></head>
<body><div class="w"><div class="mk">\U0001f4ac</div><h1>%(t)s</h1><p>Future Chat is free: chats, voice and video calls, Chatmoji, Lenses, family Circles and more.</p>
<a class="b" href="%(play)s">Get Future Chat</a><p class="s">%(codeline)s</p></div></body></html>""" % {
        "t": html.escape(("%s invited you to Future Chat" % name) if name else "Join me on Future Chat"), "play": html.escape(play),
        "codeline": ("Your invite code: <span class='code'>%s</span><br>It's added automatically when you install from this page." % html.escape(code)) if uid else ""}
    data = page.encode("utf-8")
    h.send_response(200); h.send_header("Content-Type", "text/html; charset=utf-8"); h.send_header("Cache-Control", "public, max-age=300")
    h.send_header("Content-Length", str(len(data))); h.end_headers(); h.wfile.write(data)


def rules_page(h):
    with A.conn() as c: prize = _prize(c)
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Future Chat giveaway rules</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:0 auto;padding:24px;line-height:1.6;color:#0b1d33}h1{font-size:24px}li{margin:6px 0}</style></head><body>
<h1>Future Chat monthly giveaway &mdash; rules</h1>
<ol>
<li><b>Promoter:</b> Future Chat (Skillvaya), South Africa. Contact: through the Help and safety screen in the app.</li>
<li><b>Prize:</b> %(prize)s each calendar month, paid by EFT into a South African bank account in the winner's name within 30 days of the draw. The prize can't be exchanged for anything else.</li>
<li><b>Free to enter:</b> no payment or purchase is needed or possible. The only way to get a ticket is to invite a friend to Future Chat. You get 1 ticket for every friend who joins during that month through your invite link, invite code or an invite sent to their phone number, confirms their phone number by SMS in the app and sends at least %(n)d messages to at least 2 different people within 30 days of joining.</li>
<li>Each friend counts once, for the first person who invited them. Fake, duplicate or bought accounts don't count, and anyone who tries to cheat can be disqualified.</li>
<li><b>The draw:</b> the app draws 1 winner at random from all tickets on the 1st of the next month (South African time). More tickets = more chances. A record of every draw is kept for at least 3 years.</li>
<li><b>Who can enter:</b> anyone with a Future Chat account. Winners under 18 must have a parent or guardian accept the prize for them. The owner, staff and anyone who helps run the giveaway, and their close family, can't win.</li>
<li><b>The winner</b> is told in Future Chat and by notification, and must reply within 14 days or a new winner is drawn. Their first name and the first letter of their surname are shown in Shout-outs.</li>
<li>Personal information is used only to run the giveaway, as set out in the Future Chat Privacy Policy.</li>
<li>These rules are free to anyone who asks, including the National Consumer Commission. The promoter may change or end the giveaway with notice in the app; draws already running are completed.</li>
</ol></body></html>""" % {"prize": html.escape(prize), "n": MIN_MESSAGES}
    data = page.encode("utf-8")
    h.send_response(200); h.send_header("Content-Type", "text/html; charset=utf-8"); h.send_header("Content-Length", str(len(data))); h.end_headers(); h.wfile.write(data)


# ---------------------------------------------------------------- API
def handle_get(h, path):
    u = h.require(); uid = int(u["id"])
    if path == "/api/fcg/me":
        m = _month()
        with A.conn() as c:
            refs = c.execute("SELECT r.user_id,r.month,r.how,r.created_at,u.name FROM fcg_refs r JOIN users u ON u.id=r.user_id WHERE r.inviter_id=? ORDER BY r.created_at DESC LIMIT 100", (uid,)).fetchall()
            friends, mine = [], 0
            for r in refs:
                ok, why = _qualifies(c, int(r["user_id"]))
                if ok and r["month"] == m: mine += 1
                if r["month"] == "pre": ok, why = False, "joined before the giveaway started"
                friends.append({"name": (r["name"] or "Friend").split(" ")[0], "month": r["month"], "ticket": ok, "why": why, "this_month": r["month"] == m})
            last = c.execute("SELECT d.*,u.name FROM fcg_draws d LEFT JOIN users u ON u.id=d.winner_id ORDER BY d.month DESC LIMIT 1").fetchone()
            invited = int(c.execute("SELECT COUNT(*) AS n FROM fcg_invites WHERE inviter_id=?", (uid,)).fetchone()["n"])
            total = sum(tickets(c, m).values())
            prize = _prize(c)
            owner = c.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()["role"] == "admin"
            won = [{"month": _month_label(r["month"]), "prize": r["prize"], "paid": bool(r["paid_at"])} for r in c.execute("SELECT * FROM fcg_draws WHERE winner_id=? ORDER BY month DESC", (uid,)).fetchall()]
        nxt = (_sa().replace(day=1) + datetime.timedelta(days=32)).replace(day=1, hour=8, minute=0, second=0, microsecond=0) - SA
        code = code_for(uid)
        last_out = None
        if last:
            n = (last["name"] or "").split(); last_out = {"month": _month_label(last["month"]), "prize": last["prize"], "name": (n[0] + (" " + n[-1][0] + "." if len(n) > 1 else "")) if n else "", "tickets": int(last["tickets"])}
        first = (u.get("name") or "").split(" ")[0] if hasattr(u, "get") else ""
        return h.sendj({"code": code, "link": invite_link(code, first), "site": SITE, "starts": _month_label(START) if _month() < START else "", "prize": prize, "month": _month_label(m), "draw_at": nxt.isoformat(), "my_tickets": mine,
                        "all_tickets": total, "friends": friends, "invited": invited, "last": last_out, "won": won, "owner": owner, "min_messages": MIN_MESSAGES})
    if path == "/api/fcg/admin":
        with A.conn() as c:
            if c.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()["role"] != "admin": return h.sendj({"error": "Owner only."}, 403)
            m = _month(); t = tickets(c, m)
            names = {int(r["id"]): r["name"] for r in c.execute("SELECT id,name FROM users WHERE id IN (%s)" % ",".join(str(int(k)) for k in t) if t else "SELECT id,name FROM users WHERE 0=1").fetchall()}
            draws = [{"month": _month_label(r["month"]), "key": r["month"], "prize": r["prize"], "winner": r["name"] or "", "winner_id": int(r["winner_id"]), "phone": r["phone"] or "", "tickets": int(r["tickets"]), "people": int(r["people"]), "paid": bool(r["paid_at"]), "proof": r["proof"][:16]}
                     for r in c.execute("SELECT d.*,u.name,u.phone FROM fcg_draws d LEFT JOIN users u ON u.id=d.winner_id ORDER BY d.month DESC LIMIT 24").fetchall()]
            return h.sendj({"prize": _prize(c), "month": _month_label(m), "leaders": sorted([{"name": names.get(k, ""), "tickets": v} for k, v in t.items()], key=lambda x: -x["tickets"])[:50], "draws": draws})
    return h.sendj({"error": "Not found"}, 404)


def handle_post(h, path, d):
    u = h.require(); uid = int(u["id"]); d = d or {}
    if path == "/api/fcg/invite":
        phone = A.FC.normalize_phone(str(d.get("phone") or ""))
        if not phone: return h.sendj({"error": "Enter your friend's full phone number."}, 400)
        with A.conn() as c:
            if c.execute("SELECT 1 FROM users WHERE phone_e164=? AND phone_verified_at<>''", (phone,)).fetchone():
                return h.sendj({"error": "Good news — that number is already on Future Chat. Start a chat with them instead.", "member": True}, 409)
        record_invite(uid, phone)
        return h.sendj({"ok": True, "phone": phone})
    if path == "/api/fcg/claim":
        inviter = user_for(d.get("code"))
        if not inviter or inviter == uid: return h.sendj({"ok": False})
        with A.conn() as c:
            me = c.execute("SELECT created_at FROM users WHERE id=?", (uid,)).fetchone()
            if c.execute("SELECT 1 FROM fcg_refs WHERE user_id=?", (uid,)).fetchone(): return h.sendj({"ok": False, "already": True})
            try: new = (_now() - datetime.datetime.fromisoformat(me["created_at"].replace("Z", "+00:00"))).days <= 3
            except Exception: new = False
            if not new: return h.sendj({"ok": False, "reason": "Invite codes are for new accounts."})
            c.execute("INSERT INTO fcg_refs(user_id,inviter_id,how,month,created_at) VALUES(?,?,?,?,?)", (uid, inviter, "link", _ref_month(), A.now()))
        return h.sendj({"ok": True})
    if path == "/api/fcg/admin":
        with A.conn() as c:
            if c.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()["role"] != "admin": return h.sendj({"error": "Owner only."}, 403)
            if d.get("prize"):
                p = str(d.get("prize")).strip()[:40]
                if c.execute("SELECT 1 FROM fcg_settings WHERE k='prize'").fetchone(): c.execute("UPDATE fcg_settings SET v=? WHERE k='prize'", (p,))
                else: c.execute("INSERT INTO fcg_settings(k,v) VALUES('prize',?)", (p,))
            if d.get("paid"): c.execute("UPDATE fcg_draws SET paid_at=? WHERE month=?", (A.now(), str(d["paid"])))
        return h.sendj({"ok": True})
    return h.sendj({"error": "Not found"}, 404)
