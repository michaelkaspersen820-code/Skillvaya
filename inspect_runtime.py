import app
for n in ("HTML","OWNER_HTML","OWNER_APP_HTML"):
 h=getattr(app,n)
 print(n,"len",len(h),"checkout", "checkout_ready" in h,"refundPayment","refundPayment" in h,"paymentreq","Payment requests" in h,"choosePlan","choosePlan" in h)
