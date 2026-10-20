from pathlib import Path
p=Path("app.py"); s=p.read_text(encoding="utf-8")
old='''                amount=PLANS[plan]["monthly"]*(11 if billing=="yearly" else 1); ref="SV-"+secrets.token_hex(4).upper()
                with conn() as c:
                    b=c.execute("SELECT id FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    cur=c.execute("INSERT INTO payments(user_id,business_id,plan,billing,amount,reference,created_at) VALUES(?,?,?,?,?,?,?)",(u["id"],b["id"] if b else None,plan,billing,amount,ref,now()))
                notify("payment_request","PayFast payment request created","Provider: "+u["email"]+"; plan: "+plan+"; billing: "+billing+"; amount: R"+str(amount)+"; reference: "+ref+". Payment is not confirmed.")
                cfg=payfast_config()
                if not cfg["public_url"] or not cfg["public_url"].startswith("https://"):
                    return self.sendj({"ok":True,"reference":ref,"amount":amount,"status":"pending","checkout_ready":False,"error":"PayFast checkout requires SKILLVAYA_PUBLIC_URL to be set to the public HTTPS Skillvaya address. This local-only installation cannot receive PayFast notifications."},200)
                if not cfg["merchant_id"] or not cfg["merchant_key"]:
                    return self.sendj({"ok":True,"reference":ref,"amount":amount,"status":"pending","checkout_ready":False,"error":"PayFast merchant credentials are not configured."},200)
                fields={"merchant_id":cfg["merchant_id"],"merchant_key":cfg["merchant_key"],"return_url":cfg["public_url"]+"/payment/return","cancel_url":cfg["public_url"]+"/payment/cancel","notify_url":cfg["public_url"]+"/api/payfast/itn","name_first":u["name"].split()[0][:100],"name_last":" ".join(u["name"].split()[1:])[:100],"email_address":u["email"],"m_payment_id":ref,"amount":format(float(amount),".2f"),"item_name":"Skillvaya "+PLANS[plan]["name"],"item_description":("Yearly" if billing=="yearly" else "Monthly")+" paid provider placement"}
'''
new='''                cfg=payfast_config()
                if not cfg["public_url"] or not cfg["public_url"].startswith("https://"):
                    return self.sendj({"error":"PayFast checkout is disabled until SKILLVAYA_PUBLIC_URL is set to a real public HTTPS Skillvaya address. This local-only installation cannot receive PayFast notifications."},503)
                if not cfg["merchant_id"] or not cfg["merchant_key"] or not cfg["passphrase"]:
                    return self.sendj({"error":"PayFast merchant ID, key, and passphrase must be configured before checkout."},503)
                amount=PLANS[plan]["monthly"]*(11 if billing=="yearly" else 1); ref="SV-"+secrets.token_hex(4).upper()
                with conn() as c:
                    b=c.execute("SELECT id FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1",(u["id"],)).fetchone()
                    c.execute("INSERT INTO payments(user_id,business_id,plan,billing,amount,reference,created_at) VALUES(?,?,?,?,?,?,?)",(u["id"],b["id"] if b else None,plan,billing,amount,ref,now()))
                notify("payment_request","PayFast payment request created","Provider: "+u["email"]+"; plan: "+plan+"; billing: "+billing+"; amount: R"+str(amount)+"; reference: "+ref+". Payment is not confirmed.")
                fields={"merchant_id":cfg["merchant_id"],"merchant_key":cfg["merchant_key"],"return_url":cfg["public_url"]+"/payment/return","cancel_url":cfg["public_url"]+"/payment/cancel","notify_url":cfg["public_url"]+"/api/payfast/itn","name_first":u["name"].split()[0][:100],"name_last":" ".join(u["name"].split()[1:])[:100],"email_address":u["email"],"m_payment_id":ref,"amount":format(float(amount),".2f"),"item_name":"Skillvaya "+PLANS[plan]["name"],"item_description":("Yearly" if billing=="yearly" else "Monthly")+" paid provider placement"}
'''
assert old in s,"payment creation block not found"
s=s.replace(old,new,1)
# Require the unique PayFast transaction ID before accepting an ITN.
needle='''    ref=fields.get("m_payment_id","")
    with conn() as c:'''
replacement='''    if not fields.get("pf_payment_id","").strip(): return False,"Missing PayFast transaction ID"
    ref=fields.get("m_payment_id","")
    with conn() as c:'''
assert needle in s
s=s.replace(needle,replacement,1)
p.write_text(s,encoding="utf-8")
print("Disabled checkout before creating a payment record when HTTPS/credentials are missing; ITN now requires pf_payment_id.")
