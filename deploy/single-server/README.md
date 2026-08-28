# Heyu Agent 单服务器部署（RackNerd VPS）

单台机器上的生产部署方案：Docker Compose 编排 `postgres` + `backend` + `frontend` 三个容器，
沙箱走 **DooD**（backend 容器挂 `/var/run/docker.sock` + docker CLI，直接管理宿主机上的沙箱容器）。

与 `deploy/`（CCE/K8s + provisioner）不同：这里**不需要** provisioner、K8s、Redis、MinIO。

## 架构

```
浏览器 ─:80─▶ frontend (Next.js) ──/py/api/* rewrite──▶ backend (FastAPI :8001)
                                                           │ docker.sock
                                                           ▼
                                            宿主机 daemon 起沙箱容器（DooD）
                                                           │
                     backend ──DATABASE_URL──▶ postgres (业务表 + checkpointer)
                     backend ──/agent-test──▶ 宿主机 ${AGENT_TEST_HOST_DIR}（文件落盘）
```

## 前置条件

- 已安装 Docker Engine（≥ 20.10，支持 `host-gateway`）与 Docker Compose v2（`docker compose`）。
- 沙箱镜像 `docker-sandbox` 已能在宿主机上被 daemon 拉取/构建（见下方「沙箱镜像」）。

## 快速开始

```bash
cd deploy/single-server

# 1. 生成并填写配置
cp .env.example .env
cp backend.env.example backend.env
#   编辑 .env：POSTGRES_PASSWORD、AGENT_TEST_HOST_DIR（宿主机绝对路径）
#   编辑 backend.env：SECRET_KEY、VOLCENGINE_API_KEY 等密钥

# 2. 确保沙箱工作区目录存在
mkdir -p "$AGENT_TEST_HOST_DIR"     # 即 .env 里填的绝对路径

# 3. 构建并启动
make up        # 等价 docker compose build && docker compose up -d

# 查看日志 / 状态
make logs
make ps
```

## 配置说明

### `.env`（Compose 级）
| 变量 | 说明 |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | 数据库账号（默认 `postgres` / `agent`） |
| `AGENT_TEST_HOST_DIR` | **宿主机绝对路径**，沙箱工作区根目录；backend 容器内挂到 `/agent-test`，同时是沙箱容器 bind-mount 的源 |
| `FRONTEND_PORT` | 前端对外端口（默认 `80`） |

### `backend.env`（backend 密钥）
`SECRET_KEY`（JWT 签名）、`VOLCENGINE_API_KEY`（模型）、`QCC_API_KEY` / `WEB_SEARCH_API_KEY` / `JINA_API_KEY`（可选工具）。

其余非密钥项（`DATABASE_URL`、`SKILLHUB_HOST_BASE_DIR`、`SKILLHUB_SANDBOX_HOST`、`ENVIRONMENT`、
`STORAGE_BACKEND`、`RATE_LIMIT_BACKEND`、`CORS_ORIGINS`）已写死在 `docker-compose.yml` 的
`environment` 段，无需在 `backend.env` 重复。

### 无需改 `backend/config.yaml`
现有 `backend/config.yaml` 已适配单机 DooD：`sandbox.provider: docker`、`provisioner_url: ''`
（走 `LocalContainerBackend`）、`checkpointer.type: postgres`、`workspace: ../agent-test`（容器内解析为 `/agent-test`）。
其中 `sandbox.pool.size: 3` 仅在 K8s provisioner 模式生效，此处惰性、无需处理。

## 数据库

- backend 容器启动时会自动 `alembic upgrade head`（写在 backend Dockerfile 的 CMD），
  空库会从根迁移一路建表（`users` / `runs` / `messages` / `user_skills`）。
- checkpointer 表由 langgraph-checkpoint-postgres 首次连接时自建，无需额外步骤。
- 手动迁移（如需脱离发布单独跑）：`make db-migrate`。

## 验证

```bash
# 健康检查（经前端同源反代）
curl http://<VPS_IP>/py/api/health          # 期望 {"status":"ok"}

# 前端页面
curl -I http://<VPS_IP>/                    # 期望 200

# 注册一个用户
curl -X POST http://<VPS_IP>/py/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"a@b.com","password":"...","username":"..."}'
```

触发一次需要沙箱的对话（如「用 python 算 1+1」），然后在宿主机：

```bash
docker ps | grep skillhub-sandbox           # 应看到新建的沙箱容器
```

agent 生成的文件会落到 `${AGENT_TEST_HOST_DIR}/users/<uid>/threads/<thread_id>/outputs/`，
前端「文件树」面板应能预览。

## 沙箱镜像

backend 的 `LocalContainerBackend` 会用 config.yaml 里的默认沙箱镜像
（`swr.cn-south-1.myhuaweicloud.com/fintech-aigc/docker-sandbox:...`，国内源）或你自行指定的镜像起沙箱容器。

RackNerd 是海外机器，**国内镜像源可能拉不动**。二选一：

1. 在宿主机上构建并打 tag 成默认镜像名（或改 `backend/config.yaml` → `sandbox.image`）；
2. 推送到 Docker Hub 等可达仓库，再让 config.yaml 的 `sandbox.image` 指向它。

> 沙箱镜像 Dockerfile 见 `backend/SandBox.Dockerfile`（基础镜像也是国内源，需在海外可拉的基础上重建）。

## 安全提示

- **`/var/run/docker.sock` 是特权挂载**：backend 容器因此具备宿主机 root 等效能力。
  这是 DooD 的固有权衡，仅建议在可信单机上使用；不要把它暴露到公网（backend 端口默认不对外）。
- `SECRET_KEY` 请用随机长串；生产请后续补 HTTPS（当前是裸 IP + HTTP）。
- 沙箱容器由 backend 直接管理，务必限制后端可访问性与 DB 密码强度。

## 常见问题

- **backend 起不来 / healthcheck 503**：多半是 `DATABASE_URL` 连不上 postgres，或 `backend.env` 缺 `SECRET_KEY`。
  看日志 `make logs`。
- **沙箱容器建了但 agent 连不上**：确认 Docker Engine ≥ 20.10（`host-gateway` 支持），
  以及 `.env` 的 `AGENT_TEST_HOST_DIR` 是**绝对路径**且存在。
- **沙箱镜像拉取失败**：见「沙箱镜像」一节，换成海外可达镜像。
- **SSE 一次性返回 / 流式不生效**：前端 `compress: false` 已关闭 gzip（next.config.ts），
  确认前端镜像是用最新 `next.config.ts`（含 `output: standalone` + `compress: false`）构建的。
