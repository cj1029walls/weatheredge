/* DFSRADAR · college football renderers (CFB weather page + CFB props desk).
 *   C.card(g, ctx) · C.row(g) · C.detail(g, ctx)
 */
(function () {
  "use strict";
  var D = window.DR, F = window.F, esc = D.esc, isNum = D.isNum, FC = F.cfb;

  function logo(src, ab) {
    return src ? '<img src="' + esc(src) + '" alt="" width="22" height="22" loading="lazy" onerror="this.remove()" style="display:inline-block;vertical-align:-5px;margin-right:7px;border-radius:4px;background:rgba(255,255,255,.06)">' : "";
  }
  function teams(g) { return logo(g.awayLogo) + esc(g.away) + ' <span class="at">at</span> ' + logo(g.homeLogo) + esc(g.home); }
  function where(g) { return esc(String(g.stadium || "").split("·")[0].trim()) + (g.conf && g.conf !== "Other" ? " · " + esc(g.conf) : ""); }
  function tile(ico, v, l, lcls) { return '<div class="gc__tile">' + ico + '<div style="min-width:0"><div class="v">' + v + '</div><div class="l ' + (lcls || "") + '">' + l + "</div></div></div>"; }
  function statTile(v, l, s) { return '<div class="stat"><div class="stat__v">' + v + '</div><div class="stat__l">' + l + "</div>" + (s ? '<div class="stat__s">' + s + "</div>" : "") + "</div>"; }
  function level(g) { var lv = g.edge && FC.levels[g.edge.level]; return lv ? '<span class="chip chip--' + (lv[1] || "cyan") + ' chip--sm">' + lv[0] + "</span>" : ""; }

  function hourRows(detail) {
    var r = [
      { k: "Rain", f: function (h) { return isNum(h.rain) ? h.rain + "%" : null; }, cls: function (h) { return D.rainCls(h.rain); } },
      { k: "Temp", f: function (h) { return isNum(h.t) ? h.t + "°" : null; } },
      { k: "Wind", f: function (h) { return isNum(h.w) ? h.w + (detail ? " mph" : "") : null; } }
    ];
    if (detail) r.push({ k: "Humidity", f: function (h) { return isNum(h.rh) ? h.rh + "%" : null; } });
    return r;
  }

  function card(g) {
    return '<article class="gc" id="g-' + esc(g.id) + '"><div class="gc__h"><div><div class="gc__teams">' + teams(g) + '</div><div class="gc__where">' + where(g) + "</div></div>" +
      '<div class="gc__when"><div class="t">' + esc(g.time) + '</div><div class="l">' + esc(String(g.day || "").replace(/^(\w+) .*/, "$1")) + "</div></div></div>" +
      '<div class="gc__tiles">' +
      tile('<span class="ico" aria-hidden="true">' + (g.skyIcon || "🌤️") + "</span>", g.temp + "°", esc(g.sky || "At kickoff")) +
      tile(D.compassWind(g.windDir, g.wind, 52), (isNum(g.wind) ? g.wind : "—") + "<small>mph</small>", g.windDir != null && g.wind >= 3 ? "From the " + D.compass(g.windDir) : "Wind", g.wind >= 16 ? "warn" : "") +
      tile('<span class="ico" aria-hidden="true">💧</span>', (isNum(g.rain) ? g.rain : "—") + "%", "Rain chance", g.rain >= 50 ? "warn" : "") +
      tile('<span class="ico" aria-hidden="true">🏈</span>', g.ou && g.ou.n >= 8 ? g.ou.over + "%" : "—", g.ou && g.ou.n >= 8 ? "Overs in similar games" : "Too little history") +
      "</div>" + D.hourly(g.hourly || [], hourRows(false)) +
      '<div class="gc__foot"><button class="dr-link" type="button" data-open="' + esc(g.id) + '">Full forecast &amp; history →</button>' + level(g) + "</div></article>";
  }

  function row(g) {
    return '<tr data-open="' + esc(g.id) + '" tabindex="0" style="cursor:pointer"><td class="who">' + esc(g.away) + ' <span class="dim">@</span> ' + esc(g.home) +
      "<small>" + esc(String(g.stadium || "").split("·")[0].trim()) + (g.conf && g.conf !== "Other" ? " · " + esc(g.conf) : "") + "</small></td>" +
      '<td class="num">' + esc(g.time.replace(" ET", "")) + "</td>" +
      '<td class="num">' + (g.dome ? '<span class="dim">roof</span>' : (g.skyIcon || "") + " " + g.temp + "°") + "</td>" +
      '<td class="num">' + (g.dome ? "—" : "<b" + (g.wind >= 16 ? ' class="warn"' : "") + ">" + g.wind + '</b> <span class="dim">mph</span>') + "</td>" +
      '<td class="num ' + (g.dome ? "" : D.rainCls(g.rain)) + '">' + (g.dome ? "—" : g.rain + "%") + "</td>" +
      '<td class="num">' + (level(g) || '<span class="dim">—</span>') + "</td></tr>";
  }

  function detail(g, ctx) {
    var h = [];
    h.push('<div class="sec"><div class="ph__eyebrow" style="margin-bottom:8px">' + esc(g.day + " · " + g.time) + " · " + where(g) + "</div>" +
      '<h2 style="font-size:clamp(22px,3vw,30px)">' + teams(g) + '</h2><div class="chips mt12">' + (g.dome ? '<span class="chip">Indoors</span>' : "") + level(g) +
      (g.p4 ? '<span class="chip">Power 4</span>' : "") + (isNum(g.total) ? '<span class="chip">Total ' + g.total + "</span>" : "") + "</div></div>");
    h.push('<div class="sec"><div class="sec__h"><h3 class="sec__title">At kickoff</h3></div><div class="stats">' +
      statTile((g.skyIcon ? g.skyIcon + " " : "") + g.temp + "°", "Temperature", isNum(g.feels) && g.feels !== g.temp ? "Feels like " + g.feels + "°" : esc(g.sky || "")) +
      statTile((isNum(g.wind) ? g.wind : "—") + "<small>mph</small>", "Wind", g.windDir != null ? "From the " + D.compass(g.windDir) : "") +
      statTile((isNum(g.rain) ? g.rain : "—") + "<small>%</small>", "Rain chance", g.delay && g.delay.level && g.delay.level !== "clear" ? "Up to " + g.delay.pct + "% in the game window" : "") +
      statTile((isNum(g.dew) ? g.dew : "—") + "°", "Dew point", isNum(g.rh) ? g.rh + "% humidity" : "") +
      statTile((isNum(g.pres) ? g.pres : "—") + "<small>hPa</small>", "Pressure", "") + "</div></div>");
    h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">Hour by hour</h3><p class="sec__sub">Kickoff hour highlighted.</p></div></div>' +
      '<div class="card card--flat" style="padding:10px 14px">' + D.hourly(g.hourly || [], hourRows(true), { full: true }) + "</div></div>");
    if (g.metrics && g.metrics.length) {
      var rows = g.metrics.map(function (m) {
        var d = function (v) { return isNum(v) ? '<span class="' + (v >= 5 ? "good" : v <= -5 ? "cool" : "dim") + '">' + D.signed(v, 0, "%") + "</span>" : "—"; };
        return '<tr><td class="who">' + esc(F.cap(String(m.label).toLowerCase())) + '</td><td class="num"><b>' + D.fixed(m.cur, 1) + '</b></td><td class="num">' + D.fixed(m.vnAvg, 1) + " " + d(m.vnPct) +
          '</td><td class="num">' + D.fixed(m.lgAvg, 1) + " " + d(m.lgPct) + "</td></tr>";
      }).join("");
      h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">What weather like this has meant here</h3><p class="sec__sub">' + D.plural(g.metrics[0].n || g.sample || 0, "game") +
        " at this stadium in similar conditions — " + esc(g.note || "") + ".</p></div></div>" +
        '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Per game</th><th class="num">In this weather</th><th class="num">Stadium normal</th><th class="num">League normal</th></tr></thead><tbody>' + rows + "</tbody></table></div>" +
        (g.ou && g.ou.n ? '<p class="small dim mt12">Against their own closing totals, those games went over ' + g.ou.over + "% and under " + g.ou.under + "% of the time.</p>" : "") + "</div>");
    } else if (!g.dome) {
      h.push('<div class="note mt24">' + D.IC.info + "<div>" + esc(g.note || "No similar-weather history at this stadium yet.") + "</div></div>");
    }
    if (g.matches && g.matches.length) {
      var mr = g.matches.map(function (m) {
        var dd = String(m.d || ""), date = dd.length === 8 ? dd.slice(4, 6) + "/" + dd.slice(6, 8) + "/" + dd.slice(0, 4) : esc(dd);
        return "<tr><td>" + date + '</td><td class="num">' + m.t + '°</td><td class="num">' + m.w + ' mph</td><td class="num">' + m.pts + '</td><td class="num">' + (m.line != null ? m.line : "—") +
          '</td><td class="num">' + (m.res ? '<span class="res res--' + (m.res === "over" ? "w" : m.res === "under" ? "l" : "p") + '">' + esc(m.res.toUpperCase()) + "</span>" : "—") + "</td></tr>";
      }).join("");
      h.push('<div class="sec"><div class="sec__h"><div><h3 class="sec__title">The similar games</h3></div></div><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th class="num">Temp</th><th class="num">Wind</th><th class="num">Points</th><th class="num">Line</th><th class="num">O/U</th></tr></thead><tbody>' + mr + "</tbody></table></div></div>");
    }
    h.push('<div class="sec"><div class="note">' + D.IC.info + '<div>Rushing props for college games live on the <a href="' + D.u("/props/cfb/") + '">CFB props desk</a> — the trench board matches each offensive line against the defense it faces.</div></div></div>');
    return h.join("");
  }

  window.C = { card: card, row: row, detail: detail, teams: teams };
})();
