from pathlib import Path
import re
p=Path(r"C:\Users\user\Documents\Codex\Skillvaya\app.py")
s=p.read_text(encoding="utf-8")
orig=s
# Durable records for owner-created promotions.
if "CREATE TABLE IF NOT EXISTS owner_promotions" not in s:
    marker="        CREATE TABLE IF NOT EXISTS subscriptions("
    i=s.find(marker); assert i>=0
    end=s.find("\n",i)
    s=s[:end]+"""
        CREATE TABLE IF NOT EXISTS owner_promotions(
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'ad',
            business_name TEXT NOT NULL, title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Other professional services',
            description TEXT NOT NULL, target_url TEXT NOT NULL DEFAULT '',
            image_url TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
            owner_free INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );"""+s[end:]
# Hide owner navigation from the customer app.
s,n=re.subn(r'<button[^>]*>Owner control</button>','',s,count=1)
if n==0: print("Owner control label button not found in source")
# Public endpoint returns active owner-owned promotions only.
if 'if path=="/api/owner-promotions":' not in s:
    marker='            if path=="/api/categories": return self.sendj({"categories":CATEGORIES})'
    assert marker in s
    s=s.replace(marker,'''            if path=="/api/owner-promotions":
                with conn() as c:
                    rows=c.execute("SELECT id,kind,business_name,title,category,description,target_url,image_url,status,owner_free,created_at FROM owner_promotions WHERE status='active' ORDER BY created_at DESC").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
'''+marker,1)
# Owner-only listing API.
if 'if path=="/api/admin/owner-promotions":' not in s:
    marker='            if path.startswith("/api/admin/"):'
    assert marker in s
    s=s.replace(marker,'''            if path=="/api/admin/owner-promotions":
                self.require("admin")
                with conn() as c:
                    rows=c.execute("SELECT * FROM owner_promotions ORDER BY created_at DESC").fetchall()
                return self.sendj({"items":[dict(x) for x in rows]})
'''+marker,1)
# Owner-only create and status API in POST handler.
if 'INSERT INTO owner_promotions' not in s:
    marker='            if path.startswith("/api/admin/refunds/"):'
    assert marker in s
    s=s.replace(marker,'''            if path=="/api/admin/owner-promotions":
                self.require("admin")
                kind=str(d.get("kind","ad")).strip().lower()
                business_name=str(d.get("business_name","")).strip()[:120]
                title=str(d.get("title","")).strip()[:160]
                category=str(d.get("category","Other professional services")).strip()
                description=str(d.get("description","")).strip()[:3000]
                target_url=str(d.get("target_url","")).strip()[:500]
                image_url=str(d.get("image_url","")).strip()[:1000]
                if kind not in ("business","ad","app"): return self.sendj({"error":"Choose business, ad or app."},400)
                if not business_name or not title or not description: return self.sendj({"error":"Business name, title and description are required."},400)
                if category not in CATEGORIES: return self.sendj({"error":"Choose a valid category."},400)
                if any(x and not x.startswith(("https://","http://")) for x in (target_url,image_url)): return self.sendj({"error":"Links must start with http:// or https://."},400)
                with conn() as c:
                    cur=c.execute("INSERT INTO owner_promotions(kind,business_name,title,category,description,target_url,image_url,status,owner_free,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'active',1,?,?)",(kind,business_name,title,category,description,target_url,image_url,now(),now()))
                return self.sendj({"ok":True,"id":cur.lastrowid,"owner_free":True},201)
            if path.startswith("/api/admin/owner-promotions/"):
                self.require("admin")
                try: pid=int(path.rsplit("/",1)[1])
                except ValueError: return self.sendj({"error":"Invalid promotion ID."},400)
                status=str(d.get("status","")).strip().lower()
                if status not in ("active","paused","removed"): return self.sendj({"error":"Invalid status."},400)
                with conn() as c:
                    cur=c.execute("UPDATE owner_promotions SET status=?,updated_at=? WHERE id=?",(status,now(),pid))
                if not cur.rowcount: return self.sendj({"error":"Promotion not found."},404)
                return self.sendj({"ok":True,"status":status})
'''+marker,1)
# Owner Control button and UI.
btn='''<button onclick="load('settings')" class="secondary">Owner email</button>'''
if "My Businesses & Promotions" not in s:
    assert btn in s
    s=s.replace(btn,btn+'''<button onclick="load('owner-promotions')" class="secondary">My Businesses & Promotions</button>''',1)
# Inject the management form into the existing Owner Control load() router.
if "if(tab==='owner-promotions')" not in s:
    marker="""if(tab==='analytics')"""
    assert marker in s
    branch=""" if(tab==='owner-promotions'){let d=await api('/api/admin/owner-promotions');let cats="""+repr(["Builders & construction","Plumbers","Electricians","Painters & decorators","Mechanics & automotive","Cleaning & housekeeping","Gardening & landscaping","Roofing & waterproofing","Carpenters & furniture","Welders & fabricators","Appliance repairs","IT & computer support","Graphic designers","Artists & photographers","Marketing & advertising","Web & software developers","Lawyers & legal services","Private doctors & clinics","Dentists & specialists","Nurses & home care","Accountants & tax","Financial & insurance services","Real estate & property","Tutors & education","Beauty & hair","Catering & chefs","Transport & removals","Security services","Events & entertainment","Tailors & fashion","Pet care & veterinary","Funeral services","Engineering & consulting","Other professional services"])+""";p.innerHTML='<h2>My Businesses & Promotions</h2><p>Owner-created business profiles, ads and apps are permanently exempt from Skillvaya listing and subscription fees.</p><form id="ownerPromoForm"><label>Type</label><select name="kind"><option value="business">My business</option><option value="ad">Advertisement / product / service</option><option value="app">App I created</option></select><label>Business / brand name</label><input name="business_name" required maxlength="120"><label>Listing title</label><input name="title" required maxlength="160"><label>Category</label><select name="category">'+cats.map(x=>'<option>'+esc(x)+'</option>').join('')+'</select><label>Description</label><textarea name="description" required maxlength="3000" rows="4"></textarea><label>Website / app download URL</label><input name="target_url" type="url" maxlength="500" placeholder="https://..."><label>Image URL (optional)</label><input name="image_url" type="url" maxlength="1000" placeholder="https://..."><p><button>Save & publish for free</button></p></form><div id="ownerPromoStatus" class="muted"></div><h3>Your entries</h3>'+table(['Type','Business','Title','Status','Fee exemption','Action'],(d.items||[]).map(x=>[x.kind,x.business_name,x.title,x.status,x.owner_free?'Free':'Review',x.status==='removed'?'Removed':'<button onclick="ownerPromoStatus('+x.id+',\\''+(x.status==='active'?'paused':'active')+'\\')">'+(x.status==='active'?'Pause':'Publish')+'</button> <button class="secondary" onclick="ownerPromoStatus('+x.id+',\\'removed\\')">Delete</button>']));document.getElementById('ownerPromoForm').onsubmit=async e=>{e.preventDefault();let st=document.getElementById('ownerPromoStatus');try{await api('/api/admin/owner-promotions',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});st.textContent='Saved and published. Owner fee exemption stored.';load('owner-promotions')}catch(x){st.textContent='Not saved: '+x.message}};return}
"""
    s=s.replace(marker,branch+marker,1)
if "async function ownerPromoStatus(" not in s:
    marker="async function testEmail(){"
    assert marker in s
    s=s.replace(marker,"async function ownerPromoStatus(id,status){try{await api('/api/admin/owner-promotions/'+id,{method:'POST',body:JSON.stringify({status})});load('owner-promotions')}catch(e){alert(e.message)}}\n"+marker,1)
# Public section before footer.
if "owner-promotions-public-list" not in s:
    marker='</main><footer class="footer">'
    if marker in s:
        public='''<section id="owner-promotions-public" class="wrap" style="padding:20px 0"><h2>Skillvaya owner businesses & apps</h2><div id="owner-promotions-public-list" class="results"><p class="muted">Loading owner promotions…</p></div></section><script>(async()=>{try{let r=await fetch('/api/owner-promotions');if(!r.ok)return;let d=await r.json();let root=document.getElementById('owner-promotions-public-list');root.innerHTML=(d.items||[]).map(x=>'<article class="card biz"><span class="tag">Owner '+String(x.kind).replace(/[&<>]/g,'')+'</span><h3>'+String(x.title).replace(/[&<>]/g,'')+'</h3><div class="muted tiny">'+String(x.business_name).replace(/[&<>]/g,'')+' · '+String(x.category).replace(/[&<>]/g,'')+'</div><p>'+String(x.description).replace(/[&<>]/g,'')+'</p>'+(x.image_url?'<img loading="lazy" alt="" style="max-width:100%;max-height:220px;object-fit:contain" src="'+String(x.image_url).replace(/"/g,'&quot;')+'">':'')+(x.target_url?'<p><a rel="noopener noreferrer" target="_blank" href="'+String(x.target_url).replace(/"/g,'&quot;')+'">Visit website / download app</a></p>':'')+'</article>').join('')||'<p class="muted">No owner promotions published yet.</p>'}catch(e){console.warn(e)}})();</script></main><footer class="footer">'''
        s=s.replace(marker,public,1)
if s==orig: raise SystemExit("No changes were made")
p.write_text(s,encoding="utf-8")
print("Patched owner promotion database, APIs, owner UI and customer navigation.")
