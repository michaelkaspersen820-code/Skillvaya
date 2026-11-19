"""LG-01 (owner 2026-11-19): stop password guessing. Future Chat now allows short passwords (4+ characters), so after
5 wrong passwords for the same account in 15 minutes, signing in to that account is paused for 15 minutes.
A correct password (or a password reset) clears the count. app.py: bind(globals()); init(c); used by /api/login.
"""
import datetime

A = None
MAX_FAILS = 5
WINDOW_MIN = 15
LOCK_MIN = 15


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items(): setattr(A, k, v)


def init(c):
    A.execute_script(c, "CREATE TABLE IF NOT EXISTS lg_fails(email TEXT PRIMARY KEY, fails INTEGER NOT NULL DEFAULT 0, first_at TEXT NOT NULL, locked_until TEXT NOT NULL DEFAULT '');")


def _utc(): return datetime.datetime.now(datetime.timezone.utc)
def _dt(s):
    try:
        d = datetime.datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except Exception: return None


def locked_message(email):
    """None when sign-in may go ahead, otherwise the message to show."""
    email = (email or "").strip().lower()
    if not email: return None
    with A.conn() as c:
        r = c.execute("SELECT locked_until FROM lg_fails WHERE email=?", (email,)).fetchone()
    until = _dt(r["locked_until"]) if r and r["locked_until"] else None
    if not until or until <= _utc(): return None
    mins = max(1, int((until - _utc()).total_seconds() // 60) + 1)
    return "Too many wrong passwords. For your safety, signing in to this account is paused for %d more minute%s. You can tap \"Forgot password\" to set a new one." % (mins, "" if mins == 1 else "s")


def failed(email):
    email = (email or "").strip().lower()
    if not email: return
    now = _utc()
    with A.conn() as c:
        r = c.execute("SELECT fails,first_at FROM lg_fails WHERE email=?", (email,)).fetchone()
        first = _dt(r["first_at"]) if r else None
        if not r or not first or now - first > datetime.timedelta(minutes=WINDOW_MIN):
            c.execute("INSERT INTO lg_fails(email,fails,first_at,locked_until) VALUES(?,1,?,'') ON CONFLICT(email) DO UPDATE SET fails=1, first_at=excluded.first_at, locked_until=''",
                      (email, now.isoformat()))
            return
        n = int(r["fails"]) + 1
        lock = (now + datetime.timedelta(minutes=LOCK_MIN)).isoformat() if n >= MAX_FAILS else ""
        c.execute("UPDATE lg_fails SET fails=?, locked_until=? WHERE email=?", (0 if lock else n, lock, email))
        if lock: c.execute("UPDATE lg_fails SET first_at=? WHERE email=?", (now.isoformat(), email))


def cleared(email):
    email = (email or "").strip().lower()
    if not email: return
    with A.conn() as c: c.execute("DELETE FROM lg_fails WHERE email=?", (email,))
