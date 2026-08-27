# Agent 项目初步改造：脱离 SkillHub / Java，自建用户体系

> 状态: **进行中** | 创建: 2026-08-27

## 1. 背景与目标

`agent` 项目源自 **SkillHub**（多用户 AI Agent + Skill 执行平台）。SkillHub 为了对接外部的 **Java 主系统**，其认证链路完全依赖 Java 端：

- Java 系统签发 JWT（HMAC512 / HS512），claim 里带 `login_user_key`（= userId）；
- Python 端只验证 token，**不自行签发** token、不存密码；
- 登录态由 Redis 校验（`login_tokens:{user_id}` key 存在即视为已登录）。

`agent` 后续**不再对接 Java**，因此需要**自建一套用户体系**（注册 / 登录 / 签发 token / 鉴权），把「Java 签发 token + Redis 登录态」这条链路替换掉。

本项目的改造分为两条线：

| 线 | 内容 | 状态 |
|---|---|---|
| 前端 | 脱离 dify-cmbc，独立 Next.js 项目 | ✅ 构建已通过，待补 lib 源码 |
| 后端 | 去除 Java 耦合，自建用户体系 | ⏳ 未开始 |

## 2. 现状：Java 耦合点清单（后端）

以下代码与「Java 签发 token + Redis 登录态」强耦合，改造时是重点对象：

| 文件 | 耦合点 | 说明 |
|---|---|---|
| `backend/app/core/auth.py` | `check_is_authenticated()` | 校验 Java 签发的 JWT（HS512）+ Redis `login_tokens:{user_id}` 登录态 |
| `backend/app/core/dependencies.py` | `get_current_user()` | 所有业务接口的鉴权依赖，内部调用 `check_is_authenticated`；并把 user 绑定到 agent_sdk ContextVar |
| `backend/app/routes/auth.py` | `POST /auth/verify` | 前端首调入口：验 token + 自动注册用户 |
| `backend/app/models/database.py` | `User.id` | 直接等于 Java 的 `login_user_key`，无密码字段 |
| `backend/app/core/config.py` | `secret_key` / `algorithm=HS512` / `login_user_key` / `redis_url` | 鉴权相关配置，其中 `secret_key` 需与 Java 端一致 |
| `backend/app/utils/rate_limit.py` | 引用 `app.core.auth.redis_client` | 会话创建限流复用了 auth 模块的 redis 连接 |

## 3. 前端改造（已完成）

### 3.1 已完成

- 在 `agent/web/` 下创建独立的 **Next.js 16.3.3** 项目（App Router + Turbopack + React 19 + Tailwind 4），使用 **pnpm** 管理。
- 源码来自 dify-cmbc 的 `agc-agent`，大部分直接粘贴，少部分引用原项目组件的文件一并拷贝（如 `ScrollArea`、`code-block`、`markdown`）。
- 去 dify 化：
  - 移除访问守卫（部门访问守卫 / `useSkillhubGuard` / `queryVaildToken` / `ALLOWED_ORG`）。
  - 移除所有 skillhub + Java 后端相关接口（`@/api/login`、`@/utils-aigc-chat/network`）。
- 后端连接通过 **Next rewrites 代理**：`/api/*` → `${BACKEND_URL}/*`（默认 `http://localhost:8001`，由 `.env` 的 `BACKEND_URL` 控制）。
- 修复了 React 19 / react-markdown v10 等升级带来的编译问题，`pnpm build` 已通过。

### 3.2 待补：lib 源码

`web/app/agc-agent/lib/` 下 **5 个文件是占位 stub**，等待从原项目拿真实源码后替换：

| 文件 | 当前状态 |
|---|---|
| `chatReducer.ts` | stub：类型/骨架已就位，`STREAM_EVENT` 尚未实现 append 分段逻辑 |
| `pyNetwork.ts` | stub：`pyGET/pyPOST/pyDELETE/pyUpload/pyFetchBlob` 全部 reject |
| `pyEventsourceFetch.ts` | stub：SSE 流式接口未实现 |
| `files.ts` | stub：`downloadFile/openFileInBrowser/downloadDirectory` 全部抛错 |
| `skill.ts` | ✅ 已有可用实现（`hashColor/initialOf/badgeOf/formatAuthor/originMetaOf`） |
| `alert.ts` | ✅ 已有可用实现（基于 antd message） |

> 待办：从原项目拿回这 5 个文件的真实实现后逐个替换，再跑一遍 `pnpm build` 验证。

## 4. 自建用户体系（待设计）

目标：把「Java 签发 token + Redis 登录态」替换为 agent 自建的认证链路。需要决策并落地的事项：

- [ ] **用户模型**：`User` 表当前无密码列（`hashed_password` 已在早期迁移 `b9f3a1c72d08` 中删除）。自建体系需要重新引入凭据（密码 hash / 或对接其他 IdP）。
- [ ] **注册 / 登录接口**：新增 `POST /auth/register`、`POST /auth/login`（当前仅有 `POST /auth/verify` 验证逻辑）。
- [ ] **token 签发**：由「仅验证」改为「自行签发 + 验证」——重写 `app/core/auth.py`（当前注释明确写了「Python 端只做验证，不再自行签发 token」）。
- [ ] **登录态存储**：Redis `login_tokens:{user_id}` 是 Java 侧写入的。自建后要么由 Python 侧写入，要么改用无状态 JWT（需权衡 token 失效/登出能力）。
- [ ] **`User.id` 来源**：当前 `id = login_user_key` 由 Java 分配。自建后由本地生成（UUID 或自增）。
- [ ] **鉴权依赖改造**：`get_current_user` 与 `check_is_authenticated` 需同步改写，但 `set_current_user(ContextVar)` 的下游隔离逻辑应保持不变。
- [ ] **配置收敛**：`SECRET_KEY` / `ALGORITHM` / `LOGIN_USER_KEY` / `REDIS_URL` 的语义随自建方案调整。

## 5. 进度

| 序号 | 事项 | 状态 |
|---|---|---|
| 1 | 创建 `agent/web` 独立 Next.js 16 项目（pnpm） | ✅ 完成 |
| 2 | 拷贝 agc-agent 源文件 + 所需共享组件 | ✅ 完成 |
| 3 | 去 dify 化（移除守卫 + Java 登录 + skillhub 接口） | ✅ 完成 |
| 4 | 配置 rewrites / `.env` / 依赖 | ✅ 完成 |
| 5 | `pnpm build` 通过 | ✅ 完成 |
| 6 | 补齐 5 个 lib 占位文件的真实源码 | ⏳ 等待源码（预计 2026-08-28） |
| 7 | 后端去除 Java 耦合、自建用户体系 | ⏳ 未开始（见 §4） |

## 6. 参考

- 前端项目: `agent/web/`
- 认证链路: `backend/app/core/auth.py`、`backend/app/core/dependencies.py`、`backend/app/routes/auth.py`
- 用户模型: `backend/app/models/database.py`（`User`）
- 相关设计文档: [[multi-user-storage-design]]、[[user-api-keys-design]]
