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

  window.H = { load: load, status: status, pickCard: pickCard, recordLine: recordLine, watchOf: watchOf, watchItem: watchItem };
})();
