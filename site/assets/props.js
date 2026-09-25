/* DFSRADAR · props desk building blocks (every sport's desk + the Props hub).
 *
 *   P.board(el, spec)      a sortable board with expandable "why" rows and the
 *                          free-#1 / PRO lock built in; re-render with P.refresh(el)
 *   P.topCard(pick, opt)   the featured free pick
 *   P.recordStrip(items)   the record tiles every desk opens with
 *
 * spec = { cols:[{k,label,num,cls,html(row,i),sort(row)}], rows:[], key(row), expand(row) -> html,
 *          free: 1 (rows shown to non-members), member: bool, lock:{what, title, sub},
 *          sort:{k, dir}, empty:"…", foot:"…" }
 * Rows beyond `free` are never written into the page for non-members — only a
 * count and blurred placeholder shapes.
 */
(function () {
  "use strict";
  var D = window.DR, esc = D.esc, isNum = D.isNum;
  var specs = new WeakMap();

  function board(el, spec) {
    if (!el) return;
    var prev = specs.get(el);
    spec.state = spec.state || (prev && prev.state) || { k: spec.sort && spec.sort.k, dir: (spec.sort && spec.sort.dir) || "desc", open: {} };
    specs.set(el, spec);
    render(el);
    if (!el.__wired) {
      el.__wired = true;
      el.addEventListener("click", function (e) {
        var sp = specs.get(el);
        if (e.target.closest && e.target.closest("[data-all]")) { sp.state.all = true; render(el); return; }
        var th = e.target.closest && e.target.closest("th[data-sort]");
        if (th) {
          var k = th.getAttribute("data-sort");
          if (sp.state.k === k) sp.state.dir = sp.state.dir === "desc" ? "asc" : "desc";
          else { sp.state.k = k; sp.state.dir = "desc"; }
          render(el);
          return;
        }
        var tr = e.target.closest && e.target.closest("tr[data-row]");
        if (tr && sp.expand && !e.target.closest("a,button:not(.row-btn)")) {
          var id = tr.getAttribute("data-row");
          sp.state.open[id] = !sp.state.open[id];
          render(el);
        }
      });
      el.addEventListener("keydown", function (e) {
        if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("tr[data-row]")) { e.preventDefault(); e.target.click(); }
      });
    }
  }
  function refresh(el, patch) {
    var sp = specs.get(el);
    if (!sp) return;
    if (patch) Object.keys(patch).forEach(function (k) { sp[k] = patch[k]; });
    render(el);
  }

  function sorted(sp) {
    var rows = sp.rows.slice();
    var col = sp.cols.filter(function (c) { return c.k === sp.state.k; })[0];
    if (col && col.sort) {
      var dir = sp.state.dir === "asc" ? 1 : -1;
      rows.sort(function (a, b) {
        var x = col.sort(a), y = col.sort(b);
        var nx = x == null || (typeof x === "number" && !isFinite(x)), ny = y == null || (typeof y === "number" && !isFinite(y));
        if (nx && ny) return 0; if (nx) return 1; if (ny) return -1;
        return x < y ? -dir : x > y ? dir : 0;
      });
    }
    return rows;
  }

  function render(el) {
    var sp = specs.get(el);
    var cols = sp.cols, member = !!sp.member;
    var head = "<tr>" + cols.map(function (c) {
      var s = c.sort && member ? ' class="sortable' + (c.num ? " num" : "") + '" data-sort="' + c.k + '" tabindex="0"' + (sp.state.k === c.k ? ' aria-sort="' + (sp.state.dir === "asc" ? "ascending" : "descending") + '"' : "")
        : (c.num ? ' class="num"' : "");
      return "<th" + s + (c.w ? ' style="width:' + c.w + '"' : "") + ">" + c.label + "</th>";
    }).join("") + "</tr>";
    if (!sp.rows.length) {
      el.innerHTML = '<div class="tbl-wrap"><div class="empty"><h3>' + esc(sp.emptyTitle || "Nothing on this board yet") + "</h3><p>" + (sp.empty || "") + "</p></div></div>";
      return;
    }
    var all = member ? sorted(sp) : sp.rows.slice(0, sp.free == null ? 1 : sp.free);
    var lim = member && sp.limit && !sp.state.all ? sp.limit : 0;
    var rows = lim ? all.slice(0, lim) : all;
    var body = rows.map(function (r, i) {
      var id = sp.key ? sp.key(r) : String(i), open = !!sp.state.open[id];
      var isFree = !member;
      var tr = '<tr data-row="' + esc(id) + '"' + (sp.expand ? ' tabindex="0" style="cursor:pointer" aria-expanded="' + open + '"' : "") + (open ? ' class="is-open"' : "") + ">" +
        cols.map(function (c) { return "<td" + (c.num ? ' class="num"' : c.cls ? ' class="' + c.cls + '"' : "") + ">" + c.html(r, i, isFree) + "</td>"; }).join("") + "</tr>";
      if (open && sp.expand) tr += '<tr class="x"><td colspan="' + cols.length + '">' + sp.expand(r) + "</td></tr>";
      return tr;
    }).join("");
    var hidden = member ? 0 : Math.max(0, sp.rows.length - (sp.free == null ? 1 : sp.free));
    if (hidden) body += D.fakeRows(Math.min(hidden, 4), cols.length);
    var foot = "";
    if (hidden) foot = D.lockbar({ count: hidden, what: (sp.lock && sp.lock.what) || "more prop", title: sp.lock && sp.lock.title, sub: sp.lock && sp.lock.sub });
    else if (lim && all.length > lim) foot = '<div class="tbl-foot row between"><span>Showing ' + lim + " of " + all.length + '</span><button class="btn btn--sm btn--ghost" type="button" data-all>Show all ' + all.length + "</button></div>";
    else if (sp.foot) foot = '<div class="tbl-foot">' + sp.foot + "</div>";
    el.innerHTML = '<div class="tbl-wrap"><table class="tbl"><thead>' + head + "</thead><tbody>" + body + "</tbody></table>" + foot + "</div>";
  }

  /* ------------------------------------------------------------ bits */
  function sideTag(side) {
    var s = String(side || "").toUpperCase();
    var cls = { OVER: "over", UNDER: "under", YES: "yes", TARGET: "target", FADE: "fade", WATCH: "watch" }[s] || "watch";
    var label = { YES: "HR", TARGET: "TARGET" }[s] || s;
    return '<span class="side side--' + cls + '">' + esc(label) + "</span>";
  }
  function edgeHtml(v, suf, lo, dir) {
    lo = lo == null ? 1.5 : lo;
    if (!isNum(v)) return '<span class="dim">—</span>';
    return '<span class="edge ' + (v >= lo ? "edge--pos" : v <= -lo ? (dir ? "edge--under" : "edge--neg") : "edge--flat") + '">' + D.signed(v, 1, suf || "") + "</span>";
  }
  var BOOK = { DraftKings: "DK", FanDuel: "FD", BetMGM: "MGM", Caesars: "CZR", "Caesars Sportsbook": "CZR", BetRivers: "BR", "ESPN BET": "ESPN",
    Fanatics: "FAN", bet365: "365", "Hard Rock Bet": "HRB", BetOnline: "BOL", "BetOnline.ag": "BOL", Bovada: "BOV", MyBookie: "MYB", LowVig: "LV", "LowVig.ag": "LV", BetUS: "BUS", Fliff: "FLF" };
  function bookTag(b) { return b ? '<span title="' + esc(b) + '">' + esc(BOOK[b] || String(b).slice(0, 4)) + "</span>" : ""; }
  /* median price, implied %, book count and — when one book beats the median — the best price and where */
  function priceHtml(p, imp, books, best) {
    if (!D.validOdds(p)) return '<span class="dim">no price</span>';
    var b = best && D.validOdds(best.price) && best.price !== p ? '<div class="small" style="font-size:11.5px;color:var(--good2)">best ' + D.odds(best.price) + " · " + bookTag(best.book) + "</div>" : "";
    return "<b>" + D.odds(p) + "</b>" + (isNum(imp) ? ' <span class="dim hide-sm">' + D.pct(imp) + "</span>" : "") +
      (b || (books ? '<div class="small dim" style="font-size:11.5px">' + D.plural(books, "book") + "</div>" : ""));
  }

  /* featured pick: pick = {sportLabel, market, side, player, sub, nums:[{v,l,cls}], chips:[], why, href} */
  function topCard(p, o) {
    o = o || {};
    return '<div class="pc' + (o.plain ? "" : " pc--free") + '"><div class="pc__top"><span class="pc__sport">' + esc(p.sportLabel || "") + "</span>" +
      '<span class="chip ' + (o.pro ? "chip--solid-pro" : "chip--free") + '">' + esc(o.tag || "FREE PICK") + "</span></div>" +
      '<div class="pc__who">' + (p.side ? sideTag(p.side) : "") + esc(p.player) + "<small>" + esc(p.sub || "") + "</small></div>" +
      (p.nums && p.nums.length ? '<div class="pc__nums" style="grid-template-columns:repeat(' + p.nums.length + ',minmax(0,1fr))">' + p.nums.map(function (n) {
        return '<div><div class="v ' + (n.cls || "") + '">' + n.v + '</div><div class="l">' + esc(n.l) + "</div></div>";
      }).join("") + "</div>" : "") +
      (p.why ? '<p class="why">' + p.why + "</p>" : "") +
      (p.chips && p.chips.length ? '<div class="chips">' + p.chips.join("") + "</div>" : "") +
      (p.href ? '<div class="pc__cta"><span class="small dim">' + esc(p.note || "") + '</span><a href="' + p.href + '">' + esc(p.hrefLabel || "See the board") + " →</a></div>" : "") +
      "</div>";
  }
  function lockedCard(label, n, blurb) {
    return '<div class="pc pc--locked"><div class="pc__top"><span class="pc__sport">' + esc(label) + '</span><span class="chip chip--pro">PRO</span></div>' +
      '<div class="pc__who">Hidden Player<small>Team · Game · Details</small></div>' +
      '<div class="pc__nums"><div><div class="v">24.1%</div><div class="l">Ours</div></div><div><div class="v">+320</div><div class="l">Books</div></div><div><div class="v">+3.1</div><div class="l">Edge</div></div></div>' +
      '<div class="pc__cta"><span class="small muted">' + esc(blurb || (n ? D.plural(n, "more pick") + " on this board." : "The full board.")) + "</span>" +
      '<a class="btn btn--sm btn--pro pay-cta" href="' + D.u("/pro/") + '">Get PRO</a></div></div>';
  }

  function recordStrip(items) {
    return '<div class="stats">' + items.map(function (it) {
      return '<div class="stat"><div class="stat__v ' + (it.cls || "") + '">' + it.v + '</div><div class="stat__l">' + esc(it.l) + "</div>" + (it.s ? '<div class="stat__s">' + it.s + "</div>" : "") + "</div>";
    }).join("") + "</div>";
  }

  /* graded list rows: [{res:'w'|'l'|'p', title, sub, right}] */
  function results(list) {
    if (!list.length) return '<div class="empty"><p>Nothing graded yet.</p></div>';
    return '<div class="tbl-wrap"><table class="tbl"><tbody>' + list.map(function (r) {
      return '<tr><td style="width:56px"><span class="res res--' + r.res + '">' + ({ w: "HIT", l: "MISS", p: "PUSH" }[r.res] || "—") + "</span></td>" +
        '<td><div class="who" style="white-space:normal">' + r.title + "</div>" + (r.sub ? '<div class="small dim">' + r.sub + "</div>" : "") + "</td>" +
        '<td class="num small">' + (r.right || "") + "</td></tr>";
    }).join("") + "</tbody></table></div>";
  }

  /* units at the posted price: [{price, hit}] -> {n, w, units, roi} */
  function units(list) {
    var n = 0, w = 0, u = 0;
    list.forEach(function (x) {
      if (!D.validOdds(x.price) || x.hit == null) return;
      n++;
      if (x.hit === true) { w++; u += D.payout(x.price); }
      else if (x.hit === false) u -= 1;
    });
    return { n: n, w: w, units: Math.round(u * 100) / 100, roi: n ? u / n * 100 : null };
  }

  window.P = { board: board, refresh: refresh, sideTag: sideTag, edgeHtml: edgeHtml, priceHtml: priceHtml, bookTag: bookTag, topCard: topCard,
    lockedCard: lockedCard, recordStrip: recordStrip, results: results, units: units };
})();
