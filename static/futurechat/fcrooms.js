/* FCR-01 (owner 2026-11-19): Future Chat Game Rooms - talk by voice with your squad while you play.
   Up to 6 people, every phone sends its voice straight to the others (WebRTC mesh, TURN relay when needed),
   low-data mono Opus (~24 kbps, 16 kbps with Data saver), echo cancellation + noise suppression.
   Open mic or push-to-talk, mute, who's talking, invite by link or in a chat, owner can remove people / close the room.
   On the Android app the voice keeps going while a game is open (GameVoiceService: notification with Mute / Leave and
   a floating F bubble over the game). Server: fcrooms.py (/api/fcr/*). Loaded after fcadmin.js on /futurechat-app. */
(function () {
  'use strict';
  const FCX = window.FCX; if (!window.SV_FC_APP || !FCX || !FCX.kit) return;
  const K = FCX.kit, { api, post, esc, $, toast, sheet, frame, push, pop, row, bind, openPanel, X, avatar } = K;
  const NATIVE = () => { const n = window.FutureChatNative; return n && typeof n.roomStart === 'function' ? n : null; };
  const top = () => X.stack[X.stack.length - 1];
  const R = FCX.rooms = { cur: null };
  const BEAT_MS = 1500, MISS_LIMIT = 3;
  const GAME_ICONS = { 'Free Fire': '🔥', 'PUBG Mobile': '🪖', 'Call of Duty Mobile': '🎯', 'Roblox': '🧱', 'Minecraft': '⛏️', 'EA FC': '⚽', 'eFootball': '⚽',
    'Fortnite': '🏗️', 'Mobile Legends': '⚔️', 'Clash Royale': '👑', 'Among Us': '🚀', 'Genshin Impact': '🌌', 'Brawl Stars': '⭐', 'Other': '🎮' };
  const gIcon = g => GAME_ICONS[g] || '🎮';
  let GAMES = Object.keys(GAME_ICONS);
  const MIC = '<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
  const MICOFF = '<svg viewBox="0 0 24 24"><path d="M15 9V6a3 3 0 0 0-5.7-1.3M9 9v2a3 3 0 0 0 5 2.2M5 11a7 7 0 0 0 11.7 5.2M19 11a7 7 0 0 1-.6 2.8M12 18v3M3 3l18 18"/></svg>';
  const dataSaver = () => { try { return !!(window.FCX.dataSaver && window.FCX.dataSaver()); } catch (_) { return false; } };

  // ================================================================ voice engine
  function cur() { return R.cur; }
  async function getMic() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('Voice isn\'t available on this phone.');
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 }, video: false });
    } catch (e) {
      const n = e && e.name;
      if (n === 'NotAllowedError' || n === 'SecurityError') throw new Error('Future Chat needs the microphone for Game Rooms. Allow it in your phone\'s Settings → Apps → Future Chat → Permissions.');
      if (n === 'NotReadableError') throw new Error('Another app is using the microphone. Close it (or end the call) and try again.');
      throw new Error('The microphone couldn\'t start. Please try again.');
    }
  }
  function tuneOpus(sdp) {
    const kbps = dataSaver() ? 16000 : 24000;
    const m = sdp.match(/a=rtpmap:(\d+) opus\/48000/i); if (!m) return sdp;
    const pt = m[1], want = 'maxaveragebitrate=' + kbps + ';stereo=0;sprop-stereo=0;useinbandfec=1;usedtx=1';
    const re = new RegExp('a=fmtp:' + pt + ' ([^\\r\\n]*)');
    if (re.test(sdp)) return sdp.replace(re, (all, p) => 'a=fmtp:' + pt + ' ' + p.split(';').filter(x => x && !/^(maxaveragebitrate|stereo|sprop-stereo|useinbandfec|usedtx)=/.test(x.trim())).concat(want).join(';'));
    return sdp.replace('a=rtpmap:' + pt + ' opus/48000/2', 'a=rtpmap:' + pt + ' opus/48000/2\r\na=fmtp:' + pt + ' ' + want);
  }
  function limitSender(pc) {
    try { pc.getSenders().forEach(s => { if (!s.track || s.track.kind !== 'audio') return; const p = s.getParameters(); p.encodings = p.encodings && p.encodings.length ? p.encodings : [{}]; p.encodings[0].maxBitrate = dataSaver() ? 16000 : 24000; s.setParameters(p).catch(() => {}); }); } catch (_) {}
  }
  let outbox = [], outTimer = 0;
  function sendSignal(to, kind, body) {
    const c = cur(); if (!c) return;
    outbox.push({ to, kind, body: typeof body === 'string' ? body : JSON.stringify(body || {}) });
    if (!outTimer) outTimer = setTimeout(flushSignals, kind === 'cand' ? 120 : 0);
  }
  async function flushSignals() {
    outTimer = 0; const c = cur(); if (!c || !outbox.length) { outbox = []; return; }
    const items = outbox.splice(0, 60);
    try { await post('/api/fcr/signal', { code: c.code, items }); } catch (_) { /* the peer is gone or we left: harmless */ }
    if (outbox.length) outTimer = setTimeout(flushSignals, 50);
  }
  function makePeer(uid) {
    const c = cur(); if (!c) return null;
    const pc = new RTCPeerConnection({ iceServers: c.ice, bundlePolicy: 'max-bundle', iceCandidatePoolSize: 2 });
    const p = { uid, pc, cands: [], audio: null, an: null, level: 0, talk: false, failT: 0, offerer: c.me < uid, created: Date.now() };
    c.peers.set(uid, p);
    c.stream.getAudioTracks().forEach(t => pc.addTrack(t, c.stream));
    pc.onicecandidate = e => { if (e.candidate) sendSignal(uid, 'cand', e.candidate.toJSON ? e.candidate.toJSON() : { candidate: e.candidate.candidate, sdpMid: e.candidate.sdpMid, sdpMLineIndex: e.candidate.sdpMLineIndex }); };
    pc.ontrack = e => {
      const st = (e.streams && e.streams[0]) || new MediaStream([e.track]);
      if (!p.audio) { p.audio = document.createElement('audio'); p.audio.autoplay = true; p.audio.setAttribute('playsinline', ''); audioBox().appendChild(p.audio); }
      p.audio.srcObject = st; p.audio.play().catch(() => {});
      p.an = meter(st);
    };
    pc.onconnectionstatechange = () => {
      const s = pc.connectionState;
      if (s === 'connected') { clearTimeout(p.failT); p.failT = 0; limitSender(pc); paint(); }
      else if (s === 'disconnected') { clearTimeout(p.failT); p.failT = setTimeout(() => { if (pc.connectionState !== 'connected') dropPeer(uid); }, 9000); paint(); }
      else if (s === 'failed') { dropPeer(uid); }
    };
    return p;
  }
  function dropPeer(uid) {
    const c = cur(); if (!c) return; const p = c.peers.get(uid); if (!p) return;
    c.peers.delete(uid); clearTimeout(p.failT);
    try { p.pc.close(); } catch (_) {}
    if (p.audio) { try { p.audio.srcObject = null; p.audio.remove(); } catch (_) {} }
    paint();   // the lower id offers again on the next heartbeat if they're still in the room
  }
  async function offer(p) {
    try {
      const o = await p.pc.createOffer({ offerToReceiveAudio: true });
      o.sdp = tuneOpus(o.sdp); await p.pc.setLocalDescription(o);
      sendSignal(p.uid, 'offer', { type: 'offer', sdp: p.pc.localDescription.sdp });
    } catch (_) { dropPeer(p.uid); }
  }
  async function onSignal(s) {
    const c = cur(); if (!c) return;
    let body = {}; try { body = JSON.parse(s.body || '{}'); } catch (_) {}
    if (s.kind === 'bye') { dropPeer(s.from); return; }
    if (s.kind === 'offer') {
      dropPeer(s.from);                         // a fresh offer always starts a fresh connection (they rejoined / restarted)
      const p = makePeer(s.from); if (!p) return;
      try {
        await p.pc.setRemoteDescription({ type: 'offer', sdp: body.sdp });
        const a = await p.pc.createAnswer(); a.sdp = tuneOpus(a.sdp); await p.pc.setLocalDescription(a);
        sendSignal(s.from, 'answer', { type: 'answer', sdp: p.pc.localDescription.sdp });
        for (const cd of p.cands.splice(0)) { try { await p.pc.addIceCandidate(cd); } catch (_) {} }
      } catch (_) { dropPeer(s.from); }
      return;
    }
    const p = c.peers.get(s.from); if (!p) return;
    if (s.kind === 'answer') {
      try { if (p.pc.signalingState === 'have-local-offer') await p.pc.setRemoteDescription({ type: 'answer', sdp: body.sdp }); for (const cd of p.cands.splice(0)) { try { await p.pc.addIceCandidate(cd); } catch (_) {} } } catch (_) { dropPeer(s.from); }
    } else if (s.kind === 'cand') {
      if (p.pc.remoteDescription && p.pc.remoteDescription.type) { try { await p.pc.addIceCandidate(body); } catch (_) {} } else p.cands.push(body);
    }
  }
  // ---- who's talking (local level meters, no server round trip)
  let actx = null;
  function meter(stream) {
    try {
      actx = actx || new (window.AudioContext || window.webkitAudioContext)();
      if (actx.state === 'suspended') actx.resume().catch(() => {});
      const src = actx.createMediaStreamSource(stream), an = actx.createAnalyser(); an.fftSize = 512; src.connect(an);
      return { an, buf: new Uint8Array(an.fftSize), src };
    } catch (_) { return null; }
  }
  function level(m) {
    if (!m) return 0; m.an.getByteTimeDomainData(m.buf); let s = 0;
    for (let i = 0; i < m.buf.length; i++) { const v = (m.buf[i] - 128) / 128; s += v * v; }
    return Math.sqrt(s / m.buf.length);
  }
  function tickTalk() {
    const c = cur(); if (!c) return;
    let changed = false;
    const mineLive = c.stream && c.stream.getAudioTracks().some(t => t.enabled);
    const lv = mineLive ? level(c.localMeter) : 0;
    c.myLevel = c.myLevel * 0.6 + lv * 0.4;
    const meTalk = c.myLevel > 0.035;
    if (meTalk !== c.meTalk) { c.meTalk = meTalk; changed = true; }
    c.peers.forEach(p => { p.level = p.level * 0.6 + level(p.an) * 0.4; const t = p.level > 0.03; if (t !== p.talk) { p.talk = t; changed = true; } });
    if (changed) { paintTalk(); nativeUpdate(); }
  }
  function audioBox() { let b = $('#fcrAudio'); if (!b) { b = document.createElement('div'); b.id = 'fcrAudio'; b.style.cssText = 'position:fixed;width:0;height:0;overflow:hidden'; document.body.appendChild(b); } return b; }

  // ---- mic state: open mic / mute / push-to-talk
  function micLive() { const c = cur(); return !!c && !c.muted && (!c.ptt || c.pttDown); }
  function applyMic() {
    const c = cur(); if (!c || !c.stream) return;
    const on = micLive(); c.stream.getAudioTracks().forEach(t => t.enabled = on);
    paintControls(); nativeUpdate(); beatSoon();
  }
  R.mute = v => { const c = cur(); if (!c) return; c.muted = v == null ? !c.muted : !!v; if (!c.muted && c.ptt) c.ptt = false; applyMic(); };
  R.ptt = v => { const c = cur(); if (!c) return; c.ptt = v == null ? !c.ptt : !!v; c.pttDown = false; if (c.ptt) c.muted = false; try { localStorage.setItem('fcr_ptt', c.ptt ? '1' : ''); } catch (_) {} applyMic(); };
  R.talk = down => { const c = cur(); if (!c || !c.ptt) return; c.pttDown = !!down; applyMic(); };

  // ---- heartbeat: presence + signals + who is in the room
  let beatT = 0, beatBusy = false;
  function beatSoon() { const c = cur(); if (!c || beatBusy) return; clearTimeout(beatT); beatT = setTimeout(beat, 60); }
  async function beat() {
    clearTimeout(beatT); const c = cur(); if (!c) return;
    beatBusy = true; let d = null;
    try { d = await post('/api/fcr/beat', { code: c.code, after: c.after, muted: !micLive(), talking: c.meTalk }); }
    catch (e) { if (e.data && e.data.gone) { beatBusy = false; return ended(e.message); } c.netFails = (c.netFails || 0) + 1; if (c.netFails === 4) toast('Connection is weak - trying to stay in the room…'); }
    beatBusy = false;
    if (cur() !== c) return;
    if (d) {
      c.netFails = 0;
      if (d.gone) return ended(d.error || 'You left the game room.');
      if (d.title) { c.title = d.title; c.game = d.game || ''; }
      for (const s of d.signals || []) { c.after = Math.max(c.after, s.id); await onSignal(s); }
      c.members = d.members || [];
      const here = new Set(c.members.map(m => m.id));
      c.members.forEach(m => { if (m.id === c.me) return; c.miss.delete(m.id); if (!c.peers.has(m.id) && c.me < m.id) { const p = makePeer(m.id); if (p) offer(p); } });
      c.peers.forEach((p, uid) => { if (here.has(uid)) return; const n = (c.miss.get(uid) || 0) + 1; c.miss.set(uid, n); if (n >= MISS_LIMIT) dropPeer(uid); });
      // an answerer that never got an offer (e.g. the offer was lost): ask again by restarting from our side after 12 s
      c.members.forEach(m => { if (m.id !== c.me && m.id < c.me && !c.peers.has(m.id)) { const t = c.wait.get(m.id) || Date.now(); c.wait.set(m.id, t); if (Date.now() - t > 12000) { c.wait.delete(m.id); sendSignal(m.id, 'bye', {}); } } else c.wait.delete(m.id); });
      paint(); nativeUpdate();
    }
    beatT = setTimeout(beat, BEAT_MS);
  }

  // ---- join / leave
  R.join = async function (code, opts) {
    code = String(code || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (!code) return;
    const c0 = cur();
    if (c0 && c0.code === code) { R.show(); return; }
    if (c0) { if (!confirm('Leave "' + c0.title + '" and join the other room?')) return; await R.leave(true); }
    if (window.svActiveVideoCall || document.querySelector('#svVideoCallModal:not(.hidden)')) { toast('Finish your call first, then join the game room.'); return; }
    const busy = toastStay('Joining the game room…');
    let stream;
    try { stream = await getMic(); } catch (e) { busy(); sheet('<h3>Microphone needed</h3><p>' + esc(e.message) + '</p><button class="fc-btn" id="fcrOk">OK</button>', (el, done) => { $('#fcrOk', el).onclick = done; }); return; }
    let d;
    try { d = await post('/api/fcr/join', { code, muted: false }); }
    catch (e) { busy(); stream.getTracks().forEach(t => t.stop()); sheet('<h3>Can\'t join</h3><p>' + esc(e.message) + '</p><button class="fc-btn" id="fcrOk">OK</button>', (el, done) => { $('#fcrOk', el).onclick = done; }); return; }
    busy();
    let ptt = false; try { ptt = localStorage.getItem('fcr_ptt') === '1'; } catch (_) {}
    const c = R.cur = { code, title: d.room.title, game: d.room.game, owner: d.room.owner_id, me: d.me, after: d.after || 0, ice: d.iceServers || [{ urls: 'stun:stun.l.google.com:19302' }],
      stream, peers: new Map(), miss: new Map(), wait: new Map(), members: d.room.live || [], muted: false, ptt, pttDown: false, meTalk: false, myLevel: 0, link: d.room.link, joinedAt: Date.now() };
    c.localMeter = meter(stream);
    try { localStorage.setItem('fcr_last', code); } catch (_) {}
    // clear any half-open connections the others still hold from an earlier visit, then the lower id offers
    (c.members || []).forEach(m => { if (m.id !== c.me) sendSignal(m.id, 'bye', {}); });
    applyMic();
    c.talkT = setInterval(tickTalk, 160);
    const n = NATIVE(); if (n) { try { n.roomStart(JSON.stringify({ code, title: brand(c.title), game: c.game })); } catch (_) {} }
    bar(); beat();
    if (!(opts && opts.quiet)) R.show();
    if (n && typeof n.overlayAllowed === 'function') { try { if (!n.overlayAllowed() && !localStorage.getItem('fcr_bubble_asked')) setTimeout(askBubble, 900); } catch (_) {} }
  };
  R.leave = async function (silent) {
    const c = cur(); if (!c) return;
    R.cur = null; clearTimeout(beatT); clearInterval(c.talkT); clearTimeout(outTimer); outbox = []; outTimer = 0;
    c.peers.forEach(p => { try { p.pc.close(); } catch (_) {} if (p.audio) { try { p.audio.srcObject = null; p.audio.remove(); } catch (_) {} } });
    c.stream.getTracks().forEach(t => { try { t.stop(); } catch (_) {} });
    try { if (c.localMeter && c.localMeter.src) c.localMeter.src.disconnect(); } catch (_) {}
    const n = NATIVE(); if (n) { try { n.roomStop(); } catch (_) {} }
    bar();
    try { await post('/api/fcr/leave', { code: c.code }); } catch (_) {}
    if (!silent) toast('You left ' + c.title);
    if (top() === scrRoom) { try { pop(); } catch (_) {} }
    else if (X.stack.some(f => f === scrRooms) && top() === scrRooms) scrRooms();
  };
  function ended(msg) {
    const c = cur(); if (!c) return;
    R.leave(true); toast(msg || 'You left the game room.');
  }
  // the native notification / bubble talk to the room through here
  window.fcRoomAction = function (a) {
    const c = cur(); if (!c) { const n = NATIVE(); if (n) try { n.roomStop(); } catch (_) {} return; }
    if (a === 'mute') R.mute(true); else if (a === 'unmute') R.mute(false); else if (a === 'toggle') R.mute();
    else if (a === 'leave') R.leave(); else if (a === 'ptt_down') { if (!c.ptt) R.ptt(true); R.talk(true); } else if (a === 'ptt_up') R.talk(false);
    else if (a === 'ptt_on') R.ptt(true); else if (a === 'ptt_off') R.ptt(false); else if (a === 'open') R.show();
  };
  window.fcRoomJoin = code => { if (code) R.openCode(code); };
  let lastNative = '';
  const brand = t => String(t || '').replace(/Skillvaya/gi, 'Future Chat');
  function nativeUpdate() {
    const n = NATIVE(), c = cur(); if (!n || !c || typeof n.roomUpdate !== 'function') return;
    const people = (c.members || []).map(m => ({ name: m.me ? 'You' : brand(m.name.split(' ')[0]), talking: m.me ? (c.meTalk && micLive()) : !!(c.peers.get(m.id) || {}).talk, muted: m.me ? !micLive() : !!m.muted }));
    const s = JSON.stringify({ title: brand(c.title), game: c.game, muted: c.muted, ptt: c.ptt, live: micLive(), people });
    if (s === lastNative) return; lastNative = s;
    try { n.roomUpdate(s); } catch (_) {}
  }
  function askBubble() {
    const n = NATIVE(); if (!n || !cur()) return;
    try { localStorage.setItem('fcr_bubble_asked', '1'); } catch (_) {}
    sheet('<h3>Talk over your game 🎮</h3><p>Future Chat can show a small <b>F bubble</b> on top of your game, so you can mute, push-to-talk or leave without leaving the game.</p><p style="font-size:13px;color:#9cb7cc">Android will open a settings page: turn on <b>Allow display over other apps</b> for Future Chat, then come back.</p>' +
      '<button class="fc-btn" id="fcrBub">Turn on the bubble</button><button class="fc-btn sec" id="fcrNo">Not now</button>', (el, done) => {
      $('#fcrBub', el).onclick = () => { done(); try { n.askOverlay(); } catch (_) {} };
      $('#fcrNo', el).onclick = () => { done(); toast('You can still mute or leave from the Future Chat notification'); };
    });
  }

  // ================================================================ screens
  function toastStay(t) { const n = document.createElement('div'); n.className = 'fc-toast'; n.textContent = t; n.style.animation = 'none'; document.body.appendChild(n); return () => n.remove(); }
  function liveDots(r) {
    if (!r.count) return '<small class="fcr-quiet">Nobody in the room right now</small>';
    return '<span class="fcr-faces">' + r.live.slice(0, 4).map(p => avatar(p.name, p.photo, 'xs')).join('') + '</span><small class="fcr-on">● ' + r.count + ' in the room</small>';
  }
  async function scrRooms() {
    const self = top();
    const bd = frame('Game Rooms', 'Talk to your squad while you play', { action: [K.SVG.plus, 'New game room', newRoom] });
    const c = cur();
    let h = '';
    if (c) h += '<button class="fcr-now" data-a="now"><span class="fcr-pulse"></span><span class="tx"><b>You\'re in ' + esc(c.title) + '</b><small>' + (c.members.length || 1) + ' in the room · tap to open</small></span><span class="chev">›</span></button>';
    h += '<div class="fcr-hero"><div class="fcr-hero-ic">🎧</div><div><b>Voice chat for gamers</b><small>Up to 6 people. Keep talking while your game is open - mute or leave from the F bubble or the notification.</small></div></div>';
    h += '<div class="fca-acts" style="grid-template-columns:repeat(2,1fr)"><button class="fca-act" data-a="new"><i>➕</i>New game room</button><button class="fca-act" data-a="code"><i>🔑</i>Join with a code</button></div>';
    h += '<div id="fcrList"><div class="fca-empty"><span class="big">🎮</span><b>Loading your rooms…</b></div></div>';
    bd.innerHTML = h;
    bind(bd, { new: newRoom, code: joinByCode, now: () => R.show() });
    let d; try { d = await api('/api/fcr/rooms'); } catch (e) { if (top() === self) $('#fcrList', bd).innerHTML = '<div class="fca-empty"><b>Couldn\'t load your rooms</b>' + esc(e.message) + '</div>'; return; }
    if (top() !== self) return;
    if (d.games && d.games.length) GAMES = d.games;
    const box = $('#fcrList', bd);
    if (!d.rooms.length) { box.innerHTML = '<div class="fca-empty"><span class="big">🎮</span><b>No game rooms yet</b>Make a room for your squad, invite them, then open your game and keep talking.</div>'; return; }
    box.innerHTML = '<div class="fca-gl">Your rooms</div><div class="fca-card">' + d.rooms.map((r, i) =>
      '<button type="button" class="fca-row fcr-room" data-i="' + i + '"><span class="fcr-gic">' + gIcon(r.game) + '</span><span class="tx"><b>' + esc(r.title) + (r.mine ? ' <em class="fcr-tag">yours</em>' : '') + '</b><small>' + esc(r.game || 'Any game') + ' · code ' + esc(r.code) + '</small>' + liveDots(r) + '</span>' +
      (c && c.code === r.code ? '<span class="fcr-in">IN</span>' : '<span class="fcr-join">' + (r.count ? 'Join' : 'Open') + '</span>') + '</button>').join('') + '</div>';
    box.querySelectorAll('[data-i]').forEach(b => b.onclick = () => roomSheet(d.rooms[Number(b.dataset.i)]));
    // refresh "who's in" every 10 s while this list is on screen
    setTimeout(() => { if (top() === self && document.visibilityState === 'visible') scrRooms(); }, 10000);
  }
  function roomSheet(r) {
    const c = cur(), inIt = c && c.code === r.code;
    sheet('<h3>' + gIcon(r.game) + ' ' + esc(r.title) + '</h3><p>' + esc(r.game || 'Any game') + ' · code <b>' + esc(r.code) + '</b> · made by ' + esc(r.mine ? 'you' : r.owner) + '</p>' +
      (r.count ? '<p>' + r.live.map(p => esc(p.name.split(' ')[0])).join(', ') + (r.count === 1 ? ' is' : ' are') + ' in the room now.</p>' : '<p>Nobody is in the room right now.</p>') +
      '<div class="fc-acts">' + (inIt ? '<button class="fc-act" data-a="open"><i>🎧</i>Open the room</button>' : '<button class="fc-act" data-a="join"><i>🎙️</i>Join and talk</button>') +
      '<button class="fc-act" data-a="inv"><i>📨</i>Invite people</button>' +
      (r.mine ? '<button class="fc-act" data-a="ren"><i>✏️</i>Rename / change game</button><button class="fc-act" data-a="close"><i>🗑️</i>Close this room</button>' : '<button class="fc-act" data-a="forget"><i>🗑️</i>Remove from my list</button>') + '</div>', (el, done) => bind(el, {
      open: () => { done(); R.show(); }, join: () => { done(); R.join(r.code); }, inv: () => { done(); invite(r); }, ren: () => { done(); renameRoom(r); },
      close: async () => { if (!confirm('Close "' + r.title + '"? Everyone in it is disconnected and the code stops working.')) return; done(); try { if (inIt) await R.leave(true); await post('/api/fcr/close', { code: r.code }); toast('Room closed'); if (top() === scrRooms) scrRooms(); } catch (e) { toast(e.message); } },
      forget: async () => { done(); try { if (inIt) await R.leave(true); await post('/api/fcr/leave', { code: r.code, forget: true }); toast('Removed from your list'); if (top() === scrRooms) scrRooms(); } catch (e) { toast(e.message); } } }));
  }
  function gamePicker(sel) {
    return '<div class="fcr-games">' + GAMES.map(g => '<button type="button" data-g="' + esc(g) + '" class="' + (g === sel ? 'on' : '') + '">' + gIcon(g) + ' ' + esc(g) + '</button>').join('') + '</div>';
  }
  function wireGames(el) { el.querySelectorAll('[data-g]').forEach(b => b.onclick = () => { el.querySelectorAll('[data-g]').forEach(x => x.classList.toggle('on', x === b)); }); }
  function pickedGame(el) { const b = el.querySelector('[data-g].on'); return b ? b.dataset.g : ''; }
  function newRoom() {
    const first = ((X.me && X.me.name) || '').split(' ')[0];
    sheet('<h3>New game room</h3><label class="fca-field"><span>Room name</span><input id="fcrT" maxlength="40" placeholder="' + esc((first ? first + '\'s' : 'My') + ' squad') + '"></label>' +
      '<div class="fca-field"><span>What are you playing?</span>' + gamePicker('') + '</div><button class="fc-btn" id="fcrGo">Create and join</button>', (el, done) => {
      wireGames(el);
      $('#fcrGo', el).onclick = async () => {
        const btn = $('#fcrGo', el); btn.disabled = true;
        try { const d = await post('/api/fcr/create', { title: $('#fcrT', el).value.trim(), game: pickedGame(el) }); done(); await R.join(d.room.code); }
        catch (e) { btn.disabled = false; toast(e.message); }
      };
    });
  }
  function renameRoom(r) {
    sheet('<h3>Rename the room</h3><label class="fca-field"><span>Room name</span><input id="fcrT" maxlength="40" value="' + esc(r.title) + '"></label><div class="fca-field"><span>Game</span>' + gamePicker(r.game) + '</div><button class="fc-btn" id="fcrGo">Save</button>', (el, done) => {
      wireGames(el);
      $('#fcrGo', el).onclick = async () => { try { await post('/api/fcr/rename', { code: r.code, title: $('#fcrT', el).value.trim(), game: pickedGame(el) }); done(); toast('Saved'); const c = cur(); if (c && c.code === r.code) { c.title = $('#fcrT', el).value.trim() || c.title; c.game = pickedGame(el); paint(); } if (top() === scrRooms) scrRooms(); } catch (e) { toast(e.message); } };
    });
  }
  function joinByCode() {
    sheet('<h3>Join with a code</h3><p>Ask your friend for their 6-letter room code.</p><label class="fca-field"><span>Room code</span><input id="fcrC" maxlength="8" autocapitalize="characters" autocomplete="off" placeholder="e.g. K7Q2MX" style="text-transform:uppercase;letter-spacing:.2em;font-weight:800"></label><button class="fc-btn" id="fcrGo">Find the room</button>', (el, done) => {
      const go = () => { const v = $('#fcrC', el).value.trim(); if (v.length < 4) { toast('Type the room code'); return; } done(); R.openCode(v); };
      $('#fcrGo', el).onclick = go; $('#fcrC', el).onkeydown = e => { if (e.key === 'Enter') go(); };
      setTimeout(() => { try { $('#fcrC', el).focus(); } catch (_) {} }, 200);
    });
  }
  R.openCode = async function (code) {
    code = String(code || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    const c = cur(); if (c && c.code === code) { R.show(); return; }
    let d; try { d = await api('/api/fcr/room?code=' + encodeURIComponent(code)); } catch (e) { toast(e.message); return; }
    const r = d.room;
    if (r.why_not) { sheet('<h3>' + esc(r.title) + '</h3><p>' + esc(r.why_not) + '</p><button class="fc-btn" id="fcrOk">OK</button>', (el, done) => { $('#fcrOk', el).onclick = done; }); return; }
    sheet('<div class="fcr-inv-hd">' + gIcon(r.game) + '</div><h3 style="text-align:center">' + esc(r.title) + '</h3><p style="text-align:center">' + esc(r.game || 'Any game') + ' · made by ' + esc(r.mine ? 'you' : r.owner) + '<br>' +
      (r.count ? esc(r.live.map(p => p.name.split(' ')[0]).join(', ')) + (r.count === 1 ? ' is' : ' are') + ' talking now' : 'Nobody is in the room yet') + '</p>' +
      (r.count >= r.max ? '<p style="text-align:center;color:#ffb4b4">The room is full (' + r.max + ' people).</p>' : '<button class="fc-btn" id="fcrGo">🎙️ Join and talk</button>') + '<button class="fc-btn sec" id="fcrNo">Not now</button>', (el, done) => {
      const g = $('#fcrGo', el); if (g) g.onclick = () => { done(); R.join(code); };
      $('#fcrNo', el).onclick = done;
    });
  };
  // ---- invite: share the link anywhere, or send it in Future Chat chats
  function invite(r) {
    const c = cur(); r = r || (c && { code: c.code, title: c.title, game: c.game, link: c.link });
    if (!r) return;
    const first = ((X.me && X.me.name) || '').split(' ')[0];
    const link = (r.link || ('https://futurechat-v5lx.onrender.com/?room=' + r.code)) + (first ? '&n=' + encodeURIComponent(first) : '');
    const text = '🎮 Join my game room "' + r.title + '"' + (r.game ? ' (' + r.game + ')' : '') + ' on Future Chat - we talk while we play. Room code ' + r.code + '\n' + link;
    let chats = []; try { chats = (K.FC().state().list || []).filter(x => !x.archived).slice(0, 80); } catch (_) {}
    sheet('<h3>Invite to ' + esc(r.title) + '</h3><p>Room code <b style="letter-spacing:.15em">' + esc(r.code) + '</b></p><div class="fc-acts"><button class="fc-act" data-a="share"><i>📤</i>Share link (WhatsApp, SMS…)</button><button class="fc-act" data-a="copy"><i>📋</i>Copy link</button></div>' +
      (chats.length ? '<div class="fca-gl" style="margin-top:12px">Send in Future Chat (up to 10)</div><div class="fcr-pick">' + chats.map(x => '<label><input type="checkbox" value="' + x.id + '"><span>' + esc(x.title) + '</span>' + (x.kind === 'group' ? '<em>group</em>' : '') + '</label>').join('') + '</div><button class="fc-btn" id="fcrSend">Send invite</button>' : ''), (el, done) => {
      bind(el, {
        share: () => { done(); const n = window.FutureChatNative; if (n && n.share) { try { n.share(text); return; } catch (_) {} } if (navigator.share) navigator.share({ text }).catch(() => {}); else copy(text); },
        copy: () => { done(); copy(text); } });
      const s = $('#fcrSend', el); if (!s) return;
      el.querySelectorAll('.fcr-pick input').forEach(i => i.onchange = () => { const on = el.querySelectorAll('.fcr-pick input:checked'); if (on.length > 10) { i.checked = false; toast('Up to 10 chats at a time'); } });
      s.onclick = async () => {
        const ids = [...el.querySelectorAll('.fcr-pick input:checked')].map(i => Number(i.value));
        if (!ids.length) { toast('Tick who to invite'); return; }
        s.disabled = true;
        try { const d = await post('/api/fcr/invite', { code: r.code, chats: ids }); done(); toast('Invite sent to ' + d.sent + (d.sent === 1 ? ' chat' : ' chats')); try { K.FC().reloadList(); } catch (_) {} }
        catch (e) { s.disabled = false; toast(e.message); }
      };
    });
  }
  function copy(t) { try { navigator.clipboard.writeText(t).then(() => toast('Link copied'), () => toast(t)); } catch (_) { toast(t); } }

  // ---- the room itself
  R.show = function () { const c = cur(); if (!c) { push(scrRooms); return; } if (top() === scrRoom) { scrRoom(); return; } openPanel(); push(scrRoom); };
  function scrRoom() {
    const c = cur(); if (!c) { pop(); return; }
    const bd = frame(c.title, (c.game ? gIcon(c.game) + ' ' + c.game + ' · ' : '') + 'code ' + c.code, { action: ['<span style="font-size:20px;line-height:1">⋯</span>', 'Room options', roomMenu] });
    bd.innerHTML = '<div class="fcr-grid" id="fcrGrid"></div>' +
      '<div class="fcr-ctl" id="fcrCtl"></div>' +
      '<div class="fcr-tip"><b>🎮 Now open your game.</b> Your squad keeps hearing you. ' + (NATIVE() ? 'Mute, push-to-talk or leave from the <b>F bubble</b> on top of the game or from the notification.' : 'Keep Future Chat open in the background.') + '</div>' +
      (NATIVE() && typeof NATIVE().overlayAllowed === 'function' && !safe(() => NATIVE().overlayAllowed()) ? '<button class="fca-btn sec" id="fcrBubOn">🫧 Show the F bubble over games</button>' : '') +
      '<p class="fca-note">Voice goes straight between phones and is never recorded. Uses about 10-15 MB of data an hour (less with Data saver).</p>';
    const bo = $('#fcrBubOn', bd); if (bo) bo.onclick = askBubble;
    paint();
  }
  const safe = f => { try { return f(); } catch (_) { return false; } };
  function roomMenu() {
    const c = cur(); if (!c) return;
    const mine = c.owner === c.me;
    sheet('<h3>' + esc(c.title) + '</h3><div class="fc-acts"><button class="fc-act" data-a="inv"><i>📨</i>Invite people</button>' +
      (mine ? '<button class="fc-act" data-a="ren"><i>✏️</i>Rename / change game</button>' : '') +
      '<button class="fc-act" data-a="ptt"><i>' + (c.ptt ? '🎙️' : '✋') + '</i>' + (c.ptt ? 'Switch to open mic' : 'Switch to push-to-talk') + '</button>' +
      (NATIVE() && typeof NATIVE().askOverlay === 'function' ? '<button class="fc-act" data-a="bub"><i>🫧</i>F bubble over games</button>' : '') +
      '<button class="fc-act" data-a="all"><i>🗂️</i>All my game rooms</button>' +
      (mine ? '<button class="fc-act" data-a="close"><i>🗑️</i>Close the room for everyone</button>' : '') + '<button class="fc-act" data-a="leave"><i>🚪</i>Leave the room</button></div>', (el, done) => bind(el, {
      inv: () => { done(); invite(); }, ren: () => { done(); renameRoom({ code: c.code, title: c.title, game: c.game }); }, ptt: () => { done(); R.ptt(); },
      bub: () => { done(); askBubble(); }, all: () => { done(); push(scrRooms); }, leave: () => { done(); R.leave(); },
      close: async () => { if (!confirm('Close the room for everyone? The code stops working.')) return; done(); const code = c.code; await R.leave(true); try { await post('/api/fcr/close', { code }); toast('Room closed'); } catch (e) { toast(e.message); } } }));
  }
  function personSheet(m) {
    const c = cur(); if (!c || m.me) return;
    const p = c.peers.get(m.id), st = p ? p.pc.connectionState : 'new';
    const mine = c.owner === c.me;
    sheet('<h3>' + esc(m.name) + '</h3><p>' + (st === 'connected' ? '🟢 Connected' : st === 'failed' ? '🔴 Connection failed - reconnecting' : '🟡 Connecting…') + (m.muted ? ' · 🔇 muted' : '') + '</p>' +
      '<label class="fca-field"><span>Their volume on your phone</span><input type="range" min="0" max="100" value="' + Math.round(((p && p.audio && p.audio.volume) || 1) * 100) + '" id="fcrVol"></label>' +
      '<div class="fc-acts">' + (mine ? '<button class="fc-act" data-a="rm"><i>🚫</i>Remove from the room</button>' : '') + '<button class="fc-act" data-a="re"><i>🔄</i>Reconnect to them</button></div>', (el, done) => {
      const v = $('#fcrVol', el); v.oninput = () => { const q = cur() && cur().peers.get(m.id); if (q && q.audio) q.audio.volume = Number(v.value) / 100; };
      bind(el, {
        re: () => { done(); dropPeer(m.id); sendSignal(m.id, 'bye', {}); toast('Reconnecting…'); beatSoon(); },
        rm: async () => { if (!confirm('Remove ' + m.name + ' from the room? They can\'t come back in.')) return; done(); try { await post('/api/fcr/remove', { code: c.code, user: m.id }); dropPeer(m.id); toast(m.name.split(' ')[0] + ' was removed'); beatSoon(); } catch (e) { toast(e.message); } } });
    });
  }
  function paint() {
    paintGrid(); paintControls(); bar();
  }
  function paintGrid() {
    const c = cur(), g = $('#fcrGrid'); if (!c || !g) return;
    const list = (c.members && c.members.length ? c.members : [{ id: c.me, name: (X.me && X.me.name) || 'You', photo: (X.me && X.me.photo) || '', me: true }]).slice(0, 6);
    if (!list.some(m => m.me)) list.unshift({ id: c.me, name: (X.me && X.me.name) || 'You', photo: (X.me && X.me.photo) || '', me: true });
    let h = list.map(m => {
      const p = c.peers.get(m.id), conn = m.me ? 'connected' : (p ? p.pc.connectionState : 'new');
      const talk = m.me ? (c.meTalk && micLive()) : !!(p && p.talk);
      const muted = m.me ? !micLive() : m.muted;
      return '<button type="button" class="fcr-tile' + (talk ? ' talk' : '') + (conn !== 'connected' ? ' wait' : '') + '" data-u="' + m.id + '">' + avatar(m.name, m.photo, 'lg') +
        '<b>' + esc(m.me ? 'You' : m.name.split(' ')[0]) + '</b><small>' + (muted ? '🔇 muted' : conn === 'connected' ? (talk ? 'talking' : 'listening') : 'connecting…') + '</small></button>';
    }).join('');
    for (let i = list.length; i < 6; i++) h += '<button type="button" class="fcr-tile empty" data-inv="1"><span class="fcr-plus">+</span><b>Invite</b><small>a friend</small></button>';
    g.innerHTML = h;
    g.querySelectorAll('[data-u]').forEach(b => b.onclick = () => { const m = (c.members || []).find(x => String(x.id) === b.dataset.u); if (m) personSheet(m); });
    g.querySelectorAll('[data-inv]').forEach(b => b.onclick = () => invite());
  }
  function paintTalk() {
    const c = cur(), g = $('#fcrGrid'); if (!c || !g) { bar(); return; }
    g.querySelectorAll('[data-u]').forEach(b => {
      const id = Number(b.dataset.u), p = c.peers.get(id), me = id === c.me;
      const talk = me ? (c.meTalk && micLive()) : !!(p && p.talk); b.classList.toggle('talk', talk);
      const m = (c.members || []).find(x => x.id === id) || {}; const muted = me ? !micLive() : m.muted; const conn = me ? 'connected' : (p ? p.pc.connectionState : 'new');
      const s = b.querySelector('small'); if (s) s.textContent = muted ? '🔇 muted' : conn === 'connected' ? (talk ? 'talking' : 'listening') : 'connecting…';
    });
    bar();
  }
  function paintControls() {
    const c = cur(), el = $('#fcrCtl'); if (!c || !el) { bar(); return; }
    el.innerHTML = (c.ptt
      ? '<button class="fcr-big ptt' + (c.pttDown ? ' down' : '') + '" id="fcrPtt">' + MIC + '<span>' + (c.pttDown ? 'Talking…' : 'Hold to talk') + '</span></button>'
      : '<button class="fcr-big' + (c.muted ? ' off' : '') + '" id="fcrMute">' + (c.muted ? MICOFF : MIC) + '<span>' + (c.muted ? 'Unmute' : 'Mute') + '</span></button>') +
      '<div class="fcr-row"><button class="fcr-sm" id="fcrMode">' + (c.ptt ? '🎙️ Open mic' : '✋ Push-to-talk') + '</button><button class="fcr-sm" id="fcrInv">📨 Invite</button><button class="fcr-sm red" id="fcrLeave">🚪 Leave</button></div>';
    const m = $('#fcrMute', el); if (m) m.onclick = () => R.mute();
    const p = $('#fcrPtt', el);
    if (p) {
      const dn = e => { e.preventDefault(); R.talk(true); }, up = e => { e.preventDefault(); R.talk(false); };
      p.addEventListener('pointerdown', dn); p.addEventListener('pointerup', up); p.addEventListener('pointercancel', up); p.addEventListener('pointerleave', up);
      p.oncontextmenu = e => e.preventDefault();
    }
    $('#fcrMode', el).onclick = () => R.ptt(); $('#fcrInv', el).onclick = () => invite(); $('#fcrLeave', el).onclick = () => R.leave();
  }
  // ---- the little "in a game room" bar on every other screen
  function bar() {
    const c = cur(); let b = $('#fcrBar');
    const hide = !c || top() === scrRoom || document.documentElement.classList.contains('fca-inconv') && false;
    if (hide) { if (b) b.remove(); document.documentElement.classList.remove('fcr-onbar'); return; }
    if (!b) { b = document.createElement('div'); b.id = 'fcrBar'; document.body.appendChild(b); }
    document.documentElement.classList.add('fcr-onbar');
    const talkers = (c.members || []).filter(m => m.me ? (c.meTalk && micLive()) : !!(c.peers.get(m.id) || {}).talk).map(m => m.me ? 'You' : m.name.split(' ')[0]);
    b.innerHTML = '<button class="fcr-bar-main" id="fcrBarOpen"><span class="fcr-pulse"></span><span class="tx"><b>' + esc(c.title) + '</b><small>' + (talkers.length ? '🗣 ' + esc(talkers.join(', ')) : (c.members.length || 1) + ' in the room') + '</small></span></button>' +
      '<button class="fcr-bar-btn' + (micLive() ? '' : ' off') + '" id="fcrBarMute" aria-label="' + (micLive() ? 'Mute' : 'Unmute') + '">' + (micLive() ? MIC : MICOFF) + '</button><button class="fcr-bar-btn red" id="fcrBarLeave" aria-label="Leave">✕</button>';
    $('#fcrBarOpen', b).onclick = () => R.show();
    $('#fcrBarMute', b).onclick = () => { if (c.ptt) R.ptt(false); R.mute(); };
    $('#fcrBarLeave', b).onclick = () => R.leave();
  }
  // keep the bar right when screens change
  const baseDraw = K.draw;
  setInterval(() => { if (cur()) { const isRoom = top() === scrRoom; const b = $('#fcrBar'); if (isRoom && b) bar(); else if (!isRoom && !b) bar(); } }, 700);

  // ================================================================ hooks into the rest of Future Chat
  FCX.gameRooms = () => push(scrRooms);
  // invite cards in chats
  const baseSpecial = FCX.special;
  FCX.special = function (m) {
    const t = m.meta || {};
    if (t.room && t.room.code) {
      const c = cur(), inIt = c && c.code === t.room.code;
      return '<div class="fc-card fcr-card"><span class="k">🎮 GAME ROOM</span><b>' + esc(t.room.title || 'Game room') + '</b><small>' + esc(t.room.game || 'Any game') + ' · code ' + esc(t.room.code) + '</small>' +
        '<button class="pri" onclick="event.stopPropagation();window.FCX.rooms.' + (inIt ? 'show()' : 'openCode(\'' + esc(t.room.code) + '\')') + '">' + (inIt ? '🎧 Open the room' : (m.mine ? '🎙️ Go to the room' : '🎙️ Join and talk')) + '</button></div>';
    }
    return baseSpecial ? baseSpecial(m) : '';
  };
  // "Game room" in a chat's share sheet: invite this chat to a room
  const baseTiles = FCX.attachTiles;
  FCX.attachTiles = function (conv) {
    const t = baseTiles ? baseTiles(conv) : []; if (!conv || !conv.id) return t;
    return t.concat([['🎮', 'Game room', '#0e7490', () => chatRoom(conv)]]);
  };
  async function chatRoom(conv) {
    const c = cur();
    if (c) { try { await post('/api/fcr/invite', { code: c.code, chats: [conv.id] }); toast('Invite sent'); try { K.FC().reloadList(); } catch (_) {} } catch (e) { toast(e.message); } return; }
    let rooms = []; try { rooms = ((await api('/api/fcr/rooms')).rooms || []).filter(r => r.mine).slice(0, 8); } catch (_) {}
    sheet('<h3>Game room with ' + esc(conv.title || 'this chat') + '</h3><p>They get a card in the chat - one tap and you\'re talking.</p><div class="fc-acts"><button class="fc-act" data-r="new"><i>➕</i>New room and invite</button>' +
      rooms.map((r, i) => '<button class="fc-act" data-r="' + i + '"><i>' + gIcon(r.game) + '</i>' + esc(r.title) + '</button>').join('') + '</div>', (el, done) => {
      el.querySelectorAll('[data-r]').forEach(b => b.onclick = async () => {
        done();
        try {
          let code;
          if (b.dataset.r === 'new') { const first = ((X.me && X.me.name) || 'My').split(' ')[0]; code = (await post('/api/fcr/create', { title: first + '\'s squad', game: '' })).room.code; }
          else code = rooms[Number(b.dataset.r)].code;
          await post('/api/fcr/invite', { code, chats: [conv.id] }); try { K.FC().reloadList(); } catch (_) {}
          await R.join(code);
        } catch (e) { toast(e.message); }
      });
    });
  }
  // chat menu entry
  const baseActs = FCX.convActs;
  FCX.convActs = function (cv) { const a = baseActs ? baseActs(cv) : []; a.push(['🎮', 'Talk in a game room', () => chatRoom(cv)]); return a; };
  // a room link opened the app (Play install referrer "fcroom=CODE", or the website's "Open in Future Chat")
  function pendingFromUrl() {
    let code = '';
    try { const u = new URL(location.href); code = u.searchParams.get('room') || ''; if (code) { u.searchParams.delete('room'); history.replaceState(history.state, '', u.pathname + (u.search || '') + u.hash); } } catch (_) {}
    try { const n = window.FutureChatNative; if (!code && n && typeof n.roomRef === 'function') code = n.roomRef() || ''; } catch (_) {}
    return code;
  }
  function whenReady(fn, n) { n = n || 0; const me = X.me; if (me && me.id) { fn(); return; } if (n > 60) return; setTimeout(() => whenReady(fn, n + 1), 1000); }
  const startCode = pendingFromUrl();
  if (startCode) whenReady(() => setTimeout(() => R.openCode(startCode), 800));
  // the page is closing (app swiped away): tell the others straight away
  window.addEventListener('pagehide', () => { const c = cur(); if (!c) return; try { fetch('/api/fcr/leave', { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (localStorage.getItem('skillvaya_token') || localStorage.getItem('sv_token') || '') }, body: JSON.stringify({ code: c.code }) }); } catch (_) {} });
  // a call comes in while you're in a room: mute the room so the call is private, unmute after
  setInterval(() => { const c = cur(); if (!c) return; const inCall = !!document.querySelector('#svVideoCallModal:not(.hidden)'); if (inCall && !c.callMuted) { c.callMuted = true; c.wasMuted = c.muted; R.mute(true); c.peers.forEach(p => { if (p.audio) p.audio.muted = true; }); toast('Game room muted during your call'); } else if (!inCall && c.callMuted) { c.callMuted = false; R.mute(c.wasMuted); c.peers.forEach(p => { if (p.audio) p.audio.muted = false; }); } }, 1000);
})();
