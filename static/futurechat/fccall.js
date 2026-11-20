/* FC-CALLUI-01 + FC-RECONNECT-01 (owner 2026-11-20). Future Chat app only — loaded on /futurechat-app, never in Skillvaya.
   - The call's top button no longer ends the call: it shrinks the call into a small window over your chats (tap it to go back).
     "End call" still ends the call.
   - The phone's back button closes Filters first, then shrinks the call (it never ends the call).
   - A call that drops reconnects by itself: the caller sends a fresh connection offer (ICE restart) through
     /api/video-calls action "restart" and the other phone answers it. */
(function () {
  'use strict';
  if (!window.SV_FC_APP) return;
  const active = () => { try { return typeof svActiveVideoCall !== 'undefined' ? svActiveVideoCall : null; } catch (_) { return null; } };
  const myId = () => { try { return typeof me !== 'undefined' && me ? Number(me.id) : 0; } catch (_) { return 0; } };
  const call$ = (url, opts) => { try { if (typeof api === 'function') return api(url, opts); } catch (_) {} return Promise.reject(new Error('not ready')); };
  const modal = () => document.getElementById('svVideoCallModal');
  const isOpen = m => !!m && !m.classList.contains('hidden');
  const fxOpen = () => { const b = document.getElementById('svFxBar'); return !!(b && !b.hidden && b.getClientRects().length); };   // hidden on voice calls = not open
  const closeFx = () => { if (fxOpen()) { try { svToggleFxBar(); } catch (_) { const b = document.getElementById('svFxBar'); if (b) b.hidden = true; } } };
  const setState = t => { try { svSetCallState(t); } catch (_) {} };

  // ---------------------------------------------------------------- small call window
  const st = document.createElement('style');
  st.textContent = [
    'html .sv-call-overlay.fc-min{inset:auto 12px calc(env(safe-area-inset-bottom) + 86px) auto!important;width:118px!important;height:170px!important;padding:0!important;background:#000!important;border-radius:18px!important;overflow:hidden!important;box-shadow:0 10px 30px rgba(0,0,0,.55)!important;border:2px solid #1ed6c8!important;display:block!important}',
    'html .sv-call-overlay.fc-min .sv-call-panel{position:relative!important;height:100%!important;min-height:0!important;max-height:none!important;padding:0!important;border-radius:0!important;background:#000!important;overflow:hidden!important}',
    'html .sv-call-overlay.fc-min .sv-call-header,html .sv-call-overlay.fc-min .sv-call-actions,html .sv-call-overlay.fc-min #svFxBar,html .sv-call-overlay.fc-min .sv-call-note,html .sv-call-overlay.fc-min .sv-call-local-wrap,html .sv-call-overlay.fc-min .sv-call-video-label,html .sv-call-overlay.fc-min .sv-call-audio-only{display:none!important}',
    'html .sv-call-overlay.fc-min .sv-call-videos{position:absolute!important;inset:0!important;height:100%!important;margin:0!important;padding:0!important}',
    'html .sv-call-overlay.fc-min .sv-call-remote-wrap{position:absolute!important;inset:0!important;border-radius:0!important}',
    'html .sv-call-overlay.fc-min video{width:100%!important;height:100%!important;object-fit:cover!important;max-height:none!important}',
    '#fcCallTap{position:absolute;inset:0;z-index:5;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:2px;padding:0 4px 10px;border:0;background:linear-gradient(rgba(0,0,0,0) 45%,rgba(0,0,0,.7));color:#fff;font:700 12px/1.2 sans-serif;text-align:center}',
    '#fcCallTap b{font-size:22px}',
    '.fc-call-mini-btn{white-space:nowrap}',
    // FC-FXSMALL-01: a smaller, neater Filters panel so the other person's video stays big
    'html #svFxBar{max-height:30vh!important;overflow-y:auto!important;flex:none!important;margin-top:4px!important}',
    'html #svFxBar .sv-fx-bar{gap:6px!important;padding:4px 2px 2px!important}',
    'html #svFxBar .sv-fx-chip{padding:5px 11px!important;font-size:12.5px!important}',
    'html #svFxBar .sv-lens-title{font-size:12.5px!important;margin:6px 2px 0!important;padding:0!important}',
    'html #svFxBar .sv-lens-chip{width:44px!important;height:44px!important;padding:4px!important}',
    'html #svFxBar .sv-orig-chip{min-width:44px!important;height:44px!important;padding:3px 6px!important;gap:0!important}',
    'html #svFxBar .sv-orig-chip small{font-size:9px!important}',
    'html #svFxBar .sv-lens-chip img{width:30px!important;height:30px!important}',
    'html #svFxBar .sv-orig-chip span{font-size:21px!important;line-height:1!important}',
    // FC-VOICENOFX-01 (owner 2026-11-20): no Filters on a voice call (nothing to filter) - video calls keep them
    'html .sv-call-overlay.sv-call-voice-only #svFxBar,html .sv-call-overlay.sv-call-voice-only button[onclick^="svToggleFxBar"]{display:none!important}'
  ].join('');
  document.head.appendChild(st);

  let tapBtn = null;
  function minimise() {
    const m = modal(); if (!isOpen(m) || !active()) return;
    closeFx();
    m.classList.add('fc-min');
    if (!tapBtn) {
      tapBtn = document.createElement('button'); tapBtn.type = 'button'; tapBtn.id = 'fcCallTap'; tapBtn.setAttribute('aria-label', 'Go back to the call');
      tapBtn.onclick = e => { e.preventDefault(); e.stopPropagation(); restore(); };
    }
    tapBtn.innerHTML = (m.classList.contains('sv-call-voice-only') ? '<b>📞</b>' : '') + '<span>On call<br>Tap to return</span>';
    m.appendChild(tapBtn);
    leaveState();
  }
  function restore() {
    const m = modal(); if (!m) return;
    m.classList.remove('fc-min'); if (tapBtn) tapBtn.remove();
    if (isOpen(m) && active()) pushState();
  }
  function patchClose(m) {
    const b = m.querySelector('.sv-call-header button'); if (!b || b.dataset.fcmin) return;
    b.dataset.fcmin = '1'; b.removeAttribute('onclick'); b.classList.add('fc-call-mini-btn');
    b.textContent = '💬 Chats'; b.setAttribute('aria-label', 'Keep the call going and go to your chats');
    b.onclick = e => { e.preventDefault(); if (active()) minimise(); else { try { closeSkillvayaVideoCall(true); } catch (_) {} } };
  }

  // ---------------------------------------------------------------- phone back button
  // The call screen adds one history entry. Back: Filters open -> close Filters; otherwise shrink the call.
  let pushed = false, skipPop = 0;
  function pushState() { if (pushed) return; try { history.pushState({ fccall: 1 }, ''); pushed = true; } catch (_) {} }
  function leaveState() {
    if (!pushed) return; pushed = false;
    if (history.state && history.state.fccall) { skipPop++; try { history.back(); } catch (_) { skipPop--; } }
  }
  window.addEventListener('popstate', e => {
    if (skipPop > 0) { skipPop--; e.stopImmediatePropagation(); return; }
    if (!pushed) return;
    pushed = false;   // our entry was taken off by the back button
    const m = modal();
    if (!isOpen(m) || !active() || m.classList.contains('fc-min')) return;
    e.stopImmediatePropagation();
    if (fxOpen()) { closeFx(); pushState(); return; }
    minimise();
  }, true);

  // ---------------------------------------------------------------- reconnect a dropped call
  const R = { id: '', last: 0, busy: false, badSince: 0, tries: 0, lastTry: 0, polling: false, polledAt: 0, hooked: null, offerId: 0 };
  const sigUrl = (call, after) => '/api/video-calls/' + encodeURIComponent(call.callId) + '?after=' + (after || 0);
  const descOf = pc => ({ type: pc.localDescription.type, sdp: pc.localDescription.sdp });
  async function readdCandidates(call, afterId) {
    // Candidates sent right after a reconnect can arrive before the new offer/answer is applied; add them again now.
    try {
      const d = await call$(sigUrl(call, afterId)); const me2 = myId();
      for (const ev of ((d.call || {}).signals || [])) {
        if (ev.kind !== 'candidate' || Number(ev.sender_id) === me2) continue;
        try { await call.pc.addIceCandidate(new RTCIceCandidate(JSON.parse(ev.payload))); } catch (_) {}
      }
    } catch (_) {}
  }
  async function restart(call) {
    R.busy = true; R.tries++; R.lastTry = Date.now();
    setState('Connection dropped — reconnecting…');
    try {
      try { if (call.pc.restartIce) call.pc.restartIce(); } catch (_) {}
      const offer = await call.pc.createOffer({ iceRestart: true });
      await call.pc.setLocalDescription(offer);
      const r = await call$('/api/video-calls', { method: 'POST', body: JSON.stringify({ action: 'restart', call_id: call.callId, sdp: descOf(call.pc) }) });
      R.offerId = Number(r && r.signal_id) || 0;
    } catch (e) { R.busy = false; console.warn('Future Chat reconnect offer failed', e && e.message); }
    const mine = R.lastTry;
    setTimeout(() => {
      if (!R.busy || R.lastTry !== mine) return;
      R.busy = false;   // no answer: allow another try
      try { if (call.pc && call.pc.signalingState === 'have-local-offer') call.pc.setLocalDescription({ type: 'rollback' }).catch(() => {}); } catch (_) {}
    }, 9000);
  }
  async function answerRestart(call, offer, offerId) {
    try {
      setState('Connection dropped — reconnecting…');
      await call.pc.setRemoteDescription(new RTCSessionDescription(offer));
      const ans = await call.pc.createAnswer(); await call.pc.setLocalDescription(ans);
      await call$('/api/video-calls', { method: 'POST', body: JSON.stringify({ action: 'restart', call_id: call.callId, sdp: descOf(call.pc) }) });
      await readdCandidates(call, offerId);
    } catch (e) { console.warn('Future Chat reconnect answer failed', e && e.message); }
  }
  async function poll(call, fast) {
    if (R.polling || Date.now() - R.polledAt < (fast ? 600 : 1500)) return;
    R.polling = true; R.polledAt = Date.now();
    try {
      const d = await call$(sigUrl(call, R.last)); const me2 = myId();
      if (active() !== call) return;
      for (const ev of ((d.call || {}).signals || [])) {
        const id = Number(ev.id) || 0; R.last = Math.max(R.last, id);
        if (Number(ev.sender_id) === me2) continue;
        if (ev.kind === 'restart_offer' && !call.isCaller) await answerRestart(call, JSON.parse(ev.payload), id);
        else if (ev.kind === 'restart_answer' && call.isCaller && call.pc.signalingState === 'have-local-offer') {
          try { await call.pc.setRemoteDescription(new RTCSessionDescription(JSON.parse(ev.payload))); await readdCandidates(call, R.offerId); } catch (e) { console.warn('Future Chat reconnect failed', e && e.message); }
          R.busy = false;
        }
      }
    } catch (_) {} finally { R.polling = false; }
  }
  function watchCall(call) {
    if (!call || !call.pc || !call.callId) return;
    if (R.id !== call.callId) Object.assign(R, { id: call.callId, last: 0, busy: false, badSince: 0, tries: 0, lastTry: 0, hooked: null, offerId: 0 });
    const pc = call.pc;
    if (R.hooked !== pc) {
      R.hooked = pc;
      pc.addEventListener('connectionstatechange', () => {
        const s = pc.connectionState;
        if (s === 'failed' || s === 'disconnected') setState('Connection dropped — reconnecting…');
        if (s === 'connected') { R.badSince = 0; R.tries = 0; }
      });
    }
    const answered = call.isCaller ? !!call.remoteDescriptionSet : true;
    if (!answered) return;
    const s = pc.connectionState, bad = s === 'failed' || s === 'disconnected';
    if (bad) { if (!R.badSince) R.badSince = Date.now(); } else R.badSince = 0;
    poll(call, bad || R.busy);
    if (bad && call.isCaller && !R.busy && R.tries < 8 && Date.now() - R.lastTry > 9000 && (s === 'failed' || Date.now() - R.badSince > 3500)) restart(call);
  }

  // ---------------------------------------------------------------- keep everything in step
  setInterval(() => {
    const m = modal(), call = active();
    if (!m) return;
    patchClose(m);
    if (isOpen(m) && call) { if (!m.classList.contains('fc-min')) pushState(); }
    else { if (m.classList.contains('fc-min')) { m.classList.remove('fc-min'); if (tapBtn) tapBtn.remove(); } leaveState(); }
    if (call) watchCall(call);
  }, 400);
})();
