/**
 * The web app is the single entry point. The browser only ever talks to this origin; requests to /api/* are
 * proxied server-side to the backend API (MODELER_API_BASE, default localhost:8000). So there is one URL for
 * the user, no CORS, and the backend location is never exposed to the browser.
 * @type {import('next').NextConfig}
 */
const nextConfig = {
  // A client delivery (many sheets, PDFs and Word files at once, read on arrival) is larger and slower than Next's proxy
  // defaults allow: past 10 MB the body was cut short and after 30 s the API was given up on, both answered with a bare
  // HTTP 500. Raised to what one "Add data" upload needs; MODELER_UPLOAD_MAX_MB and MODELER_PROXY_TIMEOUT_S override.
  experimental: {
    proxyClientMaxBodySize: `${Number(process.env.MODELER_UPLOAD_MAX_MB || 500)}mb`,
    proxyTimeout: Number(process.env.MODELER_PROXY_TIMEOUT_S || 600) * 1000,
  },
  async rewrites() {
    const api = (process.env.MODELER_API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "");
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
