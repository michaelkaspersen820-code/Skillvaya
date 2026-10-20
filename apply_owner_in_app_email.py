from pathlib import Path
import shutil, re, sys
root=Path(r"C:\Users\user\Documents\Codex\Skillvaya")
p=root/"app.py"
s=p.read_text(encoding="utf-8")
backup=root/"app.py.pre_owner_in_app_email_20261020.bak"
shutil.copy2(p,backup)
logo=Path(r"C:\Users\user\Desktop\sv app icon.jpeg")
assets=root/"sv-logo.jpeg"
shutil.copy2(logo,assets)

# Main app favicon and brand lockup use the exact supplied SV image.
s=s.replace('<link rel="icon" href="/icon.svg" type="image/svg+xml">','<link rel="icon" href="/sv-logo.jpeg" type="image/jpeg">')
s=s.replace('.brand{font-size:26px;font-weight:850}.brand span{color:#75b7ff}', '.brandlock{display:flex;align-items:center;gap:11px}.sv-logo{width:46px;height:46px;object-fit:contain;border-radius:10px;background:#08142b;box-shadow:0 2px 10px #0003;flex:0 0 auto}.brand{font-size:26px;font-weight:850}.brand span{color:#75b7ff}')
s=s.replace('<div><div class="brand">skill<span>vaya</span></div><div class="tiny" style="color:#cbd8e9">Good people. Great work. Near you.</div></div>', '<div class="brandlock"><img class="sv-logo" src="/sv-logo.jpeg" alt="SV Skillvaya logo"><div><div class="brand">skill<span>vaya</span></div><div class="tiny" style="color:#cbd8e9">Good people. Great work. Near you.</div></div></div>')
# Owner button inside the normal application, no paid plan or subscription.
s=s.replace('<button id="nav-terms" onclick="view(\'terms\')">Terms, rules & safety</button>', '<button id="nav-terms" onclick="view(\'terms\')">Terms, rules & safety</button><button onclick="location.href=\'/owner-control\'">Owner control</button>')
# Remove Gmail external links in footer; keep account email as text.
s=s.replace(' Â· <a href="https://mail.google.com/mail/u/0/#inbox" target="_blank" rel="noopener">Email inbox</a>', ' Â· Owner email and inbox are managed in Owner Control')
# Owner page logo and internal navigation/actions.
s=s.replace('<link rel="icon" href="/icon.svg" type="image/svg+xml">','<link rel="icon" href="/sv-logo.jpeg" type="image/jpeg">')
s=s.replace('.head{background:#10233f;color:white;padding:20px}', '.head{background:#10233f;color:white;padding:20px}.owner-brand{display:flex;align-items:center;gap:12px}.owner-brand img{width:54px;height:54px;object-fit:contain;border-radius:10px;background:#08142b}')
s=s.replace('<h1 style="margin:0">Skillvaya â€” Owner Control</h1>', '<div class="owner-brand"><img src="/sv-logo.jpeg" alt="SV Skillvaya logo"><div><h1 style="margin:0">Skillvaya â€” Owner Control</h1><div class="tiny">Owner workspace</div></div></div>')
s=s.replace('<div style="margin-top:8px"><a style="color:#fff" href="mailto:skillvaya@gmail.com">skillvaya@gmail.com</a> Â· <a style="color:#fff" href="https://mail.google.com/mail/u/0/#inbox" target="_blank" rel="noopener">Open Gmail inbox</a></div>', '<div style="margin-top:8px">Platform email: <span id="ownerEmailLabel">skillvaya@gmail.com</span></div>')
s=s.replace('<button onclick="location.href=\'mailto:skillvaya@gmail.com\'" class="secondary">Compose email</button><button onclick="window.open(\'https://mail.google.com/mail/u/0/#inbox\',\'_blank\',\'noopener\')" class="secondary">Open inbox</button><button onclick="location.href=\'/\'" class="secondary">Open customer app</button>', '<button onclick="load(\'compose\')" class="secondary">Compose email</button><button onclick="load(\'inbox\')" class="secondary">In-app inbox</button><button onclick="location.href=\'/\'" class="secondary">Back to Skillvaya app</button>')
# Internal inbox and compose tabs in owner page. Emails use actual registered accounts.
anchor="if(tab==='settings'){let d=await api('/api/admin/settings');"
insert="""if(tab==='compose'){let d=await api('/api/admin/clients');let items=d.items||[];p.innerHTML='<h2>Compose email</h2><p class="muted">Compose and send within Skillvaya. Delivery requires the server email connection to be configured.</p><form id="composeForm"><label>Recipient account</label><select name="client_id" required><option value="">Choose a customer or provider</option>'+items.map(x=>'<option value="'+x.id+'">'+esc(x.name)+' â€” '+esc(x.email)+' ('+esc(x.role)+')</option>').join('')+'</select><label>Subject</label><input name="subject" maxlength="180" required><label>Message</label><textarea name="body" rows="6" maxlength="10000" required></textarea><p><button class="primary">Send from Skillvaya</button></p><div id="composeStatus" class="muted"></div></form>';document.getElementById('composeForm').onsubmit=async e=>{e.preventDefault();let f=Object.fromEntries(new FormData(e.target));let st=document.getElementById('composeStatus');st.textContent='Sending through Skillvaya email serviceâ€¦';try{let r=await api('/api/admin/email-client',{method:'POST',body:JSON.stringify(f)});st.textContent='Sent to '+r.recipient+'.'}catch(err){st.textContent='Not sent: '+err.message;}};return}
if(tab==='inbox'){let d=await api('/api/admin/notifications');p.innerHTML='<h2>Skillvaya in-app inbox</h2><p class="muted">This inbox shows messages and system alerts recorded by Skillvaya. It is not a live mirror of Gmail; Gmail mailbox syncing requires Google OAuth authorization.</p>'+table(['Date','Type','Subject','Status','Recipient','Message'],(d.items||[]).map(x=>[x.created_at,x.kind,x.subject,x.status,x.recipient,x.body]));return}
"""
if anchor not in s: raise SystemExit("Settings tab insertion point not found")
s=s.replace(anchor,insert+anchor,1)
# Remove external compose/open Gmail links inside settings.
s=s.replace('<p><a href="mailto:skillvaya@gmail.com">Compose a message in your email app</a> Â· <a href="https://mail.google.com/mail/u/0/#inbox" target="_blank" rel="noopener">Open Gmail inbox</a></p>', '<p><button type="button" class="secondary" onclick="load(\'compose\')">Compose inside Skillvaya</button> <button type="button" class="secondary" onclick="load(\'inbox\')">Open Skillvaya inbox</button></p>')
# Account records in directory already come from users table. Owner local panel doesn't require paid account.
# Serve the exact image at a first-party URL.
route='''            if path=="/sv-logo.jpeg":
                logo_path=os.path.join(os.path.dirname(__file__),"sv-logo.jpeg")
                with open(logo_path,"rb") as f: b=f.read()
                self.send_response(200); self.send_header("Content-Type","image/jpeg"); self.send_header("Cache-Control","no-cache"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
'''
if 'if path=="/sv-logo.jpeg":' not in s:
    s=s.replace('            if path=="/manifest.json":',route+'            if path=="/manifest.json":',1)
p.write_text(s,encoding="utf-8")
print("Patched",p)
print("Backup",backup)
print("Logo asset",assets,assets.stat().st_size)
print("main logo:", 'src="/sv-logo.jpeg"' in s)
print("in-app compose:", "if(tab==='compose')" in s)
print("in-app inbox:", "if(tab==='inbox')" in s)
print("gmail links remaining:", s.count("mail.google.com"))