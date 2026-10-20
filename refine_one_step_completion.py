from pathlib import Path
p=Path("app.py"); s=p.read_text(encoding="utf-8")
old="""async function choosePlan(plan,billing){if(!me){view('account');alert('Create a provider account or sign in first.');return}try{let d=await api('/api/payments',{method:'POST',body:JSON.stringify({plan,billing})});alert('Payment request created. Reference: '+d.reference+'\\nAmount: R'+d.amount+'\\nStatus: pending verification. Automatic activation requires a live payment gateway.')}catch(e){alert(e.message)}}"""
new="""async function choosePlan(plan,billing){if(!me){view('account');alert('Create a provider account or sign in first.');return}try{let d=await api('/api/payments',{method:'POST',body:JSON.stringify({plan,billing})});if(!d.checkout_ready){alert((d.error||'PayFast checkout is not configured.')+'\\nReference: '+(d.reference||'not created')+'\\nAmount: R'+(d.amount||''));return}let f=document.createElement('form');f.method='POST';f.action=d.checkout_url;f.style.display='none';Object.entries(d.fields).forEach(([k,v])=>{let i=document.createElement('input');i.type='hidden';i.name=k;i.value=v;f.appendChild(i)});document.body.appendChild(f);f.submit()}catch(e){alert(e.message)}}"""
assert old in s, "choosePlan source not found"
s=s.replace(old,new,1)
start=s.find("d.items.map(x=>'<tr><td>'+esc(x.reference)")
assert start>=0, "payment row start not found"
end=s.find(".join('')+'</table></div>'",start)
assert end>=0, "payment row end not found"
end+=len(".join('')")
s=s[:start]+"""d.items.map(x=>'<tr><td>'+esc(x.reference)+'</td><td>'+esc(x.plan)+' / '+esc(x.billing)+'</td><td>R'+x.amount+'</td><td>'+esc(x.status)+'<br>'+esc(x.refund_status||'none')+'</td><td>'+(x.status==='verified'&&x.pf_payment_id?'<button class=\\\\"danger\\\\" onclick=\\\\"refundPayment('+x.id+','+x.amount+','+(x.refunded_amount||0)+')\\\\">Refund</button>':(x.status==='pending'?'Awaiting PayFast confirmation':'—'))+'</td></tr>').join('')"""+s[end:]
s=s.replace('''"checkout_ready":False,"error":"PayFast checkout requires SKILLVAYA_PUBLIC_URL to be set to the public HTTPS Skillvaya address. This local-only installation cannot receive PayFast notifications."},503)''','''"checkout_ready":False,"error":"PayFast checkout requires SKILLVAYA_PUBLIC_URL to be set to the public HTTPS Skillvaya address. This local-only installation cannot receive PayFast notifications."},200)''')
s=s.replace('''"checkout_ready":False,"error":"PayFast merchant credentials are not configured."},503)''','''"checkout_ready":False,"error":"PayFast merchant credentials are not configured."},200)''')
old='''                        if row["status"]=="verified":
                            return self.sendj({"ok":True,"already_verified":True})
                        c.execute("UPDATE payments SET status='verified',verified_at=? WHERE id=?",(now(),pid))
                        if row["business_id"]:
                            days=365 if row["billing"]=="yearly" else 30
                            expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=days)).isoformat()
                            c.execute("UPDATE businesses SET plan=?,billing=?,payment_status='verified',status='active',subscription_expires_at=? WHERE id=?",(row["plan"],row["billing"],expires,row["business_id"]))
                            c.execute("INSERT INTO subscriptions(business_id,user_id,plan,billing,status,started_at,expires_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(business_id) DO UPDATE SET user_id=excluded.user_id,plan=excluded.plan,billing=excluded.billing,status='active',started_at=excluded.started_at,expires_at=excluded.expires_at,cancelled_at=NULL",(row["business_id"],row["user_id"],row["plan"],row["billing"],"active",now(),expires))
                        c.execute("INSERT INTO notifications(kind,subject,body,created_at) VALUES(?,?,?,?)",("payment_verified","Payment verified","Payment reference "+row["reference"]+" has been marked verified. Amount: R"+str(row["amount"])+".",now()))
                        return self.sendj({"ok":True})'''
new='''                        if row["status"]=="verified":
                            return self.sendj({"ok":True,"already_verified":True})
                        return self.sendj({"error":"Manual payment verification is disabled. Paid plans activate only after a valid PayFast notification."},409)'''
assert old in s, "manual verify block not found"
s=s.replace(old,new,1)
p.write_text(s,encoding="utf-8")
print("UI checkout redirect, refund controls and ITN-only activation patched")
