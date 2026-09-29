/* QuizPop SmartLink tracking (Playbook Phase 5).
   - SMARTLINK is a placeholder. Replace ONCE here at deploy time with your
     real Monetag Direct Link. Never commit the real link to a public repo.
   - The link fires ONLY from a user click on a clearly-labeled Sponsored CTA
     (a[data-smartlink]). Never auto-fire on load, scroll, or quiz completion.
   - UTM params are attached at click-time so crawlers never index them. */
var SMARTLINK = "YOUR_MONETAG_SMARTLINK"; // ← replace at deploy

function smartlinkURL(source, campaign, content) {
  var u = new URL(SMARTLINK);
  u.searchParams.set("utm_source", source);       // tiktok | youtube | pinterest | organic
  u.searchParams.set("utm_medium", "smartlink");
  u.searchParams.set("utm_campaign", campaign);    // quiz_funnel
  u.searchParams.set("utm_content", content);      // page-slug__cta-id
  return u.toString();
}

document.querySelectorAll("a[data-smartlink]").forEach(function (a) {
  a.addEventListener("click", function () {
    var page = location.pathname.replace(/\//g, "") || "home";
    var src = "organic";
    try { src = new URLSearchParams(location.search).get("src") || "organic"; } catch (e) {}
    // GA4 event
    if (window.gtag) {
      gtag("event", "smartlink_click", {
        page_slug: page,
        cta_id: a.getAttribute("data-cta") || "unknown",
        traffic_source: src
      });
    }
    // Local backup log (survives ad-blockers that kill GA)
    try {
      var log = JSON.parse(localStorage.getItem("sl_clicks") || "[]");
      log.push({ t: new Date().toISOString(), page: page, cta: a.getAttribute("data-cta"), src: src });
      localStorage.setItem("sl_clicks", JSON.stringify(log.slice(-500)));
    } catch (e) {}
    // Set the final href at click-time
    a.href = smartlinkURL(src, "quiz_funnel", page + "__" + (a.getAttribute("data-cta") || "cta"));
  });
});

/* QuizPop cookie consent banner (AdSense readiness).
   Simple, non-blocking: informs visitors about cookies for analytics and
   future advertising, links to /privacy/, remembers choice in localStorage. */
(function () {
  try {
    if (localStorage.getItem("qp_cookie_consent")) return;
    var bar = document.createElement("div");
    bar.id = "qp-cookie-bar";
    bar.setAttribute("role", "dialog");
    bar.setAttribute("aria-label", "Cookie notice");
    bar.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:9999;background:#1e1b2e;color:#fff;padding:12px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:center;font-size:14px;box-shadow:0 -2px 12px rgba(0,0,0,.25)";
    bar.innerHTML = '<span>We use cookies for analytics and, in the future, personalized ads. See our <a href="/privacy/" style="color:#ffd166">Privacy Policy</a>.</span>';
    var btn = document.createElement("button");
    btn.textContent = "Got it";
    btn.style.cssText = "background:#ff5d8f;border:0;color:#fff;font-weight:700;padding:8px 18px;border-radius:999px;cursor:pointer";
    btn.onclick = function () {
      try { localStorage.setItem("qp_cookie_consent", "1"); } catch (e) {}
      bar.remove();
    };
    bar.appendChild(btn);
    document.addEventListener("DOMContentLoaded", function () { document.body.appendChild(bar); });
  } catch (e) {}
})();
