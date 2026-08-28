# Agent 项目初步改造：脱离 SkillHub / Java，自建用户体系

> 状态: **主体完成，Phase 2 待办** | 创建: 2026-08-27 | 更新: 2026-08-28

## 1. 背景与目标

`agent` 项目源自 **SkillHub**（多用户 AI Agent + Skill 执行平台）。SkillHub 为了对接外部的 **Java 主系统**，其认证链路完全依赖 Java 端：

- Java 系统签发 JWT（HMAC512 / HS512），claim 里带 `login_user_key`（= userId）；
- Python 端只验证 token，**不自行签发** token、不存密码；
- 登录态由 Redis 校验（`login_tokens:{user_id}` key 存在即视为已登录）。

`agent` 后续**不再对接 Java**，因此需要**自建一套用户体系**（注册 / 登录 / 签发 token / 鉴权），把「Java 签发 token + Redis 登录态」这条链路替换掉。

> 注：本项目现已正式定名 **Heyu Agent**（与 dify-cmbc 无关），可见品牌已全部替换。本节及下文的「SkillHub」仅作为「脱离对象」的历史语境保留。

本项目的改造分为两条线：

| 线 | 内容 | 状态 |
|---|---|---|
| 前端 | 脱离 dify-cmbc，独立 Next.js 项目 | ✅ 完成（含登录/注册页、品牌 Heyu Agent） |
| 后端 | 去除 Java 耦合，自建用户体系 | ✅ 完成（邮箱+密码注册/登录，纯 JWT，去 Redis） |

## 2. 现状：Java 耦合点清单（后端）

以下代码曾与「Java 签发 token + Redis 登录态」强耦合，是本轮改造的重点对象（现已全部解除）：

| 文件 | 耦合点 | 说明 |
|---|---|---|
| `backend/app/core/auth.py` | `check_is_authenticated()` | ~~校验 Java 签发的 JWT + Redis 登录态~~ → 改为纯 JWT 校验 + 自行签发 |
| `backend/app/core/dependencies.py` | `get_current_user()` | 所有业务接口的鉴权依赖，内部调用 `check_is_authenticated`；user 绑定到 agent_sdk ContextVar 的逻辑保持不变 |
| `backend/app/routes/auth.py` | `POST /auth/verify` | ~~前端首调入口~~ → 保留，并新增 `register` / `login` |
| `backend/app/models/database.py` | `User.id` | ~~直接等于 Java `login_user_key`，无密码字段~~ → 本地 `uuid4` + `hashed_password` |
| `backend/app/core/config.py` | `secret_key` / `algorithm=HS512` / `login_user_key` / `redis_url` | 鉴权相关配置；`secret_key` 仍为 HS512 签名密钥（兼容历史 Java token） |
| `backend/app/utils/rate_limit.py` | 引用 `app.core.auth.redis_client` | 会话创建限流已抽成 memory / redis 可切换抽象（`rate_limit_backend`，默认 memory）；Redis 仅在显式选择 redis 后端时用到 |

## 3. 前端改造（已完成）

### 3.1 已完成

- 在 `agent/web/` 下创建独立的 **Next.js 16.3.3** 项目（App Router + Turbopack + React 19 + Tailwind 4），使用 **pnpm** 管理。
- 源码来自 dify-cmbc 的 `agc-agent`，大部分直接粘贴，少部分引用原项目组件的文件一并拷贝（如 `ScrollArea`、`code-block`、`markdown`）。
- 去 dify 化：
  - 移除访问守卫（部门访问守卫 / `useSkillhubGuard` / `queryVaildToken` / `ALLOWED_ORG`）。
  - 移除所有 skillhub + Java 后端相关接口（`@/api/login`、`@/utils-aigc-chat/network`）。
- 后端连接通过 **Next rewrites 代理**：`/py/api/*` → `${BACKEND_URL}/py/api/*`（默认 `http://localhost:8001`，由 `.env` 的 `BACKEND_URL` 控制）。
- 修复了 React 19 / react-markdown v10 等升级带来的编译问题，`pnpm build` 已通过。

### 3.2 lib 源码（已补齐）

`web/app/agc-agent/lib/` 下原先 5 个占位 stub 已全部替换为真实实现：

| 文件 | 状态 |
|---|---|
| `chatReducer.ts` | ✅ 真实实现（流式事件 append / 分段逻辑） |
| `pyNetwork.ts` | ✅ 真实实现（`pyGET/pyPOST/pyDELETE/pyUpload/pyFetchBlob`） |
| `pyEventsourceFetch.ts` | ✅ 真实实现（SSE 流式） |
| `files.ts` | ✅ 真实实现（`downloadFile/openFileInBrowser/downloadDirectory`） |
| `skill.ts` | ✅ 已有（`hashColor/initialOf/badgeOf/formatAuthor/originMetaOf`） |
| `alert.ts` | ✅ 已有（基于 antd message） |

### 3.3 登录 / 注册页（根路由）

- 登录 / 注册页在根路由 `/`（`web/app/page.tsx`），单页内「登录 / 注册」切换。
- 成功后 `localStorage['token']` 存 token，跳 `/agc-agent`；`/agc-agent` 无 token 自动跳回 `/`。
- 样式沿用 ui-pages：浅色白卡片、`#0072ff` 主按钮、lucide-react 图标。

### 3.4 Markdown 样式

- `web/app/styles/markdown.scss` 从 dify-cmbc 原样搬入（GitHub 风格 `.markdown-body`），在 `web/app/layout.tsx` 全局引入，补齐对话正文排版。

## 4. 自建用户体系（已完成）

把「Java 签发 token + Redis 登录态」替换为 agent 自建的认证链路，已落地：

- **用户模型**：`users` 表重新引入 `hashed_password`（VARCHAR(200) 可空，兼容既有 Java 用户），`email` 加唯一索引（可空，兼容无邮箱的 Java 用户）。迁移 `3f5a8b2c1d9e_add_hashed_password_and_unique_email.py`（down_revision `9bab26aea54c`）。
- **注册 / 登录接口**：新增 `POST /auth/register`（201，重复邮箱→409）、`POST /auth/login`（凭证错→401，禁用→403）；保留 `POST /auth/verify`。
- **token 签发**：`app/core/auth.py` 改为「自行签发 + 验证」——`create_access_token(user_id)` 用 HS512 签发 `{login_user_key, iat, exp}`；`check_is_authenticated` 只验 JWT，去掉 Redis `login_tokens` 查询。
- **登录态存储**：**无状态 JWT**，废弃 Redis `login_tokens` 校验；`redis_client` 仅保留给 `rate_limit.py`。
- **`User.id` 来源**：本地生成 `uuid4`（不再等于 Java `login_user_key`）。
- **密码哈希**：bcrypt（`hash_password` / `verify_password`）。
- **配置**：新增 `access_token_expire_minutes`（默认 10080 = 7 天）。
- **分层落地**（四层架构）：`schemas/auth.py` → `repositories/user_repo.py` → `services/auth_service.py` → `routes/auth.py`。

> 注：chat / conversations 路由目前仍未挂 `get_current_user` 鉴权（见 §6 Phase 2）。

## 5. 品牌重命名：SkillHub → Heyu Agent

- 项目名确定为 **Heyu Agent**，可见品牌全部替换：页面标题 / metadata / 登录页 / 侧栏 logo / 后端 FastAPI `title` / **系统提示词**（`backend/app/core/agent.py`）/ Dockerfile / nginx.conf / CLAUDE.md 等 38+ 处。
- 后端系统提示词由 `You are 爱共创AIGC Agent` → `You are Heyu Agent`（此前还残留更早的「爱共创AIGC」品牌，已一并清理）。
- **内部代码标识符保持不变**（非品牌，不改）：`/agc-agent` 路由、`skillhubApi`、`SkillhubChatProvider`、`skillhub-sandbox-*` 容器名、`skillhub-files` bucket 等。
- 本文件（§1 背景）中的「SkillHub」保留，用于记录「脱离 SkillHub/Java」的历史语境。

## 6. 进度

| 序号 | 事项 | 状态 |
|---|---|---|
| 1 | 创建 `agent/web` 独立 Next.js 16 项目（pnpm） | ✅ 完成 |
| 2 | 拷贝 agc-agent 源文件 + 所需共享组件 | ✅ 完成 |
| 3 | 去 dify 化（移除守卫 + Java 登录 + skillhub 接口） | ✅ 完成 |
| 4 | 配置 rewrites / `.env` / 依赖 | ✅ 完成 |
| 5 | `pnpm build` 通过 | ✅ 完成 |
| 6 | 补齐 lib 占位文件的真实源码 | ✅ 完成 |
| 7 | 后端去除 Java 耦合、自建用户体系 | ✅ 完成 |
| 8 | 邮箱+密码注册/登录 + 纯 JWT（去 Redis） | ✅ 完成 |
| 9 | 登录/注册页（根路由 `/`）+ Markdown 样式 | ✅ 完成 |
| 10 | 品牌重命名 SkillHub → Heyu Agent | ✅ 完成 |
| 11 | Phase 2：chat 路由挂鉴权、`user_skills` 工具过滤、动态工具加载、skill 上传 API | ⏳ 未开始 |

## 7. 参考

- 前端项目: `agent/web/`
- 登录/注册页: `web/app/page.tsx`
- 认证链路: `backend/app/core/auth.py`、`backend/app/core/dependencies.py`、`backend/app/routes/auth.py`
- 认证服务/仓库/模型: `backend/app/services/auth_service.py`、`backend/app/repositories/user_repo.py`、`backend/app/schemas/auth.py`
- 用户模型: `backend/app/models/database.py`（`User`）
- 迁移: `backend/migrations/versions/3f5a8b2c1d9e_add_hashed_password_and_unique_email.py`
- 相关设计文档: [[multi-user-storage-design]]、[[user-api-keys-design]]
