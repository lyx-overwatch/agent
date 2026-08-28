# ============================================================================
# Heyu Agent 主后端 Docker 镜像
# ============================================================================
# 基于 uv workspace 构建，包含 FastAPI 应用（port 8001）+ agent-sdk。
#
# 构建（从 backend/ 目录执行）:
#   docker build -t skillhub-backend:latest .
#
# 推送到华为云 SWR:
#   docker tag skillhub-backend:latest swr.cn-south-1.myhuaweicloud.com/<ns>/skillhub-backend:<tag>
#   docker push swr.cn-south-1.myhuaweicloud.com/<ns>/skillhub-backend:<tag>
#
# 运行:
#   docker run --env-file .env -p 8001:8001 skillhub-backend:latest
# ============================================================================

FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm

# ── 系统依赖 + 镜像源（国内加速）────────────────────────────────────────────
RUN sed -i "s|deb.debian.org|mirrors.aliyun.com|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i "s|deb.debian.org|mirrors.aliyun.com|g" /etc/apt/sources.list 2>/dev/null || true

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── 安装 uv ──────────────────────────────────────────────────────────────────
# pip install uv（避免 ghcr.io 在国内网络不可达）
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

# ── 依赖层（利用 Docker 缓存：只有依赖元数据变化时才重新安装外部依赖）──────
# 1. 只复制 workspace 元数据（pyproject.toml + uv.lock），不复制 agent_sdk 源码
COPY pyproject.toml uv.lock ./
COPY packages/harness/pyproject.toml packages/harness/
COPY packages/harness/README.md packages/harness/

# 2. 安装外部依赖。--no-install-workspace 跳过本地 workspace member 的
#    editable 安装，因此本层不依赖 agent_sdk 源码——改 agent_sdk 代码不再使本层失效。
#    （--mount 需要 BuildKit；若在旧版 Docker 上构建失败，可删除该参数）
RUN --mount=type=cache,target=/root/.cache/uv,id=uv-cache \
    uv sync --frozen --no-dev --no-install-workspace

# ── 运行时代码层 ─────────────────────────────────────────────────────────────
# agent_sdk 是 workspace member，源码变更只影响这一层
COPY packages/harness/agent_sdk/ packages/harness/agent_sdk/
COPY app/ app/
COPY config.yaml run.py ./
COPY skills/ skills/
COPY alembic.ini ./
COPY migrations/ migrations/

# 安装 workspace members（root + agent-sdk）为 editable：外部依赖已就绪，
# 只需构建两个本地包的 editable wheel，速度很快
RUN --mount=type=cache,target=/root/.cache/uv,id=uv-cache \
    uv sync --frozen --no-dev

# 将 .venv 加入 PATH，使 uvicorn 可直接调用
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8001

# ── 启动 ─────────────────────────────────────────────────────────────────────
# 先跑数据库迁移（alembic upgrade head），成功后再启动 uvicorn。
# 迁移失败则容器退出、由 K8s 自动重启重试，等价于原 initContainer 的语义。
# 默认使用 config.yaml（可通过 SKILLHUB_CONFIG_PATH 环境变量覆盖）
CMD ["sh", "-c", "cd /app && python -m alembic -c /app/alembic.ini upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8001"]
