import app
h=app.OWNER_HTML
for k in ["Payment requests","async function load","function load(","adminTab","verifyPayment","api('/api/admin/payments')"]:
 i=h.find(k); print("\n---",k,i,"---\n",h[i:i+1800] if i>=0 else "not found")
