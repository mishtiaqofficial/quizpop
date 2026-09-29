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
