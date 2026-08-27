# SkillHub Agent 迁移至 dify-cmbc/web — 对齐基线文档

> **用途**：跨多次对话对齐迁移进度。每次开始工作前先读本文件 + [progress.md](progress.md)。
> **最后更新**：2026-08-19
> **状态**：已确认决策，未开始编码。

---

## 1. 背景与目标

把 `frontend/debug-agent.html`（SkillHub 的调试界面，3686 行原生 JS，功能已跑通）迁移进现有 Next.js 前端项目 `D:\registry\origin\dify-cmbc\web`，作为该前端的一个功能模块。

**核心定性**：不是「搬运 HTML」，而是**把 debug-agent.html 当成功能规格说明书，用 React + TypeScript 按 dify-cmbc/web 的约定重写**。debug-agent.html 的价值在于它的功能清单、SSE 事件状态机、以及各种边界态处理经验，代码本身（全局变量 / 命令式 DOM / innerHTML 拼字符串）不搬。

**开发工作流**（与日常前端一致，D5）：**先出 UI 设计稿 → 按稿写页面 → mock 数据 → 最后对接 API**。UI 设计稿承担两个角色：① 留存（领导预览页面长什么样、快速交付）② 后续 AI 实现的视觉参考标准。

### 涉及的两个代码库边界

| 路径 | 角色 | 本次是否改动 |
|---|---|---|
| `D:\registry\origin\skill-hub` | SkillHub 后端（FastAPI）+ 调试前端 + 文档 | 后端不改；只新增文档 |
| `D:\registry\origin\dify-cmbc\web` | 目标前端（Next.js 13 App Router） | ✅ 全部改动在此 |

---

## 2. 已确认决策（决策日志）

| 编号 | 决策 | 状态 | 日期 |
|---|---|---|---|
| D1 | ~~不做独立 UI 设计稿，直接把 debug-agent.html 迁进 Next.js~~ | ⛔ 已推翻（见 D5） | 2026-08-19 |
| D2 | 前端为 `/py/api` 单独写一套**不做 `code/data/msg` 解包**的请求层（方案 A） | ✅ 确认 | 2026-08-19 |
| D3 | 认证复用 Java 主系统同一个 JWT token，直接放 `Authorization: Bearer` | ✅ 确认 | 2026-08-19 |
| D4 | 接口前缀 `/py/api`（Java 侧是 `/java/api`），同主机 | ✅ 确认 | 2026-08-19 |
| D5 | **先出 UI 设计稿**（留存 + 作为 AI 实现参考标准），再按「UI 稿 → 页面 → mock 数据 → 对接 API」顺序开发 | ✅ 确认 | 2026-08-19 |
| D6 | UI 设计稿**落盘到 `public/phase1`，改写已有的 HTML 静态原型**（`pages/task-detail.html`），而非新建 docs/design | ✅ 确认 | 2026-08-19 |
| D7 | **调试面板（连接检测 / JWT 手动粘贴 / 快捷测试 prompt）完全去掉**，不在设计稿/页面中出现 | ✅ 确认 | 2026-08-19 |

> D5 的两个动机：① **留存**——让领导了解后续页面长什么样，可快速交付；② **参考标准**——让 AI 后续写页面时有依有据。D1 因 D5 而作废。
> D6 补充：设计稿与 phase1 其余页面同目录、同风格（Tailwind CDN + Lucide + antd 4.24、蓝色 #2563eb）。

### ⚠️ 已作废的旧方案

`docs/SkillHub-部署与前端集成方案.md` 曾提出：
- 「前端 = 独立 HTML 放 `public/skillhub/index.html`，零 React 代码」
- 「反代前缀 `/skillhub-api/`」

**这两条已作废**。当前实际部署是：同主机、`/py/api`（Python）与 `/java/api`（Java）两个前缀区分。本项目不再是「public 静态文件」，而是「React 组件集成」。该文档其余部分（SSE 反代需关 buffering、standalone 模式的 public 拷贝坑等）仍可参考，但涉及「静态 HTML / /skillhub-api」的部分以本文为准。

---

## 3. 已核实技术事实

### 3.1 部署拓扑与请求层现状

- 现有前端所有请求走 `utils-aigc-chat/network.tsx`：
  - `export const prefixURL = '/java/api'`（第 100 行，**全局单例硬编码**）
  - axios `baseURL` dev 环境 = `https://ftdream.oa.cmbchina.biz`
- 所以现状完整地址 = `https://<host>/java/api/...`；SkillHub = `https://<host>/py/api/...`（同主机、同 token）。

### 3.2 响应格式差异（D2 的根因）

`network.tsx` 的 `requestDecorator`（第 167–217 行）对**所有** REST 响应强制解包：

```js
const { code, msg, data } = res.data;
if (code === 200) resolve({ data, code, success: true });
else reject({ code, msg, data: null, success: false });
```

- Java 后端：统一 `{code, data, msg}`，`code===200` 表示成功。
- Python 后端：**裸 JSON**（无 `code/data/msg` 包裹）。

若 Python 接口走现有 `GET/POST`，`code` 取到 `undefined` → 直接 `reject`，**静默失败**（连错误提示都没有，因为 `msg` 也是 undefined）。因此必须新增一套 `pyGET/pyPOST/pyDELETE/pyUpload`，直接返回 `res.data` 原样。

### 3.3 SSE 路径（两边一致，可复用）

`utils-aigc-chat/ssePost.ts` 的 `eventsourceFetch` 已经：
- 用 `@microsoft/fetch-event-source`
- `onmessage` 里 `JSON.parse(event.data)` 后原样 `onData(parsedData, event.event)`，**不解包 code/data/msg**

所以 SSE 流式路径 Java/Python 行为一致，只需给 `eventsourceFetch` 增加一个「前缀参数」即可复用。**但注意**：Python 的 `chat/stream` 用 `multipart/form-data`（见 §4.1），而现有 `eventsourceFetch` 发的是 JSON，需要新写一个 FormData 版本。

### 3.4 认证（D3）

- `network.tsx` 的 `setApiToken()` 已从 `localStorage.getItem('token')` 读并挂 `Bearer`。
- `ssePost.ts` 的 `eventsourceFetch` 同样拼 `Authorization: Bearer ${token}`。
- Python 验的正是这个 HS512 JWT（`login_user_key` claim）。
- **额外要求**：调用任何业务接口前，必须先 `POST /py/api/auth/verify`（见 §4.2），完成校验 + 自动注册。

---

## 4. 接口契约（权威来源：`docs/api/`）

> 以下只是索引，**细节以 `docs/api/*.md` 为准**，不要靠 debug-agent.html 的假设。

### 4.1 完整端点清单

| 方法 | 路径 | 用途 | Content-Type | 备注 |
|---|---|---|---|---|
| POST | `/py/api/auth/verify` | 校验 token + 自动注册 | 无 body | 业务前必调 |
| POST | `/py/api/conversations` | 创建会话（可带文件） | `multipart/form-data` | 返回 `conversation_id` / `thread_id` / `files` |
| POST | `/py/api/conversations/{id}/files` | 追加文件 | `multipart/form-data` | `files: file[]` |
| GET | `/py/api/conversations` | 会话列表 | — | 按最近活动倒序 |
| DELETE | `/py/api/conversations/{id}` | 删除会话（级联） | — | 删消息/运行/沙箱/文件/日志 |
| GET | `/py/api/conversations/{id}/files/tree` | 文件树 | — | `roots`（outputs/workspace/uploads）递归结构 |
| POST | `/py/api/chat/stream` | SSE 流式对话 | `multipart/form-data` | 核心接口 |
| POST | `/py/api/chat/stream/stop` | 停止生成 | `multipart/form-data` | 传 `conversation_id` |
| GET | `/py/api/chat/messages/{id}` | 消息历史 | — | 结构化消息 |
| GET | `/py/api/chat/files/{id}` | 文件内容（预览/下载） | query `path` + `download` | 二进制，需带 auth header |
| GET | `/py/api/chat/files/{id}/url` | 自认证下载 URL | query `path` + `download` | Java 式下载，`<a>` 直接导航 |
| GET | `/py/api/chat/files/{id}/info` | 文件元数据（是否可预览） | query `path` | 返回 `previewable` |
| GET | `/py/api/models` | 模型列表 | — | 返回 `{models:[...]}` |
| GET | `/py/api/skills` | 技能列表 | — | 返回 `[{name, description}]` |
| GET | `/health` | 健康检查（无需认证） | — | ⚠️ 无 `/py/api` 前缀，见 §4.3 |

### 4.2 认证流程

```
1. 前端已从 Java 主系统拿到 JWT（localStorage.token）
2. POST /py/api/auth/verify  → 返回 { user_id, is_new_user }
3. 后续所有业务接口带同一 Authorization: Bearer <token>
```

### 4.3 SSE 事件类型（`docs/api/index.md`）

| 事件 | 说明 |
|---|---|
| `run_start` | 开始，含 `conversation_id` + `thread_id` |
| `thinking_start` / `thinking_end` | 深度思考起止 |
| `token` | 文本增量 |
| `reasoning` | 推理内容增量 |
| `tool_start` / `tool_end` | 工具调用（含 `tool` / `input` / `output` / `run_id`） |
| `sandbox_provisioning` | 首次 sandbox 工具时，容器准备中 |
| `progress` | 1s 心跳，`phase` ∈ `thinking`/`tool`/`provisioning`（仅 provisioning 带耗时） |
| `subagent_progress` | 子代理进度 |
| `error` | 错误 |
| `run_end` | 结束，`finish_reason` ∈ `stop`/`cancelled`/`error` |
| `[DONE]` | 流结束 |

**重要行为**（chat.md）：客户端断线**不**中断后端任务，只有 `POST /chat/stream/stop` 才会取消；取消后已生成内容仍保存。

### 4.4 ⚠️ debug-agent.html 与正式 API 的差异（迁移时必须对齐）

| 项 | debug-agent.html 假设 | 正式 API（docs/api） |
|---|---|---|
| 健康检查 | `GET /py/api/health`，读 `model`/`version` | `GET /health`，返回 `{status:"ok"}` |
| 会话状态枚举 | `completed`/`running`/`step_limit`/`error` | `pending`/`running`/`completed`/`cancelled`/`error`（**无 step_limit**） |
| 模型「锁定思考」 | `/models` 返回 `thinking_locked` | 返回 `supports_thinking`（布尔），无 `thinking_locked` 字段 |
| 停止生成 | 前端 AbortController 断流 | 需额外调 `POST /chat/stream/stop` |
| 文件下载 | 前端 fetch 二进制 | 有 `/files/{id}/url` 自认证 URL 更优（Java 式） |

---

## 5. debug-agent.html 功能对齐清单

> 状态：`复用` = 项目已有能力；`新建` = 需写 React 组件；`改造` = 复用但需适配。

### 5.1 会话管理

| debug 功能 | 迁移方式 | 依赖接口 |
|---|---|---|
| 会话列表（状态点 + token 计数 + 缓存命中率） | 新建 `ConversationSidebar` | `GET /conversations` |
| 新建会话 | 复用逻辑，重写 | `POST /conversations` |
| 删除会话（hover + 确认） | 新建 | `DELETE /conversations/{id}` |
| 切换会话加载历史 | 新建 | `GET /chat/messages/{id}` |

### 5.2 对话流

| debug 功能 | 迁移方式 | 依赖 |
|---|---|---|
| SSE 流式解析（run_start/token/reasoning/tool_* 等） | 改造 `eventsourceFetch`（加前缀 + FormData） | `POST /chat/stream` |
| Markdown 渲染 | **复用**（react-markdown + remark-gfm + katex 已装） | — |
| 思考过程折叠卡片 | 新建 `ThinkingCard` | `reasoning` 事件 |
| 工具卡片（输入/输出/错误/耗时） | 新建 `ToolCard` | `tool_start`/`tool_end` |
| 子代理卡片 | 新建（ToolCard 变体） | `tool_name==task` + `subagent_progress` |
| 「生成中/思考中/准备中」状态条 | 新建 `GenStatusBar` | `progress`（phase） |
| 停止生成 | 新建 | `POST /chat/stream/stop` |
| 错误/取消/结束态 | 新建 | `error`/`run_end` |
| 消息内文件路径 linkify | 新建（`linkifyFilePaths`） | 前端逻辑 |

### 5.3 模型与思考控制

| debug 功能 | 迁移方式 | 依赖 |
|---|---|---|
| 模型下拉 | **复用**项目模型体系 + 新建 `ModelSelector` | `GET /py/api/models` |
| 深度思考开关 | 新建 `ThinkingToggle` | `supports_thinking`（非 dify 的 `inferenceLocked`） |

> 注意：SkillHub 的模型（Claude/DeepSeek）与 dify 项目自身的模型体系（Kimi/豆包等）是**两套**。SkillHub 的「思考能力」应来自 `/py/api/models` 的 `supports_thinking`，**不要**复用 `constants/model-capabilities.ts` 里的 `isInferenceLocked`（那是 dify 自己模型的）。

### 5.4 文件能力

| debug 功能 | 迁移方式 | 依赖 |
|---|---|---|
| 附件上传（多文件 chips） | 新建（上传走 `multipart`） | `POST /conversations` 或 `/{id}/files` |
| 消息内上传文件 chips | 新建 | `file_metadatas` 字段 |
| 递归文件树 | 新建 `FileTreePanel` | `GET /conversations/{id}/files/tree` |
| 文件预览（图片/文本/代码/PDF） | 新建 `FilePreviewModal`（项目有 react-pdf/react-file-viewer 可复用） | `GET /chat/files/{id}` + `/info` |
| 文件下载 | 改造（优先用 `/files/{id}/url` 自认证 URL） | `GET /chat/files/{id}/url` |

### 5.5 调试面板（是否保留待定）

| debug 功能 | 迁移方式 |
|---|---|
| 连接检测（健康检查） | 可保留但改调 `GET /health` |
| JWT 手动粘贴 | **正式环境删除**（复用项目 token 自动挂载） |
| 快捷操作（测试 prompt） | 可保留为「调试面板」折叠项，或整体去掉 |

---

## 6. 迁移架构

### 6.1 请求层（新建）

新建 `utils-aigc-chat/pyNetwork.ts`（或 `service/` 下）：
- `pyPrefixURL = '/py/api'`
- `pyGET / pyPOST / pyDELETE / pyUpload`：复用现有 `_axios` 实例（token 已挂），但**响应不做 code/data/msg 解包**，直接 `resolve(res.data)`。
- `pyEventsourceFetch`：基于 `eventsourceFetch` 改造，支持 FormData body（因为 `chat/stream` 是 `multipart/form-data`）和 `/py/api` 前缀。

### 6.2 组件拆分（新建，放在 `app/agc-agent/` 下，顶层路由、自带侧栏布局）

```
app/agc-agent/
├── page.tsx                 # 入口，组合布局
├── components/
│   ├── ConversationSidebar.tsx   # 会话列表 + 状态点 + 删除 + 新建
│   ├── ModelSelector.tsx         # 模型下拉（读 /py/api/models）
│   ├── ThinkingToggle.tsx        # 深度思考开关（supports_thinking）
│   ├── ChatView.tsx              # 消息列表容器
│   ├── MessageBubble.tsx         # 用户/助手消息
│   ├── ThinkingCard.tsx          # 思考折叠卡
│   ├── ToolCard.tsx              # 工具卡（含子代理变体）
│   ├── GenStatusBar.tsx          # 生成中/思考中/准备中状态条
│   ├── FileTreePanel.tsx         # 右侧文件树
│   ├── FilePreviewModal.tsx      # 文件预览
│   └── InputArea.tsx             # 输入框 + 附件 + 发送/停止
├── api/skillhub.ts          # 接口方法封装（或并入项目 api/ 目录）
├── store/                   # 如需 Redux slice（可先组件内 state）
└── types.ts                 # SSE 事件 / 消息 / 文件树 类型定义
```

> 是否用 Redux 待定：先组件内 state + context，够用就不上 slice（项目其余 chat 用 Redux Toolkit，后续可对齐）。

### 6.3 认证接线

1. 进入 skillhub 页面时，先 `POST /py/api/auth/verify`（复用 localStorage token）。
2. 失败（401）→ 走项目现有 `reLogin`（`constants/login.ts`）。

### 6.4 SSE 流状态机（对齐 debug + 正式 API）

debug-agent.html 的 `sendStream`（第 2648 行起）是核心参考：文本段与工具卡**交错**渲染、`pendingCards` 按 `run_id` 匹配 `tool_start`/`tool_end`、`detached` 守卫防止被新会话覆盖、`genStatusEl` 状态条常驻。这套逻辑需翻译成 React 状态（`useReducer` 或 `useState` + ref）。

---

## 7. 分阶段计划（按 D5 新工作流调整）

开发顺序与日常前端一致：**UI 稿 → 页面 → mock 数据 → 对接 API**。

| 阶段 | 内容 | 产出 |
|---|---|---|
| **U0 UI 设计稿**（先行） | 可交付的设计稿，覆盖 §5 全部功能 + 各交互/异常态 | 独立 HTML 设计稿（留存 + 参考标准） |
| **U1 页面** | 按 UI 稿写 React 页面（纯 UI，不接 API） | 静态 React 页面 |
| **U2 mock 数据** | 用 mock 数据把交互/流式/状态跑通 | 可交互页面（mock 驱动） |
| **U3 对接 API** | 把 mock 换成真实接口 | 联调完成 |

> - **U0 阶段**：参照 §5 功能对齐清单 + debug-agent.html 保证功能不遗漏；UI 稿的视觉规范见 §10。
> - **U3 阶段**：才需要用到 §4 接口契约 + §6 请求层 + progress.md 里的 API 对接清单。
> - 原有的「P0 契约核实 / P1 请求层 / …」清单降级为 U3 阶段的子任务，仍保留在 [progress.md](progress.md)。

---

## 8. 开放问题 / 待核实

- [ ] **`/health` 前缀**：docs 说 `GET /health`（无 `/py/api`），但 debug 用 `/py/api/health`。以 docs 为准，实现前再向后端确认一次。
- [ ] **`supports_thinking` vs 思考锁定**：正式 API 只有 `supports_thinking`，没有「锁定不可关」概念。若确有某些模型强制开思考，需要后端补字段或前端约定。先按「`supports_thinking=false` 时隐藏开关」处理。
- [ ] **会话状态 `step_limit` 已不存在**：debug 的「步数超限」态在正式 API 里没有对应枚举，确认后端是否合并进了 `error` 或 `cancelled`。
- [ ] **Redux 是否需要**：先不引入，跑通后看复杂度。
- [x] **调试面板去留**：✅ 已决策——**完全去掉**（D7）。
- [ ] **i18n**：项目支持 zh-Hans/en，SkillHub 文案是否要双语。

---

## 9. 相关文档索引

| 文档 | 内容 |
|---|---|
| `docs/api/index.md` | 接口总览 + SSE 事件类型 |
| `docs/api/chat.md` | 对话/流式/文件接口详情 |
| `docs/api/conversations.md` | 会话/文件树接口详情 |
| `docs/api/auth.md` | 认证 verify 接口 |
| `docs/api/models.md` | 模型列表接口 |
| `docs/api/skills.md` | 技能列表接口 |
| `docs/api/health.md` | 健康检查 |
| `docs/SkillHub-部署与前端集成方案.md` | ⚠️ 部分作废（静态 HTML + /skillhub-api 方案） |
| `frontend/debug-agent.html` | 功能规格参考（非搬运对象） |
| `../dify-cmbc/web/CLAUDE.md` | 目标项目约定 |

---

## 10. UI 设计稿规范（U0 阶段参考）

> 给「UI 设计」新会话用的输入约定。目标：产出一套可交付设计稿，既留存（领导预览），也作为后续写页面的视觉标准。

### 10.1 输入来源

| 来源 | 说明 |
|---|---|
| `frontend/debug-agent.html` | 功能规格：全部功能、SSE 状态机、交互/异常态（§5 已列清单） |
| `public/phase1/pages/*` | 之前的 5 个原型页（浅色主题，Tailwind CDN + Lucide + antd 4.24） |
| `dify-cmbc/web` 自身 | 目标项目设计系统（Tailwind + antd 4.24），**UI 稿应与之对齐，而非另起炉灶** |

### 10.2 设计稿应覆盖

- 全部页面：会话列表、对话主视图、模型/思考控制、文件树、文件预览、输入区
- 关键交互态：流式生成中（token 打字）、思考中、工具执行中、sandbox 准备中、停止、错误、取消、空态、loading
- 工具卡 / 思考卡 / 子代理卡 / 状态条的视觉形态（参照 debug-agent.html 的 `createToolCard` / `genStatusEl`）

### 10.3 交付形式

- 独立 HTML 静态稿（可点击原型）。**落盘位置已定（D6）**：改写 `public/phase1/pages/task-detail.html`，与 phase1 其余原型同目录同风格。
- 页面映射（重要）：`chat.html` = 默认进入的欢迎页（无「新对话」按钮，保持原样）；`task-detail.html` = 会话详情页（承载完整 Agent 设计稿，含侧栏/对话流/文件树/预览）。
- 侧边栏统一：以 task-detail 为准（Logo + 导航 + 会话列表），**去掉「新对话」按钮**；chat.html / market.html / my-skills.html 侧边栏已统一（仅导航 active 随页面变化，会话项跳转 task-detail.html）。
- U0 已完成，覆盖 README §5 全部功能与各交互/异常态（详见 progress.md U0 节 + HTML 内注释）。
