# SkillHub Sandbox 沙箱实现原理

> 本文档解释 SkillHub 的 Agent 代码执行沙箱是如何工作的——从配置文件到 Docker 容器，从虚拟路径到物理路径的完整链路。

---

## 一、一句话概括

Agent 执行代码时不能直接在 SkillHub 的 Python 进程里跑——不安全。所以 SkillHub 把代码执行（bash、文件读写等）隔离到**沙箱**里。

沙箱有两种实现：
- **本地沙箱**（开发用）：在宿主机上开子进程，无隔离
- **Docker 沙箱**（生产用）：每个对话线程启动一个 Docker 容器，完全隔离

---

## 二、架构分层

沙箱系统由两层独立组件构成，各司其职：

```
┌─────────────────────────────────────────────────────────┐
│                      Agent 工具层                        │
│  bash, ls, glob, grep, read_file, write_file,           │
│  str_replace（7 个 sandbox 工具）                        │
└────────────┬────────────────────────────┬────────────────┘
             │                            │
     ┌───────▼────────┐          ┌────────▼───────────┐
     │ PathProvider   │          │ SandboxProvider    │
     │ "路径长什么样"  │          │ "IO 怎么执行"       │
     │                │          │                    │
     │ 目录结构定义    │          │ 容器/子进程管理     │
     │ 虚拟↔物理映射  │          │ 获取→使用→释放     │
     └───────┬────────┘          └────────┬───────────┘
             │                            │
             └──────────┬─────────────────┘
                        │
              ┌─────────▼──────────┐
              │ SandboxPathResolver│
              │ 路径校验 + 翻译     │
              │ 输出脱敏            │
              └────────────────────┘
```

| 层 | 职责 | 核心问题 |
|---|---|---|
| **PathProvider** | 定义目录结构 | "这个线程的工作目录在哪？" |
| **SandboxProvider** | 管理执行环境 | "在哪个容器/进程里跑这条命令？" |
| **SandboxPathResolver** | 翻译路径 + 安全校验 | "Agent 写的 `/mnt/user-data/outputs/a.pptx` 实际对应磁盘上哪个文件？" |

---

## 三、PathProvider — 目录结构

### 3.1 物理目录布局

当前 SkillHub 使用 `DefaultPathProvider`，目录结构如下：

```
{workspace}/                          # 例: ../agent-test/
└── users/
    └── {user_id | "default"}/
        └── threads/
            └── {thread_id}/
                ├── workspace/        # Agent 临时工作区（中间文件）
                ├── uploads/          # 用户上传的文件（只读）
                ├── outputs/          # Agent 生成的交付物（前端可下载）
                └── acp-workspace/    # 子代理通信目录
```

| 目录 | 用途 | 权限 |
|---|---|---|
| `workspace/` | Agent 写代码、跑脚本的临时目录 | 读写 |
| `uploads/` | 用户上传的文件（Excel、PDF 等） | 读写（宿主机） |
| `outputs/` | Agent 生成的交付物（PPT、Word、图表等） | 读写 |
| `acp-workspace/` | 子代理（subagent）之间的通信目录 | 只读（容器内） |

### 3.2 虚拟路径 vs 物理路径

Agent 看到的是**虚拟路径**（容器内视角），不感知物理路径：

| Agent 视角（虚拟路径） | 实际磁盘位置（物理路径） |
|---|---|
| `/mnt/user-data/workspace/` | `../agent-test/users/default/threads/abc123/workspace/` |
| `/mnt/user-data/outputs/report.pptx` | `../agent-test/users/default/threads/abc123/outputs/report.pptx` |
| `/mnt/user-data/uploads/data.xlsx` | `../agent-test/users/default/threads/abc123/uploads/data.xlsx` |

虚拟前缀 `/mnt/user-data` 是硬编码的（`config_loader.py` 第 360 行），与 DeerFlow 容器镜像的约定保持一致。

---

## 四、SandboxProvider — 两种实现

### 4.1 LocalSandboxProvider（开发用）

```
Python 进程
  │
  │  tool 调用 bash("ls /mnt/user-data/workspace/")
  ▼
LocalSandbox.acquire(thread_id)
  │
  │  创建目录 → subprocess.run("ls /真实/路径/workspace/", shell=True, cwd=workspace)
  ▼
返回 stdout 字符串
```

- 直接在当前机器上 `subprocess.run()`
- **无任何安全隔离**——Agent 可以访问宿主机任意文件
- 每个线程创建一个 `LocalSandbox` 实例，物理上都在同一台机器
- 每个命令超时 30 秒，输出上限 50K 字符
- 启动快、调试方便，仅用于开发

### 4.2 AioSandboxProvider（生产用）

```
SkillHub Python 进程
  │
  │  tool 调用 bash("ls /mnt/user-data/workspace/")
  ▼
AioSandbox.acquire(thread_id)
  │
  │  HTTP API 调用 → agent_sandbox 客户端
  ▼
Docker 容器（sandbox）
  │  - 运行 all-in-one-sandbox 镜像
  │  - 挂载了 thread 专属目录
  │  - 暴露 HTTP API（默认端口 8080）
  │
  │  bash 在容器内执行
  ▼
返回 stdout 字符串
```

核心要点：

| 特性 | 说明 |
|---|---|
| **镜像** | `enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest` |
| **通信方式** | HTTP API（通过 `agent_sandbox` Python 客户端库） |
| **隔离** | 完全 Docker 容器隔离，agent 无法访问宿主机 |
| **持久化** | 不是——容器不保存状态，所有有意义的文件通过 bind mount 写到宿主机 |
| **文件共享** | 通过 Docker bind mount 把宿主机目录挂进容器 |

---

## 五、Docker 沙箱的完整生命周期

### 5.1 容器创建（`acquire`）

```
acquire(thread_id="userA-conv1")
  │
  ├─ 1. 生成 sandbox_id = sha256("userA-conv1")[:8]
  │      （确定性哈希，同一 thread 永远得到同一 id）
  │
  ├─ 2. 查找已有容器（缓存 / 暖池 / 运行中容器）
  │      └─ 找到了 → 直接复用，跳到最后
  │
  ├─ 3. 没找到 → 创建新容器
  │      │
  │      ├─ 检查并发上限（replicas，默认 3）
  │      │   └─ 满了 → 销毁最旧的暖池容器腾位置
  │      │
  │      ├─ 分配端口（从 base_port=8080 开始扫描）
  │      │
  │      ├─ 构造 bind mount：
  │      │   宿主机 /data/agent-test/users/userA/threads/conv1/workspace
  │      │     → 容器内 /mnt/user-data/workspace (rw)
  │      │   宿主机 /data/agent-test/users/userA/threads/conv1/outputs
  │      │     → 容器内 /mnt/user-data/outputs (rw)
  │      │   宿主机 /data/agent-test/users/userA/threads/conv1/uploads
  │      │     → 容器内 /mnt/user-data/uploads (rw)
  │      │   宿主机 /data/agent-test/users/userA/threads/conv1/acp-workspace
  │      │     → 容器内 /mnt/acp-workspace (ro)
  │      │
  │      ├─ docker run --rm -d -p {port}:8080 --name skillhub-sandbox-{id}
  │      │              --security-opt seccomp=unconfined
  │      │              {mount_args} {image}
  │      │
  │      └─ 等待健康检查通过（polling GET /v1/sandbox，最长 30s）
  │
  └─ 4. 返回 sandbox_id → 存入活跃池
```

### 5.2 容器使用（工具调用）

每次工具调用时：

```
_ensure_sandbox(runtime)
  │
  ├─ 1. 从 runtime.state 取 sandbox_id
  ├─ 2. provider.get(sandbox_id) → AioSandbox 实例
  ├─ 3. 如果容器挂了，用同一 sandbox_id 重新 acquire
  │
  ▼
AioSandbox 内部：
  ├─ bash 命令 → HTTP POST 到容器的 shell API
  │               （加 threading.Lock 串行化，因为容器维护持久 shell 会话）
  ├─ read_file  → HTTP GET 容器的文件 API
  ├─ write_file → HTTP POST 容器的文件 API
  └─ glob/grep  → 容器内 find + grep 命令
```

### 5.3 容器释放（`release`）

```
release(sandbox_id)
  │
  └─ 不销毁！移到暖池（warm pool）
     容器保持运行，下次同一个 thread 可以秒级复用
```

### 5.4 容器销毁

有几个触发条件：

| 触发条件 | 说明 |
|---|---|
| **空闲超时** | 后台线程每 60 秒检查，超过 `idle_timeout`（默认 600s）未使用的活跃容器 → 销毁 |
| **暖池超时** | 暖池容器也有超时，超时后销毁 |
| **并发上限** | `acquire` 时若达到 `replicas` 上限，销毁最老的暖池容器 |
| **进程退出** | `shutdown()` 销毁所有活跃 + 暖池容器 |
| **Signal** | 收到 SIGTERM/SIGINT 时先 shutdown 再退出 |

---

## 六、两种部署架构：Docker Socket vs 远程 Provisioner

### 6.1 为什么需要关注 Docker Socket 安全

AioSandboxProvider 需要动态创建容器。在开发环境直接挂载 `/var/run/docker.sock` 就行，但生产环境中 Docker Socket 权限极高——能访问它基本等于宿主机 root 权限。如果一个被攻破的容器持有 Docker Socket，攻击者可以：

- 查看 / 停止 / 删除宿主机上所有容器
- 创建特权容器并挂载宿主机根目录
- 实现**容器逃逸**，进一步控制宿主机

因此生产环境不能简单地把 Docker Socket 挂给 SkillHub 容器。

### 6.2 两种 SandboxBackend

SkillHub 的 AIO 沙箱设计了两种后端，用于不同部署场景：

| | `LocalContainerBackend` | `RemoteSandboxBackend` |
|---|---|---|
| **原理** | 直接调 `docker run` 创建容器 | 调 provisioner 的 HTTP API，由 provisioner 创建 Pod |
| **Docker Socket** | ✅ 需要挂载到 SkillHub 容器 | ❌ 不需要 |
| **适用场景** | 本地开发、单机测试 | 生产环境（K8s） |
| **代码位置** | `backend.py` `LocalContainerBackend` | `backend.py` `RemoteSandboxBackend` |
| **启用方式** | 默认 | 设 `provisioner_url` 配置项 |

### 6.3 开发/测试环境架构（LocalContainerBackend）

```
┌───────────────────────────┐
│  宿主机                    │
│                           │
│  ┌─────────────────┐     │
│  │ SkillHub 容器    │     │
│  │                 │     │
│  │ -v docker.sock  │────► docker daemon
│  │                 │     │     │
│  └─────────────────┘     │     │ docker run
│                           │     ▼
│                           │  ┌──────────────┐
│                           │  │ 沙箱容器 #1   │
│                           │  │ 沙箱容器 #2   │
│                           │  │ 沙箱容器 #3   │
│                           │  └──────────────┘
└───────────────────────────┘

简单直接，适合只有一台机器、没有 K8s 的测试环境。
风险：SkillHub 容器如果被攻破，攻击者可通过 Docker Socket 逃逸。
测试环境可接受此风险。
```

### 6.4 生产环境架构（RemoteSandboxBackend + K8s Provisioner）

```
┌──────────────────────────────────────────────────────────────┐
│                        K8s 集群                               │
│                                                              │
│  ┌─────────────────┐         HTTP          ┌──────────────┐  │
│  │  SkillHub Pod    │─────────────────────→│ Provisioner   │  │
│  │                  │  POST /api/sandboxes │              │  │
│  │  无 docker.sock  │  DELETE /api/...     │ K8s RBAC     │  │
│  │  普通应用权限    │                      │ 最小权限      │  │
│  └─────────────────┘                      └──────┬───────┘  │
│                                                  │          │
│                                       创建 Pod / 删除 Pod    │
│                                                  │          │
│                                                  ▼          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  沙箱 Pod (按需创建，用完回收)                          │   │
│  │                                                      │   │
│  │  - 通过 PVC 挂载线程工作目录                          │   │
│  │  - NetworkPolicy 网络隔离                             │   │
│  │  - ResourceQuota 资源限制                             │   │
│  │  - 自动 TTL 回收                                      │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

**核心思路**：SkillHub 不直接操作 Docker/K8s，只调 provisioner 的 REST API。Provisioner 是唯一拥有容器管理权限的服务，可以做严格的 RBAC 控制。

**RemoteSandboxBackend 的代码（已实现）**：

```python
# backend.py 第 461 行起
class RemoteSandboxBackend(SandboxBackend):
    """薄 HTTP 客户端，所有沙箱生命周期都委托给 provisioner。"""

    def create(self, thread_id, sandbox_id, extra_mounts=None) -> SandboxInfo:
        resp = requests.post(
            f"{self._provisioner_url}/api/sandboxes",
            json={"sandbox_id": sandbox_id, "thread_id": thread_id},
            timeout=30,
        )
        return SandboxInfo(sandbox_id=sandbox_id, sandbox_url=data["sandbox_url"])

    def destroy(self, info: SandboxInfo) -> None:
        requests.delete(
            f"{self._provisioner_url}/api/sandboxes/{info.sandbox_id}",
            timeout=15,
        )
```

启用方式：在创建 AioSandboxProvider 时传入 `provisioner_url=http://provisioner:8080`。

### 6.5 各阶段推荐

| 阶段 | 后端 | 说明 |
|---|---|---|
| **本地开发** | `LocalContainerBackend` | 需要本地 Docker Desktop，`docker run` 直接创建 |
| **测试环境** | `LocalContainerBackend` | 单机 Docker，挂载 docker.sock 风险可控 |
| **生产环境** | `RemoteSandboxBackend` | 需要 provisioner 服务就位，SkillHub 不需要 Docker Socket |

**测试环境可以用 LocalContainerBackend 先上**，生产再切 RemoteSandboxBackend。两者对 SkillHub 其他代码完全透明——只是换了 `SandboxBackend` 的实现。

### 6.6 沙箱冷启动优化：镜像预热 + 节点亲和

**问题**：生产模式（RemoteSandboxBackend）下，每个对话线程创建一个全新 Pod。沙箱镜像 `docker-sandbox`（约 1~2GB）拉取策略是 `IfNotPresent`（`provisioner/app.py`），即「节点本地有缓存就不拉」。如果 Pod 被调度到一个本地还没缓存该镜像的节点，就要现场从 SWR 拉 1~2GB，实测启动时长 2 分钟以上。

**根因**：不是 CCE 慢，而是「冷节点全量拉镜像」。两个变量叠加放大：

- 沙箱 Pod 没有 nodeAffinity → 调度器把它摊到任意节点 → 缓存命中率只有 1/N（N=节点数）；
- CCE 节点池若配置了弹性伸缩，节点回收/扩容会把镜像缓存清掉。

**解法**：两个机制配合，职责不同：

| 机制 | 职责 | 落地 |
|---|---|---|
| **镜像预热** | 把镜像提前拉到沙箱节点的本地磁盘 | `deploy/sandbox-image-warmer.yaml`（Deployment，1 副本） |
| **节点亲和** | 让沙箱 Pod 只调度到那些已预热的节点 | `provisioner/app.py` 的 `_build_node_affinity()`，由 `SANDBOX_NODE_LABEL_KEY`/`SANDBOX_NODE_LABEL_VALUE` 控制 |

预热 Deployment 原理：一个 `sleep infinity` 占位 Pod 靠 nodeSelector 落在目标沙箱节点上（按 `kubernetes.io/hostname` 固定，无需打自定义标签），引用同一个沙箱镜像 → 逼 K8s 先把镜像拉到节点本地，之后沙箱 Pod 落地即命中缓存、秒起。（不用 DaemonSet 是因为沙箱只固定在 1 个节点，且部分集群的 Gatekeeper 策略会拦截 DaemonSet。）

启用步骤（有顺序要求）：

```bash
# 1. 找到 provisioner 所在节点（记下 NODE 列，即要固定的节点名）
kubectl get pods -n fintech-aigc-dev -l app=sandbox-provisioner -o wide

# 2. 把节点名写进两个文件（无需打标签，用内置 kubernetes.io/hostname）：
#    - deploy/provisioner-deployment.yaml 的 SANDBOX_NODE_LABEL_VALUE
#    - deploy/sandbox-image-warmer.yaml   的 nodeSelector

# 3. 部署预热 Deployment（在目标节点上拉镜像，1~2 分钟，一次性）
kubectl apply -f deploy/sandbox-image-warmer.yaml

# 4. 重部署 provisioner（生效 nodeAffinity，把沙箱 Pod 固定到目标节点）
kubectl apply -f deploy/provisioner-deployment.yaml
```

**节点数量规划**：沙箱 Pod 资源极轻（100m~1000m CPU / 256Mi~1Gi 内存），真正的瓶颈是 LLM API 的 QPS 而非沙箱算力（见第十节）。因此：

| 环境 | 沙箱节点 | 节点数 | 说明 |
|---|---|---|---|
| 测试环境 | 现有集群 `fintech-cce-dev` 内的 1 个节点 | **1 个** | 单节点能跑几十个并发沙箱 Pod；**无需新建节点池**，按节点名固定即可 |
| 生产环境 | `skillhub-sandbox-pool`（专用节点池） | **2~3 个** | 按并发量定，配合弹性伸缩 |

节点越多，预热后的镜像缓存越被稀释、命中率越低——所以沙箱节点「宁少勿多」，保证冗余即可。

**固定到指定节点（无需打标签）**：

集群的 Gatekeeper 策略（`[node]`）禁止普通用户（`cce:users` 组）修改 Node，`kubectl label node` 会被拒。改用**内置标签 `kubernetes.io/hostname`** 直接按节点名固定，无需任何 Node 修改权限：

```yaml
# provisioner 环境变量
SANDBOX_NODE_LABEL_KEY   = kubernetes.io/hostname
SANDBOX_NODE_LABEL_VALUE = <目标节点名>   # 如 c2744bb7-aa96-4a3d-8c14-ad18e68c3983
```

> 效果等同于「把沙箱 Pod 钉在这台节点上」。若以后拿到修改 Node 的权限，再换回自定义标签 + 节点池即可。
>
> 注意：CCE 节点常带 `node.cce.io/NodePodKey` 的 `NoSchedule` taint，沙箱 Pod 与 warmer 已加对应 toleration（`operator: Exists`），否则会一直 Pending。

---

## 七、DooD 路径翻译（重要）

### 7.1 问题

当 SkillHub 本身运行在 Docker 容器里，又通过 Docker socket 调度沙箱容器时，路径会出现两套视角：

```
┌─────────────────────────────────────────────────────────┐
│ 宿主机                                                   │
│   /var/lib/skillhub/agent-test/  ← 磁盘上的真实路径      │
│       │                                                 │
│       │ docker run -v 挂载                               │
│       ▼                                                 │
│   ┌──────────────┐      ┌──────────────────────┐        │
│   │ SkillHub 容器 │      │ 沙箱容器（agent 执行） │        │
│   │              │      │                      │        │
│   │ 看到的路径：  │      │ 挂载源必须用宿主机路径 │        │
│   │ /data/       │      │ /var/lib/skillhub/   │        │
│   │   agent-test/│      │   agent-test/...     │        │
│   └──────────────┘      └──────────────────────┘        │
└─────────────────────────────────────────────────────────┘
```

SkillHub 容器内看到 `/data/agent-test/`，但 Docker daemon 在宿主机上，需要 `/var/lib/skillhub/agent-test/` 才能正确 bind mount。

### 7.2 解决方案

设置 `SKILLHUB_HOST_BASE_DIR` 环境变量：

```bash
# SkillHub 容器启动时
docker run \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/lib/skillhub/agent-test:/data/agent-test \
  -e SKILLHUB_HOST_BASE_DIR=/var/lib/skillhub/agent-test \
  skillhub:latest
```

AioSandboxProvider 内部：
- `_thread_base_dir` = `/data/agent-test`（容器内视角，用于定位文件）
- `_host_base_dir` = `/var/lib/skillhub/agent-test`（宿主机视角，用于构造 `docker run -v` 的 mount source）

---

## 八、路径解析与安全

### 8.1 核心组件：`SandboxPathResolver`

负责四项工作：

| 功能 | 说明 | 调用时机 |
|---|---|---|
| **校验** | 拒绝越权路径（`..` 遍历、写到允许范围外的路径） | 每次文件写入前 |
| **解析** | 虚拟路径 → 物理路径 | 本地沙箱的每个工具调用 |
| **脱敏** | 工具输出中的物理路径 → 替换回虚拟路径 | 本地沙箱的输出处理 |
| **重写** | bash 命令中的虚拟路径 → 替换为物理路径 | 本地沙箱的 bash 工具 |

### 8.2 安全边界

Agent 的 `write_file` 工具只允许写到以下路径的子路径：

```
/mnt/user-data/workspace/*    （读写）
/mnt/user-data/outputs/*     （读写）
/mnt/user-data/uploads/*     （读写——本地模式；Docker 模式只读）
/mnt/acp-workspace/*         （只读）
```

以下操作被拒绝：
- 写到虚拟路径的**根**（`/mnt/user-data/`，不包含子目录）
- 路径中包含 `..`
- `file://` URL
- 写到自定义 mount 的只读目录

---

## 九、七个沙箱工具

`make_sandbox_tools()` 工厂函数生成 7 个 langchain Tool：

| 工具 | 功能 | 特别说明 |
|---|---|---|
| `bash` | 在沙箱中执行 shell 命令 | 输出超过 50000 字符时中间截断（50/50）。对本地沙箱还会校验命令中的路径。 |
| `ls` | 列出目录内容 | 最大深度 2，上限 100K 条目，60s 超时 |
| `glob` | 通配符搜索文件 | 支持 `include_dirs`，上限可配 |
| `grep` | 正则/文本搜索文件内容 | 跳过 >10MiB 的文件，匹配行截断到 200 字符 |
| `read_file` | 读取文件内容 | UTF-8，上限 50000 字符，超出则头部截断 |
| `write_file` | 写入文本文件 | 支持 append 模式，自动创建父目录 |
| `str_replace` | 文本替换（精确匹配） | 类似于 IDE 的精确查找替换 |

每个工具的执行流程：

```
Tool 被调用
  │
  ├─ 1. _ensure_sandbox(runtime) → 获取或创建 sandbox 实例
  ├─ 2. _ensure_thread_directories_exist(runtime) → 确保目录存在（本地沙箱）
  ├─ 3. 路径解析：
  │      Docker 沙箱 → 直接传虚拟路径（容器自己解析）
  │      本地沙箱  → 虚拟路径翻译成物理路径再传给子进程
  ├─ 4. 调用 Sandbox 的 I/O 方法
  ├─ 5. 输出处理：
  │      本地沙箱 → 把输出中的物理路径替换回虚拟路径
  └─ 6. 返回结果
```

---

## 十、并发控制与资源消耗

### 10.1 容器数量有上限……但是软限制

`AioSandboxProvider` 通过 `replicas` 参数（默认 **3**）控制并发容器数。**但这是软限制**——优先通过踢暖池来控，踢不了就超限创建：

```python
# provider.py _create_sandbox() 的实际逻辑
if total >= replicas:
    evicted = self._evict_oldest_warm()  # 先尝试从暖池踢一个
    if not evicted:
        logger.warning("All replicas slots are active; creating beyond soft limit")
        # ↑ 只是打个 warning，不阻塞，照建容器

info = self._backend.create(...)  # 不管怎样都执行 docker run
```

不是 100 个用户 = 100 个容器，但也不是硬限制在 3 个。

### 10.2 复用机制：暖池（Warm Pool）

容器**不会**在请求结束后马上销毁，而是移到暖池待命：

```
用户A 发消息 → docker run #1 → 执行 → 释放到暖池（容器保持运行）
                              │
用户A 再发消息 → 暖池有 #1 → 秒级复用，不走 docker run
用户B 发消息 → 暖池没 B 的容器 → docker run #2
用户C 发消息 → docker run #3（达到 replicas=3 上限）
用户D 发消息 → 3 个都在用 → 踢掉暖池里最久未用的 → docker run #4
```

靠 `sha256(thread_id)` 做确定性命名，同一用户的同一对话永远映射到同一个容器名，实现跨请求复用。

### 10.3 回收机制

| 触发条件 | 行为 |
|---|---|
| 容器空闲超过 `idle_timeout`（默认 600s = 10 分钟） | 后台线程每 60s 扫描一次，超时的 `docker stop` |
| 暖池里的容器超过自己的超时 | 同上 |
| 达到 `replicas` 上限时有新请求进来 | 销毁最老的暖池容器腾位置 |
| SkillHub 进程退出 / 收到 SIGTERM | 销毁所有活跃 + 暖池容器 |

### 10.4 实际时间线示例

```
09:00  用户A 发消息 → docker run #1 → 用完入暖池
09:01  用户A 又发   → 复用 #1
09:02  用户B 发消息 → docker run #2 → 用完入暖池
09:03  用户C 发消息 → docker run #3（达到 replicas）→ 用完入暖池
09:04  用户D 发消息 → 暖池有空的 → 复用 #1（踢出暖池分给 D）
09:04  用户E 发消息 → 暖池有空的 → 复用 #2
09:05  用户F 发消息 → 暖池空的，活跃的也全在用
                     → 超软限制，创建 #4（打一条 warning 日志）
09:15  没人说话   → 10 分钟超时，所有容器 docker stop
```

### 10.5 为什么 100 个并发用户也不会撑爆服务器

Agent 的耗时分布决定了沙箱不太可能成为瓶颈：

```
一个 Agent 请求的时间分布：
┌──────────────────────────────────────────────┐
│ 思考(等 LLM 返回)  ██████████████████  5-30秒 │
│ 执行工具(沙箱)              ██░░░░░  1-5秒    │
│ 思考(等 LLM 返回)           ░░██████████████  │
│ 执行工具(沙箱)                    ██  1-5秒   │
└──────────────────────────────────────────────┘
         沙箱占用时间占比 ≈ 5-10%
```

100 个用户同时发消息 → 100 个 Agent 同时调 LLM → **只有 5-10 个刚好在执行工具**。真正的瓶颈是 LLM API 的 QPS 和延迟，不是沙箱。

### 10.6 资源消耗估算

沙箱容器不是虚拟机，只是一个带 Python + 基础工具的轻量 Docker 镜像：

| 资源 | 单个沙箱容器 | 3 个容器（replicas 上限） |
|---|---|---|
| 内存 | ~200-500 MB | ~1-1.5 GB |
| CPU | 空闲时接近 0 | 空闲时接近 0 |
| 磁盘 | 不存数据（bind mount 到宿主机） | 镜像约 1-2 GB（只拉一次） |

加上 SkillHub 自己的 Python 进程（~500MB-1GB），**日常 2-3 GB 内存足够**。

---

## 十一、配置项汇总

### config.yaml 中的 sandbox 段

```yaml
sandbox:
  provider: docker        # local | docker | auto
  workspace: ../agent-test  # 工作区根目录（相对 backend/）
  bash_output_max_chars: 50000
  read_file_output_max_chars: 50000
```

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `provider` | `local`=子进程, `docker`=Docker 容器, `auto`=先试 Docker 再回退 | `auto` |
| `workspace` | 所有线程数据存放的根目录 | `../agent-test` |
| `bash_output_max_chars` | bash 工具输出截断阈值（0=不截断） | 50000 |
| `read_file_output_max_chars` | 读文件输出截断阈值 | 50000 |

### AioSandboxProvider 的关键参数（代码中硬编码）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `image` | `enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest` | 沙箱镜像 |
| `replicas` | 3 | 最大并发容器数（软限制） |
| `idle_timeout` | 600s | 空闲容器自动销毁时间 |
| `base_port` | 8080 | 容器端口分配起始值 |

### 环境变量

| 变量 | 说明 |
|---|---|
| `SKILLHUB_HOST_BASE_DIR` | DooD 场景下，宿主机上的 workspace 真实路径。不设则 fallback 到容器内路径 |

Provisioner 侧（生产 K8s 模式，见 6.6 节）：

| 变量 | 说明 | 默认 |
|---|---|---|
| `SANDBOX_NODE_LABEL_KEY` | 沙箱节点标签 key；设置后沙箱 Pod 只调度到匹配该 key=value 的节点。可用内置 `kubernetes.io/hostname` 按节点名固定，无需改 Node | 空（不限制调度） |
| `SANDBOX_NODE_LABEL_VALUE` | 沙箱节点标签 value（如节点名） | `true` |

---

## 十二、端到端流程示意

用户发一条消息"把这份 Excel 生成一个 PPT"：

```
1. Chat API 收到请求
     │
2. ChatService 创建 RunManager，启动 Agent
     │
3. Agent 开始执行 ReAct 循环
     │
4. Agent 决定调用 read_file 工具读取 Excel
     │
5. read_file 工具内部：
   ├─ acquire("userA-conv1") → Docker 容器启动/复用
   │   ├─ 创建目录 /data/agent-test/users/userA/threads/conv1/workspace/
   │   ├─ docker run -v /data/.../workspace:/mnt/user-data/workspace ...
   │   └─ 返回 sandbox_id
   │
   ├─ 解析路径 /mnt/user-data/uploads/data.xlsx
   │   → 物理路径 /data/agent-test/.../uploads/data.xlsx（bind mount 处理）
   │
   ├─ AioSandbox.read_file(...) → HTTP 调容器 API
   │   → 容器读 /mnt/user-data/uploads/data.xlsx → 返回内容
   │
   └─ 返回文件内容给 Agent
     │
6. Agent 分析数据 → 调用 bash("python generate_ppt.py")
     │
7. bash 工具内部：
   ├─ 复用自己的 sandbox（同一个 thread_id）
   ├─ 容器内执行 python 脚本
   │   → 写 /mnt/user-data/outputs/report.pptx
   │   → 因为 bind mount，实际写到了宿主机 .../outputs/report.pptx
   └─ 返回输出
     │
8. Agent 完成 → SandboxMiddleware 调 release(sandbox_id)
   → 容器移到暖池，不销毁（下次用秒级恢复）
     │
9. 前端调 /chat/files/{conversation_id}?path=/mnt/user-data/outputs/report.pptx
   → FileTreeBuilder 扫描宿主机 outputs 目录
   → FileResponse 返回文件
```
