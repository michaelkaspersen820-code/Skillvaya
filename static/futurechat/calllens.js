/* Chatmoji Lenses for video calls: the same 130 lenses as the Future Chat Lens camera, tracked to your face live.
   Face tracking uses Google's MediaPipe face detector, loaded only when a lens is picked. SV94-LENS SV95-FACE SV96-WARP SV97-MESH
   SV97: uses the 478-point face mesh, so the expression moves your actual eyebrows, eyelids and mouth, adapts to the
   expression you are already making, and the colour follows the outline of your face exactly. */
(function () {
  'use strict';
  // Same order and effects as the Android LensCatalog (generated from the Chatmoji designs).
  var KIND = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,0,0,0,0,0,0,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2];
  var FX = ["rise","burst","burst","orbit","corner","rise","orbit","drift","burst","burst","rain","rain","rise","burst","orbit","corner","drift","orbit","orbit","drift","burst","orbit","orbit","fall","burst","orbit","fall","rise","orbit","rise","rise","drift","drift","orbit","burst","burst","corner","drift","burst","rise","rise","drift","orbit","burst","orbit","corner","fall","drift","drift","fall","rise","rise","rise","rise","fall","rise","orbit","burst","rise","fall","burst","burst","orbit","burst","rise","burst","rise","burst","burst","orbit","fall","rise","fall","fall","corner","hat","burst","fall","corner","burst","hat","drift","orbit","drift","orbit","fall","orbit","burst","drift","drift","corner","corner","drift","rain","fall","corner","fall","fall","bottom","bottom","launch","bottom","launch","bottom","orbit","orbit","bottom","bottom","fall","drift","orbit","rise","hat","drift","drift","orbit","burst","orbit","drift","orbit","orbit","orbit","orbit","burst","drift","rise","rise","corner","orbit","orbit"];
  var SPRITE = ["sparkles","star","laugh","sparkle_heart","sun","heart_pink","flower","cloud","popper","heart_pink","rain","cloud","fire","exclaim","question","moon","cloud","clock","star","mute","joy","star","gem","cake","sparkles","globe","popper","cloud","book","heart_teal","sparkle_heart","cloud","mute","question","exclaim","boom","moon","leaf","firework","fire","fire","cloud","globe","bolt","heart_pink","sun","gem","shield","lock","snow","heart_pink","heart_teal","heart_blue","heart_violet","heartbreak","sparkle_heart","star","bolt","fire","gem","check","cross","question","exclaim","plus_one","hundred","like","sparkles","boom","eyes","popper","balloon","gift","cake","disco","crown","firework","medal","trophy","toast","bulb","pencil","book","calendar","clock","pin","magnifier","target","checklist","mail","sun","moon","cloud","rain","snow","rainbow","flower","leaf","wave","mountain","rocket","car","plane","house","globe","compass","tent","boat","bag","map","camera","music","headphones","phone","laptop","gamepad","play","mic","tv","battery","lock","shield","shield_check","bell","mute","bubble","typing","flag","eye_open","key"];
  var MP = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14';
  var MODEL = 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';
  var MODEL_LM = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';

  var S = window.svLens = { i: -1, e: -1, det: null, mode: '', lm: null, bs: {}, loading: false, failed: false, face: null, seen: 0, frame: 0, imgs: {} };
  function names() { var c = (window.FC_CHATMOJI && window.FC_CHATMOJI.cats) || [], out = []; c.forEach(function (x) { out = out.concat(x[1]); }); return out; }
  function img(name) {
    if (S.imgs[name]) return S.imgs[name];
    var svg = (window.FC_CHATMOJI && window.FC_CHATMOJI.svg && window.FC_CHATMOJI.svg[name]) || '';
    var im = new Image(); im.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg); S.imgs[name] = im; return im;
  }

  var FEAT = {}, TINT = {};
  function svgOf(name) { return (window.FC_CHATMOJI && window.FC_CHATMOJI.svg && window.FC_CHATMOJI.svg[name]) || ''; }
  function tint(name) { if (!TINT[name]) { var m = svgOf(name).match(/<path[^>]*fill="(#[0-9A-Fa-f]{6})"/); TINT[name] = m ? m[1] : '#FFC23D'; } return TINT[name]; }
  function feat(name) {
    if (FEAT[name]) return FEAT[name];
    var svg = svgOf(name), parts = svg.match(/<path[^>]*\/>/g) || [];
    var body = parts.slice(2).join(''); // drop the face disc and its shine; keep eyes, mouth, tears, blush
    var im = new Image(); im.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent('<svg viewBox="0 0 64 64" width="512" height="512" xmlns="http://www.w3.org/2000/svg">' + body + '</svg>');
    FEAT[name] = im; return im;
  }
  function rgba(hex, a) { var n = parseInt(hex.slice(1), 16); return 'rgba(' + (n >> 16 & 255) + ',' + (n >> 8 & 255) + ',' + (n & 255) + ',' + a + ')'; }
  function blob(c, cx, cy, rx, ry, rot, col, a0) {
    c.save(); c.translate(cx, cy); c.rotate(rot || 0); c.scale(rx, ry);
    var g = c.createRadialGradient(0, 0, 0, 0, 0, 1); g.addColorStop(0, rgba(col, a0)); g.addColorStop(.7, rgba(col, a0 * .9)); g.addColorStop(1, rgba(col, 0));
    c.fillStyle = g; c.beginPath(); c.arc(0, 0, 1, 0, Math.PI * 2); c.fill(); c.restore();
  }
  /* Expression recipes: how each Chatmoji reshapes YOUR real face.
     bi/bo = inner/outer eyebrow raise (+ up, - down), e = eyes open (0 closed .. 1.4 wide), c = mouth corners (+ smile, - frown),
     o = mouth open, w = mouth wider (- = pucker), k = cheeks up. L/R suffix = one side only (image left/right). */
  var EXP = {
    smile:{c:.8,w:.3,k:.4,e:.9}, grin:{c:1,w:.6,o:.3,k:.6,e:.8}, joy:{c:1,w:.6,o:.7,e:.15,bi:.2,k:.8}, wink:{c:.6,k:.3,eR:0,eL:1},
    cool:{c:.5}, lovestruck:{c:.8,k:.4}, blush:{c:.4,e:.35,k:.3}, calm:{e:0,c:.3,bi:.1}, silly:{c:.7,o:.5,eR:.3,eL:1},
    kiss:{w:-.7,e:.25}, sad:{bi:1,c:-.8,e:.7}, cry:{bi:1.1,c:-1,e:0,o:.2}, angry:{bi:-1.2,bo:.4,c:-.7,e:.8},
    shock:{bi:.9,bo:.9,e:1.4,o:1,w:-.3}, think:{biL:.7,biR:-.4,c:-.2}, sleepy:{e:0,bi:.2,o:.3}, sick:{e:.5,c:-.4},
    worried:{bi:.9,c:-.4,e:1}, dizzy:{o:.2}, hush:{w:-.4,e:.8}, laugh:{c:.9,o:.55,w:.4,e:.1,k:.8}, starstruck:{c:1,o:.7,w:.6},
    smirk:{cL:.8,cR:0,e:.8,boR:.4}, yum:{c:.8,o:.2,e:.2}, sweat_smile:{c:.9,o:.5,e:.3,bi:.4}, upside:{c:.7}, party_face:{c:.9,o:.4,e:.8},
    angel:{c:.6,e:.2}, nerd:{c:.8,o:.3}, hug:{c:.8,e:.2,k:.5}, pleading:{bi:1,e:1.3,c:-.2}, eyeroll:{e:.6,bi:.2,c:-.3},
    unamused:{e:.55,c:-.4,bi:-.2}, confused:{biL:.7,biR:-.4,c:-.3}, grimace:{w:.9,o:.3,c:-.1,bi:.4,e:1.1}, scream:{bi:1,e:1.4,o:1.2,w:-.4},
    yawn:{e:0,o:1.2,w:-.3,bi:.3}, relieved:{e:0,c:.5,bi:.3}, mindblown:{e:1.4,o:.9,bo:1}, hot:{bi:.5,o:.5,c:-.2,e:.7},
    devil:{bi:-1,c:.7,e:.8}, cat:{c:.6,w:.3}, cowboy:{c:.8}, money:{c:.8,o:.5}, mask:{e:.8}, zipper:{w:.2}, cold:{bi:.5,c:-.4,e:.8}
  };
  // Extras that stay drawn on top (tears, heart/star eyes, glasses, blush...). Indices are paths in the Chatmoji drawing.
  var ACC = { cool:[2,3,4,5,6], nerd:[2,3,4,5,6], lovestruck:[2,3], starstruck:[2,3], money:[2,3,4,5,7,8], dizzy:[2,3,4,5], joy:[], laugh:[],
    cry:[], blush:[5,6], sweat_smile:[7], sleepy:[5] };
  var ACCI = {};
  function acc(name) {
    if (ACCI[name] !== undefined) return ACCI[name];
    var parts = svgOf(name).match(/<path[^>]*\/>/g) || [], keep = [];
    if (ACC[name]) keep = ACC[name].map(function (i) { return parts[i]; }).filter(Boolean);
    else parts.slice(2).forEach(function (q) { // default: coloured extras outside the eye/mouth shapes (we reshape the real ones)
      var f = (q.match(/fill="([^"]*)"/) || [])[1] || 'none'; if (f === 'none' || /0A2A44/i.test(f)) return;
      var nums = ((q.match(/d="([^"]*)"/) || [])[1] || '').match(/-?\d+(\.\d+)?/g) || []; var x0 = +nums[0], y0 = +nums[1];
      if (x0 > 18 && x0 < 46 && y0 > 33) return; // tongue / teeth inside the mouth
      if (x0 > 12 && x0 < 52 && y0 > 16 && y0 < 36) return; // eye whites / pupils
      keep.push(q);
    });
    if (!keep.length) { ACCI[name] = null; return null; }
    var im = new Image(); im.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent('<svg viewBox="0 0 64 64" width="512" height="512" xmlns="http://www.w3.org/2000/svg">' + keep.join('') + '</svg>');
    ACCI[name] = im; return im;
  }

  // ---- WebGL face warp: the video is drawn through a grid whose texture points are pushed by the expression.
  var GLW = null, GN = 40;
  function glInit(w, h) {
    if (GLW && GLW.w === w && GLW.h === h) return GLW;
    var c = (GLW && GLW.c) || document.createElement('canvas'); c.width = w; c.height = h;
    var gl = (GLW && GLW.gl) || c.getContext('webgl', { preserveDrawingBuffer: true, premultipliedAlpha: false }); if (!gl) return null;
    if (!GLW || !GLW.prog) {
      var sh = function (t, src) { var o = gl.createShader(t); gl.shaderSource(o, src); gl.compileShader(o); return o; };
      var pr = gl.createProgram();
      gl.attachShader(pr, sh(gl.VERTEX_SHADER, 'attribute vec2 p;attribute vec2 t;varying vec2 v;void main(){gl_Position=vec4(p,0.,1.);v=t;}'));
      gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, 'precision mediump float;uniform sampler2D s;varying vec2 v;void main(){gl_FragColor=texture2D(s,v);}'));
      gl.linkProgram(pr); if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) return null;
      var tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex);
      [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T].forEach(function (k) { gl.texParameteri(gl.TEXTURE_2D, k, gl.CLAMP_TO_EDGE); });
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      var idx = []; for (var j = 0; j < GN; j++) for (var i = 0; i < GN; i++) { var a = j * (GN + 1) + i; idx.push(a, a + 1, a + GN + 1, a + 1, a + GN + 2, a + GN + 1); }
      var ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(idx), gl.STATIC_DRAW);
      var pos = [], P = []; for (j = 0; j <= GN; j++) for (i = 0; i <= GN; i++) { pos.push(i / GN * 2 - 1, 1 - j / GN * 2); P.push(i / GN, j / GN); }
      var pb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, pb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(pos), gl.STATIC_DRAW);
      GLW = { c: c, gl: gl, prog: pr, tex: tex, ib: ib, pb: pb, tb: gl.createBuffer(), P: P, n: idx.length };
    }
    GLW.w = w; GLW.h = h; GLW.c.width = w; GLW.c.height = h; return GLW;
  }
  function warp(v, w, h, ctrl) {
    var G = glInit(w, h); if (!G) return null; var gl = G.gl, P = G.P, T = new Float32Array(P.length);
    for (var q = 0; q < P.length; q += 2) {
      var px = P[q] * w, py = P[q + 1] * h, dx = 0, dy = 0;
      for (var i = 0; i < ctrl.length; i++) { var C = ctrl[i], ex = px - C.x, ey = py - C.y, g = Math.exp(-(ex * ex + ey * ey) / (2 * C.s * C.s)); dx += C.dx * g; dy += C.dy * g; }
      T[q] = (px - dx) / w; T[q + 1] = (py - dy) / h;
    }
    gl.viewport(0, 0, w, h); gl.useProgram(G.prog);
    gl.bindTexture(gl.TEXTURE_2D, G.tex); gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    try { gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, v); } catch (_) { return null; }
    var lp = gl.getAttribLocation(G.prog, 'p'), lt = gl.getAttribLocation(G.prog, 't');
    gl.bindBuffer(gl.ARRAY_BUFFER, G.pb); gl.enableVertexAttribArray(lp); gl.vertexAttribPointer(lp, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, G.tb); gl.bufferData(gl.ARRAY_BUFFER, T, gl.DYNAMIC_DRAW); gl.enableVertexAttribArray(lt); gl.vertexAttribPointer(lt, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, G.ib); gl.drawElements(gl.TRIANGLES, G.n, gl.UNSIGNED_SHORT, 0);
    return G.c;
  }
  function pick(E, k, side) { var s = E[k + side]; return s !== undefined ? s : (E[k] !== undefined ? E[k] : null); }
  /* Reshape the real face into the Chatmoji's expression, recolour the skin, then add the extras. */
  function faceAs(x, name, f, w, h, v) {
    var col = tint(name), kp = f.kp; if (!kp) return false;
    var re = kp[0], le = kp[1], mo = kp[3]; if (le.x < re.x) { var tmp = re; re = le; le = tmp; }
    var ux = le.x - re.x, uy = le.y - re.y, d = Math.hypot(ux, uy); if (d < 8) return false; ux /= d; uy /= d;
    var vx = -uy, vy = ux, a = Math.atan2(uy, ux), E = EXP[name] || { c: .3 }, ctrl = [];
    var P = function (o, au, av) { return { x: o.x + ux * au * d + vx * av * d, y: o.y + uy * au * d + vy * av * d }; };
    var push = function (pt, du, dv, sig) { if (!du && !dv) return; ctrl.push({ x: pt.x, y: pt.y, dx: (ux * du + vx * dv) * d, dy: (uy * du + vy * dv) * d, s: sig * d }); };
    [[re, -1, 'L'], [le, 1, 'R']].forEach(function (S2) {
      var eye = S2[0], out = S2[1], sd = S2[2];
      var bi = pick(E, 'bi', sd) || 0, bo = pick(E, 'bo', sd) || 0, eo = pick(E, 'e', sd); if (eo === null) eo = 1;
      push(P(eye, -out * .22, -.42), out * (bi < 0 ? -bi * .06 : 0), -bi * .16, .17);  // inner brow
      push(P(eye, out * .3, -.36), 0, -bo * .1, .18);                                    // outer brow
      push(P(eye, 0, -.1), 0, (1 - eo) * .15, .14);                                      // upper eyelid
      push(P(eye, 0, .08), 0, -(1 - eo) * .06, .1);                                     // lower eyelid
      push(P(eye, 0, .55), 0, -(E.k || 0) * .07, .25);                                   // cheek
    });
    var cL = pick(E, 'c', 'L') || 0, cR = pick(E, 'c', 'R') || 0, wd = E.w || 0, op = E.o || 0;
    push(P(mo, -.42, 0), -wd * .12, -cL * .22, .2); push(P(mo, .42, 0), wd * .12, -cR * .22, .2); push(P(mo, 0, -.02), 0, ((cL + cR) / 2) * .07, .18);
    push(P(mo, 0, .1), 0, op * .2, .22); push(P(mo, 0, -.08), 0, -op * .04, .16);
    var gc = warp(v, w, h, ctrl);
    if (gc) { x.drawImage(gc, 0, 0, w, h); }
    // skin takes the Chatmoji colour, keeping your own shading
    if (!S.off || S.off.width !== w || S.off.height !== h) { S.off = document.createElement('canvas'); S.off.width = w; S.off.height = h; }
    var o = S.off.getContext('2d'); o.clearRect(0, 0, w, h);
    blob(o, f.cx, f.cy + f.bh * .02, f.bw * .56, f.bh * .66, a, col, 1);
    // only the face itself: fade out above the eyebrows (keeps hair and fringe natural) and below the chin
    var em = { x: (re.x + le.x) / 2, y: (re.y + le.y) / 2 }, gt = P(em, 0, -.78), gb = P(em, 0, 1.75);
    var lg = o.createLinearGradient(gt.x, gt.y, gb.x, gb.y);
    lg.addColorStop(0, 'rgba(0,0,0,0)'); lg.addColorStop(.12, 'rgba(0,0,0,1)'); lg.addColorStop(.78, 'rgba(0,0,0,1)'); lg.addColorStop(1, 'rgba(0,0,0,0)');
    o.save(); o.globalCompositeOperation = 'destination-in'; o.fillStyle = lg; o.fillRect(0, 0, w, h); o.restore();
    x.save(); x.globalCompositeOperation = 'color'; x.globalAlpha = .9; x.drawImage(S.off, 0, 0); x.globalCompositeOperation = 'multiply'; x.globalAlpha = .18; x.drawImage(S.off, 0, 0); x.restore();
    var im = acc(name);
    if (im && im.complete) { var mx = (re.x + le.x) / 2, my = (re.y + le.y) / 2, down = Math.hypot(mo.x - mx, mo.y - my), sx = d / 20, sy = Math.max(sx * .85, Math.min(sx * 1.6, down / 17));
      x.save(); x.translate(mx, my); x.rotate(a); x.scale(sx, sy); x.drawImage(im, -32, -28, 64, 64); x.restore(); }
    return true;
  }

  /* ---- SV97: precise version using the full face mesh ---- */
  var OVAL = [10,338,297,332,284,251,389,356,454,323,361,288,397,365,379,378,400,377,152,148,176,149,150,136,172,58,132,93,234,127,162,21,54,103,67,109];
  // Per side (as seen by the subject): inner/mid/outer brow, upper/lower eyelid, eye corners, cheek, mouth corner, blendshape side.
  var SIDE = { r: { bi: 107, bm: 105, bo: 70, up: 159, lo: 145, c1: 33, c2: 133, ck: 205, mc: 61, bs: 'Right',
                    eye: [33,246,161,160,159,158,157,173,133,155,154,153,145,144,163,7], low: [33,7,163,144,145,153,154,155,133] },
               l: { bi: 336, bm: 334, bo: 300, up: 386, lo: 374, c1: 362, c2: 263, ck: 425, mc: 291, bs: 'Left',
                    eye: [263,466,388,387,386,385,384,398,362,382,381,380,374,373,390,249], low: [263,249,390,373,374,380,381,382,362] } };
  var TEARS = { cry: 2, joy: 1, laugh: 1, sweat_smile: 0, sad: 0, pleading: 0 };   // 2 = streaming, 1 = tears of joy
  // Closed eye: cover the opening with your own eyelid skin and draw a soft lash line.
  function shutEye(x, L, K, amt, d) {
    var cx = 0, cy = 0; K.eye.forEach(function (i) { cx += L[i].x; cy += L[i].y; }); cx /= K.eye.length; cy /= K.eye.length;
    var eyeH = Math.hypot(L[K.up].x - L[K.lo].x, L[K.up].y - L[K.lo].y), lift = eyeH * 1.15 + d * .03;
    var pts = K.eye.map(function (i) { return { x: cx + (L[i].x - cx) * 1.2, y: cy + (L[i].y - cy) * 1.5 }; });
    var m = d * .08, x0 = Math.min.apply(null, pts.map(function (q) { return q.x; })) - m, y0 = Math.min.apply(null, pts.map(function (q) { return q.y; })) - m;
    var bw = Math.ceil(Math.max.apply(null, pts.map(function (q) { return q.x; })) + m - x0), bh = Math.ceil(Math.max.apply(null, pts.map(function (q) { return q.y; })) + m - y0);
    if (bw < 4 || bh < 4) return;
    var c = S.eyeC || (S.eyeC = document.createElement('canvas')); c.width = bw; c.height = bh; var e = c.getContext('2d');
    e.drawImage(x.canvas, x0, y0 + lift, bw, bh, 0, 0, bw, bh);                       // skin from just under the eye
    e.globalCompositeOperation = 'destination-in'; e.filter = 'blur(' + (d * .025).toFixed(1) + 'px)'; e.fillStyle = '#000'; e.beginPath();
    pts.forEach(function (q, n) { if (n) e.lineTo(q.x - x0, q.y - y0); else e.moveTo(q.x - x0, q.y - y0); }); e.closePath(); e.fill();
    x.save(); x.globalAlpha = amt; x.drawImage(c, x0, y0); x.restore();
    // lash line where the lids meet: a soft downward curve
    x.save(); x.globalAlpha = .55 * amt; x.strokeStyle = 'rgb(50,34,28)'; x.lineWidth = Math.max(1.2, d * .016); x.lineCap = 'round'; x.lineJoin = 'round';
    x.filter = 'blur(' + (d * .004).toFixed(1) + 'px)'; x.beginPath();
    K.low.forEach(function (i, n) { var X = L[i].x, Y = L[i].y - eyeH * .3; if (n) x.lineTo(X, Y); else x.moveTo(X, Y); }); x.stroke(); x.restore();
  }
  function tears(x, L, K, d, mode, t, ph) {
    var s = L[K.lo], o = L[K.c1], start = { x: s.x + (o.x - s.x) * .35, y: s.y + d * .03 }, r = d * (mode === 2 ? .055 : .045);
    var len = d * (mode === 2 ? .9 : .45), u = ((t * (mode === 2 ? .7 : .5)) + ph) % 1, y = start.y + u * len, a = u < .85 ? 1 : (1 - u) / .15;
    x.save(); x.globalAlpha = .45 * (mode === 2 ? 1 : .7); x.strokeStyle = 'rgba(190,225,255,1)'; x.lineWidth = r * .55; x.lineCap = 'round';
    x.beginPath(); x.moveTo(start.x, start.y); x.lineTo(start.x, y - r); x.stroke(); x.restore();
    x.save(); x.globalAlpha = a; x.translate(start.x, y);
    var g = x.createLinearGradient(-r, -r, r, r); g.addColorStop(0, 'rgba(225,243,255,.95)'); g.addColorStop(1, 'rgba(110,175,240,.8)');
    x.fillStyle = g; x.beginPath(); x.moveTo(0, -r * 1.9); x.bezierCurveTo(r * .9, -r * .6, r, r * .3, 0, r); x.bezierCurveTo(-r, r * .3, -r * .9, -r * .6, 0, -r * 1.9); x.fill();
    x.fillStyle = 'rgba(255,255,255,.9)'; x.beginPath(); x.arc(-r * .3, -r * .1, r * .22, 0, Math.PI * 2); x.fill(); x.restore();
  }
  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
  function faceMesh(x, name, w, h, v) {
    var L = S.lm, B = S.bs || {}, col = tint(name), E = EXP[name] || { c: .3 };
    var mid = function (a, b) { return { x: (L[a].x + L[b].x) / 2, y: (L[a].y + L[b].y) / 2 }; };
    var er = mid(33, 133), el = mid(362, 263), imgLeftIsR = er.x <= el.x;
    var re = imgLeftIsR ? er : el, le = imgLeftIsR ? el : er;
    var ux = le.x - re.x, uy = le.y - re.y, d = Math.hypot(ux, uy); if (d < 8) return false; ux /= d; uy /= d;
    var vx = -uy, vy = ux, a = Math.atan2(uy, ux), ctrl = [];
    var push = function (pt, du, dv, sig) { if (Math.abs(du) < 1e-3 && Math.abs(dv) < 1e-3) return; ctrl.push({ x: pt.x, y: pt.y, dx: (ux * du + vx * dv) * d, dy: (uy * du + vy * dv) * d, s: sig * d }); };
    var bsv = function (k) { return +B[k] || 0; };
    // Your own expression right now, so the lens only adds what is missing (no double smile, no over-closing).
    var have = { bi: bsv('browInnerUp') - (bsv('browDownLeft') + bsv('browDownRight')) / 2 }, shut = [], browDown = 0;
    [['L', imgLeftIsR ? SIDE.r : SIDE.l, -1], ['R', imgLeftIsR ? SIDE.l : SIDE.r, 1]].forEach(function (Q) {
      var sd = Q[0], K = Q[1], out = Q[2], bs = K.bs;
      var bi = pick(E, 'bi', sd), bo = pick(E, 'bo', sd), eo = pick(E, 'e', sd), k = E.k;
      var eyeH = Math.hypot(L[K.up].x - L[K.lo].x, L[K.up].y - L[K.lo].y) / d;  // how open this eye is now
      if (bi !== null) { var db = clamp(bi - have.bi, -1.4, 1.4); if (db < 0) browDown = Math.max(browDown, -db * .3);
        push(L[K.bi], db < 0 ? out * db * .13 : 0, -db * .3, .22); push(L[K.bm], 0, -db * .15, .2); push(L[K.bo], 0, db < 0 ? db * .06 : 0, .18); }
      if (bo !== null) { var dbo = clamp(bo - bsv('browOuterUp' + bs), -1, 1.2); push(L[K.bo], 0, -dbo * .2, .2); }
      if (eo !== null) {
        var want = clamp(1 - eo, -.5, 1) - bsv('eyeBlink' + bs);                 // + close, - widen
        if (want > .55) { shut.push([K, clamp((want - .45) * 2, 0, 1)]); push(L[K.up], 0, eyeH * .3, .1); }
        else if (want > 0) { push(L[K.up], 0, want * eyeH * .95, .1); push(L[K.lo], 0, -want * eyeH * .12, .07); }
        else if (want < 0) { push(L[K.up], 0, want * .15, .13); push(L[K.lo], 0, -want * .05, .09); }
      }
      if (k !== undefined) { var dk = clamp(k - bsv('cheekSquint' + bs), -1, 1); push(L[K.ck], 0, -dk * .12, .26); }
      var c = pick(E, 'c', sd);
      if (c !== null) { var dc = clamp(c - (bsv('mouthSmile' + bs) - bsv('mouthFrown' + bs)), -1.1, 1.2);
        push(L[K.mc], 0, -dc * (dc < 0 ? .24 : .26), .27); }
      if (E.w) push(L[K.mc], out * E.w * .2, 0, .24);
    });
    if (E.o !== undefined) { var dopen = clamp(E.o - bsv('jawOpen'), -.25, 1.2);
      var mw = Math.hypot(L[61].x - L[291].x, L[61].y - L[291].y) / d;
      push(L[14], 0, dopen * .13, mw * .24); push(L[17], 0, dopen * .1, mw * .28); }
    var gc = warp(v, w, h, ctrl);
    if (gc) { x.drawImage(gc, 0, 0, w, h); }
    shut.forEach(function (Z) { shutEye(x, L, Z[0], Z[1], d); });
    // Colour: exactly your face outline, stopping just above the eyebrows so hair and fringe stay natural.
    if (!S.off || S.off.width !== w || S.off.height !== h) { S.off = document.createElement('canvas'); S.off.width = w; S.off.height = h; }
    var o = S.off.getContext('2d'); o.clearRect(0, 0, w, h);
    var em = { x: (re.x + le.x) / 2, y: (re.y + le.y) / 2 }, topV = -.84 + browDown;
    o.save(); o.filter = 'blur(' + Math.max(2, d * .09).toFixed(1) + 'px)'; o.fillStyle = col; o.beginPath();
    OVAL.forEach(function (i, n) {
      var p = L[i], au = (p.x - em.x) * ux + (p.y - em.y) * uy, av = (p.x - em.x) * vx + (p.y - em.y) * vy;
      if (av < topV * d) av = topV * d; au *= .97;                          // flatten the top at the brow line, keep off the ears
      var X = em.x + ux * au + vx * av, Y = em.y + uy * au + vy * av; if (n) o.lineTo(X, Y); else o.moveTo(X, Y);
    });
    o.closePath(); o.fill(); o.restore();
    x.save(); x.globalCompositeOperation = 'color'; x.globalAlpha = .82; x.drawImage(S.off, 0, 0); x.globalCompositeOperation = 'multiply'; x.globalAlpha = .14; x.drawImage(S.off, 0, 0); x.restore();
    if (TEARS[name]) { var t = Date.now() / 1000; tears(x, L, SIDE.r, d, TEARS[name], t, 0); tears(x, L, SIDE.l, d, TEARS[name], t, .5); }
    var im = acc(name), mo = mid(13, 14);
    if (im && im.complete) { var down = Math.hypot(mo.x - em.x, mo.y - em.y), sx = d / 20, sy = Math.max(sx * .85, Math.min(sx * 1.6, down / 17));
      x.save(); x.translate(em.x, em.y); x.rotate(a); x.scale(sx, sy); x.drawImage(im, -32, -28, 64, 64); x.restore(); }
    return true;
  }

  async function loadDetector() {
    if (S.det || S.loading || S.failed) return;
    S.loading = true;
    try {
      var m = await import(MP + '/vision_bundle.mjs');
      var files = await m.FilesetResolver.forVisionTasks(MP + '/wasm');
      var opts = function (d) { return { baseOptions: { modelAssetPath: MODEL, delegate: d }, runningMode: 'VIDEO', minDetectionConfidence: 0.5 }; };
      var lmo = function (d) { return { baseOptions: { modelAssetPath: MODEL_LM, delegate: d }, runningMode: 'VIDEO', numFaces: 1, outputFaceBlendshapes: true,
        minFaceDetectionConfidence: 0.5, minFacePresenceConfidence: 0.5, minTrackingConfidence: 0.5 }; };
      try { S.det = await m.FaceLandmarker.createFromOptions(files, lmo('GPU')); S.mode = 'mesh'; }
      catch (_) { try { S.det = await m.FaceLandmarker.createFromOptions(files, lmo('CPU')); S.mode = 'mesh'; } catch (__) {} }
      if (!S.det) {
        try { S.det = await m.FaceDetector.createFromOptions(files, opts('GPU')); }
        catch (_) { S.det = await m.FaceDetector.createFromOptions(files, opts('CPU')); }
        S.mode = 'box';
      }
    } catch (e) { S.failed = true; console.warn('Lens face tracking unavailable', e && e.message); }
    S.loading = false;
  }

  function track(v, w, h) {
    if (!S.det || v.readyState < 2) return;
    if ((S.frame++ % (S.slow ? 2 : 1)) !== 0) return; // slower phones track every other frame to keep calls smooth
    var t0 = performance.now(), r; try { r = S.det.detectForVideo(v, t0); } catch (_) { return; }
    S.slow = performance.now() - t0 > 28;
    if (S.mode === 'mesh') { trackMesh(r, w, h); return; }
    var d = r && r.detections && r.detections[0]; if (!d || !d.boundingBox) return;
    var b = d.boundingBox, k = d.keypoints || [];
    var g = { cx: b.originX + b.width / 2, cy: b.originY + b.height / 2, s: Math.max(b.width, b.height), a: 0 };
    if (k.length >= 2) { var dx = (k[1].x - k[0].x) * w, dy = (k[1].y - k[0].y) * h; g.a = Math.atan2(dy, dx); if (Math.abs(g.a) > Math.PI / 2) g.a += Math.PI; }
    g.bw = b.width; g.bh = b.height;
    g.kp = k.length >= 4 ? k.slice(0, 4).map(function (q) { return { x: q.x * w, y: q.y * h }; }) : null;
    var p = S.face, L = function (a, b) { return a + (b - a) * .55; };
    S.face = p ? { cx: L(p.cx, g.cx), cy: L(p.cy, g.cy), s: L(p.s, g.s), a: L(p.a, g.a), bw: L(p.bw, g.bw), bh: L(p.bh, g.bh),
      kp: (p.kp && g.kp) ? g.kp.map(function (q, i) { return { x: L(p.kp[i].x, q.x), y: L(p.kp[i].y, q.y) }; }) : g.kp } : g;
    S.seen = Date.now();
  }

  function trackMesh(r, w, h) {
    var lm = r && r.faceLandmarks && r.faceLandmarks[0]; if (!lm || lm.length < 468) return;
    var P = lm.map(function (q) { return { x: q.x * w, y: q.y * h }; }), prev = S.lm;
    var d = Math.hypot(P[33].x - P[263].x, P[33].y - P[263].y) || 1;
    if (prev && prev.length === P.length) {
      // steady when you hold still, quick when you move
      var mv = Math.hypot(P[1].x - prev[1].x, P[1].y - prev[1].y) / d, k = clamp(.35 + mv * 6, .35, .9);
      P = P.map(function (q, i) { return { x: prev[i].x + (q.x - prev[i].x) * k, y: prev[i].y + (q.y - prev[i].y) * k }; });
    }
    S.lm = P;
    var cats = r.faceBlendshapes && r.faceBlendshapes[0] && r.faceBlendshapes[0].categories;
    if (cats) cats.forEach(function (c) { var o = S.bs[c.categoryName]; S.bs[c.categoryName] = o === undefined ? c.score : o + (c.score - o) * .5; });
    var xs = OVAL.map(function (i) { return P[i].x; }), ys = OVAL.map(function (i) { return P[i].y; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    var a = Math.atan2(P[263].y - P[33].y, P[263].x - P[33].x); if (Math.abs(a) > Math.PI / 2) a += Math.PI;
    var mid = function (i, j) { return { x: (P[i].x + P[j].x) / 2, y: (P[i].y + P[j].y) / 2 }; };
    S.face = { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, s: Math.max(x1 - x0, y1 - y0), a: a, bw: x1 - x0, bh: y1 - y0,
      kp: [mid(33, 133), mid(362, 263), P[1], mid(13, 14)] };
    S.seen = Date.now();
  }

  function sprite(x, name, cx, cy, size, rot) {
    var im = img(name); if (!im.complete || !im.naturalWidth && !im.width) return;
    var A = S.avoid; if (A) { var ex = (cx - A.x) / A.rx, ey = (cy - A.y) / A.ry; if (ex * ex + ey * ey < 1) return; } // keep effects off the face
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

  /* ---- SV100: Skillvaya originals. Drawn live (not stickers); several react to your face. ---- */
  var ORIG = [
    ['smile_hearts', '😍', 'Smile → hearts'], ['steam', '😤', 'Frown → steam'], ['wow', '😮', 'Open mouth → confetti'],
    ['wink', '😉', 'Wink → sparkle'], ['lekker', '👌', 'Lekker! / Eish!'], ['vuvuzela', '📯', 'Vuvuzela'],
    ['braai', '🔥', 'Braai smoke'], ['bokke', '🏉', 'Bokke!'], ['jacaranda', '💜', 'Jacaranda petals'],
    ['mzansi', '🇿🇦', 'Mzansi confetti'], ['payout', '💸', 'Stokvel payout'], ['jobdone', '✅', 'Job done ✓']
  ];
  var SA = ['#E03C31', '#001489', '#007749', '#FFB81C', '#000000', '#FFFFFF'];
  var P = [];   // live particles
  function rnd(a, b) { return a + Math.random() * (b - a); }
  function add(o) { if (P.length < 160) P.push(o); }
  function heartPath(x, r) { x.beginPath(); x.moveTo(0, r * .35); x.bezierCurveTo(-r * 1.1, -r * .35, -r * .45, -r * 1.05, 0, -r * .45); x.bezierCurveTo(r * .45, -r * 1.05, r * 1.1, -r * .35, 0, r * .35); x.closePath(); }
  function star(x, r) { x.beginPath(); for (var i = 0; i < 8; i++) { var a = i * Math.PI / 4, q = i % 2 ? r * .32 : r; x.lineTo(Math.cos(a) * q, Math.sin(a) * q); } x.closePath(); }
  function drawP(x, q) {
    var a = clamp(q.life / q.max, 0, 1), fade = a < .2 ? a / .2 : (a > .85 ? (1 - a) / .15 : 1);
    x.save(); x.translate(q.x, q.y); x.rotate(q.rot || 0); x.globalAlpha = fade * (q.alpha || 1);
    if (q.k === 'heart') { var g = x.createRadialGradient(-q.r * .3, -q.r * .4, 0, 0, 0, q.r * 1.2); g.addColorStop(0, '#ff9ac2'); g.addColorStop(1, q.c || '#ff2d6f'); x.fillStyle = g; heartPath(x, q.r); x.fill(); }
    else if (q.k === 'conf') { x.fillStyle = q.c; x.fillRect(-q.r, -q.r * .45, q.r * 2, q.r * .9); }
    else if (q.k === 'petal') { x.fillStyle = q.c; x.beginPath(); x.ellipse(0, 0, q.r, q.r * .55, 0, 0, Math.PI * 2); x.fill(); x.fillStyle = 'rgba(255,255,255,.35)'; x.beginPath(); x.ellipse(-q.r * .3, -q.r * .1, q.r * .35, q.r * .18, 0, 0, Math.PI * 2); x.fill(); }
    else if (q.k === 'puff') { var r = q.r * (1 + (1 - a) * 1.6), gg = x.createRadialGradient(0, 0, 0, 0, 0, r); gg.addColorStop(0, q.c); gg.addColorStop(1, 'rgba(255,255,255,0)'); x.fillStyle = gg; x.beginPath(); x.arc(0, 0, r, 0, Math.PI * 2); x.fill(); }
    else if (q.k === 'spark') { x.fillStyle = q.c || '#fff6b0'; star(x, q.r); x.fill(); }
    else if (q.k === 'ember') { x.fillStyle = q.c || '#ffb347'; x.beginPath(); x.arc(0, 0, q.r, 0, Math.PI * 2); x.fill(); }
    else if (q.k === 'note') { x.fillStyle = '#3f9b5a'; x.strokeStyle = '#1f5e33'; x.lineWidth = q.r * .08; x.fillRect(-q.r, -q.r * .5, q.r * 2, q.r); x.strokeRect(-q.r * .9, -q.r * .42, q.r * 1.8, q.r * .84);
      x.fillStyle = '#e8f5e9'; x.font = '900 ' + Math.round(q.r * .55) + 'px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText('R100', 0, 0); }
    else if (q.k === 'ring') { x.strokeStyle = q.c || 'rgba(255,215,0,.9)'; x.lineWidth = q.r * .08; x.beginPath(); x.arc(0, 0, q.r * (1.6 - a * 1.2), -.7, .7); x.stroke(); }
    x.restore();
  }
  function stepP(x, dt) {
    for (var i = P.length - 1; i >= 0; i--) { var q = P[i]; q.life -= dt; if (q.life <= 0) { P.splice(i, 1); continue; }
      q.vy += (q.g || 0) * dt; q.x += q.vx * dt + (q.sway ? Math.sin(q.life * 3 + q.ph) * q.sway * dt : 0); q.y += q.vy * dt; q.rot = (q.rot || 0) + (q.vr || 0) * dt; drawP(x, q); }
  }
  function label(x, text, cx, cy, size, fill, stroke, rot) {
    x.save(); x.translate(cx, cy); x.rotate(rot || 0); x.font = '900 ' + Math.round(size) + 'px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle';
    x.lineJoin = 'round'; x.lineWidth = size * .16; x.strokeStyle = stroke; x.strokeText(text, 0, 0); x.fillStyle = fill; x.fillText(text, 0, 0); x.restore();
  }
  function bubble(x, text, cx, cy, size) {
    x.save(); x.font = '900 ' + Math.round(size) + 'px sans-serif'; var tw = x.measureText(text).width, pw = tw + size * 1.1, ph = size * 1.6;
    cx = clamp(cx, pw / 2 + 6, x.canvas.width - pw / 2 - 6); cy = clamp(cy, ph / 2 + 6, x.canvas.height - ph);
    x.fillStyle = '#fff'; x.strokeStyle = '#0b2447'; x.lineWidth = size * .1; x.beginPath();
    if (x.roundRect) x.roundRect(cx - pw / 2, cy - ph / 2, pw, ph, ph / 2); else x.rect(cx - pw / 2, cy - ph / 2, pw, ph);
    x.moveTo(cx - size * .3, cy + ph / 2); x.lineTo(cx - size * .9, cy + ph / 2 + size * .7); x.lineTo(cx + size * .2, cy + ph / 2); x.fill(); x.stroke();
    x.fillStyle = '#0b2447'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText(text, cx, cy + size * .05); x.restore();
  }
  function hint() { return; }
  function hint_unused(x, text, w, h) { var sz = Math.max(13, Math.min(w, h) * .04); x.save(); x.font = '800 ' + Math.round(sz) + 'px sans-serif'; var tw = x.measureText(text).width;
    x.globalAlpha = .75; x.fillStyle = '#000'; x.fillRect(w / 2 - tw / 2 - sz * .6, h - sz * 2.6, tw + sz * 1.2, sz * 1.8); x.globalAlpha = 1; x.fillStyle = '#fff'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText(text, w / 2, h - sz * 1.7); x.restore(); }
  function drawOrig(x, id, w, h, f, t) {
    var now = performance.now(), dt = S.lastO ? clamp((now - S.lastO) / 1000, 0, .1) : 0; S.lastO = now;
    var L = S.mode === 'mesh' && S.lm && (Date.now() - S.seen < 1500) ? S.lm : null, B = S.bs || {}, m = Math.min(w, h);
    var d = L ? Math.hypot(L[33].x - L[263].x, L[33].y - L[263].y) : f.bw * .45;
    var mouth = L ? { x: (L[13].x + L[14].x) / 2, y: (L[13].y + L[14].y) / 2 } : { x: f.cx, y: f.cy + f.bh * .25 };
    var earL = L ? L[234] : { x: f.cx - f.bw * .5, y: f.cy }, earR = L ? L[454] : { x: f.cx + f.bw * .5, y: f.cy };
    var top = L ? L[10] : { x: f.cx, y: f.cy - f.bh * .5 };
    var bv = function (k) { return +B[k] || 0; }, smile = (bv('mouthSmileLeft') + bv('mouthSmileRight')) / 2, jaw = bv('jawOpen');
    var frown = Math.max((bv('browDownLeft') + bv('browDownRight')) / 2, (bv('mouthFrownLeft') + bv('mouthFrownRight')) / 2);
    var react = !!L, pulse = (t % 3) < .9;   // without precise tracking, reactive effects play on a gentle loop instead
    var on = function (v, th) { return react ? v > th : pulse; };
    S.oc = (S.oc || 0) + dt;
    var name = ORIG[id][0];
    if (name === 'smile_hearts') {
      if (on(smile, .45)) { S.idle = 0; if (Math.random() < .2) [L ? L[61] : { x: mouth.x - d * .4, y: mouth.y }, L ? L[291] : { x: mouth.x + d * .4, y: mouth.y }].forEach(function (c) {
        add({ k: 'heart', x: c.x, y: c.y, vx: rnd(-.6, .6) * d, vy: rnd(-2.2, -1.4) * d, life: 1.6, max: 1.6, r: d * rnd(.1, .17), vr: rnd(-1, 1), sway: d * .6, ph: rnd(0, 6), c: ['#ff2d6f', '#ff5fa2', '#e0006b'][i3()] }); }); }
      else S.idle = (S.idle || 0) + dt;
      stepP(x, dt); if (S.idle > 2.5) hint(x, 'Smile to send hearts 😍', w, h);
    } else if (name === 'steam') {
      if (on(frown, .3)) { S.idle = 0; [[earL, -1], [earR, 1]].forEach(function (E) { if (Math.random() < .5) add({ k: 'puff', x: E[0].x, y: E[0].y - d * .1, vx: E[1] * rnd(.3, .9) * d, vy: rnd(-1.6, -.9) * d, life: 1.3, max: 1.3, r: d * .14, c: 'rgba(255,255,255,.85)' }); });
        x.save(); x.globalCompositeOperation = 'soft-light'; x.globalAlpha = .7 * clamp(frown * 2, 0, 1); var gR = x.createRadialGradient(f.cx, f.cy + f.bh * .05, 0, f.cx, f.cy + f.bh * .05, f.bw * .55); gR.addColorStop(0, 'rgba(255,40,0,1)'); gR.addColorStop(.7, 'rgba(255,40,0,.6)'); gR.addColorStop(1, 'rgba(255,40,0,0)'); x.fillStyle = gR; x.fillRect(0, 0, w, h); x.restore(); }
      else S.idle = (S.idle || 0) + dt;
      stepP(x, dt); if (S.idle > 2.5) hint(x, 'Frown to let off steam 😤', w, h);
    } else if (name === 'wow') {
      if (on(jaw, .35)) { S.idle = 0; for (var i = 0; i < 4; i++) { var an = rnd(-Math.PI, 0), sp = rnd(2, 4.5) * d; add({ k: i % 3 ? 'conf' : 'spark', x: mouth.x, y: mouth.y, vx: Math.cos(an) * sp, vy: Math.sin(an) * sp, g: 5 * d, life: 1.6, max: 1.6, r: d * rnd(.06, .11), vr: rnd(-8, 8), c: ['#ff4d6d', '#ffd60a', '#4cc9f0', '#80ed99', '#c77dff'][i3(5)] }); } }
      else S.idle = (S.idle || 0) + dt;
      stepP(x, dt); if (S.idle > 2.5) hint(x, 'Open your mouth wide 😮', w, h);
    } else if (name === 'wink') {
      var bl = bv('eyeBlinkLeft'), br = bv('eyeBlinkRight'), w1 = react ? Math.abs(bl - br) > .35 : pulse;
      if (w1) { S.idle = 0; var eye = L ? (bl > br ? (L[33].x < L[263].x ? L[263] : L[33]) : (L[33].x < L[263].x ? L[33] : L[263])) : { x: f.cx + f.bw * .2, y: f.cy - f.bh * .1 };
        if (Math.random() < .6) add({ k: 'spark', x: eye.x + rnd(-.3, .3) * d, y: eye.y + rnd(-.3, .2) * d, vx: rnd(-.5, .5) * d, vy: rnd(-.8, -.2) * d, life: .9, max: .9, r: d * rnd(.08, .18), vr: rnd(-3, 3) });
        x.save(); x.translate(eye.x + d * .35, eye.y - d * .3); x.rotate(t * 2); x.fillStyle = '#fffbe0'; x.globalAlpha = .9; star(x, d * .22); x.fill(); x.restore(); }
      else S.idle = (S.idle || 0) + dt;
      stepP(x, dt); if (S.idle > 2.5) hint(x, 'Wink one eye 😉', w, h);
    } else if (name === 'lekker') {
      var say = react ? (smile > .5 ? 'Lekker!' : (frown > .35 ? 'Eish!' : '')) : ((t % 6) < 3 ? 'Lekker!' : 'Eish!');
      if (say) { S.say = say; S.sayT = 1.2; } S.sayT = (S.sayT || 0) - dt;
      if (S.sayT > 0) { var pop = 1 + Math.max(0, S.sayT - 1) * 2; bubble(x, S.say, top.x + d * 1.1, top.y - d * .1, Math.max(14, d * .34) * pop); }
      
    } else if (name === 'vuvuzela') {
      var ang = .3, len = d * 1.8, bell = d * .42, ux2 = Math.cos(ang), uy2 = Math.sin(ang), end = { x: mouth.x + ux2 * len, y: mouth.y + uy2 * len };
      x.save(); x.translate(mouth.x, mouth.y); x.rotate(ang);
      var gH = x.createLinearGradient(0, 0, len, 0); gH.addColorStop(0, '#007749'); gH.addColorStop(.5, '#FFB81C'); gH.addColorStop(1, '#007749');
      x.fillStyle = gH; x.beginPath(); x.moveTo(0, -d * .06); x.lineTo(len, -bell); x.quadraticCurveTo(len + d * .12, 0, len, bell); x.lineTo(0, d * .06); x.closePath(); x.fill();
      x.strokeStyle = 'rgba(0,0,0,.25)'; x.lineWidth = d * .03; x.stroke(); x.fillStyle = '#0b2447'; x.beginPath(); x.ellipse(len, 0, d * .08, bell * .92, 0, 0, Math.PI * 2); x.fill(); x.restore();
      var loud = react ? clamp(.35 + jaw * 2, 0, 1.5) : 1; S.ring = (S.ring || 0) + dt * (2 + loud * 3);
      if (S.ring > 1) { S.ring = 0; add({ k: 'ring', x: end.x, y: end.y, vx: ux2 * d * 1.5, vy: uy2 * d * 1.5, rot: ang, life: .9, max: .9, r: bell * (1 + loud * .4), c: SA[3] }); }
      stepP(x, dt);
    } else if (name === 'braai') {
      if (Math.random() < .45) add({ k: 'puff', x: rnd(0, w), y: h * rnd(.85, 1.02), vx: rnd(-.05, .05) * m, vy: -rnd(.16, .28) * m, life: 3.5, max: 3.5, r: m * rnd(.05, .09), c: 'rgba(200,195,190,.5)', sway: m * .05, ph: rnd(0, 6) });
      if (Math.random() < .4) add({ k: 'ember', x: rnd(0, w), y: h, vx: rnd(-.04, .04) * m, vy: -rnd(.2, .45) * m, life: 2.2, max: 2.2, r: m * rnd(.004, .009), sway: m * .08, ph: rnd(0, 6), c: ['#ffb347', '#ff7b00', '#ffd27a'][i3()] });
      var gB = x.createLinearGradient(0, h, 0, h * .7); gB.addColorStop(0, 'rgba(255,110,20,.45)'); gB.addColorStop(1, 'rgba(255,110,20,0)'); x.fillStyle = gB; x.fillRect(0, h * .7, w, h * .3);
      stepP(x, dt);
    } else if (name === 'bokke') {
      if (S.oc > 2.6) { S.oc = 0; for (var j = 0; j < 40; j++) { var a2 = rnd(0, Math.PI * 2), s2 = rnd(.2, .55) * m; add({ k: 'conf', x: w / 2, y: h * .3, vx: Math.cos(a2) * s2, vy: Math.sin(a2) * s2 - m * .2, g: m * .5, life: 2.2, max: 2.2, r: m * .014, vr: rnd(-9, 9), c: j % 2 ? '#007749' : '#FFB81C' }); } }
      stepP(x, dt); var bb = 1 + Math.max(0, .35 - S.oc) * 1.4; label(x, 'BOKKE!', w / 2, m * .13, m * .12 * bb, '#FFB81C', '#004d2e', Math.sin(t * 2) * .05);
    } else if (name === 'jacaranda') {
      if (Math.random() < .5) add({ k: 'petal', x: rnd(-.05, 1.05) * w, y: -m * .05, vx: rnd(-.03, .03) * m, vy: rnd(.08, .16) * m, life: 7, max: 7, r: m * rnd(.012, .022), vr: rnd(-2, 2), sway: m * .12, ph: rnd(0, 6), c: ['#8e6fd8', '#a689e8', '#7b5cc7', '#b9a3f0'][i3(4)] });
      stepP(x, dt);
    } else if (name === 'mzansi') {
      if (Math.random() < .7) add({ k: 'conf', x: rnd(0, w), y: -m * .03, vx: rnd(-.04, .04) * m, vy: rnd(.15, .3) * m, life: 5, max: 5, r: m * rnd(.01, .016), vr: rnd(-6, 6), sway: m * .1, ph: rnd(0, 6), c: SA[i3(6)] });
      stepP(x, dt);
    } else if (name === 'payout') {
      if (Math.random() < .25) add({ k: 'note', x: rnd(0, w), y: -m * .06, vx: rnd(-.03, .03) * m, vy: rnd(.12, .2) * m, life: 6, max: 6, r: m * .055, vr: rnd(-1.2, 1.2), sway: m * .15, ph: rnd(0, 6) });
      stepP(x, dt); if (S.oc > 4) S.oc = 0; if (S.oc < 1.4) { var pp = 1 + Math.max(0, .3 - S.oc) * 2; label(x, 'PAYOUT!', w / 2, m * .13, m * .11 * pp, '#7CFC9A', '#0b3d1e', -.05); }
    } else if (name === 'jobdone') {
      if (S.oc > 4.5) S.oc = 0;
      if (S.oc < 3) { var sc = S.oc < .25 ? 2.2 - S.oc * 4.8 : 1, cx2 = w - m * .26, cy2 = h - m * .2;
        if (S.oc < .05) for (var k2 = 0; k2 < 10; k2++) add({ k: 'spark', x: cx2 + rnd(-.15, .15) * m, y: cy2 + rnd(-.08, .08) * m, vx: rnd(-.2, .2) * m, vy: rnd(-.3, -.05) * m, life: .8, max: .8, r: m * .02, c: '#ffe066' });
        x.save(); x.translate(cx2, cy2); x.rotate(-.18); x.scale(sc, sc); x.globalAlpha = S.oc > 2.6 ? (3 - S.oc) / .4 : .95;
        x.strokeStyle = '#1a9e4b'; x.lineWidth = m * .012; x.strokeRect(-m * .2, -m * .06, m * .4, m * .12); x.fillStyle = 'rgba(26,158,75,.12)'; x.fillRect(-m * .2, -m * .06, m * .4, m * .12);
        x.fillStyle = '#1a9e4b'; x.font = '900 ' + Math.round(m * .062) + 'px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText('JOB DONE ✓', 0, m * .004); x.restore(); }
      stepP(x, dt);
    }
  }
  var I3 = 0; function i3(n) { I3 = (I3 + 1) % 9973; return Math.floor(Math.random() * (n || 3)); }

  /* Called by the call filter engine for every outgoing frame. Face lens (S.i) and effect (S.e) can be combined. SV99-COMBO */
  window.svLensDraw = function (x, v, w, h) {
    if (S.i < 0 && S.e < 0) return;
    var nm = names(); if (!nm.length) return;
    track(v, w, h);
    var fresh = S.face && (Date.now() - S.seen < 1500);
    var f = fresh ? S.face : { cx: w / 2, cy: h * .42, s: Math.min(w, h) * .42, a: 0, bw: Math.min(w, h) * .4, bh: Math.min(w, h) * .5 };
    var t = Date.now() / 1000, done = false, name = S.i >= 0 ? nm[S.i] : '';
    if (name) {
      var k = KIND[S.i];
      done = k === 0 && fresh && (S.mode === 'mesh' && S.lm ? faceMesh(x, name, w, h, v) : faceAs(x, name, f, w, h, v));
      if (!done && (k === 1 || S.failed || !S.det)) sprite(x, name, f.cx, f.cy - f.s * .04, f.s * (k === 1 ? 1.75 : 1.5), f.a);
    }
    S.avoid = (done && fresh) ? { x: f.cx, y: f.cy, rx: f.bw * .62, ry: f.bh * .62 } : null;
    if (name && S.e < 0) { var fxk = FX[S.i]; if (KIND[S.i] === 0 && (fxk === 'burst' || fxk === 'hat')) fxk = 'orbit'; scene(x, fxk, SPRITE[S.i], w, h, f, t); }
    if (S.e >= 200) { S.avoid = null; drawOrig(x, S.e - 200, w, h, f, t); }
    else if (S.e >= 0) { var fe = FX[S.e]; if (done && fe === 'burst') fe = 'orbit'; scene(x, fe, SPRITE[S.e], w, h, f, t); }
    S.avoid = null;
  };

  function chip(i, on, fn) { var nm = names(); return '<button type="button" class="sv-lens-chip' + (on ? ' on' : '') + '" aria-label="' + nm[i].replace(/_/g, ' ') + '" onclick="' + fn + '(' + i + ')"><img alt="" src="' + img(nm[i]).src + '"></button>'; }
  window.svLensBarHTML = function () {
    var nm = names(); if (!nm.length) return '';
    var faces = [], fx = []; nm.forEach(function (_, i) { (KIND[i] < 2 ? faces : fx).push(i); });
    var status = S.loading ? ' · starting face tracking…' : (S.failed ? ' · face tracking unavailable, lens shown centred' : (S.mode === 'mesh' ? ' · precise face tracking' : (S.mode === 'box' ? ' · basic face tracking' : '')));
    return '<div class="sv-lens-title">Face lenses' + status + '</div><div class="sv-fx-bar sv-lens-bar">' +
      '<button type="button" class="sv-fx-chip' + (S.i < 0 ? ' on' : '') + '" onclick="svPickLens(-1)">No lens</button>' +
      faces.map(function (i) { return chip(i, S.i === i, 'svPickLens'); }).join('') + '</div>' +
      '<div class="sv-lens-title">Effects</div><div class="sv-fx-bar sv-lens-bar">' +
      '<button type="button" class="sv-fx-chip' + (S.e < 0 ? ' on' : '') + '" onclick="svPickEffect(-1)">No effect</button>' +
      fx.map(function (i) { return chip(i, S.e === i, 'svPickEffect'); }).join('') + '</div>' +
      '<div class="sv-lens-title">Skillvaya originals</div><div class="sv-fx-bar sv-lens-bar">' +
      ORIG.map(function (o, n) { return '<button type="button" class="sv-orig-chip' + (S.e === 200 + n ? ' on' : '') + '" aria-label="' + o[2] + '" onclick="svPickEffect(' + (200 + n) + ')"><span>' + o[1] + '</span></button>'; }).join('') + '</div>';
  };

  async function refresh() {
    if (S.i >= 0 || S.e >= 0) loadDetector().then(function () { if (typeof svRenderFxBar === 'function') svRenderFxBar(); });
    try { if (typeof svApplyCallFx === 'function') await svApplyCallFx(typeof svFx !== 'undefined' ? svFx.id : 'none'); } catch (_) {}
    if (typeof svRenderFxBar === 'function') svRenderFxBar();
  }
  window.svPickLens = function (i) { i = Number(i); if (i >= 0 && KIND[i] === 2) { S.e = i; } else { S.i = i; S.face = null; S.lm = null; } return refresh(); };
  window.svPickEffect = function (i) { S.e = Number(i); P.length = 0; S.oc = 0; S.idle = 0; S.sayT = 0; return refresh(); };

  try {
    var st = document.createElement('style');
    st.textContent = '.sv-lens-title{color:#fff;font-weight:800;font-size:13px;margin:10px 2px 0;opacity:.9}.sv-lens-chip{flex:none;width:52px;height:52px;border-radius:50%;border:2px solid rgba(255,255,255,.3);background:rgba(255,255,255,.1);padding:6px;display:grid;place-items:center}.sv-lens-chip img{width:36px;height:36px}.sv-lens-chip.on{border-color:#fff;background:rgba(255,255,255,.3)}.sv-orig-chip{flex:none;min-width:52px;height:52px;align-content:center;border-radius:16px;border:2px solid rgba(255,215,0,.45);background:linear-gradient(180deg,rgba(0,119,73,.35),rgba(255,184,28,.18));color:#fff;padding:6px 8px;display:grid;justify-items:center;gap:2px}.sv-orig-chip span{font-size:26px;line-height:1}.sv-orig-chip small{font-size:10.5px;font-weight:800;white-space:nowrap}.sv-orig-chip.on{border-color:#FFB81C;background:rgba(255,184,28,.45)}';
    document.head.appendChild(st);
  } catch (_) {}
})();
