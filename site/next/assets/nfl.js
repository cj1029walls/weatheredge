/* DFSRADAR · NFL renderers shared by the NFL weather page and the NFL props desk.
 *   N.card(g, ctx) · N.detail(g, ctx) · N.gameProps(g, ctx) · N.splits(edge, cond)
 * ctx = { d: /nfl/data.json, pro: /pro/nfl.json|null, member: bool, freeKey }
 */
(function () {
  "use strict";
  var D = window.DR, F = window.F, esc = D.esc, isNum = D.isNum, FN = F.nfl;

  function teams(g) { return esc(FN.name(g.away)) + ' <span class="at">at</span> ' + esc(FN.name(g.home)); }
  function where(g) { var c = FN.city(g); return esc(FN.venue(g)) + (c ? " · " + esc(c) : g.neutral ? " · " + esc(String(g.stadium).split("·")[1] || "").trim() : ""); }
  function when(g) { return esc((g.day || "") + " · " + g.time); }
  function axWord(ax) { return ax == null ? "" : ax >= 60 ? "cross" : ax <= 30 ? "axis" : "angled"; }
  function statTile(v, l, s) { return '<div class="stat"><div class="stat__v">' + v + '</div><div class="stat__l">' + l + "</div>" + (s ? '<div class="stat__s">' + s + "</div>" : "") + "</div>"; }
  function tile(ico, v, l, lcls) { return '<div class="gc__tile">' + ico + '<div style="min-width:0"><div class="v">' + v + '</div><div class="l ' + (lcls || "") + '">' + l + "</div></div></div>"; }

  function hourRows(detail) {
    var r = [
      { k: "Rain", f: function (h) { return isNum(h.rain) ? h.rain + "%" : null; }, cls: function (h) { return D.rainCls(h.rain); } },
      { k: "Temp", f: function (h) { return isNum(h.t) ? h.t + "°" : null; } },
      { k: "Wind", f: function (h) { return isNum(h.w) ? h.w + (detail ? " mph" : "") : null; } },
      { k: "Vs field", f: function (h) { return h.ax == null ? null : axWord(h.ax); } }
    ];
    if (detail) r.push({ k: "Humidity", f: function (h) { return isNum(h.rh) ? h.rh + "%" : null; } });
    return r;
  }

  function proGame(g, pro) {
    if (!pro || !pro.games) return null;
    for (var i = 0; i < pro.games.length; i++) if (pro.games[i].away === g.away && pro.games[i].home === g.home) return pro.games[i];
    return null;
  }
  function leansFor(g, pro) {
    if (!pro || !pro.leans) return [];
    var key = g.away + "@" + g.home;
    return F.nfl.picks(pro).filter(function (p) { return p.game === key; });
  }

  /* ------------------------------------------------------------ card */
  function card(g, ctx) {
    var head = '<div class="gc__h"><div><div class="gc__teams">' + teams(g) + '</div><div class="gc__where">' + where(g) + "</div></div>" +
      '<div class="gc__when"><div class="t">' + esc(g.time) + '</div><div class="l">' + esc(g.day || "Kickoff") + "</div></div></div>";
    var n = leansFor(g, ctx.pro).length;
    var foot = '<div class="gc__foot"><button class="dr-link" type="button" data-open="' + esc(g.id) + '">Full forecast, splits &amp; history →</button>' +
      (n ? '<a class="small dim" href="' + D.u("/props/nfl/") + "#game=" + encodeURIComponent(g.away + "@" + g.home) + '">' + D.plural(n, "lean") + "</a>" : "") + "</div>";
    if (g.dome) {
      return '<article class="gc gc--dome" id="g-' + esc(g.id) + '">' + head +
        '<div class="gc__impact" style="border-top:1px solid var(--line2)"><div class="row" style="gap:14px">' + D.fieldWind(0, 0, true, 44) +
        '<div><div style="font:700 16px/1.3 var(--display)">Roof closed — weather-neutral</div><div class="small dim">' +
        (isNum(g.ptsGm) && g.sample ? g.ptsGm + " points per game indoors here (" + g.sample + " games)" : "Indoor game") + "</div></div></div></div>" + foot + "</article>";
    }
    var dl = g.delay && FN.delay[g.delay.level];
    var rainL = dl ? dl[0] : "Rain chance";
    var ouOk = g.ou && g.ou.n >= 8;
    var tiles =
      tile('<span class="ico" aria-hidden="true">' + D.sky(g) + "</span>", g.temp + "°", g.sky ? esc(g.sky) : "At kickoff") +
      tile(D.fieldWind(g.ax, g.wind, false, 52), (isNum(g.wind) ? g.wind : "—") + "<small>mph</small>", esc(F.cap(FN.axis(g))), g.wind >= 15 ? "warn" : "") +
      tile('<span class="ico" aria-hidden="true">' + D.wx("drop") + "</span>", (isNum(g.rain) ? g.rain : "—") + "%", rainL, dl ? dl[1] : "") +
      tile('<span class="ico" aria-hidden="true">' + D.wx("football") + "</span>", ouOk ? g.ou.over + "%" : "—", ouOk ? "Overs in similar games" : "Too little history");
    var chips = [];
    ((g.edge && g.edge.badges) || []).forEach(function (b) { chips.push('<span class="chip" title="' + esc(b.txt + (b.rec ? " — " + b.rec : "")) + '">' + esc(F.cap(b.k.toLowerCase())) + " · " + esc(b.team) + "</span>"); });
    if (g.windFx && /HIGH|EXTREME/.test(g.windFx.rating) && g.wind >= 10) chips.push('<span class="chip">Wind-sensitive stadium</span>');
    if (isNum(g.total)) chips.push('<span class="chip">Total ' + g.total + "</span>");
    return '<article class="gc" id="g-' + esc(g.id) + '">' + head + '<div class="gc__tiles">' + tiles + "</div>" + D.hourly(g.hourly || [], hourRows(false)) +
      (chips.length ? '<div class="gc__impact"><div class="chips">' + chips.join("") + "</div></div>" : "") + foot + "</article>";
  }

  /* ------------------------------------------------------------ splits */
  function cond(g) {                               // which splits matter today
    var c = [];
    if (!g.dome && isNum(g.wind) && g.wind >= 12) c.push("windy");
    if (!g.dome && isNum(g.temp) && g.temp < 40) c.push("cold");
    if (!g.dome && isNum(g.temp) && g.temp >= 80) c.push("hot");
    return c;
  }
  var CLAB = { windy: "In wind", cold: "In cold (<40°)", chilly: "Chilly", hot: "In heat" };

  function teamSplits(g) {
    var tw = g.edge && g.edge.teamWx;
    if (!tw) return "";
    var want = cond(g);
    var keys = want.length ? want : ["windy", "cold", "hot"];
    var rows = [g.away, g.home].map(function (t) {
      var w = tw[t];
      if (!w) return "";
      return '<tr><td class="who">' + esc(FN.name(t)) + "<small>" + D.fixed(w.basePpg, 1) + " pts/gm normally · " + w.n + " games</small></td>" +
        keys.map(function (k) {
          var s = w[k];
          if (!s || !s.n) return '<td class="num dim">—</td>';
          return '<td class="num"><b>' + D.fixed(s.ppg, 1) + '</b> <span class="' + (s.delta >= 5 ? "good" : s.delta <= -5 ? "cool" : "dim") + '">' + D.signed(s.delta, 0, "%") + '</span><div class="small dim" style="font-size:11.5px">' + s.n + " games</div></td>";
        }).join("") + "</tr>";
    }).join("");
    return '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Team scoring</th>' + keys.map(function (k) { return '<th class="num">' + CLAB[k] + "</th>"; }).join("") +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>";
  }

  function playerTable(title, obj, cols, want) {
    var names = Object.keys(obj || {});
    if (!names.length) return "";
    var rows = names.map(function (nm) { return { nm: nm, p: obj[nm] }; })
      .sort(function (a, b) { return ((b.p.base || b.p.all || {}).g || (b.p.all || {}).att || 0) - ((a.p.base || a.p.all || {}).g || (a.p.all || {}).att || 0); }).slice(0, 6);
    var key = want[0] || "windy";
    var body = rows.map(function (r) {
      return '<tr><td class="who">' + esc(r.nm) + "<small>" + esc(r.p.team || "") + "</small></td>" + cols.map(function (c) { return '<td class="num">' + c.f(r.p, key) + "</td>"; }).join("") + "</tr>";
    }).join("");
    return '<div class="tbl-wrap mt16"><table class="tbl"><thead><tr><th>' + title + "</th>" + cols.map(function (c) { return '<th class="num">' + c.h(key) + "</th>"; }).join("") +
      "</tr></thead><tbody>" + body + "</tbody></table></div>";
  }
  function splitCell(s, base, fld, d) {
    if (!s || !isNum(s[fld])) return '<span class="dim">—</span>';
    return "<b>" + s[fld].toFixed(d) + '</b> <span class="dim">/ ' + (base && isNum(base[fld]) ? base[fld].toFixed(d) : "—") + "</span>" +
      (isNum(s.delta) ? ' <span class="' + (s.delta >= 5 ? "good" : s.delta <= -5 ? "cool" : "dim") + '">' + D.signed(s.delta, 0, "%") + "</span>" : "") +
      '<div class="small dim" style="font-size:11.5px">' + (s.g || s.att || 0) + (s.att != null && s.g == null ? " att" : " games") + "</div>";
  }
  function players(g) {
    var e = g.edge || {}, want = cond(g);
    var k = want[0] || "windy";
    var out = playerTable("Quarterbacks", e.qbs, [
      { h: function (k) { return "Pass yds/gm · " + (CLAB[k] || k).toLowerCase(); }, f: function (p, k) { return splitCell(p[k], p.base, "ypg", 1); } },
      { h: function () { return "Comp %"; }, f: function (p, k) { return p[k] ? D.fixed(p[k].compPct, 1) + '<span class="dim"> / ' + D.fixed(p.base && p.base.compPct, 1) + "</span>" : '<span class="dim">—</span>'; } }
    ], want) +
      playerTable("Kickers", e.kickers, [
        { h: function (k) { return "FG% · " + (CLAB[k] || k).toLowerCase(); }, f: function (p, k) { var s = p[k]; return s ? "<b>" + s.pct + "%</b>" + ' <span class="dim">(' + s.made + "/" + s.att + ")</span>" : '<span class="dim">—</span>'; } },
        { h: function () { return "Career"; }, f: function (p) { return p.all ? p.all.pct + '% <span class="dim">(' + p.all.att + " att)</span>" : "—"; } },
        { h: function () { return "50+ yds"; }, f: function (p) { return p.long50 ? p.long50.pct + '% <span class="dim">(' + p.long50.att + ")</span>" : '<span class="dim">—</span>'; } }
      ], want) +
      playerTable("Running backs", e.rbs, [
        { h: function (k) { return "Rush yds/gm · " + (CLAB[k] || k).toLowerCase(); }, f: function (p, k) { return splitCell(p[k], p.base, "ypg", 1); } },
        { h: function () { return "Carries/gm"; }, f: function (p, k) { return p[k] ? D.fixed(p[k].attG, 1) + '<span class="dim"> / ' + D.fixed(p.base && p.base.attG, 1) + "</span>" : '<span class="dim">—</span>'; } }
      ], want) +
      playerTable("Receivers", e.wrs, [
        { h: function (k) { return "Rec/gm · " + (CLAB[k] || k).toLowerCase(); }, f: function (p, k) { return splitCell(p[k], p.base, "recG", 1); } },
        { h: function () { return "Rec yds/gm"; }, f: function (p, k) { return p[k] ? D.fixed(p[k].ypg, 1) + '<span class="dim"> / ' + D.fixed(p.base && p.base.ypg, 1) + "</span>" : '<span class="dim">—</span>'; } }
      ], want);
    return out;
  }

  /* ------------------------------------------------------------ detail */
  function detail(g, ctx) {
    var h = [];
    var badges = ((g.edge && g.edge.badges) || []).map(function (b) { return '<span class="chip" title="' + esc(b.rec || "") + '">' + esc(b.txt) + "</span>"; }).join("");
    h.push('<div class="sec"><div class="ph__eyebrow" style="margin-bottom:8px">' + when(g) + " · " + where(g) + "</div>" +
      '<h2 style="font-size:clamp(24px,3vw,32px)">' + teams(g) + "</h2>" +
      '<div class="chips mt12">' + (g.dome ? '<span class="chip">Roof closed</span>' : "") + (isNum(g.total) ? '<span class="chip">Total ' + g.total + "</span>" : "") +
      (g.windFx ? '<span class="chip">Stadium wind factor: ' + esc(g.windFx.rating.toLowerCase()) + "</span>" : "") + badges + "</div></div>");

    h.push('<div class="sec"><div class="sec__h"><h3 class="sec__title">At kickoff</h3></div><div class="stats">' +
      statTile(D.sky(g) + g.temp + "°", "Temperature", esc(g.sky || "")) +
      statTile((isNum(g.wind) ? g.wind : "—") + "<small>mph</small>", "Wind", esc(F.cap(FN.axis(g)))) +
      statTile((isNum(g.rain) ? g.rain : "—") + "<small>%</small>", "Rain chance", g.delay && FN.delay[g.delay.level] ? FN.delay[g.delay.level][0] + (isNum(g.delay.pct) ? " — up to " + g.delay.pct + "%" : "") : "Dry") +
      statTile((isNum(g.dew) ? g.dew : "—") + "°", "Dew point", isNum(g.rh) ? g.rh + "% humidity" : "") +
      statTile((isNum(g.pres) ? g.pres : "—") + "<small>hPa</small>", "Pressure", "") + "</div></div>");

    if (!g.dome) {
      var wtxt = !isNum(g.wind) || g.wind < 4 ? "Barely a breeze." : g.wind + " mph, " + FN.axis(g) + (g.windClass === "cross" ? " — crosswinds hurt kickers and deep throws the most." : g.windClass === "along" ? " — one team gets it at its back each quarter." : ".");
      var fx = g.windFx && isNum(g.windFx.pct10) ? " At " + esc(FN.venue(g)) + ", each extra 10 mph has moved scoring about " + D.signed(g.windFx.pct10, 0, "%") + " historically." : "";
      h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">Wind at ' + esc(FN.venue(g)) + '</h3><p class="sec__sub">' + esc(wtxt) + fx + "</p></div>" + D.btn3d("View in 3D") + "</div>" +
        '<div class="card card--flat" style="padding:18px;display:flex;justify-content:center;overflow:hidden" data-3d-box><div data-flat style="width:100%;display:flex;justify-content:center">' + D.fieldWindBig(g.ax, g.wind, false) + "</div></div></div>");
    }
    h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">Hour by hour</h3><p class="sec__sub">Kickoff hour highlighted.</p></div></div>' +
      '<div class="card card--flat" style="padding:10px 14px">' + D.hourly(g.hourly || [], hourRows(true), { full: true }) + "</div></div>");

    if ((g.sample || 0) > 0) {
      h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">What weather like this has meant here</h3>' +
        '<p class="sec__sub">Games at this stadium in conditions like these, since ' + ((ctx.d && ctx.d.seasons && ctx.d.seasons[0]) || 2015) + " — " + esc(g.note || "a close weather window") + ".</p></div></div>" +
        '<div class="grid g2"><div class="card card--flat card--pad"><div class="label" style="margin-bottom:14px">Scoring vs this stadium\'s normal · ' + D.plural(g.sample, "game") + "</div>" +
        D.impact("Points", g.pts) + '<p class="small dim mt16">' + D.fixed(g.ptsGm, 1) + " points per game in those games vs " + D.fixed(g.ptsStad, 1) + " normally here.</p></div>" +
        (g.ou && g.ou.n ? '<div class="card card--flat card--pad"><div class="label" style="margin-bottom:14px">Against their own closing totals</div><div class="row" style="gap:18px">' +
          '<div class="stat"><div class="stat__v good">' + g.ou.over + '%</div><div class="stat__l">went over</div></div><div class="stat"><div class="stat__v cool">' + g.ou.under + '%</div><div class="stat__l">went under</div></div></div>' +
          '<p class="small dim mt16">Each similar game graded against the total the books closed it at — not today\'s ' + (isNum(g.total) ? g.total : "") + ".</p></div>" : "") + "</div></div>");
    }

    if (g.edge && (g.edge.teamWx || g.edge.qbs)) {
      var want = cond(g);
      h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">The teams and players in this weather</h3><p class="sec__sub">' +
        (want.length ? "Split for today's conditions: " + want.map(function (k) { return (CLAB[k] || k).toLowerCase(); }).join(" and ") + ". Bold = in those conditions; grey = normal." :
          "No weather extreme today — splits shown for wind, cold and heat for reference.") + "</p></div></div>" + teamSplits(g) + players(g) +
        '<p class="small dim mt12">Players listed by games on file for these franchises since ' + ((ctx.d && ctx.d.seasons && ctx.d.seasons[0]) || 2015) + " — check today's active roster.</p></div>");
    }
    var rest = g.edge && g.edge.rest;
    if (rest && isNum(rest.away) && isNum(rest.home)) {
      h.push('<div class="note mt24">' + D.IC.info + "<div><b>Rest:</b> " + esc(FN.name(g.away)) + " " + rest.away + " days, " + esc(FN.name(g.home)) + " " + rest.home + " days." +
        (((g.edge && g.edge.badges) || []).length ? " " + g.edge.badges.map(function (b) { return esc(b.txt) + (b.rec ? " (" + esc(b.rec) + ")" : ""); }).join(" · ") + "." : "") + "</div></div>");
    }
    h.push('<div class="sec" data-game-props>' + gameProps(g, ctx) + "</div>");
    if (g.matches && g.matches.length) {
      var rows = g.matches.map(function (m) {
        var dd = String(m.d || ""), date = dd.length === 8 ? dd.slice(4, 6) + "/" + dd.slice(6, 8) + "/" + dd.slice(0, 4) : esc(dd);
        return "<tr><td>" + date + '</td><td class="num">' + m.t + '°</td><td class="num">' + m.w + " mph" + (m.ax != null ? ' <span class="dim">' + axWord(m.ax) + "</span>" : "") +
          '</td><td class="num">' + m.pts + '</td><td class="num">' + (m.line != null ? m.line : "—") + '</td><td class="num">' + (m.res ? '<span class="res res--' + (m.res === "over" ? "w" : m.res === "under" ? "l" : "p") + '">' + esc(m.res.toUpperCase()) + "</span>" : "—") + "</td></tr>";
      }).join("");
      h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">The similar games</h3><p class="sec__sub">Result against each game\'s own closing total.</p></div></div>' +
        '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th class="num">Temp</th><th class="num">Wind</th><th class="num">Points</th><th class="num">Line</th><th class="num">O/U</th></tr></thead><tbody>' + rows + "</tbody></table></div></div>");
    }
    return h.join("");
  }

  /* ------------------------------------------------------------ props in this game */
  function leanRow(p, isFree) {
    var sideLine = (isNum(p.line) ? " " + p.line : "");
    return '<tr><td class="who">' + esc(p.player) + (isFree ? ' <span class="chip chip--free">FREE PICK</span>' : "") + "<small>" + esc(p.team ? p.team + " · " : "") + esc(p.market) + " · " + esc(p.factor) + "</small></td>" +
      "<td>" + window.P.sideTag(p.side) + '<b class="tnum">' + esc(sideLine) + "</b></td>" +
      '<td class="num">' + (D.validOdds(p.price) ? "<b>" + D.odds(p.price) + "</b>" + bestLine(p) : '<span class="dim">' + (p.side === "WATCH" ? "info" : "no price") + "</span>") + "</td>" +
      '<td class="num">' + (isNum(p.delta) ? '<span class="' + (p.delta >= 5 ? "good" : p.delta <= -5 ? "cool" : "dim") + '">' + D.signed(p.delta, 0, "%") + "</span>" + (p.n ? '<div class="small dim" style="font-size:11.5px">' + p.n + " games</div>" : "") : '<span class="dim">—</span>') + "</td></tr>";
  }
  function bestLine(p) {
    var b = p.raw && p.raw.best;
    if (b && (b.line !== p.line || b.price !== p.price)) return '<div class="small" style="font-size:11.5px;color:var(--good2)">best ' + (p.side === "UNDER" ? "u" : "o") + b.line + " " + D.odds(b.price) + " · " + window.P.bookTag(b.book) + "</div>";
    return p.books ? '<div class="small dim" style="font-size:11.5px">' + D.plural(p.books, "book") + "</div>" : "";
  }
  function gameProps(g, ctx) {
    var head = '<div class="sec__h"><div><h3 class="sec__title">Props in this game</h3><p class="sec__sub">Our weather leans — the books\' line and price as last pulled.</p></div>' +
      '<a class="sec__more" href="' + D.u("/props/nfl/") + "#game=" + encodeURIComponent(g.away + "@" + g.home) + '">Open in NFL props →</a></div>';
    if (!ctx.pro) return head + '<div class="note">' + D.IC.info + "<div>This week's leans aren't posted yet.</div></div>";
    var L = leansFor(g, ctx.pro);
    if (!L.length) return head + '<div class="note">' + D.IC.info + "<div>No leans in this game — the weather and the splits don't line up for a call.</div></div>";
    var thead = "<thead><tr><th>Player · prop</th><th>Lean</th><th class=\"num\">Books</th><th class=\"num\">Split</th></tr></thead>";
    if (!ctx.member) {
      var free = L.filter(function (p) { return ctx.freeKey && ctx.freeKey === p.player + "|" + p.game + "|" + p.k; })[0];
      return head + '<div class="tbl-wrap">' + (free ? '<table class="tbl">' + thead + "<tbody>" + leanRow(free, true) + "</tbody></table>" : "") +
        D.lockbar({ count: free ? L.length - 1 : L.length, what: "lean", title: free ? null : D.plural(L.length, "lean") + " in this game — unlock with PRO" }) + "</div>";
    }
    return head + '<div class="tbl-wrap"><table class="tbl">' + thead + "<tbody>" + L.map(function (p) { return leanRow(p, false); }).join("") + "</tbody></table></div>" +
      '<p class="small dim mt12">' + L.map(function (p) { return "<b>" + esc(p.player) + ":</b> " + esc(p.why); }).join("<br>") + "</p>";
  }

  /* ------------------------------------------------------------ 3D view */
  var v3 = null;
  function afterDetail(root, g) {
    var btn = root.querySelector("[data-3d]"), box = root.querySelector("[data-3d-box]");
    if (!btn || !box) return;
    var calm = !isNum(g.wind) || g.wind < 4;
    v3 = D.view3d({ btn: btn, box: box, flat: box.querySelector("[data-flat]"), spec: { sport: "nfl", g: g },
      chips: ['<span class="chip' + (calm ? "" : " chip--cyan") + '">' + D.wx("wind") + (calm ? "Light wind" : g.wind + " mph · " + esc(FN.axis(g))) + "</span>",
        '<span class="chip">' + (isNum(g.temp) ? g.temp + "°" : "") + " at kickoff</span>"],
      cap: "Wind drawn at its forecast angle to the field. The forecast gives the angle, not which end it blows toward.",
      label: "3D view of " + FN.venue(g) + (calm ? " in light wind" : " with a " + g.wind + " mph wind " + FN.axis(g)) });
  }
  function dispose() { if (v3) v3.close(); v3 = null; }

  window.N = { card: card, detail: detail, afterDetail: afterDetail, dispose: dispose, gameProps: gameProps, leanRow: leanRow, bestLine: bestLine, leansFor: leansFor, proGame: proGame, cond: cond };
})();
