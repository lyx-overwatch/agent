# Heyu Agent Provisioner 说明

> 本文档说明 Provisioner 的职责、工作原理、与主后端的交互方式，以及 Heyu Agent 特有的设计决策。

---

## 一、Provisioner 是什么

**一句话**：Provisioner 是 Heyu Agent 的一个**独立辅助服务**，负责在 K8s 集群中按需创建/销毁 Sandbox Pod。

**为什么需要它**：Heyu Agent 部署在华为云 CCE（Kubernetes）上，没有 Docker socket 可用。Agent 执行代码需要隔离环境——Provisioner 替主后端跟 K8s API Server 打交道，为每个对话线程创建独立的 Sandbox Pod。

**为什么是独立服务**：
- **权限隔离**：Provisioner 需要 K8s Pod/Service CRUD 权限，主后端不需要
- **安全边界**：即使主后端被攻破，攻击者无法直接操纵 K8s 资源
- **职责单一**：轻量级 K8s API 代理，独立扩缩容

---

## 二、Provisioner 做了什么（逐行解读）

### 2.1 启动流程

```
FastAPI lifespan 启动
  → 等待 kubeconfig（本地开发）或自动切换到 in-cluster config（CCE 内）
  → 初始化 K8s API 客户端（CoreV1Api）
  → 确保 namespace 存在（不存在则创建）
  → 服务就绪
```

### 2.2 K8s 认证方式

| 环境 | 认证方式 | 说明 |
|---|---|---|
| **本地开发** | `~/.kube/config` 挂载 | 容器内通过 `KUBECONFIG_PATH` 指定 |
| **CCE 测试/生产** | `load_incluster_config()` | Pod 内自动从 ServiceAccount 获取凭证 |

### 2.3 核心 API

| 端点 | 作用 | 调用方 |
|---|---|---|
| `GET /health` | 健康检查 | K8s readiness/liveness probe |
| `POST /api/sandboxes` | 创建 Sandbox Pod + NodePort Service | 主后端的 `RemoteSandboxBackend` |
| `DELETE /api/sandboxes/{id}` | 销毁 Sandbox Pod + Service | 主后端（对话结束 / idle timeout） |
| `GET /api/sandboxes/{id}` | 查询 Sandbox 状态 | 主后端（跨进程发现已有 sandbox） |
| `GET /api/sandboxes` | 列出所有 Sandbox | 运维/监控 |

### 2.4 `POST /api/sandboxes` 详细流程

```
主后端请求: {"sandbox_id": "abc12345", "thread_id": "user-xxx"}

1. 幂等检查: 如果 sandbox_id 已存在 → 直接返回现有信息
2. 创建 Pod:
   - 名称: sandbox-{sandbox_id}
   - 标签: app=skillhub-sandbox, sandbox-id={sandbox_id}
   - 镜像: swr.cn-south-1...sandbox:20260810V1.0
   - 端口: 8080 (HTTP)
   - 健康检查: GET /v1/sandbox
   - 重启策略: Never（一次性 Pod，退出后不复活）
   - 资源限制: 100m~1000m CPU, 256Mi~1Gi 内存
3. 创建 NodePort Service:
   - 名称: sandbox-{sandbox_id}-svc
   - 端口: 8080 → K8s 自动分配 NodePort (30000-32767)
   - 选择器: sandbox-id={sandbox_id}
4. 轮询等待 Service 分配 NodePort (最多 10 秒)
5. 返回: {"sandbox_id": "...", "sandbox_url": "http://{node_ip}:{nodePort}", "status": "Pending/Running"}
```

### 2.5 返回的 `sandbox_url`

```
主后端拿到 sandbox_url → 直接通过 {node_ip}:{NodePort} 访问 Sandbox Pod 的 HTTP API
```

后续 Agent 的所有文件操作（bash、read_file、write_file 等）都通过这个 URL 发送到 Sandbox Pod。

### 2.6 Volume 挂载策略

| Volume | 优先级 1 (PVC) | 优先级 2 (hostPath) | 优先级 3 (emptyDir) | Heyu Agent 实际需要? |
|---|---|---|---|---|
| `skills` | `SKILLS_PVC_NAME` | `SKILLS_HOST_PATH` | 空目录 | ❌ **不需要** — Heyu Agent 通过 `read_skill` 工具动态注入 |
| `user-data` | `USERDATA_PVC_NAME` | `THREADS_HOST_PATH` | 临时存储 | ✅ **必须** — workspace/outputs/uploads |

**关键设计决策 — 为什么不需要 skills volume**：

Heyu Agent 的 skill 注入流程与 DeerFlow 完全不同：

```
DeerFlow 方式:  skills 目录 → Docker volume mount → /mnt/skills（预挂载，只读）

Heyu Agent 方式:  read_skill 工具 → 从主后端磁盘读取 skill 文件
                → 通过 sandbox HTTP API (update_file) 写入 sandbox
                → /mnt/user-data/workspace/.skills/<name>/
```

因此 Sandbox Pod **不需要** skills volume mount。保留它只会多一个空目录。代码已用 `emptyDir` 兜底。

---

## 三、与主后端的交互链路

### 3.1 配置入口

主后端 `config.yaml` 中设置 `sandbox.provisioner_url`：

```yaml
# 本地开发（留空 → LocalContainerBackend）
sandbox:
  provider: docker
  provisioner_url: ""

# CCE 生产
sandbox:
  provider: docker
  provisioner_url: http://provisioner:8002
```

### 3.2 后端代码链路

```
config_loader.py
  → _aio_sandbox_kwargs() 读取 sandbox.provisioner_url
  → 传给 AioSandboxProvider(provisioner_url="http://provisioner:8002")
  → AioSandboxProvider._create_backend()
    → RemoteSandboxBackend(provisioner_url)  ← 关键分支
```

```
RemoteSandboxBackend （backend/packages/harness/agent_sdk/community/aio_sandbox/backend.py）
  .create()      → POST http://provisioner:8002/api/sandboxes
  .destroy()     → DELETE http://provisioner:8002/api/sandboxes/{id}
  .discover()    → GET http://provisioner:8002/api/sandboxes/{id}
  .is_alive()    → GET http://provisioner:8002/api/sandboxes/{id}
```

### 3.3 端到端流程

```
用户发消息
  → 主后端 ChatService 运行 Agent
  → Agent 需要 sandbox → AioSandboxProvider.acquire(thread_id)
    → RemoteSandboxBackend.create(thread_id, sandbox_id)
      → POST provisioner:8002/api/sandboxes
        → Provisioner 创建 K8s Pod + NodePort Service
        → 返回 sandbox_url
    → 返回 sandbox_id
  → Agent 工具调用（bash, read_file, write_file...）
    → 通过 sandbox_url 直接发 HTTP 到 Sandbox Pod
    → Sandbox Pod 处理命令，返回结果
  → 对话结束
  → AioSandboxProvider.release(sandbox_id) → 放入 warm pool
  → idle timeout 后 → destroy → DELETE provisioner:8002/api/sandboxes/{id}
    → Provisioner 删除 Pod + Service
```

---

## 四、Provisioner 的独立性

### 4.1 为什么有独立的 Dockerfile

Provisioner 是一个**独立部署的服务**，需要：

| 项目 | Provisioner | Heyu Agent 主后端 |
|---|---|---|
| **Python 依赖** | fastapi + uvicorn + kubernetes | 大量 AI/Agent 依赖 |
| **镜像大小** | ~200MB（slim） | ~2GB+ |
| **K8s 权限** | 需要 Pod/Service CRUD | 不需要 |
| **端口** | 8002 | 8001 |
| **扩缩容** | 1 个副本足够 | 按并发量扩缩 |

### 4.2 VSCode "无法解析导入 kubernetes" 是正常的

这个错误是因为你在主后端（`backend/app/`）的 workspace 里打开了 `backend/provisioner/app.py`。这个文件**不在主后端的 pyproject.toml 依赖范围内**。

Provisioner 的 `kubernetes` 依赖写在自己的 `Dockerfile` 里：

```dockerfile
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    kubernetes
```

本地开发 provisioner 时，单独给它创建虚拟环境：

```bash
cd backend/provisioner
uv init --no-readme
uv add fastapi "uvicorn[standard]" kubernetes urllib3 pydantic
uv run uvicorn app:app --host 0.0.0.0 --port 8002
```

---

## 五、与 DeerFlow 原版的差异

| 项目 | DeerFlow 原版 | Heyu Agent 适配后 |
|---|---|---|
| Skills 挂载 | volume mount → `/mnt/skills` | **不需要**（`read_skill` 动态注入到 workspace） |
| 重启策略 | `Always` | **`Never`**（一次性 Pod） |
| NODE_HOST 默认值 | `host.docker.internal` | **空**（自动从 K8s API 解析节点 IP） |
| Volume 策略 | 强制 hostPath | PVC 优先 → hostPath → emptyDir 兜底 |
| Pod 命名前缀 | `deer-flow-sandbox` | **`skillhub-sandbox`** |
| Namespace | 硬编码 | 可通过 `K8S_NAMESPACE` 环境变量配置 |

---

## 六、配置参考

```bash
# ── 必需 ──────────────────────────────────────────────
SANDBOX_IMAGE=swr.cn-south-1.myhuaweicloud.com/fintech-aigc/docker-sandbox:20260810V1.0

# ── Volume（选一个）───────────────────────────────────
# PVC 方式（生产推荐）
USERDATA_PVC_NAME=skillhub-userdata

# 或 hostPath 方式（本地开发/单机）
THREADS_HOST_PATH=/data/skillhub/threads
SKILLS_HOST_PATH=    # Heyu Agent 不需要，留空

# ── K8s 认证（选一个）─────────────────────────────────
# CCE 内：都不设，自动用 ServiceAccount
# 本地/外挂：挂载 kubeconfig
KUBECONFIG_PATH=/root/.kube/config

# ── 网络 ──────────────────────────────────────────────
K8S_NAMESPACE=skillhub
NODE_HOST=            # 留空 → 自动解析

# ── 可选 ──────────────────────────────────────────────
K8S_API_SERVER=https://host.docker.internal:26443  # Docker Desktop K8s
K8S_NODE_IP=10.0.0.1   # 显式指定节点 IP
```
