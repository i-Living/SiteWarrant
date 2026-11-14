import type { NextConfig } from "next";

const apiBase = process.env.SITEWARRANT_API ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    // The browser talks to this app, not to the API: the FastAPI service stays on the
    // internal network in a deployment, and a relative fetch needs no CORS.
    return [{ source: "/api/:path*", destination: `${apiBase}/:path*` }];
  },
};

export default nextConfig;
