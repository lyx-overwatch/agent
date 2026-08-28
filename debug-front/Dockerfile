# ============================================================================
# Heyu Agent 前端静态镜像（debug-agent.html）
# ============================================================================
# 单文件前端，所有依赖（marked / fontawesome）走 CDN，无构建步骤。
# nginx 直接 serve 静态文件。
#
# 构建（从 frontend/ 目录执行）:
#   docker build -t skillhub-frontend:latest .
#
# 推送到华为云 SWR:
#   docker tag skillhub-frontend:latest \
#     swr.cn-south-1.myhuaweicloud.com/<ns>/skillhub-frontend:<tag>
#   docker push swr.cn-south-1.myhuaweicloud.com/<ns>/skillhub-frontend:<tag>
#
# 部署到 CCE 后:
#   前端会自动通过域名判断环境:
#     localhost → Base URL = http://localhost:8001（本地后端）
#     线上      → Base URL = 同源地址（K8s Ingress 已把 /py/api/* 路由到后端）
#   也可在 UI「调试 → 连接 → Base URL」手动覆盖。
# ============================================================================

FROM docker.m.daocloud.io/library/nginx:1.27-alpine

# ── 国内镜像源（alpine apk） ────────────────────────────────────────────────
RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories

# ── 站点文件 ────────────────────────────────────────────────────────────────
# debug-agent.html 作为站点入口（用户访问 / 直接落到这个页面）
COPY debug-agent.html /usr/share/nginx/html/index.html

# nginx 配置：根路径直接返回 index.html，sub-path 找不到时也回退到它
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# ── 健康检查 ────────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O- http://127.0.0.1/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]