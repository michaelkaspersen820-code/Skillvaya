from pathlib import Path
p=Path(r"C:\Users\user\Documents\Codex\Skillvaya\app.py")
s=p.read_text(encoding="utf-8")
start=s.index('OWNER_APP_HTML = r"""')
end=s.index('\nOWNER_HTML = r"""',start)
part=s[start:end]
if 'showTab(&quot;promotions&quot;)' not in part:
    marker='</div><div class="grid">'
    assert marker in part
    part=part.replace(marker,'<button class="action" onclick="showTab(&quot;promotions&quot;)">My Businesses & Promotions</button></div><div class="grid">',1)
if 'id="promotions"' not in part:
    marker='</section></main><script>function showTab(t){'
    section='''</section><section id="promotions" class="framewrap"><div class="framehead"><button class="action" onclick="showTab('home')">Back</button><h2>My Businesses & Promotions</h2></div><iframe class="frame" src="/owner-control#owner-promotions" title="My Businesses & Promotions"></iframe></section></main><script>function showTab(t){'''
    assert marker in part
    part=part.replace(marker,section,1)
if "getElementById('promotions').classList.toggle('active',t==='promotions')" not in part:
    marker="document.getElementById('payments').classList.toggle('active',t==='payments');"
    assert marker in part
    part=part.replace(marker,marker+"document.getElementById('promotions').classList.toggle('active',t==='promotions');",1)
s=s[:start]+part+s[end:]
p.write_text(s,encoding="utf-8")
print("Integrated My Businesses & Promotions directly into the Owner App tab navigation.")
