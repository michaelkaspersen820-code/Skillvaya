import app,sys
sys.stdout.reconfigure(encoding="utf-8")
h=app.OWNER_HTML
for k in ["tab==='payments'","load('payments')","/api/admin/payments","<h2>Payments"]:
 i=h.find(k); print("\n---",k,i,"---\n",h[i:i+2600] if i>=0 else "not found")
