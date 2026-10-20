from pathlib import Path
p=Path(r"C:\Users\user\Documents\Codex\Skillvaya\app.py")
s=p.read_text(encoding="utf-8")
old='''    # Dispatch queued owner alerts without creating duplicate alert records.
    with conn() as c:'''
new='''    # Cancel unpaid payment requests after a 7-day grace window.
    cutoff=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=7)).isoformat()
    with conn() as c:
        pending=c.execute("SELECT p.*,u.email,u.name,b.name business_name FROM payments p JOIN users u ON u.id=p.user_id LEFT JOIN businesses b ON b.id=p.business_id WHERE p.status='pending' AND p.created_at<=?",(cutoff,)).fetchall()
        for pay in pending:
            c.execute("UPDATE payments SET status='expired' WHERE id=?",(pay["id"],))
            if pay["business_id"]:
                c.execute("UPDATE businesses SET status='suspended',payment_status='overdue' WHERE id=? AND payment_status!='verified'",(pay["business_id"],))
            business=pay["business_name"] or "your provider listing"
            c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("payment_expired","Unpaid plan request cancelled","Hello "+pay["name"]+", your Skillvaya plan request ("+pay["reference"]+") for "+business+" expired because payment was not confirmed within 7 days. The paid placement is not active. Sign in to request a new plan when ready.",now(),pay["email"]))
            c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("owner_alert","Unpaid plan request expired","Account: "+pay["email"]+"; reference: "+pay["reference"]+"; amount: R"+str(pay["amount"])+"; business: "+business+". Request expired and listing was paused where applicable.",now(),setting("owner_email")))
    # Dispatch queued owner alerts without creating duplicate alert records.
    with conn() as c:'''
if old not in s: raise RuntimeError("expiry dispatcher anchor missing")
s=s.replace(old,new,1)
p.write_text(s,encoding="utf-8")
print("7-day unpaid plan expiry added")
