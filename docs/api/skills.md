# Skills（技能）

> 路由前缀: `/py/api/skills`  
> 源码: `backend/app/routes/skills.py`、`backend/app/services/skill_service.py`  
> 认证: 所有接口需 `Authorization: Bearer <token>`

技能分为两类：

- **内置（官方）技能**：随镜像打包在容器文件系统 `skills/<name>/`，全员默认可用，只读。
- **自定义（用户创作）技能**：文件本体存 OBS（key 前缀 `skills/custom/<name>/`），
  走「上传 → 发布 → 审核 → 广场 → 添加」生命周期，单副本共享。

## 审核生命周期

```
draft ──发布──▶ pending ──通过(approve)──▶ approved ──添加──▶ 用户可用
  ▲                │
  │                └──驳回(reject, 必填原因)──▶ rejected ──重新提交──▶ pending
  └──────────────────────────────────────────────────┘
```

| 状态 | 含义 | 可操作 |
|------|------|--------|
| `draft` | 草稿（刚上传） | 作者可发布、可删除 |
| `pending` | 待审核 | 管理员可 `approve` / `reject` |
| `approved` | 已通过（进广场） | 任意用户可「添加」；作者可删除 |
| `rejected` | 已驳回（含 `review_note`） | 作者可重新提交、可删除 |

## 接口列表

- [POST /](#post-) — 上传 `.zip` 压缩包（→ draft）
- [GET /](#get-) — 内置技能列表（向后兼容别名）
- [GET /builtin](#get-builtin) — 官方内置区
- [GET /mine](#get-mine) — 我创建的技能（各状态）
- [GET /marketplace](#get-marketplace) — 技能广场（approved）
- [GET /available](#get-available) — 当前用户可用技能全量
- [GET /pending](#get-pending) — 待审核队列（仅管理员）
- [PUT /{name}](#put-name) — 更新展示名/描述（仅作者）
- [DELETE /{name}](#delete-name) — 删除技能（仅作者）
- [POST /{name}/publish](#post-namepublish) — 发布/重新提交（draft 或 rejected → pending）
- [POST /{name}/add](#post-nameadd) — 添加广场技能
- [DELETE /{name}/add](#delete-nameadd) — 取消添加
- [POST /{name}/review](#post-namereview) — 管理员审核

---

## POST /

上传一个技能，支持三种格式：`.zip` 归档、`.md` 单文件 Markdown，以及 `.skill`
（非标准格式，按内容嗅探：是 zip 则当归档解包，否则当 Markdown 处理）。归档走
「解包 + frontmatter 校验 + LLM 安全扫描」后逐文件上传到 OBS；`.md` 直接当作
`SKILL.md` 处理，若缺 frontmatter 则按文件名自动补 `name`。落库为 `draft`。

> ⚠️ 一个 zip 归档只能包含**一个**技能。若压缩包里打包了多个技能
> （含「外层目录套多个技能」的情况），会返回 400 并提示分别打包。

### Request

```
POST /py/api/skills
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | `file` | ✅ | `.zip` 归档、`.skill`（内容嗅探）或 `.md` 单文件 |
| `display_name` | `string` | 否 | 展示名，缺省用技能 `name` |

### Response `201 Created`

```json
{
  "skill_name": "my-excel-tool",
  "display_name": "我的 Excel 工具",
  "review_status": "draft"
}
```

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 400 | 非法文件 / 非 `.zip`/`.skill`/`.md` 后缀 / 非 UTF-8 / frontmatter 校验失败 / 打包了多个技能 |
| 409 | 同名技能已存在 |
| 422 | 安全扫描未通过 |

---

## GET /

内置技能列表，等价于 [`GET /builtin`](#get-builtin)（向后兼容旧前端）。

### Response `200 OK`

```json
[
  { "name": "file-processing", "description": "读取和处理 CSV、Excel 等数据文件…" },
  { "name": "web-search", "description": "联网搜索最新信息…" }
]
```

---

## GET /builtin

官方内置技能（只读列表）。

### Response `200 OK`

```json
[
  { "name": "file-processing", "description": "读取和处理 CSV、Excel 等数据文件…" }
]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `string` | 技能名（目录名） |
| `description` | `string` | 中文描述 |

---

## GET /mine

我创建的技能（各状态：draft / pending / approved / rejected）。

### Response `200 OK`

```json
{
  "skills": [
    {
      "name": "my-excel-tool",
      "display_name": "我的 Excel 工具",
      "description": "处理 Excel 数据…",
      "author_id": "user123",
      "author_name": "张三",
      "review_status": "rejected",
      "review_note": "描述过于简略，请补充使用说明",
      "reviewed_by": "admin001",
      "reviewed_at": "2026-08-25T16:00:00+00:00",
      "version": "1.0.0",
      "created_at": "2026-08-25T10:00:00",
      "added": false
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `string` | 技能名（全局唯一） |
| `display_name` | `string` | 展示名 |
| `description` | `string` | 描述（来自 SKILL.md frontmatter） |
| `author_id` | `string \| null` | 作者 user_id |
| `author_name` | `string \| null` | 作者显示名（上传时取 username，缺失回退 user_id） |
| `review_status` | `string` | `draft` / `pending` / `approved` / `rejected` |
| `review_note` | `string \| null` | 驳回原因（仅 `rejected` 时非空） |
| `reviewed_by` | `string \| null` | 审核人 user_id（仅 `approved` / `rejected` 时非空） |
| `reviewed_at` | `string \| null` | 审核时间 ISO 8601（仅 `approved` / `rejected` 时非空） |
| `version` | `string` | 版本（来自 frontmatter，缺省 `1.0.0`） |
| `created_at` | `string \| null` | 创建时间 (ISO 8601) |
| `added` | `boolean` | 是否已添加（此处恒为 `false`） |

---

## GET /marketplace

技能广场：所有 `approved` 的自定义技能，附带当前用户「是否已添加」。

### Response `200 OK`

```json
{
  "skills": [
    {
      "name": "my-excel-tool",
      "display_name": "我的 Excel 工具",
      "description": "处理 Excel 数据…",
      "author_id": "user123",
      "author_name": "张三",
      "review_status": "approved",
      "review_note": null,
      "reviewed_by": "admin001",
      "reviewed_at": "2026-08-25T16:00:00+00:00",
      "version": "1.0.0",
      "created_at": "2026-08-25T10:00:00",
      "added": true
    }
  ]
}
```

字段同 [`GET /mine`](#get-mine)，额外：`added` 为 `true` 表示当前用户已添加。

---

## GET /available

当前用户可用技能全量 = 内置（全部）+ 我创建的（任意状态）+ 我已添加的（approved）。
`origin` 标记来源，供前端「我的技能」页与 agent `list_skills` 复用。

### Response `200 OK`

```json
{
  "skills": [
    { "name": "file-processing", "display_name": "file-processing", "description": "…", "origin": "builtin", "review_status": null, "review_note": null, "version": null },
    { "name": "my-excel-tool", "display_name": "我的 Excel 工具", "description": "…", "origin": "mine", "review_status": "rejected", "review_note": "描述过于简略…", "version": "1.0.0" },
    { "name": "someone-elses-tool", "display_name": "别人的工具", "description": "…", "origin": "added", "review_status": "approved", "review_note": null, "version": "1.0.0" }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `string` | 技能名 |
| `display_name` | `string \| null` | 展示名 |
| `description` | `string` | 描述 |
| `origin` | `string` | `builtin` / `mine` / `added` |
| `review_status` | `string \| null` | 自定义技能才有 |
| `review_note` | `string \| null` | 驳回原因（仅 `origin=mine` 且 `rejected` 时非空） |
| `version` | `string \| null` | 自定义技能才有 |

---

## GET /pending

待审核技能队列（**仅管理员**，`users.role='admin'`）。

### Response `200 OK`

```json
{
  "skills": [
    {
      "name": "my-excel-tool",
      "display_name": "我的 Excel 工具",
      "description": "处理 Excel 数据…",
      "author_id": "user123",
      "author_name": "张三",
      "review_status": "pending",
      "review_note": null,
      "reviewed_by": null,
      "reviewed_at": null,
      "version": "1.0.0",
      "created_at": "2026-08-25T10:00:00",
      "added": false
    }
  ]
}
```

字段同 [`GET /mine`](#get-mine)。`review_note` / `reviewed_by` / `reviewed_at` 恒为 `null`（尚未审核）。

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 403 | 非管理员 |

---

## PUT /{name}

更新技能的展示名 / 描述（仅作者）。

### Request

```
PUT /py/api/skills/{name}
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{ "display_name": "新名字", "description": "新描述" }
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `display_name` | `string` | 否 | 展示名（≤200 字符） |
| `description` | `string` | 否 | 描述（≤1024 字符） |

### Response `200 OK`

```json
{ "skill_name": "my-excel-tool", "display_name": "新名字", "description": "新描述" }
```

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 404 | 技能不存在 |
| 403 | 非作者 |

---

## DELETE /{name}

删除技能（仅作者）。级联：删 OBS 对象 + 删 `skills` 记录 + 清所有 `user_skills` 引用。

### Response `200 OK`

```json
{ "skill_name": "my-excel-tool", "deleted": true }
```

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 404 | 技能不存在 |
| 403 | 非作者 |

---

## POST /{name}/publish

发布 / 重新提交技能（仅作者）：`draft` 或 `rejected → pending`，进入待审核队列。
重新提交时会清空旧的 `review_note` / `reviewed_by` / `reviewed_at`。

### Response `200 OK`

```json
{ "skill_name": "my-excel-tool", "review_status": "pending" }
```

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 404 | 技能不存在 |
| 403 | 非作者 |
| 409 | 当前状态非 `draft` / `rejected`（如已在 `pending` 或 `approved`） |

---

## POST /{name}/add

添加广场技能到当前用户（仅 `approved` 技能有效），写入 `user_skills`。

### Response `200 OK`

```json
{ "skill_name": "my-excel-tool", "added": true }
```

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 404 | 技能不存在 |
| 409 | 技能非 `approved` |

---

## DELETE /{name}/add

取消添加，删除 `user_skills` 记录（幂等）。

### Response `200 OK`

```json
{ "skill_name": "my-excel-tool", "added": false }
```

---

## POST /{name}/review

管理员审核（仅 `users.role='admin'`）：`pending → approved / rejected`。
`reject` 时**必须**填写 `reason`（存入 `review_note`，作者可见）；`approve` 时忽略 `reason`。

### Request

```
POST /py/api/skills/{name}/review
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{ "action": "reject", "reason": "描述过于简略，请补充使用说明" }
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | `string` | ✅ | `approve`（通过 → 进广场）或 `reject`（驳回） |
| `reason` | `string` | 否 | 驳回原因（`action=reject` 时必填，≤1000 字符） |

### Response `200 OK`

```json
{ "skill_name": "my-excel-tool", "review_status": "rejected", "review_note": "描述过于简略，请补充使用说明" }
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `skill_name` | `string` | 技能名 |
| `review_status` | `string` | 审核后状态：`approved` / `rejected` |
| `review_note` | `string \| null` | 驳回原因（`approve` 时为 `null`） |

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 403 | 非管理员 |
| 404 | 技能不存在 |
| 409 | 当前状态非 `pending` |
| 422 | `action=reject` 但未填写原因 |
