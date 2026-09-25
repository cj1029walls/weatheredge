/* DFSRADAR · cross-sport summaries for Home, the Weather hub and the Props hub.
 *   H.load(parts)          -> Promise<{mlb:{…}, nfl:{…}, …}>  parts: "wx","pro","rec"
 *   H.status(k, s)         -> {k, name, head, sub, watch:[…], fresh:{…}, href}
 *   H.pickCard(k, s, opt)  -> the sport's free #1 as a card (or a note why there isn't one)
 *   H.recordLine(k, s)     -> one-line record summary
 */
(function () {
  "use strict";
  var D = window.DR, F = window.F, esc = D.esc, isNum = D.isNum;

  var URLS = {
    mlb: { wx: F.mlb.url, pro: F.mlb.proUrl, rec: F.mlb.recUrl },
    nfl: { wx: F.nfl.url, pro: F.nfl.proUrl, rec: F.nfl.recUrl },
    cfb: { wx: F.cfb.url, pro: F.cfb.proUrl, rec: F.cfb.recUrl },
    pga: { wx: F.pga.url, pro: F.pga.proUrl, rec: F.pga.recUrl },
    nascar: { wx: F.nascar.url, pro: F.nascar.proUrl, rec: F.nascar.recUrl }
  };
  function load(parts) {
    var out = {}, jobs = [];
    Object.keys(URLS).forEach(function (k) {
      out[k] = {};
      parts.forEach(function (p) { jobs.push(D.get(URLS[k][p]).then(function (v) { out[k][p] = v; })); });
    });
    return Promise.all(jobs).then(function () { return out; });
  }

  function watchOf(k, s) {
    var w = s.wx;
    if (!w) return [];
    return (F[k].watch(w) || []).map(function (x) { x.sport = k; return x; });
  }

  function roofs(n) { return n ? n + " under a roof" : "all open-air"; }

  function status(k, s) {
    var w = s.wx, sp = D.sport(k), r = { k: k, name: sp.name, href: D.u(sp.weather), watch: watchOf(k, s), head: "", sub: "", fresh: null };
    if (!w) { r.head = "Forecast unavailable"; r.sub = "The feed didn't load — refresh in a minute."; return r; }
    if (k === "mlb") {
      var n = (w.games || []).length;
      r.head = n ? D.plural(n, "game") + " · " + D.longDate(w.date).replace(/^(\w+),.*/, "$1") : "No games today";
      var first = (w.games || []).slice().sort(function (a, b) { return a.sortTime - b.sortTime; })[0];
      r.sub = n ? "First pitch " + first.time + " · " + roofs(w.games.filter(function (g) { return g.dome; }).length) : (w.note || "Back tomorrow.");
      r.fresh = { built: w.generated, stale: w.stale, status: w.status, maxAgeH: 9, forDate: w.date };
    } else if (k === "nfl") {
      var g = w.games || [];
      r.head = g.length ? "Week " + (g[0].week || "") + " · " + D.plural(g.length, "game") : "Between weeks";
      r.sub = g.length ? roofs(g.filter(function (x) { return x.dome; }).length) + " · kickoffs " + g[0].day.split(" ")[0] + "–" + g[g.length - 1].day.split(" ")[0] : "Next slate appears as its forecasts come into range.";
      r.fresh = { built: w.generated, stale: w.stale, status: w.status, maxAgeH: 30 };
    } else if (k === "cfb") {
      var c = w.games || [];
      r.head = c.length ? "Week " + (c[0].week || "") + " · " + D.plural(c.length, "game") : "Between weeks";
      r.sub = (w.counts && (w.counts.severe || w.counts.elevated) ? (w.counts.severe || 0) + " severe · " + (w.counts.elevated || 0) + " elevated" : "Inside the forecast window");
      r.fresh = { built: w.generated, stale: w.stale, status: w.status, maxAgeH: 30 };
    } else if (k === "pga") {
      r.head = w.event ? w.event.name : "No event this week";
      r.sub = w.event ? w.event.course + " · " + (w.event.dates || "") : (w.brief || "");
      r.fresh = { built: w.generated, stale: w.stale, status: w.status, maxAgeH: 30 };
    } else if (k === "nascar") {
      r.head = w.race ? w.race.name : "No race this week";
      r.sub = w.race ? w.race.track + " · " + w.race.day.split(",")[0] + " " + w.race.time : (w.brief || "");
      r.fresh = { built: w.generated, stale: w.stale, status: w.status, maxAgeH: 30 };
    }
    return r;
  }

  /* each sport's free #1, as a card */
  function pickCard(k, s) {
    var pro = s.pro, sp = D.sport(k), href = D.u(sp.props);
    var none = function (why) {
      return '<div class="pc"><div class="pc__top"><span class="pc__sport">' + sp.name + '</span><span class="chip chip--sm">No pick</span></div>' +
        '<div class="pc__who" style="font-size:17px">' + esc(why) + '</div><div class="pc__cta"><span></span><a href="' + href + '">' + sp.name + " props →</a></div></div>";
    };
    if (!pro) return none("The board isn't posted yet.");
    if (k === "mlb") {
      if (!pro.targets || !pro.targets.length || pro.date !== D.todayET()) return none(pro.targets && pro.targets.length ? "Tomorrow's card posts in the morning." : "No MLB card today.");
      var p = F.mlb.picks(pro)[0];
      return window.P.topCard({ sportLabel: "MLB · home run · " + p.game, player: p.player, side: "YES", sub: p.team + " · vs " + (p.raw.sp || "TBD"),
        nums: [{ v: p.oursTxt, l: "Our chance", cls: "cyan" }, { v: p.priceTxt, l: "Books' price" }, { v: isNum(p.edge) ? D.signed(p.edge, 1) : "—", l: "Edge (pts)" }],
        href: href, hrefLabel: "All MLB props" });
    }
    if (k === "nfl") {
      var L = F.nfl.picks(pro).filter(function (x) { return x.side !== "WATCH" && x.k !== "SPOT" && x.k !== "REF TOTAL"; });
      if (!L.length) return none("No weather lean has cleared the bar this week.");
      var n = L[0];
      return window.P.topCard({ sportLabel: "NFL · " + n.market.toLowerCase() + " · " + n.game.replace("@", " @ "), player: n.player, side: n.side, sub: (n.team ? n.team + " · " : "") + n.factor + " split",
        nums: [{ v: isNum(n.line) ? String(n.line) : "—", l: "Books' line" }, { v: D.validOdds(n.price) ? D.odds(n.price) : "—", l: "Books' price" }, { v: isNum(n.delta) ? D.signed(n.delta, 0, "%") : "—", l: "In this weather" }],
        href: href, hrefLabel: "All NFL leans" });
    }
    if (k === "cfb") {
      var C = F.cfb.picks(pro);
      if (!C.length) return none(pro.paused ? "Trench board paused — our college data source is down." : "No trench lean this week.");
      return window.P.topCard({ sportLabel: "CFB · team rushing · " + C[0].game, player: C[0].player, side: C[0].side, sub: "Trench edge " + D.signed(C[0].cd, 1), href: href, hrefLabel: "The trench board" });
    }
    if (k === "pga") {
      var G = F.pga.picks(pro);
      if (!G.length) return none("No golf targets this week.");
      return window.P.topCard({ sportLabel: "Golf · top-20 · " + (pro.event ? pro.event.name : ""), player: G[0].player, side: "TARGET", sub: G[0].why,
        nums: [{ v: isNum(G[0].raw.score) ? G[0].raw.score.toFixed(1) : "—", l: "Course score", cls: "cyan" }, { v: D.validOdds(G[0].price) ? D.odds(G[0].price) : "—", l: "Books · to win" }], href: href, hrefLabel: "All golf targets" });
    }
    if (k === "nascar") {
      var R = F.nascar.picks(pro);
      if (!R.length) return none("No race targets this week.");
      return window.P.topCard({ sportLabel: "NASCAR · " + R[0].market.toLowerCase() + " · " + (pro.race ? pro.race.track : ""), player: R[0].player, side: "TARGET", sub: R[0].why, href: href, hrefLabel: "All race targets" });
    }
    return "";
  }

  function recordLine(k, s) {
    var r = s.rec;
    if (!r || !r.summary) return { v: "—", s: "No graded calls yet" };
    var x = r.summary;
    if (k === "mlb") return { v: x.value && x.value.n ? D.signed(x.value.units, 2, "u") : "—", s: "HR value flags · " + (x.value ? x.value.w + " of " + x.value.n + " hit" : ""), cls: x.value && x.value.units >= 0 ? "good" : "bad" };
    var o = x.overall || {};
    var lab = { nfl: "NFL leans", cfb: "CFB trench leans", pga: "Golf targets · top-20", nascar: "NASCAR targets · top-10" }[k];
    return { v: o.n ? o.w + "–" + (o.n - o.w) : "—", s: lab + (o.n ? " · " + D.pct(o.w / o.n * 100, 0) : "") };
  }

  function watchItem(x) {
    var sp = D.sport(x.sport);
    var href = x.sport === "pga" || x.sport === "nascar" ? D.u(sp.weather) : D.u(sp.weather) + "#g=" + encodeURIComponent(x.id);
    return '<a href="' + href + '"><span class="ic ' + (x.tone || "") + '" aria-hidden="true">' + x.icon + "</span>" +
      '<span><span class="w" style="display:block;margin:0 0 4px"><b style="color:var(--cyan2);font-weight:700">' + sp.name + "</b> · " + esc((x.game || "") + (x.when ? " · " + x.when : "")) + "</span>" +
      '<span class="t" style="display:block">' + esc(x.title) + '</span><span class="s" style="display:block">' + esc(x.sub) + "</span></span></a>";
  }

  /* ------------------------------------------------------------ featured venue
     One venue per sport worth seeing in 3D today, best first: the strongest
     wind at an open-air game still to come (rain adds weight, today beats
     later), race day at the track, the round being played at the course. */
  function etKey(d) {                      // Date -> "2026-09-25 19:05" in ET
    try {
      var o = {};
      new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
        .formatToParts(d).forEach(function (p) { o[p.type] = p.value; });
      return o.year + "-" + o.month + "-" + o.day + " " + o.hour + ":" + o.minute;
    } catch (e) { return ""; }
  }
  function mins(key) {                     // "YYYY-MM-DD HH:MM" -> minutes, for differences
    var m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(key || "");
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) / 60000 : null;
  }
  function featured(all) {
    var now = etKey(new Date()), nowM = mins(now), today = now.slice(0, 10), out = [];
    var soon = function (key, horizonH) {  // started under 3h ago, or starting within the horizon
      var m = mins(key); if (m == null || nowM == null) return false;
      return m >= nowM - 180 && m <= nowM + horizonH * 60;
    };
    var windChip = function (txt, calm) { return '<span class="chip' + (calm ? "" : " chip--cyan") + '">' + D.wx("wind") + esc(txt) + "</span>"; };
    var tempChip = function (t, lab) { return isNum(t) ? '<span class="chip">' + D.wx("temp") + t + "° " + lab + "</span>" : ""; };
    var rainChip = function (r) { return isNum(r) && r >= 40 ? '<span class="chip chip--warn">' + D.wx("drop") + r + "% rain</span>" : ""; };
    var best = function (list, score) { var b = null, bs = -1e9; list.forEach(function (g) { var s = score(g); if (s > bs) { bs = s; b = g; } }); return b ? { g: b, s: bs } : null; };

    var M = all.mlb && all.mlb.wx;
    if (M && M.games && M.games.length) {
      var FM = F.mlb, keyOf = function (g) { var t = isNum(g.sortTime) ? g.sortTime : 0; return M.date + " " + String(Math.floor(t / 100)).padStart(2, "0") + ":" + String(t % 100).padStart(2, "0"); };
      var open = M.games.filter(function (g) { return !g.dome && soon(keyOf(g), 36); });
      var b = best(open, function (g) { var k = FM.windKind(g); return (g.wind || 0) * (k === "out" || k === "in" ? 1.15 : 1) + (g.rain >= 40 ? 6 : 0) + (keyOf(g).slice(0, 10) === today ? 3 : 0); });
      if (b) {
        var g = b.g, k = FM.windKind(g), w = FM.wind(g.windLabel);
        out.push({ k: "mlb", s: b.s, spec: { sport: "mlb", g: g }, venue: FM.park(g), match: FM.name(g.away) + " at " + FM.name(g.home) + " · " + g.time,
          chips: [windChip(k === "calm" ? "Light wind" : g.wind + " mph " + w, k === "calm"), tempChip(g.temp, "at first pitch"), rainChip(g.rain)].filter(Boolean),
          cap: "Wind drawn against " + FM.park(g) + "'s real field layout at the forecast angle.", href: D.u("/mlb/") + "#g=" + encodeURIComponent(g.id),
          label: "3D view of " + FM.park(g) + (k === "calm" ? " in light wind" : " with the wind blowing " + w) });
      }
    }
    var N = all.nfl && all.nfl.wx;
    if (N && N.games && N.games.length) {
      var FN = F.nfl, nKey = function (g) { var s = String(g.sortTime || ""); return s.slice(0, 10) + " " + s.slice(10, 15); };
      var b2 = best(N.games.filter(function (g) { return !g.dome && soon(nKey(g), 100); }), function (g) {
        var dAway = Math.max(0, (mins(nKey(g)) - nowM) / 1440); return (g.wind || 0) * 1.1 + (g.rain >= 40 ? 6 : 0) + (nKey(g).slice(0, 10) === today ? 4 : 0) - dAway * 2; });
      if (b2) {
        var n = b2.g, calm = !isNum(n.wind) || n.wind < 4;
        out.push({ k: "nfl", s: b2.s, spec: { sport: "nfl", g: n }, venue: FN.venue(n), match: FN.name(n.away) + " at " + FN.name(n.home) + " · " + (n.day || "") + " " + n.time,
          chips: [windChip(calm ? "Light wind" : n.wind + " mph · " + FN.axis(n), calm), tempChip(n.temp, "at kickoff"), rainChip(n.rain)].filter(Boolean),
          cap: "Wind drawn at its forecast angle to the field. The forecast gives the angle, not which end it blows toward.", href: D.u("/nfl/") + "#g=" + encodeURIComponent(n.id),
          label: "3D view of " + FN.venue(n) });
      }
    }
    var C = all.cfb && all.cfb.wx;
    if (C && C.games && C.games.length) {
      var cKey = function (g) { var d = Date.parse(g.sortTime || ""); return isNaN(d) ? "" : etKey(new Date(d)); };
      var b3 = best(C.games.filter(function (g) { return !g.dome && soon(cKey(g), 100); }), function (g) {
        var dAway = Math.max(0, (mins(cKey(g)) - nowM) / 1440); return (g.wind || 0) + (g.rain >= 40 ? 6 : 0) + (cKey(g).slice(0, 10) === today ? 4 : 0) - dAway * 2 - (g.fcs ? 3 : 0); });
      if (b3) {
        var c = b3.g, cc = !isNum(c.wind) || c.wind < 3, stad = String(c.stadium || "").split("·")[0].trim();
        out.push({ k: "cfb", s: b3.s, spec: { sport: "cfb", g: c }, venue: stad, match: c.away + " at " + c.home + " · " + (c.day || "") + " " + (c.time || ""),
          chips: [windChip(cc ? "Light wind" : c.wind + " mph" + (c.windDir != null ? " from the " + D.compass(c.windDir) : ""), cc), tempChip(c.temp, "at kickoff"), rainChip(c.rain)].filter(Boolean),
          cap: "Field drawn north–south with the wind by compass: we don't have each stadium's orientation.", href: D.u("/cfb/") + "#g=" + encodeURIComponent(c.id),
          label: "3D view of " + stad });
      }
    }
    var R = all.nascar && all.nascar.wx, rc = R && R.race;
    if (rc && rc.shape && /^(oval|flat|paperclip|bullring|trioval|quadoval|dshape|egg|dogleg)$/.test(rc.shape.kind || "")) {
      var raceDay = rc.day === D.longDate(today);
      out.push({ k: "nascar", s: (raceDay ? 14 : rc.inWindow ? 5 : 1) + (rc.wind || 0) * 0.4, spec: { sport: "nascar", g: rc }, venue: rc.track, match: rc.name + " · " + String(rc.day || "").split(",")[0] + " " + (rc.time || ""),
        chips: rc.inWindow ? [tempChip(rc.temp, rc.temp >= 88 ? "· hot track" : "at the green flag"), '<span class="chip">' + D.wx("wind") + rc.wind + " mph, gusts " + rc.gust + "</span>", rainChip(rc.rain)].filter(Boolean) : ['<span class="chip">Race-day forecast not in range yet</span>'],
        cap: "Drawn from the track's layout, length and banking. The forecast has no wind direction, so wind shows in the flag.", href: D.u("/nascar/"),
        label: "3D view of " + rc.track });
    }
    var P = all.pga && all.pga.wx, ev = P && P.event;
    if (ev && ev.hole) {
      var rd = null, r1 = /^(\d{4})-(\d{2})-(\d{2})/.exec(ev.r1 || "");
      (P.rounds || []).forEach(function (r, i) {
        if (rd || !r.inWindow || !r1) return;
        var day = new Date(Date.UTC(+r1[1], +r1[2] - 1, +r1[3] + i, 12)).toISOString().slice(0, 10);
        if (day >= today) rd = { r: r, today: day === today };
      });
      out.push({ k: "pga", s: rd ? (rd.today ? 6 : 3) + (rd.r.wind || 0) * 0.5 : 1, spec: { sport: "pga", g: rd ? { wind: rd.r.wind, gust: rd.r.gust, rain: rd.r.rain } : { wind: 6 }, event: ev },
        venue: "No. " + ev.hole.n + " at " + ev.course, match: ev.name + " · par " + ev.hole.par + ", " + ev.hole.yds + " yards",
        chips: rd ? ['<span class="chip chip--cyan">' + D.wx("wind") + esc(rd.r.name.split(" · ")[0]) + ": " + rd.r.wind + " mph, gusts " + rd.r.gust + "</span>"] : ['<span class="chip">Round forecasts not in range yet</span>'],
        cap: "Drawn from the hole's par, length, dogleg and water: an illustration, not a survey. The flag shows wind speed.", href: D.u("/pga/"),
        label: "3D illustration of hole " + ev.hole.n + " at " + ev.course });
    }
    return out.sort(function (a, b) { return b.s - a.s; });
  }

  window.H = { load: load, status: status, pickCard: pickCard, recordLine: recordLine, watchOf: watchOf, watchItem: watchItem, featured: featured };
})();
