from pathlib import Path
p=Path(r"C:\Users\user\Documents\Codex\Skillvaya\app.py")
s=p.read_text(encoding="utf-8")
def rep(old,new,label):
    global s
    if old not in s:
        raise RuntimeError("Missing anchor: "+label)
    s=s.replace(old,new,1)
# Persisted monitoring, notifications, and owner settings.
rep('''        CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, business_id INTEGER, plan TEXT NOT NULL, billing TEXT NOT NULL, amount INTEGER NOT NULL, reference TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at TEXT NOT NULL, verified_at TEXT);
        """)''','''        CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, business_id INTEGER, plan TEXT NOT NULL, billing TEXT NOT NULL, amount INTEGER NOT NULL, reference TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at TEXT NOT NULL, verified_at TEXT);
        CREATE TABLE IF NOT EXISTS analytics(id INTEGER PRIMARY KEY, event TEXT NOT NULL, user_id INTEGER, detail TEXT DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL, emailed_at TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, user_id INTEGER NOT NULL, plan TEXT NOT NULL, billing TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', started_at TEXT NOT NULL, expires_at TEXT NOT NULL, cancelled_at TEXT, UNIQUE(business_id));
        """)
        # Safe schema migration for databases created by earlier local versions.
        cols={r[1] for r in c.execute("PRAGMA table_info(businesses)")}
        if "subscription_expires_at" not in cols:
            c.execute("ALTER TABLE businesses ADD COLUMN subscription_expires_at TEXT")
        if not c.execute("SELECT 1 FROM settings WHERE key='owner_email'").fetchone():
            c.execute("INSERT INTO settings(key,value) VALUES('owner_email','')")
        if not c.execute("SELECT 1 FROM settings WHERE key='terms_version'").fetchone():
            c.execute("INSERT INTO settings(key,value) VALUES('terms_version','2026-10-20')")''',"schema")
# Add Terms & Safety tab and page.
rep('''<button id="nav-account" onclick="view('account')">Account / Sign in</button></div></div></div>
<main class="wrap">''','''<button id="nav-account" onclick="view('account')">Account / Sign in</button><button id="nav-terms" onclick="view('terms')">Terms, rules & safety</button></div></div></div>
<main class="wrap">''',"nav terms")
rep('''<section id="admin" class="hidden" style="padding:25px 0 55px">''','''<section id="terms" class="hidden" style="padding:25px 0 55px"><div class="card"><h2>Terms, conditions, rules & safety</h2><p class="muted">Effective date: 20 October 2026 · Version 1.0 · Please read before using Skillvaya.</p>
<div class="notice">Safety warning: Skillvaya is a directory and introduction service. We do not guarantee a provider's identity, qualifications, availability, workmanship, prices or outcomes. Verify licences, references, insurance and credentials independently before hiring or paying anyone.</div>
<h3>1. Accounts and accurate information</h3><p>Give accurate account and contact details, protect your password, and tell us if you suspect unauthorised use. One person may not impersonate another or create accounts to evade a restriction. Keep business details, service areas, prices and credentials current.</p>
<h3>2. Provider responsibilities</h3><p>Providers must be legally entitled and suitably qualified to offer their listed services, comply with applicable South African laws and professional rules, quote honestly, obtain consent before work, respect customers, and not misrepresent credentials or results. Do not list prohibited, illegal, unsafe or misleading services.</p>
<h3>3. Customer responsibilities</h3><p>Check a provider's identity, credentials, references, written quote, scope, timing, insurance and payment terms. Do not send money solely because a listing appears on Skillvaya. Never share passwords, one-time PINs or banking credentials. Arrange meetings safely and tell someone where you are going when appropriate.</p>
<h3>4. Listings, plans and payments</h3><p>Customer browsing and contact are free unless clearly stated otherwise. Paid placement affects visibility only and is not an endorsement, certification or guarantee. Fees, billing period, renewal date, cancellation rules and taxes must be shown before purchase. A payment is considered received only after confirmed by the payment provider or reconciled by the owner. Do not treat a pending request as paid.</p>
<h3>5. Renewal, overdue payment and cancellation</h3><p>Paid provider placement may be paused or cancelled when a subscription expires without confirmed renewal payment. We will attempt to notify the account email before or when access is suspended, where email delivery is available. Cancellation of a paid placement does not erase lawful records or outstanding payment obligations. A provider can contact support to correct a payment-record error.</p>
<h3>6. Reports, complaints and moderation</h3><p>Use Report business for genuine safety, fraud, harassment, misleading claims or service concerns. Provide factual details and only lawful evidence. Do not submit knowingly false, retaliatory or abusive reports. Reports are allegations, not findings of guilt; Skillvaya may request information, restrict a listing while investigating, restore it, or remove it based on the evidence and applicable law. Immediate danger should be reported to local emergency services.</p>
<h3>7. Prohibited conduct</h3><ul><li>Fraud, scams, threats, harassment, discrimination or violence.</li><li>Illegal services, stolen goods, counterfeit goods or deceptive claims.</li><li>Spam, scraping, unauthorised access, malware or attempts to disrupt the service.</li><li>Posting another person's private information, images or documents without a lawful basis or permission.</li><li>Manipulating reviews, ratings, enquiries, reports or payment records.</li></ul>
<h3>8. Privacy and communications</h3><p>We use account, listing, enquiry, payment-status and report information to operate the marketplace, protect users, provide support, prevent abuse and maintain records. Contact details should only be used for the relevant enquiry or lawful business purposes. Do not publish sensitive information in public listing fields. The production privacy notice and retention schedule must be completed before public launch.</p>
<h3>9. Availability, liability and changes</h3><p>The local development build may be unavailable, incomplete or lose data and is not a production-grade service. To the extent permitted by law, Skillvaya is not a party to contracts between customers and providers and does not guarantee third-party work. Nothing here removes rights that cannot legally be excluded. We may update these rules; material changes should be communicated and dated.</p>
<h3>10. Contact and complaints</h3><p>For account, billing, safety or privacy concerns, use the in-app reporting feature or the official owner contact shown in the account settings. Do not submit bank passwords, card security codes or one-time PINs.</p>
<div class="notice">Before public launch, have these draft terms, the privacy notice, consumer disclosures, cancellation/refund wording and POPIA processes reviewed for your actual business and payment provider. This draft is not legal advice.</div></div></section>
<section id="admin" class="hidden" style="padding:25px 0 55px">''',"terms page")
# Main sections navigation logic
rep("function view(v){['customer','provider','admin','account'].forEach(x=>{document.getElementById(x).classList.toggle('hidden',x!==v);document.getElementById('nav-'+x).classList.toggle('active',x===v)});document.getElementById('hero').classList.toggle('hidden',v!=='customer');if(v==='admin')loadAdmin();if(v==='account')sessionInfo();window.scrollTo(0,0)}",
"function view(v){['customer','provider','admin','account','terms'].forEach(x=>{document.getElementById(x).classList.toggle('hidden',x!==v);document.getElementById('nav-'+x).classList.toggle('active',x===v)});document.getElementById('hero').classList.toggle('hidden',v!=='customer');if(v==='admin')loadAdmin();if(v==='account')sessionInfo();window.scrollTo(0,0)}","view tabs")
# Admin panels for dashboard, clients, analytics, settings, notifications
rep('''<div class="switchline"><button class="ghost" onclick="adminTab('complaints')">Complaints</button><button class="ghost" onclick="adminTab('businesses')">Listings</button><button class="ghost" onclick="adminTab('payments')">Payments</button></div><div id="adminTable" class="card"></div>''','''<div class="switchline"><button class="ghost" onclick="adminTab('complaints')">Reports & complaints</button><button class="ghost" onclick="adminTab('businesses')">Listings</button><button class="ghost" onclick="adminTab('payments')">Payments</button><button class="ghost" onclick="adminTab('clients')">Client accounts</button><button class="ghost" onclick="adminTab('analytics')">Downloads & usage</button><button class="ghost" onclick="adminTab('notifications')">Alerts</button><button class="ghost" onclick="adminTab('settings')">Email settings</button></div><div id="adminTable" class="card"></div>''',"admin tabs")
# Track visits and install accepted event; browser can't truthfully count APK downloads that never pass through this app.
rep("init();\nif('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(console.warn);",
"init();\ntry{fetch('/api/analytics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event:'visit',detail:/Mobi|Android|iPhone/i.test(navigator.userAgent)?'mobile':'desktop'})})}catch(e){}\nlet installPrompt=null;window.addEventListener('beforeinstallprompt',e=>{installPrompt=e;});window.addEventListener('appinstalled',()=>{fetch('/api/analytics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event:'install',detail:'pwa'})}).catch(()=>{})});\nif('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(console.warn);","analytics client")
# Notification/email helpers
rep('''def hashpw(p): return hashlib.sha256(p.encode()).hexdigest()
HTML =''','''def hashpw(p): return hashlib.sha256(p.encode()).hexdigest()
def setting(key, default=""):
    with conn() as c:
        row=c.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
    return row["value"] if row else default
def notify(kind, subject, body):
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
        return False
def expire_subscriptions():
    with conn() as c:
        rows=c.execute("SELECT id,name,user_id,subscription_expires_at FROM businesses WHERE status='active' AND payment_status='verified' AND subscription_expires_at IS NOT NULL AND subscription_expires_at<=?",(now(),)).fetchall()
        for b in rows:
            c.execute("UPDATE businesses SET status='suspended',payment_status='overdue' WHERE id=?",(b["id"],))
            c.execute("UPDATE subscriptions SET status='expired',cancelled_at=? WHERE business_id=?",(now(),b["id"]))
            owner=c.execute("SELECT email,name FROM users WHERE id=?",(b["user_id"],)).fetchone() if b["user_id"] else None
            if owner:
                c.execute("INSERT INTO notifications(kind,subject,body,created_at) VALUES(?,?,?,?)",("subscription_overdue","Paid listing suspended: "+b["name"],"Hello "+owner["name"]+", your Skillvaya paid placement has expired because renewal payment was not confirmed. The listing is paused. Sign in and renew to request reactivation. Account email: "+owner["email"],now()))
                # Queue owner alert; provider email can be sent by a configured mail service in the next sweep.
                c.execute("INSERT INTO notifications(kind,subject,body,created_at) VALUES(?,?,?,?)",("owner_alert","Subscription overdue: "+b["name"],"Provider account: "+owner["email"]+"; business: "+b["name"]+"; listing paused automatically.",now()))
    # Send owner alerts and customer notices through configured SMTP, if present.
    with conn() as c:
        pending=c.execute("SELECT id,kind,subject,body FROM notifications WHERE status='new' ORDER BY id LIMIT 20").fetchall()
    for n in pending:
        if notify(n["kind"],n["subject"],n["body"]):
            with conn() as c: c.execute("UPDATE notifications SET status='emailed' WHERE id=?",(n["id"],))
HTML =''',"email helpers")
# Ensure analytics/events route, count only real visits and accepted PWA installs.
rep('''            if path=="/api/categories": return self.sendj({"categories":CATEGORIES})''','''            if path=="/api/categories": return self.sendj({"categories":CATEGORIES})
            if path=="/api/analytics/summary":
                self.require("admin")
                with conn() as c:
                    return self.sendj({"visits":c.execute("SELECT count(*) FROM analytics WHERE event='visit'").fetchone()[0],"installs":c.execute("SELECT count(*) FROM analytics WHERE event='install'").fetchone()[0],"visitors":c.execute("SELECT count(DISTINCT user_id) FROM analytics WHERE user_id IS NOT NULL").fetchone()[0],"users":c.execute("SELECT count(*) FROM users").fetchone()[0],"providers":c.execute("SELECT count(*) FROM users WHERE role='provider'").fetchone()[0],"paid":c.execute("SELECT count(*) FROM payments WHERE status='verified'").fetchone()[0],"revenue":c.execute("SELECT coalesce(sum(amount),0) FROM payments WHERE status='verified'").fetchone()[0],"desktop":c.execute("SELECT count(*) FROM analytics WHERE event='visit' AND detail='desktop'").fetchone()[0],"mobile":c.execute("SELECT count(*) FROM analytics WHERE event='visit' AND detail='mobile'").fetchone()[0]})
            if path=="/api/admin/clients":
                self.require("admin")
                with conn() as c:
                    rows=c.execute("SELECT u.id,u.name,u.email,u.role,u.created_at,(SELECT count(*) FROM businesses b WHERE b.user_id=u.id) businesses,(SELECT count(*) FROM payments p WHERE p.user_id=u.id AND p.status='verified') paid FROM users u ORDER BY u.created_at DESC").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/admin/analytics":
                self.require("admin")
                with conn() as c:
                    stats={"visits":c.execute("SELECT count(*) FROM analytics WHERE event='visit'").fetchone()[0],"installs":c.execute("SELECT count(*) FROM analytics WHERE event='install'").fetchone()[0],"accounts":c.execute("SELECT count(*) FROM users").fetchone()[0],"providers":c.execute("SELECT count(*) FROM users WHERE role='provider'").fetchone()[0],"verified_payments":c.execute("SELECT count(*) FROM payments WHERE status='verified'").fetchone()[0],"revenue":c.execute("SELECT coalesce(sum(amount),0) FROM payments WHERE status='verified'").fetchone()[0],"desktop_visits":c.execute("SELECT count(*) FROM analytics WHERE event='visit' AND detail='desktop'").fetchone()[0],"mobile_visits":c.execute("SELECT count(*) FROM analytics WHERE event='visit' AND detail='mobile'").fetchone()[0]}
                return self.sendj({"stats":stats})
            if path=="/api/admin/notifications":
                self.require("admin")
                with conn() as c: rows=c.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 200").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
            if path=="/api/admin/settings":
                self.require("admin")
                return self.sendj({"owner_email":setting("owner_email"),"smtp_configured":bool(os.environ.get("SKILLVAYA_SMTP_HOST") and os.environ.get("SKILLVAYA_SMTP_USER") and os.environ.get("SKILLVAYA_SMTP_PASSWORD")),"note":"SMTP credentials must be configured in the server environment; secrets are not stored in the browser."})''',"admin APIs")
# Capture all non-sensitive audit events; never accept arbitrary event names.
rep('''    def do_POST(self):
        path=urlparse(self.path).path
        try:
            d=self.body()
            if path=="/api/signup":''','''    def do_POST(self):
        path=urlparse(self.path).path
        try:
            d=self.body()
            if path=="/api/analytics":
                event=d.get("event","")
                if event not in ("visit","install"): return self.sendj({"error":"Unsupported event."},400)
                u=self.user()
                detail=str(d.get("detail",""))[:40]
                with conn() as c: c.execute("INSERT INTO analytics(event,user_id,detail,created_at) VALUES(?,?,?,?)",(event,u["id"] if u else None,detail,now()))
                return self.sendj({"ok":True},201)
            if path=="/api/admin/settings":
                self.require("admin")
                email=d.get("owner_email","").strip().lower()
                if email and ("@" not in email or len(email)>254): return self.sendj({"error":"Enter a valid owner email address."},400)
                with conn() as c: c.execute("INSERT INTO settings(key,value) VALUES('owner_email',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(email,))
                notify("settings","Skillvaya owner email updated","Owner notification destination is now "+(email or "(not configured)")+". SMTP still requires server environment settings.")
                return self.sendj({"ok":True,"owner_email":email})
            if path=="/api/admin/test-email":
                self.require("admin")
                if not setting("owner_email"): return self.sendj({"error":"Save your owner email address first."},400)
                ok=notify("test","Test email","This is a Skillvaya test notification. If you received it, email delivery is working.")
                if not ok: return self.sendj({"error":"Email was queued locally but not sent. Configure SKILLVAYA_SMTP_HOST, SKILLVAYA_SMTP_PORT, SKILLVAYA_SMTP_USER, SKILLVAYA_SMTP_PASSWORD and SKILLVAYA_SMTP_FROM on the server."},503)
                return self.sendj({"ok":True})
            if path=="/api/signup":''',"post analytics/settings")
# Notify report, new accounts, payment requests.
rep('''                u={"id":uid,"name":name,"email":email,"role":role}; t=secrets.token_urlsafe(32); SESSIONS[t]=u; return self.sendj({"token":t,"user":u})''','''                u={"id":uid,"name":name,"email":email,"role":role}; t=secrets.token_urlsafe(32); SESSIONS[t]=u
                notify("new_account","New Skillvaya account","New "+role+" account created: "+name+" <"+email+">.")
                return self.sendj({"token":t,"user":u})''',"account notify")
rep('''                return self.sendj({"ok":True},201)
            if path=="/api/payments":''','''                notify("complaint","New business report submitted","Business ID: "+str(bid)+"; customer ID: "+str(u["id"])+"; report: "+reason)
                return self.sendj({"ok":True},201)
            if path=="/api/payments":''',"report notify")
rep('''                return self.sendj({"ok":True,"reference":ref,"amount":amount,"status":"pending"})''','''                notify("payment_request","Payment request created","Provider: "+u["email"]+"; plan: "+plan+"; billing: "+billing+"; amount: R"+str(amount)+"; reference: "+ref+". Payment is not confirmed.")
                return self.sendj({"ok":True,"reference":ref,"amount":amount,"status":"pending"})''',"payment notify")
# Successful verification provisions subscription and expiry.
rep('''                        if row["business_id"]: c.execute("UPDATE businesses SET plan=?,billing=?,payment_status='verified',status='active' WHERE id=?",(row["plan"],row["billing"],row["business_id"]))
                        return self.sendj({"ok":True})''','''                        if row["business_id"]:
                            days=365 if row["billing"]=="yearly" else 30
                            expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=days)).isoformat()
                            c.execute("UPDATE businesses SET plan=?,billing=?,payment_status='verified',status='active',subscription_expires_at=? WHERE id=?",(row["plan"],row["billing"],expires,row["business_id"]))
                            c.execute("INSERT INTO subscriptions(business_id,user_id,plan,billing,status,started_at,expires_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(business_id) DO UPDATE SET user_id=excluded.user_id,plan=excluded.plan,billing=excluded.billing,status='active',started_at=excluded.started_at,expires_at=excluded.expires_at,cancelled_at=NULL",(row["business_id"],row["user_id"],row["plan"],row["billing"],"active",now(),expires))
                        notify("payment_verified","Payment verified","Payment reference "+row["reference"]+" has been marked verified. Amount: R"+str(row["amount"])+".")
                        return self.sendj({"ok":True})''',"subscription provision")
# Add admin rendering for new tabs
rep('''async function adminTab(tab){try{let d=await api('/api/admin/'+tab);let h='';if(tab==='complaints'){''','''async function adminTab(tab){try{if(tab==='settings'){let d=await api('/api/admin/settings');document.getElementById('adminTable').innerHTML='<h3>Owner email & alerts</h3><p>Reports, new account notices, payment events and overdue subscription alerts can be emailed when SMTP is configured.</p><form id="ownerEmailForm"><label>Owner notification email</label><input name="owner_email" type="email" value="'+esc(d.owner_email)+'" placeholder="you@example.com" required><p><button class="primary">Save email</button> <button type="button" class="ghost" onclick="testOwnerEmail()">Send test email</button></p></form><div class="notice">'+(d.smtp_configured?'SMTP credentials detected.':'Email sending is not yet configured; events are saved to Alerts until SMTP is configured.')+'</div><p class="muted tiny">'+esc(d.note)+'</p>';document.getElementById('ownerEmailForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/admin/settings',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});alert('Owner email saved.');adminTab('settings')}catch(x){alert(x.message)}};return}
if(tab==='analytics'){let d=await api('/api/admin/analytics'),s=d.stats;document.getElementById('adminTable').innerHTML='<h3>Downloads & usage</h3><div class="stats">'+[['Page visits',s.visits],['PWA installs recorded',s.installs],['Accounts',s.accounts],['Provider accounts',s.providers],['Verified payments',s.verified_payments],['Verified payment total','R'+Number(s.revenue).toLocaleString('en-ZA')],['Desktop visits',s.desktop_visits],['Mobile visits',s.mobile_visits]].map(x=>'<div class="card"><span class="tiny muted">'+x[0]+'</span><strong>'+x[1]+'</strong></div>').join('')+'</div><p class="notice">These are events recorded by this running installation, not store download counts or unique people. Actual app-store downloads require store analytics; visits can include repeat visits.</p>';return}
let d=await api('/api/admin/'+tab);let h='';if(tab==='clients'){h='<h3>Client & provider accounts</h3><div class="tablewrap"><table class="table"><tr><th>Name</th><th>Email</th><th>Type</th><th>Created</th><th>Listings</th><th>Paid subscriptions</th></tr>'+d.items.map(x=>'<tr><td>'+esc(x.name)+'</td><td>'+esc(x.email)+'</td><td>'+esc(x.role)+'</td><td>'+esc(x.created_at)+'</td><td>'+x.businesses+'</td><td>'+x.paid+'</td></tr>').join('')+'</table></div>';document.getElementById('adminTable').innerHTML=h;return}
if(tab==='notifications'){h='<h3>Alert inbox</h3><div class="tablewrap"><table class="table"><tr><th>Date</th><th>Type</th><th>Subject</th><th>Status</th><th>Details</th></tr>'+d.items.map(x=>'<tr><td>'+esc(x.created_at)+'</td><td>'+esc(x.kind)+'</td><td>'+esc(x.subject)+'</td><td>'+esc(x.status)+'</td><td>'+esc(x.body)+'</td></tr>').join('')+'</table></div>';document.getElementById('adminTable').innerHTML=h;return}
if(tab==='complaints'){''',"admin rendering")
# Add test email client helper
rep('''async function resolveComplaint(id){''','''async function testOwnerEmail(){try{await api('/api/admin/test-email',{method:'POST',body:'{}'});alert('Test email sent.')}catch(e){alert(e.message)}}
async function resolveComplaint(id){''',"test email helper")
# Sweep expiries at startup and daily; keep app thread alive with lightweight timer.
rep('''def main():
    init()
    server=ThreadingHTTPServer((HOST,PORT),Handler)''','''def main():
    init()
    expire_subscriptions()
    def expiry_loop():
        while True:
            threading.Event().wait(3600)
            try: expire_subscriptions()
            except Exception as e: print("Subscription expiry check failed:",e,flush=True)
    threading.Thread(target=expiry_loop,daemon=True).start()
    server=ThreadingHTTPServer((HOST,PORT),Handler)''',"expiry sweep")
p.write_text(s,encoding="utf-8")
print("Patched Skillvaya")
