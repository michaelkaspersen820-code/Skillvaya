from pathlib import Path
p=Path(r"C:\Users\user\Documents\Codex\Skillvaya\app.py")
s=p.read_text(encoding="utf-8")
s=s.replace('''CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL, emailed_at TEXT);''','''CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL, emailed_at TEXT, recipient TEXT NOT NULL DEFAULT '');''',1)
s=s.replace('''        cols={r[1] for r in c.execute("PRAGMA table_info(businesses)")}''','''        ncols={r[1] for r in c.execute("PRAGMA table_info(notifications)")}
        if "recipient" not in ncols:
            c.execute("ALTER TABLE notifications ADD COLUMN recipient TEXT NOT NULL DEFAULT ''")
        cols={r[1] for r in c.execute("PRAGMA table_info(businesses)")}''',1)
s=s.replace('''def send_owner_email(subject, body):
    recipient=setting("owner_email")''','''def send_owner_email(subject, body, recipient=None):
    recipient=recipient or setting("owner_email")''',1)
s=s.replace('''def notify(kind, subject, body):
    with conn() as c:
        cur=c.execute("INSERT INTO notifications(kind,subject,body,created_at) VALUES(?,?,?,?)",(kind,subject,body,now()))
        nid=cur.lastrowid
    if send_owner_email(subject,body):''','''def notify(kind, subject, body, recipient=""):
    with conn() as c:
        cur=c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",(kind,subject,body,now(),recipient))
        nid=cur.lastrowid
    if send_owner_email(subject,body,recipient or None):''',1)
s=s.replace('''c.execute("INSERT INTO notifications(kind,subject,body,created_at) VALUES(?,?,?,?)",("subscription_overdue","Paid listing suspended: "+b["name"],"Hello "+owner["name"]+", your Skillvaya paid placement has expired because renewal payment was not confirmed. The listing is paused. Sign in and renew to request reactivation. Account email: "+owner["email"],now()))
                # Queue owner alert; provider email can be sent by a configured mail service in the next sweep.
                c.execute("INSERT INTO notifications(kind,subject,body,created_at) VALUES(?,?,?,?)",("owner_alert","Subscription overdue: "+b["name"],"Provider account: "+owner["email"]+"; business: "+b["name"]+"; listing paused automatically.",now()))''','''c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("subscription_overdue","Paid listing suspended: "+b["name"],"Hello "+owner["name"]+", your Skillvaya paid placement has expired because renewal payment was not confirmed. The listing is paused. Sign in and renew to request reactivation. Account email: "+owner["email"],now(),owner["email"]))
                c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("owner_alert","Subscription overdue: "+b["name"],"Provider account: "+owner["email"]+"; business: "+b["name"]+"; listing paused automatically.",now(),setting("owner_email")))''',1)
s=s.replace('''pending=c.execute("SELECT id,subject,body FROM notifications WHERE status='new' ORDER BY id LIMIT 20").fetchall()
    for n in pending:
        if send_owner_email(n["subject"],n["body"]):''','''pending=c.execute("SELECT id,subject,body,recipient FROM notifications WHERE status='new' ORDER BY id LIMIT 20").fetchall()
    for n in pending:
        if send_owner_email(n["subject"],n["body"],n["recipient"] or None):''',1)
p.write_text(s,encoding="utf-8")
print("Client email routing patched")
