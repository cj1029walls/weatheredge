/* DFSRADAR PRO · membership gate — one copy for every PRO page (the desk index and six desks).
 *
 * Who gets in: a DFSRADAR PRO ($15/mo) or DFS Kitchen All-Access ($60/mo) plan connection that
 * is ACTIVE or TRIALING. Everyone else gets the page's own paywall.
 *
 * Load it from <head>, after the page's <style>:  <script src="/pro/gate.js"></script>
 * (it injects its own CSS there, so the "Checking…" box is styled on first paint), then, once
 * the page's script has defined its loader, call
 *
 *     ProGate.start({ load: fn })     // fn runs once, the first time a member is confirmed —
 *                                     // desk data is never fetched before that or for anyone else
 *
 * Page parts it drives (all optional except #pro-app / #paywall):
 *   #gate-status   slot at the top of <main>; ships with "Checking your membership…"
 *   #member-bar    email · Account · Log out (#member-email inside) — logged-in visitors only
 *   #paywall       the sales hero. Its CSS says display:none, so it is shown with
 *                  display:"block" — setting "" would leave it hidden.
 *   #pro-app       the desk (inline display:none until a member is confirmed)
 *   .pay-cta       Subscribe          .pay-login / .ms-login   Log in
 *   .ms-logout     Log out            .ms-account               Account
 *   [data-gate-show="loggedout unreachable"]   shown only in the listed states
 *
 * States: checking · member · billing (PAST_DUE / UNPAID …: "Fix billing", not the sales
 * pitch) · lapsed (logged in, canceled or no plan: paywall + their email and Log out) ·
 * loggedout (paywall, never a Log out) · unreachable (Memberstack didn't load in ~6 s, or
 * errored on the first check: "Couldn't reach the login service" + Retry).
 *
 * Re-checks (tab refocus, auth changes) only move a visitor on a DEFINITE answer from
 * Memberstack. A network blip mid-session never hides a member's desk.
 */
(function () {
  "use strict";
  var APP_ID = "app_cmos1ov2900kh0swuf8r49fo1";
  var MS_SRC = "https://static.memberstack.com/scripts/v2/memberstack.js";
  var PLANS = { "pln_dfsradar-pro-mnvo0vbh": "DFSRADAR PRO",
                "pln_all-access-bundle-5kpn0n3d": "DFS Kitchen All-Access" };
  var PRO_PRICE = "prc_pro-monthly-rdvp0vis";          // $15/mo — the price every desk sells
  var OPEN = ["ACTIVE", "TRIALING"];
  var BILLING = ["PAST_DUE", "UNPAID", "REQUIRES_PAYMENT", "REQUIRES_AUTHENTICATION", "INCOMPLETE"];
  var WAIT_MS = 6000;                                  // how long Memberstack gets to appear
  var ASK_MS = 10000;                                  // how long one getCurrentMember may take

  /* ---------------------------------------------------------------- styles */
  var CSS = "" +
    ".gate-status{max-width:640px;margin:34px auto 30px}" +
    ".gate-status[hidden],[data-gate-show][hidden]{display:none!important}" +
    ".gate-status.is-note{max-width:none;margin:0 0 16px}" +
    ".gate-status.is-banner{max-width:none;margin:4px 0 22px}" +
    ".gate-box{background:#323A4A;border:1px solid #454E61;border-radius:16px;padding:26px 28px;" +
    "box-shadow:inset 0 1px 0 rgba(255,255,255,.05),0 1px 2px rgba(0,0,0,.35),0 10px 26px rgba(0,0,0,.24);" +
    "color:#C7CEDC;font:400 15px/1.6 Ubuntu,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;animation:gate-in .25s ease both}" +
    ".gate-box h2{font:700 20px/1.25 Sora,Ubuntu,-apple-system,sans-serif;letter-spacing:-.3px;color:#EFF1F7;margin:0 0 8px}" +
    ".gate-box p{margin:0 0 16px;max-width:60ch;font-size:14.5px}" +
    ".gate-box p:last-child{margin-bottom:0}" +
    ".gate-box b{color:#EFF1F7}" +
    ".gate-checking{display:flex;align-items:center;justify-content:center;gap:12px;min-height:120px;text-align:center}" +
    ".gate-checking .gt{font-weight:500;color:#EFF1F7}" +
    ".gate-checking .gs{display:block;font-size:13px;color:#8E97AD;margin-top:2px}" +
    ".gate-spin{flex:0 0 18px;width:18px;height:18px;border-radius:50%;border:2px solid rgba(34,211,238,.22);border-top-color:#22d3ee;animation:gate-spin .8s linear infinite}" +
    ".gate-warn{border-color:rgba(251,191,36,.42);background:linear-gradient(0deg,rgba(251,191,36,.07),rgba(251,191,36,.07)),#323A4A}" +
    ".gate-warn h2{color:#fcd34d}" +
    ".gate-acts{display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px}" +
    ".gate-btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 22px;border-radius:12px;" +
    "border:1px solid rgba(34,211,238,.55);background:rgba(34,211,238,.14);color:#EFF1F7;cursor:pointer;text-decoration:none;" +
    "font:700 14.5px/1 Ubuntu,-apple-system,BlinkMacSystemFont,sans-serif}" +
    ".gate-btn:hover{background:rgba(34,211,238,.24);color:#fff}" +
    ".gate-sub{font-size:13px;color:#8E97AD}" +
    ".gate-sub a{color:#67e8f9}" +
    ".gate-note{background:rgba(255,255,255,.035);border:1px solid #454E61;border-left:3px solid rgba(34,211,238,.6);" +
    "border-radius:12px;padding:12px 16px;font:400 14px/1.55 Ubuntu,-apple-system,BlinkMacSystemFont,sans-serif;color:#C7CEDC}" +
    ".gate-note b{color:#EFF1F7}" +
    "#member-bar{flex-wrap:wrap;gap:0}" +
    "#member-bar a{display:inline-flex;align-items:center;min-height:40px;padding:0 9px;cursor:pointer}" +
    "#member-email{overflow-wrap:anywhere;padding-right:9px}" +
    "@keyframes gate-spin{to{transform:rotate(360deg)}}" +
    "@keyframes gate-in{from{opacity:0}to{opacity:1}}" +
    "@media (prefers-reduced-motion:reduce){.gate-spin,.gate-box{animation:none}}" +
    "@media (max-width:640px){.gate-status{margin:18px auto 22px}.gate-box{padding:22px 20px}.gate-box h2{font-size:18px}}";
  (function injectCSS() {
    if (document.getElementById("gate-css")) return;
    var s = document.createElement("style");
    s.id = "gate-css";
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  })();

  /* Watch the Memberstack <script> itself: a Retry re-adds it only if it failed. */
  var msTag = document.querySelector("script[data-memberstack-app]");
  var msTagFailed = false;
  if (msTag) msTag.addEventListener("error", function () { msTagFailed = true; });

  /* ----------------------------------------------------------------- state */
  var S = { state: "checking", member: null, plan: null, why: "", loaded: false, opts: {},
            inflight: null, last: 0, wired: false, watching: false, authHooked: false,
            loginAsked: false, injectedAt: 0 };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function ms() { return window.$memberstackDom || null; }

  function msReady(timeout) {
    return new Promise(function (res) {
      var t0 = Date.now();
      (function poll() {
        if (window.$memberstackDom) return res(window.$memberstackDom);
        if (Date.now() - t0 >= timeout) return res(null);
        setTimeout(poll, 150);
      })();
    });
  }

  function withTimeout(p, t) {
    return Promise.race([p, new Promise(function (_, rej) {
      setTimeout(function () { rej(new Error("timeout")); }, t);
    })]);
  }

  /* One plan connection list -> which door this visitor gets. */
  function classify(member) {
    if (!member) return { state: "loggedout", plan: null };
    var ours = (member.planConnections || []).filter(function (pc) { return pc && PLANS[pc.planId]; });
    var st = function (pc) { return String(pc.status || "").toUpperCase(); };
    var open = ours.filter(function (pc) { return OPEN.indexOf(st(pc)) >= 0; })[0];
    if (open) return { state: "member", plan: open };
    var owed = ours.filter(function (pc) { return BILLING.indexOf(st(pc)) >= 0; })[0];
    if (owed) return { state: "billing", plan: owed };
    return { state: "lapsed", plan: ours[0] || null };
  }

  /* Ask Memberstack. Returns a DEFINITE state (member / billing / lapsed / loggedout) or
     "unreachable" (not loaded) / "error" (it answered badly) — never guessed. */
  function ask(timeout) {
    return msReady(timeout).then(function (m) {
      if (!m) return { state: "unreachable" };
      return withTimeout(Promise.resolve().then(function () { return m.getCurrentMember(); }), ASK_MS)
        .then(function (r) {
          if (!r || typeof r !== "object" || !("data" in r)) return { state: "error" };
          var member = r.data || null;
          var c = classify(member);
          return { state: c.state, plan: c.plan, member: member };
        }, function (e) { return { state: "error", error: e }; });
    });
  }

  /* ---------------------------------------------------------------- render */
  function email() { return (S.member && S.member.auth && S.member.auth.email) || ""; }
  function planName() { return (S.plan && PLANS[S.plan.planId]) || "DFSRADAR PRO"; }

  function statusBox() {
    var st = S.state;
    if (st === "checking") {
      return ["", '<div class="gate-box gate-checking" role="status"><span class="gate-spin" aria-hidden="true"></span>' +
        '<span><span class="gt">' + esc(S.why || "Checking your membership…") + '</span>' +
        '<span class="gs">Your desks open as soon as your login is confirmed.</span></span></div>'];
    }
    if (st === "unreachable") {
      return ["", '<div class="gate-box gate-warn" role="alert"><h2>Couldn’t reach the login service</h2>' +
        "<p>" + (S.why ? esc(S.why) + " " : "") + "Your membership is checked by our login service (Memberstack), and it didn’t load. " +
        "That’s usually a content blocker — <b>disable content blockers for dfsradar.com</b>, or retry.</p>" +
        '<div class="gate-acts"><button type="button" class="gate-btn" data-gate-retry>Retry</button>' +
        '<span class="gate-sub">Still stuck? <a href="' + esc(location.pathname) + '">Reload the page</a> after allowing the site.</span></div></div>'];
    }
    if (st === "billing") {
      var e = email();
      return ["is-banner", '<div class="gate-box gate-warn" role="alert"><h2>Your last payment didn’t go through</h2>' +
        "<p>" + esc(planName()) + (e ? " on <b>" + esc(e) + "</b>" : "") + " is past due, so the desks are locked until the card " +
        "on file is updated. Fixing billing reopens every desk right away.</p>" +
        '<div class="gate-acts"><button type="button" class="gate-btn" data-gate-portal>Fix billing</button>' +
        '<span class="gate-sub">Opens the secure billing portal · <a href="#" class="ms-logout">Log out</a></span></div></div>'];
    }
    if (st === "lapsed") {
      var em = email(), ended = S.plan && String(S.plan.status || "").toUpperCase() === "CANCELED";
      var msg = ended
        ? "Your " + esc(planName()) + " subscription" + (em ? " on <b>" + esc(em) + "</b>" : "") + " has ended — subscribe again below and the desks reopen right away."
        : "You’re logged in" + (em ? " as <b>" + esc(em) + "</b>" : "") + ", but this account doesn’t have DFSRADAR PRO or All-Access yet.";
      return ["is-note", '<div class="gate-note" role="status">' + msg + "</div>"];
    }
    return null;
  }

  function show(el, disp) { if (el) el.style.display = disp; }

  function render() {
    var st = S.state, box = $("gate-status");
    document.documentElement.setAttribute("data-gate", st);
    show($("pro-app"), st === "member" ? "block" : "none");
    show($("paywall"), (st === "loggedout" || st === "lapsed") ? "block" : "none");   // "block", never ""
    var bar = $("member-bar"), loggedIn = st === "member" || st === "billing" || st === "lapsed";
    if (bar) {
      bar.style.display = loggedIn ? "flex" : "none";
      var me = $("member-email");
      if (me) me.textContent = loggedIn ? email() : "";
    }
    if (box) {
      var b = statusBox();
      if (b) { box.className = ("gate-status " + b[0]).trim(); box.innerHTML = b[1]; box.hidden = false; }
      else { box.hidden = true; box.innerHTML = ""; box.className = "gate-status"; }
    }
    Array.prototype.forEach.call(document.querySelectorAll("[data-gate-show]"), function (el) {
      el.hidden = (" " + el.getAttribute("data-gate-show") + " ").indexOf(" " + st + " ") < 0;
    });
    if (typeof S.opts.onState === "function") { try { S.opts.onState(st); } catch (e) { /* page hook only */ } }
  }

  function setState(res) {
    S.state = res.state;
    if (res.state === "loggedout") { S.member = null; S.plan = null; }
    else if ("member" in res) { S.member = res.member; S.plan = res.plan || null; }
    S.why = res.why || "";
    render();
    if (S.state === "member" && !S.loaded) {
      S.loaded = true;
      try { if (typeof S.opts.load === "function") S.opts.load(); }
      catch (e) { if (window.console) console.error("desk load", e); }
    }
  }

  function definite(st) { return st === "member" || st === "billing" || st === "lapsed" || st === "loggedout"; }

  /* ------------------------------------------------------- re-checks */
  function hookAuth() {
    var m = ms();
    if (!m || S.authHooked || typeof m.onAuthChange !== "function") return;
    S.authHooked = true;
    try { m.onAuthChange(function () { recheck(true); }); } catch (e) { /* optional API */ }
  }

  /* A later look: moves the visitor ONLY on a definite answer. */
  function recheck(force) {
    if (S.state === "checking") return Promise.resolve();
    if (S.inflight) return S.inflight;
    if (!force && Date.now() - S.last < 5000) return Promise.resolve();
    S.inflight = ask(S.state === "unreachable" ? 1500 : 0).then(function (res) {
      S.last = Date.now();
      S.inflight = null;
      if (definite(res.state)) { setState(res); hookAuth(); }
      /* "error" / "unreachable" is not an answer: whatever is on screen stays. */
      return res;
    });
    return S.inflight;
  }

  function watchForMemberstack() {
    if (S.watching) return;
    S.watching = true;
    var t0 = Date.now();
    (function tick() {
      if (S.state !== "unreachable") { S.watching = false; return; }
      if (ms()) { S.watching = false; firstLook(0); return; }
      if (Date.now() - t0 > 120000) { S.watching = false; return; }
      setTimeout(tick, 1000);
    })();
  }

  function reinject() {
    if (ms()) return;
    if (Date.now() - S.injectedAt < 8000) return;
    var loaded = msTag && msTag.getAttribute("data-gate-loaded") === "1";
    if (msTag && !msTagFailed && loaded) return;          // it ran; a second copy won't help
    S.injectedAt = Date.now();
    try {
      if (msTag && msTagFailed && msTag.parentNode) msTag.parentNode.removeChild(msTag);
      var s = document.createElement("script");
      s.src = MS_SRC;
      s.setAttribute("data-memberstack-app", APP_ID);
      s.async = true;
      msTagFailed = false;
      s.addEventListener("error", function () { msTagFailed = true; });
      s.addEventListener("load", function () { s.setAttribute("data-gate-loaded", "1"); });
      document.head.appendChild(s);
      msTag = s;
    } catch (e) { /* nothing more to try */ }
  }
  if (msTag) msTag.addEventListener("load", function () { msTag.setAttribute("data-gate-loaded", "1"); });

  /* The first answer on this page view (also used by Retry). */
  function firstLook(timeout, why) {
    S.state = "checking"; S.why = why || ""; render();
    return ask(timeout).then(function (res) {
      if (res.state === "error" || res.state === "unreachable") {
        setState({ state: "unreachable", why: "" });
        watchForMemberstack();
        return res;
      }
      S.last = Date.now();
      setState(res);
      hookAuth();
      if (location.hash === "#login" && !S.loginAsked && res.state === "loggedout") {
        S.loginAsked = true;
        openLogin();
      }
      return res;
    });
  }

  /* ------------------------------------------------------- actions */
  function needService(why) {
    /* Log in / Subscribe clicked while Memberstack is missing: try once more, visibly. */
    reinject();
    S.state = "checking"; S.why = "Connecting to the login service…"; render();
    return msReady(WAIT_MS).then(function (m) {
      if (!m) { setState({ state: "unreachable", why: why }); watchForMemberstack(); }
      return m;
    });
  }

  function openLogin() {
    var m = ms();
    var go = m ? Promise.resolve(m) : needService("Log in needs it too.");
    return go.then(function (mm) {
      if (!mm) return;
      return Promise.resolve().then(function () { return mm.openModal("LOGIN"); })
        .catch(function () { /* closed or failed: the re-check below tells */ })
        .then(function () { try { mm.hideModal(); } catch (e) { /* already closed */ } })
        .then(function () { return S.state === "checking" ? firstLook(2000) : recheck(true); });
    });
  }

  function buy() {
    var m = ms();
    var go = m ? Promise.resolve(m) : needService("Checkout needs it too.");
    return go.then(function (mm) {
      if (!mm) return;
      var member = null;
      return Promise.resolve().then(function () { return mm.getCurrentMember(); })
        .then(function (r) { member = r && r.data; }, function () { /* treat as logged out */ })
        .then(function () {
          if (member) return member;
          return Promise.resolve().then(function () { return mm.openModal("SIGNUP"); })
            .then(function (r) { try { mm.hideModal(); } catch (e) { /* closed */ } return r && r.data; },
                  function () { return null; });
        })
        .then(function (mem) {
          if (!mem) { if (S.state === "checking") return firstLook(2000); return; }
          return ask(2000).then(function (res) {
            if (definite(res.state)) setState(res);
            if (S.state === "member" || S.state === "billing") return;   // All-Access / PRO already — or billing: fix, don't re-buy
            return Promise.resolve().then(function () {
              return mm.purchasePlansWithCheckout({ priceId: PRO_PRICE,
                successUrl: location.origin + location.pathname,
                cancelUrl: location.origin + location.pathname });
            }).catch(function (e) {
              if (window.console) console.error("checkout", e);
              var box = $("gate-status");
              if (box) {
                box.className = "gate-status is-note"; box.hidden = false;
                box.innerHTML = '<div class="gate-note" role="alert">Couldn’t open checkout — please try again, or log in first if you already have an account.</div>';
              }
            });
          });
        });
    });
  }

  function portal() {
    var m = ms();
    if (!m) return needService("The billing portal needs it too.");
    var p = typeof m.launchStripeCustomerPortal === "function"
      ? Promise.resolve().then(function () { return m.launchStripeCustomerPortal({ returnUrl: location.href }); })
      : Promise.reject(new Error("no portal"));
    return p.catch(function () {
      return Promise.resolve().then(function () { return m.openModal("PROFILE"); }).catch(function () { /* nothing else to open */ });
    });
  }

  function account() {
    if (S.state === "billing") return portal();
    var m = ms();
    if (!m) return needService("");
    return Promise.resolve().then(function () { return m.openModal("PROFILE"); }).catch(function () { /* closed */ })
      .then(function () { return recheck(true); });
  }

  function logout() {
    var m = ms();
    var p = m ? Promise.resolve().then(function () { return m.logout(); }).catch(function () { /* already out */ }) : Promise.resolve();
    return p.then(function () { return ask(2500); }).then(function (res) {
      /* The visitor asked to leave: anything but "still a member" is logged out. */
      setState(definite(res.state) && res.state !== "member" ? res : { state: "loggedout" });
    });
  }

  function retry() {
    reinject();
    return firstLook(WAIT_MS);
  }

  function wire() {
    if (S.wired) return;
    S.wired = true;
    document.addEventListener("click", function (e) {
      var t = e.target && e.target.closest ? e.target : null;
      if (!t) return;
      var hit;
      if ((hit = t.closest(".pay-cta"))) { e.preventDefault(); buy(); return; }
      if ((hit = t.closest(".pay-login, .ms-login"))) { e.preventDefault(); openLogin(); return; }
      if ((hit = t.closest(".ms-logout"))) { e.preventDefault(); logout(); return; }
      if ((hit = t.closest(".ms-account"))) { e.preventDefault(); account(); return; }
      if ((hit = t.closest("[data-gate-portal]"))) { e.preventDefault(); portal(); return; }
      if ((hit = t.closest("[data-gate-retry]"))) { e.preventDefault(); retry(); return; }
    });
    document.addEventListener("visibilitychange", function () { if (!document.hidden) recheck(false); });
    window.addEventListener("focus", function () { recheck(false); });
  }

  function start(opts) {
    S.opts = opts || {};
    wire();
    return firstLook(WAIT_MS);
  }

  window.ProGate = {
    start: start,
    recheck: recheck,
    login: openLogin,
    buy: buy,
    logout: logout,
    state: function () { return S.state; },
    PRO_PRICE: PRO_PRICE
  };
})();
