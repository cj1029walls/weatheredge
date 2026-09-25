/* DFSRADAR · 3D venues (three.js r128, loaded on demand).
 *
 * One look for every sport, drawn in the site's own palette: slate surfaces
 * like the cards, soft studio light, white chalk, and cyan for the one thing
 * that moves: the wind. Every venue sits on a faint radar scope.
 *
 *   Venue3D.load()               -> Promise<THREE>   (three.js + fonts, once)
 *   Venue3D.mount(canvas, spec)  -> instance | null  (null = no WebGL: keep the flat view)
 *       spec.sport  "mlb" | "nfl" | "cfb" | "nascar" | "pga"
 *       spec.g      the feed object: MLB/NFL/CFB game, NASCAR race, PGA round
 *       spec.event  PGA only: the event (carries .hole)
 *   Venue3D.dispose(instance)
 *   Park3D.load / mount(canvas, g) / dispose   MLB alias kept for older callers
 *
 * Honest about what we know: MLB wind is drawn against the real park (the
 * feed's angle to center field), NFL wind at its real angle to the field
 * axis, college wind by compass (no stadium bearings on file, so the field is
 * drawn north-south and says so). NASCAR and golf feeds carry no wind
 * direction, so there the wind shows only as flags moving with its speed.
 */
(function () {
"use strict";

/* ================================================================ loader */
const THREE_SRC = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
const RM = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
let threeP = null, fontsP = null;
function loadThree() {
  if (window.THREE) return Promise.resolve(window.THREE);
  if (!threeP) threeP = new Promise((resolve, reject) => {
    const sc = document.createElement("script");
    let settled = false;
    const done = (ok, err) => { if (settled) return; settled = true; clearTimeout(timer); if (ok) resolve(window.THREE); else { threeP = null; reject(err); } };
    const timer = setTimeout(() => done(false, new Error("three.js timed out")), 15000);
    sc.src = THREE_SRC; sc.async = true;
    sc.onload = () => done(!!window.THREE, new Error("three.js missing"));
    sc.onerror = () => done(false, new Error("three.js failed to load"));
    document.head.appendChild(sc);
  });
  return threeP;
}
/* labels are painted with the site's display face; wait for it (briefly) */
function fontsReady() {
  if (!fontsP) {
    const f = document.fonts;
    fontsP = !f || !f.load ? Promise.resolve() :
      Promise.race([Promise.all([f.load("700 64px Sora"), f.load("600 64px Sora")]), new Promise(r => setTimeout(r, 1500))]).catch(() => {});
  }
  return fontsP;
}
function load() { return Promise.all([loadThree(), fontsReady()]).then(() => window.THREE); }

/* ================================================================ palette
   dr.css tokens plus the few surface tones a venue needs, all from the same
   slate family (grass leans toward the cyan accent, clay toward mauve) so the
   canvas reads as part of its card. */
const PAL = {
  ground: "#252A35", card: "#323A4A", ring: "#67e8f9",
  turf: "#35545A", turf2: "#39595F", turfDim: "#2E464C", rough: "#2B3F45", green: "#3F6166",
  clay: "#5A5563", clayDark: "#4A4653", sand: "#8C889A", waste: "#555160",
  stand: "#4A5467", stand2: "#3C4455", glass: "#2A303D", rim: "#5C6780", wall: "#3F4859", facade: "#384050", cap: "#C7CEDC",
  chalk: "#E8EDF5", ink: "#20242E", dim: "#8E97AD",
  asphalt: "#30343F", asphaltHot: "#3C3538", apron: "#414755", water: "#1D3550", tree: "#27393F",
  cyan: "#22d3ee", cyan2: "#67e8f9", warn: "#fbbf24", cool: "#93b4dd"
};

/* ================================================================ MLB parks
   real fence distances [LF, LCF, CF, RCF, RF] and wall heights (ft) */
const PARKS = {
  ARI:{name:"Chase Field",              dims:[330,374,407,374,334], walls:[8,8,25,8,9],    roof:true},
  ATH:{name:"Sutter Health Park",       dims:[330,396,403,386,325], walls:[8,8,8,8,8]},
  ATL:{name:"Truist Park",              dims:[335,385,400,375,325], walls:[8,8,8,8,16]},
  BAL:{name:"Camden Yards",             dims:[333,364,410,373,318], walls:[7,7,7,8,21]},
  BOS:{name:"Fenway Park",              dims:[310,379,390,380,302], walls:[37,37,17,5,3]},
  CHC:{name:"Wrigley Field",            dims:[355,368,400,368,353], walls:[15,11,11,11,15]},
  CIN:{name:"Great American Ball Park", dims:[328,379,404,370,325], walls:[12,8,8,8,8]},
  CLE:{name:"Progressive Field",        dims:[325,370,405,375,325], walls:[19,19,9,9,9]},
  COL:{name:"Coors Field",              dims:[347,390,415,375,350], walls:[8,8,8,13,14]},
  CWS:{name:"Rate Field",               dims:[330,375,400,375,335], walls:[8,8,8,8,8]},
  DET:{name:"Comerica Park",            dims:[345,370,412,365,330], walls:[8,8,9,9,8]},
  HOU:{name:"Daikin Park",              dims:[315,362,409,373,326], walls:[19,19,9,9,7],   roof:true},
  KC: {name:"Kauffman Stadium",         dims:[330,387,410,387,330], walls:[8,8,8,8,8]},
  LAA:{name:"Angel Stadium",            dims:[330,387,396,370,330], walls:[8,8,8,18,18]},
  LAD:{name:"Dodger Stadium",           dims:[330,385,395,385,330], walls:[8,8,8,8,8]},
  MIA:{name:"loanDepot park",           dims:[344,386,400,387,335], walls:[10,10,10,10,10],roof:true},
  MIL:{name:"American Family Field",    dims:[344,371,400,374,345], walls:[8,8,8,8,8],     retract:true},
  MIN:{name:"Target Field",             dims:[339,377,404,367,328], walls:[8,8,8,23,23]},
  NYM:{name:"Citi Field",               dims:[335,370,408,380,330], walls:[8,8,8,8,8]},
  NYY:{name:"Yankee Stadium",           dims:[318,399,408,385,314], walls:[8,8,8,8,8]},
  PHI:{name:"Citizens Bank Park",       dims:[329,374,401,369,330], walls:[12,12,6,12,12]},
  PIT:{name:"PNC Park",                 dims:[325,389,399,375,320], walls:[6,10,10,21,21]},
  SD: {name:"Petco Park",               dims:[336,390,396,391,322], walls:[4,8,8,8,10]},
  SEA:{name:"T-Mobile Park",            dims:[331,378,401,381,326], walls:[8,8,8,8,8],     retract:true},
  SF: {name:"Oracle Park",              dims:[339,364,391,415,309], walls:[8,8,8,8,25]},
  STL:{name:"Busch Stadium",            dims:[336,375,400,375,335], walls:[8,8,8,8,8]},
  TB: {name:"Tropicana Field",          dims:[315,370,404,370,322], walls:[10,10,10,10,10],roof:true},
  TEX:{name:"Globe Life Field",         dims:[329,372,407,374,326], walls:[8,8,8,8,8],     roof:true},
  TOR:{name:"Rogers Centre",            dims:[328,375,400,375,328], walls:[10,10,10,10,10],retract:true},
  WSH:{name:"Nationals Park",           dims:[336,377,402,370,335], walls:[8,8,8,8,8]},
};
const PARK_DEFAULT = { dims: [335, 375, 400, 375, 335], walls: [8, 8, 8, 8, 8] };

/* ================================================================ helpers */
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
function hourOf(s) { /* "7:05 PM ET" -> 19 */
  const m = /(\d{1,2}):(\d{2})\s*([AP])M/i.exec(String(s || ""));
  if (!m) return null;
  let h = +m[1] % 12; if (/p/i.test(m[3])) h += 12;
  return h + (+m[2]) / 60;
}

function kit(T) {
  const lin = hex => new T.Color(hex).convertSRGBToLinear();
  const lam = (hex, o) => new T.MeshLambertMaterial(Object.assign({ color: lin(hex) }, o || {}));
  const bas = (hex, o) => new T.MeshBasicMaterial(Object.assign({ color: lin(hex), toneMapped: false }, o || {}));
  const V2 = (x, y) => new T.Vector2(x, y);
  const V3 = (x, y, z) => new T.Vector3(x, y, z);
  /* shape coords (x, y) lie flat on the ground as world (x, h, -y) */
  function flat(pts, y, mat, o) {
    const geo = new T.ShapeGeometry(new T.Shape(pts), (o && o.curveSegs) || 12);
    const m = new T.Mesh(geo, mat);
    m.rotation.x = -Math.PI / 2; m.position.y = y;
    m.receiveShadow = true;
    return m;
  }
  /* quad strip between parallel polylines (arrays of Vector3 of equal length) */
  function strip(rows, mat, o) {
    o = o || {};
    const n = rows[0].length, pos = [], uv = [], idx = [];
    const du = [0];
    for (let i = 1; i < n; i++) du.push(du[i - 1] + rows[0][i].distanceTo(rows[0][i - 1]));
    rows.forEach((row, r) => row.forEach((p, i) => { pos.push(p.x, p.y, p.z); uv.push(du[i] / (o.uScale || 1), r * (o.vScale || 1)); }));
    for (let r = 0; r < rows.length - 1; r++) for (let i = 0; i < n - 1; i++) {
      const a = r * n + i, b = a + 1, c = a + n, d = c + 1;
      idx.push(a, c, b, b, c, d);
    }
    const geo = new T.BufferGeometry();
    geo.setAttribute("position", new T.Float32BufferAttribute(pos, 3));
    geo.setAttribute("uv", new T.Float32BufferAttribute(uv, 2));
    geo.setIndex(idx); geo.computeVertexNormals();
    const m = new T.Mesh(geo, mat);
    m.castShadow = !!o.cast; m.receiveShadow = o.receive !== false;
    return m;
  }
  /* flat band of width w along a ground polyline (Vector2 shape coords) */
  function band(pts2, w, y, mat, closed) {
    const L = [], R = [];
    const n = pts2.length;
    for (let i = 0; i < n; i++) {
      const a = pts2[closed ? (i - 1 + n) % n : Math.max(0, i - 1)], b = pts2[closed ? (i + 1) % n : Math.min(n - 1, i + 1)];
      const t = V2(b.x - a.x, b.y - a.y).normalize(), nn = V2(-t.y, t.x);
      L.push(V3(pts2[i].x + nn.x * w / 2, y, -(pts2[i].y + nn.y * w / 2)));
      R.push(V3(pts2[i].x - nn.x * w / 2, y, -(pts2[i].y - nn.y * w / 2)));
    }
    if (closed) { L.push(L[0].clone()); R.push(R[0].clone()); }
    return strip([L, R], mat, { receive: true });
  }
  /* canvas texture with text, painted in the site's display face */
  function textTex(text, o) {
    o = o || {};
    const px = o.px || 96, pad = o.pad == null ? Math.round(px * 0.3) : o.pad;
    const cv = document.createElement("canvas"), cx = cv.getContext("2d");
    const font = (o.weight || 700) + " " + px + "px Sora, \"Segoe UI\", Arial, sans-serif";
    cx.font = font;
    const tw = Math.ceil(cx.measureText(text).width);
    cv.width = tw + pad * 2; cv.height = Math.ceil(px * 1.25) + pad;
    cx.font = font; cx.textAlign = "center"; cx.textBaseline = "middle";
    if (o.bg) {
      const r = Math.min(cv.height / 2, px * 0.5);
      cx.fillStyle = o.bg; cx.beginPath();
      cx.moveTo(r, 0); cx.lineTo(cv.width - r, 0); cx.quadraticCurveTo(cv.width, 0, cv.width, r);
      cx.lineTo(cv.width, cv.height - r); cx.quadraticCurveTo(cv.width, cv.height, cv.width - r, cv.height);
      cx.lineTo(r, cv.height); cx.quadraticCurveTo(0, cv.height, 0, cv.height - r);
      cx.lineTo(0, r); cx.quadraticCurveTo(0, 0, r, 0); cx.fill();
      if (o.border) { cx.strokeStyle = o.border; cx.lineWidth = Math.max(2, px * 0.05); cx.stroke(); }
    }
    if (o.letter) { try { cx.letterSpacing = o.letter + "px"; } catch (e) {} }
    cx.fillStyle = o.color || PAL.chalk;
    cx.fillText(text, cv.width / 2, cv.height / 2 + px * 0.04);
    const tex = new T.CanvasTexture(cv);
    tex.encoding = T.sRGBEncoding; tex.anisotropy = 8;
    return { tex, aspect: cv.width / cv.height };
  }
  function textPlane(text, h, o) {
    const t = textTex(text, o);
    const mat = new T.MeshBasicMaterial({ map: t.tex, transparent: true, depthWrite: false, toneMapped: false, opacity: (o && o.opacity) || 1, side: T.DoubleSide });
    const m = new T.Mesh(new T.PlaneGeometry(h * t.aspect, h), mat);
    m.renderOrder = 3;
    return m;
  }
  function textSprite(text, h, o) {
    const t = textTex(text, o);
    const s = new T.Sprite(new T.SpriteMaterial({ map: t.tex, transparent: true, depthWrite: false, toneMapped: false }));
    s.scale.set(h * t.aspect, h, 1); s.renderOrder = 5;
    return s;
  }
  /* repeating canvas pattern (stripes, seat rows, fences, checkers) */
  function pattern(w, h, draw, o) {
    const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
    draw(cv.getContext("2d"), w, h);
    const tex = new T.CanvasTexture(cv);
    tex.wrapS = tex.wrapT = T.RepeatWrapping; tex.encoding = T.sRGBEncoding; tex.anisotropy = 8;
    if (o && o.repeat) tex.repeat.set(o.repeat[0], o.repeat[1]);
    if (o && o.rotation) tex.rotation = o.rotation;
    return tex;
  }
  let glowTexC = null;
  function glowTex() {
    if (glowTexC) return glowTexC;
    const cv = document.createElement("canvas"); cv.width = cv.height = 128;
    const cx = cv.getContext("2d"), g = cx.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(0.18, "rgba(235,246,255,.55)"); g.addColorStop(0.5, "rgba(200,230,255,.12)"); g.addColorStop(1, "rgba(200,230,255,0)");
    cx.fillStyle = g; cx.fillRect(0, 0, 128, 128);
    glowTexC = new T.CanvasTexture(cv);
    return glowTexC;
  }
  function glow(size, color, opacity) {
    const s = new T.Sprite(new T.SpriteMaterial({ map: glowTex(), color: lin(color || "#ffffff"), transparent: true, opacity: opacity == null ? 0.9 : opacity, blending: T.AdditiveBlending, depthWrite: false, toneMapped: false }));
    s.scale.set(size, size, 1); s.renderOrder = 4;
    return s;
  }
  return { lin, lam, bas, V2, V3, flat, strip, band, textTex, textPlane, textSprite, pattern, glow };
}

/* seats: fine rows with aisles, the texture every stand shares */
function seatTex(K) {
  return K.pattern(256, 64, (c, w, h) => {
    c.fillStyle = PAL.stand; c.fillRect(0, 0, w, h);
    for (let y = 0; y < h; y += 8) { c.fillStyle = "rgba(14,18,26,.22)"; c.fillRect(0, y + 5, w, 2); c.fillStyle = "rgba(255,255,255,.06)"; c.fillRect(0, y + 3, w, 1); }
    c.fillStyle = "rgba(14,18,26,.30)"; c.fillRect(0, 0, 4, h); c.fillRect(w / 2, 0, 3, h);
  });
}
/* mowed turf: two tones in bands */
function stripeTex(K, a, b, o) {
  return K.pattern(128, 128, (c, w, h) => {
    c.fillStyle = a; c.fillRect(0, 0, w, h);
    c.fillStyle = b; c.fillRect(0, 0, w / 2, h);
    if (o && o.check) { c.fillStyle = "rgba(255,255,255,.035)"; c.fillRect(0, 0, w, h / 2); }
  }, o);
}

/* ================================================================ stage */
function makeStage(T, K, canvas, env) {
  let renderer;
  try {
    renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  } catch (e) { return null; }
  if (!renderer || !renderer.getContext()) return null;
  const small = Math.min(window.innerWidth || 1000, window.innerHeight || 800) < 700;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, small ? 2 : 1.75));
  renderer.setClearColor(0x000000, 0);
  renderer.outputEncoding = T.sRGBEncoding;
  renderer.toneMapping = T.NoToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  const W = canvas.clientWidth || 800, H = canvas.clientHeight || 400;
  renderer.setSize(W, H, false);

  const scene = new T.Scene();
  const S = env.S;
  /* fog is mixed after encoding in r128, so it takes the card's sRGB value:
     the far side of a venue hazes into the card behind the canvas */
  scene.fog = new T.Fog(new T.Color(PAL.card), S * (env.fog ? 1.1 : 1.7), S * (env.fog ? 3.2 : 4.6));

  /* soft studio light: a strong sky dome and a high key, so every side of a
     venue reads while the camera turns and shadows stay light */
  const overcast = /overcast|cloud|rain|fog|shower|storm/i.test(env.sky || "");
  const amb = new T.AmbientLight(K.lin(env.night ? "#C9D5EA" : "#E3EAF5"), env.night ? 0.6 : 0.64);
  const hemi = new T.HemisphereLight(K.lin(env.night ? "#B7C6E0" : "#E6EEF8"), K.lin("#2A303D"), env.night ? 0.3 : (overcast ? 0.36 : 0.28));
  const key = new T.DirectionalLight(K.lin(env.night ? "#E4EEFF" : "#FFF6EA"), env.night ? 0.34 : (overcast ? 0.3 : 0.42));
  const c = env.center;
  if (env.night) key.position.set(c.x + S * 0.2, S * 1.9, c.z + S * 0.3);
  else key.position.set(c.x - S * 0.55, S * 1.6, c.z + S * 0.45);
  key.target.position.copy(c);
  key.castShadow = true;
  key.shadow.mapSize.set(small ? 1024 : 2048, small ? 1024 : 2048);
  const sc = key.shadow.camera;
  sc.left = -S * 1.25; sc.right = S * 1.25; sc.top = S * 1.25; sc.bottom = -S * 1.25; sc.near = 1; sc.far = S * 5;
  key.shadow.bias = -0.0006; key.shadow.normalBias = S * 0.0015;
  const fill = new T.DirectionalLight(K.lin("#9FB6D8"), env.night ? 0.22 : 0.18);
  fill.position.set(c.x + S * 0.8, S * 0.55, c.z - S * 0.6);
  scene.add(amb, hemi, key, key.target, fill);

  /* ground: slate floor that fades out at its edge, under a radar scope */
  const gr = S * 2.7;
  const fade = K.pattern(256, 256, (cx, w) => {
    const g = cx.createRadialGradient(w / 2, w / 2, w * 0.18, w / 2, w / 2, w / 2);
    g.addColorStop(0, "#fff"); g.addColorStop(0.62, "#bbb"); g.addColorStop(1, "#000");
    cx.fillStyle = g; cx.fillRect(0, 0, w, w);
  });
  fade.wrapS = fade.wrapT = T.ClampToEdgeWrapping; fade.encoding = T.LinearEncoding;
  const floor = new T.Mesh(new T.CircleGeometry(gr, 72), K.lam(PAL.ground, { transparent: true, alphaMap: fade, depthWrite: false }));
  floor.rotation.x = -Math.PI / 2; floor.position.set(c.x, -0.6, c.z); floor.receiveShadow = true; floor.renderOrder = -2;
  scene.add(floor);
  const rings = K.pattern(1024, 1024, (cx, w) => {
    const R = w / 2, n = 6;
    for (let i = 1; i <= n; i++) {
      cx.beginPath(); cx.arc(R, R, R * (i / (n + 0.5)), 0, Math.PI * 2);
      cx.strokeStyle = "rgba(103,232,249," + (0.26 - i * 0.022).toFixed(3) + ")"; cx.lineWidth = i === n ? 2.4 : 1.6; cx.stroke();
    }
    cx.strokeStyle = "rgba(103,232,249,.09)"; cx.lineWidth = 1.4;
    cx.beginPath(); cx.moveTo(R, 0); cx.lineTo(R, w); cx.moveTo(0, R); cx.lineTo(w, R); cx.stroke();
    for (let a = 0; a < 360; a += 5) {
      const rad = a * Math.PI / 180, r0 = R * (n / (n + 0.5)), len = a % 30 === 0 ? 18 : 8;
      cx.beginPath(); cx.moveTo(R + Math.cos(rad) * r0, R + Math.sin(rad) * r0); cx.lineTo(R + Math.cos(rad) * (r0 + len), R + Math.sin(rad) * (r0 + len));
      cx.strokeStyle = "rgba(103,232,249,.22)"; cx.lineWidth = a % 30 === 0 ? 2 : 1.2; cx.stroke();
    }
    cx.globalCompositeOperation = "destination-in";
    const g = cx.createRadialGradient(R, R, R * 0.1, R, R, R);
    g.addColorStop(0, "rgba(0,0,0,.55)"); g.addColorStop(0.5, "rgba(0,0,0,1)"); g.addColorStop(0.9, "rgba(0,0,0,.7)"); g.addColorStop(1, "rgba(0,0,0,0)");
    cx.fillStyle = g; cx.fillRect(0, 0, w, w);
  });
  rings.wrapS = rings.wrapT = T.ClampToEdgeWrapping;
  const scope = new T.Mesh(new T.PlaneGeometry(gr * 1.7, gr * 1.7), new T.MeshBasicMaterial({ map: rings, transparent: true, depthWrite: false, toneMapped: false, opacity: env.night ? 0.95 : 0.8 }));
  scope.rotation.x = -Math.PI / 2; scope.position.set(c.x, -0.4, c.z); scope.renderOrder = -1;
  scene.add(scope);
  /* a slow radar sweep across the scope; skipped for reduced motion */
  let sweep = null;
  if (!RM.matches) {
    const st = K.pattern(512, 512, (cx, w) => {
      const R = w / 2, N = 160, span = 1.1;
      for (let i = N - 1; i >= 0; i--) {
        const a0 = -span * i / N, a1 = a0 - span / N * 1.6;
        cx.beginPath(); cx.moveTo(R, R); cx.arc(R, R, R, a1, a0); cx.closePath();
        cx.fillStyle = "rgba(103,232,249," + (0.11 * Math.pow(1 - i / N, 2.4)).toFixed(4) + ")"; cx.fill();
      }
      cx.globalCompositeOperation = "destination-in";
      const g = cx.createRadialGradient(R, R, 0, R, R, R);
      g.addColorStop(0, "rgba(0,0,0,.2)"); g.addColorStop(0.35, "rgba(0,0,0,1)"); g.addColorStop(0.75, "rgba(0,0,0,.8)"); g.addColorStop(1, "rgba(0,0,0,0)");
      cx.fillStyle = g; cx.fillRect(0, 0, w, w);
    });
    st.wrapS = st.wrapT = T.ClampToEdgeWrapping;
    sweep = new T.Mesh(new T.CircleGeometry(gr * 0.62, 72), new T.MeshBasicMaterial({ map: st, transparent: true, depthWrite: false, toneMapped: false, blending: T.AdditiveBlending, opacity: 0.8 }));
    sweep.rotation.x = -Math.PI / 2; sweep.position.set(c.x, -0.3, c.z); sweep.renderOrder = -1;
    scene.add(sweep);
  }
  return { renderer, scene, key, hemi, sweep, small };
}

/* ================================================================ wind, rain, flags */
/* wind: long streamlines drifting across the venue, with bright dashes that
   flow downwind at a pace set by the forecast speed. One merged mesh, one
   scrolling texture. */
function windLines(T, K, scene, o) {
  const mph = o.mph || 0, str = clamp(mph / 20, 0.12, 1), S = o.S;
  const N = Math.round(12 + str * 20);
  const d = new T.Vector2(o.dir.x, o.dir.z).normalize(), pp = new T.Vector2(-d.y, d.x);
  const C = o.center, R = o.R || S;
  const rnd = (a, b) => a + Math.random() * (b - a);
  const dashLen = S * 0.46;
  const pos = [], uv = [], col = [], idx = [];
  const cc = K.lin(PAL.cyan2);
  let vi = 0;
  for (let k = 0; k < N; k++) {
    const sOff = lerp(-R * 0.92, R * 0.92, (k + rnd(0.1, 0.9)) / N);
    const half = Math.sqrt(Math.max(0, R * R - sOff * sOff));
    if (half < R * 0.25) continue;
    const y0 = lerp(o.y0, o.y1, Math.pow(Math.random(), 1.2)), rise = rnd(-0.04, 0.06) * S;
    const amp = rnd(0.008, 0.026) * S, fq = rnd(0.5, 1.1) * Math.PI / half, ph = rnd(0, 6.28);
    const w = S * rnd(0.004, 0.0065), u0 = rnd(0, 1), a0 = rnd(0.6, 1);
    const M = 64, pts = [];
    for (let i = 0; i <= M; i++) {
      const t = lerp(-half, half, i / M);
      const lat = sOff + amp * Math.sin(fq * t + ph);
      pts.push(new T.Vector3(C.x + d.x * t + pp.x * lat, y0 + rise * (i / M), C.z + d.y * t + pp.y * lat));
    }
    let run = 0;
    for (let i = 0; i <= M; i++) {
      const P = pts[i], Q = pts[Math.min(M, i + 1)], Pm = pts[Math.max(0, i - 1)];
      const tx = Q.x - Pm.x, tz = Q.z - Pm.z, tl = Math.hypot(tx, tz) || 1;
      const nx = -tz / tl, nz = tx / tl;
      if (i) run += P.distanceTo(pts[i - 1]);
      const f = i / M, fade = smooth(0, 0.18, f) * smooth(1, 0.8, f) * a0;
      pos.push(P.x + nx * w / 2, P.y, P.z + nz * w / 2, P.x - nx * w / 2, P.y, P.z - nz * w / 2);
      const u = u0 + run / dashLen;
      uv.push(u, 0, u, 1);
      col.push(cc.r, cc.g, cc.b, fade, cc.r, cc.g, cc.b, fade);
      if (i < M) { const a = vi + i * 2; idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3); }
    }
    vi += (M + 1) * 2;
  }
  /* the dash: a soft tail brightening into a crisp head */
  const tex = K.pattern(512, 4, (c, w, h) => {
    c.clearRect(0, 0, w, h);
    const g = c.createLinearGradient(0, 0, w, 0);
    g.addColorStop(0, "rgba(255,255,255,0)"); g.addColorStop(0.3, "rgba(255,255,255,0)");
    g.addColorStop(0.86, "rgba(255,255,255,.95)"); g.addColorStop(0.9, "rgba(255,255,255,1)"); g.addColorStop(0.93, "rgba(255,255,255,0)"); g.addColorStop(1, "rgba(255,255,255,0)");
    c.fillStyle = g; c.fillRect(0, 0, w, h);
  });
  tex.wrapT = T.ClampToEdgeWrapping;
  const geo = new T.BufferGeometry();
  geo.setAttribute("position", new T.Float32BufferAttribute(pos, 3));
  geo.setAttribute("uv", new T.Float32BufferAttribute(uv, 2));
  geo.setAttribute("color", new T.Float32BufferAttribute(col, 4));
  geo.setIndex(idx);
  const mat = new T.MeshBasicMaterial({ map: tex, vertexColors: true, transparent: true, depthWrite: false, side: T.DoubleSide, blending: T.AdditiveBlending, toneMapped: false, opacity: 0.55 + 0.4 * str });
  const mesh = new T.Mesh(geo, mat); mesh.renderOrder = 6; mesh.frustumCulled = false;
  scene.add(mesh);
  /* a faint, steady trace of every line under the dashes */
  const trace = new T.Mesh(geo, new T.MeshBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false, side: T.DoubleSide, blending: T.AdditiveBlending, toneMapped: false, opacity: 0.05 + 0.05 * str }));
  trace.renderOrder = 5; trace.frustumCulled = false; scene.add(trace);
  const speed = S * (0.08 + mph * 0.011) / dashLen;
  return function advance(dt) { tex.offset.x -= dt * speed; };
}
function rainFall(T, K, scene, o) {
  const RN = Math.round(110 + clamp((o.pct - 40) / 50, 0, 1) * 220);
  const a = Math.atan2(o.dir ? o.dir.x : 0, o.dir ? -o.dir.z : -1), tilt = o.dir ? Math.min(0.45, o.mph * 0.028) : 0.05;
  const vel = new T.Vector3(Math.sin(a) * tilt, -1, -Math.cos(a) * tilt).normalize();
  const bx = o.box, rnd = (p, q) => p + Math.random() * (q - p);
  const drops = [];
  for (let i = 0; i < RN; i++) drops.push(new T.Vector3(rnd(bx.x0, bx.x1), rnd(0, bx.y1 * 1.3), rnd(bx.z0, bx.z1)));
  const geo = new T.BufferGeometry();
  geo.setAttribute("position", new T.BufferAttribute(new Float32Array(RN * 6), 3));
  const mesh = new T.LineSegments(geo, new T.LineBasicMaterial({ color: K.lin(PAL.cool), transparent: true, opacity: 0.42, toneMapped: false }));
  mesh.frustumCulled = false; scene.add(mesh);
  const len = o.S * 0.022, speed = o.S * 0.75;
  return function advance(dt) {
    const pos = geo.attributes.position.array;
    for (let i = 0; i < RN; i++) {
      const d = drops[i];
      d.addScaledVector(vel, speed * dt);
      if (d.y < 0.5) d.set(rnd(bx.x0, bx.x1), bx.y1 * 1.3, rnd(bx.z0, bx.z1));
      pos[i * 6] = d.x; pos[i * 6 + 1] = d.y; pos[i * 6 + 2] = d.z;
      pos[i * 6 + 3] = d.x + vel.x * len; pos[i * 6 + 4] = d.y + vel.y * len; pos[i * 6 + 5] = d.z + vel.z * len;
    }
    geo.attributes.position.needsUpdate = true;
  };
}
/* a cloth flag: hoist at the origin, flying along +x of its group */
function makeFlag(T, K, o) {
  const w = o.w, h = o.h;
  const geo = new T.PlaneGeometry(w, h, 16, 6); geo.translate(w / 2, -h / 2, 0);
  const mat = o.map ? new T.MeshLambertMaterial({ map: o.map, side: T.DoubleSide }) : K.lam(o.color || PAL.cyan, { side: T.DoubleSide, emissive: K.lin(o.color || PAL.cyan), emissiveIntensity: 0.35 });
  const mesh = new T.Mesh(geo, mat); mesh.castShadow = true;
  const grp = new T.Group(); grp.add(mesh);
  const base = geo.attributes.position.array.slice();
  const mph = o.mph || 0, lift = clamp(mph / 14, 0.15, 1), amp = 0.05 + clamp(mph / 25, 0, 1) * 0.16, freq = 2.2 + mph * 0.22;
  const ph = Math.random() * 6;
  function update(t) {
    const a = geo.attributes.position.array;
    for (let i = 0; i < a.length; i += 3) {
      const x = base[i], y = base[i + 1], u = x / w;
      const droop = (1 - lift) * u * u * h * 1.25;
      a[i] = x * (0.82 + 0.18 * lift);
      a[i + 1] = y - droop;
      a[i + 2] = Math.sin(u * 7.5 - t * freq + ph) * amp * w * u + Math.sin(u * 3.1 - t * freq * 0.6) * amp * 0.4 * w * u;
    }
    geo.attributes.position.needsUpdate = true; geo.computeVertexNormals();
  }
  update(0);
  return { group: grp, update };
}

/* ================================================================ camera + controls */
const SWAY = 0.42;
function orbit(canvas, cam, o) {
  let theta = o.theta || 0, el = o.el, dist = o.dist || 800;
  const target = o.target.clone(), home = { theta, el, dist };
  const ptr = new Map(); let pinch = 0, idle = 0; let dirty = true;
  function place() {
    cam.position.set(target.x + Math.sin(theta) * Math.cos(el) * dist, target.y + Math.sin(el) * dist, target.z + Math.cos(theta) * Math.cos(el) * dist);
    cam.lookAt(target);
  }
  let base = dist, swayOn = false, swayBase = 0, ph = 0;
  const clampAll = () => { el = clamp(el, o.minEl || 0.18, o.maxEl || 1.3); dist = clamp(dist, base * 0.45, base * 1.7); };
  function down(e) { ptr.set(e.pointerId, { x: e.clientX, y: e.clientY }); try { canvas.setPointerCapture(e.pointerId); } catch (x) {} idle = 0; if (ptr.size === 2) pinch = spread(); }
  function spread() { const p = [...ptr.values()]; return Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y); }
  function move(e) {
    if (!ptr.has(e.pointerId)) return;
    const prev = ptr.get(e.pointerId), cur = { x: e.clientX, y: e.clientY };
    ptr.set(e.pointerId, cur); idle = 0; dirty = true;
    if (ptr.size === 1) { theta -= (cur.x - prev.x) * 0.0065; el += (cur.y - prev.y) * 0.0042; }
    else if (ptr.size === 2) { const s = spread(); if (pinch > 0) dist *= pinch / s; pinch = s; }
    clampAll();
  }
  function up(e) { ptr.delete(e.pointerId); pinch = ptr.size === 2 ? spread() : 0; }
  function wheel(e) { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); dist *= Math.exp(e.deltaY * 0.0025); clampAll(); idle = 0; dirty = true; }
  function dbl() { theta = home.theta; el = home.el; dist = home.dist; dirty = true; idle = 0; }
  canvas.addEventListener("pointerdown", down); canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
  canvas.addEventListener("wheel", wheel, { passive: false }); canvas.addEventListener("dblclick", dbl);
  return {
    place,
    rebase(b) { if (!(b > 0)) return; dist *= b / base; home.dist = b; base = b; dirty = true; },
    set(th, e, d) { if (th != null && !isNaN(th)) theta = th; if (e != null && !isNaN(e)) el = e; if (d != null && !isNaN(d)) dist = d; idle = -1e9; dirty = true; },
    /* when left alone, the view sways gently around wherever it was left */
    tick(dt, auto) {
      idle += dt;
      if (!auto || ptr.size || idle <= 3) { swayOn = false; return; }
      if (!swayOn) { swayOn = true; swayBase = theta; ph = 0; }
      ph += dt;
      theta = swayBase + (o.sway == null ? SWAY : o.sway) * Math.sin(ph * 0.16) * smooth(0, 3, ph);
    },
    get dirty() { const d = dirty; dirty = false; return d; },
    dispose() {
      canvas.removeEventListener("pointerdown", down); canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up); canvas.removeEventListener("pointercancel", up);
      canvas.removeEventListener("wheel", wheel); canvas.removeEventListener("dblclick", dbl);
    }
  };
}

/* ================================================================ shared structure: stands + lights */
/* tiered stands along a path of front-edge points (Vector2 shape coords) with
   outward normals; tiers = [[offset, height], ...] per row line. The back is
   closed with a facade down to the ground, and open runs get end caps, so
   the stands read as solid massing from every side. */
function buildStands(T, K, grp, front, normals, tiers, o) {
  o = o || {};
  const DS = T.DoubleSide;
  const mats = {
    seat: o.seats || K.lam("#ffffff", { map: seatTex(K), side: DS }),
    glass: K.lam(PAL.glass, { side: DS }),
    rim: K.lam(PAL.rim, { side: DS }),
    wall: K.lam(PAL.wall, { side: DS })
  };
  const facade = K.lam(PAL.facade, { side: DS });
  const rows = tiers.map(([off, h]) => front.map((p, i) => K.V3(p.x + normals[i].x * off, h, -(p.y + normals[i].y * off))));
  const plen = front.reduce((s, p, i) => i ? s + p.distanceTo(front[i - 1]) : 0, 0);
  for (let r = 0; r < rows.length - 1; r++) {
    const kind = (o.kinds || [])[r] || "seat";
    const m = K.strip([rows[r], rows[r + 1]], mats[kind] || mats.wall, { cast: true, uScale: kind === "seat" ? 24 : 1, vScale: 1 });
    if (kind === "seat") {
      const uv = m.geometry.attributes.uv;
      for (let i = 0; i < uv.count; i++) uv.setY(i, uv.getY(i) * Math.max(4, Math.round((tiers[r + 1][0] - tiers[r][0]) / 3.2)));
      uv.needsUpdate = true;
    }
    grp.add(m);
  }
  /* facade: from the top rim straight down */
  const last = tiers[tiers.length - 1];
  const foot = front.map((p, i) => K.V3(p.x + normals[i].x * last[0], 0, -(p.y + normals[i].y * last[0])));
  grp.add(K.strip([rows[rows.length - 1], foot], facade, { cast: true }));
  if (tiers[0][1] > 0.5) {
    const toe = front.map((p, i) => K.V3(p.x + normals[i].x * tiers[0][0], 0, -(p.y + normals[i].y * tiers[0][0])));
    grp.add(K.strip([toe, rows[0]], mats.wall, { cast: false }));
  }
  /* end caps on open runs: the stand's profile, filled */
  if (!o.closed) [0, front.length - 1].forEach(i => {
    const prof = tiers.map(([off, h]) => K.V2(off, h));
    prof.push(K.V2(last[0], 0));
    if (tiers[0][1] > 0.5) prof.push(K.V2(tiers[0][0], 0));
    const geo = new T.ShapeGeometry(new T.Shape(prof));
    const pa = geo.attributes.position;
    for (let k = 0; k < pa.count; k++) { const sx = pa.getX(k), sy = pa.getY(k); pa.setXYZ(k, front[i].x + normals[i].x * sx, sy, -(front[i].y + normals[i].y * sx)); }
    geo.computeVertexNormals();
    const cap = new T.Mesh(geo, facade); cap.castShadow = true; cap.receiveShadow = true; grp.add(cap);
  });
  /* LED ribbon board along the suite level */
  if (o.ribbonAt != null) {
    const [off, h] = o.ribbonAt;
    const top = front.map((p, i) => K.V3(p.x + normals[i].x * (off - 0.4), h + 2.2, -(p.y + normals[i].y * (off - 0.4))));
    const bot = front.map((p, i) => K.V3(p.x + normals[i].x * (off - 0.4), h, -(p.y + normals[i].y * (off - 0.4))));
    const led = K.strip([bot, top], K.bas(PAL.cyan2, { transparent: true, opacity: o.night ? 0.9 : 0.6, side: DS }), { receive: false });
    led.renderOrder = 2; grp.add(led);
  }
  return { rows, length: plen };
}
function lightTower(T, K, grp, at, h, face, night) {
  const pole = new T.Mesh(new T.CylinderGeometry(0.8, 1.2, h, 8), K.lam(PAL.rim));
  pole.position.set(at.x, at.y + h / 2, at.z); pole.castShadow = true; pole.userData.noFit = true; grp.add(pole);
  const head = new T.Group();
  const frame = new T.Mesh(new T.BoxGeometry(20, 9, 2.4), K.lam(PAL.stand2));
  const lamps = new T.Mesh(new T.PlaneGeometry(18, 7.4), night ? K.bas("#F4FAFF") : K.lam("#9AA3B8"));
  lamps.position.z = 1.3; head.add(frame, lamps); frame.userData.noFit = lamps.userData.noFit = true;
  head.position.set(at.x, at.y + h + 4, at.z);
  head.lookAt(face.x, at.y + h * 0.2, face.z);
  grp.add(head);
  if (night) { const gl = K.glow(80, "#EAF6FF", 0.5); gl.position.copy(head.position); grp.add(gl); }
}
/* a closed roof hugging whatever the venue has built so far */
function domeOver(T, K, grp, lift) {
  const bb = new T.Box3().setFromObject(grp), c = new T.Vector3(), sz = new T.Vector3();
  bb.getCenter(c); bb.getSize(sz);
  domeShell(T, K, grp, K.V3(c.x, (lift || 0) + sz.y * 0.55, c.z), sz.x * 0.53, sz.z * 0.53, Math.max(sz.x, sz.z) * 0.2);
}
function domeShell(T, K, grp, c, rx, rz, hy) {
  const geo = new T.SphereGeometry(1, 48, 16, 0, Math.PI * 2, 0, Math.PI / 2);
  const shell = new T.Mesh(geo, K.bas(PAL.cap, { transparent: true, opacity: 0.07, side: T.DoubleSide, depthWrite: false }));
  shell.scale.set(rx, hy, rz); shell.position.copy(c); shell.renderOrder = 7; grp.add(shell);
  const wire = new T.LineSegments(new T.EdgesGeometry(new T.SphereGeometry(1, 20, 7, 0, Math.PI * 2, 0, Math.PI / 2), 1),
    new T.LineBasicMaterial({ color: K.lin(PAL.cyan2), transparent: true, opacity: 0.2, toneMapped: false, depthWrite: false }));
  wire.scale.copy(shell.scale); wire.position.copy(c); wire.renderOrder = 7; grp.add(wire);
}
/* outward normals for an open path of shape points, pointing away from ctr */
function outwardNormals(T, pts, ctr) {
  return pts.map((p, i) => {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
    const t = new T.Vector2(b.x - a.x, b.y - a.y).normalize();
    let n = new T.Vector2(-t.y, t.x);
    if (n.dot(new T.Vector2(p.x - ctr.x, p.y - ctr.y)) < 0) n.multiplyScalar(-1);
    return n;
  });
}

/* ================================================================ MLB ballpark */
function buildMLB(T, K, st, spec, env) {
  const g = spec.g || {}, park = PARKS[g.home] || PARK_DEFAULT, D = park.dims, WH = park.walls;
  const grp = new T.Group(); st.scene.add(grp);
  const SQ = Math.SQRT1_2, V2 = K.V2;
  const ang = [-45, -22.5, 0, 22.5, 45].map(a => a * Math.PI / 180);
  const ctrl = D.map((r, i) => V2(Math.sin(ang[i]) * r, Math.cos(ang[i]) * r));
  const wall = new T.SplineCurve(ctrl).getPoints(150);
  const uL = V2(-SQ, SQ), uR = V2(SQ, SQ), nL = V2(-SQ, -SQ), nR = V2(SQ, -SQ);
  const FOUL = 62, TRACK = 16;
  const at = (u, s, n, off) => V2(u.x * s + n.x * off, u.y * s + n.y * off);
  const inward = (p, by) => { const r = p.length(); return p.clone().multiplyScalar((r - by) / r); };
  /* front of the infield stands, RF corner -> behind home -> LF corner */
  function standsFront(off, sR, sL, n) {
    n = n || 20;
    const pts = [];
    for (let i = 0; i <= n; i++) pts.push(at(uR, sR * (1 - i / n), nR, off));
    for (let i = 1; i < 24; i++) { const a = -Math.PI / 4 - (Math.PI / 2) * (i / 24); pts.push(V2(Math.cos(a) * off, Math.sin(a) * off)); }
    for (let i = 0; i <= n; i++) pts.push(at(uL, sL * (i / n), nL, off));
    return pts;
  }
  const whole = [...wall, ...standsFront(FOUL, D[4], D[0])];
  const inner = [...wall.map(p => inward(p, TRACK)), ...standsFront(FOUL - TRACK, D[4] - TRACK, D[0] - TRACK)];
  const fair = [V2(0, 0), ...wall.map(p => inward(p, TRACK))];

  const clay = K.lam(PAL.clay), clayD = K.lam(PAL.clayDark);
  grp.add(K.flat(whole, 0.0, clayD));
  const foulTurf = K.lam(PAL.turfDim);
  grp.add(K.flat(inner, 0.3, foulTurf));
  const mow = stripeTex(K, PAL.turf, PAL.turf2, { repeat: [1 / 36, 1 / 36], rotation: Math.PI / 4 });
  grp.add(K.flat(fair, 0.6, K.lam("#ffffff", { map: mow })));
  /* infield skin, grass square, mound, plate area */
  const skin = new T.Mesh(new T.CircleGeometry(95, 64, -0.2, Math.PI + 0.4), clay);
  skin.rotation.x = -Math.PI / 2; skin.rotation.z = 0; skin.position.set(0, 0.9, -60.5); skin.receiveShadow = true;
  /* CircleGeometry thetaStart measured from +x; the arc must face CF (-z world = +y shape) */
  grp.add(skin);
  const skinBack = K.flat([V2(-64, 63), V2(0, -2), V2(64, 63), V2(0, 70)], 0.9, clay); grp.add(skinBack);
  const plateC = new T.Mesh(new T.CircleGeometry(14, 40), clay); plateC.rotation.x = -Math.PI / 2; plateC.position.set(0, 0.95, 0); plateC.receiveShadow = true; grp.add(plateC);
  const sq = [V2(0, 12), V2(52, 63.6), V2(0, 115.3), V2(-52, 63.6)];
  grp.add(K.flat(sq, 1.2, K.lam("#ffffff", { map: mow })));
  const mound = new T.Mesh(new T.CylinderGeometry(6.5, 9.5, 1.6, 36), clay);
  mound.position.set(0, 1.9, -60.5); mound.receiveShadow = true; mound.castShadow = true; grp.add(mound);
  const chalkB = K.bas(PAL.chalk);
  const rubber = new T.Mesh(new T.BoxGeometry(2.6, 0.4, 0.8), chalkB); rubber.position.set(0, 2.9, -60.5); grp.add(rubber);
  [[63.64, 63.64], [0, 127.28], [-63.64, 63.64]].forEach(([x, y]) => {
    const b = new T.Mesh(new T.BoxGeometry(3.4, 0.9, 3.4), K.lam(PAL.chalk, { emissive: K.lin(PAL.chalk), emissiveIntensity: 0.35 }));
    b.rotation.y = Math.PI / 4; b.position.set(x, 1.5, -y); b.castShadow = true; grp.add(b);
  });
  grp.add(K.flat([V2(-1.6, 0.8), V2(1.6, 0.8), V2(1.6, -0.6), V2(0, -2), V2(-1.6, -0.6)], 1.25, chalkB));
  /* chalk: foul lines out to the poles, batter's boxes */
  const lineMat = K.bas(PAL.chalk, { transparent: true, opacity: 0.92 });
  grp.add(K.band([V2(0, 0), at(uL, D[0], nL, 0)], 1.7, 1.35, lineMat));
  grp.add(K.band([V2(0, 0), at(uR, D[4], nR, 0)], 1.7, 1.35, lineMat));
  [-1, 1].forEach(sd => {
    const x0 = sd * 2.4, x1 = sd * 6.4;
    grp.add(K.band([V2(x0, -3), V2(x1, -3), V2(x1, 3), V2(x0, 3), V2(x0, -3)], 0.45, 1.3, lineMat));
  });
  /* dugouts cut into the front of the stands */
  [[uL, nL], [uR, nR]].forEach(([u, n]) => {
    const a = at(u, 58, n, FOUL - 7), b = at(u, 128, n, FOUL - 7);
    const dug = new T.Mesh(new T.BoxGeometry(70, 3.2, 9), K.lam(PAL.glass));
    dug.position.set((a.x + b.x) / 2, 1.6, -(a.y + b.y) / 2); dug.rotation.y = Math.atan2(-(b.y - a.y), b.x - a.x) * -1;
    dug.castShadow = true; grp.add(dug);
  });

  /* outfield wall: real heights (exaggerated 1.5x so they read), with the
     short returns from each foul pole to the stands */
  const HS = 1.5;
  const hAt = t => { const f = clamp(t, 0, 1) * 4, i = Math.min(3, Math.floor(f)), u = f - i; return (WH[i] * (1 - u) + WH[i + 1] * u) * HS; };
  const path = [at(uL, D[0], nL, FOUL), ...wall, at(uR, D[4], nR, FOUL)];
  const hs = path.map((p, i) => i === 0 ? WH[0] * HS : i === path.length - 1 ? WH[4] * HS : hAt((i - 1) / (wall.length - 1)));
  const wb = path.map(p => K.V3(p.x, 0, -p.y)), wt = path.map((p, i) => K.V3(p.x, hs[i], -p.y));
  grp.add(K.strip([wb, wt], K.lam(PAL.wall, { side: T.DoubleSide }), { cast: true }));
  const capIn = path.map((p, i) => { const q = i === 0 || i === path.length - 1 ? p : inward(p, 0.1); return K.V3(q.x, hs[i] + 0.1, -q.y); });
  const capOut = path.map((p, i) => { const r = p.length(), q = i === 0 || i === path.length - 1 ? p : p.clone().multiplyScalar((r + 2.6) / r); return K.V3(q.x, hs[i] + 0.1, -q.y); });
  grp.add(K.strip([capIn, capOut], K.lam(PAL.cap, { emissive: K.lin(PAL.cap), emissiveIntensity: 0.12 }), { cast: false }));
  const ledB = wall.map((p, i) => { const q = inward(p, 0.25); return K.V3(q.x, hAt(i / (wall.length - 1)) - 1.1, -q.y); });
  const ledT = wall.map((p, i) => { const q = inward(p, 0.25); return K.V3(q.x, hAt(i / (wall.length - 1)) - 0.2, -q.y); });
  const led = K.strip([ledB, ledT], K.bas(PAL.cyan2, { transparent: true, opacity: env.night ? 0.95 : 0.75, side: T.DoubleSide }), { receive: false });
  led.renderOrder = 2; grp.add(led);
  /* the three distances that matter, floating over the wall */
  [0, 2, 4].forEach(i => {
    const p = ctrl[i].clone().multiplyScalar(1.0), h = WH[i] * HS;
    const tag = K.textSprite(String(D[i]), 20, { px: 64, weight: 700, color: PAL.chalk, bg: "rgba(37,42,53,.85)", border: "rgba(103,232,249,.45)" });
    tag.position.set(p.x, h + 24, -p.y); grp.add(tag);
  });
  /* foul poles */
  [[D[0], uL], [D[4], uR]].forEach(([d, u]) => {
    const ph = Math.max(WH[0], WH[4]) * HS + 36;
    const pole = new T.Mesh(new T.CylinderGeometry(0.75, 0.9, ph, 10), K.lam(PAL.chalk, { emissive: K.lin(PAL.chalk), emissiveIntensity: 0.25 }));
    pole.position.set(u.x * d, ph / 2, -u.y * d); pole.castShadow = true; pole.userData.noFit = true; grp.add(pole);
    const tip = K.glow(10, PAL.cyan2, 0.9); tip.position.set(u.x * d, ph + 1, -u.y * d); grp.add(tip);
  });

  /* stands: two-deck grandstand around the infield, bleachers beyond the wall */
  const front = standsFront(FOUL, D[4] + 12, D[0] + 12, 26);
  const fn = outwardNormals(T, front, V2(0, 150));
  buildStands(T, K, grp, front, fn,
    [[0, 0], [0, 5], [78, 32], [78, 42], [82, 46], [140, 78], [145, 82]],
    { kinds: ["wall", "seat", "glass", "wall", "seat", "rim"], ribbonAt: [78, 35], night: env.night });
  const cfGap = 9 * Math.PI / 180;
  const sideL = [], sideR = [];
  wall.forEach((p, i) => { const a = Math.atan2(p.x, p.y); if (a < -cfGap) sideL.push({ p, i }); else if (a > cfGap) sideR.push({ p, i }); });
  [sideL, sideR].forEach(side => {
    if (side.length < 3) return;
    const pts = side.map(s => s.p), nn = pts.map(p => p.clone().normalize());
    const h0 = side.map(s => hAt(s.i / (wall.length - 1)));
    const rowsAt = (off, dh) => pts.map((p, i) => K.V3(p.x + nn[i].x * off, h0[i] + dh, -(p.y + nn[i].y * off)));
    const seats = K.lam("#ffffff", { map: seatTex(K), side: T.DoubleSide });
    const r0 = rowsAt(3, 1.5), r1 = rowsAt(62, 24), r2 = rowsAt(66, 27);
    const m = K.strip([r0, r1], seats, { cast: true, uScale: 24 });
    const uv = m.geometry.attributes.uv; for (let k = 0; k < uv.count; k++) uv.setY(k, uv.getY(k) * 20); uv.needsUpdate = true;
    const foot = pts.map((p, i) => K.V3(p.x + nn[i].x * 66, 0, -(p.y + nn[i].y * 66)));
    const fac = K.lam(PAL.facade, { side: T.DoubleSide });
    grp.add(m, K.strip([r1, r2], K.lam(PAL.rim, { side: T.DoubleSide }), { cast: true }), K.strip([r2, foot], fac, { cast: true }));
    [0, pts.length - 1].forEach(i => {
      const prof = [K.V2(3, h0[i] + 1.5), K.V2(62, h0[i] + 24), K.V2(66, h0[i] + 27), K.V2(66, 0), K.V2(3, 0)];
      const geo = new T.ShapeGeometry(new T.Shape(prof)), pa = geo.attributes.position;
      for (let k = 0; k < pa.count; k++) { const sx = pa.getX(k), sy = pa.getY(k); pa.setXYZ(k, pts[i].x + nn[i].x * sx, sy, -(pts[i].y + nn[i].y * sx)); }
      geo.computeVertexNormals(); grp.add(new T.Mesh(geo, fac));
    });
  });
  /* batter's eye in dead center */
  const eyeP = wall.filter(p => Math.abs(Math.atan2(p.x, p.y)) <= cfGap + 0.01);
  if (eyeP.length > 2) {
    const nn = eyeP.map(p => p.clone().normalize());
    const b0 = eyeP.map((p, i) => K.V3(p.x + nn[i].x * 3, 0, -(p.y + nn[i].y * 3)));
    const b1 = eyeP.map((p, i) => K.V3(p.x + nn[i].x * 3, hAt(0.5) + 34, -(p.y + nn[i].y * 3)));
    grp.add(K.strip([b0, b1], K.lam(PAL.glass, { side: T.DoubleSide }), { cast: true }));
  }
  /* light towers ring the park; lit for night games */
  const towers = [0.1, 0.32, 0.68, 0.9].map(f => { const i = Math.round(f * (front.length - 1)); const p = front[i], n = fn[i]; return K.V3(p.x + n.x * 148, 80, -(p.y + n.y * 148)); });
  [sideL, sideR].forEach(side => { if (!side.length) return; const s = side[Math.floor(side.length / 2)]; const n = s.p.clone().normalize(); towers.push(K.V3(s.p.x + n.x * 70, hAt(s.i / (wall.length - 1)) + 27, -(s.p.y + n.y * 70))); });
  towers.forEach(p => lightTower(T, K, grp, p, 46, K.V3(0, 0, -170), env.night));
  if (env.dome) domeOver(T, K, grp);

  return {
    center: K.V3(0, 0, -150),
    grp, cam: { target: K.V3(0, 4, -165), el: 0.6, theta: 0, aim: [-0.9, 0.9] },
    box: { x0: -470, x1: 470, y0: 10, y1: 170, z0: -620, z1: 240 },
    flow: { center: K.V3(0, 0, -185), R: 390, y0: 18, y1: 58 },
    dir: g.dome || !(g.wind > 1) || g.windAngle == null ? null : { x: Math.sin(g.windAngle * Math.PI / 180), z: -Math.cos(g.windAngle * Math.PI / 180) },
    anims: []
  };
}

/* ================================================================ football stadium (NFL + college) */
function buildFootball(T, K, st, spec, env, college) {
  const g = spec.g || {};
  const grp = new T.Group(); st.scene.add(grp);
  const V2 = K.V2;
  /* field: 360 x 160 ft (end zones included), long axis along x */
  const rect = (x0, y0, x1, y1) => [V2(x0, y0), V2(x1, y0), V2(x1, y1), V2(x0, y1)];
  const rrect = (hx, hy, r, n) => {
    const pts = [];
    const cs = [[hx - r, hy - r, 0], [-hx + r, hy - r, Math.PI / 2], [-hx + r, -hy + r, Math.PI], [hx - r, -hy + r, Math.PI * 1.5]];
    cs.forEach(([cx, cy, a0]) => { for (let i = 0; i <= n; i++) { const a = a0 + (Math.PI / 2) * i / n; pts.push(V2(cx + Math.cos(a) * r, cy + Math.sin(a) * r)); } });
    return pts;
  };
  grp.add(K.flat(rrect(236, 150, 70, 14), 0.0, K.lam(PAL.turfDim)));
  const mow = stripeTex(K, PAL.turf, PAL.turf2, { repeat: [1 / 30, 1 / 30] });
  grp.add(K.flat(rect(-150, -80, 150, 80), 0.4, K.lam("#ffffff", { map: mow })));
  const ez = K.lam("#2B4247");
  grp.add(K.flat(rect(150, -80, 180, 80), 0.4, ez), K.flat(rect(-180, -80, -150, 80), 0.4, ez));
  const chalk = K.bas(PAL.chalk, { transparent: true, opacity: 0.8 });
  /* border, goal lines, every 5 yards, hashes, inbound ticks: one merged mesh */
  const q = [];
  const box = (x0, z0, x1, z1) => q.push([x0, z0, x1, z1]);
  box(-186, 80, 186, 86); box(-186, -86, 186, -80); box(180, -86, 186, 86); box(-186, -86, -180, 86);
  for (let yd = -50; yd <= 50; yd += 5) { const x = yd * 3; const w = yd % 50 === 0 && yd !== 0 ? 1.3 : 0.55; box(x - w, -79.5, x + w, 79.5); }
  const hz = college ? 20 : 9.25;
  for (let yd = -49; yd <= 49; yd++) {
    if (yd % 5 === 0) continue;
    const x = yd * 3;
    [hz, -hz].forEach(z => box(x - 0.25, z - 1.2, x + 0.25, z + 1.2));
    [78.2, -78.2].forEach(z => box(x - 0.25, z - 1.2, x + 0.25, z + 1.2));
  }
  const pos = [], idx = [];
  q.forEach(([x0, z0, x1, z1], k) => { const b = k * 4; pos.push(x0, 0.7, z0, x1, 0.7, z0, x1, 0.7, z1, x0, 0.7, z1); idx.push(b, b + 2, b + 1, b, b + 3, b + 2); });
  const lg = new T.BufferGeometry(); lg.setAttribute("position", new T.Float32BufferAttribute(pos, 3)); lg.setIndex(idx);
  const lines = new T.Mesh(lg, chalk); lines.renderOrder = 1; grp.add(lines);
  /* yard numbers, readable from each sideline */
  [10, 20, 30, 40, 50, 40, 30, 20, 10].forEach((n, i) => {
    const x = (i - 4) * 30;
    [1, -1].forEach(side => {
      const pl = K.textPlane(String(n), 17, { px: 120, color: PAL.chalk, opacity: 0.9 });
      const hold = new T.Group(); hold.add(pl); pl.rotation.x = -Math.PI / 2;
      hold.position.set(x, 0.8, side * 47); hold.rotation.y = side > 0 ? 0 : Math.PI; grp.add(hold);
    });
  });
  /* the radar ring at midfield */
  const ring = new T.Mesh(new T.RingGeometry(22, 23.6, 72), K.bas(PAL.cyan2, { transparent: true, opacity: 0.85 }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.9; grp.add(ring);
  /* home team in both end zones */
  const home = String((college ? g.homeAb : g.home) || "").toUpperCase().slice(0, 12);
  if (home) [1, -1].forEach(side => {
    const pl = K.textPlane(home, 20, { px: 120, color: PAL.chalk, opacity: 0.22, letter: 14 });
    const hold = new T.Group(); hold.add(pl); pl.rotation.x = -Math.PI / 2;
    hold.position.set(side * 165, 0.8, 0); hold.rotation.y = side > 0 ? -Math.PI / 2 : Math.PI / 2; grp.add(hold);
  });
  /* goalposts (flagged at the top, like the real ones) */
  const post = K.lam(PAL.chalk, { emissive: K.lin(PAL.chalk), emissiveIntensity: 0.3 });
  const flags = [];
  [1, -1].forEach(e => {
    const xb = e * 187, xe = e * 180;
    const base = new T.Mesh(new T.CylinderGeometry(1.1, 1.1, 11, 12), post); base.position.set(xb, 5.5, 0); base.castShadow = true; grp.add(base);
    const neck = new T.Mesh(new T.TubeGeometry(new T.QuadraticBezierCurve3(K.V3(xb, 10.5, 0), K.V3(xb, 13, 0), K.V3(xe, 13, 0)), 12, 0.8, 8, false), post);
    neck.castShadow = true; grp.add(neck);
    const bar = new T.Mesh(new T.CylinderGeometry(0.7, 0.7, 18.5, 10), post); bar.rotation.x = Math.PI / 2; bar.position.set(xe, 13, 0); bar.castShadow = true; grp.add(bar);
    [9.25, -9.25].forEach(z => {
      const up = new T.Mesh(new T.CylinderGeometry(0.55, 0.65, 38, 10), post); up.position.set(xe, 13 + 19, z); up.castShadow = true; grp.add(up);
      flags.push(K.V3(xe, 51, z));
    });
  });
  /* the bowl */
  const front = rrect(236, 150, 70, 14);
  const fn = outwardNormals(T, front, V2(0, 0));
  front.push(front[0].clone()); fn.push(fn[0].clone());
  buildStands(T, K, grp, front, fn,
    [[0, 0], [0, 6], [72, 32], [72, 41], [76, 45], [128, 72], [132, 76]],
    { kinds: ["wall", "seat", "glass", "wall", "seat", "rim"], ribbonAt: [72, 35], night: env.night, closed: true });
  /* rim lights: towers at the corners, halos along the rim at night */
  [[1, 1], [-1, 1], [1, -1], [-1, -1]].forEach(([sx, sz]) => {
    const p = K.V3(sx * (166 + 206 * 0.7071), 76, -sz * (80 + 206 * 0.7071));
    lightTower(T, K, grp, p, 42, K.V3(0, 0, 0), env.night);
  });
  if (env.dome) domeOver(T, K, grp);
  /* college: no stadium bearings on file, so north is marked on the scope */
  if (college && !env.dome) {
    const n = K.textSprite("N", 26, { px: 80, color: PAL.cyan2, bg: "rgba(37,42,53,.85)", border: "rgba(103,232,249,.5)" });
    n.position.set(-420, 26, 0); grp.add(n);
  }
  let dir = null;
  if (!env.dome && g.wind > 1) {
    if (college && g.windDir != null) { const toward = (g.windDir + 180) * Math.PI / 180; dir = { x: -Math.cos(toward), z: -Math.sin(toward) }; }
    else if (!college && g.ax != null) { const a = g.ax * Math.PI / 180; dir = { x: Math.cos(a), z: -Math.sin(a) }; }
  }
  const anims = [];
  if (dir) flags.forEach(p => {
    const f = makeFlag(T, K, { w: 9, h: 3.2, color: PAL.cyan2, mph: g.wind });
    f.group.position.copy(p); f.group.rotation.y = Math.atan2(-dir.z, dir.x); grp.add(f.group); anims.push((dt, t) => f.update(t));
  });
  return {
    center: K.V3(0, 0, 0),
    grp, cam: { target: K.V3(0, 4, 0), el: 0.62, theta: 0.18, aim: [-0.8, 0.9] },
    box: { x0: -470, x1: 470, y0: 10, y1: 180, z0: -380, z1: 380 },
    flow: { center: K.V3(0, 0, 0), R: 360, y0: 14, y1: 54 },
    dir, anims
  };
}

/* ================================================================ NASCAR track */
/* the racing line for each layout, as a closed loop scaled to its length */
function trackLine(T, kind, mi) {
  const P = { oval: { sr: 2.0 }, flat: { sr: 2.4 }, paperclip: { sr: 3.2 }, bullring: { sr: 1.35 },
    trioval: { sr: 2.1, tri: 0.2 }, quadoval: { sr: 2.2, quad: 0.16 }, dshape: { sr: 1.8, dee: 0.34 },
    egg: { sr: 1.9, egg: 0.78 }, dogleg: { sr: 1.9, egg: 0.86, dog: 0.15 } }[kind] || { sr: 2.0 };
  const r = 1, a = P.sr * r / 2, per = 4 * a + 2 * Math.PI * r, M = 900;
  /* the base stadium shape sampled evenly by arc length (straights + half
     circles), then bent into the layout; no spline, so no overshoot */
  const at = d => {
    d = ((d % per) + per) % per;
    if (d < a) return [d, -r];
    d -= a; if (d < Math.PI * r) { const t = -Math.PI / 2 + d / r; return [a + Math.cos(t) * r, Math.sin(t) * r]; }
    d -= Math.PI * r; if (d < 2 * a) return [a - d, r];
    d -= 2 * a; if (d < Math.PI * r) { const t = Math.PI / 2 + d / r; return [-a + Math.cos(t) * r, Math.sin(t) * r]; }
    d -= Math.PI * r; return [-a + d, -r];
  };
  const raw = [];
  for (let i = 0; i < M; i++) {
    let [x, y] = at(per * i / M);
    if (P.egg && x > 0) y *= 1 - (1 - P.egg) * smooth(0, a + r, x);
    const onFront = y < 0 && Math.abs(x) <= a, onBack = y > 0 && Math.abs(x) <= a;
    if (onFront && P.tri) y -= P.tri * r * Math.pow(Math.max(0, 1 - Math.abs(x) / a), 1.15);
    if (onFront && P.quad) y -= P.quad * r * (1 - smooth(0.32 * a, 0.92 * a, Math.abs(x)));
    if (onFront && P.dee) y -= P.dee * r * (1 - (x / a) * (x / a));
    if (onBack && P.dog) y += P.dog * r * Math.max(0, 1 - Math.abs(x + 0.2 * a) / (0.6 * a));
    raw.push(new T.Vector2(x, y));
  }
  /* even spacing again after bending */
  const cl = [0]; for (let i = 1; i <= M; i++) cl.push(cl[i - 1] + raw[i % M].distanceTo(raw[i - 1]));
  const line = [], NL = 360;
  for (let i = 0, k = 0; i < NL; i++) {
    const d = cl[M] * i / NL; while (cl[k + 1] < d) k++;
    const f = (d - cl[k]) / (cl[k + 1] - cl[k]); line.push(raw[k].clone().lerp(raw[(k + 1) % M], f));
  }
  /* drawn to a display size (a long track still reads longer than a short one),
     with the racing surface exaggerated so it reads at this scale */
  let x0 = 1e9, x1 = -1e9; line.forEach(p => { x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x); });
  const want = lerp(700, 1100, clamp(((mi || 1.5) - 0.5) / 2, 0, 1));
  const k = want / (x1 - x0);
  return line.map(p => p.multiplyScalar(k));
}
function buildNASCAR(T, K, st, spec, env) {
  const rc = spec.g || {}, sh = rc.shape || { kind: "oval", mi: 1.5, bank: 18 };
  const grp = new T.Group(); st.scene.add(grp);
  const V2 = K.V2, line = trackLine(T, sh.kind, sh.mi), n = line.length;
  const W = 58, APRON = 22, DS = T.DoubleSide;
  /* the front stretch is the stretch at the bottom of the loop (y < 0) */
  const tan = [], nrm = [], kap = [];
  for (let i = 0; i < n; i++) {
    const a = line[(i - 1 + n) % n], b = line[(i + 1) % n];
    const t = V2(b.x - a.x, b.y - a.y).normalize(); tan.push(t); nrm.push(V2(-t.y, t.x));
  }
  for (let i = 0; i < n; i++) { const t0 = tan[(i - 1 + n) % n], t1 = tan[(i + 1) % n]; kap.push(Math.abs(Math.atan2(t0.x * t1.y - t0.y * t1.x, t0.dot(t1)))); }
  const km = Math.max(...kap) || 1;
  const bankDeg = sh.bank || 12, bankS = Math.min(bankDeg * 0.3, 9);
  const bank = kap.map((k, i) => { let sm = 0; for (let j = -14; j <= 14; j++) sm += kap[(i + j + n) % n]; return lerp(bankS, bankDeg, smooth(0.1, 0.75, sm / 29 / km)); });
  /* is +normal the inside of the loop? (the loop runs counter-clockwise) */
  let area = 0; for (let i = 0; i < n; i++) { const p = line[i], q = line[(i + 1) % n]; area += p.x * q.y - q.x * p.y; }
  const IN = area > 0 ? 1 : -1;
  const P3 = (p, h) => K.V3(p.x, h, -p.y);
  const edge = (i, off) => V2(line[i].x + nrm[i].x * off * IN, line[i].y + nrm[i].y * off * IN);
  const inner = [], outer = [], apronIn = [], hOut = [];
  for (let i = 0; i <= n; i++) {
    const j = i % n, h = W * Math.tan(bank[j] * Math.PI / 180) * 1.15;
    inner.push(P3(edge(j, W / 2), 0.6)); outer.push(P3(edge(j, -W / 2), h + 0.6)); apronIn.push(P3(edge(j, W / 2 + APRON), 0.4)); hOut.push(h);
  }
  const hot = (rc.temp || 0) >= 88;
  grp.add(K.strip([inner, outer], K.lam(hot ? PAL.asphaltHot : PAL.asphalt, { side: DS }), { receive: true }));
  grp.add(K.strip([apronIn, inner], K.lam(PAL.apron, { side: DS }), { receive: true }));
  /* lane lines: the white line at the bottom of the track, a faint racing groove */
  const ribbon = (off0, off1, lift, mat) => {
    const A = [], B = [];
    for (let i = 0; i <= n; i++) { const j = i % n, f0 = (W / 2 - off0) / W, f1 = (W / 2 - off1) / W; A.push(P3(edge(j, off0), 0.6 + hOut[j] * f0 + lift)); B.push(P3(edge(j, off1), 0.6 + hOut[j] * f1 + lift)); }
    return K.strip([A, B], mat, { receive: false });
  };
  grp.add(ribbon(W / 2 - 0.4, W / 2 - 2.2, 0.15, K.bas(PAL.chalk, { transparent: true, opacity: 0.8, side: DS })));
  grp.add(ribbon(4, -8, 0.12, K.bas("#1E2129", { transparent: true, opacity: 0.35, side: DS })));
  /* infield */
  const infield = []; for (let i = 0; i < n; i += 2) infield.push(edge(i, W / 2 + APRON - 0.5));
  grp.add(K.flat(infield, 0.2, K.lam("#ffffff", { map: stripeTex(K, PAL.turfDim, "#31494F", { repeat: [1 / 44, 1 / 44] }) })));
  /* pit road + pit wall + stalls along the front stretch, garages behind */
  let fi = 0; line.forEach((p, i) => { if (p.y < line[fi].y) fi = i; });
  const span = Math.round(n * 0.1), pr0 = [], pr1 = [], pw0 = [], pw1 = [];
  for (let i = -span; i <= span; i++) {
    const j = (fi + i + n) % n;
    pr0.push(P3(edge(j, W / 2 + APRON + 10), 0.45)); pr1.push(P3(edge(j, W / 2 + APRON + 40), 0.45));
    pw0.push(P3(edge(j, W / 2 + APRON + 8), 0.45)); pw1.push(P3(edge(j, W / 2 + APRON + 8), 3.6));
  }
  grp.add(K.strip([pr0, pr1], K.lam(PAL.asphalt, { side: DS }), { receive: true }));
  grp.add(K.strip([pw0, pw1], K.lam(PAL.cap, { side: DS }), { cast: true }));
  const stall = K.bas(PAL.chalk, { transparent: true, opacity: 0.35 });
  for (let i = -span + 2; i <= span - 2; i += 2) { const j = (fi + i + n) % n; grp.add(K.band([edge(j, W / 2 + APRON + 22), edge(j, W / 2 + APRON + 39)], 0.5, 0.6, stall)); }
  const gar = K.lam(PAL.stand, { side: DS }), garRoof = K.lam(PAL.rim);
  [-0.55, 0, 0.55].forEach(f => {
    const j = (fi + Math.round(f * span) + n) % n, c = edge(j, W / 2 + APRON + 78);
    const g1 = new T.Mesh(new T.BoxGeometry(span * 1.3, 9, 24), gar); g1.position.set(c.x, 4.5, -c.y); g1.rotation.y = Math.atan2(tan[j].y, tan[j].x); g1.castShadow = g1.receiveShadow = true; grp.add(g1);
    const r1 = new T.Mesh(new T.BoxGeometry(span * 1.3 + 2, 1, 26), garRoof); r1.position.set(c.x, 9.5, -c.y); r1.rotation.y = g1.rotation.y; grp.add(r1);
  });
  /* SAFER wall + catch fence around the outside */
  const wallB = [], wallT = [], fenceT = [];
  for (let i = 0; i <= n; i++) { const j = i % n, q = edge(j, -W / 2 - 0.8); wallB.push(P3(q, hOut[j] + 0.6)); wallT.push(P3(q, hOut[j] + 4.4)); fenceT.push(P3(q, hOut[j] + 20)); }
  const wallOut = []; for (let i = 0; i <= n; i++) { const j = i % n; wallOut.push(P3(edge(j, -W / 2 - 3), 0)); }
  grp.add(K.strip([wallB, wallT], K.lam(PAL.cap, { side: DS }), { cast: true }));
  grp.add(K.strip([wallT, wallOut], K.lam(PAL.facade, { side: DS }), { cast: true }));
  const meshTex = K.pattern(64, 64, (c, w, h) => { c.clearRect(0, 0, w, h); c.strokeStyle = "rgba(210,228,245,.6)"; c.lineWidth = 2; c.strokeRect(0, 0, w, h); c.beginPath(); c.moveTo(0, 0); c.lineTo(w, h); c.stroke(); });
  const fence = K.strip([wallT, fenceT], new T.MeshBasicMaterial({ map: meshTex, transparent: true, opacity: 0.3, side: DS, depthWrite: false, toneMapped: false, color: K.lin("#A9BCD3") }), { uScale: 9, receive: false });
  const fuv = fence.geometry.attributes.uv; for (let k = 0; k < fuv.count; k++) fuv.setY(k, fuv.getY(k) * 2); fuv.needsUpdate = true;
  fence.renderOrder = 3; grp.add(fence);
  /* start/finish checkers + flag stand at the middle of the front stretch */
  const chk = K.pattern(64, 16, (c, w, h) => { for (let x = 0; x < w; x += 8) for (let y = 0; y < h; y += 8) { c.fillStyle = ((x + y) / 8) % 2 ? PAL.ink : PAL.chalk; c.fillRect(x, y, 8, 8); } });
  chk.wrapS = chk.wrapT = T.ClampToEdgeWrapping;
  const sf0 = [], sf1 = [];
  for (let sgi = 0; sgi <= 8; sgi++) {
    const off = W / 2 - W * sgi / 8, hh = (W / 2 - off) / W * hOut[fi];
    const base = edge(fi, off);
    sf0.push(P3(V2(base.x - tan[fi].x * 5, base.y - tan[fi].y * 5), hh + 0.8)); sf1.push(P3(V2(base.x + tan[fi].x * 5, base.y + tan[fi].y * 5), hh + 0.8));
  }
  grp.add(K.strip([sf0, sf1], new T.MeshBasicMaterial({ map: chk, toneMapped: false, side: DS }), { receive: false }));
  const standBase = edge(fi, -W / 2 - 4);
  const stand = new T.Group();
  [-6, 6].forEach(d => { const leg = new T.Mesh(new T.BoxGeometry(1.2, 30, 1.2), K.lam(PAL.rim)); leg.position.set(d, 15, 0); leg.castShadow = true; stand.add(leg); });
  const booth = new T.Mesh(new T.BoxGeometry(16, 8, 9), K.lam(PAL.stand2)); booth.position.set(0, 34, 0); booth.castShadow = true; stand.add(booth);
  const win = new T.Mesh(new T.PlaneGeometry(13, 3.4), K.bas(PAL.cyan2, { transparent: true, opacity: 0.7 })); win.position.set(0, 35, 4.6); stand.add(win);
  const ang = Math.atan2(tan[fi].y, tan[fi].x);
  stand.position.set(standBase.x, hOut[fi], -standBase.y); stand.rotation.y = ang; grp.add(stand);
  const anims = [];
  const flagTex = K.pattern(64, 40, (c, w, h) => { for (let x = 0; x < w; x += 8) for (let y = 0; y < h; y += 8) { c.fillStyle = ((x + y) / 8) % 2 ? "#1d212a" : "#f2f5fa"; c.fillRect(x, y, 8, 8); } });
  const fl = makeFlag(T, K, { w: 12, h: 7.5, map: flagTex, mph: rc.wind || 0 });
  fl.group.position.set(standBase.x, hOut[fi] + 50, -standBase.y); fl.group.rotation.y = ang;
  const staff = new T.Mesh(new T.CylinderGeometry(0.3, 0.3, 12, 6), K.lam(PAL.chalk)); staff.position.set(standBase.x, hOut[fi] + 44, -standBase.y); grp.add(staff, fl.group);
  anims.push((dt, t) => fl.update(t));
  /* grandstands along the front stretch and into both turns */
  const gi = [], gn = [], gspan = Math.round(n * 0.17);
  for (let i = -gspan; i <= gspan; i++) { const j = (fi + i + n) % n; gi.push(edge(j, -W / 2 - 16)); gn.push(V2(-nrm[j].x * IN, -nrm[j].y * IN)); }
  const gh = Math.max(4, hOut[fi] * 0.8);
  buildStands(T, K, grp, gi, gn, [[0, 0], [0, gh + 6], [58, gh + 34], [58, gh + 42], [62, gh + 46], [108, gh + 74], [112, gh + 78]],
    { kinds: ["wall", "seat", "glass", "wall", "seat", "rim"], ribbonAt: [58, gh + 36], night: env.night });
  /* the field: a pack of cars on the racing line, leaning into the banking */
  const cum = [0]; for (let i = 1; i <= n; i++) cum.push(cum[i - 1] + line[i % n].distanceTo(line[i - 1]));
  const lap = cum[n];
  const bodyG = new T.BoxGeometry(15, 3.4, 6.4); bodyG.translate(0, 2.3, 0);
  const cabG = new T.BoxGeometry(6.6, 2.6, 5.2); cabG.translate(-1.4, 5.2, 0);
  const tints = [PAL.chalk, PAL.cool, PAL.cap, PAL.dim, PAL.chalk, PAL.cool];
  const cabM = K.lam(PAL.ink);
  const cars = [];
  for (let i = 0; i < 14; i++) {
    const car = new T.Group();
    const b = new T.Mesh(bodyG, i === 0 ? K.lam(PAL.cyan2, { emissive: K.lin(PAL.cyan), emissiveIntensity: 0.35 }) : K.lam(tints[i % tints.length]));
    const cb = new T.Mesh(cabG, cabM);
    b.castShadow = true; b.userData.noFit = cb.userData.noFit = true; car.add(b, cb); grp.add(car);
    cars.push({ g: car, s: lap * 0.02 - i * (24 + (i % 3) * 5), lane: (i % 2 ? 1 : -1) * (i < 2 ? 0 : 7) });
  }
  const bx = new T.Vector3(), by = new T.Vector3(), bz = new T.Vector3(), mm = new T.Matrix4();
  const placeCar = c => {
    let sv = ((c.s % lap) + lap) % lap, i = 0;
    let lo = 0, hi = n; while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (cum[mid] <= sv) lo = mid; else hi = mid; } i = lo;
    const f = (sv - cum[i]) / Math.max(1e-6, cum[i + 1] - cum[i]), j = i % n, k = (i + 1) % n;
    const off = -2 + c.lane, P = edge(j, off), Q = edge(k, off);
    const x = lerp(P.x, Q.x, f), y = lerp(P.y, Q.y, f);
    const hh = 0.6 + lerp(hOut[j], hOut[k], f) * (W / 2 - off) / W;
    const b = lerp(bank[j], bank[k], f) * Math.PI / 180;
    bx.set(Q.x - P.x, 0, -(Q.y - P.y)).normalize();
    const inw = K.V3(nrm[j].x * IN, 0, -nrm[j].y * IN);
    by.set(0, Math.cos(b), 0).addScaledVector(inw, Math.sin(b)).normalize();
    bz.crossVectors(bx, by).normalize(); by.crossVectors(bz, bx);
    mm.makeBasis(bx, by, bz); c.g.quaternion.setFromRotationMatrix(mm); c.g.position.set(x, hh, -y);
  };
  cars.forEach(placeCar);
  const lapSec = 13 + (sh.mi || 1.5) * 1.5;
  anims.push(dt => { cars.forEach(c => { c.s += lap / lapSec * dt; placeCar(c); }); });
  /* light poles for night races */
  if (env.night) for (let i = 0; i < n; i += 30) { const q = edge(i, -W / 2 - 34); lightTower(T, K, grp, P3(q, 0), 70, K.V3(0, 0, 0), true); }
  let x0 = 1e9, x1 = -1e9, z0 = 1e9, z1 = -1e9;
  line.forEach(p => { x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x); z0 = Math.min(z0, -p.y); z1 = Math.max(z1, -p.y); });
  const ext = Math.max(x1 - x0, z1 - z0) / 2, S = ext + 200;
  const c = K.V3((x0 + x1) / 2, 0, (z0 + z1) / 2);
  return {
    center: c, S,
    grp, cam: { target: K.V3(c.x, 0, c.z), el: 0.56, theta: Math.PI + 0.16, sway: 0.3 },
    box: null, dir: null, anims
  };
}

/* ================================================================ golf: the signature hole */
/* drawn from what the schedule says about the hole (par, length, dogleg,
   water, desert) — an illustration of the hole, not a survey of it */
function rng(seed) { let t = seed >>> 0; return () => { t += 0x6D2B79F5; let r = Math.imul(t ^ (t >>> 15), 1 | t); r ^= r + Math.imul(r ^ (r >>> 7), 61 | r); return ((r ^ (r >>> 14)) >>> 0) / 4294967296; }; }
function buildPGA(T, K, st, spec, env) {
  const ev = spec.event || {}, hole = ev.hole || { n: 18, par: 4, yds: 440, dl: 0, water: "none" }, r = spec.g || {};
  const grp = new T.Group(); st.scene.add(grp);
  const V2 = K.V2, DS = T.DoubleSide;
  const par = hole.par || 4, yds = hole.yds || (par === 3 ? 180 : par === 5 ? 560 : 440), L = yds * 3;
  const dl = hole.dl || 0, water = hole.water || "none", desert = !!hole.desert;
  const R = rng((hole.n || 1) * 1009 + yds * 7 + (dl + 2) * 131);
  const rnd = (a, b) => a + R() * (b - a);
  /* routing: straight off the tee, turning at the elbow on a dogleg */
  const bendAt = par >= 4 && dl ? (par === 5 ? 0.6 : 0.55) : 1, bend = dl * 0.42;
  const elbow = V2(0, L * bendAt), tail = L * (1 - bendAt);
  const G = V2(elbow.x + Math.sin(bend) * tail, elbow.y + Math.cos(bend) * tail);
  const pathAt = t => { if (t <= bendAt) return V2(0, L * t); const u = (t - bendAt) * L; return V2(elbow.x + Math.sin(bend) * u, elbow.y + Math.cos(bend) * u); };
  const dirAt = t => t <= bendAt ? V2(0, 1) : V2(Math.sin(bend), Math.cos(bend));
  const side = (t, off) => { const p = pathAt(t), d = dirAt(t); return V2(p.x + d.y * off, p.y - d.x * off); };
  const corridor = (w0, w1, t0, t1, wig, ph) => {
    const Lp = [], Rp = [], N = 70;
    for (let i = 0; i <= N; i++) {
      const t = lerp(t0, t1, i / N), u = i / N, end = Math.sin(Math.PI * u);
      const w = lerp(w0, w1, u) * (0.35 + 0.65 * Math.pow(end, 0.35));
      Lp.push(side(t, -(w + Math.sin(t * 17 + ph) * wig))); Rp.push(side(t, w + Math.sin(t * 13 + ph * 2) * wig));
    }
    return [...Lp, ...Rp.reverse()];
  };
  const ln = L / 1300;
  /* rough, then first cut, then the fairway */
  grp.add(K.flat(corridor(210, 240, -0.2, 1.16, 14, 1), 0.0, K.lam(desert ? PAL.waste : PAL.rough)));
  grp.add(K.flat(corridor(128, 140, -0.12, 1.1, 9, 2), 0.15, K.lam(desert ? "#46505A" : PAL.turfDim)));
  const mow = stripeTex(K, PAL.turf, PAL.turf2, { repeat: [1 / 34, 1 / 34], rotation: -bend * 0.5 });
  if (par >= 4) grp.add(K.flat(corridor(44, 52, 0.27, 0.95, 6, 3), 0.35, K.lam("#ffffff", { map: mow })));
  else grp.add(K.flat(corridor(36, 42, 0.8, 0.96, 3, 3), 0.35, K.lam("#ffffff", { map: mow })));
  /* tee box and markers */
  const teeY = 2.4;
  const tee = new T.Mesh(new T.BoxGeometry(34, teeY, 62), K.lam(PAL.turf2)); tee.position.set(0, teeY / 2, 4); tee.receiveShadow = tee.castShadow = true; grp.add(tee);
  [-9, 9].forEach(x => { const m = new T.Mesh(new T.SphereGeometry(1.3, 12, 8), K.lam(PAL.chalk)); m.position.set(x, teeY + 1.1, -16); grp.add(m); });
  /* green: fringe collar, a gently domed putting surface, the pin toward the back */
  const gd = dirAt(1), ga = Math.atan2(gd.x, gd.y);
  const fringe = new T.Mesh(new T.CircleGeometry(1, 64), K.lam(PAL.turf2)); fringe.rotation.x = -Math.PI / 2; fringe.rotation.z = -ga; fringe.scale.set(62, 50, 1); fringe.position.set(G.x, 0.5, -G.y); fringe.receiveShadow = true; grp.add(fringe);
  const green = new T.Mesh(new T.SphereGeometry(1, 48, 12, 0, Math.PI * 2, 0, Math.PI / 2), K.lam(PAL.green)); green.scale.set(52, 2.6, 41); green.position.set(G.x, 0.4, -G.y); green.rotation.y = ga; green.receiveShadow = true; grp.add(green);
  const pin = V2(G.x + gd.x * 14 - gd.y * 9, G.y + gd.y * 14 + gd.x * 9);
  const cup = new T.Mesh(new T.CircleGeometry(1.5, 16), K.bas(PAL.ink)); cup.rotation.x = -Math.PI / 2; cup.position.set(pin.x, 2.75, -pin.y); grp.add(cup);
  const stickH = 30;
  const stick = new T.Mesh(new T.CylinderGeometry(0.45, 0.45, stickH, 8), K.lam(PAL.chalk)); stick.position.set(pin.x, 2.6 + stickH / 2, -pin.y); stick.castShadow = true; grp.add(stick);
  const flag = makeFlag(T, K, { w: 11, h: 7, color: PAL.cyan2, mph: r.wind || 0 });
  flag.group.position.set(pin.x, 2.6 + stickH, -pin.y); flag.group.rotation.y = -Math.PI / 4; grp.add(flag.group);
  const pinGlow = K.glow(22, PAL.cyan2, 0.6); pinGlow.position.set(pin.x, 2.6 + stickH - 3, -pin.y); grp.add(pinGlow);
  const ringG = new T.Mesh(new T.RingGeometry(7, 8.2, 48), K.bas(PAL.cyan2, { transparent: true, opacity: 0.7 })); ringG.rotation.x = -Math.PI / 2; ringG.position.set(pin.x, 2.8, -pin.y); grp.add(ringG);
  /* the line of play, tee to pin, in dots */
  const route = [V2(0, -10), elbow, pin], dotG = [];
  for (let k = 0; k < route.length - 1; k++) {
    const A = route[k], B = route[k + 1], len = A.distanceTo(B), nd = Math.floor(len / 22);
    for (let i = 0; i < nd; i++) { const f = i / nd; if (k === route.length - 2 && len * (1 - f) < 40) continue; dotG.push(V2(lerp(A.x, B.x, f), lerp(A.y, B.y, f))); }
  }
  const dotGeo = new T.CircleGeometry(1.6, 10); dotGeo.rotateX(-Math.PI / 2);
  const dots = new T.InstancedMesh(dotGeo, K.bas(PAL.cyan2, { transparent: true, opacity: 0.55 }), dotG.length);
  const m4 = new T.Matrix4();
  dotG.forEach((p, i) => { m4.makeTranslation(p.x, (Math.hypot(p.x, p.y) < 36 ? teeY : 0) + 1.2, -p.y); dots.setMatrixAt(i, m4); });
  dots.renderOrder = 2; grp.add(dots);
  /* yardages to the middle of the green, like the sprinkler heads */
  [100, 150, 200, 250].forEach(yd => {
    if (yd * 3 > L - 90) return;
    let t = 1, need = yd * 3, acc = 0; const step = 1 / 400;
    for (let tt = 1; tt > 0; tt -= step) { acc += pathAt(tt).distanceTo(pathAt(tt - step)); if (acc >= need) { t = tt; break; } }
    const at = pathAt(t), tag = K.textSprite(String(yd), 15, { px: 56, weight: 700, color: PAL.chalk, bg: "rgba(37,42,53,.8)", border: "rgba(142,151,173,.5)" });
    tag.position.set(at.x, 16, -at.y); grp.add(tag);
  });
  /* sand */
  const blob = (c, rx, ry, rot, seed) => { const pts = []; for (let i = 0; i < 30; i++) { const a = i / 30 * Math.PI * 2, rr = 1 + 0.16 * Math.sin(a * 2 + seed) + 0.09 * Math.sin(a * 3 + seed * 2); const x = Math.cos(a) * rx * rr, y = Math.sin(a) * ry * rr; pts.push(V2(c.x + x * Math.cos(rot) - y * Math.sin(rot), c.y + x * Math.sin(rot) + y * Math.cos(rot))); } return pts; };
  const sandM = K.lam(PAL.sand), lipM = K.lam("#6C6A7C");
  const bunk = [];
  const gside = (lat, fwd) => V2(G.x + gd.y * lat + gd.x * fwd, G.y - gd.x * lat + gd.y * fwd);
  if (water !== "left") bunk.push([gside(-66, -6), 24, 13, -ga + 0.5, 1]);
  if (water !== "right") bunk.push([gside(64, 14), 22, 12, -ga - 0.5, 2.3]);
  if (water !== "front" && par === 3) bunk.push([gside(-8, -64), 28, 10, -ga + 1.57, 3.1]);
  if (par >= 4) { bunk.push([side(0.6, (dl || 1) * -70), 30, 14, -ga, 4.2]); if (par === 5) bunk.push([side(0.82, (dl || -1) * 62), 26, 12, -ga + 0.3, 5.3]); }
  if (desert) bunk.push([gside(0, 70), 36, 12, -ga + 1.57, 6.1]);
  bunk.forEach(([c, rx, ry, rot, seed]) => { grp.add(K.flat(blob(c, rx + 3, ry + 3, rot, seed), 0.55, lipM)); grp.add(K.flat(blob(c, rx, ry, rot, seed), 0.7, sandM)); });
  /* water, with a slow shimmer */
  const anims = [];
  if (water !== "none") {
    let pond;
    if (water === "front") { const c = gside(0, par === 3 ? -120 : -112); pond = blob(c, par === 3 ? 150 : 120, par === 3 ? 58 : 46, -ga + Math.PI / 2 * 0 + 0, 0.7); pond = blob(c, par === 3 ? 140 : 110, par === 3 ? 58 : 46, Math.PI / 2 - ga + Math.PI / 2, 0.7); }
    else { const sgn = water === "left" ? -1 : 1, t0 = par === 3 ? 0.5 : 0.62; const c = side((t0 + 1.03) / 2, sgn * 112); pond = blob(c, L * (1.03 - t0) / 2 + 36, 58, Math.PI / 2 - ga, 1.9); }
    grp.add(K.flat(pond.map(p => p), 0.45, K.lam("#2C4A62")));
    const inner = pond.map((p, i, arr) => { let cx = 0, cy = 0; arr.forEach(q => { cx += q.x; cy += q.y; }); cx /= arr.length; cy /= arr.length; return V2(cx + (p.x - cx) * 0.93, cy + (p.y - cy) * 0.93); });
    grp.add(K.flat(inner, 0.55, new T.MeshStandardMaterial({ color: K.lin(PAL.water), roughness: 0.3, metalness: 0.2 })));
    const rip = K.pattern(256, 256, (c, w, h) => { c.clearRect(0, 0, w, h); const q = rng(7); for (let i = 0; i < 44; i++) { c.strokeStyle = "rgba(103,232,249," + (0.06 + q() * 0.12).toFixed(3) + ")"; c.lineWidth = 1.5; const y = q() * h, x = q() * w; c.beginPath(); c.moveTo(x, y); c.lineTo(x + 18 + q() * 36, y); c.stroke(); } }, { repeat: [1 / 70, 1 / 70] });
    grp.add(K.flat(inner, 0.8, new T.MeshBasicMaterial({ map: rip, transparent: true, depthWrite: false, toneMapped: false, blending: T.AdditiveBlending })));
    anims.push(dt => { rip.offset.x += dt * 0.01; rip.offset.y += dt * 0.004; });
  }
  /* trees (low-poly), or rocks and scrub on desert holes */
  const spots = [];
  for (let t = -0.16; t <= 1.14; t += 0.022) [-1, 1].forEach(sd => {
    if (R() < (desert ? 0.72 : 0.18)) return;
    const off = sd * rnd(150, 235), p = side(t + rnd(-0.01, 0.01), off);
    if (water !== "none" && p.distanceTo(G) < 200 && ((water === "left" && sd < 0) || (water === "right" && sd > 0))) return;
    if (p.distanceTo(V2(0, 0)) < 60 || p.distanceTo(G) < 95) return;
    spots.push([p, R()]);
  });
  const flatM = hex => new T.MeshPhongMaterial({ color: K.lin(hex), flatShading: true, shininess: 0, specular: 0x000000 });
  const cone = new T.ConeGeometry(1, 1, 7); cone.translate(0, 0.5, 0);
  const ball = new T.IcosahedronGeometry(1, 0); ball.translate(0, 1, 0);
  const rock = new T.DodecahedronGeometry(1, 0);
  const sets = desert ? [[rock, flatM("#5E5A6A"), 0.45], [ball, flatM("#3B4A4A"), 1]] : [[cone, flatM(PAL.tree), 0.5], [ball, flatM("#2E4549"), 1]];
  let lo = 0;
  sets.forEach(([geo, mat, upTo]) => {
    const mine = spots.filter(([, k]) => k >= lo && k < upTo); lo = upTo;
    if (!mine.length) return;
    const im = new T.InstancedMesh(geo, mat, mine.length), q = new T.Quaternion(), e = new T.Euler();
    mine.forEach(([p], i) => {
      let sc;
      if (geo === cone) sc = K.V3(rnd(11, 16), rnd(40, 62), 0);
      else if (geo === ball) sc = desert ? K.V3(rnd(5, 8), rnd(3, 5), 0) : K.V3(rnd(14, 20), rnd(15, 22), 0);
      else sc = K.V3(rnd(5, 10), rnd(3, 6), 0);
      sc.z = sc.x * rnd(0.85, 1.15);
      e.set(0, rnd(0, 6.28), 0); q.setFromEuler(e);
      m4.compose(K.V3(p.x, geo === rock ? sc.y * 0.4 : 0, -p.y), q, sc); im.setMatrixAt(i, m4);
    });
    im.castShadow = true; im.receiveShadow = true; grp.add(im);
    if (geo === ball && !desert) {
      const trunks = new T.InstancedMesh(new T.CylinderGeometry(0.12, 0.16, 1, 5).translate(0, 0.5, 0), flatM("#3A3F4A"), mine.length);
      mine.forEach(([p], i) => { m4.compose(K.V3(p.x, 0, -p.y), new T.Quaternion(), K.V3(10, 12, 10)); trunks.setMatrixAt(i, m4); });
      grp.add(trunks);
    }
  });
  /* the hole card, over the tee */
  const card = K.textSprite("No. " + (hole.n || "") + " · Par " + par + " · " + yds + " yds", 22, { px: 60, weight: 600, color: PAL.chalk, bg: "rgba(37,42,53,.85)", border: "rgba(103,232,249,.45)" });
  card.position.set(0, 40, 26); grp.add(card);
  let x0 = Math.min(0, G.x, elbow.x) - 240, x1 = Math.max(0, G.x, elbow.x) + 240, y0 = -60, y1 = G.y + 120;
  const cx = (x0 + x1) / 2, cz = -(y0 + y1) / 2, ext = Math.max(x1 - x0, y1 - y0) / 2;
  return {
    center: K.V3(cx, 0, cz), S: ext + 160,
    grp, cam: { target: K.V3(cx, 0, cz), el: 0.66, theta: 0.2, wide: Math.PI / 2, sway: 0.22 },
    box: null, dir: null, anims: anims.concat([(dt, t) => flag.update(t)])
  };
}

/* ================================================================ mount */
const BUILD = { mlb: buildMLB, nfl: (T, K, st, sp, env) => buildFootball(T, K, st, sp, env, false), cfb: (T, K, st, sp, env) => buildFootball(T, K, st, sp, env, true), nascar: buildNASCAR, pga: buildPGA };

function envFor(spec) {
  const g = spec.g || {};
  let hour = null;
  if (spec.sport === "mlb") hour = typeof g.sortTime === "number" ? Math.floor(g.sortTime / 100) + (g.sortTime % 100) / 60 : hourOf(g.time);
  else if (spec.sport === "nfl") { const m = /(\d{2}):(\d{2})$/.exec(String(g.sortTime || "")); hour = m ? +m[1] + (+m[2]) / 60 : hourOf(g.time); }
  else if (spec.sport === "cfb") hour = g.kickHour != null ? +g.kickHour : hourOf(g.time);
  else if (spec.sport === "nascar") hour = hourOf(g.time);
  const S = { mlb: 480, nfl: 400, cfb: 400, nascar: 750, pga: 900 }[spec.sport] || 500;
  return {
    night: hour != null && hour >= 18.5 && spec.sport !== "pga",
    dome: !!g.dome, sky: g.sky || "", fog: /fog|marine|mist/i.test(g.sky || ""), S,
    center: new window.THREE.Vector3(0, 0, spec.sport === "mlb" ? -150 : 0)
  };
}

function mount(canvas, spec) {
  const T = window.THREE;
  if (!T || !canvas || !spec || !BUILD[spec.sport]) return null;
  const K = kit(T), env = envFor(spec);
  /* the venue decides its own size; build it into a throwaway group first when
     it needs to (tracks and holes vary with the week) */
  let pre = null;
  if (spec.sport === "nascar" || spec.sport === "pga") {
    const probe = { scene: new T.Scene() };
    const r = BUILD[spec.sport](T, K, probe, spec, env);
    env.S = r.S; env.center = r.center;
    probe.scene.traverse(o => { if (o.geometry) o.geometry.dispose(); });
    pre = r;
  }
  const st = makeStage(T, K, canvas, env);
  if (!st) return null;
  const v = BUILD[spec.sport](T, K, st, spec, env);
  const scene = st.scene, g = spec.g || {};
  const anims = (v.anims || []).slice();
  if (v.dir && v.flow) anims.push(windLines(T, K, scene, Object.assign({ dir: v.dir, mph: g.wind || 0, S: env.S }, v.flow)));
  if (!env.dome && (g.rain || 0) >= 40) {
    const b = v.box || { x0: env.center.x - env.S, x1: env.center.x + env.S, y0: 0, y1: env.S * 0.3, z0: env.center.z - env.S, z1: env.center.z + env.S };
    anims.push(rainFall(T, K, scene, { pct: g.rain, dir: v.dir, mph: g.wind || 0, box: b, S: env.S }));
  }
  if (st.sweep) anims.push(dt => { st.sweep.rotation.z -= dt * 0.35; });
  /* turn the opening view so the wind crosses the screen instead of running
     toward the camera, staying near the venue's natural angle */
  if (v.dir && v.cam.aim) {
    let best = v.cam.theta, bs = -1;
    for (let th = v.cam.aim[0]; th <= v.cam.aim[1] + 1e-6; th += 0.05) {
      const sc = Math.abs(v.dir.x * Math.cos(th) - v.dir.z * Math.sin(th)) - 0.1 * Math.abs(th - v.cam.theta);
      if (sc > bs) { bs = sc; best = th; }
    }
    v.cam.theta = best;
  }
  const W = canvas.clientWidth || 800, H = canvas.clientHeight || 400;
  if (v.cam.wide != null && W / H > 1.5) v.cam.theta = v.cam.wide;
  const cam = new T.PerspectiveCamera(34, W / H, 2, env.S * 9);
  /* frame the venue from its own geometry: the closest camera distance that
     keeps every part of it in view across the whole sway, for this box's shape */
  const pts = [], tmp = new T.Vector3();
  v.grp.updateMatrixWorld(true);
  v.grp.traverse(o => {
    if (!o.isMesh || o.isInstancedMesh || o.userData.noFit || !o.geometry || !o.geometry.attributes.position) return;
    const pa = o.geometry.attributes.position, step = Math.max(1, Math.floor(pa.count / 300));
    for (let i = 0; i < pa.count; i += step) pts.push(tmp.fromBufferAttribute(pa, i).applyMatrix4(o.matrixWorld).clone());
  });
  const tg = v.cam.target;
  function need(th, el, aspect) {
    const tv = Math.tan(cam.fov * Math.PI / 360) * 0.95, thz = tv * aspect;
    const f = new T.Vector3(-Math.sin(th) * Math.cos(el), -Math.sin(el), -Math.cos(th) * Math.cos(el));
    const r = new T.Vector3(Math.cos(th), 0, -Math.sin(th));
    const u = new T.Vector3(-Math.sin(th) * Math.sin(el), Math.cos(el), -Math.cos(th) * Math.sin(el));
    let d = 0;
    for (let i = 0; i < pts.length; i++) {
      tmp.copy(pts[i]).sub(tg);
      const pf = tmp.dot(f);
      d = Math.max(d, Math.abs(tmp.dot(r)) / thz - pf, Math.abs(tmp.dot(u)) / tv - pf);
    }
    return d;
  }
  const baseEl = v.cam.el, sway = v.cam.sway == null ? SWAY : v.cam.sway;
  function fitTo(aspect) {
    const el = aspect < 1.35 ? baseEl + 0.14 : aspect > 2 ? baseEl - 0.05 : baseEl;
    let d = 0;
    for (let k = -2; k <= 2; k++) d = Math.max(d, need(v.cam.theta + sway * k / 2, el, aspect));
    return { d: d * (aspect < 1.35 ? (v.cam.crop || 0.88) : 1), el };
  }
  const f0 = fitTo(W / H);
  v.cam.el = f0.el; v.cam.dist = f0.d;
  const ctl = orbit(canvas, cam, v.cam);
  ctl.place();
  const still = RM.matches;
  if (still) for (let i = 0; i < 90; i++) anims.forEach(f => f(1 / 60, i / 60));
  const inst = { renderer: st.renderer, scene, raf: 0, ctl, io: null, ro: null, dead: false,
    view(th, e, d) { ctl.set(th, e, d == null ? null : d * v.cam.dist); dirty = true; } };
  let visible = true, t = 0, dirty = true;
  if ("IntersectionObserver" in window) { inst.io = new IntersectionObserver(es => { visible = es[es.length - 1].isIntersecting; }); inst.io.observe(canvas); }
  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    st.renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); ctl.rebase(fitTo(w / h).d); dirty = true;
  }
  if ("ResizeObserver" in window) { inst.ro = new ResizeObserver(resize); inst.ro.observe(canvas); }
  const clock = new T.Clock();
  (function tick() {
    if (inst.dead) return;
    inst.raf = requestAnimationFrame(tick);
    if (!canvas.isConnected) { dispose(inst); return; }
    const dt = Math.min(clock.getDelta(), 0.05);
    if (!visible || document.hidden) return;
    t += dt;
    if (still) {
      if (!(ctl.dirty || dirty)) return;
      dirty = false; ctl.place(); st.renderer.render(scene, cam); return;
    }
    ctl.tick(dt, true);
    for (let i = 0; i < anims.length; i++) anims[i](dt, t);
    ctl.place();
    st.renderer.render(scene, cam);
  })();
  return inst;
}

function dispose(inst) {
  if (!inst || inst.dead) return;
  inst.dead = true;
  cancelAnimationFrame(inst.raf);
  if (inst.io) inst.io.disconnect();
  if (inst.ro) inst.ro.disconnect();
  if (inst.ctl) inst.ctl.dispose();
  inst.scene.traverse(o => {
    if (o.geometry) o.geometry.dispose();
    const mats = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
    mats.forEach(m => { ["map", "alphaMap"].forEach(k => { if (m[k]) m[k].dispose(); }); m.dispose(); });
  });
  inst.renderer.dispose();
  try { inst.renderer.forceContextLoss(); } catch (e) {}
}

window.Venue3D = { load, mount, dispose, PARKS };
/* older callers: Park3D.mount(canvas, game) is the MLB view */
window.Park3D = { load, mount: (canvas, g) => mount(canvas, { sport: "mlb", g }), dispose, PARKS };
})();
