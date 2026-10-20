from pathlib import Path
import shutil,datetime
p=Path(r"C:\Users\user\Documents\Codex\Skillvaya\app.py")
s=p.read_text(encoding="utf-8")
stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(p, p.with_name("app.py.pre_email_link_"+stamp+".bak"))
old='''if not c.execute("SELECT 1 FROM settings WHERE key='owner_email'").fetchone():
            c.execute("INSERT INTO settings(key,value) VALUES('owner_email','')")'''
new='''if not c.execute("SELECT 1 FROM settings WHERE key='owner_email'").fetchone():
            c.execute("INSERT INTO settings(key,value) VALUES('owner_email','skillvaya@gmail.com')")
        else:
            c.execute("UPDATE settings SET value='skillvaya@gmail.com' WHERE key='owner_email' AND (value IS NULL OR value='' OR value='owner@skillvaya.local')")'''
assert s.count(old)==1
s=s.replace(old,new)
# owner console visible email/contact shortcuts
old='''<div>Private developer console · local PC only · no owner sign-in</div></div></header>'''
new='''<div>Private developer console · local PC only · no owner sign-in</div><div style="margin-top:8px"><a style="color:#fff" href="mailto:skillvaya@gmail.com">skillvaya@gmail.com</a> · <a style="color:#fff" href="https://mail.google.com/mail/u/0/#inbox" target="_blank" rel="noopener">Open Gmail inbox</a></div></div></header>'''
assert s.count(old)==1
s=s.replace(old,new)
# Add quick email links in control panel
old='''<button onclick="load('settings')" class="secondary">Owner email</button><button onclick="location.href='/'" class="secondary">Open customer app</button>'''
new='''<button onclick="load('settings')" class="secondary">Owner email</button><button onclick="location.href='mailto:skillvaya@gmail.com'" class="secondary">Compose email</button><button onclick="window.open('https://mail.google.com/mail/u/0/#inbox','_blank','noopener')" class="secondary">Open inbox</button><button onclick="location.href='/'" class="secondary">Open customer app</button>'''
assert s.count(old)==1
s=s.replace(old,new)
# Default settings page includes actionable links and explains server credentials required for app-triggered sending.
old='''<p class="muted">'+esc(d.note)+' '+(d.smtp_configured?'SMTP detected.':'SMTP not configured yet; alerts remain in the local inbox.')+'</p>';'''
new='''<p><a href="mailto:skillvaya@gmail.com">Compose a message in your email app</a> · <a href="https://mail.google.com/mail/u/0/#inbox" target="_blank" rel="noopener">Open Gmail inbox</a></p><p class="muted">'+esc(d.note)+' '+(d.smtp_configured?'SMTP detected.':'SMTP not configured yet; app-triggered emails cannot be sent until Gmail SMTP credentials are configured securely on the server.')+'</p>';'''
assert s.count(old)==1
s=s.replace(old,new)
# Terms contact links
old='''<h3>10. Contact and complaints</h3><p>For account, billing, safety or privacy concerns, use the in-app reporting feature or the official owner contact shown in the account settings. Do not submit bank passwords, card security codes or one-time PINs.</p>'''
new='''<h3>10. Contact and complaints</h3><p>For account, billing, safety or privacy concerns, email <a href="mailto:skillvaya@gmail.com">skillvaya@gmail.com</a> or use the in-app reporting feature. Do not submit bank passwords, card security codes or one-time PINs.</p>'''
assert s.count(old)==1
s=s.replace(old,new)
old='''<div class="wrap">Skillvaya local application · Customer search is free · Paid advertising is labelled · Complaint reports are allegations requiring fair investigation.</div>'''
new='''<div class="wrap">Skillvaya local application · Customer search is free · Paid advertising is labelled · <a href="mailto:skillvaya@gmail.com">skillvaya@gmail.com</a> · <a href="https://mail.google.com/mail/u/0/#inbox" target="_blank" rel="noopener">Email inbox</a> · Complaint reports are allegations requiring fair investigation.</div>'''
assert s.count(old)==1
s=s.replace(old,new)
p.write_text(s,encoding="utf-8")
print("EMAIL_LINK_PATCH_OK",stamp)
