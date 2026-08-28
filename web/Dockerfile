# ============================================================================
# Heyu Agent 前端镜像（Next.js 16 standalone）
# ============================================================================
# 多阶段构建：deps（装依赖）→ builder（build）→ runner（next start）。
# BACKEND_URL 在构建期 baked 进 next.config.ts 的 rewrites（/py/api/* 反代目标）。
# 默认指向 compose 内网服务名 backend:8001。
#
# 构建:
#   docker build --build-arg BACKEND_URL=http://backend:8001 -t heyu-frontend .
# ============================================================================

# ── 依赖层 ────────────────────────────────────────────────────────────────
FROM node:20-alpine AS deps
RUN npm install -g pnpm@9
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ── 构建层 ────────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
RUN npm install -g pnpm@9
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG BACKEND_URL=http://backend:8001
ENV BACKEND_URL=$BACKEND_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# ── 运行层 ────────────────────────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
# standalone 产物不含 public 与 .next/static，需手动拷贝
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
