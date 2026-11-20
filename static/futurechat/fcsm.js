/* FCSTATUS-01: Future Chat Status - 24-hour statuses from the people you chat with, plus ONE rotating "Sponsored" status
   (approved, paid business ads; each shows ~30 s, or the full length of a video ad). Works in Skillvaya and the Future Chat app. */
(function () {
  'use strict';
  const S = { data: null, loading: false, loadedAt: 0 };
  const tok = () => { try { return localStorage.getItem('skillvaya_token') || localStorage.getItem('sv_token') || ''; } catch (_) { return ''; } };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  async function api(path, body) {
    const t = tok();
    const r = await fetch(path, { method: body ? 'POST' : 'GET', cache: 'no-store', credentials: 'same-origin', headers: Object.assign({ 'Content-Type': 'application/json' }, t ? { Authorization: 'Bearer ' + t } : {}), body: body ? JSON.stringify(body) : undefined });
    let d = {}; try { d = await r.json(); } catch (_) {}
    if (!r.ok) throw new Error(d.error || 'Something went wrong. Please try again.');
    return d;
  }
  function toast(t) { const n = document.createElement('div'); n.className = 'fc-toast'; n.textContent = t; document.body.appendChild(n); setTimeout(() => n.remove(), 2600); }
  const ago = iso => { const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000)); return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : Math.round(m / 60) + ' h ago'; };
  const initials = n => String(n || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0] || '').join('').toUpperCase() || '?';
  const hue = s => { let h = 0; for (const ch of String(s)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return h % 360; };

  const css = document.createElement('style');
  css.textContent = [
    '#fcStatusStrip{display:flex;gap:14px;overflow-x:auto;padding:10px 4px 4px;scrollbar-width:none;-webkit-overflow-scrolling:touch}',
    '#fcStatusStrip::-webkit-scrollbar{display:none}','#fcStatusStrip .fcs-ring.so{background:conic-gradient(#f43f5e,#f59e0b,#ec4899,#f43f5e)!important}',
    '#fcStatusStrip .fcs-it{display:block!important;flex:none!important;width:66px!important;height:auto!important;min-height:0!important;border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;padding:0!important;margin:0!important;color:#dbe9f7!important;font:inherit;text-align:center;cursor:pointer}',
    '#fcStatusStrip .fcs-ring{display:block!important;box-sizing:border-box;position:relative;width:60px!important;height:60px!important;margin:0 auto;border-radius:50%;padding:3px;background:conic-gradient(#5fd3e6,#8ab8ff,#5fd3e6)}',
    '#fcStatusStrip .fcs-av{box-sizing:border-box}#fcStatusStrip .fcs-nm{display:block!important;color:#dbe9f7!important;font-size:11.5px!important;line-height:1.3!important;max-width:66px}',
    '#fcStatusStrip .fcs-ring.seen{background:rgba(255,255,255,.28)}#fcStatusStrip .fcs-ring.none{background:transparent;border:2px dashed rgba(255,255,255,.35);padding:1px}',
    '#fcStatusStrip .fcs-ring.ad{background:conic-gradient(#ffcf5c,#ff8a5c,#ffcf5c)}',
    '.fcs-av{width:100%;height:100%;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:18px;color:#fff;border:2px solid #0b2447;overflow:hidden;background-size:cover;background-position:center}',
    '.fcs-plus{position:absolute;right:-2px;bottom:-2px;width:22px;height:22px;border-radius:50%;background:#5fd3e6;color:#06233f;font-weight:900;display:grid;place-items:center;border:2px solid #0b2447;font-size:15px;line-height:1}',
    '.fcs-nm{display:block;margin-top:5px;font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '#fcsView{position:fixed;inset:0;z-index:13000;background:#000;color:#fff;display:flex;flex-direction:column;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;user-select:none}',
    '#fcsView .bars{display:flex;gap:4px;padding:max(10px,env(safe-area-inset-top)) 10px 6px}',
    '#fcsView .bar{flex:1;height:3px;border-radius:2px;background:rgba(255,255,255,.3);overflow:hidden}#fcsView .bar i{display:block;height:100%;width:0;background:#fff}',
    '#fcsView .top{display:flex;align-items:center;gap:10px;padding:4px 12px 8px}#fcsView .top b{font-size:15px}#fcsView .top small{display:block;color:#c9d6e3;font-size:12px}',
    '#fcsView .top .sp{margin-left:auto;display:flex;gap:6px}#fcsView .top button{border:0;background:rgba(255,255,255,.14);color:#fff;border-radius:999px;padding:8px 12px;font-size:14px}',
    '#fcsView .stage{position:relative;flex:1;display:grid;place-items:center;overflow:hidden}',
    '#fcsView .stage img,#fcsView .stage video{max-width:100%;max-height:100%;object-fit:contain}',
    '#fcsView .txt{width:100%;height:100%;display:grid;place-items:center;padding:28px;font-size:26px;font-weight:700;line-height:1.35;text-align:center;white-space:pre-wrap;word-break:break-word}',
    '#fcsView .cap{position:absolute;left:0;right:0;bottom:0;padding:14px 16px 18px;background:linear-gradient(transparent,rgba(0,0,0,.75));font-size:16px;line-height:1.4;white-space:pre-wrap}',
    '#fcsView .tapL,#fcsView .tapR{position:absolute;top:0;bottom:0;width:35%;z-index:2}#fcsView .tapL{left:0}#fcsView .tapR{right:0}',
    '#fcsView .foot{padding:10px 14px max(14px,env(safe-area-inset-bottom));display:flex;gap:10px;align-items:center;justify-content:center;min-height:54px}',
    '#fcsView .seenbtn{border:0;background:rgba(255,255,255,.16);color:#fff;border-radius:999px;padding:10px 18px;font-size:15px;font-weight:700}',
    '#fcsView .seenlist{position:absolute;left:0;right:0;bottom:0;max-height:62%;z-index:5;background:#101c2c;border-radius:20px 20px 0 0;display:flex;flex-direction:column;box-shadow:0 -10px 30px rgba(0,0,0,.5)}',
    '#fcsView .seenlist .hd{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 8px}#fcsView .seenlist .hd b{font-size:17px}#fcsView .seenlist .hd button{border:0;background:rgba(255,255,255,.14);color:#fff;border-radius:999px;width:36px;height:36px;font-size:16px}',
    '#fcsView .seenlist .bd{overflow-y:auto;padding:4px 12px max(16px,env(safe-area-inset-bottom))}#fcsView .seenlist .row{display:flex;align-items:center;gap:12px;padding:9px 4px;border-bottom:1px solid rgba(255,255,255,.07)}',
    '#fcsView .seenlist .av{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:#1ed6c8;color:#04202b;font-weight:800;flex:none}#fcsView .seenlist .nm{font-size:15px;font-weight:700}#fcsView .seenlist .nm small{display:block;font-weight:400;color:#9cb7cc;font-size:12.5px}#fcsView .seenlist .none{color:#9cb7cc;text-align:center;padding:18px}',
    '#fcsView .cta{border:0;border-radius:14px;padding:13px 22px;font-weight:800;font-size:16px;background:linear-gradient(90deg,#ffcf5c,#ff8a5c);color:#2a1300}',
    '#fcsView .adtag{display:inline-block;background:#ffcf5c;color:#2a1300;font-size:11px;font-weight:800;border-radius:6px;padding:2px 6px;margin-right:6px;vertical-align:1px}',
    '#fcsView .adbox{width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:24px;text-align:center;background:linear-gradient(160deg,#0b2447,#0d6f86)}',
    '#fcsView .adbox h3{margin:0;font-size:26px}#fcsView .adbox p{margin:0;font-size:17px;color:#dbe9f7;line-height:1.45;white-space:pre-wrap}',
    '.fcs-bgs{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.fcs-bgs button{width:30px;height:30px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #c9d6e3}.fcs-bgs button.on{box-shadow:0 0 0 3px #0d6f86}',
    '.fcs-ta{width:100%;box-sizing:border-box;min-height:120px;border-radius:14px;border:0;padding:16px;color:#fff;font-size:20px;font-weight:700;text-align:center;resize:none;outline:none}',
    '.fcs-prev{max-width:100%;max-height:42vh;border-radius:12px;display:block;margin:8px auto}',
    // FCS-LIKE-01 + FCS-SHARE-01
    '#fcsView .foot{flex-wrap:wrap}#fcsView .fcs-act{border:0;background:rgba(255,255,255,.16);color:#fff;border-radius:999px;padding:10px 16px;font-size:15px;font-weight:700}',
    '#fcsView .fcs-act.on{background:rgba(244,63,94,.32)}#fcsView .seenlist .lk{margin-left:auto;font-size:16px}'
  ].join('');
  document.head.appendChild(css);

  // Shown in the Sponsored status when no business advert is running, so the slot is never empty.
  const HOUSE_AD = { id: 0, house: true, advertiser: 'Future Chat', headline: 'Advertise your business here',
    body: 'Your advert can show in the Sponsored status of everyone on Future Chat and Skillvaya. Pay safely through Google Play; every advert is checked before it goes live.',
    cta: 'Advertise with us', target: 'https://skillvaya.onrender.com/customer-app', mime: '', media: '' };
  // ---------- status bar inside the Future Chat chat list header
  async function load(force) {
    if (!tok() || S.loading) return S.data;
    if (!force && S.data && Date.now() - S.loadedAt < 20000) return S.data;
    S.loading = true;
    try { S.data = await api('/api/fc/statuses'); S.loadedAt = Date.now(); } catch (_) {} finally { S.loading = false; }
    return S.data;
  }
  function drawStrip() {
    const hdr = document.querySelector('#fcRoot .fc-hdr'); if (!hdr) return;
    let strip = document.getElementById('fcStatusStrip');
    if (!strip) { strip = document.createElement('div'); strip.id = 'fcStatusStrip'; strip.setAttribute('aria-label', 'Status'); hdr.appendChild(strip); }
    const d = S.data || { mine: [], others: [], sponsored: [], me: {} };
    const me = d.me || {};
    let html = '<button class="fcs-it" data-k="me" aria-label="My status"><span class="fcs-ring ' + (d.mine.length ? 'seen' : 'none') + '"><span class="fcs-av" style="background:hsl(' + hue(me.name) + ',55%,38%)">' + esc(initials(me.name)) + '</span><span class="fcs-plus">+</span></span><span class="fcs-nm">My status</span></button>';
    if (!d.sponsored || !d.sponsored.length) d.sponsored = [HOUSE_AD];
    if (d.shoutouts && d.shoutouts.length) html += '<button class="fcs-it" data-k="so" aria-label="Shout-outs"><span class="fcs-ring so"><span class="fcs-av" style="background:linear-gradient(135deg,#be185d,#f59e0b);font-size:20px">📣</span></span><span class="fcs-nm">Shout-outs</span></button>';
    html += '<button class="fcs-it" data-k="ad" aria-label="Sponsored status"><span class="fcs-ring ad"><span class="fcs-av" style="background:#3a2a00;font-size:12px">AD</span></span><span class="fcs-nm">Sponsored</span></button>';
    (d.others || []).forEach((p, i) => { html += '<button class="fcs-it" data-k="p" data-i="' + i + '" aria-label="' + esc(p.name) + ' status"><span class="fcs-ring ' + (p.unseen ? '' : 'seen') + '"><span class="fcs-av" style="background:hsl(' + hue(p.name) + ',55%,38%)">' + esc(initials(p.name)) + '</span></span><span class="fcs-nm">' + esc(p.name.split(' ')[0]) + '</span></button>'; });
    if (strip.dataset.html !== html) { strip.innerHTML = html; strip.dataset.html = html; }
    strip.querySelectorAll('.fcs-it').forEach(b => b.onclick = () => {
      const k = b.dataset.k;
      if (k === 'me') { if (d.mine.length) openViewer([{ name: 'My status', items: d.mine, mine: true }], 0); else compose(); }
      else if (k === 'ad') openAds(d.sponsored);
      else if (k === 'so') openAds(d.shoutouts);
      else openViewer(d.others.map(p => ({ name: p.name, items: p.items })), Number(b.dataset.i));
    });
    const plus = strip.querySelector('[data-k="me"] .fcs-plus');
    if (plus) plus.onclick = e => { e.stopPropagation(); compose(); };
  }
  async function refresh(force) { await load(force); drawStrip(); }
  // The chat list header is redrawn by Future Chat; put the status bar back whenever it is missing.
  function ensureStrip() { const hdr = document.querySelector('#fcRoot.open .fc-hdr'); if (hdr && hdr.querySelector('.fc-chips') && !document.getElementById('fcStatusStrip')) { drawStrip(); refresh(false); } }
  const mo = new MutationObserver(ensureStrip);
  function watch() { const r = document.getElementById('fcRoot'); if (r) { mo.observe(r, { childList: true }); ensureStrip(); } else setTimeout(watch, 500); }
  watch(); setInterval(ensureStrip, 1000);
  setInterval(() => { if (document.getElementById('fcStatusStrip') && document.visibilityState !== 'hidden') refresh(true); }, 30000);

  // ---------- viewer for people's statuses
  const BLOBS = new Map();
  async function mediaUrl(path) {
    if (BLOBS.has(path)) return BLOBS.get(path);
    const r = await fetch(path, { cache: 'force-cache', credentials: 'same-origin', headers: { Authorization: 'Bearer ' + tok() } });
    if (!r.ok) throw new Error('This status has ended.');
    const u = URL.createObjectURL(await r.blob());
    BLOBS.set(path, u);
    if (BLOBS.size > 40) { const k = BLOBS.keys().next().value; URL.revokeObjectURL(BLOBS.get(k)); BLOBS.delete(k); }
    return u;
  }
  let V = null;
  function closeViewer() { if (!V) return; clearTimeout(V.t); cancelAnimationFrame(V.raf); if (V.el) V.el.remove(); V = null; refresh(true); }
  function openViewer(people, pi) {
    closeViewer();
    const el = document.createElement('div'); el.id = 'fcsView'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', 'Status');
    document.body.appendChild(el);
    V = { el, people, pi, ii: 0, t: 0, raf: 0 };
    const first = people[pi].items.findIndex(x => !x.viewed); V.ii = first > 0 ? first : 0;
    show();
  }
  function show() {
    const p = V.people[V.pi], it = p.items[V.ii];
    V.el.innerHTML = '<div class="bars">' + p.items.map((x, i) => '<div class="bar"><i style="width:' + (i < V.ii ? 100 : 0) + '%"></i></div>').join('') + '</div>' +
      '<div class="top"><div><b>' + esc(p.name) + '</b><small>' + esc(ago(it.at)) + '</small></div><div class="sp">' + (p.mine ? '<button data-a="add">+ Add</button><button data-a="del">Delete</button>' : '') + '<button data-a="x" aria-label="Close">✕</button></div></div>' +
      '<div class="stage"><div class="tapL"></div><div class="tapR"></div>' +
      (it.kind === 'text' ? '<div class="txt" style="background:' + esc(it.bg) + '">' + esc(it.body) + '</div>'
        : it.kind === 'video' ? '<video playsinline autoplay></video>' + (it.body ? '<div class="cap">' + esc(it.body) + '</div>' : '')
        : '<img alt="">' + (it.body ? '<div class="cap">' + esc(it.body) + '</div>' : '')) + '</div>' +
      '<div class="foot">' + (p.mine ? '<button data-a="seen" class="seenbtn">👁 ' + Number(it.views || 0) + (Number(it.views) === 1 ? ' view' : ' views') + (Number(it.likes) ? ' · ❤️ ' + Number(it.likes) : '') + ' ›</button>' : likeHtml(it) + shareHtml) + '</div>';
    V.el.querySelector('[data-a="x"]').onclick = closeViewer;
    const add = V.el.querySelector('[data-a="add"]'); if (add) add.onclick = () => { closeViewer(); compose(); };
    const del = V.el.querySelector('[data-a="del"]'); if (del) del.onclick = async () => { if (!confirm('Delete this status?')) return; try { await api('/api/fc/status/delete', { id: it.id }); toast('Status deleted'); } catch (e) { toast(e.message); } closeViewer(); };
    const seen = V.el.querySelector('[data-a="seen"]'); if (seen) seen.onclick = () => viewers(it);
    const lk = V.el.querySelector('[data-a="like"]'); if (lk) lk.onclick = e => { e.stopPropagation(); doLike('status', it, lk); };
    const shb = V.el.querySelector('[data-a="share"]'); if (shb) shb.onclick = e => { e.stopPropagation(); shareThing(() => statusPayload(p.name, it)); };
    V.el.querySelector('.tapL').onclick = () => step(-1);
    V.el.querySelector('.tapR').onclick = () => step(1);
    if (!p.mine && !it.viewed) { it.viewed = true; api('/api/fc/status/view', { id: it.id }).catch(() => {}); }
    const bar = V.el.querySelectorAll('.bar i')[V.ii];
    const vid = V.el.querySelector('video');
    const pic = V.el.querySelector('.stage img');
    if (it.media && (vid || pic)) {
      // Status media needs the signed-in account, so it is fetched with the account token and shown from memory.
      mediaUrl(it.media).then(u => { if (V && V.el.contains(vid || pic)) (vid || pic).src = u; }).catch(() => { if (vid) vid.onerror && vid.onerror(); });
    }
    const run = ms => { const t0 = performance.now(); const tick = () => { if (!V) return; const f = Math.min(1, (performance.now() - t0) / ms); bar.style.width = (f * 100) + '%'; if (f < 1) V.raf = requestAnimationFrame(tick); }; tick(); V.t = setTimeout(() => step(1), ms); };
    if (vid) { vid.onloadedmetadata = () => run(Math.min(60000, Math.max(3000, (vid.duration || 10) * 1000))); vid.onerror = () => run(4000); }
    else run(it.kind === 'text' ? Math.min(12000, 4000 + it.body.length * 45) : 6000);
  }
  // FCS-VIEWERS-01: who viewed my status. The status pauses while the list is open.
  async function viewers(it) {
    if (!V) return; clearTimeout(V.t); cancelAnimationFrame(V.raf);
    const box = document.createElement('div'); box.className = 'seenlist';
    box.innerHTML = '<div class="hd"><b>Viewed by</b><button data-a="seenx" aria-label="Close">✕</button></div><div class="bd">Loading…</div>';
    V.el.appendChild(box);
    box.querySelector('[data-a="seenx"]').onclick = e => { e.stopPropagation(); box.remove(); if (V) show(); };
    try {
      const d = await api('/api/fc/status/viewers?id=' + encodeURIComponent(it.id));
      const list = d.viewers || [];
      box.querySelector('.bd').innerHTML = list.length ? list.map(v => '<div class="row"><span class="av">' + esc((v.name || '?').trim().charAt(0).toUpperCase()) + '</span><span class="nm">' + esc(v.name) + '<small>' + esc(ago(v.at)) + '</small></span>' + (v.liked ? '<span class="lk" aria-label="Liked">❤️</span>' : '') + '</div>').join('')
        : '<p class="none">Nobody has viewed this status yet.</p>';
    } catch (e) { box.querySelector('.bd').textContent = e.message; }
  }
  function step(dir) {
    if (!V) return; clearTimeout(V.t); cancelAnimationFrame(V.raf);
    const p = V.people[V.pi];
    V.ii += dir;
    if (V.ii < 0) { if (V.pi > 0) { V.pi--; V.ii = V.people[V.pi].items.length - 1; } else V.ii = 0; }
    if (V.ii >= p.items.length) { if (V.pi < V.people.length - 1) { V.pi++; V.ii = 0; } else return closeViewer(); }
    show();
  }

  // ---------- FCS-LIKE-01 + FCS-SHARE-01 (owner 2026-11-20): like and share statuses and Sponsored adverts (Future Chat app)
  const likeHtml = o => '<button class="fcs-act' + (o.liked ? ' on' : '') + '" data-a="like" aria-pressed="' + (o.liked ? 'true' : 'false') + '">' + (o.liked ? '❤️ Liked' : '🤍 Like') + '</button>';
  const shareHtml = '<button class="fcs-act" data-a="share">↗ Share</button>';
  function paintLike(btn, on) { btn.classList.toggle('on', on); btn.textContent = on ? '❤️ Liked' : '🤍 Like'; btn.setAttribute('aria-pressed', on ? 'true' : 'false'); }
  async function doLike(kind, o, btn) {
    const on = !o.liked; o.liked = on; paintLike(btn, on);
    if (on) { try { navigator.vibrate && navigator.vibrate(15); } catch (_) {} }
    try { const d = await api('/api/fc/status/like', { kind, id: o.id, on }); o.likes = Number(d.likes) || 0; }
    catch (e) { o.liked = !on; paintLike(btn, !on); toast(e.message); }
  }
  function pauseV() { if (!V) return; clearTimeout(V.t); cancelAnimationFrame(V.raf); const v = V.el.querySelector('video'); if (v) { try { v.pause(); } catch (_) {} } }
  function resumeV() { if (!V) return; if (V.ads) showAd(); else show(); }
  async function blobB64(url) {
    const b = await (await fetch(url, { credentials: 'same-origin' })).blob();
    const data = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] || ''); r.onerror = rej; r.readAsDataURL(b); });
    return { b, data };
  }
  async function statusPayload(name, it) {
    const head = '📢 ' + (name || 'Someone') + "'s status";
    if (it.kind === 'text' || !it.media) return { kind: 'text', body: head + ':\n' + (it.body || '') };
    const { b, data } = await blobB64(await mediaUrl(it.media));
    const mime = b.type || it.mime || (it.kind === 'video' ? 'video/mp4' : 'image/jpeg');
    return { kind: it.kind === 'video' ? 'video' : 'photo', body: head + (it.body ? ':\n' + it.body : ''), files: [{ filename: 'status.' + ((mime.split('/')[1] || 'jpg').replace('jpeg', 'jpg')), mime_type: mime, data_base64: data }] };
  }
  async function adPayload(ad, sh) {
    const t = String(ad.target || ''), link = /^https?:\/\//i.test(t) ? '\n' + t : '';
    const body = (sh ? '📣 ' + (sh.label || 'Shout-out') + ' from ' + (sh.from || '') : '📢 Sponsored · ' + (ad.advertiser || 'Business')) +
      ((ad.headline || ad.body) ? ':\n' + [ad.headline, ad.body].filter(Boolean).join('\n') : '') + link;
    if (/^image\//.test(ad.mime || '') && ad.media) { try { const { b, data } = await blobB64(ad.media); return { kind: 'photo', body, files: [{ filename: 'advert.jpg', mime_type: b.type || ad.mime, data_base64: data }] }; } catch (_) {} }
    return { kind: 'text', body };
  }
  function shareThing(build) {
    pauseV();
    let chats = []; try { chats = ((window.FutureChat && window.FutureChat.state && window.FutureChat.state().list) || []).filter(c => !c.archived); } catch (_) {}
    const max = 5, sel = new Set(); let q = '';
    sheet('<div class="fcf-hd"><h3>Share to…</h3><span id="fcsN"></span></div>' +
      '<input id="fcsQ" type="text" placeholder="Search chats" autocomplete="off" style="width:100%;box-sizing:border-box;margin:10px 0 6px">' +
      '<div class="fcf-bar"><small>Up to ' + max + ' chats at a time</small></div><div class="fcf-list" id="fcsL"></div>' +
      (navigator.share ? '<button class="fc-btn sec" data-a="out" style="width:100%">Share outside Future Chat</button>' : '') +
      '<button class="fc-btn" id="fcsGo" disabled style="width:100%">Send</button>', (dim, done) => {
      dim.style.zIndex = '13500';   // above the status viewer
      let finished = false;
      const end = () => { if (finished) return; finished = true; done(); resumeV(); };
      dim.addEventListener('click', e => { if (e.target === dim) { finished = true; resumeV(); } });
      const L = dim.querySelector('#fcsL'), N = dim.querySelector('#fcsN'), go = dim.querySelector('#fcsGo');
      const paint = () => {
        const f = q.toLowerCase(), list = chats.filter(c => !f || String(c.title || '').toLowerCase().includes(f));
        L.innerHTML = list.length ? list.slice(0, 300).map(c => '<button type="button" class="fcf-row' + (sel.has(c.id) ? ' on' : '') + '" data-c="' + c.id + '"><span class="fcf-av">' + esc(initials(c.title)) + '</span><span class="fcf-t"><b>' + esc(c.title || 'Chat') + '</b>' + (c.kind === 'group' ? '<small>Group</small>' : '') + '</span><span class="fcf-ck">✓</span></button>').join('')
          : '<p style="opacity:.7;margin:10px 4px">' + (chats.length ? 'No chat matches “' + esc(q) + '”.' : 'Open your chats first, then try again.') + '</p>';
        N.textContent = sel.size + ' of ' + max + ' selected';
        go.disabled = !sel.size; go.textContent = sel.size ? 'Send to ' + sel.size + (sel.size === 1 ? ' chat' : ' chats') : 'Send';
        L.querySelectorAll('[data-c]').forEach(b => b.onclick = () => {
          const id = Number(b.dataset.c);
          if (sel.has(id)) sel.delete(id); else if (sel.size >= max) { toast('You can share to ' + max + ' chats at a time'); return; } else sel.add(id);
          paint();
        });
      };
      dim.querySelector('#fcsQ').oninput = e => { q = e.target.value.trim(); paint(); };
      go.onclick = async () => {
        const ids = Array.from(sel); if (!ids.length) return;
        end(); toast('Sharing…');
        try {
          const p = await build(); let ok = 0, err = '';
          for (const c of ids) { try { await api('/api/fc/send', { c, kind: p.kind, body: p.body, meta: { fwd: 1 }, files: p.files || [] }); ok++; } catch (e) { err = e.message; } }
          toast(ok ? 'Shared to ' + ok + (ok === 1 ? ' chat' : ' chats') + (err ? ' · ' + err : '') : (err || 'Could not share'));
        } catch (e) { toast(e.message || 'Could not share'); }
      };
      const out = dim.querySelector('[data-a="out"]');
      if (out) out.onclick = async () => { end(); try { const p = await build(); await navigator.share({ title: 'Future Chat', text: p.body }); } catch (_) {} };
      paint();
    });
  }

  // ---------- ONE Sponsored status that rotates through the paid business ads
  function openAds(ads) {
    closeViewer();
    if (!ads || !ads.length) return;
    const el = document.createElement('div'); el.id = 'fcsView'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', 'Sponsored status');
    document.body.appendChild(el);
    V = { el, people: [], pi: 0, ii: 0, t: 0, raf: 0, ads };
    showAd();
  }
  function showAd() {
    const ad = V.ads[V.ii];
    const isVid = /^video\//.test(ad.mime || ''), isImg = /^image\//.test(ad.mime || '');
    const sh = window.FCX && window.FCX.shoutStage ? window.FCX.shoutStage(ad) : null;   // FCP-01: shout-outs and proposals
    V.el.innerHTML = '<div class="bars">' + V.ads.map((x, i) => '<div class="bar"><i style="width:' + (i < V.ii ? 100 : 0) + '%"></i></div>').join('') + '</div>' +
      '<div class="top"><div><b><span class="adtag">' + esc(sh ? sh.label : 'Sponsored') + '</span>' + esc(sh ? sh.from : (ad.advertiser || 'Business')) + '</b><small>' + (sh ? 'Paid shout-out' : 'Paid business advert') + '</small></div><div class="sp"><button data-a="x" aria-label="Close">✕</button></div></div>' +
      '<div class="stage"><div class="tapL"></div><div class="tapR"></div>' +
      (sh ? sh.html : isVid ? '<video src="' + esc(ad.media) + '" playsinline autoplay></video>' + ((ad.headline || ad.body) ? '<div class="cap"><b>' + esc(ad.headline) + '</b>' + (ad.body ? '\n' + esc(ad.body) : '') + '</div>' : '')
        : isImg ? '<img src="' + esc(ad.media) + '" alt="' + esc(ad.headline) + '">' + ((ad.headline || ad.body) ? '<div class="cap"><b>' + esc(ad.headline) + '</b>' + (ad.body ? '\n' + esc(ad.body) : '') + '</div>' : '')
        : '<div class="adbox"><h3>' + esc(ad.headline) + '</h3><p>' + esc(ad.body) + '</p></div>') + '</div>' +
      '<div class="foot">' + (ad.target ? '<button class="cta" data-a="cta">' + esc(ad.cta || 'Find out more') + '</button>' : '') + (ad.house ? '' : likeHtml(ad) + shareHtml) + '</div>';
    V.el.querySelector('[data-a="x"]').onclick = closeViewer;
    const alk = V.el.querySelector('[data-a="like"]'); if (alk) alk.onclick = e => { e.stopPropagation(); doLike('ad', ad, alk); };
    const ash = V.el.querySelector('[data-a="share"]'); if (ash) ash.onclick = e => { e.stopPropagation(); shareThing(() => adPayload(ad, sh)); };
    V.el.querySelector('.tapL').onclick = () => adStep(-1);
    V.el.querySelector('.tapR').onclick = () => adStep(1);
    const cta = V.el.querySelector('[data-a="cta"]');
    if (cta) cta.onclick = () => {
      if (!ad.house) api('/api/home-ads/event', { id: ad.id, ev: 'click' }).catch(() => {});
      const t = String(ad.target || '');
      if (/^https?:\/\//i.test(t)) window.open(t, '_blank', 'noopener');
      else if (/^tel:/i.test(t)) location.href = t;
      else if (/^provider:\d+$/.test(t)) { try { closeViewer(); window.FutureChat && window.FutureChat.close(); window.openProvider(Number(t.split(':')[1])); } catch (_) {} }
      else if (/^\+?[0-9 ]{7,}$/.test(t)) location.href = 'tel:' + t.replace(/\s+/g, '');
      else if (t.indexOf('@') > 0) location.href = 'mailto:' + t;
    };
    if (!ad.house) api('/api/fc/status/adseen', { id: ad.id }).catch(() => {});   // FC-ADS-02: counts a showing for this person
    const bar = V.el.querySelectorAll('.bar i')[V.ii];
    const vid = V.el.querySelector('video');
    const run = ms => { const t0 = performance.now(); const tick = () => { if (!V) return; const f = Math.min(1, (performance.now() - t0) / ms); bar.style.width = (f * 100) + '%'; if (f < 1) V.raf = requestAnimationFrame(tick); }; tick(); V.t = setTimeout(() => adStep(1), ms); };
    // Each advert shows for about 30 seconds, or for the full length of a video advert.
    if (vid) { vid.onloadedmetadata = () => run(Math.min(120000, Math.max(5000, (vid.duration || 30) * 1000))); vid.onerror = () => run(30000); }
    else run(30000);
  }
  function adStep(dir) {
    if (!V) return; clearTimeout(V.t); cancelAnimationFrame(V.raf);
    // The Sponsored status loops: after the last advert it starts again at the first one.
    V.ii = (V.ii + dir + V.ads.length) % V.ads.length;
    if (V.ii === 0 && dir > 0) V.el.querySelectorAll('.bar i').forEach(b => { b.style.width = '0%'; });
    showAd();
  }

  // ---------- posting a status
  const BGS = ['#0b2447', '#0d6f86', '#7b2cbf', '#c2185b', '#2e7d32', '#ef6c00', '#263238',
    'linear-gradient(135deg,#9d174d,#f59e0b)', 'linear-gradient(135deg,#1e3a8a,#0ea5e9)', 'linear-gradient(135deg,#14532d,#b91c1c)', 'linear-gradient(135deg,#6d28d9,#ec4899)'];   // festive colours
  function sheet(html, mount) {
    const dim = document.createElement('div'); dim.className = 'fc-dim';
    dim.innerHTML = '<div class="fc-sheet" role="dialog" aria-modal="true"><div class="fc-handle"></div>' + html + '</div>';
    const done = () => dim.remove();
    dim.addEventListener('click', e => { if (e.target === dim) done(); });
    document.body.appendChild(dim); mount(dim, done);
  }
  function compose() {
    sheet('<h3>New status</h3><p class="fc-muted" style="margin:4px 0 12px">Your status shows to the people you chat with and disappears after 24 hours.</p>' +
      '<div class="fc-acts"><button class="fc-act" data-a="text"><i>✍️</i><span>Write a text status</span></button><button class="fc-act" data-a="media"><i>📷</i><span>Photo or video</span></button></div>', (el, done) => {
      el.querySelector('[data-a="text"]').onclick = () => { done(); composeText(); };
      el.querySelector('[data-a="media"]').onclick = () => { done(); composeMedia(); };
    });
  }
  function composeText() {
    let bg = BGS[0];
    sheet('<h3>Text status</h3><textarea class="fcs-ta" maxlength="700" placeholder="Type your status" style="background:' + bg + '"></textarea>' +
      '<div class="fcs-bgs">' + BGS.map((c, i) => '<button type="button" aria-label="Colour" data-c="' + c + '" class="' + (i ? '' : 'on') + '" style="background:' + c + '"></button>').join('') + '</div>' +
      '<button class="fc-btn" data-a="post" style="width:100%">Post status</button>', (el, done) => {
      const ta = el.querySelector('textarea'); setTimeout(() => ta.focus(), 50);
      el.querySelectorAll('[data-c]').forEach(b => b.onclick = () => { bg = b.dataset.c; ta.style.background = bg; el.querySelectorAll('[data-c]').forEach(x => x.classList.toggle('on', x === b)); });
      el.querySelector('[data-a="post"]').onclick = async e => {
        const body = ta.value.trim(); if (!body) { toast('Type something first'); return; }
        e.target.disabled = true;
        try { await api('/api/fc/status', { body, bg }); done(); toast('Status posted'); refresh(true); } catch (err) { toast(err.message); e.target.disabled = false; }
      };
    });
  }
  function shrinkImage(file) {
    return new Promise((res, rej) => {
      const img = new Image(), url = URL.createObjectURL(file);
      img.onload = () => { const max = 1280, k = Math.min(1, max / Math.max(img.width, img.height)); const c = document.createElement('canvas'); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k); c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url); res(c.toDataURL('image/jpeg', 0.82)); };
      img.onerror = () => { URL.revokeObjectURL(url); rej(new Error('That photo could not be opened.')); };
      img.src = url;
    });
  }
  function readFile(file) { return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => rej(new Error('That file could not be read.')); r.readAsDataURL(file); }); }
  // FCSTATUS-CAM-01: in the Future Chat app, "Photo or video" asks Camera or Gallery; Camera opens the phone camera.
  // Skillvaya keeps its old behaviour (straight to the picker).
  function composeMedia() {
    if (!window.SV_FC_APP) { pickMedia(false); return; }
    sheet('<h3>Photo or video status</h3>' +
      '<div class="fc-acts"><button class="fc-act" data-a="cam"><i>📷</i><span>Take a photo</span></button><button class="fc-act" data-a="lib"><i>🖼️</i><span>Choose from gallery</span></button></div>', (el, done) => {
      el.querySelector('[data-a="cam"]').onclick = () => { done(); pickMedia(true); };
      el.querySelector('[data-a="lib"]').onclick = () => { done(); pickMedia(false); };
    });
  }
  function pickMedia(useCamera) {
    const inp = document.createElement('input'); inp.type = 'file';
    if (useCamera) { inp.accept = 'image/*'; inp.setAttribute('capture', 'environment'); }
    else inp.accept = 'image/*,video/mp4,video/webm';
    inp.onchange = async () => {
      const f = inp.files && inp.files[0]; if (!f) return;
      let data;
      try {
        if (/^image\//.test(f.type)) data = await shrinkImage(f);
        else if (/^video\/(mp4|webm)$/.test(f.type)) { if (f.size > 3 * 1024 * 1024) { toast('That video is too big for a status (3 MB maximum). Try a shorter clip.'); return; } data = await readFile(f); }
        else { toast('Choose a photo or an MP4 video.'); return; }
      } catch (e) { toast(e.message); return; }
      const isVid = data.startsWith('data:video');
      sheet('<h3>Photo or video status</h3>' + (isVid ? '<video class="fcs-prev" src="' + data + '" controls playsinline></video>' : '<img class="fcs-prev" src="' + data + '" alt="">') +
        '<input class="fc-in" maxlength="700" placeholder="Add a caption (optional)" style="width:100%;box-sizing:border-box;margin:8px 0">' +
        '<button class="fc-btn" data-a="post" style="width:100%">Post status</button>', (el, done) => {
        el.querySelector('[data-a="post"]').onclick = async e => {
          e.target.disabled = true; e.target.textContent = 'Posting…';
          try { await api('/api/fc/status', { media: data, body: el.querySelector('input').value.trim() }); done(); toast('Status posted'); refresh(true); }
          catch (err) { toast(err.message); e.target.disabled = false; e.target.textContent = 'Post status'; }
        };
      });
    };
    inp.click();
  }
  // FCSTATUS-ADV-01: the house card's button opens "Advertise with us" (Future Chat app) or the ad builder (Skillvaya)
  document.addEventListener('click', e => {
    const b = e.target && e.target.closest && e.target.closest('#fcsView [data-a]');
    if (!b || !V || !V.ads) return;
    const ad = V.ads[V.ii]; if (!ad || !ad.house) return;
    if (b.dataset.a !== 'cta') return;
    e.preventDefault(); e.stopPropagation();
    closeViewer();
    if (window.FCX && window.FCX.advertise) window.FCX.advertise();
    else if (window.HomeAds && window.HomeAds.openBuilder) { try { window.FutureChat && window.FutureChat.close(); } catch (_) {} window.HomeAds.openBuilder(); }
  }, true);
  window.FutureChatStatus = { refresh, compose, load, data: () => S.data, view: openViewer, ads: openAds, house: () => HOUSE_AD };
})();
