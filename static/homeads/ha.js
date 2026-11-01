/* Skillvaya homepage ads (SV92): the homepage block rotates paid, owner-approved "Sponsored" ads
   with the Future Chat card; businesses create and pay for ads here; the owner approves them. */
(function () {
  'use strict';
  const token = () => localStorage.getItem('skillvaya_token') || localStorage.getItem('sv_token') || sessionStorage.getItem('skillvaya_token') || sessionStorage.getItem('sv_token') || localStorage.getItem('skillvaya_owner_token') || '';
  async function api(path, body) {
    const t = token();
    const r = await fetch(path, { method: body ? 'POST' : 'GET', headers: Object.assign({ 'Content-Type': 'application/json' }, t ? { Authorization: 'Bearer ' + t } : {}), body: body ? JSON.stringify(body) : undefined, cache: 'no-store' });
    let d = {}; try { d = await r.json(); } catch (_) {}
    if (!r.ok) { const e = new Error(d.error || ('Request failed (' + r.status + ')')); e.data = d; throw e; }
    return d;
  }
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const native = () => /SkillvayaNative/i.test(navigator.userAgent) && window.SkillvayaBilling && typeof window.SkillvayaBilling.purchaseAd === 'function';
  const dataSaver = () => { try { return typeof window.svDataSaver === 'function' ? !!window.svDataSaver() : localStorage.getItem('sv_data_saver') === '1'; } catch (_) { return false; } };
  function toast(msg) {
    let t = document.getElementById('haToast');
    if (!t) { t = document.createElement('div'); t.id = 'haToast'; t.style.cssText = 'position:fixed;left:50%;bottom:96px;transform:translateX(-50%);z-index:21000;background:#0b1d33;color:#fff;padding:10px 16px;border-radius:12px;font-size:14px;max-width:88vw;text-align:center;box-shadow:0 8px 24px #0006;transition:opacity .3s'; document.body.appendChild(t); }
    t.textContent = msg; t.style.opacity = '1'; clearTimeout(t._h); t._h = setTimeout(() => { t.style.opacity = '0'; }, 3800);
  }
  function sheet(html, onMount) {
    const dim = document.createElement('div'); dim.className = 'fc-dim'; dim.style.zIndex = '20500';
    dim.innerHTML = '<div class="fc-sheet" role="dialog" aria-modal="true" style="max-height:88vh;overflow:auto"><div class="fc-handle"></div>' + html + '</div>';
    dim.addEventListener('click', e => { if (e.target === dim) dim.remove(); });
    document.body.appendChild(dim); if (onMount) onMount(dim.firstChild, () => dim.remove()); return dim;
  }

  // ------------------------------------------------------------ homepage slot
  const S = { ads: [], idx: 0, timer: 0, base: '', seen: {}, card: null, height: 0 };
  function openTarget(ad) {
    api('/api/home-ads/event', { id: ad.id, ev: 'click' }).catch(() => {});
    const t = ad.target || '';
    if (/^provider:\d+$/.test(t)) { try { window.openProvider(Number(t.split(':')[1])); } catch (_) {} return; }
    if (/^tel:/.test(t)) { location.href = t; return; }
    if (/^https?:\/\//.test(t)) { window.open(t, '_blank', 'noopener'); }
  }
  function adHtml(ad) {
    const media = ad.kind === 'photo' && ad.media ? '<img src="' + esc(ad.media) + '" alt="" style="width:100%;height:100%;object-fit:cover;display:block">'
      : ad.kind === 'video' && ad.media ? '<video src="' + esc(ad.media) + '" muted playsinline loop ' + (dataSaver() ? 'preload="none"' : 'autoplay preload="metadata"') + ' style="width:100%;height:100%;object-fit:cover;display:block;background:#000"></video>' + (dataSaver() ? '<span class="ha-play" style="position:absolute;inset:0;display:grid;place-items:center;font-size:30px;color:#fff;text-shadow:0 2px 8px #000">▶</span>' : '<span class="ha-snd" style="position:absolute;right:6px;bottom:6px;background:#0009;color:#fff;border-radius:10px;padding:2px 7px;font-size:12px">🔇</span>') : '';
    return '<div style="display:flex;gap:14px;align-items:stretch;height:100%">' +
      (media ? '<div class="ha-media" style="position:relative;flex:0 0 42%;max-width:220px;border-radius:12px;overflow:hidden;background:#0a1a2e">' + media + '</div>' : '<div style="font-size:34px;line-height:1" aria-hidden="true">📣</div>') +
      '<div style="flex:1;min-width:0;display:flex;flex-direction:column">' +
      '<div style="font-size:11px;font-weight:800;letter-spacing:.08em;color:#ffd479;text-transform:uppercase">Sponsored' + (ad.advertiser ? ' · <span style="text-transform:none;letter-spacing:0;color:#cfe0f5">' + esc(ad.advertiser) + '</span>' : '') + '</div>' +
      '<h2 style="margin:2px 0 6px;color:#fff;font-size:clamp(17px,4.6vw,22px);line-height:1.2;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">' + esc(ad.headline) + '</h2>' +
      (ad.body ? '<p style="margin:0 0 10px;color:#cfe0f5;overflow:hidden;display:-webkit-box;-webkit-line-clamp:' + (media ? 3 : 2) + ';-webkit-box-orient:vertical">' + esc(ad.body) + '</p>' : '') +
      '<div style="margin-top:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap">' + (ad.target ? '<button type="button" class="ha-cta" style="background:#ffd479;color:#2a1d00;border:0;border-radius:12px;padding:9px 14px;font-weight:800;cursor:pointer">' + esc(ad.cta || 'Learn more') + '</button>' : '') + '</div></div></div>';
  }
  function dots() {
    const n = S.ads.length + 1; if (n < 2) return '';
    let h = '<div style="position:absolute;left:0;right:0;bottom:6px;display:flex;justify-content:center;gap:5px;pointer-events:none">';
    for (let i = 0; i < n; i++) h += '<span style="width:6px;height:6px;border-radius:3px;background:' + (i === S.idx ? '#fff' : '#ffffff55') + '"></span>';
    return h + '</div>';
  }
  function footer() {
    return '<button type="button" class="ha-adv" style="position:absolute;bottom:4px;right:12px;background:none;border:0;color:#a9c8e7;font-size:12px;text-decoration:underline;cursor:pointer;padding:2px 0">Advertise here</button>';
  }
  function show(i) {
    const card = S.card; if (!card) return;
    clearTimeout(S.timer);
    if (!S.height) { const h = S.idx === 0 ? card.getBoundingClientRect().height : 0; if (h > 60) { S.height = h; card.style.height = h + 'px'; } else if (!card.style.height) card.style.minHeight = '190px'; }
    const total = S.ads.length + 1; S.idx = ((i % total) + total) % total;
    const inner = card.querySelector('.ha-inner');
    const ad = S.idx === 0 ? null : S.ads[S.idx - 1];
    inner.innerHTML = ad ? adHtml(ad) : S.base;
    inner.style.opacity = '0'; requestAnimationFrame(() => { inner.style.transition = 'opacity .35s'; inner.style.opacity = '1'; });
    card.querySelector('.ha-dots').innerHTML = dots();
    let wait = 8000;
    if (ad) {
      if (!S.seen[ad.id]) { S.seen[ad.id] = 1; api('/api/home-ads/event', { id: ad.id, ev: 'view' }).catch(() => {}); }
      const cta = inner.querySelector('.ha-cta'); if (cta) cta.onclick = e => { e.stopPropagation(); openTarget(ad); };
      const v = inner.querySelector('video');
      if (v) {
        wait = 20000;
        const snd = inner.querySelector('.ha-snd'), play = inner.querySelector('.ha-play');
        inner.querySelector('.ha-media').onclick = e => { e.stopPropagation(); if (v.paused) { v.play().catch(() => {}); if (play) play.remove(); } else if (snd) { v.muted = !v.muted; snd.textContent = v.muted ? '🔇' : '🔊'; } };
        v.addEventListener('volumechange', () => { if (!v.muted) clearTimeout(S.timer); });
      }
    } else {
      try { if (typeof window.svBindFutureChatCard === 'function') window.svBindFutureChatCard(inner); } catch (_) {}
    }
    if (total > 1) S.timer = setTimeout(() => show(S.idx + 1), wait);
  }
  async function setupSlot() {
    const card = document.getElementById('svFutureChatCard'); if (!card || card.dataset.ha) return;
    card.dataset.ha = '1'; S.card = card;
    S.base = card.innerHTML;
    card.style.position = 'relative'; card.style.overflow = 'hidden';
    card.innerHTML = '<div class="ha-inner" style="height:100%">' + S.base + '</div><div class="ha-dots"></div>' + footer();
    card.querySelector('.ha-adv').onclick = e => { e.stopPropagation(); openBuilder(); };
    // Same size for every slide: lock the block to the Future Chat card's own height.
    const lock = () => { if (S.idx !== 0) return; card.style.height = ''; const h = card.getBoundingClientRect().height; if (h > 60) { S.height = h; card.style.height = h + 'px'; } };
    lock(); window.addEventListener('resize', () => { const i = S.idx; if (i === 0) lock(); });
    let sx = 0; card.addEventListener('touchstart', e => { sx = e.touches[0].clientX; }, { passive: true });
    card.addEventListener('touchend', e => { const dx = e.changedTouches[0].clientX - sx; if (Math.abs(dx) > 50) show(S.idx + (dx < 0 ? 1 : -1)); }, { passive: true });
    try { const d = await api('/api/home-ads/live'); S.ads = d.items || []; } catch (_) { S.ads = []; }
    if (S.ads.length) { show(1); } else { card.querySelector('.ha-dots').innerHTML = ''; }
    setInterval(async () => { if (document.visibilityState === 'hidden') return; try { const d = await api('/api/home-ads/live'); const ids = (d.items || []).map(x => x.id).join(','); if (ids !== S.ads.map(x => x.id).join(',')) { S.ads = d.items || []; if (S.idx > S.ads.length) show(0); } } catch (_) {} }, 120000);
  }

  // ------------------------------------------------------------ advertiser: create + pay
  const CTAS = ['Learn more', 'Call now', 'Book now', 'Get a quote', 'Visit website', 'Shop now', 'Message us'];
  let ME = null, PLANS = [], PLAY = {};
  window.haAdProducts = (json) => { try { (JSON.parse(json || '[]') || []).forEach(p => { PLAY[p.productId] = p.price; }); } catch (_) {} document.querySelectorAll('[data-haprice]').forEach(el => { const pr = PLAY[el.dataset.haprice]; if (pr) el.textContent = pr; }); };
  window.haAdError = (msg) => { toast(msg || 'Google Play payment did not complete.'); const b = document.getElementById('haPay'); if (b) { b.disabled = false; b.textContent = b.dataset.label || 'Pay with Google Play'; } };
  window.haAdResult = (json) => { let d = {}; try { d = typeof json === 'string' ? JSON.parse(json) : (json || {}); } catch (_) {} document.querySelectorAll('.fc-dim').forEach(x => { if (x.querySelector('#haForm')) x.remove(); }); if (d.ok) { toast(d.message || 'Payment received. Your ad is waiting for approval.'); openMine(); } else if (d.cancelled) toast('Payment cancelled. You were not charged.'); else toast(d.message || 'The payment could not be confirmed yet.'); };
  async function loadMe() { const d = await api('/api/home-ads/mine'); ME = d.me; PLANS = d.plans || []; return d; }
  function readFile(f) { return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.onerror = () => rej(new Error('The file could not be read.')); r.readAsDataURL(f); }); }
  async function openBuilder() {
    if (!token()) { try { window.view('settings'); window.profileAuthMode('signin'); } catch (_) {} toast('Sign in to advertise on Skillvaya'); return; }
    try { await loadMe(); } catch (e) { toast(e.message); return; }
    if (native()) { try { window.SkillvayaBilling.queryAdProducts(); window.SkillvayaBilling.restoreAdPurchases(String(ME.id), token()); } catch (_) {} }
    const owner = ME.role === 'admin';
    const price = id => { const p = PLANS.find(x => x.product_id === id); return PLAY[id] || (p ? p.price : ''); };
    sheet('<h3>📣 Advertise on the Skillvaya homepage</h3><p>Your ad shows in the big block at the top of the Skillvaya homepage, rotating with other ads. It\'s marked <b>Sponsored</b> and checked by Skillvaya before it goes live. Your week or month starts when it goes live.</p>' +
      '<form id="haForm" onsubmit="return false">' +
      '<div class="fc-chips" style="margin:6px 0 10px" id="haKind"><button type="button" class="fc-chip on" data-k="word">✍️ Words</button><button type="button" class="fc-chip" data-k="photo">🖼️ Photo</button><button type="button" class="fc-chip" data-k="video">🎬 Video</button></div>' +
      '<input id="haAdv" maxlength="60" placeholder="Business name" value="' + esc(ME.business_name || ME.name || '') + '">' +
      '<input id="haHead" maxlength="60" placeholder="Headline, e.g. Same-day plumbing in Durban">' +
      '<textarea id="haBody" rows="2" maxlength="180" placeholder="Short message (optional)"></textarea>' +
      '<div id="haMediaRow" style="display:none"><input id="haFile" type="file"><small id="haFileNote" style="color:#55667d"></small></div>' +
      '<label style="display:block;font-size:13px;margin-top:6px;color:#33475f">Button</label><select id="haCta" style="width:100%;padding:12px;border:1px solid #cfd9e6;border-radius:12px;font-size:16px;margin:6px 0">' + CTAS.map(c => '<option>' + c + '</option>').join('') + '</select>' +
      '<label style="display:block;font-size:13px;margin-top:6px;color:#33475f">When people tap the button</label><select id="haTo" style="width:100%;padding:12px;border:1px solid #cfd9e6;border-radius:12px;font-size:16px;margin:6px 0">' + (ME.business_id ? '<option value="profile">Open my Skillvaya profile</option>' : '') + '<option value="web">Open my website</option><option value="tel">Call my number</option><option value="none">Nothing (just show the ad)</option></select>' +
      '<input id="haLink" placeholder="www.mybusiness.co.za" style="display:none">' +
      '<label style="display:block;font-size:13px;margin-top:8px;color:#33475f">How long</label><div class="fc-acts" id="haPlans"></div>' +
      '<p style="font-size:12px;color:#55667d;margin:10px 0 0">Ads must be honest and legal, and follow the <a href="/terms" target="_blank" rel="noopener">Skillvaya rules</a>: no adult content, weapons, gambling, scams, misleading claims or other people\'s trademarks. If your ad isn\'t approved, you get your money back. Payments are made through Google Play.</p>' +
      '<button type="button" class="fc-btn" id="haPay"></button><button type="button" class="fc-btn sec" id="haMine">My ads</button></form>', (el, done) => {
      let kind = 'word', product = '';
      const $ = s => el.querySelector(s);
      const drawPlans = () => {
        const tier = kind === 'video' ? 'video' : 'word';
        const list = PLANS.filter(p => p.tier === tier);
        if (!list.some(p => p.product_id === product)) product = list[0] ? list[0].product_id : '';
        $('#haPlans').innerHTML = list.map(p => '<button type="button" class="fc-act" data-p="' + p.product_id + '" style="' + (p.product_id === product ? 'border:2px solid #0b766e;background:#e7f6f4' : '') + '"><i>' + (p.days === 7 ? '📅' : '🗓️') + '</i><span>' + (p.days === 7 ? '1 week' : '1 month') + ' · <b data-haprice="' + p.product_id + '">' + esc(price(p.product_id)) + '</b><br><small style="color:#55667d">' + esc(p.label) + '</small></span></button>').join('');
        $('#haPlans').querySelectorAll('[data-p]').forEach(b => b.onclick = () => { product = b.dataset.p; drawPlans(); });
        const pay = $('#haPay');
        pay.textContent = owner ? 'Publish now (free for the owner)' : native() ? 'Pay ' + price(product) + ' with Google Play' : 'Pay in the Skillvaya Android app';
        pay.dataset.label = pay.textContent;
      };
      $('#haKind').querySelectorAll('[data-k]').forEach(b => b.onclick = () => {
        kind = b.dataset.k; $('#haKind').querySelectorAll('[data-k]').forEach(x => x.classList.toggle('on', x === b));
        $('#haMediaRow').style.display = kind === 'word' ? 'none' : 'block';
        $('#haFile').accept = kind === 'photo' ? 'image/jpeg,image/png,image/webp' : 'video/mp4,video/webm,video/quicktime';
        $('#haFile').value = '';
        $('#haFileNote').textContent = kind === 'photo' ? 'JPG, PNG or WebP, up to 2 MB. A wide picture looks best.' : 'MP4 video up to 12 MB (about 30 seconds). It plays silently until tapped.';
        drawPlans();
      });
      const syncTo = () => { const v = $('#haTo').value; $('#haLink').style.display = v === 'web' || v === 'tel' ? 'block' : 'none'; $('#haLink').placeholder = v === 'tel' ? '082 123 4567' : 'www.mybusiness.co.za'; $('#haLink').inputMode = v === 'tel' ? 'tel' : 'url'; };
      $('#haTo').onchange = syncTo; syncTo();
      $('#haMine').onclick = () => { done(); openMine(); };
      drawPlans();
      $('#haPay').onclick = async () => {
        const pay = $('#haPay');
        if (!owner && !native()) { sheet('<h3>Pay in the app</h3><p>Homepage ads are paid securely through Google Play in the Skillvaya Android app. Open the app, tap <b>Advertise here</b> on the homepage, and your ad will be ready to pay.</p><a class="fc-btn" style="text-align:center;text-decoration:none" href="https://play.google.com/store/apps/details?id=za.co.skillvaya.app">Get the Skillvaya app</a>'); return; }
        const headline = $('#haHead').value.trim(); if (headline.length < 3) { toast('Add a short headline'); return; }
        const to = $('#haTo').value, link = $('#haLink').value.trim();
        const target = to === 'profile' ? 'provider:' + ME.business_id : to === 'none' ? '' : to === 'tel' ? (link ? 'tel:' + link.replace(/[^\d+]/g, '') : '') : link;
        if ((to === 'web' || to === 'tel') && !link) { toast(to === 'tel' ? 'Add your phone number' : 'Add your website link'); return; }
        let media = null;
        if (kind !== 'word') {
          const f = $('#haFile').files[0]; if (!f) { toast('Add your ' + kind); return; }
          if (kind === 'photo' && f.size > 2 * 1024 * 1024) { toast('Photos must be 2 MB or smaller'); return; }
          if (kind === 'video' && f.size > 12 * 1024 * 1024) { toast('Videos must be 12 MB or smaller (about 30 seconds)'); return; }
          media = { mime: f.type === 'video/quicktime' ? 'video/quicktime' : f.type, data_base64: await readFile(f) };
        }
        pay.disabled = true; pay.textContent = 'Uploading your ad…';
        try {
          const d = await api('/api/home-ads/create', { kind, headline, body: $('#haBody').value.trim(), cta: $('#haCta').value, target, advertiser: $('#haAdv').value.trim(), product_id: product, media });
          if (d.status === 'active') { done(); toast('Your ad is live on the homepage'); S.ads = []; try { const l = await api('/api/home-ads/live'); S.ads = l.items || []; show(1); } catch (_) {} return; }
          pay.textContent = 'Opening Google Play…';
          window.SkillvayaBilling.purchaseAd(d.product_id, String(d.id), String(ME.id), token());
        } catch (e) { toast(e.message); pay.disabled = false; pay.textContent = pay.dataset.label; }
      };
    });
  }
  const STATUS = { pending_payment: ['Not paid', '#8a6d00'], pending_review: ['Waiting for approval', '#155ca8'], active: ['Live', '#0b766e'], paused: ['Paused', '#8a6d00'], rejected: ['Not approved', '#b42318'], expired: ['Ended', '#55667d'] };
  async function openMine() {
    let d; try { d = await loadMe(); } catch (e) { toast(e.message); return; }
    const items = d.items || [];
    sheet('<h3>My homepage ads</h3>' + (items.length ? items.map(a => {
      const st = STATUS[a.status] || [a.status, '#55667d'];
      return '<div class="fc-card" style="min-width:0;margin:8px 0"><div class="ln"><b>' + esc(a.headline) + '</b><span style="color:' + st[1] + ';font-weight:700">' + st[0] + '</span></div>' +
        '<div class="ln"><span>' + esc(a.plan || '') + '</span><span>' + esc(a.price || '') + '</span></div>' +
        (a.status === 'active' || a.status === 'expired' || a.status === 'paused' ? '<div class="ln"><span>Shown ' + a.views + ' times · ' + a.clicks + ' taps</span><span>' + (a.ends_at ? 'Until ' + new Date(a.ends_at).toLocaleDateString() : '') + '</span></div>' : '') +
        (a.note && a.status === 'rejected' ? '<small style="color:#b42318">' + esc(a.note) + '</small>' : '') +
        (['pending_payment', 'rejected', 'expired'].indexOf(a.status) >= 0 ? '<button type="button" class="fc-chip" data-del="' + a.id + '">Remove</button>' : '') + '</div>';
    }).join('') : '<p>You haven\'t made any ads yet.</p>') + '<button type="button" class="fc-btn" id="haNew">Create an ad</button>', (el, done) => {
      el.querySelector('#haNew').onclick = () => { done(); openBuilder(); };
      el.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => { try { await api('/api/home-ads/delete', { id: Number(b.dataset.del) }); done(); openMine(); } catch (e) { toast(e.message); } });
    });
  }
  window.HomeAds = { openBuilder, openMine };

  // ------------------------------------------------------------ owner app: approve ads
  function setupOwner() {
    const nav = document.getElementById('ownerNav'); if (!nav || nav.querySelector('[data-area="homeads"]')) return;
    const b = document.createElement('button'); b.dataset.area = 'homeads'; b.textContent = '📣 Homepage ads'; b.onclick = () => window.showArea('homeads');
    const fc = nav.querySelector('[data-area="futurechat"]'); if (fc && fc.nextSibling) nav.insertBefore(b, fc.nextSibling); else nav.appendChild(b);
    try { if (window.titles) window.titles.homeads = 'Homepage ads'; } catch (_) {}
    try { titles.homeads = 'Homepage ads'; } catch (_) {}
    const orig = window.showArea;
    window.showArea = async function (area) {
      if (area !== 'homeads') return orig.apply(this, arguments);
      try { currentArea = area; } catch (_) {}
      document.querySelectorAll('#ownerNav button').forEach(x => x.classList.toggle('active', x.dataset.area === area));
      const t = document.getElementById('pageTitle'); if (t) t.textContent = 'Homepage ads';
      await renderOwner();
    };
    api('/api/admin/home-ads').then(d => { if (d.pending) b.textContent = '📣 Homepage ads (' + d.pending + ' to approve)'; }).catch(() => {});
  }
  async function renderOwner() {
    const panel = document.getElementById('panel'); panel.innerHTML = '<div class="panel">Loading ads…</div>';
    let d; try { d = await api('/api/admin/home-ads'); } catch (e) { panel.innerHTML = '<div class="panel">' + esc(e.message) + '</div>'; return; }
    const items = d.items || [];
    const st = s => (STATUS[s] || [s])[0];
    panel.innerHTML = '<div class="panel"><h2>📣 Homepage ads</h2><p class="muted">Businesses pay through Google Play (word/photo R149 a week or R499 a month; video R249 a week or R799 a month). Check each ad is honest, legal and suitable before approving. The run starts when you approve. Rejecting refunds the payment automatically where Google allows it. You can also create free ads yourself from the homepage in your Skillvaya app (Advertise here).</p>' +
      (items.length ? items.map(a => '<div style="display:flex;gap:14px;align-items:flex-start;border-top:1px solid #e3ecf6;padding:14px 0;flex-wrap:wrap">' +
        '<div style="flex:0 0 180px;max-width:100%">' + (a.kind === 'photo' && a.media ? '<img src="' + esc(a.media) + '" style="width:180px;max-width:100%;border-radius:10px">' : a.kind === 'video' && a.media ? '<video src="' + esc(a.media) + '" controls muted playsinline preload="metadata" style="width:180px;max-width:100%;border-radius:10px;background:#000"></video>' : '<div style="font-size:42px">✍️</div>') + '</div>' +
        '<div style="flex:1;min-width:220px"><div style="font-weight:800">' + esc(a.headline) + ' <span style="font-weight:600;color:#155ca8">· ' + esc(st(a.status)) + '</span></div>' +
        '<div class="muted">' + esc(a.body) + '</div><div class="muted" style="margin-top:4px">By ' + esc(a.advertiser || a.owner_name) + ' (' + esc(a.owner_email) + ') · Button: ' + esc(a.cta) + (a.target ? ' → ' + esc(a.target) : '') + '</div>' +
        '<div class="muted">' + esc(a.plan) + ' · ' + esc(a.price) + (a.order_id ? ' · Order ' + esc(a.order_id) : '') + (a.ends_at ? ' · Ends ' + esc(new Date(a.ends_at).toLocaleString()) : '') + ' · Shown ' + a.views + ' · Taps ' + a.clicks + '</div>' +
        (a.note ? '<div class="muted">' + esc(a.note) + '</div>' : '') +
        '<div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">' +
        (a.status === 'pending_review' ? '<button data-ha="approve" data-id="' + a.id + '">✔ Approve</button><button class="danger" data-ha="reject" data-id="' + a.id + '">✖ Reject &amp; refund</button>' : '') +
        (a.status === 'active' ? '<button data-ha="pause" data-id="' + a.id + '">Pause</button>' : '') + (a.status === 'paused' ? '<button data-ha="resume" data-id="' + a.id + '">Resume</button>' : '') +
        '</div></div></div>').join('') : '<p>No ads yet. When a business pays for an ad, it appears here for your approval.</p>') + '</div>';
    panel.querySelectorAll('[data-ha]').forEach(btn => btn.onclick = async () => {
      const action = btn.dataset.ha; let reason = '';
      if (action === 'reject') { reason = prompt('Why is this ad not approved? (The business will see this.)', 'It doesn\'t meet the Skillvaya advertising rules.'); if (reason === null) return; }
      btn.disabled = true;
      try { const r = await api('/api/admin/home-ads', { id: Number(btn.dataset.id), action, reason }); if (r.refund === 'refund_failed') alert('Rejected. Google Play did not allow an automatic refund. Please refund this order in Play Console > Order management.'); await renderOwner(); }
      catch (e) { alert(e.message); btn.disabled = false; }
    });
  }

  function boot() {
    if (document.getElementById('ownerNav')) setupOwner();
    if (document.getElementById('svFutureChatCard')) setupSlot();
    else { const mo = new MutationObserver(() => { if (document.getElementById('svFutureChatCard')) { mo.disconnect(); setupSlot(); } }); mo.observe(document.documentElement, { childList: true, subtree: true }); setTimeout(() => mo.disconnect(), 30000); }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
