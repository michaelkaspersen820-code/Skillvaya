"""FC-WAKE-01 (owner 2026-11-20): instant updates for Future Chat without changing how messages or calls work.

Every person has a small counter. When something happens that they need to see (a new message, reaction, edit or
delete in one of their chats, or a call starting / being answered / connecting / ending), their counter goes up.
The app keeps one request open to /api/fc/wait; the server answers it the moment the counter changes (or after
25 seconds with "nothing new"), and the app then fetches exactly what it fetched before - just straight away instead
of waiting for the next timed check. The old timed checks stay as a backup, only slower, so the server has less work.
"""
import threading, time, urllib.parse

A = None   # app.py namespace, set by bind() at start-up (same as the other Future Chat modules)


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)

_COND = threading.Condition()
_VER = {}            # user_id -> counter
_WAITING = [0]       # how many requests are waiting right now (kept small so the server never runs out of threads)
MAX_WAITERS = 300


def bump(user_ids):
    ids = {int(u) for u in user_ids if u}
    if not ids: return
    with _COND:
        for u in ids: _VER[u] = _VER.get(u, 0) + 1
        _COND.notify_all()


def current(uid):
    with _COND: return _VER.get(int(uid), 0)


def handle_get(h, path):
    """GET /api/fc/wait?v=<last counter>&t=<seconds> -> {"v": counter, "changed": bool}."""
    u = h.require(); uid = int(u["id"])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    try: seen = int((q.get("v") or ["-1"])[0])
    except ValueError: seen = -1
    try: t = max(1.0, min(25.0, float((q.get("t") or ["25"])[0])))
    except ValueError: t = 25.0
    with _COND:
        now_v = _VER.get(uid, 0)
        if seen != now_v or _WAITING[0] >= MAX_WAITERS:
            v = now_v
        else:
            _WAITING[0] += 1
            try:
                end = time.monotonic() + t
                while _VER.get(uid, 0) == now_v:
                    left = end - time.monotonic()
                    if left <= 0: break
                    _COND.wait(left)
                v = _VER.get(uid, 0)
            finally:
                _WAITING[0] -= 1
    return h.sendj({"v": v, "changed": v != seen})


def after_post(h, path, d):
    """Called after every POST (the response has already been sent). Never raises."""
    try:
        if not isinstance(d, dict): return
        # Messages only (owner 2026-11-20): calls keep their own proven checks and are never woken from here.
        if path not in ("/api/fc/send", "/api/fc/react", "/api/fc/edit", "/api/fc/delete", "/api/fc/add-members", "/api/fc/settings"): return
        try: actor = int((h.user() or {}).get("id") or 0)
        except Exception: actor = 0
        uids = set()
        with A.conn() as c:
            conv = 0
            if path in ("/api/fc/send", "/api/fc/add-members", "/api/fc/settings"):
                conv = int(d.get("c") or 0)
            elif path in ("/api/fc/react", "/api/fc/edit", "/api/fc/delete"):
                r = c.execute("SELECT conversation_id FROM fc_messages WHERE id=?", (int(d.get("m") or 0),)).fetchone()
                conv = int(r["conversation_id"]) if r else 0
            elif path == "/api/video-calls":
                if str(d.get("action") or "") == "start":
                    conv = int(d.get("conversation_id") or 0)
                else:
                    r = c.execute("SELECT caller_id,callee_id FROM video_calls WHERE id=?", (str(d.get("call_id") or "")[:100],)).fetchone()
                    if r: uids.update((int(r["caller_id"]), int(r["callee_id"])))
            if conv:
                uids.update(int(r["user_id"]) for r in c.execute("SELECT user_id FROM fc_members WHERE conversation_id=?", (conv,)).fetchall())
        uids.discard(actor)
        bump(uids)
    except Exception as exc:
        print("Future Chat wake skipped:", type(exc).__name__)
