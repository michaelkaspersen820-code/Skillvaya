/* FCP-01: Future Chat shop for everyone (owner 2026-11-19).
   Shout-outs and proposals in Sponsored status, premium greeting cards (animated, tune, voice message), event invitations
   with RSVP, chat theme packs (52 themes), quiz packs, Future Chat Plus (HD video calls, files up to 48 MB, unlimited
   scheduled messages, stokvel record). Payments: Google Play in the Future Chat app (window.SkillvayaBilling). Server: fcpay.py. */
(function () {
  'use strict';
  const FCX = window.FCX; if (!window.SV_FC_APP || !FCX || !FCX.kit) return;
  const K = FCX.kit, { api, post, esc, $, toast, sheet, avatar, when, frame, push, pop, go, row, bind, openPanel, X, FC } = K;
  const tok = () => { try { return localStorage.getItem('skillvaya_token') || localStorage.getItem('sv_token') || ''; } catch (_) { return ''; } };
  const top = () => X.stack[X.stack.length - 1];
  const P = FCX.shop = { me: null, play: {} };
  const curConv = () => { try { const st = FC().state(); if (!st || !st.conv) return null; return (st.list || []).find(c => c.id === st.conv) || { id: st.conv, title: '' }; } catch (_) { return null; } };
  const chats = () => { try { return (FC().state().list || []).filter(c => !c.archived); } catch (_) { return []; } };
  const refreshChat = () => { try { FC().refreshMsgs(); } catch (_) {} };

  async function loadShop() {
    try { P.me = await api('/api/fcp/me'); window.FCX_HD = !!P.me.plus; } catch (_) {}
    if (bill()) { try { window.SkillvayaBilling.queryShop && window.SkillvayaBilling.queryShop((P.me && P.me.catalog || []).map(x => x.product_id).join(',')); if (!P.restored && window.SkillvayaBilling.restoreShop) { P.restored = true; window.SkillvayaBilling.restoreShop(String((X.me || {}).id || ''), tok()); } } catch (_) {} }
    applyTheme(curTheme());
    return P.me;
  }
  const bill = () => !!(window.SkillvayaBilling && typeof window.SkillvayaBilling.buy === 'function');
  const price = id => P.play[id] || ((P.me && P.me.catalog || []).find(x => x.product_id === id) || {}).price || '';
  window.fcpProducts = json => { try { (JSON.parse(json || '[]') || []).forEach(p => { P.play[p.productId] = p.price; }); } catch (_) {} document.querySelectorAll('[data-fcpprice]').forEach(el => { const v = P.play[el.dataset.fcpprice]; if (v) el.textContent = v; }); };
  let pending = null;
  window.fcpError = msg => { toast(msg || 'Google Play payment did not complete.'); const p = pending; pending = null; if (p) p(false); };
  window.fcpResult = async json => { let r = {}; try { r = typeof json === 'string' ? JSON.parse(json) : (json || {}); } catch (_) {}
    if (r.ok) { if (r.me) { P.me = Object.assign(P.me || {}, r.me); window.FCX_HD = !!P.me.plus; } else await loadShop(); toast(r.message || 'Thank you! ✨'); }
    else toast(r.cancelled ? 'Payment cancelled. You were not charged.' : (r.message || r.error || 'The payment could not be confirmed yet.'));
    const p = pending; pending = null; if (p) p(!!r.ok); };
  /** buy(productId) -> resolves true when it's yours (owner: always true, free) */
  function buy(pid) {
    return new Promise(res => {
      if (P.me && P.me.owner) { res(true); return; }
      if (!bill()) { toast('Update Future Chat from Google Play to buy this'); res(false); return; }
      pending = res;
      try { window.SkillvayaBilling.buy(pid, String((X.me || {}).id || ''), tok()); } catch (_) { pending = null; res(false); }
    });
  }
  P.buy = buy;
  const has = what => !!(P.me && (P.me.unlocks || []).indexOf(what) >= 0);
  P.has = has;

  // ---------------------------------------------------------------- THEMES (52)
  const svg = s => 'url("data:image/svg+xml,' + encodeURIComponent(s) + '")';
  const dots = (c, o) => svg('<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22"><circle cx="3" cy="3" r="1.6" fill="' + c + '" fill-opacity="' + (o || .18) + '"/></svg>');
  const stars = (c) => svg('<svg xmlns="http://www.w3.org/2000/svg" width="90" height="90"><g fill="' + c + '"><circle cx="10" cy="14" r="1.2"/><circle cx="54" cy="8" r=".8"/><circle cx="76" cy="40" r="1.4"/><circle cx="30" cy="60" r=".9"/><circle cx="64" cy="76" r="1.1"/><circle cx="8" cy="80" r=".7"/><path d="M40 30l1.5 4 4 .5-3 2.6 1 4-3.5-2.2-3.5 2.2 1-4-3-2.6 4-.5z" fill-opacity=".7"/></g></svg>');
  const waves = (c) => svg('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40"><path d="M0 20 Q20 8 40 20 T80 20" fill="none" stroke="' + c + '" stroke-opacity=".16" stroke-width="2"/></svg>');
  const hearts = (c) => svg('<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60"><path d="M30 44s-12-7.5-12-15a6.5 6.5 0 0 1 12-3.5A6.5 6.5 0 0 1 42 29c0 7.5-12 15-12 15z" fill="' + c + '" fill-opacity=".14"/></svg>');
  const tri = (a, b) => svg('<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><path d="M0 48L24 0l24 48z" fill="' + a + '" fill-opacity=".14"/><path d="M12 48L24 24l12 24z" fill="' + b + '" fill-opacity=".22"/><rect x="0" y="44" width="48" height="4" fill="#000" fill-opacity=".18"/></svg>');
  const diamonds = (c) => svg('<svg xmlns="http://www.w3.org/2000/svg" width="34" height="34"><path d="M17 3l14 14-14 14L3 17z" fill="none" stroke="' + c + '" stroke-opacity=".18" stroke-width="1.5"/><circle cx="17" cy="17" r="2" fill="' + c + '" fill-opacity=".25"/></svg>');
  const leaves = (c) => svg('<svg xmlns="http://www.w3.org/2000/svg" width="70" height="70"><path d="M20 50c0-18 14-30 30-30-2 18-14 30-30 30z" fill="' + c + '" fill-opacity=".12"/></svg>');
  const stripes = (c) => svg('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><path d="M-10 50L50 -10M0 60L60 0" stroke="' + c + '" stroke-opacity=".12" stroke-width="8"/></svg>');
  const snow = () => svg('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><g fill="#fff" fill-opacity=".5"><circle cx="10" cy="12" r="2"/><circle cx="50" cy="30" r="1.5"/><circle cx="70" cy="64" r="2.2"/><circle cx="26" cy="58" r="1.2"/></g></svg>');
  const moon = () => svg('<svg xmlns="http://www.w3.org/2000/svg" width="140" height="140"><path d="M100 30a22 22 0 1 0 14 38 18 18 0 1 1-14-38z" fill="#fde68a" fill-opacity=".28"/><g fill="#fde68a" fill-opacity=".5"><circle cx="30" cy="40" r="1.4"/><circle cx="60" cy="100" r="1"/><circle cx="20" cy="110" r="1.6"/></g></svg>');
  const lamps = () => svg('<svg xmlns="http://www.w3.org/2000/svg" width="70" height="70"><path d="M20 50h20l-4 6h-12z" fill="#f59e0b" fill-opacity=".35"/><path d="M30 34c4 6 4 10 0 14-4-4-4-8 0-14z" fill="#fbbf24" fill-opacity=".55"/></svg>');
  const G = (a, b, ang) => 'linear-gradient(' + (ang || 160) + 'deg,' + a + ',' + b + ')';
  // [id, name, pack, chat background, my bubble, my text, their bubble, their text]
  const THEMES = [
    ['classic', 'Classic', 'free', '', '', '', '', ''],
    ['midnight', 'Midnight', 'free', dots('#7dd3fc') + ',' + G('#050b16', '#0b1730'), G('#2563eb', '#1d4ed8'), '#fff', 'rgba(255,255,255,.08)', '#e6f0ff'],
    ['teal', 'Teal calm', 'free', G('#063238', '#0a4c55'), G('#14b8a6', '#0d9488'), '#fff', 'rgba(255,255,255,.1)', '#e7fffb'],
    ['charcoal', 'Charcoal', 'free', G('#141414', '#262626'), G('#525252', '#3f3f46'), '#fff', 'rgba(255,255,255,.07)', '#f4f4f5'],
    ['deepsea', 'Deep sea', 'ocean', waves('#67e8f9') + ',' + G('#03243b', '#05486b'), G('#0891b2', '#0e7490'), '#fff', 'rgba(255,255,255,.1)', '#e0faff'],
    ['lagoon', 'Lagoon', 'ocean', waves('#fff') + ',' + G('#0e7490', '#14b8a6', 200), G('#06b6d4', '#0284c7'), '#fff', 'rgba(255,255,255,.85)', '#083344'],
    ['reef', 'Coral reef', 'ocean', dots('#fda4af', .3) + ',' + G('#0c4a6e', '#be185d', 170), G('#fb7185', '#e11d48'), '#fff', 'rgba(255,255,255,.12)', '#fff1f2'],
    ['seafoam', 'Seafoam', 'ocean', G('#ccfbf1', '#a5f3fc'), G('#0f766e', '#115e59'), '#fff', '#ffffff', '#134e4a'],
    ['golden', 'Golden hour', 'sunset', G('#7c2d12', '#f59e0b', 175), G('#ea580c', '#c2410c'), '#fff', 'rgba(0,0,0,.25)', '#fff7ed'],
    ['dusk', 'Dusk', 'sunset', G('#312e81', '#db2777', 170), G('#f472b6', '#db2777'), '#fff', 'rgba(255,255,255,.12)', '#fdf2f8'],
    ['desert', 'Karoo', 'sunset', dots('#7c2d12', .25) + ',' + G('#fed7aa', '#fdba74'), G('#9a3412', '#7c2d12'), '#fff', '#fff7ed', '#431407'],
    ['peach', 'Peach', 'sunset', G('#ffe4e6', '#fed7aa'), G('#fb923c', '#f97316'), '#fff', '#ffffff', '#431407'],
    ['forest', 'Forest', 'nature', leaves('#86efac') + ',' + G('#052e16', '#14532d'), G('#16a34a', '#15803d'), '#fff', 'rgba(255,255,255,.08)', '#ecfdf5'],
    ['fynbos', 'Fynbos', 'nature', leaves('#f9a8d4') + ',' + G('#1e293b', '#365314'), G('#db2777', '#be185d'), '#fff', 'rgba(255,255,255,.1)', '#f0fdf4'],
    ['savanna', 'Savanna', 'nature', G('#a16207', '#facc15', 175), G('#854d0e', '#713f12'), '#fff', 'rgba(255,255,255,.75)', '#422006'],
    ['bamboo', 'Bamboo', 'nature', stripes('#365314') + ',' + G('#ecfccb', '#d9f99d'), G('#4d7c0f', '#3f6212'), '#fff', '#ffffff', '#1a2e05'],
    ['rainbow-nation', 'Rainbow Nation', 'heritage', tri('#facc15', '#16a34a') + ',' + G('#0b3d2e', '#002395', 170), G('#de3831', '#b91c1c'), '#fff', 'rgba(255,255,255,.1)', '#fffbeb'],
    ['ndebele', 'Ndebele', 'heritage', tri('#1d4ed8', '#dc2626') + ',' + G('#fefce8', '#fef9c3'), G('#1e3a8a', '#1e40af'), '#fff', '#ffffff', '#111827'],
    ['kente', 'Kente', 'heritage', stripes('#16a34a') + ',' + G('#ca8a04', '#b45309'), G('#166534', '#14532d'), '#fff', 'rgba(0,0,0,.28)', '#fefce8'],
    ['shweshwe', 'Shweshwe', 'heritage', diamonds('#fff') + ',' + G('#1e3a8a', '#172554'), G('#e5e7eb', '#cbd5e1'), '#172554', 'rgba(255,255,255,.1)', '#eff6ff'],
    ['peace', 'Peace', 'faith', G('#e0f2fe', '#f8fafc'), G('#0369a1', '#075985'), '#fff', '#ffffff', '#0c4a6e'],
    ['grace', 'Grace', 'faith', dots('#a16207', .2) + ',' + G('#fefce8', '#fde68a'), G('#a16207', '#854d0e'), '#fff', '#ffffff', '#422006'],
    ['crescent', 'Crescent night', 'faith', moon() + ',' + G('#022c22', '#064e3b'), G('#d97706', '#b45309'), '#fff', 'rgba(255,255,255,.08)', '#ecfdf5'],
    ['lotus', 'Lotus', 'faith', G('#fae8ff', '#fbcfe8'), G('#a21caf', '#86198f'), '#fff', '#ffffff', '#4a044e'],
    ['roses', 'Roses', 'love', hearts('#fecdd3') + ',' + G('#4c0519', '#881337'), G('#e11d48', '#be123c'), '#fff', 'rgba(255,255,255,.1)', '#fff1f2'],
    ['valentine', 'Valentine', 'love', hearts('#e11d48') + ',' + G('#ffe4e6', '#fecdd3'), G('#e11d48', '#be123c'), '#fff', '#ffffff', '#4c0519'],
    ['lavender', 'Lavender', 'love', G('#ede9fe', '#ddd6fe'), G('#7c3aed', '#6d28d9'), '#fff', '#ffffff', '#2e1065'],
    ['blush', 'Blush', 'love', G('#fdf2f8', '#fce7f3'), G('#ec4899', '#db2777'), '#fff', '#ffffff', '#500724'],
    ['cyber', 'Cyber', 'neon', stripes('#22d3ee') + ',' + G('#020617', '#0f172a'), G('#22d3ee', '#06b6d4'), '#020617', 'rgba(34,211,238,.1)', '#a5f3fc'],
    ['arcade', 'Arcade', 'neon', dots('#f0abfc', .4) + ',' + G('#1e0536', '#3b0764'), G('#d946ef', '#a21caf'), '#fff', 'rgba(255,255,255,.08)', '#fae8ff'],
    ['laser', 'Laser green', 'neon', G('#020617', '#052e16'), G('#4ade80', '#22c55e'), '#052e16', 'rgba(74,222,128,.1)', '#bbf7d0'],
    ['synthwave', 'Synthwave', 'neon', G('#2e1065', '#be185d', 180), G('#f97316', '#ea580c'), '#fff', 'rgba(255,255,255,.1)', '#fdf4ff'],
    ['bubblegum', 'Bubblegum', 'kids', dots('#ec4899', .3) + ',' + G('#fce7f3', '#e0f2fe'), G('#ec4899', '#db2777'), '#fff', '#ffffff', '#500724'],
    ['dino', 'Dino land', 'kids', leaves('#15803d') + ',' + G('#dcfce7', '#fef9c3'), G('#16a34a', '#15803d'), '#fff', '#ffffff', '#14532d'],
    ['rainbow', 'Rainbow', 'kids', 'linear-gradient(160deg,#fecaca,#fde68a,#bbf7d0,#bfdbfe,#ddd6fe)', G('#6366f1', '#4f46e5'), '#fff', '#ffffff', '#1e1b4b'],
    ['spacekid', 'Space kid', 'kids', stars('#fde68a') + ',' + G('#1e1b4b', '#312e81'), G('#f59e0b', '#d97706'), '#fff', 'rgba(255,255,255,.1)', '#eef2ff'],
    ['nebula', 'Nebula', 'galaxy', stars('#fff') + ',radial-gradient(circle at 30% 20%,#7c3aed,transparent 55%),radial-gradient(circle at 80% 70%,#db2777,transparent 50%),#0b0618', G('#8b5cf6', '#7c3aed'), '#fff', 'rgba(255,255,255,.08)', '#f5f3ff'],
    ['aurora', 'Aurora', 'galaxy', stars('#fff') + ',linear-gradient(180deg,#022c22,#065f46 40%,#1e3a8a)', G('#10b981', '#059669'), '#fff', 'rgba(255,255,255,.08)', '#ecfdf5'],
    ['milkyway', 'Milky Way', 'galaxy', stars('#e0e7ff') + ',' + G('#020617', '#1e1b4b'), G('#4f46e5', '#4338ca'), '#fff', 'rgba(255,255,255,.08)', '#eef2ff'],
    ['starfield', 'Starfield', 'galaxy', stars('#fef08a') + ',#030712', G('#ca8a04', '#a16207'), '#fff', 'rgba(255,255,255,.07)', '#fefce8'],
    ['christmas', 'Christmas', 'festive', snow() + ',' + G('#14532d', '#7f1d1d', 170), G('#dc2626', '#b91c1c'), '#fff', 'rgba(255,255,255,.1)', '#f0fdf4'],
    ['eid', 'Eid', 'festive', moon() + ',' + G('#0f172a', '#134e4a'), G('#ca8a04', '#a16207'), '#fff', 'rgba(255,255,255,.08)', '#fefce8'],
    ['diwali', 'Diwali', 'festive', lamps() + ',' + G('#431407', '#7c2d12'), G('#f59e0b', '#d97706'), '#fff', 'rgba(255,255,255,.1)', '#fffbeb'],
    ['newyear', 'New Year', 'festive', stars('#fde68a') + ',' + G('#020617', '#3b0764'), G('#eab308', '#ca8a04'), '#111827', 'rgba(255,255,255,.08)', '#fefce8'],
    ['goldgreen', 'Gold & green', 'sport', stripes('#facc15') + ',' + G('#14532d', '#166534'), G('#facc15', '#eab308'), '#14532d', 'rgba(255,255,255,.1)', '#f0fdf4'],
    ['stripes', 'Black & white', 'sport', stripes('#fff') + ',#111', G('#f4f4f5', '#d4d4d8'), '#111', 'rgba(255,255,255,.1)', '#fafafa'],
    ['sunshine', 'Sunshine yellow', 'sport', G('#fef08a', '#facc15'), G('#1d4ed8', '#1e40af'), '#fff', '#ffffff', '#1e3a8a'],
    ['skyblue', 'Sky blue', 'sport', G('#e0f2fe', '#7dd3fc'), G('#0369a1', '#075985'), '#fff', '#ffffff', '#082f49'],
    ['blackgold', 'Black gold', 'luxury', diamonds('#d4af37') + ',' + G('#0a0a0a', '#1c1917'), 'linear-gradient(135deg,#d4af37,#a16207)', '#0a0a0a', 'rgba(212,175,55,.1)', '#fef9c3'],
    ['marble', 'Marble', 'luxury', 'linear-gradient(120deg,#f5f5f4 0%,#e7e5e4 30%,#fafaf9 50%,#d6d3d1 80%)', G('#292524', '#44403c'), '#fff', '#ffffff', '#1c1917'],
    ['champagne', 'Champagne', 'luxury', dots('#a16207', .2) + ',' + G('#fefce8', '#fef3c7'), G('#b45309', '#92400e'), '#fff', '#ffffff', '#451a03'],
    ['emerald', 'Emerald', 'luxury', diamonds('#6ee7b7') + ',' + G('#022c22', '#064e3b'), G('#d4af37', '#a16207'), '#022c22', 'rgba(255,255,255,.08)', '#ecfdf5'],
    ['plus-prism', 'Prism (Plus)', 'plus', 'conic-gradient(from 200deg at 70% 30%,#1e3a8a,#7c3aed,#db2777,#f59e0b,#10b981,#1e3a8a)', 'rgba(0,0,0,.45)', '#fff', 'rgba(255,255,255,.85)', '#111827'],
    ['plus-aurora', 'Northern lights (Plus)', 'plus', stars('#fff') + ',linear-gradient(180deg,#0f172a,#0e7490 45%,#7c3aed)', G('#22d3ee', '#a855f7'), '#fff', 'rgba(255,255,255,.1)', '#f0fdfa']
  ];
  const PACKS = { free: 'Free', ocean: 'Ocean', sunset: 'Sunset', nature: 'Nature', heritage: 'Heritage', faith: 'Faith', love: 'Love', neon: 'Neon', kids: 'Kids', galaxy: 'Galaxy', festive: 'Festive', sport: 'Sport colours', luxury: 'Luxury', plus: 'Plus' };
  const themeOk = t => t[2] === 'free' || (t[2] === 'plus' ? !!(P.me && P.me.plus) : has('theme:' + t[2]));
  function curTheme() { try { return localStorage.getItem('fc_theme') || 'classic'; } catch (_) { return 'classic'; } }
  function applyTheme(id) {
    const t = THEMES.find(x => x[0] === id) || THEMES[0];
    const ok = !P.me || themeOk(t);   // until the shop loads, keep what the phone remembered
    const st = document.documentElement.style;
    if (!ok || t[0] === 'classic') { document.documentElement.classList.remove('fct'); return; }
    st.setProperty('--fct-bg', t[3]); st.setProperty('--fct-mine', t[4]); st.setProperty('--fct-mine-ink', t[5]); st.setProperty('--fct-theirs', t[6]); st.setProperty('--fct-theirs-ink', t[7]);
    document.documentElement.classList.add('fct');
  }
  async function scrThemes() {
    const self = top();
    const bd = frame('Chat themes', THEMES.length + ' themes for your chats');
    if (!P.me) await loadShop(); if (top() !== self) return;
    const cur = curTheme();
    let h = '<p class="fca-note" style="margin-top:0">Your theme is just for you — the people you chat with keep their own.</p>';
    Object.keys(PACKS).forEach(pk => {
      const list = THEMES.filter(t => t[2] === pk); const open = list.length && themeOk(list[0]);
      const pid = 'futurechat_theme_' + pk;
      h += '<div class="fcp-packhd"><b>' + esc(PACKS[pk]) + '</b>' + (open ? '<span class="ok">✓ Yours</span>' : pk === 'plus' ? '<button class="fc-chip" data-plus>With Plus</button>' : '<button class="fc-chip fcp-buy" data-buy="' + pid + '"><span data-fcpprice="' + pid + '">' + esc(price(pid)) + '</span></button>') + '</div>' +
        '<div class="fcp-themes">' + list.map(t => '<button class="fcp-th' + (t[0] === cur ? ' on' : '') + (open ? '' : ' locked') + '" data-t="' + t[0] + '" style="background:' + (t[3] ? t[3].replace(/"/g, '&quot;') : 'linear-gradient(160deg,#0a1f33,#11506a)') + '"><i style="background:' + (t[4] || 'linear-gradient(135deg,#0f8f98,#0b6f86)') + '"></i><i class="th" style="background:' + (t[6] || 'rgba(255,255,255,.09)') + '"></i><span>' + esc(t[1]) + (open ? '' : ' 🔒') + '</span></button>').join('') + '</div>';
    });
    h += '<div class="fca-card" style="margin-top:12px">' + row('🎨', 'Every theme pack', 'All ' + (Object.keys(PACKS).length - 2) + ' packs, for good', { data: 'data-buy="futurechat_themes_all"' }, '<span class="fc-chip fcp-buy"><span data-fcpprice="futurechat_themes_all">' + esc(price('futurechat_themes_all')) + '</span></span>') + '</div>';
    bd.innerHTML = h;
    bd.querySelectorAll('[data-t]').forEach(b => b.onclick = () => {
      const t = THEMES.find(x => x[0] === b.dataset.t);
      if (!themeOk(t)) { applyTheme(t[0]); document.documentElement.classList.add('fct'); toast('Preview — get the ' + PACKS[t[2]] + ' pack to keep it'); setTimeout(() => applyTheme(curTheme()), 2500); return; }
      try { localStorage.setItem('fc_theme', t[0]); } catch (_) {} applyTheme(t[0]); bd.querySelectorAll('.fcp-th').forEach(x => x.classList.toggle('on', x === b)); toast(t[1] + ' ✓');
    });
    bd.querySelectorAll('[data-buy]').forEach(b => b.onclick = async e => { e.stopPropagation(); if (await buy(b.dataset.buy)) { await loadShop(); scrThemes(); } });
    bd.querySelectorAll('[data-plus]').forEach(b => b.onclick = () => push(scrPlus));
  }

  // ---------------------------------------------------------------- FUTURE CHAT PLUS
  function scrPlus() {
    const bd = frame('Future Chat Plus', 'A little extra, R20 a month');
    const on = P.me && P.me.plus;
    bd.innerHTML = '<div class="fca-hero" style="background:linear-gradient(135deg,#7c3aed,#0e8c9e)"><small>✨ FUTURE CHAT PLUS</small><b>' + (on ? (P.me.owner ? 'You have everything (owner)' : 'You have Plus') : 'Get more out of Future Chat') + '</b><p>' + (on && P.me.plus_until ? 'Renews or ends on ' + new Date(P.me.plus_until).toLocaleDateString() + '. Manage it in Google Play.' : 'Chats, calls, Chatmoji and lenses stay free for everyone. Plus is for people who want a bit more.') + '</p></div>' +
      '<div class="fca-card">' + row('🎥', 'HD video calls', 'Your video is sent in sharp 720p HD', {}, '') + row('📎', 'Bigger files', 'Send files and videos up to 48 MB (16 MB free)', {}, '') +
      row('🕛', 'Unlimited scheduled messages', 'Free: 5 waiting at a time', {}, '') + row('💰', 'Stokvel record', 'Save your stokvel payments as a spreadsheet', {}, '') + row('🌌', 'Plus themes', 'Prism and Northern lights', {}, '') + '</div>' +
      (on ? '' : '<button class="fca-btn" data-a="buy">Get Plus · <span data-fcpprice="futurechat_plus_monthly">' + esc(price('futurechat_plus_monthly')) + '</span> a month</button><p class="fca-note">Paid monthly through Google Play. Cancel any time in Google Play → Subscriptions.</p>');
    bind(bd, { buy: async () => { if (await buy('futurechat_plus_monthly')) { await loadShop(); scrPlus(); } } });
  }
  P.plus = () => { openPanel(); push(scrPlus); };

  // ---------------------------------------------------------------- SHOP
  async function scrShop() {
    const self = top();
    const bd = frame('Shop', 'Small things that make a big moment');
    bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    await loadShop(); if (top() !== self) return;
    const cr = (P.me && P.me.credits) || {};
    bd.innerHTML = '<div class="fcp-grid">' +
      tile('📣', 'Shout-out', 'Birthday, congrats, new baby, RIP… in Sponsored status', 'R5 a day', 'shout') +
      tile('💍', 'Propose', 'Ask the big question where everyone can see', 'R29', 'propose') +
      tile('🎁', 'Premium card', 'Animated card with a tune and your voice', price('futurechat_card_premium') + (cr.card ? ' · ' + cr.card + ' ready' : ''), 'card') +
      tile('💌', 'Invitation', 'Wedding, party, church — with RSVP', price('futurechat_event_invite') + (cr.event ? ' · ' + cr.event + ' ready' : ''), 'event') +
      tile('🎨', 'Chat themes', THEMES.length + ' themes in 12 packs', 'from ' + price('futurechat_theme_ocean'), 'themes') +
      tile('🧠', 'Quiz packs', 'Bible, soccer, science and more', price('futurechat_quiz_bible') + ' each', 'quiz') + '</div>' +
      '<div class="fca-card" style="margin-top:12px">' + row('✨', 'Future Chat Plus', P.me && P.me.plus ? 'Active' : 'HD video calls, bigger files and more · R20 a month', { data: 'data-a="plus"' }) + row('📅', 'My events', 'Invitations you sent and got', { data: 'data-a="events"' }) + row('📣', 'Advertise your business', 'From R5 a day', { data: 'data-a="ads"' }) + '</div>' +
      '<p class="fca-note">Payments go through Google Play. Prices are shown in your currency.</p>';
    bind(bd, { shout: () => push(() => scrShout(false)), propose: () => push(() => scrShout(true)), card: () => pickChat(c => premiumCard(c.id)), event: () => eventForm(null),
      themes: () => push(scrThemes), quiz: () => push(scrQuizPacks), plus: () => push(scrPlus), events: () => push(scrEvents), ads: () => FCX.advertise() });
  }
  const tile = (i, t, s, p, a) => '<button class="fcp-tile" data-a="' + a + '"><i>' + i + '</i><b>' + esc(t) + '</b><small>' + esc(s) + '</small><em>' + esc(p) + '</em></button>';
  P.open = () => { go('you'); push(scrShop); };
  function pickChat(cb) {
    const c = curConv(); if (c) { cb(c); return; }
    const list = chats();
    sheet('<h3>Send it to</h3><div class="fc-acts" style="max-height:60vh;overflow:auto">' + list.map(c => '<button class="fc-act" data-c="' + c.id + '"><i>' + (c.kind === 'group' ? '◎' : '💬') + '</i>' + esc(c.title) + '</button>').join('') + '</div>', (el, done) =>
      el.querySelectorAll('[data-c]').forEach(b => b.onclick = () => { done(); cb(list.find(x => x.id === Number(b.dataset.c))); }));
  }

  // ---------------------------------------------------------------- QUIZ PACKS (questions live in fcfamily.js PACKS)
  function scrQuizPacks() {
    const bd = frame('Quiz packs', 'More family fun');
    const NAMES = { bible: ['✝️', 'Bible'], soccer: ['⚽', 'Soccer'], science: ['🔬', 'Science'], world: ['🌍', 'Around the world'], animals: ['🦒', 'Animals'], history: ['🏛️', 'History'] };
    bd.innerHTML = '<div class="fca-card">' + Object.keys(NAMES).map(k => row(NAMES[k][0], NAMES[k][1], '12 questions · play with the family', { data: 'data-q="' + k + '"' }, has('quiz:' + k) ? '<span class="ok">✓</span>' : '<span class="fc-chip fcp-buy"><span data-fcpprice="futurechat_quiz_' + k + '">' + esc(price('futurechat_quiz_' + k)) + '</span></span>')).join('') + '</div>' +
      '<p class="fca-note">Start a quiz from any chat: tap 📎 then Family quiz.</p>';
    bd.querySelectorAll('[data-q]').forEach(b => b.onclick = async () => { const k = b.dataset.q; if (has('quiz:' + k)) { toast('Yours ✓ — start it from a chat'); return; } if (await buy('futurechat_quiz_' + k)) { await loadShop(); scrQuizPacks(); } });
  }

  // ---------------------------------------------------------------- SHOUT-OUTS + PROPOSALS (Sponsored status)
  const DESIGNS = { bday: ['🎂', 'Birthday', '#be185d', '#f59e0b'], congrats: ['🎉', 'Congratulations', '#7c3aed', '#0ea5e9'], baby: ['🍼', 'New baby', '#38bdf8', '#f9a8d4'], love: ['❤️', 'Love', '#be123c', '#fb7185'],
    thanks: ['🙏', 'Thank you', '#0f766e', '#84cc16'], grad: ['🎓', 'Graduation', '#1e3a8a', '#ca8a04'], wedding: ['💒', 'Wedding', '#a16207', '#fde68a'], faith: ['🕊️', 'Blessings', '#0369a1', '#a5f3fc'],
    memorial: ['🕯️', 'In loving memory', '#1f2937', '#475569'], lost: ['🔎', 'Lost & found', '#b45309', '#f59e0b'], propose: ['💍', 'Proposal', '#831843', '#f43f5e'] };
  function scrShout(propose) {
    const bd = frame(propose ? 'Propose 💍' : 'Send a shout-out', propose ? 'Ask the big question in Status' : 'Seen by everyone who opens Sponsored');
    let design = propose ? 'propose' : 'bday', plan = propose ? 'futurechat_propose_1d' : 'futurechat_shout_1d';
    bd.innerHTML = (propose ? '<div class="fcp-prop"><div class="rings">💍</div><b>Will you marry me?</b><p>Your proposal shows in Sponsored status for a day, with hearts and roses. Your partner also gets a special card in your chat with a <b>YES</b> button — and when they say yes, everyone sees it.</p></div>'
        : '<div class="fcp-designs">' + Object.keys(DESIGNS).filter(k => k !== 'propose').map(k => '<button data-d="' + k + '" class="' + (k === design ? 'on' : '') + '" style="background:linear-gradient(135deg,' + DESIGNS[k][2] + ',' + DESIGNS[k][3] + ')"><i>' + DESIGNS[k][0] + '</i><span>' + DESIGNS[k][1] + '</span></button>').join('') + '</div>') +
      (propose ? '<label class="fca-field"><span>Your partner\'s Future Chat number</span><input id="fcpTo" type="tel" placeholder="e.g. 082 123 4567"></label>' : '') +
      '<label class="fca-field"><span>' + (propose ? 'Your question' : 'Headline') + '</span><input id="fcpH" maxlength="60" placeholder="' + (propose ? 'e.g. Lerato, will you marry me?' : 'e.g. Happy 40th, Mom! 🎉') + '"></label>' +
      '<label class="fca-field"><span>' + (propose ? 'A few words from your heart' : 'Message (optional)') + '</span><textarea id="fcpB" rows="3" maxlength="180"></textarea></label>' +
      '<div class="fca-field"><span>Photo (optional)</span><input id="fcpF" type="file" hidden accept="image/jpeg,image/png,image/webp"><button type="button" class="fca-pick" id="fcpPick"><i>📎</i><span><b id="fcpPN">Add a photo</b><small>Tap to choose from your phone</small></span></button></div>' +
      (propose ? '' : '<div class="fca-gl">How long</div><div class="fcaad-plans"><button data-p="futurechat_shout_1d" class="on"><b>1 day</b><em>R5</em></button><button data-p="futurechat_shout_3d"><b>3 days</b><em>R15</em></button></div>') +
      '<p class="fca-note">Every shout-out is checked before it shows. Be kind: no insults, private details or things that could hurt someone. If it isn\'t approved, you get your money back.</p>' +
      '<button class="fca-btn" data-a="go">' + (propose ? 'Propose · R29' : 'Send shout-out') + '</button>';
    bd.querySelectorAll('[data-d]').forEach(b => b.onclick = () => { design = b.dataset.d; bd.querySelectorAll('[data-d]').forEach(x => x.classList.toggle('on', x === b)); if (design === 'memorial') $('#fcpH', bd).placeholder = 'e.g. Rest in peace, Gogo Thandi'; });
    bd.querySelectorAll('[data-p]').forEach(b => b.onclick = () => { plan = b.dataset.p; bd.querySelectorAll('[data-p]').forEach(x => x.classList.toggle('on', x === b)); });
    $('#fcpPick', bd).onclick = () => $('#fcpF', bd).click();
    $('#fcpF', bd).onchange = () => { const f = $('#fcpF', bd).files[0]; $('#fcpPN', bd).textContent = f ? f.name : 'Add a photo'; };
    bind(bd, { go: async b => {
      const head = $('#fcpH', bd).value.trim(); if (head.length < 3) { toast(propose ? 'Write your question' : 'Add a headline'); return; }
      const f = $('#fcpF', bd).files[0]; if (f && f.size > 2 * 1024 * 1024) { toast('Photos must be 2 MB or smaller'); return; }
      const media = f ? { mime: f.type, data_base64: await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(String(fr.result)); fr.readAsDataURL(f); }) } : null;
      b.disabled = true; b.textContent = 'Sending…';
      try {
        const d = await post('/api/home-ads/create', { kind: f ? 'photo' : 'word', headline: head, body: $('#fcpB', bd).value.trim(), cta: '', advertiser: ((X.me || {}).name || '').split(' ')[0], product_id: plan, design, to_phone: propose ? $('#fcpTo', bd).value : '', media });
        if (d.status === 'active' || d.status === 'queued') { toast(propose ? 'Your proposal is live 💍 Good luck!' : 'Your shout-out is live 📣'); pop(); return; }
        if (!(window.SkillvayaBilling && window.SkillvayaBilling.purchaseAd)) { toast('Update Future Chat from Google Play to pay in the app'); b.disabled = false; return; }
        window.haAdResult = json => { let r = {}; try { r = JSON.parse(json); } catch (_) {} toast(r.ok ? (propose ? 'Paid 💍 It goes live as soon as it\'s checked' : 'Paid 📣 It goes live as soon as it\'s checked') : (r.cancelled ? 'Cancelled. You were not charged.' : (r.message || 'Payment not confirmed yet'))); b.disabled = false; if (r.ok) pop(); };
        window.haAdError = msg => { toast(msg); b.disabled = false; };
        window.SkillvayaBilling.purchaseAd(d.product_id, String(d.id), String((X.me || {}).id || ''), tok());
      } catch (e) { toast(e.message); b.disabled = false; b.textContent = propose ? 'Propose · R29' : 'Send shout-out'; }
    } });
  }
  // how a shout-out / proposal looks inside Sponsored status (used by fcstatus.js)
  FCX.shoutStage = function (ad) {
    if (ad.tier !== 'shout' && ad.tier !== 'propose') return null;
    const x = ad.x || {}; const dz = DESIGNS[x.design] || DESIGNS.congrats; const prop = ad.tier === 'propose';
    const fx = prop ? '<div class="fcp-fx hearts">' + Array.from({ length: 14 }, (_, i) => '<span style="left:' + (i * 7 + 3) + '%;animation-delay:' + (i * .37).toFixed(2) + 's">' + ['❤️', '🌹', '💖', '💍'][i % 4] + '</span>').join('') + '</div>'
      : x.design === 'memorial' ? '' : '<div class="fcp-fx">' + Array.from({ length: 10 }, (_, i) => '<span style="left:' + (i * 10 + 4) + '%;animation-delay:' + (i * .45).toFixed(2) + 's">' + [dz[0], '✨', '🎉', '💫'][i % 4] + '</span>').join('') + '</div>';
    const said = prop && x.answer === 'yes' ? '<div class="fcp-yes">💍 ' + esc(x.to_name || 'They') + ' said YES! 🎉</div>' : '';
    return { label: prop ? '💍 A proposal' : (x.design === 'memorial' ? '🕯️ In memory' : '📣 Shout-out'), from: ad.advertiser || 'Someone',
      html: '<div class="fcp-stage' + (x.design === 'memorial' ? ' quiet' : '') + '" style="background:linear-gradient(160deg,' + dz[2] + ',' + dz[3] + ')">' + fx +
        (/^image\//.test(ad.mime || '') ? '<img src="' + esc(ad.media) + '" alt="">' : '<div class="big">' + dz[0] + '</div>') + '<h3>' + esc(ad.headline) + '</h3>' + (ad.body ? '<p>' + esc(ad.body) + '</p>' : '') + said + '<small>— ' + esc(ad.advertiser || '') + '</small></div>' };
  };

  // ---------------------------------------------------------------- PREMIUM CARDS
  const CARDS = [['gold', 'Gold confetti', '🎉', '#78350f', '#f59e0b'], ['balloons', 'Balloons', '🎈', '#be185d', '#f472b6'], ['fireworks', 'Fireworks', '🎆', '#1e1b4b', '#7c3aed'], ['hearts', 'Hearts', '💖', '#9f1239', '#fb7185'],
    ['night', 'Starry night', '🌙', '#0f172a', '#4338ca'], ['flowers', 'Flowers', '🌸', '#be185d', '#fde68a'], ['lanterns', 'Lanterns', '🏮', '#7f1d1d', '#f59e0b'], ['lamps', 'Diya lamps', '🪔', '#7c2d12', '#facc15'],
    ['snow', 'Snowy Christmas', '🎄', '#14532d', '#dc2626'], ['clouds', 'Baby clouds', '☁️', '#38bdf8', '#e0f2fe'], ['cake', 'Big cake', '🎂', '#9d174d', '#fbbf24'], ['trophy', 'Well done', '🏆', '#713f12', '#facc15']];
  const OCC = [['bday', 'Birthday', 'Happy birthday!'], ['congrats', 'Congratulations', 'Congratulations!'], ['love', 'Love', 'I love you'], ['thanks', 'Thank you', 'Thank you!'], ['eid', 'Eid', 'Eid Mubarak'], ['diwali', 'Diwali', 'Happy Diwali'],
    ['christmas', 'Christmas', 'Merry Christmas'], ['newyear', 'New Year', 'Happy New Year'], ['baby', 'New baby', 'Welcome, little one!'], ['getwell', 'Get well', 'Get well soon']];
  function premiumCard(conv) {
    let design = 'gold', occ = 'bday', voice = null, rec = null;
    sheet('<h3>🎁 Premium card</h3><div class="fcp-cards">' + CARDS.map(c => '<button data-cd="' + c[0] + '" class="' + (c[0] === design ? 'on' : '') + '" style="background:linear-gradient(135deg,' + c[3] + ',' + c[4] + ')"><i>' + c[2] + '</i><span>' + c[1] + '</span></button>').join('') + '</div>' +
      '<div class="fc-chips" style="margin:10px 0;flex-wrap:wrap">' + OCC.map(o => '<button class="fc-chip' + (o[0] === occ ? ' on' : '') + '" data-oc="' + o[0] + '">' + o[1] + '</button>').join('') + '</div>' +
      '<label class="fca-field"><span>Title</span><input id="fcpCT" maxlength="80" value="Happy birthday!"></label><label class="fca-field"><span>Your words</span><textarea id="fcpCB" rows="3" maxlength="600" placeholder="Write something from the heart…"></textarea></label>' +
      '<button class="fc-btn sec" id="fcpRec">🎙️ Add a voice message (optional)</button><div id="fcpRecS" style="text-align:center;color:#9cb7cc;font-size:13px"></div>' +
      '<button class="fc-btn" id="fcpSend">Send card · ' + ((P.me && P.me.credits && P.me.credits.card) ? 'ready' : '<span data-fcpprice="futurechat_card_premium">' + esc(price('futurechat_card_premium')) + '</span>') + '</button>', (el, done) => {
      el.querySelectorAll('[data-cd]').forEach(b => b.onclick = () => { design = b.dataset.cd; el.querySelectorAll('[data-cd]').forEach(x => x.classList.toggle('on', x === b)); });
      el.querySelectorAll('[data-oc]').forEach(b => b.onclick = () => { occ = b.dataset.oc; el.querySelectorAll('[data-oc]').forEach(x => x.classList.toggle('on', x === b)); $('#fcpCT', el).value = (OCC.find(o => o[0] === occ) || [])[2] || ''; });
      $('#fcpRec', el).onclick = async () => {
        if (rec && rec.state === 'recording') { rec.stop(); return; }
        let s; try { s = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (_) { toast('Allow the microphone to add your voice'); return; }
        const parts = []; rec = new MediaRecorder(s); const t0 = Date.now();
        rec.ondataavailable = e => e.data.size && parts.push(e.data);
        rec.onstop = () => { s.getTracks().forEach(t => t.stop()); voice = new Blob(parts, { type: rec.mimeType || 'audio/webm' }); $('#fcpRec', el).textContent = '🎙️ Record again'; $('#fcpRecS', el).textContent = 'Voice message added ✓ (' + Math.round((Date.now() - t0) / 1000) + ' s)'; };
        rec.start(); $('#fcpRec', el).textContent = '⏹ Stop recording'; $('#fcpRecS', el).textContent = 'Recording… up to 2 minutes';
        setTimeout(() => { if (rec && rec.state === 'recording') rec.stop(); }, 120000);
      };
      $('#fcpSend', el).onclick = async e => {
        const b = e.target.closest('button'); b.disabled = true;
        if (!(P.me && P.me.credits && P.me.credits.card > 0)) { if (!(await buy('futurechat_card_premium'))) { b.disabled = false; return; } await loadShop(); }
        let v = null; if (voice) v = { mime: voice.type, data_base64: await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(String(fr.result)); fr.readAsDataURL(voice); }) };
        try { await post('/api/fcp/card', { c: conv, design, k: occ, title: $('#fcpCT', el).value, body: $('#fcpCB', el).value, voice: v }); done(); toast('Card sent 🎁'); loadShop(); refreshChat(); }
        catch (er) { toast(er.message); b.disabled = false; }
      };
    });
  }
  // a premium card inside the chat: animated, with a tune button
  const baseGreet = FCX.greet;
  FCX.greet = function (m) {
    const c = m.meta && m.meta.card; if (!c || !c.premium) return baseGreet ? baseGreet(m) : '';
    const d = CARDS.find(x => x[0] === c.premium) || CARDS[0];
    let words = String(m.body || ''); if (c.t && words.indexOf(c.t) === 0) words = words.slice(c.t.length).trim();
    return '<div class="fcp-card fx-' + esc(d[0]) + '" style="background:linear-gradient(150deg,' + d[3] + ',' + d[4] + ')"><div class="fcp-fx">' + Array.from({ length: 8 }, (_, i) => '<span style="left:' + (i * 12 + 4) + '%;animation-delay:' + (i * .5).toFixed(1) + 's">' + [d[2], '✨', '💫', d[2]][i % 4] + '</span>').join('') + '</div>' +
      '<div class="em">' + d[2] + '</div><b>' + esc(c.t || '') + '</b>' + (words ? '<p>' + esc(words) + '</p>' : '') + '<button class="tune" onclick="event.stopPropagation();window.FCX.shop.tune(\'' + esc(c.k || 'bday') + '\')">▶ Play the tune</button></div>';
  };
  // simple tunes made on the phone (no recordings): Happy Birthday is public domain
  P.tune = function (k) {
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)(); let t = ac.currentTime + .05;
      const N = { C4: 261.6, D4: 293.7, E4: 329.6, F4: 349.2, G4: 392, A4: 440, Bb4: 466.2, C5: 523.3, D5: 587.3, E5: 659.3, G5: 784 };
      const bday = [['C4', .3], ['C4', .2], ['D4', .5], ['C4', .5], ['F4', .5], ['E4', 1], ['C4', .3], ['C4', .2], ['D4', .5], ['C4', .5], ['G4', .5], ['F4', 1], ['C4', .3], ['C4', .2], ['C5', .5], ['A4', .5], ['F4', .5], ['E4', .5], ['D4', 1], ['Bb4', .3], ['Bb4', .2], ['A4', .5], ['F4', .5], ['G4', .5], ['F4', 1.2]];
      const chime = [['C5', .25], ['E5', .25], ['G5', .4], ['E5', .25], ['G5', .25], ['C5', .6], ['D5', .3], ['E5', .8]];
      (k === 'bday' ? bday : chime).forEach(([n, d]) => { const o = ac.createOscillator(), g = ac.createGain(); o.type = 'triangle'; o.frequency.value = N[n]; g.gain.setValueAtTime(.0001, t); g.gain.exponentialRampToValueAtTime(.25, t + .03); g.gain.exponentialRampToValueAtTime(.0001, t + d * .95); o.connect(g).connect(ac.destination); o.start(t); o.stop(t + d); t += d; });
      setTimeout(() => ac.close(), (t - ac.currentTime + .5) * 1000);
      K.confetti('🎉');
    } catch (_) {}
  };

  // ---------------------------------------------------------------- EVENT INVITATIONS
  const EVD = { party: ['🎉', 'Party', '#7c3aed', '#ec4899'], wedding: ['💒', 'Wedding', '#a16207', '#fde68a'], birthday: ['🎂', 'Birthday', '#be185d', '#f59e0b'], baby: ['🍼', 'Baby shower', '#38bdf8', '#f9a8d4'],
    church: ['⛪', 'Church / faith', '#1e3a8a', '#93c5fd'], braai: ['🔥', 'Braai', '#7c2d12', '#f97316'], graduation: ['🎓', 'Graduation', '#1e3a8a', '#ca8a04'], memorial: ['🕯️', 'Memorial', '#1f2937', '#475569'] };
  function eventForm(conv) {
    const soon = new Date(Date.now() + 7 * 864e5); soon.setHours(14, 0, 0, 0);
    const list = chats(); const pre = conv || (curConv() || {}).id;
    let design = 'party';
    sheet('<h3>💌 Invitation</h3><div class="fcp-designs sm">' + Object.keys(EVD).map(k => '<button data-d="' + k + '" class="' + (k === design ? 'on' : '') + '" style="background:linear-gradient(135deg,' + EVD[k][2] + ',' + EVD[k][3] + ')"><i>' + EVD[k][0] + '</i><span>' + EVD[k][1] + '</span></button>').join('') + '</div>' +
      '<label class="fca-field"><span>What is it?</span><input id="fcpET" maxlength="90" placeholder="e.g. Lerato & Sipho\'s wedding"></label>' +
      '<label class="fca-field"><span>When</span><input id="fcpEW" type="datetime-local" value="' + K.localInput(soon.toISOString()) + '"></label>' +
      '<label class="fca-field"><span>Where</span><input id="fcpEP" maxlength="160" placeholder="Address or place name"></label>' +
      '<label class="fca-field"><span>Anything else (dress code, what to bring…)</span><textarea id="fcpEN" rows="2" maxlength="800"></textarea></label>' +
      '<div class="fca-gl">Invite</div><div class="fcp-pick">' + list.map(c => '<label><input type="checkbox" value="' + c.id + '"' + (c.id === pre ? ' checked' : '') + '><span>' + (c.kind === 'group' ? '◎ ' : '') + esc(c.title) + '</span></label>').join('') + '</div>' +
      '<button class="fc-btn" id="fcpEGo">Send invitations · ' + ((P.me && P.me.credits && P.me.credits.event) ? 'ready' : '<span data-fcpprice="futurechat_event_invite">' + esc(price('futurechat_event_invite')) + '</span>') + '</button><p style="font-size:12px;color:#9cb7cc">Guests answer Going, Maybe or Can\'t, and say how many people they bring. Everyone coming gets a reminder the day before and 2 hours before.</p>', (el, done) => {
      el.querySelectorAll('[data-d]').forEach(b => b.onclick = () => { design = b.dataset.d; el.querySelectorAll('[data-d]').forEach(x => x.classList.toggle('on', x === b)); });
      $('#fcpEGo', el).onclick = async e => {
        const b = e.target.closest('button');
        const ids = Array.from(el.querySelectorAll('.fcp-pick input:checked')).map(i => Number(i.value));
        const w = $('#fcpEW', el).value; if (!ids.length) { toast('Choose who to invite'); return; } if ($('#fcpET', el).value.trim().length < 3) { toast('Give your event a name'); return; }
        b.disabled = true;
        if (!(P.me && P.me.credits && P.me.credits.event > 0)) { if (!(await buy('futurechat_event_invite'))) { b.disabled = false; return; } await loadShop(); }
        try { const r = await post('/api/fcp/event', { title: $('#fcpET', el).value, starts_at: w ? new Date(w).toISOString() : '', place: $('#fcpEP', el).value, note: $('#fcpEN', el).value, design, chats: ids }); done(); toast('Invitations sent 💌'); loadShop(); refreshChat(); openEvent(r.id); }
        catch (er) { toast(er.message); b.disabled = false; }
      };
    });
  }
  async function openEvent(id) {
    let ev; try { ev = (await api('/api/fcp/event/' + id)).event; } catch (e) { toast(e.message); return; }
    const d = EVD[ev.design] || EVD.party, dt = new Date(ev.starts_at);
    sheet('<div class="fcp-inv" style="background:linear-gradient(150deg,' + d[2] + ',' + d[3] + ')"><div class="em">' + d[0] + '</div><small>' + esc(ev.host) + ' invites you</small><b>' + esc(ev.title) + '</b><p>📅 ' + esc(dt.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' }) + ' · ' + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })) + '</p>' +
      (ev.place ? '<p>📍 ' + esc(ev.place) + '</p>' : '') + (ev.note ? '<p style="white-space:pre-wrap">' + esc(ev.note) + '</p>' : '') + (ev.cancelled ? '<p><b>❌ This event was cancelled</b></p>' : '') + '</div>' +
      (ev.place ? '<a class="fc-btn sec" style="display:block;text-align:center;text-decoration:none" target="_blank" rel="noopener" href="https://maps.google.com/?q=' + encodeURIComponent(ev.place) + '">Open in Maps</a>' : '') +
      '<p style="text-align:center;margin:10px 0">' + ev.coming + ' coming · ' + ev.counts.maybe + ' maybe · ' + ev.counts.no + ' can\'t</p>' +
      (ev.cancelled ? '' : '<div class="fca-rsvp">' + [['yes', 'Going'], ['maybe', 'Maybe'], ['no', 'Can\'t go']].map(([a, l]) => '<button data-r="' + a + '" class="' + (ev.my_answer === a ? 'on' : '') + '">' + l + '</button>').join('') + '</div>' +
        '<label class="fca-field" style="margin-top:10px"><span>Extra people with me</span><select id="fcpEG">' + Array.from({ length: 11 }, (_, i) => '<option' + (ev.my_guests === i ? ' selected' : '') + '>' + i + '</option>').join('') + '</select></label>') +
      (ev.mine && ev.guests ? '<div class="fca-gl">Guest list</div><div class="fca-card">' + ev.guests.map(g => row(g.answer === 'yes' ? '✅' : g.answer === 'maybe' ? '🤔' : '❌', g.name + (g.guests ? ' +' + g.guests : ''), g.note || '', {}, '')).join('') + '</div>' + (ev.cancelled ? '' : '<button class="fc-btn danger" id="fcpECx">Cancel the event</button>') : ''), (el, done) => {
      el.querySelectorAll('[data-r]').forEach(b => b.onclick = async () => { try { await post('/api/fcp/rsvp', { id, answer: b.dataset.r, guests: Number(($('#fcpEG', el) || {}).value || 0) }); done(); toast({ yes: 'See you there! 🎉', maybe: 'Answer saved', no: 'Thanks for letting them know' }[b.dataset.r]); refreshChat(); } catch (e) { toast(e.message); } });
      const cx = $('#fcpECx', el); if (cx) cx.onclick = async () => { if (!confirm('Cancel this event for everyone?')) return; try { await post('/api/fcp/event/cancel', { id }); done(); toast('Cancelled'); refreshChat(); } catch (e) { toast(e.message); } };
    });
  }
  P.event = openEvent;
  async function scrEvents() {
    const self = top(); const bd = frame('My events', 'Invitations you sent and got'); bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let items = []; try { items = (await api('/api/fcp/events')).items || []; } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    bd.innerHTML = (items.length ? '<div class="fca-card">' + items.map(e => row((EVD[e.design] || EVD.party)[0], e.title, K.dueText(e.starts_at) + ' · ' + e.coming + ' coming' + (e.mine ? ' · you host' : e.my_answer ? ' · you: ' + e.my_answer : ''), { data: 'data-e="' + e.id + '"' })).join('') + '</div>'
      : '<div class="fca-empty"><span class="big">💌</span><b>No events yet</b>Send an invitation for a wedding, party or church event — with RSVP and reminders.</div>') + '<button class="fca-btn" data-a="new">New invitation</button>';
    bd.querySelectorAll('[data-e]').forEach(b => b.onclick = () => openEvent(Number(b.dataset.e)));
    bind(bd, { new: () => eventForm(null) });
  }

  // ---------------------------------------------------------------- cards in the chat: invitations + proposals
  const baseSpecial = FCX.special;
  FCX.special = function (m) {
    const t = m.meta || {};
    if (t.invite) {
      const d = EVD[t.design] || EVD.party;
      return '<div class="fc-card fcp-invc" style="background:linear-gradient(150deg,' + d[2] + ',' + d[3] + ')!important"><span class="k">' + (t.cancelled ? '❌ CANCELLED' : d[0] + ' INVITATION') + '</span><b>' + esc(String(m.body || '').replace(/^\S+\s*(You're invited:|Cancelled:)\s*/, '')) + '</b>' + (t.cancelled ? '' : '<button class="pri" onclick="event.stopPropagation();window.FCX.shop.event(' + Number(t.invite) + ')">Open · RSVP</button>') + '</div>';
    }
    if (t.proposal) {
      return '<div class="fc-card fcp-propc"><div class="fcp-fx hearts">' + Array.from({ length: 8 }, (_, i) => '<span style="left:' + (i * 12 + 4) + '%;animation-delay:' + (i * .4).toFixed(1) + 's">' + ['❤️', '🌹', '💖', '💍'][i % 4] + '</span>').join('') + '</div><div class="em">💍</div><b>' + esc(String(m.body || '').replace(/^💍\s*/, '')) + '</b>' + (t.words ? '<p>' + esc(t.words) + '</p>' : '') +
        (m.mine ? '<small>Waiting for the answer… 💓</small>' : '<button class="pri" onclick="event.stopPropagation();window.FCX.shop.answer(' + Number(t.proposal) + ',\'yes\')">💍 YES!</button><button class="sec" onclick="event.stopPropagation();window.FCX.shop.answer(' + Number(t.proposal) + ',\'moment\')">I need a moment</button>') + '</div>';
    }
    if (t.proposal_answer && t.answer === 'yes') { if (!m.mine) setTimeout(() => K.confetti('💍'), 300); return '<div class="fc-card fcp-propc yes"><div class="em">💍🎉</div><b>YES! 💖</b><small>Congratulations to you both!</small></div>'; }
    return baseSpecial ? baseSpecial(m) : '';
  };
  P.answer = async (id, a) => { try { await post('/api/fcp/proposal/answer', { id, answer: a }); if (a === 'yes') K.confetti('💍'); refreshChat(); } catch (e) { toast(e.message); } };

  // ---------------------------------------------------------------- big files for Plus (sent in 3 MB pieces)
  FCX.bigSend = async function (file, kind, caption, conv) {
    let st;
    try { st = await post('/api/fcp/upload/start', { size: file.size, name: file.name, mime: file.type || 'application/octet-stream' }); }
    catch (e) { if (e.data && e.data.plus) { sheet('<h3>Bigger files with Plus</h3><p>' + esc(e.message) + '</p><button class="fc-btn" id="fcpGoPlus">See Future Chat Plus</button>', (el, done) => { $('#fcpGoPlus', el).onclick = () => { done(); P.plus(); }; }); } else toast(e.message); return null; }
    const n = file.size; let off = 0; const CH = st.chunk || 3145728;
    const bar = document.createElement('div'); bar.className = 'fcp-up'; bar.innerHTML = '<b>Sending ' + esc(file.name) + '</b><i><em style="width:0%"></em></i>'; document.body.appendChild(bar);
    try {
      while (off < n) {
        const part = file.slice(off, Math.min(n, off + CH));
        const b64 = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] || ''); r.onerror = rej; r.readAsDataURL(part); });
        let tries = 0, r;
        while (true) { try { r = await post('/api/fcp/upload/chunk', { id: st.id, offset: off, data_base64: b64 }); break; } catch (e) { if (++tries > 4) throw e; await new Promise(x => setTimeout(x, 1500 * tries)); } }
        off = r.got; bar.querySelector('em').style.width = Math.round(100 * off / n) + '%';
      }
      const d = await post('/api/fcp/upload/finish', { id: st.id, c: conv, kind, body: caption || '' });
      refreshChat(); return d;
    } catch (e) { toast(e.message || 'The file could not be sent. Try again.'); return null; }
    finally { bar.remove(); }
  };

  // ---------------------------------------------------------------- hooks: You tab, attach menu, chat menu
  const baseYou = FCX.youExtra;
  FCX.youExtra = function (bd) {
    if (baseYou) baseYou(bd);
    const gl = Array.from(bd.querySelectorAll('.fca-gl')).find(x => x.textContent.trim() === 'Family');
    const box = document.createElement('div');
    box.innerHTML = '<div class="fca-gl">Shop</div><div class="fca-card">' + row('🛍️', 'Shop', 'Shout-outs, proposals, cards, invitations, themes', { data: 'data-a="pshop"' }) +
      row('🎨', 'Chat theme', (THEMES.find(t => t[0] === curTheme()) || THEMES[0])[1], { data: 'data-a="ptheme"' }) + row('✨', 'Future Chat Plus', P.me && P.me.plus ? 'Active' : 'HD video calls, bigger files · R20 a month', { data: 'data-a="pplus"' }) + '</div>';
    if (gl) gl.parentNode.insertBefore(box, gl); else bd.appendChild(box);
    bind(box, { pshop: () => push(scrShop), ptheme: () => push(scrThemes), pplus: () => push(scrPlus) });
  };
  const baseTiles = FCX.attachTiles;
  FCX.attachTiles = function (conv) {
    const t = baseTiles ? baseTiles(conv) : []; if (!conv || !conv.id) return t;
    return t.concat([['🎁', 'Premium card', '#be185d', () => premiumCard(conv.id)], ['💌', 'Invitation', '#7c3aed', () => eventForm(conv.id)]]);
  };
  const baseActs = FCX.convActs;
  FCX.convActs = function (c) {
    const a = baseActs ? baseActs(c) : [];
    if (c.kind === 'group') a.push(['📊', 'Save stokvel record (Plus)', () => stokvelCsv(c)]);
    return a;
  };
  async function stokvelCsv(c) {
    try {
      const r = await fetch('/api/fcp/stokvel.csv?c=' + c.id, { headers: { Authorization: 'Bearer ' + tok() } });
      if (!r.ok) { let d = {}; try { d = await r.json(); } catch (_) {} if (d.plus) { P.plus(); return; } toast(d.error || 'Could not save it'); return; }
      const text = await r.text();
      const a = document.createElement('a'); a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(text); a.download = (c.title || 'stokvel') + '.csv'; document.body.appendChild(a); a.click(); a.remove();
      toast('Saved to Downloads ✓');
    } catch (_) { toast('Could not save it. Check your connection.'); }
  }

  // ---------------------------------------------------------------- styles
  const css = document.createElement('style');
  css.textContent = [
    'html.fc-app.fct .fc-msgs{background:var(--fct-bg)!important;background-attachment:local!important}',
    'html.fc-app.fct .fc-m.mine .fc-b{background:var(--fct-mine)!important;color:var(--fct-mine-ink)!important}html.fc-app.fct .fc-m.mine .fc-meta{color:var(--fct-mine-ink)!important;opacity:.75}',
    'html.fc-app.fct .fc-m.theirs .fc-b{background:var(--fct-theirs)!important;color:var(--fct-theirs-ink)!important}html.fc-app.fct .fc-m.theirs .fc-meta{color:var(--fct-theirs-ink)!important;opacity:.65}',
    '.fcp-packhd{display:flex;align-items:center;justify-content:space-between;margin:14px 2px 8px}.fcp-packhd b{color:#fff;font-size:15px}.fcp-packhd .ok,.fca-row .ok{color:#1ed6c8;font-weight:800}',
    '.fcp-themes{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.fcp-th{position:relative;height:96px;border-radius:14px;border:2px solid transparent;background-size:auto,cover;overflow:hidden;padding:0}.fcp-th.on{border-color:#1ed6c8}.fcp-th i{position:absolute;right:8px;top:12px;width:44%;height:14px;border-radius:8px}.fcp-th i.th{left:8px;right:auto;top:32px}.fcp-th span{position:absolute;left:0;right:0;bottom:0;padding:4px;background:rgba(0,0,0,.55);color:#fff;font-size:10.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fcp-th.locked{opacity:.85}',
    '.fcp-buy{color:#fde047!important;border-color:rgba(253,224,71,.55)!important;font-weight:800}',
    '.fcp-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.fcp-tile{display:flex;flex-direction:column;align-items:flex-start;gap:4px;text-align:left;padding:14px;border-radius:18px;border:1px solid var(--fca-line);background:var(--fca-card2);color:#fff;font:inherit}.fcp-tile i{font-size:28px;font-style:normal}.fcp-tile b{font-size:15px}.fcp-tile small{color:var(--fca-pale);font-size:12px;line-height:1.35}.fcp-tile em{font-style:normal;color:#fde047;font-weight:800;font-size:13px;margin-top:2px}',
    '.fcp-designs{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}.fcp-designs.sm{grid-template-columns:repeat(4,1fr)}.fcp-designs button{display:flex;flex-direction:column;align-items:center;gap:4px;padding:12px 4px;border-radius:14px;border:2px solid transparent;color:#fff;font:inherit;font-size:11.5px;font-weight:700}.fcp-designs button i{font-size:24px;font-style:normal}.fcp-designs button.on{border-color:#fff;box-shadow:0 0 0 2px #1ed6c8}',
    '.fcp-prop{text-align:center;padding:20px 14px;border-radius:20px;background:linear-gradient(160deg,#831843,#f43f5e);margin-bottom:12px;color:#fff}.fcp-prop .rings{font-size:54px;animation:fcpPulse 1.6s ease-in-out infinite}.fcp-prop b{display:block;font-size:22px;margin:4px 0}.fcp-prop p{color:#ffe4e6;font-size:14px;line-height:1.45}.fcp-prop p b{display:inline;font-size:inherit;margin:0;color:#fff}',
    '@keyframes fcpPulse{50%{transform:scale(1.12)}}@keyframes fcpRise{0%{transform:translateY(0);opacity:0}15%{opacity:1}100%{transform:translateY(-260px);opacity:0}}',
    '.fcp-fx{position:absolute;inset:0;pointer-events:none;overflow:hidden}.fcp-fx span{position:absolute;bottom:-30px;font-size:22px;animation:fcpRise 4.5s linear infinite}',
    '.fcp-stage{position:relative;min-height:62vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:26px;border-radius:22px;color:#fff;overflow:hidden;margin:0 10px}.fcp-stage .big{font-size:84px}.fcp-stage img{max-width:100%;max-height:36vh;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.35)}.fcp-stage h3{font-size:28px;margin:14px 0 6px;text-shadow:0 2px 10px rgba(0,0,0,.3)}.fcp-stage p{font-size:17px;white-space:pre-wrap;opacity:.95}.fcp-stage small{margin-top:10px;opacity:.85}.fcp-stage.quiet{background:linear-gradient(160deg,#111827,#334155)!important}.fcp-yes{margin-top:12px;font-size:22px;font-weight:900;background:rgba(255,255,255,.18);padding:10px 16px;border-radius:16px;animation:fcpPulse 1.4s infinite}',
    '.fcp-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.fcp-cards button{display:flex;flex-direction:column;align-items:center;gap:3px;padding:10px 2px;border-radius:12px;border:2px solid transparent;color:#fff;font:inherit;font-size:10.5px;font-weight:700}.fcp-cards button i{font-size:24px;font-style:normal}.fcp-cards button.on{border-color:#fff}',
    '.fcp-card{position:relative;overflow:hidden;border-radius:18px;padding:20px 16px 14px;color:#fff;text-align:center;min-width:230px;max-width:290px;margin:2px auto}.fcp-card .em{font-size:52px;animation:fcpPulse 2s infinite}.fcp-card b{display:block;font-size:20px;margin:6px 0}.fcp-card p{white-space:pre-wrap;font-size:14.5px;opacity:.95;margin:4px 0 10px}.fcp-card .tune{border:0;border-radius:20px;padding:8px 14px;background:rgba(255,255,255,.22);color:#fff;font-weight:800;position:relative}',
    '.fcp-pick{display:grid;gap:6px;max-height:30vh;overflow:auto;margin-bottom:10px}.fcp-pick label{display:flex;gap:10px;align-items:center;padding:10px 12px;border-radius:12px;background:rgba(255,255,255,.06);color:#fff}.fcp-pick input{width:20px;height:20px;accent-color:#1ed6c8}',
    '.fcp-inv{text-align:center;padding:22px 16px;border-radius:20px;color:#fff;margin-bottom:10px}.fcp-inv .em{font-size:50px}.fcp-inv small{opacity:.85}.fcp-inv b{display:block;font-size:22px;margin:6px 0}.fcp-inv p{margin:6px 0;font-size:15px}',
    '.fc-card.fcp-invc{color:#fff!important;border:0!important}.fc-card.fcp-invc .k{color:#fff!important;opacity:.9}.fc-card.fcp-invc .pri{background:#fff!important;color:#111827!important}',
    '.fc-card.fcp-propc{position:relative;overflow:hidden;text-align:center;color:#fff!important;background:linear-gradient(160deg,#831843,#f43f5e)!important;border:0!important;padding:18px 14px!important}.fcp-propc .em{font-size:48px;animation:fcpPulse 1.6s infinite}.fcp-propc b{font-size:19px}.fcp-propc .pri{background:#fff!important;color:#be123c!important;font-weight:900}.fcp-propc .sec{background:rgba(255,255,255,.18)!important;color:#fff!important}.fcp-propc.yes{background:linear-gradient(160deg,#be185d,#f59e0b)!important}',
    '.fcp-up{position:fixed;left:16px;right:16px;bottom:calc(var(--fca-nav,70px) + 80px);z-index:10150;background:#0b1d33;color:#fff;border-radius:14px;padding:12px 14px;box-shadow:0 10px 30px rgba(0,0,0,.4)}.fcp-up b{display:block;font-size:13px;margin-bottom:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fcp-up i{display:block;height:6px;border-radius:4px;background:rgba(255,255,255,.15)}.fcp-up em{display:block;height:100%;border-radius:4px;background:#1ed6c8;transition:width .3s}',
    '@media (max-width:360px){.fcp-themes,.fcp-cards{grid-template-columns:repeat(3,1fr)}}'
  ].join('');
  document.head.appendChild(css);

  try { applyTheme(curTheme()); } catch (_) {}
  setTimeout(() => { if (tok()) loadShop(); }, 1500);
  try { const q = new URLSearchParams(location.search); if (q.get('fcx') === 'event' && q.get('id')) setTimeout(() => openEvent(Number(q.get('id'))), 1600); } catch (_) {}
})();
