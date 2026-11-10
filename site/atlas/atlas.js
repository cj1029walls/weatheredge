/* DFSRADAR · Venue Atlas. One file for the index (/atlas/) and every venue
 * page (/atlas/<slug>/, which carries data-venue on <main>). The data is
 * site/atlas/data.json, built by scripts/atlas/build.py from our own history. */
document.addEventListener("DOMContentLoaded", function () {
  var D = DR, esc = D.esc, app = document.getElementById("atlas-app");
  var want = document.getElementById("atlas").getAttribute("data-venue"), base = D.u("/atlas/");
  var KIND = { mlb: "ballpark", nfl: "stadium", cfb: "stadium", pga: "course", nascar: "track" };
  var MANY = { mlb: "ballparks", nfl: "stadiums", cfb: "stadiums", pga: "courses", nascar: "tracks" };
  D.shell({ section: "atlas" });

  D.get(D.u("/atlas/data.json")).then(function (d) {
    if (!d || !d.venues) {
      app.innerHTML = '<div class="empty card"><h3>The Atlas didn\'t load</h3><p>Refresh in a minute.</p></div>';
      return;
    }
    if (want) venue(d.venues, d.venues.filter(function (v) { return v.id === want; })[0]);
    else index(d.venues);
  });

  function onFile(v) { return v.n ? v.n.toLocaleString() + " " + (v.n === 1 ? v.unit.replace(/s$/, "") : v.unit) : ""; }

  /* ------------------------------------------------------------ the index */
  function index(V) {
    var q = "", sport = "all";
    function card(v) {
      var t = v.tiles[0];
      return '<a class="card card--pad" href="' + base + v.slug + '/" style="display:flex;flex-direction:column;gap:8px;padding:18px">' +
        '<span class="label" style="color:var(--cyan2)">' + esc(v.sub) + "</span>" +
        '<span style="font:700 17px/1.3 var(--display)">' + esc(v.name) + "</span>" +
        '<span class="small dim" style="margin-top:auto">' + esc(t[0]) + ' <b style="color:var(--text)">' + esc(t[1]) + "</b>" +
        (v.n ? " · " + onFile(v) : "") + "</span></a>";
    }
    function draw() {
      var list = V.filter(function (v) {
        return (sport === "all" || v.sport === sport) && (!q || (v.name + " " + v.sub).toLowerCase().indexOf(q) >= 0);
      });
      document.getElementById("at-list").innerHTML = D.SPORTS.map(function (sp) {
        var xs = list.filter(function (v) { return v.sport === sp.k; });
        if (!xs.length) return "";
        return '<section class="sec"><div class="sec__h"><div><h2 class="sec__title">' + sp.name + " " + MANY[sp.k] +
          '</h2><p class="sec__sub">' + xs.length + " on file</p></div></div>" +
          '<div class="grid g3">' + xs.map(card).join("") + "</div></section>";
      }).join("") || '<div class="empty card mt24"><h3>No venue matches</h3><p>Try a park, a team or a city.</p></div>';
    }
    app.innerHTML = '<section class="ph"><div class="ph__eyebrow"><span>Venue Atlas</span><span class="faint">·</span><span>' + V.length + " venues</span></div>" +
      '<h1 class="ph__title">Every ballpark, stadium, course and track — and its weather</h1>' +
      '<p class="ph__lede">Each venue in 3D, with what the weather usually is there and what it has done to the games played in it. ' +
      "All of it comes from our own records, and every number shows the games behind it.</p>" +
      '<div class="row" style="gap:12px;flex-wrap:wrap;margin-top:20px"><div class="seg-scroll"><div class="seg" id="at-seg" role="group" aria-label="Sport">' +
      [["all", "All"]].concat(D.SPORTS.map(function (s) { return [s.k, s.name]; })).map(function (x) {
        return '<button type="button" data-s="' + x[0] + '" aria-pressed="' + (x[0] === "all") + '">' + x[1] + "</button>";
      }).join("") + "</div></div>" +
      '<input class="search" id="at-q" type="search" placeholder="Find a park, team or city" aria-label="Find a venue" style="max-width:300px"></div></section>' +
      '<div id="at-list"></div>';
    D.$$("#at-seg button").forEach(function (b) {
      b.addEventListener("click", function () {
        sport = b.getAttribute("data-s");
        D.$$("#at-seg button").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
        draw();
      });
    });
    document.getElementById("at-q").addEventListener("input", function (e) { q = e.target.value.trim().toLowerCase(); draw(); });
    draw();
  }

  /* ---------------------------------------------------------- one venue */
  function venue(V, v) {
    if (!v) {
      app.innerHTML = '<div class="empty card mt24"><h3>That venue isn\'t in the Atlas</h3><p><a class="cyan" href="' + base + '">See every venue →</a></p></div>';
      return;
    }
    var sp = D.sport(v.sport), same = V.filter(function (x) { return x.sport === v.sport; }), i = same.indexOf(v);
    var prev = same[(i - 1 + same.length) % same.length], next = same[(i + 1) % same.length];
    var rows = (v.bars && v.bars.rows) || [], max = Math.max.apply(null, rows.map(function (r) { return r[1]; }).concat([1]));
    app.innerHTML =
      '<section class="ph"><div class="ph__eyebrow"><a href="' + base + '">Venue Atlas</a><span class="faint">·</span><span>' + sp.name + " " + KIND[v.sport] + "</span></div>" +
      '<h1 class="ph__title">' + esc(v.name) + '</h1><p class="ph__lede">' + esc(v.sub) + "</p>" +
      '<div class="ph__meta"><span class="chips">' + (v.roof ? '<span class="chip">' + esc(v.roof) + "</span>" : "") +
      (v.n ? '<span class="chip">' + onFile(v) + " on file · " + esc(v.span) + "</span>" : "") + "</span></div></section>" +
      '<section class="sec" id="at-3d-sec"><div class="card" id="at-3d" style="overflow:hidden;padding:0"></div></section>' +
      '<section class="sec"><div class="sec__h"><div><h2 class="sec__title">What the weather does here</h2>' +
      '<p class="sec__sub">' + (v.n ? "From " + onFile(v) + ", " + esc(v.span) + "." : "History builds from the first event we record here.") + "</p></div></div>" +
      '<div class="stats">' + v.tiles.map(function (t) {
        return '<div class="stat"><div class="stat__v">' + esc(t[1]) + '</div><div class="stat__l">' + esc(t[0]) + '</div><div class="stat__s">' + esc(t[2] || "") + "</div></div>";
      }).join("") + "</div>" +
      (v.notes.length ? '<div class="card card--pad mt16"><ul class="at-notes">' + v.notes.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") + "</ul></div>" : "") +
      "</section>" +
      (rows.length ? '<section class="sec"><div class="card card--pad at-bars"><div class="label" style="margin-bottom:16px">' + esc(v.bars.title) + "</div>" +
        rows.map(function (r) {
          return '<div class="imp" style="grid-template-columns:64px 1fr 84px"><span class="k">' + esc(r[0]) + '</span><span class="bar"><i style="position:absolute;top:0;bottom:0;border-radius:8px;left:0;width:' +
            (r[1] / max * 100).toFixed(1) + '%;background:var(--cyan)"></i></span><span class="v">' + r[1] + esc(v.bars.unit) + "</span></div>";
        }).join("") + "</div></section>" : "") +
      '<section class="sec"><div class="row between" style="flex-wrap:wrap;gap:12px">' +
      '<a class="btn btn--ghost" href="' + base + prev.slug + '/">← ' + esc(prev.name) + "</a>" +
      '<a class="btn btn--cyan" href="' + D.u(sp.weather) + '">' + sp.name + (sp.season.on ? " weather this week" : " weather") + " →</a>" +
      '<a class="btn btn--ghost" href="' + base + next.slug + '/">' + esc(next.name) + " →</a></div></section>";
    var box = document.getElementById("at-3d");
    if (!D.hasGL()) { document.getElementById("at-3d-sec").hidden = true; return; }
    D.stage3d(box, { spec: v.spec, label: v.name + " in 3D", cap: v.model }).ready.then(function (ok) {
      if (!ok) document.getElementById("at-3d-sec").hidden = true;
    });
  }
});
