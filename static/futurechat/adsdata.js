/* ADS-DATA-01 (owner 2026-11-20): "Ads data" - one screen for Skillvaya Owner Control AND Future Chat Control.
   Money made from adverts, who posts adverts, and for every advert / shout-out / proposal: people reached, views,
   clicks, likes, shares, the NAMES of who clicked / liked / shared / saw it, daily charts and a report file for companies.
   Server: /api/admin/ad-stats, /api/admin/ad-people (owner only). Use: AdsData.open(containerElement, apiFunction). */
(function () {
  'use strict';
  if (window.AdsData) return;
  const E = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = v => Number(v || 0).toLocaleString('en-ZA');
  const rand = v => 'R' + Number(v || 0).toLocaleString('en-ZA', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  const pct = (a, b) => b ? (a / b * 100).toFixed(1) + '%' : '—';
  const SA = iso => { const t = Date.parse(iso || ''); return isNaN(t) ? '' : new Date(t + 7200000).toISOString().slice(0, 10); };
  const when = iso => { const t = Date.parse(iso || ''); if (isNaN(t)) return iso ? String(iso) : '—'; return new Date(t).toLocaleString('en-ZA', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); };
  const niceDay = d => { const t = Date.parse(d + 'T12:00:00Z'); return isNaN(t) ? d : new Date(t).toLocaleDateString('en-ZA', { weekday: 'short', day: 'numeric', month: 'short' }); };
  const FC = '#1ed6c8', SV = '#8ab8ff', GOLD = '#ffcf5c', PINK = '#ff8fb1', LILAC = '#c7a6ff';

  const css = document.createElement('style');
  css.textContent = [
    '.ad-w{color:#f4f9ff;font-family:Inter,system-ui,sans-serif}',
    '.ad-w button{font:inherit;cursor:pointer}',
    '.ad-gl{margin:16px 2px 8px;font-size:12px;font-weight:800;letter-spacing:.08em;color:#1ed6c8;text-transform:uppercase}',
    '.ad-note{color:#9cb7cc;font-size:12.5px;margin:4px 2px 10px;line-height:1.45}',
    '.ad-tabs{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;padding:2px 0 8px}.ad-tabs::-webkit-scrollbar{display:none}',
    'html body .ad-chip{flex:none;padding:7px 13px;border-radius:999px;font-size:13px;font-weight:700;white-space:nowrap;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);color:#f4f9ff}',
    'html body .ad-chip.on{background:#1ed6c8;color:#03222c;border-color:#1ed6c8}',
    '.ad-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}@media(max-width:560px){.ad-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}}',
    'html body .ad-tile{display:flex;flex-direction:column;align-items:flex-start;gap:2px;padding:12px;min-height:74px;text-align:left;border-radius:16px;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.09);color:#f4f9ff}',
    'html body .ad-tile b{font-size:21px;font-weight:800;line-height:1.1}.ad-tile span{font-size:12px;color:#9cb7cc;line-height:1.3}.ad-tile.fc b{color:#1ed6c8}.ad-tile.sv b{color:#8ab8ff}.ad-tile.gold b{color:#ffcf5c}',
    '.ad-card{background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.09);border-radius:18px;overflow:hidden;margin-bottom:12px}',
    '.ad-box{background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.09);border-radius:18px;padding:12px 12px 8px;margin-bottom:12px}.ad-box h4{margin:0 0 8px;font-size:14px}',
    'html body .ad-row{display:flex;align-items:center;gap:12px;width:100%;padding:11px 14px;border:0;border-bottom:1px solid rgba(255,255,255,.08);background:transparent;color:#f4f9ff;text-align:left;min-height:54px}',
    'html body .ad-card>.ad-row:last-child{border-bottom:0}.ad-row .ic{width:34px;height:34px;border-radius:11px;background:rgba(30,214,200,.13);display:grid;place-items:center;flex:none;font-size:16px}',
    '.ad-row .tx{flex:1;min-width:0}.ad-row .tx b{display:block;font-size:14.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ad-row .tx small{display:block;color:#9cb7cc;font-size:12.5px;margin-top:2px;overflow-wrap:anywhere}',
    '.ad-row .rt{flex:none;text-align:right;font-weight:800}.ad-row .chev{color:#9cb7cc;font-size:20px;flex:none}',
    '.ad-n{display:flex;flex-wrap:wrap;gap:3px 11px;font-size:12px;color:#cfe3f2;margin-top:5px}.ad-n b{color:#fff}',
    '.ad-tools{display:flex;gap:8px;align-items:center;margin:0 0 10px}.ad-tools input,.ad-tools select{min-width:0;padding:10px 12px;border-radius:12px;background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.14);color:#f4f9ff;font:inherit;font-size:14px}.ad-tools input{flex:1}',
    'html body .ad-btn{padding:10px 14px;border-radius:12px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);color:#f4f9ff;font-weight:700}.ad-btn.pri{background:linear-gradient(135deg,#1ed6c8,#12a8d0);color:#03222c;border:0}',
    '.ad-legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:#cfe3f2;margin-top:6px}.ad-legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}',
    '.ad-pick{min-height:20px;color:#9cb7cc;font-size:12.5px;margin:6px 2px 2px}',
    '.ad-dim{position:fixed;inset:0;z-index:30000;background:rgba(3,10,20,.62);display:flex;align-items:flex-end;justify-content:center}',
    '.ad-sheet{width:100%;max-width:640px;max-height:90dvh;overflow-y:auto;background:#0f2338;color:#f4f9ff;border:1px solid rgba(255,255,255,.1);border-radius:22px 22px 0 0;padding:14px 16px calc(20px + env(safe-area-inset-bottom));font-family:Inter,system-ui,sans-serif}',
    '.ad-sheet h3{margin:4px 0 4px;font-size:19px}.ad-kv{display:grid;grid-template-columns:minmax(110px,38%) minmax(0,1fr);gap:6px 10px;margin:12px 0;font-size:14px}.ad-kv dt{color:#9cb7cc}.ad-kv dd{margin:0;overflow-wrap:anywhere}',
    '.ad-b{display:inline-block;font-size:11px;font-weight:700;border-radius:999px;padding:2px 8px;margin-right:5px;background:rgba(30,214,200,.15);color:#9ff3ec}.ad-b.gold{background:rgba(255,207,92,.16);color:#ffe2a0}.ad-b.grey{background:rgba(255,255,255,.08);color:#9cb7cc}',
    '.ad-bar{height:8px;border-radius:5px;background:rgba(255,255,255,.08);overflow:hidden;margin-top:6px}.ad-bar i{display:block;height:100%;border-radius:5px}'
  ].join('');
  document.head.appendChild(css);

  const TYPE_NAME = { fc: 'Future Chat Status ad', home: 'Skillvaya home ad', shout: 'Shout-out / proposal' };
  const ST_NAME = { active: 'Running', wait: 'Waiting / paused', ended: 'Ended' };
  const adType = a => (a.tier === 'shout' || a.tier === 'propose') ? 'shout' : a.fc ? 'fc' : 'home';
  const stOf = a => a.status === 'active' ? 'active' : (a.status === 'queued' || a.status === 'paused') ? 'wait' : 'ended';
  const S = a => a.stats || {};
  const METRICS = [['views', 'Views'], ['reach', 'People reached'], ['clicks', 'Clicks'], ['likes', 'Likes'], ['shares', 'Shares']];
  const MCOL = { views: FC, reach: GOLD, clicks: SV, likes: PINK, shares: LILAC };
  const SORTS = [['new', 'Newest first'], ['reach', 'Most people reached'], ['views', 'Most views'], ['clicks', 'Most clicks'], ['ctr', 'Best click rate'], ['likes', 'Most likes'], ['shares', 'Most shares'], ['money', 'Most money']];
  const price = a => Number(String(a.price || '').replace(/[^\d.]/g, '')) || 0;
  const paidOf = a => (a.paid_at ? price(a) : 0);
  const sortVal = (a, k) => k === 'new' ? Number(a.id) : k === 'ctr' ? (S(a).views ? S(a).clicks / S(a).views : 0) : k === 'money' ? paidOf(a) : Number(S(a)[k] || 0);

  // ---------------------------------------------------------------- tappable bar chart
  function chart(box, labels, series, fmt) {
    if (!box) return;
    const f = fmt || num, W = 340, Hh = 118, n = labels.length, g = W / Math.max(1, n);
    const max = Math.max(1, ...series.map(s => Math.max(0, ...s.vals.map(Number))));
    const bw = Math.max(1.2, (g * 0.8) / series.length), off = (g - bw * series.length) / 2, step = Math.max(1, Math.ceil(n / 6));
    let s = '<svg viewBox="0 0 ' + W + ' ' + (Hh + 16) + '" width="100%" role="img" style="display:block;overflow:visible">' +
      '<line x1="0" x2="' + W + '" y1="12" y2="12" stroke="rgba(255,255,255,.08)" stroke-dasharray="3 3"/><text x="2" y="9" font-size="9" fill="#9cb7cc">' + E(f(max)) + '</text>' +
      '<line x1="0" x2="' + W + '" y1="' + Hh + '" y2="' + Hh + '" stroke="rgba(255,255,255,.18)"/>';
    labels.forEach((l, i) => {
      series.forEach((se, j) => { const v = Number(se.vals[i]) || 0, bh = v ? Math.max(2, v / max * (Hh - 12)) : 0;
        if (bh) s += '<rect x="' + (i * g + off + j * bw).toFixed(1) + '" y="' + (Hh - bh).toFixed(1) + '" width="' + Math.max(1, bw - 1).toFixed(1) + '" height="' + bh.toFixed(1) + '" rx="1.5" fill="' + se.color + '"/>'; });
      if ((n - 1 - i) % step === 0) s += '<text x="' + (i * g + g / 2).toFixed(1) + '" y="' + (Hh + 12) + '" font-size="9" fill="#9cb7cc" text-anchor="middle">' + l.slice(8) + '/' + l.slice(5, 7) + '</text>';
      s += '<rect data-i="' + i + '" x="' + (i * g).toFixed(1) + '" y="0" width="' + g.toFixed(1) + '" height="' + (Hh + 16) + '" fill="transparent" style="cursor:pointer"></rect>';
    });
    const tot = se => se.vals.reduce((a, b) => a + (Number(b) || 0), 0);
    box.innerHTML = s + '</svg><div class="ad-legend">' + series.map(se => '<span><i style="background:' + se.color + '"></i>' + E(se.name) + ' · ' + E(f(tot(se))) + ' in total</span>').join('') + '</div><div class="ad-pick">Tap a day to see its numbers</div>';
    const pick = box.querySelector('.ad-pick');
    box.querySelectorAll('rect[data-i]').forEach(r => r.addEventListener('click', () => {
      const i = Number(r.dataset.i);
      box.querySelectorAll('rect[data-i]').forEach(x => x.setAttribute('fill', 'transparent')); r.setAttribute('fill', 'rgba(255,255,255,.07)');
      pick.innerHTML = '<b style="color:#fff">' + E(niceDay(labels[i])) + '</b> · ' + series.map(se => E(se.name) + ' <b style="color:#fff">' + E(f(se.vals[i] || 0)) + '</b>').join(' · ');
    }));
  }
  const chips = (list, cur, attr) => '<div class="ad-tabs">' + list.map(c => '<button type="button" class="ad-chip' + (String(c[0]) === String(cur) ? ' on' : '') + '" data-' + attr + '="' + c[0] + '">' + E(c[1]) + '</button>').join('') + '</div>';
  const tile = (n, label, go, cls) => '<button type="button" class="ad-tile ' + (cls || '') + '" data-go="' + go + '"><b>' + E(n) + '</b><span>' + E(label) + '</span></button>';
  const row = (ic, title, sub, right, attrs) => '<button type="button" class="ad-row" ' + (attrs || '') + '><span class="ic">' + ic + '</span><span class="tx"><b>' + E(title) + '</b>' + (sub ? '<small>' + sub + '</small>' : '') + '</span>' + (right ? '<span class="rt">' + right + '</span>' : '') + '<span class="chev">›</span></button>';

  // ---------------------------------------------------------------- sheet
  let sheetEl = null;
  function closeSheet() { if (sheetEl) { sheetEl.remove(); sheetEl = null; } }
  function sheet(html) {
    closeSheet();
    sheetEl = document.createElement('div'); sheetEl.className = 'ad-dim';
    sheetEl.innerHTML = '<div class="ad-sheet ad-w" role="dialog" aria-modal="true">' + html + '</div>';
    sheetEl.addEventListener('click', e => { if (e.target === sheetEl) closeSheet(); });
    document.body.appendChild(sheetEl); return sheetEl;
  }
  window.addEventListener('popstate', closeSheet);

  // ---------------------------------------------------------------- reports (CSV opens in Excel)
  const cq = v => { v = String(v == null ? '' : v); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const csvRow = r => r.map(cq).join(',');
  const HEAD = ['Advert ID', 'Advertiser', 'Headline', 'Type', 'Status', 'Plan', 'Price paid', 'Paid on', 'Started', 'Ends', 'People reached', 'Views', 'Views Future Chat Status', 'Views Skillvaya home',
    'Reached Future Chat app users', 'Reached Skillvaya app users', 'Clicks', 'Different people who clicked', 'Click rate', 'Likes', 'Shares', 'Different people who shared', 'Bought by', 'Owner email'];
  const cells = a => { const s = S(a); return [a.id, a.advertiser, a.headline, TYPE_NAME[adType(a)], ST_NAME[stOf(a)], a.plan, a.paid_at ? rand(price(a)) : 'R0', (a.paid_at || '').slice(0, 10), (a.starts_at || '').slice(0, 10), (a.ends_at || '').slice(0, 10),
    s.reach || 0, s.views || 0, s.views_fc || 0, s.views_home || 0, (s.reach_apps || {}).futurechat || 0, (s.reach_apps || {}).skillvaya || 0, s.clicks || 0, s.people_clicked || 0, pct(s.clicks, s.views), s.likes || 0, s.shares || 0, s.people_shared || 0, a.owner_name, a.owner_email]; };
  function download(name, text) {
    try {
      const url = URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (e) { alert('Could not make the report: ' + e.message); }
  }
  const today = () => SA(new Date().toISOString());
  function summaryText(a) {
    const s = S(a);
    return 'Advert report: ' + (a.headline || 'Advert #' + a.id) + (a.advertiser ? ' (' + a.advertiser + ')' : '') + '\nRan: ' + when(a.starts_at) + ' to ' + when(a.ends_at) +
      '\nPeople reached: ' + num(s.reach) + '\nViews: ' + num(s.views) + ' (Future Chat Status ' + num(s.views_fc) + ', Skillvaya home ' + num(s.views_home) + ')' +
      '\nClicks: ' + num(s.clicks) + ' by ' + num(s.people_clicked) + ' different people · click rate ' + pct(s.clicks, s.views) + '\nLikes: ' + num(s.likes) + '\nShares: ' + num(s.shares) + ' by ' + num(s.people_shared) + ' people' +
      '\nFigures from Skillvaya / Future Chat on ' + niceDay(today()) + '. Detailed counting since 20 Nov 2026.';
  }

  // ---------------------------------------------------------------- the screen
  function open(root, api) {
    const V = { d: null, days: 30, tab: 'overview', st: 'all', ty: 'all', sort: 'new', q: '', metric: 'views', adv: null };
    root.classList.add('ad-w');
    async function load() {
      root.innerHTML = '<p class="ad-note">Loading ads data…</p>';
      try { V.d = await api('/api/admin/ad-stats?days=' + V.days); } catch (e) { root.innerHTML = '<p class="ad-note">Could not load ads data: ' + E(e.message) + '</p>'; return; }
      draw();
    }
    const items = () => V.d.items || [];
    function list() {
      const q = V.q.toLowerCase();
      return items().filter(a => (V.st === 'all' || stOf(a) === V.st) && (V.ty === 'all' || adType(a) === V.ty) && (!V.adv || String(a.user_id) === String(V.adv)) &&
        (!q || [a.headline, a.body, a.advertiser, a.owner_name, a.owner_email, a.id].some(v => String(v || '').toLowerCase().includes(q)))).sort((a, b) => sortVal(b, V.sort) - sortVal(a, V.sort));
    }
    function go(g) {
      if (g.indexOf('tab:') === 0) { V.tab = g.slice(4); draw(); root.scrollIntoView && window.scrollTo({ top: 0 }); return; }
      if (g.indexOf('sort:') === 0) { V.tab = 'adverts'; V.sort = g.slice(5); V.st = 'all'; draw(); return; }
      if (g.indexOf('st:') === 0) { V.tab = 'adverts'; V.st = g.slice(3); draw(); return; }
      if (g.indexOf('metric:') === 0) { V.metric = g.slice(7); V.tab = 'overview'; draw(); const b = root.querySelector('#adAll'); if (b) b.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
    }
    function draw() {
      const d = V.d, m = d.money || {}, posted = d.posted || {}, all = items(), sum = (arr, k) => arr.reduce((t, a) => t + Number(S(a)[k] || 0), 0);
      const tabs = chips([['overview', 'Overview'], ['adverts', 'Adverts (' + all.length + ')'], ['money', 'Money'], ['advertisers', 'Who posts adverts (' + (d.advertisers || []).length + ')']], V.tab, 'tab');
      let h = tabs;
      if (V.tab === 'overview') {
        const tv = sum(all, 'views'), tc = sum(all, 'clicks');
        h += '<div class="ad-gl">Money made from adverts</div><div class="ad-tiles">' + tile(rand(m.total), 'All time', 'tab:money', 'gold') + tile(rand(m.month), 'This month', 'tab:money', 'gold') + tile(rand(m.today), 'Today', 'tab:money', 'gold') + '</div>' +
          '<div class="ad-gl">Adverts posted</div><div class="ad-tiles">' + tile(num(posted.total), 'Adverts posted (all time)', 'tab:adverts') + tile(num(posted.month), 'Posted this month', 'tab:adverts') + tile(num(posted.today), 'Posted today', 'tab:adverts') +
          tile(num((d.advertisers || []).length), 'Different people who posted adverts', 'tab:advertisers', 'fc') + tile(num(all.filter(a => stOf(a) === 'active').length), 'Running now', 'st:active', 'fc') + tile(num(m.paid_adverts), 'Paid adverts', 'tab:money') + '</div>' +
          '<div class="ad-gl">What the adverts got · tap to rank the adverts</div><div class="ad-tiles">' +
          tile(num(sum(all, 'reach')), 'People reached (added up per advert)', 'sort:reach', 'fc') + tile(num(tv), 'Views', 'sort:views') + tile(num(tc) + ' · ' + pct(tc, tv), 'Clicks · click rate', 'sort:clicks', 'sv') +
          tile(num(sum(all, 'people_clicked')), 'Different people who clicked', 'sort:clicks', 'sv') + tile(num(sum(all, 'likes')), 'Likes', 'sort:likes') + tile(num(sum(all, 'shares')) + ' · ' + num(sum(all, 'people_shared')) + ' ppl', 'Shares · people who shared', 'sort:shares') + '</div>' +
          '<div class="ad-box" style="margin-top:12px"><h4>All adverts together, per day</h4>' + chips([[7, '7 days'], [30, '30 days'], [90, '90 days']], V.days, 'days') + chips(METRICS, V.metric, 'metric') + '<div id="adAll"></div></div>' +
          '<p class="ad-note">Tap any number to open the list behind it, then tap an advert to see exactly who saw it, clicked it, liked it and shared it. Reach, likes, shares and names are counted from 20 Nov 2026.</p>';
      } else if (V.tab === 'money') {
        const paid = all.filter(a => a.paid_at && price(a)).sort((a, b) => String(b.paid_at).localeCompare(String(a.paid_at)));
        const bt = m.by_type || {}, tot = Math.max(1, (bt.fc || 0) + (bt.home || 0) + (bt.shout || 0));
        h += '<div class="ad-tiles">' + tile(rand(m.total), 'All time', '', 'gold') + tile(rand(m.month), 'This month', '', 'gold') + tile(rand(m.today), 'Today', '', 'gold') + '</div>' +
          '<div class="ad-box" style="margin-top:12px"><h4>Money made each day</h4>' + chips([[7, '7 days'], [30, '30 days'], [90, '90 days']], V.days, 'days') + '<div id="adMoney"></div></div>' +
          '<div class="ad-box"><h4>Where the money came from</h4>' + [['fc', 'Future Chat Status ads', FC], ['home', 'Skillvaya home ads', SV], ['shout', 'Shout-outs & proposals', PINK]].map(t =>
            '<div style="margin:8px 0"><div style="display:flex;justify-content:space-between;font-size:13.5px"><span>' + t[1] + '</span><b>' + rand(bt[t[0]]) + '</b></div><div class="ad-bar"><i style="width:' + ((bt[t[0]] || 0) / tot * 100).toFixed(1) + '%;background:' + t[2] + '"></i></div></div>').join('') + '</div>' +
          '<div class="ad-gl">Every paid advert · ' + paid.length + '</div><div class="ad-card">' + (paid.length ? paid.map(a => row(adType(a) === 'shout' ? '🎉' : adType(a) === 'fc' ? '📢' : '🏠', a.headline || a.advertiser || 'Advert #' + a.id,
            E([a.owner_name || a.advertiser, a.plan, 'paid ' + when(a.paid_at)].filter(Boolean).join(' · ')), rand(price(a)), 'data-ad="' + a.id + '"')).join('') : '<div class="ad-row"><span class="tx"><b>No paid adverts yet</b></span></div>') + '</div>' +
          '<p class="ad-note">Amounts are the prices people paid through Google Play. Google keeps its service fee (15%) from these before paying you. Your own free adverts are not counted as money.</p>';
      } else if (V.tab === 'advertisers') {
        const ad = d.advertisers || [];
        h += '<p class="ad-note">Everyone who has posted an advert, shout-out or proposal, with how much they spent. Tap someone to see their adverts and results.</p><div class="ad-card">' +
          (ad.length ? ad.map(p => row('👤', p.name || p.email || 'Account #' + p.id, E([p.email, num(p.adverts) + (p.adverts === 1 ? ' advert' : ' adverts'), 'last ' + when(p.last)].filter(Boolean).join(' · ')), rand(p.spent), 'data-adv="' + p.id + '"')).join('')
            : '<div class="ad-row"><span class="tx"><b>Nobody has posted an advert yet</b></span></div>') + '</div>';
      } else {
        const L = list(), advName = V.adv ? ((d.advertisers || []).find(p => String(p.id) === String(V.adv)) || {}).name : '';
        h += (V.adv ? '<div class="ad-tools"><span class="ad-b gold">Only ' + E(advName || 'this person') + '\'s adverts</span><button type="button" class="ad-btn" data-x="clearadv">Show everyone\'s</button></div>' : '') +
          chips([['all', 'All'], ['active', 'Running'], ['wait', 'Waiting / paused'], ['ended', 'Ended']], V.st, 'st') +
          chips([['all', 'All types'], ['fc', 'Future Chat Status ads'], ['home', 'Skillvaya home ads'], ['shout', 'Shout-outs & proposals']], V.ty, 'ty') +
          '<div class="ad-tools"><input id="adQ" placeholder="Search advertiser, headline or owner" autocomplete="off"><select id="adSort">' + SORTS.map(s => '<option value="' + s[0] + '"' + (s[0] === V.sort ? ' selected' : '') + '>' + s[1] + '</option>').join('') + '</select></div>' +
          '<div class="ad-tools"><button type="button" class="ad-btn" data-x="csv">⬇ Report of these adverts (opens in Excel)</button></div>' +
          '<div class="ad-gl">' + L.length + ' adverts · tap one for who saw, clicked, liked and shared it</div><div class="ad-card">' + (L.length ? L.map(a => { const s = S(a);
            return '<button type="button" class="ad-row" data-ad="' + a.id + '"><span class="ic">' + (adType(a) === 'shout' ? '🎉' : adType(a) === 'fc' ? '📢' : '🏠') + '</span><span class="tx"><b>' + E(a.headline || a.advertiser || 'Advert #' + a.id) + '</b><small>' +
              E([a.advertiser || a.owner_name, TYPE_NAME[adType(a)], ST_NAME[stOf(a)], a.paid_at ? rand(price(a)) + ' paid' : ''].filter(Boolean).join(' · ')) + '</small>' +
              '<span class="ad-n"><span>👥 <b>' + num(s.reach) + '</b> reached</span><span>👁 <b>' + num(s.views) + '</b> views</span><span>👆 <b>' + num(s.clicks) + '</b> clicks (' + pct(s.clicks, s.views) + ')</span><span>❤ <b>' + num(s.likes) + '</b></span><span>↗ <b>' + num(s.shares) + '</b> shares</span></span></span><span class="chev">›</span></button>'; }).join('')
            : '<div class="ad-row"><span class="tx"><b>No adverts match</b><small>Try another filter</small></span></div>') + '</div>';
      }
      root.innerHTML = h;
      // wiring
      root.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { V.tab = b.dataset.tab; if (V.tab !== 'adverts') V.adv = null; draw(); });
      root.querySelectorAll('[data-go]').forEach(b => b.onclick = () => { if (b.dataset.go) go(b.dataset.go); });
      root.querySelectorAll('[data-days]').forEach(b => b.onclick = () => { V.days = Number(b.dataset.days); load(); });
      root.querySelectorAll('[data-metric]').forEach(b => b.onclick = () => { V.metric = b.dataset.metric; draw(); });
      root.querySelectorAll('[data-st]').forEach(b => b.onclick = () => { V.st = b.dataset.st; draw(); });
      root.querySelectorAll('[data-ty]').forEach(b => b.onclick = () => { V.ty = b.dataset.ty; draw(); });
      root.querySelectorAll('[data-ad]').forEach(b => b.onclick = () => adSheet(items().find(a => String(a.id) === b.dataset.ad)));
      root.querySelectorAll('[data-adv]').forEach(b => b.onclick = () => { V.adv = b.dataset.adv; V.tab = 'adverts'; V.st = 'all'; V.ty = 'all'; draw(); });
      const ca = root.querySelector('[data-x="clearadv"]'); if (ca) ca.onclick = () => { V.adv = null; draw(); };
      const cv = root.querySelector('[data-x="csv"]'); if (cv) cv.onclick = () => download('advert-results-' + today() + '.csv', [csvRow(HEAD)].concat(list().map(a => csvRow(cells(a)))).join('\r\n'));
      const q = root.querySelector('#adQ'); if (q) { q.value = V.q; q.oninput = e => { V.q = e.target.value.trim(); clearTimeout(V.t); V.t = setTimeout(() => { draw(); const n = root.querySelector('#adQ'); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }, 350); }; }
      const so = root.querySelector('#adSort'); if (so) so.onchange = e => { V.sort = e.target.value; draw(); };
      const L = d.labels || [];
      const ca2 = root.querySelector('#adAll');
      if (ca2) { const mm = V.metric; chart(ca2, L, [{ name: (METRICS.find(x => x[0] === mm) || METRICS[0])[1], color: MCOL[mm], vals: L.map(day => all.reduce((t, a) => t + Number(((S(a).series || {})[day] || {})[mm] || 0), 0)) }]); }
      const cm = root.querySelector('#adMoney'); if (cm) chart(cm, L, [{ name: 'Money made', color: GOLD, vals: L.map(day => Number((m.series || {})[day] || 0)) }], rand);
    }
    async function adSheet(a) {
      if (!a) return;
      const s = S(a), freq = s.reach ? (s.views / s.reach).toFixed(1) : '—';
      const el = sheet('<h3>' + E(a.headline || a.advertiser || 'Advert #' + a.id) + '</h3><span class="ad-b">' + E(TYPE_NAME[adType(a)]) + '</span><span class="ad-b ' + (stOf(a) === 'active' ? '' : stOf(a) === 'wait' ? 'gold' : 'grey') + '">' + E(ST_NAME[stOf(a)]) + '</span>' + (a.paid_at ? '<span class="ad-b gold">' + rand(price(a)) + ' paid</span>' : '') +
        '<div class="ad-tiles" style="margin-top:12px">' + tile(num(s.reach), 'Different people reached', 'p:reached', 'fc') + tile(num(s.views), 'Views (' + freq + ' per person)', 'm:views') +
        tile(num(s.clicks) + ' · ' + pct(s.clicks, s.views), 'Clicks · click rate', 'p:clicked', 'sv') + tile(num(s.people_clicked), 'Different people who clicked', 'p:clicked', 'sv') +
        tile(num(s.likes), 'Likes', 'p:liked') + tile(num(s.shares) + ' · ' + num(s.people_shared) + ' ppl', 'Shares · people who shared', 'p:shared') + '</div>' +
        '<div class="ad-box" style="margin-top:12px"><h4>Who it was · names</h4>' + chips([['clicked', '👆 Clicked'], ['liked', '❤ Liked'], ['shared', '↗ Shared'], ['reached', '👥 Saw it']], 'clicked', 'who') + '<div id="adWho" class="ad-note">Loading names…</div></div>' +
        '<div class="ad-box"><h4>Per day (last ' + V.days + ' days)</h4>' + chips(METRICS, 'views', 'sm') + '<div id="adOne"></div></div>' +
        '<dl class="ad-kv"><dt>Advertiser</dt><dd>' + E(a.advertiser || '—') + '</dd><dt>Bought by</dt><dd>' + E([a.owner_name, a.owner_email].filter(Boolean).join(' · ') || '—') + '</dd>' +
        '<dt>Plan</dt><dd>' + E([a.plan, a.price].filter(Boolean).join(' · ') || '—') + (a.paid_at ? '<br>Paid ' + E(when(a.paid_at)) : '<br>Not paid (owner advert)') + '</dd><dt>Ran</dt><dd>' + E(when(a.starts_at)) + ' → ' + E(when(a.ends_at)) + '</dd>' +
        '<dt>Where it was seen</dt><dd>Future Chat Status ' + num(s.views_fc) + ' · Skillvaya home ' + num(s.views_home) + '</dd>' +
        '<dt>Who it reached</dt><dd>Future Chat app users ' + num((s.reach_apps || {}).futurechat) + ' · Skillvaya app users ' + num((s.reach_apps || {}).skillvaya) + '</dd>' +
        (a.target ? '<dt>Link</dt><dd>' + E(a.target) + '</dd>' : '') + (a.body ? '<dt>Text</dt><dd>' + E(a.body) + '</dd>' : '') + '</dl>' +
        '<div style="display:flex;gap:8px;flex-wrap:wrap"><button class="ad-btn pri" data-x="csv">⬇ Report for the company</button><button class="ad-btn" data-x="copy">Copy summary</button>' + (navigator.share ? '<button class="ad-btn" data-x="share">Share summary</button>' : '') + '<button class="ad-btn" data-x="close">Close</button></div>');
      const L = V.d.labels || [], ser = s.series || {};
      const drawDay = mm => chart(el.querySelector('#adOne'), L, [{ name: (METRICS.find(x => x[0] === mm) || METRICS[0])[1], color: MCOL[mm], vals: L.map(day => (ser[day] || {})[mm] || 0) }]);
      el.querySelectorAll('[data-sm]').forEach(b => b.onclick = () => { el.querySelectorAll('[data-sm]').forEach(x => x.classList.toggle('on', x === b)); drawDay(b.dataset.sm); });
      drawDay('views');
      let ppl = null;
      const WHO = { clicked: 'clicked it', liked: 'liked it', shared: 'shared it', reached: 'saw it' };
      const showWho = k => {
        el.querySelectorAll('[data-who]').forEach(x => x.classList.toggle('on', x.dataset.who === k));
        const box = el.querySelector('#adWho'); if (!ppl) { box.textContent = 'Loading names…'; return; }
        const L2 = ppl[k] || [];
        box.className = ''; box.innerHTML = '<p class="ad-note">' + L2.length + (L2.length === 1 ? ' person ' : ' people ') + WHO[k] + (k === 'reached' ? ' (signed-in people only)' : '') + '</p>' + (L2.length ? '<div class="ad-card" style="margin:0">' + L2.map(p =>
          '<div class="ad-row" style="cursor:default"><span class="ic">👤</span><span class="tx"><b>' + E(p.name || 'No name') + '</b><small>' + E([p.phone, p.email].filter(Boolean).join(' · ')) + '</small></span><span class="rt" style="font-weight:400;font-size:12px;color:#9cb7cc">' + E(k === 'reached' ? niceDay(p.at) : when(p.at)) + '</span></div>').join('') + '</div>' : '');
      };
      el.querySelectorAll('[data-who]').forEach(b => b.onclick = () => showWho(b.dataset.who));
      el.querySelectorAll('[data-go]').forEach(b => b.onclick = () => { const g = b.dataset.go; if (g.indexOf('p:') === 0) { showWho(g.slice(2)); el.querySelector('#adWho').scrollIntoView({ behavior: 'smooth', block: 'center' }); } else { const c = el.querySelector('[data-sm="' + g.slice(2) + '"]'); if (c) { c.click(); c.scrollIntoView({ behavior: 'smooth', block: 'center' }); } } });
      const on = (k, f) => { const b = el.querySelector('[data-x="' + k + '"]'); if (b) b.onclick = f; };
      const text = summaryText(a);
      on('close', closeSheet);
      on('csv', async () => {
        const rows = [csvRow(HEAD), csvRow(cells(a)), '', csvRow(['Day', 'Views', 'People reached', 'Clicks', 'Likes', 'Shares'])].concat(L.map(day => { const v = ser[day] || {}; return csvRow([day, v.views || 0, v.reach || 0, v.clicks || 0, v.likes || 0, v.shares || 0]); }));
        download('advert-' + a.id + '-report-' + today() + '.csv', rows.join('\r\n'));
      });
      on('copy', async () => { try { await navigator.clipboard.writeText(text); alert('Summary copied.'); } catch (_) { prompt('Copy this summary:', text); } });
      on('share', () => navigator.share({ title: 'Advert report', text }).catch(() => {}));
      try { ppl = await api('/api/admin/ad-people?id=' + a.id); } catch (e) { ppl = { clicked: [], liked: [], shared: [], reached: [] }; }
      if (sheetEl && el === sheetEl) showWho((el.querySelector('[data-who].on') || {}).dataset ? el.querySelector('[data-who].on').dataset.who : 'clicked');
    }
    load();
  }
  window.AdsData = { open, close: closeSheet };
})();
