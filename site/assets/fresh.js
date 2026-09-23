/* DFSRADAR · freshness chip + stale banner, shared by the free radars and the PRO desks.
 *
 * Every builder stamps its JSON with a time like "2026-09-22 19:31 ET" (generated /
 * updated / built). When a build fails, the last good file is kept and marked
 * {stale:true, status:{ok:false, reason, lastGood}}. This file turns that into one
 * consistent signal on every page:
 *
 *   RadarFresh.render(el, {built, stale, status, maxAgeH, forDate})
 *     -> "● Updated 7:31 PM ET"                       (fresh)
 *     -> "● Not refreshed since Sun 9:53 AM ET"         (builder marked it stale)
 *     -> "● Updated Sun 9:53 AM ET · refresh delayed"   (older than maxAgeH)
 *     -> "● Last slate · Mon Sep 21"                    (forDate isn't today in ET)
 *   RadarFresh.assess(info) -> {level:'ok'|'warn', text, why, ageH}
 *   RadarFresh.banner(el, title, body)  — amber explanation box (el hidden when title is empty)
 *
 * Times are shown in Eastern, the site's convention. No dependencies.
 */
(function () {
  "use strict";
  var TZ = "America/New_York";
  var fmtParts;
  try {
    fmtParts = new Intl.DateTimeFormat("en-US", {
      timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", weekday: "short", hourCycle: "h23"
    });
  } catch (e) { fmtParts = null; }

  function et(t) {
    if (!fmtParts) {                                   // very old browser: assume EDT
      var u = new Date(t.getTime() - 4 * 36e5);
      return { y: u.getUTCFullYear(), mo: u.getUTCMonth() + 1, d: u.getUTCDate(),
               h: u.getUTCHours(), mi: u.getUTCMinutes(),
               wd: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][u.getUTCDay()] };
    }
    var o = {};
    fmtParts.formatToParts(t).forEach(function (p) { o[p.type] = p.value; });
    return { y: +o.year, mo: +o.month, d: +o.day, h: (+o.hour) % 24, mi: +o.minute, wd: o.weekday };
  }

  /* "2026-09-22 19:31 ET" (or "...T19:31...") -> Date, DST-correct. */
  function parseET(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})/.exec(String(s || ""));
    if (!m) return null;
    var y = +m[1], mo = +m[2], d = +m[3], h = +m[4], mi = +m[5];
    for (var off = 4; off <= 5; off++) {
      var t = new Date(Date.UTC(y, mo - 1, d, h + off, mi));
      var p = et(t);
      if (p.h === h && p.d === d) return t;
    }
    return new Date(Date.UTC(y, mo - 1, d, h + 4, mi));
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function todayET() { var p = et(new Date()); return p.y + "-" + pad(p.mo) + "-" + pad(p.d); }

  function clock(p) {
    var h12 = p.h % 12 || 12;
    return h12 + ":" + pad(p.mi) + " " + (p.h < 12 ? "AM" : "PM") + " ET";
  }

  /* 7:31 PM ET  |  Sun 9:53 AM ET (when not today) */
  function fmt(t, forceDay) {
    if (!t) return "";
    var p = et(t), today = todayET();
    var same = (p.y + "-" + pad(p.mo) + "-" + pad(p.d)) === today;
    return (forceDay || !same ? p.wd + " " : "") + clock(p);
  }

  function ago(h) {
    if (h == null || !isFinite(h)) return "";
    if (h < 1) return Math.max(1, Math.round(h * 60)) + " min ago";
    if (h < 36) return Math.round(h) + " h ago";
    return Math.round(h / 24) + " days ago";
  }

  function dayLabel(iso) {                              // "2026-09-21" -> "Mon Sep 21"
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    if (!m) return iso || "";
    var t = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], 16));
    return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][t.getUTCDay()] + " " +
      ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][t.getUTCMonth()] +
      " " + t.getUTCDate();
  }

  function assess(o) {
    o = o || {};
    var st = (o.status && typeof o.status === "object") ? o.status : {};
    var builtT = parseET(o.built);
    var lastT = parseET(st.lastGood) || builtT;
    var ageH = builtT ? (Date.now() - builtT.getTime()) / 36e5 : null;
    var stale = !!(o.stale || st.ok === false);
    if (stale) {
      return { level: "warn", ageH: ageH,
               text: "Not refreshed since " + (lastT ? fmt(lastT, true) : "the last build"),
               why: st.reason ? String(st.reason) : "The last update could not be completed." };
    }
    if (o.forDate && o.forDate !== todayET()) {
      return { level: "warn", ageH: ageH, text: "Last slate · " + dayLabel(o.forDate),
               why: "Today's slate hasn't been built yet — this is the most recent one." };
    }
    if (ageH != null && o.maxAgeH && ageH > o.maxAgeH) {
      return { level: "warn", ageH: ageH, text: "Updated " + fmt(builtT, true) + " · refresh delayed",
               why: "The scheduled refresh is running late — last build " + ago(ageH) + "." };
    }
    if (!builtT) return { level: "none", ageH: null, text: "", why: "" };
    return { level: "ok", ageH: ageH, text: "Updated " + fmt(builtT), why: "Built " + ago(ageH) + "." };
  }

  var CSS = "" +
    ".rf-chip{display:inline-flex;align-items:center;gap:8px;font:600 11.5px/1.2 Ubuntu,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;" +
    "letter-spacing:.2px;padding:6px 11px;border-radius:999px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.05);" +
    "color:#C7CEDC;white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis;vertical-align:middle}" +
    ".rf-chip::before{content:'';flex:0 0 7px;width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 3px rgba(34,197,94,.16)}" +
    ".rf-chip.warn{color:#fcd34d;border-color:rgba(251,191,36,.38);background:rgba(251,191,36,.10)}" +
    ".rf-chip.warn::before{background:#fbbf24;box-shadow:0 0 0 3px rgba(251,191,36,.2)}" +
    ".rf-banner{display:flex;gap:12px;align-items:flex-start;border:1px solid rgba(251,191,36,.34);background:rgba(251,191,36,.09);" +
    "border-radius:12px;padding:13px 16px;color:#EFF1F7;font:400 13.5px/1.6 Ubuntu,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}" +
    ".rf-banner b{color:#fcd34d;font-weight:700}" +
    ".rf-banner::before{content:'';flex:0 0 8px;width:8px;height:8px;margin-top:7px;border-radius:50%;background:#fbbf24;box-shadow:0 0 0 3px rgba(251,191,36,.2)}" +
    ".rf-banner[hidden]{display:none}";

  function injectCSS() {
    if (document.getElementById("rf-css")) return;
    var s = document.createElement("style");
    s.id = "rf-css";
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function render(el, o) {
    if (!el) return null;
    injectCSS();
    var a = assess(o);
    if (a.level === "none") { el.hidden = true; el.innerHTML = ""; return a; }
    el.hidden = false;
    el.innerHTML = '<span class="rf-chip ' + a.level + '" role="status">' + esc(a.text) + "</span>";
    el.title = a.why || "";
    return a;
  }

  function banner(el, title, body) {
    if (!el) return;
    injectCSS();
    if (!title) { el.hidden = true; el.innerHTML = ""; return; }
    el.className = (el.className.replace(/\brf-banner\b/, "") + " rf-banner").trim();
    el.hidden = false;
    el.setAttribute("role", "status");
    el.innerHTML = "<div><b>" + esc(title) + "</b>" + (body ? " " + esc(body) : "") + "</div>";
  }

  window.RadarFresh = { parseET: parseET, fmt: fmt, todayET: todayET, dayLabel: dayLabel,
                        ago: ago, assess: assess, render: render, banner: banner };
})();
