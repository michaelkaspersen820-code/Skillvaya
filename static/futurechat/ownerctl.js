/* OWN-CTL-01 (owner 2026-11-20): Skillvaya Owner Control in the Future Chat Control style.
   - One clean screen: tappable number tiles (every number opens the people or records behind it), then every section as a row.
   - New "People" screen: every account with WHICH PHONE APP it uses (Skillvaya / Future Chat / both / none yet) and when it
     was last on, with filters (on today, this week, new, providers, paid ...) and a details sheet with ban / restore.
   - Every section gets a back button; the phone's back button returns to the dashboard.
   All existing sections and their code are unchanged; this file only adds the new look and screens. Server: /api/tst/people. */
(function () {
  'use strict';
  if (window.__ownerCtl) return; window.__ownerCtl = 1;
  const $q = (s, r) => (r || document).querySelector(s);
  const H = s => esc(s);
  const SA = iso => { const t = Date.parse(iso || ''); return isNaN(t) ? '' : new Date(t + 7200000).toISOString().slice(0, 10); };
  const TODAY = () => SA(new Date().toISOString());
  const ago = iso => { const t = Date.parse(iso || ''); if (isNaN(t)) return ''; const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 600) return 'just now'; if (s < 3600) return Math.round(s / 60) + ' min ago'; if (s < 86400) return Math.round(s / 3600) + ' h ago';
    const d = Math.round(s / 86400); return d === 1 ? 'yesterday' : d + ' days ago'; };
  const day = iso => { const t = Date.parse(iso || ''); return isNaN(t) ? '—' : new Date(t).toLocaleString('en-ZA', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); };
  // OWN-CTL-02: time on, days used, offline lists, testers, trends, advert results
  const APPS = [['skillvaya', 'Skillvaya app'], ['futurechat', 'Future Chat app']];
  const SVC = '#8ab8ff', FCC = '#1ed6c8';
  const niceDay = d => { const t = Date.parse(d + 'T12:00:00Z'); return isNaN(t) ? d : new Date(t).toLocaleDateString('en-ZA', { weekday: 'short', day: 'numeric', month: 'short' }); };
  const dayList = n => { const t0 = Date.parse(TODAY() + 'T00:00:00Z'), out = []; for (let i = n - 1; i >= 0; i--) out.push(new Date(t0 - i * 86400000).toISOString().slice(0, 10)); return out; };
  const dget = (p, app, d) => { const a = (p.days || {})[app], v = a && a[d]; return v ? [Number(v[0]) || 0, Number(v[1]) || 0] : [0, 0]; };
  const sumOn = (p, app, n) => dayList(n).reduce((s, d) => { const v = dget(p, app, d); s[0] += v[0]; s[1] += v[1]; return s; }, [0, 0]);
  const activeApp = (p, app, d) => dget(p, app, d)[0] > 0 || SA(last(p, app)) === d;
  const activeOn = (p, d) => APPS.some(a => activeApp(p, a[0], d));
  const activeDays = (p, n) => dayList(n).filter(d => activeOn(p, d)).length;
  const onWithin = (p, n) => dayList(n).some(d => activeOn(p, d)) || within(last(p, 'skillvaya'), n) || within(last(p, 'futurechat'), n);
  const minsDay = (p, d) => APPS.reduce((s, a) => s + dget(p, a[0], d)[0], 0);
  const fmtMin = m => { m = Math.round(Number(m) || 0); return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : ''); };
  const pct = (a, b) => b ? (a / b * 100).toFixed(1) + '%' : '—';
  const num = v => Number(v || 0).toLocaleString('en-ZA');

  // ---------------------------------------------------------------- look (same family as Future Chat Control)
  const css = document.createElement('style');
  css.textContent = [
    'html{background:#0f3150}body.oc{background:linear-gradient(180deg,#0a1f33 0%,#0f3150 55%,#11506a 100%) fixed!important;background-color:#0f3150!important;min-height:100dvh;color:#f4f9ff}',
    'body.oc .layout{display:block!important;min-height:100dvh}body.oc aside{display:none!important}',
    'body.oc main{max-width:860px!important;margin:0 auto!important;padding:10px 14px 90px!important}',
    'body.oc #svOwnerToApp{position:static!important;margin:0 0 8px!important;padding:8px 12px!important;font-size:13px!important;border-radius:12px!important;background:rgba(30,214,200,.12)!important;color:#1ed6c8!important;border:1px solid rgba(30,214,200,.3)}',
    'body.oc main>.top{position:sticky!important;top:0!important;z-index:40!important;display:flex!important;flex-wrap:nowrap!important;align-items:center!important;gap:10px!important;margin:0 0 10px!important;padding:10px 12px!important;border-radius:16px!important;background:rgba(7,26,44,.94)!important;backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.09);box-shadow:0 8px 22px rgba(0,0,0,.25)}',
    'body.oc main>.top>div{flex:1;min-width:0}body.oc main>.top h1{font-size:19px!important;margin:0!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    'body.oc main>.top .muted{font-size:12px!important;color:#9cb7cc!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    'body.oc main>.top>button{flex:none;padding:8px 12px!important;border-radius:12px!important;background:rgba(255,255,255,.07)!important;border:1px solid rgba(255,255,255,.12)!important;font-size:13px}',
    '#ocBack{display:none;width:40px;height:40px;padding:0!important;font-size:24px!important;line-height:1}body.oc-sub #ocBack{display:grid;place-items:center}',
    'body.oc .panel,body.oc .stat,body.oc .hero{background:rgba(255,255,255,.055)!important;border:1px solid rgba(255,255,255,.09)!important;border-radius:18px!important;box-shadow:none!important}',
    'body.oc .hero{background:linear-gradient(135deg,rgba(30,214,200,.14),rgba(18,168,208,.06))!important}',
    'body.oc button{border-radius:12px;background:rgba(255,255,255,.07);border-color:rgba(255,255,255,.14)}',
    'body.oc button.primary{background:linear-gradient(135deg,#1ed6c8,#12a8d0)!important;color:#03222c!important;border:0!important}',
    'body.oc button.danger{background:rgba(255,107,107,.16)!important;color:#ffb4b4!important;border:1px solid rgba(255,107,107,.4)!important}',
    'body.oc input,body.oc select,body.oc textarea{background:rgba(0,0,0,.25)!important;border-color:rgba(255,255,255,.14)!important;border-radius:12px!important}',
    'body.oc table{background:transparent!important}body.oc th{background:rgba(255,255,255,.06)!important}body.oc .tablewrap{border-color:rgba(255,255,255,.1)!important}',
    'body.oc .pill{background:rgba(30,214,200,.14);color:#bff6f1}',
    '.oc-gl{margin:18px 4px 8px;font-size:12px;font-weight:800;letter-spacing:.09em;color:#1ed6c8;text-transform:uppercase}',
    '.oc-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}',
    '.oc-tile{display:flex!important;flex-direction:column;align-items:flex-start;gap:2px;padding:12px!important;min-height:78px;text-align:left;border-radius:16px!important;background:rgba(255,255,255,.055)!important;border:1px solid rgba(255,255,255,.09)!important;color:#f4f9ff!important;font-weight:400!important}',
    '.oc-tile b{font-size:22px;font-weight:800;line-height:1.1}.oc-tile span{font-size:12px;color:#9cb7cc;line-height:1.3}.oc-tile:active{background:rgba(255,255,255,.1)!important}',
    '.oc-tile.sv b{color:#8ab8ff}.oc-tile.fc b{color:#1ed6c8}.oc-tile.warn b{color:#ffcf5c}',
    '.oc-card{background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.09);border-radius:18px;overflow:hidden;margin-bottom:12px}',
    '.oc-row{display:flex!important;align-items:center;gap:12px;width:100%;padding:12px 14px!important;border:0!important;border-bottom:1px solid rgba(255,255,255,.08)!important;border-radius:0!important;background:transparent!important;color:#f4f9ff!important;text-align:left;font-weight:400!important;min-height:56px}',
    '.oc-card>.oc-row:last-child{border-bottom:0!important}.oc-row:active{background:rgba(255,255,255,.05)!important}',
    '.oc-row .ic{width:36px;height:36px;border-radius:11px;background:rgba(30,214,200,.13);color:#1ed6c8;display:grid;place-items:center;flex:none;font-size:17px}',
    '.oc-row .tx{flex:1;min-width:0}.oc-row .tx b{display:block;font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.oc-row .tx small{display:block;color:#9cb7cc;font-size:12.5px;margin-top:2px;line-height:1.35;overflow-wrap:anywhere}.oc-row .chev{color:#9cb7cc;font-size:20px;flex:none}',
    '.oc-row.danger .ic{background:rgba(255,107,107,.14);color:#ffb4b4}.oc-row.danger .tx b{color:#ffb4b4}',
    '.oc-badges{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}.oc-b{display:inline-block;font-size:11px;font-weight:700;border-radius:999px;padding:2px 8px}',
    '.oc-b.sv{background:rgba(138,184,255,.16);color:#bcd6ff}.oc-b.fc{background:rgba(30,214,200,.15);color:#9ff3ec}.oc-b.none{background:rgba(255,255,255,.08);color:#9cb7cc}.oc-b.red{background:rgba(255,107,107,.18);color:#ffb4b4}.oc-b.gold{background:rgba(255,207,92,.16);color:#ffe2a0}',
    '.oc-chips{display:flex;gap:6px;overflow-x:auto;padding:2px 0 8px;scrollbar-width:none}.oc-chips::-webkit-scrollbar{display:none}',
    '.oc-chip{flex:none;padding:6px 12px!important;border-radius:999px!important;font-size:13px!important;font-weight:700!important;white-space:nowrap}.oc-chip.on{background:#1ed6c8!important;color:#03222c!important;border-color:#1ed6c8!important}',
    '.oc-note{color:#9cb7cc;font-size:12.5px;margin:4px 4px 10px;line-height:1.45}',
    '.oc-dim{position:fixed;inset:0;z-index:20000;background:rgba(3,10,20,.6);display:flex;align-items:flex-end;justify-content:center}',
    '.oc-sheet{width:100%;max-width:620px;max-height:88dvh;overflow-y:auto;background:#0f2338;border:1px solid rgba(255,255,255,.1);border-radius:22px 22px 0 0;padding:14px 16px calc(20px + env(safe-area-inset-bottom))}',
    '.oc-sheet h3{margin:4px 0 2px;font-size:19px}.oc-kv{display:grid;grid-template-columns:minmax(110px,38%) minmax(0,1fr);gap:6px 10px;margin:12px 0;font-size:14px}.oc-kv dt{color:#9cb7cc}.oc-kv dd{margin:0;overflow-wrap:anywhere}',
    '#ownerGrowthCards .stat{cursor:pointer}',
    '.oc-play{border-radius:16px;padding:12px;margin:12px 0 4px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.09)}.oc-play b{display:block;font-size:15px}.oc-play small{display:block;color:#9cb7cc;font-size:12.5px;margin-top:2px}',
    '.oc-play.good{border-color:rgba(30,214,200,.45)}.oc-play.mid{border-color:rgba(255,207,92,.45)}.oc-play.low{border-color:rgba(255,107,107,.45)}',
    '.oc-strip{display:flex;gap:3px;margin-top:8px}.oc-strip i{flex:1;height:18px;border-radius:4px;min-width:8px}',
    '.oc-box{background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.09);border-radius:18px;padding:12px 12px 8px;margin-bottom:12px}.oc-box h4{margin:0 0 8px;font-size:14px}',
    '.oc-legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:#cfe3f2;margin-top:6px}.oc-legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}',
    '.oc-pick{min-height:20px;margin:6px 0 2px!important}.oc-pick .oc-chip{margin-left:6px;padding:3px 10px!important}',
    '.oc-tr{display:grid;grid-template-columns:minmax(0,1fr) minmax(120px,48%) 34px;gap:8px;align-items:center;padding:7px 12px;border-bottom:1px solid rgba(255,255,255,.07);width:100%;background:transparent!important;border-left:0!important;border-right:0!important;border-top:0!important;border-radius:0!important;color:#f4f9ff!important;text-align:left;font-weight:400!important}',
    '.oc-tr b{font-size:13.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.oc-tr .oc-strip{margin:0}.oc-tr .oc-strip i{height:14px;min-width:4px}.oc-tr em{font-style:normal;font-size:12px;color:#9cb7cc;text-align:right}',
    '.oc-tools{display:flex;gap:8px;align-items:center;margin:0 0 10px}.oc-tools input{flex:1;min-width:0;margin:0!important}.oc-tools select{flex:none;max-width:48%}',
    '.oc-ad-n{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px;color:#cfe3f2;margin-top:5px}.oc-ad-n span b{color:#fff}',
    '@media(max-width:560px){.oc-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.oc-tile b{font-size:20px}}'
  ].join('');
  document.head.appendChild(css);
  document.body.classList.add('oc');

  // ---------------------------------------------------------------- back button + phone back
  const topBar = $q('#appShell main>.top');
  if (topBar && !$q('#ocBack')) {
    const b = document.createElement('button'); b.id = 'ocBack'; b.type = 'button'; b.textContent = '‹'; b.setAttribute('aria-label', 'Back to the dashboard');
    b.onclick = () => { if (history.state && history.state.oc) history.back(); else window.showArea('dashboard'); };
    topBar.insertBefore(b, topBar.firstChild);
  }
  try { titles.people = 'People'; titles.dashboard = 'Owner Control'; titles.trends = 'Trends'; titles['tester-board'] = 'Testers board'; titles['ad-results'] = 'Ads data'; } catch (_) {}
  const OWN_AREAS = { trends: () => renderTrends(), 'tester-board': () => renderTesterBoard(), 'ad-results': () => renderAds() };
  const origShow = window.showArea;
  window.showArea = async function (area) {
    area = String(area || 'dashboard');
    const sub = area !== 'dashboard';
    document.body.classList.toggle('oc-sub', sub);
    if (sub && !(history.state && history.state.oc)) { try { history.pushState({ oc: 1 }, ''); } catch (_) {} }
    if (!sub && history.state && history.state.oc) { try { history.replaceState(null, ''); } catch (_) {} }
    if (area === 'people' || area.indexOf('people:') === 0) {
      try { currentArea = area; } catch (_) {}
      $('pageTitle').textContent = 'People'; status('');
      return renderPeople(area.slice(7) || 'all');
    }
    if (OWN_AREAS[area]) {
      try { currentArea = area; } catch (_) {}
      $('pageTitle').textContent = titles[area] || area; status('');
      return OWN_AREAS[area]();
    }
    return origShow.apply(this, arguments);
  };
  window.addEventListener('popstate', () => {
    let cur = 'dashboard'; try { cur = currentArea; } catch (_) {}
    closeSheet();
    if (cur !== 'dashboard') { document.body.classList.remove('oc-sub'); origShow('dashboard'); }
  });

  // ---------------------------------------------------------------- people and filters
  const P = { items: [], at: 0, filter: 'all', q: '' };
  const last = (p, app) => { const a = p.apps && p.apps[app]; let t = a ? a.last_seen : ''; if (app === 'futurechat' && p.fc_last && (!t || p.fc_last > t)) t = p.fc_last; return t || ''; };
  const usesSV = p => !!(p.apps && p.apps.skillvaya), usesFC = p => !!(p.apps && p.apps.futurechat);
  const within = (iso, days) => { const t = Date.parse(iso || ''); return !isNaN(t) && Date.now() - t < days * 86400000; };
  const FILTERS = [
    ['all', 'Everyone', () => true],
    ['sv', 'Skillvaya app', usesSV],
    ['fc', 'Future Chat app', usesFC],
    ['both', 'Both apps', p => usesSV(p) && usesFC(p)],
    ['noapp', 'No phone app yet', p => !usesSV(p) && !usesFC(p)],
    ['today', 'On today', p => SA(last(p, 'skillvaya')) === TODAY() || SA(last(p, 'futurechat')) === TODAY()],
    ['sv_today', 'Skillvaya today', p => SA(last(p, 'skillvaya')) === TODAY()],
    ['fc_today', 'Future Chat today', p => SA(last(p, 'futurechat')) === TODAY()],
    ['week', 'On this week', p => within(last(p, 'skillvaya'), 7) || within(last(p, 'futurechat'), 7)],
    ['new', 'New this week', p => within(p.joined, 7)],
    ['providers', 'Providers', p => p.role === 'provider'],
    ['paid', 'Paid', p => p.paid > 0],
    ['suspended', 'Suspended', p => p.role === 'suspended'],
    ['off_today', 'Not on today', p => !activeOn(p, TODAY())],
    ['off_week', 'Not on this week', p => !onWithin(p, 7)],
    ['off_month', 'Not on this month', p => !onWithin(p, 30)],
    ['testers', 'Testers', p => isTester(p)],
    ['testers_off', 'Testers not on today', p => isTester(p) && !activeOn(p, TODAY())]
  ];
  const isTester = p => P.testerIds.has(String(p.id)) || P.testerEmails.has(String(p.email || '').toLowerCase());
  const F = id => {
    id = String(id || 'all');
    let m = id.match(/^on:(\d{4}-\d\d-\d\d)(?::(sv|fc))?$/);
    if (m) { const d = m[1], a = m[2] === 'sv' ? 'skillvaya' : m[2] === 'fc' ? 'futurechat' : ''; return [id, 'On ' + niceDay(d) + (a ? (a === 'skillvaya' ? ' · Skillvaya' : ' · Future Chat') : ''), p => a ? activeApp(p, a, d) : activeOn(p, d)]; }
    m = id.match(/^joined:(\d{4}-\d\d-\d\d)$/);
    if (m) return [id, 'Joined ' + niceDay(m[1]), p => SA(p.joined) === m[1]];
    return FILTERS.find(f => f[0] === id) || FILTERS[0];
  };
  P.testers = []; P.testerIds = new Set(); P.testerEmails = new Set();
  async function people(force) {
    if (force || !P.items.length || Date.now() - P.at > 60000) {
      const d = await api('/api/tst/people'); P.items = d.items || []; P.at = Date.now();
      P.testers = d.testers || [];
      P.testerIds = new Set(P.testers.filter(t => t.user_id).map(t => String(t.user_id)));
      P.testerEmails = new Set(P.testers.map(t => String(t.email || '').toLowerCase()).filter(Boolean));
    }
    return P.items;
  }
  function badges(p) {
    const b = [];
    if (usesSV(p)) b.push('<span class="oc-b sv">Skillvaya app · ' + H(ago(last(p, 'skillvaya')) || 'opened') + '</span>');
    if (usesFC(p)) b.push('<span class="oc-b fc">Future Chat app · ' + H(ago(last(p, 'futurechat')) || 'opened') + '</span>');
    if (!b.length) b.push('<span class="oc-b none">No phone app yet</span>');
    const mt = minsDay(p, TODAY()); if (mt) b.push('<span class="oc-b fc">' + H(fmtMin(mt)) + ' today</span>');
    if (isTester(p)) b.push('<span class="oc-b gold">Tester</span>');
    if (p.role === 'provider') b.push('<span class="oc-b gold">Provider</span>');
    if (p.role === 'admin') b.push('<span class="oc-b gold">Owner</span>');
    if (p.role === 'suspended') b.push('<span class="oc-b red">Suspended</span>');
    if (p.paid > 0) b.push('<span class="oc-b gold">Paid</span>');
    return '<span class="oc-badges">' + b.join('') + '</span>';
  }
  async function renderPeople(filter) {
    P.filter = F(filter)[0];
    const panel = $('panel');
    panel.innerHTML = '<div class="panel">Loading people…</div>';
    let items; try { items = await people(true); } catch (e) { panel.innerHTML = '<div class="panel"><h2>Could not load people</h2><p>' + H(e.message) + '</p></div>'; return; }
    panel.innerHTML = '<p class="oc-note">Which phone app each person uses comes from the apps themselves (people who only used the website show as "No phone app yet"). "Today" is South African time.</p>' +
      '<div class="oc-chips" id="ocChips"></div><input id="ocQ" placeholder="Search name, email, phone or account number" autocomplete="off" style="margin:0 0 10px">' +
      '<div id="ocCount" class="oc-note"></div><div class="oc-card" id="ocList"></div>';
    $('ocQ').value = P.q;
    $('ocQ').oninput = e => { P.q = e.target.value.trim().toLowerCase(); drawPeople(); };
    drawPeople();
  }
  function drawPeople() {
    const items = P.items;
    const chipList = FILTERS.some(f => f[0] === P.filter) ? FILTERS : [F(P.filter)].concat(FILTERS);
    $('ocChips').innerHTML = chipList.map(f => '<button type="button" class="oc-chip' + (f[0] === P.filter ? ' on' : '') + '" data-f="' + f[0] + '">' + H(f[1]) + ' ' + items.filter(f[2]).length + '</button>').join('');
    $('ocChips').querySelectorAll('[data-f]').forEach(b => b.onclick = () => { P.filter = b.dataset.f; try { currentArea = 'people:' + P.filter; } catch (_) {} drawPeople(); });
    const q = P.q, list = items.filter(F(P.filter)[2]).filter(p => !q || [p.name, p.email, p.phone, p.id, p.role].some(v => String(v || '').toLowerCase().includes(q)));
    $('ocCount').textContent = list.length + (list.length === 1 ? ' person' : ' people') + ' · ' + F(P.filter)[1] + ' · tap someone to see everything about them';
    $('ocList').innerHTML = list.length ? list.slice(0, 500).map(p => '<button type="button" class="oc-row" data-id="' + p.id + '"><span class="ic">' + (p.role === 'suspended' ? '⛔' : p.role === 'provider' ? '🧰' : '👤') + '</span><span class="tx"><b>' + H(p.name || 'No name') + '</b><small>' + H([p.email, p.phone].filter(Boolean).join(' · ')) + '</small>' + badges(p) + '</span><span class="chev">›</span></button>').join('')
      : '<div class="oc-row" style="cursor:default"><span class="ic">👥</span><span class="tx"><b>Nobody here</b></span></div>';
    $('ocList').querySelectorAll('[data-id]').forEach(b => b.onclick = () => person(items.find(x => String(x.id) === b.dataset.id)));
  }
  let sheetEl = null;
  function closeSheet() { if (sheetEl) { sheetEl.remove(); sheetEl = null; } }
  function sheet(html) {
    closeSheet();
    sheetEl = document.createElement('div'); sheetEl.className = 'oc-dim';
    sheetEl.innerHTML = '<div class="oc-sheet" role="dialog" aria-modal="true">' + html + '</div>';
    sheetEl.addEventListener('click', e => { if (e.target === sheetEl) closeSheet(); });
    document.body.appendChild(sheetEl); return sheetEl;
  }
  function appRows(label, a, extraLast) {
    if (!a) return '<dt>' + label + '</dt><dd>Never opened</dd>';
    const l = extraLast && (!a.last_seen || extraLast > a.last_seen) ? extraLast : a.last_seen;
    return '<dt>' + label + '</dt><dd>Last on ' + H(day(l)) + ' (' + H(ago(l)) + ')<br>First opened ' + H(day(a.first_seen)) + (a.version ? '<br>Version ' + H(a.version) : '') +
      '<br>' + (a.from_play ? 'Installed from Google Play' : (a.installer ? 'Installed from ' + H(a.installer) : 'Install source not reported yet')) + '</dd>';
  }
  function person(p) {
    if (!p) return;
    const el = sheet('<h3>' + H(p.name || 'No name') + '</h3>' + badges(p) + timeBlock(p) +
      '<dl class="oc-kv"><dt>Account number</dt><dd>#' + H(p.id) + '</dd><dt>Email</dt><dd>' + H(p.email || '—') + '</dd><dt>Phone</dt><dd>' + H(p.phone || '—') + '</dd>' +
      '<dt>Type</dt><dd>' + H(p.role) + '</dd><dt>Account created</dt><dd>' + H(day(p.joined)) + '</dd><dt>Joined Future Chat</dt><dd>' + (p.fc_joined ? H(day(p.fc_joined)) : 'Not yet (number not confirmed)') + '</dd>' +
      appRows('Skillvaya app', p.apps && p.apps.skillvaya) + appRows('Future Chat app', p.apps && p.apps.futurechat, p.fc_last) +
      '<dt>Listings</dt><dd>' + H(p.businesses) + '</dd><dt>Verified payments</dt><dd>' + H(p.paid) + '</dd></dl>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      (p.role === 'admin' ? '<span class="oc-b gold">Protected owner account</span>' : p.role === 'suspended' ? '<button class="primary" data-x="restore">Restore access</button>' : '<button class="danger" data-x="suspend">Ban / Suspend</button>') +
      (p.businesses ? '<button data-x="listings">Open listings</button>' : '') + (p.paid ? '<button data-x="payments">Open payments</button>' : '') +
      (p.email ? '<button data-x="mail">Email</button>' : '') + '<button data-x="close">Close</button></div>');
    const on = (k, f) => { const b = el.querySelector('[data-x="' + k + '"]'); if (b) b.onclick = f; };
    on('close', closeSheet);
    on('listings', () => { closeSheet(); window.showArea('listings'); });
    on('payments', () => { closeSheet(); window.showArea('payments'); });
    on('mail', () => { location.href = 'mailto:' + p.email; });
    const access = async action => {
      let reason = '';
      if (action === 'suspend') {
        reason = prompt('Reason for banning / suspending ' + (p.name || 'this account') + ' (required and recorded):', ''); if (reason === null) return;
        if (reason.trim().length < 3) { alert('Please give a reason of at least 3 characters.'); return; }
        if (!confirm('Suspend ' + (p.name || '') + ' and sign them out everywhere? Their records and payments are kept.')) return;
      } else if (!confirm('Restore sign-in access for ' + (p.name || 'this account') + '?')) return;
      try { const d = await api('/api/admin/accounts/' + p.id + '/access', { method: 'POST', body: JSON.stringify({ action, reason }) }); status(d.message || 'Account access updated.'); closeSheet(); await people(true); drawPeople(); }
      catch (e) { alert(e.message); }
    };
    on('suspend', () => access('suspend')); on('restore', () => access('restore'));
  }

  // ---------------------------------------------------------------- OWN-CTL-02: time on + Play Store test days (person sheet)
  function strip(p, n) {
    return '<div class="oc-strip">' + dayList(n).map(d => {
      const m = minsDay(p, d), on = activeOn(p, d);
      return '<i title="' + H(niceDay(d) + ': ' + (m ? fmtMin(m) : on ? 'opened' : 'not on')) + '" style="background:' + (on ? (m >= 10 ? FCC : 'rgba(30,214,200,.45)') : 'rgba(255,255,255,.09)') + '"></i>';
    }).join('') + '</div>';
  }
  function timeBlock(p) {
    const n = activeDays(p, 14), acts = APPS.reduce((s, a) => s + sumOn(p, a[0], 14)[1], 0);
    const v = n >= 12 ? ['good', 'On track for the Play Store test'] : n >= 7 ? ['mid', 'Some days missed'] : ['low', 'Not testing enough yet'];
    const rows = APPS.map(a => { const t = sumOn(p, a[0], 1), w = sumOn(p, a[0], 7), f = sumOn(p, a[0], 14);
      return '<dt>' + a[1] + ' · time on</dt><dd>Today <b>' + fmtMin(t[0]) + '</b> · 7 days <b>' + fmtMin(w[0]) + '</b> · 14 days <b>' + fmtMin(f[0]) + '</b><br><small style="color:#9cb7cc">' + num(f[1]) + ' taps / actions in 14 days · ' + dayList(14).filter(d => activeApp(p, a[0], d)).length + ' days used</small></dd>'; }).join('');
    return '<div class="oc-play ' + v[0] + '"><b>Play Store test: used on ' + n + ' of the last 14 days</b><small>' + v[1] + ' · ' + num(acts) + ' taps / actions · oldest day on the left, today on the right</small>' + strip(p, 14) + '</div>' +
      '<dl class="oc-kv">' + rows + '</dl><p class="oc-note" style="margin-top:-6px">Time on counts every minute someone is using a phone app (from 20 Nov 2026; earlier days show only that they opened it).</p>';
  }

  // ---------------------------------------------------------------- tappable bar chart
  function chart(id, labels, series, onTap, fmt) {
    const box = $(id); if (!box) return;
    const f = fmt || num, W = 340, Hh = 118, n = labels.length, g = W / n;
    const max = Math.max(1, ...series.map(s => Math.max(0, ...s.vals.map(Number))));
    const bw = Math.max(1.2, (g * 0.8) / series.length), off = (g - bw * series.length) / 2, step = Math.max(1, Math.ceil(n / 6));
    let s = '<svg viewBox="0 0 ' + W + ' ' + (Hh + 16) + '" width="100%" role="img" style="display:block;overflow:visible">' +
      '<line x1="0" x2="' + W + '" y1="12" y2="12" stroke="rgba(255,255,255,.08)" stroke-dasharray="3 3"/><text x="2" y="9" font-size="9" fill="#9cb7cc">' + H(f(max)) + '</text>' +
      '<line x1="0" x2="' + W + '" y1="' + Hh + '" y2="' + Hh + '" stroke="rgba(255,255,255,.18)"/>';
    labels.forEach((l, i) => {
      series.forEach((se, j) => { const v = Number(se.vals[i]) || 0, bh = v ? Math.max(2, v / max * (Hh - 12)) : 0;
        if (bh) s += '<rect x="' + (i * g + off + j * bw).toFixed(1) + '" y="' + (Hh - bh).toFixed(1) + '" width="' + Math.max(1, bw - 1).toFixed(1) + '" height="' + bh.toFixed(1) + '" rx="1.5" fill="' + se.color + '"/>'; });
      if ((n - 1 - i) % step === 0) s += '<text x="' + (i * g + g / 2).toFixed(1) + '" y="' + (Hh + 12) + '" font-size="9" fill="#9cb7cc" text-anchor="middle">' + l.slice(8) + '/' + l.slice(5, 7) + '</text>';
      s += '<rect data-i="' + i + '" x="' + (i * g).toFixed(1) + '" y="0" width="' + g.toFixed(1) + '" height="' + (Hh + 16) + '" fill="transparent" style="cursor:pointer"></rect>';
    });
    s += '</svg>';
    const tot = se => se.vals.reduce((a, b) => a + (Number(b) || 0), 0);
    box.innerHTML = s + '<div class="oc-legend">' + series.map(se => '<span><i style="background:' + se.color + '"></i>' + H(se.name) + ' · ' + H(f(tot(se))) + ' in total</span>').join('') + '</div>' +
      '<div class="oc-pick oc-note">' + (onTap ? 'Tap a day to see its numbers and who it was' : 'Tap a day to see its numbers') + '</div>';
    const pick = box.querySelector('.oc-pick');
    box.querySelectorAll('rect[data-i]').forEach(r => r.addEventListener('click', () => {
      const i = Number(r.dataset.i);
      box.querySelectorAll('rect[data-i]').forEach(x => x.setAttribute('fill', 'transparent')); r.setAttribute('fill', 'rgba(255,255,255,.07)');
      pick.innerHTML = '<b style="color:#fff">' + H(niceDay(labels[i])) + '</b> · ' + series.map(se => H(se.name) + ' <b style="color:#fff">' + H(f(se.vals[i] || 0)) + '</b>').join(' · ') + (onTap ? '<button type="button" class="oc-chip" data-open>See who ›</button>' : '');
      const o = pick.querySelector('[data-open]'); if (o) o.onclick = () => onTap(labels[i]);
    }));
  }
  const chips = (list, cur, attr) => '<div class="oc-chips">' + list.map(c => '<button type="button" class="oc-chip' + (String(c[0]) === String(cur) ? ' on' : '') + '" data-' + attr + '="' + c[0] + '">' + H(c[1]) + '</button>').join('') + '</div>';
  const fail = (panel, what, e) => { panel.innerHTML = '<div class="panel"><h2>Could not load ' + H(what) + '</h2><p>' + H(e && e.message || 'Please try again.') + '</p></div>'; };

  // ---------------------------------------------------------------- Trends
  const TR = { days: 30 };
  async function renderTrends() {
    const panel = $('panel'); panel.innerHTML = '<div class="panel">Loading trends…</div>';
    let pp; try { pp = await people(true); } catch (e) { return fail(panel, 'trends', e); }
    const L = dayList(TR.days);
    const sv = L.map(d => pp.filter(p => activeApp(p, 'skillvaya', d)).length), fc = L.map(d => pp.filter(p => activeApp(p, 'futurechat', d)).length);
    const any = L.map(d => pp.filter(p => activeOn(p, d)).length), joined = L.map(d => pp.filter(p => SA(p.joined) === d).length);
    const mins = L.map(d => pp.reduce((s, p) => s + minsDay(p, d), 0));
    const best = any.indexOf(Math.max(...any)), avg = any.reduce((a, b) => a + b, 0) / L.length;
    const used = pp.filter(p => L.some(d => activeOn(p, d))).length, minTot = mins.reduce((a, b) => a + b, 0);
    panel.innerHTML = chips([[7, 'Last 7 days'], [14, '14 days'], [30, '30 days']], TR.days, 'td') +
      '<div class="oc-tiles" style="margin-bottom:12px">' + tile(avg.toFixed(1), 'People on per day (average)', 'people:week') + tile(any[best] || 0, 'Best day · ' + niceDay(L[best]), 'people:on:' + L[best]) +
      tile(used, 'Different people on in ' + TR.days + ' days', 'people:week') + tile(joined.reduce((a, b) => a + b, 0), 'New accounts in ' + TR.days + ' days', 'people:new') +
      tile(fmtMin(minTot), 'Total time on (phone apps)', 'people:today') + tile(used ? fmtMin(minTot / used) : '0 min', 'Average time per person', 'people:week') + '</div>' +
      '<div class="oc-box"><h4>People on each day, by app</h4><div id="ocT1"></div></div>' +
      '<div class="oc-box"><h4>Everyone on (any app)</h4><div id="ocT2"></div></div>' +
      '<div class="oc-box"><h4>New accounts each day</h4><div id="ocT3"></div></div>' +
      '<div class="oc-box"><h4>Time on each day (all people)</h4><div id="ocT4"></div></div>' +
      '<p class="oc-note">Use this to see what brings people back: compare days before and after an advert, a message or an update. Time on is counted from 20 Nov 2026.</p>';
    wireGo(panel);
    panel.querySelectorAll('[data-td]').forEach(b => b.onclick = () => { TR.days = Number(b.dataset.td); renderTrends(); });
    chart('ocT1', L, [{ name: 'Skillvaya app', color: SVC, vals: sv }, { name: 'Future Chat app', color: FCC, vals: fc }], d => window.showArea('people:on:' + d));
    chart('ocT2', L, [{ name: 'People on', color: '#ffcf5c', vals: any }], d => window.showArea('people:on:' + d));
    chart('ocT3', L, [{ name: 'New accounts', color: '#c7a6ff', vals: joined }], d => window.showArea('people:joined:' + d));
    chart('ocT4', L, [{ name: 'Time on', color: FCC, vals: mins }], d => window.showArea('people:on:' + d), fmtMin);
  }

  // ---------------------------------------------------------------- Testers board (the Play Store test list)
  async function renderTesterBoard() {
    const panel = $('panel'); panel.innerHTML = '<div class="panel">Loading testers…</div>';
    let pp; try { pp = await people(true); } catch (e) { return fail(panel, 'testers', e); }
    const T = TODAY(), L = dayList(14);
    const list = P.testers.map(t => ({ t, p: pp.find(p => (t.user_id && String(p.id) === String(t.user_id)) || (t.email && String(p.email || '').toLowerCase() === String(t.email).toLowerCase())) }));
    const acc = list.filter(x => x.p), noAcc = list.filter(x => !x.p);
    const onT = acc.filter(x => activeOn(x.p, T)), offT = acc.filter(x => !activeOn(x.p, T));
    const offW = acc.filter(x => !onWithin(x.p, 7)), never = acc.filter(x => !usesSV(x.p) && !usesFC(x.p) && !L.some(d => activeOn(x.p, d)));
    const track = acc.filter(x => activeDays(x.p, 14) >= 12);
    const perDay = L.map(d => acc.filter(x => activeOn(x.p, d)).length);
    const sorted = acc.slice().sort((a, b) => activeDays(b.p, 14) - activeDays(a.p, 14) || String(a.p.name).localeCompare(String(b.p.name)));
    const trow = x => '<button type="button" class="oc-tr" data-id="' + x.p.id + '"><b>' + H(x.p.name || x.p.email || 'No name') + '</b>' + strip(x.p, 14) + '<em>' + activeDays(x.p, 14) + '/14</em></button>';
    const prow = x => '<button type="button" class="oc-row" data-id="' + x.p.id + '"><span class="ic">🧪</span><span class="tx"><b>' + H(x.p.name || 'No name') + '</b><small>' + H([x.p.email, x.p.phone].filter(Boolean).join(' · ')) + ' · last on ' + H(ago(lastAny(x.p)) || 'never') + '</small></span><span class="chev">›</span></button>';
    panel.innerHTML = '<div class="oc-tiles" style="margin-bottom:12px">' +
      tile(list.length, 'Testers on the list', 'people:testers') + tile(onT.length, 'On today', 'people:testers', 'fc') + tile(offT.length, 'Not on today', 'people:testers_off', offT.length ? 'warn' : '') +
      tile(offW.length, 'Not on this week', '#offw', offW.length ? 'warn' : '') + tile(never.length + noAcc.length, 'Never opened / no account', '#never', (never.length + noAcc.length) ? 'warn' : '') +
      tile(track.length, 'On track (12+ of 14 days)', 'people:testers') + '</div>' +
      '<div class="oc-box"><h4>Testers on each day (last 14 days)</h4><div id="ocTB"></div></div>' +
      '<div class="oc-gl">Every tester · 14 days, oldest on the left</div><div class="oc-card">' + (sorted.length ? sorted.map(trow).join('') : '<div class="oc-row"><span class="tx"><b>No testers have accounts yet</b></span></div>') + '</div>' +
      '<div class="oc-gl" id="ocOffT">Not on today · ' + offT.length + '</div><div class="oc-card">' + (offT.length ? offT.map(prow).join('') : '<div class="oc-row"><span class="ic">✅</span><span class="tx"><b>Every tester has been on today</b></span></div>') + '</div>' +
      '<div class="oc-gl" id="ocOffW">Not on this week · ' + offW.length + '</div><div class="oc-card">' + (offW.length ? offW.map(prow).join('') : '<div class="oc-row"><span class="ic">✅</span><span class="tx"><b>Everyone has been on this week</b></span></div>') + '</div>' +
      (noAcc.length || never.length ? '<div class="oc-gl" id="ocNever">Never opened an app / no account · ' + (never.length + noAcc.length) + '</div><div class="oc-card">' + never.map(prow).join('') +
        noAcc.map(x => '<div class="oc-row"><span class="ic">✉</span><span class="tx"><b>' + H(x.t.email || 'Unknown') + '</b><small>On the tester list but no account with this email yet</small></span></div>').join('') + '</div>' : '') +
      '<p class="oc-note">Google Play wants testers using the app every day for 14 days. Green = used that day (bright green = 10 minutes or more), grey = not on.</p>';
    panel.querySelectorAll('[data-go]').forEach(b => b.onclick = () => {
      const g = b.dataset.go;
      if (g === '#offw') { const e = $('ocOffW'); if (e) e.scrollIntoView({ behavior: 'smooth' }); }
      else if (g === '#never') { const e = $('ocNever') || $('ocOffW'); if (e) e.scrollIntoView({ behavior: 'smooth' }); }
      else window.showArea(g);
    });
    panel.querySelectorAll('[data-id]').forEach(b => b.onclick = () => person(pp.find(p => String(p.id) === b.dataset.id)));
    chart('ocTB', L, [{ name: 'Testers on', color: FCC, vals: perDay }], d => window.showArea('people:on:' + d));
  }
  const lastAny = p => { const a = last(p, 'skillvaya'), b = last(p, 'futurechat'); return a > b ? a : b; };

  // ---------------------------------------------------------------- Advertising results (HA-STATS-01)
  const AD = { d: null, days: 30, st: 'all', ty: 'all', sort: 'new', q: '', metric: 'views' };
  const adType = a => (a.tier === 'shout' || a.tier === 'propose') ? 'shout' : a.fc ? 'fc' : 'home';
  const TYPE_NAME = { fc: 'Future Chat Status ad', home: 'Skillvaya home ad', shout: 'Shout-out / proposal' };
  const stOf = a => a.status === 'active' ? 'active' : (a.status === 'queued' || a.status === 'paused') ? 'wait' : 'ended';
  const ST_NAME = { active: 'Running', wait: 'Waiting / paused', ended: 'Ended' };
  const SORTS = [['new', 'Newest first'], ['reach', 'Most people reached'], ['views', 'Most views'], ['clicks', 'Most clicks'], ['ctr', 'Best click rate'], ['likes', 'Most likes'], ['shares', 'Most shares']];
  const METRICS = [['views', 'Views'], ['reach', 'People reached'], ['clicks', 'Clicks'], ['likes', 'Likes'], ['shares', 'Shares']];
  const MCOL = { views: FCC, reach: '#ffcf5c', clicks: SVC, likes: '#ff8fb1', shares: '#c7a6ff' };
  const sOf = a => a.stats || {};
  const sortVal = (a, k) => k === 'new' ? Number(a.id) : k === 'ctr' ? (sOf(a).views ? sOf(a).clicks / sOf(a).views : 0) : Number(sOf(a)[k] || 0);
  const price = a => Number(String(a.price || '').replace(/[^\d.]/g, '')) || 0;
  function adList() {
    const q = AD.q.toLowerCase();
    return (AD.d.items || []).filter(a => (AD.st === 'all' || stOf(a) === AD.st) && (AD.ty === 'all' || adType(a) === AD.ty) &&
      (!q || [a.headline, a.body, a.advertiser, a.owner_name, a.owner_email, a.id].some(v => String(v || '').toLowerCase().includes(q))))
      .sort((a, b) => sortVal(b, AD.sort) - sortVal(a, AD.sort));
  }
  async function renderAds(keep) {
    const panel = $('panel');
    if (window.AdsData) { panel.innerHTML = ''; return window.AdsData.open(panel, api); }   // ADS-DATA-01: shared Ads data screen (same in Future Chat Control)
    if (!keep || !AD.d) {
      panel.innerHTML = '<div class="panel">Loading advert results…</div>';
      try { AD.d = await api('/api/admin/ad-stats?days=' + AD.days); } catch (e) { return fail(panel, 'advert results', e); }
    }
    const L = AD.d.labels || [], list = adList(), S = k => list.reduce((s, a) => s + Number(sOf(a)[k] || 0), 0);
    const tv = S('views'), tc = S('clicks');
    panel.innerHTML = '<p class="oc-note">Every advert, shout-out and proposal with who it reached. Totals are for the whole run of each advert; the charts show the last ' + AD.days + ' days. Detailed counting (reach, likes, shares, different people) started on 20 Nov 2026.</p>' +
      chips([['all', 'All'], ['active', 'Running'], ['wait', 'Waiting / paused'], ['ended', 'Ended']], AD.st, 'ast') +
      chips([['all', 'All types'], ['fc', 'Future Chat Status ads'], ['home', 'Skillvaya home ads'], ['shout', 'Shout-outs & proposals']], AD.ty, 'aty') +
      '<div class="oc-tools"><input id="ocAdQ" placeholder="Search advertiser, headline or owner" autocomplete="off"><select id="ocAdSort">' + SORTS.map(s => '<option value="' + s[0] + '"' + (s[0] === AD.sort ? ' selected' : '') + '>' + s[1] + '</option>').join('') + '</select></div>' +
      '<div class="oc-tiles" style="margin-bottom:12px">' +
      tile(list.length, 'Adverts', '#list') + tile(num(S('reach')), 'People reached (added up per advert)', '#list', 'fc') + tile(num(tv), 'Views', '#views') +
      tile(num(tc), 'Clicks · ' + pct(tc, tv) + ' click rate', '#clicks', 'sv') + tile(num(S('people_clicked')), 'Different people who clicked', '#clicks') + tile(num(S('likes')), 'Likes', '#likes') +
      tile(num(S('shares')), 'Shares · ' + num(S('people_shared')) + ' people', '#shares') + tile(num(S('views_fc')) + ' / ' + num(S('views_home')), 'Views: Future Chat Status / Skillvaya home', '#views') +
      tile('R' + num(list.reduce((s, a) => s + price(a), 0)), 'Paid for these adverts', '#list') + '</div>' +
      '<div class="oc-box"><h4>All these adverts together, per day</h4>' + chips([[7, '7 days'], [30, '30 days'], [90, '90 days']], AD.days, 'adays') + chips(METRICS, AD.metric, 'am') + '<div id="ocAdAll"></div></div>' +
      '<div class="oc-tools"><button type="button" id="ocAdCsv">⬇ Download report (CSV, opens in Excel)</button></div>' +
      '<div class="oc-gl" id="ocAdL">' + list.length + ' adverts · tap one for its full report</div><div class="oc-card">' + (list.length ? list.map(a => {
        const s = sOf(a);
        return '<button type="button" class="oc-row" data-ad="' + a.id + '"><span class="ic">' + (adType(a) === 'shout' ? '🎉' : adType(a) === 'fc' ? '📢' : '🏠') + '</span><span class="tx"><b>' + H(a.headline || a.advertiser || 'Advert #' + a.id) + '</b><small>' + H([a.advertiser, TYPE_NAME[adType(a)], ST_NAME[stOf(a)], a.plan].filter(Boolean).join(' · ')) + '</small>' +
          '<span class="oc-ad-n"><span>👥 <b>' + num(s.reach) + '</b> reached</span><span>👁 <b>' + num(s.views) + '</b></span><span>👆 <b>' + num(s.clicks) + '</b> (' + pct(s.clicks, s.views) + ')</span><span>❤ <b>' + num(s.likes) + '</b></span><span>↗ <b>' + num(s.shares) + '</b></span></span></span><span class="chev">›</span></button>';
      }).join('') : '<div class="oc-row"><span class="ic">📣</span><span class="tx"><b>No adverts match</b><small>Try another filter</small></span></div>') + '</div>';
    const q = $('ocAdQ'); q.value = AD.q; q.oninput = e => { AD.q = e.target.value.trim(); clearTimeout(AD.t); AD.t = setTimeout(() => { renderAds(true); const n = $('ocAdQ'); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }, 350); };
    $('ocAdSort').onchange = e => { AD.sort = e.target.value; renderAds(true); };
    panel.querySelectorAll('[data-ast]').forEach(b => b.onclick = () => { AD.st = b.dataset.ast; renderAds(true); });
    panel.querySelectorAll('[data-aty]').forEach(b => b.onclick = () => { AD.ty = b.dataset.aty; renderAds(true); });
    panel.querySelectorAll('[data-adays]').forEach(b => b.onclick = () => { AD.days = Number(b.dataset.adays); renderAds(); });
    panel.querySelectorAll('[data-am]').forEach(b => b.onclick = () => { AD.metric = b.dataset.am; renderAds(true); });
    panel.querySelectorAll('[data-go]').forEach(b => b.onclick = () => {
      const g = b.dataset.go.slice(1);
      if (g !== 'list') AD.metric = g;
      if (g === 'list') { const e = $('ocAdL'); if (e) e.scrollIntoView({ behavior: 'smooth' }); } else renderAds(true);
    });
    panel.querySelectorAll('[data-ad]').forEach(b => b.onclick = () => adSheet(list.find(a => String(a.id) === b.dataset.ad)));
    $('ocAdCsv').onclick = () => download('advert-results-' + TODAY() + '.csv', csvAll(list));
    const m = AD.metric, name = (METRICS.find(x => x[0] === m) || METRICS[0])[1];
    chart('ocAdAll', L, [{ name, color: MCOL[m], vals: L.map(d => list.reduce((s, a) => s + Number(((sOf(a).series || {})[d] || {})[m] || 0), 0)) }]);
  }
  function adSheet(a) {
    if (!a) return;
    const s = sOf(a), freq = s.reach ? (s.views / s.reach).toFixed(1) : '—';
    const eng = s.reach ? pct((s.people_clicked || 0) + (s.people_liked || 0) + (s.people_shared || 0), s.reach) : '—';
    const el = sheet('<h3>' + H(a.headline || a.advertiser || 'Advert #' + a.id) + '</h3><span class="oc-badges"><span class="oc-b fc">' + H(TYPE_NAME[adType(a)]) + '</span><span class="oc-b ' + (stOf(a) === 'active' ? 'fc' : stOf(a) === 'wait' ? 'gold' : 'none') + '">' + H(ST_NAME[stOf(a)]) + '</span></span>' +
      '<div class="oc-tiles" style="margin-top:12px">' + tile(num(s.reach), 'Different people reached', '#reach', 'fc') + tile(num(s.views), 'Views (' + freq + ' per person)', '#views') +
      tile(num(s.clicks), 'Clicks · ' + pct(s.clicks, s.views), '#clicks', 'sv') + tile(num(s.people_clicked), 'Different people who clicked', '#clicks') +
      tile(num(s.likes), 'Likes', '#likes') + tile(num(s.shares) + ' · ' + num(s.people_shared) + ' ppl', 'Shares · people who shared', '#shares') + '</div>' +
      '<div class="oc-box" style="margin-top:12px"><h4>Per day (last ' + AD.days + ' days)</h4>' + chips(METRICS, 'views', 'sm') + '<div id="ocAdOne"></div></div>' +
      '<dl class="oc-kv"><dt>Advertiser</dt><dd>' + H(a.advertiser || '—') + '</dd><dt>Bought by</dt><dd>' + H([a.owner_name, a.owner_email].filter(Boolean).join(' · ') || '—') + '</dd>' +
      '<dt>Plan</dt><dd>' + H([a.plan, a.price].filter(Boolean).join(' · ') || '—') + '</dd><dt>Ran</dt><dd>' + H(day(a.starts_at)) + ' → ' + H(day(a.ends_at)) + '</dd>' +
      '<dt>Where it was seen</dt><dd>Future Chat Status ' + num(s.views_fc) + ' · Skillvaya home ' + num(s.views_home) + '</dd>' +
      '<dt>Who it reached</dt><dd>Future Chat app users ' + num((s.reach_apps || {}).futurechat) + ' · Skillvaya app users ' + num((s.reach_apps || {}).skillvaya) + '</dd>' +
      '<dt>Engagement</dt><dd>' + eng + ' of the people reached clicked, liked or shared</dd>' +
      (a.target ? '<dt>Link</dt><dd>' + H(a.target) + '</dd>' : '') + (a.body ? '<dt>Text</dt><dd>' + H(a.body) + '</dd>' : '') + '</dl>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap"><button class="primary" data-x="csv">⬇ Report for the company (CSV)</button><button data-x="copy">Copy summary</button>' + (navigator.share ? '<button data-x="share">Share summary</button>' : '') + '<button data-x="manage">Open in Advertising</button><button data-x="close">Close</button></div>');
    const L = AD.d.labels || [], ser = s.series || {};
    const draw = m => chart('ocAdOne', L, [{ name: (METRICS.find(x => x[0] === m) || METRICS[0])[1], color: MCOL[m], vals: L.map(d => (ser[d] || {})[m] || 0) }]);
    el.querySelectorAll('[data-sm]').forEach(b => b.onclick = () => { el.querySelectorAll('[data-sm]').forEach(x => x.classList.toggle('on', x === b)); draw(b.dataset.sm); });
    draw('views');
    el.querySelectorAll('[data-go]').forEach(b => b.onclick = () => { const c = el.querySelector('[data-sm="' + b.dataset.go.slice(1) + '"]'); if (c) { c.click(); c.scrollIntoView({ behavior: 'smooth', block: 'center' }); } });
    const text = adText(a), on = (k, f) => { const b = el.querySelector('[data-x="' + k + '"]'); if (b) b.onclick = f; };
    on('close', closeSheet);
    on('manage', () => { closeSheet(); window.showArea('owner-promotions'); });
    on('csv', () => download('advert-' + a.id + '-report-' + TODAY() + '.csv', csvOne(a)));
    on('copy', async () => { try { await navigator.clipboard.writeText(text); status('Summary copied.'); } catch (_) { prompt('Copy this summary:', text); } });
    on('share', () => navigator.share({ title: 'Advert report', text }).catch(() => {}));
  }
  function adText(a) {
    const s = sOf(a);
    return 'Advert report: ' + (a.headline || 'Advert #' + a.id) + (a.advertiser ? ' (' + a.advertiser + ')' : '') + '\n' +
      'Ran: ' + day(a.starts_at) + ' to ' + day(a.ends_at) + '\n' +
      'People reached: ' + num(s.reach) + '\nViews: ' + num(s.views) + ' (Future Chat Status ' + num(s.views_fc) + ', Skillvaya home ' + num(s.views_home) + ')\n' +
      'Clicks: ' + num(s.clicks) + ' by ' + num(s.people_clicked) + ' different people · click rate ' + pct(s.clicks, s.views) + '\n' +
      'Likes: ' + num(s.likes) + '\nShares: ' + num(s.shares) + ' by ' + num(s.people_shared) + ' people\n' +
      'Figures from Skillvaya / Future Chat on ' + niceDay(TODAY()) + '. Detailed counting since 20 Nov 2026.';
  }
  const cq = v => { v = String(v == null ? '' : v); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const csvRow = r => r.map(cq).join(',');
  const HEAD = ['Advert ID', 'Advertiser', 'Headline', 'Type', 'Status', 'Plan', 'Price', 'Started', 'Ends', 'People reached', 'Views', 'Views Future Chat Status', 'Views Skillvaya home',
    'Reached Future Chat app users', 'Reached Skillvaya app users', 'Clicks', 'Different people who clicked', 'Click rate', 'Likes', 'Shares', 'Different people who shared', 'Bought by', 'Owner email'];
  const adCells = a => { const s = sOf(a); return [a.id, a.advertiser, a.headline, TYPE_NAME[adType(a)], ST_NAME[stOf(a)], a.plan, a.price, (a.starts_at || '').slice(0, 10), (a.ends_at || '').slice(0, 10),
    s.reach || 0, s.views || 0, s.views_fc || 0, s.views_home || 0, (s.reach_apps || {}).futurechat || 0, (s.reach_apps || {}).skillvaya || 0, s.clicks || 0, s.people_clicked || 0, pct(s.clicks, s.views), s.likes || 0, s.shares || 0, s.people_shared || 0, a.owner_name, a.owner_email]; };
  const csvAll = list => [csvRow(HEAD)].concat(list.map(a => csvRow(adCells(a)))).join('\r\n');
  const csvOne = a => { const ser = sOf(a).series || {};
    return [csvRow(HEAD), csvRow(adCells(a)), '', csvRow(['Day', 'Views', 'People reached', 'Clicks', 'Likes', 'Shares'])]
      .concat((AD.d.labels || []).map(d => { const v = ser[d] || {}; return csvRow([d, v.views || 0, v.reach || 0, v.clicks || 0, v.likes || 0, v.shares || 0]); })).join('\r\n'); };
  function download(name, text) {
    try {
      const url = URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000); status('Report downloaded: ' + name);
    } catch (e) { alert('Could not download the report: ' + e.message); }
  }

  // ---------------------------------------------------------------- the new dashboard
  const tile = (n, label, go, cls) => '<button type="button" class="oc-tile ' + (cls || '') + '" data-go="' + go + '"><b>' + H(n) + '</b><span>' + H(label) + '</span></button>';
  const row = (ic, title, sub, go, cls) => '<button type="button" class="oc-row ' + (cls || '') + '" data-go="' + go + '"><span class="ic">' + ic + '</span><span class="tx"><b>' + H(title) + '</b>' + (sub ? '<small>' + H(sub) + '</small>' : '') + '</span><span class="chev">›</span></button>';
  const SECTIONS = [
    ['👥', 'People', 'Everyone, which app they use, time on and when they were last on', 'people:all'],
    ['📈', 'Trends', 'People on each day per app, new accounts and time on · tap any day', 'trends'],
    ['📣', 'Ads data', 'Money made, who posted adverts, reach, clicks, likes, shares and who did them · reports for companies', 'ad-results'],
    ['🧪', 'Testers board', 'The Play Store test list: who was on each day and who has not been on', 'tester-board'],
    ['♙', 'Customers & Providers', 'Search accounts · ban / suspend or restore', 'clients'],
    ['✔', 'Listings & Verification', 'Approve verified badges, suspend or restore listings', 'listings'],
    ['⚑', 'Reports & Complaints', 'Review and resolve reports', 'complaints'],
    ['▤', 'Payments & Subscriptions', 'Payment records and confirmations', 'payments'],
    ['✧', 'Advertising & Promotions', 'Your businesses, ads and campaigns', 'owner-promotions'],
    ['✉', 'Email Centre & Inbox', 'Notifications, audit records and email', 'inbox'],
    ['🧾', 'Tester sign-ups', 'The original testers screen and tester reminders', 'testers'],
    ['💬', 'Future Chat Launch', 'Waiting list and launch announcement', 'futurechat'],
    ['🗑', 'Account deletion requests', 'Requests to delete accounts', 'account-deletions'],
    ['🔒', 'Customer & Provider Access', 'Who can use which features', 'accessControl'],
    ['⚙', 'Platform Settings', 'Owner email and platform settings', 'settings']
  ];
  function wireGo(root) {
    root.querySelectorAll('[data-go]').forEach(b => b.onclick = () => {
      const g = b.dataset.go;
      if (g === 'app') location.href = '/customer-app';
      else if (g === 'logout') { if (confirm('Sign out of Owner Control?')) ownerLogout(); }
      else window.showArea(g);
    });
  }
  window.renderDashboard = async function () {
    const panel = $('panel');
    panel.innerHTML = '<div class="panel">Loading your dashboard…</div>';
    const safe = (p, fb) => Promise.race([p.catch(() => fb), new Promise(r => setTimeout(() => r(fb), 8000))]);
    const [s, a, pp, ads] = await Promise.all([safe(api('/api/admin/summary'), {}), safe(api('/api/admin/analytics'), { stats: {} }), safe(people(true), []), safe(api('/api/admin/ad-stats?days=30'), null)]);
    const x = a.stats || {}, cnt = id => pp.filter(F(id)[2]).length, dash = v => (v == null ? '—' : v);
    if (ads && ads.items) { AD.d = ads; AD.days = 30; }
    const ai = (ads && ads.items) || [], aS = k => ai.reduce((t, i) => t + Number(sOf(i)[k] || 0), 0);
    const tst = pp.filter(isTester), tOn = tst.filter(p => activeOn(p, TODAY())).length;
    panel.innerHTML =
      '<div class="oc-gl">People · tap a number to see who</div><div class="oc-tiles">' +
      tile(pp.length || dash(x.accounts), 'All accounts', 'people:all') + tile(cnt('sv'), 'Use the Skillvaya app', 'people:sv', 'sv') + tile(cnt('fc'), 'Use the Future Chat app', 'people:fc', 'fc') +
      tile(cnt('both'), 'Use both apps', 'people:both') + tile(cnt('today'), 'On today (any app)', 'people:today') + tile(cnt('sv_today'), 'On Skillvaya today', 'people:sv_today', 'sv') +
      tile(cnt('fc_today'), 'On Future Chat today', 'people:fc_today', 'fc') + tile(cnt('new'), 'New this week', 'people:new') + tile(cnt('noapp'), 'No phone app yet', 'people:noapp') + '</div>' +
      '<div class="oc-gl">Not been on · the offline lists</div><div class="oc-tiles">' +
      tile(cnt('off_today'), 'Not on today', 'people:off_today', 'warn') + tile(cnt('off_week'), 'Not on this week', 'people:off_week', 'warn') + tile(cnt('off_month'), 'Not on this month', 'people:off_month', 'warn') + '</div>' +
      '<div class="oc-gl">Play Store testers</div><div class="oc-tiles">' +
      tile(P.testers.length, 'Testers on the list', 'tester-board') + tile(tOn, 'Testers on today', 'tester-board', 'fc') + tile(P.testers.length - tOn, 'Testers not on today (incl. no account)', 'tester-board', (P.testers.length - tOn) ? 'warn' : '') + '</div>' +
      '<div class="oc-gl">Ads data · tap any number</div><div class="oc-tiles">' +
      tile('R' + num((ads && ads.money || {}).total), 'Money made from adverts', 'ad-results', 'warn') + tile('R' + num((ads && ads.money || {}).month), 'Ad money this month', 'ad-results', 'warn') +
      tile(num(((ads && ads.advertisers) || []).length), 'People who posted adverts', 'ad-results') + tile(num((ads && ads.posted || {}).total), 'Adverts posted', 'ad-results') +
      tile(ai.filter(i => i.status === 'active').length, 'Adverts running', 'ad-results') + tile(num(aS('reach')), 'People reached', 'ad-results', 'fc') + tile(num(aS('views')), 'Advert views', 'ad-results') +
      tile(num(aS('clicks')), 'Advert clicks · ' + pct(aS('clicks'), aS('views')), 'ad-results', 'sv') + tile(num(aS('likes')), 'Advert likes', 'ad-results') + tile(num(aS('shares')), 'Advert shares', 'ad-results') + '</div>' +
      '<div class="oc-card" style="margin-top:10px">' + row('📈', 'Trends', 'Tap any day to see who was on', 'trends') + '</div>' +
      '<div class="oc-gl">Business · tap to open</div><div class="oc-tiles">' +
      tile(dash(x.providers), 'Providers', 'people:providers') + tile(dash(s.businesses), 'Listings', 'listings') + tile(dash(s.pending), 'Listings waiting for you', 'listings', s.pending ? 'warn' : '') +
      tile(dash(s.complaints), 'Open complaints', 'complaints', s.complaints ? 'warn' : '') + tile(dash(s.payments), 'Payments to confirm', 'payments', s.payments ? 'warn' : '') + tile(dash(x.verified_payments), 'Verified payments', 'payments') +
      tile('R' + Number(x.revenue || 0).toLocaleString('en-ZA'), 'Verified revenue', 'payments') + tile(cnt('paid'), 'Paid customers', 'people:paid') + tile(cnt('suspended'), 'Suspended accounts', 'people:suspended') + '</div>' +
      '<div class="oc-gl">More numbers</div><div class="cards" id="ownerGrowthCards" style="margin:0"></div>' +
      '<div class="oc-gl">Manage</div><div class="oc-card">' + SECTIONS.map(r => row(r[0], r[1], r[2], r[3])).join('') + '</div>' +
      '<div class="oc-card">' + row('👁', 'View the customer app', 'See Skillvaya the way customers see it', 'app') + row('🚪', 'Sign out', 'Private owner access', 'logout', 'danger') + '</div>' +
      '<p class="oc-note">High-impact account actions need a reason and confirmation. Account records and payment history are kept.</p>';
    wireGo(panel);
    try {
      await ownerGrowthStats();
      const g = $('ownerGrowthCards'), go = ['listings', 'listings', 'futurechat', 'listings'];
      if (g) Array.from(g.children).forEach((c, i) => { c.setAttribute('role', 'button'); c.onclick = () => window.showArea(go[i] || 'listings'); });
    } catch (_) {}
  };
  // The dashboard may already be showing the old layout if this file loaded after the owner signed in.
  try { if (currentArea === 'dashboard' && !$q('#appShell').classList.contains('hidden')) window.renderDashboard(); } catch (_) {}
})();
