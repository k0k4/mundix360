/** @type {import('next').NextConfig} */
const API_BASE = process.env.MUNDIX_API_BASE || "http://127.0.0.1:8099";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_BASE}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
