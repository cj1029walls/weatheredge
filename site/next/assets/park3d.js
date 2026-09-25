/* DFSRADAR · 3D ballpark (three.js r128, loaded on demand).
 * Ported from the original MLB radar: a stylized stadium from each park's real
 * fence distances and wall heights, with tonight's wind drawn as particle flow
 * and rain as falling streaks when the chance is real.
 *
 *   Park3D.load()             -> Promise<THREE>   (fetches three.js once)
 *   Park3D.mount(canvas, g)   -> instance | null  (g = a /data.json game)
 *   Park3D.dispose(instance)
 */
(function () {
"use strict";
const THREE_SRC = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
const RM = window.matchMedia ? matchMedia("(prefers-reduced-motion: reduce)") : {matches:false};
let threeP = null, threeDead = false;
function loadThree(){
  if(window.THREE) return Promise.resolve(window.THREE);
  if(threeDead) return Promise.reject(new Error("three.js unavailable"));
  if(!threeP) threeP = new Promise((resolve, reject)=>{
    const sc = document.createElement("script");
    let settled = false;
    const done = (ok, err)=>{ if(settled) return; settled = true; clearTimeout(timer); if(ok) resolve(window.THREE); else { threeP = null; reject(err); } };
    const timer = setTimeout(()=>done(false, new Error("three.js timed out")), 12000);
    sc.src = THREE_SRC; sc.async = true;
    sc.onload = ()=>{ if(window.THREE) done(true); else { threeDead = true; done(false, new Error("three.js missing")); } };
    sc.onerror = ()=>{ threeDead = true; done(false, new Error("three.js failed to load")); };
    document.head.appendChild(sc);
  });
  return threeP;
}
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


function disposeP3D(inst){
  if(!inst) return;
  cancelAnimationFrame(inst.raf);
  inst.scene.traverse(o=>{
    if(o.geometry) o.geometry.dispose();
    const mats = Array.isArray(o.material)?o.material:(o.material?[o.material]:[]);
    mats.forEach(m=>{ if(m.map) m.map.dispose(); m.dispose(); });
  });
  inst.renderer.dispose();
}
function makeWallLabel(txt){
  const cv=document.createElement("canvas"); cv.width=128; cv.height=64;
  const cx=cv.getContext("2d");
  cx.font="700 40px -apple-system,Segoe UI,Arial"; cx.textAlign="center"; cx.textBaseline="middle";
  cx.fillStyle="rgba(20,28,44,0.92)"; cx.fillText(txt,64,34);
  const tex=new THREE.CanvasTexture(cv);
  return new THREE.Mesh(new THREE.PlaneGeometry(26,13),
    new THREE.MeshBasicMaterial({map:tex, transparent:true, depthWrite:false}));
}
function initPark3D(g, canvas){
  if(typeof THREE === "undefined") return null;
  const park = PARKS[g.home] || {dims:[335,375,400,375,335], walls:[8,8,8,8,8]};
  const W = canvas.clientWidth || 780, H = canvas.clientHeight || 330;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({canvas, antialias:true});
  } catch(e) {
    /* WebGL context unavailable (blocked, unsupported, or GPU exhausted) —
       the caller keeps the flat park diagram instead of leaving a dead box. */
    return null;
  }
  let dirty = true;          // reduced-motion mode renders only when something changed
  renderer.setSize(W, H, false);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1, 2));
  const scene = new THREE.Scene();

  const night = g.sortTime >= 1900;
  const foggy = /fog|marine/i.test(g.sky);
  const dome = !!g.dome;

  /* ---- weather-tinted monochrome palette (Home Run Report style) ----
     the whole scene lives in ONE hue; conditions pick it:
     hot = ember/crimson · mild = deep navy · cool = steel · fog = misty slate · dome = graphite */
  let hue, sat;
  /* Anchored to the DFS Kitchen surfaces (#2E3240 is hue .625 / sat .16) so the
     canvas sits inside its card instead of fighting it. Weather still moves the
     hue, but toward the palette's own accents -- warm to the accent orange,
     cold to the radar cyan -- and at a fraction of the old saturation. */
  if(dome){ hue=0.625; sat=0.07; }
  else if(foggy){ hue=0.58; sat=0.10; }
  else if(g.temp>=88){ hue=0.075; sat=0.26; }
  else if(g.temp<=72){ hue=0.525; sat=0.24; }
  else { hue=0.625; sat=0.17; }
  /* day games get an airy, brighter scene; night games go deep and floodlit —
     the white wall and streamlines pop against the dark. Domes keep graphite. */
  /* backgrounds lifted off near-black: at 0.055 the canvas read as a hole
     punched in the card. These sit around the --inset surface instead. */
  const LT = dome ? {bg:0.145, apron:0.235, grass:0.30, track:0.205, dirt:0.225, diamond:0.27, mound:0.19}
           : night ? {bg:0.135, apron:0.215, grass:0.275, track:0.185, dirt:0.20, diamond:0.245, mound:0.17}
                   : {bg:0.175, apron:0.285, grass:0.355, track:0.245, dirt:0.265, diamond:0.315, mound:0.23};
  const L = (l)=> new THREE.Color().setHSL(hue, sat, Math.max(0.04, l));
  const COL = {
    bg:      L(LT.bg),
    apron:   L(LT.apron),
    grass:   L(LT.grass),
    track:   L(LT.track),
    dirt:    L(LT.dirt),
    diamond: L(LT.diamond),
    mound:   L(LT.mound),
  };
  /* The frame is always the radar cyan-slate; only the field carries weather. */
  const SKY = new THREE.Color().setHSL(0.545, 0.30, dome ? 0.115 : (night ? 0.105 : 0.145));
  scene.background = SKY;
  scene.fog = foggy ? new THREE.Fog(SKY, 260, 900) : new THREE.Fog(SKY, 900, 1900);
  const M = c => new THREE.MeshBasicMaterial({color:c});

  /* geometry: 2D layout has +y toward CF; mapped to 3D as (x, 0, -y) */
  const angles = [-45,-22.5,0,22.5,45].map(a=>a*Math.PI/180);
  const pts2 = park.dims.map((r,i)=>new THREE.Vector2(Math.sin(angles[i])*r, Math.cos(angles[i])*r));
  const curve = new THREE.SplineCurve(pts2);
  const samples = curve.getPoints(72);

  /* foul-territory apron — rounded pad the field sits on */
  const apron = new THREE.Mesh(new THREE.CircleGeometry(148, 48), M(COL.apron));
  apron.rotation.x = -Math.PI/2; apron.position.set(0,-0.15,-30); scene.add(apron);

  /* outfield grass fan */
  const shape = new THREE.Shape();
  shape.moveTo(0,0);
  samples.forEach(p=>shape.lineTo(p.x,p.y));
  shape.lineTo(0,0);
  const grass = new THREE.Mesh(new THREE.ShapeGeometry(shape), M(COL.grass));
  grass.rotation.x = -Math.PI/2; grass.position.y = 0.05; scene.add(grass);

  /* warning track — darker band hugging the wall */
  const inner = samples.map(p=>{ const r=Math.hypot(p.x,p.y), s=(r-17)/r; return new THREE.Vector2(p.x*s,p.y*s); });
  const ringPts = [...samples, ...inner.slice().reverse()];
  const track = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(ringPts)), M(COL.track));
  track.rotation.x = -Math.PI/2; track.position.y = 0.12; scene.add(track);

  /* infield dirt arc + inner diamond + mound */
  const dirt = new THREE.Mesh(new THREE.CircleGeometry(95, 44), M(COL.dirt));
  dirt.rotation.x = -Math.PI/2; dirt.position.set(0, 0.18, -60.5); scene.add(dirt);
  const dShape = new THREE.Shape();
  dShape.moveTo(0,10); dShape.lineTo(53.6,63.6); dShape.lineTo(0,117.3); dShape.lineTo(-53.6,63.6); dShape.lineTo(0,10);
  const diamond = new THREE.Mesh(new THREE.ShapeGeometry(dShape), M(COL.diamond));
  diamond.rotation.x = -Math.PI/2; diamond.position.y = 0.26; scene.add(diamond);
  const mound = new THREE.Mesh(new THREE.CircleGeometry(9.5, 24), M(COL.mound));
  mound.rotation.x = -Math.PI/2; mound.position.set(0, 0.34, -60.5); scene.add(mound);
  const rubber = new THREE.Mesh(new THREE.BoxGeometry(2.4,0.3,0.7), M(0xf4f6fa));
  rubber.position.set(0, 0.6, -60.5); scene.add(rubber);

  /* home plate circle + plate */
  const homeC = new THREE.Mesh(new THREE.CircleGeometry(13, 24), M(COL.mound));
  homeC.rotation.x = -Math.PI/2; homeC.position.set(0, 0.34, 0); scene.add(homeC);
  const plate = new THREE.Mesh(new THREE.BoxGeometry(1.9,0.3,1.9), M(0xf4f6fa));
  plate.position.set(0, 0.6, 0); scene.add(plate);

  /* bases — white pads rotated 45° */
  [[63.64,-63.64],[0,-127.28],[-63.64,-63.64]].forEach(([x,z])=>{
    const b = new THREE.Mesh(new THREE.BoxGeometry(3.6,0.7,3.6), M(0xf4f6fa));
    b.rotation.y = Math.PI/4; b.position.set(x, 0.6, z); scene.add(b);
  });

  /* foul lines — crisp white chalk to each pole */
  [[park.dims[0], 1],[park.dims[4], -1]].forEach(([len, side])=>{
    const line = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.15, len), M(0xf4f6fa));
    line.rotation.y = side * Math.PI/4;
    line.position.set(-side*0.3536*len, 0.4, -0.3536*len);
    scene.add(line);
  });

  /* outfield wall — glowing white ribbon with real per-section heights */
  const hAt = t => { const f=t*4, i=Math.min(3,Math.floor(f)), u=f-i; return park.walls[i]*(1-u)+park.walls[i+1]*u; };
  const wv=[], wi=[];
  const HSCALE = 1.7;
  samples.forEach((p,i)=>{ const h=hAt(i/(samples.length-1))*HSCALE; wv.push(p.x,0,-p.y, p.x,h,-p.y); });
  for(let i=0;i<samples.length-1;i++){ const a=i*2; wi.push(a,a+2,a+1, a+1,a+2,a+3); }
  const wallGeo = new THREE.BufferGeometry();
  wallGeo.setAttribute("position", new THREE.Float32BufferAttribute(wv,3));
  wallGeo.setIndex(wi); wallGeo.computeVertexNormals();
  scene.add(new THREE.Mesh(wallGeo, new THREE.MeshBasicMaterial({color:0xf4f6fa, side:THREE.DoubleSide})));
  /* wall cap — thin top edge catches the eye like the reference renders */
  const capPts = samples.map((p,i)=>new THREE.Vector3(p.x, hAt(i/(samples.length-1))*HSCALE+0.25, -p.y));
  scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(capPts),
    new THREE.LineBasicMaterial({color:0xffffff})));

  /* wall shadow skirt — soft dark base line grounding the wall */
  const skv=[], ski=[];
  samples.forEach(p=>{ const r=Math.hypot(p.x,p.y), s=(r+7)/r; skv.push(p.x,0.02,-p.y, p.x*s,0.02,-p.y*s); });
  for(let i=0;i<samples.length-1;i++){ const a=i*2; ski.push(a,a+2,a+1, a+1,a+2,a+3); }
  const skirtGeo = new THREE.BufferGeometry();
  skirtGeo.setAttribute("position", new THREE.Float32BufferAttribute(skv,3));
  skirtGeo.setIndex(ski);
  scene.add(new THREE.Mesh(skirtGeo, new THREE.MeshBasicMaterial({color:L(0.14), side:THREE.DoubleSide})));

  /* foul poles — tall bright yellow */
  [[0,1],[4,-1]].forEach(([di, side])=>{
    const d = park.dims[di];
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.9,0.9,46,8), M(0xffd94a));
    pole.position.set(-side*0.707*d, 23, -0.707*d); scene.add(pole);
  });

  /* wall distance markers — real numbers on the wall face */
  [0,1,2,3,4].forEach(i=>{
    const p = pts2[i], r = Math.hypot(p.x,p.y), s=(r-2.5)/r;
    const lbl = makeWallLabel(String(park.dims[i]));
    const h = park.walls[i]*HSCALE;
    lbl.position.set(p.x*s, Math.min(h*0.55, h-3)+3.5, -p.y*s);
    lbl.lookAt(0, lbl.position.y, 0);
    scene.add(lbl);
  });

  /* team logo laid flat on the outfield grass */
  const MLBID = {ARI:109,ATH:133,ATL:144,BAL:110,BOS:111,CHC:112,CIN:113,CLE:114,COL:115,
    CWS:145,DET:116,HOU:117,KC:118,LAA:108,LAD:119,MIA:146,MIL:158,MIN:142,NYM:121,NYY:147,
    PHI:143,PIT:134,SD:135,SEA:136,SF:137,STL:138,TB:139,TEX:140,TOR:141,WSH:120};
  if(MLBID[g.home]){
    new THREE.TextureLoader().load(
      `https://midfield.mlbstatic.com/v1/team/${MLBID[g.home]}/spots/256`,
      tex=>{
        const logo=new THREE.Mesh(new THREE.PlaneGeometry(78,78),
          new THREE.MeshBasicMaterial({map:tex, transparent:true, opacity:0.9, depthWrite:false}));
        logo.rotation.x=-Math.PI/2;
        logo.position.set(0, 0.3, -262);
        scene.add(logo); dirty = true;
      },
      undefined, ()=>{} /* CORS/load failure → just skip the logo */);
  }

  /* dome roof shell */
  if(dome){
    const roof = new THREE.Mesh(new THREE.SphereGeometry(400,36,18,0,Math.PI*2,0,Math.PI/2),
      new THREE.MeshBasicMaterial({color:0xe8ecf2, transparent:true, opacity:0.10, side:THREE.DoubleSide}));
    roof.scale.y = 0.45; roof.position.set(0,2,-140); scene.add(roof);
  }

  /* wind — nullschool-style particle flow: hundreds of thin streaks
     drifting along the wind field with organic curl, trails fading behind */
  let wind = null;
  if(!dome && g.wind>2){
    const N=130, TAIL=22;
    const base=g.windAngle*Math.PI/180;
    const spawn=()=>new THREE.Vector3((Math.random()-0.5)*700, 8+Math.random()*135, 115-Math.random()*660);
    const parts=[];
    for(let i=0;i<N;i++){
      const p=spawn();
      parts.push({p, age:Math.random()*3, life:3+Math.random()*2.6,
                  hist:Array.from({length:TAIL},()=>p.clone())});
    }
    /* single solid ribbon per streak: each trail is a thin quad strip
       (real geometric width — no stacked-line doubling) */
    const RIBBON_W = 2.8;
    const vCount=N*TAIL*2;
    const geo=new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(vCount*3),3));
    /* RGBA vertex colors: constant wind-grey, alpha-only fades — the streak
       never blends toward the background, so no dark tail */
    const colArr=new Float32Array(vCount*4);
    const GREY=new THREE.Color(0xa8b2c1);
    for(let i=0;i<vCount;i++){ colArr[i*4]=GREY.r; colArr[i*4+1]=GREY.g; colArr[i*4+2]=GREY.b; colArr[i*4+3]=0; }
    geo.setAttribute("color", new THREE.BufferAttribute(colArr,4));
    const idx=[];
    for(let p=0;p<N;p++){
      const o=p*TAIL*2;
      for(let i=0;i<TAIL-1;i++){
        const a=o+i*2, b=o+i*2+1, c=o+i*2+2, d=o+i*2+3;
        idx.push(a,b,c, b,d,c);
      }
    }
    geo.setIndex(idx);
    const mat=new THREE.MeshBasicMaterial({vertexColors:true, transparent:true,
      opacity: foggy?0.5:0.7, side:THREE.DoubleSide, depthWrite:false});
    wind={mesh:new THREE.Mesh(geo,mat), parts, tail:TAIL, base, spawn, t:0,
          speed:46 + g.wind*6.5, w:RIBBON_W};
    scene.add(wind.mesh);
  }

  /* rain — falling streaks, tilted with the wind, when rain risk is real */
  let rain = null;
  if(!dome && (g.rain||0) >= 45){
    const RN = Math.round(90 + Math.min(1,(g.rain-45)/45)*130);
    const a=g.windAngle*Math.PI/180;
    const tilt = Math.min(0.45, (g.wind||0)*0.03);
    const vel = new THREE.Vector3(Math.sin(a)*tilt, -1, -Math.cos(a)*tilt).normalize();
    const drops=[];
    for(let i=0;i<RN;i++)
      drops.push(new THREE.Vector3((Math.random()-0.5)*680, Math.random()*185, 110-Math.random()*640));
    const rgeo=new THREE.BufferGeometry();
    rgeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(RN*6),3));
    const rcol = new THREE.Color().setHSL(hue, Math.min(0.25,sat), night?0.55:0.72);
    rain={mesh:new THREE.LineSegments(rgeo, new THREE.LineBasicMaterial({color:rcol, transparent:true, opacity:0.38})),
          drops, vel, len:9, speed:330};
    scene.add(rain.mesh);
  }

  /* camera + drag orbit — high angle behind home, like the reference */
  const cam = new THREE.PerspectiveCamera(36, W/H, 1, 3200);
  const target = new THREE.Vector3(0, 6, -150);
  let theta=0, el=0.62, dragging=false, lastX=0, lastY=0, idleT=0;
  function place(){
    const r=545;
    cam.position.set(target.x+Math.sin(theta)*Math.cos(el)*r, target.y+Math.sin(el)*r, target.z+Math.cos(theta)*Math.cos(el)*r);
    cam.lookAt(target);
  }
  canvas.addEventListener("pointerdown", e=>{ dragging=true; lastX=e.clientX; lastY=e.clientY; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", e=>{
    if(!dragging) return;
    theta -= (e.clientX-lastX)*0.006;
    el = Math.min(1.15, Math.max(0.22, el + (e.clientY-lastY)*0.004));
    lastX=e.clientX; lastY=e.clientY; idleT=0; dirty = true;
  });
  canvas.addEventListener("pointerup", ()=>dragging=false);
  canvas.addEventListener("pointercancel", ()=>dragging=false);

  const clock = new THREE.Clock();
  const inst = {renderer, scene, raf:0};
  function advance(dt){
    if(wind){
      wind.t += dt;
      const pos = wind.mesh.geometry.attributes.position.array;
      const col = wind.mesh.geometry.attributes.color.array;
      const fbPerpX = Math.cos(wind.base), fbPerpZ = Math.sin(wind.base);
      wind.parts.forEach((pt, pi)=>{
        pt.age += dt;
        /* flow field: base wind direction + smooth positional curl so
           neighbouring particles bend together like a fluid */
        const curl = 0.42*Math.sin(pt.p.x*0.010 + wind.t*0.5)
                   + 0.30*Math.sin(pt.p.z*0.0065 - wind.t*0.33);
        const a = wind.base + curl;
        pt.p.x += Math.sin(a)*wind.speed*dt;
        pt.p.z += -Math.cos(a)*wind.speed*dt;
        const out = Math.abs(pt.p.x)>390 || pt.p.z<-640 || pt.p.z>170;
        if(pt.age>pt.life || out){
          pt.p.copy(wind.spawn()); pt.age=0; pt.life=2.2+Math.random()*2.4;
          pt.hist.forEach(h=>h.copy(pt.p));
        }
        const tailv = pt.hist.pop(); tailv.copy(pt.p); pt.hist.unshift(tailv);
        /* alpha: quick fade-in, fade-out at end of life — no popping */
        const env = Math.max(0, Math.min(1, pt.age/0.35, (pt.life-pt.age)/0.55));
        const o = pi*wind.tail*2;
        for(let ti=0; ti<wind.tail; ti++){
          const P=pt.hist[ti];
          const Q=pt.hist[ti+1] || pt.hist[ti-1] || P;
          let dx=P.x-Q.x, dz=P.z-Q.z;
          const len=Math.hypot(dx,dz);
          let px, pz;
          if(len>0.0001){ px=-dz/len; pz=dx/len; } else { px=fbPerpX; pz=fbPerpZ; }
          /* solid grey stroke that tapers to a point — the taper IS the fade */
          const u = ti/(wind.tail-1);
          const half = wind.w*0.5*Math.pow(1-u, 0.65);
          const v=(o+ti*2)*3;
          pos[v]  =P.x+px*half; pos[v+1]=P.y; pos[v+2]=P.z+pz*half;
          pos[v+3]=P.x-px*half; pos[v+4]=P.y; pos[v+5]=P.z-pz*half;
          const a4=(o+ti*2)*4;
          const alpha = env*(0.9-0.35*u);
          col[a4+3]=alpha; col[a4+7]=alpha;
        }
      });
      wind.mesh.geometry.attributes.position.needsUpdate = true;
      wind.mesh.geometry.attributes.color.needsUpdate = true;
    }
    if(rain){
      const pos = rain.mesh.geometry.attributes.position.array;
      rain.drops.forEach((d,i)=>{
        d.addScaledVector(rain.vel, rain.speed*dt);
        if(d.y < 1){ d.set((Math.random()-0.5)*680, 170+Math.random()*20, 110-Math.random()*640); }
        pos[i*6]=d.x;                       pos[i*6+1]=d.y;                       pos[i*6+2]=d.z;
        pos[i*6+3]=d.x+rain.vel.x*rain.len; pos[i*6+4]=d.y+rain.vel.y*rain.len;   pos[i*6+5]=d.z+rain.vel.z*rain.len;
      });
      rain.mesh.geometry.attributes.position.needsUpdate = true;
    }
  }
  /* reduced motion: no auto-rotation and no drifting particles — the wind and
     rain are warmed up into a still frame; dragging still turns the view */
  const still = RM.matches;
  if(still) for(let i=0; i<90; i++) advance(1/60);
  (function tick(){
    inst.raf = requestAnimationFrame(tick);
    const dt = Math.min(clock.getDelta(), 0.05);
    if(still){
      if(!dirty) return;
      dirty = false; place(); renderer.render(scene, cam); return;
    }
    idleT += dt;
    if(!dragging && idleT>2.5) theta += dt*0.07;
    advance(dt);
    place();
    renderer.render(scene, cam);
  })();
  return inst;
}


window.Park3D = { load: loadThree, mount: initPark3D, dispose: disposeP3D, PARKS: PARKS };
})();
