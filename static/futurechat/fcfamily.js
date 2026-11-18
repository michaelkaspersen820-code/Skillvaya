/* Future Chat for families (FCF-01, owner 2026-11-19 "add all of that in").
   Family Circle home (members, notice board, coming up, shared lists, chores with stars and rewards, album with "On this day",
   bedtime stories, family quiz and Chatmoji puzzles, savings pot), "I'm home safe" / "Where are you?" check-ins,
   Emergency (SOS) button, Gogo mode (big and simple), family dates (anniversaries, gentle remembrance), parents & teens safety.
   Needs fcapp.js (FCX.kit). Server: fcfamily.py (/api/fcf/*). */
(function () {
  'use strict';
  const FCX = window.FCX; if (!window.SV_FC_APP || !FCX || !FCX.kit) return;
  const K = FCX.kit, { api, post, esc, $, toast, sheet, avatar, when, dueText, localInput, frame, push, pop, go, row, bind, openPanel, X, FC } = K;
  const fam = FCX.fam = {};
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const top = () => X.stack[X.stack.length - 1];
  const first = s => String(s || '').trim().split(/\s+/)[0] || '';
  const tok = () => { try { return localStorage.getItem('skillvaya_token') || localStorage.getItem('sv_token') || ''; } catch (_) { return ''; } };
  const curConv = () => { try { const st = FC().state(); if (!st || !st.conv) return null; return (st.list || []).find(c => c.id === st.conv) || { id: st.conv, title: '' }; } catch (_) { return null; } };
  const groups = () => { try { return (FC().state().list || []).filter(c => c.kind === 'group'); } catch (_) { return []; } };
  const directs = () => { try { return (FC().state().list || []).filter(c => c.kind !== 'group'); } catch (_) { return []; } };
  const refreshChat = () => { try { FC().refreshMsgs(); } catch (_) {} };
  function daysTo(d, m) { const n = new Date(); n.setHours(0, 0, 0, 0); let t = new Date(n.getFullYear(), m - 1, d); if (t < n) t = new Date(n.getFullYear() + 1, m - 1, d); return [t, Math.round((t - n) / 864e5)]; }
  const soonText = n => n === 0 ? 'Today' : n === 1 ? 'Tomorrow' : 'In ' + n + ' days';

  // ---------------------------------------------------------------- location (only when the person says yes)
  function getLoc(ms) {
    return new Promise(res => {
      if (!navigator.geolocation) return res(null);
      let done = false; const fin = v => { if (!done) { done = true; res(v); } };
      setTimeout(() => fin(null), ms || 8000);
      try { navigator.geolocation.getCurrentPosition(p => fin({ lat: p.coords.latitude, lng: p.coords.longitude }), () => fin(null), { enableHighAccuracy: true, timeout: ms || 8000, maximumAge: 60000 }); } catch (_) { fin(null); }
    });
  }
  const mapUrl = l => 'https://maps.google.com/?q=' + Number(l.lat) + ',' + Number(l.lng);

  // ---------------------------------------------------------------- check-ins
  function checkin(conv, kind) {
    if (!conv) return;
    const T = { safe: ['✅', 'I\'m home safe', 'Let everyone in this chat know you got home.'], ask: ['📍', 'Where are you?', 'Ask everyone in this chat to check in. They get a button to say they\'re safe.'], here: ['📍', 'Share where I am', 'Send your location to this chat once. It is not tracked after that.'] }[kind];
    sheet('<h3>' + T[0] + ' ' + esc(T[1]) + '</h3><p>' + esc(T[2]) + '</p><div class="fc-acts">' +
      (kind === 'ask' ? '<button class="fc-act" data-a="noloc"><i>📣</i>Send the question</button>'
        : '<button class="fc-act" data-a="loc"><i>📍</i>Send with my location</button><button class="fc-act" data-a="noloc"><i>' + T[0] + '</i>' + (kind === 'here' ? 'Cancel' : 'Send without location') + '</button>') + '</div>', (el, done) => bind(el, {
      loc: async b => { b.disabled = true; toast('Finding where you are…'); const l = await getLoc(9000); done(); if (!l) toast('Location is off — sent without it'); send(conv, kind, l); },
      noloc: () => { done(); if (kind !== 'here') send(conv, kind, null); }
    }));
  }
  async function send(conv, kind, l) {
    try { await post('/api/fcf/checkin', Object.assign({ c: conv, kind }, l || {})); toast(kind === 'ask' ? 'Asked ✓' : 'Sent ✓'); refreshChat(); } catch (e) { toast(e.message); }
  }
  fam.checkin = checkin;

  // ---------------------------------------------------------------- cards inside the chat
  FCX.special = function (m) {
    const t = m.meta || {}; const loc = t.loc && t.loc.lat != null ? t.loc : null;
    if (t.sos) return '<div class="fc-card fcf-sosc"><span class="k">🆘 EMERGENCY</span><b>' + esc(m.body.replace(/^🆘\s*/, '')) + '</b><small>' + esc(when(t.at || m.created_at)) + (loc ? '' : ' · location not shared') + '</small>' +
      (loc ? '<a class="pri" target="_blank" rel="noopener" href="' + mapUrl(loc) + '">📍 See where they are</a>' : '') + (t.phone && !m.mine ? '<a class="pri" href="tel:' + esc(t.phone) + '">📞 Call them now</a>' : '') +
      '<span class="fcf-nums">Police <a href="tel:10111">10111</a> · Ambulance <a href="tel:10177">10177</a> · Any phone <a href="tel:112">112</a></span></div>';
    if (t.checkin) {
      if (t.checkin === 'ask') return '<div class="fc-card"><span class="k">📍 CHECK-IN</span><b>' + esc(m.body.replace(/^📍\s*/, '').replace(/ Tap I'm safe$/, '')) + '</b>' + (m.mine ? '<small>Everyone gets a button to say they\'re safe.</small>' : '<button class="pri" onclick="event.stopPropagation();window.FCX.fam.reply(\'safe\')">✅ I\'m safe</button><button class="sec" onclick="event.stopPropagation();window.FCX.fam.reply(\'here\')">📍 Share where I am</button>') + '</div>';
      return '<div class="fc-card fcf-safe"><span class="k">' + (t.checkin === 'safe' ? '✅ HOME SAFE' : '📍 LOCATION') + '</span><b>' + esc(m.body.replace(/^(✅|📍)\s*/, '')) + '</b><small>' + esc(when(t.at || m.created_at)) + '</small>' + (loc ? '<a class="pri" target="_blank" rel="noopener" href="' + mapUrl(loc) + '">Open in Maps</a>' : '') + '</div>';
    }
    if (t.story) return '<div class="fc-card fcf-story"><span class="k">🌙 BEDTIME STORY</span><b>' + esc(t.story.t || 'A story for you') + '</b><small>' + (m.mine ? 'You recorded this story' : 'Press play above. Sweet dreams 💤') + '</small></div>';
    if (t.notice) return '<div class="fc-card"><span class="k">📌 NOTICE BOARD</span><b>' + esc(m.body.replace(/^📌 Notice board:\s*/, '')) + '</b></div>';
    if (t.fcf) {
      const k = t.fcf_kind, id = Number(t.fcf) || 0;
      const L = { list: ['🛒 SHARED LIST', 'Open list'], chore: ['🧹 CHORE', 'Open chores'], reward: ['🎁 REWARD', 'See rewards'], game: ['🎮 FAMILY QUIZ', 'Play now'] }[k] || ['ITEM', 'Open'];
      return '<div class="fc-card"><span class="k">' + L[0] + '</span><b>' + esc(m.body.replace(/^\S+\s*(New list:|New reward:|Chore for [^:]*:)?\s*/, '')) + '</b><button class="pri" onclick="event.stopPropagation();window.FCX.fam.open(\'' + k + '\',' + id + ')">' + L[1] + '</button></div>';
    }
    return '';
  };
  fam.reply = kind => { const c = curConv(); if (c) checkin(c.id, kind); };
  fam.open = (kind, id) => {
    const c = curConv();
    if (kind === 'list') return openList(id);
    if (kind === 'game') return playGame(id);
    if (c) { openPanel(); push(() => circleHome(c.id, c.title)); }
  };

  // ---------------------------------------------------------------- attach menu (paperclip) tiles
  const baseTiles = FCX.attachTiles;
  FCX.attachTiles = function (conv) {
    const t = baseTiles ? baseTiles(conv) : [];
    if (!conv || !conv.id) return t;
    return [['🏠', 'Home safe', '#15803d', () => checkin(conv.id, 'safe')], ['📍', 'Where are you?', '#0369a1', () => checkin(conv.id, 'ask')],
      ['🛒', 'List', '#0e7490', () => newList(conv.id)], ['🧹', 'Chore', '#a16207', () => choreForm(conv.id)],
      ['🌙', 'Bedtime story', '#4338ca', () => storyForm(conv.id)], ['🎮', 'Family quiz', '#be123c', () => gameForm(conv.id)]].concat(t);
  };

  // ---------------------------------------------------------------- FAMILY CIRCLE HOME
  async function circleHome(id, title) {
    const self = top();
    const bd = frame(title || 'Circle', 'Family Circle');
    bd.innerHTML = '<div class="fca-empty">Loading your Circle…</div>';
    let d; try { d = await api('/api/fcf/circle?c=' + id); } catch (e) { bd.innerHTML = '<div class="fca-empty"><b>Couldn\'t load</b>' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    const again = () => { if (top() === self) circleHome(id, title); };
    const me = (X.me || {}).id;
    let h = '<div class="fcf-mem">' + d.members.map(p => { const b = p.birthday ? daysTo(p.birthday.d, p.birthday.m)[1] : 99; return '<span>' + avatar(p.name, p.photo, 'sm') + '<small>' + esc(p.id === me ? 'You' : first(p.name)) + (b <= 7 ? ' 🎂' : '') + '</small></span>'; }).join('') + '</div>';
    h += '<div class="fca-acts fcf-quick">' + [['chat', '💬', 'Chat'], ['call', '📞', 'Call'], ['video', '🎥', 'Video'], ['safe', '🏠', 'Home safe'], ['ask', '📍', 'Where are you?'], ['album', '🖼️', 'Album'], ['plans', '📅', 'Plans'], ['pot', '💰', 'Savings pot'], ['quiz', '🎮', 'Quiz']]
      .map(([a, i, l]) => '<button class="fca-act" data-a="' + a + '"><i>' + i + '</i>' + l + '</button>').join('') + '</div>';
    // notice board
    h += '<div class="fca-gl">📌 Notice board</div>' + (d.notice ? '<button type="button" class="fcf-board" data-a="notice"><b>' + esc(d.notice.text) + '</b><small>' + esc(d.notice.by ? d.notice.by + ' · ' : '') + esc(when(d.notice.at)) + ' · tap to change</small></button>'
      : '<button type="button" class="fcf-board empty" data-a="notice"><b>Pin a note for everyone</b><small>e.g. "Gogo\'s birthday lunch Sunday 1pm" or the Wi-Fi password</small></button>');
    // coming up
    const up = [];
    (d.coming || []).forEach(i => up.push([new Date(i.due_at), ({ event: '📅', reminder: '⏰', task: '✅', chore: '🧹' }[i.kind] || '•'), i.title, dueText(i.due_at), 'item', i.id]));
    d.members.forEach(p => { if (!p.birthday) return; const [t, n] = daysTo(p.birthday.d, p.birthday.m); if (n <= 31) up.push([t, '🎂', (p.id === me ? 'Your' : first(p.name) + '\'s') + ' birthday', soonText(n), 'bday', p.id]); });
    (d.dates || []).forEach(x => { const [t, n] = daysTo(x.d, x.m); if (n <= 31) up.push([t, x.kind === 'remembrance' ? '🕯️' : x.kind === 'anniversary' ? '💍' : '🎉', x.title, soonText(n), 'date', x.id]); });
    up.sort((a, b) => a[0] - b[0]);
    h += '<div class="fca-gl">Coming up</div>' + (up.length ? '<div class="fca-card">' + up.slice(0, 10).map(u => row(u[1], u[2], u[3], { data: 'data-up="' + u[4] + '" data-id="' + u[5] + '"' })).join('') + '</div>' : '<div class="fca-empty" style="padding:16px">Nothing in the next month. Add a meeting, reminder or family date.</div>');
    // lists
    h += '<div class="fca-gl">🛒 Shared lists</div><div class="fca-card">' + (d.lists || []).map(l => row('🛒', l.title, l.count ? (l.count - l.done) + ' to get · ' + l.done + ' done' : 'Empty — tap to add', { data: 'data-list="' + l.id + '"' })).join('') + row('➕', 'New list', 'Shopping, packing, braai — everyone can add', { data: 'data-a="newlist"' }) + '</div>';
    // chores + stars + rewards
    h += '<div class="fca-gl">🧹 Chores and ⭐ stars</div><div class="fca-card">' + (d.chores || []).map(c => '<div class="fca-item' + (c.done ? ' done' : '') + '"><button class="ck' + (c.done ? ' on' : '') + '" data-chore="' + c.id + '" aria-label="Done">' + (c.done ? '✓' : '') + '</button><div class="tx"><b>' + esc(c.title) + '</b><small>' + esc(c.assignee_name) + ' · ' + c.stars + ' ⭐' + (c.due_at ? ' · ' + esc(dueText(c.due_at)) : '') + '</small></div></div>').join('') +
      row('➕', 'Add a chore', 'Give stars for jobs well done', { data: 'data-a="chore"' }) + '</div>';
    if ((d.stars || []).length) h += '<div class="fcf-stars">' + d.stars.slice(0, 6).map((s, i) => '<span><b>' + (['🥇', '🥈', '🥉'][i] || '⭐') + '</b>' + esc(s.user_id === me ? 'You' : first(s.name)) + '<em>' + s.points + ' ⭐</em></span>').join('') + '</div>';
    h += '<div class="fca-card">' + (d.rewards || []).map(r => row('🎁', r.title, r.cost + ' ⭐' + (d.my_stars >= r.cost ? ' · you can claim it' : ''), { data: 'data-rw="' + r.id + '"' }, '<span class="fc-chip fcf-claim">' + (d.my_stars >= r.cost ? 'Claim' : r.cost + ' ⭐') + '</span>')).join('') +
      row('🎁', 'Add a reward', 'e.g. Choose Friday\'s movie · 10 ⭐', { data: 'data-a="reward"' }) + '</div><p class="fca-note">You have ' + (d.my_stars || 0) + ' ⭐ in this Circle.</p>';
    // stories + games
    h += '<div class="fca-gl">🌙 Bedtime stories</div><div class="fca-card">' + (d.stories || []).slice(0, 6).map(s => row('🌙', s.title, 'by ' + s.by + ' · ' + when(s.at), { data: 'data-story="' + s.id + '"' })).join('') + row('🎙️', 'Record a bedtime story', 'Far away tonight? Read them a story anyway', { data: 'data-a="story"' }) + '</div>';
    h += '<div class="fca-gl">🎮 Family games</div><div class="fca-card">' + (d.games || []).slice(0, 4).map(g => row('🎮', g.title, when(g.at), { data: 'data-game="' + g.id + '"' })).join('') + row('➕', 'Start a quiz or Chatmoji puzzle', 'Everyone plays on their own phone, scores in the chat', { data: 'data-a="quiz"' }) + '</div>';
    h += '<div class="fca-card">' + row('💍', 'Family dates', 'Anniversaries and days we remember', { data: 'data-a="dates"' }) + '</div>';
    bd.innerHTML = h;
    bind(bd, {
      chat: () => FC().openConv(id), call: () => FC().callConv(id, 'voice'), video: () => FC().callConv(id, 'video'),
      safe: () => checkin(id, 'safe'), ask: () => checkin(id, 'ask'), album: () => push(() => scrAlbum(id, title)), plans: () => push(() => K.scrCirclePlans(id, title)),
      pot: () => { FC().openConv(id); setTimeout(() => { try { FC().stokvel(); } catch (_) {} }, 900); }, quiz: () => gameForm(id, again),
      notice: () => noticeForm(id, d.notice, again), newlist: () => newList(id, again), chore: () => choreForm(id, again, d.members), reward: () => rewardForm(id, again),
      story: () => storyForm(id), dates: () => push(scrDates)
    });
    bd.querySelectorAll('[data-list]').forEach(b => b.onclick = () => openList(Number(b.dataset.list), again));
    bd.querySelectorAll('[data-chore]').forEach(b => b.onclick = async () => { try { const r = await post('/api/fcf/chore/done', { id: Number(b.dataset.chore) }); if (r.done) { toast('Well done! ⭐'); K.confetti('⭐'); } again(); } catch (e) { toast(e.message); } });
    bd.querySelectorAll('[data-rw]').forEach(b => b.onclick = async () => { const r = (d.rewards || []).find(x => x.id === Number(b.dataset.rw)); if (!confirm('Use ' + r.cost + ' ⭐ for "' + r.title + '"?')) return; try { await post('/api/fcf/reward/redeem', { id: r.id }); toast('Enjoy! 🎁'); K.confetti('🎁'); again(); } catch (e) { toast(e.message); } });
    bd.querySelectorAll('[data-story]').forEach(b => b.onclick = () => { const s = d.stories.find(x => x.id === Number(b.dataset.story)); playStory(s); });
    bd.querySelectorAll('[data-game]').forEach(b => b.onclick = () => playGame(Number(b.dataset.game), again));
    bd.querySelectorAll('[data-up]').forEach(b => b.onclick = () => { const k = b.dataset.up; if (k === 'item') K.itemSheet(Number(b.dataset.id), again); else if (k === 'date') push(scrDates); else push(K.scrCelebrations); });
  }
  FCX.circleHome = circleHome;
  fam.home = circleHome;

  function noticeForm(id, cur, after) {
    sheet('<h3>📌 Notice board</h3><p>Everyone in this Circle sees it at the top of the Circle.</p><label class="fca-field"><span>Note</span><textarea id="fcfN" rows="4" maxlength="1000">' + esc(cur ? cur.text : '') + '</textarea></label><button class="fc-btn" id="fcfNGo">Pin it</button>' + (cur ? '<button class="fc-btn sec" id="fcfNRm">Clear the board</button>' : ''), (el, done) => {
      const save = async text => { try { await post('/api/fcf/notice', { c: id, text }); done(); toast(text ? 'Pinned 📌' : 'Cleared'); if (after) after(); refreshChat(); } catch (e) { toast(e.message); } };
      $('#fcfNGo', el).onclick = () => save($('#fcfN', el).value.trim()); const rm = $('#fcfNRm', el); if (rm) rm.onclick = () => save('');
    });
  }

  // ---------------------------------------------------------------- shared live lists
  function newList(conv, after) {
    sheet('<h3>🛒 New shared list</h3><p>Everyone in the chat can add and tick things off. It updates live.</p><label class="fca-field"><span>List name</span><input id="fcfLT" maxlength="80" placeholder="e.g. Shopping · Holiday packing · Braai"></label><button class="fc-btn" id="fcfLGo">Create list</button>', (el, done) => {
      setTimeout(() => { try { $('#fcfLT', el).focus(); } catch (_) {} }, 60);
      $('#fcfLGo', el).onclick = async () => { try { const r = await post('/api/fcf/list', { c: conv, title: $('#fcfLT', el).value }); done(); refreshChat(); if (after) after(); openList(r.id, after); } catch (e) { toast(e.message); } };
    });
  }
  function openList(id, after) { openPanel(); push(() => scrList(id, after)); }
  async function scrList(id, after) {
    const self = top();
    let d; try { d = await api('/api/fcf/list/' + id); } catch (e) { const bd = frame('List', ''); bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    const bd = frame(d.title, 'Shared list · updates live', d.mine ? { action: ['🗑️', 'Delete list', async () => { if (!confirm('Delete this list for everyone?')) return; try { await post('/api/fcf/list/delete', { id }); toast('List deleted'); pop(); if (after) after(); } catch (e) { toast(e.message); } }] } : null);
    const paint = () => {
      const open = d.entries.filter(e => !e.done), got = d.entries.filter(e => e.done);
      const one = e => '<div class="fca-item' + (e.done ? ' done' : '') + '"><button class="ck' + (e.done ? ' on' : '') + '" data-t="' + e.id + '">' + (e.done ? '✓' : '') + '</button><div class="tx"><b>' + esc(e.text) + '</b><small>' + esc(e.by) + '</small></div><button class="fcf-x" data-r="' + e.id + '" aria-label="Remove">✕</button></div>';
      $('#fcfLB', bd).innerHTML = (open.length ? '<div class="fca-card">' + open.map(one).join('') + '</div>' : '<div class="fca-empty" style="padding:16px">Nothing on the list. Add the first thing above.</div>') + (got.length ? '<div class="fca-gl">Got it</div><div class="fca-card">' + got.map(one).join('') + '</div>' : '');
      bd.querySelectorAll('[data-t]').forEach(b => b.onclick = async () => { try { await post('/api/fcf/list/toggle', { entry: Number(b.dataset.t) }); reload(); } catch (e) { toast(e.message); } });
      bd.querySelectorAll('[data-r]').forEach(b => b.onclick = async () => { const e = d.entries.find(x => x.id === Number(b.dataset.r)); if (e && e.by && e.by !== (X.me || {}).name && !confirm('Take "' + e.text + '" off the list? ' + first(e.by) + ' added it.')) return; try { await post('/api/fcf/list/remove', { entry: Number(b.dataset.r) }); reload(); } catch (e) { toast(e.message); } });
    };
    const reload = async () => { try { d = await api('/api/fcf/list/' + id); if (top() === self) paint(); } catch (_) {} };
    bd.innerHTML = '<div class="fcf-add"><input id="fcfLI" maxlength="200" placeholder="Add something… e.g. milk"><button id="fcfLA" class="fca-ib" aria-label="Add">＋</button></div><p class="fca-note" style="margin:-4px 2px 10px">Tick what you got. Anyone can take something off with ✕ — e.g. when there\'s no money for sweets this week.</p><div id="fcfLB"></div>';
    const add = async () => { const i = $('#fcfLI', bd); const t = i.value.trim(); if (!t) return; i.value = ''; try { await post('/api/fcf/list/add', { id, text: t }); reload(); } catch (e) { toast(e.message); } i.focus(); };
    $('#fcfLA', bd).onclick = add; $('#fcfLI', bd).onkeydown = e => { if (e.key === 'Enter') add(); };
    paint();
    const live = setInterval(() => { if (top() !== self || !document.getElementById('fcfLB')) return clearInterval(live); if (document.visibilityState !== 'hidden') reload(); }, 5000);
  }

  // ---------------------------------------------------------------- chores and rewards
  async function choreForm(conv, after, members) {
    if (!members) { try { members = (await api('/api/fcf/circle?c=' + conv)).members; } catch (e) { toast(e.message); return; } }
    sheet('<h3>🧹 New chore</h3><label class="fca-field"><span>What needs doing?</span><input id="fcfCT" maxlength="120" placeholder="e.g. Wash the dishes"></label>' +
      '<label class="fca-field"><span>Who?</span><select id="fcfCA"><option value="0">Anyone</option>' + members.map(m => '<option value="' + m.id + '">' + esc(m.name) + '</option>').join('') + '</select></label>' +
      '<label class="fca-field"><span>Stars for doing it</span><select id="fcfCS">' + [1, 2, 3, 5, 10].map(n => '<option' + (n === 2 ? ' selected' : '') + '>' + n + '</option>').join('') + '</select></label>' +
      '<label class="fca-field"><span>By when (optional)</span><input id="fcfCD" type="datetime-local"></label><button class="fc-btn" id="fcfCGo">Add chore</button>', (el, done) => {
      $('#fcfCGo', el).onclick = async () => { const dv = $('#fcfCD', el).value; try { await post('/api/fcf/chore', { c: conv, title: $('#fcfCT', el).value, assignee: Number($('#fcfCA', el).value), stars: Number($('#fcfCS', el).value), due_at: dv ? new Date(dv).toISOString() : '' }); done(); toast('Chore added 🧹'); refreshChat(); if (after) after(); } catch (e) { toast(e.message); } };
    });
  }
  function rewardForm(conv, after) {
    sheet('<h3>🎁 New reward</h3><p>Anyone with enough ⭐ can claim it. The stars are taken off and everyone sees it in the chat.</p><label class="fca-field"><span>Reward</span><input id="fcfRT" maxlength="120" placeholder="e.g. Choose Friday\'s movie · R50 airtime"></label>' +
      '<label class="fca-field"><span>Costs (⭐)</span><select id="fcfRC">' + [3, 5, 10, 15, 20, 30, 50].map(n => '<option' + (n === 10 ? ' selected' : '') + '>' + n + '</option>').join('') + '</select></label><button class="fc-btn" id="fcfRGo">Add reward</button>', (el, done) => {
      $('#fcfRGo', el).onclick = async () => { try { await post('/api/fcf/reward', { c: conv, title: $('#fcfRT', el).value, cost: Number($('#fcfRC', el).value) }); done(); toast('Reward added 🎁'); if (after) after(); } catch (e) { toast(e.message); } };
    });
  }

  // ---------------------------------------------------------------- family album + "On this day"
  let dbP = null;
  function mediaDb() { if (dbP) return dbP; dbP = new Promise(res => { try { const r = indexedDB.open('futurechat_media', 1); r.onupgradeneeded = () => r.result.createObjectStore('files'); r.onsuccess = () => res(r.result); r.onerror = () => res(null); } catch (_) { res(null); } }); return dbP; }
  async function blob(id) {
    const db = await mediaDb();
    const kept = db ? await new Promise(res => { try { const q = db.transaction('files').objectStore('files').get(id); q.onsuccess = () => res(q.result || null); q.onerror = () => res(null); } catch (_) { res(null); } }) : null;
    if (kept) return URL.createObjectURL(kept);
    const r = await fetch('/api/fc/file/' + id, { headers: { Authorization: 'Bearer ' + tok() }, credentials: 'same-origin' });
    if (!r.ok) throw new Error(r.status === 410 ? 'gone' : 'fail');
    const b = await r.blob(); try { if (db) db.transaction('files', 'readwrite').objectStore('files').put(b, id); } catch (_) {}
    return URL.createObjectURL(b);
  }
  async function scrAlbum(id, title) {
    const self = top();
    const bd = frame('Family album', title || ''); bd.innerHTML = '<div class="fca-empty">Loading photos…</div>';
    let items = []; try { items = (await api('/api/fcf/album?c=' + id)).items || []; } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    if (!items.length) { bd.innerHTML = '<div class="fca-empty"><span class="big">🖼️</span><b>No photos yet</b>Photos and videos shared in this chat collect here, so the whole family can look back on them.</div>'; return; }
    const n = new Date(); const otd = items.filter(i => { const d = new Date(i.at); return d.getDate() === n.getDate() && d.getMonth() === n.getMonth() && d.getFullYear() < n.getFullYear(); });
    const tile = i => '<button class="fcf-ph" data-p="' + i.id + '" data-v="' + (i.video ? 1 : 0) + '">' + (i.video ? '<em>▶</em>' : '') + '</button>';
    let h = '';
    if (otd.length) h += '<div class="fca-hero" style="background:linear-gradient(135deg,#7c2d12,#f59e0b)"><small>✨ ON THIS DAY</small><b>' + otd.length + (otd.length === 1 ? ' memory' : ' memories') + ' from this day in earlier years</b></div><div class="fcf-grid">' + otd.map(tile).join('') + '</div>';
    const byMonth = {}; items.forEach(i => { const d = new Date(i.at); const k = MONTHS[d.getMonth()] + ' ' + d.getFullYear(); (byMonth[k] = byMonth[k] || []).push(i); });
    Object.keys(byMonth).forEach(k => { h += '<div class="fca-gl">' + esc(k) + '</div><div class="fcf-grid">' + byMonth[k].map(tile).join('') + '</div>'; });
    h += '<p class="fca-note">Photos live on the phones they were sent to. If one shows a grey square, it was saved before this phone joined the chat.</p>';
    bd.innerHTML = h;
    const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { io.unobserve(e.target); fill(e.target); } }), { root: document.getElementById('fcaPanel') }) : null;
    const fill = async el => { try { const u = await blob(Number(el.dataset.p)); el.dataset.u = u; if (el.dataset.v === '1') el.insertAdjacentHTML('afterbegin', '<video src="' + u + '" muted playsinline preload="metadata"></video>'); else el.style.backgroundImage = 'url(\'' + u + '\')'; } catch (_) { el.classList.add('gone'); } };
    bd.querySelectorAll('.fcf-ph').forEach(el => { if (io) io.observe(el); else fill(el); el.onclick = () => { const u = el.dataset.u; if (!u) return; sheet(el.dataset.v === '1' ? '<video src="' + u + '" controls autoplay playsinline style="width:100%;border-radius:14px"></video>' : '<img src="' + u + '" style="width:100%;border-radius:14px" alt="Photo">'); }; });
  }

  // ---------------------------------------------------------------- bedtime stories (voice or video)
  function storyForm(conv) {
    sheet('<h3>🌙 Bedtime story</h3><p>Record yourself reading a story or singing a lullaby. It arrives in the chat, ready to play at bedtime.</p><label class="fca-field"><span>Story name</span><input id="fcfST" maxlength="80" placeholder="e.g. The Three Little Pigs"></label>' +
      '<div class="fc-acts"><button class="fc-act" data-a="voice"><i>🎙️</i>Record my voice</button><button class="fc-act" data-a="video"><i>🎥</i>Record or choose a video</button></div>', (el, done) => {
      const t = () => $('#fcfST', el).value.trim() || 'Bedtime story';
      bind(el, { voice: () => { const title = t(); done(); recordStory(conv, title); }, video: () => { const title = t(); done(); pickVideo(conv, title); } });
    });
  }
  const b64 = b => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] || ''); r.onerror = rej; r.readAsDataURL(b); });
  async function sendStory(conv, title, kind, file) {
    if (file.size > 16 * 1024 * 1024) { toast('That is too long. Keep stories under about 15 minutes of voice or 1 minute of video.'); return; }
    toast('Sending your story…');
    try { await post('/api/fc/send', { c: conv, kind, body: '🌙 Bedtime story: ' + title, meta: { story: { t: title } }, files: [{ filename: (kind === 'voice' ? 'story.' : 'story-video.') + ((file.type.split('/')[1] || 'webm').split(';')[0]), mime_type: file.type || (kind === 'voice' ? 'audio/webm' : 'video/mp4'), data_base64: await b64(file) }] }); toast('Story sent 🌙'); refreshChat(); }
    catch (e) { toast(e.message); }
  }
  async function recordStory(conv, title) {
    let stream; try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (_) { toast('Allow the microphone for Future Chat to record a story'); return; }
    let rec; try { rec = new MediaRecorder(stream); } catch (_) { stream.getTracks().forEach(t => t.stop()); toast('Recording is not supported on this phone'); return; }
    const parts = []; let cancel = false; const t0 = Date.now();
    rec.ondataavailable = e => { if (e.data && e.data.size) parts.push(e.data); };
    const dim = sheet('<h3>🌙 ' + esc(title) + '</h3><div class="fcf-rec"><span class="dot"></span><b id="fcfRT2">0:00</b></div><p>Read slowly and enjoy it. Up to 15 minutes.</p><button class="fc-btn" data-a="stop">⏹ Finish and send</button><button class="fc-btn sec" data-a="no">Cancel</button>', (el, done) => {
      const tick = setInterval(() => { const s = Math.floor((Date.now() - t0) / 1000); const e = $('#fcfRT2', el); if (e) e.textContent = Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); if (s >= 900 && rec.state === 'recording') rec.stop(); }, 500);
      rec.onstop = () => { clearInterval(tick); stream.getTracks().forEach(t => t.stop()); done(); if (!cancel && parts.length) sendStory(conv, title, 'voice', new Blob(parts, { type: rec.mimeType || 'audio/webm' })); };
      bind(el, { stop: () => rec.state === 'recording' && rec.stop(), no: () => { cancel = true; if (rec.state === 'recording') rec.stop(); else done(); } });
    });
    dim.addEventListener('click', e => { if (e.target === dim) { cancel = true; try { rec.stop(); } catch (_) {} } });
    rec.start(1000);
  }
  function pickVideo(conv, title) {
    const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'video/*'; inp.setAttribute('capture', 'user'); inp.style.display = 'none';
    inp.onchange = () => { const f = inp.files && inp.files[0]; if (f) sendStory(conv, title, 'video', f); inp.remove(); };
    document.body.appendChild(inp); inp.click();
  }
  async function playStory(s) {
    if (!s || !s.att || !s.att.length) { toast('Open the chat to play this story'); return; }
    try { const u = await blob(s.att[0]); sheet('<h3>🌙 ' + esc(s.title) + '</h3><p>by ' + esc(s.by) + '</p><video src="' + u + '" controls autoplay playsinline style="width:100%;border-radius:14px;background:#000;max-height:60vh"></video>'); }
    catch (_) { toast('This story is saved on the phones it was sent to'); }
  }

  // ---------------------------------------------------------------- family games (questions are append-only: games keep their numbers)
  const PACKS = {
    gk: ['🧠 Everyone quiz', [
      ['How many continents are there?', ['5', '6', '7', '8'], 2], ['Which is the biggest planet?', ['Earth', 'Jupiter', 'Saturn', 'Mars'], 1], ['How many legs does a spider have?', ['6', '8', '10', '12'], 1],
      ['What do bees make?', ['Milk', 'Honey', 'Silk', 'Wax only'], 1], ['At what temperature does water freeze?', ['0 °C', '10 °C', '-10 °C', '100 °C'], 0], ['Which is the largest ocean?', ['Atlantic', 'Indian', 'Arctic', 'Pacific'], 3],
      ['How many days are in a leap year?', ['364', '365', '366', '367'], 2], ['Blue and yellow make which colour?', ['Purple', 'Orange', 'Green', 'Brown'], 2], ['Which is the fastest land animal?', ['Lion', 'Cheetah', 'Horse', 'Springbok'], 1],
      ['Which planet is called the Red Planet?', ['Venus', 'Mars', 'Mercury', 'Jupiter'], 1], ['How many sides does a hexagon have?', ['5', '6', '7', '8'], 1], ['Which gas do plants take in from the air?', ['Oxygen', 'Carbon dioxide', 'Helium', 'Nitrogen'], 1],
      ['Which is the tallest animal?', ['Elephant', 'Giraffe', 'Camel', 'Ostrich'], 1], ['What is the capital of France?', ['Rome', 'Madrid', 'Paris', 'Berlin'], 2], ['How many players does a soccer team have on the field?', ['9', '10', '11', '12'], 2],
      ['Who painted the Mona Lisa?', ['Picasso', 'Leonardo da Vinci', 'Van Gogh', 'Michelangelo'], 1], ['What is H₂O?', ['Salt', 'Water', 'Air', 'Sugar'], 1], ['Which is the longest river in Africa?', ['Congo', 'Zambezi', 'Nile', 'Orange'], 2],
      ['How many colours are in a rainbow?', ['5', '6', '7', '8'], 2], ['Which is the biggest animal that has ever lived?', ['Blue whale', 'T. rex', 'Elephant', 'Giant squid'], 0], ['Which instrument usually has 88 keys?', ['Guitar', 'Piano', 'Violin', 'Drum'], 1],
      ['What is the smallest prime number?', ['0', '1', '2', '3'], 2], ['Which country is home to the kangaroo?', ['Brazil', 'Australia', 'Kenya', 'India'], 1], ['What is the hardest natural material?', ['Gold', 'Iron', 'Diamond', 'Granite'], 2],
      ['Which planet is closest to the sun?', ['Mercury', 'Venus', 'Earth', 'Mars'], 0], ['How many minutes are in an hour?', ['30', '60', '90', '100'], 1], ['What do caterpillars turn into?', ['Bees', 'Butterflies or moths', 'Beetles', 'Spiders'], 1],
      ['How many hours are in a day?', ['12', '20', '24', '30'], 2], ['Which shape has three sides?', ['Square', 'Circle', 'Triangle', 'Pentagon'], 2], ['What is the opposite of "ancient"?', ['Old', 'Modern', 'Broken', 'Tall'], 1]]],
    za: ['🇿🇦 South Africa', [
      ['How many official languages does South Africa have?', ['9', '11', '12', '14'], 2], ['In which city does Parliament sit?', ['Pretoria', 'Cape Town', 'Durban', 'Bloemfontein'], 1], ['What is the national rugby team called?', ['Proteas', 'Bafana Bafana', 'Springboks', 'Lions'], 2],
      ['What is South Africa\'s national animal?', ['Lion', 'Springbok', 'Elephant', 'Kudu'], 1], ['What is the national flower?', ['King protea', 'Rose', 'Sunflower', 'Strelitzia'], 0], ['In which year was South Africa\'s first democratic election?', ['1990', '1994', '1999', '2004'], 1],
      ['Who was the first democratically elected president?', ['Thabo Mbeki', 'Nelson Mandela', 'F. W. de Klerk', 'Jacob Zuma'], 1], ['What is the currency?', ['Pula', 'Rand', 'Kwacha', 'Shilling'], 1], ['Which city is called eGoli, the place of gold?', ['Durban', 'Johannesburg', 'Kimberley', 'Polokwane'], 1],
      ['Which flat-topped mountain overlooks Cape Town?', ['Lion\'s Head', 'Table Mountain', 'Drakensberg', 'Kilimanjaro'], 1], ['When is Freedom Day?', ['16 June', '27 April', '24 September', '16 December'], 1], ['Which famous game reserve is in Limpopo and Mpumalanga?', ['Addo', 'Kruger National Park', 'Pilanesberg', 'Etosha'], 1],
      ['Bafana Bafana play which sport?', ['Rugby', 'Cricket', 'Soccer', 'Netball'], 2], ['Which ocean is on the east coast?', ['Atlantic', 'Indian', 'Pacific', 'Southern only'], 1], ['What is the national bird?', ['Ostrich', 'Blue crane', 'Fish eagle', 'Hadeda'], 1],
      ['How many provinces are there?', ['7', '8', '9', '10'], 2], ['When is Heritage Day?', ['24 September', '9 August', '1 May', '21 March'], 0], ['Which Archbishop won the Nobel Peace Prize in 1984?', ['Desmond Tutu', 'Steve Biko', 'Albert Luthuli', 'Walter Sisulu'], 0],
      ['What is a braai?', ['A dance', 'A barbecue', 'A hat', 'A song'], 1], ['What is the highest mountain range?', ['Magaliesberg', 'Drakensberg', 'Cederberg', 'Outeniqua'], 1]]],
    emoji: ['✦ Chatmoji puzzles', [
      ['🌧️🐱🐶', ['Raining cats and dogs', 'Pet shop', 'Wet weekend', 'Storm chasers'], 0], ['⏰💰', ['Pay day', 'Time is money', 'Late fee', 'Alarm clock'], 1], ['🍰👌', ['Birthday party', 'Piece of cake', 'Bake sale', 'Sweet tooth'], 1],
      ['☀️👓', ['Sunglasses', 'Daylight', 'Sunrise', 'Eye test'], 0], ['❄️⛄', ['Ice cream', 'Snowman', 'Winter coat', 'Cold drink'], 1], ['🍯🌙', ['Honeymoon', 'Night snack', 'Bee hive', 'Moonlight'], 0],
      ['🌲🍎', ['Apple tree', 'Pineapple', 'Forest fruit', 'Orchard'], 1], ['⭐🐟', ['Goldfish', 'Starfish', 'Fish and chips', 'Night fishing'], 1], ['🔥🚒', ['Fire truck', 'Hot car', 'Firework', 'Fast lane'], 0],
      ['🧈🪰', ['Butterfly', 'Dragonfly', 'Bread fly', 'Bee'], 0], ['🍿🎬', ['Popcorn machine', 'Movie night', 'Corn field', 'Cinema queue'], 1], ['🎂🕯️', ['Candle shop', 'Birthday', 'Power cut', 'Bakery'], 1],
      ['🌊🏄', ['Surfing', 'Boat trip', 'Fishing', 'Swimming pool'], 0], ['🐶🏠', ['Dog house', 'Home alone', 'Vet', 'Pet sitter'], 0], ['✋👜', ['Shopping', 'Handbag', 'Pickpocket', 'Glove'], 1],
      ['💙🌙', ['Once in a blue moon', 'Good night', 'Cold night', 'Blue sky'], 0], ['🍎📅👨‍⚕️', ['Doctor\'s appointment', 'An apple a day keeps the doctor away', 'Fruit market', 'Healthy week'], 1], ['🐘🧠', ['An elephant never forgets', 'Big head', 'Smart zoo', 'Heavy thinking'], 0],
      ['🥚🌱', ['Eggplant', 'Easter', 'Breakfast', 'Garden'], 0], ['☔🎀', ['Rainbow', 'Gift wrap', 'Rain dance', 'Wet hair'], 0]]]
  };
  function gameForm(conv, after) {
    sheet('<h3>🎮 Family quiz</h3><p>Everyone plays on their own phone. Scores go in the chat.</p><div class="fc-acts">' + Object.keys(PACKS).map(k => '<button class="fc-act" data-p="' + k + '"><i>' + PACKS[k][0].split(' ')[0] + '</i>' + esc(PACKS[k][0].replace(/^\S+\s/, '')) + '</button>').join('') + '</div>' +
      '<div class="fca-seg" style="margin-top:10px"><button data-n="5" class="on">5 questions</button><button data-n="10">10 questions</button></div>', (el, done) => {
      let n = 5; el.querySelectorAll('[data-n]').forEach(b => b.onclick = () => { n = Number(b.dataset.n); el.querySelectorAll('[data-n]').forEach(x => x.classList.toggle('on', x === b)); });
      el.querySelectorAll('[data-p]').forEach(b => b.onclick = async () => {
        const k = b.dataset.p, all = PACKS[k][1].map((_, i) => i); for (let i = all.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [all[i], all[j]] = [all[j], all[i]]; }
        try { const r = await post('/api/fcf/game', { c: conv, title: PACKS[k][0].replace(/^\S+\s/, ''), pack: k, qs: all.slice(0, n) }); done(); refreshChat(); if (after) after(); playGame(r.id, after); } catch (e) { toast(e.message); }
      });
    });
  }
  async function playGame(id, after) {
    let g; try { g = await api('/api/fcf/game/' + id); } catch (e) { toast(e.message); return; }
    const pack = PACKS[g.pack] || PACKS.gk; const qs = g.qs.map(i => pack[1][i]).filter(Boolean);
    const board = () => '<div class="fca-card">' + (g.scores.length ? g.scores.map((s, i) => row(['🥇', '🥈', '🥉'][i] || '🎮', s.me ? 'You' : s.name, s.score + ' / ' + qs.length, {}, '')).join('') : row('⏳', 'No scores yet', 'Be the first to play', {}, '')) + '</div>';
    if (g.played) { sheet('<h3>🎮 ' + esc(pack[0]) + '</h3><p>You already played. Here\'s the scoreboard:</p>' + board()); return; }
    let i = 0, score = 0;
    sheet('<div id="fcfQ"></div>', (el, done) => {
      const box = $('#fcfQ', el);
      const show = () => {
        if (i >= qs.length) {
          box.innerHTML = '<h3>' + (score === qs.length ? '🏆 Perfect!' : score >= qs.length / 2 ? '🎉 Well played!' : '👏 Nice try!') + '</h3><p class="fcf-score">' + score + ' / ' + qs.length + '</p><p>Your score was posted in the chat.</p>';
          post('/api/fcf/game/score', { id, score }).then(async () => { refreshChat(); if (after) after(); try { g = await api('/api/fcf/game/' + id); box.insertAdjacentHTML('beforeend', board()); } catch (_) {} }).catch(e => toast(e.message));
          if (score === qs.length) K.confetti('🏆'); return;
        }
        const q = qs[i];
        box.innerHTML = '<small class="fcf-qn">' + esc(pack[0]) + ' · question ' + (i + 1) + ' of ' + qs.length + '</small><h3 class="' + (g.pack === 'emoji' ? 'fcf-emoji' : '') + '">' + esc(q[0]) + '</h3>' + (g.pack === 'emoji' ? '<p>What does this mean?</p>' : '') +
          '<div class="fcf-opts">' + q[1].map((o, j) => '<button data-o="' + j + '">' + esc(o) + '</button>').join('') + '</div>';
        box.querySelectorAll('[data-o]').forEach(b => b.onclick = () => {
          const j = Number(b.dataset.o); box.querySelectorAll('[data-o]').forEach(x => { x.disabled = true; if (Number(x.dataset.o) === q[2]) x.classList.add('ok'); });
          if (j === q[2]) score++; else b.classList.add('no');
          setTimeout(() => { i++; show(); }, 900);
        });
      };
      show();
    });
  }

  // ---------------------------------------------------------------- EMERGENCY (SOS)
  function sosScreen() {
    const bd = frame('Emergency', 'Hold the button for 3 seconds');
    const p = X.prefs || {}; const chosen = (p.sos || []).length;
    bd.innerHTML = '<div class="fcf-sosw"><button type="button" class="fcf-sos" id="fcfSos" aria-label="Hold for 3 seconds to send an emergency alert"><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="46" class="trk"/><circle cx="50" cy="50" r="46" class="bar" id="fcfSosBar"/></svg><b>SOS</b><small>Hold 3 s</small></button>' +
      '<p id="fcfSosMsg">Sends "I need help" with your location to ' + (chosen ? chosen + (chosen === 1 ? ' person' : ' people') + ' you chose' : 'everyone in your Circles') + '.</p></div>' +
      '<div class="fca-gl">Call for help</div><div class="fca-card">' +
      '<a class="fca-row" href="tel:10111"><span class="ic">🚓</span><span class="tx"><b>Police · 10111</b><small>SAPS emergency</small></span><span class="chev">📞</span></a>' +
      '<a class="fca-row" href="tel:10177"><span class="ic">🚑</span><span class="tx"><b>Ambulance and fire · 10177</b><small>Emergency medical services</small></span><span class="chev">📞</span></a>' +
      '<a class="fca-row" href="tel:112"><span class="ic">📱</span><span class="tx"><b>From any cellphone · 112</b><small>Works even without airtime</small></span><span class="chev">📞</span></a></div>' +
      '<div class="fca-card">' + row('👥', 'Who gets my alert', chosen ? chosen + ' chosen' : 'Not chosen yet · everyone in my Circles', { data: 'data-a="who"' }) + '</div>' +
      '<p class="fca-note">Future Chat is not an emergency service. In danger, call 10111 or 112 first. Your alert goes to people you already chat with, as a message and a loud notification.</p>';
    bind(bd, { who: () => push(sosWho) });
    const btn = $('#fcfSos', bd), bar = $('#fcfSosBar', bd); let t = 0, raf = 0, start = 0;
    const L = 2 * Math.PI * 46; bar.style.strokeDasharray = L; bar.style.strokeDashoffset = L;
    const reset = () => { cancelAnimationFrame(raf); clearTimeout(t); bar.style.strokeDashoffset = L; btn.classList.remove('hold'); };
    const anim = () => { const f = Math.min(1, (Date.now() - start) / 3000); bar.style.strokeDashoffset = L * (1 - f); if (f < 1) raf = requestAnimationFrame(anim); };
    const down = e => { e.preventDefault(); start = Date.now(); btn.classList.add('hold'); anim(); try { navigator.vibrate && navigator.vibrate(40); } catch (_) {} t = setTimeout(fire, 3000); };
    btn.addEventListener('pointerdown', down); ['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => btn.addEventListener(ev, () => { if (!btn.classList.contains('sent')) reset(); }));
    btn.oncontextmenu = e => e.preventDefault();
    async function fire() {
      btn.classList.add('sent'); cancelAnimationFrame(raf); try { navigator.vibrate && navigator.vibrate([200, 100, 200]); } catch (_) {}
      const msg = $('#fcfSosMsg', bd); msg.textContent = 'Getting your location…';
      const l = await getLoc(6000);
      try { const r = await post('/api/fcf/sos', l || {}); msg.innerHTML = r.sent ? '<b>🆘 Alert sent to ' + r.sent + (r.sent === 1 ? ' person' : ' people') + '.</b><br>' + (l ? 'They can see where you are.' : 'Your location was off, so it was sent without it.') + ' If you are in danger, call 10111 or 112 now.'
        : '<b>Nobody to alert yet.</b> Start a chat with family first, then choose who gets your alert. Call 10111 or 112 if you need help now.'; }
      catch (e) { msg.textContent = e.message + ' — call 10111 or 112.'; }
      setTimeout(() => { btn.classList.remove('sent'); reset(); }, 8000);
    }
  }
  async function sosWho() {
    const self = top(); const bd = frame('Who gets my alert', 'Choose up to 12 people');
    if (!Object.keys(X.peers || {}).length) { try { X.peers = (await api('/api/fcx/peers')).peers || {}; } catch (_) {} }
    if (top() !== self) return;
    const sel = new Set(((X.prefs || {}).sos || []).map(Number));
    const people = directs().map(c => [c, (X.peers[String(c.id)] || {}).user_id]).filter(x => x[1]);
    bd.innerHTML = (people.length ? '<div class="fca-card">' + people.map(([c, u]) => '<button type="button" class="fca-row" data-u="' + u + '">' + avatar(c.title, (X.peers[String(c.id)] || {}).photo, 'sm') + '<span class="tx"><b>' + esc(c.title) + '</b></span><span class="fca-sw' + (sel.has(u) ? ' on' : '') + '"></span></button>').join('') + '</div>'
      : '<div class="fca-empty">Start a chat with your family first.</div>') + '<p class="fca-note">If you choose nobody, the alert goes to everyone in your Circles.</p>';
    bd.querySelectorAll('[data-u]').forEach(b => b.onclick = async () => { const u = Number(b.dataset.u); if (sel.has(u)) sel.delete(u); else { if (sel.size >= 12) return toast('Up to 12 people'); sel.add(u); } b.querySelector('.fca-sw').classList.toggle('on', sel.has(u)); await K.savePrefs({ sos: Array.from(sel) }); });
  }

  // ---------------------------------------------------------------- GOGO MODE (big and simple)
  const gogoOn = () => { const p = X.prefs; if (p) return !!p.gogo; try { return localStorage.getItem('fc_gogo') === '1'; } catch (_) { return false; } };
  function setGogo(on) { try { localStorage.setItem('fc_gogo', on ? '1' : ''); } catch (_) {} document.documentElement.classList.toggle('fca-gogo', !!on); if (X.prefs) X.prefs.gogo = !!on; if (!on) hideGogo(); return K.savePrefs({ gogo: !!on }); }
  let gogoEl = null;
  function hideGogo() { if (gogoEl) { gogoEl.remove(); gogoEl = null; } }
  function showGogo() {
    if (gogoEl) return;
    const pick = ((X.prefs || {}).gogo_people || []).map(Number);
    let list = directs().map(c => [c, X.peers[String(c.id)] || {}]);
    if (pick.length) list = list.filter(x => pick.indexOf(x[1].user_id) >= 0); else list = list.slice(0, 6);
    gogoEl = document.createElement('div'); gogoEl.id = 'fcfGogo';
    gogoEl.innerHTML = '<header><b>Future Chat</b><span>' + new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' }) + '</span></header><div class="gg">' +
      (list.length ? list.map(([c, p]) => '<div class="gp">' + avatar(c.title, p.photo, 'xl') + '<b>' + esc(c.title) + (c.unread ? ' <em>' + c.unread + ' new</em>' : '') + '</b><div class="gb"><button data-v="' + c.id + '">📞<span>Call</span></button><button data-vv="' + c.id + '">🎥<span>Video</span></button><button data-m="' + c.id + '">💬<span>Message</span></button></div></div>').join('')
        : '<p class="gnone">Ask someone in your family to start a chat with you. Their name will show here with big buttons.</p>') +
      '</div><footer><button data-a="sos" class="ggsos">🆘 Emergency</button><button data-a="people">👥 Choose people</button><button data-a="off">Normal app</button></footer>';
    document.body.appendChild(gogoEl);
    gogoEl.querySelectorAll('[data-v]').forEach(b => b.onclick = () => FC().callConv(Number(b.dataset.v), 'voice'));
    gogoEl.querySelectorAll('[data-vv]').forEach(b => b.onclick = () => FC().callConv(Number(b.dataset.vv), 'video'));
    gogoEl.querySelectorAll('[data-m]').forEach(b => b.onclick = () => { hideGogo(); FC().openConv(Number(b.dataset.m)); });
    bind(gogoEl, { sos: () => { hideGogo(); go('you'); push(sosScreen); }, people: () => { hideGogo(); go('you'); push(gogoScreen); }, off: () => { if (confirm('Go back to the normal Future Chat?')) setGogo(false); } });
  }
  setInterval(() => {   // show the big home whenever the chat list is on screen
    if (!gogoOn() || !tok() || document.getElementById('fcaAuth')) { hideGogo(); document.documentElement.classList.toggle('fca-gogo', gogoOn()); return; }
    document.documentElement.classList.add('fca-gogo');
    const panelOpen = (document.getElementById('fcaPanel') || {}).classList && document.getElementById('fcaPanel').classList.contains('open');
    const inConv = !!curConv(); const busy = document.querySelector('.fc-dim') || document.querySelector('.sv-call-overlay:not(.hidden)');
    if (!inConv && !panelOpen && !busy) showGogo(); else if (gogoEl && (inConv || panelOpen)) hideGogo();
  }, 1200);
  function gogoScreen() {
    const bd = frame('Gogo mode', 'Big, simple and easy');
    const on = gogoOn(); const pick = new Set(((X.prefs || {}).gogo_people || []).map(Number));
    const people = directs().map(c => [c, (X.peers[String(c.id)] || {}).user_id]).filter(x => x[1]);
    bd.innerHTML = '<div class="fca-hero" style="background:linear-gradient(135deg,#065f46,#0e8c9e)"><small>👵 GOGO MODE</small><b>Big text and one-tap calls</b><p>Perfect for gogo, mkhulu, ouma and oupa: the people they love, with huge Call, Video and Message buttons. Set it up on their phone.</p></div>' +
      '<div class="fca-card">' + row('🔆', 'Gogo mode', on ? 'On' : 'Off', { data: 'data-a="tg"' }, '<span class="fca-sw' + (on ? ' on' : '') + '"></span>') + '</div>' +
      '<div class="fca-gl">People on the big screen (up to 6)</div>' + (people.length ? '<div class="fca-card">' + people.map(([c, u]) => '<button type="button" class="fca-row" data-u="' + u + '">' + avatar(c.title, '', 'sm') + '<span class="tx"><b>' + esc(c.title) + '</b></span><span class="fca-sw' + (pick.has(u) ? ' on' : '') + '"></span></button>').join('') + '</div>' : '<div class="fca-empty">Start chats with the family first.</div>') +
      '<p class="fca-note">If you choose nobody, the six most recent chats show. To leave Gogo mode, tap "Normal app" at the bottom of the big screen.</p>';
    bind(bd, { tg: () => { setGogo(!on); if (!on) toast('Gogo mode is on — go back to see the big screen'); gogoScreen(); } });
    bd.querySelectorAll('[data-u]').forEach(b => b.onclick = async () => { const u = Number(b.dataset.u); if (pick.has(u)) pick.delete(u); else { if (pick.size >= 6) return toast('Up to 6 people'); pick.add(u); } b.querySelector('.fca-sw').classList.toggle('on', pick.has(u)); await K.savePrefs({ gogo_people: Array.from(pick) }); hideGogo(); });
  }

  // ---------------------------------------------------------------- family dates: anniversaries and remembrance
  let DATES = null, datesAt = 0;
  async function loadDates(force) { if (!force && DATES && Date.now() - datesAt < 600000) return DATES; try { DATES = (await api('/api/fcf/dates')).items || []; datesAt = Date.now(); } catch (_) { DATES = DATES || []; } return DATES; }
  async function scrDates() {
    const self = top(); const bd = frame('Family dates', 'Anniversaries and days we remember', { action: [K.SVG.plus, 'Add a date', () => dateForm(() => { if (top() === self) scrDates(); })] });
    bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    const items = await loadDates(true); if (top() !== self) return;
    const one = x => { const [, n] = daysTo(x.d, x.m); return '<div class="fca-row"><span class="ic">' + (x.kind === 'remembrance' ? '🕯️' : x.kind === 'anniversary' ? '💍' : '🎉') + '</span><span class="tx"><b>' + esc(x.title) + '</b><small>' + x.d + ' ' + MONTHS[x.m - 1] + (x.y ? ' ' + x.y : '') + ' · ' + soonText(n) + (x.circle ? ' · shared with ' + esc(x.circle) : ' · just me') + '</small></span>' + (x.mine ? '<button class="fcf-x" data-del="' + x.id + '" aria-label="Remove">✕</button>' : '') + '</div>'; };
    bd.innerHTML = (items.length ? '<div class="fca-card">' + items.map(one).join('') + '</div>' : '<div class="fca-empty"><span class="big">💍</span><b>No family dates yet</b>Add wedding anniversaries, the day you met, or a gentle day to remember someone who passed.</div>') +
      '<button class="fca-btn" data-a="add">Add a family date</button><p class="fca-note">On the day you (and the Circle you share it with) get a gentle reminder. Days of remembrance never show confetti or "Happy".</p>';
    bind(bd, { add: () => dateForm(() => { if (top() === self) scrDates(); }) });
    bd.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => { if (!confirm('Remove this date?')) return; try { await post('/api/fcf/date/delete', { id: Number(b.dataset.del) }); scrDates(); } catch (e) { toast(e.message); } });
  }
  function dateForm(after) {
    const gs = groups();
    sheet('<h3>💍 Add a family date</h3><div class="fca-seg" id="fcfDK"><button data-k="anniversary" class="on">💍 Anniversary</button><button data-k="remembrance">🕯️ Remembrance</button><button data-k="other">🎉 Other</button></div>' +
      '<label class="fca-field"><span>Name</span><input id="fcfDT" maxlength="120" placeholder="e.g. Mom and Dad\'s wedding anniversary"></label>' +
      '<div style="display:grid;grid-template-columns:1fr 2fr 1.3fr;gap:8px"><label class="fca-field"><span>Day</span><select id="fcfDD">' + Array.from({ length: 31 }, (_, i) => '<option>' + (i + 1) + '</option>').join('') + '</select></label><label class="fca-field"><span>Month</span><select id="fcfDM">' + MONTHS.map((m, i) => '<option value="' + (i + 1) + '">' + m + '</option>').join('') + '</select></label><label class="fca-field"><span>Year (optional)</span><input id="fcfDY" inputmode="numeric" maxlength="4"></label></div>' +
      '<label class="fca-field"><span>Share with</span><select id="fcfDC"><option value="0">Just me</option>' + gs.map(g => '<option value="' + g.id + '">' + esc(g.title) + '</option>').join('') + '</select></label><button class="fc-btn" id="fcfDGo">Save</button>', (el, done) => {
      let kind = 'anniversary';
      el.querySelectorAll('[data-k]').forEach(b => b.onclick = () => { kind = b.dataset.k; el.querySelectorAll('[data-k]').forEach(x => x.classList.toggle('on', x === b)); $('#fcfDT', el).placeholder = kind === 'remembrance' ? 'e.g. Remembering Gogo Thandi' : kind === 'anniversary' ? 'e.g. Mom and Dad\'s wedding anniversary' : 'e.g. The day we moved into our home'; });
      $('#fcfDGo', el).onclick = async () => { try { await post('/api/fcf/date', { kind, title: $('#fcfDT', el).value, d: Number($('#fcfDD', el).value), m: Number($('#fcfDM', el).value), y: Number($('#fcfDY', el).value) || 0, c: Number($('#fcfDC', el).value) }); done(); toast('Saved'); loadDates(true); if (after) after(); } catch (e) { toast(e.message); } };
    });
  }
  // gentle banner on the chat list on the day (no confetti for remembrance)
  const baseAfter = FCX.afterList;
  FCX.afterList = function (body, items, S) {
    if (baseAfter) baseAfter(body, items, S);
    if (!S || S.archivedView || (S.filter && S.filter !== 'all') || (S.q || '').trim()) return;
    const paint = list => {
      if (!body.isConnected || body.querySelector('.fcf-today')) return;
      const n = new Date(); const today = (list || []).filter(x => x.d === n.getDate() && x.m === n.getMonth() + 1);
      if (!today.length) return;
      const box = document.createElement('div'); box.className = 'fcf-today';
      box.innerHTML = today.map(x => x.kind === 'remembrance'
        ? '<button class="fcf-remember" data-c="' + x.conversation_id + '"><span>🕯️</span><b>' + esc(x.title) + '</b><small>Today we remember. ' + (x.conversation_id ? 'Share a memory with ' + esc(x.circle) : 'Take a quiet moment') + '</small></button>'
        : '<button class="fcf-anniv" data-c="' + x.conversation_id + '"><span>' + (x.kind === 'anniversary' ? '💍' : '🎉') + '</span><b>' + esc(x.title) + (x.y ? ' · ' + (n.getFullYear() - x.y) + ' years' : '') + '</b><small>' + (x.conversation_id ? 'Send love in ' + esc(x.circle) : 'A special day today') + '</small></button>').join('');
      const cs = body.querySelector('.fca-celeb'); if (cs) cs.after(box); else body.insertBefore(box, body.firstChild);
      box.querySelectorAll('[data-c]').forEach(b => b.onclick = () => { const c = Number(b.dataset.c); if (c) FC().openConv(c); else go('you'); });
    };
    if (DATES) paint(DATES); loadDates().then(paint);
  };
  FCX.celebExtra = function (bd) {
    bd.insertAdjacentHTML('afterbegin', '<div class="fca-card">' + row('💍', 'Family dates', 'Anniversaries and days we remember', { data: 'data-a="fdates"' }) + '</div>');
    bind(bd, { fdates: () => push(scrDates) });
  };

  // ---------------------------------------------------------------- parents and teens (13-17)
  async function scrSafety() {
    const self = top(); const bd = frame('Family safety', 'Parents and teens'); bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let d; try { d = await api('/api/fcf/guardian'); } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    let h = '<div class="fca-hero" style="background:linear-gradient(135deg,#1e3a8a,#0e8c9e)"><small>🛡️ TEEN PROTECTION</small><b>Strangers can\'t add teens to groups</b><p>People aged 13 to 17 can only be added to a group by someone they already chat with, or a parent they linked. Everyone else gets "not added for privacy".</p></div>';
    h += '<div class="fca-card">' + (d.under18 ? row('🛡️', 'Teen protection is on', 'Because your birthday says you\'re under 18', {}, '<span class="fca-sw on"></span>')
      : row('🛡️', 'Protect me like a teen', 'Only people I chat with can add me to groups', { data: 'data-a="tg"' }, '<span class="fca-sw' + (d.teen_safe ? ' on' : '') + '"></span>')) + '</div>';
    if (d.parents.length) h += '<div class="fca-gl">Parents linked to you</div><div class="fca-card">' + d.parents.map(p => '<div class="fca-row"><span class="ic">👪</span><span class="tx"><b>' + esc(p.name) + '</b><small>' + (p.status === 'pending' ? 'Wants to link as your parent' : 'Can see the names of your Circles — never your messages') + '</small></span>' +
      (p.status === 'pending' ? '<button class="fc-chip" data-ok="' + p.id + '" style="color:#1ed6c8;border-color:#1ed6c8">Accept</button><button class="fc-chip" data-no="' + p.id + '">No</button>' : '<button class="fc-chip" data-no="' + p.id + '">Unlink</button>') + '</div>').join('') + '</div>';
    h += '<div class="fca-gl">My teens</div>' + (d.teens.length ? d.teens.map(t => '<div class="fca-card"><div class="fca-row"><span class="ic">🧒</span><span class="tx"><b>' + esc(t.name) + '</b><small>' + (t.status === 'pending' ? 'Waiting for them to accept on their phone' : t.circles.length + (t.circles.length === 1 ? ' Circle' : ' Circles')) + '</small></span><button class="fc-chip" data-no="' + t.id + '">' + (t.status === 'pending' ? 'Cancel' : 'Unlink') + '</button></div>' +
      (t.circles.length ? t.circles.map(c => '<div class="fca-row" style="padding-left:56px"><span class="tx"><b>◎ ' + esc(c.title) + '</b><small>' + c.members + ' members</small></span></div>').join('') : '') + '</div>').join('') : '<div class="fca-empty" style="padding:16px">No teens linked yet.</div>') +
      '<button class="fca-btn sec" data-a="link">Link my teen</button>' +
      '<p class="fca-note">Linking needs your teen to accept on their own phone. You see which groups (Circles) they are in and how many people are in each — never their messages, photos or calls. Either of you can unlink at any time. Future Chat does not read or filter message content, so talk with your teen about staying safe online and to block and report anyone who makes them uncomfortable.</p>';
    bd.innerHTML = h;
    bind(bd, { tg: async () => { if (await K.savePrefs({ teen_safe: !d.teen_safe })) scrSafety(); }, link: linkTeen });
    const ans = async (id, action) => { try { await post('/api/fcf/guardian/answer', { id, action }); scrSafety(); } catch (e) { toast(e.message); } };
    bd.querySelectorAll('[data-ok]').forEach(b => b.onclick = () => ans(Number(b.dataset.ok), 'accept'));
    bd.querySelectorAll('[data-no]').forEach(b => b.onclick = () => { if (confirm('End this family link?')) ans(Number(b.dataset.no), b.textContent === 'No' ? 'decline' : 'unlink'); });
  }
  function linkTeen() {
    sheet('<h3>👪 Link my teen</h3><p>Enter your teen\'s Future Chat number. They get a request to accept.</p><label class="fca-field"><span>Their mobile number</span><input id="fcfGP" type="tel" placeholder="e.g. 082 123 4567"></label><button class="fc-btn" id="fcfGGo">Send request</button>', (el, done) => {
      $('#fcfGGo', el).onclick = async () => { try { const r = await post('/api/fcf/guardian/request', { phone: $('#fcfGP', el).value }); done(); toast(r.message || 'Request sent'); scrSafety(); } catch (e) { toast(e.message); } };
    });
  }

  // ---------------------------------------------------------------- You tab: Family section
  FCX.youExtra = function (bd) {
    const gl = Array.from(bd.querySelectorAll('.fca-gl')).find(x => x.textContent.trim() === 'Preferences');
    const box = document.createElement('div');
    box.innerHTML = '<div class="fca-gl">Family</div><div class="fca-card">' +
      row('🆘', 'Emergency SOS', 'Hold 3 seconds · alerts your family with your location', { data: 'data-a="fsos"', cls: 'fcf-sosrow' }) +
      row('👵', 'Gogo mode', gogoOn() ? 'On · big and simple' : 'Big text, one-tap calls for gogo and oupa', { data: 'data-a="fgogo"' }) +
      row('🛡️', 'Family safety', 'Parents and teens', { data: 'data-a="fsafe"' }) +
      row('💍', 'Family dates', 'Anniversaries and remembrance', { data: 'data-a="fdates"' }) + '</div>';
    if (gl) gl.parentNode.insertBefore(box, gl); else bd.appendChild(box);
    bind(box, { fsos: () => push(sosScreen), fgogo: () => push(gogoScreen), fsafe: () => push(scrSafety), fdates: () => push(scrDates) });
  };
  fam.sos = () => { go('you'); push(sosScreen); };

  // ---------------------------------------------------------------- styles
  const css = document.createElement('style');
  css.textContent = [
    '.fcf-mem{display:flex;gap:12px;overflow-x:auto;padding:2px 2px 12px;margin-bottom:4px}.fcf-mem span{display:flex;flex-direction:column;align-items:center;gap:5px;min-width:56px}.fcf-mem small{font-size:12px;color:var(--fca-pale);white-space:nowrap}',
    '.fcf-quick{grid-template-columns:repeat(3,1fr)}',
    '.fcf-board{display:block;width:100%;text-align:left;border:1px dashed rgba(250,204,21,.55);background:linear-gradient(135deg,rgba(250,204,21,.14),rgba(250,204,21,.05));color:#fff;border-radius:16px;padding:14px;margin-bottom:12px}.fcf-board b{display:block;font-size:16px;white-space:pre-wrap}.fcf-board small{display:block;margin-top:6px;color:#fde68a;font-size:12px}.fcf-board.empty b{color:#fde68a}',
    '.fcf-stars{display:flex;gap:8px;overflow-x:auto;margin:-2px 0 12px}.fcf-stars span{flex:none;display:flex;align-items:center;gap:6px;background:var(--fca-card2);border:1px solid var(--fca-line);border-radius:20px;padding:7px 12px;font-size:13px;color:#fff}.fcf-stars em{font-style:normal;color:#fde047;font-weight:800}',
    '.fcf-claim{color:#fde047!important;border-color:rgba(253,224,71,.5)!important}.fcf-x{border:0;background:transparent;color:var(--fca-pale);font-size:18px;padding:6px 10px}',
    '.fcf-add{display:flex;gap:8px;margin-bottom:12px}.fcf-add input{flex:1;border:1px solid var(--fca-line);background:var(--fca-card2);color:#fff;border-radius:14px;padding:13px 14px;font-size:16px;outline:none}.fcf-add input:focus{border-color:var(--fca-teal)}.fcf-add .fca-ib{font-size:22px;width:50px}',
    '.fcf-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-bottom:12px}.fcf-ph{position:relative;aspect-ratio:1;border:0;border-radius:8px;background:#11324d center/cover no-repeat;overflow:hidden;padding:0}.fcf-ph video{width:100%;height:100%;object-fit:cover}.fcf-ph em{position:absolute;right:6px;bottom:4px;color:#fff;font-style:normal;text-shadow:0 1px 4px #000;z-index:1}.fcf-ph.gone{opacity:.35}',
    '.fcf-rec{display:flex;align-items:center;gap:12px;justify-content:center;margin:12px 0;font-size:28px}.fcf-rec .dot{width:16px;height:16px;border-radius:50%;background:#ef4444;animation:fcfPulse 1s infinite}@keyframes fcfPulse{50%{opacity:.3}}',
    '.fcf-qn{color:#9cb7cc}.fcf-emoji{font-size:54px!important;text-align:center;letter-spacing:6px;margin:10px 0!important}.fcf-opts{display:grid;gap:8px;margin-top:10px}.fcf-opts button{border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.07);color:#fff;border-radius:14px;padding:14px;font-size:16px;font-weight:700;text-align:left}.fcf-opts button.ok{background:#15803d;border-color:#22c55e}.fcf-opts button.no{background:#991b1b;border-color:#ef4444}.fcf-score{font-size:46px;font-weight:900;text-align:center;color:#1ed6c8;margin:6px 0}',
    '.fc-card.fcf-sosc{border-color:#ef4444!important;background:linear-gradient(135deg,rgba(127,29,29,.9),rgba(69,10,10,.9))!important}.fc-card.fcf-sosc .k{color:#fecaca!important}.fc-card.fcf-sosc .pri{background:#ef4444!important;color:#fff!important;display:block;margin-top:8px}.fcf-nums{display:block;margin-top:8px;font-size:12px;color:#fecaca}.fc-card .fcf-nums a{display:inline!important;padding:0!important;margin:0!important;background:none!important;color:#fff!important;font-weight:800;text-decoration:underline}',
    'a.fca-row{text-decoration:none;color:inherit}a.fca-row b,a.fca-row small{text-decoration:none}',
    '.fc-card.fcf-safe{border-color:rgba(34,197,94,.55)!important}.fc-card.fcf-safe .k{color:#86efac!important}.fc-card.fcf-story{background:linear-gradient(135deg,rgba(49,46,129,.85),rgba(30,27,75,.85))!important;border-color:rgba(165,180,252,.4)!important}.fc-card.fcf-story .k{color:#c7d2fe!important}',
    '.fcf-sosw{text-align:center;padding:14px 0 6px}.fcf-sos{position:relative;width:210px;height:210px;border-radius:50%;border:0;background:radial-gradient(circle at 50% 40%,#f87171,#b91c1c 70%);color:#fff;box-shadow:0 0 0 10px rgba(239,68,68,.15),0 14px 40px rgba(185,28,28,.45);touch-action:none;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}',
    '.fcf-sos svg{position:absolute;inset:-8px;width:calc(100% + 16px);height:calc(100% + 16px);transform:rotate(-90deg)}.fcf-sos .trk{fill:none;stroke:rgba(255,255,255,.12);stroke-width:4}.fcf-sos .bar{fill:none;stroke:#fff;stroke-width:4;stroke-linecap:round}.fcf-sos b{display:block;font-size:48px;letter-spacing:2px}.fcf-sos small{font-size:14px;opacity:.85}.fcf-sos.hold{transform:scale(.96)}.fcf-sos.sent{background:radial-gradient(circle,#22c55e,#15803d)}',
    '#fcfSosMsg{margin:18px 10px 6px;color:#fff;font-size:15px;line-height:1.45}.fcf-sosrow .ic{background:#b91c1c!important}',
    '.fcf-today{display:grid;gap:8px;margin:8px 12px 4px}.fcf-today button{display:grid;grid-template-columns:40px 1fr;text-align:left;align-items:center;border-radius:16px;padding:12px 14px;border:1px solid;color:#fff}.fcf-today span{grid-row:span 2;font-size:26px}.fcf-today small{color:inherit;opacity:.8}',
    '.fcf-remember{background:linear-gradient(135deg,#1f2937,#334155);border-color:rgba(203,213,225,.3)!important}.fcf-anniv{background:linear-gradient(135deg,#831843,#be185d);border-color:rgba(251,207,232,.4)!important}',
    // gogo mode: bigger everything + simple home
    'html.fca-gogo #fcRoot .fc-b{font-size:20px;line-height:1.45}html.fca-gogo #fcRoot .fc-name{font-size:20px}html.fca-gogo #fcRoot .fc-last{font-size:17px}html.fca-gogo #fcRoot #fcText{font-size:20px}html.fca-gogo .fca-row b{font-size:18px}html.fca-gogo .fc-btn,html.fca-gogo .fca-btn{font-size:19px;padding:18px}',
    '#fcfGogo{visibility:visible!important;position:fixed;inset:0;bottom:var(--fca-nav,0);z-index:10055;overflow:auto;background:linear-gradient(180deg,#0a1f33,#0f3150 60%,#11506a);color:#fff;padding:max(18px,env(safe-area-inset-top)) 14px 20px}',
    '#fcfGogo header{display:flex;flex-direction:column;margin:6px 4px 14px}#fcfGogo header b{font-size:30px}#fcfGogo header span{font-size:18px;color:#9cb7cc}',
    '#fcfGogo .gg{display:grid;gap:14px}#fcfGogo .gp{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12);border-radius:22px;padding:16px;display:grid;grid-template-columns:auto 1fr;gap:12px 14px;align-items:center}#fcfGogo .gp>b{font-size:26px}#fcfGogo .gp em{font-style:normal;font-size:15px;background:#1ed6c8;color:#05283a;border-radius:12px;padding:2px 8px;vertical-align:middle}',
    '#fcfGogo .gb{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,1fr);gap:10px}#fcfGogo .gb button{border:0;border-radius:18px;padding:16px 4px;font-size:34px;background:#15803d;color:#fff;display:flex;flex-direction:column;align-items:center;gap:4px}#fcfGogo .gb button:nth-child(2){background:#1d4ed8}#fcfGogo .gb button:nth-child(3){background:#0e8c9e}#fcfGogo .gb span{font-size:18px;font-weight:800}',
    '#fcfGogo footer{display:grid;gap:10px;margin-top:18px}#fcfGogo footer button{border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.08);color:#fff;border-radius:18px;padding:16px;font-size:20px;font-weight:800}#fcfGogo footer .ggsos{background:#b91c1c;border-color:#ef4444}#fcfGogo .gnone{font-size:20px;line-height:1.5;color:#cfe3f2}'
  ].join('');
  document.head.appendChild(css);

  // deep links from notifications
  try { const q = new URLSearchParams(location.search); if (q.get('fcx') === 'guardian') setTimeout(() => { go('you'); push(scrSafety); }, 1200); } catch (_) {}
  try { if (localStorage.getItem('fc_gogo') === '1') document.documentElement.classList.add('fca-gogo'); } catch (_) {}
})();
