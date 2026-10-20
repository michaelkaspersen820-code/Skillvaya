from pathlib import Path
p=Path("app.py"); s=p.read_text(encoding="utf-8")
old="""if(tab==='payments'){p.innerHTML='<h2>Payment requests</h2>'+table(['Reference','User','Amount','Plan','Status','Action'],items.map(x=>[x.reference,x.user_id,'R'+x.amount,x.plan,x.status,x.status==='pending'?'<button onclick="verify('+x.id+')">Mark manually verified</button>':'—']));return}"""
new="""if(tab==='payments'){p.innerHTML='<h2>PayFast payment requests & refunds</h2><p class="muted">Paid plans activate only from verified PayFast notifications. Refunds can be requested only for confirmed PayFast transactions.</p>'+table(['Reference','User','Amount','Plan','Status','Refund','Action'],items.map(x=>[x.reference,x.user_id,'R'+x.amount,x.plan,x.status,x.refund_status||'none',x.status==='verified'&&x.pf_payment_id?'<button onclick="refund('+x.id+','+x.amount+','+(x.refunded_amount||0)+')">Refund</button>':x.status==='pending'?'Awaiting PayFast confirmation':'—']));return}"""
assert old in s,"owner payments tab not found"
s=s.replace(old,new,1)
old="""async function verify(id){if(!confirm('Manually mark this payment verified? Do this only after checking actual receipt with the payment provider/bank.'))return;try{await api('/api/admin/payments/'+id,{method:'POST',body:'{}'});load('payments')}catch(e){alert(e.message)}}"""
new="""async function refund(id,amount,already){let remaining=amount*100-Number(already||0);let value=prompt('Refund amount in Rands (maximum R'+(remaining/100).toFixed(2)+')',''+(remaining/100).toFixed(2));if(value===null)return;let cents=Math.round(Number(value)*100);if(!Number.isFinite(cents)||cents<1||cents>remaining){alert('Enter a valid amount within the remaining paid balance.');return}let reason=prompt('Reason for refund (at least 3 characters):');if(!reason||reason.trim().length<3)return;if(!confirm('Submit a real PayFast refund request for R'+(cents/100).toFixed(2)+'?'))return;try{let d=await api('/api/admin/refunds/'+id,{method:'POST',body:JSON.stringify({amount:cents,reason})});alert(d.message||'PayFast accepted the refund request.');load('payments')}catch(e){alert(e.message)}}"""
assert old in s,"owner verify function not found"
s=s.replace(old,new,1)
p.write_text(s,encoding="utf-8")
print("Owner Control now exposes verified PayFast refund controls; manual verification removed from its UI.")
