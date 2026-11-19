/* Future Chat inside Skillvaya. Replaces the old Messages screen. */
(function () {
  'use strict';
  const CM = window.FC_CHATMOJI || { cats: [], svg: {} };
  const QUICK = ['heart_pink', 'joy', 'like', 'shock', 'cry', 'popper'];
  const COLORS = ['#0b766e', '#7c3aed', '#1d4ed8', '#c2410c', '#0f766e', '#be185d', '#475569', '#0369a1', '#4d7c0f', '#9333ea'];
  const ICON = {
    back: '<svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M12 7v6M9 10h6"/></svg>',
    search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
    more: '<svg viewBox="0 0 24 24"><circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/></svg>',
    phone: '<svg viewBox="0 0 24 24"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/></svg>',
    video: '<svg viewBox="0 0 24 24"><rect x="2" y="6" width="14" height="12" rx="2"/><path d="m22 8-6 4 6 4z"/></svg>',
    smile: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8.5 14.5s1.3 2 3.5 2 3.5-2 3.5-2M9 9.5h.01M15 9.5h.01"/></svg>',
    clip: '<svg viewBox="0 0 24 24"><path d="M21.4 11.1 12.2 20.3a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/></svg>',
    cam: '<svg viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
    send: '<svg viewBox="0 0 24 24"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/></svg>',
    mic: '<svg viewBox="0 0 24 24"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4"/></svg>',
    stop: '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
    x: '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>'
  };
  const S = { open: false, list: [], filter: 'all', q: '', conv: null, msgs: [], lastId: 0, me: null, verified: false, reply: null,
    msgFilter: '', timer: null, fullTimer: null, media: new Map(), rec: null, archivedView: false };
  let root, bodyEl;

  // ---------- helpers
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = x => String(x == null ? '' : x).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const token = () => localStorage.getItem('skillvaya_token') || localStorage.getItem('sv_token') || sessionStorage.getItem('skillvaya_token') || sessionStorage.getItem('sv_token') || localStorage.getItem('skillvaya_owner_token') || '';
  async function api(path, body) {
    const t = token();
    const r = await fetch(path, { method: body ? 'POST' : 'GET', cache: 'no-store', credentials: 'same-origin',
      headers: Object.assign({ 'Content-Type': 'application/json' }, t ? { Authorization: 'Bearer ' + t } : {}), body: body ? JSON.stringify(body) : undefined });
    let d = {}; try { d = await r.json(); } catch (_) {}
    if (!r.ok) { const e = new Error(d.error || ('Request failed (' + r.status + ')')); e.data = d; e.status = r.status; throw e; }
    return d;
  }
  function toast(t) { const n = document.createElement('div'); n.className = 'fc-toast'; n.textContent = t; document.body.appendChild(n); setTimeout(() => n.remove(), 2600); }
  const color = s => { let h = 0; for (const ch of String(s)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return COLORS[h % COLORS.length]; };
  const initials = s => String(s || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0] || '').join('').toUpperCase() || '?';
  const cmSvg = n => CM.svg[n] || '';
  function rich(text) {
    return esc(text).replace(/:([a-z0-9_]+):/g, (m, n) => CM.svg[n] ? '<span class="fc-cm" title="' + n.replace(/_/g, ' ') + '">' + CM.svg[n] + '</span>' : m)
      .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline">$1</a>');
  }
  const onlyCm = t => { const s = String(t || '').trim(); const m = s.match(/:([a-z0-9_]+):/g) || []; return m.length > 0 && m.length <= 3 && m.every(x => CM.svg[x.slice(1, -1)]) && !s.replace(/:([a-z0-9_]+):/g, '').trim(); };
  function when(v) { const d = new Date(v); if (isNaN(d)) return ''; const n = new Date(); if (d.toDateString() === n.toDateString()) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const y = new Date(n); y.setDate(n.getDate() - 1); if (d.toDateString() === y.toDateString()) return 'Yesterday';
    return (n - d) < 6 * 864e5 ? d.toLocaleDateString([], { weekday: 'short' }) : d.toLocaleDateString([], { day: 'numeric', month: 'short' }); }
  const clock = v => { const d = new Date(v); return isNaN(d) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); };
  function dayLabel(v) { const d = new Date(v), n = new Date(); if (d.toDateString() === n.toDateString()) return 'Today'; const y = new Date(n); y.setDate(n.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return 'Yesterday'; return d.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' }); }
  const native = () => window.FutureChatNative || null;
  function sheet(html, onMount) {
    const dim = document.createElement('div'); dim.className = 'fc-dim';
    dim.innerHTML = '<div class="fc-sheet" role="dialog" aria-modal="true"><div class="fc-handle"></div>' + html + '</div>';
    dim.addEventListener('click', e => { if (e.target === dim) dim.remove(); });
    document.body.appendChild(dim); if (onMount) onMount(dim.firstChild, () => dim.remove()); return dim;
  }

  // ---------- shell
  function ensureRoot() {
    if (root) return;
    root = document.createElement('section'); root.id = 'fcRoot'; root.setAttribute('aria-label', 'Future Chat');
    document.body.appendChild(root);
    const nav = document.querySelector('.bottom-tabbar');
    const setNav = () => { const n = document.querySelector('.bottom-tabbar'); const vis = n && getComputedStyle(n).display !== 'none' && n.getBoundingClientRect().height > 0;
      let top = vis ? n.getBoundingClientRect().top : window.innerHeight;
      if (vis) { let t = Infinity; n.querySelectorAll('button,a').forEach(b => { const r = b.getBoundingClientRect(); if (r.height > 0 && r.top < t) t = r.top; }); if (t !== Infinity && t > top) top = t - 6; }   /*FC-NAVGAP-01*/
      const h = vis ? Math.max(0, Math.round(window.innerHeight - top)) : 0;
      document.documentElement.style.setProperty('--fc-nav', h + 'px'); if (root) root.classList.toggle('fc-on-nav', h > 0); };
    setNav(); window.addEventListener('resize', setNav); setTimeout(setNav, 600);
  }
  function setNavActive(on) {
    document.querySelectorAll('.bottom-tabbar button').forEach(b => b.classList.toggle('active', on && b.id === 'nav-messages'));
  }
  async function open(convId) {
    ensureRoot();
    if (!token()) { try { if (typeof window.view === 'function') window.view('settings'); } catch (_) {} toast('Sign in to use Future Chat'); return; }
    if (!S.open) { try { if (!(history.state && history.state.fc)) history.pushState({ fc: 'list' }, ''); } catch (_) {} }   // FCBACK-20261102: phone Back closes Future Chat
    S.open = true; const nv = document.querySelector('.bottom-tabbar'); if (nv) { nv.style.display = 'grid'; nv.style.zIndex = '5000'; } root.classList.add('open'); setNavActive(true); document.body.classList.add('fc-open'); window.dispatchEvent(new Event('resize'));
    if (convId) return openConv(Number(convId));
    renderList(true);
  }
  function close(fromBack) {
    if (!S.open) return;
    if (fromBack !== true) { try { if (history.state && history.state.fc) { S.unwind = true; history.back(); } } catch (_) {} }
    S.open = false; try { window.dispatchEvent(new CustomEvent('fc:view', { detail: { conv: 0, closed: true } })); } catch (_) {} stopTimers(); if (root) root.classList.remove('open'); document.body.classList.remove('fc-open'); S.conv = null;
  }
  window.addEventListener('popstate', () => {
    if (window.FCX && window.FCX.onBack && window.FCX.onBack()) return;
    if (S.unwind) { if (history.state && history.state.fc) { history.back(); return; } S.unwind = false; return; }
    if (!S.open) return;
    if (S.conv) { S.archivedView = false; renderList(true); if (!(history.state && history.state.fc)) try { history.pushState({ fc: 'list' }, ''); } catch (_) {} return; }
    close(true);
  });
  function stopTimers() { clearInterval(S.timer); clearInterval(S.fullTimer); S.timer = S.fullTimer = null; }

  // ---------- chat list
  async function renderList(load) {
    try { window.dispatchEvent(new CustomEvent('fc:view', { detail: { conv: 0 } })); } catch (_) {}
    stopTimers(); S.conv = null; S.reply = null;
    root.innerHTML = '<header class="fc-hdr"><div class="fc-hrow"><button class="fc-ib plain" id="fcClose" aria-label="Back" title="Back">' + ICON.back + '</button><div class="fc-logo" aria-hidden="true">' + cmSvg('bubble') + '</div><div class="fc-ttl"><b>Future Chat</b><small>Chats, calls and Chatmoji in Skillvaya</small></div>' +
      '<button class="fc-ib" id="fcNew" aria-label="New chat">' + ICON.plus + '</button></div>' +
      '<label class="fc-search">' + ICON.search.replace('<svg', '<svg width="18" height="18" stroke="#a9c8e7" fill="none" stroke-width="2"') + '<input id="fcQ" placeholder="Search chats, providers, groups" aria-label="Search chats" value="' + esc(S.q) + '"></label>' +
      '<div class="fc-chips" role="tablist">' + [['all', 'All'], ['unread', 'Unread'], ['contacts', 'Contacts'], ['business', 'Providers'], ['person', 'People'], ['group', 'Groups']].filter(x => !(window.SV_FC_APP && x[0] === 'business')).map(([k, l]) =>
        '<button class="fc-chip' + (S.filter === k ? ' on' : '') + '" data-f="' + k + '">' + l + '</button>').join('') + '</div></header>' +
      '<div class="fc-body" id="fcBody"><div class="fc-empty">Loading your chats…</div></div>';
    bodyEl = $('#fcBody', root);
    const fab = document.createElement('button'); fab.className = 'fc-fab'; fab.setAttribute('aria-label', 'Start a new chat'); fab.innerHTML = ICON.plus; fab.onclick = newChat; bodyEl.appendChild(fab);
    $('#fcNew', root).onclick = newChat;
    $('#fcClose', root).onclick = () => close();
    // FCAPP-01: in the stand-alone Future Chat app the top-left button opens Account & settings instead of leaving Future Chat.
    if (window.FCX && window.FCX.listHeader) { try { window.FCX.listHeader(root); } catch (_) {} }
    else if (window.SV_FC_APP) { const cb = $('#fcClose', root); cb.innerHTML = '<span style="display:inline-grid;width:26px;height:26px">' + cmSvg('smile') + '</span>'; cb.setAttribute('aria-label', 'Account and settings'); cb.title = 'Account and settings'; cb.onclick = () => { if (window.fcAppMenu) window.fcAppMenu(); }; const sm = root.querySelector('.fc-ttl small'); if (sm) sm.textContent = 'Chats, calls and Chatmoji'; }
    $('#fcQ', root).oninput = e => { S.q = e.target.value; drawList(); };
    root.querySelectorAll('.fc-chip').forEach(b => b.onclick = () => { S.filter = b.dataset.f; root.querySelectorAll('.fc-chip').forEach(x => x.classList.toggle('on', x === b)); drawList(); });
    if (load) await loadList(); else drawList();
    autoSyncContacts();
    S.timer = setInterval(async () => { if (!S.open || S.conv || document.visibilityState === 'hidden') return; try { const p = await api('/api/fc/pulse'); if (p.latest !== S.latestSeen) { S.latestSeen = p.latest; await loadList(); } } catch (_) {} }, 4000);
  }
  async function loadList() {
    try { const d = await api('/api/fc/conversations'); S.list = d.items || []; S.me = d.me; S.verified = !!(d.me && d.me.phone_verified); drawList(); updateBadge(); }
    catch (e) { if (bodyEl) bodyEl.innerHTML = '<div class="fc-empty"><b>Couldn\'t load chats</b>' + esc(e.message) + '</div>'; }
  }
  function drawList() {
    if (!bodyEl || S.conv) return;
    const fab = $('.fc-fab', bodyEl);
    if (S.filter === 'contacts') { drawContacts(fab); return; }
    const q = S.q.trim().toLowerCase();
    let items = S.list.filter(c => !!c.archived === S.archivedView);
    if (S.filter === 'unread') items = items.filter(c => c.unread > 0);
    else if (S.filter === 'business') items = items.filter(c => c.kind === 'business');
    else if (S.filter === 'person') items = items.filter(c => c.kind === 'direct');
    else if (S.filter === 'group') items = items.filter(c => c.kind === 'group');
    if (q) items = items.filter(c => (c.title + ' ' + (c.last ? c.last.text : '')).toLowerCase().includes(q));
    items.sort((a, b) => (b.pinned - a.pinned) || String(b.updated_at).localeCompare(String(a.updated_at)));
    let html = '';
    if (!S.verified && !S.archivedView) html += '<div class="fc-banner"><div style="flex:1"><b>Verify your number</b><br>Let friends and family find you on Future Chat and call you.</div><button id="fcVerifyBtn">Verify</button></div>';
    if (!S.archivedView && !contactsState().synced && !lsGet('fc_contacts_dismissed')) html += '<div class="fc-banner"><div style="flex:1"><b>Find your friends</b><br>See which of your phone contacts are on Future Chat.</div><button id="fcCtBtn">Allow</button><button id="fcCtNo" style="background:none;color:#a9c8e7;margin-left:4px" aria-label="Not now">✕</button></div>';
    if (S.archivedView) html += '<div class="fc-filterbar"><span>Archived chats</span><button id="fcArchBack">Back</button></div>';
    if (!items.length) html += '<div class="fc-empty">' + cmSvg('bubble').replace('<svg', '<svg width="56" height="56"') + '<b>' + (S.list.length ? 'No chats here' : 'Your conversations start here') + '</b>' +
      (S.list.length ? 'Try another filter.' : window.SV_FC_APP ? 'Tap the chat button to message a friend by phone number, or start a group.' : 'Tap the chat button to message a provider, a friend by phone number, or start a group.') + '</div>';
    for (const c of items) {
      const tag = window.SV_FC_APP ? (c.kind === 'group' ? '<span class="fc-tag">GROUP</span>' : '') : c.kind === 'business' && c.who === 'business' ? '<span class="fc-tag">PROVIDER ✓</span>' : c.kind === 'group' ? '<span class="fc-tag">GROUP</span>' : c.who === 'customer' ? '<span class="fc-tag">CUSTOMER</span>' : '';
      html += '<button class="fc-row" data-c="' + c.id + '"><div class="fc-av" style="background:' + color(c.title) + '">' + esc(initials(c.title)) + '</div><div class="fc-mid"><div class="fc-name"><span>' + esc(c.title) + '</span>' + tag + (c.pinned ? '<span title="Pinned">📌</span>' : '') + (c.muted ? '<span title="Muted">🔕</span>' : '') +
        '</div><div class="fc-last">' + (c.last ? (c.last.mine ? 'You: ' : '') + rich(c.last.text) : '<i>No messages yet</i>') + '</div></div><div class="fc-end"><span class="fc-time">' + esc(when(c.last ? c.last.at : c.updated_at)) + '</span>' +
        (c.unread ? '<span class="fc-badge">' + c.unread + '</span>' : '') + '</div></button>';
    }
    const arch = S.list.filter(c => c.archived).length;
    if (arch && !S.archivedView) html += '<button class="fc-link" id="fcArch">Archived chats (' + arch + ')</button>';
    html += '<div style="height:90px"></div>';
    bodyEl.innerHTML = html; if (fab) bodyEl.appendChild(fab);
    bodyEl.querySelectorAll('.fc-row').forEach(r => r.onclick = () => openConv(Number(r.dataset.c)));
    const vb = $('#fcVerifyBtn', bodyEl); if (vb) vb.onclick = () => verifyPhone(false);
    const cb = $('#fcCtBtn', bodyEl); if (cb) cb.onclick = () => askContacts();
    const cn = $('#fcCtNo', bodyEl); if (cn) cn.onclick = () => { lsSet('fc_contacts_dismissed', '1'); drawList(); };
    const ab = $('#fcArch', bodyEl); if (ab) ab.onclick = () => { S.archivedView = true; drawList(); };
    const bb = $('#fcArchBack', bodyEl); if (bb) bb.onclick = () => { S.archivedView = false; drawList(); };
    if (window.FCX && window.FCX.afterList) { try { window.FCX.afterList(bodyEl, items, S); } catch (_) {} }
  }
  function updateBadge() {
    const n = S.list.reduce((a, c) => a + (c.archived ? 0 : c.unread), 0);
    const btn = document.getElementById('nav-messages'); if (!btn) return;
    let b = btn.querySelector('.fc-navbadge');
    if (!b) { b = document.createElement('span'); b.className = 'fc-navbadge'; b.style.cssText = 'position:absolute;top:4px;right:calc(50% - 22px);min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:#e5484d;color:#fff;font-size:11px;font-weight:700;display:none;place-items:center;line-height:18px'; btn.style.position = 'relative'; btn.appendChild(b); }
    b.textContent = n > 99 ? '99+' : String(n); b.style.display = n ? 'grid' : 'none';
  }

  // ---------- phone contacts (SV91)
  function lsGet(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (_) {} }
  function contactsState() {
    if (!S.ct) { try { S.ct = JSON.parse(lsGet('fc_contacts_v1') || 'null'); } catch (_) { S.ct = null; } }
    return S.ct || { synced: 0, on: [], invite: [] };
  }
  async function matchContacts(list) {
    if (!list || !list.length) { toast('No phone numbers found in your contacts'); return; }
    try {
      const d = await api('/api/fc/contacts', { contacts: list.slice(0, 5000) });
      S.ct = { synced: Date.now(), on: d.on_future_chat || [], invite: d.invite || [] }; lsSet('fc_contacts_v1', JSON.stringify(S.ct));
      if (S.open && !S.conv) drawList();
      if (S.ctToast) { S.ctToast = false; toast(S.ct.on.length ? S.ct.on.length + (S.ct.on.length === 1 ? ' contact is' : ' contacts are') + ' on Future Chat' : 'None of your contacts are on Future Chat yet — invite them!'); }
    } catch (e) { toast(e.message); }
  }
  window.fcContacts = json => { let list = []; try { list = JSON.parse(json || '[]'); } catch (_) {} matchContacts(list); };
  window.fcContactsDenied = () => { toast('Contacts permission was not given. You can still add people by phone number.'); };
  function contactsPermission() { const n = native(); try { return n && n.contactsPermission ? String(n.contactsPermission()) : ''; } catch (_) { return ''; } }
  function autoSyncContacts() {
    const st = contactsState();
    if (contactsPermission() === 'granted' && Date.now() - (st.synced || 0) > 6 * 3600e3) { try { native().readContacts(); } catch (_) {} }
  }
  function askContacts() {
    const n = native(), webPicker = 'contacts' in navigator && navigator.contacts && navigator.contacts.select;
    if (n && n.readContacts && contactsPermission() === 'granted') { S.ctToast = true; n.readContacts(); return; }
    if (!(n && n.readContacts) && !webPicker) { toast('Update the Skillvaya app to find friends from your contacts. You can still add people by phone number.'); return; }
    sheet('<h3>Find friends from your contacts</h3><p>Skillvaya will read the <b>names and phone numbers</b> in your contacts and send the numbers securely to our server <b>only to check which of them use Future Chat</b>. Numbers that aren\'t on Future Chat are not saved, sold or shared, and nobody is contacted unless you choose to invite them.</p><p style="font-size:12px;color:#55667d">You can turn this off anytime in your phone\'s app settings. See the Privacy Policy for details.</p><div class="fc-acts"><button class="fc-btn" id="fcCtAllow">Allow and find friends</button><button class="fc-act" id="fcCtLater"><i>⏭️</i>Not now</button></div>', (el, done) => {
      $('#fcCtLater', el).onclick = () => { lsSet('fc_contacts_dismissed', '1'); done(); drawList(); };
      $('#fcCtAllow', el).onclick = async () => {
        done(); S.ctToast = true;
        if (n && n.readContacts) { n.readContacts(); return; }
        try { const picked = await navigator.contacts.select(['name', 'tel'], { multiple: true }); const list = []; (picked || []).forEach(p => (p.tel || []).forEach(t => list.push({ name: (p.name || [])[0] || '', phone: t }))); if (list.length) matchContacts(list); else oldPickerHelp(); }
        catch (_) { oldPickerHelp(); }
      };
    });
  }
  // Older app versions only have the phone's own contact picker, which picks contacts one at a time.
  function oldPickerHelp() {
    sheet('<h3>Load all your contacts at once</h3><p>This version of Skillvaya can only pick contacts one at a time. The latest Skillvaya app loads <b>all</b> your contacts with one tap on <b>Allow</b> and shows everyone who is on Future Chat.</p><a class="fc-btn" style="display:block;text-align:center;text-decoration:none" href="https://play.google.com/store/apps/details?id=za.co.skillvaya.app">Update Skillvaya</a><button class="fc-btn sec" id="fcPickAgain">Pick contacts one by one for now</button>', (el, done) => {
      $('#fcPickAgain', el).onclick = async () => { done(); try { const picked = await navigator.contacts.select(['name', 'tel'], { multiple: true }); const list = []; (picked || []).forEach(p => (p.tel || []).forEach(t => list.push({ name: (p.name || [])[0] || '', phone: t }))); if (list.length) { S.ctToast = true; matchContacts(list); } } catch (_) {} };
    });
  }
  function drawContacts(fab) {
    const st = contactsState(), q = S.q.trim().toLowerCase();
    const match = x => !q || ((x.contact_name || x.name || '') + ' ' + x.phone).toLowerCase().includes(q);
    let html = '';
    if (!st.synced) html += '<div class="fc-empty">' + cmSvg('bubble').replace('<svg', '<svg width="56" height="56"') + '<b>See who\'s on Future Chat</b>Allow contacts to find friends and family who already use Skillvaya.<br><br><button class="fc-btn" id="fcCtBtn2">Find friends</button></div>';
    else {
      const on = st.on.filter(match), inv = st.invite.filter(match);
      html += '<div class="fc-filterbar"><span>' + st.on.length + ' on Future Chat</span><button id="fcCtRe">Refresh</button></div>';
      for (const p of on) html += '<button class="fc-row" data-u="' + p.id + '"><div class="fc-av" style="background:' + color(p.contact_name || p.name) + '">' + esc(initials(p.contact_name || p.name)) + '</div><div class="fc-mid"><div class="fc-name"><span>' + esc(p.contact_name || p.name) + '</span></div><div class="fc-last">' + esc(p.phone) + ' · on Future Chat</div></div><div class="fc-end"><span class="fc-time">💬</span></div></button>';
      if (inv.length) html += '<div class="fc-filterbar"><span>Invite to Future Chat</span></div>';
      for (const p of inv.slice(0, 150)) html += '<div class="fc-row" style="cursor:default"><div class="fc-av" style="background:#33415a">' + esc(initials(p.name || '#')) + '</div><div class="fc-mid"><div class="fc-name"><span>' + esc(p.name || p.phone) + '</span></div><div class="fc-last">' + esc(p.phone) + '</div></div><div class="fc-end"><button class="fc-chip" data-inv="' + esc(p.phone) + '">Invite</button></div></div>';
      if (!on.length && !inv.length) html += '<div class="fc-empty"><b>No matches</b>Try another search.</div>';
    }
    html += '<div style="height:90px"></div>';
    bodyEl.innerHTML = html; if (fab) bodyEl.appendChild(fab);
    bodyEl.querySelectorAll('[data-u]').forEach(b => b.onclick = () => start({ user_id: Number(b.dataset.u) }));
    bodyEl.querySelectorAll('[data-inv]').forEach(b => b.onclick = () => invite(b.dataset.inv));
    const f = $('#fcCtBtn2', bodyEl); if (f) f.onclick = () => askContacts();
    const r = $('#fcCtRe', bodyEl); if (r) r.onclick = () => askContacts();
  }

  // ---------- new chat
  function newChat() {
    sheet('<h3>New chat</h3><p>' + (window.SV_FC_APP ? 'Message anyone on Future Chat by their phone number.' : 'Message anyone on Skillvaya by phone number, or find a service provider.') + '</p>' +
      '<input id="fcNQ" type="text" inputmode="text" placeholder="' + (window.SV_FC_APP ? 'Phone number' : 'Phone number or business name') + '" autocomplete="off"><div id="fcNRes"></div>' +
      '<div class="fc-acts" style="margin-top:6px"><button class="fc-act" id="fcNGroup"><i>👥</i>New group</button><button class="fc-act" id="fcNInvite"><i>✉️</i>Invite friends to Future Chat</button></div>', (el, done) => {
      const inp = $('#fcNQ', el), res = $('#fcNRes', el); let t;
      const showContacts = () => { const st = contactsState(); if (!st.synced) { res.innerHTML = '<button class="fc-act" id="fcNCt"><i>📇</i>Find friends from your contacts</button>'; $('#fcNCt', el).onclick = () => { done(); askContacts(); }; return; }
        res.innerHTML = st.on.length ? '<p style="margin:8px 0 4px;font-size:12px;color:#55667d">CONTACTS ON FUTURE CHAT</p>' + st.on.slice(0, 40).map(p => '<button class="fc-act" data-u="' + p.id + '"><i>💬</i>' + esc(p.contact_name || p.name) + '<small style="color:#55667d;margin-left:auto">' + esc(p.phone) + '</small></button>').join('') : '<p>None of your contacts are on Future Chat yet — invite them below.</p>';
        res.querySelectorAll('[data-u]').forEach(b => b.onclick = () => start({ user_id: Number(b.dataset.u) }, done)); };
      showContacts();
      inp.focus();
      inp.oninput = () => { clearTimeout(t); t = setTimeout(async () => {
        const q = inp.value.trim(); if (q.length < 2) { showContacts(); return; }
        try {
          const d = await api('/api/fc/search-people?q=' + encodeURIComponent(q)); let h = '';
          for (const p of d.people || []) h += '<button class="fc-act" data-u="' + p.id + '"><i>💬</i>' + esc(p.name) + '<small style="color:#55667d;margin-left:auto">' + esc(d.phone) + '</small></button>';
          for (const b of d.businesses || []) h += '<button class="fc-act" data-b="' + b.business_id + '"><i>✦</i><span>' + esc(b.name) + '<br><small style="color:#55667d">' + esc(b.category) + ' · ' + esc(b.area) + '</small></span></button>';
          if (d.phone && !(d.people || []).length) h += '<p>' + esc(d.phone) + ' isn\'t on Future Chat yet.</p><button class="fc-btn" data-inv="' + esc(d.phone) + '">Invite them</button>';
          if (!h) h = '<p>No matches yet.</p>';
          res.innerHTML = h;
          res.querySelectorAll('[data-u]').forEach(b => b.onclick = () => start({ user_id: Number(b.dataset.u) }, done));
          res.querySelectorAll('[data-b]').forEach(b => b.onclick = () => start({ business_id: Number(b.dataset.b) }, done));
          res.querySelectorAll('[data-inv]').forEach(b => b.onclick = () => invite(b.dataset.inv));
        } catch (e) { res.innerHTML = '<p>' + esc(e.message) + '</p>'; }
      }, 350); };
      $('#fcNGroup', el).onclick = () => { done(); newGroup(); };
      $('#fcNInvite', el).onclick = () => invite('');
    });
  }
  async function start(body, done) {
    try { const d = await api('/api/fc/start', body); if (done) done(); openConv(d.conversation_id); }
    catch (e) { if (e.data && e.data.verify_required) { if (done) done(); verifyPhone(false); } else toast(e.message); }
  }
  function invite(phone) {
    if (window.FCX && window.FCX.invite) return window.FCX.invite(phone);   // FCG-01: personal link + giveaway ticket
    const text = 'Join me on Future Chat in Skillvaya — free chats, calls, Chatmoji and Lenses: https://skillvaya.onrender.com/download';
    if (phone) { location.href = 'sms:' + phone + '?body=' + encodeURIComponent(text); return; }
    if (navigator.share) navigator.share({ title: 'Future Chat', text }).catch(() => {});
    else { navigator.clipboard && navigator.clipboard.writeText(text); toast('Invite link copied'); }
  }
  function newGroup() {
    sheet('<h3>New group</h3><p>Give it a name and add people by phone number (one per line). People who aren\'t on Future Chat yet can be invited later.</p><input id="fcGT" maxlength="60" placeholder="Group name"><textarea id="fcGP" rows="4" placeholder="Phone numbers"></textarea><button class="fc-btn" id="fcGGo">Create group</button>', (el, done) => {
      $('#fcGGo', el).onclick = async () => {
        const title = $('#fcGT', el).value.trim(); if (!title) { toast('Give the group a name'); return; }
        const phones = $('#fcGP', el).value.split(/[\n,;]+/).map(x => x.trim()).filter(Boolean);
        try { const d = await api('/api/fc/start', { group_title: title, phones }); done(); toast(d.added ? 'Group created with ' + d.added + ' ' + (d.added === 1 ? 'person' : 'people') : 'Group created'); openConv(d.conversation_id); }
        catch (e) { if (e.data && e.data.verify_required) { done(); verifyPhone(false); } else toast(e.message); }
      };
    });
  }

  // ---------- conversation
  async function openConv(id) {
    try { window.dispatchEvent(new CustomEvent('fc:view', { detail: { conv: id } })); } catch (_) {}
    stopTimers(); S.conv = { id, title: '…', kind: '' }; S.msgs = []; S.lastId = 0; S.reply = null; S.msgFilter = '';
    root.innerHTML = '<header class="fc-hdr fc-conv-hdr"><button class="fc-ib plain" id="fcBack" aria-label="Back to chats">' + ICON.back + '</button><div class="fc-av sm" id="fcAv"></div><div class="fc-ttl" style="padding-left:6px"><b id="fcTitle" style="font-size:16px">Loading…</b><small id="fcSub"></small></div>' +
      '<button class="fc-ib plain" id="fcVoice" aria-label="Voice call">' + ICON.phone + '</button><button class="fc-ib plain" id="fcVideo" aria-label="Video call">' + ICON.video + '</button><button class="fc-ib plain" id="fcMore" aria-label="Chat options">' + ICON.more + '</button></header>' +
      '<div id="fcFilter"></div><div class="fc-msgs" id="fcMsgs" aria-live="polite"></div>' +
      '<div class="fc-composer"><div id="fcReply"></div><div class="fc-cbar"><div class="fc-pill"><button class="fc-ib" id="fcEmoji" aria-label="Chatmoji">' + ICON.smile + '</button>' +
      '<textarea id="fcText" rows="1" placeholder="Message" aria-label="Message"></textarea><button class="fc-ib" id="fcAttach" aria-label="Attach">' + ICON.clip + '</button><button class="fc-ib" id="fcCam" aria-label="Camera">' + ICON.cam + '</button></div>' +
      '<button class="fc-send" id="fcSend" aria-label="Record voice note">' + ICON.mic + '</button></div></div>';
    try { if (!(history.state && history.state.fc === 'conv')) history.pushState({ fc: 'conv' }, ''); } catch (_) {}
    $('#fcBack', root).onclick = () => { if (history.state && history.state.fc === 'conv') history.back(); else { S.archivedView = false; renderList(true); } };
    const ta = $('#fcText', root), sendBtn = $('#fcSend', root);
    const sync = () => { ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px'; const has = !!ta.value.trim(); sendBtn.innerHTML = has ? ICON.send : (S.rec ? ICON.stop : ICON.mic); sendBtn.setAttribute('aria-label', has ? 'Send' : (S.rec ? 'Stop and send voice note' : 'Record voice note')); };
    ta.oninput = sync;
    if (S.pendingShare) { ta.value = S.pendingShare; S.pendingShare = ''; setTimeout(() => { try { sync(); ta.focus(); } catch (_) {} }, 0); toast('Choose Send to share it'); }
    ta.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && window.matchMedia('(pointer:fine)').matches) { e.preventDefault(); sendText(); } };
    sendBtn.onclick = () => { if (ta.value.trim()) sendText(); else voiceNote(sync); };
    $('#fcEmoji', root).onclick = () => picker(name => { insertAt(ta, ':' + name + ': '); sync(); });
    $('#fcAttach', root).onclick = attachSheet;
    $('#fcCam', root).onclick = camera;
    $('#fcMore', root).onclick = convMenu;
    $('#fcVoice', root).onclick = () => call('voice');
    $('#fcVideo', root).onclick = () => call('video');
    await loadMsgs(true);
    S.timer = setInterval(() => { if (document.visibilityState !== 'hidden') loadMsgs(false); }, 2500);
    S.fullTimer = setInterval(() => { if (document.visibilityState !== 'hidden') loadMsgs(true, true); }, 15000);
  }
  function insertAt(ta, text) { const s = ta.selectionStart ?? ta.value.length, e = ta.selectionEnd ?? s; ta.value = ta.value.slice(0, s) + text + ta.value.slice(e); ta.selectionStart = ta.selectionEnd = s + text.length; ta.focus(); }
  async function loadMsgs(full, quiet) {
    if (!S.conv) return; const id = S.conv.id;
    try {
      const d = await api('/api/fc/messages?c=' + id + (full ? '' : '&after=' + S.lastId));
      if (!S.conv || S.conv.id !== id) return;
      S.conv = Object.assign(S.conv, d.conversation);
      const items = d.items || [];
      if (full) S.msgs = items; else if (items.length) S.msgs = S.msgs.concat(items.filter(m => !S.msgs.some(x => x.id === m.id)));
      else if (!quiet) return;
      if (!full && !items.length) return;
      const newest = S.msgs.length ? S.msgs[S.msgs.length - 1].id : 0;
      const grew = newest > S.lastId; S.lastId = newest;
      drawHeader(); drawMsgs(full && !quiet ? 'bottom' : (grew ? 'bottom-if-near' : 'keep'));
      if (grew) api('/api/fc/read', { c: id, last: newest }).catch(() => {});
    } catch (e) { if (!quiet) toast(e.message); }
  }
  function drawHeader() {
    const c = S.conv; $('#fcTitle', root).textContent = c.title; const av = $('#fcAv', root); av.textContent = initials(c.title); av.style.background = color(c.title);
    $('#fcSub', root).textContent = c.kind === 'group' ? (c.members || []).map(m => m.name).slice(0, 5).join(', ') : window.SV_FC_APP ? 'Future Chat' : c.who === 'business' ? 'Service provider · Skillvaya' : c.who === 'customer' ? 'Your customer' : 'Future Chat';
    if (window.FCX && window.FCX.afterHeader) { try { window.FCX.afterHeader(root, c); } catch (_) {} }
  }
  function bubble(m, prev) {
    if (m.kind === 'system') return '<div class="fc-sys">' + rich(m.body) + '</div>';
    if (m.kind === 'stokvel') return '<div class="fc-sys" style="cursor:pointer" onclick="window.FutureChat&&window.FutureChat.stokvel()">💰 ' + esc(m.body) + ' · ' + esc(clock(m.created_at)) + '</div>';
    if (m.kind === 'call') return '<div class="fc-sys">' + (/missed/i.test(m.body) ? '📵 ' : '📞 ') + esc((m.mine ? 'You · ' : '') + (m.body || 'Call')) + ' · ' + esc(clock(m.created_at)) + '</div>';
    const big = !m.deleted && m.kind === 'text' && !m.reply && onlyCm(m.body);
    const showName = S.conv.kind === 'group' && !m.mine && (!prev || prev.sender_id !== m.sender_id || prev.kind === 'system');
    const sender = (S.conv.members || []).find(x => x.id === m.sender_id);
    let inner = '';
    if (showName) inner += '<div class="fc-sender">' + esc(sender ? sender.name : 'Member') + '</div>';
    if (m.reply) inner += '<span class="fc-quote"><b>' + (m.reply.sender_id === (S.me && S.me.id) ? 'You' : esc(((S.conv.members || []).find(x => x.id === m.reply.sender_id) || {}).name || 'Reply')) + '</b>' + rich(m.reply.text) + '</span>';
    if (m.deleted) inner += '<i style="opacity:.75">🚫 This message was deleted</i>';
    else {
      for (const a of m.attachments || []) {
        if (/^image\//.test(a.mime_type)) inner += '<img class="fc-img" data-att="' + a.id + '" alt="' + esc(a.filename) + '">';
        else if (/^video\//.test(a.mime_type)) inner += '<video class="fc-img" data-att="' + a.id + '" controls playsinline preload="metadata"></video>';
        else if (/^audio\//.test(a.mime_type)) inner += '<div class="fc-voice">🎤<audio data-att="' + a.id + '" controls preload="none"></audio></div>';
        else inner += '<a class="fc-file" href="#" data-dl="' + a.id + '" data-name="' + esc(a.filename) + '"><i>' + esc((a.filename.split('.').pop() || 'FILE').slice(0, 4).toUpperCase()) + '</i><span>' + esc(a.filename) + '<br><small>' + Math.max(1, Math.round(a.size / 1024)) + ' KB</small></span></a>';
      }
      if (m.kind === 'location' && m.meta && m.meta.lat != null) inner += '<div class="fc-card"><span class="k">📍 LOCATION</span><b>' + esc(m.meta.label || 'Shared location') + '</b><a class="pri" target="_blank" rel="noopener" href="https://maps.google.com/?q=' + Number(m.meta.lat) + ',' + Number(m.meta.lng) + '">Open in Maps</a></div>';
      if (m.kind === 'contact' && m.meta) inner += '<div class="fc-card"><span class="k">👤 CONTACT</span><b>' + esc(m.meta.name) + '</b><span>' + esc(m.meta.phone) + '</span><a class="pri" href="tel:' + esc(m.meta.phone) + '">Call</a><button class="sec" data-chatphone="' + esc(m.meta.phone) + '">Message on Future Chat</button></div>';
      if (m.kind === 'quote' && m.meta && Array.isArray(m.meta.lines)) {
        const tot = m.meta.lines.reduce((s, l) => s + Number(l.amount || 0), 0);
        inner += '<div class="fc-card"><span class="k">🧾 QUOTE</span><b>' + esc(m.meta.title || 'Quote') + '</b>' + m.meta.lines.map(l => '<div class="ln"><span>' + esc(l.label) + '</span><span>R' + Number(l.amount || 0).toLocaleString('en-ZA') + '</span></div>').join('') +
          '<div class="tot"><span>Total</span><span>R' + tot.toLocaleString('en-ZA') + '</span></div>' + (m.meta.valid ? '<small style="color:#55667d">Valid ' + esc(m.meta.valid) + '</small>' : '') +
          (!m.mine ? '<button class="pri" data-acceptq="' + m.id + '">Accept quote</button>' : '') + '</div>';
      }
      if (m.meta && m.meta.fwd) inner = '<div style="font-size:11.5px;font-style:italic;color:#8fa9bd;margin-bottom:3px">↪ ' + (Number(m.meta.fwd) > 5 ? 'Forwarded many times' : 'Forwarded') + '</div>' + inner;   // FCA-01
      const sp = m.meta && window.FCX && window.FCX.special ? (function () { try { return window.FCX.special(m); } catch (_) { return ''; } })() : '';
      if (sp) inner += sp;
      else if (m.meta && m.meta.card && window.FCX && window.FCX.greet) inner += window.FCX.greet(m);
      else if (m.meta && m.meta.fcx && window.FCX && window.FCX.card) inner += window.FCX.card(m);
      else if (m.body) inner += (inner ? '<div style="margin-top:4px">' : '<div>') + rich(m.body) + '</div>';
    }
    const ticks = m.mine ? '<span class="fc-tick' + (m.read ? ' read' : '') + '" aria-label="' + (m.read ? 'Read' : 'Sent') + '">' + (m.read ? '✓✓' : '✓') + '</span>' : '';
    inner += '<div class="fc-meta">' + (m.starred ? '<span class="fc-star">★</span>' : '') + (m.edited && !m.deleted ? 'Edited · ' : '') + clock(m.created_at) + ticks + '</div>';
    const counts = {}; (m.reactions || []).forEach(r => counts[r.emoji] = (counts[r.emoji] || 0) + 1);
    const reacts = Object.keys(counts).length ? '<button class="fc-react" data-react="' + m.id + '">' + Object.entries(counts).map(([e, n]) => (CM.svg[e.slice(1, -1)] || '') + (n > 1 ? n : '')).join('') + '</button>' : '';
    return '<div class="fc-m ' + (m.mine ? 'mine' : 'theirs') + (big ? ' big' : '') + '" data-m="' + m.id + '"><div class="fc-b">' + inner + '</div>' + reacts + '</div>';
  }
  function drawMsgs(scroll) {
    const box = $('#fcMsgs', root); if (!box) return;
    const near = box.scrollHeight - box.scrollTop - box.clientHeight < 140, keepTop = box.scrollTop;
    const f = S.msgFilter.toLowerCase();
    let list = S.msgs;
    if (f === '★') list = list.filter(m => m.starred); else if (f) list = list.filter(m => (m.body || '').toLowerCase().includes(f));
    const fb = $('#fcFilter', root);
    fb.innerHTML = S.msgFilter ? '<div class="fc-filterbar"><span>' + (f === '★' ? '★ Starred messages' : 'Results for “' + esc(S.msgFilter) + '”') + ' · ' + list.length + '</span><button id="fcClearF">Clear</button></div>' : '';
    if (S.msgFilter) $('#fcClearF', root).onclick = () => { S.msgFilter = ''; drawMsgs('bottom'); };
    let html = '', lastDay = '', prev = null;
    if (!S.msgs.length) html = '<div class="fc-empty">' + cmSvg('smile').replace('<svg', '<svg width="56" height="56"') + '<b>Say hello</b>Send the first message, a Chatmoji, a photo or a voice note.</div>';
    for (const m of list) { const dl = dayLabel(m.created_at); if (dl !== lastDay) { html += '<div class="fc-day">' + esc(dl) + '</div>'; lastDay = dl; prev = null; } html += bubble(m, prev); prev = m; }
    box.innerHTML = html;
    box.querySelectorAll('.fc-m').forEach(el => bindHold(el, () => msgMenu(Number(el.dataset.m))));
    box.querySelectorAll('[data-react]').forEach(b => b.onclick = e => { e.stopPropagation(); reactInfo(Number(b.dataset.react)); });
    box.querySelectorAll('[data-att]').forEach(el => loadMedia(el));
    box.querySelectorAll('[data-dl]').forEach(a => a.onclick = e => { e.preventDefault(); download(Number(a.dataset.dl), a.dataset.name); });
    box.querySelectorAll('[data-chatphone]').forEach(b => b.onclick = () => start({ phone: b.dataset.chatphone }));
    box.querySelectorAll('[data-acceptq]').forEach(b => b.onclick = () => sendRaw({ c: S.conv.id, body: '✅ I accept this quote. Let\'s book it.', kind: 'text', reply_to: Number(b.dataset.acceptq) }));
    if (scroll === 'bottom' || (scroll === 'bottom-if-near' && near)) box.scrollTop = box.scrollHeight; else box.scrollTop = keepTop;
  }
  function bindHold(el, fn) {
    let t; el.addEventListener('contextmenu', e => { e.preventDefault(); fn(); });
    el.addEventListener('touchstart', () => { t = setTimeout(() => { t = null; if (navigator.vibrate) navigator.vibrate(15); fn(); }, 450); }, { passive: true });
    ['touchend', 'touchmove', 'touchcancel'].forEach(ev => el.addEventListener(ev, () => clearTimeout(t), { passive: true }));
  }
  // Photos, videos and files live on the phone (IndexedDB); the server only passes them along.
  let dbP = null;
  function mediaDb() {
    if (dbP) return dbP;
    dbP = new Promise(res => { try { const r = indexedDB.open('futurechat_media', 1); r.onupgradeneeded = () => r.result.createObjectStore('files'); r.onsuccess = () => res(r.result); r.onerror = () => res(null); } catch (_) { res(null); } });
    return dbP;
  }
  async function localGet(id) { const db = await mediaDb(); if (!db) return null; return new Promise(res => { try { const q = db.transaction('files').objectStore('files').get(id); q.onsuccess = () => res(q.result || null); q.onerror = () => res(null); } catch (_) { res(null); } }); }
  async function localPut(id, blob) { const db = await mediaDb(); if (!db) return; try { db.transaction('files', 'readwrite').objectStore('files').put(blob, id); } catch (_) {} }
  async function blobFor(id) {
    if (S.media.has(id)) return S.media.get(id);
    const p = (async () => {
      const kept = await localGet(id); if (kept) return URL.createObjectURL(kept);
      const r = await fetch('/api/fc/file/' + id, { headers: { Authorization: 'Bearer ' + token() }, credentials: 'same-origin' });
      if (r.status === 410) { const e = new Error('Saved on the phones it was sent to'); e.purged = true; throw e; }
      if (!r.ok) throw new Error('File unavailable');
      const b = await r.blob(); localPut(id, b); return URL.createObjectURL(b);
    })();
    S.media.set(id, p); p.catch(() => S.media.delete(id)); return p;
  }
  async function loadMedia(el) {
    try { const u = await blobFor(Number(el.dataset.att)); el.src = u; if (el.tagName === 'IMG') el.onclick = () => viewImage(u); }
    catch (e) { const n = document.createElement('div'); n.className = 'fc-file'; n.innerHTML = '<i>' + (el.tagName === 'VIDEO' ? '🎬' : el.tagName === 'AUDIO' ? '🎤' : '📷') + '</i><span>' + esc(e.purged ? 'No longer on this phone' : 'Couldn\'t load') + '<br><small>' + esc(e.purged ? 'Media is kept on the phones it was sent to' : 'Check your connection') + '</small></span>'; (el.closest('.fc-voice') || el).replaceWith(n); }
  }
  async function download(id, name) { try { const u = await blobFor(id); const a = document.createElement('a'); a.href = u; a.download = name || 'file'; document.body.appendChild(a); a.click(); a.remove(); } catch (e) { toast(e.message); } }
  function viewImage(u) { const d = sheet('<img src="' + u + '" style="width:100%;border-radius:14px" alt="Photo"><button class="fc-btn sec" id="fcImgClose">Close</button>', (el, done) => { $('#fcImgClose', el).onclick = done; }); return d; }

  // ---------- sending
  async function sendRaw(body) {
    try { const d = await api('/api/fc/send', body); S.reply = null; drawReply(); await loadMsgs(false); return d; }
    catch (e) { toast(e.message); throw e; }
  }
  async function sendText() {
    const ta = $('#fcText', root); const body = ta.value.trim(); if (!body) return;
    ta.value = ''; ta.dispatchEvent(new Event('input'));
    const reply = S.reply ? S.reply.id : 0;
    try { await sendRaw({ c: S.conv.id, body, kind: 'text', reply_to: reply }); } catch (_) { ta.value = body; ta.dispatchEvent(new Event('input')); }
  }
  function drawReply() {
    const el = $('#fcReply', root); if (!el) return;
    if (!S.reply) { el.innerHTML = ''; return; }
    el.innerHTML = '<div class="fc-replybar"><div><b>Replying to ' + (S.reply.mine ? 'yourself' : esc(S.reply.name || '')) + '</b>' + rich(S.reply.text) + '</div><button class="fc-ib" style="background:transparent;color:#55667d" id="fcRX" aria-label="Cancel reply">' + ICON.x + '</button></div>';
    $('#fcRX', el).onclick = () => { S.reply = null; drawReply(); };
  }
  const toB64 = blob => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] || ''); r.onerror = rej; r.readAsDataURL(blob); });
  async function shrink(file) {
    const ds = !!(window.FCX && window.FCX.dataSaver && window.FCX.dataSaver());
    if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size < (ds ? 150 : 350) * 1024) return file;
    try {
      const bmp = await createImageBitmap(file); const k = Math.min(1, (ds ? 1280 : 1600) / Math.max(bmp.width, bmp.height));
      const cv = document.createElement('canvas'); cv.width = Math.round(bmp.width * k); cv.height = Math.round(bmp.height * k); cv.getContext('2d').drawImage(bmp, 0, 0, cv.width, cv.height);
      const out = await new Promise(r => cv.toBlob(r, 'image/jpeg', ds ? 0.7 : 0.82)); if (!out || out.size >= file.size) return file;
      if (ds && window.FCX.savedBytes) window.FCX.savedBytes(file.size - out.size);
      return new File([out], file.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' });
    } catch (_) { return file; }
  }
  async function sendFiles(files, caption) {
    for (let f of files) {
      f = await shrink(f);
      const kind = /^image\//.test(f.type) ? 'photo' : /^video\//.test(f.type) ? 'video' : /^audio\//.test(f.type) ? 'voice' : 'file';
      if (f.size > 15 * 1024 * 1024) {   // FCP-01: big files go in pieces (up to 48 MB with Future Chat Plus)
        if (window.FCX && window.FCX.bigSend) { const d = await window.FCX.bigSend(f, kind, caption, S.conv.id); if (d) { caption = ''; if (d.attachments && d.attachments[0]) { localPut(d.attachments[0], f); S.media.delete(d.attachments[0]); } await loadMsgs(false); } continue; }
        toast(f.name + ' is bigger than 16 MB'); continue;
      }
      toast('Sending ' + (kind === 'file' ? f.name : kind) + '…');
      try { const d = await sendRaw({ c: S.conv.id, kind, body: caption || '', reply_to: S.reply ? S.reply.id : 0, files: [{ filename: f.name, mime_type: f.type || 'application/octet-stream', data_base64: await toB64(f) }] }); caption = ''; if (d && d.attachments && d.attachments[0]) { localPut(d.attachments[0], f); S.media.delete(d.attachments[0]); } } catch (_) {}
    }
  }
  function pickFiles(accept, capture, multiple) {
    const i = document.createElement('input'); i.type = 'file'; i.accept = accept; if (capture) i.setAttribute('capture', capture); if (multiple) i.multiple = true;
    i.onchange = () => { if (i.files && i.files.length) sendFiles(Array.from(i.files)); }; i.click();
  }
  function camera() {
    const n = native();
    if (n && n.openLens) { window.fcLensResult = async (b64, mime) => { if (!b64) return; const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0)); sendFiles([new File([bin], 'FutureChat_Lens.jpg', { type: mime || 'image/jpeg' })]); }; n.openLens(); return; }
    pickFiles('image/*', 'environment');
  }
  async function voiceNote(sync) {
    if (S.rec) { S.rec.stop(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) { toast('Voice notes need microphone access'); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const type = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : (MediaRecorder.isTypeSupported('audio/mp4') ? 'audio/mp4' : '');
      const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined); const chunks = []; const startT = Date.now();
      rec.ondataavailable = e => e.data.size && chunks.push(e.data);
      const ui = recBar(stream, startT, () => { ui.cancelled = true; try { rec.stop(); } catch (_) {} });
      rec.onstop = async () => { stream.getTracks().forEach(t => t.stop()); S.rec = null; ui.close(); const btn = $('#fcSend', root); if (btn) btn.classList.remove('rec'); sync && sync();
        if (ui.cancelled) { toast('Voice note deleted'); return; }
        if (Date.now() - startT < 800) { toast('Hold on a little longer to record'); return; }
        const mime = (rec.mimeType || 'audio/webm').split(';')[0]; const blob = new Blob(chunks, { type: mime });
        await sendFiles([new File([blob], 'Voice note.' + (mime.includes('mp4') ? 'm4a' : 'webm'), { type: mime })]); };
      rec.start(); S.rec = rec; const btn = $('#fcSend', root); btn.classList.add('rec'); sync && sync(); toast('Recording… tap again to send');
      setTimeout(() => { if (S.rec === rec) rec.stop(); }, 5 * 60 * 1000);
    } catch (e) { toast('Microphone permission is needed for voice notes'); }
  }
  // Live recording bar: red dot, timer, moving sound wave from the microphone, bin to cancel
  function recBar(stream, startT, onCancel) {
    const pill = $('.fc-pill', root); const out = { cancelled: false, close() {} }; if (!pill) return out;
    const bar = document.createElement('div'); bar.className = 'fc-recbar'; bar.setAttribute('role', 'status');
    bar.innerHTML = '<button type="button" class="fc-recx" aria-label="Delete voice note">🗑️</button><span class="fc-recdot"></span><b class="fc-rect">0:00</b><canvas class="fc-recw" aria-hidden="true"></canvas><small class="fc-rech">Tap ■ to send</small>';
    pill.appendChild(bar);
    bar.querySelector('.fc-recx').onclick = e => { e.preventDefault(); onCancel(); };
    const cv = bar.querySelector('canvas'), tm = bar.querySelector('.fc-rect');
    let ac = null, an = null, buf = null, raf = 0; const lv = [];
    try { const AC = window.AudioContext || window.webkitAudioContext; ac = new AC(); const src = ac.createMediaStreamSource(stream); an = ac.createAnalyser(); an.fftSize = 512; src.connect(an); buf = new Uint8Array(an.fftSize); if (ac.state === 'suspended') ac.resume(); } catch (_) {}
    let last = 0;
    const draw = t => {
      raf = requestAnimationFrame(draw);
      const s = Math.floor((Date.now() - startT) / 1000); tm.textContent = Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
      if (t - last < 60) return; last = t;
      let v = 0.04;
      if (an) { an.getByteTimeDomainData(buf); let sum = 0; for (let i = 0; i < buf.length; i++) { const x = (buf[i] - 128) / 128; sum += x * x; } v = Math.min(1, Math.sqrt(sum / buf.length) * 4.5); }
      lv.push(Math.max(0.06, v));
      const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight; if (!w || !h) return;
      if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
      const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
      const step = 5, n = Math.floor(w / step); while (lv.length > n) lv.shift();
      g.fillStyle = getComputedStyle(bar).getPropertyValue('--fc-wave').trim() || '#12a8d0';
      lv.forEach((a, i) => { const bh = Math.max(3, a * (h - 4)); const x = w - (lv.length - i) * step; g.beginPath(); if (g.roundRect) g.roundRect(x, (h - bh) / 2, 3, bh, 1.5); else g.rect(x, (h - bh) / 2, 3, bh); g.fill(); });
    };
    raf = requestAnimationFrame(draw);
    out.close = () => { cancelAnimationFrame(raf); try { ac && ac.close(); } catch (_) {} bar.remove(); };
    return out;
  }
  function attachSheet() {
    const tiles = [['📷', 'Photos & videos', '#7c3aed', () => pickFiles('image/*,video/*', '', true)], ['✨', 'Lens camera', '#0b766e', camera],
      ['📄', 'Document', '#1d4ed8', () => pickFiles('*/*', '', true)], ['📍', 'Location', '#16a34a', shareLocation],
      ['👤', 'Contact', '#0369a1', shareContact], ['🎤', 'Voice note', '#e5484d', () => voiceNote(() => { const ta = $('#fcText', root); ta && ta.dispatchEvent(new Event('input')); })],
      ['🧾', 'Quote', '#c2410c', makeQuote], ['😀', 'Chatmoji', '#ca8a04', () => picker(n => sendRaw({ c: S.conv.id, body: ':' + n + ':', kind: 'text', reply_to: S.reply ? S.reply.id : 0 }))]];
    if (S.conv && S.conv.kind === 'group') tiles.push(['💰', 'Stokvel', '#15803d', stokvel]);
    if (window.FCX && window.FCX.attachTiles) { try { window.FCX.attachTiles(S.conv).forEach(t => tiles.push(t)); } catch (_) {} }
    sheet('<h3>Share</h3><div class="fc-grid">' + tiles.map((t, i) => '<button class="fc-tile" data-i="' + i + '"><i style="background:' + t[2] + '">' + t[0] + '</i>' + t[1] + '</button>').join('') + '</div>', (el, done) => {
      el.querySelectorAll('.fc-tile').forEach(b => b.onclick = () => { done(); tiles[Number(b.dataset.i)][3](); });
    });
  }
  function shareLocation() {
    if (!navigator.geolocation) { toast('Location isn\'t available on this device'); return; }
    toast('Finding your location…');
    navigator.geolocation.getCurrentPosition(p => sendRaw({ c: S.conv.id, kind: 'location', body: '', meta: { lat: +p.coords.latitude.toFixed(6), lng: +p.coords.longitude.toFixed(6), label: 'My location' } }),
      () => toast('Allow location access to share where you are'), { enableHighAccuracy: true, timeout: 15000 });
  }
  function shareContact() {
    sheet('<h3>Share a contact</h3><input id="fcCN" placeholder="Name"><input id="fcCP" type="tel" placeholder="Phone number"><button class="fc-btn" id="fcCGo">Share</button>', (el, done) => {
      $('#fcCGo', el).onclick = () => { const name = $('#fcCN', el).value.trim(), phone = $('#fcCP', el).value.trim(); if (!name || !phone) { toast('Add a name and number'); return; } done(); sendRaw({ c: S.conv.id, kind: 'contact', body: '', meta: { name, phone } }); };
    });
  }
  function makeQuote() {
    sheet('<h3>Send a quote</h3><p>Add each item and its price in rand.</p><input id="fcQT" placeholder="What is this quote for?"><div id="fcQL"></div><button class="fc-btn sec" id="fcQAdd">+ Add item</button><input id="fcQV" placeholder="Valid for (e.g. 7 days)"><button class="fc-btn" id="fcQGo">Send quote</button>', (el, done) => {
      const L = $('#fcQL', el); const add = () => { const r = document.createElement('div'); r.style.cssText = 'display:flex;gap:8px'; r.innerHTML = '<input placeholder="Item" style="flex:2"><input type="number" inputmode="decimal" placeholder="R" style="flex:1">'; L.appendChild(r); };
      add(); add(); $('#fcQAdd', el).onclick = add;
      $('#fcQGo', el).onclick = () => {
        const lines = Array.from(L.children).map(r => ({ label: r.children[0].value.trim(), amount: Number(r.children[1].value || 0) })).filter(l => l.label && l.amount > 0);
        if (!lines.length) { toast('Add at least one item with a price'); return; }
        done(); sendRaw({ c: S.conv.id, kind: 'quote', body: '', meta: { title: $('#fcQT', el).value.trim() || 'Quote', lines, valid: $('#fcQV', el).value.trim() } });
      };
    });
  }

  // ---------- message actions
  function findMsg(id) { return S.msgs.find(m => m.id === id); }
  function msgMenu(id) {
    const m = findMsg(id); if (!m || m.deleted) return;
    const mine = (m.reactions || []).find(r => r.user_id === (S.me && S.me.id));
    const acts = [['↩️', 'Reply', () => { const who = (S.conv.members || []).find(x => x.id === m.sender_id); S.reply = { id: m.id, mine: m.mine, name: who ? who.name : '', text: m.body || (m.kind === 'photo' ? '📷 Photo' : m.kind) }; drawReply(); $('#fcText', root).focus(); }]];
    if (m.body) acts.push(['📋', 'Copy text', () => { navigator.clipboard && navigator.clipboard.writeText(m.body).then(() => toast('Copied')); }]);
    if (m.body && window.FCX && window.FCX.translate) acts.push(['🌐', 'Translate', () => window.FCX.translate(m.body)]);
    if (m.mine && m.kind === 'text') acts.push(['✏️', 'Edit', () => editMsg(m)]);
    acts.push(['⭐', m.starred ? 'Unstar' : 'Star', () => api('/api/fc/star', { m: m.id, on: !m.starred }).then(() => loadMsgs(true, true))]);
    acts.push(['↪️', 'Forward', () => forward(m)]);
    if (m.mine) acts.push(['🗑️', 'Delete for everyone', () => { if (confirm('Delete this message for everyone?')) api('/api/fc/delete', { m: m.id }).then(() => loadMsgs(true, true)).catch(e => toast(e.message)); }, 'danger']);
    sheet('<div class="fc-reacts">' + QUICK.map(n => '<button data-r="' + n + '" class="' + (mine && mine.emoji === ':' + n + ':' ? 'on' : '') + '" aria-label="React ' + n + '">' + cmSvg(n) + '</button>').join('') +
      '<button data-r="+" aria-label="More reactions" style="font-size:26px;color:#0b766e">＋</button></div><div class="fc-acts">' +
      acts.map((a, i) => '<button class="fc-act' + (a[3] ? ' ' + a[3] : '') + '" data-a="' + i + '"><i>' + a[0] + '</i>' + a[1] + '</button>').join('') + '</div>', (el, done) => {
      el.querySelectorAll('[data-r]').forEach(b => b.onclick = () => { done(); const r = b.dataset.r;
        if (r === '+') picker(n => react(m, ':' + n + ':')); else react(m, mine && mine.emoji === ':' + r + ':' ? '' : ':' + r + ':'); });
      el.querySelectorAll('[data-a]').forEach(b => b.onclick = () => { done(); acts[Number(b.dataset.a)][2](); });
    });
  }
  function react(m, emoji) { api('/api/fc/react', { m: m.id, emoji }).then(() => loadMsgs(true, true)).catch(e => toast(e.message)); }
  function reactInfo(id) {
    const m = findMsg(id); if (!m) return;
    const rows = (m.reactions || []).map(r => { const who = (S.conv.members || []).find(x => x.id === r.user_id); const me = r.user_id === (S.me && S.me.id);
      return '<button class="fc-act" ' + (me ? 'data-rm="1"' : '') + '><i style="background:transparent">' + (CM.svg[r.emoji.slice(1, -1)] || '').replace('<svg', '<svg width="32" height="32"') + '</i>' + esc(me ? 'You' : (who ? who.name : 'Member')) + (me ? '<small style="margin-left:auto;color:#55667d">Tap to remove</small>' : '') + '</button>'; }).join('');
    sheet('<h3>Reactions</h3><div class="fc-acts">' + rows + '</div>', (el, done) => { const rm = el.querySelector('[data-rm]'); if (rm) rm.onclick = () => { done(); react(m, ''); }; });
  }
  function editMsg(m) {
    sheet('<h3>Edit message</h3><textarea id="fcED" rows="3"></textarea><button class="fc-btn" id="fcEGo">Save</button>', (el, done) => {
      const t = $('#fcED', el); t.value = m.body; t.focus();
      $('#fcEGo', el).onclick = () => { const v = t.value.trim(); if (!v) return; done(); api('/api/fc/edit', { m: m.id, body: v }).then(() => loadMsgs(true, true)).catch(e => toast(e.message)); };
    });
  }
  function forward(m) {
    const targets = S.list.filter(c => c.id !== S.conv.id && !c.archived).slice(0, 40);
    sheet('<h3>Forward to…</h3><div class="fc-acts">' + (targets.length ? targets.map(c => '<button class="fc-act" data-c="' + c.id + '"><i>💬</i>' + esc(c.title) + '</button>').join('') : '<p>Open your chat list first to load your chats.</p>') + '</div>', (el, done) => {
      el.querySelectorAll('[data-c]').forEach(b => b.onclick = async () => {
        done();
        try {
          const files = [];
          for (const a of m.attachments || []) { const u = await blobFor(a.id); const blob = await (await fetch(u)).blob(); files.push({ filename: a.filename, mime_type: a.mime_type, data_base64: await toB64(blob) }); }
          await api('/api/fc/send', { c: Number(b.dataset.c), kind: m.kind === 'system' ? 'text' : m.kind, body: m.body, meta: Object.assign({}, m.meta || {}, { fwd: (Number((m.meta || {}).fwd) || 0) + 1 }), files });   // FCA-01 forward count
          toast('Forwarded');
        } catch (e) { toast(e.message); }
      });
    });
  }
  function convMenu() {
    const c = S.conv; const acts = [['🔎', 'Search in chat', () => { const q = prompt('Search this chat'); if (q) { S.msgFilter = q; drawMsgs('top'); } }],
      ['⭐', 'Starred messages', () => { S.msgFilter = '★'; drawMsgs('top'); }],
      [c.pinned ? '📌' : '📌', c.pinned ? 'Unpin chat' : 'Pin chat', () => setConv({ pinned: !c.pinned })],
      ['🔕', c.muted ? 'Unmute notifications' : 'Mute notifications', () => setConv({ muted: !c.muted })],
      ['🗂️', c.archived ? 'Unarchive chat' : 'Archive chat', () => setConv({ archived: !c.archived }, true)]];
    if (c.kind === 'group') { acts.unshift(['💰', 'Stokvel', stokvel]); acts.push(['➕', 'Add people', addPeople]); acts.push(['✏️', 'Rename group', () => { const t = prompt('Group name', c.title); if (t) setConv({ title: t }); }]); acts.push(['🚪', 'Leave group', () => { if (confirm('Leave this group?')) setConv({ leave: true }, true); }, 'danger']); }
    if (c.kind === 'business' && c.who === 'business') acts.push(['✦', 'View provider profile', () => { close(); try { window.openProvider && window.openProvider(c.business_id); } catch (_) {} }]);
    if (window.FCX && window.FCX.convActs) { try { window.FCX.convActs(c).forEach(a => acts.push(a)); } catch (_) {} }
    acts.push(['⚑', 'Report', report, 'danger']);
    sheet('<h3>' + esc(c.title) + '</h3><div class="fc-acts">' + acts.map((a, i) => '<button class="fc-act' + (a[3] ? ' ' + a[3] : '') + '" data-a="' + i + '"><i>' + a[0] + '</i>' + a[1] + '</button>').join('') + '</div>', (el, done) => {
      el.querySelectorAll('[data-a]').forEach(b => b.onclick = () => { done(); acts[Number(b.dataset.a)][2](); });
    });
  }
  async function setConv(patch, back) { try { await api('/api/fc/settings', Object.assign({ c: S.conv.id }, patch)); if (back) { renderList(true); return; } await loadMsgs(true, true); toast('Saved'); } catch (e) { toast(e.message); } }
  function addPeople() {
    sheet('<h3>Add people</h3><p>Phone numbers, one per line.</p><textarea id="fcAP" rows="4"></textarea><button class="fc-btn" id="fcAPGo">Add</button>', (el, done) => {
      $('#fcAPGo', el).onclick = async () => { const phones = $('#fcAP', el).value.split(/[\n,;]+/).map(x => x.trim()).filter(Boolean); done();
        try { const d = await api('/api/fc/add-members', { c: S.conv.id, phones }); toast(d.added.length ? 'Added ' + d.added.join(', ') : 'Nobody new was found on Future Chat'); loadMsgs(true, true); } catch (e) { toast(e.message); } };
    });
  }
  function report() {
    const reasons = ['Spam or scam', 'Harassment or bullying', 'Hate speech or threats', 'Sexual or inappropriate content', 'Pretending to be someone else', 'Something else'];
    sheet('<h3>Report this chat</h3><p>Our team reviews every report. The last messages in this chat are included so we can act.</p><div class="fc-acts">' + reasons.map((r, i) => '<button class="fc-act" data-r="' + i + '"><i>⚑</i>' + r + '</button>').join('') + '</div>', (el, done) => {
      el.querySelectorAll('[data-r]').forEach(b => b.onclick = async () => { done();
        const lines = S.msgs.slice(-15).map(m => '[' + clock(m.created_at) + '] ' + (m.mine ? 'Me' : (((S.conv.members || []).find(x => x.id === m.sender_id) || {}).name || 'Member')) + ': ' + (m.body || m.kind)).join('\n');
        try { await api('/api/fc/report', { c: S.conv.id, reason: reasons[Number(b.dataset.r)] }); toast('Report sent. Thank you.'); }
        catch (_) { location.href = 'mailto:skillvaya@gmail.com?subject=' + encodeURIComponent('Future Chat report: ' + reasons[Number(b.dataset.r)]) + '&body=' + encodeURIComponent('Conversation: ' + S.conv.title + '\n\n' + lines); } });
    });
  }

  // ---------- stokvels (SV91): the group's shared record of contributions and whose turn it is to be paid
  async function stokvel() {
    const c = S.conv; if (!c || c.kind !== 'group') { toast('Stokvels live in group chats'); return; }
    let d; try { d = await api('/api/fc/stokvel?c=' + c.id); } catch (e) { toast(e.message); return; }
    const st = d.stokvel;
    if (!st) {
      if (!d.can_manage) { sheet('<h3>💰 Stokvel</h3><p>This group doesn\'t have a stokvel yet. Ask the group admin to start one from the group menu.</p>'); return; }
      return stokvelForm(d, null);
    }
    const rows = st.rows.map(r => '<div class="ln" style="align-items:center;padding:6px 0;border-top:1px solid #eef2f7"><span>' + esc(r.name) + (r.role === 'admin' ? ' <small style="color:#55667d">admin</small>' : '') + '<br><small style="color:#55667d">Saved ' + esc(r.total_confirmed) + '</small></span><span>' +
      (r.confirmed ? '✅ Confirmed' : r.paid ? '🕓 Paid' + (d.can_manage ? ' <button class="fc-chip" data-ok="' + r.id + '">Confirm</button>' : '') : '— Not yet' + (d.can_manage ? ' <button class="fc-chip" data-ok="' + r.id + '">Mark paid</button>' : '')) + '</span></div>').join('');
    sheet('<h3>💰 ' + esc(st.name) + '</h3><div class="fc-card" style="min-width:0"><div class="ln"><span>Contribution</span><b>' + esc(st.amount) + ' ' + esc(st.frequency) + '</b></div><div class="ln"><span>This ' + (st.frequency === 'weekly' ? 'week' : 'month') + ' (' + esc(st.period) + ')</span><b>' + st.paid_count + ' of ' + st.rows.length + ' paid</b></div>' +
      '<div class="ln"><span>Payout this round</span><b>' + esc(st.pot) + ' → ' + esc(st.payout_to || '—') + '</b></div><div class="ln"><span>Next in line</span><b>' + esc(st.next_payout_to || '—') + '</b></div><div class="ln"><span>Saved together (confirmed)</span><b>' + esc(st.total_saved) + '</b></div></div>' +
      (st.rules ? '<p style="white-space:pre-wrap;font-size:13px;color:#33475f"><b>Rules:</b> ' + esc(st.rules) + '</p>' : '') +
      '<div style="margin-top:8px">' + rows + '</div>' +
      (!st.me_paid ? '<button class="fc-btn" id="fcSkPay">I\'ve paid my ' + esc(st.amount) + '</button>' : '') +
      (d.can_manage ? '<button class="fc-btn sec" id="fcSkEdit">Edit stokvel</button>' : '') +
      '<p style="font-size:11px;color:#55667d;margin-top:10px">Skillvaya keeps your group\'s record of payments and payout turns. Money is paid between members directly (e.g. EFT or cash); Skillvaya never holds stokvel money.</p>', (el, done) => {
      const pay = $('#fcSkPay', el); if (pay) pay.onclick = async () => { try { await api('/api/fc/stokvel', { c: c.id, action: 'pay' }); done(); toast('Marked as paid'); loadMsgs(true, true); } catch (e) { toast(e.message); } };
      const ed = $('#fcSkEdit', el); if (ed) ed.onclick = () => { done(); stokvelForm(d, st); };
      el.querySelectorAll('[data-ok]').forEach(b => b.onclick = async () => { try { await api('/api/fc/stokvel', { c: c.id, action: 'confirm', user_id: Number(b.dataset.ok) }); done(); stokvel(); loadMsgs(true, true); } catch (e) { toast(e.message); } });
    });
  }
  function stokvelForm(d, st) {
    const c = S.conv;
    sheet('<h3>' + (st ? 'Edit stokvel' : 'Start a stokvel') + '</h3><p>Everyone in this group contributes the same amount each round, and one member receives the full pot in turn.</p>' +
      '<input id="fcSkN" maxlength="60" placeholder="Stokvel name" value="' + esc(st ? st.name : c.title) + '">' +
      '<input id="fcSkA" inputmode="decimal" placeholder="Contribution per member, e.g. 500" value="' + (st ? (st.amount_cents / 100) : '') + '">' +
      '<div class="fc-chips" style="margin:6px 0"><button class="fc-chip' + (!st || st.frequency === 'monthly' ? ' on' : '') + '" data-fq="monthly">Monthly</button><button class="fc-chip' + (st && st.frequency === 'weekly' ? ' on' : '') + '" data-fq="weekly">Weekly</button></div>' +
      '<p style="margin:8px 0 2px;font-size:13px"><b>Payout order</b> (tap to move someone up)</p><div id="fcSkO"></div>' +
      '<textarea id="fcSkR" rows="3" maxlength="1000" placeholder="Group rules (optional), e.g. pay by the 5th; R50 late fee">' + esc(st ? st.rules : '') + '</textarea>' +
      '<button class="fc-btn" id="fcSkGo">' + (st ? 'Save' : 'Start stokvel') + '</button>' + (st ? '<button class="fc-btn danger" id="fcSkClose">Close stokvel</button>' : ''), (el, done) => {
      let freq = st ? st.frequency : 'monthly';
      let order = d.members.slice();
      if (st && st.order) order.sort((a, b) => st.order.indexOf(a.name) - st.order.indexOf(b.name));
      const drawO = () => { $('#fcSkO', el).innerHTML = order.map((m, i) => '<button class="fc-act" data-up="' + i + '"><i>' + (i + 1) + '</i>' + esc(m.name) + '</button>').join(''); el.querySelectorAll('[data-up]').forEach(b => b.onclick = () => { const i = Number(b.dataset.up); if (i > 0) { [order[i - 1], order[i]] = [order[i], order[i - 1]]; drawO(); } }); };
      drawO();
      el.querySelectorAll('[data-fq]').forEach(b => b.onclick = () => { freq = b.dataset.fq; el.querySelectorAll('[data-fq]').forEach(x => x.classList.toggle('on', x === b)); });
      $('#fcSkGo', el).onclick = async () => {
        try { await api('/api/fc/stokvel', { c: c.id, action: st ? 'update' : 'create', name: $('#fcSkN', el).value, amount: $('#fcSkA', el).value, frequency: freq, rules: $('#fcSkR', el).value, order: order.map(m => m.id) }); done(); toast(st ? 'Stokvel saved' : 'Stokvel started'); loadMsgs(true, true); stokvel(); }
        catch (e) { toast(e.message); }
      };
      const cl = $('#fcSkClose', el); if (cl) cl.onclick = async () => { if (!confirm('Close this stokvel? Its history stays in the chat.')) return; try { await api('/api/fc/stokvel', { c: c.id, action: 'close' }); done(); toast('Stokvel closed'); loadMsgs(true, true); } catch (e) { toast(e.message); } };
    });
  }

  // ---------- calls
  function call(mode) {
    const c = S.conv; if (!c) return;
    const canData = typeof window.startSkillvayaVideoCall === 'function';
    const label = (mode === 'video' ? 'Video call' : 'Voice call') + ' over data', note = 'Free · uses your data or Wi-Fi';
    // FC-CALL-STAY-01: keep Future Chat (and this conversation) open under the call screen, so ending the call
    // returns the person to the chat they were in instead of the home screen. The call screen sits above Future Chat.
    const dataCall = calleeId => { try { window.startSkillvayaVideoCall(c.business_id || 0, c.customer_id || 0, mode, { conversationId: c.id, calleeId: calleeId || 0 }); } catch (e) { toast(e.message); } };
    const acts = [];
    if (canData && c.kind === 'group') {
      (c.members || []).filter(x => x.id !== (S.me && S.me.id)).slice(0, 12).forEach(x => acts.push([mode === 'video' ? '🎥' : '📞', label + ' · ' + x.name, note, () => dataCall(x.id)]));
    } else if (canData) acts.push([mode === 'video' ? '🎥' : '📞', label, note, () => dataCall(0)]);
    if (!acts.length) { toast(window.SV_FC_APP ? 'Calls need the latest Future Chat app.' : 'Calls need the latest Skillvaya app or a browser with camera and microphone support.'); return; }
    if (acts.length === 1) { acts[0][3](); return; }
    sheet('<h3>' + esc(c.title) + '</h3><div class="fc-acts">' + acts.map((a, i) => '<button class="fc-act" data-a="' + i + '"><i>' + a[0] + '</i><span>' + a[1] + '<br><small style="color:#55667d">' + esc(a[2]) + '</small></span></button>').join('') + '</div>', (el, done) => {
      el.querySelectorAll('[data-a]').forEach(b => b.onclick = () => { done(); acts[Number(b.dataset.a)][3](); });
    });
  }

  // ---------- Chatmoji picker
  function recent() { try { return JSON.parse(localStorage.getItem('fc_cm_recent') || '[]').filter(n => CM.svg[n]); } catch (_) { return []; } }
  function remember(n) { try { const r = [n].concat(recent().filter(x => x !== n)).slice(0, 18); localStorage.setItem('fc_cm_recent', JSON.stringify(r)); } catch (_) {} }
  function picker(onPick) {
    const cats = (recent().length ? [['Recent', recent()]] : []).concat(CM.cats);
    sheet('<h3>Chatmoji</h3><p style="margin-bottom:6px">Our own emoji set · ' + Object.keys(CM.svg).length + ' designs</p><div class="fc-pick-tabs">' + cats.map((c, i) => '<button data-t="' + i + '" class="' + (i === 0 ? 'on' : '') + '">' + esc(c[0]) + '</button>').join('') + '</div><div class="fc-pick" id="fcPick"></div>', (el, done) => {
      const grid = $('#fcPick', el);
      const show = i => { grid.innerHTML = cats[i][1].map(n => '<button data-n="' + n + '" aria-label="' + n.replace(/_/g, ' ') + '">' + CM.svg[n] + '</button>').join('');
        grid.querySelectorAll('[data-n]').forEach(b => b.onclick = () => { remember(b.dataset.n); done(); onPick(b.dataset.n); }); };
      el.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { el.querySelectorAll('[data-t]').forEach(x => x.classList.toggle('on', x === b)); show(Number(b.dataset.t)); });
      show(0);
    });
  }

  // ---------- phone verification (Firebase via the Skillvaya app, or the web)
  async function verifyPhone(afterSignup) {
    let st = {}; try { st = await api('/api/phone/status'); } catch (_) {}
    if (st.mode === 'sim' && !st.confirmed) return verifyPhoneBySim(st, afterSignup);
    if (st.verified && !afterSignup) { toast('Your number ' + st.phone + (st.method === 'email' ? ' is confirmed by email (not SMS-checked yet)' : st.method === 'self' ? ' is saved' : ' is verified')); return; }
    if (st.mode === 'sim') return verifyPhoneBySim(st, afterSignup);
    if (st.mode === 'email') return verifyPhoneByEmail(st, afterSignup);
    return verifyPhoneByCode(st, afterSignup);
  }
  // FCV-02: Google (Firebase) texts a 6-digit code to the number. Receiving an SMS is free, so this works with no airtime.
  function verifyPhoneByCode(st, afterSignup) {
    sheet('<h3>' + (st.mode === 'sim' ? 'Get a free code by SMS' : 'Verify your phone number') + '</h3><p>' + (afterSignup ? 'One last step. ' : '') + 'We\'ll send a 6-digit code by SMS. Receiving it is free, even with no airtime.</p>' +
      '<input id="fcPN" type="tel" autocomplete="tel" placeholder="Phone number, e.g. 082 123 4567" value="' + esc(st.phone || '') + '"><button class="fc-btn" id="fcPSend">Send code</button>' +
      '<div id="fcPStep2" style="display:none"><input id="fcPC" class="fc-codes" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••"><button class="fc-btn" id="fcPConfirm">Verify</button></div>' +
      '<p id="fcPMsg" role="status"></p>' + (afterSignup ? '<button class="fc-btn sec" id="fcPLater">Later</button>' : '') + '<div id="fcRecaptcha"></div>', (el, done) => {
      const msg = t => { $('#fcPMsg', el).textContent = t; };
      const later = $('#fcPLater', el); if (later) later.onclick = done;
      const finish = async idToken => {
        try { const r = await api('/api/phone/verify', { id_token: idToken }); msg(''); done(); S.verified = true; toast('Verified ' + r.phone + ' ✓'); if (S.open && !S.conv) loadList(); }
        catch (e) { msg(e.message); }
      };
      const e164 = () => { let v = $('#fcPN', el).value.replace(/[^\d+]/g, ''); if (v.startsWith('00')) v = '+' + v.slice(2); if (!v.startsWith('+')) v = '+27' + v.replace(/^0+/, ''); return v; };
      const n = native();
      window.fcPhoneCodeSent = () => { msg('Code sent. It may fill in automatically.'); $('#fcPStep2', el).style.display = 'block'; $('#fcPC', el).focus(); };
      window.fcPhoneVerified = token => finish(token);
      window.fcPhoneError = t => msg(t || 'Verification failed. Check the number and try again.');
      let web = null;
      $('#fcPSend', el).onclick = async () => {
        const num = e164(); if (num.replace(/\D/g, '').length < 9) { msg('Enter your full phone number.'); return; }
        msg('Sending code…');
        if (n && n.startPhoneVerification) { n.startPhoneVerification(num); return; }
        try { web = await webVerify(st.web_config, num, el); window.fcPhoneCodeSent(); } catch (e) { msg(e.message); }
      };
      $('#fcPConfirm', el).onclick = async () => {
        const code = $('#fcPC', el).value.replace(/\D/g, ''); if (code.length !== 6) { msg('Enter the 6-digit code.'); return; }
        msg('Checking…');
        if (n && n.confirmPhoneCode) { n.confirmPhoneCode(code); return; }
        try { const cred = await web.confirm(code); finish(await cred.user.getIdToken()); } catch (e) { msg('That code didn\'t work. Check it or send a new one.'); }
      };
    });
  }
  // FCV-01: prove the number with ONE normal SMS from the person's own SIM. Their SMS app opens with the code
  // already typed in; they tap Send. The server sees which number it came from.
  function verifyPhoneBySim(st, afterSignup) {
    sheet('<h3>Confirm your number</h3><p>' + (afterSignup ? 'One last step. ' : '') + 'Your SMS app will open with a short code already typed in. <b>Just tap Send.</b> It costs one normal SMS and proves this number is really yours.</p>' +
      '<input id="fcPN" type="tel" autocomplete="tel" placeholder="Your phone number, e.g. 082 123 4567" value="' + esc(st.phone || '') + '"><button class="fc-btn" id="fcPSend">Open SMS app</button>' +
      '<div id="fcPWait" style="display:none;text-align:center;margin:10px 0"><div style="font-size:30px;line-height:1">📨</div><p style="margin:6px 0">Waiting for your SMS…</p><p class="fc-muted" style="font-size:12.5px;opacity:.8" id="fcPHow"></p><button class="fc-btn sec" id="fcPAgain">Open SMS app again</button></div>' +
      '<p id="fcPMsg" role="status"></p><p class="fc-muted" style="font-size:12px;opacity:.75">Send it from the phone that has this SIM. The code works for 30 minutes.</p>' +
      '<button class="fc-btn sec" id="fcPFree">No airtime? Get a free code by SMS instead</button>' + (afterSignup ? '<button class="fc-btn sec" id="fcPLater">Later</button>' : ''), (el, done) => {
      const msg = t => { $('#fcPMsg', el).textContent = t; };
      let timer = 0, last = null;
      $('#fcPFree', el).onclick = () => { if (timer) clearInterval(timer); timer = 0; const ph = $('#fcPN', el).value.trim() || st.phone || ''; done(); verifyPhoneByCode(Object.assign({}, st, { phone: ph }), afterSignup); };
      const stop = () => { if (timer) clearInterval(timer); timer = 0; };
      const finish = d => { stop(); done(); S.verified = true; toast('Number ' + (d.phone || '') + ' confirmed ✓'); if (S.open && !S.conv) loadList(); };
      const later = $('#fcPLater', el); if (later) later.onclick = () => { stop(); done(); };
      const openSms = r => { location.href = 'sms:' + r.to + '?body=' + encodeURIComponent(r.body); };
      $('#fcPAgain', el).onclick = () => { if (last) openSms(last); };
      $('#fcPSend', el).onclick = async () => {
        const raw = $('#fcPN', el).value; if (raw.replace(/\D/g, '').length < 9) { msg('Enter your full phone number.'); return; }
        msg('');
        try {
          const r = await api('/api/fcv/start', { phone: raw }); last = r;
          $('#fcPWait', el).style.display = 'block'; $('#fcPSend', el).style.display = 'none';
          $('#fcPHow', el).textContent = 'Or send "' + r.code + '" by SMS to ' + r.to_pretty + ' from ' + r.phone + '.';
          openSms(r);
          stop(); const t0 = Date.now();
          timer = setInterval(async () => {
            if (!el.isConnected || Date.now() - t0 > 30 * 60 * 1000) return stop();
            try { const s = await api('/api/fcv/status'); if (s.confirmed) finish(s); } catch (_) {}
          }, 3000);
        } catch (e) { msg(e.message); }
      };
    });
  }
  // SV93-EMAILPHONE: free check while SMS is off. The code goes to the account email; the number is marked "confirmed by email".
  function verifyPhoneByEmail(st, afterSignup) {
    sheet('<h3>Add your phone number</h3><p>' + (afterSignup ? 'One last step. ' : '') + 'Your number lets friends and family find you on Future Chat and call you. We\'ll email a 6-digit code to ' + esc(st.email_hint || 'your account email') + ' to confirm it\'s you.</p>' +
      '<input id="fcPN" type="tel" autocomplete="tel" placeholder="Phone number, e.g. 082 123 4567" value="' + esc(st.phone || '') + '"><button class="fc-btn" id="fcPSend">Email me a code</button>' +
      '<div id="fcPStep2" style="display:none"><input id="fcPC" class="fc-codes" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••"><button class="fc-btn" id="fcPConfirm">Confirm</button></div>' +
      '<p id="fcPMsg" role="status"></p><p class="fc-muted" style="font-size:12px;opacity:.75">Your number is marked "confirmed by email" until SMS checks are switched on.</p>' + (afterSignup ? '<button class="fc-btn sec" id="fcPLater">Later</button>' : ''), (el, done) => {
      const msg = t => { $('#fcPMsg', el).textContent = t; };
      const later = $('#fcPLater', el); if (later) later.onclick = done;
      $('#fcPSend', el).onclick = async () => {
        const raw = $('#fcPN', el).value; if (raw.replace(/\D/g, '').length < 9) { msg('Enter your full phone number.'); return; }
        msg('Sending…');
        try { const r = await api('/api/phone/email-start', { phone: raw }); if (r.saved) { done(); S.verified = true; toast('Number ' + r.phone + ' saved ✓'); if (S.open && !S.conv) loadList(); return; } /*SV93-SELFPHONE*/ msg('Code sent to ' + r.sent_to + '. Check your inbox (and spam).'); $('#fcPStep2', el).style.display = 'block'; $('#fcPC', el).focus();
          /*SV93-SKIPMAIL*/ setTimeout(() => { if (!el.isConnected || $('#fcPSkip', el)) return; const b = document.createElement('button'); b.id = 'fcPSkip'; b.className = 'fc-btn sec'; b.textContent = "Didn't get the email? Save my number anyway"; b.onclick = async () => { try { const s = await api('/api/phone/email-start', { phone: raw, skip: true }); done(); S.verified = true; toast('Number ' + s.phone + ' saved ✓'); if (S.open && !S.conv) loadList(); } catch (e2) { msg(e2.message); } }; $('#fcPStep2', el).appendChild(b); }, 30000); }
        catch (e) { msg(e.message); }
      };
      $('#fcPConfirm', el).onclick = async () => {
        const code = $('#fcPC', el).value.replace(/\D/g, ''); if (code.length !== 6) { msg('Enter the 6-digit code.'); return; }
        msg('Checking…');
        try { const r = await api('/api/phone/email-confirm', { code }); done(); S.verified = true; toast('Number ' + r.phone + ' added ✓'); if (S.open && !S.conv) loadList(); }
        catch (e) { msg(e.message); }
      };
    });
  }
  function loadScript(src) { return new Promise((res, rej) => { if (document.querySelector('script[src="' + src + '"]')) return res(); const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = () => rej(new Error('Could not load verification')); document.head.appendChild(s); }); }
  async function webVerify(cfg, num, el) {
    if (!cfg) throw new Error('Open the Skillvaya app on your phone to verify your number.');
    await loadScript('https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js');
    await loadScript('https://www.gstatic.com/firebasejs/10.12.2/firebase-auth-compat.js');
    const fb = window.firebase; const app = fb.apps.length ? fb.app() : fb.initializeApp(cfg);
    const v = new fb.auth.RecaptchaVerifier($('#fcRecaptcha', el), { size: 'invisible' }, app);
    return fb.auth(app).signInWithPhoneNumber(num, v);
  }

  // ---------- wiring into the Skillvaya app
  function wire() {
    const navBtn = document.getElementById('nav-messages');
    if (navBtn) { navBtn.innerHTML = '<span class="bottom-tab-icon" aria-hidden="true" style="display:inline-grid;width:22px;height:22px">' + cmSvg('bubble') + '</span><span>Future Chat</span>'; navBtn.onclick = e => { e.preventDefault(); open(); }; navBtn.setAttribute('aria-label', 'Future Chat'); }
    window.showMessagesScreen = function () { open(); };
    window.viewMessages = function () { open(); };
    window.openMessageConversation = async function (businessId, customerId) {
      try { const me = window.me || {}; if (me.id && Number(customerId) === Number(me.id)) { const d = await api('/api/fc/start', { business_id: Number(businessId) }); open(d.conversation_id); return; } } catch (_) {}
      open();
    };
    if (typeof window.view === 'function' && !window.view.__fc) {
      const orig = window.view; const wrapped = function () { close(); return orig.apply(this, arguments); }; wrapped.__fc = true; window.view = wrapped;
    }
    const p = new URLSearchParams(location.search); const fc = p.get('fc');
    if (fc && token()) setTimeout(() => open(Number(fc) || 0), 400);
    if (p.get('fc_verify') === '1' && token()) setTimeout(() => verifyPhone(true), 800);
    // SV93-ASKPHONE: every signed-in customer and provider is asked to add and confirm their number once,
    // with "Later" snoozing the ask for a day. Account also gets a Phone number card.
    let asked = false;
    const askPhone = async () => {
      if (asked || !token() || S.open || document.querySelector('.fc-sheet')) return;
      let snooze = 0; try { snooze = Number(localStorage.getItem('sv_phone_ask_snooze') || 0); } catch (_) {}
      let st = {}; try { st = await api('/api/phone/status'); } catch (_) { return; }
      phoneCard(st);
      if ((st.mode === 'sim' ? st.confirmed : st.verified) || Date.now() < snooze) { asked = true; return; }
      asked = true;
      try { localStorage.setItem('sv_phone_ask_snooze', String(Date.now() + 24 * 3600 * 1000)); } catch (_) {}
      verifyPhone(true);
    };
    const phoneCard = st => {
      const s = document.getElementById('settings'); if (!s) return;
      let c = document.getElementById('svPhoneCard');
      if (!c) { c = document.createElement('div'); c.id = 'svPhoneCard'; c.className = 'card'; c.style.cssText = 'margin:16px 0;border-radius:16px;padding:14px 16px!important;overflow:visible!important;box-sizing:border-box;background:#fff;border:1px solid #dce7f5;color:#122238'; const ref = document.getElementById('svDataSaverCard'); if (ref) s.insertBefore(c, ref); else s.appendChild(c); }
      const label = st.verified ? (st.method === 'email' ? 'Confirmed by email' : st.method === 'self' ? (st.mode === 'sim' ? 'Not confirmed yet' : 'Saved') : 'Verified') : 'Not added yet';
      c.innerHTML = '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px"><span><strong>Phone number</strong><span class="muted tiny" style="display:block">' + esc(st.verified ? st.phone : 'Add your number so customers, providers, friends and family can reach you on Future Chat.') + ' · ' + label + '</span></span><button type="button" class="primary" style="flex:none;padding:8px 14px;border-radius:10px">' + (st.mode === 'sim' && st.verified && !st.confirmed ? 'Confirm' : st.verified ? 'Change' : 'Add number') + '</button></div>';
      c.querySelector('button').onclick = () => verifyPhone(true);
    };
    setTimeout(askPhone, 2500); setInterval(askPhone, 20000);
    document.addEventListener('click', e => { const t = e.target && e.target.closest && e.target.closest('#nav-settings'); if (t) setTimeout(async () => { try { phoneCard(await api('/api/phone/status')); } catch (_) {} }, 600); }, true);
    setInterval(async () => { if (!token() || document.visibilityState === 'hidden' || S.open) return; try { const d = await api('/api/fc/pulse'); const btn = document.getElementById('nav-messages'); if (btn) { S.list = S.list || []; let b = btn.querySelector('.fc-navbadge'); if (!b) { updateBadge(); b = btn.querySelector('.fc-navbadge'); } if (b) { b.textContent = d.unread > 99 ? '99+' : String(d.unread); b.style.display = d.unread ? 'grid' : 'none'; } } } catch (_) {} }, 15000);
  }
  function share(text) { S.pendingShare = String(text || ''); open(); setTimeout(() => toast('Pick a chat to share with'), 300); }
  function inviteFriends() { invite(''); }
  window.FutureChat = { open, close, verifyPhone, newChat, share, stokvel, inviteFriends, findFriends: () => { open(); setTimeout(askContacts, 300); },
    newGroup, openConv: id => { open(); return openConv(Number(id)); }, picker, state: () => ({ open: S.open, conv: S.conv ? S.conv.id : 0, list: S.list, me: S.me }),
    callConv: async (id, mode) => { open(); await openConv(Number(id)); call(mode === 'video' ? 'video' : 'voice'); },
    reloadList: () => { if (S.open && !S.conv) loadList(); }, refreshMsgs: () => { if (S.conv) loadMsgs(true, true); } };
  window.fcVerifyPhone = verifyPhone;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire); else wire();
})();
