# SkillHub 外部依赖与基础设施清单

> 本文档供 Java 后端同事了解 SkillHub 需要哪些基础设施支持，以便规划测试环境部署。
> 部署环境：华为云 CCE（Kubernetes 容器化）。

---

## 一、总览

| 序号 | 依赖 | 用途 | 是否必需 | 当前状态 |
|---|---|---|---|---|
| 1 | PostgreSQL | 业务数据 + Agent 对话状态持久化 | ✅ 必需 | 开发在用，测试环境待建库 |
| 2 | Redis | 登录态校验（验证 Java 端写入的 session） | ✅ 必需 | 开发在用，测试环境待建实例 |
| 3 | LLM API 代理 | 大模型推理接口 | ✅ 必需 | 已有，走腾讯 MAS 代理 |
| 4 | K8s Sandbox 运行环境 | Agent 代码执行沙箱（安全隔离） | ✅ 必需 | **Provisioner 方案（K8s Pod）** |
| 5 | 文件存储（对象存储） | Agent 生成的文件 / 用户上传文件 | ✅ 必需 | **OBS（S3 兼容，本地 MinIO 开发）** |
| 6 | 日志采集 | 应用日志集中存储 + 检索 | ✅ 必需 | **待确认方案** |
| 7 | Java 主系统（Auth） | 用户认证 + JWT 签发 | ✅ 必需 | 已有 |
| 8 | SkillHub Provisioner | K8s Sandbox Pod 生命周期管理 | ✅ 必需 | **已有代码，待部署** |

---

## 二、各依赖详细说明

### 1. PostgreSQL

**用途**：SkillHub 的全部持久化数据，包括用户表、对话记录、消息历史、LangGraph Agent 对话状态（checkpoint）。

**连接方式**：`postgresql+asyncpg://user:password@host:5432/dbname`（异步驱动 asyncpg）

**数据库表**（5 张，由 Alembic 自动建表）：

| 表名 | 说明 | 关键字段 |
|---|---|---|
| `users` | 用户表（首次登录自动注册） | `id` (PK, = Java 的 login_user_key), `username`, `email`, `is_active` |
| `user_skills` | 用户启用的技能 | `user_id` (FK), `skill_name`, `enabled` |
| `runs` | 对话会话元数据 | `id` (= conversation_id, UUID), `user_id` (FK), `thread_id`, `title`, `total_tokens`, `status` |
| `messages` | 对话消息 + 工具调用记录 | `conversation_id` (FK), `role`, `content`, `event_type`, `tool_name/input/output` |
| `alembic_version` | 数据库迁移版本 | （Alembic 自动管理） |

**额外用途 — LangGraph Checkpointer**：
Agent 对话状态（对话历史、工具调用堆栈等）通过 LangGraph 的 PostgreSQL checkpointer 写入同一数据库的 `checkpoint` 相关表。这确保服务重启后对话可以无缝恢复。

**需要 Java 后端提供的信息**：

| 问题 | 说明 |
|---|---|
| 测试环境 PostgreSQL 地址/端口 | 是华为云 RDS 还是自建？ |
| 数据库名 | SkillHub 独立用一个 database 即可 |
| 账号/密码 | 给 SkillHub 建一个专用账号 |
| 网络可达性 | SkillHub 容器要能连通数据库端口 |
| 备份策略 | 已有的话不必重复做 |

---

### 2. Redis

**用途**：验证用户登录态。Java 主系统登录后会在 Redis 写入 `login_tokens:{userId}` key，SkillHub 每次请求都校验这个 key 是否存在，确保登录态有效。

**连接方式**：`redis://host:6379`（通过 `redis-py` 异步客户端）

**使用方式**：
```python
# 每次 API 请求都执行
exists = await redis_client.exists(f"login_tokens:{user_id}")
if not exists:
    raise HTTPException(401, "Redis 无登录态，请先在主系统登录")
```

**Key 格式**：`login_tokens:{user_id}`（与 Java 端保持一致）

**注意**：SkillHub 只做 `exists` 校验，不写入 Redis。Redis key 由 Java 系统管理（写入 + 过期/删除）。

**需要 Java 后端提供的信息**：

| 问题 | 说明 |
|---|---|
| 测试环境 Redis 地址/端口 | 是华为云 DCS 还是自建？ |
| 密码 | 如果有 |
| 网络可达性 | SkillHub 容器要能连通 Redis 端口 |
| Key 格式确认 | 是否为 `login_tokens:{userId}`？ |

---

### 3. LLM API 代理

**用途**：大模型推理。SkillHub 目前配置了 6 个模型，全部通过腾讯 MAS 代理访问。

**API 端点**：`https://tokenhub.tencentmaas.com/plan/v3`

**使用中的模型**：

| 模型名 | model ID | 用途 |
|---|---|---|
| DeepSeek-V4-Flash | `deepseek-v4-flash` | 快速日常对话 |
| DeepSeek-V4-Pro | `deepseek-v4-pro-202606` | 复杂任务（默认） |
| Kimi-K27 | `kimi-k2.7-code` | 代码任务 |
| Hy3-Preview | `hy3-preview` | 备用 |
| GLM-5.2 | `glm-5.2` | 备用 |
| Qwen3.5-Flash | `qwen3.5-flash` | 备用 |
| Minimax-M3 | `minimax-m3` | 备用 |

**认证**：通过 API Key（环境变量 `VOLCENGINE_API_KEY`）。注意虽然变量名叫 `VOLCENGINE`，实际指向的是腾讯 MAS 代理。

**需要确认**：
- API Key 已有，测试环境沿用即可
- SkillHub 容器需要能出网访问 `tokenhub.tencentmaas.com`

---

### 4. K8s Sandbox 运行环境

**用途**：Agent 执行代码（bash、文件操作等）时，在独立的 K8s Pod 中进行，实现安全隔离。每个对话线程启动一个沙箱 Pod。

**方案**：通过 SkillHub Provisioner（独立的辅助服务）动态创建/销毁 K8s Pod。

**机制**：

```
SkillHub 后端 → POST /api/sandboxes → Provisioner → K8s API → 创建 Sandbox Pod (NodePort)
                                                              → 创建 Service (NodePort)
              ← { sandbox_url: "http://{node_ip}:{node_port}" }
              → 直接通过 sandbox_url 访问 Sandbox Pod HTTP API
```

**架构图**：

```
┌─────────────────────────────────────────────────────────┐
│                    CCE 集群                               │
│  ┌──────────────┐  HTTP   ┌────────────┐  K8s API       │
│  │  SkillHub     │ ─────▸ │ Provisioner │ ────────────┐  │
│  │  (主后端)     │        │   :8002     │              │  │
│  │  :8001        │        └────────────┘              │  │
│  └──────────────┘                              ┌──────▼──────────┐
│                                                 │  Sandbox Pod    │
│                                                 │  (按需创建)     │
│                                                 └─────────────────┘
```

**组件说明**：

| 组件 | 说明 |
|---|---|
| **SkillHub 主后端** | FastAPI 应用，处理对话请求。通过 `AioSandboxProvider` + `RemoteSandboxBackend` 与 provisioner 交互。 |
| **Provisioner** | 独立的 FastAPI 服务（端口 8002），提供 REST API 管理 K8s Sandbox Pod 生命周期（create / destroy / list / health）。需要 K8s RBAC 权限。 |
| **Sandbox Pod** | 按对话线程创建的隔离 Pod，运行沙箱容器镜像，提供代码执行环境。对话结束即销毁。 |

**Provisioner 需要的能力**：
- 在指定 namespace 内创建/删除 Pod 和 Service（NodePort 类型）
- Pod 重启策略为 `Never`（沙箱是一次性的，退出后 K8s 自动清理）
- 沙箱 Pod 通过 PVC 挂载 skills（只读）和 user-data（读写）目录
- 在 CCE 中使用 `load_incluster_config()` 自动获取 K8s 凭证

**为什么 Provisioner 是独立服务？**
- 权限隔离：Provisioner 需要 K8s API 权限（Pod/Service CRUD），主后端不需要
- 职责单一：轻量级 K8s API 代理，独立扩缩容
- 安全边界：即使主后端被攻破，攻击者无法直接操作 K8s 资源

**沙箱镜像**：

| 项目 | 值 |
|---|---|
| 镜像地址 | `swr.cn-south-1.myhuaweicloud.com/fintech-aigc/docker-sandbox:20260810V1.0` |
| 镜像仓库 | 华为云 SWR |
| 构建脚本 | `backend/SandBox.Dockerfile` |

**部署方式 — 两个 Docker 镜像**：

| 镜像 | 端口 | 说明 |
|---|---|---|
| `skillhub-backend` | 8001 | 主后端（FastAPI + Agent） |
| `skillhub-provisioner` | 8002 | Provisioner 辅助服务（K8s 代理） |

**节点池规划**：

集群沿用现有 `fintech-cce-dev`，**不新建集群、也不新建节点池**。集群的 Gatekeeper 策略（`[node]`）禁止普通用户修改 Node，打自定义标签会被拒，故改用**内置标签 `kubernetes.io/hostname` 按节点名固定**：

| 对象 | 用途 | 说明 |
|---|---|---|
| provisioner 所在节点（按节点名固定） | 沙箱 Pod + 预热 Deployment | 用 `kubernetes.io/hostname=<节点名>` 固定，无需打标签 |
| 其余节点（现有） | backend / provisioner / 前端 / 迁移 job | 不变 |

- 固定方式：provisioner 环境变量 `SANDBOX_NODE_LABEL_KEY=kubernetes.io/hostname`、`SANDBOX_NODE_LABEL_VALUE=<节点名>`
- 沙箱 Pod 通过 nodeAffinity 只调度到该节点；配合 `deploy/sandbox-image-warmer.yaml` 预热镜像，避免每次冷拉 1~2GB
- CCE 节点带 `node.cce.io/NodePodKey` 的 `NoSchedule` taint，沙箱 Pod 与 warmer 已加对应 toleration
- 详见 `docs/SkillHub-Sandbox沙箱实现原理.md` 6.6 节

**需要 Java 后端提供的信息**：

| 问题 | 说明 |
|---|---|
| K8s namespace | Provisioner 在哪个 namespace 创建 Sandbox Pod？和 SkillHub 后端同一 namespace 还是独立？ |
| RBAC 权限 | Provisioner 的 ServiceAccount 是否已有创建 Pod/Service 的权限？ |
| PVC 名称 | 测试环境的 skills PVC 和 user-data PVC 名称是什么？ |
| 网络策略 | Sandbox Pod 需要出网访问 PyPI / apt 等下载依赖吗？ |

---

### 5. 文件存储（OBS）

**目标方案**：Agent 生成文件后 → 上传到 OBS → 返回预签名 URL 给前端直接下载。

**架构设计 — S3 兼容抽象层**：

```
Agent 写文件到 Sandbox Pod (PV)
         │
         ▼ (Agent 完成后)
  SkillHub upload 到 OBS/MinIO
         │
         ▼
  后端返回 预签名 URL → 前端直接下载
```

**存储后端支持**：

| 后端 | 类型 | 用途 | 配置 |
|---|---|---|---|
| `local` | 本地磁盘 | 开发环境（无需外部依赖） | `STORAGE_BACKEND=local` |
| `s3` | S3 兼容（MinIO / OBS） | 测试/生产环境 | `STORAGE_BACKEND=s3` + S3 配置 |

**关键设计点**：
- OBS 兼容 S3 协议，MinIO 也兼容 S3 协议 → 代码中使用 `boto3` (S3 SDK)，通过 endpoint 区分 OBS / MinIO
- 本地开发：启动 MinIO 容器即可调试，无需连 OBS
- 线上切换：只改环境变量（`S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET`），代码零改动
- 文件下载：S3 后端返回预签名 URL（302 重定向），前端直接从 OBS/MinIO 下载，不经过 SkillHub 进程（节省带宽）
- 用户上传文件：创建对话时上传的文件也写入对象存储

**⚠️ OBS 上传坑（必读，已踩过并修复，不要改回去）**：

华为 OBS 的 S3 兼容不完整，`put_object` 会报：

> `An error occurred (XAmzContentSHA256Mismatch) when calling the PutObject operation: The provided 'x-amz-content-sha256' header does not match what was computed.`

- **根因**：OBS 的 SigV4 校验**只接受 `UNSIGNED-PAYLOAD` 和 `STREAMING-AWS4-HMAC-SHA256-PAYLOAD` 两种 payload 模式**。boto3 默认把真实 SHA256 hex 写进 `x-amz-content-sha256` 头（signed payload），OBS 不认 → 报 mismatch。这与「流式 body / bytes / `upload_file`」都无关，换写法没用。
- **解法**：在 boto3 client 配置里关掉 payload 签名 + 关掉 boto3 ≥1.36 自动加的 CRC32 checksum：

```python
from botocore.config import Config
Config(
    signature_version='s3v4',
    request_checksum_calculation="WHEN_REQUIRED",   # boto3 >= 1.36 才有
    response_checksum_validation="WHEN_REQUIRED",
    s3={
        "addressing_style": "virtual",              # OBS 用 virtual
        "payload_signing_enabled": False,           # 关键：发 UNSIGNED-PAYLOAD
    },
)
```

  当前实现见 `backend/app/core/storage.py` 的 `S3StorageBackend._build_boto_config()`。
- **addressing_style**：OBS 用 `virtual`（默认，无需改）；`head_bucket` / `list_objects` 等**无 body** 的请求不受此坑影响——所以「`/storage/health` 连接测试通过、但上传失败」是**正常现象**，不是网络/凭证问题。
- **上传实现**：`_upload_blocking()` 读 `local_path.read_bytes()` 后 `put_object(Body=data)`，外层有线程池 + 3 次重试。
- **快速验证**：部署后可直接用诊断接口（不走 agent）验证，见 `POST /py/api/storage/upload` / `GET /py/api/storage/health` / `GET /py/api/storage/url` / `GET /py/api/storage/list` / `DELETE /py/api/storage/object`。

  `GET /py/api/storage/url?key=<对象key>&download=true` 只生成下载 URL、不实际上传——先用 `upload` 传一个测试文件拿到 key，再用它验证 OBS 代理下载链路（V2 预签名 URL 是否以 `S3_PROXY_URL` 开头、浏览器能否直接下载）。

**需要 Java 后端提供的信息**：

| 问题 | 说明 |
|---|---|
| 用华为云 OBS 还是其他对象存储？ | 决定了 endpoint 配置 |
| AK/SK 从哪里拿？ | 给 SkillHub 建一个专用的 IAM 账号 |
| Bucket 名称 / 目录规范 | 测试环境用什么 bucket？文件目录结构？ |
| 预签名 URL 有效期 | 建议多久？默认 1 小时 |
| CDN 加速 | OBS 是否有 CDN 加速域名？有的话预签名 URL 走 CDN |

---

### 6. 日志采集

**当前做法**：日志同时输出到 `stdout`（彩色人类可读）和本地文件 `backend/logs/app.log`（JSON 格式）。

**测试环境的做法**：
- **应用侧**：关闭文件输出，只打 JSON 格式到 stdout
- **基础设施侧**：容器运行时采集 stdout → 日志系统 → 检索

**应用侧改造很小**（加一个 `ENVIRONMENT=staging` 环境变量即可切换），关键在基础设施侧。

**需要确认**：

| 问题 | 说明 |
|---|---|
| 日志采集方案是什么？ | 华为云 LTS？自建 ELK / Loki？还是直接看容器日志？ |
| 日志保留策略 | 保留多久？有没有合规要求？ |
| 日志格式要求 | 有没有统一的日志格式规范？ |

---

### 7. Java 主系统（Auth）

**已有，无需新建**。SkillHub 的认证流程：

```
用户 → Java 主系统登录 → Java 签发 JWT (HMAC512/HS512) + 写 Redis login_tokens
                              │
                              ▼
                         浏览器带 JWT 调 SkillHub API
                              │
                              ▼
                    SkillHub 验证 JWT 签名 + 查 Redis 登录态
                              │
                              ▼
                         返回结果
```

**JWT 参数**（双方保持一致）：

| 参数 | 值 |
|---|---|
| 算法 | HS512 |
| 签名密钥 | `SECRET_KEY`（环境变量，必须与 Java 一致） |
| 用户标识 claim | `login_user_key` |
| Token 传递方式 | `Authorization: Bearer <token>` Header |

---

## 三、环境变量汇总

SkillHub 通过 `.env` 文件配置以下变量。测试环境需要在容器启动时注入。

```bash
# ── 必需 ──────────────────────────────────────────────
SECRET_KEY=<与 Java 端相同的 HMAC512 密钥>
ALGORITHM=HS512
LOGIN_USER_KEY=login_user_key

# ── 数据库 ────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/skillhub

# ── Redis ─────────────────────────────────────────────
REDIS_URL=redis://host:6379

# ── LLM ───────────────────────────────────────────────
VOLCENGINE_API_KEY=<腾讯 MAS API Key>
ANTHROPIC_BASE_URL=（可选，如需 Claude 直连）
ANTHROPIC_API_KEY=（可选）
MODEL_ID=deepseek-v4-pro  # 默认模型

# ── 其他 API Key ──────────────────────────────────────
JINA_API_KEY=（可选，Jina AI）
QCC_API_KEY=（可选，企查查 MCP）
ZHIPU_API_KEY=（可选，智谱 AI）

# ── 部署相关 ──────────────────────────────────────────
ENVIRONMENT=staging       # 环境标识
SKILLHUB_CONFIG_PATH=/path/to/config.yaml  # 如 config.yaml 不在默认位置

# ── 文件存储 ──────────────────────────────────────────
STORAGE_BACKEND=s3                          # local | s3
S3_ENDPOINT=https://obs.cn-south-1.myhuaweicloud.com
S3_ACCESS_KEY=<OBS AK>
S3_SECRET_KEY=<OBS SK>
S3_BUCKET=skillhub-files
S3_REGION=cn-south-1
S3_ADDRESSING_STYLE=virtual                 # OBS 用 virtual（默认），MinIO 用 path
S3_PROXY_URL=https://agc-study.oa.cmbchina.biz/obs   # 下载反向代理前缀，留空则用 OBS 直连预签名地址
DOWNLOAD_URL_EXPIRES=3600                   # 预签名 URL 有效期（秒）

# ── Provisioner（仅 SkillHub 主后端需要）──────────────
# PROVISIONER_URL=http://provisioner:8002    # CCE 中通过 Service DNS
```

**Provisioner 独立环境变量**（provisioner 容器专用）：

```bash
# ── K8s 配置 ──────────────────────────────────────────
K8S_NAMESPACE=skillhub
SANDBOX_IMAGE=swr.cn-south-1.myhuaweicloud.com/fintech-aigc/docker-sandbox:20260810V1.0
SKILLS_PVC_NAME=<PVC 名称，如 skillhub-skills>
USERDATA_PVC_NAME=<PVC 名称，如 skillhub-userdata>
NODE_HOST=localhost   # CCE 中不需要特殊设置
# KUBECONFIG_PATH 不设 → 自动使用 in-cluster config
```

---

## 四、容器运行要求

### SkillHub 主后端

| 要求 | 说明 |
|---|---|
| **基础镜像** | Python 3.12+ |
| **端口** | 8001（FastAPI uvicorn） |
| **K8s 权限** | 无（不需要访问 K8s API） |
| **PVC 挂载** | 用户会话数据（与 Sandbox Pod 共享的 user-data PVC） |
| **网络** | 出网 → Provisioner:8002、PostgreSQL、Redis、LLM API、OBS；入网 → nginx 反代过来的 HTTP 请求 |
| **资源** | 建议 2C4G 起步，实际取决于并发量 |

### Provisioner

| 要求 | 说明 |
|---|---|
| **基础镜像** | Python 3.12+ slim（`backend/provisioner/Dockerfile`） |
| **端口** | 8002 |
| **K8s 权限** | ServiceAccount 需要 Pod/Service CRUD 权限（namespace scoped） |
| **网络** | 入网 → SkillHub 主后端 HTTP 调用；出网 → K8s API Server |
| **资源** | 轻量，建议 0.5C512M |

---

## 五、需要 Java 后端同事帮忙确认的清单

### 高优先级（阻塞部署）

- [x] **K8s Sandbox**：方案已确定 — Provisioner + K8s Pod，不依赖 Docker socket。
- [x] **文件存储**：OBS (S3 兼容)，本地用 MinIO 开发。
- [ ] **PostgreSQL**：测试环境数据库地址、端口、库名、账号密码。需要 SkillHub 专用 database（不含表也行，Alembic 自动建表）。
- [ ] **Redis**：测试环境 Redis 地址、端口、密码。确认 `login_tokens:{userId}` key 格式。
- [ ] **OBS 凭证**：AK/SK、Bucket 名称、Endpoint。
- [ ] **PVC 配置**：skills 和 user-data 的 PVC 名称。
- [ ] **日志采集**：CCE 有没有接 LTS 或自建日志系统？

### 中优先级（部署前确认）

- [ ] **网络策略**：SkillHub 容器是否能访问 PostgreSQL / Redis / LLM API / OBS / Provisioner？
- [ ] **域名/反代**：参照《部署与前端集成方案》配 nginx，`/skillhub-api/*` → SkillHub:8001
- [ ] **K8s RBAC**：Provisioner 的 ServiceAccount 权限配置
- [ ] **沙箱镜像**：SWR 上的镜像能否正常拉取？是否需要镜像拉取凭证（imagePullSecret）？

---

## 六、关键技术依赖（Python 包）

核心依赖见 `backend/pyproject.toml`，以下是涉及外部服务的：

| 包 | 版本 | 用途 |
|---|---|---|
| `fastapi` + `uvicorn` | ≥0.115 | Web 框架 |
| `asyncpg` | ≥0.31 | PostgreSQL 异步驱动 |
| `sqlmodel` + `alembic` | ≥0.0.38 | ORM + 数据库迁移 |
| `redis` (redis-py) | ≥5.0 | Redis 异步客户端 |
| `httpx` | ≥0.28 | HTTP 客户端（调 Java Auth、调 Provisioner） |
| `pyjwt` | ≥2.9 | JWT 验证 |
| `langgraph` + `langgraph-checkpoint-postgres` | ≥0.2 | Agent 框架 + PostgreSQL 状态持久化 |
| `loguru` | ≥0.7 | 日志 |
| `agent-sdk` | workspace | SkillHub 自己的 Agent SDK |
| `boto3` | ≥1.35 | S3 兼容对象存储 SDK（OBS / MinIO） |
| `kubernetes` | ≥30 | K8s Python 客户端（仅 Provisioner） |
