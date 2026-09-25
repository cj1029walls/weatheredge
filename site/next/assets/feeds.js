/* DFSRADAR · feed normalizers shared by the hubs (home, Weather, Props, Record)
 * and the sport pages. Light on purpose: no rendering beyond small strings.
 *
 * Each sport exposes:
 *   F.<sport>.url / F.<sport>.proUrl     where its feeds live (always the live site root)
 *   F.<sport>.watch(data)                weather-watch items, most severe first
 *   F.<sport>.picks(pro, extra)          its prop board, ranked — [0] is the free #1
 *   F.<sport>.record(rec)                headline record numbers
 * Items share one shape so any page can list them together.
 */
(function () {
  "use strict";
  var D = window.DR;
  var isNum = D.isNum;

  /* ============================================================ MLB */
  var MLB = {
    ARI: ["Diamondbacks", "Phoenix, AZ"], ATH: ["Athletics", "West Sacramento, CA"], ATL: ["Braves", "Atlanta, GA"],
    BAL: ["Orioles", "Baltimore, MD"], BOS: ["Red Sox", "Boston, MA"], CHC: ["Cubs", "Chicago, IL"], CIN: ["Reds", "Cincinnati, OH"],
    CLE: ["Guardians", "Cleveland, OH"], COL: ["Rockies", "Denver, CO"], CWS: ["White Sox", "Chicago, IL"], DET: ["Tigers", "Detroit, MI"],
    HOU: ["Astros", "Houston, TX"], KC: ["Royals", "Kansas City, MO"], LAA: ["Angels", "Anaheim, CA"], LAD: ["Dodgers", "Los Angeles, CA"],
    MIA: ["Marlins", "Miami, FL"], MIL: ["Brewers", "Milwaukee, WI"], MIN: ["Twins", "Minneapolis, MN"], NYM: ["Mets", "Queens, NY"],
    NYY: ["Yankees", "Bronx, NY"], PHI: ["Phillies", "Philadelphia, PA"], PIT: ["Pirates", "Pittsburgh, PA"], SD: ["Padres", "San Diego, CA"],
    SEA: ["Mariners", "Seattle, WA"], SF: ["Giants", "San Francisco, CA"], STL: ["Cardinals", "St. Louis, MO"], TB: ["Rays", "St. Petersburg, FL"],
    TEX: ["Rangers", "Arlington, TX"], TOR: ["Blue Jays", "Toronto, ON"], WSH: ["Nationals", "Washington, DC"]
  };
  function mlbName(a) { return (MLB[a] || [a])[0]; }
  function mlbCity(a) { return (MLB[a] || ["", ""])[1]; }

  /* "IN FROM RF" -> "in from right" ; "CROSS L→R" -> "across, left to right" */
  function mlbWind(lbl, short) {
    var s = String(lbl || "").toUpperCase().trim();
    var side = { LF: "left", CF: "center", RF: "right" };
    var m;
    if ((m = /^OUT TO (LF|CF|RF)/.exec(s))) return "out to " + side[m[1]];
    if ((m = /^IN FROM (LF|CF|RF)/.exec(s))) return "in from " + side[m[1]];
    if (/^CROSS L/.test(s)) return short ? "across, L to R" : "across, left to right";
    if (/^CROSS R/.test(s)) return short ? "across, R to L" : "across, right to left";
    if (/CALM/.test(s)) return "calm";
    return s.toLowerCase();
  }
  function cap(s) { s = String(s || ""); return s.charAt(0).toUpperCase() + s.slice(1); }
  function windKind(g) {                       // out · in · cross · calm · roof
    if (g.dome) return "roof";
    if (!isNum(g.wind) || g.wind < 5) return "calm";
    var s = String(g.windLabel || "").toUpperCase();
    return /^OUT/.test(s) ? "out" : /^IN/.test(s) ? "in" : "cross";
  }

  /* ET clock now as HHMM (1305) — to mark games that have started */
  function etHHMM() {
    try {
      var o = {};
      new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
        .formatToParts(new Date()).forEach(function (p) { o[p.type] = p.value; });
      return (+o.hour) * 100 + (+o.minute);
    } catch (e) { return null; }
  }
  function mlbStarted(d, g) {
    if (!d || d.date !== D.todayET()) return d && d.date < D.todayET();
    var now = etHHMM();
    return now != null && isNum(g.sortTime) && now >= g.sortTime;
  }

  var DELAY = { watch: ["Rain watch", "warn"], likely: ["Delay likely", "bad"], severe: ["Postponement risk", "bad"] };

  function parkName(g) { return String(g.park || "").split("·")[0].trim(); }

  /* One watch item per game: its most severe reason leads, the rest ride along. */
  function mlbWatch(d) {
    var out = [];
    if (!d || !d.games) return out;
    d.games.forEach(function (g) {
      if (g.dome) return;
      var game = g.away + " @ " + g.home, pk = parkName(g), R = [];
      var dl = g.delay && DELAY[g.delay.level];
      if (dl) R.push({ sev: g.delay.level === "watch" ? 3 : 4, icon: D.wx("rain"), tone: dl[1], title: dl[0],
        sub: "Rain chance peaks near " + (g.delay.pct != null ? g.delay.pct : g.rain) + "% during the game window at " + pk + ".", short: dl[0].toLowerCase() });
      var k = windKind(g);
      if ((k === "out" || k === "in") && g.wind >= 10) {
        var fx = g.windFx && /HIGH|EXTREME/.test(g.windFx.rating) ? " " + pk + " is one of the parks where wind matters most." : "";
        R.push({ sev: g.wind >= 15 ? 3 : 2, icon: D.wx("wind"), tone: k === "out" ? "good" : "cool", title: g.wind + " mph, " + mlbWind(g.windLabel),
          sub: (k === "out" ? "Carries fly balls toward the seats." : "Knocks fly balls down.") + fx, short: g.wind + " mph " + mlbWind(g.windLabel) });
      } else if (k === "cross" && g.wind >= 18) {
        R.push({ sev: 1, icon: D.wx("wind"), tone: "", title: g.wind + " mph crosswind", sub: "Blowing " + mlbWind(g.windLabel) + " at " + pk + ".", short: g.wind + " mph crosswind" });
      }
      if (isNum(g.temp) && g.temp >= 88) R.push({ sev: 2, icon: D.wx("hot"), tone: "good", title: "Hot one: " + g.temp + "°", sub: "Warm air lets the ball travel.", short: g.temp + "° heat" });
      if (isNum(g.temp) && g.temp <= 50) R.push({ sev: 2, icon: D.wx("cold"), tone: "cool", title: "Cold one: " + g.temp + "°", sub: "Dense, cold air holds fly balls in.", short: g.temp + "° cold" });
      if (isNum(g.hr) && (g.sample || 0) >= 10 && Math.abs(g.hr) >= 20) {
        var up = g.hr > 0;
        R.push({ sev: 1, icon: D.wx(up ? "up" : "down"), tone: up ? "good" : "cool", title: (up ? "Home-run weather: " : "Home-run drag: ") + D.signed(g.hr, 0, "%"),
          sub: "Across " + g.sample + " past games at " + pk + " in weather like this, vs the park's normal.", short: "HR " + D.signed(g.hr, 0, "%") + " in similar weather" });
      }
      if (!R.length) return;
      R.sort(function (a, b) { return b.sev - a.sev; });
      var top = R[0];
      out.push({ sport: "mlb", id: g.id, game: game, when: g.time, sev: top.sev + R.length * 0.1, icon: top.icon, tone: top.tone,
        title: top.title, sub: top.sub, also: R.slice(1).map(function (r) { return r.short; }) });
    });
    out.sort(function (a, b) { return b.sev - a.sev; });
    return out;
  }

  /* HR factor multipliers -> readable chips */
  function mlbFactors(f) {
    if (!f) return [];
    var L = { bat: "Hitter power", wx: "Weather", ump: "Umpire", sp: "Opposing SP", bvp: "Vs this SP" };
    return ["bat", "wx", "sp", "ump"].filter(function (k) { return isNum(f[k]); }).map(function (k) {
      var pctv = Math.round((f[k] - 1) * 100);
      return { k: k, label: L[k], v: f[k], pct: pctv, txt: k === "bat" ? f[k].toFixed(2) + "× lg rate" : D.signed(pctv, 0, "%") };
    });
  }

  /* one normalized pick row from a PRO HR target */
  function mlbHrPick(t, i) {
    return {
      sport: "mlb", rank: i + 1, market: "Home run", marketKey: "hr", side: "YES", player: t.player, team: t.team, opp: t.opp, game: t.game,
      ours: t.prob, oursTxt: D.pct(t.prob), oursLab: "Our HR chance",
      price: t.price, books: t.books, implied: t.implied, fair: t.fair, edge: t.edge, value: !!t.value,
      priceTxt: D.odds(t.price), impliedTxt: isNum(t.implied) ? D.pct(t.implied) : "—",
      edgeTxt: isNum(t.edge) ? D.signed(t.edge, 1, " pts") : "—",
      why: "Batting " + (t.order ? "#" + t.order : "TBD") + " vs " + (t.sp || "TBD") + " · " + (t.seasons || ""),
      factors: mlbFactors(t.f), raw: t
    };
  }
  function mlbPicks(pd) {
    if (!pd || !pd.targets) return [];
    return pd.targets.map(mlbHrPick);
  }
  function mlbRecord(rec) {
    var s = rec && rec.summary;
    if (!s) return null;
    return {
      top1: s.top1, value: s.value, kleans: s.kleans, nights: s.nights, graded: s.graded, cal: s.cal, gameProj: s.gameProj,
      headline: s.value && s.value.n ? D.signed(s.value.units, 2, "u") + " on value flags" : null
    };
  }


  /* ============================================================ NFL */
  var NFL = {
    ARI: ["Cardinals", "Glendale, AZ"], ATL: ["Falcons", "Atlanta, GA"], BAL: ["Ravens", "Baltimore, MD"], BUF: ["Bills", "Orchard Park, NY"],
    CAR: ["Panthers", "Charlotte, NC"], CHI: ["Bears", "Chicago, IL"], CIN: ["Bengals", "Cincinnati, OH"], CLE: ["Browns", "Cleveland, OH"],
    DAL: ["Cowboys", "Arlington, TX"], DEN: ["Broncos", "Denver, CO"], DET: ["Lions", "Detroit, MI"], GB: ["Packers", "Green Bay, WI"],
    HOU: ["Texans", "Houston, TX"], IND: ["Colts", "Indianapolis, IN"], JAX: ["Jaguars", "Jacksonville, FL"], KC: ["Chiefs", "Kansas City, MO"],
    LV: ["Raiders", "Las Vegas, NV"], LAC: ["Chargers", "Inglewood, CA"], LA: ["Rams", "Inglewood, CA"], LAR: ["Rams", "Inglewood, CA"],
    MIA: ["Dolphins", "Miami Gardens, FL"], MIN: ["Vikings", "Minneapolis, MN"], NE: ["Patriots", "Foxborough, MA"], NO: ["Saints", "New Orleans, LA"],
    NYG: ["Giants", "East Rutherford, NJ"], NYJ: ["Jets", "East Rutherford, NJ"], PHI: ["Eagles", "Philadelphia, PA"], PIT: ["Steelers", "Pittsburgh, PA"],
    SF: ["49ers", "Santa Clara, CA"], SEA: ["Seahawks", "Seattle, WA"], TB: ["Buccaneers", "Tampa, FL"], TEN: ["Titans", "Nashville, TN"],
    WAS: ["Commanders", "Landover, MD"], WSH: ["Commanders", "Landover, MD"]
  };
  function nflName(a) { return (NFL[a] || [a])[0]; }
  function nflCity(g) { return g.neutral ? "" : (NFL[g.home] || ["", ""])[1]; }
  function nflVenue(g) { return String(g.stadium || "").split("·")[0].trim(); }
  function nflAxis(g) {                        // plain words for the wind vs the field
    if (g.dome) return "roof closed";
    if (!isNum(g.wind) || g.wind < 4) return "light wind";
    if (g.ax == null || !g.windClass) return "direction vs field not on file";
    return g.windClass === "cross" ? "crosswind" : g.windClass === "along" ? "down the field" : "quartering";
  }
  var NDELAY = { watch: ["Rain watch", "warn"], likely: ["Heavy rain likely", "bad"], severe: ["Heavy rain", "bad"] };
  function nflWatch(d) {
    var out = [];
    if (!d || !d.games) return out;
    d.games.forEach(function (g) {
      if (g.dome) return;
      var R = [], venue = nflVenue(g);
      var dl = g.delay && NDELAY[g.delay.level];
      if (dl || (g.rain || 0) >= 40) {
        var pctv = Math.max(g.rain || 0, (g.delay && g.delay.pct) || 0);
        R.push({ sev: pctv >= 70 ? 4 : 3, icon: D.wx("rain"), tone: pctv >= 70 ? "bad" : "warn", title: "Rain: " + pctv + "% around kickoff",
          sub: "A wet ball means more fumbles and fewer completions downfield.", short: pctv + "% rain" });
      }
      if (isNum(g.wind) && g.wind >= 15) {
        var fx = g.windFx && /HIGH|EXTREME/.test(g.windFx.rating) ? " " + venue + " is a " + g.windFx.rating.toLowerCase() + "-wind stadium." : "";
        R.push({ sev: g.wind >= 20 ? 4 : 3, icon: D.wx("wind"), tone: "cool", title: g.wind + " mph wind, " + nflAxis(g),
          sub: "Deep passing and long kicks are what wind takes away first." + fx, short: g.wind + " mph " + nflAxis(g) });
      }
      if (isNum(g.temp) && g.temp <= 32) R.push({ sev: 3, icon: D.wx("cold"), tone: "cool", title: "Freezing: " + g.temp + "°", sub: "Cold games have run lower-scoring at most stadiums.", short: g.temp + "°" });
      if (isNum(g.temp) && g.temp >= 88) R.push({ sev: 2, icon: D.wx("hot"), tone: "warn", title: "Heat: " + g.temp + "°", sub: "Heat wears down defenses late — and tempo teams notice.", short: g.temp + "° heat" });
      if (isNum(g.pts) && (g.sample || 0) >= 10 && Math.abs(g.pts) >= 8) {
        R.push({ sev: 1, icon: D.wx(g.pts > 0 ? "up" : "down"), tone: g.pts > 0 ? "good" : "cool", title: "Scoring " + D.signed(g.pts, 0, "%") + " in weather like this",
          sub: "Across " + g.sample + " games at " + venue + " in similar conditions.", short: "points " + D.signed(g.pts, 0, "%") });
      }
      if (!R.length) return;
      R.sort(function (a, b) { return b.sev - a.sev; });
      var top = R[0];
      out.push({ sport: "nfl", id: g.id, game: g.away + " @ " + g.home, when: (g.day ? g.day.split(" ")[0] + " " : "") + g.time, sev: top.sev + R.length * 0.1,
        icon: top.icon, tone: top.tone, title: top.title, sub: top.sub, also: R.slice(1).map(function (r) { return r.short; }) });
    });
    out.sort(function (a, b) { return b.sev - a.sev; });
    return out;
  }

  /* NFL leans: rank by the size of the weather split and its sample, priced props first */
  var NKIND = {
    "QB WIND": ["Passing yards", "Wind"], "QB COLD": ["Passing yards", "Cold"], "RB WIND": ["Rushing yards", "Wind"], "RB COLD": ["Rushing yards", "Cold"],
    "WR WIND": ["Receptions", "Wind"], "KICKER": ["Kicking points", "Wind"], "ALTITUDE": ["Kicking points", "Altitude"],
    "COLD": ["Team total", "Cold"], "SPOT": ["Game spot", "Schedule"], "REF TOTAL": ["Game total", "Referee"]
  };
  function nflSplit(l) {
    var m = /\(([+\-−]?\d+)% vs [\d.]+ (?:norm|career)/.exec(l.why || ""), g = /(\d+) gms\)/.exec(l.why || "");
    var k = /(\d+)% in wind \((\d+)\/(\d+)\) vs (\d+)% career/.exec(l.why || "");
    if (k) return { delta: +k[1] - +k[4], n: +k[3] };
    return { delta: m ? +m[1].replace("−", "-") : null, n: g ? +g[1] : null };
  }
  function nflPick(l) {
    var kind = NKIND[l.k] || [l.prop || l.k, ""];
    var sp = nflSplit(l);
    var priced = D.validOdds(l.price) && isNum(l.line);
    var score = (isNum(sp.delta) ? Math.abs(sp.delta) : 4) * Math.sqrt(Math.min(sp.n || 4, 16) / 16) + (priced ? 30 : 0) + (l.side === "WATCH" ? -40 : 0);
    var who = String(l.who || ""), team = (/\(([A-Z]{2,3})\)/.exec(who) || [])[1] || "";
    return {
      sport: "nfl", k: l.k, market: kind[0], factor: kind[1], side: l.side, player: who.replace(/\s*\([A-Z]{2,3}\)\s*$/, ""), team: team, game: l.game,
      line: l.line, price: l.price, books: l.books, atd: l.atd, delta: sp.delta, n: sp.n, priced: priced, score: score, why: l.why, raw: l
    };
  }
  function nflPicks(pro) {
    if (!pro || !pro.leans) return [];
    return pro.leans.map(nflPick).sort(function (a, b) { return b.score - a.score; });
  }

  /* ============================================================ CFB */
  var CLEVEL = { severe: ["Severe weather", "bad", 4], elevated: ["Weather matters", "warn", 3], watch: ["Worth a look", "", 1] };
  function cfbWatch(d) {
    var out = [];
    if (!d || !d.games) return out;
    d.games.forEach(function (g) {
      if (g.dome) return;
      var lv = g.edge && CLEVEL[g.edge.level];
      var R = [];
      if ((g.rain || 0) >= 50) R.push({ sev: 3, icon: D.wx("rain"), tone: "warn", title: "Rain: " + g.rain + "% around kickoff", sub: "Wet ball, shorter passing game.", short: g.rain + "% rain" });
      if (isNum(g.wind) && g.wind >= 16) R.push({ sev: g.wind >= 22 ? 4 : 3, icon: D.wx("wind"), tone: "cool", title: g.wind + " mph wind", sub: "Deep balls and long field goals suffer first.", short: g.wind + " mph wind" });
      if (isNum(g.temp) && g.temp <= 35) R.push({ sev: 2, icon: D.wx("cold"), tone: "cool", title: "Cold: " + g.temp + "°", sub: "Cold, dense air — kicks and deep throws come up short.", short: g.temp + "°" });
      if (isNum(g.temp) && g.temp >= 90) R.push({ sev: 2, icon: D.wx("hot"), tone: "warn", title: "Heat: " + g.temp + "°", sub: "Depth gets tested in the second half.", short: g.temp + "° heat" });
      if (!R.length && lv && lv[2] >= 3) R.push({ sev: lv[2], icon: D.wx("warn"), tone: lv[1], title: lv[0], sub: "The forecast here is strong enough to move this game's numbers.", short: lv[0].toLowerCase() });
      if (!R.length) return;
      R.sort(function (a, b) { return b.sev - a.sev; });
      var top = R[0];
      out.push({ sport: "cfb", id: g.id, game: g.away + " @ " + g.home, when: String(g.day || "").split(" ")[0] + " " + g.time, sev: top.sev + (g.p4 ? 0.5 : 0) + R.length * 0.1,
        icon: top.icon, tone: top.tone, title: top.title, sub: top.sub, also: R.slice(1).map(function (r) { return r.short; }), p4: g.p4 });
    });
    out.sort(function (a, b) { return b.sev - a.sev; });
    return out;
  }
  function cfbPick(l) {
    return { sport: "cfb", k: l.k, market: "Team rushing", factor: "Trenches", side: l.side, player: l.who, team: "", game: l.game, cd: l.cd, why: l.why || "", raw: l,
      score: Math.abs(l.cd || 0) };
  }
  function cfbPicks(pro) {
    if (!pro || !pro.leans) return [];
    return pro.leans.map(cfbPick).sort(function (a, b) { return b.score - a.score; });
  }

  /* ============================================================ PGA */
  function pgaWatch(d) {
    var out = [];
    if (!d || !d.rounds) return out;
    d.rounds.forEach(function (r) {
      if (!r.inWindow) return;
      var R = [];
      if (isNum(r.gust) && r.gust >= 25 || isNum(r.wind) && r.wind >= 15) R.push({ sev: 3, icon: D.wx("wind"), tone: "cool", title: (r.wind || 0) + " mph, gusts " + (r.gust || "—"), sub: "Scoring climbs and ball-strikers separate.", short: "gusts " + r.gust });
      if ((r.rain || 0) >= 40 || r.delay === "likely" || r.delay === "severe") R.push({ sev: 3, icon: D.wx("rain"), tone: "warn", title: "Rain: " + r.rain + "%", sub: "Soft greens and possible delays.", short: r.rain + "% rain" });
      if (isNum(r.temp) && r.temp <= 50) R.push({ sev: 1, icon: D.wx("cold"), tone: "cool", title: "Cold: " + r.temp + "°", sub: "The ball won't fly as far.", short: r.temp + "°" });
      if (!R.length) return;
      R.sort(function (a, b) { return b.sev - a.sev; });
      var t = R[0];
      out.push({ sport: "pga", id: r.name, game: d.event && d.event.name, when: r.name, sev: t.sev, icon: t.icon, tone: t.tone, title: t.title, sub: t.sub, also: R.slice(1).map(function (x) { return x.short; }) });
    });
    return out;
  }
  function pgaPick(l) {
    var mk = l.market || {};
    return { sport: "pga", k: l.k, market: "Top-20 finish", factor: "Course history", side: "TARGET", player: l.who, game: "", why: l.why, score: -(l.score || 0),
      price: mk.price, implied: mk.implied, raw: l };
  }
  function pgaPicks(pro) { return pro && pro.leans ? pro.leans.map(pgaPick) : []; }

  /* ============================================================ NASCAR */
  function nascarWatch(d) {
    var r = d && d.race, out = [];
    if (!r || !r.inWindow) return out;
    var R = [];
    var dl = r.delay && r.delay.level && r.delay.level !== "clear";
    if (dl || (r.rain || 0) >= 30) R.push({ sev: r.delay && (r.delay.level === "likely" || r.delay.level === "severe") ? 4 : 2, icon: D.wx("rain"), tone: "warn",
      title: "Rain risk: " + Math.max(r.rain || 0, (r.delay && r.delay.pct) || 0) + "%", sub: "Ovals don't race wet — a delay or a shortened race changes strategy.", short: "rain" });
    if (isNum(r.temp) && r.temp >= 88) R.push({ sev: 2, icon: D.wx("hot"), tone: "warn", title: "Hot track: " + r.temp + "°", sub: "Slick, greasy track — tire wear and handling decide it.", short: r.temp + "°" });
    if (isNum(r.gust) && r.gust >= 25) R.push({ sev: 1, icon: D.wx("wind"), tone: "cool", title: "Gusts to " + r.gust + " mph", sub: "Crosswinds unsettle cars in the corners.", short: "gusts" });
    if (!R.length) return out;
    R.sort(function (a, b) { return b.sev - a.sev; });
    var t = R[0];
    out.push({ sport: "nascar", id: "race", game: r.name, when: r.day + " " + r.time, sev: t.sev, icon: t.icon, tone: t.tone, title: t.title, sub: t.sub, also: R.slice(1).map(function (x) { return x.short; }) });
    return out;
  }
  function nascarPick(l) { return { sport: "nascar", k: l.k, market: l.k === "DOMINATOR" ? "Top-5 finish" : "Top-10 finish", factor: "Track history", side: "TARGET", player: l.who, game: "", why: l.why, raw: l }; }
  function nascarPicks(pro) { return pro && pro.leans ? pro.leans.map(nascarPick) : []; }

  window.F = {
    mlb: {
      url: "/data.json", proUrl: "/pro/data.json", recUrl: "/pro/record.json", teaserUrl: "/teaser.json",
      name: mlbName, city: mlbCity, park: parkName, wind: mlbWind, windKind: windKind, started: mlbStarted, delay: DELAY,
      watch: mlbWatch, picks: mlbPicks, hrPick: mlbHrPick, factors: mlbFactors, record: mlbRecord
    },
    nfl: {
      url: "/nfl/data.json", proUrl: "/pro/nfl.json", recUrl: "/pro/nfl_record.json",
      name: nflName, city: nflCity, venue: nflVenue, axis: nflAxis, delay: NDELAY, watch: nflWatch, picks: nflPicks, pick: nflPick, split: nflSplit, kinds: NKIND
    },
    cfb: { url: "/cfb/data.json", proUrl: "/pro/cfb.json", wxUrl: "/pro/cfb_wx.json", recUrl: "/pro/cfb_record.json", levels: CLEVEL, watch: cfbWatch, picks: cfbPicks },
    pga: { url: "/pga/data.json", proUrl: "/pro/pga.json", recUrl: "/pro/pga_record.json", watch: pgaWatch, picks: pgaPicks },
    nascar: { url: "/nascar/data.json", proUrl: "/pro/nascar.json", recUrl: "/pro/nascar_record.json", watch: nascarWatch, picks: nascarPicks },
    cap: cap, etHHMM: etHHMM
  };
})();
