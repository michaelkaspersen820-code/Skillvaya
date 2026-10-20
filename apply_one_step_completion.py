from pathlib import Path
p=Path(r"C:\Users\user\Documents\Codex\Skillvaya\app.py")
s=p.read_text(encoding="utf-8")
original=s
s=s.replace("import json, sqlite3, hashlib, hmac, secrets, os, datetime, threading, webbrowser","import json, sqlite3, hashlib, hmac, secrets, os, datetime, threading, webbrowser, urllib.parse, urllib.request, urllib.error")
s=s.replace("CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, business_id INTEGER, plan TEXT NOT NULL, billing TEXT NOT NULL, amount INTEGER NOT NULL, reference TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at TEXT NOT NULL, verified_at TEXT);","CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, business_id INTEGER, plan TEXT NOT NULL, billing TEXT NOT NULL, amount INTEGER NOT NULL, reference TEXT NOT NULL UNIQUE, status TEXT DEFAULT 'pending', created_at TEXT NOT NULL, verified_at TEXT, pf_payment_id TEXT, refunded_amount INTEGER NOT NULL DEFAULT 0, refund_status TEXT NOT NULL DEFAULT 'none');")
needle='''        if not c.execute("SELECT 1 FROM settings WHERE key='owner_email'").fetchone():'''
migration='''        pcols={r[1] for r in c.execute("PRAGMA table_info(payments)")}
        if "pf_payment_id" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN pf_payment_id TEXT")
        if "refunded_amount" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN refunded_amount INTEGER NOT NULL DEFAULT 0")
        if "refund_status" not in pcols: c.execute("ALTER TABLE payments ADD COLUMN refund_status TEXT NOT NULL DEFAULT 'none'")
'''
assert needle in s
s=s.replace(needle,migration+needle,1)
needle="def expire_subscriptions():"
helpers=r'''
def payfast_config():
    mode=os.environ.get("SKILLVAYA_PAYFAST_MODE","sandbox").strip().lower()
    sandbox=mode!="live"
    return {
        "mode":"sandbox" if sandbox else "live",
        "merchant_id":os.environ.get("SKILLVAYA_PAYFAST_MERCHANT_ID","10000100" if sandbox else "").strip(),
        "merchant_key":os.environ.get("SKILLVAYA_PAYFAST_MERCHANT_KEY","46f0cd694581a" if sandbox else "").strip(),
        "passphrase":os.environ.get("SKILLVAYA_PAYFAST_PASSPHRASE","jt7NOE43FZPn" if sandbox else ""),
        "public_url":os.environ.get("SKILLVAYA_PUBLIC_URL","").strip().rstrip("/"),
        "host":"sandbox.payfast.co.za" if sandbox else "www.payfast.co.za",
        "api_host":"https://api.sandbox.payfast.co.za" if sandbox else "https://api.payfast.co.za"
    }

def pf_form_signature(fields, passphrase):
    pairs=[]
    for key,value in fields.items():
        if value is None or str(value)=="" or key=="signature": continue
        pairs.append(str(key)+"="+urllib.parse.quote_plus(str(value).strip()))
    if passphrase: pairs.append("passphrase="+urllib.parse.quote_plus(passphrase.strip()))
    return hashlib.md5("&".join(pairs).encode()).hexdigest()

def pf_api_signature(values, passphrase):
    data={str(k):str(v) for k,v in values.items() if v is not None and str(v)!=""}
    if passphrase: data["passphrase"]=passphrase
    return hashlib.md5(urllib.parse.urlencode(sorted(data.items())).encode()).hexdigest()

def pf_api_request(method,path,body=None):
    cfg=payfast_config()
    if not all((cfg["merchant_id"],cfg["passphrase"])):
        raise RuntimeError("PayFast merchant ID and passphrase are not configured.")
    stamp=datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    headers={"merchant-id":cfg["merchant_id"],"version":"v1","timestamp":stamp}
    signed=dict(headers)
    if body: signed.update({k:str(v).lower() if isinstance(v,bool) else str(v) for k,v in body.items() if v is not None})
    headers["signature"]=pf_api_signature(signed,cfg["passphrase"])
    raw=json.dumps(body or {}).encode() if method in ("POST","PUT") else None
    if raw is not None: headers["Content-Type"]="application/json"
    req=urllib.request.Request(cfg["api_host"]+path,data=raw,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=20) as res: return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail=e.read().decode(errors="replace")[:1000]
        raise RuntimeError("PayFast API rejected the request ("+str(e.code)+"): "+detail)

def activate_payment(c, row, pfid):
    if row["status"]=="verified": return False
    c.execute("UPDATE payments SET status='verified',verified_at=?,pf_payment_id=? WHERE id=?",(now(),str(pfid),row["id"]))
    if row["business_id"]:
        days=365 if row["billing"]=="yearly" else 30
        expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=days)).isoformat()
        c.execute("UPDATE businesses SET plan=?,billing=?,payment_status='verified',status='active',subscription_expires_at=? WHERE id=?",(row["plan"],row["billing"],expires,row["business_id"]))
        c.execute("INSERT INTO subscriptions(business_id,user_id,plan,billing,status,started_at,expires_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(business_id) DO UPDATE SET user_id=excluded.user_id,plan=excluded.plan,billing=excluded.billing,status='active',started_at=excluded.started_at,expires_at=excluded.expires_at,cancelled_at=NULL",(row["business_id"],row["user_id"],row["plan"],row["billing"],"active",now(),expires))
    c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("payment_verified","PayFast payment verified","Payment reference "+row["reference"]+" was confirmed by PayFast. Amount: R"+str(row["amount"])+".",now(),setting("owner_email")))
    return True

def process_payfast_itn(raw):
    cfg=payfast_config()
    try: fields={k:v[-1] for k,v in urllib.parse.parse_qs(raw.decode("utf-8"),keep_blank_values=True).items()}
    except Exception: return False,"Malformed notification"
    signature=fields.get("signature","")
    signed_fields={k:v for k,v in fields.items() if k!="signature"}
    if not signature or not hmac.compare_digest(signature,pf_form_signature(signed_fields,cfg["passphrase"])):
        return False,"Invalid PayFast signature"
    if fields.get("merchant_id","")!=cfg["merchant_id"]:
        return False,"Merchant ID mismatch"
    ref=fields.get("m_payment_id","")
    with conn() as c:
        row=c.execute("SELECT * FROM payments WHERE reference=?",(ref,)).fetchone()
    if not row: return False,"Unknown payment reference"
    try: gross=float(fields.get("amount_gross","-1"))
    except ValueError: return False,"Invalid amount"
    if abs(gross-float(row["amount"]))>0.01: return False,"Amount mismatch"
    # PayFast's server-side validation is required in addition to the signature.
    param_string="&".join(k+"="+urllib.parse.quote_plus(str(v).strip()) for k,v in signed_fields.items())
    validate_url="https://"+cfg["host"]+"/eng/query/validate"
    request=urllib.request.Request(validate_url,data=param_string.encode(),headers={"Content-Type":"application/x-www-form-urlencoded","User-Agent":"Skillvaya/1.0"},method="POST")
    try:
        with urllib.request.urlopen(request,timeout=15) as response: validation=response.read().decode().strip()
    except Exception: return False,"Could not validate notification with PayFast"
    if validation!="VALID": return False,"PayFast server validation failed"
    status=fields.get("payment_status","").upper()
    with conn() as c:
        row=c.execute("SELECT * FROM payments WHERE reference=?",(ref,)).fetchone()
        if not row: return False,"Payment disappeared"
        if row["status"]=="verified":
            if row["pf_payment_id"] and row["pf_payment_id"]!=fields.get("pf_payment_id",""): return False,"Duplicate reference with different transaction"
            return True,"Duplicate notification safely ignored"
        if status=="COMPLETE":
            activate_payment(c,row,fields.get("pf_payment_id",""))
        elif status in ("CANCELLED","FAILED"):
            c.execute("UPDATE payments SET status=? WHERE id=? AND status='pending'",(status.lower(),row["id"]))
    return True,"Notification processed"

'''
assert needle in s
s=s.replace(needle,helpers+needle,1)
# Return/cancel status page
needle='''            if path=="/api/categories": return self.sendj({"categories":CATEGORIES})'''
replacement='''            if path in ("/payment/return","/payment/cancel"):
                cancelled=path.endswith("cancel")
                body=("<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><title>Skillvaya payment</title><body style='font:16px Arial;background:#071426;color:#eef;padding:28px'><h1>"+("Payment cancelled" if cancelled else "Payment submitted")+"</h1><p>"+("No payment was taken by Skillvaya on this page. You can return to the customer app and try again." if cancelled else "Thank you. Skillvaya activates paid features only after a verified PayFast notification. You can return to the customer app; payment status may take a moment to update.")+"</p><p><a style='color:#42d3d0' href='/customer'>Return to Skillvaya</a></p></body>").encode()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
            if path=="/api/payment/status":
                u=self.require()
                with conn() as c:
                    rows=c.execute("SELECT reference,plan,billing,amount,status,created_at,verified_at,refund_status FROM payments WHERE user_id=? ORDER BY id DESC LIMIT 20",(u["id"],)).fetchall()
                return self.sendj({"payments":[dict(x) for x in rows],"gateway":payfast_config()["mode"]})
            if path=="/api/categories": return self.sendj({"categories":CATEGORIES})'''
assert needle in s
s=s.replace(needle,replacement,1)
# payment create: add checkout details response
old='''                notify("payment_request","Payment request created","Provider: "+u["email"]+"; plan: "+plan+"; billing: "+billing+"; amount: R"+str(amount)+"; reference: "+ref+". Payment is not confirmed.")
                return self.sendj({"ok":True,"reference":ref,"amount":amount,"status":"pending"})'''
new='''                notify("payment_request","PayFast payment request created","Provider: "+u["email"]+"; plan: "+plan+"; billing: "+billing+"; amount: R"+str(amount)+"; reference: "+ref+". Payment is not confirmed.")
                cfg=payfast_config()
                if not cfg["public_url"] or not cfg["public_url"].startswith("https://"):
                    return self.sendj({"ok":True,"reference":ref,"amount":amount,"status":"pending","checkout_ready":False,"error":"PayFast checkout requires SKILLVAYA_PUBLIC_URL to be set to the public HTTPS Skillvaya address. This local-only installation cannot receive PayFast notifications."},503)
                if not cfg["merchant_id"] or not cfg["merchant_key"]:
                    return self.sendj({"ok":True,"reference":ref,"amount":amount,"status":"pending","checkout_ready":False,"error":"PayFast merchant credentials are not configured."},503)
                fields={"merchant_id":cfg["merchant_id"],"merchant_key":cfg["merchant_key"],"return_url":cfg["public_url"]+"/payment/return","cancel_url":cfg["public_url"]+"/payment/cancel","notify_url":cfg["public_url"]+"/api/payfast/itn","name_first":u["name"].split()[0][:100],"name_last":" ".join(u["name"].split()[1:])[:100],"email_address":u["email"],"m_payment_id":ref,"amount":format(float(amount),".2f"),"item_name":"Skillvaya "+PLANS[plan]["name"],"item_description":("Yearly" if billing=="yearly" else "Monthly")+" paid provider placement"}
                fields["signature"]=pf_form_signature(fields,cfg["passphrase"])
                return self.sendj({"ok":True,"reference":ref,"amount":amount,"status":"pending","checkout_ready":True,"checkout_url":"https://"+cfg["host"]+"/eng/process","fields":fields,"mode":cfg["mode"]})'''
assert old in s
s=s.replace(old,new,1)
# Special ITN route before JSON body parsing
old='''        try:
            d=self.body()
            if path=="/api/analytics":'''
new='''        try:
            if path=="/api/payfast/itn":
                raw=self.rfile.read(int(self.headers.get("Content-Length","0")))
                ok,message=process_payfast_itn(raw)
                if ok:
                    self.send_response(200); self.send_header("Content-Type","text/plain; charset=utf-8"); self.end_headers(); self.wfile.write(b"OK")
                else:
                    print("PayFast ITN rejected:",message,flush=True)
                    self.send_response(400); self.send_header("Content-Type","text/plain; charset=utf-8"); self.end_headers(); self.wfile.write(message.encode("utf-8"))
                return
            d=self.body()
            if path=="/api/analytics":'''
assert old in s
s=s.replace(old,new,1)
# Admin refund API before generic admin path
needle='''            if path.startswith("/api/admin/"):
                self.require("admin")
                bits=path.strip("/").split("/")'''
refund=r'''            if path=="/api/admin/refunds":
                self.require("admin")
                return self.sendj({"items":self._refund_list()})
            if path.startswith("/api/admin/refunds/"):
                self.require("admin")
                pid=int(path.rsplit("/",1)[1])
                reason=str(d.get("reason","")).strip()[:255]
                try: amount=int(d.get("amount",0))
                except (ValueError,TypeError): return self.sendj({"error":"Refund amount must be entered in cents."},400)
                if amount<1 or len(reason)<3: return self.sendj({"error":"Enter a refund amount greater than zero and a reason of at least 3 characters."},400)
                with conn() as c: row=c.execute("SELECT * FROM payments WHERE id=?",(pid,)).fetchone()
                if not row: return self.sendj({"error":"Payment not found."},404)
                if row["status"]!="verified" or not row["pf_payment_id"]: return self.sendj({"error":"Only PayFast-confirmed transactions can be refunded."},400)
                if amount+int(row["refunded_amount"] or 0)>int(row["amount"])*100: return self.sendj({"error":"Refund exceeds the remaining amount paid."},400)
                query=pf_api_request("GET","/refunds/query/"+urllib.parse.quote(str(row["pf_payment_id"]),safe=""))
                qdata=query.get("data",query)
                available=qdata.get("amount_available_for_refund")
                if available is not None and amount>int(float(available)): return self.sendj({"error":"PayFast reports a lower remaining refundable balance."},400)
                payload={"amount":str(amount),"reason":reason,"notify_buyer":True,"notify_merchant":True}
                result=pf_api_request("POST","/refunds/"+urllib.parse.quote(str(row["pf_payment_id"]),safe=""),payload)
                data=result.get("data",result)
                if not (result.get("status")=="success" or data.get("response") is True):
                    return self.sendj({"error":"PayFast did not confirm the refund request. "+str(result)[:500]},502)
                with conn() as c:
                    total=int(row["refunded_amount"] or 0)+amount
                    c.execute("UPDATE payments SET refunded_amount=?,refund_status=? WHERE id=?",(total,"refunded" if total>=int(row["amount"])*100 else "partial",pid))
                    c.execute("INSERT INTO notifications(kind,subject,body,created_at,recipient) VALUES(?,?,?,?,?)",("refund","PayFast refund submitted","Payment reference "+row["reference"]+"; refund requested R"+format(amount/100,".2f")+"; reason: "+reason,now(),setting("owner_email")))
                return self.sendj({"ok":True,"refund_status":"refunded" if total>=int(row["amount"])*100 else "partial","refunded_amount":total,"message":"PayFast accepted the refund request."})
            if path.startswith("/api/admin/"):
                self.require("admin")
                bits=path.strip("/").split("/")'''
assert needle in s
s=s.replace(needle,refund,1)
# add _refund_list method to Handler before do_GET
needle='''    def do_GET(self):
'''
method='''    def _refund_list(self):
        with conn() as c:
            rows=c.execute("SELECT p.id,p.reference,p.plan,p.billing,p.amount,p.status,p.created_at,p.verified_at,p.pf_payment_id,p.refunded_amount,p.refund_status,u.email user_email FROM payments p JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC LIMIT 300").fetchall()
        return [dict(x) for x in rows]
    def do_GET(self):
'''
assert needle in s
s=s.replace(needle,method,1)
# Customer JS redirect to PayFast checkout form rather than alert-only
old="""async function choosePlan(plan,billing){if(!me){view('account');alert('Create a provider account or sign in first.');return}try{let d=await api('/api/payments',{method:'POST',body:JSON.stringify({plan,billing})});alert('Payment request created. Reference: '+d.reference+'\\\\nAmount: R'+d.amount+'\\\\nStatus: pending verification. Automatic activation requires a live payment gateway.')}catch(e){alert(e.message)}}"""
new="""async function choosePlan(plan,billing){if(!me){view('account');alert('Create a provider account or sign in first.');return}try{let d=await api('/api/payments',{method:'POST',body:JSON.stringify({plan,billing})});if(!d.checkout_ready){alert((d.error||'PayFast checkout is not configured.')+'\\\\nReference: '+d.reference+'\\\\nAmount: R'+d.amount);return}let f=document.createElement('form');f.method='POST';f.action=d.checkout_url;f.style.display='none';Object.entries(d.fields).forEach(([k,v])=>{let i=document.createElement('input');i.type='hidden';i.name=k;i.value=v;f.appendChild(i)});document.body.appendChild(f);f.submit()}catch(e){alert(e.message)}}"""
if old not in s:
    print("WARNING: choosePlan exact string not found; payment API patched but UI redirect needs follow-up.")
else: s=s.replace(old,new,1)
# Owner payment table: add refund controls and details; new API uses amount in cents
old="""if(tab==='notifications'){h='<h3>Alert inbox</h3>"""
# leave existing payment table in place; add refund button in its row
oldrow="""d.items.map(x=>'<tr><td>'+esc(x.reference)+'</td><td>'+esc(x.plan)+' / '+esc(x.billing)+'</td><td>R'+x.amount+'</td><td>'+esc(x.status)+'</td><td>'+(x.status==='pending'?'<button class=\\"primary\\" onclick=\\"verifyPayment('+x.id+')\\">Mark verified</button>':'—')+'</td></tr>').join('')"""
newrow="""d.items.map(x=>'<tr><td>'+esc(x.reference)+'</td><td>'+esc(x.plan)+' / '+esc(x.billing)+'</td><td>R'+x.amount+'</td><td>'+esc(x.status)+'<br>'+esc(x.refund_status||'none')+'</td><td>'+(x.status==='pending'?'<button class=\\"primary\\" onclick=\\"verifyPayment('+x.id+')\\">Mark verified (manual)</button>':(x.status==='verified'&&x.pf_payment_id?'<button class=\\"danger\\" onclick=\\"refundPayment('+x.id+','+x.amount+','+(x.refunded_amount||0)+')\\">Refund</button>':'—'))+'</td></tr>').join('')"""
if oldrow in s: s=s.replace(oldrow,newrow,1)
else: print("WARNING: payment table row replacement not found")
needle="""async function verifyPayment(id){if(!confirm('Only confirm if payment has actually been received and checked in your bank/payment provider. Continue?'))return;try{await api('/api/admin/payments/'+id,{method:'POST',body:'{}'});adminTab('payments')}catch(e){alert(e.message)}}"""
refundjs=needle+"""
async function refundPayment(id,amount,already){let remaining=amount*100-Number(already||0);let dollars=prompt('Refund amount in Rands (up to R'+(remaining/100).toFixed(2)+'). Partial refunds are supported.',''+(remaining/100).toFixed(2));if(dollars===null)return;let cents=Math.round(Number(dollars)*100);if(!Number.isFinite(cents)||cents<1||cents>remaining){alert('Enter a valid amount within the remaining paid balance.');return}let reason=prompt('Reason for the refund (required):');if(!reason||reason.trim().length<3)return; if(!confirm('Submit a real PayFast refund for R'+(cents/100).toFixed(2)+'?'))return;try{let d=await api('/api/admin/refunds/'+id,{method:'POST',body:JSON.stringify({amount:cents,reason})});alert(d.message||'Refund request accepted by PayFast.');adminTab('payments')}catch(e){alert(e.message)}}"""
if needle in s: s=s.replace(needle,refundjs,1)
else: print("WARNING: verifyPayment JS not found")
# Update owner shell payment message
s=s.replace("Refund actions will be added with the PayFast integration; they are not available yet. PayFast is not live-connected, so real transactions remain disabled.","PayFast payment status, verified transactions and eligible refunds are managed in Owner Control. Live processing requires merchant credentials and public HTTPS hosting.")
s=s.replace("Refund controls are not implemented yet. Gateway connection status: not configured. Do not accept live payments until PayFast sandbox integration, notification verification, refunds and HTTPS callback hosting have been tested.","Refunds are enabled for PayFast-confirmed transactions when the merchant API credentials are configured. Current mode and readiness depend on the server environment; this local PC URL is not a public HTTPS callback.")
if s==original: raise SystemExit("No changes made")
p.write_text(s,encoding="utf-8")
print("patched",len(s),"bytes")
