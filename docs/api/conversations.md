# Conversations（会话）

> 路由前缀: `/py/api/conversations`  
> 源码: `backend/app/routes/conversations.py`

## 接口列表

- [POST /](#post) — 创建新会话
- [POST /{conversation_id}/files](#post-conversation_idfiles) — 向已有会话追加文件
- [GET /](#get) — 获取会话列表
- [DELETE /{conversation_id}](#delete-conversation_id) — 删除会话
- [GET /{conversation_id}/files/tree](#get-conversation_idfilestree) — 获取文件树

---

## POST /

创建新会话。会话创建后可选择上传文件，后续对话通过 `POST /chat/stream` 进行。

### Request

```
POST /py/api/conversations
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | `file[]` | 否 | 上传的文件列表（可选） |

### Response `200 OK`

```json
{
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "thread_id": "user-550e8400-e29b-41d4-a716-446655440000",
  "files": [
    {
      "filename": "data.csv",
      "size": 1024,
      "path": "/mnt/user-data/uploads/data.csv",
      "extension": ".csv"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | `string` (UUID) | 会话 ID，后续对话必须携带 |
| `thread_id` | `string` | Agent 线程 ID，格式 `user-{conversation_id}` |
| `files` | `object[]` | 已保存的文件元数据 |
| `files[].filename` | `string` | 文件名 |
| `files[].size` | `number` | 文件大小（字节） |
| `files[].path` | `string` | 沙箱中的虚拟路径 |
| `files[].extension` | `string` | 文件扩展名（含 `.`） |

---

## POST /{conversation_id}/files

向已有会话追加文件。

### Request

```
POST /py/api/conversations/{conversation_id}/files
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | `file[]` | ✅ | 上传的文件列表 |

### Response `200 OK`

```json
{
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "files": [
    {
      "filename": "report.pdf",
      "size": 2048,
      "path": "/mnt/user-data/uploads/report.pdf",
      "extension": ".pdf"
    }
  ]
}
```

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 404 | 会话不存在 |
| 403 | 无权访问该会话 |

---

## GET /

获取当前用户的所有会话列表，按最近活动时间倒序排列。

### Request

```
GET /py/api/conversations
Authorization: Bearer <token>
```

### Response `200 OK`

```json
{
  "conversations": [
    {
      "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
      "thread_id": "user-550e8400-e29b-41d4-a716-446655440000",
      "title": "帮我分析这个 CSV 文件",
      "status": "completed",
      "total_tokens": 15000,
      "cache_read": 2000,
      "cache_creation": 500,
      "created_at": "2026-08-12T10:30:00",
      "updated_at": "2026-08-12T10:35:00"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | `string` (UUID) | 会话 ID |
| `thread_id` | `string` | Agent 线程 ID |
| `title` | `string \| null` | 会话标题（取首条消息截断） |
| `status` | `string` | 状态: `pending` / `running` / `completed` / `cancelled` / `error` |
| `total_tokens` | `number` | 总 token 用量 |
| `cache_read` | `number` | 缓存读取的 token 数 |
| `cache_creation` | `number` | 缓存创建的 token 数 |
| `created_at` | `string \| null` | 创建时间 (ISO 8601) |
| `updated_at` | `string \| null` | 最后更新时间 (ISO 8601) |

---

## DELETE /{conversation_id}

删除指定会话及其所有关联数据。

### 级联删除内容

1. `messages` 表中的所有消息
2. `runs` 表中的运行记录
3. 沙箱容器（如有）
4. 远程存储文件（S3 / MinIO）
5. 本地线程目录（workspace / outputs / uploads）
6. 状态日志文件

### Request

```
DELETE /py/api/conversations/{conversation_id}
Authorization: Bearer <token>
```

### Response `200 OK`

```json
{
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "deleted": true
}
```

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 404 | 会话不存在 |
| 403 | 无权访问该会话 |

---

## GET /{conversation_id}/files/tree

获取会话的文件树，包含 `outputs`、`workspace`、`uploads` 三个根节点。

### Request

```
GET /py/api/conversations/{conversation_id}/files/tree
Authorization: Bearer <token>
```

### Response `200 OK`

```json
{
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "roots": [
    {
      "name": "outputs",
      "label": "输出文件",
      "type": "directory",
      "virtual_path": "/mnt/user-data/outputs",
      "children": [
        {
          "name": "report.pptx",
          "type": "file",
          "virtual_path": "/mnt/user-data/outputs/report.pptx",
          "size": 123456,
          "extension": ".pptx",
          "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          "previewable": true
        }
      ]
    },
    {
      "name": "workspace",
      "label": "工作区",
      "type": "directory",
      "virtual_path": "/mnt/user-data/workspace",
      "children": []
    },
    {
      "name": "uploads",
      "label": "上传文件",
      "type": "directory",
      "virtual_path": "/mnt/user-data/uploads",
      "children": [
        {
          "name": "data.csv",
          "type": "file",
          "virtual_path": "/mnt/user-data/uploads/data.csv",
          "size": 1024,
          "extension": ".csv",
          "content_type": "text/csv",
          "previewable": true
        }
      ]
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | `string` | 会话 ID |
| `roots` | `FileTreeRoot[]` | 三个根节点列表 |
| `roots[].name` | `string` | 目录英文名（`outputs` / `workspace` / `uploads`） |
| `roots[].label` | `string` | 目录中文标签 |
| `roots[].type` | `string` | 固定为 `"directory"` |
| `roots[].virtual_path` | `string` | 虚拟路径 |
| `roots[].children` | `FileTreeNode[]` | 子节点（递归结构） |

#### FileTreeNode（文件）

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `string` | 文件/目录名 |
| `type` | `string` | `"file"` 或 `"directory"` |
| `virtual_path` | `string` | 虚拟路径 |
| `children` | `FileTreeNode[] \| null` | 仅目录有，递归子节点 |
| `size` | `number \| null` | 文件大小（字节），仅文件 |
| `extension` | `string \| null` | 文件扩展名，仅文件 |
| `content_type` | `string \| null` | MIME 类型，仅文件 |
| `previewable` | `boolean` | 前端是否可预览，仅文件 |

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 404 | 会话不存在 |
| 403 | 无权访问该会话 |
