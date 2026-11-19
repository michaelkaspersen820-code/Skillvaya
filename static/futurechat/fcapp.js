/* FCAPP-02: the stand-alone Future Chat app (Google Play, za.co.futurechat.app) = the FULL original Future Chat app.
   Loaded only on /futurechat-app (window.SV_FC_APP = 1). Same accounts, chats and calls as Future Chat inside Skillvaya.
   Bottom tabs like the original app: Chats | Status | Calls | Circles | You. Profile picture, settings, call history,
   tasks / reminders / meeting proposals / polls, translation, blocked accounts, data saver, business and creator tools.
   Server side: fcextras.py (/api/fcx/*). Look: fcapp.css (original navy -> blue/teal design). */
(function () {
  'use strict';
  if (!window.SV_FC_APP) return;
  document.documentElement.classList.add('fc-app');

  // ---------------------------------------------------------------- helpers
  const tok = () => { try { return localStorage.getItem('skillvaya_token') || localStorage.getItem('sv_token') || ''; } catch (_) { return ''; } };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (s, el) => (el || document).querySelector(s);
  async function api(path, body) {
    const t = tok();
    const r = await fetch(path, { method: body ? 'POST' : 'GET', cache: 'no-store', credentials: 'same-origin',
      headers: Object.assign({ 'Content-Type': 'application/json' }, t ? { Authorization: 'Bearer ' + t } : {}), body: body ? JSON.stringify(body) : undefined });
    let d = {}; try { d = await r.json(); } catch (_) {}
    if (!r.ok) { const e = new Error(d.error || 'Something went wrong. Please try again.'); e.data = d; e.status = r.status; throw e; }
    return d;
  }
  const post = (p, b) => api(p, b || {});
  function toast(t) { const n = document.createElement('div'); n.className = 'fc-toast'; n.textContent = t; document.body.appendChild(n); setTimeout(() => n.remove(), 2600); }
  const initials = s => String(s || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0] || '').join('').toUpperCase() || '?';
  const hue = s => { let h = 0; for (const ch of String(s || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return h % 360; };
  function avatar(name, photo, cls) {
    return '<div class="fca-av ' + (cls || '') + '" style="' + (photo ? 'background-image:url(\'' + esc(photo) + '\');color:transparent' : 'background-color:hsl(' + hue(name) + ',50%,36%)') + '">' + esc(initials(name)) + '</div>';
  }
  function when(v) { const d = new Date(v); if (isNaN(d)) return ''; const n = new Date();
    if (d.toDateString() === n.toDateString()) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const y = new Date(n); y.setDate(n.getDate() - 1); if (d.toDateString() === y.toDateString()) return 'Yesterday ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return d.toLocaleDateString([], { day: 'numeric', month: 'short' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
  function dueText(v) { const d = new Date(v); if (!v || isNaN(d)) return ''; return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' }) + ' · ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
  function localInput(v) { const d = v ? new Date(v) : null; if (!d || isNaN(d)) return ''; const p = n => String(n).padStart(2, '0'); return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + 'T' + p(d.getHours()) + ':' + p(d.getMinutes()); }
  function sheet(html, mount) {
    const dim = document.createElement('div'); dim.className = 'fc-dim';
    dim.innerHTML = '<div class="fc-sheet" role="dialog" aria-modal="true"><div class="fc-handle"></div>' + html + '</div>';
    const done = () => dim.remove();
    dim.addEventListener('click', e => { if (e.target === dim) done(); });
    document.body.appendChild(dim); if (mount) mount(dim.firstChild, done); return dim;
  }
  const FC = () => window.FutureChat || {};
  const CM = () => window.FC_CHATMOJI || { cats: [], svg: {} };
  const SVG = {
    chats: '<svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    status: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" stroke-dasharray="4 2.5"/><circle cx="12" cy="12" r="4.5"/></svg>',
    calls: '<svg viewBox="0 0 24 24"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/></svg>',
    circles: '<svg viewBox="0 0 24 24"><circle cx="9" cy="9" r="5"/><circle cx="15" cy="15" r="5"/></svg>',
    you: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c1-4.5 4.4-7 8-7s7 2.5 8 7"/></svg>',
    back: '<svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
    newchat: '<svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M12 7v6M9 10h6"/></svg>',
    video: '<svg viewBox="0 0 24 24"><rect x="2" y="6" width="14" height="12" rx="2"/><path d="m22 8-6 4 6 4z"/></svg>',
    cam: '<svg viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>'
  };
  const MARK = '<svg class="fca-mark" viewBox="0 0 48 48" aria-hidden="true"><defs><linearGradient id="fcaMk" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5ff0e2"/><stop offset="1" stop-color="#12a8d0"/></linearGradient></defs><circle cx="24" cy="24" r="21" fill="url(#fcaMk)"/><path d="M15 16h18M15 23h13M15 30h8" stroke="#06283a" stroke-width="4" stroke-linecap="round"/><path d="M15 36v-6" stroke="#06283a" stroke-width="4" stroke-linecap="round"/></svg>';

  // ---------------------------------------------------------------- my account + settings (server)
  const X = { me: null, prefs: null, langs: [], counts: {}, peers: {}, tab: 'chats', stack: [] };
  async function loadMe() {
    try { const d = await api('/api/fcx/me'); X.me = d.me; X.prefs = d.prefs; X.langs = d.languages || []; X.counts = d.counts || {};
      try { localStorage.setItem('fc_data_saver', X.prefs.data_saver ? '1' : ''); } catch (_) {}
      paintMe(); } catch (_) {}
    return X.me;
  }
  function paintMe() {
    const m = X.me; if (!m) return;
    document.querySelectorAll('.fca-me').forEach(b => { b.style.backgroundImage = m.photo ? 'url(\'' + m.photo + '\')' : ''; b.textContent = m.photo ? '' : initials(m.name); });
  }
  async function savePrefs(patch) {
    try { const d = await post('/api/fcx/prefs', patch); X.prefs = d.prefs; try { localStorage.setItem('fc_data_saver', X.prefs.data_saver ? '1' : ''); } catch (_) {} return true; }
    catch (e) { toast(e.message); return false; }
  }
  async function loadPeers() {
    try { const d = await api('/api/fcx/peers'); X.peers = d.peers || {}; paintPeers(); } catch (_) {}
  }
  function paintPeers() {
    document.querySelectorAll('#fcRoot .fc-row[data-c]').forEach(r => {
      const p = X.peers[r.dataset.c]; const av = r.querySelector('.fc-av'); if (!av) return;
      if (p && p.photo) { av.style.backgroundImage = 'url(\'' + p.photo + '\')'; av.classList.add('ph'); }
      const nm = r.querySelector('.fc-name'); if (nm && p && p.seen === 'online' && !nm.querySelector('.fca-seen')) nm.insertAdjacentHTML('beforeend', '<span class="fca-seen">● online</span>');
    });
  }

  // ---------------------------------------------------------------- hooks used by fc.js
  const FCX = window.FCX = {};

  // ---------------------------------------------------------------- app language (FCX-I18N-01): pick on sign-up or in You -> Language
  const APP_LANGS = [
    ['en', 'English', 'English', 1], ['af', 'Afrikaans', 'Afrikaans', 1], ['zu', 'isiZulu', 'Zulu', 1], ['xh', 'isiXhosa', 'Xhosa', 1], ['st', 'Sesotho', 'Sotho', 1],
    ['tn', 'Setswana', 'Tswana', 1], ['sw', 'Kiswahili', 'Swahili', 1], ['fr', 'Français', 'French', 1], ['pt', 'Português', 'Portuguese', 1], ['es', 'Español', 'Spanish', 1],
    ['de', 'Deutsch', 'German', 1], ['hi', 'हिन्दी', 'Hindi', 1], ['zh', '中文', 'Chinese', 1], ['ar', 'العربية', 'Arabic', 1],
    ['nso', 'Sepedi', 'Northern Sotho'], ['ts', 'Xitsonga', 'Tsonga'], ['ve', 'Tshivenḓa', 'Venda'], ['ss', 'siSwati', 'Swati'], ['nr', 'isiNdebele', 'Ndebele'],
    ['sn', 'chiShona', 'Shona'], ['ny', 'Chichewa', 'Chichewa'], ['yo', 'Yorùbá', 'Yoruba'], ['ig', 'Igbo', 'Igbo'], ['ha', 'Hausa', 'Hausa'], ['am', 'አማርኛ', 'Amharic'],
    ['so', 'Soomaali', 'Somali'], ['rw', 'Kinyarwanda', 'Kinyarwanda'], ['lg', 'Luganda', 'Luganda'], ['mg', 'Malagasy', 'Malagasy'], ['nl', 'Nederlands', 'Dutch'],
    ['it', 'Italiano', 'Italian'], ['ru', 'Русский', 'Russian'], ['uk', 'Українська', 'Ukrainian'], ['pl', 'Polski', 'Polish'], ['tr', 'Türkçe', 'Turkish'],
    ['el', 'Ελληνικά', 'Greek'], ['ro', 'Română', 'Romanian'], ['hu', 'Magyar', 'Hungarian'], ['cs', 'Čeština', 'Czech'], ['sv', 'Svenska', 'Swedish'],
    ['nb', 'Norsk', 'Norwegian'], ['da', 'Dansk', 'Danish'], ['fi', 'Suomi', 'Finnish'], ['he', 'עברית', 'Hebrew'], ['fa', 'فارسی', 'Persian'], ['ur', 'اردو', 'Urdu'],
    ['bn', 'বাংলা', 'Bengali'], ['ta', 'தமிழ்', 'Tamil'], ['te', 'తెలుగు', 'Telugu'], ['gu', 'ગુજરાતી', 'Gujarati'], ['pa', 'ਪੰਜਾਬੀ', 'Punjabi'], ['mr', 'मराठी', 'Marathi'],
    ['ja', '日本語', 'Japanese'], ['ko', '한국어', 'Korean'], ['vi', 'Tiếng Việt', 'Vietnamese'], ['th', 'ไทย', 'Thai'], ['id', 'Bahasa Indonesia', 'Indonesian'],
    ['ms', 'Bahasa Melayu', 'Malay'], ['tl', 'Filipino', 'Filipino'], ['ka', 'ქართული', 'Georgian'], ['hy', 'Հայերեն', 'Armenian']
  ];
  const RTL = { ar: 1, he: 1, fa: 1, ur: 1 };
  const langInfo = c => APP_LANGS.find(x => x[0] === c) || null;
  function appLang() {
    try { const s = localStorage.getItem('fc_lang'); if (s && langInfo(s)) return s; } catch (_) {}
    try { for (const l of (navigator.languages || [navigator.language || ''])) { const c = String(l).toLowerCase(); const hit = langInfo(c.slice(0, 3)) || langInfo(c.slice(0, 2)); if (hit) return hit[0]; } } catch (_) {}
    return 'en';
  }
  let langTimer = 0;
  async function applyLang(code, tries) {
    clearTimeout(langTimer);
    try { localStorage.setItem('sv_lang', 'en'); } catch (_) {}   // Future Chat runs its own wording, not Skillvaya's
    if (typeof window.svUseDict !== 'function') { setTimeout(() => applyLang(code, tries), 300); return; }
    if (!code || code === 'en') { window.svUseDict('en', null); document.documentElement.dir = 'ltr'; return; }
    const info = langInfo(code) || [code, code, code];
    let cached = null; try { cached = JSON.parse(localStorage.getItem('fc_i18n_' + code) || 'null'); } catch (_) {}
    if (cached && cached.strings) { window.svUseDict(code, cached.strings); document.documentElement.dir = RTL[code] ? 'rtl' : 'ltr'; }
    try {
      const r = await fetch('/api/fcx/i18n?lang=' + encodeURIComponent(code) + '&name=' + encodeURIComponent(info[2]), { cache: 'no-store' });
      const d = await r.json();
      if (d && d.strings) {
        try { localStorage.setItem('fc_i18n_' + code, JSON.stringify({ strings: d.strings, at: Date.now() })); } catch (_) {}
        if (appLang() === code) { window.svUseDict(code, d.strings); document.documentElement.dir = RTL[code] ? 'rtl' : 'ltr'; }
        tries = (tries || 0) + 1;
        if (!d.complete && d.filling && tries < 12 && appLang() === code) langTimer = setTimeout(() => applyLang(code, tries), 20000);
      }
    } catch (_) {}
  }
  function setAppLang(code) {
    try { localStorage.setItem('fc_lang', code); } catch (_) {}
    applyLang(code);
    try { if (tok()) post('/api/fcx/prefs', { app_lang: code }).catch(() => {}); } catch (_) {}
  }
  function langPicker(onDone) {
    const cur = appLang();
    const rowL = l => '<button type="button" class="fc-act" data-l="' + l[0] + '" data-no-tr style="' + (l[0] === cur ? 'border:1px solid #1ed6c8;border-radius:12px' : '') + '"><i style="font-size:13px;font-weight:800">' + l[0].toUpperCase() + '</i><span style="flex:1">' + esc(l[1]) + (l[1] !== l[2] ? ' <small style="color:#9cb7cc">· ' + esc(l[2]) + '</small>' : '') + '</span>' + (l[0] === cur ? '<b style="color:#1ed6c8">✓</b>' : '') + '</button>';
    sheet('<h3 data-no-tr>🌐 Language · Taal · Ulimi · Ulwimi · Puo</h3><input id="fcaLangQ" placeholder="Search · Soek · Sesha" data-no-tr style="margin:6px 0 10px">' +
      '<div id="fcaLangL" class="fc-acts" style="max-height:58vh;overflow:auto"></div>', (el, done) => {
      const paint = q => { q = (q || '').toLowerCase(); const list = APP_LANGS.filter(l => !q || (l[1] + ' ' + l[2] + ' ' + l[0]).toLowerCase().includes(q));
        const top = list.filter(l => l[3]), rest = list.filter(l => !l[3]);
        $('#fcaLangL', el).innerHTML = top.map(rowL).join('') + (rest.length ? '<p data-no-tr style="margin:12px 4px 4px;font-size:12px;color:#9cb7cc">More languages (translated automatically the first time)</p>' + rest.map(rowL).join('') : '');
        el.querySelectorAll('[data-l]').forEach(b => b.onclick = () => { done(); setAppLang(b.dataset.l); if (onDone) onDone(b.dataset.l); }); };
      $('#fcaLangQ', el).oninput = e => paint(e.target.value); paint('');
    });
  }
  FCX.langPicker = langPicker;
  applyLang(appLang());
  FCX.listHeader = function (root) {
    const hdr = root.querySelector('.fc-hdr'); const row = hdr && hdr.querySelector('.fc-hrow'); if (!row) return;
    const top = document.createElement('div');
    top.innerHTML = '<div class="fca-brand">' + MARK + '<div class="fca-bt"><b>FUTURE CHAT</b><small>Stay close. Wherever life takes you.</small></div><button class="fca-me" type="button" aria-label="You: profile and settings"></button></div>' +
      '<div class="fca-title" style="margin-top:10px"><div><h1>Chats</h1><p>Your people, all in one place</p></div><button class="fca-ib" type="button" id="fcaNewChat" aria-label="New chat">' + SVG.newchat + '</button></div>';
    row.replaceWith(top);
    top.querySelector('.fca-me').onclick = () => go('you');
    top.querySelector('#fcaNewChat').onclick = () => FC().newChat && FC().newChat();
    const q = hdr.querySelector('#fcQ'); if (q) q.placeholder = 'Search messages';
    paintMe();
    // FCA-HDR-02: the big top part folds away as you scroll the chats, so the list gets the whole screen
    const body = root.querySelector('#fcBody');
    if (body) { let coll = false; body.addEventListener('scroll', () => { const y = body.scrollTop;
      if (!coll && y > 48) { coll = true; hdr.classList.add('fca-hcoll'); } else if (coll && y < 6) { coll = false; hdr.classList.remove('fca-hcoll'); } }, { passive: true }); }
  };
  FCX.afterList = function (body, items, S) {
    paintPeers();
    if (!S || S.archivedView || (S.filter && S.filter !== 'all') || (S.q || '').trim()) return;
    const sp = document.createElement('div'); sp.className = 'fca-space';
    sp.innerHTML = '<div class="fca-sec">Your space</div><div class="fca-tiles">' +
      '<button class="fca-tile" data-g="circles"><i>◎</i><b>Circles</b><small>Your people and groups</small></button>' +
      '<button class="fca-tile" data-g="tasks"><i>✓</i><b>Tasks</b><small>Plans and reminders</small></button>' +
      '<button class="fca-tile" data-g="chatmoji"><i>✦</i><b>Future Chatmoji</b><small>Add a little meaning</small></button></div>';
    const spacer = body.lastElementChild && !body.lastElementChild.className ? body.lastElementChild : null;
    const fab = body.querySelector('.fc-fab');
    body.insertBefore(sp, spacer || fab || null);
    celebStrip(body);
    sp.querySelectorAll('[data-g]').forEach(b => b.onclick = () => { const g = b.dataset.g; if (g === 'circles') go('circles'); else if (g === 'tasks') { go('you'); push(scrTasks); } else { go('you'); push(scrChatmoji); } });
    navBadge();
    if (!FCX._peersAt || Date.now() - FCX._peersAt > 20000) { FCX._peersAt = Date.now(); loadPeers(); }
  };
  FCX.afterHeader = function (root, c) {
    const p = X.peers[String(c.id)] || {};
    const av = root.querySelector('#fcAv'); if (av && p.photo) { av.style.backgroundImage = 'url(\'' + p.photo + '\')'; av.style.backgroundSize = 'cover'; av.style.color = 'transparent'; }
    const sub = root.querySelector('#fcSub'); if (sub && c.kind !== 'group') sub.textContent = p.blocked ? 'Blocked' : (p.seen || 'Tap here for their profile');
    const t = root.querySelector('.fc-conv-hdr .fc-ttl');
    if (t && !t.dataset.fcx) { t.dataset.fcx = '1'; t.onclick = () => { if (c.kind === 'group') { openPanel(); push(() => scrCircle(c.id, c.title)); } else if (p.user_id) { openPanel(); push(() => scrPeer(p.user_id, c.id)); } }; if (av) av.onclick = t.onclick; }
  };
  FCX.card = function (m) {
    const k = m.meta.fcx_kind || 'task', id = Number(m.meta.fcx) || 0;
    const label = { poll: '📊 POLL', task: '✅ TASK', event: '📅 MEETING PROPOSAL', reminder: '⏰ REMINDER' }[k] || 'ITEM';
    const title = String(m.body || '').replace(/^[^:]*:\s*/, '');
    const btn = { poll: 'Vote', task: 'Open task', event: 'Reply yes / no', reminder: 'Open' }[k] || 'Open';
    return '<div class="fc-card fcx-card"><span class="k">' + label + '</span><b>' + esc(title) + '</b><button class="pri" onclick="event.stopPropagation();window.FCX.openItem(' + id + ')">' + btn + '</button></div>';
  };
  FCX.attachTiles = function (conv) {
    if (!conv || !conv.id) return [];
    return [['📊', 'Poll', '#0e8c9e', () => itemForm('poll', conv.id)], ['✅', 'Task', '#0f766e', () => itemForm('task', conv.id)],
      ['📅', 'Meeting', '#1d4ed8', () => itemForm('event', conv.id)], ['⏰', 'Reminder', '#7c3aed', () => itemForm('reminder', conv.id)],
      ['🕛', 'Schedule', '#0f766e', () => scheduleForm(conv)], ['🎉', 'Greeting card', '#be185d', () => greetingFor(conv)]];
  };
  FCX.convActs = function (c) {
    const acts = [], p = X.peers[String(c.id)] || {};
    if (c.kind !== 'group' && p.user_id) acts.unshift(['👤', 'View profile', () => { openPanel(); push(() => scrPeer(p.user_id, c.id)); }]);
    if (c.kind === 'group') acts.push(['🏡', 'Family Circle home', () => { openPanel(); push(() => scrCircle(c.id, c.title)); }]);
    acts.push(['✅', 'Tasks, polls and meetings', () => { openPanel(); push(() => scrCirclePlans(c.id, c.title)); }]);
    if (c.kind !== 'group' && p.user_id) acts.push(['🚫', p.blocked ? 'Unblock' : 'Block', () => blockUser(p.user_id, !p.blocked, c.title)]);
    acts.push(['💾', 'Save a copy of this chat', () => saveCopy(c.id, c.title)]);
    acts.push(['🧹', 'Clear chat', () => clearChats(c.id, c.title), 'danger']);
    return acts;
  };
  FCX.dataSaver = () => !!(X.prefs ? X.prefs.data_saver : (function () { try { return localStorage.getItem('fc_data_saver'); } catch (_) { return ''; } })());
  FCX.savedBytes = n => { try { const mk = new Date().toISOString().slice(0, 7); let s = JSON.parse(localStorage.getItem('fc_ds') || '{}'); if (s.m !== mk) s = { m: mk, b: 0, n: 0 }; s.b += Math.max(0, n); s.n += 1; localStorage.setItem('fc_ds', JSON.stringify(s)); } catch (_) {} };
  FCX.translate = function (text) {
    const langs = X.langs.length ? X.langs : ['English', 'Afrikaans', 'isiZulu', 'isiXhosa'];
    let to = (X.prefs && X.prefs.language) || 'English';
    sheet('<h3>Translate</h3><p style="white-space:pre-wrap">' + esc(text.slice(0, 600)) + '</p><label class="fca-field"><span>Translate into</span><select id="fcaTrTo">' + langs.map(l => '<option' + (l === to ? ' selected' : '') + '>' + esc(l) + '</option>').join('') + '</select></label><div id="fcaTrOut"></div><button class="fc-btn" id="fcaTrGo">Translate</button>', (el) => {
      const out = $('#fcaTrOut', el), go_ = $('#fcaTrGo', el);
      const run = async () => { to = $('#fcaTrTo', el).value; go_.disabled = true; out.innerHTML = '<div class="fca-tr"><small>' + esc(to.toUpperCase()) + '</small>Translating…</div>';
        try { const d = await post('/api/fcx/translate', { text, to }); out.innerHTML = '<div class="fca-tr"><small>' + esc(d.to.toUpperCase()) + '</small>' + esc(d.text) + '</div>'; }
        catch (e) { out.innerHTML = '<div class="fca-tr"><small>TRANSLATION</small>' + esc(e.message) + '</div>'; }
        go_.disabled = false; };
      go_.onclick = run; $('#fcaTrTo', el).onchange = run; run();
    });
  };
  FCX.openItem = id => itemSheet(id);
  FCX.onBack = function () {
    if (document.querySelector('.fc-dim')) { const d = document.querySelectorAll('.fc-dim'); d[d.length - 1].remove(); keepEntry(); return true; }
    if (X.stack.length > 1) { X.stack.pop(); draw(); return true; }
    if (X.stack.length === 1 && X.inline) { X.stack = []; X.inline = false; closePanel(); return true; }
    if (X.tab !== 'chats') { go('chats', true); return true; }
    return false;
  };
  function keepEntry() { try { history.pushState({ fcx: 1 }, ''); } catch (_) {} }

  // ---------------------------------------------------------------- bottom tabs + panel
  let nav, panel;
  function build() {
    if (nav) return;
    nav = document.createElement('nav'); nav.id = 'fcaNav'; nav.setAttribute('aria-label', 'Future Chat');
    nav.innerHTML = [['chats', 'Chats'], ['status', 'Status'], ['calls', 'Calls'], ['circles', 'Circles'], ['you', 'You']].map(([k, l]) =>
      '<button type="button" data-t="' + k + '" class="' + (k === 'chats' ? 'on' : '') + '">' + SVG[k] + '<span>' + l + '</span>' + (k === 'chats' ? '<b class="dot" id="fcaChatsDot"></b>' : '') + '</button>').join('');
    document.body.appendChild(nav);
    nav.querySelectorAll('button').forEach(b => b.onclick = () => go(b.dataset.t));
    panel = document.createElement('section'); panel.id = 'fcaPanel'; panel.setAttribute('aria-live', 'polite');
    document.body.appendChild(panel);
    window.addEventListener('fc:view', e => {
      const conv = e.detail && e.detail.conv;
      document.documentElement.classList.toggle('fca-inconv', !!conv);
      if (conv && panel.classList.contains('open')) { X.stack = []; X.inline = false; closePanel(); setTab('chats'); }
    });
  }
  function setTab(t) { X.tab = t; if (nav) nav.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.t === t)); }
  function openPanel() { panel.classList.add('open'); if (!X.stack.length) X.inline = true; }
  function closePanel() { panel.classList.remove('open'); panel.innerHTML = ''; }
  function go(t, fromBack) {
    const was = X.tab; setTab(t); X.inline = false;
    if (t === 'chats') { X.stack = []; closePanel(); try { const st = FC().state && FC().state(); if (!st || !st.open) FC().open(); else if (st.conv) { history.back(); } else FC().reloadList(); } catch (_) {} return; }
    if (!fromBack && was === 'chats') keepEntry();
    X.stack = [{ chats: 0, status: scrStatus, calls: scrCalls, circles: scrCircles, you: scrYou }[t]];
    panel.classList.add('open'); draw();
  }
  function push(fn) { if (!panel.classList.contains('open')) openPanel(); X.stack.push(fn); keepEntry(); draw(); }
  function pop() { if (X.stack.length > 1 || X.inline) { try { history.back(); } catch (_) { FCX.onBack(); } } }
  function draw() {
    const fn = X.stack[X.stack.length - 1]; if (!fn) { closePanel(); return; }
    panel.classList.toggle('full', !!X.inline);
    panel.scrollTop = 0; fn();
  }
  // page frame: header (title / back) + scrolling body
  function frame(title, sub, opts) {
    opts = opts || {};
    const root = X.stack.length <= 1 && !X.inline;
    panel.innerHTML = '<header class="fca-hd">' + (root ? '<div class="fca-brand">' + MARK + '<div class="fca-bt"><b>FUTURE CHAT</b><small>Stay close. Wherever life takes you.</small></div><button class="fca-me" type="button" aria-label="You"></button></div>' +
      '<div class="fca-title"><div><h1>' + esc(title) + '</h1><p>' + esc(sub || '') + '</p></div>' + (opts.action ? '<button class="fca-ib" type="button" id="fcaHdAct" aria-label="' + esc(opts.action[1]) + '">' + opts.action[0] + '</button>' : '') + '</div>'
      : '<div class="fca-sub"><button class="fca-back" type="button" aria-label="Back">' + SVG.back + '</button><h2>' + esc(title) + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</h2>' + (opts.action ? '<button class="fca-ib" type="button" id="fcaHdAct" aria-label="' + esc(opts.action[1]) + '">' + opts.action[0] + '</button>' : '') + '</div>') +
      '</header><div class="fca-bd" id="fcaBd"></div>';
    const b = $('.fca-back', panel); if (b) b.onclick = pop;
    const me = $('.fca-me', panel); if (me) me.onclick = () => go('you');
    const a = $('#fcaHdAct', panel); if (a && opts.action) a.onclick = opts.action[2];
    paintMe();
    return $('#fcaBd', panel);
  }
  function row(ic, title, sub, attrs, end) {
    return '<button type="button" class="fca-row ' + (attrs && attrs.cls || '') + '" ' + (attrs && attrs.data || '') + '><span class="ic">' + ic + '</span><span class="tx"><b>' + esc(title) + '</b>' + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</span>' + (end != null ? end : '<span class="chev">›</span>') + '</button>';
  }
  function bind(el, map) { el.querySelectorAll('[data-a]').forEach(b => { const f = map[b.dataset.a]; if (f) b.onclick = () => f(b); }); }
  function navBadge() {
    try { const st = FC().state(); const n = (st.list || []).reduce((a, c) => a + (c.archived ? 0 : (c.unread || 0)), 0); const d = $('#fcaChatsDot'); if (d) { d.textContent = n > 99 ? '99+' : String(n); d.style.display = n ? 'grid' : 'none'; } } catch (_) {}
  }

  // ---------------------------------------------------------------- STATUS tab
  async function scrStatus() {
    const bd = frame('Status', 'Moments that disappear after 24 hours', { action: [SVG.cam, 'New status', () => window.FutureChatStatus && window.FutureChatStatus.compose()] });
    bd.innerHTML = '<div class="fca-empty"><span class="big">◌</span><b>Loading status…</b></div>';
    const FS = window.FutureChatStatus; if (!FS) { bd.innerHTML = '<div class="fca-empty"><b>Status is loading</b>Try again in a moment.</div>'; return; }
    await FS.load(true); await loadBirthdays(); if (X.stack[X.stack.length - 1] !== scrStatus) return;
    const bdayIds = bdayToday().map(b => b.user_id);
    const d = FS.data() || { mine: [], others: [], sponsored: [] }; const me = X.me || {};
    const rings = d.sponsored_rings && d.sponsored_rings.length ? d.sponsored_rings : [d.sponsored && d.sponsored.length ? d.sponsored : [FS.house()]];   // FC-ADS-02
    const ads = rings[0];
    const views = (d.mine || []).reduce((a, s) => a + (s.views || 0), 0);
    let h = '<div class="fca-card"><button type="button" class="fca-row" data-a="mine"><span class="fca-sp"><span class="fca-ring ' + (d.mine.length ? 'seen' : 'none') + '">' + avatar(me.name, me.photo) + '<span class="plus">+</span></span></span><span class="tx"><b>My status</b><small>' +
      (d.mine.length ? d.mine.length + (d.mine.length === 1 ? ' update' : ' updates') + ' · ' + views + (views === 1 ? ' view' : ' views') : 'Tap to add a photo, video or text') + '</small></span><span class="chev">›</span></button>' +
      '<button type="button" class="fca-row" data-a="add"><span class="ic">✎</span><span class="tx"><b>Add to my status</b><small>Photo, video or text · visible for 24 hours</small></span><span class="chev">›</span></button></div>';
    const so = d.shoutouts || [];
    h += '<div class="fca-gl">Shout-outs</div><div class="fca-card">' + (so.length ? '<button type="button" class="fca-row" data-a="shouts"><span class="fca-sp"><span class="fca-ring" style="background:conic-gradient(#f43f5e,#f59e0b,#ec4899,#f43f5e)"><div class="fca-av" style="background:linear-gradient(135deg,#be185d,#f59e0b);font-size:22px">📣</div></span></span><span class="tx"><b>Shout-outs' + (so.some(a => a.tier === 'propose') ? ' 💍' : '') + '</b><small>' + so.length + (so.length === 1 ? ' shout-out' : ' shout-outs') + ' · birthdays, congrats, proposals…</small></span><span class="chev">›</span></button>' : '') +
      '<button type="button" class="fca-row" data-a="newshout"><span class="ic">📣</span><span class="tx"><b>Send a shout-out</b><small>To everyone, or just your contacts · from R5</small></span><span class="chev">›</span></button></div>';
    h += '<div class="fca-gl">Sponsored</div><div class="fca-card">' + rings.map((r, i) => '<button type="button" class="fca-row" data-ring="' + i + '"><span class="fca-sp"><span class="fca-ring ad"><div class="fca-av" style="background:#3a2a00;font-size:12px">AD</div></span></span><span class="tx"><b>Sponsored' + (rings.length > 1 ? ' ' + (i + 1) : '') + '</b><small>' + r.length + (r.length === 1 ? ' business' : ' businesses') + ' · only when you open it</small></span><span class="chev">›</span></button>').join('') + '</div>';
    const unseen = (d.others || []).map((p, i) => [p, i]).filter(x => x[0].unseen), seen = (d.others || []).map((p, i) => [p, i]).filter(x => !x[0].unseen);
    const list = arr => arr.map(([p, i]) => '<button type="button" class="fca-row" data-a="p" data-i="' + i + '"><span class="fca-sp"><span class="fca-ring ' + (p.unseen ? '' : 'seen') + '">' + avatar(p.name, peerPhotoByUser(p.user_id)) + '</span></span><span class="tx"><b>' + esc(p.name) + (bdayIds.indexOf(p.user_id) >= 0 ? ' 🎂' : '') + '</b><small>' + esc(when(p.latest)) + ' · ' + p.items.length + (p.items.length === 1 ? ' update' : ' updates') + '</small></span></button>').join('');
    if (unseen.length) h += '<div class="fca-gl">Recent updates</div><div class="fca-card">' + list(unseen) + '</div>';
    if (seen.length) h += '<div class="fca-gl">Viewed updates</div><div class="fca-card">' + list(seen) + '</div>';
    if (!d.others || !d.others.length) h += '<div class="fca-empty"><span class="big">◎</span><b>No updates yet</b>When the people you chat with post a status, it shows here.</div>';
    const vis = X.prefs && X.prefs.status === 'nobody' ? 'Nobody (your status is hidden)' : 'The people you chat with';
    h += '<div class="fca-card">' + row('🔒', 'Who sees my status', vis, { data: 'data-a="privacy"' }) + '</div>';
    bd.innerHTML = h;
    bind(bd, { mine: () => d.mine.length ? FS.view([{ name: 'My status', items: d.mine, mine: true }], 0) : FS.compose(), add: () => FS.compose(), shouts: () => FS.ads(d.shoutouts || []), newshout: () => { if (FCX.shop && FCX.shop.shout) FCX.shop.shout(false); },
      p: b => FS.view(d.others.map(p => ({ name: p.name, items: p.items })), Number(b.dataset.i)), privacy: () => push(scrPrivacy) });
  }
  function peerPhotoByUser(uid) { for (const k in X.peers) if (X.peers[k].user_id === uid && X.peers[k].photo) return X.peers[k].photo; return ''; }
  // refresh the Status tab after posting / viewing
  setInterval(() => { if (panel && X.stack.length === 1 && X.stack[0] === scrStatus && !document.getElementById('fcsView') && !document.querySelector('.fc-dim') && document.visibilityState !== 'hidden') { const t = Date.now(); if (!X._stAt || t - X._stAt > 15000) { X._stAt = t; scrStatus(); } } }, 3000);

  // ---------------------------------------------------------------- CALLS tab
  async function scrCalls() {
    const bd = frame('Calls', 'Voice and video calls, free over data', { action: [SVG.plus, 'New call', newCall] });
    bd.innerHTML = '<div class="fca-empty"><span class="big">📞</span><b>Loading your calls…</b></div>';
    let items = []; try { items = (await api('/api/fcx/calls')).items || []; } catch (e) { bd.innerHTML = '<div class="fca-empty"><b>Couldn\'t load your calls</b>' + esc(e.message) + '</div>'; return; }
    if (X.stack[X.stack.length - 1] !== scrCalls) return;
    if (!items.length) { bd.innerHTML = '<div class="fca-empty"><span class="big">📞</span><b>No calls yet</b>Call anyone you chat with — free over Wi-Fi or mobile data.</div><button class="fca-btn" data-a="new">Start a call</button>'; bind(bd, { new: newCall }); return; }
    const missed = items.filter(c => c.missed && !c.outgoing).length;
    let h = '<div class="fca-seg" style="margin-bottom:12px"><button class="on" data-f="all">All</button><button data-f="missed">Missed' + (missed ? ' (' + missed + ')' : '') + '</button></div><div class="fca-card" id="fcaCallList"></div>';
    bd.innerHTML = h;
    const paint = f => {
      const list = f === 'missed' ? items.filter(c => c.missed && !c.outgoing) : items;
      $('#fcaCallList', bd).innerHTML = list.length ? list.map((c, i) => {
        const dir = c.outgoing ? (c.answered ? '↗ Outgoing' : '↗ No answer') : (c.missed ? '↙ Missed' : '↙ Incoming');
        const dur = c.seconds ? ' · ' + (c.seconds >= 60 ? Math.floor(c.seconds / 60) + ' min ' : '') + (c.seconds % 60) + ' s' : '';
        return '<button type="button" class="fca-row' + (c.missed && !c.outgoing ? ' miss' : '') + '" data-i="' + items.indexOf(c) + '">' + avatar(c.name, peerPhotoByUser(c.other_id), 'sm') + '<span class="tx"><b>' + esc(c.name) + '</b><small>' + esc(dir) + ' ' + (c.video ? 'video' : 'voice') + ' call · ' + esc(when(c.at)) + esc(dur) + '</small></span><span class="end" style="font-size:20px">' + (c.video ? '🎥' : '📞') + '</span></button>';
      }).join('') : '<div class="fca-empty" style="margin:0;border:0">No missed calls</div>';
      $('#fcaCallList', bd).querySelectorAll('[data-i]').forEach(b => b.onclick = () => callSheet(items[Number(b.dataset.i)]));
    };
    bd.querySelectorAll('.fca-seg button').forEach(b => b.onclick = () => { bd.querySelectorAll('.fca-seg button').forEach(x => x.classList.toggle('on', x === b)); paint(b.dataset.f); });
    paint('all');
    const clr = document.createElement('div'); clr.className = 'fca-card'; clr.innerHTML = row('🗑️', 'Clear call history', 'Remove every call from this list', { data: 'data-a="clrcalls"', cls: 'danger' }, '');
    bd.appendChild(clr); bind(clr, { clrcalls: clearCalls });
  }
  // FCX-CALLCLEAR-01: clear the whole call list, or one call
  async function clearCalls() {
    if (!confirm('Clear your whole call history? Only your list is cleared — the other person keeps theirs.')) return;
    try { await api('/api/fcx/calls/clear', {}); toast('Call history cleared'); if (X.stack[X.stack.length - 1] === scrCalls) scrCalls(); } catch (e) { toast(e.message); }
  }
  document.addEventListener('click', e => { const b = e.target.closest && e.target.closest('#fcaPanel [data-ring]'); if (!b) return; const d = (window.FutureChatStatus && window.FutureChatStatus.data()) || {}; const rings = d.sponsored_rings && d.sponsored_rings.length ? d.sponsored_rings : [d.sponsored && d.sponsored.length ? d.sponsored : [window.FutureChatStatus.house()]]; window.FutureChatStatus.ads(rings[Number(b.dataset.ring)] || rings[0]); });
  function callSheet(c) {
    sheet('<h3>' + esc(c.name) + '</h3><p>' + esc(when(c.at)) + '</p><div class="fc-acts">' +
      (c.conversation_id ? '<button class="fc-act" data-a="voice"><i>📞</i>Voice call</button><button class="fc-act" data-a="video"><i>🎥</i>Video call</button><button class="fc-act" data-a="msg"><i>💬</i>Message</button>' : '<p>This call was made before Future Chat calls had chats.</p>') +
      '<button class="fc-act" data-a="del"><i>🗑️</i>Delete from call history</button></div>', (el, done) => bind(el, {
        voice: () => { done(); FC().callConv(c.conversation_id, 'voice'); }, video: () => { done(); FC().callConv(c.conversation_id, 'video'); },
        msg: () => { done(); FC().openConv(c.conversation_id); },
        del: async () => { done(); try { await api('/api/fcx/calls/delete', { id: c.id }); toast('Removed from call history'); if (X.stack[X.stack.length - 1] === scrCalls) scrCalls(); } catch (e) { toast(e.message); } } }));
  }
  function directChats() { try { return (FC().state().list || []).filter(c => c.kind !== 'group' && !c.archived); } catch (_) { return []; } }
  function newCall() {
    const list = directChats();
    sheet('<h3>New call</h3>' + (list.length ? '<p>Choose who to call.</p><div class="fc-acts">' + list.slice(0, 60).map(c => '<button class="fc-act" data-c="' + c.id + '"><i>📞</i><span style="flex:1">' + esc(c.title) + '</span><span data-v="' + c.id + '" style="font-size:20px;padding:0 6px">🎥</span></button>').join('') + '</div>'
      : '<p>Start a chat with someone first, then you can call them.</p><button class="fc-btn" id="fcaNc">New chat</button>'), (el, done) => {
      el.querySelectorAll('[data-c]').forEach(b => b.onclick = e => { done(); const v = e.target.closest('[data-v]'); FC().callConv(Number(b.dataset.c), v ? 'video' : 'voice'); });
      const nc = $('#fcaNc', el); if (nc) nc.onclick = () => { done(); go('chats'); setTimeout(() => FC().newChat(), 200); };
    });
  }

  // ---------------------------------------------------------------- CIRCLES tab (groups + their tasks, polls, meetings)
  function scrCircles() {
    const bd = frame('Circles', 'Your people and groups', { action: [SVG.plus, 'New circle', () => FC().newGroup && FC().newGroup()] });
    let groups = []; try { groups = (FC().state().list || []).filter(c => c.kind === 'group'); } catch (_) {}
    let h = '<div class="fca-acts" style="grid-template-columns:repeat(2,1fr)"><button class="fca-act" data-a="new"><i>➕</i>New circle</button><button class="fca-act" data-a="games"><i>🎮</i>Game Rooms</button><button class="fca-act" data-a="tasks"><i>✅</i>All tasks</button><button class="fca-act" data-a="stokvel"><i>💰</i>Stokvels</button></div>';
    if (!groups.length) h += '<div class="fca-empty"><span class="big">◎</span><b>No circles yet</b>A circle is a group of your people — family, friends, a team or a stokvel — with its own chat, tasks, polls and meetings.</div>';
    else h += '<div class="fca-gl">Your circles</div><div class="fca-card">' + groups.map(g => '<button type="button" class="fca-row" data-g="' + g.id + '">' + avatar(g.title, '', 'sm') + '<span class="tx"><b>' + esc(g.title) + '</b><small>' + esc(g.last ? (g.last.mine ? 'You: ' : '') + g.last.text.replace(/:([a-z0-9_]+):/g, '') : 'No messages yet') + '</small></span>' + (g.unread ? '<span class="end"><b class="fc-badge" style="display:inline-grid">' + g.unread + '</b></span>' : '<span class="chev">›</span>') + '</button>').join('') + '</div>';
    bd.innerHTML = h;
    bind(bd, { new: () => FC().newGroup(), games: () => FCX.gameRooms ? FCX.gameRooms() : toast('Game Rooms is loading - try again in a moment'), tasks: () => push(scrTasks), stokvel: () => toast(groups.length ? 'Open a circle, then choose Stokvel in its chat menu' : 'Create a circle first, then start a stokvel in it') });
    bd.querySelectorAll('[data-g]').forEach(b => b.onclick = () => { const g = groups.find(x => x.id === Number(b.dataset.g)); push(() => scrCircle(g.id, g.title)); });
  }
  function scrCircle(id, title) { return FCX.circleHome ? FCX.circleHome(id, title) : scrCirclePlans(id, title); }
  async function scrCirclePlans(id, title) {
    const self = X.stack[X.stack.length - 1];
    const bd = frame(title || 'Circle', 'Tasks, polls and meetings');
    bd.innerHTML = '<div class="fca-acts"><button class="fca-act" data-a="chat"><i>💬</i>Open chat</button><button class="fca-act" data-a="poll"><i>📊</i>Poll</button><button class="fca-act" data-a="task"><i>✅</i>Task</button><button class="fca-act" data-a="event"><i>📅</i>Meeting</button><button class="fca-act" data-a="reminder"><i>⏰</i>Reminder</button><button class="fca-act" data-a="call"><i>📞</i>Call</button></div><div id="fcaItems"><div class="fca-empty">Loading…</div></div>';
    bind(bd, { chat: () => FC().openConv(id), call: () => FC().callConv(id, 'voice'), poll: () => itemForm('poll', id, () => scrCirclePlans(id, title)), task: () => itemForm('task', id, () => scrCirclePlans(id, title)), event: () => itemForm('event', id, () => scrCirclePlans(id, title)), reminder: () => itemForm('reminder', id, () => scrCirclePlans(id, title)) });
    let items = []; try { items = (await api('/api/fcx/items?c=' + id)).items || []; } catch (e) { $('#fcaItems', bd).innerHTML = '<div class="fca-empty"><b>Couldn\'t load</b>' + esc(e.message) + '</div>'; return; }
    if (X.stack[X.stack.length - 1] !== self) return;
    itemList($('#fcaItems', bd), items, () => scrCirclePlans(id, title), 'Nothing planned here yet. Add a poll, task, meeting proposal or reminder — everyone in the chat sees it.');
  }

  // ---------------------------------------------------------------- tasks / reminders / meetings / polls
  const KIND = { task: ['✅', 'Task'], reminder: ['⏰', 'Reminder'], event: ['📅', 'Meeting proposal'], poll: ['📊', 'Poll'] };
  function itemList(box, items, refresh, emptyText) {
    if (!items.length) { box.innerHTML = '<div class="fca-empty"><span class="big">✓</span><b>All clear</b>' + esc(emptyText || 'Nothing here yet.') + '</div>'; return; }
    const open = items.filter(i => !i.done), done = items.filter(i => i.done);
    const one = i => '<div class="fca-item' + (i.done ? ' done' : '') + '" data-id="' + i.id + '">' +
      (i.kind === 'task' || i.kind === 'reminder' ? '<button class="ck' + (i.done ? ' on' : '') + '" data-ck="' + i.id + '" aria-label="Mark done">' + (i.done ? '✓' : '') + '</button>' : '<span style="font-size:20px;width:26px;text-align:center">' + KIND[i.kind][0] + '</span>') +
      '<div class="tx"><b>' + esc(i.title) + '</b><small>' + esc(KIND[i.kind][1]) + (i.where ? ' · ' + esc(i.where) : '') + (i.kind === 'poll' ? ' · ' + i.votes + (i.votes === 1 ? ' vote' : ' votes') : '') + (i.kind === 'event' && i.rsvp ? ' · ' + i.rsvp.yes + ' going' : '') + (i.done && i.done_by ? ' · done by ' + esc(i.done_by) : '') + '</small>' +
      (i.due_at ? '<span class="due">' + (i.kind === 'event' ? 'WHEN  ' : 'DUE  ') + esc(dueText(i.due_at).toUpperCase()) + '</span>' : '') + (i.place ? '<small>📍 ' + esc(i.place) + '</small>' : '') + '</div></div>';
    box.innerHTML = (open.length ? '<div class="fca-card">' + open.map(one).join('') + '</div>' : '') + (done.length ? '<div class="fca-gl">Done</div><div class="fca-card">' + done.map(one).join('') + '</div>' : '');
    box.querySelectorAll('[data-ck]').forEach(b => b.onclick = async e => { e.stopPropagation(); const it = items.find(x => x.id === Number(b.dataset.ck)); try { await post('/api/fcx/item/update', { id: it.id, done: !it.done }); refresh(); } catch (er) { toast(er.message); } });
    box.querySelectorAll('.fca-item').forEach(r => r.onclick = () => itemSheet(Number(r.dataset.id), refresh));
  }
  async function itemSheet(id, after) {
    let it; try { it = (await api('/api/fcx/item/' + id)).item; } catch (e) { toast(e.message); return; }
    const k = KIND[it.kind] || ['•', 'Item'];
    let h = '<h3>' + k[0] + ' ' + esc(it.title) + '</h3><p>' + esc(k[1]) + (it.where ? ' · ' + esc(it.where) : '') + '</p>';
    if (it.notes) h += '<p style="white-space:pre-wrap;color:#fff">' + esc(it.notes) + '</p>';
    if (it.due_at) h += '<p><b style="color:#1ed6c8">' + (it.kind === 'event' ? 'When: ' : 'Due: ') + esc(dueText(it.due_at)) + '</b></p>';
    if (it.place) h += '<p>📍 ' + esc(it.place) + '</p>';
    if (it.kind === 'poll') {
      const tot = Math.max(1, it.votes);
      h += '<div class="fca-poll">' + it.options.map((o, i) => '<button class="opt' + (it.my_vote === i ? ' on' : '') + '" data-v="' + i + '"><i style="width:' + Math.round(100 * it.counts[i] / tot) + '%"></i><span>' + (it.my_vote === i ? '✓ ' : '') + esc(o) + '</span><em>' + it.counts[i] + '</em></button>').join('') + '</div><p style="margin-top:10px">' + it.votes + (it.votes === 1 ? ' vote' : ' votes') + ' · tap your answer' + (it.my_vote >= 0 ? ' (tap it again to take your vote back)' : '') + '</p>';
    }
    if (it.kind === 'event') h += '<div class="fca-rsvp">' + [['yes', 'Going'], ['maybe', 'Maybe'], ['no', 'Can\'t go']].map(([a, l]) => '<button data-r="' + a + '" class="' + (it.my_rsvp === a ? 'on' : '') + '">' + l + ' · ' + it.rsvp[a] + '</button>').join('') + '</div>';
    if (it.kind === 'task' || it.kind === 'reminder') h += '<button class="fc-btn" data-a="done">' + (it.done ? 'Mark as not done' : 'Mark as done') + '</button>';
    if (it.conversation_id) h += '<button class="fc-btn sec" data-a="chat">Open the chat</button>';
    if (it.mine) h += '<button class="fc-btn sec" data-a="edit">Edit</button><button class="fc-btn danger" data-a="del">Delete</button>';
    sheet(h, (el, done) => {
      const again = () => { done(); itemSheet(id, after); if (after) after(); try { FC().refreshMsgs(); } catch (_) {} };
      el.querySelectorAll('[data-v]').forEach(b => b.onclick = async () => { const v = Number(b.dataset.v); try { await post('/api/fcx/vote', { id, choice: it.my_vote === v ? -1 : v }); again(); } catch (e) { toast(e.message); } });
      el.querySelectorAll('[data-r]').forEach(b => b.onclick = async () => { const r = b.dataset.r; try { await post('/api/fcx/rsvp', { id, answer: it.my_rsvp === r ? '' : r }); again(); } catch (e) { toast(e.message); } });
      bind(el, {
        done: async () => { try { await post('/api/fcx/item/update', { id, done: !it.done }); done(); toast(it.done ? 'Back on the list' : 'Done ✓'); if (after) after(); } catch (e) { toast(e.message); } },
        chat: () => { done(); FC().openConv(it.conversation_id); },
        edit: () => { done(); itemForm(it.kind, it.conversation_id, after, it); },
        del: async () => { if (!confirm('Delete this ' + k[1].toLowerCase() + '?')) return; try { await post('/api/fcx/item/delete', { id }); done(); toast('Deleted'); if (after) after(); } catch (e) { toast(e.message); } }
      });
    });
  }
  function itemForm(kind, conv, after, edit) {
    const k = KIND[kind];
    const soon = new Date(Date.now() + 3600e3); soon.setMinutes(0, 0, 0);
    let h = '<h3>' + k[0] + ' ' + (edit ? 'Edit ' + k[1].toLowerCase() : 'New ' + k[1].toLowerCase()) + '</h3>' + (conv && !edit ? '<p>Everyone in this chat will see it.</p>' : '');
    h += '<label class="fca-field"><span>' + (kind === 'poll' ? 'Question' : kind === 'event' ? 'What are you planning?' : kind === 'reminder' ? 'Remind me to…' : 'What needs doing?') + '</span><input id="fcaIT" maxlength="200" value="' + esc(edit ? edit.title : '') + '"></label>';
    if (kind === 'poll' && !edit) h += '<div id="fcaOpts">' + [1, 2, 3].map(n => '<label class="fca-field"><span>Answer ' + n + (n > 2 ? ' (optional)' : '') + '</span><input class="fcaO" maxlength="80"></label>').join('') + '</div><button class="fc-btn sec" id="fcaMore" type="button">+ Add another answer</button>';
    if (kind !== 'poll') h += '<label class="fca-field"><span>' + (kind === 'event' ? 'When' : kind === 'reminder' ? 'When should we remind you?' : 'Due (optional)') + '</span><input id="fcaID" type="datetime-local" value="' + esc(edit ? localInput(edit.due_at) : kind === 'task' ? '' : localInput(soon.toISOString())) + '"></label>';
    if (kind === 'event') h += '<label class="fca-field"><span>Where (optional)</span><input id="fcaIP" maxlength="160" value="' + esc(edit ? edit.place : '') + '"></label>';
    if (kind === 'task' || kind === 'event') h += '<label class="fca-field"><span>Notes (optional)</span><textarea id="fcaIN" rows="3" maxlength="1000">' + esc(edit ? edit.notes : '') + '</textarea></label>';
    if (kind === 'reminder' || (kind !== 'poll' && !conv)) h += '<p style="font-size:13px">You\'ll get a notification at that time, even when Future Chat is closed.</p>';
    h += '<button class="fc-btn" id="fcaIGo">' + (edit ? 'Save' : conv ? 'Share in chat' : 'Save') + '</button>';
    sheet(h, (el, done) => {
      const more = $('#fcaMore', el); if (more) more.onclick = () => { const n = el.querySelectorAll('.fcaO').length; if (n >= 10) return; $('#fcaOpts', el).insertAdjacentHTML('beforeend', '<label class="fca-field"><span>Answer ' + (n + 1) + ' (optional)</span><input class="fcaO" maxlength="80"></label>'); };
      setTimeout(() => { try { $('#fcaIT', el).focus(); } catch (_) {} }, 50);
      $('#fcaIGo', el).onclick = async e => {
        const v = s => { const x = $(s, el); return x ? x.value : undefined; };
        const dueRaw = v('#fcaID'); const due = dueRaw ? new Date(dueRaw).toISOString() : '';
        const body = { title: (v('#fcaIT') || '').trim() };
        if (dueRaw !== undefined) body.due_at = due;
        if (v('#fcaIP') !== undefined) body.place = v('#fcaIP');
        if (v('#fcaIN') !== undefined) body.notes = v('#fcaIN');
        e.target.disabled = true;
        try {
          if (edit) await post('/api/fcx/item/update', Object.assign({ id: edit.id }, body));
          else await post('/api/fcx/item', Object.assign({ kind, c: conv || 0, options: Array.from(el.querySelectorAll('.fcaO')).map(i => i.value) }, body));
          done(); toast(edit ? 'Saved' : conv ? 'Shared in the chat' : 'Saved'); if (after) after(); try { FC().refreshMsgs(); } catch (_) {}
        } catch (er) { toast(er.message); e.target.disabled = false; }
      };
    });
  }
  async function scrTasks() {
    const self = X.stack[X.stack.length - 1];
    const bd = frame('Tasks', 'Plans, reminders and meetings');
    bd.innerHTML = '<div class="fca-acts"><button class="fca-act" data-a="task"><i>✅</i>New task</button><button class="fca-act" data-a="reminder"><i>⏰</i>Reminder</button><button class="fca-act" data-a="event"><i>📅</i>Meeting</button></div>' +
      '<div class="fca-seg" style="margin-bottom:12px">' + [['all', 'All'], ['task', 'Tasks'], ['reminder', 'Reminders'], ['event', 'Meetings'], ['poll', 'Polls']].map(([f, l], i) => '<button data-f="' + f + '" class="' + (i ? '' : 'on') + '">' + l + '</button>').join('') + '</div><div id="fcaItems"><div class="fca-empty">Loading…</div></div>';
    const again = () => { if (X.stack[X.stack.length - 1] === self) scrTasks(); };
    bind(bd, { task: () => itemForm('task', 0, again), reminder: () => itemForm('reminder', 0, again), event: () => itemForm('event', 0, again) });
    let items = []; try { items = (await api('/api/fcx/items?all=1')).items || []; } catch (e) { $('#fcaItems', bd).innerHTML = '<div class="fca-empty"><b>Couldn\'t load</b>' + esc(e.message) + '</div>'; return; }
    if (X.stack[X.stack.length - 1] !== self) return;
    const paint = f => itemList($('#fcaItems', bd), f === 'all' ? items : items.filter(i => i.kind === f), again, 'Add a task, a reminder or a meeting proposal. Things shared in your chats and circles show here too.');
    bd.querySelectorAll('.fca-seg button').forEach(b => b.onclick = () => { bd.querySelectorAll('.fca-seg button').forEach(x => x.classList.toggle('on', x === b)); paint(b.dataset.f); });
    paint('all');
  }

  // ---------------------------------------------------------------- YOU tab: profile + settings
  async function scrYou() {
    const bd = frame('Your Future Chat', 'Your profile, settings and boundaries');
    if (!X.me) await loadMe();
    const m = X.me || {}, p = X.prefs || {};
    bd.innerHTML = '<div class="fca-prof"><button type="button" class="fca-cam" data-a="photo" aria-label="Change profile picture" style="border:0;background:none;padding:0">' + avatar(m.name, m.photo, 'xl') + '<span>📷</span></button>' +
      '<h3>' + esc(m.name || 'Your name') + '</h3><p>' + esc(p.about || 'Add a few words about you') + '</p><p>' + esc(m.phone ? m.phone + (m.phone_verified ? ' ✓' : ' · not confirmed') : 'No mobile number yet') + '</p>' +
      '<button type="button" class="fca-pill" data-a="edit">✎ Edit profile</button></div>' +
      '<div class="fca-gl">Account</div><div class="fca-card">' +
      row('👤', 'Profile details', 'Picture, name and about', { data: 'data-a="edit"' }) +
      row('📱', 'Mobile number', m.phone ? m.phone + (m.phone_verified ? ' · confirmed' : ' · tap to confirm') : 'Add the number people use to find you', { data: 'data-a="phone"' }) +
      row('💻', 'Linked devices', 'Phones and computers signed in to your account', { data: 'data-a="devices"' }) + '</div>' +
      '<div class="fca-gl">Productivity</div><div class="fca-card">' +
      row('✅', 'Tasks', 'Turn conversations into to-dos', { data: 'data-a="tasks"' }) +
      row('⏰', 'Reminders and meetings', 'Never miss something important', { data: 'data-a="tasks"' }) +
      row('◎', 'Circles', 'Your people and groups', { data: 'data-a="circles"' }) +
      row('🎉', 'Celebrations', 'Birthdays, holidays and special days', { data: 'data-a="celeb"' }) +
      row('🕛', 'Scheduled messages', 'Messages waiting to be sent', { data: 'data-a="sched"' }) + '</div>' +
      '<div class="fca-gl">Preferences</div><div class="fca-card">' +
      row('🔒', 'Privacy and visibility', 'Last seen, profile picture and status', { data: 'data-a="privacy"' }) +
      row('🔔', 'Notifications', 'Messages, calls and circles', { data: 'data-a="notif"' }) +
      row('🚫', 'Blocked accounts', (X.counts.blocked || 0) ? X.counts.blocked + ' blocked' : 'Manage your blocked list', { data: 'data-a="blocked"' }) +
      row('🗣️', 'App language', (langInfo(appLang()) || ['', 'English'])[1], { data: 'data-a="applang"' }) +
      row('🌐', 'Language and translation', p.language || 'English', { data: 'data-a="lang"' }) +
      row('📶', 'Data saver', p.data_saver ? 'On · photos sent smaller' : 'Use less mobile data', { data: 'data-a="data"' }) +
      row('✦', 'Future Chatmoji collection', 'Express more', { data: 'data-a="cm"' }) + '</div>' +
      '<div class="fca-gl">More</div><div class="fca-card">' +
      row('💼', 'Business and creator tools', 'Business profile and broadcasts', { data: 'data-a="biz"' }) +
      row('☁️', 'Chat backup', 'Your chats are backed up to your account', { data: 'data-a="backup"' }) +
      row('💾', 'Storage and data', 'Clear chats, media on this phone, your data', { data: 'data-a="storage"' }) +
      row('💌', 'Invite friends', 'Share a link to Future Chat', { data: 'data-a="invite"' }) +
      row('🛡️', 'Help and safety', 'Report, block and protect', { data: 'data-a="help"' }) +
      row('📄', 'Terms and policies', 'Terms, Rules & Safety · Privacy Policy', { data: 'data-a="terms"' }) +
      row('ⓘ', 'About Future Chat', 'Version ' + appVersion(), { data: 'data-a="about"' }) + '</div>' +
      '<div class="fca-card">' + row('🚪', 'Sign out', '', { data: 'data-a="signout"' }, '') + row('🗑️', 'Delete my account', 'Ask us to delete your account and data', { data: 'data-a="delete"', cls: 'danger' }, '') + '</div>';
    bind(bd, {
      photo: () => pickPhoto(), edit: () => push(scrProfile), phone: () => { try { FC().verifyPhone(true); } catch (_) {} }, devices: () => push(scrDevices),
      tasks: () => push(scrTasks), circles: () => go('circles'), privacy: () => push(scrPrivacy), notif: () => push(scrNotif), blocked: () => push(scrBlocked),
      celeb: () => push(scrCelebrations), sched: () => push(scrScheduled), lang: () => push(scrLang), applang: () => langPicker(() => setTimeout(() => { if (X.stack.length) draw(); }, 400)), data: () => push(scrData), cm: () => push(scrChatmoji), biz: () => push(scrBiz), storage: () => push(scrStorage), backup: () => push(scrBackup),
      invite: () => { try { FC().inviteFriends(); } catch (_) {} }, help: () => push(scrHelp), terms: () => push(scrTerms), about: () => push(scrAbout),
      signout: signOut, delete: deleteAccount
    });
    if (FCX.youExtra) { try { FCX.youExtra(bd); } catch (_) {} }
  }
  function appVersion() { const m = navigator.userAgent.match(/FutureChatApp\/([\d.]+)/); return m ? m[1] : '1.1'; }
  // profile picture: choose from the phone or take one with the camera; resized on the phone before upload
  function pickPhoto() {
    const m = X.me || {};
    sheet('<h3>Profile picture</h3><p>People you chat with see it next to your name.</p><div class="fc-acts"><button class="fc-act" data-a="cam"><i>📷</i>Take a photo</button><button class="fc-act" data-a="lib"><i>🖼️</i>Choose from your phone</button>' + (m.photo ? '<button class="fc-act danger" data-a="rm"><i>🗑️</i>Remove picture</button>' : '') + '</div>', (el, done) => bind(el, {
      cam: () => { done(); choose(true); }, lib: () => { done(); choose(false); },
      rm: async () => { done(); try { await post('/api/fcx/profile', { name: m.name, about: (X.prefs || {}).about || '', photo: '' }); await loadMe(); redraw(); toast('Picture removed'); } catch (e) { toast(e.message); } }
    }));
  }
  function choose(camera) {
    const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/*'; if (camera) inp.setAttribute('capture', 'user');
    inp.onchange = async () => {
      const f = inp.files && inp.files[0]; if (!f) return;
      toast('Saving your picture…');
      try {
        const data = await squarePhoto(f);
        await post('/api/fcx/profile', { name: (X.me || {}).name, about: (X.prefs || {}).about || '', photo: data });
        await loadMe(); redraw(); toast('Profile picture saved ✓');
      } catch (e) { toast(e.message || 'That picture could not be used. Try another one.'); }
    };
    document.body.appendChild(inp); inp.style.display = 'none'; inp.click(); setTimeout(() => inp.remove(), 60000);
  }
  async function squarePhoto(file) {
    const url = URL.createObjectURL(file);
    try {
      const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('That picture could not be opened. Try another one.')); i.src = url; });
      const s = Math.min(img.naturalWidth, img.naturalHeight), out = Math.min(640, s);
      const cv = document.createElement('canvas'); cv.width = cv.height = out;
      cv.getContext('2d').drawImage(img, (img.naturalWidth - s) / 2, (img.naturalHeight - s) / 2, s, s, 0, 0, out, out);
      return cv.toDataURL('image/jpeg', 0.85);
    } finally { URL.revokeObjectURL(url); }
  }
  function redraw() { if (X.stack.length) draw(); paintMe(); }
  function scrProfile() {
    const bd = frame('Profile details', 'Picture, name and about'); const m = X.me || {}, p = X.prefs || {};
    bd.innerHTML = '<div class="fca-prof"><button type="button" class="fca-cam" data-a="photo" style="border:0;background:none;padding:0" aria-label="Change profile picture">' + avatar(m.name, m.photo, 'xl') + '<span>📷</span></button><p style="margin-top:10px">Tap the picture to take a photo or choose one</p></div>' +
      '<div class="fca-acts" style="grid-template-columns:1fr 1fr"><button class="fca-act" data-a="cam"><i>📷</i>Camera</button><button class="fca-act" data-a="lib"><i>🖼️</i>Gallery</button></div>' +
      '<label class="fca-field"><span>Your name</span><input id="fcaPN" maxlength="60" value="' + esc(m.name || '') + '"></label>' +
      '<label class="fca-field"><span>About (people you chat with can see this)</span><input id="fcaPA" maxlength="140" placeholder="e.g. Available · Busy · At work" value="' + esc(p.about || '') + '"></label>' +
      '<label class="fca-field"><span>Email (for signing in)</span><input value="' + esc(m.email || '') + '" readonly></label>' +
      '<div class="fca-card">' + row('🎂', 'Birthday', (p.birthday && p.birthday.d) ? p.birthday.d + '/' + p.birthday.m : 'Add your birthday', { data: 'data-a="bday"' }) + '</div>' +
      '<button class="fca-btn" data-a="save">Save</button>';
    bind(bd, { photo: pickPhoto, cam: () => choose(true), lib: () => choose(false), bday: () => push(scrMyBirthday),
      save: async b => { b.disabled = true; try { await post('/api/fcx/profile', { name: $('#fcaPN', bd).value, about: $('#fcaPA', bd).value }); await loadMe(); toast('Profile saved ✓'); pop(); } catch (e) { toast(e.message); b.disabled = false; } } });
  }
  async function scrDevices() {
    const self = X.stack[X.stack.length - 1];
    const bd = frame('Linked devices', 'Where your account is signed in'); bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let items = []; try { items = (await api('/api/fcx/sessions')).items || []; } catch (e) { bd.innerHTML = '<div class="fca-empty"><b>Couldn\'t load</b>' + esc(e.message) + '</div>'; return; }
    if (X.stack[X.stack.length - 1] !== self) return;
    bd.innerHTML = '<div class="fca-card">' + items.map(s => row(s.current ? '📱' : '💻', s.current ? 'This phone' : 'Signed in ' + when(s.created_at), s.current ? 'Active now' : 'Stays signed in until ' + new Date(s.expires_at).toLocaleDateString(), {}, '')).join('') + '</div>' +
      '<p class="fca-note" data-keep-brand>Future Chat and Skillvaya use the same account, so signing in on either app shows here.</p>' +
      (items.length > 1 ? '<button class="fca-btn danger" data-a="out">Sign out all other devices</button>' : '');
    bind(bd, { out: async () => { if (!confirm('Sign out everywhere except this phone?')) return; try { const d = await post('/api/fcx/sessions/logout-others'); toast('Signed out ' + d.signed_out + (d.signed_out === 1 ? ' device' : ' devices')); scrDevices(); } catch (e) { toast(e.message); } } });
  }
  function choiceRows(key, label, opts) {
    const cur = (X.prefs || {})[key];
    return '<div class="fca-gl">' + esc(label) + '</div><div class="fca-card">' + opts.map(([v, l, s]) => row(cur === v ? '●' : '○', l, s, { data: 'data-a="set" data-k="' + key + '" data-v="' + v + '"' }, '')).join('') + '</div>';
  }
  function bindChoices(bd, again) { bd.querySelectorAll('[data-a="set"]').forEach(b => b.onclick = async () => { const o = {}; o[b.dataset.k] = b.dataset.v; if (await savePrefs(o)) { toast('Saved'); again(); } }); }
  function scrPrivacy() {
    const bd = frame('Privacy and visibility', 'Choose how you connect');
    bd.innerHTML = choiceRows('last_seen', 'Last seen and online', [['contacts', 'The people I chat with', ''], ['nobody', 'Nobody', 'If you hide yours, you can\'t see other people\'s either']]) +
      choiceRows('photo', 'Profile picture', [['contacts', 'The people I chat with', ''], ['nobody', 'Nobody', '']]) +
      choiceRows('status', 'My status', [['contacts', 'The people I chat with', ''], ['nobody', 'Nobody', 'Pauses your status for everyone']]) +
      '<div class="fca-card" style="margin-top:12px">' + row('🚫', 'Blocked accounts', 'People you blocked can\'t message or call you', { data: 'data-a="blocked"' }) + '</div>' +
      '<p class="fca-note">Only your name, number and email are kept on our server. Photos and videos you send stay on the phones they were sent to.</p>';
    bindChoices(bd, scrPrivacy); bind(bd, { blocked: () => push(scrBlocked) });
  }
  function toggles(list) {
    const p = X.prefs || {};
    return '<div class="fca-card">' + list.map(([k, l, s]) => row('', l, s, { data: 'data-a="tg" data-k="' + k + '"' }, '<span class="fca-sw' + (p[k] ? ' on' : '') + '"></span>').replace('<span class="ic"></span>', '')).join('') + '</div>';
  }
  function bindToggles(bd) { bd.querySelectorAll('[data-a="tg"]').forEach(b => b.onclick = async () => { const k = b.dataset.k, sw = b.querySelector('.fca-sw'); const on = !sw.classList.contains('on'); sw.classList.toggle('on', on); const o = {}; o[k] = on; if (!(await savePrefs(o))) sw.classList.toggle('on', !on); }); }
  function scrNotif() {
    const bd = frame('Notifications', 'What Future Chat tells you about');
    bd.innerHTML = toggles([['notify_messages', 'Message notifications', 'New messages in your chats'], ['notify_groups', 'Circle and group activity', 'Messages, polls and plans in groups'], ['notify_calls', 'Call alerts', 'Ring when someone calls you, even when the app is closed'], ['notify_previews', 'Show message text', 'Off: notifications only say "New message"']]) +
      '<p class="fca-note">You can also mute one chat from its menu. Sounds and vibration are set in your phone\'s settings for Future Chat.</p>';
    bindToggles(bd);
  }
  async function scrBlocked() {
    const self = X.stack[X.stack.length - 1];
    const bd = frame('Blocked accounts', 'They can\'t message or call you', { action: [SVG.plus, 'Block someone', blockPicker] }); bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let items = []; try { items = (await api('/api/fcx/blocks')).items || []; } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (X.stack[X.stack.length - 1] !== self) return;
    bd.innerHTML = (items.length ? '<div class="fca-card">' + items.map(b => '<div class="fca-row">' + avatar(b.name, '', 'sm') + '<span class="tx"><b>' + esc(b.name) + '</b><small>Blocked ' + esc(when(b.at)) + '</small></span><button class="fc-chip" data-u="' + b.user_id + '" style="color:#1ed6c8;border-color:#1ed6c8">Unblock</button></div>').join('') + '</div>'
      : '<div class="fca-empty"><span class="big">🚫</span><b>No accounts blocked</b>People you block will appear here.</div>') + '<button class="fca-btn sec" data-a="add">Block someone</button><p class="fca-note">Blocked people can\'t message you, call you, see your picture, last seen or status. They aren\'t told that you blocked them.</p>';
    bd.querySelectorAll('[data-u]').forEach(b => b.onclick = async () => { await blockUser(Number(b.dataset.u), false); scrBlocked(); });
    bind(bd, { add: blockPicker });
  }
  function blockPicker() {
    const list = directChats();
    sheet('<h3>Block someone</h3>' + (list.length ? '<p>Choose a person you chat with.</p><div class="fc-acts">' + list.map(c => '<button class="fc-act" data-c="' + c.id + '"><i>🚫</i>' + esc(c.title) + '</button>').join('') + '</div>' : '<p>You have no one-to-one chats yet.</p>'), (el, done) => {
      el.querySelectorAll('[data-c]').forEach(b => b.onclick = async () => { done(); const c = list.find(x => x.id === Number(b.dataset.c)); if (!confirm('Block ' + c.title + '? They won\'t be able to message or call you.')) return; try { await post('/api/fcx/block', { c: c.id, on: true }); toast(c.title + ' is blocked'); loadPeers(); loadMe(); if (X.stack.length) draw(); } catch (e) { toast(e.message); } });
    });
  }
  async function blockUser(uid, on, name) {
    if (on && !confirm('Block ' + (name || 'this person') + '? They won\'t be able to message or call you.')) return;
    try { await post('/api/fcx/block', { user_id: uid, on }); toast(on ? 'Blocked' : 'Unblocked'); loadPeers(); loadMe(); } catch (e) { toast(e.message); }
  }
  function scrLang() {
    const bd = frame('Language and translation', 'Read messages in your language'); const p = X.prefs || {};
    bd.innerHTML = '<div class="fca-card">' + row('🗣️', 'App language', (langInfo(appLang()) || ['', 'English'])[1], { data: 'data-a="applang"' }) + '</div>' +
      '<label class="fca-field"><span>Translate messages into</span><select id="fcaLang">' + (X.langs || []).map(l => '<option' + (l === p.language ? ' selected' : '') + '>' + esc(l) + '</option>').join('') + '</select></label>' +
      toggles([['translate', 'Offer Translate on messages', 'Hold a message, then tap Translate']]) +
      '<p class="fca-note">Translation is free and works for South African languages like Afrikaans, isiZulu and isiXhosa as well as many others. Only the message you choose is translated.</p>';
    $('#fcaLang', bd).onchange = async e => { if (await savePrefs({ language: e.target.value })) toast('Saved'); };
    bind(bd, { applang: () => langPicker(() => setTimeout(scrLang, 400)) });
    bindToggles(bd);
  }
  function scrData() {
    const bd = frame('Data saver', 'Use less mobile data');
    let s = { b: 0, n: 0 }; try { const x = JSON.parse(localStorage.getItem('fc_ds') || '{}'); if (x.m === new Date().toISOString().slice(0, 7)) s = x; } catch (_) {}
    bd.innerHTML = '<div class="fca-hero"><small>SAVED THIS MONTH</small><b>' + (s.b / 1048576).toFixed(1) + ' MB</b><p>' + (s.n ? s.n + (s.n === 1 ? ' photo' : ' photos') + ' made smaller before sending' : 'Turn on data saver and photos you send are made smaller first.') + '</p></div>' +
      toggles([['data_saver', 'Make photos smaller before sending', 'Sharp on a phone screen, a fraction of the data']]) +
      '<p class="fca-note">Photos are resized to a sharp phone-screen size and saved as compact JPEGs. A typical camera photo drops from 3–5 MB to about 200–400 KB. Messages and calls stay the same.</p>';
    bindToggles(bd);
  }
  function scrChatmoji() {
    const bd = frame('Future Chatmoji', 'Tap one to send it in a chat'); const cm = CM();
    const cats = (cm.cats || []).map(c => Array.isArray(c) ? { name: c[0], items: c[1] } : c).filter(c => c && c.items && c.items.length);
    const groups = cats.length ? cats : [{ name: 'All', items: Object.keys(cm.svg || {}) }];
    bd.innerHTML = '<div class="fca-seg" style="margin-bottom:12px">' + groups.map((g, i) => '<button data-i="' + i + '" class="' + (i ? '' : 'on') + '">' + esc(g.name || g.label || ('Set ' + (i + 1))) + '</button>').join('') + '</div><div class="fca-cm" id="fcaCm"></div><p class="fca-note">Future Chatmoji and Lenses are free for everyone, always.</p>';
    const paint = i => { $('#fcaCm', bd).innerHTML = (groups[i].items || []).filter(n => cm.svg[n]).map(n => '<button data-n="' + esc(n) + '" aria-label="' + esc(n.replace(/_/g, ' ')) + '">' + cm.svg[n] + '</button>').join(''); $('#fcaCm', bd).querySelectorAll('[data-n]').forEach(b => b.onclick = () => { go('chats'); setTimeout(() => FC().share(':' + b.dataset.n + ': '), 150); }); };
    bd.querySelectorAll('.fca-seg button').forEach(b => b.onclick = () => { bd.querySelectorAll('.fca-seg button').forEach(x => x.classList.toggle('on', x === b)); paint(Number(b.dataset.i)); });
    paint(0);
  }
  function scrBiz() {
    const bd = frame('Business and creator tools', 'Your professional workspace'); const b = (X.prefs || {}).biz || {};
    const f = (k, l, ph, ta) => '<label class="fca-field"><span>' + l + '</span>' + (ta ? '<textarea data-k="' + k + '" rows="3" maxlength="300" placeholder="' + esc(ph) + '">' + esc(b[k] || '') + '</textarea>' : '<input data-k="' + k + '" maxlength="120" placeholder="' + esc(ph) + '" value="' + esc(b[k] || '') + '">') + '</label>';
    bd.innerHTML = '<div class="fca-gl" style="margin-top:4px">Business profile</div><p class="fca-note">People you chat with see this on your profile.</p>' +
      f('name', 'Business name', 'e.g. Hayleigh\'s Cakes') + f('category', 'What you do', 'e.g. Baker, Plumber, Hair salon') + f('about', 'About your business', 'What you offer, areas you serve', true) +
      f('hours', 'Opening hours', 'e.g. Mon–Fri 08:00–17:00') + f('address', 'Address or area', 'e.g. Bellville, Cape Town') + f('website', 'Website or social link', 'https://') + f('email', 'Business email', '') +
      '<button class="fca-btn" data-a="save">Save business profile</button>' +
      '<div class="fca-gl">Creator tools</div><div class="fca-card">' + row('📣', 'Broadcast a message', 'Send one message to many chats at once (each person gets it privately)', { data: 'data-a="bc"' }) + row('📊', 'Your status reach', 'How many people saw your status', { data: 'data-a="reach"' }) + '</div>';
    bind(bd, {
      save: async btn => { const o = {}; bd.querySelectorAll('[data-k]').forEach(i => o[i.dataset.k] = i.value); btn.disabled = true; if (await savePrefs({ biz: o })) toast('Business profile saved ✓'); btn.disabled = false; },
      bc: broadcast, reach: async () => { const FS = window.FutureChatStatus; if (!FS) return; await FS.load(true); const d = FS.data() || { mine: [] }; const v = d.mine.reduce((a, s) => a + (s.views || 0), 0); sheet('<h3>Your status reach</h3><p>' + (d.mine.length ? 'Your ' + d.mine.length + (d.mine.length === 1 ? ' status update was' : ' status updates were') + ' viewed ' + v + (v === 1 ? ' time' : ' times') + ' in the last 24 hours.' : 'You have no status right now. Post one from the Status tab.') + '</p>'); }
    });
  }
  function broadcast() {
    let list = []; try { list = (FC().state().list || []).filter(c => !c.archived); } catch (_) {}
    sheet('<h3>Broadcast</h3><p>Each person gets your message in your own chat with them.</p><textarea id="fcaBcT" rows="4" maxlength="4000" placeholder="Your message"></textarea><div style="max-height:36vh;overflow:auto;margin:8px 0">' +
      list.map(c => '<label class="fca-chk"><input type="checkbox" value="' + c.id + '"><span>' + esc(c.title) + '</span></label>').join('') + '</div><button class="fc-btn" id="fcaBcGo">Send</button>', (el, done) => {
      $('#fcaBcGo', el).onclick = async e => { const ids = Array.from(el.querySelectorAll('input[type=checkbox]:checked')).map(i => Number(i.value)); e.target.disabled = true;
        try { const d = await post('/api/fcx/broadcast', { body: $('#fcaBcT', el).value, conversations: ids }); done(); toast('Sent to ' + d.sent + (d.sent === 1 ? ' chat' : ' chats')); } catch (er) { toast(er.message); e.target.disabled = false; } };
    });
  }
  function scrStorage() {
    const bd = frame('Storage and data', 'Your Future Chat information'); const c = X.counts || {};
    bd.innerHTML = '<div class="fca-stat"><div><b>' + (c.chats || 0) + '</b><small>Chats</small></div><div><b>' + (c.sent || 0) + '</b><small>Messages sent</small></div><div><b>' + (c.items || 0) + '</b><small>Tasks & plans</small></div></div>' +
      '<div class="fca-card">' + row('☁️', 'Chat backup', 'Back up, save a copy, restore cleared chats', { data: 'data-a="backup"' }) + row('🧹', 'Clear media on this phone', 'Photos and videos Future Chat saved on this phone', { data: 'data-a="clear"' }) + row('📞', 'Clear call history', 'Remove every call from your Calls list', { data: 'data-a="clrcalls"' }) + row('⬇️', 'Download my data', 'A copy of your account information', { data: 'data-a="export"' }) + '</div>' +
      '<div class="fca-card">' + row('🗑️', 'Clear all chats', 'Empty every chat on your account (you can restore from backup)', { data: 'data-a="clearall"', cls: 'danger' }, '') + '</div>' +
      '<p class="fca-note">Photos, videos and voice notes are kept on the phones they were sent to, not on our server.</p>';
    bind(bd, {
      backup: () => push(scrBackup), clearall: () => clearChats(0, ''), clrcalls: clearCalls,
      clear: () => { if (!confirm('Remove the photos and videos Future Chat saved on this phone? Your messages stay.')) return; try { indexedDB.deleteDatabase('futurechat_media'); } catch (_) {} toast('Media cleared from this phone'); },
      export: async () => { try { const r = await fetch('/api/account/export', { headers: { Authorization: 'Bearer ' + tok() }, cache: 'no-store' }); if (!r.ok) throw new Error('Could not prepare your data right now.'); const txt = await r.text();
        if (navigator.share) { try { await navigator.share({ title: 'My Future Chat data', text: txt.slice(0, 90000) }); return; } catch (_) {} }
        const a = document.createElement('a'); a.href = 'data:application/json;charset=utf-8,' + encodeURIComponent(txt); a.download = 'future-chat-data.json'; document.body.appendChild(a); a.click(); a.remove(); } catch (e) { toast(e.message); } }
    });
  }

  // ---------------------------------------------------------------- celebrations: birthdays + holidays for everyone (FCX-CELEB-01)
  // Fixed days, Easter-based days and dates from the phone's own Hebrew, Islamic (Umm al-Qura) and Chinese calendars,
  // so every year is right without updates. Diwali and Holi follow the Hindu lunar calendar: dates listed to 2030.
  const CG = { sa: '🇿🇦 South Africa', christian: '✝️ Christian', jewish: '✡️ Jewish', muslim: '☪️ Muslim', hindu: '🪔 Hindu & Sikh', asian: '🧧 Chinese & Asian', family: '💐 Family & world days', world: '🌍 Other countries' };
  const CELEB = [
    ['newyear', 'family', '🎆', 'New Year', { md: [1, 1] }, 'Happy New Year! Wishing you a wonderful year ahead.', ['#1b2a6b', '#c2410c']],
    ['valentine', 'family', '💝', "Valentine's Day", { md: [2, 14] }, "Happy Valentine's Day! Sending you lots of love.", ['#9d174d', '#f43f5e']],
    ['womensday', 'family', '💜', "International Women's Day", { md: [3, 8] }, "Happy International Women's Day! Celebrating you today.", ['#5b21b6', '#a855f7']],
    ['mothers', 'family', '💐', "Mother's Day", { nth: [5, 0, 2] }, "Happy Mother's Day! Thank you for all your love.", ['#9d174d', '#fb7185']],
    ['fathers', 'family', '👔', "Father's Day", { nth: [6, 0, 3] }, "Happy Father's Day! Thank you for everything.", ['#1e3a8a', '#0ea5e9']],
    ['halloween', 'family', '🎃', 'Halloween', { md: [10, 31] }, 'Happy Halloween! 🎃', ['#431407', '#f97316']],
    ['newyearseve', 'family', '🥂', "New Year's Eve", { md: [12, 31] }, "Happy New Year's Eve! Let's end the year well.", ['#111827', '#b45309']],
    ['humanrights', 'sa', '✊', 'Human Rights Day', { md: [3, 21] }, 'Happy Human Rights Day! Dignity and equality for all.', ['#14532d', '#16a34a']],
    ['freedom', 'sa', '🇿🇦', 'Freedom Day', { md: [4, 27] }, 'Happy Freedom Day, South Africa!', ['#14532d', '#ca8a04']],
    ['workers', 'sa', '🛠️', "Workers' Day", { md: [5, 1] }, "Happy Workers' Day! Thank you for all your hard work.", ['#7c2d12', '#ea580c']],
    ['africa', 'sa', '🌍', 'Africa Day', { md: [5, 25] }, 'Happy Africa Day! Proudly African.', ['#14532d', '#d97706']],
    ['youth', 'sa', '🎓', 'Youth Day', { md: [6, 16] }, 'Happy Youth Day! Honouring the youth of 1976 and today.', ['#1e3a8a', '#16a34a']],
    ['mandela', 'sa', '🤝', 'Mandela Day', { md: [7, 18] }, 'Happy Mandela Day! 67 minutes to make a difference.', ['#1f2937', '#ca8a04']],
    ['womensdaysa', 'sa', '👩🏾', "National Women's Day", { md: [8, 9] }, "Happy Women's Day! Wathint' abafazi, wathint' imbokodo.", ['#701a75', '#db2777']],
    ['heritage', 'sa', '🔥', 'Heritage Day', { md: [9, 24] }, 'Happy Heritage Day! Enjoy the braai and celebrate our cultures.', ['#7c2d12', '#16a34a']],
    ['reconciliation', 'sa', '🕊️', 'Day of Reconciliation', { md: [12, 16] }, 'Happy Day of Reconciliation! Together we are one nation.', ['#1e3a8a', '#0d9488']],
    ['goodwill', 'sa', '🎁', 'Day of Goodwill', { md: [12, 26] }, 'Happy Day of Goodwill! Spread kindness today.', ['#14532d', '#dc2626']],
    ['goodfriday', 'christian', '✝️', 'Good Friday', { easter: -2 }, 'Wishing you a blessed and peaceful Good Friday.', ['#1f2937', '#6b21a8']],
    ['easter', 'christian', '🐣', 'Easter', { easter: 0 }, 'Happy Easter! He is risen. 🙏', ['#065f46', '#facc15']],
    ['christmas', 'christian', '🎄', 'Christmas', { md: [12, 25] }, 'Merry Christmas! Wishing you joy, peace and love.', ['#14532d', '#b91c1c']],
    ['passover', 'jewish', '🍷', 'Passover (Pesach)', { heb: ['Nisan', 15] }, 'Chag Pesach Sameach! Wishing you a happy Passover.', ['#1e3a8a', '#7c3aed']],
    ['roshhashanah', 'jewish', '🍎', 'Rosh Hashanah', { heb: ['Tishri', 1] }, 'Shana Tova! Wishing you a sweet new year. 🍯', ['#7f1d1d', '#d97706']],
    ['yomkippur', 'jewish', '🕊️', 'Yom Kippur', { heb: ['Tishri', 10] }, "G'mar Chatima Tova. Wishing you an easy and meaningful fast.", ['#1e293b', '#475569']],
    ['hanukkah', 'jewish', '🕎', 'Hanukkah', { heb: ['Kislev', 25], days: 8 }, 'Happy Hanukkah! Chag Sameach. May your home be full of light. ✨', ['#1e3a8a', '#0ea5e9']],
    ['ramadan', 'muslim', '🌙', 'Ramadan begins', { isl: [9, 1] }, 'Ramadan Mubarak! Wishing you a blessed month.', ['#064e3b', '#0d9488']],
    ['eidfitr', 'muslim', '🕌', 'Eid al-Fitr', { isl: [10, 1] }, 'Eid Mubarak! Wishing you and your family joy and peace.', ['#064e3b', '#ca8a04']],
    ['eidadha', 'muslim', '🐑', 'Eid al-Adha', { isl: [12, 10] }, 'Eid al-Adha Mubarak! Blessings to you and your family.', ['#064e3b', '#a16207']],
    ['islamicny', 'muslim', '🌙', 'Islamic New Year', { isl: [1, 1] }, 'Happy Islamic New Year! May the year bring blessings.', ['#0f172a', '#0d9488']],
    ['diwali', 'hindu', '🪔', 'Diwali', { dates: ['2026-11-08', '2027-10-29', '2028-10-17', '2029-11-05', '2030-10-26'] }, 'Happy Diwali! May your home be filled with light and joy. 🪔', ['#7c2d12', '#f59e0b']],
    ['holi', 'hindu', '🎨', 'Holi', { dates: ['2027-03-22', '2028-03-11', '2029-03-01', '2030-03-20'] }, 'Happy Holi! Wishing you a colourful and joyful festival. 🌈', ['#be185d', '#22c55e']],
    ['vaisakhi', 'hindu', '🌾', 'Vaisakhi', { md: [4, 14] }, 'Happy Vaisakhi! Wishing you a joyful harvest festival.', ['#9a3412', '#eab308']],
    ['lunarny', 'asian', '🧧', 'Lunar New Year', { chn: [1, 1] }, 'Happy Lunar New Year! Wishing you luck and good fortune. 🧧', ['#7f1d1d', '#dc2626']],
    ['usindependence', 'world', '🇺🇸', 'Independence Day (USA)', { md: [7, 4] }, 'Happy Fourth of July! 🎆', ['#1e3a8a', '#b91c1c']],
    ['thanksgiving', 'world', '🦃', 'Thanksgiving (USA)', { nth: [11, 4, 4] }, 'Happy Thanksgiving! Grateful for you.', ['#7c2d12', '#ca8a04']],
    ['germanunity', 'world', '🇩🇪', 'German Unity Day', { md: [10, 3] }, 'Frohen Tag der Deutschen Einheit! Happy German Unity Day.', ['#111827', '#dc2626']],
    ['indiaday', 'world', '🇮🇳', 'Independence Day (India)', { md: [8, 15] }, 'Happy Independence Day, India! 🇮🇳', ['#c2410c', '#15803d']],
    ['nigeriaday', 'world', '🇳🇬', 'Independence Day (Nigeria)', { md: [10, 1] }, 'Happy Independence Day, Nigeria! 🇳🇬', ['#14532d', '#16a34a']],
    ['canadaday', 'world', '🇨🇦', 'Canada Day', { md: [7, 1] }, 'Happy Canada Day! 🇨🇦', ['#7f1d1d', '#dc2626']],
    ['australiaday', 'world', '🇦🇺', 'Australia Day', { md: [1, 26] }, 'Happy Australia Day! 🇦🇺', ['#1e3a8a', '#ca8a04']]
  ];
  const BDAY_THEMES = [['🎂', 'Cake', ['#9d174d', '#f59e0b']], ['🎈', 'Balloons', ['#1d4ed8', '#22d3ee']], ['🎉', 'Party', ['#6d28d9', '#ec4899']], ['🌟', 'Stars', ['#0f172a', '#1ed6c8']]];
  const DAY = 864e5;
  const ymd = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  function easterOf(y) { const a = y % 19, b = Math.floor(y / 100), c = y % 100, d = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30, i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451), mo = Math.floor((h + l - 7 * m + 114) / 31), da = ((h + l - 7 * m + 114) % 31) + 1; return new Date(y, mo - 1, da); }
  function nthWeekday(y, mo, wd, n) { const d = new Date(y, mo - 1, 1); let c = 0; while (true) { if (d.getDay() === wd && ++c === n) return new Date(d); d.setDate(d.getDate() + 1); } }
  const CALF = {};
  function calParts(cal, d) {
    try {
      const f = CALF[cal] || (CALF[cal] = new Intl.DateTimeFormat('en-u-ca-' + cal, { timeZone: 'UTC', month: cal === 'hebrew' ? 'long' : 'numeric', day: 'numeric' }));
      const p = f.formatToParts(new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())));
      return { m: (p.find(x => x.type === 'month') || {}).value, d: Number((p.find(x => x.type === 'day') || {}).value) };
    } catch (_) { return { m: '', d: 0 }; }
  }
  const YEAR_CACHE = {};
  function celebYear(y) {   // id -> list of yyyy-mm-dd in that year
    if (YEAR_CACHE[y]) return YEAR_CACHE[y];
    const out = {};
    const add = (id, d, days) => { for (let i = 0; i < (days || 1); i++) { const x = new Date(d); x.setDate(x.getDate() + i); (out[id] = out[id] || []).push(ymd(x)); } };
    const lunar = CELEB.filter(c => c[4].heb || c[4].isl || c[4].chn);
    for (const c of CELEB) {
      const r = c[4];
      if (r.md) add(c[0], new Date(y, r.md[0] - 1, r.md[1]));
      else if (r.nth) add(c[0], nthWeekday(y, r.nth[0], r.nth[1], r.nth[2]));
      else if (r.easter != null) { const e = easterOf(y); e.setDate(e.getDate() + r.easter); add(c[0], e); }
      else if (r.dates) r.dates.filter(x => x.slice(0, 4) === String(y)).forEach(x => (out[c[0]] = out[c[0]] || []).push(x));
    }
    for (let t = new Date(y, 0, 1); t.getFullYear() === y; t = new Date(t.getTime() + DAY + 3600e3), t.setHours(0, 0, 0, 0)) {
      let H = null, I = null, C = null;
      for (const c of lunar) {
        const r = c[4];
        if (r.heb) { H = H || calParts('hebrew', t); if (H.m === r.heb[0] && H.d === r.heb[1]) add(c[0], t, r.days); }
        else if (r.isl) { I = I || calParts('islamic-umalqura', t); if (I.m === String(r.isl[0]) && I.d === r.isl[1]) add(c[0], t, r.days); }
        else if (r.chn) { C = C || calParts('chinese', t); if (C.m === String(r.chn[0]) && C.d === r.chn[1]) add(c[0], t, r.days); }
      }
    }
    return (YEAR_CACHE[y] = out);
  }
  function celebrates(id) { const l = (X.prefs && X.prefs.celebrate) || ['*']; if (l.indexOf('*') >= 0) return l.indexOf('-' + id) < 0; return l.indexOf(id) >= 0; }
  function celebsOn(d) { const key = ymd(d), Y = celebYear(d.getFullYear()); return CELEB.filter(c => (Y[c[0]] || []).indexOf(key) >= 0); }
  function upcomingCelebs(days) {
    const out = [], now = new Date(); now.setHours(0, 0, 0, 0);
    for (let i = 0; i <= days; i++) { const d = new Date(now.getTime() + i * DAY + 3600e3); d.setHours(0, 0, 0, 0); celebsOn(d).forEach(c => { if (!out.some(o => o[0][0] === c[0])) out.push([c, d, i]); }); }
    return out;
  }
  function nextBirthday(b) { const now = new Date(); now.setHours(0, 0, 0, 0); let y = now.getFullYear(); const mk = yy => { const leap = yy % 4 === 0 && (yy % 100 !== 0 || yy % 400 === 0); return (b.m === 2 && b.d === 29 && !leap) ? new Date(yy, 1, 28) : new Date(yy, b.m - 1, b.d); }; let d = mk(y); if (d < now) d = mk(y + 1); return [d, Math.round((d - now) / DAY)]; }
  // birthdays of the people I chat with (cached a few minutes)
  async function loadBirthdays(force) {
    if (!force && X.bdays && Date.now() - X.bdaysAt < 300000) return X.bdays;
    try { X.bdays = (await api('/api/fcx/birthdays')).items || []; X.bdaysAt = Date.now(); } catch (_) { X.bdays = X.bdays || []; }
    return X.bdays;
  }
  function bdayToday() { return (X.bdays || []).filter(b => nextBirthday(b)[1] === 0); }
  // strip at the top of Chats: today's birthdays + today's celebrations + tomorrow's birthdays
  async function celebStrip(body) {
    await loadBirthdays();
    if (!body.isConnected) return;
    const old = body.querySelector('.fca-celeb'); if (old) old.remove();
    const items = [];
    const today = new Date(); today.setHours(0, 0, 0, 0);
    bdayToday().forEach(b => items.push(['🎂', b.name.split(' ')[0] + "'s birthday today", 'Send a wish', () => bdayCard(b)]));
    celebsOn(today).filter(c => celebrates(c[0])).forEach(c => items.push([c[2], c[3], 'Send wishes', () => cardSheet({ kind: 'holiday', celeb: c })]));
    (X.bdays || []).filter(b => nextBirthday(b)[1] === 1).forEach(b => items.push(['🎈', b.name.split(' ')[0] + "'s birthday is tomorrow", 'Send at midnight', () => bdayCard(b)]));
    if (!items.length) return;
    const el = document.createElement('div'); el.className = 'fca-celeb';
    el.innerHTML = items.map((x, i) => '<button type="button" data-i="' + i + '"><i>' + x[0] + '</i><span><b>' + esc(x[1]) + '</b><small>' + esc(x[2]) + ' →</small></span></button>').join('');
    el.querySelectorAll('[data-i]').forEach(b => b.onclick = () => items[Number(b.dataset.i)][3]());
    body.insertBefore(el, body.firstChild);
    // birthday cake next to the person in the chat list
    bdayToday().forEach(b => { const r = document.querySelector('#fcRoot .fc-row[data-c="' + b.conversation_id + '"] .fc-name'); if (r && !r.querySelector('.fca-cake')) r.insertAdjacentHTML('beforeend', '<span class="fca-cake" title="Birthday today">🎂</span>'); });
  }
  // greeting card: preview, edit the words, send to one person (birthday) or to chats you pick (holidays)
  function cardHtml(emoji, title, text, cols, big) {
    return '<div class="fcx-greet' + (big ? ' big' : '') + '" style="background:linear-gradient(135deg,' + cols[0] + ',' + cols[1] + ')"><div class="em">' + emoji + '</div><b>' + esc(title) + '</b><p>' + esc(text) + '</p><span class="sp">✦ ✧ ✦</span></div>';
  }
  function cardSheet(o) {
    const isB = o.kind === 'bday';
    let theme = 0;
    const first = isB ? o.person.name.split(' ')[0] : '';
    const title = isB ? 'Happy birthday, ' + first + '!' : o.celeb[3];
    let text = isB ? 'Wishing you a wonderful birthday and an amazing year ahead! 🎉' : o.celeb[5];
    let chats = []; try { chats = (FC().state().list || []).filter(c => !c.archived); } catch (_) {}
    sheet('<h3>' + (isB ? '🎂 Birthday card' : o.celeb[2] + ' ' + esc(o.celeb[3])) + '</h3><div id="fcaCardPrev"></div>' +
      (isB ? '<div class="fca-seg" style="margin:10px 0" id="fcaThemes">' + BDAY_THEMES.map((t, i) => '<button type="button" data-t="' + i + '" class="' + (i ? '' : 'on') + '">' + t[0] + ' ' + t[1] + '</button>').join('') + '</div>' : '') +
      '<textarea id="fcaCardT" rows="3" maxlength="400">' + esc(text) + '</textarea>' +
      '<p style="margin:10px 0 4px">When</p><div class="fca-seg" id="fcaWhen">' + (isB && o.days > 0 ? '<button type="button" data-w="mid" class="on">🌙 Midnight on ' + esc(o.dateText) + '</button><button type="button" data-w="now">Now</button>' : '<button type="button" data-w="now" class="on">Now</button>') + '<button type="button" data-w="pick">⏰ Pick a time</button></div>' +
      '<input id="fcaWhenT" type="datetime-local" style="display:none;margin-top:8px">' +
      (isB ? '' : '<label class="fca-chk" style="padding-left:2px"><input type="checkbox" id="fcaAsStatus"><span>Also post it as my status</span></label>') +
      (isB ? '' : '<p style="margin:8px 0 4px">Send to</p><div style="max-height:30vh;overflow:auto"><label class="fca-chk"><input type="checkbox" id="fcaAll"><span><b>Everyone below</b></span></label>' + chats.map(c => '<label class="fca-chk"><input type="checkbox" class="fcaCc" value="' + c.id + '"><span>' + esc(c.title) + '</span></label>').join('') + '</div>') +
      '<button class="fc-btn" id="fcaCardGo">' + (isB ? 'Send to ' + esc(first) : 'Send') + '</button>', (el, done) => {
      const paint = () => { const t = isB ? BDAY_THEMES[theme] : null; $('#fcaCardPrev', el).innerHTML = cardHtml(isB ? t[0] : o.celeb[2], title, $('#fcaCardT', el).value, isB ? t[2] : o.celeb[6]); };
      $('#fcaCardT', el).oninput = paint; paint();
      el.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { theme = Number(b.dataset.t); el.querySelectorAll('[data-t]').forEach(x => x.classList.toggle('on', x === b)); paint(); });
      const all = $('#fcaAll', el); if (all) all.onchange = () => el.querySelectorAll('.fcaCc').forEach(c => c.checked = all.checked);
      let whenMode = (isB && o.days > 0) ? 'mid' : 'now';
      el.querySelectorAll('[data-w]').forEach(b => b.onclick = () => { whenMode = b.dataset.w; el.querySelectorAll('[data-w]').forEach(x => x.classList.toggle('on', x === b)); $('#fcaWhenT', el).style.display = whenMode === 'pick' ? 'block' : 'none'; });
      $('#fcaCardGo', el).onclick = async e => {
        const words = $('#fcaCardT', el).value.trim() || text;
        const meta = { card: isB ? { k: 'bday', th: theme, t: title } : { k: o.celeb[0], t: title } };
        const emoji = isB ? BDAY_THEMES[theme][0] : o.celeb[2];
        const body = emoji + ' ' + title + ' ' + words;
        let ids = isB ? [o.person.conversation_id] : Array.from(el.querySelectorAll('.fcaCc:checked')).map(c => Number(c.value));
        if (isB && !ids[0]) { toast('Start a chat with ' + first + ' first'); return; }
        if (!ids.length) { toast('Choose at least one chat'); return; }
        let at = '';
        if (whenMode === 'mid') at = new Date(o.date.getFullYear(), o.date.getMonth(), o.date.getDate(), 0, 0, 30).toISOString();
        if (whenMode === 'pick') { const v = $('#fcaWhenT', el).value; if (!v) { toast('Choose the day and time'); return; } at = new Date(v).toISOString(); }
        e.target.disabled = true; let ok = 0;
        for (const c of ids) { try { if (at) await post('/api/fcx/schedule', { c, body, meta, send_at: at }); else await post('/api/fc/send', { c, body, kind: 'text', meta }); ok++; } catch (er) { if (at) toast(er.message); } }
        const st = $('#fcaAsStatus', el);
        if (st && st.checked) { try { await post('/api/fc/status', { body: emoji + ' ' + title + '\n' + words, bg: 'linear-gradient(135deg,' + o.celeb[6][0] + ',' + o.celeb[6][1] + ')' }); try { window.FutureChatStatus && window.FutureChatStatus.refresh(true); } catch (_) {} } catch (_) {} }
        done();
        if (at) toast(ok ? '⏰ Scheduled — it will be sent ' + new Date(at).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'Could not schedule it.');
        else toast(ok ? (isB ? 'Birthday card sent 🎉' : 'Sent to ' + ok + (ok === 1 ? ' chat' : ' chats') + ' ✓') : 'Could not send. Check your connection.');
        if (isB && ok && !at) FC().openConv(ids[0]);
      };
    });
  }
  function bdayCard(p) { const [d, n] = nextBirthday(p); cardSheet({ kind: 'bday', person: p, days: n, date: d, dateText: d.toLocaleDateString([], { day: 'numeric', month: 'short' }) }); }
  // card inside the chat (+ confetti the first time the person opens it)
  FCX.greet = function (m) {
    const k = m.meta.card.k, c = CELEB.find(x => x[0] === k);
    const th = k === 'bday' ? (BDAY_THEMES[Number(m.meta.card.th) || 0] || BDAY_THEMES[0]) : null;
    const emoji = th ? th[0] : (c ? c[2] : '🎉'), cols = th ? th[2] : (c ? c[6] : ['#1e3a8a', '#1ed6c8']);
    const title = String(m.meta.card.t || (c ? c[3] : 'Celebrate!'));
    let words = String(m.body || ''); const cut = words.indexOf(title); if (cut >= 0) words = words.slice(cut + title.length).trim();
    if (!m.mine) { let seen = []; try { seen = JSON.parse(localStorage.getItem('fc_greet_seen') || '[]'); } catch (_) {} if (seen.indexOf(m.id) < 0) { seen.push(m.id); try { localStorage.setItem('fc_greet_seen', JSON.stringify(seen.slice(-300))); } catch (_) {} setTimeout(() => confetti(emoji), 350); } }
    return cardHtml(emoji, title, words, cols, true);
  };
  function confetti(emoji) {
    const box = document.createElement('div'); box.className = 'fca-confetti'; box.setAttribute('aria-hidden', 'true');
    const bits = [emoji, '🎉', '✨', '🎈', '💫', emoji];
    let h = ''; for (let i = 0; i < 34; i++) h += '<span style="left:' + Math.round(Math.random() * 100) + '%;animation-delay:' + (Math.random() * 0.9).toFixed(2) + 's;font-size:' + (18 + Math.round(Math.random() * 18)) + 'px">' + bits[i % bits.length] + '</span>';
    box.innerHTML = h; document.body.appendChild(box); setTimeout(() => box.remove(), 3800);
  }
  // You -> Celebrations
  async function scrCelebrations() {
    const self = X.stack[X.stack.length - 1];
    const bd = frame('Celebrations', 'Birthdays and special days');
    bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    await loadBirthdays(true);
    if (X.stack[X.stack.length - 1] !== self) return;
    const me = (X.prefs && X.prefs.birthday) || {};
    const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    const when_ = n => n === 0 ? 'Today 🎉' : n === 1 ? 'Tomorrow' : 'In ' + n + ' days';
    const bl = (X.bdays || []).map(b => [b, ...nextBirthday(b)]).sort((a, b) => a[2] - b[2]).slice(0, 40);
    const up = upcomingCelebs(60).filter(x => celebrates(x[0][0]));
    let h = '<div class="fca-card">' + row('🎂', 'My birthday', me.d ? me.d + ' ' + MONTHS[me.m - 1] + ((X.prefs || {}).birthday_vis === 'nobody' ? ' · hidden' : ' · people you chat with see it') : 'Add your birthday so friends can celebrate you', { data: 'data-a="mine"' }) + '</div>';
    h += '<div class="fca-gl">Birthdays coming up</div>' + (bl.length ? '<div class="fca-card">' + bl.map(([b, d, n]) => '<button type="button" class="fca-row" data-b="' + b.user_id + '">' + avatar(b.name, b.photo, 'sm') + '<span class="tx"><b>' + esc(b.name) + '</b><small>' + d.getDate() + ' ' + MONTHS[d.getMonth()] + ' · ' + when_(n) + '</small></span><span class="end" style="font-size:20px">' + (n === 0 ? '🎂' : '🎈') + '</span></button>').join('') + '</div>'
      : '<div class="fca-empty"><span class="big">🎈</span><b>No birthdays yet</b>When the people you chat with add their birthday, you\'ll see them here and get a reminder.</div>');
    h += '<div class="fca-gl">Special days coming up</div>' + (up.length ? '<div class="fca-card">' + up.map(([c, d, n]) => '<button type="button" class="fca-row" data-c="' + c[0] + '"><span class="ic" style="background:linear-gradient(135deg,' + c[6][0] + ',' + c[6][1] + ');font-size:19px">' + c[2] + '</span><span class="tx"><b>' + esc(c[3]) + '</b><small>' + d.getDate() + ' ' + MONTHS[d.getMonth()] + ' · ' + when_(n) + '</small></span><span class="chev">›</span></button>').join('') + '</div>' : '<div class="fca-empty">Nothing in the next two months.</div>');
    h += '<div class="fca-card">' + row('🗓️', 'Which special days do you celebrate?', 'Choose your religion, culture and country days', { data: 'data-a="pick"' }) + '</div>' +
      '<p class="fca-note">Future Chat celebrates everyone: Christian, Jewish, Muslim, Hindu, Sikh, Chinese and many more days. You get a banner and a ready greeting card on the day. Muslim dates follow the Umm al-Qura calendar and can differ by a day where the moon is sighted locally; Jewish holidays start the evening before.</p>';
    bd.innerHTML = h;
    bind(bd, { mine: () => push(scrMyBirthday), pick: () => push(scrPickCelebs) });
    bd.querySelectorAll('[data-b]').forEach(b => b.onclick = () => { const p = X.bdays.find(x => x.user_id === Number(b.dataset.b)); bdayCard(p); });
    bd.querySelectorAll('[data-c]').forEach(b => b.onclick = () => cardSheet({ kind: 'holiday', celeb: CELEB.find(x => x[0] === b.dataset.c) }));
    if (FCX.celebExtra) { try { FCX.celebExtra(bd); } catch (_) {} }
  }
  function scrMyBirthday() {
    const bd = frame('My birthday', 'So friends can celebrate you'); const b = (X.prefs && X.prefs.birthday) || {};
    const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    bd.innerHTML = '<div class="fca-hero" style="background:linear-gradient(135deg,#9d174d,#f59e0b)"><small>🎂 BIRTHDAY</small><b>' + (b.d ? b.d + ' ' + MONTHS[b.m - 1] : 'Add your birthday') + '</b><p>On your birthday the people you chat with get a reminder to wish you, and your circles get a note.</p></div>' +
      '<div style="display:grid;grid-template-columns:1fr 2fr;gap:10px"><label class="fca-field"><span>Day</span><select id="fcaBd">' + '<option value="">—</option>' + Array.from({ length: 31 }, (_, i) => '<option' + (b.d === i + 1 ? ' selected' : '') + '>' + (i + 1) + '</option>').join('') + '</select></label>' +
      '<label class="fca-field"><span>Month</span><select id="fcaBm"><option value="">—</option>' + MONTHS.map((m, i) => '<option value="' + (i + 1) + '"' + (b.m === i + 1 ? ' selected' : '') + '>' + m + '</option>').join('') + '</select></label></div>' +
      '<label class="fca-field"><span>Year (optional — never shown to anyone)</span><input id="fcaBy" inputmode="numeric" maxlength="4" placeholder="e.g. 1990" value="' + (b.y || '') + '"></label>' +
      choiceRows('birthday_vis', 'Who sees my birthday', [['contacts', 'The people I chat with', ''], ['nobody', 'Nobody', 'No reminders go out for you']]) +
      '<button class="fca-btn" data-a="save">Save my birthday</button>' + (b.d ? '<button class="fca-btn danger" data-a="rm">Remove my birthday</button>' : '');
    bindChoices(bd, scrMyBirthday);
    bind(bd, {
      save: async () => { const d = Number($('#fcaBd', bd).value), m = Number($('#fcaBm', bd).value); if (!d || !m) { toast('Choose the day and month'); return; } if (await savePrefs({ birthday: { d, m, y: Number($('#fcaBy', bd).value) || 0 } })) { toast('Birthday saved 🎂'); pop(); } },
      rm: async () => { if (await savePrefs({ birthday: {} })) { toast('Birthday removed'); scrMyBirthday(); } }
    });
  }
  function scrPickCelebs() {
    const bd = frame('Special days', 'Choose what you celebrate');
    const draw_ = () => {
      bd.innerHTML = toggles([['notify_celeb', 'Morning reminder on my special days', 'A friendly nudge to send greetings']]) +
        '<p class="fca-note">Turn on the days you celebrate. You\'ll see a banner and a greeting card on the day. Reminders for faith days only come for the days you switch on here.</p>' +
        Object.keys(CG).map(g => '<div class="fca-gl">' + esc(CG[g]) + '</div><div class="fca-card">' + CELEB.filter(c => c[1] === g).map(c => row(c[2], c[3], '', { data: 'data-k="' + c[0] + '"' }, '<span class="fca-sw' + (celebrates(c[0]) ? ' on' : '') + '"></span>')).join('') + '</div>').join('');
      bindToggles(bd);
      bd.querySelectorAll('[data-k]').forEach(b => b.onclick = async () => {
        const id = b.dataset.k; let l = ((X.prefs && X.prefs.celebrate) || ['*']).slice();
        if (l.indexOf('*') >= 0) { const i = l.indexOf('-' + id); if (i >= 0) l.splice(i, 1); else l.push('-' + id); }
        else { const i = l.indexOf(id); if (i >= 0) l.splice(i, 1); else l.push(id); }
        if (await savePrefs({ celebrate: l })) draw_();
      });
    };
    draw_();
  }
  FCX.celebrations = () => { openPanel(); push(scrCelebrations); };
  function greetingFor(conv) {
    const peer = X.peers[String(conv.id)] || {};
    const b = (X.bdays || []).find(x => x.user_id === peer.user_id);
    const up = upcomingCelebs(30).filter(x => celebrates(x[0][0])).slice(0, 8);
    const opts = [];
    if (b) opts.push(['🎂', 'Birthday card for ' + b.name.split(' ')[0], () => bdayCard(b)]);
    up.forEach(([c, d, n]) => opts.push([c[2], c[3] + (n === 0 ? ' · today' : ' · ' + d.toLocaleDateString([], { day: 'numeric', month: 'short' })), () => cardSheet({ kind: 'holiday', celeb: c })]));
    CELEB.filter(c => !up.some(u => u[0][0] === c[0])).slice(0, 0).forEach(() => {});
    opts.push(['🎉', 'All special days…', () => { openPanel(); push(scrCelebrations); }]);
    sheet('<h3>🎉 Greeting card</h3><div class="fc-acts">' + opts.map((o, i) => '<button class="fc-act" data-i="' + i + '"><i>' + o[0] + '</i>' + esc(o[1]) + '</button>').join('') + '</div>', (el, done) => {
      el.querySelectorAll('[data-i]').forEach(x => x.onclick = () => { done(); opts[Number(x.dataset.i)][2](); });
    });
  }

  async function scrScheduled() {
    const self = X.stack[X.stack.length - 1];
    const bd = frame('Scheduled messages', 'Sent automatically at the time you chose'); bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let items = []; try { items = (await api('/api/fcx/scheduled')).items || []; } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (X.stack[X.stack.length - 1] !== self) return;
    bd.innerHTML = items.length ? '<div class="fca-card">' + items.map(s => '<div class="fca-item"><span style="font-size:20px;width:26px;text-align:center">⏰</span><div class="tx"><b>' + esc(s.title) + '</b><small data-no-tr>' + esc(s.body.slice(0, 120)) + '</small><span class="due">' + esc(dueText(s.send_at).toUpperCase()) + '</span></div><button class="x" data-x="' + s.id + '" aria-label="Cancel">✕</button></div>').join('') + '</div>'
      : '<div class="fca-empty"><span class="big">⏰</span><b>Nothing scheduled</b>Write a message now and Future Chat sends it later — like a birthday wish at midnight.</div>';
    bd.querySelectorAll('[data-x]').forEach(b => b.onclick = async () => { if (!confirm('Cancel this scheduled message?')) return; try { await post('/api/fcx/schedule/cancel', { id: Number(b.dataset.x) }); toast('Cancelled'); scrScheduled(); } catch (e) { toast(e.message); } });
  }
  function scheduleForm(conv) {
    const soon = new Date(Date.now() + 3600e3); soon.setMinutes(0, 0, 0);
    sheet('<h3>⏰ Schedule a message</h3><p>Future Chat sends it for you at the time you choose.</p><textarea id="fcaSchT" rows="4" maxlength="4000" placeholder="Your message"></textarea>' +
      '<label class="fca-field"><span>Send on</span><input id="fcaSchW" type="datetime-local" value="' + esc(localInput(soon.toISOString())) + '"></label><button class="fc-btn" id="fcaSchGo">Schedule</button>', (el, done) => {
      setTimeout(() => { try { $('#fcaSchT', el).focus(); } catch (_) {} }, 50);
      $('#fcaSchGo', el).onclick = async e => { const t = $('#fcaSchT', el).value.trim(), w = $('#fcaSchW', el).value; if (!t) { toast('Type your message first'); return; } if (!w) { toast('Choose when to send it'); return; }
        e.target.disabled = true; try { const d = await post('/api/fcx/schedule', { c: conv.id, body: t, send_at: new Date(w).toISOString() }); done(); toast('⏰ Scheduled for ' + dueText(d.send_at)); } catch (er) { toast(er.message); e.target.disabled = false; } };
    });
  }

  // ---------------------------------------------------------------- clear chats + backup (FCX-CLEAR-01)
  async function clearChats(cid, title) {
    const all = !cid;
    if (!confirm(all ? 'Clear ALL your chats? Every chat will be empty on your account. Other people keep their copy. You can bring them back with Chat backup → Restore.' :
      'Clear all messages in "' + title + '"? Only for you — the other person keeps their copy. You can bring them back with Chat backup → Restore.')) return;
    try { const d = await post('/api/fcx/clear', all ? { all: true } : { c: cid }); toast(all ? 'Cleared ' + d.cleared + (d.cleared === 1 ? ' chat' : ' chats') : 'Chat cleared');
      try { FC().refreshMsgs(); FC().reloadList(); } catch (_) {} if (X.stack.length) draw(); } catch (e) { toast(e.message); }
  }
  function backupText(d) {
    const L = ['Future Chat backup', 'Account: ' + d.account, 'Saved: ' + new Date(d.exported_at).toLocaleString(), ''];
    for (const ch of d.chats) {
      L.push('==================================================', ch.chat + (ch.kind === 'group' ? ' (group)' : ''), '==================================================');
      let day = '';
      for (const m of ch.messages) {
        const t = new Date(m.at); const dd = t.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
        if (dd !== day) { L.push('', '--- ' + dd + ' ---'); day = dd; }
        L.push('[' + t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + '] ' + m.from + ': ' + (m.text || '') + (m.files && m.files.length ? '  (files: ' + m.files.join(', ') + ')' : ''));
      }
      if (!ch.messages.length) L.push('(no messages)');
      L.push('');
    }
    return L.join('\n');
  }
  async function saveCopy(cid, title) {
    toast('Preparing your copy…');
    try {
      const d = await api('/api/fcx/backup' + (cid ? '?c=' + cid : ''));
      const name = 'FutureChat-' + (cid ? String(title || 'chat').replace(/[^A-Za-z0-9]+/g, '-').slice(0, 40) : 'backup') + '-' + new Date().toISOString().slice(0, 10) + '.txt';
      const a = document.createElement('a'); a.href = 'data:text/plain;charset=utf-8,' + encodeURIComponent(backupText(d)); a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => toast('Saved to your Downloads folder: ' + name), 400);
    } catch (e) { toast(e.message); }
  }
  async function scrBackup() {
    const self = X.stack[X.stack.length - 1];
    const bd = frame('Chat backup', 'Keep your chats safe'); bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let i; try { i = await api('/api/fcx/backup/info'); } catch (e) { bd.innerHTML = '<div class="fca-empty"><b>Couldn\'t load</b>' + esc(e.message) + '</div>'; return; }
    if (X.stack[X.stack.length - 1] !== self) return;
    bd.innerHTML = '<div class="fca-hero"><small>AUTOMATIC BACKUP · ON</small><b>' + i.messages + (i.messages === 1 ? ' message' : ' messages') + '</b><p>' + i.chats + (i.chats === 1 ? ' chat' : ' chats') + ' backed up to your Future Chat account · last change ' + esc(when(i.backed_up_at)) + '. Sign in on a new phone and your chats are there.</p></div>' +
      '<div class="fca-card">' + row('☁️', 'Back up now', 'Check that everything is backed up', { data: 'data-a="now"' }) +
      row('💾', 'Save a copy to this phone', 'All your chats as a text file in Downloads', { data: 'data-a="copy"' }) +
      (i.cleared ? row('♻️', 'Restore cleared chats', i.cleared + (i.cleared === 1 ? ' message' : ' messages') + ' you cleared can come back', { data: 'data-a="restore"' }) : '') + '</div>' +
      '<div class="fca-card">' + row('🗑️', 'Clear all chats', 'Empty every chat (restore from here later)', { data: 'data-a="clearall"', cls: 'danger' }, '') + '</div>' +
      '<p class="fca-note">Messages are backed up to your account automatically. Photos, videos and voice notes are kept on the phones they were sent to — keep them with your phone\'s own Google Photos or gallery backup.</p>';
    bind(bd, {
      now: async b => { b.disabled = true; try { await api('/api/fcx/backup/info'); toast('All ' + i.messages + ' messages are backed up ✓'); } catch (e) { toast(e.message); } b.disabled = false; },
      copy: () => saveCopy(0, ''),
      restore: async () => { if (!confirm('Bring back the messages you cleared?')) return; try { const d = await post('/api/fcx/restore'); toast('Restored ' + d.restored + (d.restored === 1 ? ' chat' : ' chats')); try { FC().reloadList(); } catch (_) {} scrBackup(); } catch (e) { toast(e.message); } },
      clearall: async () => { await clearChats(0, ''); scrBackup(); }
    });
  }

  // ---------------------------------------------------------------- Advertise with us (FC-ADS-02: cheap day prices, paid in this app)
  const payReady = () => !!(window.SkillvayaBilling && typeof window.SkillvayaBilling.purchaseAd === 'function');
  const PLAY_PRICE = {};
  FCX.advertise = async function () {
    let d = {};
    try { d = await api('/api/home-ads/mine?app=futurechat'); } catch (_) {}
    if (!X.stack.length) { openPanel(); }
    if (payReady()) { try { window.SkillvayaBilling.queryAdProducts(); if (d.me) window.SkillvayaBilling.restoreAdPurchases(String(d.me.id), tok()); } catch (_) {} }
    push(() => scrAdvertise(d.me || {}, d.plans || [], d.reach || null));
  };
  function adHooks(after) {
    window.haAdProducts = json => { try { (JSON.parse(json || '[]') || []).forEach(p => { PLAY_PRICE[p.productId] = p.price; }); } catch (_) {} document.querySelectorAll('[data-fcprice]').forEach(el => { const pr = PLAY_PRICE[el.dataset.fcprice]; if (pr) el.textContent = pr; }); };
    window.haAdError = msg => { toast(msg || 'Google Play payment did not complete.'); if (after) after(false); };
    window.haAdResult = json => { let r = {}; try { r = typeof json === 'string' ? JSON.parse(json) : (json || {}); } catch (_) {}
      if (r.ok) { toast(r.message || 'Payment received ✓ Your ad is waiting for approval.'); if (after) after(true); }
      else { toast(r.cancelled ? 'Payment cancelled. You were not charged.' : (r.message || 'The payment could not be confirmed yet.')); if (after) after(false); } };
  }
  function scrAdvertise(me, plans, reach) {
    const bd = frame('Advertise with us', 'From R5 a day');
    const owner = me.role === 'admin';
    const pr = id => PLAY_PRICE[id] || ((plans.find(p => p.product_id === id) || {}).price || '');
    const dayWord = n => n === 7 ? '1 week' : n === 1 ? '1 day' : n + ' days';
    const R = reach || {}; const ppl = R.people_today || 0;
    bd.innerHTML = '<div class="fca-hero"><small>SPONSORED STATUS</small><b>Your business in Status, from R5 a day</b><p>Your ad shows in Sponsored at the top of Status — only when people choose to open it. Never a pop-up, never in chats. Every ad is checked before it goes live, and you get your money back if it isn\'t approved.</p></div>' +
      '<div class="fca-gl">How many people see it</div><div class="fca-card">' +
      row('👥', ppl ? ppl + (ppl === 1 ? ' person' : ' people') + ' on Future Chat today' : 'Future Chat is growing every day', 'Each person can see your picture up to 2 times a day, a video up to 3 times', {}, '') +
      row('🔁', 'Fair turns for every ad', 'Ads take turns of about 30 seconds. When there are more ads, more Sponsored statuses appear (up to ' + ((R.capacity || 50) / 10) + ')', {}, '') +
      (R.places_left === 0 ? row('⏳', 'All places are taken today', 'Your ad starts as soon as a place opens — your days only start then', {}, '') : '') + '</div>' +
      '<div class="fca-gl">Your ad</div>' +
      '<div class="fca-seg" style="margin-bottom:10px" id="fcaAdK"><button class="on" data-k="photo">🖼️ Picture</button><button data-k="word">✍️ Words only</button><button data-k="video">🎬 Video</button></div>' +
      '<label class="fca-field"><span>Business name</span><input id="fcaAdA" maxlength="60" value="' + esc(me.business_name || me.name || '') + '"></label>' +
      '<label class="fca-field"><span>Headline</span><input id="fcaAdH" maxlength="60" placeholder="e.g. Fresh cakes delivered in Bellville"></label>' +
      '<label class="fca-field"><span>Short message (optional)</span><textarea id="fcaAdB" rows="2" maxlength="180"></textarea></label>' +
      '<div class="fca-field" id="fcaAdFRow"><span id="fcaAdFL">Picture (JPG, PNG or WebP, up to 2 MB)</span><input id="fcaAdF" type="file" hidden accept="image/jpeg,image/png,image/webp">' +
      '<button type="button" class="fca-pick" id="fcaAdPick"><i>📎</i><span><b id="fcaAdPN">Add your picture</b><small id="fcaAdPS">Tap to choose from your phone</small></span></button><div class="fca-prev" id="fcaAdPrev"></div></div>' +
      '<label class="fca-field"><span>When people tap your ad</span><select id="fcaAdTo"><option value="tel">Call my number</option><option value="web">Open my website or page</option><option value="none">Nothing (just show the ad)</option></select></label>' +
      '<label class="fca-field" id="fcaAdLRow"><span id="fcaAdLL">Phone number</span><input id="fcaAdL" inputmode="tel" placeholder="082 123 4567" value="' + esc((X.me || {}).phone || '') + '"></label>' +
      '<div class="fca-gl">How long</div><div class="fcaad-plans" id="fcaAdP"></div>' +
      '<p class="fca-note">Ads must be honest and legal: no adult content, weapons, gambling, scams, misleading claims or other people\'s trademarks. Payment is through Google Play.</p>' +
      '<button class="fca-btn" data-a="go" id="fcaAdGo"></button><button class="fca-btn sec" data-a="mine">My ads</button>';
    let kind = 'photo', product = '';
    const $$ = s => $(s, bd);
    const label = () => owner ? 'Publish my ad (free for the owner)' : payReady() ? 'Pay ' + pr(product) + ' with Google Play' : 'Send my ad';
    const drawPlans = () => {
      const tier = kind === 'video' ? 'video' : 'word', list = plans.filter(p => p.tier === tier).sort((a, b) => a.days - b.days);
      if (!list.some(p => p.product_id === product)) product = list[0] ? list[0].product_id : '';
      $$('#fcaAdP').innerHTML = list.map(p => '<button type="button" data-p="' + p.product_id + '" class="' + (p.product_id === product ? 'on' : '') + '"><b>' + dayWord(p.days) + '</b><em data-fcprice="' + p.product_id + '">' + esc(pr(p.product_id)) + '</em></button>').join('') ||
        '<div class="fca-empty" style="padding:14px">Prices are loading. Try again in a moment.</div>';
      $$('#fcaAdP').querySelectorAll('[data-p]').forEach(b => b.onclick = () => { product = b.dataset.p; drawPlans(); });
      $$('#fcaAdGo').textContent = label();
    };
    bd.querySelectorAll('#fcaAdK button').forEach(b => b.onclick = () => { kind = b.dataset.k; bd.querySelectorAll('#fcaAdK button').forEach(x => x.classList.toggle('on', x === b));
      $$('#fcaAdFRow').style.display = kind === 'word' ? 'none' : 'block'; $$('#fcaAdFL').textContent = kind === 'photo' ? 'Picture (JPG, PNG or WebP, up to 2 MB)' : 'Video (MP4, up to 12 MB, about 30 seconds)';
      $$('#fcaAdF').accept = kind === 'photo' ? 'image/jpeg,image/png,image/webp' : 'video/mp4,video/webm,video/quicktime'; $$('#fcaAdF').value = ''; showPick(); drawPlans(); });
    const showPick = () => {
      const f = $$('#fcaAdF').files && $$('#fcaAdF').files[0], prev = $$('#fcaAdPrev');
      $$('#fcaAdPN').textContent = f ? f.name : (kind === 'video' ? 'Add your video' : 'Add your picture');
      $$('#fcaAdPS').textContent = f ? (f.size / 1048576).toFixed(1) + ' MB · tap to change' : 'Tap to choose from your phone';
      if (prev.dataset.url) { URL.revokeObjectURL(prev.dataset.url); delete prev.dataset.url; }
      prev.innerHTML = '';
      if (f) { const u = URL.createObjectURL(f); prev.dataset.url = u; prev.innerHTML = /^video\//.test(f.type) ? '<video src="' + u + '" muted playsinline controls></video>' : '<img src="' + u + '" alt="Your ad picture">'; }
    };
    $$('#fcaAdPick').onclick = () => $$('#fcaAdF').click();
    $$('#fcaAdF').onchange = showPick;
    $$('#fcaAdTo').onchange = () => { const v = $$('#fcaAdTo').value; $$('#fcaAdLRow').style.display = v === 'none' ? 'none' : 'block'; $$('#fcaAdLL').textContent = v === 'tel' ? 'Phone number' : 'Website or page link'; $$('#fcaAdL').inputMode = v === 'tel' ? 'tel' : 'url'; $$('#fcaAdL').placeholder = v === 'tel' ? '082 123 4567' : 'www.mybusiness.co.za'; if (v === 'web') $$('#fcaAdL').value = ''; };
    drawPlans();
    const reset = b => { b.disabled = false; b.textContent = label(); };
    bind(bd, {
      mine: () => push(scrMyAds),
      go: async b => {
        if (!product) { toast('Choose how long'); return; }
        const headline = $$('#fcaAdH').value.trim(); if (headline.length < 3) { toast('Add a short headline'); return; }
        const to = $$('#fcaAdTo').value, link = $$('#fcaAdL').value.trim();
        if (to !== 'none' && !link) { toast(to === 'tel' ? 'Add your phone number' : 'Add your website link'); return; }
        const target = to === 'none' ? '' : to === 'tel' ? 'tel:' + link.replace(/[^\d+]/g, '') : (/^https?:\/\//i.test(link) ? link : 'https://' + link);
        let media = null;
        if (kind !== 'word') {
          const f = $$('#fcaAdF').files[0]; if (!f) { toast(kind === 'video' ? 'Add your video' : 'Add your picture'); return; }
          if (kind === 'photo' && f.size > 2 * 1024 * 1024) { toast('Pictures must be 2 MB or smaller'); return; }
          if (kind === 'video' && f.size > 12 * 1024 * 1024) { toast('Videos must be 12 MB or smaller'); return; }
          media = { mime: f.type, data_base64: await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.onerror = () => rej(new Error('That file could not be read.')); r.readAsDataURL(f); }) };
        }
        b.disabled = true; b.textContent = 'Uploading your ad…';
        try {
          const d = await post('/api/home-ads/create', { kind, headline, body: $$('#fcaAdB').value.trim(), cta: to === 'tel' ? 'Call now' : to === 'web' ? 'Visit' : 'Learn more', target, advertiser: $$('#fcaAdA').value.trim(), product_id: product, media });
          if (owner || d.status === 'active' || d.status === 'queued') {
            toast(d.status === 'queued' ? 'Approved — it starts as soon as a place opens ✓' : 'Your ad is live in Sponsored status ✓');
            try { window.FutureChatStatus && window.FutureChatStatus.refresh(true); } catch (_) {} pop(); return;
          }
          if (!payReady()) { toast('Update Future Chat from Google Play to pay for ads in the app'); reset(b); return; }
          b.textContent = 'Opening Google Play…';
          adHooks(ok => { if (ok) { pop(); push(scrMyAds); } else reset(b); });
          window.SkillvayaBilling.purchaseAd(d.product_id, String(d.id), String(me.id), tok());
        } catch (e) { toast(e.message); reset(b); }
      }
    });
    adHooks(null);
  }
  async function scrMyAds() {
    const self = X.stack[X.stack.length - 1];
    const bd = frame('My ads', 'Your Sponsored status ads'); bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let d; try { d = await api('/api/home-ads/mine?app=futurechat'); } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (X.stack[X.stack.length - 1] !== self) return;
    const ST = { pending_payment: 'Not paid yet', pending_review: 'Waiting for approval', queued: 'Approved · starts when a place opens', active: 'Live', paused: 'Paused', rejected: 'Not approved', expired: 'Ended' };
    const items = d.items || [];
    bd.innerHTML = items.length ? '<div class="fca-card">' + items.map(a => row(a.status === 'active' ? '🟢' : '📣', a.headline, (ST[a.status] || a.status) + ' · ' + (a.plan || '') + (a.status === 'active' || a.status === 'expired' ? ' · shown ' + a.views + ' times, ' + a.clicks + ' taps' : '') + (a.ends_at ? ' · until ' + new Date(a.ends_at).toLocaleDateString() : ''), {}, '')).join('') + '</div>'
      : '<div class="fca-empty"><span class="big">📣</span><b>No ads yet</b>Create your first ad and reach people in Status.</div>';
  }

  function scrHelp() {
    const bd = frame('Help and safety', 'Report, block and protect your account');
    bd.innerHTML = '<div class="fca-card">' + row('🛡️', 'Stay safe on Future Chat', 'Simple ways to protect yourself', { data: 'data-a="tips"' }) + row('⚑', 'Report a problem', 'Tell the Future Chat team', { data: 'data-a="report"' }) + row('🚫', 'Blocked accounts', '', { data: 'data-a="blocked"' }) + row('🗑️', 'How to delete an account', '', { data: 'data-a="del"' }) + '</div>' +
      '<p class="fca-note">To report a person or a group, open the chat, tap ⋮ and choose Report.</p>';
    bind(bd, {
      tips: () => sheet('<h3>Stay safe on Future Chat</h3><p>Check who you are talking to before you trust them. Never share your password or a code we send you — Future Chat will never ask for it. Don\'t send money to someone you can\'t verify. Block and report anyone who makes you uncomfortable. If you are in danger, contact the police (10111 in South Africa).</p>'),
      report: () => sheet('<h3>Report a problem</h3><textarea id="fcaRp" rows="5" maxlength="3000" placeholder="What happened?"></textarea><button class="fc-btn" id="fcaRpGo">Send report</button>', (el, done) => { $('#fcaRpGo', el).onclick = async e => { e.target.disabled = true; try { const d = await post('/api/fcx/report', { body: $('#fcaRp', el).value }); done(); toast(d.message); } catch (er) { toast(er.message); e.target.disabled = false; } }; }),
      blocked: () => push(scrBlocked), del: () => window.open('/account-deletion', '_blank')
    });
  }
  function scrTerms() {
    const bd = frame('Terms and policies', '');
    bd.innerHTML = '<div class="fca-card">' + row('📄', 'Terms, Rules & Safety', '', { data: 'data-a="t"' }) + row('🔒', 'Privacy Policy', '', { data: 'data-a="p"' }) + row('🗑️', 'Account deletion', '', { data: 'data-a="d"' }) + '</div>';
    bind(bd, { t: () => window.open('https://futurechat-v5lx.onrender.com/terms.html', '_blank'), p: () => window.open('https://futurechat-v5lx.onrender.com/privacy.html', '_blank'), d: () => window.open('/account-deletion', '_blank') });
  }
  function scrAbout() {
    const bd = frame('About Future Chat', 'Stay close. Wherever life takes you.');
    bd.innerHTML = '<div class="fca-prof">' + MARK.replace('class="fca-mark"', 'style="width:84px;height:84px"') + '<h3>Future Chat</h3><p>Version ' + esc(appVersion()) + '</p></div>' +
      '<p class="fca-note" style="font-size:14.5px;color:#cfe3f2">Chats, free voice and video calls, Status, Circles, polls, tasks and reminders — and the Future Chatmoji language with Lenses, free for everyone. Made in South Africa.</p>';
  }
  async function scrPeer(uid, convId) {
    const self = X.stack[X.stack.length - 1];
    const bd = frame('Profile', ''); bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let p; try { p = (await api('/api/fcx/profile/' + uid)).profile; } catch (e) { bd.innerHTML = '<div class="fca-empty"><b>Couldn\'t load this profile</b>' + esc(e.message) + '</div>'; return; }
    if (X.stack[X.stack.length - 1] !== self) return;
    let h = '<div class="fca-prof">' + avatar(p.name, p.photo, 'xl') + '<h3>' + esc(p.name) + '</h3>' + (p.seen ? '<p style="color:#1ed6c8">' + esc(p.seen) + '</p>' : '') + (p.about ? '<p>' + esc(p.about) + '</p>' : '') + (p.phone ? '<p>' + esc(p.phone) + '</p>' : '') + '</div>';
    if (!p.blocked) h += '<div class="fca-acts"><button class="fca-act" data-a="msg"><i>💬</i>Message</button><button class="fca-act" data-a="voice"><i>📞</i>Voice</button><button class="fca-act" data-a="video"><i>🎥</i>Video</button></div>';
    if (p.biz) h += '<div class="fca-gl">Business</div><div class="fca-card" style="padding:14px"><b style="font-size:17px">' + esc(p.biz.name) + '</b>' + (p.biz.category ? '<p class="fca-note" style="margin:2px 0">' + esc(p.biz.category) + '</p>' : '') + (p.biz.about ? '<p style="margin:8px 0;white-space:pre-wrap">' + esc(p.biz.about) + '</p>' : '') +
      [['🕒', p.biz.hours], ['📍', p.biz.address], ['🔗', p.biz.website], ['✉️', p.biz.email]].filter(x => x[1]).map(x => '<p class="fca-note" style="margin:4px 0">' + x[0] + ' ' + esc(x[1]) + '</p>').join('') + '</div>';
    if (p.groups && p.groups.length) h += '<div class="fca-gl">Circles together</div><div class="fca-card">' + p.groups.map(g => row('◎', g.title, '', { data: 'data-a="grp" data-g="' + g.id + '"' })).join('') + '</div>';
    h += '<div class="fca-card">' + row('🚫', p.blocked ? 'Unblock ' + p.name : 'Block ' + p.name, '', { data: 'data-a="block"', cls: 'danger' }, '') + '</div>';
    bd.innerHTML = h;
    bind(bd, { msg: () => FC().openConv(convId), voice: () => FC().callConv(convId, 'voice'), video: () => FC().callConv(convId, 'video'),
      block: async () => { await blockUser(uid, !p.blocked, p.name); scrPeer(uid, convId); } });
    bd.querySelectorAll('[data-g]').forEach(b => b.onclick = () => { const g = p.groups.find(x => x.id === Number(b.dataset.g)); push(() => scrCircle(g.id, g.title)); });
  }
  async function signOut() {
    if (!confirm('Sign out of Future Chat on this phone?')) return;
    try { await post('/api/logout', {}); } catch (_) {}
    try { ['skillvaya_token', 'sv_token', 'skillvaya_user'].forEach(k => localStorage.removeItem(k)); } catch (_) {}
    location.replace('/futurechat-app');
  }
  async function deleteAccount() {
    const reason = prompt('We are sorry to see you go. Tell us why (optional), then press OK to ask us to delete your account and data.');
    if (reason === null) return;
    try { const d = await post('/api/account/delete-request', { reason: reason || 'Requested in the Future Chat app' }); alert(d.message || 'Your deletion request has been recorded. We will confirm by email.'); }
    catch (err) { alert('Could not send your request: ' + err.message + '\nYou can also use ' + location.origin + '/account-deletion'); }
  }
  window.fcAppMenu = () => go('you');

  // ---------------------------------------------------------------- sign in / create account (unchanged flow, own look)
  function showAuth(mode) {
    let el = document.getElementById('fcaAuth');
    if (!el) { el = document.createElement('div'); el.id = 'fcaAuth'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', 'Future Chat sign in'); document.body.appendChild(el); }
    const create = mode === 'create';
    el.innerHTML = '<div class="fca-w"><button type="button" class="fca-langbtn" id="fcaLangBtn" data-no-tr>🌐 ' + esc((langInfo(appLang()) || ['', 'English'])[1]) + ' ▾</button><div class="fca-brand2">' + MARK.replace('class="fca-mark"', 'class="fca-lg"') + '<div><b>Future Chat</b><small>Stay close. Wherever life takes you.</small></div></div>' +
      '<div class="fca-tabs" role="tablist"><button type="button" data-m="signin" class="' + (create ? '' : 'on') + '">Sign in</button><button type="button" data-m="create" class="' + (create ? 'on' : '') + '">Create account</button></div>' +
      '<form id="fcaForm" novalidate>' +
      (create ? '<label for="fcaName">Your name</label><input id="fcaName" type="text" autocomplete="name" required>' : '') +
      '<label for="fcaEmail">Email</label><input id="fcaEmail" type="email" autocomplete="email" inputmode="email" required>' +
      (create ? '<label for="fcaPhone">Mobile number</label><input id="fcaPhone" type="tel" autocomplete="tel" inputmode="tel" placeholder="e.g. 082 123 4567" required>' : '') +
      '<label for="fcaPw">Password' + (create ? ' (8 or more characters)' : '') + '</label><input id="fcaPw" type="password" autocomplete="' + (create ? 'new-password' : 'current-password') + '" required>' +
      '<label class="fca-tick"><input id="fcaTerms" type="checkbox"><span>I have read and agree to the <a href="https://futurechat-v5lx.onrender.com/terms.html" target="_blank" rel="noopener">Terms of Use</a> and the <a href="https://futurechat-v5lx.onrender.com/privacy.html" target="_blank" rel="noopener">Privacy Policy</a>. I am 13 or older.</span></label>' +
      '<button class="fca-go" type="submit">' + (create ? 'Create my account' : 'Sign in') + '</button><div class="fca-msg" id="fcaMsg" role="alert"></div>' + (create ? '' : '<button type="button" class="fca-forgot" id="fcaForgot">Forgot your password?</button>') + '</form>' +
      '<p class="fca-note2" data-keep-brand>' + (create ? 'Your number lets friends and family find you and call you on Future Chat. We confirm it with a code.' : 'One account for Future Chat and Skillvaya: sign in with the same email and password.') +
      ' <a href="/account-deletion" target="_blank" rel="noopener">Delete an account</a></p></div>';
    el.querySelectorAll('.fca-tabs button').forEach(b => b.onclick = () => showAuth(b.dataset.m));
    el.querySelector('#fcaLangBtn').onclick = () => langPicker(() => setTimeout(() => showAuth(mode), 300));
    const form = el.querySelector('#fcaForm'), msg = el.querySelector('#fcaMsg'), btn = el.querySelector('.fca-go');
    const fg = el.querySelector('#fcaForgot');
    if (fg) fg.onclick = async () => {
      const email = ((el.querySelector('#fcaEmail') || {}).value || '').trim();
      if (!email || email.indexOf('@') < 0) { msg.style.color = '#ffd0d0'; msg.textContent = 'Type your email above first, then tap Forgot your password.'; return; }
      fg.disabled = true;
      try { const d = await post('/api/password-reset/request', { email }); msg.style.color = '#bff3d6'; msg.textContent = (d.message || 'If an account matches that email, a reset link is on its way.') + ' Check your inbox and spam folder.'; }
      catch (err) { msg.style.color = '#ffd0d0'; msg.textContent = err.message; }
      fg.disabled = false;
    };
    form.onsubmit = async e => {
      e.preventDefault(); msg.style.color = ''; msg.textContent = '';
      const v = id => (el.querySelector('#' + id) || {}).value || '';
      if (!el.querySelector('#fcaTerms').checked) { msg.textContent = 'Please tick the box to agree to the Terms and Privacy Policy.'; return; }
      btn.disabled = true;
      try {
        let d;
        const cc = (() => { try { return (typeof window.svCountry === 'function' && window.svCountry()) || 'ZA'; } catch (_) { return 'ZA'; } })();
        if (create) d = await post('/api/signup', { name: v('fcaName').trim(), email: v('fcaEmail').trim(), phone: v('fcaPhone').trim(), password: v('fcaPw'), role: 'customer', country: cc, accept_terms: true });
        else d = await post('/api/login', { email: v('fcaEmail').trim(), password: v('fcaPw'), accept_terms: true });
        try { localStorage.setItem('skillvaya_token', d.token); localStorage.setItem('sv_token', d.token); localStorage.setItem('skillvaya_user', JSON.stringify({ id: d.user.id, name: d.user.name, email: d.user.email, role: d.user.role })); } catch (_) {}
        location.replace('/futurechat-app' + (create ? '?fc_verify=1' : ''));
      } catch (err) { msg.textContent = err.message; btn.disabled = false; }
    };
  }
  const authCss = document.createElement('style');
  authCss.textContent = '#fcaAuth{position:fixed;inset:0;z-index:12000;overflow:auto;color:#eaf4ff;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:linear-gradient(180deg,#0a1f33 0%,#0f3150 55%,#11506a 100%)}#fcaAuth *{box-sizing:border-box}' +
    '#fcaAuth .fca-langbtn{display:block;margin:0 0 6px auto;border:1px solid rgba(30,214,200,.45);background:rgba(30,214,200,.1);color:#5ff0e2;border-radius:20px;padding:8px 14px;font-weight:700;font-size:14px}' +
    '#fcaAuth .fca-w{max-width:440px;margin:0 auto;padding:max(30px,env(safe-area-inset-top)) 22px 40px}#fcaAuth .fca-brand2{display:flex;align-items:center;gap:14px;margin:10px 0 20px}#fcaAuth .fca-lg{width:58px;height:58px;flex:none}' +
    '#fcaAuth .fca-brand2 b{display:block;font-size:27px;color:#fff}#fcaAuth .fca-brand2 small{display:block;color:#9cb7cc;font-size:14px;margin-top:2px}' +
    '#fcaAuth .fca-tabs{display:grid;grid-template-columns:1fr 1fr;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.09);border-radius:15px;padding:4px;margin:10px 0 18px}#fcaAuth .fca-tabs button{border:0;border-radius:11px;padding:11px;font-weight:800;font-size:15px;background:transparent;color:#cfe3f2}#fcaAuth .fca-tabs button.on{background:#1ed6c8;color:#05283a}' +
    '#fcaAuth label{display:block;font-size:13px;color:#9cb7cc;margin:12px 0 6px}#fcaAuth input[type=text],#fcaAuth input[type=email],#fcaAuth input[type=tel],#fcaAuth input[type=password]{width:100%;border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.07);color:#fff;border-radius:13px;padding:13px 14px;font-size:16px;outline:none}#fcaAuth input:focus{border-color:#1ed6c8}' +
    '#fcaAuth .fca-tick{display:flex;gap:10px;align-items:flex-start;margin:16px 0 4px;font-size:14px;color:#cfe3f2;line-height:1.4}#fcaAuth .fca-tick input{width:20px;height:20px;flex:none;margin-top:1px;accent-color:#1ed6c8}#fcaAuth a{color:#5ff0e2}' +
    '#fcaAuth .fca-go{width:100%;margin-top:18px;border:0;border-radius:15px;padding:15px;font-size:16px;font-weight:800;color:#05283a;background:linear-gradient(90deg,#1ed6c8,#5fc4ff)}#fcaAuth .fca-go[disabled]{opacity:.6}' +
    '#fcaAuth .fca-msg{min-height:20px;margin-top:12px;font-size:14px;color:#ffd0d0}#fcaAuth .fca-forgot{display:block;margin:14px auto 0;border:0;background:transparent;color:#5ff0e2;font-size:15px;font-weight:700;text-decoration:underline;padding:6px}#fcaAuth .fca-note2{margin-top:22px;font-size:12.5px;color:#8fb0cf;line-height:1.5}';
  document.head.appendChild(authCss);

  // ---------------------------------------------------------------- brand: no "Skillvaya" anywhere on screen in this app
  function rebrand(node) {
    try {
      const w = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, { acceptNode: t => /Skillvaya/.test(t.nodeValue) && !(t.parentNode && (/^(SCRIPT|STYLE|TEXTAREA)$/.test(t.parentNode.nodeName) || (t.parentNode.closest && t.parentNode.closest('[data-keep-brand]')))) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
      const hits = []; while (w.nextNode()) hits.push(w.currentNode);
      hits.forEach(t => { t.nodeValue = t.nodeValue.replace(/Skillvaya/g, 'Future Chat'); });
      if (node.querySelectorAll) node.querySelectorAll('[aria-label*="Skillvaya"],[title*="Skillvaya"],[placeholder*="Skillvaya"]').forEach(e => ['aria-label', 'title', 'placeholder'].forEach(a => { const v = e.getAttribute(a); if (v && v.indexOf('Skillvaya') >= 0) e.setAttribute(a, v.replace(/Skillvaya/g, 'Future Chat')); }));
    } catch (_) {}
  }
  const brandObs = new MutationObserver(ms => { for (const m of ms) { if (m.type === 'characterData') { if (/Skillvaya/.test(m.target.nodeValue || '') && !(m.target.parentNode && m.target.parentNode.closest && m.target.parentNode.closest('[data-keep-brand]'))) m.target.nodeValue = m.target.nodeValue.replace(/Skillvaya/g, 'Future Chat'); } else m.addedNodes.forEach(n => { if (n.nodeType === 1) rebrand(n); else if (n.nodeType === 3 && /Skillvaya/.test(n.nodeValue) && !(n.parentNode && n.parentNode.closest && n.parentNode.closest('[data-keep-brand]'))) n.nodeValue = n.nodeValue.replace(/Skillvaya/g, 'Future Chat'); }); } });
  function watchBrand() { if (!document.body) return setTimeout(watchBrand, 30); rebrand(document.body); brandObs.observe(document.body, { childList: true, subtree: true, characterData: true }); }
  watchBrand();
  const _alert = window.alert, _confirm = window.confirm;
  window.alert = m => _alert.call(window, String(m == null ? '' : m).replace(/Skillvaya/g, 'Future Chat'));
  window.confirm = m => _confirm.call(window, String(m == null ? '' : m).replace(/Skillvaya/g, 'Future Chat'));
  const _title = Object.getOwnPropertyDescriptor(Document.prototype, 'title');
  try { Object.defineProperty(document, 'title', { get() { return _title.get.call(document); }, set(v) { _title.set.call(document, String(v).replace(/Skillvaya/g, 'Future Chat')); } }); } catch (_) {}

  (function typing() {
    const fix = () => { const t = document.getElementById('fcText'); if (!t || t.dataset.fct) return; t.dataset.fct = '1';
      t.setAttribute('autocorrect', 'on'); t.setAttribute('autocapitalize', 'sentences'); t.setAttribute('spellcheck', 'true'); t.setAttribute('autocomplete', 'on'); t.setAttribute('inputmode', 'text'); t.setAttribute('enterkeyhint', 'enter'); };
    new MutationObserver(fix).observe(document.documentElement, { childList: true, subtree: true }); fix();
  })();
  FCX.kit = { api, post, esc, $, toast, sheet, avatar, when, dueText, localInput, frame, push, pop, draw, go, row, bind, openPanel, X, FC, toggles, bindToggles, choiceRows, bindChoices, savePrefs, loadMe, itemForm, itemList, itemSheet, scrCirclePlans, scrTasks, scrCelebrations, confetti, redraw, SVG };

  // ---------------------------------------------------------------- start
  function boot() {
    if (!tok()) { showAuth('signin'); return; }
    build();
    try { history.replaceState({ fc: 'list' }, ''); } catch (_) {}
    const p = new URLSearchParams(location.search);
    if (!p.get('fc')) { try { window.FutureChat.open(); } catch (_) {} }
    loadMe();
    setTimeout(loadPeers, 800);
    if (p.get('fcx') === 'item' && p.get('id')) setTimeout(() => itemSheet(Number(p.get('id'))), 900);
    if (p.get('fcx') === 'bday') setTimeout(() => { go('you'); push(scrCelebrations); }, 900);
    if (p.get('fcx') === 'celeb' && p.get('id')) setTimeout(() => { const c = CELEB.find(x => x[0] === p.get('id')); if (c) cardSheet({ kind: 'holiday', celeb: c }); }, 1200);
    // keep Future Chat underneath the tabs at all times
    setInterval(() => {
      if (!tok() || document.getElementById('fcaAuth')) return;
      const r = document.getElementById('fcRoot');
      if (window.FutureChat && (!r || !r.classList.contains('open'))) { try { window.FutureChat.open(); } catch (_) {} }
      navBadge();
    }, 800);
    // online / last seen
    const ping = () => { if (document.visibilityState !== 'hidden') post('/api/fcx/ping').catch(() => {}); };
    ping(); setInterval(ping, 30000); document.addEventListener('visibilitychange', ping);
    setInterval(() => { if (document.visibilityState !== 'hidden') loadPeers(); }, 45000);
  }
  function whenReady() { if (window.FutureChat) boot(); else setTimeout(whenReady, 100); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', whenReady); else whenReady();
})();
