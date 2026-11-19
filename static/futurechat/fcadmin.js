/* FCA-01 (owner 2026-11-19): Future Chat Control (owner only), business client lists + broadcasts, and the
   "Stop messages from this business" button on broadcast messages. Server: fcadmin.py (/api/fca/*). */
(function () {
  'use strict';
  const FCX = window.FCX; if (!window.SV_FC_APP || !FCX || !FCX.kit) return;
  const K = FCX.kit, { api, post, esc, $, toast, sheet, frame, push, pop, go, row, bind, openPanel, X } = K;
  const top = () => X.stack[X.stack.length - 1];
  const A = FCX.ctl = { me: null };
  async function me() { try { A.me = await api('/api/fca/me'); } catch (_) {} return A.me; }
  const ago = iso => { if (!iso) return 'never'; const s = Math.max(0, (Date.now() - new Date(iso)) / 1000); if (s < 90) return 'online now'; if (s < 3600) return Math.round(s / 60) + ' min ago'; if (s < 86400) return Math.round(s / 3600) + ' h ago'; return Math.round(s / 86400) + ' days ago'; };
  const until = b => !b ? '' : (b.until ? 'banned until ' + new Date(b.until).toLocaleString('en-ZA', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'banned for good');

  // ---------------------------------------------------------------- simple bar chart (SVG, no libraries)
  function chart(title, labels, values, color) {
    const W = 320, H = 120, n = values.length, max = Math.max(1, ...values), bw = W / n;
    const bars = values.map((v, i) => { const h = Math.round((v / max) * (H - 18)); return '<rect x="' + (i * bw + 1).toFixed(1) + '" y="' + (H - h) + '" width="' + Math.max(1, bw - 2).toFixed(1) + '" height="' + h + '" rx="2" fill="' + color + '"><title>' + labels[i] + ': ' + v + '</title></rect>'; }).join('');
    const total = values.reduce((a, b) => a + b, 0), last = values[values.length - 1] || 0;
    return '<div class="fca-card" style="padding:12px 14px"><div style="display:flex;justify-content:space-between;align-items:baseline"><b style="font-size:14px">' + esc(title) + '</b><span style="font-size:12px;color:#9cb7cc">today ' + last + ' · ' + n + ' days ' + total + '</span></div>' +
      '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:auto;margin-top:8px" role="img" aria-label="' + esc(title) + '"><line x1="0" y1="' + H + '" x2="' + W + '" y2="' + H + '" stroke="#2a4458"/>' + bars +
      '<text x="0" y="10" fill="#9cb7cc" font-size="10">' + max + '</text></svg><div style="display:flex;justify-content:space-between;font-size:10.5px;color:#7f9bb0"><span>' + esc(labels[0].slice(5)) + '</span><span>' + esc(labels[labels.length - 1].slice(5)) + '</span></div></div>';
  }
  const tile = (n, label, a) => '<button class="fca-card" ' + (a ? 'data-a="' + a + '"' : '') + ' style="flex:1;min-width:92px;padding:12px;text-align:left;border:0;color:inherit;font:inherit;cursor:' + (a ? 'pointer' : 'default') + '"><b style="font-size:22px;display:block">' + n + '</b><span style="font-size:12px;color:#9cb7cc">' + esc(label) + '</span></button>';

  // ---------------------------------------------------------------- Control: overview
  async function scrControl() {
    const self = top();
    const bd = frame('Future Chat Control', 'Only you can see this');
    bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let s; try { s = await api('/api/fca/admin/stats?days=30'); } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    bd.innerHTML = '<div style="display:flex;flex-wrap:wrap;gap:8px">' + tile(s.online_now, 'online now', 'online') + tile(s.today_active, 'used it today') + tile(s.mau, 'used it this month') + '</div>' +
      '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px">' + tile(s.fc_total, 'joined Future Chat', 'joined') + tile(s.open_reports, 'open complaints', 'reports') + tile(s.active_bans, 'banned now', 'bans') + '</div>' +
      chart('People joining per day', s.labels, s.joined, '#1ed6c8') + chart('People using the app per day', s.labels, s.active, '#5aa9ff') + chart('Messages sent per day', s.labels, s.messages, '#b38cff') +
      '<div class="fca-card">' + row('🟢', 'Who\'s online now', s.online_now + (s.online_now === 1 ? ' person' : ' people'), { data: 'data-a="online"' }) + row('⚑', 'Complaints', s.open_reports + ' open', { data: 'data-a="reports"' }) +
      row('⛔', 'Bans', s.active_bans + ' banned now · spam is banned for 24 h automatically', { data: 'data-a="bans"' }) + row('🔎', 'Find a person', 'See their details, ban them or delete their account', { data: 'data-a="find"' }) + '</div>' +
      '<p class="fca-note">"Used it" counts people who opened Future Chat that day. Total accounts (Skillvaya + Future Chat): ' + s.total + '.</p>';
    bind(bd, { joined: () => push(scrJoined), online: () => push(() => scrOnline(s)), reports: () => push(scrReports), bans: () => push(scrBans), find: () => push(scrFind) });
  }
  function personRow(p, sub) {
    return row(p.banned ? '⛔' : (sub === 'online now' ? '🟢' : '👤'), p.name, [p.phone, sub || ago(p.last_seen), p.banned ? until(p.banned) : ''].filter(Boolean).join(' · '), { data: 'data-p="' + p.id + '"' });
  }
  function wirePeople(bd, people) { bd.querySelectorAll('[data-p]').forEach(el => el.onclick = () => person(people.find(x => String(x.id) === el.dataset.p))); }
  async function scrOnline(s) {
    const self = top(); const bd = frame('Online now', 'Updated every 30 seconds');
    const draw = st => { bd.innerHTML = '<div class="fca-card">' + (st.online.length ? st.online.map(p => personRow(p, ago(p.last_seen))).join('') : row('😴', 'Nobody is online right now', '', {}, '')) + '</div>'; wirePeople(bd, st.online); };
    draw(s);
    const t = setInterval(async () => { if (top() !== self) { clearInterval(t); return; } try { draw(await api('/api/fca/admin/stats?days=7')); } catch (_) {} }, 30000);
  }
  async function scrJoined() {
    const self = top(); const bd = frame('People on Future Chat', 'Everyone who joined, newest first');
    bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let d; try { d = await api('/api/fca/admin/users?fc=1'); } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    const fmt = iso => { try { return new Date(iso).toLocaleDateString('en-ZA', { day: 'numeric', month: 'short', year: 'numeric' }); } catch (_) { return iso; } };
    bd.innerHTML = '<p class="fca-note" style="margin-top:0">' + d.items.length + (d.items.length === 1 ? ' person has' : ' people have') + ' joined (confirmed their number).</p><div class="fca-card">' +
      (d.items.length ? d.items.map(p => row(p.banned ? '⛔' : '👤', p.name, [p.phone, 'joined ' + fmt(p.joined_at || p.joined), 'last seen ' + ago(p.last_seen)].filter(Boolean).join(' · '), { data: 'data-p="' + p.id + '"' })).join('') : row('👥', 'Nobody yet', '', {}, '')) + '</div>';
    wirePeople(bd, d.items);
  }
  async function scrFind() {
    const bd = frame('Find a person', 'Name, number or email');
    bd.innerHTML = '<label class="fca-field"><span>Search</span><input id="fcaQ" placeholder="e.g. Thabo or 082 123 4567"></label><div id="fcaRes"><div class="fca-empty">Newest accounts…</div></div>';
    const res = $('#fcaRes', bd);
    const run = async () => { try { const d = await api('/api/fca/admin/users?q=' + encodeURIComponent($('#fcaQ', bd).value.trim())); res.innerHTML = '<div class="fca-card">' + (d.items.length ? d.items.map(p => personRow(p)).join('') : row('🤷', 'Nobody found', '', {}, '')) + '</div>'; wirePeople(res, d.items); } catch (e) { res.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; } };
    let tm; $('#fcaQ', bd).oninput = () => { clearTimeout(tm); tm = setTimeout(run, 350); };
    run();
  }
  function person(p) {
    if (!p) return;
    const isOwner = p.role === 'admin';
    sheet('<h3>' + esc(p.name) + '</h3><p style="font-size:13px;color:#9cb7cc">' + [p.phone, p.email, 'joined ' + p.joined, 'last seen ' + ago(p.last_seen)].filter(Boolean).map(esc).join('<br>') + (p.banned ? '<br><b style="color:#ff9a9a">' + esc(until(p.banned)) + (p.banned.reason ? ' — ' + esc(p.banned.reason) : '') + '</b>' : '') + '</p>' +
      (isOwner ? '<p>This is an owner account.</p>' : '<div class="fc-acts">' + (p.banned ? '<button class="fc-act" data-a="unban"><i>✅</i>Lift the ban</button>' : '') +
        '<button class="fc-act" data-a="b24"><i>⏳</i>Ban 24 hours</button><button class="fc-act" data-a="b168"><i>📅</i>Ban 7 days</button><button class="fc-act" data-a="b0"><i>⛔</i>Ban for good</button>' +
        '<button class="fc-act" data-a="del" style="color:#ff8a8a"><i>🗑️</i>Delete account</button></div><p style="font-size:12px;color:#9cb7cc">A ban stops them sending messages and starting chats on Future Chat. They can still read.</p>'), (el, done) => bind(el, {
      unban: async () => { try { const r = await post('/api/fca/admin/unban', { user_id: p.id }); done(); toast(r.message); refresh(); } catch (e) { toast(e.message); } },
      b24: () => doBan(p, 24, done), b168: () => doBan(p, 168, done), b0: () => doBan(p, 0, done),
      del: () => { done(); delAccount(p); }
    }));
  }
  function doBan(p, hours, done) {
    done();
    sheet('<h3>Why are you banning ' + esc(p.name) + '?</h3><input id="fcaWhy" maxlength="300" placeholder="e.g. Spam, scams, harassment"><button class="fc-btn" id="fcaGo">Ban ' + (hours ? (hours === 24 ? '24 hours' : '7 days') : 'for good') + '</button>', (el, d2) => {
      $('#fcaGo', el).onclick = async () => { try { const r = await post('/api/fca/admin/ban', { user_id: p.id, hours, reason: $('#fcaWhy', el).value.trim() || 'Broke the Future Chat rules' }); d2(); toast(r.message); refresh(); } catch (e) { toast(e.message); } };
    });
  }
  function delAccount(p) {
    sheet('<h3>Delete ' + esc(p.name) + '\'s account?</h3><p>This deletes their account, messages, pictures and everything else for good, on Future Chat <b>and</b> Skillvaya. It can\'t be undone.</p><p>Type <b>DELETE</b> to confirm.</p><input id="fcaDel" autocapitalize="characters"><button class="fc-btn" id="fcaDelGo" style="background:#d84a4a">Delete for good</button>', (el, done) => {
      $('#fcaDelGo', el).onclick = async () => { try { const r = await post('/api/fca/admin/delete', { user_id: p.id, confirm: $('#fcaDel', el).value.trim().toUpperCase() }); done(); toast(r.message); refresh(); } catch (e) { toast(e.message); } };
    });
  }
  function refresh() { const t = top(); if (t && t.redraw) t.redraw(); }

  // ---------------------------------------------------------------- complaints
  async function scrReports() {
    const self = top(); const bd = frame('Complaints', 'Reports from people using Future Chat');
    bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let d; try { d = await api('/api/fca/admin/reports'); } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    const open = d.items.filter(r => r.status === 'open'), done = d.items.filter(r => r.status !== 'open');
    const card = r => row(r.status === 'open' ? '⚑' : '✅', r.reason + (r.reported ? ' — about ' + r.reported : ''), 'From ' + r.reporter + ' · ' + new Date(r.at).toLocaleString('en-ZA', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) + (r.reply ? ' · replied' : ''), { data: 'data-r="' + r.id + '"' });
    bd.innerHTML = '<div class="fca-gl">Open (' + open.length + ')</div><div class="fca-card">' + (open.length ? open.map(card).join('') : row('🎉', 'No open complaints', '', {}, '')) + '</div>' +
      (done.length ? '<div class="fca-gl">Resolved</div><div class="fca-card">' + done.slice(0, 40).map(card).join('') + '</div>' : '') +
      (d.problems.length ? '<div class="fca-gl">Problem reports (app problems)</div><div class="fca-card">' + d.problems.slice(0, 40).map(p => row('🛠️', p.name, p.body.slice(0, 140), {}, '')).join('') + '</div>' : '');
    bd.querySelectorAll('[data-r]').forEach(el => el.onclick = () => report(d.items.find(x => String(x.id) === el.dataset.r)));
    self.redraw = scrReports;
  }
  function report(r) {
    sheet('<h3>⚑ ' + esc(r.reason) + '</h3><p style="font-size:13px">From <b>' + esc(r.reporter) + '</b>' + (r.reported ? ' about <b>' + esc(r.reported) + '</b>' : '') + '</p>' +
      '<div style="max-height:200px;overflow:auto;font-size:12px;background:#0b1a26;border-radius:10px;padding:8px;white-space:pre-wrap">' + esc(r.snapshot || 'No messages attached.') + '</div>' +
      (r.reply ? '<p style="font-size:12px;color:#9cb7cc">Your reply: ' + esc(r.reply) + '</p>' : '') +
      '<textarea id="fcaRep" rows="3" placeholder="Reply to ' + esc(r.reporter) + ' (sent as a Future Chat message)"></textarea><button class="fc-btn" id="fcaSend">Send reply</button>' +
      '<div class="fc-acts"><button class="fc-act" data-a="res"><i>' + (r.status === 'open' ? '✅' : '↩️') + '</i>' + (r.status === 'open' ? 'Mark resolved' : 'Reopen') + '</button>' +
      (r.reported_id ? '<button class="fc-act" data-a="who"><i>⛔</i>Ban / delete ' + esc(r.reported) + '</button>' : '') + '</div>', (el, done) => {
      $('#fcaSend', el).onclick = async () => { const t = $('#fcaRep', el).value.trim(); if (!t) return; try { await post('/api/fca/admin/reply', { report_id: r.id, text: t }); done(); toast('Reply sent'); refresh(); } catch (e) { toast(e.message); } };
      bind(el, {
        res: async () => { try { await post('/api/fca/admin/resolve', { report_id: r.id, reopen: r.status !== 'open' }); done(); refresh(); } catch (e) { toast(e.message); } },
        who: async () => { done(); try { const d = await api('/api/fca/admin/users?q=' + encodeURIComponent(r.reported)); person(d.items.find(p => p.id === r.reported_id) || d.items[0]); } catch (e) { toast(e.message); } }
      });
    });
  }

  // ---------------------------------------------------------------- bans
  async function scrBans() {
    const self = top(); const bd = frame('Bans', 'Spam is stopped and banned for 24 hours automatically');
    bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let d; try { d = await api('/api/fca/admin/bans'); } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    bd.innerHTML = '<div class="fca-card">' + (d.items.length ? d.items.map(b => row(b.auto ? '🤖' : '⛔', b.name, until(b) + ' · ' + b.reason, { data: 'data-b="' + b.user_id + '"' })).join('') : row('✅', 'Nobody is banned', '', {}, '')) + '</div>' +
      '<div class="fca-gl">History</div><div class="fca-card">' + (d.log.length ? d.log.map(l => row({ 'auto-ban': '🤖', ban: '⛔', unban: '✅', expired: '⌛', deleted: '🗑️' }[l.action] || '•', l.name + ' · ' + l.action, (l.detail || '') + ' · ' + new Date(l.at).toLocaleDateString('en-ZA'), {}, '')).join('') : row('📄', 'Nothing yet', '', {}, '')) + '</div>' +
      '<p class="fca-note">🤖 = stopped automatically (same message to 15+ chats in 10 minutes, messaging 20+ people who never replied within an hour, or 40+ messages in a minute). Tap a person to lift the ban or make it permanent.</p>';
    bd.querySelectorAll('[data-b]').forEach(el => el.onclick = async () => { const b = d.items.find(x => String(x.user_id) === el.dataset.b); try { const r = await api('/api/fca/admin/users?q=' + encodeURIComponent(b.phone || b.name)); person(r.items.find(p => p.id === b.user_id) || r.items[0]); } catch (e) { toast(e.message); } });
    self.redraw = scrBans;
  }

  // ---------------------------------------------------------------- businesses: client list + broadcast
  async function scrClients() {
    const self = top(); const bd = frame('My clients', 'Message all your clients at once');
    bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let d; try { d = await api('/api/fca/biz/clients'); } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    const active = d.clients.filter(c => !c.opted_out), out = d.clients.filter(c => c.opted_out);
    bd.innerHTML = '<div class="fca-card" style="padding:12px"><b>📣 Send to all ' + active.length + ' clients</b><textarea id="fcaB" rows="3" maxlength="2000" placeholder="e.g. We\'re open on Saturday from 8 to 1. Book your spot!" style="margin-top:8px"></textarea>' +
      '<button class="fca-btn" data-a="send"' + (active.length && d.left_today ? '' : ' disabled') + '>Send to ' + active.length + ' clients</button><small style="color:#9cb7cc">' + d.left_today + ' of ' + d.per_day + ' broadcasts left today. Each client gets it as a private message and can tap "Stop messages from this business".</small></div>' +
      '<div class="fca-card">' + row('➕', 'Add people you chat with', d.suggest.length + ' people to choose from', { data: 'data-a="pick"' }) + row('📱', 'Add by phone number', 'They must be on Future Chat', { data: 'data-a="num"' }) + '</div>' +
      '<div class="fca-gl">Clients (' + active.length + ')</div><div class="fca-card">' + (active.length ? active.map(c => row('👤', c.name, (c.phone || '') + ' · added ' + c.added, {}, '<button class="fc-chip" data-rm="' + c.id + '">Remove</button>')).join('') : row('👥', 'No clients yet', 'Add the people you work with', {}, '')) + '</div>' +
      (out.length ? '<div class="fca-gl">Asked to stop (' + out.length + ')</div><div class="fca-card">' + out.map(c => row('🔕', c.name, 'Doesn\'t want broadcasts', {}, '')).join('') + '</div>' : '') +
      (d.past.length ? '<div class="fca-gl">Sent before</div><div class="fca-card">' + d.past.map(p => row('📣', p.body, 'to ' + p.sent + ' · ' + new Date(p.at).toLocaleDateString('en-ZA'), {}, '')).join('') + '</div>' : '') +
      '<p class="fca-note">Only add people who are your clients. If many people report your messages, your account can be banned.</p>';
    self.redraw = scrClients;
    bind(bd, {
      send: async () => { const t = $('#fcaB', bd).value.trim(); if (!t) { toast('Type your message first'); return; } try { const r = await post('/api/fca/biz/broadcast', { body: t }); toast('Sent to ' + r.sent + ' clients'); scrClients(); } catch (e) { toast(e.message); } },
      pick: () => pick(d), num: () => byNumber()
    });
    bd.querySelectorAll('[data-rm]').forEach(b => b.onclick = async ev => { ev.stopPropagation(); try { await post('/api/fca/biz/remove', { user_id: Number(b.dataset.rm) }); scrClients(); } catch (e) { toast(e.message); } });
  }
  function pick(d) {
    if (!d.suggest.length) { toast('Everyone you chat with is already on your list'); return; }
    sheet('<h3>Add clients</h3><div style="max-height:50vh;overflow:auto">' + d.suggest.map(s => '<label style="display:flex;gap:10px;align-items:center;padding:8px 0"><input type="checkbox" value="' + s.id + '" style="width:20px;height:20px"><span>' + esc(s.name) + '<br><small style="color:#9cb7cc">' + esc(s.phone) + '</small></span></label>').join('') + '</div><button class="fc-btn" id="fcaAdd">Add to my clients</button>', (el, done) => {
      $('#fcaAdd', el).onclick = async () => { const ids = [...el.querySelectorAll('input:checked')].map(i => Number(i.value)); if (!ids.length) return; try { const r = await post('/api/fca/biz/add', { user_ids: ids }); done(); toast(r.added + ' added'); scrClients(); } catch (e) { toast(e.message); } };
    });
  }
  function byNumber() {
    sheet('<h3>Add by number</h3><p>One number per line.</p><textarea id="fcaNums" rows="5" placeholder="082 123 4567"></textarea><button class="fc-btn" id="fcaNGo">Add</button>', (el, done) => {
      $('#fcaNGo', el).onclick = async () => { const phones = $('#fcaNums', el).value.split(/[\n,;]+/).map(x => x.trim()).filter(Boolean); if (!phones.length) return; try { const r = await post('/api/fca/biz/add', { phones }); done(); toast(r.added + ' added' + (r.not_on_app ? ' · ' + r.not_on_app + ' not on Future Chat yet' : '') + (r.skipped ? ' · ' + r.skipped + ' skipped' : '')); scrClients(); } catch (e) { toast(e.message); } };
    });
  }

  // ---------------------------------------------------------------- broadcast messages in a chat: "Stop messages from this business"
  const baseSpecial = FCX.special;
  FCX.special = function (m) {
    const t = m.meta || {};
    if (t.bc && t.bc.biz) {
      return '<div class="fc-card"><span class="k">📣 FROM ' + esc(String(t.bc.name || 'BUSINESS').toUpperCase()) + '</span><div style="white-space:pre-wrap;margin:4px 0">' + esc(m.body) + '</div>' +
        (m.mine ? '<small>Sent to your client list</small>' : '<button class="sec" onclick="event.stopPropagation();window.FCX.ctl.optout(' + Number(t.bc.biz) + ')">🔕 Stop messages from this business</button>') + '</div>';
    }
    return baseSpecial ? baseSpecial(m) : '';
  };
  A.optout = biz => sheet('<h3>Stop broadcast messages?</h3><p>This business won\'t be able to send you messages to all its clients any more. You can still chat with them normally.</p><button class="fc-btn" id="fcaOut">Stop messages</button>', (el, done) => {
    $('#fcaOut', el).onclick = async () => { try { const r = await post('/api/fca/optout', { biz }); done(); toast(r.message); } catch (e) { toast(e.message); } };
  });

  // ---------------------------------------------------------------- You tab entries
  const baseYou = FCX.youExtra;
  FCX.youExtra = function (bd) {
    if (baseYou) baseYou(bd);
    const box = document.createElement('div');
    const draw = () => {
      const m = A.me || {}; let h = '';
      if (m.owner) h += row('🛡️', 'Future Chat Control', 'People, online now, charts, complaints and bans', { data: 'data-a="ctl"' });
      if (m.business) h += row('👥', 'My clients', 'Your client list · message all your clients at once', { data: 'data-a="cli"' });
      if (m.banned) h += row('⛔', 'Sending is paused', m.banned.message, {}, '');
      box.innerHTML = h ? '<div class="fca-card">' + h + '</div>' : '';
      bind(box, { ctl: () => push(scrControl), cli: () => push(scrClients) });
    };
    const prof = bd.querySelector('.fca-prof'); if (prof) prof.after(box); else bd.prepend(box);
    draw(); me().then(draw);
  };

  // ---------------------------------------------------------------- FCA-02: hold a chat or a call for options (like WhatsApp)
  const FCc = () => window.FutureChat || {};
  let holdT = null, held = false, sx = 0, sy = 0, lastOpen = 0;
  const holdTarget = e => (e.target && e.target.closest) ? e.target.closest('.fc-row[data-c], #fcaCallList [data-i]') : null;
  const cancelHold = () => { clearTimeout(holdT); holdT = null; };
  function openHold(t) {
    if (Date.now() - lastOpen < 900) return; lastOpen = Date.now();
    if (t.matches('.fc-row[data-c]')) chatMenu(Number(t.dataset.c)); else callMenu(Number(t.dataset.i), t);
  }
  document.addEventListener('touchstart', e => {
    held = false; const t = holdTarget(e); if (!t) return;
    const pt = e.touches[0]; sx = pt.clientX; sy = pt.clientY; cancelHold();
    holdT = setTimeout(() => { held = true; if (navigator.vibrate) navigator.vibrate(15); openHold(t); }, 480);
  }, { passive: true, capture: true });
  document.addEventListener('touchmove', e => { const pt = e.touches[0]; if (Math.abs(pt.clientX - sx) > 10 || Math.abs(pt.clientY - sy) > 10) cancelHold(); }, { passive: true, capture: true });
  document.addEventListener('touchend', cancelHold, { passive: true, capture: true });
  document.addEventListener('touchcancel', cancelHold, { passive: true, capture: true });
  document.addEventListener('contextmenu', e => { const t = holdTarget(e); if (!t) return; e.preventDefault(); cancelHold(); openHold(t); }, true);
  document.addEventListener('click', e => { if (held && holdTarget(e)) { e.preventDefault(); e.stopPropagation(); held = false; } }, true);

  async function setting(cid, patch, msg) { try { await post('/api/fc/settings', Object.assign({ c: cid }, patch)); toast(msg); try { FCc().reloadList(); } catch (_) {} } catch (e) { toast(e.message); } }
  async function block(uid, on, name) {
    if (on && !confirm('Block ' + (name || 'this person') + '? They won\'t be able to message or call you.')) return;
    try { await post('/api/fcx/block', { user_id: uid, on }); toast(on ? 'Blocked' : 'Unblocked'); const pr = X.peers || {}; Object.keys(pr).forEach(k => { if (pr[k] && pr[k].user_id === uid) pr[k].blocked = on; }); } catch (e) { toast(e.message); }
  }
  function chatMenu(cid) {
    let c = null; try { c = (FCc().state().list || []).find(x => x.id === cid); } catch (_) {}
    if (!c) return;
    const p = (X.peers || {})[String(cid)] || {}, group = c.kind === 'group';
    const acts = [['pin', c.pinned ? '📌' : '📌', c.pinned ? 'Unpin chat' : 'Pin chat'], ['mute', '🔕', c.muted ? 'Unmute notifications' : 'Mute notifications'],
      ['arch', '🗂️', c.archived ? 'Unarchive chat' : 'Archive chat']];
    if (!group && p.user_id) acts.push(['block', '🚫', p.blocked ? 'Unblock ' + c.title : 'Block ' + c.title]);
    acts.push(['del', '🗑️', group ? 'Exit group and delete' : 'Delete chat']);
    sheet('<h3>' + esc(c.title) + '</h3><div class="fc-acts">' + acts.map(a => '<button class="fc-act" data-a="' + a[0] + '"' + (a[0] === 'del' ? ' style="color:#ff8a8a"' : '') + '><i>' + a[1] + '</i>' + esc(a[2]) + '</button>').join('') + '</div>', (el, done) => bind(el, {
      pin: () => { done(); setting(cid, { pinned: !c.pinned }, c.pinned ? 'Unpinned' : 'Pinned'); },
      mute: () => { done(); setting(cid, { muted: !c.muted }, c.muted ? 'Notifications on' : 'Muted'); },
      arch: () => { done(); setting(cid, { archived: !c.archived }, c.archived ? 'Unarchived' : 'Archived'); },
      block: () => { done(); block(p.user_id, !p.blocked, c.title); },
      del: async () => {
        done();
        if (!confirm(group ? 'Exit "' + c.title + '" and delete it from your chats?' : 'Delete your chat with ' + c.title + '? The messages are removed for you only. If they message you again, the chat comes back.')) return;
        try { await post('/api/fca/chat/delete', { c: cid }); toast(group ? 'You left the group' : 'Chat deleted'); FCc().reloadList(); } catch (e) { toast(e.message); }
      }
    }));
  }
  async function callMenu(i, rowEl) {
    let c = null; try { c = ((await api('/api/fcx/calls')).items || [])[i]; } catch (_) {}
    if (!c) return;
    const p = Object.values(X.peers || {}).find(x => x && x.user_id === c.other_id) || {};
    sheet('<h3>' + esc(c.name) + '</h3><div class="fc-acts">' +
      (c.conversation_id ? '<button class="fc-act" data-a="msg"><i>💬</i>Message</button><button class="fc-act" data-a="voice"><i>📞</i>Voice call</button><button class="fc-act" data-a="video"><i>🎥</i>Video call</button>' : '') +
      (c.other_id ? '<button class="fc-act" data-a="block"><i>🚫</i>' + (p.blocked ? 'Unblock ' : 'Block ') + esc(c.name) + '</button>' : '') +
      '<button class="fc-act" data-a="del" style="color:#ff8a8a"><i>🗑️</i>Delete from call history</button></div>', (el, done) => bind(el, {
        msg: () => { done(); FCc().openConv(c.conversation_id); },
        voice: () => { done(); FCc().callConv(c.conversation_id, 'voice'); }, video: () => { done(); FCc().callConv(c.conversation_id, 'video'); },
        block: () => { done(); block(c.other_id, !p.blocked, c.name); },
        del: async () => { done(); try { await post('/api/fcx/calls/delete', { id: c.id }); toast('Removed from call history'); if (rowEl) rowEl.remove(); } catch (e) { toast(e.message); } }
      }));
  }
  A.open = () => { openPanel(); go('you'); push(scrControl); };
  try { if (/[?&]fca=1/.test(location.search)) setTimeout(() => { me().then(m => { if (m && m.owner) A.open(); }); }, 1500); } catch (_) {}
})();
