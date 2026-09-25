/* DFSRADAR · MLB renderers shared by the MLB weather page and the MLB props desk.
 *   M.card(g, ctx)      one game card (Roth-style: four big numbers + the hours around first pitch)
 *   M.detail(g, ctx)    the full game view (sheet)          -> html; call M.afterDetail(root, g) once it's in the DOM
 *   M.gameProps(g, ctx) props in this game (PRO rows, the free #1 if it's here)
 * ctx = { d: /data.json, pd: /pro/data.json|null, member: bool, freeKey: "player|game" }
 */
(function () {
  "use strict";
  var D = window.DR, F = window.F, esc = D.esc, isNum = D.isNum;
  var FM = F.mlb;

  function teams(g) { return esc(FM.name(g.away)) + ' <span class="at">at</span> ' + esc(FM.name(g.home)); }
  function where(g) { return esc(g.park) + (FM.city(g.home) ? " · " + esc(FM.city(g.home)) : ""); }
  function pk(g) { return esc(FM.park(g)); }
  function hrTone(v) { return !isNum(v) ? "dim" : v >= 5 ? "good" : v <= -5 ? "cool" : "muted"; }

  function hourRows(detail) {
    var rows = [
      { k: "Rain", f: function (h) { return isNum(h.rain) ? h.rain + "%" : null; }, cls: function (h) { return D.rainCls(h.rain); } },
      { k: "Temp", f: function (h) { return isNum(h.t) ? h.t + "°" : null; } },
      { k: "Wind", f: function (h) { return isNum(h.w) ? h.w + (detail ? " mph" : "") : null; } },
      { k: "Dir", f: function (h) { return h.dir || null; } }
    ];
    if (detail) {
      rows.push({ k: "Dew pt", f: function (h) { return isNum(h.dew) ? h.dew + "°" : null; } });
      rows.push({ k: "Humidity", f: function (h) { return isNum(h.rh) ? h.rh + "%" : null; } });
    }
    return rows;
  }

  function delayChip(g) {
    var dl = g.delay && FM.delay[g.delay.level];
    return dl ? '<span class="chip chip--' + dl[1] + '">' + dl[0] + "</span>" : "";
  }

  /* ------------------------------------------------------------ card */
  function card(g, ctx) {
    var started = FM.started(ctx.d, g);
    var head = '<div class="gc__h"><div><div class="gc__teams">' + teams(g) + '</div><div class="gc__where">' + where(g) + "</div></div>" +
      '<div class="gc__when"><div class="t">' + esc(g.time) + '</div><div class="l">' + (started ? "Underway" : "First pitch") + "</div></div></div>";
    if (g.dome) {
      return '<article class="gc gc--dome" id="g-' + esc(g.id) + '" data-id="' + esc(g.id) + '">' + head +
        '<div class="gc__impact" style="border-top:1px solid var(--line2)"><div class="row" style="gap:14px">' + D.parkWind(0, 0, true, 44) +
        '<div><div style="font:700 16px/1.3 var(--display)">Roof closed — weather-neutral</div><div class="small dim">Outside: ' +
        (isNum(g.temp) ? g.temp + "°, " : "") + (isNum(g.wind) ? g.wind + " mph" : "") + (g.sky ? ", " + esc(g.sky.toLowerCase()) : "") + "</div></div></div></div>" +
        foot(g, ctx) + "</article>";
    }
    var k = FM.windKind(g);
    var windL = k === "calm" ? "Light wind" : F.cap(FM.wind(g.windLabel, true));
    var dly = g.delay && FM.delay[g.delay.level];
    var rainL = dly ? dly[0] + (isNum(g.delay.pct) && g.delay.pct > (g.rain || 0) ? " · peaks " + g.delay.pct + "%" : "") : "Rain chance";
    var rainCls = g.delay && FM.delay[g.delay.level] ? FM.delay[g.delay.level][1] : "";
    var hrOk = isNum(g.hr) && (g.sample || 0) >= 5;
    var tiles =
      tile('<span class="ico" aria-hidden="true">' + D.sky(g) + "</span>", g.temp + "°", g.sky ? esc(g.sky) : "At first pitch") +
      tile(D.parkWind(g.windAngle, g.wind, false, 52), (isNum(g.wind) ? g.wind : "—") + "<small>mph</small>", esc(windL), k === "out" && g.wind >= 8 ? "good" : "") +
      tile('<span class="ico" aria-hidden="true">' + D.wx("drop") + "</span>", (isNum(g.rain) ? g.rain : "—") + "%", rainL, rainCls) +
      tile('<span class="ico" aria-hidden="true">' + D.wx("ball") + "</span>", hrOk ? '<span class="' + hrTone(g.hr) + '">' + D.signed(g.hr, 0, "%") + "</span>" : "—",
        hrOk ? "HR in weather like this" : "Too little history");
    var chips = [];
    if (started) chips.push('<span class="chip">Underway</span>');
    if (g.windFx && /HIGH|EXTREME/.test(g.windFx.rating) && (k === "out" || k === "in") && g.wind >= 8) chips.push('<span class="chip" title="How much wind moves home runs at this park, from every game here since 2015">Wind-sensitive park</span>');
    var lean = g.ouLean;
    if (lean && g.ou && isNum(g.total)) chips.push('<span class="chip chip--' + (lean === "over" ? "good" : "cool") + '" title="Share of similar-weather games here that went ' + lean + ' today\'s total">' +
      F.cap(lean) + " " + g.total + " in " + (lean === "over" ? g.ou.over : g.ou.under) + "% of similar games</span>");
    return '<article class="gc" id="g-' + esc(g.id) + '" data-id="' + esc(g.id) + '">' + head +
      '<div class="gc__tiles">' + tiles + "</div>" +
      D.hourly(g.hourly || [], hourRows(false)) +
      (chips.length ? '<div class="gc__impact"><div class="chips">' + chips.join("") + "</div></div>" : "") +
      foot(g, ctx) + "</article>";
  }
  function tile(ico, v, l, lcls) {
    return '<div class="gc__tile">' + ico + '<div style="min-width:0"><div class="v">' + v + '</div><div class="l ' + (lcls || "") + '">' + l + "</div></div></div>";
  }
  function foot(g, ctx) {
    var n = ctx.pd ? propCount(g, ctx.pd) : 0;
    return '<div class="gc__foot"><button class="dr-link" type="button" data-open="' + esc(g.id) + '">Full forecast &amp; history →</button>' +
      (n ? '<a class="small dim" href="' + D.u("/props/mlb/") + "#game=" + encodeURIComponent(g.away + "@" + g.home) + '">' + n + " priced props</a>" :
        (g.sample ? '<span class="small dim">' + g.sample + " similar games</span>" : "")) + "</div>";
  }

  /* ------------------------------------------------------------ PRO join */
  function proGame(g, pd) {
    if (!pd || !pd.games) return null;
    for (var i = 0; i < pd.games.length; i++) if (pd.games[i].gamePk && pd.games[i].gamePk === g.gamePk) return pd.games[i];
    return null;
  }
  function batters(pg) {
    var out = [];
    if (!pg || !pg.lineup) return out;
    Object.keys(pg.lineup).forEach(function (t) { (pg.lineup[t] || []).forEach(function (b) { out.push(b); }); });
    out.sort(function (a, b) { return (b.prob || 0) - (a.prob || 0); });
    return out;
  }
  function kFor(pg, pd) {
    if (!pg || !pd || !pd.kprops) return [];
    return pd.kprops.filter(function (k) { return k.pitcher === pg.spAway || k.pitcher === pg.spHome; });
  }
  function propCount(g, pd) {
    var pg = proGame(g, pd);
    if (!pg) return 0;
    return batters(pg).filter(function (b) { return D.validOdds(b.price); }).length + kFor(pg, pd).filter(function (k) { return isNum(k.line); }).length;
  }

  /* ------------------------------------------------------------ detail */
  function statTile(v, l, s) { return '<div class="stat"><div class="stat__v">' + v + '</div><div class="stat__l">' + l + "</div>" + (s ? '<div class="stat__s">' + s + "</div>" : "") + "</div>"; }

  function detail(g, ctx) {
    var k = FM.windKind(g);
    var h = [];
    h.push('<div class="sec"><div class="ph__eyebrow" style="margin-bottom:8px">' + esc(g.time) + " · " + where(g) + "</div>" +
      '<h2 style="font-size:clamp(24px,3vw,32px)">' + teams(g) + "</h2>" +
      '<div class="chips mt12">' + (g.dome ? '<span class="chip">Roof closed</span>' : "") + delayChip(g) +
      (g.windFx ? '<span class="chip">Park wind factor: ' + esc(g.windFx.rating.toLowerCase()) + "</span>" : "") +
      (g.tempFx ? '<span class="chip">Park heat factor: ' + esc(g.tempFx.rating.toLowerCase()) + "</span>" : "") + "</div></div>");

    /* conditions */
    h.push('<div class="sec"><div class="sec__h"><h3 class="sec__title">At first pitch</h3></div><div class="stats">' +
      statTile(D.sky(g) + g.temp + "°", "Temperature", esc(g.sky || "")) +
      statTile((isNum(g.wind) ? g.wind : "—") + "<small>mph</small>", "Wind", g.dome ? "Roof closed" : esc(F.cap(FM.wind(g.windLabel))) + (g.dir ? " (from " + esc(g.dir) + ")" : "")) +
      statTile((isNum(g.rain) ? g.rain : "—") + "<small>%</small>", "Rain chance", g.delay && FM.delay[g.delay.level] ? FM.delay[g.delay.level][0] + (isNum(g.delay.pct) ? " — peaks " + g.delay.pct + "% in the game window" : "") : "No delay concern") +
      statTile((isNum(g.dew) ? g.dew : "—") + "°", "Dew point", isNum(g.rh) ? g.rh + "% humidity" : "") +
      statTile((isNum(g.pres) ? g.pres : "—") + "<small>hPa</small>", "Pressure", isNum(g.cloud) ? g.cloud + "% cloud cover" : "") +
      "</div></div>");

    /* wind + 3D */
    if (!g.dome) {
      var windTxt = k === "calm" ? "Barely a breeze — wind won't be a factor." :
        k === "out" ? g.wind + " mph blowing " + FM.wind(g.windLabel) + " — it helps fly balls carry." :
        k === "in" ? g.wind + " mph blowing " + FM.wind(g.windLabel) + " — it knocks fly balls down." :
        g.wind + " mph blowing " + FM.wind(g.windLabel) + " — mostly across the field.";
      var fx = g.windFx ? " At " + pk(g) + ", 10 mph blowing straight out has " + (g.windFx.pct10 >= 0 ? "added" : "cut") + " about " + Math.abs(g.windFx.pct10) +
        "% to home runs historically (" + esc(g.windFx.rating.toLowerCase()) + " wind factor)." : "";
      h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">Wind at ' + pk(g) + '</h3><p class="sec__sub">' + esc(windTxt) + fx + "</p></div>" +
        D.btn3d("View in 3D") + "</div>" +
        '<div class="card card--flat" style="padding:18px;display:flex;align-items:center;justify-content:center;min-height:220px;position:relative;overflow:hidden" data-3d-box>' +
        '<div data-flat style="width:100%;display:flex;justify-content:center">' + D.parkWindBig(g.windAngle, g.wind, false) + '</div></div></div>');
    }

    /* hourly */
    h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">Hour by hour</h3><p class="sec__sub">First-pitch hour highlighted.</p></div></div>' +
      '<div class="card card--flat" style="padding:10px 14px">' + D.hourly(g.hourly || [], hourRows(true), { full: true }) + "</div></div>");

    /* history */
    if (!g.dome && (g.sample || 0) > 0) {
      var parts = '<div class="card card--flat card--pad"><div class="label" style="margin-bottom:14px">Vs. this park\'s normal · ' + D.plural(g.sample, "similar-weather game") + "</div>" +
        D.impact("Home runs", g.hr) + D.impact("Runs", g.runs) + D.impact("Strikeouts", g.ks) +
        '<p class="small dim mt16">Games here within ' + esc(g.note || "a close weather window") + " of today's forecast, since " + ((ctx.d && ctx.d.seasons && ctx.d.seasons[0]) || 2015) + ". " +
        (isNum(g.hrGm) && isNum(g.hrPark) ? g.hrGm.toFixed(1) + " HR per game in those games vs " + g.hrPark.toFixed(1) + " normally." : "") + "</p></div>";
      var tot = "";
      if (g.ou && isNum(g.total)) {
        tot = '<div class="card card--flat card--pad"><div class="label" style="margin-bottom:14px">Today\'s total ' + g.total + (g.lineSource === "book" ? " (books)" : " (estimated)") + "</div>" +
          '<div class="row" style="gap:18px;align-items:flex-end">' +
          '<div class="stat"><div class="stat__v good">' + g.ou.over + '%</div><div class="stat__l">went over</div></div>' +
          '<div class="stat"><div class="stat__v cool">' + g.ou.under + '%</div><div class="stat__l">went under</div></div>' +
          (g.ou.push ? '<div class="stat"><div class="stat__v dim">' + g.ou.push + '%</div><div class="stat__l">push</div></div>' : "") + "</div>" +
          '<p class="small dim mt16">' + (g.ouLean ? "The similar games' median total (" + g.ouMedian + ") clears the line by a full run — an " + g.ouLean + " lean." :
            "No lean — the similar games' median total (" + (isNum(g.ouMedian) ? g.ouMedian : "—") + ") sits within a run of the line.") + "</p></div>";
      }
      var vsLg = g.mlb ? '<div class="card card--flat card--pad"><div class="label" style="margin-bottom:14px">Vs. the MLB average</div>' +
        D.impact("Home runs", g.mlb.hr) + D.impact("Runs", g.mlb.runs) + D.impact("Strikeouts", g.mlb.ks) +
        '<p class="small dim mt16">Park and weather together, against a league-average game.</p></div>' : "";
      h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">What weather like this has meant here</h3>' +
        '<p class="sec__sub">Not a forecast of tonight\'s score — what actually happened at this park in games played in similar conditions.</p></div></div>' +
        '<div class="grid g3">' + parts + tot + vsLg + "</div>" + rainBlock(g) + "</div>");
    }

    /* matchup in this weather */
    var mu = matchup(g);
    if (mu) h.push(mu);

    /* props in this game */
    h.push('<div class="sec" data-game-props>' + gameProps(g, ctx) + "</div>");

    /* similar games */
    if (g.matches && g.matches.length) {
      var rows = g.matches.map(function (m) {
        var dd = String(m.d || "");
        var date = dd.length === 8 ? dd.slice(4, 6) + "/" + dd.slice(6, 8) + "/" + dd.slice(0, 4) : esc(dd);
        return "<tr><td>" + date + '</td><td class="num">' + m.t + '°</td><td class="num">' + m.w + ' mph</td><td class="num">' + m.r + '</td><td class="num">' + m.hr + "</td>" +
          '<td class="num">' + (m.p ? D.pct(m.p * 100, 0) : "—") + "</td></tr>";
      }).join("");
      h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">The similar games</h3><p class="sec__sub">' +
        (g.sample > g.matches.length ? "The " + g.matches.length + " most recent of " + g.sample + " matches." : "Every match on file.") + "</p></div></div>" +
        '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th class="num">Temp</th><th class="num">Wind</th><th class="num">Runs</th><th class="num">HR</th><th class="num">Rain</th></tr></thead><tbody>' +
        rows + "</tbody></table></div></div>");
    }
    return h.join("");
  }

  function rainBlock(g) {
    if (g.dome || !isNum(g.rain) || g.rain < 20 || !g.rainHist || !g.rainHist.wet) return "";
    var r = g.rainHist;
    return '<div class="note note--warn mt16">' + D.IC.warn + "<div><b>" + g.rain + "% chance of rain at first pitch.</b> In " + r.wet.n + " wet games here, teams averaged " +
      r.wet.r.toFixed(1) + " runs and " + r.wet.hr.toFixed(1) + " HR, vs " + r.dry.r.toFixed(1) + " and " + r.dry.hr.toFixed(1) + " in dry games" +
      (r.wetOver != null ? " — " + r.wetOver + "% of wet games went over." : ".") + "</div></div>";
  }

  function matchup(g) {
    var P = g.pitchers || {}, parts = [];
    var prow = function (side) {
      var p = P[side];
      if (!p || !p.name) return "";
      var s = p.sim, a = p.all || {};
      var cell = function (sv, av, d) {
        if (!s || !isNum(sv)) return '<td class="num">' + (isNum(av) ? av.toFixed(d) : "—") + "</td>";
        return '<td class="num"><b>' + sv.toFixed(d) + '</b> <span class="dim">/ ' + (isNum(av) ? av.toFixed(d) : "—") + "</span></td>";
      };
      return '<tr><td class="who">' + esc(p.name) + "<small>" + esc(FM.name(g[side])) + " · " + (s ? s.n + " starts in similar weather" : "no similar-weather starts") + "</small></td>" +
        cell(s && s.k9, a.k9, 1) + cell(s && s.hr9, a.hr9, 2) + cell(s && s.era, a.era, 2) + "</tr>";
    };
    var pr = prow("away") + prow("home");
    if (pr) parts.push('<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Starting pitcher</th><th class="num">K/9</th><th class="num">HR/9</th><th class="num">ERA</th></tr></thead><tbody>' + pr +
      '</tbody></table><div class="tbl-foot"><b>Bold</b> = in similar weather · grey = all starts on file.</div></div>');
    var mv = g.mvp || {}, bats = [];
    ["away", "home"].forEach(function (side) {
      var m = mv[side];
      if (!m || !m.name) return;
      bats.push('<div class="factor"><div class="k">' + esc(FM.name(g[side])) + " · best bat in this weather</div>" +
        '<div class="v" style="font-size:17px">' + esc(m.name) + "</div>" +
        '<div class="s">' + (isNum(m.slg) ? m.slg.toFixed(3).replace(/^0/, "") : "—") + " SLG in weather like this (" + (isNum(m.allSlg) ? m.allSlg.toFixed(3).replace(/^0/, "") : "—") +
        " overall) · " + m.hr + " HR in " + m.ab + " AB</div></div>");
    });
    if (bats.length) parts.push('<div class="factors mt16" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">' + bats.join("") + "</div>");
    var u = g.ump;
    if (u && u.name) {
      parts.push('<div class="note mt16">' + D.IC.info + "<div><b>Behind the plate: " + esc(u.name) + ".</b> " + (u.n ? u.n + " games on file · " : "") +
        (isNum(u.dHr) ? "HR " + D.signed(u.dHr, 0, "%") + " vs league" : "") + (isNum(u.dR) ? " · runs " + D.signed(u.dR, 0, "%") : "") + (isNum(u.dSo) ? " · strikeouts " + D.signed(u.dSo, 0, "%") : "") + ".</div></div>");
    }
    if (!parts.length) return "";
    return '<div class="sec"><div class="sec__h"><div><h3 class="sec__title">The matchup in this weather</h3><p class="sec__sub">How today\'s starters and hitters have done when it looked like this.</p></div></div>' + parts.join("") + "</div>";
  }

  /* ------------------------------------------------------------ props in this game */
  function gameProps(g, ctx) {
    var head = '<div class="sec__h"><div><h3 class="sec__title">Props in this game</h3><p class="sec__sub">Our number vs the books\' number — the books\' prices as last pulled.</p></div>' +
      '<a class="sec__more" href="' + D.u("/props/mlb/") + "#game=" + encodeURIComponent(g.away + "@" + g.home) + '">Open in MLB props →</a></div>';
    if (!ctx.pd) return head + '<div class="note">' + D.IC.info + "<div>Props load with the day's PRO card — check back after the morning build.</div></div>";
    var pg = proGame(g, ctx.pd);
    if (!pg) return head + '<div class="note">' + D.IC.info + "<div>No props posted for this game yet.</div></div>";
    var bs = batters(pg).filter(function (b) { return D.validOdds(b.price) || b.prob >= 12; }).slice(0, 8);
    var ks = kFor(pg, ctx.pd);
    var env = '<div class="stats" style="margin-bottom:16px">' +
      statTile(isNum(pg.expHr) ? pg.expHr.toFixed(2) : "—", "Expected HR", isNum(pg.vsPark) ? D.signed(pg.vsPark, 0, "%") + " vs park normal" : "") +
      (pg.runs && isNum(pg.runs.total) ? statTile(pg.runs.total.toFixed(1), "Our run total", isNum(pg.runs.line) ? "Books: " + pg.runs.line + (pg.runs.lean ? " · lean " + pg.runs.lean.toLowerCase() : "") : "") : "") +
      (pg.ump ? statTile('<span style="font-size:20px">' + esc(pg.ump) + "</span>", "Plate umpire", isNum(pg.umpMult) ? "HR " + D.signed((pg.umpMult - 1) * 100, 0, "%") + " vs league" + (pg.umpN ? " · " + pg.umpN + " games" : "") : "") : "") + "</div>";
    if (!ctx.member) {
      var free = bs.filter(function (b) { return ctx.freeKey && ctx.freeKey === b.player + "|" + b.game; })[0];
      var n = bs.length + ks.length;
      var t = free ? '<div class="tbl-wrap"><table class="tbl"><tbody>' + hrRow(free, true) + "</tbody></table>" + D.lockbar({ count: n - 1, what: "more prop" }) + "</div>"
        : '<div class="tbl-wrap">' + D.lockbar({ title: n ? D.plural(n, "prop") + " priced in this game — unlock with PRO" : "Unlock this game's props with PRO" }) + "</div>";
      return head + env + t;
    }
    var rows = bs.map(function (b) { return hrRow(b, false); }).join("");
    var krows = ks.map(function (k) {
      return '<tr><td class="who">' + esc(k.pitcher) + "<small>" + esc(k.team) + " vs " + esc(k.opp) + "</small></td>" +
        '<td class="num"><b>' + D.fixed(k.proj, 1) + '</b> <span class="dim">K</span></td>' +
        '<td class="num">' + (isNum(k.line) ? k.line + ' <span class="dim">o' + D.odds(k.over) + " / u" + D.odds(k.under) + "</span>" : '<span class="dim">no line</span>') + "</td>" +
        '<td class="num">' + (isNum(k.diff) ? '<span class="edge ' + (k.diff >= 0.5 ? "edge--pos" : k.diff <= -0.5 ? "edge--neg" : "edge--flat") + '">' + D.signed(k.diff, 1) + "</span>" : "—") + "</td></tr>";
    }).join("");
    return head + env +
      (rows ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Hitter · home run</th><th class="num">Our chance</th><th class="num">Books</th><th class="num">Edge</th></tr></thead><tbody>' + rows + "</tbody></table></div>" : "") +
      (krows ? '<div class="tbl-wrap mt16"><table class="tbl"><thead><tr><th>Pitcher · strikeouts</th><th class="num">Our projection</th><th class="num">Books\' line</th><th class="num">Diff</th></tr></thead><tbody>' + krows + "</tbody></table></div>" : "");
  }
  function hrRow(b, isFree) {
    return '<tr><td class="who">' + esc(b.player) + (isFree ? ' <span class="chip chip--free">FREE PICK</span>' : "") + "<small>" + esc(b.team) + (b.order ? " · bats " + b.order : "") + " · vs " + esc(b.sp || "TBD") + "</small></td>" +
      '<td class="num"><b>' + D.pct(b.prob) + "</b></td>" +
      '<td class="num">' + (D.validOdds(b.price) ? D.odds(b.price) + ' <span class="dim">' + D.pct(b.implied) + "</span>" : '<span class="dim">no price</span>') + "</td>" +
      '<td class="num">' + (isNum(b.edge) ? '<span class="edge ' + (b.edge >= 2 ? "edge--pos" : b.edge <= -2 ? "edge--neg" : "edge--flat") + '">' + D.signed(b.edge, 1) + "</span>" : "—") + "</td></tr>";
  }

  /* ------------------------------------------------------------ 3D view */
  var v3 = null;
  function afterDetail(root, g) {
    var btn = root.querySelector("[data-3d]"), box = root.querySelector("[data-3d-box]");
    if (!btn || !box) return;
    var k = FM.windKind(g), park = FM.park(g), w = FM.wind(g.windLabel);
    v3 = D.view3d({ auto: true, onLabel: "Show the diagram", btn: btn, box: box, flat: box.querySelector("[data-flat]"), spec: { sport: "mlb", g: g },
      chips: ['<span class="chip' + (k === "calm" ? "" : " chip--cyan") + '">' + D.wx("wind") + (k === "calm" ? "Light wind" : g.wind + " mph " + esc(w)) + "</span>",
        '<span class="chip">' + (isNum(g.temp) ? g.temp + "°" : "") + " at first pitch</span>"],
      cap: "Wind drawn against " + park + "'s real field layout at the forecast angle. Walls shown 1.5× taller so they read.",
      label: "3D view of " + park + (k === "calm" ? " in light wind" : " with the wind blowing " + w) });
  }
  function dispose() { if (v3) v3.close(); v3 = null; }

  window.M = { card: card, detail: detail, afterDetail: afterDetail, dispose: dispose, gameProps: gameProps, proGame: proGame, batters: batters, kFor: kFor, propCount: propCount, hrRow: hrRow };
})();
