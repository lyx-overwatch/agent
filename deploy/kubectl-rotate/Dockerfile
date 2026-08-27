# ============================================================================
# kubectl 工具镜像 —— 供 sandbox-pool-rotate CronJob 执行 kubectl delete
# ============================================================================
# 背景：bitnami/kubectl 已从 Docker Hub 下架（Bitnami 2025-08 目录迁移），
# CCE 节点又拉不到公开 Docker Hub，所以自建「alpine + kubectl 二进制」极简镜像
# 推到内网 SWR，与其余 Deployment/Job 同源、走 default-secret 拉取。
#
# 用法：
#   cd deploy/kubectl-rotate
#   docker build -t swr.cn-south-1.myhuaweicloud.com/fintech-aigc/kubectl:1.32.3 \
#     --build-arg KUBECTL_VERSION=v1.32.3 .
#   docker login swr.cn-south-1.myhuaweicloud.com
#   docker push swr.cn-south-1.myhuaweicloud.com/fintech-aigc/kubectl:1.32.3
#
# 说明：CronJob 里用的是 command（对应 Docker 的 ENTRYPOINT），会整体覆盖本镜像
# 的 ENTRYPOINT/CMD，所以只要 kubectl 在 PATH 里即可，不依赖入口脚本。
# ============================================================================

# 基础镜像走 daocloud 国内镜像源（与 provisioner 一致）；本地能直连 Docker Hub
# 的话可改成 FROM alpine:3.20
FROM docker.m.daocloud.io/library/alpine:3.20

ARG KUBECTL_VERSION=v1.32.3

# 下载源走 dl.k8s.io。国内慢/不通时，把 url 换成阿里云镜像：
#   https://mirrors.aliyun.com/kubernetes/kubectl/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl
RUN set -eux; \
    apk add --no-cache ca-certificates; \
    arch="$(uname -m)"; \
    case "$arch" in \
      x86_64) arch=amd64 ;; \
      aarch64) arch=arm64 ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    url="https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl"; \
    wget -q -O /usr/local/bin/kubectl "$url"; \
    wget -q -O /tmp/kubectl.sha256 "$url.sha256"; \
    expected="$(awk '{print $1}' /tmp/kubectl.sha256)"; \
    actual="$(sha256sum /usr/local/bin/kubectl | awk '{print $1}')"; \
    [ "$expected" = "$actual" ] || { echo "checksum mismatch" >&2; exit 1; }; \
    chmod +x /usr/local/bin/kubectl; \
    rm -f /tmp/kubectl.sha256; \
    kubectl version --client

# ENTRYPOINT 只是给本地 docker run 调试方便；CronJob 的 command 会覆盖它。
ENTRYPOINT ["kubectl"]
CMD ["--help"]
