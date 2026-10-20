from pathlib import Path
p=Path("app.py"); s=p.read_text(encoding="utf-8")
# Owner App payment tab opens the payment-specific section, not the generic overview.
old='<iframe class="frame" src="/owner-control" title="Skillvaya payment controls"></iframe>'
new='<iframe class="frame" src="/owner-control#payments" title="Skillvaya payment controls"></iframe>'
assert old in s
s=s.replace(old,new,1)
# Add an owner-only gateway readiness endpoint.
needle='''            if path=="/api/categories": return self.sendj({"categories":CATEGORIES})'''
replacement='''            if path=="/api/admin/payfast/status":
                self.require("admin")
                cfg=payfast_config()
                public_https=cfg["public_url"].startswith("https://")
                credentials=bool(cfg["merchant_id"] and cfg["merchant_key"] and cfg["passphrase"])
                return self.sendj({"mode":cfg["mode"],"merchant_configured":credentials,"public_https_configured":public_https,"checkout_ready":bool(credentials and public_https),"refund_api_ready":bool(cfg["merchant_id"] and cfg["passphrase"]),"live":cfg["mode"]=="live","message":"Ready for sandbox checkout only after public HTTPS callback is configured." if cfg["mode"]=="sandbox" and not public_https else ("Public HTTPS callback and merchant settings detected." if credentials and public_https else "Not ready: configure the public HTTPS callback and PayFast merchant credentials.")})
            if path=="/api/categories": return self.sendj({"categories":CATEGORIES})'''
assert needle in s
s=s.replace(needle,replacement,1)
# Add gateway readiness status to the owner-control payments view.
old="""if(tab==='payments'){p.innerHTML='<h2>PayFast payment requests & refunds</h2><p class="muted">Paid plans activate only from verified PayFast notifications. Refunds can be requested only for confirmed PayFast transactions.</p>'+table(['Reference','User','Amount','Plan','Status','Refund','Action'],items.map(x=>[x.reference,x.user_id,'R'+x.amount,x.plan,x.status,x.refund_status||'none',x.status==='verified'&&x.pf_payment_id?'<button onclick="refund('+x.id+','+x.amount+','+(x.refunded_amount||0)+')">Refund</button>':x.status==='pending'?'Awaiting PayFast confirmation':'—']));return}"""
new="""if(tab==='payments'){let g=await api('/api/admin/payfast/status');p.innerHTML='<h2>PayFast payment requests & refunds</h2><p class="muted">Mode: <b>'+esc(g.mode)+'</b> · Merchant settings: '+(g.merchant_configured?'detected':'missing')+' · Public HTTPS callback: '+(g.public_https_configured?'detected':'missing')+'</p><p class="muted">'+esc(g.message)+'</p><p>Paid plans activate only from verified PayFast notifications. Refunds can be requested only for confirmed PayFast transactions.</p>'+table(['Reference','User','Amount','Plan','Status','Refund','Action'],items.map(x=>[x.reference,x.user_id,'R'+x.amount,x.plan,x.status,x.refund_status||'none',x.status==='verified'&&x.pf_payment_id?'<button onclick="refund('+x.id+','+x.amount+','+(x.refunded_amount||0)+')">Refund</button>':x.status==='pending'?'Awaiting PayFast confirmation':'—']));return}"""
assert old in s,"payments UI block not found for readiness status"
s=s.replace(old,new,1)
# Owner control route hash directs the iframe to the selected panel.
old="""load('summary');
</script></body></html>"""
new="""if(location.hash==='#payments')load('payments');else load('summary');
</script></body></html>"""
assert old in s,"owner startup load not found"
s=s.replace(old,new,1)
p.write_text(s,encoding="utf-8")
print("Owner App payment tab now opens payment controls and shows gateway readiness.")
