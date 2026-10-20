import app,re,subprocess,tempfile,pathlib,urllib.request,json
for name,html in [("customer",app.HTML),("owner",app.OWNER_HTML),("shell",app.OWNER_APP_HTML)]:
 scripts=re.findall(r"<script[^>]*>(.*?)</script>",html,re.S|re.I)
 for i,js in enumerate(scripts):
  p=pathlib.Path(tempfile.gettempdir())/("sv_"+name+"_"+str(i)+".js")
  p.write_text(js,encoding="utf-8")
  r=subprocess.run(["node","--check",str(p)],capture_output=True,text=True)
  if r.returncode: raise SystemExit(name+" JS SYNTAX ERROR: "+r.stderr)
 print("PASS JS syntax:",name,len(scripts),"script(s)")
for path in ["/","/customer","/owner-control","/manifest.json","/api/categories","/api/admin/payments","/api/admin/notifications"]:
 with urllib.request.urlopen("http://127.0.0.1:8877"+path,timeout=5) as r:
  data=r.read().decode(errors="replace")
  print("LIVE",path,r.status,len(data))
