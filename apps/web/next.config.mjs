/**
 * The web app is the single entry point. The browser only ever talks to this origin; requests to /api/* are
 * proxied server-side to the backend API (MODELER_API_BASE, default localhost:8000). So there is one URL for
 * the user, no CORS, and the backend location is never exposed to the browser.
 * @type {import('next').NextConfig}
 */
const nextConfig = {
  async rewrites() {
    const api = (process.env.MODELER_API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "");
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
