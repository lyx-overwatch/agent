import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8001";

const nextConfig: NextConfig = {
  // 关闭 Next 自带的 gzip 压缩。
  // 原因：`/py/api/chat/stream` 的 SSE 响应经 rewrites 反代时会被 Next 套上
  // `Content-Encoding: gzip`，而浏览器用 fetch + getReader 读 gzip 压缩的
  // text/event-stream 会整段缓冲、等流结束后一次性吐出（流式输出变成一次性返回）。
  // curl 能流式解压所以测不出来，浏览器不行 —— 因此必须关掉压缩让 SSE 明文逐帧下发。
  compress: false,
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
