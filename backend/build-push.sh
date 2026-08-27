#!/usr/bin/env bash
# ====================================================================
# 打包并推送 skillhub-backend 后端镜像到华为云 SWR
#
# 用法: ./build-push.sh <版本号>
#   tag 自动用当天日期拼，如 20260821V1.0
#
# 示例:
#   ./build-push.sh 1.0        # -> skillhub-backend:20260821V1.0
# ====================================================================

set -euo pipefail

usage() {
  cat <<'EOF'
用法: ./build-push.sh <版本号>

  version   版本号，如 1.0（tag 自动拼成 当天日期V版本，如 20260821V1.0）

示例:
  ./build-push.sh 1.0
EOF
}

if [ "$#" -lt 1 ]; then
  usage >&2
  exit 1
fi

VERSION="$1"

# 切到脚本所在目录（backend/），保证 docker build 上下文正确
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REGISTRY="swr.cn-south-1.myhuaweicloud.com"
NAMESPACE="fintech-aigc"
IMAGE="${REGISTRY}/${NAMESPACE}/skillhub-backend"
TAG="$(date +%Y%m%d)V${VERSION}"

echo "==> 目标镜像: ${IMAGE}:${TAG}"
echo ""

echo "==> 构建 ${IMAGE}:${TAG}"
docker build -t "${IMAGE}:${TAG}" .

echo "==> 推送 ${IMAGE}:${TAG}"
docker push "${IMAGE}:${TAG}"

echo ""
echo "完成: ${IMAGE}:${TAG}"
