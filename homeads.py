"""Skillvaya homepage ads (SV92).

Businesses buy a week or a month in the homepage ad block (the slot that used to say
"Future Chat coming soon"). Payment is a Google Play one-time product, verified on the
server; the owner approves every ad before it shows, and the run starts on approval.
Every ad is labelled "Sponsored".
"""
import base64, collections, datetime, hashlib, json, os, re, threading, time

A = None

PLANS = {
    # product id: (tier, days, price in cents, label)
    "skillvaya_ad_word_week": ("word", 7, 14900, "Word or photo ad · 1 week"),
    "skillvaya_ad_word_month": ("word", 30, 49900, "Word or photo ad · 1 month"),
    "skillvaya_ad_video_week": ("video", 7, 24900, "Video ad · 1 week"),
    "skillvaya_ad_video_month": ("video", 30, 79900, "Video ad · 1 month"),
}
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
MAX_PHOTO = 2 * 1024 * 1024
MAX_VIDEO = 12 * 1024 * 1024
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "homeads")


def bind(ns):
    global A
    class _A: pass
    A = _A()
    for k, v in ns.items():
        setattr(A, k, v)


def init(c):
    pk = A.WF_ID_TYPE + " PRIMARY KEY" + ("" if A.DATABASE_URL else " AUTOINCREMENT")
    A.execute_script(c, """
        CREATE TABLE IF NOT EXISTS home_ads(id %(pk)s, user_id BIGINT NOT NULL, kind TEXT NOT NULL DEFAULT 'word',
            headline TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '', cta TEXT NOT NULL DEFAULT '', target TEXT NOT NULL DEFAULT '',
            advertiser TEXT NOT NULL DEFAULT '', media_mime TEXT NOT NULL DEFAULT '', media_b64 TEXT NOT NULL DEFAULT '',
            product_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft', purchase_token TEXT NOT NULL DEFAULT '',
            order_id TEXT NOT NULL DEFAULT '', paid_at TEXT NOT NULL DEFAULT '', starts_at TEXT NOT NULL DEFAULT '', ends_at TEXT NOT NULL DEFAULT '',
            views BIGINT NOT NULL DEFAULT 0, clicks BIGINT NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_home_ads_status ON home_ads(status, ends_at);
        CREATE INDEX IF NOT EXISTS idx_home_ads_user ON home_ads(user_id);
    """ % {"pk": pk})


def _now_dt():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _expire(c):
    c.execute("UPDATE home_ads SET status='expired',updated_at=? WHERE status='active' AND ends_at<>'' AND ends_at<?", (A.now(), _iso(_now_dt())))


def _public(r, with_owner=False):
    d = {"id": int(r["id"]), "kind": r["kind"], "headline": r["headline"], "body": r["body"], "cta": r["cta"],
         "target": r["target"], "advertiser": r["advertiser"], "mime": r["media_mime"],
         "media": ("/api/home-ads/media/%d?v=%s" % (int(r["id"]), hashlib.sha1((r["updated_at"] or "").encode()).hexdigest()[:8])) if r["media_mime"] else ""}
    if with_owner:
        plan = PLANS.get(r["product_id"] or "")
        d.update({"status": r["status"], "product_id": r["product_id"], "plan": plan[3] if plan else "", "price": ("R%d" % (plan[2] // 100)) if plan else "",
                  "views": int(r["views"] or 0), "clicks": int(r["clicks"] or 0), "starts_at": r["starts_at"], "ends_at": r["ends_at"],
                  "paid_at": r["paid_at"], "order_id": r["order_id"], "note": r["note"], "created_at": r["created_at"], "user_id": int(r["user_id"])})
    return d


COLS = "id,user_id,kind,headline,body,cta,target,advertiser,media_mime,product_id,status,order_id,paid_at,starts_at,ends_at,views,clicks,note,created_at,updated_at"

# Small in-memory cache so popular ad media is not decoded from the database on every view.
_MEDIA = collections.OrderedDict()
_MEDIA_LOCK = threading.Lock()
_MEDIA_MAX = 40 * 1024 * 1024


def _media_bytes(ad_id, version):
    key = (ad_id, version)
    with _MEDIA_LOCK:
        if key in _MEDIA:
            _MEDIA.move_to_end(key); return _MEDIA[key]
    with A.conn() as c:
        r = c.execute("SELECT media_mime,media_b64,status FROM home_ads WHERE id=?", (ad_id,)).fetchone()
    if not r or not r["media_b64"]: return None
    item = (r["media_mime"], base64.b64decode(r["media_b64"]), r["status"])
    with _MEDIA_LOCK:
        _MEDIA[key] = item
        while sum(len(v[1]) for v in _MEDIA.values()) > _MEDIA_MAX and len(_MEDIA) > 1: _MEDIA.popitem(last=False)
    return item


def serve_static(h, path):
    name = path.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[a-z0-9_\-]+\.(js|css)", name): return h.sendj({"error": "Not found"}, 404)
    fp = os.path.join(STATIC, name)
    if not os.path.isfile(fp): return h.sendj({"error": "Not found"}, 404)
    with open(fp, "rb") as f: data = f.read()
    h.send_response(200)
    h.send_header("Content-Type", "application/javascript; charset=utf-8" if name.endswith(".js") else "text/css; charset=utf-8")
    h.send_header("Cache-Control", "public, max-age=300")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers(); h.wfile.write(data)


def _optional_user(h):
    try: return h.require()
    except Exception: return None


# ---------------------------------------------------------------- GET
def handle_get(h, path):
    q = A.urllib.parse.parse_qs(A.urlparse(h.path).query)
    if path == "/api/home-ads/live":
        with A.conn() as c:
            _expire(c)
            rows = c.execute("SELECT " + COLS + " FROM home_ads WHERE status='active' ORDER BY starts_at DESC LIMIT 30").fetchall()
        body = json.dumps({"items": [_public(r) for r in rows]}).encode()
        h.send_response(200); h.send_header("Content-Type", "application/json"); h.send_header("Cache-Control", "public, max-age=60")
        h.send_header("Content-Length", str(len(body))); h.end_headers(); h.wfile.write(body); return
    if path.startswith("/api/home-ads/media/"):
        try: ad_id = int(path.rsplit("/", 1)[1])
        except ValueError: return h.sendj({"error": "Not found"}, 404)
        item = _media_bytes(ad_id, (q.get("v", [""])[0])[:12])
        if not item: return h.sendj({"error": "Not found"}, 404)
        mime, data, status = item
        if status not in ("active", "pending_review", "approved", "paused", "expired", "draft", "pending_payment"): return h.sendj({"error": "Not found"}, 404)
        total = len(data); start, end = 0, total - 1
        rng = h.headers.get("Range", "")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1): start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else total - 1
            else: start = max(0, total - int(m.group(2)))
            end = min(end, total - 1)
            if start > end: h.send_response(416); h.send_header("Content-Range", "bytes */%d" % total); h.end_headers(); return
            h.send_response(206); h.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, total))
        else:
            h.send_response(200)
        chunk = data[start:end + 1]
        h.send_header("Content-Type", mime); h.send_header("Accept-Ranges", "bytes")
        h.send_header("Cache-Control", "public, max-age=86400"); h.send_header("Content-Length", str(len(chunk)))
        h.end_headers(); h.wfile.write(chunk); return
    if path == "/api/home-ads/mine":
        u = h.require()
        with A.conn() as c:
            _expire(c)
            rows = c.execute("SELECT " + COLS + " FROM home_ads WHERE user_id=? AND status<>'deleted' ORDER BY id DESC LIMIT 50", (int(u["id"]),)).fetchall()
            biz = c.execute("SELECT id,name FROM businesses WHERE user_id=? ORDER BY id DESC LIMIT 1", (int(u["id"]),)).fetchone()
        return h.sendj({"items": [_public(r, True) for r in rows], "plans": _plans(),
                        "me": {"id": int(u["id"]), "name": u.get("name") or "", "role": u.get("role"), "business_id": int(biz["id"]) if biz else 0,
                               "business_name": biz["name"] if biz else ""}})
    if path == "/api/admin/home-ads":
        u = h.require()
        if u.get("role") != "admin": return h.sendj({"error": "Owner only."}, 403)
        with A.conn() as c:
            _expire(c)
            rows = c.execute("SELECT a." + COLS.replace(",", ",a.") + ",u.name owner_name,u.email owner_email FROM home_ads a LEFT JOIN users u ON u.id=a.user_id WHERE a.status NOT IN ('draft','deleted','pending_payment') ORDER BY CASE a.status WHEN 'pending_review' THEN 0 WHEN 'active' THEN 1 ELSE 2 END, a.id DESC LIMIT 200").fetchall()
        out = []
        for r in rows:
            d = _public(r, True); d["owner_name"] = r["owner_name"] or ""; d["owner_email"] = r["owner_email"] or ""; out.append(d)
        return h.sendj({"items": out, "pending": sum(1 for x in out if x["status"] == "pending_review")})
    return h.sendj({"error": "Not found"}, 404)


def _plans():
    return [{"product_id": k, "tier": v[0], "days": v[1], "price": "R%d" % (v[2] // 100), "label": v[3]} for k, v in PLANS.items()]


def _clean_target(t):
    t = str(t or "").strip()[:300]
    if not t: return ""
    if re.fullmatch(r"provider:\d+", t): return t
    if re.fullmatch(r"tel:\+?[\d ]{6,20}", t): return t.replace(" ", "")
    if re.fullmatch(r"\+?[\d ()-]{8,20}", t): return "tel:" + re.sub(r"[^\d+]", "", t)
    if not re.match(r"https?://", t, re.I): t = "https://" + t
    if not re.fullmatch(r"https?://[^\s<>\"']+\.[^\s<>\"']+", t, re.I): raise ValueError("Enter a valid website link.")
    return t


def _account_hash(uid):
    d = hashlib.sha256(str(uid).encode()).digest()
    return base64.urlsafe_b64encode(d).decode().rstrip("=")[:64]


def _publisher():
    raw = A._google_play_credentials_json().strip() if hasattr(A, "_google_play_credentials_json") else ""
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not raw and not path: return None
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    scopes = ["https://www.googleapis.com/auth/androidpublisher"]
    creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=scopes) if raw else service_account.Credentials.from_service_account_file(path, scopes=scopes)
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


def _notify(uid, title, body):
    send = getattr(A, "fcm_send_to_user", None)
    if not send: return
    threading.Thread(target=lambda: send(int(uid), title, body, {"type": "home_ad", "url": "/customer-app"}), daemon=True).start()


def _notify_owners(title, body):
    try:
        with A.conn() as c:
            ids = [int(r["id"]) for r in c.execute("SELECT id FROM users WHERE role='admin'").fetchall()]
        for i in ids: _notify(i, title, body)
    except Exception: pass


# ---------------------------------------------------------------- POST
def handle_post(h, path, d):
    if path == "/api/home-ads/event":
        try: ad_id = int(d.get("id") or 0)
        except (TypeError, ValueError): ad_id = 0
        col = "clicks" if d.get("ev") == "click" else "views"
        with A.conn() as c:
            c.execute("UPDATE home_ads SET " + col + "=" + col + "+1 WHERE id=? AND status='active'", (ad_id,))
        return h.sendj({"ok": True})
    u = h.require()
    uid = int(u["id"])
    stamp = A.now()
    if path == "/api/home-ads/create":
        kind = d.get("kind") if d.get("kind") in ("word", "photo", "video") else "word"
        headline = str(d.get("headline") or "").strip()[:60]
        body = str(d.get("body") or "").strip()[:180]
        cta = str(d.get("cta") or "Learn more").strip()[:24]
        advertiser = str(d.get("advertiser") or u.get("name") or "").strip()[:60]
        product_id = str(d.get("product_id") or "")
        if product_id not in PLANS: return h.sendj({"error": "Choose 1 week or 1 month."}, 400)
        if (PLANS[product_id][0] == "video") != (kind == "video"): return h.sendj({"error": "Video ads use the video price; word and photo ads use the standard price."}, 400)
        if len(headline) < 3: return h.sendj({"error": "Add a short headline (at least 3 characters)."}, 400)
        try: target = _clean_target(d.get("target"))
        except ValueError as e: return h.sendj({"error": str(e)}, 400)
        mime, b64 = "", ""
        if kind in ("photo", "video"):
            m = d.get("media") or {}
            mime = str(m.get("mime") or "").lower()
            b64 = str(m.get("data_base64") or "")
            if "," in b64[:80]: b64 = b64.split(",", 1)[1]
            try: raw = base64.b64decode(b64, validate=False)
            except Exception: return h.sendj({"error": "The file could not be read."}, 400)
            if kind == "photo" and (mime not in PHOTO_TYPES or len(raw) > MAX_PHOTO): return h.sendj({"error": "Use a JPG, PNG or WebP photo up to 2 MB."}, 400)
            if kind == "video" and (mime not in VIDEO_TYPES or len(raw) > MAX_VIDEO): return h.sendj({"error": "Use an MP4 or WebM video up to 12 MB (about 30 seconds)."}, 400)
            if not raw: return h.sendj({"error": "Add your " + kind + "."}, 400)
            b64 = base64.b64encode(raw).decode()
        owner = u.get("role") == "admin"
        status = "pending_review" if owner else "pending_payment"
        with A.conn() as c:
            c.execute("DELETE FROM home_ads WHERE user_id=? AND status='pending_payment' AND created_at<?", (uid, _iso(_now_dt() - datetime.timedelta(days=2))))
            ad_id = c.execute("INSERT INTO home_ads(user_id,kind,headline,body,cta,target,advertiser,media_mime,media_b64,product_id,status,paid_at,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                              (uid, kind, headline, body, cta, target, advertiser, mime, b64, product_id, status, stamp if owner else "", "Owner ad (free)" if owner else "", stamp, stamp)).fetchone()["id"]
        if owner: return _approve(h, u, int(ad_id))
        return h.sendj({"ok": True, "id": int(ad_id), "product_id": product_id, "obfuscated_profile": "ad-%d" % int(ad_id)})
    if path == "/api/home-ads/delete":
        try: ad_id = int(d.get("id") or 0)
        except (TypeError, ValueError): ad_id = 0
        with A.conn() as c:
            c.execute("UPDATE home_ads SET status='deleted',media_b64='',updated_at=? WHERE id=? AND user_id=? AND status IN ('draft','pending_payment','rejected','expired')", (stamp, ad_id, uid))
        return h.sendj({"ok": True})
    if path == "/api/home-ads/verify":
        token = str(d.get("purchase_token") or "").strip()
        product_id = str(d.get("product_id") or "").strip()
        if not token or len(token) > 4096 or product_id not in PLANS: return h.sendj({"error": "A valid Google Play ad purchase is required."}, 400)
        with A.conn() as c:
            done = c.execute("SELECT id,status FROM home_ads WHERE purchase_token=? LIMIT 1", (token,)).fetchone()
        if done: return h.sendj({"ok": True, "id": int(done["id"]), "status": done["status"], "message": "Payment received. Your ad is waiting for approval."})
        try:
            pub = _publisher()
            if pub is None: return h.sendj({"error": "Google Play has your payment, but Skillvaya couldn't confirm it yet. Reopen Advertise here and it will retry automatically, or contact Skillvaya."}, 503)
            pkg = os.environ.get("GOOGLE_PLAY_PACKAGE_NAME", "za.co.skillvaya.app").strip()
            v = pub.purchases().products().get(packageName=pkg, productId=product_id, token=token).execute()
        except Exception:
            return h.sendj({"error": "Google Play could not confirm this payment yet. Keep the app open; it will retry."}, 503)
        if int(v.get("purchaseState", 1)) != 0: return h.sendj({"error": "This Google Play payment is not complete yet."}, 409)
        acct = str(v.get("obfuscatedExternalAccountId") or "")
        if acct and acct != _account_hash(uid): return h.sendj({"error": "This payment belongs to a different Skillvaya account."}, 403)
        prof = str(v.get("obfuscatedExternalProfileId") or "")
        try: ad_id = int(prof.split("-", 1)[1]) if prof.startswith("ad-") else int(d.get("ad_id") or 0)
        except (TypeError, ValueError): ad_id = 0
        with A.conn() as c:
            ad = c.execute("SELECT id,status,user_id,headline FROM home_ads WHERE id=? AND user_id=?", (ad_id, uid)).fetchone()
            if not ad: return h.sendj({"error": "The ad for this payment was not found. Contact Skillvaya with order " + str(v.get("orderId") or "") + "."}, 404)
            c.execute("UPDATE home_ads SET status='pending_review',product_id=?,purchase_token=?,order_id=?,paid_at=?,updated_at=? WHERE id=? AND status IN ('pending_payment','draft')",
                      (product_id, token, str(v.get("orderId") or d.get("order_id") or ""), stamp, stamp, ad_id))
        _notify_owners("New homepage ad to approve", (ad["headline"] or "An ad") + " is paid and waiting for your approval.")
        return h.sendj({"ok": True, "id": ad_id, "status": "pending_review", "consume": True,
                        "message": "Payment received. Your ad will go live as soon as Skillvaya approves it (usually within a day). Your week or month starts when it goes live."})
    if path == "/api/admin/home-ads":
        if u.get("role") != "admin": return h.sendj({"error": "Owner only."}, 403)
        try: ad_id = int(d.get("id") or 0)
        except (TypeError, ValueError): ad_id = 0
        action = d.get("action")
        if action == "approve": return _approve(h, u, ad_id)
        with A.conn() as c:
            ad = c.execute("SELECT * FROM home_ads WHERE id=?", (ad_id,)).fetchone()
            if not ad: return h.sendj({"error": "Ad not found."}, 404)
            if action == "reject":
                reason = str(d.get("reason") or "It doesn't meet the Skillvaya advertising rules.")[:300]
                c.execute("UPDATE home_ads SET status='rejected',note=?,updated_at=? WHERE id=?", (reason, stamp, ad_id))
            elif action == "pause":
                c.execute("UPDATE home_ads SET status='paused',updated_at=? WHERE id=? AND status='active'", (stamp, ad_id))
            elif action == "resume":
                c.execute("UPDATE home_ads SET status='active',updated_at=? WHERE id=? AND status='paused'", (stamp, ad_id))
            else:
                return h.sendj({"error": "Unknown action."}, 400)
        refund = ""
        if action == "reject" and ad["order_id"]:
            try:
                pub = _publisher()
                pkg = os.environ.get("GOOGLE_PLAY_PACKAGE_NAME", "za.co.skillvaya.app").strip()
                pub.orders().refund(packageName=pkg, orderId=ad["order_id"]).execute()
                refund = "refunded"
            except Exception:
                refund = "refund_failed"
            with A.conn() as c:
                c.execute("UPDATE home_ads SET note=note||? WHERE id=?", (" · Refund: " + ("done" if refund == "refunded" else "please refund order " + ad["order_id"] + " in Play Console"), ad_id))
        if action == "reject":
            _notify(ad["user_id"], "Homepage ad not approved", "Your ad wasn't approved: " + str(d.get("reason") or "it doesn't meet the advertising rules") + (". Your payment has been refunded." if refund == "refunded" else ". Your payment will be refunded."))
        return h.sendj({"ok": True, "refund": refund})
    return h.sendj({"error": "Not found"}, 404)


def _approve(h, u, ad_id):
    start = _now_dt()
    with A.conn() as c:
        ad = c.execute("SELECT id,user_id,product_id,status,headline FROM home_ads WHERE id=?", (ad_id,)).fetchone()
        if not ad: return h.sendj({"error": "Ad not found."}, 404)
        if ad["status"] not in ("pending_review", "paused"): return h.sendj({"error": "Only paid ads waiting for approval can be approved."}, 409)
        days = PLANS.get(ad["product_id"], ("", 7))[1]
        c.execute("UPDATE home_ads SET status='active',starts_at=?,ends_at=?,updated_at=? WHERE id=?",
                  (_iso(start), _iso(start + datetime.timedelta(days=days)), A.now(), ad_id))
    if int(ad["user_id"]) != int(u["id"]):
        _notify(ad["user_id"], "Your ad is live", (ad["headline"] or "Your ad") + " is now showing on the Skillvaya homepage for %d days." % days)
    return h.sendj({"ok": True, "id": ad_id, "status": "active", "days": days})
