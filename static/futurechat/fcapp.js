/* FCAPP-01: stand-alone Future Chat app mode.
   Loaded only on /futurechat-app (window.SV_FC_APP = 1). Uses the same accounts, chats and calls as Future Chat inside
   Skillvaya; only the screen around it changes: Future Chat fills the screen, its own sign-in, and an Account menu. */
(function () {
  'use strict';
  if (!window.SV_FC_APP) return;
  document.documentElement.classList.add('fc-app');
  const css = document.createElement('style');
  css.textContent = [
    'html.fc-app{--fc-nav:0px!important}',
    'html.fc-app body{overflow:hidden!important;background:#071426!important}',
    'html.fc-app .bottom-tabbar{display:none!important}',
    'html.fc-app #fcRoot{top:0!important;bottom:0!important}',
    '#fcaAuth{position:fixed;inset:0;z-index:12000;overflow:auto;-webkit-overflow-scrolling:touch;color:#eaf4ff;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:linear-gradient(160deg,#071426 0%,#0b2a52 55%,#0d6f86 100%)}',
    '#fcaAuth .fca-w{max-width:440px;margin:0 auto;padding:max(28px,env(safe-area-inset-top)) 22px 40px}',
    '#fcaAuth .fca-brand{display:flex!important;flex-direction:row;align-items:center;gap:14px;margin:8px 0 18px;text-align:left}',
    '#fcaAuth .fca-brand .fca-lg{flex:none;width:56px;height:56px;border-radius:16px;display:grid;place-items:center;background:rgba(255,255,255,.12);box-shadow:0 6px 18px rgba(0,0,0,.25)}',
    '#fcaAuth .fca-brand b{display:block;font-size:26px;line-height:1.15;letter-spacing:.2px;margin:0;color:#fff}#fcaAuth .fca-brand small{display:block;color:#a9c8e7;font-size:13.5px;line-height:1.35;margin-top:3px;font-weight:500}#fcaAuth .fca-brand>div:last-child{min-width:0;flex:1}#fcaAuth *{box-sizing:border-box}#fcaAuth .fca-lg svg{width:34px;height:34px}',
    '#fcaAuth .fca-tabs{display:grid;grid-template-columns:1fr 1fr;background:rgba(255,255,255,.08);border-radius:14px;padding:4px;margin:10px 0 18px}',
    '#fcaAuth .fca-tabs button{border:0;border-radius:11px;padding:11px;font-weight:700;font-size:15px;background:transparent;color:#cfe3f7}',
    '#fcaAuth .fca-tabs button.on{background:#fff;color:#0b2447}',
    '#fcaAuth label{display:block;font-size:13px;color:#a9c8e7;margin:12px 0 6px}',
    '#fcaAuth input[type=text],#fcaAuth input[type=email],#fcaAuth input[type=tel],#fcaAuth input[type=password]{width:100%;box-sizing:border-box;border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.07);color:#fff;border-radius:12px;padding:13px 14px;font-size:16px;outline:none}',
    '#fcaAuth input:focus{border-color:#5fd3e6}',
    '#fcaAuth .fca-tick{display:flex;gap:10px;align-items:flex-start;margin:16px 0 4px;font-size:14px;color:#cfe3f7;line-height:1.4}',
    '#fcaAuth .fca-tick input{width:20px;height:20px;flex:none;margin-top:1px}',
    '#fcaAuth a{color:#7fe3f2}',
    '#fcaAuth .fca-go{width:100%;margin-top:18px;border:0;border-radius:14px;padding:15px;font-size:16px;font-weight:800;color:#06233f;background:linear-gradient(90deg,#5fd3e6,#8ab8ff)}',
    '#fcaAuth .fca-go[disabled]{opacity:.6}',
    '#fcaAuth .fca-msg{min-height:20px;margin-top:12px;font-size:14px;color:#ffd0d0}',
    '#fcaAuth .fca-forgot{display:block;margin:14px auto 0;border:0;background:transparent;color:#7fe3f2;font-size:15px;font-weight:700;text-decoration:underline;padding:6px}',
    '#fcaAuth .fca-note{margin-top:22px;font-size:12.5px;color:#8fb0cf;line-height:1.5}',
    '.fca-row{display:flex;align-items:center;gap:12px;width:100%;border:0;background:transparent;text-align:left;padding:13px 4px;font-size:16px;color:#0b1d33;border-bottom:1px solid #e6edf6}',
    '.fca-row small{display:block;color:#55667d;font-size:13px}.fca-row.danger{color:#b42318}',
    '.fca-me{padding:4px 4px 12px;border-bottom:1px solid #e6edf6}.fca-me b{font-size:18px;color:#0b1d33}.fca-me small{display:block;color:#55667d}'
  ].join('');
  document.head.appendChild(css);

  const tok = () => { try { return localStorage.getItem('skillvaya_token') || localStorage.getItem('sv_token') || ''; } catch (_) { return ''; } };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  async function post(path, body) {
    const t = tok();
    const r = await fetch(path, { method: 'POST', cache: 'no-store', credentials: 'same-origin', headers: Object.assign({ 'Content-Type': 'application/json' }, t ? { Authorization: 'Bearer ' + t } : {}), body: JSON.stringify(body || {}) });
    let d = {}; try { d = await r.json(); } catch (_) {}
    if (!r.ok) { const e = new Error(d.error || 'Something went wrong. Please try again.'); e.data = d; throw e; }
    return d;
  }
  function saveSession(d) {
    try {
      localStorage.setItem('skillvaya_token', d.token); localStorage.setItem('sv_token', d.token);
      localStorage.setItem('skillvaya_user', JSON.stringify({ id: d.user.id, name: d.user.name, email: d.user.email, role: d.user.role }));
    } catch (_) {}
  }
  function country() { try { return (typeof window.svCountry === 'function' && window.svCountry()) || 'ZA'; } catch (_) { return 'ZA'; } }

  // ---------- sign in / create account
  function showAuth(mode) {
    let el = document.getElementById('fcaAuth');
    if (!el) { el = document.createElement('div'); el.id = 'fcaAuth'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', 'Future Chat sign in'); document.body.appendChild(el); }
    const logo = '<svg viewBox="0 0 48 48" aria-hidden="true"><defs><linearGradient id="fcaG" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5fd3e6"/><stop offset="1" stop-color="#1aa6b8"/></linearGradient></defs><path d="M8 9h32a5 5 0 0 1 5 5v17a5 5 0 0 1-5 5H21l-9 7v-7H8a5 5 0 0 1-5-5V14a5 5 0 0 1 5-5z" fill="url(#fcaG)"/><rect x="12" y="18" width="22" height="3.4" rx="1.7" fill="#fff"/><rect x="12" y="25" width="15" height="3.4" rx="1.7" fill="#fff"/></svg>';
    const create = mode === 'create';
    el.innerHTML = '<div class="fca-w"><div class="fca-brand"><div class="fca-lg">' + logo + '</div><div><b>Future Chat</b><small>Chats, calls and Chatmoji with the people you know</small></div></div>' +
      '<div class="fca-tabs" role="tablist"><button type="button" data-m="signin" class="' + (create ? '' : 'on') + '">Sign in</button><button type="button" data-m="create" class="' + (create ? 'on' : '') + '">Create account</button></div>' +
      '<form id="fcaForm" novalidate>' +
      (create ? '<label for="fcaName">Your name</label><input id="fcaName" type="text" autocomplete="name" required>' : '') +
      '<label for="fcaEmail">Email</label><input id="fcaEmail" type="email" autocomplete="email" inputmode="email" required>' +
      (create ? '<label for="fcaPhone">Mobile number</label><input id="fcaPhone" type="tel" autocomplete="tel" inputmode="tel" placeholder="e.g. 082 123 4567" required>' : '') +
      '<label for="fcaPw">Password' + (create ? ' (8 or more characters)' : '') + '</label><input id="fcaPw" type="password" autocomplete="' + (create ? 'new-password' : 'current-password') + '" required>' +
      '<label class="fca-tick"><input id="fcaTerms" type="checkbox"><span>I have read and agree to the <a href="/terms" target="_blank" rel="noopener">Terms, Rules &amp; Safety</a> and the <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>. I am 13 or older.</span></label>' +
      '<button class="fca-go" type="submit">' + (create ? 'Create my account' : 'Sign in') + '</button><div class="fca-msg" id="fcaMsg" role="alert"></div>' + (create ? '' : '<button type="button" class="fca-forgot" id="fcaForgot">Forgot your password?</button>') + '</form>' +
      '<p class="fca-note">' + (create ? 'Your number lets friends and family find you and call you on Future Chat. We confirm it with a code.' : 'Already use Skillvaya? Sign in with the same email and password. Your chats are the same in both apps.') +
      ' <a href="/account-deletion" target="_blank" rel="noopener">Delete an account</a></p></div>';
    el.querySelectorAll('.fca-tabs button').forEach(b => b.onclick = () => showAuth(b.dataset.m));
    const form = el.querySelector('#fcaForm'), msg = el.querySelector('#fcaMsg'), go = el.querySelector('.fca-go');
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
      go.disabled = true;
      try {
        let d;
        if (create) d = await post('/api/signup', { name: v('fcaName').trim(), email: v('fcaEmail').trim(), phone: v('fcaPhone').trim(), password: v('fcaPw'), role: 'customer', country: country(), accept_terms: true });
        else d = await post('/api/login', { email: v('fcaEmail').trim(), password: v('fcaPw'), accept_terms: true });
        saveSession(d);
        location.replace('/futurechat-app' + (create ? '?fc_verify=1' : ''));
      } catch (err) { msg.textContent = err.message; go.disabled = false; }
    };
  }

  // ---------- account menu (top-left button in Future Chat)
  window.fcAppMenu = async function () {
    let me = null; try { me = JSON.parse(localStorage.getItem('skillvaya_user') || 'null'); } catch (_) {}
    try { if (window.me && window.me.name) me = Object.assign({}, me || {}, { name: window.me.name, email: window.me.email }); } catch (_) {}
    try { const r = await fetch('/api/phone/status', { headers: { Authorization: 'Bearer ' + tok() }, cache: 'no-store' }); if (r.ok) { const st = await r.json(); me = Object.assign({}, me || {}, { phone: st.phone, verified: st.verified }); } } catch (_) {}
    const dim = document.createElement('div'); dim.className = 'fc-dim';
    dim.innerHTML = '<div class="fc-sheet" role="dialog" aria-modal="true" aria-label="Account and settings"><div class="fc-handle"></div>' +
      '<div class="fca-me"><b>' + esc((me && me.name) || 'Your account') + '</b><small>' + esc((me && me.email) || '') + '</small><small>' + esc(me && me.phone ? me.phone + (me.verified ? ' · confirmed' : ' · not confirmed') : 'No mobile number yet') + '</small></div>' +
      '<button class="fca-row" data-a="phone">📱<span>Mobile number<small>Add or change the number people use to find you</small></span></button>' +
      '<button class="fca-row" data-a="invite">💌<span>Invite friends<small>Share a link to Future Chat</small></span></button>' +
      '<button class="fca-row" data-a="terms">📄<span>Terms, Rules &amp; Safety</span></button>' +
      '<button class="fca-row" data-a="privacy">🔒<span>Privacy Policy</span></button>' +
      '<button class="fca-row" data-a="signout">🚪<span>Sign out</span></button>' +
      '<button class="fca-row danger" data-a="delete">🗑️<span>Delete my account<small>Ask us to delete your account and data</small></span></button></div>';
    const done = () => dim.remove();
    dim.addEventListener('click', e => { if (e.target === dim) done(); });
    document.body.appendChild(dim);
    dim.querySelectorAll('[data-a]').forEach(b => b.onclick = async () => {
      const a = b.dataset.a; done();
      if (a === 'phone') { try { window.FutureChat.verifyPhone(true); } catch (_) {} }
      else if (a === 'invite') { try { window.FutureChat.inviteFriends(); } catch (_) {} }
      else if (a === 'terms') window.open('/terms', '_blank');
      else if (a === 'privacy') window.open('/privacy', '_blank');
      else if (a === 'signout') {
        if (!confirm('Sign out of Future Chat on this phone?')) return;
        try { await post('/api/logout', {}); } catch (_) {}
        try { ['skillvaya_token', 'sv_token', 'skillvaya_user'].forEach(k => localStorage.removeItem(k)); } catch (_) {}
        location.replace('/futurechat-app');
      } else if (a === 'delete') {
        const reason = prompt('We are sorry to see you go. Tell us why (optional), then press OK to ask us to delete your account and data.');
        if (reason === null) return;
        try { const d = await post('/api/account/delete-request', { reason: reason || 'Requested in the Future Chat app' }); alert(d.message || 'Your deletion request has been recorded. We will confirm by email.'); }
        catch (err) { alert('Could not send your request: ' + err.message + '\nYou can also use ' + location.origin + '/account-deletion'); }
      }
    });
  };

  // ---------- keep Future Chat on screen
  function boot() {
    if (!tok()) { showAuth('signin'); return; }
    // The chat list is the app's first screen: no extra history entry, so Back on the list closes the app.
    try { history.replaceState({ fc: 'list' }, ''); } catch (_) {}
    const p = new URLSearchParams(location.search);
    if (!p.get('fc')) { try { window.FutureChat.open(); } catch (_) {} }
    setInterval(() => {
      if (!tok() || document.getElementById('fcaAuth')) return;
      const r = document.getElementById('fcRoot');
      if (window.FutureChat && (!r || !r.classList.contains('open'))) { try { window.FutureChat.open(); } catch (_) {} }
    }, 700);
  }
  function whenReady() { if (window.FutureChat) boot(); else setTimeout(whenReady, 100); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', whenReady); else whenReady();
})();
