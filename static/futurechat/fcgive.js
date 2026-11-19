/* FCG-01: Future Chat monthly giveaway. 1 friend who joins (and sends a few messages) = 1 ticket. Free to enter.
   Invites are linked automatically: personal link (Play install referrer), invite code, or the friend's phone number. Server: fcgive.py */
(function () {
  'use strict';
  const FCX = window.FCX; if (!window.SV_FC_APP || !FCX || !FCX.kit) return;
  const K = FCX.kit, { api, post, esc, $, toast, sheet, frame, push, pop, go, row, bind, openPanel, X } = K;
  const tok = () => { try { return localStorage.getItem('skillvaya_token') || localStorage.getItem('sv_token') || ''; } catch (_) { return ''; } };
  const top = () => X.stack[X.stack.length - 1];
  const G = FCX.give = { d: null };
  async function load() { try { G.d = await api('/api/fcg/me'); } catch (_) {} return G.d; }
  const msg = d => 'Join me on Future Chat 💬 Free chats, calls, Chatmoji and Lenses. Get it here: ' + d.link + (d.code ? '  (invite code ' + d.code.toUpperCase() + ')' : '');

  // ---------------------------------------------------------------- inviting: link, WhatsApp, SMS, any app, or a phone number
  async function invite(phone) {
    const d = G.d || await load(); if (!d) { toast('Check your connection'); return; }
    if (phone) {   // invited straight from a contact or a number that isn't on Future Chat yet
      try { await post('/api/fcg/invite', { phone }); } catch (e) { if (e.data && e.data.member) { toast(e.message); return; } }
      choose(d, phone); return;
    }
    choose(d, '');
  }
  function choose(d, phone) {
    sheet('<h3>🎁 Invite a friend</h3><p>When your friend joins and sends a few messages, you get <b>1 ticket</b> for this month\'s ' + esc(d.prize) + ' giveaway. It\'s linked to you automatically.</p>' +
      '<div class="fc-acts"><button class="fc-act" data-a="wa"><i>🟢</i>WhatsApp</button><button class="fc-act" data-a="sms"><i>💬</i>SMS' + (phone ? ' to ' + esc(phone) : '') + '</button><button class="fc-act" data-a="more"><i>📤</i>Other apps</button><button class="fc-act" data-a="copy"><i>🔗</i>Copy my link</button>' +
      (phone ? '' : '<button class="fc-act" data-a="num"><i>📱</i>Type their number</button>') + '</div><p style="font-size:12px;color:#9cb7cc">Your code: <b style="letter-spacing:2px">' + esc(d.code.toUpperCase()) + '</b></p>', (el, done) => bind(el, {
      wa: () => { done(); open('https://wa.me/' + (phone ? phone.replace(/\D/g, '') : '') + '?text=' + encodeURIComponent(msg(d))); },
      sms: async () => { done(); if (!phone) { const p = await askNumber(); if (!p) return; phone = p; } location.href = 'sms:' + phone + '?body=' + encodeURIComponent(msg(d)); },
      more: () => { done(); try { if (window.FutureChatNative && window.FutureChatNative.share) { window.FutureChatNative.share(msg(d)); return; } } catch (_) {} if (navigator.share) navigator.share({ title: 'Future Chat', text: msg(d) }).catch(() => {}); else copy(d); },
      copy: () => { done(); copy(d); },
      num: async () => { done(); const p = await askNumber(); if (p) choose(d, p); }
    }));
  }
  function open(u) { const a = document.createElement('a'); a.href = u; a.target = '_blank'; a.rel = 'noopener'; document.body.appendChild(a); a.click(); a.remove(); }
  function copy(d) { try { navigator.clipboard.writeText(msg(d)); toast('Invite copied — paste it anywhere'); } catch (_) { sheet('<h3>Your invite</h3><textarea rows="4" readonly>' + esc(msg(d)) + '</textarea>'); } }
  function askNumber() {
    return new Promise(res => sheet('<h3>Your friend\'s number</h3><p>So we can link them to you when they join.</p><input id="fcgN" type="tel" placeholder="e.g. 082 123 4567"><button class="fc-btn" id="fcgNGo">Next</button>', (el, done) => {
      setTimeout(() => { try { $('#fcgN', el).focus(); } catch (_) {} }, 60);
      $('#fcgNGo', el).onclick = async () => { const v = $('#fcgN', el).value.trim(); if (!v) return; try { const r = await post('/api/fcg/invite', { phone: v }); done(); res(r.phone); } catch (e) { toast(e.message); } };
    }));
  }
  FCX.invite = invite;   // fc.js "Invite" buttons (contacts not on Future Chat, "that number isn't on Future Chat yet") come here

  // ---------------------------------------------------------------- the giveaway screen
  async function scrGive() {
    const self = top();
    const bd = frame('Monthly giveaway', 'Invite friends, win money');
    bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    const d = await load(); if (top() !== self) return;
    if (!d) { bd.innerHTML = '<div class="fca-empty">Couldn\'t load. Check your connection.</div>'; return; }
    const days = Math.max(0, Math.ceil((new Date(d.draw_at) - Date.now()) / 864e5));
    const odds = d.all_tickets ? Math.round(100 * d.my_tickets / d.all_tickets) : 0;
    let h = '<div class="fcg-hero"><div class="fx">' + Array.from({ length: 9 }, (_, i) => '<span style="left:' + (i * 11 + 3) + '%;animation-delay:' + (i * .5).toFixed(1) + 's">' + ['💰', '🎉', '✨'][i % 3] + '</span>').join('') + '</div>' +
      (d.starts ? '<small>STARTS 1 ' + esc(d.starts.toUpperCase()) + '</small><b>Win ' + esc(d.prize) + ' every month</b><p>Friends who join from 1 ' + esc(d.starts.split(' ')[0]) + ' count · free to enter</p>'
        : '<small>' + esc(d.month.toUpperCase()) + ' GIVEAWAY</small><b>Win ' + esc(d.prize) + '</b><p>Drawn in ' + days + (days === 1 ? ' day' : ' days') + ' · free to enter</p>') +
      '<div class="tk"><div><em>' + d.my_tickets + '</em><span>your tickets</span></div><div><em>' + d.all_tickets + '</em><span>tickets in the draw</span></div>' + (d.my_tickets ? '<div><em>' + odds + '%</em><span>your chance</span></div>' : '') + '</div></div>' +
      '<button class="fca-btn" data-a="inv">🎁 Invite a friend</button>' +
      '<div class="fca-card">' + row('1️⃣', 'Invite friends', 'Share your link on WhatsApp, SMS or anywhere', {}, '') + row('2️⃣', 'They join and say hi', 'They save their number and chat with 2 people (' + d.min_messages + '+ messages)', {}, '') + row('3️⃣', 'You get a ticket', '1 friend = 1 ticket. More friends, more chances', {}, '') + '</div>';
    if (d.friends.length) h += '<div class="fca-gl">Friends you invited</div><div class="fca-card">' + d.friends.slice(0, 40).map(f => row(f.ticket ? '🎟️' : '⏳', f.name, f.ticket ? (f.this_month ? 'Ticket for this month ✓' : 'Ticket for ' + f.month) : 'Almost — ' + f.why, {}, '')).join('') + '</div>';
    else h += '<div class="fca-empty" style="padding:16px">No friends joined through you yet. Invite your first one!</div>';
    if (d.won && d.won.length) h += '<div class="fca-gl">You won 🎉</div><div class="fca-card">' + d.won.map(w => row('🏆', w.prize + ' · ' + w.month, w.paid ? 'Paid ✓' : 'We\'ll message you to arrange payment', {}, '')).join('') + '</div>';
    if (d.last) h += '<div class="fca-card">' + row('🏆', 'Last winner: ' + (d.last.name || 'Someone'), d.last.prize + ' · ' + d.last.month + ' · ' + d.last.tickets + ' tickets', {}, '') + '</div>';
    h += '<div class="fca-card">' + row('📄', 'Giveaway rules', 'How it works, who can enter, how winners are paid', { data: 'data-a="rules"' }) + '</div>';
    if (d.owner) h += '<div class="fca-gl">Owner</div><div class="fca-card">' + row('⚙️', 'Run the giveaway', 'Prize, leaders, winners and payments', { data: 'data-a="admin"' }) + '</div>';
    h += '<p class="fca-note">No purchase is needed or possible. Your phone number and chats are never shown to other players.</p>';
    bd.innerHTML = h;
    bind(bd, { inv: () => invite(''), rules: () => window.open((d.site || '') + '/giveaway-rules.html', '_blank'), admin: () => push(scrAdmin) });
  }
  G.open = () => { go('you'); push(scrGive); };
  async function scrAdmin() {
    const self = top(); const bd = frame('Run the giveaway', 'Owner only'); bd.innerHTML = '<div class="fca-empty">Loading…</div>';
    let a; try { a = await api('/api/fcg/admin'); } catch (e) { bd.innerHTML = '<div class="fca-empty">' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    bd.innerHTML = '<label class="fca-field"><span>Prize every month</span><input id="fcgP" value="' + esc(a.prize) + '" maxlength="40"></label><button class="fca-btn" data-a="save">Save prize</button>' +
      '<div class="fca-gl">' + esc(a.month) + ' so far</div><div class="fca-card">' + (a.leaders.length ? a.leaders.map(l => row('🎟️', l.name, l.tickets + (l.tickets === 1 ? ' ticket' : ' tickets'), {}, '')).join('') : row('⏳', 'No tickets yet', '', {}, '')) + '</div>' +
      '<div class="fca-gl">Draws</div><div class="fca-card">' + (a.draws.length ? a.draws.map(w => row(w.paid ? '✅' : '💰', w.month + ' · ' + (w.winner || 'no tickets'), w.prize + ' · ' + w.tickets + ' tickets from ' + w.people + ' people' + (w.phone ? ' · ' + w.phone : '') + ' · proof ' + w.proof, {}, w.winner && !w.paid ? '<button class="fc-chip" data-paid="' + w.key + '" style="color:#1ed6c8;border-color:#1ed6c8">Mark paid</button>' : '')).join('') : row('📅', 'The first draw is on the 1st of next month', '', {}, '')) + '</div>' +
      '<p class="fca-note">The draw happens by itself at 08:00 on the 1st. Before paying, open the winner\'s friends to check they\'re real people. Pay by EFT into an account in the winner\'s own name.</p>';
    bind(bd, { save: async () => { try { await post('/api/fcg/admin', { prize: $('#fcgP', bd).value }); toast('Saved'); } catch (e) { toast(e.message); } } });
    bd.querySelectorAll('[data-paid]').forEach(b => b.onclick = async () => { try { await post('/api/fcg/admin', { paid: b.dataset.paid }); scrAdmin(); } catch (e) { toast(e.message); } });
  }

  // ---------------------------------------------------------------- You tab: giveaway right at the top; chat list: a small reminder
  const baseYou = FCX.youExtra;
  FCX.youExtra = function (bd) {
    if (baseYou) baseYou(bd);
    const prof = bd.querySelector('.fca-prof');
    const box = document.createElement('div');
    box.innerHTML = '<button type="button" class="fcg-cta" data-a="give"><span>🎁</span><b>Win ' + esc((G.d && G.d.prize) || 'R500') + ' this month</b><small>Invite friends · 1 friend = 1 ticket' + (G.d && G.d.my_tickets ? ' · you have ' + G.d.my_tickets : '') + '</small></button>';
    if (prof) prof.after(box); else bd.prepend(box);
    bind(box, { give: () => push(scrGive) });
    if (!G.d) load().then(() => { const b = box.querySelector('b'); if (b && G.d) b.textContent = 'Win ' + G.d.prize + ' this month'; });
  };
  const baseAfter = FCX.afterList;
  FCX.afterList = function (body, items, S) {
    if (baseAfter) baseAfter(body, items, S);
    if (!S || S.archivedView || (S.filter && S.filter !== 'all') || (S.q || '').trim() || body.querySelector('.fcg-strip')) return;
    let off = ''; try { off = localStorage.getItem('fcg_hide') || ''; } catch (_) {}
    if (off === new Date().toISOString().slice(0, 10)) return;
    const el = document.createElement('div'); el.className = 'fcg-strip';
    el.innerHTML = '<button class="go"><span>🎁</span><b>Win ' + esc((G.d && G.d.prize) || 'R500') + ' this month</b><small>Invite a friend = 1 ticket</small></button><button class="x" aria-label="Hide for today">✕</button>';
    const sp = body.querySelector('.fca-space'); if (sp) sp.before(el); else body.appendChild(el);
    el.querySelector('.go').onclick = () => { openPanel(); push(scrGive); };
    el.querySelector('.x').onclick = () => { try { localStorage.setItem('fcg_hide', new Date().toISOString().slice(0, 10)); } catch (_) {} el.remove(); };
  };
  const baseShopTiles = FCX.youExtra;   // (kept for clarity: the Shop lives in fcpay.js)

  // ---------------------------------------------------------------- linking a new person to whoever invited them (automatic)
  async function claim() {
    if (!tok()) return;
    let code = ''; try { code = localStorage.getItem('fc_ref') || ''; } catch (_) {}
    try { if (!code && window.FutureChatNative && window.FutureChatNative.installRef) code = window.FutureChatNative.installRef() || ''; } catch (_) {}
    if (!code) return;
    let done = ''; try { done = localStorage.getItem('fc_ref_done') || ''; } catch (_) {}
    if (done === code) return;
    try { const r = await post('/api/fcg/claim', { code }); try { localStorage.setItem('fc_ref_done', code); } catch (_) {} if (r.ok) toast('Welcome! Your friend gets a giveaway ticket once you send a few messages 🎁'); } catch (_) {}
  }
  // sign-up form: optional invite code (filled in for you when you came from an invite link)
  const addCodeField = () => {
    const ph = document.getElementById('fcaPhone'); if (!ph || document.getElementById('fcaRef')) return;
    let code = ''; try { code = localStorage.getItem('fc_ref') || (window.FutureChatNative && window.FutureChatNative.installRef && window.FutureChatNative.installRef()) || ''; } catch (_) {}
    ph.insertAdjacentHTML('afterend', '<label for="fcaRef">Invite code (optional)</label><input id="fcaRef" type="text" autocapitalize="characters" maxlength="14" placeholder="From the friend who invited you" value="' + esc(String(code).toUpperCase()) + '">');
    document.getElementById('fcaRef').addEventListener('input', e => { try { localStorage.setItem('fc_ref', e.target.value.trim().toLowerCase()); } catch (_) {} });
  };
  new MutationObserver(addCodeField).observe(document.documentElement, { childList: true, subtree: true });
  try { const q = new URLSearchParams(location.search); if (q.get('ref')) localStorage.setItem('fc_ref', q.get('ref').toLowerCase()); if (q.get('fcx') === 'give') setTimeout(() => G.open(), 1500); } catch (_) {}
  setTimeout(() => { claim(); load(); }, 2500);

  const css = document.createElement('style');
  css.textContent = [
    '.fcg-hero{position:relative;overflow:hidden;text-align:center;border-radius:22px;padding:22px 16px;background:linear-gradient(150deg,#065f46,#0e8c9e 55%,#ca8a04);color:#fff;margin-bottom:12px}',
    '.fcg-hero small{letter-spacing:.12em;font-weight:800;opacity:.9}.fcg-hero b{display:block;font-size:34px;margin:6px 0 2px;text-shadow:0 2px 12px rgba(0,0,0,.25)}.fcg-hero p{margin:0 0 12px;opacity:.95}',
    '.fcg-hero .tk{display:flex;justify-content:center;gap:10px}.fcg-hero .tk div{background:rgba(0,0,0,.22);border-radius:14px;padding:10px 12px;min-width:84px}.fcg-hero .tk em{display:block;font-style:normal;font-size:24px;font-weight:900}.fcg-hero .tk span{font-size:11.5px;opacity:.9}',
    '.fcg-hero .fx{position:absolute;inset:0;pointer-events:none}.fcg-hero .fx span{position:absolute;bottom:-30px;font-size:22px;animation:fcpRise 5s linear infinite}',
    '@keyframes fcpRise{0%{transform:translateY(0);opacity:0}15%{opacity:1}100%{transform:translateY(-260px);opacity:0}}',
    '.fcg-cta{display:grid;grid-template-columns:44px 1fr;align-items:center;text-align:left;width:100%;margin:6px 0 14px;padding:14px;border:0;border-radius:18px;background:linear-gradient(120deg,#065f46,#0e8c9e,#ca8a04);color:#fff;font:inherit;box-shadow:0 8px 24px rgba(0,0,0,.25)}.fcg-cta span{grid-row:span 2;font-size:30px}.fcg-cta b{font-size:17px}.fcg-cta small{opacity:.9}',
    '.fcg-strip{display:flex;align-items:center;gap:6px;margin:8px 12px}.fcg-strip .go{flex:1;display:grid;grid-template-columns:36px 1fr;align-items:center;text-align:left;padding:10px 12px;border-radius:16px;border:1px solid rgba(202,138,4,.5);background:linear-gradient(120deg,rgba(6,95,70,.6),rgba(202,138,4,.35));color:#fff;font:inherit}.fcg-strip .go span{grid-row:span 2;font-size:24px}.fcg-strip .go small{color:#fde68a}.fcg-strip .x{border:0;background:transparent;color:#9cb7cc;font-size:16px;padding:8px}'
  ].join('');
  document.head.appendChild(css);
})();
