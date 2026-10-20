from pathlib import Path
p=Path("app.py"); s=p.read_text(encoding="utf-8")
for action in ("compose","inbox"):
 old="onclick=\"load('"+action+"')\""
 new="onclick=\"load(&#39;"+action+"&#39;)\""
 count=s.count(old)
 print(action,"matches",count)
 s=s.replace(old,new)
p.write_text(s,encoding="utf-8")
