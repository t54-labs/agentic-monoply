import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // output: 'export', // Temporarily comment out or remove for development with rewrites
  async rewrites() {
    return [
      {
        source: '/api/:path*', // Matches /api/lobby/games, /api/game/... etc.
        destination: 'http://localhost:8000/api/:path*', // Proxies to your FastAPI backend
      },
    ]
  },
  // You can add other Next.js configurations here if needed
  // reactStrictMode: true, 
};

export default nextConfig;
