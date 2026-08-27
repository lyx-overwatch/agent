# SkillHub → dify-cmbc/web 迁移进度

> 每次会话结束前更新本文件：勾选完成项、补充新发现的差异点、记录下一步。
> 对齐基线见 [README.md](README.md)。

## 状态总览

- 开始日期：2026-08-19
- 当前阶段：**U3 对接 API**（✅ 完成：核心对话 + 文件 + 状态轮询）
- 已完成 / 总数：4 / 4（U0、U1、U2、U3）

---

## 开发流程（D5）

**UI 稿 → 页面 → mock 数据 → 对接 API**

| 阶段 | 状态 |
|---|---|
| U0 UI 设计稿 | ✅ 完成（改写了 `public/phase1/pages/task-detail.html`） |
| U1 页面 | ✅ 完成（React 组件写入 `web/app/agc-agent/`） |
| U2 mock 数据 | ✅ 完成（mock 流式状态机跑通） |
| U3 对接 API | ✅ 完成（核心对话 + 文件 + 状态轮询） |

---

## U0 — UI 设计稿 ✅

- [x] 产出可交付设计稿（留存 + AI 参考标准），规范见 README §10
- [x] 覆盖 README §5 全部功能 + 各交互/异常态
- [x] 视觉对齐 phase1 现有原型风格（Tailwind CDN + Lucide + antd 4.24，蓝色 #2563eb）

> **落盘**：改写 `public/phase1/pages/task-detail.html`（不是新建 docs/design）。与 phase1 其余页面同目录、同风格。三页（`chat.html` / `market.html` / `task-detail.html`）均已定稿，细节见「本轮定稿」。
> **页面映射**：`chat.html` = 默认欢迎页（无「新对话」，保持原样）；`task-detail.html` = 会话详情页（承载完整 Agent 设计稿）。
> **侧边栏统一**：以 task-detail 为准（Logo + 导航 + 会话列表），**去掉「新对话」按钮**；chat.html / market.html / my-skills.html 的侧边栏已统一为此结构（仅导航 active 项随页面变化，会话项跳转到 task-detail.html）。
> - 会话列表项：单行紧凑（状态点颜色 + 标题 + hover 删除 icon），**不展示 token/缓存/状态文字**，用状态点颜色标识状态。
> - 顶部「SkillHub」去 icon，仅文字；右侧加抽屉 icon（`panel-left-close`），点击收起侧边栏（桌面端隐藏、顶部出现展开栏）。
> - 导航「对话/技能」换 icon（`message-circle` / `sparkles`）；**active 不用蓝色，改为灰色背景**（`bg-gray-100 text-gray-900`，与下方会话列表选中一致）。
> - 中间对话区：AI 消息**去掉 bot 头像**；思考卡**默认展开**、icon 换 `lightbulb`、文案固定「深度思考」；`gen-status` 宽度对齐输入框（`max-w-3xl mx-auto px-4`），消息列表 / 状态条 / 输入框三者宽度对齐。
> **覆盖的组件/状态**（详见 HTML 注释）：
> - 会话侧栏：状态点（pending/running/completed/cancelled/error）+ token/缓存 meta + hover 删除 + 空态
> - 顶部标题栏：回退箭头（→chat.html）+ 当前会话标题 + 状态点（保留）
> - 对话流：用户气泡（含附件 chip）、AI 气泡、思考卡（折叠）、工具卡（输入/输出/耗时/错误）、子代理卡（task 变体 + 耗时）、运行中工具卡（pending）、文件路径链接化
> - 生成状态条（常驻，文案由 progress phase 驱动）、错误卡、取消卡
> - 输入区：模型下拉（supports_thinking 区分）、深度思考开关、附件 chips、发送/停止切换
> - 文件树面板（outputs/workspace/uploads 三根目录 + 嵌套目录 + 下载/预览）、文件预览弹窗（图片/代码/文本/占位）
> - 调试面板**已完全去掉**（决策 D7）

### 本轮定稿（2026-08-19）

> 三页交互细节最终确认，U1 React 重写与 U3 对接以此为基准：

- **技能页 market.html 简化**：去掉「市场/我的」tab、「全部/系统内置」筛选 + 搜索行、页面标题；仅保留卡片列表。卡片去掉「添加/移除」操作，点击统一弹出「当前技能描述」弹窗（弹窗内无「添加到我的技能」）。
- **发送按钮禁用态**：初始禁用（灰底 + 白色 icon）；输入框有文字 **或** 有附件 chip 时才启用。
- **发送 → 停止切换**：发送后按钮变红色正方形（停止态）；**保持停止态直到用户点击停止**才回蓝色箭头（发送态），不自动还原。
- **「生成被中断」提示**：靠左显示（不居中）。
- **文件树空态**：无文件的会话显示空态（`暂无文件 / 该会话未生成任何文件`）；示例用 error 态「批量处理 50 张图片」。
- **侧边栏 header**：去掉 `border-b border-gray-100`；标题栏去掉 `conv-status completed` 状态点。

## U1 — 页面（按 UI 稿，纯 UI，不接 API）✅

- [x] 会话列表 / 对话主视图 / 模型思考控制 / 文件树 / 文件预览 / 输入区
- [x] 纯静态 React 页面

> **落盘**：`web/app/agc-agent/`（**顶层路由**，自带侧栏 layout、无全局 Header；`layout.tsx` + `page.tsx` 工作台 + `skills/page.tsx` + `[conversationId]/page.tsx` 详情页 + `components/` 15 个组件 + `types.ts` + `mock.ts` + `skillhub.module.scss`）。
> - 组件与 README §6.2 对齐：`ConversationSidebar` / `ModelSelector` / `ThinkingToggle` / `ChatView` / `MessageBubble` / `ThinkingCard` / `ToolCard` / `GenStatusBar` / `FileTreePanel` / `FilePreviewModal` / `InputArea`，另加支撑件 `AttachmentChip` / `PageHeader` / `skillhub-ui`(context) / `icons`(图标映射)。
> - Markdown 复用 `@/app/components/base/markdown`（react-markdown + remark-gfm + rehype-katex）；图标用 `lucide-react`（UI 图标，精确对齐设计稿 lucide 名）+ `@fortawesome/*`（文件类型彩色 fa-file-* 图标，按扩展名匹配），见 `components/icons.tsx`。
> - 目录/图标为二次对齐后的变更：目录从 `(commonLayout)/skillhub` 迁到顶层 `agc-agent`；图标从 `@heroicons/react` 近似换成 `lucide-react` + FontAwesome。
> - 交互态（纯 UI demo）：侧栏收起/移动抽屉、会话 hover 删除、思考/工具卡折叠、模型下拉、思考开关（locked 锁定）、附件 chips、发送↔停止切换、文件树折叠/全屏、文件预览（图片/代码/占位）、技能卡片→描述弹窗。
> - 校验：`tsc --noEmit` 无 skillhub 报错；`next lint` 因项目 `.eslintrc.json` 未配 TS parser，对所有 `.tsx`（含存量 `complex-chat` 等）报「import is reserved」解析错误——预置问题，非本次引入。

## 后端时序对齐（2026-08-20）

> 会话创建 / 标题生成 / 列表排序的时序问题，本轮在后端落定（改 `run_repo.py` / `chat_service.py` / `stream_event_handler.py` / `stream_result_persister.py` / `routes/chat.py`），U3 前端按此契约实现：

- **列表排序**：`GET /conversations` 按 `created_at` 倒序（首次创建时间）。**继续旧会话不置顶**，保持原位置。
- **会话创建时机（A方案）**：`POST /conversations` 在「发送第一条消息那一刻」调用（前端流程 `POST /conversations` → `POST /chat/stream`）；后端 API 契约不变。
- **标题流程**：发消息立即用「截断的用户消息」作占位标题 → 数秒内 AI 标题经 SSE `title_update` 事件替换（**使用第一个**选项）。
- **生成中状态**：回合开始后端写 `status="running"`，前端据此显示脉冲点（设计稿 `chat.html` + `ConversationSidebar.tsx` 已就绪）。
- **新增 SSE 事件** `title_update`：`{title: string}`，首个 assistant 回复后、回合结束前下发（best-effort，最终标题仍以回合结束 upsert 为准）。

## U2 — mock 数据 ✅

- [x] mock 会话列表 / 消息历史 / SSE 流式事件 / 文件树 / 模型列表
- [x] 交互与流式状态跑通（打字 / 思考 / 工具 / 状态条 / 停止）

> **落盘**：`web/app/agc-agent/lib/mockStream.ts`（三条场景脚本：正常完成 / 中途报错 / 子代理委派，按关键词匹配）+ `lib/chatReducer.ts`（sendStream 状态机翻译：交错段渲染 / run_id 匹配 / 状态条 label / detached 守卫）+ `components/skillhub-chat.tsx`（context provider 统一持有 会话/消息/流式状态）。
> - 完整新会话链路已通：工作台发消息 → mock 新建会话（标题先占位、后被 `title_update` 替换）→ 跳转详情页 → 流式；侧栏 running 脉冲点/删除/倒序联动。
> - 停止 = 本地取消后续事件并下发 `run_end(cancelled)`（模拟 `POST /chat/stream/stop`）；后台流靠 reducer `isCurrent` 守卫隔离。
> - `types.ts` 新增 `StreamEvent`（对齐 docs/api 事件枚举 + `title_update`）；`ToolCall` 增加 `error`。U3 只需替换 `startMockStream` 为真实 SSE 解析器，调用方接口不变。
> - 校验：`tsc --noEmit` 无 agc-agent 报错（项目其余文件仍有存量类型错误，与本次无关）。

## U3 — 对接 API（原 P0–P5 清单并入此处）

### 3.0 契约核实

- [x] 通读 `docs/api/*.md`（index/chat/conversations/auth/models/skills/health）
- [x] `/health` 前缀：根 `/health` 与 `/py/api/health` 均返回 `{"status":"ok"}`（canonical 在根，见 main.py）
- [x] `supports_thinking` 语义：`/py/api/models` 实测**同时返回** `supports_thinking` + `thinking_locked` + `supports_vision`（README §4.4「无 thinking_locked」已过时）
- [ ] 会话状态枚举：docs 为 `pending/running/completed/cancelled/error`；差异点记后端另有 `active`/`step_limit`，待拿真实数据核实
- [x] `chat/stream` 请求体 `multipart/form-data`：`message`/`conversation_id`/`thinking_enabled`/`model_name`/`file_metadatas`
- [x] 文件下载：优先 `/files/{id}/url`（返回 `{url, backend}` 自认证）；`/files/{id}` 走二进制代理

### 3.1 请求层

- [x] 新建 `pyNetwork.ts`：`pyGET / pyPOST / pyDELETE / pyUpload`（不解包 code/data/msg；dev 直连 8001，prod 相对路径）
- [x] 新建 `pyEventsourceFetch`：`/py/api` 前缀 + FormData body（chat/stream）
- [x] 新建 `api/skillhub.ts`：封装 §4.1 全部端点方法 + API 响应类型
- [x] 类型定义：领域类型在 `types.ts`（含 `StreamEvent`），API snake_case 类型在 `api/skillhub.ts`
- [x] 部门访问守卫：`layout.tsx` 挂 `useSkillhubGuard`，调 `queryVaildToken()`（`/java/api/vaildToken`）校验 `data.org` 含「数字金融发展办公室」，否则页内显示无权限占位
- [x] 接入 `auth/verify` 流程：`skillhub-chat` provider 启动调 `verify()`（复用 localStorage token）；401 → reLogin 由 `layout` 的 validToken 守卫经 Java `network` 拦截器间接覆盖，`verify` 自身失败静默降级（py 后端异常时 reLogin 无效）

> **联调环境（2026-08-20）**：走「直连 + CORS」——前端 dev 用 `http://localhost:8001`，后端 `.env` `CORS_ORIGINS` 已加 `http://localhost:3000`（**需重启后端生效**）。联调前置：前端 `localStorage.token` 需有 Java 主系统签发的有效 JWT；`auth/verify` 依赖 Redis 登录态（`REDIS_URL`）。文件走 S3/MinIO（`STORAGE_BACKEND=s3`，localhost:9000），U3.3 预览/下载按 `/files/{id}/url` 走。

### 3.2 核心对话

- [x] `ConversationSidebar`（列表 + 状态点 + token/缓存 + 删除 + 新建）
- [x] 会话列表状态轮询（`syncStatusPolling`/`pollStatus`：有 `running`/`active`/`title_pending` 时 2s 自停轮询 `GET /conversations`，全终态停表，网络错误静默忽略；挂在 provider 的 `refreshConversations` 后）
- [x] `ChatView` + `MessageBubble`（用户/助手）
- [x] `ThinkingCard`（reasoning 折叠）
- [x] `ToolCard`（含子代理变体 + 输入/输出/错误/耗时）
- [x] `GenStatusBar`（生成中/思考中/准备中，phase 驱动）
- [x] SSE 状态机翻译（`mapWireEvent` wire→StreamEvent + run_id 匹配 + detached 守卫）
- [x] `InputArea`（发送 + 停止生成）
- [x] 错误/取消/结束态渲染
- [x] 问题锚点快速定位（QuestionAnchor：≥3 条用户消息显示右侧窄条，hover 展开问题列表，点击滚动定位；对齐项目 aigc-main）

### 3.3 文件能力

- [x] 附件上传（多文件 chips）：文件选择 → 新会话 `POST /conversations` 带 files / 续会话 `POST /{id}/files` 追加 → `file_metadatas` 传 `chat/stream`
- [x] `FileTreePanel`（递归树 + 计数）：`GET /conversations/{id}/files/tree` → `mapFileTree`
- [x] `FilePreviewModal`（图片/文本/代码/PDF）：`GET /chat/files/{id}` 带 auth 抓取 → blob/文本/iframe
- [x] 文件下载（优先自认证 URL）：`GET /chat/files/{id}/url`，s3 直下 / local 带 auth 抓取
- [x] ~~消息内文件路径 linkify~~（去掉不做，2026-08-20 决策）

### 3.4 模型与思考控制

- [x] `ModelSelector`（读 `/py/api/models`，展示 `display_name`、值用 `name` 键）
- [x] `ThinkingToggle`（`supports_thinking`/`thinking_locked` 驱动）

### 3.5 收尾

- [x] 空态 / loading 态补齐（会话列表 / 技能页三态+重试 / 文件树 / 消息历史）
- [x] 错误统一提示（对齐项目 AlertError；用户操作失败 + 关键加载失败弹提示，轮询/verify/停止/文件预览保持静默）
- [x] 流式输出自动滚动（ChatView 换用项目 `ScrollArea` observe + lightScroll，替代 `skillhubScroll`；用户上滑时自动停跟）
- [x] i18n：不做（2026-08-21 决策，仅中文）
- [x] 移动端适配：跳过（2026-08-21 决策，不接 mobileLayout）
- [x] 调试面板：不保留（决策 D7，已完全去掉）
- [ ] 代码走 eslint 校验（项目有 husky 钩子）

## 断线续接增强（2026-08-21）

> 补齐「刷新 / 跨 layout 切走后」的断线续接体验。根因：正文/工具记录在回合**结束**才落库（回合开始只写 user 消息 + `running` 状态），而断线后本地无 SSE 流，详情页既不重连也不显示生成中状态。

- **自动补齐正文**：`[conversationId]/page.tsx` 用两个 ref 追踪「上一次 status + 是否在流式」，当轮询把状态从 `running/active/pending` 翻成 `completed/error/cancelled/step_limit` 时自动 `loadConversation` 重拉历史；`prevStreaming` 排除 SSE 正常结束（内存已完整，避免多余请求）。
- **断线生成中占位**：刷新后 `isStreaming=false` 但 `convStatus` 仍是 in-flight → 新增 `generatingOffline`，`GenStatusBar` 恢复可见（`visible = isStreaming || generatingOffline`），底部状态条显示「正在生成…」（不再在消息区重复加 spinner 占位）。

## UI 细节对齐（2026-08-21）

> 视觉/交互细节微调，纯前端改动、不涉及接口：

- **标题栏高度统一 48px**：文件树标题栏 `h-14` → `h-12`、侧栏 Logo 区 `h-14` → `h-12`，与移动端标题栏一致。
- **文件树标题区**：去掉 `border-b`；文件列表 padding 调小（`p-3` → `px-3 py-2`）；全屏按钮 `title` 由「退出全屏/全屏」→「收缩/展开」。
- **收起/展开 icon 颜色统一**：收起按钮 `PanelLeftClose` 由 `text-gray-500` → `text-gray-600`，与收起后 `PageHeader` 的 `PanelLeftOpen` 一致。
- **详情页输入框 placeholder**：`'输入消息... (Enter 发送, Shift+Enter 换行)'`。
- **文件树可拖拽分隔条**：左边界由静态 `border-l` 改为可拖拽分隔条（`cursor-col-resize`），hover / 拖动变蓝 `#0072ff`，左右拖动调宽（`240~720px`，默认 `288px`），全屏（`flex-1`）与折叠态隐藏。
- **用户消息气泡复制**：hover 气泡左侧浮现 `Copy` 图标，点击用 `copy-to-clipboard` 复制文本 + `messageApi.success('复制成功')`（对齐项目 `ChatQuestionItem`）；仅当有文本时显示。

---

## Phase 2 技能创作者生态 — UI 设计稿（2026-08-26）

> 独立于 phase1 迁移的 Phase 2 前端设计稿，落盘 `public/phase2/pages/market.html`（纯静态 HTML mock，无 API 调用）。
> 对应后端契约见 `docs/api/skills.md`、方案见 `docs/specs/phase2-skill-creator-ecosystem.md`。
> 技术栈同 phase1 设计稿：Tailwind CDN + Lucide + React UMD + antd 4.24，蓝色 `#2563eb`。

### 页面结构

- **4 个 tab（pill/segment 样式）**：`技能广场`（默认）/ `官方内置` / `我的技能` / `审核`（仅管理员，`currentRole !== 'admin'` 时隐藏）。
- 侧边栏沿用 phase1 统一结构（Logo + 导航 + 最近会话），仅「技能」导航 active。

### 本轮定稿（2026-08-26）

- **tab 样式**：选中 = 白字 + 黑底 + 黑 border；hover = 灰底；默认 = 黑字 + 白底 + 灰 border。`TAB_ON` / `TAB_OFF` 常量驱动 `switchTab()`。
- **卡片操作按钮统一为图标**（内联 SVG，`w-3.5 h-3.5`、无 border、`p-1.5 rounded-lg text-gray-400`，hover 变灰或变红）：添加/取消（plus↔x 切换）、发布（send）、删除（trash-2）、通过（check）、驳回（x）。
- **状态角标位置统一**：技能名第 1 行（`truncate`），meta 第 2 行放状态角标或「作者 · vX.X.X」。
- **上传入口默认隐藏**：以 icon（upload）表示，点击弹出**上传弹窗**（自定义 Tailwind 弹窗，含文件选择 + 展示名输入），上传保存为「草稿」。
- **两个 section 标题**：`我的创建`（含上传 icon）/ `我的添加`。
- **通用技能详情弹窗**：点击任意卡片弹出，展示**发布者 / 技能名 / 详细描述**；4 个 tab 全覆盖。实现：卡片 `data-author` + `data-desc` 挂在描述 `<p>` 上，事件委托监听 `.skill-card` 点击（`closest('button')` 排除操作按钮）；图标复用卡片头像字母与配色。
- **卡片间距**：`p-4`（原 `p-5` 过大），标题与 meta 间距 `mt-1`（原 `mt-0.5` 过紧）。

### 状态角标配色（Tailwind）

| 状态 | 类 |
|---|---|
| 草稿 draft | `bg-gray-100 text-gray-500` |
| 待审核 pending | `bg-amber-50 text-amber-600` |
| 已通过 approved | `bg-emerald-50 text-emerald-600` |
| 已拒绝 rejected | `bg-red-50 text-red-600` |
| 内置 builtin | `bg-blue-50 text-blue-600` |

### 待办

- 仍是纯静态 mock，未接 `/py/api/skills` 接口（upload / mine / marketplace / builtin / pending / review / add / publish）。
- 后续按 phase1 流程迁移到 `dify-cmbc/web` 时，以本稿为视觉标准。

---

## 新发现的差异点（持续补充）

> 实现过程中发现任何「debug-agent.html 假设 ≠ 正式 API」的地方，记录到 README §4.4 和这里。

| 日期 | 差异点 | 处理 |
|---|---|---|
| 2026-08-19 | 已记录 5 处（health/状态枚举/thinking_locked/stop/下载），见 README §4.4 | 待 U3.0 核实 |
| 2026-08-20 | 状态枚举：后端 `create`=`active`、回合中=`running`、结束=`completed`/`cancelled`/`error`/`step_limit`；README §4.4 与 `types.ts` 仅 `pending/running/completed/cancelled/error`（缺 `active`/`step_limit`） | 待 U3.0 核实并统一 |
| 2026-08-20 | 新增 SSE 事件 `title_update`（README §4.3 未列） | U3 前端处理 + README §4.3 补充 |
| 2026-08-20 | `/py/api/models` 实测同时返回 `supports_thinking` + `thinking_locked` + `supports_vision`（README §4.4「无 thinking_locked」已过时） | 前端 ModelSelector 按 `thinking_locked` 锁定 |
| 2026-08-20 | `/py/api/health` 也返回 `{"status":"ok"}`（根 `/health` 仍在） | 无影响，canonical 用根 `/health` |
| 2026-08-20 | `thread_id == conversation_id`（后端已去掉 `"user-"` 前缀，CLAUDE.md 描述过时） | 前端只用 conversation_id，无影响 |
| 2026-08-20 | SSE 为 OpenAI 兼容格式：`type` 顶层 + 负载 `choices[0].delta` + `finish_reason` `choices[0].finish_reason` | 前端 `mapWireEvent` 已按此解析 |
| 2026-08-20 | `tool_end` 不带 `elapsed_seconds`（子代理耗时仅 `subagent_progress` 携带） | 子代理耗时从 subagent_progress 取 |
| 2026-08-20 | `title_update` SSE 事件已从后端移除（标题改后台异步生成，见 `title_service.py`） | 前端标题改由 `GET /conversations` 轮询同步 |
| 2026-08-20 | `GET /conversations` 新增 `title_pending` 字段（AI 标题后台生成中标记） | 前端轮询条件加 `title_pending===true` |
| 2026-08-20 | debug-agent.html 有会话列表状态轮询（`syncStatusPolling`/`pollStatus`：有 `running`/`active` 时以 3s 间隔轮询 `GET /conversations`，全终态自停，瞬时网络错误静默忽略）；U2 未 mock（侧栏状态由客户端流事件直接驱动，无 reconcile 层） | 留到 U3 用真实 `GET /conversations` 实现 |
| 2026-08-21 | `/java/api/vaildToken`（项目已有 `queryVaildToken()`）返回 `data.org`（如 `"总行/数字金融发展办公室"`），用于部门鉴权；仅「数字金融发展办公室」可访问 agent 页面 | 已加 `layout.tsx` 访问守卫（`org.includes('数字金融发展办公室')`，不匹配页内显示无权限占位） |
