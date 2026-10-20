from pathlib import Path
import re
root=Path(r"C:\Users\user\Documents\Codex\Skillvaya")
backup=max(root.glob("website.html.pre_owner_marketplace_upgrade_*.bak"),key=lambda p:p.stat().st_mtime)
s=backup.read_text(encoding="utf-8")
assert "Find your people" in s and "Download / install app" in s
assert "owner-control" not in s
section=r'''<section id="owner-promotions-public" class="wrap" style="padding:22px 0"><h2>Skillvaya owner businesses & apps</h2><p class="muted">Owner-created businesses, services and apps.</p><div id="owner-promotions-public-list" class="results"><p class="muted">Loading owner promotions…</p></div></section><script>
(async()=>{try{const r=await fetch('/api/owner-promotions');if(!r.ok)return;const d=await r.json();const root=document.getElementById('owner-promotions-public-list');root.innerHTML=(d.items||[]).map(x=>'<article class="card biz"><span class="tag">Owner '+String(x.kind).replace(/[&<>]/g,'')+'</span><h3>'+String(x.title).replace(/[&<>]/g,'')+'</h3><div class="muted tiny">'+String(x.business_name).replace(/[&<>]/g,'')+' · '+String(x.category).replace(/[&<>]/g,'')+'</div><p>'+String(x.description).replace(/[&<>]/g,'')+'</p>'+(x.image_url?'<img loading="lazy" alt="" style="max-width:100%;max-height:220px;object-fit:contain" src="'+String(x.image_url).replace(/"/g,'&quot;')+'">':'')+(x.target_url?'<p><a rel="noopener noreferrer" target="_blank" href="'+String(x.target_url).replace(/"/g,'&quot;')+'">Visit website / download app</a></p>':'')+'</article>').join('')||'<p class="muted">No owner promotions published yet.</p>'}catch(e){console.warn(e)}})();
</script>'''
if "owner-promotions-public-list" not in s:
    i=s.rfind("</main>")
    assert i>=0
    s=s[:i]+section+s[i:]
(root/"website.html").write_text(s,encoding="utf-8")
(root/"android-native/app/src/main/assets/website.html").write_text(s,encoding="utf-8")
print("Restored original public website layout and added owner promotions section:",len(s),"bytes")
print("Owner control link exposed to customers:",bool(re.search(r'owner-control|Owner control',s,re.I)))
