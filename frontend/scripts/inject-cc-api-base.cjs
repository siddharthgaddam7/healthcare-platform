/**
 * Vercel: set Environment Variable CC_API_BASE_URL to your Render HTTPS URL (no trailing slash).
 * This rewrites the assignment in api-base.js during deploy only (does not affect your Git remote).
 */
const fs = require("fs");
const path = require("path");

const envUrl = (process.env.CC_API_BASE_URL || process.env.RENDER_API_URL || "")
  .trim()
  .replace(/\/$/, "");

const target = path.join(__dirname, "..", "api-base.js");

if (!envUrl) {
  console.warn(
    "[inject-cc-api-base] CC_API_BASE_URL not set — set it in Vercel → Settings → Environment Variables, " +
      "or set window.__CC_API_BASE__ / <meta name=\"cc-api-base\"> manually."
  );
  process.exit(0);
}

if (!/^https:\/\//i.test(envUrl)) {
  console.error("[inject-cc-api-base] CC_API_BASE_URL must start with https:// (production).");
  process.exit(1);
}

let s = fs.readFileSync(target, "utf8");
const re = /window\.__CC_API_BASE__\s*=\s*[^;]+;/;
if (!re.test(s)) {
  console.error("[inject-cc-api-base] Could not find window.__CC_API_BASE__ assignment in api-base.js");
  process.exit(1);
}
s = s.replace(re, `window.__CC_API_BASE__ = ${JSON.stringify(envUrl)};`);
fs.writeFileSync(target, s);
console.log("[inject-cc-api-base] Injected API base URL (HTTPS, host not logged).");
