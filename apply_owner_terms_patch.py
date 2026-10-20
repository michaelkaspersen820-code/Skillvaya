from pathlib import Path
import shutil, datetime, re
root=Path(r"C:\Users\user\Documents\Codex\Skillvaya")
p=root/"app.py"
s=p.read_text(encoding="utf-8")
stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(p, root/f"app.py.pre_owner_terms_{stamp}.bak")
shutil.copy2(root/"skillvaya.sqlite3", root/f"skillvaya.pre_owner_terms_{stamp}.sqlite3.bak")
changes=[]
def rep(old,new,label,count=1):
    global s
    n=s.count(old)
    if n < count: raise RuntimeError(f"Could not find {label}: expected {count}, found {n}")
    s=s.replace(old,new,count)
    changes.append(label)
# Store explicit terms acceptance evidence.
rep('''        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'customer', created_at TEXT NOT NULL, phone TEXT DEFAULT '');''',
'''        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'customer', created_at TEXT NOT NULL, phone TEXT DEFAULT '', accepted_terms_version TEXT NOT NULL DEFAULT '', accepted_terms_at TEXT NOT NULL DEFAULT '');''',"users schema")
rep('''        usercols={r[1] for r in c.execute("PRAGMA table_info(users)")}
        if "phone" not in usercols:
            c.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")''',
'''        usercols={r[1] for r in c.execute("PRAGMA table_info(users)")}
        if "phone" not in usercols:
            c.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
        if "accepted_terms_version" not in usercols:
            c.execute("ALTER TABLE users ADD COLUMN accepted_terms_version TEXT NOT NULL DEFAULT ''")
        if "accepted_terms_at" not in usercols:
            c.execute("ALTER TABLE users ADD COLUMN accepted_terms_at TEXT NOT NULL DEFAULT ''")''',"safe terms migration")
# Local developer/owner access without an account is allowed only when this server is loopback-bound and caller is loopback.
rep('''    def require(self,role=None):
        u=self.user()
        if not u: raise PermissionError("Please sign in first.")''',
'''    def require(self,role=None):
        u=self.user()
        local_only = (role == "admin" and self.client_address[0] in ("127.0.0.1", "::1")
                      and self.server.server_address[0] in ("127.0.0.1", "::1"))
        if not u and local_only:
            return {"id": 0, "name": "Local Developer", "email": "local-owner@skillvaya.local", "role": "admin"}
        if not u: raise PermissionError("Please sign in first.")''',"local owner access")
# Enforce terms at the backend, not just with browser required validation.
rep('''                name=d.get("name","").strip(); email=d.get("email","").strip().lower(); phone=d.get("phone","").strip()[:40]; pw=d.get("password",""); role=d.get("role","customer")
                if not name or "@" not in email or len(pw)<8 or role not in ("customer","provider"): return self.sendj({"error":"Enter a name, valid email, password of 8+ characters, and valid account type."},400)
                with conn() as c:
                    try: c.execute("INSERT INTO users(name,email,password_hash,role,created_at,phone) VALUES(?,?,?,?,?,?)",(name,email,hashpw(pw),role,now(),phone)); uid=c.execute("SELECT last_insert_rowid()").fetchone()[0]''',
'''                name=d.get("name","").strip(); email=d.get("email","").strip().lower(); phone=d.get("phone","").strip()[:40]; pw=d.get("password",""); role=d.get("role","customer")
                terms_accepted = d.get("accept_terms") is True
                terms_version = setting("terms_version", "2026-10-20")
                if not terms_accepted: return self.sendj({"error":"You must read and accept the Skillvaya Terms, Conditions, Rules & Safety before creating an account."},400)
                if not name or "@" not in email or len(pw)<8 or role not in ("customer","provider"): return self.sendj({"error":"Enter a name, valid email, password of 8+ characters, and valid account type."},400)
                with conn() as c:
                    try: c.execute("INSERT INTO users(name,email,password_hash,role,created_at,phone,accepted_terms_version,accepted_terms_at) VALUES(?,?,?,?,?,?,?,?)",(name,email,hashpw(pw),role,now(),phone,terms_version,now())); uid=c.execute("SELECT last_insert_rowid()").fetchone()[0]''',"signup terms gate")
# Make the terms checkbox a required part of the visible signup form.
rep('''<label>Account type</label><select name="role"><option value="customer">Customer — free</option><option value="provider">Service provider</option></select><p><button class="primary">Create account</button></p></form>''',
'''<label>Account type</label><select name="role"><option value="customer">Customer — free</option><option value="provider">Service provider</option></select><p><label style="display:flex;gap:10px;align-items:flex-start;font-weight:500"><input name="accept_terms" type="checkbox" required style="width:auto;margin-top:5px;flex:0 0 auto"><span>I have read and agree to the <a href="#" onclick="view('terms');return false">Skillvaya Terms, Conditions, Rules & Safety</a>, including the applicable privacy and account rules. I understand I cannot create an account unless I tick this box.</span></label></p><p><button class="primary">Create account</button></p></form>''',"signup checkbox")
# JS sends checkbox explicitly (FormData checkbox absent when unticked).
rep('''document.getElementById('signup').onsubmit=async e=>{e.preventDefault();try{let o=Object.fromEntries(new FormData(e.target));let d=await api('/api/signup',{method:'POST',body:JSON.stringify(o)});token=d.token;me=d.user;localStorage.setItem('sv_token',token);msg('signupMsg','Account created and signed in.',true);sessionInfo()}catch(x){msg('signupMsg',x.message)}};''',
'''document.getElementById('signup').onsubmit=async e=>{e.preventDefault();try{let fd=new FormData(e.target);let data=Object.fromEntries(fd);data.accept_terms=document.querySelector('#signup input[name="accept_terms"]').checked;let d=await api('/api/signup',{method:'POST',body:JSON.stringify(data)});token=d.token;localStorage.setItem('sv_token',token);msg('signupMsg','Account created. Welcome, '+d.user.name+'.',true);await sessionInfo()}catch(x){msg('signupMsg',x.message)}};''',"signup JS")
# Correct terms/version in page from settings at startup later; separate owner page uses same local-only APIs.
# Add dedicated route rendering for the independent owner app before ordinary homepage.
rep('''            if path=="/" or path=="/index.html":
                b=HTML.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return''',
'''            if path=="/owner-control":
                owner_html = OWNER_HTML.encode()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(owner_html))); self.end_headers(); self.wfile.write(owner_html); return
            if path=="/" or path=="/index.html":
                b=HTML.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return''',"owner route")
owner = r'''OWNER_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Skillvaya — Owner Control</title><style>
:root{font:15px/1.5 'Segoe UI',Arial;color:#19283b;background:#f4f7fb}*{box-sizing:border-box}body{margin:0}.head{background:#10233f;color:white;padding:20px}.wrap{max-width:1100px;margin:auto;padding:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{background:white;border:1px solid #e1e8f1;border-radius:12px;padding:16px;margin-bottom:14px}button{border:0;border-radius:8px;padding:10px 13px;margin:3px;background:#2365d8;color:white;font-weight:650;cursor:pointer}.secondary{background:#eaf0f8;color:#10233f}.muted{color:#66758b}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:620px}td,th{text-align:left;padding:9px;border-bottom:1px solid #e1e8f1;vertical-align:top}.stat{font-size:28px;font-weight:800}.notice{padding:12px;border-radius:9px;background:#eaf7f0;color:#13714d;margin:10px 0}@media(max-width:600px){.wrap{padding:10px}}</style></head><body><header class="head"><div class="wrap"><h1 style="margin:0">Skillvaya — Owner Control</h1><div>Private developer console · local PC only · no owner sign-in</div></div></header><main class="wrap"><div class="notice">This control app is separate from the customer Skillvaya app. It works without an account only while the Skillvaya service is bound to this PC's loopback address. Keep the service local until a properly secured public deployment is configured.</div><div class="grid" id="stats"></div><section class="card"><h2>Quick controls</h2><button onclick="load('summary')">Refresh overview</button><button onclick="load('businesses')" class="secondary">Listings</button><button onclick="load('payments')" class="secondary">Payment requests</button><button onclick="load('complaints')" class="secondary">Reports & complaints</button><button onclick="load('clients')" class="secondary">Accounts</button><button onclick="load('notifications')" class="secondary">Alerts</button><button onclick="load('analytics')" class="secondary">Usage</button><button onclick="load('settings')" class="secondary">Owner email</button><button onclick="location.href='/'" class="secondary">Open customer app</button></section><section class="card" id="panel"><h2>Overview</h2><p class="muted">Select a control above.</p></section></main><script>
async function api(path,opts={}){opts.headers={'Content-Type':'application/json',...(opts.headers||{})};let r=await fetch(path,opts);let d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function load(tab){let p=document.getElementById('panel');try{if(tab==='summary'){let d=await api('/api/admin/summary');document.getElementById('stats').innerHTML=Object.entries({Businesses:d.businesses,'Open complaints':d.complaints,'Payment requests':d.payments,'Pending listings':d.pending}).map(([k,v])=>'<div class="card"><div class="muted">'+k+'</div><div class="stat">'+v+'</div></div>').join('');p.innerHTML='<h2>Owner overview</h2><p>Local developer access is active. Customer accounts remain separate and are not automatically signed in.</p>';return}
if(tab==='analytics'){let d=await api('/api/admin/analytics'),s=d.stats;p.innerHTML='<h2>Usage & payments</h2><div class="grid">'+Object.entries(s).map(([k,v])=>'<div class="card"><div class="muted">'+esc(k.replaceAll('_',' '))+'</div><div class="stat">'+esc(typeof v==='number'&&k==='revenue'?'R'+v.toLocaleString('en-ZA'):v)+'</div></div>').join('')+'</div><p class="muted">Local visit counts are not public website analytics or store-download totals.</p>';return}
if(tab==='settings'){let d=await api('/api/admin/settings');p.innerHTML='<h2>Owner email</h2><form id="email"><label>Notification email <input type="email" name="owner_email" value="'+esc(d.owner_email)+'" required></label><p><button>Save email</button><button type="button" class="secondary" onclick="testEmail()">Send test email</button></p></form><p class="muted">'+esc(d.note)+' '+(d.smtp_configured?'SMTP detected.':'SMTP not configured yet; alerts remain in the local inbox.')+'</p>';document.getElementById('email').onsubmit=async e=>{e.preventDefault();try{await api('/api/admin/settings',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});alert('Owner email saved');load('settings')}catch(x){alert(x.message)}};return}
let d=await api('/api/admin/'+tab);let items=d.items||[];if(tab==='clients'){p.innerHTML='<h2>Accounts</h2>'+table(['Name','Email','Role','Created','Listings','Paid'],items.map(x=>[x.name,x.email,x.role,x.created_at,x.businesses,x.paid]));return}
if(tab==='notifications'){p.innerHTML='<h2>Alerts</h2>'+table(['Date','Type','Subject','Status','Message'],items.map(x=>[x.created_at,x.kind,x.subject,x.status,x.body]));return}
if(tab==='businesses'){p.innerHTML='<h2>Listings</h2>'+table(['Name','Category','Area','Phone','Status','Plan'],items.map(x=>[x.name,x.category,x.area,x.phone,x.status,x.plan]));return}
if(tab==='payments'){p.innerHTML='<h2>Payment requests</h2>'+table(['Reference','User','Amount','Plan','Status','Action'],items.map(x=>[x.reference,x.user_id,'R'+x.amount,x.plan,x.status,x.status==='pending'?'<button onclick="verify('+x.id+')">Mark manually verified</button>':'—']));return}
if(tab==='complaints'){p.innerHTML='<h2>Reports & complaints</h2>'+table(['Date','Business','Reason','Status'],items.map(x=>[x.created_at,x.business_name,x.reason,x.status]));return}
}catch(e){p.innerHTML='<h2>Could not load control data</h2><p>'+esc(e.message)+'</p>'}}
function table(headers,rows){return '<div class="tablewrap"><table><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr>'+rows.map(row=>'<tr>'+row.map((x,i)=>'<td>'+(i===row.length-1&&String(x).startsWith('<button')?x:esc(x))+'</td>').join('')+'</tr>').join('')+'</table></div>'}
async function verify(id){if(!confirm('Manually mark this payment verified? Do this only after checking actual receipt with the payment provider/bank.'))return;try{await api('/api/admin/payments/'+id,{method:'POST',body:'{}'});load('payments')}catch(e){alert(e.message)}}
async function testEmail(){try{await api('/api/admin/test-email',{method:'POST',body:'{}'});alert('Test email sent')}catch(e){alert(e.message)}}
load('summary');
</script></body></html>"""
'''
rep('HTML = r', owner + 'HTML = r',"owner HTML insert")
p.write_text(s,encoding="utf-8")
print("PATCH_OK", ", ".join(changes))
