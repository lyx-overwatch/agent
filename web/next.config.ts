import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8001";

const nextConfig: NextConfig = {
  // 把前端 `/api/*` 代理到 SkillHub 后端（本地 make dev，端口 8001），
  // 去掉 `/api` 前缀：`/api/conversations` → `http://localhost:8001/conversations`。
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
