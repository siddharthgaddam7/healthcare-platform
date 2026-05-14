/**
 * API base for all pages (load this script before inline scripts / script.js).
 *
 * Production (non-localhost):
 *   • Preferred: Vercel env CC_API_BASE_URL — `npm run build` injects it on deploy.
 *   • Or: set window.__CC_API_BASE__ in an inline script before this file.
 *   • Or: <meta name="cc-api-base" content="https://your-service.onrender.com"> in <head>.
 * Use HTTPS only. No trailing slash.
 *
 * Local dev: leave empty; http://127.0.0.1:10000 is used automatically.
 */
window.__CC_API_BASE__ = "";

(function metaOverride() {
    try {
        const meta = document.querySelector('meta[name="cc-api-base"]');
        const m = meta && meta.getAttribute("content") && meta.getAttribute("content").trim();
        if (m) window.__CC_API_BASE__ = m.replace(/\/$/, "");
    } catch (e) { /* ignore */ }
})();

(function () {
    const h = window.location.hostname;
    const isLocal = h === "localhost" || h === "127.0.0.1";

    window.getApiBase = function () {
        if (isLocal) return "http://127.0.0.1:10000";
        let u = String(window.__CC_API_BASE__ || "").trim().replace(/\/$/, "");
        if (!u) {
            console.warn(
                "Set CC_API_BASE_URL on Vercel (build inject), or window.__CC_API_BASE__, or <meta name=\"cc-api-base\">."
            );
            return "";
        }
        if (/^http:\/\//i.test(u)) {
            console.warn("API base should use https:// on production (mixed content may break on Vercel).");
        }
        return u;
    };
})();
