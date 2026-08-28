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

## 1G 内存低配部署（单用户玩票）

> 适用：RackNerd 最低配（**1G RAM / 20G 盘 / 1G swap**）。
> **只适合单用户自己玩**：多人同时用、或开启子代理，1G 内存会 OOM。
> CCE 生产版 backend 配的是 1Gi request / 4Gi limit，那是因为要扛多用户 + 子代理 + 常驻沙箱，
> 你的场景不需要按那个规格来。

### 预期表现

- 能跑通：登录、聊天、沙箱写文件。
- 会慢：LA 到国内模型每轮多几百 ms 延迟 + swap 换页，明显比本地慢。
- 偶发 OOM：一次处理很多大文件 / 长任务时，沙箱可能被系统 OOM 杀掉（聊天中断，重发即可，不会坏数据）。

### Step 0：加 swap（机器已自带 1G，建议再加 2G）

Debian 12 上执行：

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
# 1G 内存建议更积极地用 swap，减少 OOM 概率
echo 'vm.swappiness=80' | sudo tee /etc/sysctl.d/99-swappiness.conf && sudo sysctl vm.swappiness=80
```

`fallocate` 报错时改用 `sudo dd if=/dev/zero of=/swapfile bs=1M count=2048`。

### Step 1：config.yaml 关掉吃内存的功能

`backend/config.yaml` 里把下面 4 项从 `true` 改成 `false`（各段落里搜关键字即可）：

| 段落 | 键 | 改为 | 作用 |
|---|---|---|---|
| `subagents` | `enabled` | `false` | **最大头**：关掉子代理，避免一次对话套娃起多个沙箱 |
| `summarization` | `enabled` | `false` | 省掉摘要模型实例 + 每轮摘要 LLM 调用 |
| `title` | `enabled` | `false` | 省掉后台标题模型实例 |
| `memory` | `enabled` | `false` | 省掉长期记忆存储/注入 |

> ⚠️ `config.yaml` 是本地开发和生产**共用**的。改完这 4 项，你本地开发时这些功能也会一并关掉。
> 如果本地还想保留，部署前改、回来再改回 `true`（或改前备份一份）。

### Step 2：compose 内存上限 + PG 调小（已内置）

`docker-compose.yml` 已经加好了容器级 `mem_limit`（防止单个容器吃光整机内存），并调小了 postgres：

- `postgres`: `mem_limit 256m` + `shared_buffers=64MB / max_connections=20`
- `backend`: `mem_limit 768m`
- `frontend`: `mem_limit 256m`

**升级到 2G/4G 机器后，把这些 `mem_limit` 和 postgres 的 `command` 行删掉或调大**，别让人为限制拖慢性能。

### 已知风险：沙箱容器没有内存上限

沙箱容器是 backend 在运行时用 `docker run` 动态起的（`backend.py` 的 `LocalContainerBackend`），
**命令里没带 `--memory`**，不在 compose 的 `mem_limit` 范围内 —— 它是 1G 机器上 OOM 的主因。

想给它加上限：改 `backend/packages/harness/agent_sdk/community/aio_sandbox/backend.py` 里
`create_container` 的 `cmd.extend(["--rm", "-d", ...])` 那一行，追加 `--memory 512m --cpus 1`
（改完要重新构建 backend 镜像）。不想改代码就保持单次任务小一点。

### 磁盘提醒（20G 也紧）

20G 里的大头通常是 **Docker 镜像 + postgres checkpointer**，不只是用户文件：

```bash
docker system df    # 看镜像 / 卷 / 缓存各占多少
```

- 沙箱基础镜像是华为源，LA 拉不动 —— 见下方「沙箱镜像」一节，需本地重建推 Docker Hub。
- checkpointer 快照会随对话涨，确认 `backend.env` 里 `CHECKPOINT_CLEANUP_ENABLED=true` 开着。

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
