/* Chatmoji Lenses for video calls: the same 130 lenses as the Future Chat Lens camera, tracked to your face live.
   Face tracking uses Google's MediaPipe face detector, loaded only when a lens is picked. SV94-LENS */
(function () {
  'use strict';
  // Same order and effects as the Android LensCatalog (generated from the Chatmoji designs).
  var KIND = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,0,0,0,0,0,0,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2];
  var FX = ["rise","burst","burst","orbit","corner","rise","orbit","drift","burst","burst","rain","rain","rise","burst","orbit","corner","drift","orbit","orbit","drift","burst","orbit","orbit","fall","burst","orbit","fall","rise","orbit","rise","rise","drift","drift","orbit","burst","burst","corner","drift","burst","rise","rise","drift","orbit","burst","orbit","corner","fall","drift","drift","fall","rise","rise","rise","rise","fall","rise","orbit","burst","rise","fall","burst","burst","orbit","burst","rise","burst","rise","burst","burst","orbit","fall","rise","fall","fall","corner","hat","burst","fall","corner","burst","hat","drift","orbit","drift","orbit","fall","orbit","burst","drift","drift","corner","corner","drift","rain","fall","corner","fall","fall","bottom","bottom","launch","bottom","launch","bottom","orbit","orbit","bottom","bottom","fall","drift","orbit","rise","hat","drift","drift","orbit","burst","orbit","drift","orbit","orbit","orbit","orbit","burst","drift","rise","rise","corner","orbit","orbit"];
  var SPRITE = ["sparkles","star","laugh","sparkle_heart","sun","heart_pink","flower","cloud","popper","heart_pink","rain","cloud","fire","exclaim","question","moon","cloud","clock","star","mute","joy","star","gem","cake","sparkles","globe","popper","cloud","book","heart_teal","sparkle_heart","cloud","mute","question","exclaim","boom","moon","leaf","firework","fire","fire","cloud","globe","bolt","heart_pink","sun","gem","shield","lock","snow","heart_pink","heart_teal","heart_blue","heart_violet","heartbreak","sparkle_heart","star","bolt","fire","gem","check","cross","question","exclaim","plus_one","hundred","like","sparkles","boom","eyes","popper","balloon","gift","cake","disco","crown","firework","medal","trophy","toast","bulb","pencil","book","calendar","clock","pin","magnifier","target","checklist","mail","sun","moon","cloud","rain","snow","rainbow","flower","leaf","wave","mountain","rocket","car","plane","house","globe","compass","tent","boat","bag","map","camera","music","headphones","phone","laptop","gamepad","play","mic","tv","battery","lock","shield","shield_check","bell","mute","bubble","typing","flag","eye_open","key"];
  var MP = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14';
  var MODEL = 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';

  var S = window.svLens = { i: -1, det: null, loading: false, failed: false, face: null, seen: 0, frame: 0, imgs: {} };
  function names() { var c = (window.FC_CHATMOJI && window.FC_CHATMOJI.cats) || [], out = []; c.forEach(function (x) { out = out.concat(x[1]); }); return out; }
  function img(name) {
    if (S.imgs[name]) return S.imgs[name];
    var svg = (window.FC_CHATMOJI && window.FC_CHATMOJI.svg && window.FC_CHATMOJI.svg[name]) || '';
    var im = new Image(); im.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg); S.imgs[name] = im; return im;
  }

  async function loadDetector() {
    if (S.det || S.loading || S.failed) return;
    S.loading = true;
    try {
      var m = await import(MP + '/vision_bundle.mjs');
      var files = await m.FilesetResolver.forVisionTasks(MP + '/wasm');
      var opts = function (d) { return { baseOptions: { modelAssetPath: MODEL, delegate: d }, runningMode: 'VIDEO', minDetectionConfidence: 0.5 }; };
      try { S.det = await m.FaceDetector.createFromOptions(files, opts('GPU')); }
      catch (_) { S.det = await m.FaceDetector.createFromOptions(files, opts('CPU')); }
    } catch (e) { S.failed = true; console.warn('Lens face tracking unavailable', e && e.message); }
    S.loading = false;
  }

  function track(v, w, h) {
    if (!S.det || v.readyState < 2) return;
    if ((S.frame++ % 2) !== 0) return; // track every other frame to keep calls smooth
    var r; try { r = S.det.detectForVideo(v, performance.now()); } catch (_) { return; }
    var d = r && r.detections && r.detections[0]; if (!d || !d.boundingBox) return;
    var b = d.boundingBox, k = d.keypoints || [];
    var g = { cx: b.originX + b.width / 2, cy: b.originY + b.height / 2, s: Math.max(b.width, b.height), a: 0 };
    if (k.length >= 2) { var dx = (k[1].x - k[0].x) * w, dy = (k[1].y - k[0].y) * h; g.a = Math.atan2(dy, dx); if (Math.abs(g.a) > Math.PI / 2) g.a += Math.PI; }
    var p = S.face; S.face = p ? { cx: p.cx + (g.cx - p.cx) * .55, cy: p.cy + (g.cy - p.cy) * .55, s: p.s + (g.s - p.s) * .55, a: p.a + (g.a - p.a) * .55 } : g;
    S.seen = Date.now();
  }

  function sprite(x, name, cx, cy, size, rot) {
    var im = img(name); if (!im.complete || !im.naturalWidth && !im.width) return;
    x.save(); x.translate(cx, cy); if (rot) x.rotate(rot); x.drawImage(im, -size / 2, -size / 2, size, size); x.restore();
  }

  function scene(x, fx, name, w, h, f, t) {
    var m = Math.min(w, h), s = m * 0.11, i, n, u;
    if (fx === 'rise' || fx === 'fall' || fx === 'rain') {
      n = fx === 'rain' ? 14 : 8;
      for (i = 0; i < n; i++) { u = ((t * (fx === 'rain' ? .45 : .14)) + i / n) % 1; var yy = fx === 'rise' ? h * (1.08 - u * 1.16) : h * (-0.08 + u * 1.16);
        sprite(x, name, ((i * 0.137 + 0.06) % 1) * w + Math.sin(t * 2 + i) * s * .4, yy, fx === 'rain' ? s * .7 : s, Math.sin(t + i) * .3); }
    } else if (fx === 'orbit') {
      for (i = 0; i < 6; i++) { var a = t * .9 + i / 6 * Math.PI * 2; sprite(x, name, f.cx + Math.cos(a) * f.s * .95, f.cy + Math.sin(a) * f.s * .8, s, 0); }
    } else if (fx === 'burst') {
      for (i = 0; i < 9; i++) { u = (t * .5 + i / 9) % 1; var b = i / 9 * Math.PI * 2; sprite(x, name, f.cx + Math.cos(b) * u * m * .6, f.cy + Math.sin(b) * u * m * .6, s * (1.2 - u * .6), 0); }
    } else if (fx === 'drift') {
      for (i = 0; i < 5; i++) { u = (t * .06 + i / 5) % 1; sprite(x, name, -s + u * (w + 2 * s), h * (.1 + (i % 3) * .1) + Math.sin(t + i) * s * .3, s * 1.2, 0); }
    } else if (fx === 'corner') {
      sprite(x, name, w - m * .17, m * .17, m * .24 * (1 + Math.sin(t * 3) * .06), Math.sin(t) * .15);
    } else if (fx === 'bottom') {
      for (i = 0; i < 4; i++) sprite(x, name, w * (.14 + i * .24), h - s * .9 + Math.sin(t * 3 + i) * s * .12, s * 1.3, 0);
    } else if (fx === 'launch') {
      u = (t * .22) % 1; sprite(x, name, w * (.05 + u * .9), h * (1.05 - u * 1.1), m * .2, -.6);
    } else if (fx === 'hat') {
      sprite(x, name, f.cx + Math.sin(f.a) * f.s * .75, f.cy - Math.cos(f.a) * f.s * .78, f.s * .85, f.a);
    }
  }

  /* Called by the call filter engine for every outgoing frame. */
  window.svLensDraw = function (x, v, w, h) {
    if (S.i < 0) return;
    var nm = names(); var name = nm[S.i]; if (!name) return;
    track(v, w, h);
    var fresh = S.face && (Date.now() - S.seen < 1500);
    var f = fresh ? S.face : { cx: w / 2, cy: h * .42, s: Math.min(w, h) * .42, a: 0 };
    var t = Date.now() / 1000, k = KIND[S.i];
    if (k === 0 || k === 1) {
      // Your face becomes the Chatmoji (full mask for 1, expression face for 0), with its effect around you.
      sprite(x, name, f.cx, f.cy - f.s * .04, f.s * (k === 1 ? 1.75 : 1.5), f.a);
      scene(x, FX[S.i] === 'hat' ? 'orbit' : FX[S.i], SPRITE[S.i], w, h, f, t);
    } else {
      scene(x, FX[S.i], SPRITE[S.i], w, h, f, t);
    }
  };

  window.svLensBarHTML = function () {
    var nm = names(); if (!nm.length) return '';
    var order = []; nm.forEach(function (_, i) { if (KIND[i] < 2) order.push(i); }); nm.forEach(function (_, i) { if (KIND[i] === 2) order.push(i); });
    return '<div class="sv-lens-title">Chatmoji Lenses' + (S.loading ? ' · starting face tracking…' : (S.failed ? ' · face tracking unavailable, lens shown centred' : '')) + '</div><div class="sv-fx-bar sv-lens-bar">' +
      '<button type="button" class="sv-fx-chip' + (S.i < 0 ? ' on' : '') + '" onclick="svPickLens(-1)">No lens</button>' +
      order.map(function (i) { return '<button type="button" class="sv-lens-chip' + (S.i === i ? ' on' : '') + '" aria-label="' + nm[i].replace(/_/g, ' ') + ' lens" onclick="svPickLens(' + i + ')"><img alt="" src="' + img(nm[i]).src + '"></button>'; }).join('') + '</div>';
  };

  window.svPickLens = async function (i) {
    S.i = Number(i); S.face = null;
    if (S.i >= 0) loadDetector().then(function () { if (typeof svRenderFxBar === 'function') svRenderFxBar(); });
    try { if (typeof svApplyCallFx === 'function') await svApplyCallFx(typeof svFx !== 'undefined' ? svFx.id : 'none'); } catch (_) {}
    if (typeof svRenderFxBar === 'function') svRenderFxBar();
  };

  try {
    var st = document.createElement('style');
    st.textContent = '.sv-lens-title{color:#fff;font-weight:800;font-size:13px;margin:10px 2px 0;opacity:.9}.sv-lens-chip{flex:none;width:52px;height:52px;border-radius:50%;border:2px solid rgba(255,255,255,.3);background:rgba(255,255,255,.1);padding:6px;display:grid;place-items:center}.sv-lens-chip img{width:36px;height:36px}.sv-lens-chip.on{border-color:#fff;background:rgba(255,255,255,.3)}';
    document.head.appendChild(st);
  } catch (_) {}
})();
