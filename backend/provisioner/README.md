# SkillHub Sandbox Provisioner

Provisioner 是 SkillHub 的**独立辅助服务**，负责在 K8s 集群中按需创建/销毁 Sandbox Pod。Agent 执行代码需要隔离环境，Provisioner 替主后端跟 K8s API Server 打交道，为每个对话线程创建独立的 Sandbox Pod。

## 为什么是独立服务

| | Provisioner | SkillHub 主后端 |
|---|---|---|
| **Python 依赖** | fastapi + uvicorn + kubernetes | 大量 AI/Agent 依赖 |
| **镜像大小** | ~200MB（slim） | ~2GB+ |
| **K8s 权限** | Pod/Service CRUD | 不需要 |
| **端口** | 8002 | 8001 |

**权限隔离**：Provisioner 需要 K8s CRUD 权限，主后端不需要。即使主后端被攻破，攻击者无法直接操纵 K8s 资源。

## 架构

```
┌─────────────────┐  HTTP                         ┌──────────────┐
│  SkillHub 主后端  │ ────▸ http://provisioner:8002 │  Provisioner │
│  (Pod)          │      (K8s Service DNS)        │  (Pod)       │
└────────┬────────┘                               └──────┬───────┘
         │                                               │ K8s API
         │                                               │ 创建 Pod
         │                                               ▼
         │                                      ┌──────────────┐
         │                                      │  Sandbox Pod │
         │                                      │  emptyDir    │
         │                                      │  :NodePort   │
         │                                      └──────┬───────┘
         │  HTTP API 拉取文件（base64）                  │
         └──────────────────────────────────────────────┘
                  Agent 生成文件 → Backend 拉取 → 上传 OBS
```

### 关键设计

- **emptyDir 存储**：Sandbox Pod 使用 emptyDir 临时存储（Pod 删除后自动清空），不需要 PVC
- **文件同步**：Agent 运行完成后，Backend 通过 sandbox HTTP API 拉取生成的文件 → 上传到对象存储（OBS/MinIO）
- **不需要 skills volume mount**：SkillHub 通过 `read_skill` 工具从主后端磁盘读取 skill 文件，再通过 sandbox HTTP API 写入 sandbox workspace
- **Pod 重启策略 `Never`**：Sandbox 是一次性 Pod，退出后自动清理
- **NodePort Service**：每个 Sandbox Pod 绑定一个 NodePort Service，主后端通过 `{NodeIP}:{NodePort}` 直连

## API 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 健康检查 |
| `/api/sandboxes` | POST | 创建 Sandbox Pod + NodePort Service |
| `/api/sandboxes/{sandbox_id}` | GET | 查询 Sandbox 状态 |
| `/api/sandboxes/{sandbox_id}` | DELETE | 销毁 Sandbox Pod + Service |
| `/api/sandboxes` | GET | 列出所有 Sandbox |

### POST /api/sandboxes

**请求**：
```json
{
  "sandbox_id": "abc12345",
  "thread_id": "user-xxx"
}
```

**响应**：
```json
{
  "sandbox_id": "abc12345",
  "sandbox_url": "http://10.0.0.1:32123",
  "status": "Running"
}
```

**幂等**：相同 `sandbox_id` 重复调用直接返回已有 sandbox 信息。

### DELETE /api/sandboxes/{sandbox_id}

直接删除 Pod + Service。404 不报错（Gone 状态）。

## 配置

所有配置通过**环境变量**注入（写在 K8s Deployment YAML 的 `env` 字段）。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SANDBOX_IMAGE` | (必填) | Sandbox 容器镜像地址 |
| `SANDBOX_NODE_LABEL_KEY` | (空) | 沙箱节点标签 key。设置后 Sandbox Pod 只调度到匹配该 key=value 的节点。可用内置 `kubernetes.io/hostname` 按节点名固定，无需改 Node（集群 Gatekeeper 常禁止打标签） |
| `SANDBOX_NODE_LABEL_VALUE` | `true` | 沙箱节点标签 value（如节点名，与 key 配合） |
| `K8S_NAMESPACE` | `skillhub` | K8s 命名空间 |
| `NODE_HOST` | (空) | 节点 IP/域名（空则自动从 K8s API 解析节点 IP） |
| `KUBECONFIG_PATH` | (空) | kubeconfig 文件路径（CCE 内留空，自动用 ServiceAccount） |
| `K8S_API_SERVER` | (空) | 覆盖 K8s API Server 地址 |
| `K8S_NODE_IP` | (空) | 显式指定节点 IP（优先级最高） |
| `K8S_NODE_NAME` | (空) | 通过节点名从 K8s API 查找节点 IP |

### Volume 策略

Sandbox Pod 始终使用 **emptyDir** 作为 `/mnt/user-data` 的存储——临时、跟 Pod 同生命周期、Pod 删除自动清空。

Backend 在 Agent 执行完毕后通过 sandbox HTTP API 拉取文件上传到对象存储（OBS/MinIO），故不需要持久化卷。

## 部署

### 1. 构建镜像

```bash
cd backend/provisioner
docker build -t swr.cn-south-1.myhuaweicloud.com/fintech-aigc/provisioner:20260811V1.0 .
docker push swr.cn-south-1.myhuaweicloud.com/fintech-aigc/provisioner:20260811V1.0
```

### 2. 创建 K8s 资源

**Provisioner Deployment + Service**：
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: provisioner
  namespace: skillhub
spec:
  replicas: 1
  selector:
    matchLabels:
      app: provisioner
  template:
    metadata:
      labels:
        app: provisioner
    spec:
      serviceAccountName: provisioner      # 需要 Pod/Service CRUD 权限的 RBAC
      containers:
        - name: provisioner
          image: swr.cn-south-1.myhuaweicloud.com/fintech-aigc/provisioner:20260811V1.0
          ports:
            - containerPort: 8002
          env:
            - name: SANDBOX_IMAGE
              value: "swr.cn-south-1.myhuaweicloud.com/fintech-aigc/docker-sandbox:20260810V1.0"
            - name: K8S_NAMESPACE
              value: "skillhub"
          readinessProbe:
            httpGet:
              path: /health
              port: 8002
---
apiVersion: v1
kind: Service
metadata:
  name: provisioner              # ← 集群内 DNS: http://provisioner:8002
  namespace: skillhub
spec:
  selector:
    app: provisioner
  ports:
    - port: 8002
      targetPort: 8002
```

### 3. SkillHub 主后端配置

`config.yaml` 中设置：
```yaml
sandbox:
  provisioner_url: "http://provisioner:8002"   # K8s Service DNS
```

### 4. RBAC（Provisioner 需要的 K8s 权限）

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: provisioner
  namespace: skillhub
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: provisioner-role
  namespace: skillhub
rules:
  - apiGroups: [""]
    resources: ["pods", "services"]
    verbs: ["create", "get", "list", "delete"]
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get"]
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: provisioner-binding
  namespace: skillhub
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: provisioner-role
subjects:
  - kind: ServiceAccount
    name: provisioner
    namespace: skillhub
```

## 与主后端的交互链路

```
用户发消息
  → SkillHub 主后端运行 Agent
  → Agent 需要 sandbox → AioSandboxProvider.acquire(thread_id)
    → RemoteSandboxBackend.create()
      → POST http://provisioner:8002/api/sandboxes
        → Provisioner 创建 K8s Pod + NodePort Service
        → 返回 sandbox_url = http://{NodeIP}:{NodePort}
  → Agent 工具调用（bash, read_file, write_file...）
    → 通过 sandbox_url 直接发 HTTP 到 Sandbox Pod
  → 对话结束 → destroy sandbox
    → DELETE http://provisioner:8002/api/sandboxes/{id}
```

## 安全

1. **最小权限**：Provisioner 只有 Pod/Service CRUD + Namespace/Node Read 权限
2. **资源限制**：每个 Sandbox Pod 有 CPU/Memory 限制（100m~1000m CPU, 256Mi~1Gi Memory）
3. **重启策略 `Never`**：Sandbox Pod 退出后不会自动复活，避免僵尸 Pod
4. **镜像来源**：Sandbox 镜像来自私有 SWR 仓库
