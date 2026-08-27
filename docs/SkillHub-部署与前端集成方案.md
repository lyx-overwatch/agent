# SkillHub 部署与前端集成方案

> SkillHub 前端是一个独立 HTML 文件，集成到主系统（`dify-cmbc`）Next.js 项目下；
> 后端以单个 Docker 镜像部署到华为云工作负载；nginx 已有，反向代理接入。

---

## 一、整体架构

```
浏览器
   │
   │  GET https://app.cmbc.com/skillhub
   ▼
nginx (主系统已有)
   │
   │  /skillhub       → dify-cmbc/web Next.js 容器 → public/skillhub/index.html
   │  /skillhub-api/* → SkillHub 后端容器 (FastAPI) → 去掉前缀后转发
   │
   └─ HTML 内 JS 调用 /skillhub-api/*  → 同源，无 CORS，登录态共享
```

**核心要点**

| 项 | 决策 |
|---|---|
| 前端 | 独立 HTML，落到主系统 Next.js 的 `public/` 目录下 |
| 后端 | 单一 Docker 镜像，推送到华为云镜像仓库，运维切换工作负载镜像 |
| 反代 | nginx 已存在，加两条 `location` 即可 |
| 路径 | 用 `/skillhub` 和 `/skillhub-api/` 前缀做隔离，避免和主系统路由冲突 |

---

## 二、为什么选这套方案（备选方案对比）

### 2.1 三种集成方式对比

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **A. `public/` 静态资源 + rewrite**（✅ 选用） | HTML 放 `public/skillhub/`，`next.config.js` 加 `rewrites` | 零 React 代码，HTML 版本独立管理 | 需要确认 HTML 是自包含的（CSS/JS 内联或 CDN） |
| **B. 后端镜像托管 HTML + nginx 反代** | HTML 跟后端一起打包，nginx 直转 | HTML 版本与后端强绑定 | 前端/后端发版节奏被绑死 |
| **C. `<iframe>` 嵌入** | `app/skillhub/page.tsx` 写 `<iframe>` | 灵活 | 登录态不共享、跨域、高度自适应麻烦 |

### 2.2 为什么不用「前后端 + nginx 单镜像方案」

最初考虑的"一个镜像装 nginx + frontend + backend + supervisord"方案被否决：

| 风险点 | 说明 |
|---|---|
| **日志写不进镜像** | 镜像层只读，日志必须走 stdout + 外部采集器 |
| **OSS/S3 不能打包** | OSS 是外部服务，镜像里只能放 SDK 代码和配置占位 |
| **僵尸进程** | 一个进程崩了容器不会自动重启，必须有 supervisord/s6 作 PID 1 |
| **不符合当前部署模式** | 运维已经走"切镜像"模式，多镜像职责更清晰 |

---

## 三、操作步骤

### Step 1：放置 HTML 文件

```
D:\registry\origin\dify-cmbc\web\public\skillhub\index.html
                                  └─────┬─────┘
                              Next.js 的 public/ 目录
                              部署后可通过根 URL 直接访问
```

### Step 2：在 `next.config.js` 加 `rewrites()`

当前 `dify-cmbc/web/next.config.js` 没有 `rewrites()` 字段，加上：

```js
async rewrites() {
  return [
    {
      source: '/skillhub',
      destination: '/skillhub/index.html',  // /skillhub 自动补 /index.html
    },
  ];
}
```

改完后访问 `https://app.cmbc.com/skillhub` 就能直接看到 HTML 页面。

### Step 3：调整 HTML 内的 API 调用地址

HTML 里所有调后端的请求，改成**同源相对路径** `/skillhub-api/...`：

```html
<script>
  // 修改前（举例）
  // fetch('http://后端地址/chat/stream', {...})

  // 修改后（推荐：相对路径，配合 nginx 反代，无 CORS）
  fetch('/skillhub-api/chat/stream', {...})
</script>
```

如果 HTML 里有多处硬编码 URL，批量替换脚本可参考第六节。

### Step 4：nginx 加两条 `location`

在已有的 nginx 配置里加：

```nginx
# 1. SkillHub 的 HTML 页面 → 走 Next.js 容器
location /skillhub {
    proxy_pass http://dify-cmbc-web:3000;
    # 你现有的 proxy_set_header / proxy_http_version 等保持原样
}

# 2. SkillHub 的 API 调用 → 走后端容器
location /skillhub-api/ {
    # 去掉 /skillhub-api 前缀，把 /skillhub-api/chat → /chat 转发给后端
    rewrite ^/skillhub-api/(.*)$ /$1 break;
    proxy_pass http://skillhub-backend:8001;

    # 重要：SSE 流式响应需要这几行（chat/stream 是 SSE）
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 600s;
    proxy_set_header Connection '';
    proxy_set_header X-Accel-Buffering no;
}
```

> **路径前缀 `/skillhub-api/` 而不是 `/api/`**：避免和 Next.js 项目将来可能加的 `/api` 路由冲突。

### Step 5：后端 CORS（仅在跨域时需要）

如果 Step 3 改成了同源相对路径，**无需任何 CORS 配置**。

如果 HTML 仍硬编码了后端的完整 URL（如 `https://api.cmbc.com/chat`），则在后端加：

```python
# backend/app/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.cmbc.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 四、Next.js `output: 'standalone'` 模式的坑

`dify-cmbc/web/next.config.js` 第 26 行有 `output: 'standalone'`。这个模式下：

- Next.js 默认**不会**把 `public/` 整个目录拷进 standalone 输出
- 只有 `public/` 下的**特殊资源**（比如 favicon）会被处理
- 必须手动拷贝，否则部署后 `/skillhub/index.html` 会 404

### 修复方案

**方案 A：构建脚本里手动拷贝**

```bash
pnpm build
cp -r public .next/standalone/
cp -r .next/static .next/standalone/.next/static
```

**方案 B：检查现有 Dockerfile**

打开 `dify-cmbc/web/Dockerfile`，看 `COPY` 指令有没有覆盖 `public/`。如果没有，需要在 Dockerfile 里加：

```dockerfile
COPY --from=builder /app/public ./public
```

> **部署前必做**：部署完访问 `/skillhub`，如果 404，先查这一步。

---

## 五、附录：Docker 基础概念（供查阅）

### 5.1 Dockerfile vs docker-compose

| 维度 | Dockerfile | docker-compose |
|---|---|---|
| 本质 | 构建脚本（一步步打包出一个镜像） | 运行时编排清单（声明要启动哪些容器） |
| 触发命令 | `docker build` | `docker compose up` |
| 产物 | 一个**镜像**（静态、可分发） | 一组**运行中的容器 + 网络 + 卷** |
| 不写 Dockerfile 也能用 compose | ❌ 不行（`build` 必须指向 Dockerfile） | ✅ 可以（`image: nginx:alpine` 拉现成的） |
| 不写 compose 也能用 Dockerfile | ✅ 可以（`docker run <image>` 也能跑） | ❌ 不行 |

### 5.2 docker-compose 配置来源全景

```
┌──────────────────────────────────────────────────────────────┐
│                    docker-compose.yaml 内部                    │
│                                                              │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │ YAML 字面量 │  │ environment: │  │ env_file: ./xxx.env  │ │
│  │ (image:    │  │ 列表/字典    │  │ 引用外部文件          │ │
│  │ nginx:...) │  │ 直接写在     │  │ 文件里的 KEY=VALUE   │ │
│  └────────────┘  │ compose 里   │  │ 会被注入容器          │ │
│                  └──────────────┘  └──────────────────────┘ │
│                                                              │
│  ${VAR} 占位符解析顺序（优先级从高到低）：                    │
│    1. 命令行 --env-file / 环境变量 覆盖                       │
│    2. shell 环境（你 export 出来的）                          │
│    3. 同目录 .env 文件                                        │
│    4. compose 文件里写的默认值 ${X:-default}                  │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼ 最终注入容器
                   ┌────────────────────┐
                   │  容器进程的环境变量  │
                   └────────────────────┘
```

### 5.3 `.env` 文件 vs `env_file:` 字段

| | **`.env` 文件**（自动加载） | **`env_file:` 字段**（yaml 里声明） |
|---|---|---|
| 默认文件名 | 必须是 `.env`（在 compose 同目录） | 任意名字，yaml 里指明路径 |
| 作用对象 | compose CLI 解析 `${VAR}` 时用 | 注入到容器进程里 |
| 生效阶段 | `docker compose up` 解析 yaml 时 | 容器启动后，进程里 `$VAR` 可见 |
| 能不能给容器？ | ❌ 不能（除非写 `env_file: .env`） | ✅ 能 |
| 本项目里的实例 | — | `env_file: ../frontend/.env` 喂给前端容器 |

**关键结论**：同名不同物，作用域完全分开。

### 5.4 容器日志的正确做法

```ini
# supervisord.conf（如果用单镜像方案）
[program:backend]
command=uvicorn app.main:app --host 0.0.0.0 --port 8001
stdout_logfile=/dev/stdout        # 关键：吐到容器 stdout
stderr_logfile=/dev/stderr
```

由 docker daemon 采集 → 华为云日志服务（LTS）或自建 Loki。不写文件。

### 5.5 进程管理器（PID 1）

如果一个容器跑多个进程，必须有进程管理器当 PID 1，否则：

- 一个进程挂掉容器不会自动重启
- 僵尸进程会泄漏

常见选择：

| 工具 | 特点 |
|---|---|
| **supervisord** | 老牌、配置简单、Python 生态熟悉 |
| **s6-overlay** | 更轻量、更现代 |
| **dumb-init + shell 脚本** | 最简，但需要自己写重启逻辑 |

---

## 六、HTML 批量替换脚本参考

替换前先备份。`/skillhub-api/` 前缀可以根据需要调整：

```bash
# Linux/macOS (sed)
sed -i.bak \
  -e 's|http://后端地址/|/skillhub-api/|g' \
  -e 's|http://localhost:8001/|/skillhub-api/|g' \
  -e 's|http://127.0.0.1:8001/|/skillhub-api/|g' \
  public/skillhub/index.html

# Windows PowerShell
$content = Get-Content public/skillhub/index.html -Raw
$content = $content -replace 'http://后端地址/', '/skillhub-api/'
$content = $content -replace 'http://localhost:8001/', '/skillhub-api/'
$content | Set-Content public/skillhub/index.html -Encoding utf8
```

替换完打开 HTML 搜一下 `fetch(` `axios.` `XMLHttpRequest` `url:`，确认没有遗漏。

---

## 七、最终改动清单

| 位置 | 改动 | 工作量 |
|---|---|---|
| `dify-cmbc/web/public/skillhub/index.html` | 复制文件过来 + 改 API URL | 5 分钟 |
| `dify-cmbc/web/next.config.js` | 加 `rewrites()` | 5 行代码 |
| 主系统 nginx 配置 | 加两条 `location` | 10 行配置 |
| `dify-cmbc/web/Dockerfile` | 确认 `public/` 进镜像 | 看现状 |
| 后端 CORS | 仅在跨域调用时加 | 5 行（可选） |
| HTML 内 fetch URL | 批量替换 | 1 个 sed 命令 |

**零 React 代码**。