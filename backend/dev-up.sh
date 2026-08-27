#!/usr/bin/env bash
# SkillHub 本地开发一键启动。
#
# 按依赖顺序启动：Docker(colima) → PostgreSQL → 数据库就绪(建库+自动迁移)
# → Redis → MinIO → 后端。已就绪的服务会被跳过。
#
# 注意：数据库迁移会在启动时自动执行 `uv run alembic upgrade head`
# （落后则升级，已最新则跳过）。生产环境请勿依赖此脚本，迁移应由发布流程显式执行。
#
# 用法:
#   cd backend
#   ./dev-up.sh          # 或 make up
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BACKEND_DIR"

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'
info() { printf "${GREEN}==>${NC} %s\n" "$1"; }
skip() { printf "    ${YELLOW}(已就绪，跳过)${NC} %s\n" "$1"; }
warn() { printf "    ${YELLOW}⚠${NC} %s\n" "$1"; }
die()  { printf "${RED}✗${NC} %s\n" "$1" >&2; exit 1; }

# 端口是否已有进程监听
port_open() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# 探测本机可用的代理（HTTP 或 SOCKS5），命中则设置对应环境变量。
# colima 首次启动要下载 VM 磁盘镜像（走 GitHub），国内直连慢，需代理加速。
# 返回 0 表示找到。
detect_proxy() {
    local port code
    # 常见代理端口：v2rayN(10808/10809)、ClashX(7890/7891)、通用(1087/1080/8118/8888)
    for port in 10808 10809 7890 7891 1087 1080 8118 8888; do
        # 优先 HTTP：colima 的 Go 客户端对 HTTPS_PROXY=http:// 走 CONNECT 隧道最稳、最快。
        # 实测同一节点 HTTP 3s vs SOCKS5 10s，且 SOCKS5 更易触发 colima 重定向超时。
        code=$(curl -x "http://127.0.0.1:$port" -o /dev/null -s -w '%{http_code}' --connect-timeout 3 --max-time 12 https://github.com 2>/dev/null) || code="000"
        case "$code" in
            200|301|302|307|308)
                export HTTP_PROXY="http://127.0.0.1:$port" HTTPS_PROXY="http://127.0.0.1:$port"
                export http_proxy="http://127.0.0.1:$port" https_proxy="http://127.0.0.1:$port"
                unset ALL_PROXY all_proxy   # 避免 shell 里残留的 ALL_PROXY 覆盖 HTTPS_PROXY
                return 0 ;;
        esac
        # 兜底 SOCKS5（同时设 HTTP(S)_PROXY 和 ALL_PROXY，Go 客户端也支持 HTTPS_PROXY=socks5://）
        code=$(curl -x "socks5://127.0.0.1:$port" -o /dev/null -s -w '%{http_code}' --connect-timeout 3 --max-time 8 https://github.com 2>/dev/null) || code="000"
        case "$code" in
            200|301|302|307|308)
                export HTTP_PROXY="socks5://127.0.0.1:$port" HTTPS_PROXY="socks5://127.0.0.1:$port"
                export http_proxy="socks5://127.0.0.1:$port" https_proxy="socks5://127.0.0.1:$port"
                export ALL_PROXY="socks5://127.0.0.1:$port" all_proxy="socks5://127.0.0.1:$port"
                return 0 ;;
        esac
    done
    return 1
}

# ── 1. Docker (colima) — sandbox provider=docker 依赖 ──────────────────
info "1/6 启动 Docker (colima)"
if docker info >/dev/null 2>&1; then
    skip "Docker daemon"
else
    command -v colima >/dev/null 2>&1 || die "未找到 colima，请先安装: brew install colima"
    # 探测本机代理：colima 首次下载 VM 镜像走 GitHub，直连慢
    if detect_proxy; then
        info "已探测到代理: ${HTTP_PROXY:-${ALL_PROXY}}"
    else
        warn "未探测到本机代理，colima 首次下载镜像可能很慢（国内直连 GitHub）"
    fi
    colima start
fi

# ── 2. PostgreSQL — 数据库 + checkpointer ─────────────────────────────
info "2/6 启动 PostgreSQL"
PG_SVC="$(brew services list 2>/dev/null | awk '$1 ~ /^postgres/ {print $1; exit}')"
if port_open 5432; then
    skip "PostgreSQL (5432)"
elif [ -n "$PG_SVC" ]; then
    brew services start "$PG_SVC"
else
    die "未找到 PostgreSQL 的 brew service，请手动启动"
fi

# 定位 psql/createdb（postgresql@16 是 keg-only，不在默认 PATH）
PG_BIN="$(brew --prefix "$PG_SVC" 2>/dev/null)/bin"
PSQL="$PG_BIN/psql"
CREATEDB="$PG_BIN/createdb"

# ── 3. 数据库就绪：建库（幂等） + 迁移检查（只提示不自动跑）──────────
info "3/6 数据库就绪检查"

# 从 .env 提取库名（假设 DATABASE_URL 值无引号、无 query string）
db_name="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2- | sed 's|.*/||; s|\?.*||')"
db_name="${db_name:-agent}"

if "$PSQL" -tAc "SELECT 1 FROM pg_database WHERE datname='$db_name'" postgres 2>/dev/null | grep -q 1; then
    skip "数据库 $db_name 已存在"
else
    "$CREATEDB" "$db_name" && info "已创建数据库 $db_name"
fi

# 迁移检查：落后于 head 时自动执行 upgrade（已最新则跳过）
# alembic.ini 被 .gitignore 忽略，缺失时从模板自动生成
if [ ! -f alembic.ini ] && [ -f alembic.ini.example ]; then
    cp alembic.ini.example alembic.ini
    info "已从 alembic.ini.example 生成 alembic.ini"
fi

if [ -f alembic.ini ]; then
    cur="$(uv run alembic current 2>/dev/null | grep -oE '[0-9a-f]{12,}' | tail -1)"
    head="$(uv run alembic heads 2>/dev/null | grep -oE '[0-9a-f]{12,}' | tail -1)"
    if [ -z "$cur" ] || [ "$cur" != "$head" ]; then
        info "数据库迁移落后（current=${cur:-无}, head=${head}），自动执行 upgrade"
        uv run alembic upgrade head
        info "数据库迁移已升级到 ${head}"
    else
        skip "数据库迁移已是最新 (${head})"
    fi
else
    warn "未找到 alembic.ini 和 alembic.ini.example，跳过迁移检查"
fi

# ── 4. Redis — IM channel ─────────────────────────────────────────────
info "4/6 启动 Redis"
if port_open 6379; then
    skip "Redis (6379)"
else
    brew services start redis
fi

# ── 5. MinIO — 文件存储 (S3, 默认 minioadmin/minioadmin，对应 .env) ──
info "5/6 启动 MinIO"
if port_open 9000; then
    skip "MinIO (9000)"
else
    brew services start minio
fi

# ── 6. 后端 ───────────────────────────────────────────────────────────
info "6/6 启动后端 (0.0.0.0:8001)"
exec make dev
