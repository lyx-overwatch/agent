#!/usr/bin/env bash
# Heyu Agent 前端本地开发一键启动。
#
# 依赖后端已就绪（默认 http://localhost:8001，见 .env 的 BACKEND_URL，
# /py/api/* 通过 next.config.ts 的 rewrites 反代到后端）。后端请先跑
# `../backend/dev-up.sh`（或 `make dev`）。
#
# 用法:
#   cd web
#   ./dev-up.sh
set -euo pipefail

WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WEB_DIR"

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

# ── 1. 运行环境：Node + 包管理器（优先 pnpm，其次 npm）───────────────
info "1/3 检查运行环境"
command -v node >/dev/null 2>&1 || die "未找到 node，请先安装（如 brew install node / fnm）"
if command -v pnpm >/dev/null 2>&1; then
    PM="pnpm"
elif command -v npm >/dev/null 2>&1; then
    PM="npm"
else
    die "未找到 pnpm 或 npm，请先安装: brew install pnpm"
fi
skip "Node $(node -v) + $PM"

# ── 2. 依赖安装（node_modules 缺失时）───────────────────────────────
info "2/3 安装依赖"
if [ -d node_modules ]; then
    skip "node_modules 已存在"
else
    info "安装依赖 ($PM install)"
    "$PM" install
fi

# ── 3. 后端就绪检查（前端 /py/api/* 反代目标）───────────────────────
info "3/3 启动前端 (http://localhost:3000)"
if ! port_open 8001; then
    warn "后端 8001 未监听，/py/api/* 反代会失败；请先启动后端: ../backend/dev-up.sh"
fi
exec "$PM" dev
