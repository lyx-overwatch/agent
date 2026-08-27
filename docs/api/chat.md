# Chat（对话）

> 路由前缀: `/py/api/chat`  
> 源码: `backend/app/routes/chat.py`

## 接口列表

- [POST /stream](#post-stream) — SSE 流式对话
- [POST /stream/stop](#post-streamstop) — 停止流式生成
- [GET /messages/{conversation_id}](#get-messagesconversation_id) — 获取消息历史
- [GET /files/{conversation_id}](#get-filesconversation_id) — 获取对话文件
- [GET /files/{conversation_id}/info](#get-filesconversation_idinfo) — 获取文件元数据

---

## POST /stream

SSE 流式对话接口，实时推送 token、工具调用和思考过程。

### Request

```
POST /py/api/chat/stream
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | `string` | ✅ | 用户输入文本 |
| `conversation_id` | `string` | ✅ | 会话 ID（需先通过 `POST /conversations` 创建） |
| `thinking_enabled` | `boolean` | 否 | 是否开启深度思考模式，默认 `true` |
| `model_name` | `string` | 否 | 模型名称（对应 `config.yaml` 中的模型），不传则使用默认模型 |
| `file_metadatas` | `string` | 否 | JSON 字符串，携带之前上传文件的引用信息 |

### Response `200 OK`

```
Content-Type: text/event-stream
```

SSE 流式事件序列，详见 [SSE 事件类型](index.md#sse-事件类型)。典型序列：

```
data: <run_start>
data: <thinking_start>
data: <reasoning ...>
data: <thinking_end>
data: <token ...>
data: <sandbox_provisioning ...>     # 首次 sandbox 工具时（容器准备中）
data: <tool_start ...>
data: <progress phase="provisioning" ...>   # 每 1s 心跳，容器仍准备中
data: <tool_end ...>
data: <token ...>
data: <run_end ...>
data: [DONE]
```

> 补充：当 agent 安静输出（模型思考、慢工具、容器创建）超过 1 秒时，
> 后端会以 1 秒间隔推送 `progress` 心跳事件，`phase` 取值：
> `thinking`（模型思考）、`tool`（工具执行中）、`provisioning`（容器/环境准备中）。
> 前端据此在状态栏展示动效文案（避免页面显得卡住）。后端仅对 `provisioning`（容器生成中）
> 与 `subagent_progress`（委派子代理中）返回并展示耗时；`thinking`（思考中）与
> `tool`（执行工具中）不返回、不展示耗时。

### 重要行为

- **客户端断开连接（刷新/关标签页）不会中断后端任务** — agent 会在后台继续执行并完整持久化
- 只有 `POST /chat/stream/stop` 才会主动取消执行
- 取消后已生成的部分内容会被保存到数据库

### 错误响应

流内错误以 `error` SSE 事件推送，`run_end` 的 `finish_reason` 为 `"error"`：

```
data: {"type":"error","message":"服务端内部错误，请重试。"}
data: {"type":"run_end","conversation_id":"...","finish_reason":"error"}
data: [DONE]
```

| 状态码 | 说明 |
|--------|------|
| 404 | 会话不存在（需先调用 POST /conversations 创建） |
| 403 | 无权访问该会话 |

---

## POST /stream/stop

停止指定会话的流式生成。

### Request

```
POST /py/api/chat/stream/stop
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `conversation_id` | `string` | ✅ | 要停止的会话 ID |

### Response `200 OK`

```json
{
  "status": "cancelled",
  "conversation_id": "abc123"
}
```

### Response `404 Not Found`

```json
{
  "detail": "对话 abc123 没有正在进行的流式生成"
}
```

---

## GET /messages/{conversation_id}

获取指定对话的结构化消息历史（含用户消息、助手回复、工具调用记录等）。

### Request

```
GET /py/api/chat/messages/{conversation_id}
Authorization: Bearer <token>
```

### Response `200 OK`

```json
{
  "conversation_id": "abc123",
  "messages": [
    {
      "id": "msg-uuid-1",
      "role": "user",
      "content": "帮我分析这个 CSV 文件",
      "event_type": "message",
      "tool_name": null,
      "tool_input": null,
      "tool_output": null,
      "file_metadata": "[{\"filename\":\"data.csv\",\"size\":1024,\"path\":\"/mnt/user-data/uploads/data.csv\",\"extension\":\".csv\"}]",
      "description": null,
      "duration_ms": null,
      "created_at": "2026-08-12T10:30:00"
    },
    {
      "id": "msg-uuid-2",
      "role": "assistant",
      "content": "让我先查看文件内容...",
      "event_type": "message",
      "tool_name": null,
      "tool_input": null,
      "tool_output": null,
      "file_metadata": null,
      "description": null,
      "duration_ms": null,
      "created_at": "2026-08-12T10:30:05"
    }
  ]
}
```

### 消息字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `string` | 消息 ID (UUID) |
| `role` | `string` | `user` / `assistant` / `tool` |
| `content` | `string` | 消息正文 |
| `event_type` | `string` | `message` / `reasoning` |
| `tool_name` | `string \| null` | 工具名称（仅 tool 角色） |
| `tool_input` | `string \| null` | 工具输入 JSON（仅 tool 角色） |
| `tool_output` | `string \| null` | 工具输出（仅 tool 角色） |
| `file_metadata` | `string \| null` | 文件元数据 JSON |
| `description` | `string \| null` | 描述（子代理/任务委派） |
| `duration_ms` | `number \| null` | 工具执行耗时（毫秒） |
| `created_at` | `string \| null` | 创建时间 (ISO 8601) |

> 当 `tool_name == "task"` 且 `tool_input` 不为空时，额外返回 `is_subagent: true` 和 `subagent_type` 字段。

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 404 | 会话不存在 |
| 403 | 无权访问该会话 |

---

## GET /files/{conversation_id}

获取代理工作区中的文件，支持预览和下载两种模式。

### Request

```
GET /py/api/chat/files/{conversation_id}?path={virtual_path}&download={true|false}
Authorization: Bearer <token>
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | `string` (query) | ✅ | 虚拟文件路径，如 `/mnt/user-data/outputs/report.pptx` |
| `download` | `boolean` (query) | 否 | `true` 时强制下载，`false`（默认）时内联预览 |

### Response

#### 本地存储模式

```
Content-Type: <auto-detected-mime-type>
Content-Disposition: inline; filename="report.pptx"
```

返回文件二进制内容。

#### S3/MinIO 存储模式（OBS）

```
HTTP 200 OK
Content-Type: <auto-detected-mime-type>
Content-Disposition: inline|attachment; filename="..."
```

后端从 OBS 服务端拉取对象并流式返回（代理）。不再 302 到 OBS 预签名地址——OBS
端点是内网地址且不带 CORS 头，浏览器 `fetch` 跟随重定向会被跨域拦截，所以必须
由后端代理，让下载/预览停留在与前端同源（`/py/api/...`）上。

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 400 | 路径无效 |
| 404 | 文件不存在或会话不存在 |
| 403 | 无权访问该会话 |

---

## GET /files/{conversation_id}/url

返回文件的**自认证下载 URL**（Java 式下载），前端拿到后直接导航/`<a>` 下载，
不需要 `fetch` 文件内容，因此不触发跨域。

### Request

```
GET /py/api/chat/files/{conversation_id}/url?path={virtual_path}&download={true|false}
Authorization: Bearer <token>
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | `string` (query) | ✅ | 虚拟文件路径 |
| `download` | `boolean` (query) | 否 | `true` 时生成 attachment（强制下载）URL，否则 inline |

### Response `200 OK`

```json
{
  "url": "https://fintechdev.obs.cn-south-1.myhuaweicloud.com/users/.../workspace/a.txt?X-Amz-Algorithm=AWS4-HMAC-SHA256&...",
  "backend": "s3"
}
```

- `backend: "s3"` → `url` 是 OBS 预签名地址，自带签名，浏览器直接导航即可下载，无 CORS。
- `backend: "local"` → `url` 是同源 `/py/api/chat/files/...` 相对路径，前端仍需带 `Authorization` 头 fetch。

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 400 | 路径无效 |
| 404 | 文件不存在或会话不存在 |
| 403 | 无权访问该会话 |

---

## GET /files/{conversation_id}/info

返回文件的元数据，供前端决定是否可预览。

### Request

```
GET /py/api/chat/files/{conversation_id}/info?path={virtual_path}
Authorization: Bearer <token>
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | `string` (query) | ✅ | 虚拟文件路径 |

### Response `200 OK`

```json
{
  "name": "report.pptx",
  "size": 123456,
  "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "previewable": true,
  "virtual_path": "/mnt/user-data/outputs/report.pptx"
}
```

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 400 | 路径无效 |
| 404 | 文件不存在或会话不存在 |
| 403 | 无权访问该会话 |
