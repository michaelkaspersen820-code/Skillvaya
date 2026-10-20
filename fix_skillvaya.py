from pathlib import Path
p=Path(r"C:\Users\user\Documents\Codex\Skillvaya\app.py")
s=p.read_text(encoding="utf-8")
old='''def notify(kind, subject, body):
    with conn() as c:
        c.execute("INSERT INTO notifications(kind,subject,body,created_at) VALUES(?,?,?,?)",(kind,subject,body,now()))
    # Email delivery is enabled only when the owner supplies SMTP settings as environment variables.
    recipient=setting("owner_email")
    host=os.environ.get("SKILLVAYA_SMTP_HOST","")
    port=int(os.environ.get("SKILLVAYA_SMTP_PORT","587") or "587")
    user=os.environ.get("SKILLVAYA_SMTP_USER","")
    password=os.environ.get("SKILLVAYA_SMTP_PASSWORD","")
    sender=os.environ.get("SKILLVAYA_SMTP_FROM",user)
    if not (recipient and host and user and password and sender):
        return False
    try:
        import smtplib
        from email.message import EmailMessage
        m=EmailMessage(); m["Subject"]="[Skillvaya] "+subject; m["From"]=sender; m["To"]=recipient
        m.set_content(body)
        with smtplib.SMTP(host,port,timeout=12) as server:
            server.starttls(); server.login(user,password); server.send_message(m)
        with conn() as c:
            c.execute("UPDATE notifications SET emailed_at=?,status='emailed' WHERE id=(SELECT MAX(id) FROM notifications)",(now(),))
        return True
    except Exception:
        return False'''
new='''def send_owner_email(subject, body):
    recipient=setting("owner_email")
    host=os.environ.get("SKILLVAYA_SMTP_HOST","")
    port=int(os.environ.get("SKILLVAYA_SMTP_PORT","587") or "587")
    user=os.environ.get("SKILLVAYA_SMTP_USER","")
    password=os.environ.get("SKILLVAYA_SMTP_PASSWORD","")
    sender=os.environ.get("SKILLVAYA_SMTP_FROM",user)
    if not (recipient and host and user and password and sender): return False
    try:
        import smtplib
        from email.message import EmailMessage
        m=EmailMessage(); m["Subject"]="[Skillvaya] "+subject; m["From"]=sender; m["To"]=recipient
        m.set_content(body)
        with smtplib.SMTP(host,port,timeout=12) as server:
            server.starttls(); server.login(user,password); server.send_message(m)
        return True
    except Exception:
        return False
def notify(kind, subject, body):
    with conn() as c:
        cur=c.execute("INSERT INTO notifications(kind,subject,body,created_at) VALUES(?,?,?,?)",(kind,subject,body,now()))
        nid=cur.lastrowid
    if send_owner_email(subject,body):
        with conn() as c: c.execute("UPDATE notifications SET emailed_at=?,status='emailed' WHERE id=?",(now(),nid))
        return True
    return False'''
if old not in s: raise RuntimeError("notify block not found")
s=s.replace(old,new,1)
old='''    # Send owner alerts and customer notices through configured SMTP, if present.
    with conn() as c:
        pending=c.execute("SELECT id,kind,subject,body FROM notifications WHERE status='new' ORDER BY id LIMIT 20").fetchall()
    for n in pending:
        if notify(n["kind"],n["subject"],n["body"]):
            with conn() as c: c.execute("UPDATE notifications SET status='emailed' WHERE id=?",(n["id"],))'''
new='''    # Dispatch queued owner alerts without creating duplicate alert records.
    with conn() as c:
        pending=c.execute("SELECT id,subject,body FROM notifications WHERE status='new' ORDER BY id LIMIT 20").fetchall()
    for n in pending:
        if send_owner_email(n["subject"],n["body"]):
            with conn() as c: c.execute("UPDATE notifications SET status='emailed',emailed_at=? WHERE id=?",(now(),n["id"]))'''
if old not in s: raise RuntimeError("expiry dispatch block not found")
s=s.replace(old,new,1)
old='''                        notify("payment_verified","Payment verified","Payment reference "+row["reference"]+" has been marked verified. Amount: R"+str(row["amount"])+".")
                        return self.sendj({"ok":True})'''
new='''                        c.execute("INSERT INTO notifications(kind,subject,body,created_at) VALUES(?,?,?,?)",("payment_verified","Payment verified","Payment reference "+row["reference"]+" has been marked verified. Amount: R"+str(row["amount"])+".",now()))
                        return self.sendj({"ok":True})'''
if old not in s: raise RuntimeError("payment notification block not found")
s=s.replace(old,new,1)
p.write_text(s,encoding="utf-8")
print("Notification queue corrected")
