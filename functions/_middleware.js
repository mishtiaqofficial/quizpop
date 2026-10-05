// 301 redirect: quizpop.pages.dev -> popquizdaily.site (custom domain migration, 2026-10-05)
// Preserves full path + query string so no indexed URL is lost.
export async function onRequest(context) {
  const url = new URL(context.request.url);
  if (url.hostname === "quizpop.pages.dev") {
    url.hostname = "popquizdaily.site";
    return Response.redirect(url.toString(), 301);
  }
  return context.next();
}
