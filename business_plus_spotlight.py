"""Additive Business Plus / Spotlight workspace for Skillvaya.

The workspace is deliberately isolated from existing marketplace and owner routes.
Every data request is scoped to the signed-in provider's active, verified paid listing.
"""
import json
from html import escape

class SubscriptionAccessError(PermissionError):
    """A signed-in provider is authenticated but lacks the required paid plan."""


TABLES = {
    "jobs": ("sv_business_jobs", "lead_pipeline"),
    "calendar": ("sv_business_jobs", "customer_booking_calendar"),
    "customers": ("sv_business_customers", "crm"),
    "quotes": ("sv_business_quotes", "quotation_followups"),
    "invoices": ("sv_business_invoices", "invoice_payment_tracking"),
    "packages": ("sv_business_packages", "customer_service_packages"),
    "campaigns": ("sv_business_campaigns", "campaign_management"),
    "offers": ("sv_business_offers", "promotional_offers"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sv_business_jobs (
 id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, title TEXT NOT NULL,
 customer_name TEXT NOT NULL, customer_contact TEXT DEFAULT '', lead_source TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'new',
 scheduled_for TEXT DEFAULT '', amount_cents INTEGER NOT NULL DEFAULT 0, notes TEXT DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sv_business_customers (
 id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, name TEXT NOT NULL,
 phone TEXT DEFAULT '', email TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sv_business_quotes (
 id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, customer_name TEXT NOT NULL,
 description TEXT NOT NULL, amount_cents INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
 follow_up_date TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sv_business_invoices (
 id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, customer_name TEXT NOT NULL,
 reference TEXT NOT NULL, amount_cents INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
 due_date TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(business_id, reference)
);
CREATE TABLE IF NOT EXISTS sv_business_packages (
 id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, title TEXT NOT NULL,
 description TEXT DEFAULT '', price_cents INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sv_business_campaigns (
 id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, title TEXT NOT NULL,
 channel TEXT NOT NULL DEFAULT 'Skillvaya', description TEXT DEFAULT '',
 start_date TEXT DEFAULT '', end_date TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sv_business_offers (
 id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, title TEXT NOT NULL,
 code TEXT NOT NULL, discount_text TEXT NOT NULL, starts_on TEXT DEFAULT '',
 ends_on TEXT DEFAULT '', redemption_limit INTEGER NOT NULL DEFAULT 0,
 redemptions INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
 created_at TEXT NOT NULL, UNIQUE(business_id, code)
);
"""

PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#10233f"><title>Skillvaya Business Workspace</title><style>
:root{font:15px/1.5 "Segoe UI",Arial,sans-serif;color:#19283b;background:#f4f7fb;--navy:#10233f;--blue:#2365d8;--line:#e1e8f1;--muted:#66758b}*{box-sizing:border-box}body{margin:0}header{background:var(--navy);color:white;padding:18px 22px}.brand{font-size:23px;font-weight:850}.brand span{color:#75b7ff}.wrap{max-width:1180px;margin:auto;padding:20px}.hero{background:linear-gradient(110deg,#10233f,#1c4b83);color:white;border-radius:16px;padding:22px;margin-bottom:16px}.hero p{color:#d7e7fa;margin-bottom:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:13px}.card{background:white;border:1px solid var(--line);border-radius:14px;padding:16px;min-width:0}.muted{color:var(--muted)}.notice{padding:12px;border-radius:9px;background:#fff4d8;color:#77500a;margin:12px 0}.error{background:#fff0f0;color:#a32222}.good{background:#eaf7f0;color:#13714d}.tabs{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0}.tabs button,button{border:0;border-radius:9px;padding:10px 13px;font:inherit;font-weight:650;cursor:pointer}.tabs button{background:#e8eef7;color:var(--navy)}.tabs button.active,button.primary{background:var(--blue);color:white}button.secondary{background:#e8eef7;color:var(--navy)}button.warn{background:#fff0f0;color:#a32222}label{display:block;font-weight:650;font-size:13px;margin:8px 0 4px}input,select,textarea{width:100%;border:1px solid #cfd9e6;border-radius:8px;padding:10px;font:inherit;background:#fff}textarea{min-height:75px;resize:vertical}.formgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.full{grid-column:1/-1}.stat{font-size:27px;font-weight:850}.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:560px}td,th{padding:9px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:var(--muted)}.pill{display:inline-block;padding:3px 8px;border-radius:99px;background:#e8f1ff;color:#174c91;font-size:12px}.hidden{display:none!important}.actions{display:flex;gap:6px;flex-wrap:wrap}.empty{padding:14px;color:var(--muted)}@media(max-width:600px){.wrap{padding:12px}.formgrid{grid-template-columns:1fr}.full{grid-column:auto}header{padding:14px}}
</style></head><body><header><div class="brand">skill<span>vaya</span> · Business Workspace</div><div style="opacity:.8;font-size:13px">Business Plus operations · Spotlight growth tools</div></header><main class="wrap"><section class="hero"><h1 style="margin:0">Your business, organised.</h1><p>Manage jobs, customers, quotations, invoices and service packages. Spotlight subscribers also get campaign and offer management.</p></section><div id="notice" class="notice">Checking your provider subscription…</div><section id="workspace" class="hidden"><div class="grid" id="stats"></div><div class="tabs" id="tabs"></div><section class="card"><div id="panel"></div></section></section><p><button class="secondary" onclick="location.href='/customer'">← Back to Skillvaya</button></p></main><script>
const tabs=[['jobs','Jobs & leads','Business Plus'],['calendar','Booking calendar','Business Plus'],['customers','Customer CRM','Business Plus'],['quotes','Quotations','Business Plus'],['invoices','Invoices','Business Plus'],['packages','Service packages','Business Plus'],['campaigns','Campaigns','Spotlight'],['offers','Offers & vouchers','Spotlight']];
const fields={
jobs:[['title','Job / enquiry title','text',true],['customer_name','Customer name','text',true],['customer_contact','Phone or email','text',false],['lead_source','Lead source / campaign name','text',false],['scheduled_for','Scheduled date','date',false],['amount','Estimated amount (R)','number',false],['notes','Notes','textarea',false]],
customers:[['name','Customer name','text',true],['phone','Phone','text',false],['email','Email','email',false],['notes','Customer notes','textarea',false]],
quotes:[['customer_name','Customer name','text',true],['description','Work description','textarea',true],['amount','Quote amount (R)','number',true],['follow_up_date','Follow-up date','date',false]],
invoices:[['customer_name','Customer name','text',true],['reference','Invoice reference','text',true],['amount','Invoice amount (R)','number',true],['due_date','Due date','date',false]],
packages:[['title','Package name','text',true],['description','What's included','textarea',false],['price','Price (R)','number',true]],
campaigns:[['title','Campaign name','text',true],['channel','Channel','select',false,['Skillvaya','WhatsApp (manual)','Facebook (manual)','Email (manual)','Other']],['description','Campaign details','textarea',false],['start_date','Start date','date',false],['end_date','End date','date',false]],
offers:[['title','Offer title','text',true],['code','Voucher code','text',true],['discount_text','Discount / terms','text',true],['starts_on','Starts on','date',false],['ends_on','Ends on','date',false],['redemption_limit','Redemption limit (0 = unlimited)','number',false]]
};
let token=localStorage.getItem('sv_token')||'',data={},active='jobs',me=null;
function esc(x){return String(x==null?'':x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function api(path,opts={}){let r=await fetch(path,{...opts,headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{}),...(opts.headers||{})}});let j=await r.json().catch(()=>({error:'Invalid server response'}));if(!r.ok)throw Error(j.error||'Request failed');return j}
function message(text,kind='notice'){let e=document.getElementById('notice');e.className='notice '+kind;e.textContent=text}
function money(cents){return 'R'+(Number(cents||0)/100).toLocaleString('en-ZA',{minimumFractionDigits:2,maximumFractionDigits:2})}
async function init(){if(!token){message('Please sign in to your provider account in Skillvaya first, then reopen Business Workspace.');return}try{data=await api('/api/business-tools/data');me=data.business;document.getElementById('workspace').classList.remove('hidden');message(me.name+' · '+me.plan_name+' · subscription verified','good');renderTabs();renderStats();renderPanel()}catch(e){message(e.message+' Use an active, PayFast-verified Business Plus or Business Spotlight subscription to open these tools.','error')}}
function renderTabs(){document.getElementById('tabs').innerHTML=tabs.filter(t=>data.available.includes(t[0])).map(t=>'<button class="'+(active===t[0]?'active':'')+'" onclick="active='+JSON.stringify(t[0])+';renderTabs();renderPanel()">'+t[1]+'</button>').join('')}
function renderStats(){let today=new Date().toISOString().slice(0,10);let items=[['Open jobs',(data.jobs||[]).filter(x=>!['completed','lost'].includes(x.status)).length],['Customers',(data.customers||[]).length],['Quotes awaiting decision',(data.quotes||[]).filter(x=>['draft','sent'].includes(x.status)).length],['Unpaid invoices',(data.invoices||[]).filter(x=>!['paid','cancelled'].includes(x.status)).length],['Quote follow-ups due',(data.quotes||[]).filter(x=>x.follow_up_date&&x.follow_up_date<=today&&!['accepted','rejected'].includes(x.status)).length]];if(data.available.includes('campaigns'))items.push(['Campaign-attributed leads',(data.campaign_analytics||[]).reduce((n,x)=>n+Number(x.leads||0),0)]);document.getElementById('stats').innerHTML=items.map(x=>'<div class="card"><div class="muted">'+x[0]+'</div><div class="stat">'+x[1]+'</div></div>').join('')}
function fieldHtml(x){let control=x[2]==='textarea'?'<textarea name="'+x[0]+'" '+(x[3]?'required':'')+'></textarea>':x[2]==='select'?'<select name="'+x[0]+'">'+x[4].map(v=>'<option>'+esc(v)+'</option>').join('')+'</select>':'<input name="'+x[0]+'" type="'+x[2]+'" '+(x[3]?'required':'')+(x[2]==='number'?' min="0" step="0.01"':'')+'>';return '<div class="'+(x[2]==='textarea'?'full':'')+'"><label>'+esc(x[1])+(x[3]?' *':'')+'</label>'+control+'</div>'}
function renderPanel(){let p=document.getElementById('panel');let title=tabs.find(t=>t[0]===active)?.[1]||'Workspace';let rows=data[active]||[];let f=fields[active]||[];if(active==='calendar'){let scheduled=[...(data.calendar||[])].sort((a,b)=>String(a.scheduled_for||'').localeCompare(String(b.scheduled_for||'')));p.innerHTML='<h2 style="margin-top:0">Booking calendar</h2><p class="muted">Upcoming and scheduled work, ordered by date. Create or reschedule jobs in Jobs & leads.</p><div class="tablewrap"><table><thead><tr><th>Date</th><th>Job</th><th>Customer</th><th>Contact</th><th>Status</th><th>Update</th></tr></thead><tbody>'+(scheduled.length?scheduled.map(x=>'<tr><td>'+esc(x.scheduled_for||'Unscheduled')+'</td><td>'+esc(x.title)+'</td><td>'+esc(x.customer_name)+'</td><td>'+esc(x.customer_contact)+'</td><td>'+esc(x.status)+'</td><td>'+statusButtons('calendar',x)+'</td></tr>').join(''):'<tr><td colspan="6" class="empty">No jobs are scheduled yet. Add a job and choose a scheduled date.</td></tr>')+'</tbody></table></div>';return}p.innerHTML='<h2 style="margin-top:0">'+title+'</h2><form id="createForm"><div class="formgrid">'+f.map(fieldHtml).join('')+'</div><p><button class="primary">Save '+title.toLowerCase().replace(/s$/,'')+'</button></p></form><div id="formMsg" class="muted"></div><div class="tablewrap"><table><thead><tr>'+columns(active).map(x=>'<th>'+x[1]+'</th>').join('')+'<th>Status / action</th></tr></thead><tbody>'+(rows.length?rows.map(x=>'<tr>'+columns(active).map(c=>'<td>'+esc(c[2]?money(x[c[2]]):x[c[0]])+'</td>').join('')+'<td><span class="pill">'+esc(x.status||'active')+'</span><div class="actions" style="margin-top:6px">'+statusButtons(active,x)+'</div></td></tr>').join(''):'<tr><td colspan="8" class="empty">No records yet. Use the form above to add your first record.</td></tr>')+'</tbody></table></div>';
document.getElementById('createForm').onsubmit=async e=>{e.preventDefault();let fd=Object.fromEntries(new FormData(e.target));try{await api('/api/business-tools/'+active,{method:'POST',body:JSON.stringify(fd)});await refresh();renderPanel();document.getElementById('formMsg').textContent='Saved.'}catch(err){document.getElementById('formMsg').textContent=err.message}}
}
function columns(k){return {jobs:[['title','Job'],['customer_name','Customer'],['customer_contact','Contact'],['lead_source','Lead source'],['scheduled_for','Scheduled'],['amount_cents','Estimate','amount_cents']],calendar:[['title','Job'],['customer_name','Customer'],['scheduled_for','Scheduled']],customers:[['name','Customer'],['phone','Phone'],['email','Email']],quotes:[['customer_name','Customer'],['description','Description'],['amount_cents','Amount','amount_cents'],['follow_up_date','Follow-up']],invoices:[['reference','Invoice'],['customer_name','Customer'],['amount_cents','Amount','amount_cents'],['due_date','Due']],packages:[['title','Package'],['description','Details'],['price_cents','Price','price_cents']],campaigns:[['title','Campaign'],['channel','Channel'],['start_date','Start'],['end_date','End'],['tracked_leads','Tracked leads'],['tracked_estimated_value_cents','Attributed estimates','tracked_estimated_value_cents']],offers:[['title','Offer'],['code','Code'],['discount_text','Terms'],['ends_on','Ends'],['redemptions','Redemptions']]}[k]||[]}
function statusButtons(k,x){let options={jobs:['new','quoted','booked','in_progress','completed','lost'],calendar:['new','quoted','booked','in_progress','completed','lost'],quotes:['draft','sent','accepted','rejected'],invoices:['draft','sent','paid','overdue','cancelled'],packages:['active','paused'],campaigns:['draft','active','paused','completed'],offers:['active','paused','expired']}[k];if(!options)return '';return '<select aria-label="Update status" onchange="setStatus('+JSON.stringify(k)+','+x.id+',this.value)">'+options.map(v=>'<option '+(x.status===v?'selected':'')+'>'+v+'</option>').join('')+'</select>'}
async function setStatus(k,id,status){try{await api('/api/business-tools/'+k+'/'+id,{method:'POST',body:JSON.stringify({status})});await refresh();renderStats();renderPanel()}catch(e){message(e.message,'error')}}
async function refresh(){data=await api('/api/business-tools/data');renderStats();renderTabs()}
init();
</script></body></html>'''

def init_schema(connection):
    connection.executescript(SCHEMA)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(sv_business_jobs)")}
    if "lead_source" not in columns:
        connection.execute("ALTER TABLE sv_business_jobs ADD COLUMN lead_source TEXT DEFAULT ''")

def _json(handler, payload, status=200):
    handler.sendj(payload, status)

def _business(connection, user_id, app):
    row = connection.execute(
        "SELECT id,name,plan,subscription_expires_at FROM businesses "
        "WHERE user_id=? AND status='active' AND payment_status='verified' "
        "AND plan IN ('plus','spotlight') ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    expiry = row["subscription_expires_at"]
    if expiry and expiry <= app.now():
        return None
    return dict(row)

def _access(handler, connection, app, entity):
    user = handler.require("provider")
    business = _business(connection, user["id"], app)
    if not business:
        raise PermissionError("Business tools require an active, PayFast-verified Business Plus or Business Spotlight subscription.")
    from subscription_entitlements import has_feature
    feature = TABLES[entity][1]
    if not has_feature(business["plan"], feature):
        raise SubscriptionAccessError("This tool is not included in your current subscription. Upgrade to Business Spotlight to unlock it.")
    return user, business

def _data(connection, business_id, app):
    names = list(TABLES)
    result = {"business": None, "available": [], "jobs": [], "calendar": [], "customers": [], "quotes": [], "invoices": [], "packages": [], "campaigns": [], "offers": [], "campaign_analytics": []}
    for entity in names:
        table, feature = TABLES[entity]
        from subscription_entitlements import has_feature
        if has_feature(app_plan := connection.execute("SELECT plan FROM businesses WHERE id=?", (business_id,)).fetchone()["plan"], feature):
            result["available"].append(entity)
            rows = connection.execute("SELECT * FROM "+table+" WHERE business_id=? ORDER BY id DESC LIMIT 200", (business_id,)).fetchall()
            result[entity] = [dict(r) for r in rows]
    if "campaigns" in result["available"]:
        for campaign in result["campaigns"]:
            row = connection.execute("SELECT count(*) leads, coalesce(sum(amount_cents),0) value_cents FROM sv_business_jobs WHERE business_id=? AND lower(trim(lead_source))=lower(trim(?))", (business_id, campaign["title"])).fetchone()
            campaign["tracked_leads"] = row["leads"]
            campaign["tracked_estimated_value_cents"] = row["value_cents"]
            result["campaign_analytics"].append({"campaign": campaign["title"], "leads": row["leads"], "estimated_value_cents": row["value_cents"]})
    return result

def _profile_page(business):
    name = escape(str(business["name"] or ""))
    category = escape(str(business["category"] or ""))
    area = escape(str(business["area"] or ""))
    description = escape(str(business["description"] or ""))
    phone = escape(str(business["phone"] or ""), quote=True)
    website = str(business["website"] or "").strip()
    safe_website = escape(website, quote=True) if website.startswith(("https://", "http://")) else ""
    link = ('<a class="button" href="' + safe_website + '" target="_blank" rel="noopener noreferrer">Visit website</a>') if safe_website else ""
    phone_link = ('<a class="button" href="tel:' + phone + '">Call business</a>') if phone else ""
    return ('''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#10233f"><title>''' + name + ''' · Skillvaya Spotlight</title><style>
    body{margin:0;background:#f4f7fb;color:#19283b;font:16px/1.6 "Segoe UI",Arial,sans-serif}.top{background:#10233f;color:white;padding:18px 22px}.brand{font-size:23px;font-weight:850}.brand span{color:#75b7ff}.wrap{max-width:900px;margin:32px auto;padding:0 16px}.hero{background:linear-gradient(125deg,#10233f,#1c4b83);color:white;border-radius:20px;padding:clamp(22px,5vw,48px);box-shadow:0 14px 36px #10233f20}.badge{display:inline-block;background:#d9ebff;color:#174c91;border-radius:99px;padding:5px 11px;font-size:12px;font-weight:800}.hero h1{font-size:clamp(30px,5vw,46px);line-height:1.1;margin:15px 0 6px}.hero p{color:#e1edfb}.card{background:white;border:1px solid #e1e8f1;border-radius:16px;padding:22px;margin-top:16px}.button{display:inline-block;text-decoration:none;background:#2365d8;color:white;padding:10px 15px;border-radius:9px;font-weight:700;margin:5px 7px 0 0}.secondary{background:#eaf0f8;color:#10233f}</style></head><body><header class="top"><div class="brand">skill<span>vaya</span> · Spotlight</div></header><main class="wrap"><section class="hero"><span class="badge">BUSINESS SPOTLIGHT</span><h1>''' + name + '''</h1><p>''' + category + ''' · ''' + area + '''</p><p>''' + description + '''</p><div>''' + phone_link + link + '''</div></section><section class="card"><h2>Contact this provider</h2><p>Skillvaya helps customers discover providers. Confirm the scope, price, timing and terms directly with the business before work begins.</p><a class="button secondary" href="/customer">Back to Skillvaya marketplace</a></section></main></body></html>''')

def handle_get(handler, path, app):
    if path.startswith("/business-profile/"):
        try:
            business_id = int(path.rsplit("/", 1)[1])
        except ValueError:
            handler.send_error(404)
            return True
        with app.conn() as connection:
            row = connection.execute("SELECT * FROM businesses WHERE id=? AND status='active' AND payment_status='verified' AND plan='spotlight'", (business_id,)).fetchone()
        if not row or (row["subscription_expires_at"] and row["subscription_expires_at"] <= app.now()):
            handler.send_error(404)
            return True
        body = _profile_page(dict(row)).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    if path == "/business-tools":
        body = PAGE.encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    if path != "/api/business-tools/data":
        return False
    user = handler.require("provider")
    with app.conn() as connection:
        business = _business(connection, user["id"], app)
        if not business:
            _json(handler, {"error": "Business tools require an active, PayFast-verified Business Plus or Business Spotlight subscription."}, 403)
            return True
        result = _data(connection, business["id"], app)
        result["business"] = {"id": business["id"], "name": business["name"], "plan": business["plan"], "plan_name": app.PLANS[business["plan"]]["name"]}
    _json(handler, result)
    return True

def handle_post(handler, path, payload, app):
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[:2] != ["api", "business-tools"]:
        return False
    entity = parts[2]
    if entity not in TABLES:
        _json(handler, {"error": "Unknown business tool."}, 404)
        return True
    user = handler.require("provider")
    with app.conn() as connection:
        _, business = _access(handler, connection, app, entity)
        table = TABLES[entity][0]
        stamp = app.now()
        if len(parts) == 4:
            try:
                record_id = int(parts[3])
            except ValueError:
                _json(handler, {"error": "Invalid record ID."}, 400)
                return True
            options = {
                "jobs": {"new", "quoted", "booked", "in_progress", "completed", "lost"},
                "calendar": {"new", "quoted", "booked", "in_progress", "completed", "lost"},
                "quotes": {"draft", "sent", "accepted", "rejected"},
                "invoices": {"draft", "sent", "paid", "overdue", "cancelled"},
                "packages": {"active", "paused"},
                "campaigns": {"draft", "active", "paused", "completed"},
                "offers": {"active", "paused", "expired"},
            }
            if entity not in options:
                _json(handler, {"error": "This record does not support status changes."}, 400)
                return True
            status = str(payload.get("status", "")).strip().lower()
            if status not in options[entity]:
                _json(handler, {"error": "Choose a valid status."}, 400)
                return True
            cur = connection.execute("UPDATE "+table+" SET status=?"+(",updated_at=?" if entity in ("jobs","calendar","quotes","invoices","campaigns") else "")+" WHERE id=? AND business_id=?",
                (status, stamp, record_id, business["id"]) if entity in ("jobs","calendar","quotes","invoices","campaigns") else (status, record_id, business["id"]))
            if not cur.rowcount:
                _json(handler, {"error": "Record not found."}, 404)
                return True
            _json(handler, {"ok": True, "status": status})
            return True
        if entity == "calendar":
            _json(handler, {"error": "Create and reschedule bookings from the Jobs & leads tab."}, 400); return True
        if entity == "jobs":
            title = str(payload.get("title", "")).strip()[:180]
            customer = str(payload.get("customer_name", "")).strip()[:160]
            if not title or not customer:
                _json(handler, {"error": "Job title and customer name are required."}, 400); return True
            amount = _cents(payload.get("amount", 0))
            if amount < 0:
                _json(handler, {"error": "Estimated amount must be zero or greater."}, 400); return True
            cur = connection.execute("INSERT INTO "+table+"(business_id,title,customer_name,customer_contact,lead_source,status,scheduled_for,amount_cents,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(business["id"],title,customer,str(payload.get("customer_contact","")).strip()[:160],str(payload.get("lead_source","")).strip()[:160],"new",str(payload.get("scheduled_for",""))[:20],amount,str(payload.get("notes","")).strip()[:2000],stamp,stamp))
        elif entity == "customers":
            name = str(payload.get("name","")).strip()[:160]
            if not name: _json(handler, {"error":"Customer name is required."},400); return True
            cur = connection.execute("INSERT INTO "+table+"(business_id,name,phone,email,notes,created_at) VALUES(?,?,?,?,?,?)",(business["id"],name,str(payload.get("phone","")).strip()[:60],str(payload.get("email","")).strip()[:254],str(payload.get("notes","")).strip()[:2000],stamp))
        elif entity == "quotes":
            customer=str(payload.get("customer_name","")).strip()[:160]; desc=str(payload.get("description","")).strip()[:3000]
            if not customer or not desc: _json(handler,{"error":"Customer and work description are required."},400); return True
            amount=_cents(payload.get("amount"))
            if amount <= 0: _json(handler,{"error":"Quote amount must be greater than zero."},400); return True
            cur=connection.execute("INSERT INTO "+table+"(business_id,customer_name,description,amount_cents,status,follow_up_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(business["id"],customer,desc,amount,"draft",str(payload.get("follow_up_date",""))[:20],stamp,stamp))
        elif entity == "invoices":
            customer=str(payload.get("customer_name","")).strip()[:160]; ref=str(payload.get("reference","")).strip()[:80]; amount=_cents(payload.get("amount"))
            if not customer or not ref or amount <= 0: _json(handler,{"error":"Customer, invoice reference and a positive amount are required."},400); return True
            try: cur=connection.execute("INSERT INTO "+table+"(business_id,customer_name,reference,amount_cents,status,due_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(business["id"],customer,ref,amount,"draft",str(payload.get("due_date",""))[:20],stamp,stamp))
            except app.sqlite3.IntegrityError: _json(handler,{"error":"That invoice reference already exists for this business."},409); return True
        elif entity == "packages":
            title=str(payload.get("title","")).strip()[:160]; desc=str(payload.get("description","")).strip()[:2000]; price=_cents(payload.get("price"))
            if not title or price < 0: _json(handler,{"error":"Package name and a non-negative price are required."},400); return True
            cur=connection.execute("INSERT INTO "+table+"(business_id,title,description,price_cents,status,created_at) VALUES(?,?,?,?,?,?)",(business["id"],title,desc,price,"active",stamp))
        elif entity == "campaigns":
            title=str(payload.get("title","")).strip()[:160]
            if not title: _json(handler,{"error":"Campaign name is required."},400); return True
            cur=connection.execute("INSERT INTO "+table+"(business_id,title,channel,description,start_date,end_date,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(business["id"],title,str(payload.get("channel","Skillvaya"))[:80],str(payload.get("description","")).strip()[:2000],str(payload.get("start_date",""))[:20],str(payload.get("end_date",""))[:20],"draft",stamp,stamp))
        else:
            title=str(payload.get("title","")).strip()[:160]; code=str(payload.get("code","")).strip().upper()[:40]; discount=str(payload.get("discount_text","")).strip()[:200]
            if not title or not code or not discount: _json(handler,{"error":"Offer title, voucher code and discount terms are required."},400); return True
            limit=max(0,min(1000000,int(payload.get("redemption_limit") or 0)))
            try: cur=connection.execute("INSERT INTO "+table+"(business_id,title,code,discount_text,starts_on,ends_on,redemption_limit,redemptions,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(business["id"],title,code,discount,str(payload.get("starts_on",""))[:20],str(payload.get("ends_on",""))[:20],limit,0,"active",stamp))
            except app.sqlite3.IntegrityError: _json(handler,{"error":"That voucher code already exists for this business."},409); return True
        _json(handler, {"ok": True, "id": cur.lastrowid}, 201)
    return True

def _cents(value):
    try:
        number = float(value)
        if number < 0 or number != number or number == float("inf") or number == float("-inf"):
            return -1
        return int(round(number * 100))
    except (TypeError, ValueError, OverflowError):
        return -1
