# Phase 2 实现方案 —— 创作者生态（Skill 上传 / 发布 / 审核 / 技能广场）

> 状态：**已对齐，待实施**
> 关联：`docs/SkillHub-实现方案.md` §10 Phase 2「创作者生态」
> 决策日期：2026-08-24
> 修订（2026-08-25）：自定义技能存储由 DeerFlow 的本地 `skills/custom/` **改为 OBS 对象存储**（SkillHub 是云端 agent，用户数据不落容器本地磁盘）

---

## 1. 背景与目标

Phase 1（MVP）已完成基础对话、会话、文件、认证、内置 Skill 使用。Phase 2 让用户**上传并发布自己的 Skill**，经管理员审核后进入**技能广场**，其他用户可「添加」后使用。

### 1.1 目标

- 用户上传、管理自己的 Skill（草稿）
- 用户发布 Skill，管理员审核后展示在技能广场
- 技能广场展示所有用户审核通过的技能
- 用户可「添加」广场技能，添加后即可使用
- 内置技能默认全员可用，不可添加/删除，单独呈现「官方内置」区
- agent 执行时能感知**当前用户**的全部可用技能，且**不破坏系统提示词缓存**

---

## 2. 核心概念

### 2.1 Skill 生命周期

```
上传 → 草稿(draft) → 发布 → 待审核(pending) → 管理员审核 ──通过→ 已通过(approved) → 进技能广场
                                                 └─拒绝→ rejected（退回作者）
广场技能 → 其他用户「添加」 → 进入该用户可用技能集 → 可用
内置技能 → 所有用户默认可用，不可添加/删除，不进广场
```

### 2.2 「当前用户可用技能」解析

```
available(U) = 内置技能（全部，文件系统 skills/<name>/ 根级）
             + U 自己创建的（skills 表 author_id == U，任意 review_status）
             + U 已添加的（user_skills 表，且该 skill review_status == 'approved'）
```

### 2.3 内置 vs 自定义（存储区分）

> **定位：SkillHub 是云端 agent**，不是 DeerFlow 那种本地 agent。所有用户数据文件都存 OBS，
> 个人技能文件亦然。只有随镜像打包、全员共享的内置技能才留在容器文件系统。

| 类型 | 存储位置 | 可用性 | 可否增删 |
|---|---|---|---|
| 内置（官方） | 容器文件系统 `skills/<name>/`（随镜像打包，只读共享） | 全员默认可用，**静态进系统提示词** | 否 |
| 自定义（用户创作） | **OBS** 对象存储，key 前缀 `skills/custom/<name>/` | 作者本人 + 已添加的用户 | 是 |

> 内置技能是**部署产物**（随镜像分发、所有用户相同），放容器文件系统天然可缓存、读得快；
> 自定义技能是**用户数据**，必须进 OBS（容器重启/多副本不丢、可跨 pod 共享）。
> 因此 `skills/` 目录只放内置技能，自定义技能**从不落本地 `custom/` 目录**——二者按存储天然分开，无需 DB 标记「官方/自定义」。

> **OBS 文件无用户态、单副本共享**：技能文件在 OBS 里按技能名全局唯一存一份（key `skills/custom/<name>/...`），不随用户复制。
> 「谁拥有 / 谁能用」由 DB 决定——`skills.author_id` 记作者，`user_skills` 记「谁已添加」。
> 用户 B 添加技能 1 只是插一行 `user_skills`，**不复制文件**；作者删除技能 1 时才真正删 OBS 对象 + 清所有引用它的 `user_skills`。

---

## 3. 范围

### 3.1 本阶段做

| 项 | 说明 |
|---|---|
| Skill 上传 | 上传 `.skill` 压缩包 → 解包安装到 **OBS** → 落库为 `draft` |
| Skill 发布 | 作者 `draft → pending` |
| 管理员审核 | `pending → approved / rejected`（`users.role='admin'`） |
| 技能广场 | 展示所有 `approved` 的自定义技能（可添加） |
| 添加 / 取消添加 | `user_skills` 表读写 |
| 官方内置区 | 内置技能只读列表（不可添加/删除） |
| 我的 Skill | 我创建的（各状态）+ 我已添加的 |
| agent 感知 | 内置静态进提示词；个人技能走 `list_skills` 工具（见 §6） |
| 管理员识别 | `users` 表新增 `role` 字段 |

### 3.2 本阶段**不做**

| 项 | 说明 |
|---|---|
| 分类 / 标签 | 不建列、不做筛选；只做名称展示 |
| Skill 使用统计 | 不做 skill 维度 usage_count / token 统计（总 token 已由 `runs` 覆盖） |
| 评分 / 收藏 | Phase 3（`skill_ratings` / `user_favorite_skills`） |
| `.skill` 打包（表单生成） | 前端直接上传现成 `.skill`，不做表单打包 |
| 版本管理 / 变更日志 | `version` 字段保留但无多版本流程 |
| 全局下架 | `approved` 之后的下架操作留后续 |

---

## 4. 决策记录（2026-08-24 已确认）

| # | 问题 | 决定 |
|---|---|---|
| 1 | 管理员识别 | `users` 表加 `role` 字段（默认 `user`，管理员 `admin`） |
| 2 | Skill 创建入口 | 上传 `.skill` 压缩包（不做表单生成） |
| 3 | 前端落盘 | 先 `frontend/debug-agent.html` 验证，迁移另议 |
| 4 | 使用统计 | 本阶段不做 skill 维度统计 |
| 5 | 元数据展示 | 只做名称展示，无 category / tags |
| 6 | 内置 vs 广场 | **区分**：内置单独「官方内置」区，不进广场 |
| 7 | agent 可用技能感知 | **混合**：内置静态进提示词 + 个人技能走 `list_skills` 工具 |
| 8 | 自定义技能存储位置 | **OBS**（非 DeerFlow 的本地 `skills/custom/`）。云端 agent 定位，用户数据不落容器本地磁盘 |

---

## 5. 数据模型

### 5.1 `skills` 表（新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str (uuid, pk) | 主键 |
| `name` | str (unique) | 与 SKILL.md frontmatter 一致，= 安装目录名 |
| `display_name` | str | 名称展示，上传不传则默认 = `name` |
| `description` | str | 来自 SKILL.md frontmatter |
| `author_id` | str (FK users.id) | 创建者 |
| `author_name` | str \| null | 作者显示名（本阶段可空） |
| `review_status` | str (default 'draft') | `draft` / `pending` / `approved` / `rejected` |
| `version` | str (default '1.0.0') | 版本（暂存） |
| `storage_key` | str | OBS 对象 key 前缀 `skills/custom/<name>`（指向该技能文件在 OBS 的存放处） |
| `created_at` / `updated_at` | datetime | 时间戳 |

> 本阶段**不建** `category` / `tags` / `is_public` / `is_enabled` / `is_official` / 统计列。内置技能不落 `skills` 表（由文件系统根级位置区分）。

### 5.2 `user_skills` 表（**已存在，直接复用**）

`user_id + skill_name + enabled` —— 表示「用户已添加（启用）了某个技能」。

- 「添加」= 插入一行（`enabled=true`）
- 「取消添加」= 删除该行（或置 `enabled=false`）

### 5.3 `users` 表（改）

- 新增 `role: str = Field(default="user", max_length=20)`。
- 迁移：`ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'`。
- 管理员由运维手动置为 `admin`，本阶段不提供自助提权接口。

---

## 6. 系统提示词与 agent 感知（关键设计）

### 6.1 不变式

**系统提示词必须对所有用户字节级一致。** 原因：`agent.py` 里的 system prompt 被 DeepSeek Disk Cache 缓存，一旦改变（哪怕按用户动态注入技能清单），所有用户的首次请求全部冷启动（~5K tokens 全价）。

因此「当前用户可用技能」**不能进系统提示词**，只能走运行时工具。

### 6.2 拆分方案（决策 #7 混合）

| 内容 | 机制 | 是否破坏缓存 |
|---|---|---|
| 内置技能清单（`<available_skills>`） | **静态进系统提示词**（所有用户相同） | 否 |
| 技能使用通用指引（read_skill 是唯一读技能工具等） | 静态进系统提示词 | 否 |
| 用户个人技能（自己 + 已添加） | `list_skills` 工具**运行时返回** | 否 |

### 6.3 工具改动

1. **`list_skills`（新增工具）**：运行时按 ContextVar 里的当前用户 → 查 `skills` + `user_skills` → 返回该用户个人可用技能（自己的 + 已添加且 approved）。系统提示词引导模型在需要时调用它。
2. **`read_skill`（增强）**：加载前校验目标 skill 是否在「当前用户可用集」内（内置 或 自己 或 已添加且 approved），不在则拒绝。

### 6.4 实现机制（保持 agent_sdk 可移植）

- agent_sdk 的 `read_skill` / `list_skills` 不直接依赖 DB / OBS，而是接受 **app 层注入的异步回调**：
  - `available_skills(user_id) -> set[str]`（或 `is_available(user_id, name) -> bool`）：判断某技能是否在当前用户可用集。
  - `fetch_skill_files(name) -> list[tuple[rel_path, bytes]]`（或注入 `StorageBackend` 接口）：拉取自定义技能的全部文件（`list_objects` + `download_bytes`）。
- **自定义技能按需整包落地到 sandbox**：首次 `read_skill(name)` 命中自定义技能时，SDK 用上面的回调一次性拉取整技能文件，复用现有 `_inject_skill_files` 注入到 sandbox 工作区 `.skills/<name>/`；之后同一会话内的读取命中 sandbox 本地副本，不再逐文件打 OBS。
- **内置技能仍直接从容器文件系统读**（快、不进 OBS、不注入）。只有自定义技能（不在内置集内）才走 OBS 拉取 + 注入。
- app 层实现：ContextVar 取 user → async DB 查 `skills` / `user_skills`；文件读取走 `StorageBackend`。
- 未注入回调时（SDK 独立使用），回退到「全部可用 + 全从文件系统读」的现有行为。

### 6.5 内置清单来源

内置技能随镜像打包在 `skills/<name>/`（根级）；自定义技能存 OBS、**不落本地磁盘**。
因此 `SkillsMiddleware` 直接列 `skills/` 目录即可天然只含内置技能（无需再按 `custom/` 前缀过滤——自定义技能根本不在本地）。
此清单对所有用户相同，静态可缓存；自定义技能不进系统提示词，运行时走 `list_skills` 工具。

---

## 7. API 设计

> 前缀 `/py/api/skills`，认证同其它接口（`get_current_user`）。
> 沿用 4 层架构：routes 解析参数 → service 编排 → repo 纯 CRUD。

### 7.1 Skill 管理（作者）

**`POST /skills`** — 上传 `.skill` → 解包安装到 OBS → `draft`
- `multipart/form-data`：`file`(.skill 必填) + `display_name`(可选)
- 流程：后缀校验 → 临时目录解包 + 校验 frontmatter + 安全扫描（复用 `agent_sdk.skills.installer` 的 ZIP 安全/校验原语）→ **逐文件上传到 OBS**（key `skills/custom/<name>/<rel_path>`，走 `StorageBackend.upload`）→ 读 SKILL.md 拿 description/version → 写 `skills` 表（`author_id=当前用户`，`review_status='draft'`）
- 201 返回：`{skill_name, display_name, review_status: "draft"}`
- 错误：400（非法文件/frontmatter）、409（同名已存在）、422（安全扫描不过）

**`GET /skills/mine`** — 我创建的 Skill（各状态）

**`PUT /skills/{name}`** — 更新（仅作者）：`display_name` / `description`
- 仅 `author_id == 当前用户`，否则 403

**`DELETE /skills/{name}`** — 删除（仅作者）
- 删 OBS 对象（`StorageBackend.delete_prefix("skills/custom/<name>")`）+ 删 `skills` 表记录 + 清相关 `user_skills`

**`POST /skills/{name}/publish`** — 发布（仅作者）：`draft → pending`

### 7.2 技能广场（所有用户）

**`GET /skills/builtin`** — 官方内置区（只读列表，name + description）

**`GET /skills/marketplace`** — 广场：所有 `review_status='approved'` 的自定义技能（name + display_name + description + author_name + 是否已添加）

**`POST /skills/{name}/add`** — 添加：写 `user_skills`（仅对 `approved` 技能有效）

**`DELETE /skills/{name}/add`** — 取消添加：删 `user_skills`

**`GET /skills/available`** — 当前用户可用技能全量（内置 + 我的 + 已添加，含 `origin` 字段标记来源），供前端「我的技能」页与 agent `list_skills` 复用

### 7.3 管理员

**`POST /skills/{name}/review`** — 审核（仅 `role='admin'`）
- body：`{"action": "approve" | "reject"}`
- `approve → approved`（进入广场）；`reject → rejected`（退回作者）

> ⚠️ 路由注册顺序：`/mine`、`/builtin`、`/marketplace`、`/available` 等**静态段必须注册在 `/{name}` 之前**，避免被当成 `{name}` 捕获。

---

## 8. 前端（`frontend/debug-agent.html`）

新增两个视图：

1. **「我的技能」**：三段——官方内置（锁定只读）/ 我创建的（各状态角标 + 发布/删除）/ 我已添加的（取消添加）。
2. **「技能广场」**：展示已审核技能 + 「添加/已添加」按钮；上传表单（`.skill` + `display_name`）→ 草稿 → 发布。

- 仅名称展示，无分类/标签。
- 管理员审核入口本阶段留 API（界面后续补）。

---

## 9. 实施步骤（PR 拆分）

### PR1 — DB 层
- [ ] 迁移：`skills` 表 + `users.role`
- [ ] `app/models/database.py`：新增 `Skill`；`User` 加 `role`
- [ ] `app/repositories/skill_repo.py`：`create / get_by_name / list_by_author / update / delete / list_approved / list_added_by_user`

### PR2 — 技能管理 + 广场 API
- [ ] `app/schemas/skill.py`：请求/响应模型
- [ ] `app/services/skill_service.py`：上传（解包→OBS）+ 发布 + 审核 + 添加 + 权限判断
- [ ] `app/routes/skills.py`：§7 全部端点（注意静态段路由顺序）
- [ ] 更新 `docs/api/skills.md`

### PR3 — agent 感知接线
- [ ] 内置技能随镜像留在 `skills/` 根级（自定义技能不落本地，`SkillsMiddleware` 天然只列内置）
- [ ] 新增 `list_skills` 工具（DB 查个人可用技能名/描述）+ `read_skill` 接入 per-user 可用性回调
- [ ] `read_skill` 分路读取：内置→文件系统；自定义→OBS 整包下载到 sandbox 工作区（复用 `_inject_skill_files`）
- [ ] app 层实现 `available_skills(user_id)` 回调 + `fetch_skill_files` 存储读取（ContextVar + async DB/OBS）
- [ ] 验证：未添加 → `read_skill` 拒绝；添加 → 立即可用（热生效，无需重启）

### PR4 — 前端验证
- [ ] `frontend/debug-agent.html`：「我的技能」+「技能广场」视图
- [ ] 联调：上传 → 发布 → 审核 → 广场出现 → 他人添加 → 对话中 `list_skills`/`read_skill` 可用

---

## 10. 待办 / 后续阶段

- **管理员如何被设为 `admin`**：本阶段手动置位，后续可 Java 侧同步角色或加管理接口。
- **`.skill` 打包工具**：后续让 `skill-creator` 技能直接产出 `.skill` 包，闭环上传。
- **作者草稿是否对自己可用**：默认可用（便于自测），待联调确认。
- **分类 / 标签 / 评分 / 收藏**：Phase 3。
- **skill 使用统计 / 计费**：Phase 4（模型积分消耗另行设计）。
- **全局下架 / 撤回**：`approved` 后的下架、作者撤回发布，后续加。
