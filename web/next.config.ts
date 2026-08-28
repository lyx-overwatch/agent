import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8001";

const nextConfig: NextConfig = {
  // 把前端 `/py/api/*` 反代到 Heyu Agent 后端（默认 http://localhost:8001），
  // 保留 `/py/api` 前缀：`/py/api/conversations` → `${BACKEND_URL}/py/api/conversations`。
  async rewrites() {
    return [
      {
        source: "/py/api/:path*",
        destination: `${BACKEND_URL}/py/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
