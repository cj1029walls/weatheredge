/* DFSRADAR · shared page shell + helpers (every page under /next/).
 *
 *   DR.shell({section, sport})   header, sport switcher and footer, one source of truth
 *   DR.gate.on(fn)               fn(state) now and on every membership change
 *                                states: checking · member · billing · lapsed · loggedout · unreachable
 *   DR.get(url)                  JSON feed (revalidated, never stale-cached), null on failure
 *   DR.u(path)                   site link that works in the /next/ preview and after the switch
 *   DR.sheet.open(title, html)   full-screen detail view (phone) / centred panel (desktop)
 *   formatters: DR.odds, DR.implied, DR.pct, DR.signed, DR.esc …
 *
 * Needs /pro/gate.js (membership) and /assets/fresh.js (freshness chip) loaded first.
 */
(function () {
  "use strict";

  /* ---------------------------------------------------------------- paths */
  var me = document.currentScript && document.currentScript.src || "";
  var BASE = (function () {
    try {
      var p = new URL(me, location.href).pathname;          // /next/assets/dr.js
      return p.replace(/\/assets\/dr\.js$/, "");            // "/next" in preview, "" live
    } catch (e) { return ""; }
  })();
  function u(path) { return BASE + path; }

  /* ---------------------------------------------------------------- basics */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  var MINUS = "−";
  function isNum(v) { return typeof v === "number" && isFinite(v); }
  function fixed(v, d) { return isNum(v) ? v.toFixed(d == null ? 1 : d) : "—"; }
  function signed(v, d, suf) {
    if (!isNum(v)) return "—";
    var s = Math.abs(v).toFixed(d || 0);
    if (+s === 0) return "0" + (suf || "");
    return (v > 0 ? "+" : MINUS) + s + (suf || "");
  }
  function pct(v, d) { return isNum(v) ? v.toFixed(d == null ? 1 : d).replace(/\.0$/, "") + "%" : "—"; }
  /* American odds: +265 / −114. 0 or missing is "no price". */
  function odds(p) {
    if (!isNum(p) || p === 0 || (p > -100 && p < 100)) return "—";
    return (p > 0 ? "+" : MINUS) + Math.abs(Math.round(p));
  }
  function validOdds(p) { return isNum(p) && (p >= 100 || p <= -100); }
  function implied(p) {                       // % incl. vig
    if (!validOdds(p)) return null;
    return p > 0 ? 100 / (p + 100) * 100 : -p / (-p + 100) * 100;
  }
  function payout(p) {                        // profit on 1u stake
    if (!validOdds(p)) return null;
    return p > 0 ? p / 100 : 100 / -p;
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
  function tone(v, good, bad) {               // data-semantic class
    if (!isNum(v)) return "dim";
    if (v >= good) return "good";
    if (v <= bad) return "bad";
    return "muted";
  }

  /* ---------------------------------------------------------------- data */
  var cache = {};
  function get(url) {
    if (cache[url]) return cache[url];
    cache[url] = fetch(url, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).catch(function (e) {
      if (window.console) console.warn("feed", url, e);
      return null;
    });
    return cache[url];
  }

  /* ---------------------------------------------------------------- icons */
  var IC = {
    logo: '<svg viewBox="0 0 44 44" aria-hidden="true"><circle cx="22" cy="22" r="20" fill="rgba(255,255,255,.05)" stroke="#22d3ee" stroke-width="1.8"/><circle cx="22" cy="22" r="13.5" fill="none" stroke="#67e8f9" stroke-width="1" opacity=".7"/><circle cx="22" cy="22" r="7" fill="none" stroke="#67e8f9" stroke-width="1" opacity=".5"/><line x1="22" y1="22" x2="22" y2="2.6" stroke="#EFF1F7" stroke-width="1.8" stroke-linecap="round"/><circle cx="29.5" cy="13.5" r="2.4" fill="#F08A3C"/><circle cx="22" cy="22" r="1.7" fill="#EFF1F7"/></svg>',
    menu: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 6h14M3 10h14M3 14h14"/></svg>',
    x: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M5 5l10 10M15 5L5 15"/></svg>',
    lock: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="9" width="12" height="8" rx="2"/><path d="M7 9V6.5a3 3 0 0 1 6 0V9"/></svg>',
    info: '<svg class="ic" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="10" cy="10" r="7.5"/><path d="M10 9v5M10 6.2v.1" stroke-linecap="round"/></svg>',
    warn: '<svg class="ic" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M10 3l8 14H2z"/><path d="M10 8.5v4M10 14.6v.1" stroke-linecap="round"/></svg>',
    arrow: '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h10M9 4l4 4-4 4"/></svg>',
    cube: '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><path d="M10 2.5l6.5 3.7v7.6L10 17.5l-6.5-3.7V6.2z"/><path d="M3.5 6.2L10 10l6.5-3.8M10 10v7.5"/></svg>'
  };

  /* weather + sport glyphs: drawn line icons that take the text color, so they
     read the same on every device (emoji render differently everywhere) */
  var WXP = {
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6L6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4L6 18M18 6l1.4-1.4"/>',
    moon: '<path d="M19.5 14.2A7.5 7.5 0 1 1 9.8 4.5a6 6 0 0 0 9.7 9.7z"/>',
    partly: '<path d="M8.5 2.8v1.4M3.6 7.7H5M5 4.3l1 1M12 4.3l-1 1"/><path d="M11.6 9.4A3.6 3.6 0 0 0 5 9.3"/><path d="M8 20.5a3.8 3.8 0 0 1-.3-7.6 5.2 5.2 0 0 1 9.9-1.2 4.4 4.4 0 0 1-.1 8.8z"/>',
    cloud: '<path d="M7 19.5a4.3 4.3 0 0 1-.4-8.6 6 6 0 0 1 11.5-1.1 4.9 4.9 0 0 1-.2 9.7z"/>',
    rain: '<path d="M7 15.5a4 4 0 0 1-.4-8 5.6 5.6 0 0 1 10.8-1 4.5 4.5 0 0 1 .1 9z"/><path d="M8.5 18.5l-1 2.2M12.5 18.5l-1 2.2M16.5 18.5l-1 2.2"/>',
    storm: '<path d="M7 15.5a4 4 0 0 1-.4-8 5.6 5.6 0 0 1 10.8-1 4.5 4.5 0 0 1 .1 9"/><path d="M12.5 13.5L10 17.5h3.5L11 21.5"/>',
    snow: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M9.8 4.6L12 6.4l2.2-1.8M9.8 19.4l2.2-1.8 2.2 1.8"/>',
    fog: '<path d="M4 8.5h16M3 12.5h18M5 16.5h14M8 20.5h8"/>',
    wind: '<path d="M3 8.5h10.5a2.8 2.8 0 1 0-2.8-2.8"/><path d="M3 12.5h15a3 3 0 1 1-3 3"/><path d="M3 16.5h7"/>',
    drop: '<path d="M12 3.2s6 6.4 6 10.8a6 6 0 0 1-12 0c0-4.4 6-10.8 6-10.8z"/>',
    temp: '<path d="M10 13.6V5.5a2 2 0 1 1 4 0v8.1a4 4 0 1 1-4 0z"/><path d="M12 10v6"/>',
    hot: '<path d="M8.5 13.6V5.5a2 2 0 1 1 4 0v8.1a4 4 0 1 1-4 0z"/><path d="M10.5 8v8"/><path d="M17.5 4.5v5M15 7h5"/>',
    cold: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M9.8 4.6L12 6.4l2.2-1.8M9.8 19.4l2.2-1.8 2.2 1.8"/>',
    up: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    down: '<path d="M3 7l6 6 4-4 8 8"/><path d="M15 17h6v-6"/>',
    warn: '<path d="M12 3.5l9 16H3z"/><path d="M12 10v4.5M12 17.3v.1"/>',
    roof: '<path d="M3 12.5a9 6.5 0 0 1 18 0"/><path d="M3 12.5V19h18v-6.5"/><path d="M9 19v-3.5h6V19"/>',
    ball: '<circle cx="12" cy="12" r="8.5"/><path d="M7.2 5.2c2.3 2.3 2.3 11.3 0 13.6M16.8 5.2c-2.3 2.3-2.3 11.3 0 13.6"/>',
    football: '<path d="M5 19c-1.6-4.6 1-11 7-13.6 3-1.3 5.6-1.2 7-.4 1.6 4.6-1 11-7 13.6-3 1.3-5.6 1.2-7 .4z"/><path d="M9.5 14.5l5-5M10.6 11l2.4 2.4M12.4 9.2l2.4 2.4"/>',
    flag: '<path d="M6.5 21V3"/><path d="M6.5 3.5l10.5 3.7-10.5 3.7"/><path d="M3.5 21h8"/>',
    scale: '<path d="M12 4v16M8 20h8M5 7.5h14"/><path d="M5 7.5l-2.5 6a2.5 2.5 0 0 0 5 0zM19 7.5l-2.5 6a2.5 2.5 0 0 0 5 0z"/>',
    target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r=".8"/>',
    eye: '<path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    chart: '<path d="M5 20v-8M11 20V5M17 20v-6M3 20h18"/>',
    stop: '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/>',
    dot: '<circle cx="12" cy="12" r="2.5"/>'
  };
  // emoji the data feeds still carry -> the matching line icon
  var EMO = {
    "☀": "sun", "🌤": "partly", "⛅": "partly", "🌥": "cloud", "☁": "cloud", "🌦": "rain", "🌧": "rain", "⛈": "storm",
    "🌩": "storm", "🌨": "snow", "❄": "snow", "🌫": "fog", "🌙": "moon", "🏟": "roof", "🌬": "wind", "💧": "drop",
    "🔥": "up", "💣": "up", "🚀": "up", "💥": "up", "📈": "up", "📉": "down", "🧊": "down", "🥶": "cold",
    "🎯": "target", "👀": "eye", "🛑": "stop", "📊": "chart", "⚠": "warn"
  };
  function wx(k, size) {
    var s = size || "1em";
    return '<svg class="wxi" viewBox="0 0 24 24" width="' + s + '" height="' + s + '" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (WXP[k] || WXP.dot) + "</svg>";
  }
  function emo(e, size) { return wx(EMO[String(e || "").replace(/\uFE0F/g, "")] || "dot", size); }
  function sky(g, size) {
    var s = String((g && g.sky) || "").toLowerCase(), e = String((g && g.skyIcon) || "").replace(/\uFE0F/g, ""), k;
    if (g && g.dome || /indoor|roof|dome/.test(s)) k = "roof";
    else if (/thunder|storm/.test(s)) k = "storm";
    else if (/snow|flurr|sleet/.test(s)) k = "snow";
    else if (/rain|shower|drizzle/.test(s)) k = "rain";
    else if (/fog|mist|haze/.test(s)) k = "fog";
    else if (/partly|mostly sunny|few clouds|mixed/.test(s)) k = "partly";
    else if (/overcast|cloud/.test(s)) k = "cloud";
    else if (/clear|sunny|fair/.test(s)) k = e === "🌙" ? "moon" : "sun";
    else k = EMO[e] || "partly";
    return wx(k, size);
  }

  /* ---------------------------------------------------------------- sports */
  var SPORTS = [
    { k: "mlb", name: "MLB", weather: "/mlb/", props: "/props/mlb/" },
    { k: "nfl", name: "NFL", weather: "/nfl/", props: "/props/nfl/" },
    { k: "cfb", name: "CFB", weather: "/cfb/", props: "/props/cfb/" },
    { k: "pga", name: "PGA", weather: "/pga/", props: "/props/pga/" },
    { k: "nascar", name: "NASCAR", weather: "/nascar/", props: "/props/nascar/" }
  ];
  function sport(k) { for (var i = 0; i < SPORTS.length; i++) if (SPORTS[i].k === k) return SPORTS[i]; return null; }

  /* ---------------------------------------------------------------- shell */
  var NAV = [
    { k: "weather", label: "Weather", href: "/weather/" },
    { k: "props", label: "Props", href: "/props/" },
    { k: "record", label: "Record", href: "/record/" },
    { k: "pro", label: "PRO", href: "/pro/" }
  ];

  function header(o) {
    var nav = NAV.map(function (n) {
      return '<a href="' + u(n.href) + '"' + (o.section === n.k ? ' aria-current="page"' : "") + ">" + n.label + "</a>";
    }).join("");
    return '<div class="wrap dr-top__in">' +
      '<a class="dr-brand" href="' + u("/") + '" aria-label="DFSRADAR home">' + IC.logo + '<span class="wm">DFS<b>RADAR</b></span></a>' +
      '<nav class="dr-nav" aria-label="Main">' + nav + "</nav>" +
      '<div class="dr-acts" id="dr-acts">' + acts("checking") + "</div>" +
      '<button class="dr-menu-btn" id="dr-menu-btn" aria-expanded="false" aria-controls="dr-sheet" aria-label="Menu">' + IC.menu + "</button>" +
      "</div>" +
      '<div class="dr-sheet" id="dr-sheet" hidden>' +
      NAV.map(function (n) {
        var sub = { weather: "Forecasts for every game, race and round", props: "Our number vs the books' number", record: "Every call, graded in public", pro: "$15/mo · what you get" }[n.k];
        return '<a href="' + u(n.href) + '"><span>' + n.label + "</span><small>" + sub + "</small></a>";
      }).join("") +
      '<div class="row" id="dr-sheet-acts"></div></div>';
  }

  function acts(st) {
    if (st === "member") {
      return '<span class="chip chip--pro chip--sm" title="Your PRO membership is active">PRO</span>' +
        '<button class="dr-link ms-account" type="button">Account</button>' +
        '<button class="dr-link ms-logout" type="button">Log out</button>';
    }
    if (st === "billing") {
      return '<button class="btn btn--sm btn--ghost" type="button" data-gate-portal>Fix billing</button>' +
        '<button class="dr-link ms-logout" type="button">Log out</button>';
    }
    var who = st === "lapsed" ? '<button class="dr-link ms-logout" type="button">Log out</button>'
                              : '<a class="dr-link ms-login" href="' + u("/pro/") + '#login">Log in</a>';
    return who + '<a class="btn btn--sm btn--pro pay-cta" href="' + u("/pro/") + '">Get PRO</a>';
  }

  function sheetActs(st) {
    if (st === "member") return '<button class="btn btn--ghost ms-account" type="button">Account</button><button class="btn btn--ghost ms-logout" type="button">Log out</button>';
    if (st === "billing") return '<button class="btn btn--ghost" type="button" data-gate-portal>Fix billing</button>';
    return '<a class="btn btn--ghost ms-login" href="' + u("/pro/") + '#login">Log in</a><a class="btn btn--pro pay-cta" href="' + u("/pro/") + '">Get PRO</a>';
  }

  function subnav(o) {
    if (o.section !== "weather" && o.section !== "props") return "";
    var isW = o.section === "weather";
    var links = '<a href="' + u(isW ? "/weather/" : "/props/") + '"' + (!o.sport ? ' aria-current="page"' : "") + ">" + (isW ? "All sports" : "All sports") + "</a>" +
      '<span class="sep" aria-hidden="true"></span>' +
      SPORTS.map(function (s) {
        return '<a href="' + u(isW ? s.weather : s.props) + '"' + (o.sport === s.k ? ' aria-current="page"' : "") + ">" + s.name + "</a>";
      }).join("");
    return '<div class="wrap dr-sub__in"><span class="lab">' + (isW ? "Weather" : "Props") + "</span>" + links + "</div>";
  }

  function footer() {
    var col = function (title, items) {
      return "<div><h4>" + title + "</h4>" + items.map(function (i) {
        return '<a href="' + i[1] + '"' + (i[2] ? ' target="_blank" rel="noopener"' : "") + ">" + i[0] + "</a>";
      }).join("") + "</div>";
    };
    return '<div class="wrap">' +
      '<div class="dr-foot__grid">' +
      '<div><a class="dr-brand" href="' + u("/") + '" style="display:inline-flex">' + IC.logo + '<span class="wm">DFS<b>RADAR</b></span></a>' +
      '<p style="margin-top:14px;max-width:34ch">The forecast at every venue, measured against what actually happened there in weather like it — and every call graded in public.</p></div>' +
      col("Weather", SPORTS.map(function (s) { return [s.name + " weather", u(s.weather)]; })) +
      col("Props", [["All props", u("/props/")]].concat(SPORTS.map(function (s) { return [s.name + " props", u(s.props)]; }))) +
      col("DFSRADAR", [["The record", u("/record/")], ["PRO membership", u("/pro/")], ["Log in", u("/pro/") + "#login"],
        ["DFS Kitchen", "https://dfskitchen.com/?utm_source=dfsradar&utm_medium=footer", 1], ["DFSPREP", "https://dfsprep.com", 1],
        ["DFS Books", "https://dfsbooks.com", 1], ["The Optimizer", "https://dfskitchen.com/optimizer", 1]]) +
      "</div>" +
      '<p class="fine"><b>Informational only — not betting advice.</b> Weather tendencies are tendencies, not guarantees; every number shows its sample size so you can judge it. ' +
      "Prices shown are the sportsbooks' numbers at the time we pulled them, not ours, and can move. " +
      "21+. If gambling is a problem for you, call <b style=\"white-space:nowrap\">1-800-GAMBLER</b>.</p>" +
      "</div>";
  }

  var shellOpts = null;
  function shell(o) {
    shellOpts = o || {};
    var top = document.getElementById("dr-top");
    if (top) { top.className = "dr-top"; top.innerHTML = header(shellOpts); }
    var sub = document.getElementById("dr-sub");
    if (sub) {
      var html = subnav(shellOpts);
      if (html) { sub.className = "dr-sub"; sub.innerHTML = html; } else sub.remove();
      var cur = sub.querySelector && sub.querySelector('[aria-current="page"]');
      if (cur && sub.firstChild && sub.firstChild.scrollWidth > sub.firstChild.clientWidth) {
        var box = sub.firstChild, r = cur.getBoundingClientRect(), br = box.getBoundingClientRect();
        if (r.right > br.right - 16) box.scrollLeft += r.right - br.right + 48;
      }
    }
    var foot = document.getElementById("dr-foot");
    if (foot) { foot.className = "dr-foot"; foot.innerHTML = footer(); }
    var btn = document.getElementById("dr-menu-btn"), sh = document.getElementById("dr-sheet");
    if (btn && sh) {
      btn.addEventListener("click", function () {
        var open = sh.hidden;
        sh.hidden = !open;
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        btn.innerHTML = open ? IC.x : IC.menu;
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && !sh.hidden) { sh.hidden = true; btn.setAttribute("aria-expanded", "false"); btn.innerHTML = IC.menu; }
      });
    }
    paintGate(gateState);
    startGate();
  }

  /* ---------------------------------------------------------------- membership */
  var gateState = "checking", gateFns = [], gateStarted = false;
  function paintGate(st) {
    var a = document.getElementById("dr-acts");
    if (a) a.innerHTML = acts(st);
    var s = document.getElementById("dr-sheet-acts");
    if (s) s.innerHTML = sheetActs(st);
    document.documentElement.setAttribute("data-member", st === "member" ? "1" : "0");
  }
  function setGate(st) {
    if (st === gateState && gateStarted) return;
    gateState = st;
    paintGate(st);
    gateFns.slice().forEach(function (fn) { try { fn(st); } catch (e) { if (window.console) console.error(e); } });
  }
  function startGate() {
    if (gateStarted) return;
    gateStarted = true;
    if (!window.ProGate) { setGate("unreachable"); return; }
    try {
      window.ProGate.start({ load: function () { setGate("member"); }, onState: function (st) { setGate(st); } });
    } catch (e) { setGate("unreachable"); }
  }
  var gate = {
    on: function (fn) { gateFns.push(fn); try { fn(gateState); } catch (e) { if (window.console) console.error(e); } },
    state: function () { return gateState; },
    member: function () { return gateState === "member"; }
  };

  /* The standard "rest of this board is PRO" bar. */
  function lockbar(o) {
    o = o || {};
    var st = gateState;
    var title = o.title || ((o.count ? plural(o.count, o.what || "more pick") : "The full board") + " — unlock with PRO");
    var sub = o.sub || "Every prop on every board, the research behind each one, and the full graded record. $15/mo — cancel anytime.";
    var actsHtml;
    if (st === "checking") actsHtml = '<span class="gate-line"><span class="spin" aria-hidden="true"></span>Checking your membership…</span>';
    else if (st === "billing") actsHtml = '<button class="btn btn--pro" type="button" data-gate-portal>Fix billing</button>';
    else if (st === "unreachable") actsHtml = '<button class="btn btn--ghost" type="button" data-gate-retry>Retry login</button><a class="btn btn--pro" href="' + u("/pro/") + '">Get PRO</a>';
    else actsHtml = '<a class="btn btn--pro pay-cta" href="' + u("/pro/") + '">Get PRO — $15/mo</a>' +
      (st === "lapsed" ? "" : '<a class="dr-link ms-login" href="' + u("/pro/") + '#login">Log in</a>');
    var why = st === "lapsed" ? "You're logged in, but this account doesn't have PRO yet." :
      st === "unreachable" ? "Couldn't reach the login service — often a content blocker. Allow dfsradar.com and retry." : sub;
    return '<div class="lockbar"><div class="row" style="align-items:flex-start;gap:14px"><span class="lock-ic">' + IC.lock + "</span>" +
      '<div><div class="t">' + esc(title) + '</div><div class="s">' + esc(why) + "</div></div></div>" +
      '<div class="acts">' + actsHtml + "</div></div>";
  }

  /* Blurred stand-in rows: shape only, never the real names. */
  var FAKE = ["A. Placeholder", "J. Hidden", "M. Locked", "R. Private", "T. Members", "K. Subscriber", "D. Onlyfor", "S. Propro"];
  function fakeRows(n, cols) {
    var out = "";
    for (var i = 0; i < n; i++) {
      out += '<tr class="lock-row" aria-hidden="true">';
      for (var c = 0; c < cols; c++) {
        out += "<td" + (c > 1 ? ' class="num"' : "") + '><span class="lock-fake">' +
          (c === 0 ? (i + 2) : c === 1 ? FAKE[i % FAKE.length] : c === 2 ? "22.4%" : "+310") + "</span></td>";
      }
      out += "</tr>";
    }
    return out;
  }

  /* ---------------------------------------------------------------- freshness */
  function fresh(el, info) {
    if (!el) return null;
    if (window.RadarFresh) return window.RadarFresh.render(el, info);
    return null;
  }
  function banner(el, title, body) { if (window.RadarFresh) window.RadarFresh.banner(el, title, body); }

  /* ---------------------------------------------------------------- detail sheet */
  var sheetEl = null, lastFocus = null, onSheetClose = null;
  function ensureSheet() {
    if (sheetEl) return sheetEl;
    sheetEl = document.createElement("div");
    sheetEl.className = "sheet";
    sheetEl.hidden = true;
    sheetEl.setAttribute("role", "dialog");
    sheetEl.setAttribute("aria-modal", "true");
    sheetEl.innerHTML = '<div class="sheet__box"><div class="sheet__bar"><div class="t" id="sheet-t"></div>' +
      '<button class="sheet__x" type="button" aria-label="Close">' + IC.x + '</button></div><div class="sheet__body" id="sheet-b"></div></div>';
    document.body.appendChild(sheetEl);
    sheetEl.addEventListener("click", function (e) { if (e.target === sheetEl) closeSheet(); });
    sheetEl.querySelector(".sheet__x").addEventListener("click", function () { closeSheet(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && sheetEl && !sheetEl.hidden) closeSheet(); });
    return sheetEl;
  }
  function openSheet(title, html, onClose) {
    var s = ensureSheet();
    lastFocus = document.activeElement;
    onSheetClose = onClose || null;
    s.querySelector("#sheet-t").textContent = title || "";
    s.setAttribute("aria-label", title || "Details");
    s.querySelector("#sheet-b").innerHTML = html;
    s.hidden = false;
    s.scrollTop = 0;
    document.body.classList.add("no-scroll");
    var x = s.querySelector(".sheet__x");
    if (x) x.focus({ preventScroll: true });
    return s.querySelector("#sheet-b");
  }
  function closeSheet(silent) {
    if (!sheetEl || sheetEl.hidden) return;
    sheetEl.hidden = true;
    sheetEl.querySelector("#sheet-b").innerHTML = "";
    document.body.classList.remove("no-scroll");
    var fn = onSheetClose; onSheetClose = null;
    if (fn && !silent) { try { fn(); } catch (e) {} }
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus({ preventScroll: true }); } catch (e) {} }
  }

  /* hash routes: #g=<id>  (deep links + back button close the sheet) */
  function hashParam(k) {
    var m = new RegExp("(?:^|[#&])" + k + "=([^&]+)").exec(location.hash);
    return m ? decodeURIComponent(m[1]) : null;
  }
  function setHash(k, v) {
    var h = v == null ? "" : "#" + k + "=" + encodeURIComponent(v);
    if (h === location.hash || (!h && !location.hash)) return;
    if (h) history.pushState(null, "", location.pathname + location.search + h);
    else history.replaceState(null, "", location.pathname + location.search);
  }

  /* ---------------------------------------------------------------- weather bits */
  /* Roth-style hourly table: hours across the top, measures down the side. */
  function hourly(hours, rows, opt) {
    opt = opt || {};
    if (!hours || !hours.length) return "";
    var head = "<tr><th></th>" + hours.map(function (h) {
      return '<th class="' + (h.fp ? "fp" : "") + '">' + (h.c ? '<span class="ic" aria-hidden="true">' + emo(h.c) + "</span>" : "") + esc(h.lab) + "</th>";
    }).join("") + "</tr>";
    var body = rows.map(function (r) {
      return "<tr><th scope=\"row\">" + esc(r.k) + "</th>" + hours.map(function (h) {
        var v = r.f(h), cls = r.cls ? r.cls(h) : "";
        return '<td class="' + (h.fp ? "fp " : "") + (cls || "") + '">' + (v == null ? "—" : v) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    return '<div class="hr-wrap' + (opt.full ? " hr-wrap--full" : "") + '"><table class="hr-tbl"><thead>' + head + "</thead><tbody>" + body + "</tbody></table></div>";
  }
  function rainCls(v) { return !isNum(v) ? "" : v >= 50 ? "bad" : v >= 25 ? "warn" : v <= 10 ? "good" : ""; }

  /* Compass words from degrees (meteorological, where the wind comes FROM). */
  function compass(deg) {
    if (!isNum(deg)) return "";
    return ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"][Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];
  }

  /* Ballpark wind: a diamond seen from above, arrow drawn in the direction the
     wind blows relative to the field (0 = straight out to centre, 180 = in). */
  function parkWind(angle, mph, dome, size) {
    size = size || 52;
    var c = 26;
    var field = '<path d="M26 8 L44 26 L26 44 L8 26 Z" fill="rgba(34,197,94,.10)" stroke="rgba(255,255,255,.28)" stroke-width="1.2"/>' +
      '<path d="M26 32 L32 26 L26 20 L20 26 Z" fill="none" stroke="rgba(255,255,255,.35)" stroke-width="1"/>' +
      '<circle cx="26" cy="38.6" r="1.6" fill="rgba(255,255,255,.55)"/>';
    if (dome) {
      return '<svg class="wd" viewBox="0 0 52 52" width="' + size + '" height="' + size + '" aria-hidden="true">' +
        '<path d="M5 30 A21 21 0 0 1 47 30" fill="none" stroke="rgba(255,255,255,.35)" stroke-width="1.6"/>' + field + "</svg>";
    }
    if (!isNum(angle) || !isNum(mph) || mph < 1) {
      return '<svg class="wd" viewBox="0 0 52 52" width="' + size + '" height="' + size + '" aria-hidden="true">' + field + "</svg>";
    }
    var out = Math.cos(angle * Math.PI / 180);          // +1 out, −1 in
    var col = out > 0.35 ? "#4ade80" : out < -0.35 ? "#93b4dd" : "#DDE2EC";
    var len = 12 + Math.min(mph, 25) / 25 * 9;
    var a = (angle - 90) * Math.PI / 180;               // 0° = up the screen (toward CF)
    var hx = Math.cos(a), hy = Math.sin(a), cx = 26, cy = 27;
    var x1 = cx - hx * len * 0.75, y1 = cy - hy * len * 0.75, x2 = cx + hx * len, y2 = cy + hy * len;
    var head = x2.toFixed(1) + "," + y2.toFixed(1) + " " + (x2 - hx * 7.5 - hy * 5.2).toFixed(1) + "," + (y2 - hy * 7.5 + hx * 5.2).toFixed(1) + " " +
      (x2 - hx * 7.5 + hy * 5.2).toFixed(1) + "," + (y2 - hy * 7.5 - hx * 5.2).toFixed(1);
    return '<svg class="wd" viewBox="0 0 52 52" width="' + size + '" height="' + size + '" aria-hidden="true">' + field +
      '<line x1="' + x1.toFixed(1) + '" y1="' + y1.toFixed(1) + '" x2="' + (x2 - hx * 5).toFixed(1) + '" y2="' + (y2 - hy * 5).toFixed(1) + '" stroke="' + col + '" stroke-width="3.2" stroke-linecap="round"/>' +
      '<polygon points="' + head + '" fill="' + col + '"/></svg>';
  }

  /* The big version: a ballpark from above (fan-shaped outfield, labelled
     fields) with the wind drawn across it. Same angle convention. */
  function parkWindBig(angle, mph, dome) {
    var W = 320, H = 250, hx0 = 160, hy0 = 226, R = 178;
    var P = function (deg, r) { var a = (deg - 90) * Math.PI / 180; return [hx0 + Math.cos(a) * r, hy0 + Math.sin(a) * r]; };
    var lf = P(-45, R), rf = P(45, R);
    var fan = "M" + hx0 + " " + hy0 + " L" + lf[0].toFixed(1) + " " + lf[1].toFixed(1) + " A" + R + " " + R + " 0 0 1 " + rf[0].toFixed(1) + " " + rf[1].toFixed(1) + " Z";
    var b1 = P(-45, 64), b2 = P(0, 90.5), b3 = P(45, 64);
    var dia = "M" + hx0 + " " + hy0 + " L" + b3[0].toFixed(1) + " " + b3[1].toFixed(1) + " L" + b2[0].toFixed(1) + " " + b2[1].toFixed(1) + " L" + b1[0].toFixed(1) + " " + b1[1].toFixed(1) + " Z";
    var lab = function (deg, t) { var p = P(deg, R + 14); return '<text x="' + p[0].toFixed(1) + '" y="' + (p[1] + 4).toFixed(1) + '" text-anchor="middle" font-size="11" font-weight="700" letter-spacing=".08em" fill="#8E97AD" font-family="Ubuntu,sans-serif">' + t + "</text>"; };
    var base = '<path d="' + fan + '" fill="rgba(34,197,94,.09)" stroke="rgba(255,255,255,.22)" stroke-width="1.4"/>' +
      '<path d="' + dia + '" fill="rgba(200,160,110,.10)" stroke="rgba(255,255,255,.3)" stroke-width="1.2"/>' +
      '<circle cx="' + hx0 + '" cy="' + hy0 + '" r="3" fill="#EFF1F7"/>' + lab(-38, "LF") + lab(0, "CF") + lab(38, "RF");
    var svg = function (inner) { return '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" style="max-width:420px" role="img" aria-label="Wind diagram">' + inner + "</svg>"; };
    if (dome) return svg(base + '<text x="160" y="130" text-anchor="middle" font-size="15" font-weight="700" fill="#C7CEDC" font-family="Sora,sans-serif">Roof closed</text>');
    if (!isNum(angle) || !isNum(mph) || mph < 2) return svg(base + '<text x="160" y="130" text-anchor="middle" font-size="15" font-weight="700" fill="#C7CEDC" font-family="Sora,sans-serif">Calm</text>');
    var out = Math.cos(angle * Math.PI / 180);
    var col = out > 0.35 ? "#4ade80" : out < -0.35 ? "#93b4dd" : "#DDE2EC";
    var a = (angle - 90) * Math.PI / 180, ux = Math.cos(a), uy = Math.sin(a), nx = -uy, ny = ux;
    var len = 46 + Math.min(mph, 25) / 25 * 62, cx = 160, cy = 142;
    var arrow = function (ox, oy, L, w, op) {
      var x1 = cx + ox - ux * L / 2, y1 = cy + oy - uy * L / 2, x2 = cx + ox + ux * L / 2, y2 = cy + oy + uy * L / 2, hs = w * 3.2;
      return '<g opacity="' + op + '"><line x1="' + x1.toFixed(1) + '" y1="' + y1.toFixed(1) + '" x2="' + (x2 - ux * hs * 0.8).toFixed(1) + '" y2="' + (y2 - uy * hs * 0.8).toFixed(1) + '" stroke="' + col + '" stroke-width="' + w + '" stroke-linecap="round"/>' +
        '<polygon points="' + x2.toFixed(1) + "," + y2.toFixed(1) + " " + (x2 - ux * hs - nx * hs * 0.62).toFixed(1) + "," + (y2 - uy * hs - ny * hs * 0.62).toFixed(1) + " " + (x2 - ux * hs + nx * hs * 0.62).toFixed(1) + "," + (y2 - uy * hs + ny * hs * 0.62).toFixed(1) + '" fill="' + col + '"/></g>';
    };
    var streams = arrow(nx * 44, ny * 44, len * 0.62, 2, 0.35) + arrow(-nx * 44, -ny * 44, len * 0.62, 2, 0.35) + arrow(0, 0, len, 5, 1);
    var tx = cx - ux * (len / 2 + 16), ty = cy - uy * (len / 2 + 16);
    var tag = '<g transform="translate(' + tx.toFixed(1) + "," + ty.toFixed(1) + ')"><rect x="-30" y="-13" width="60" height="26" rx="13" fill="#252A35" stroke="' + col + '" stroke-opacity=".6"/>' +
      '<text x="0" y="4.5" text-anchor="middle" font-size="12.5" font-weight="700" fill="' + col + '" font-family="Ubuntu,sans-serif">' + Math.round(mph) + " mph</text></g>";
    return svg(base + streams + tag);
  }

  /* Football field from above; ax = degrees between the wind and the long axis. */
  function fieldWind(ax, mph, dome, size) {
    size = size || 52;
    var f = '<rect x="4" y="15" width="44" height="22" rx="2" fill="rgba(34,197,94,.10)" stroke="rgba(255,255,255,.28)" stroke-width="1.2"/>' +
      '<path d="M9 15v22M43 15v22M26 15v22" stroke="rgba(255,255,255,.22)" stroke-width="1"/>';
    if (dome) return '<svg class="wd" viewBox="0 0 52 52" width="' + size + '" height="' + size + '" aria-hidden="true"><path d="M3 34 A23 23 0 0 1 49 34" fill="none" stroke="rgba(255,255,255,.35)" stroke-width="1.6"/>' + f + "</svg>";
    if (!isNum(ax) || !isNum(mph) || mph < 1) return '<svg class="wd" viewBox="0 0 52 52" width="' + size + '" height="' + size + '" aria-hidden="true">' + f + "</svg>";
    var a = -Math.max(0, Math.min(90, ax)) * Math.PI / 180;
    var col = ax <= 35 ? "#fcd34d" : ax >= 60 ? "#93b4dd" : "#C7CEDC";
    var len = 10 + Math.min(mph, 25) / 25 * 9;
    var cx = 26, cy = 26;
    var hx = Math.cos(a), hy = Math.sin(a);
    var x1 = cx - hx * len, y1 = cy - hy * len, x2 = cx + hx * len, y2 = cy + hy * len;
    var head = x2 + "," + y2 + " " + (x2 - hx * 6 - hy * 4.2) + "," + (y2 - hy * 6 + hx * 4.2) + " " + (x2 - hx * 6 + hy * 4.2) + "," + (y2 - hy * 6 - hx * 4.2);
    return '<svg class="wd" viewBox="0 0 52 52" width="' + size + '" height="' + size + '" aria-hidden="true">' + f +
      '<line x1="' + x1.toFixed(1) + '" y1="' + y1.toFixed(1) + '" x2="' + (x2 - hx * 4).toFixed(1) + '" y2="' + (y2 - hy * 4).toFixed(1) + '" stroke="' + col + '" stroke-width="2.6" stroke-linecap="round"/>' +
      '<polygon points="' + head + '" fill="' + col + '"/></svg>';
  }

  /* The big football field: end zones left and right, wind drawn at its angle
     to the long axis (we know the angle, not which end it blows toward). */
  function fieldWindBig(ax, mph, dome) {
    var W = 340, H = 200, x0 = 20, y0 = 30, fw = 300, fh = 140, ez = 26;
    var lines = "";
    for (var i = 1; i < 10; i++) { var x = x0 + ez + (fw - 2 * ez) * i / 10; lines += '<line x1="' + x.toFixed(1) + '" y1="' + y0 + '" x2="' + x.toFixed(1) + '" y2="' + (y0 + fh) + '" stroke="rgba(255,255,255,' + (i === 5 ? ".32" : ".14") + ')" stroke-width="1"/>'; }
    var base = '<rect x="' + x0 + '" y="' + y0 + '" width="' + fw + '" height="' + fh + '" rx="4" fill="rgba(34,197,94,.09)" stroke="rgba(255,255,255,.25)" stroke-width="1.4"/>' +
      '<rect x="' + x0 + '" y="' + y0 + '" width="' + ez + '" height="' + fh + '" fill="rgba(255,255,255,.04)"/><rect x="' + (x0 + fw - ez) + '" y="' + y0 + '" width="' + ez + '" height="' + fh + '" fill="rgba(255,255,255,.04)"/>' + lines;
    var svg = function (inner) { return '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" style="max-width:440px" role="img" aria-label="Wind diagram">' + inner + "</svg>"; };
    var mid = function (t) { return '<text x="170" y="' + (y0 + fh / 2 + 5) + '" text-anchor="middle" font-size="15" font-weight="700" fill="#C7CEDC" font-family="Sora,sans-serif">' + t + "</text>"; };
    if (dome) return svg(base + mid("Roof closed"));
    if (!isNum(mph) || mph < 2) return svg(base + mid("Calm"));
    if (ax == null || !isNum(ax)) return svg(base + mid(Math.round(mph) + " mph · direction not on file"));
    var col = ax <= 30 ? "#fcd34d" : ax >= 60 ? "#93b4dd" : "#DDE2EC";
    var a = -Math.max(0, Math.min(90, ax)) * Math.PI / 180, ux = Math.cos(a), uy = Math.sin(a), nx = -uy, ny = ux;
    var len = 60 + Math.min(mph, 25) / 25 * 80, cx = 170, cy = y0 + fh / 2;
    var arrow = function (ox, oy, L, w, op) {
      var x1 = cx + ox - ux * L / 2, y1 = cy + oy - uy * L / 2, x2 = cx + ox + ux * L / 2, y2 = cy + oy + uy * L / 2, hs = w * 3.2;
      return '<g opacity="' + op + '"><line x1="' + x1.toFixed(1) + '" y1="' + y1.toFixed(1) + '" x2="' + (x2 - ux * hs * 0.8).toFixed(1) + '" y2="' + (y2 - uy * hs * 0.8).toFixed(1) + '" stroke="' + col + '" stroke-width="' + w + '" stroke-linecap="round"/>' +
        '<polygon points="' + x2.toFixed(1) + "," + y2.toFixed(1) + " " + (x2 - ux * hs - nx * hs * 0.62).toFixed(1) + "," + (y2 - uy * hs - ny * hs * 0.62).toFixed(1) + " " + (x2 - ux * hs + nx * hs * 0.62).toFixed(1) + "," + (y2 - uy * hs + ny * hs * 0.62).toFixed(1) + '" fill="' + col + '"/></g>';
    };
    var tx = cx - ux * (len / 2 + 30), ty = cy - uy * (len / 2 + 30);
    tx = Math.max(52, Math.min(W - 52, tx)); ty = Math.max(16, Math.min(H - 16, ty));
    var tag = '<g transform="translate(' + tx.toFixed(1) + "," + ty.toFixed(1) + ')"><rect x="-30" y="-13" width="60" height="26" rx="13" fill="#252A35" stroke="' + col + '" stroke-opacity=".6"/>' +
      '<text x="0" y="4.5" text-anchor="middle" font-size="12.5" font-weight="700" fill="' + col + '" font-family="Ubuntu,sans-serif">' + Math.round(mph) + " mph</text></g>";
    return svg(base + arrow(nx * 38, ny * 38, len * 0.6, 2, 0.35) + arrow(-nx * 38, -ny * 38, len * 0.6, 2, 0.35) + arrow(0, 0, len, 5, 1) + tag);
  }

  /* Plain compass: arrow points where the wind is blowing TO (from = deg). */
  function compassWind(fromDeg, mph, size) {
    size = size || 52;
    var ring = '<circle cx="26" cy="26" r="20" fill="rgba(255,255,255,.03)" stroke="rgba(255,255,255,.25)" stroke-width="1.2"/>' +
      '<text x="26" y="10.5" text-anchor="middle" font-size="7" font-weight="700" fill="#8E97AD" font-family="Ubuntu,sans-serif">N</text>';
    if (!isNum(fromDeg) || !isNum(mph) || mph < 1) return '<svg class="wd" viewBox="0 0 52 52" width="' + size + '" height="' + size + '" aria-hidden="true">' + ring + "</svg>";
    var to = (fromDeg + 180) % 360;
    var a = (to - 90) * Math.PI / 180;
    var len = 9 + Math.min(mph, 25) / 25 * 7;
    var hx = Math.cos(a), hy = Math.sin(a);
    var x1 = 26 - hx * len, y1 = 27 - hy * len, x2 = 26 + hx * len, y2 = 27 + hy * len;
    var head = x2 + "," + y2 + " " + (x2 - hx * 6 - hy * 4.2) + "," + (y2 - hy * 6 + hx * 4.2) + " " + (x2 - hx * 6 + hy * 4.2) + "," + (y2 - hy * 6 - hx * 4.2);
    return '<svg class="wd" viewBox="0 0 52 52" width="' + size + '" height="' + size + '" aria-hidden="true">' + ring +
      '<line x1="' + x1.toFixed(1) + '" y1="' + y1.toFixed(1) + '" x2="' + (x2 - hx * 4).toFixed(1) + '" y2="' + (y2 - hy * 4).toFixed(1) + '" stroke="#C7CEDC" stroke-width="2.6" stroke-linecap="round"/>' +
      '<polygon points="' + head + '" fill="#C7CEDC"/></svg>';
  }

  /* −40% … +40% impact bar vs normal. */
  function impact(label, v, n) {
    if (!isNum(v)) return "";
    var w = Math.min(Math.abs(v), 40) / 40 * 50;
    var col = v >= 3 ? "var(--good)" : v <= -3 ? "var(--cool)" : "var(--line3)";
    var style = v >= 0 ? "left:50%;width:" + w + "%" : "right:50%;width:" + w + "%";
    return '<div class="imp"><span class="k">' + esc(label) + '</span><span class="bar"><i style="' + style + ";background:" + col + '"></i></span>' +
      '<span class="v ' + (v >= 3 ? "good" : v <= -3 ? "cool" : "dim") + '">' + signed(v, 0, "%") + "</span></div>";
  }

  /* ---------------------------------------------------------------- tabs */
  /* <div class="seg" role="tablist"> buttons with data-tab="x"; panels [data-panel="x"] */
  function tabs(root, onChange, key) {
    if (!root) return;
    var btns = $$("[data-tab]", root);
    var panels = btns.map(function (b) { return document.querySelector('[data-panel="' + b.getAttribute("data-tab") + '"]'); });
    function pick(k, focus) {
      btns.forEach(function (b, i) {
        var on = b.getAttribute("data-tab") === k;
        b.setAttribute("aria-selected", on ? "true" : "false");
        b.tabIndex = on ? 0 : -1;
        if (panels[i]) panels[i].hidden = !on;
        if (on && focus) b.focus();
      });
      if (key) { try { sessionStorage.setItem(key, k); } catch (e) {} }
      if (onChange) onChange(k);
    }
    btns.forEach(function (b, i) {
      b.setAttribute("role", "tab");
      b.addEventListener("click", function () { pick(b.getAttribute("data-tab")); });
      b.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        var j = (i + (e.key === "ArrowRight" ? 1 : btns.length - 1)) % btns.length;
        pick(btns[j].getAttribute("data-tab"), true);
      });
    });
    var start = null;
    if (key) { try { start = sessionStorage.getItem(key); } catch (e) {} }
    if (!start || !btns.some(function (b) { return b.getAttribute("data-tab") === start; })) {
      var cur = btns.filter(function (b) { return b.getAttribute("aria-selected") === "true"; })[0] || btns[0];
      start = cur && cur.getAttribute("data-tab");
    }
    if (start) pick(start);
    return { pick: pick };
  }

  /* ---------------------------------------------------------------- dates */
  function etParts(d) {
    try {
      var o = {};
      new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "long", month: "long", day: "numeric", year: "numeric" })
        .formatToParts(d).forEach(function (p) { o[p.type] = p.value; });
      return o;
    } catch (e) { return {}; }
  }
  function longDate(iso) {                  // "2026-09-25" -> "Friday, September 25"
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    if (!m) return "";
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], 16));
    return ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][d.getUTCDay()] + ", " +
      ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"][d.getUTCMonth()] + " " + d.getUTCDate();
  }
  /* ---------------------------------------------------------------- 3D venues
     venue3d.js (and three.js) load only when someone asks for the 3D view. */
  var v3dP = null;
  function load3d() {
    if (!v3dP) v3dP = new Promise(function (res, rej) {
      if (window.Venue3D) { res(); return; }
      var q = /\?[^#]*/.exec(me), sc = document.createElement("script");
      sc.src = u("/assets/venue3d.js") + (q ? q[0] : ""); sc.async = true;
      sc.onload = function () { if (window.Venue3D) res(); else rej(new Error("3D missing")); };
      sc.onerror = function () { rej(new Error("3D failed to load")); };
      document.head.appendChild(sc);
    }).then(function () { return window.Venue3D.load(); }).catch(function (e) { v3dP = null; throw e; });
    return v3dP;
  }
  var COARSE = !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
  /* view3d({ btn, box, flat, spec, chips, cap, label, onLabel, hideBox })
     wires a "View in 3D" button: the first press builds the 3D stage inside
     `box` (hiding `flat`), the second puts the flat view back. */
  function view3d(o) {
    var inst = null, stage = null, offHtml = o.btn.innerHTML;
    o.btn.setAttribute("aria-pressed", "false");
    function close() {
      if (inst && window.Venue3D) window.Venue3D.dispose(inst);
      inst = null;
      if (stage && stage.parentNode) stage.parentNode.removeChild(stage);
      stage = null;
      if (o.flat) o.flat.hidden = false;
      o.box.classList.remove("is-3d");
      if (o.hideBox) o.box.hidden = true;
      o.btn.innerHTML = offHtml; o.btn.setAttribute("aria-pressed", "false");
    }
    o.btn.addEventListener("click", function () {
      if (stage) { close(); return; }
      o.btn.disabled = true; o.btn.textContent = "Loading 3D…";
      load3d().then(function () {
        stage = document.createElement("div");
        stage.className = "v3d-wrap";
        stage.innerHTML = '<div class="v3d"><canvas role="img" aria-label="' + esc(o.label || "3D view") + '"></canvas>' +
          (o.chips && o.chips.length ? '<div class="v3d__hud">' + o.chips.join("") + "</div>" : "") +
          (COARSE ? "" : '<div class="v3d__hint">Drag to turn · Ctrl + scroll to zoom · double-click to reset</div>') + "</div>" +
          '<p class="v3d__note">' + (COARSE ? "<b>Swipe sideways to turn, pinch to zoom.</b> " : "") + esc(o.cap || "") + "</p>";
        if (o.hideBox) o.box.hidden = false;
        o.box.classList.add("is-3d");
        if (o.flat) o.flat.hidden = true;
        o.box.appendChild(stage);
        inst = window.Venue3D.mount(stage.querySelector("canvas"), o.spec);
        o.btn.disabled = false;
        if (!inst) { close(); o.btn.textContent = "3D isn't available on this device"; o.btn.disabled = true; return; }
        o.btn.textContent = o.onLabel || "Back to diagram"; o.btn.setAttribute("aria-pressed", "true");
      }).catch(function () { o.btn.disabled = false; o.btn.textContent = "3D didn't load — try again"; });
    });
    return { close: close };
  }
  function btn3d(label, attr) { return '<button class="btn btn--sm btn--ghost btn--3d" type="button" ' + (attr || "data-3d") + ">" + IC.cube + esc(label || "View in 3D") + "</button>"; }

  function todayET() { return window.RadarFresh ? window.RadarFresh.todayET() : new Date().toISOString().slice(0, 10); }

  window.DR = {
    BASE: BASE, u: u, esc: esc, $: $, $$: $$, isNum: isNum, fixed: fixed, signed: signed, pct: pct, odds: odds, validOdds: validOdds,
    implied: implied, payout: payout, plural: plural, tone: tone, MINUS: MINUS,
    get: get, IC: IC, wx: wx, emo: emo, sky: sky, SPORTS: SPORTS, sport: sport, shell: shell, gate: gate, lockbar: lockbar, fakeRows: fakeRows,
    fresh: fresh, banner: banner, sheet: { open: openSheet, close: closeSheet }, hashParam: hashParam, setHash: setHash,
    hourly: hourly, rainCls: rainCls, compass: compass, parkWind: parkWind, parkWindBig: parkWindBig, fieldWindBig: fieldWindBig, fieldWind: fieldWind, compassWind: compassWind,
    impact: impact, tabs: tabs, longDate: longDate, todayET: todayET, etParts: etParts, view3d: view3d, btn3d: btn3d
  };
})();
