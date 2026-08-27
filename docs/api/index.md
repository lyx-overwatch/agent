# SkillHub API 接口文档

## 概述

- **Base URL**: `http://<host>:8001`
- **Content-Type**:
  - 一般接口: `application/json`
  - 文件上传: `multipart/form-data`
  - SSE 流式: `text/event-stream`
- **认证**: 除 `/health` 外，所有接口需在 Header 中携带 `Authorization: Bearer <token>`（JWT, HS512 签名）

## 认证流程

1. 前端从 Java 主系统获取 JWT Token
2. 调用 `POST /py/api/auth/verify` 完成校验 + 自动注册
3. 后续所有业务接口携带同一 Token

## 接口索引

| 模块 | 文档 | 接口数 |
|------|------|--------|
| Auth（认证） | [auth.md](auth.md) | 1 |
| Chat（对话） | [chat.md](chat.md) | 5 |
| Conversations（会话） | [conversations.md](conversations.md) | 5 |
| Models（模型） | [models.md](models.md) | 1 |
| Skills（技能） | [skills.md](skills.md) | 13 |
| Health（健康检查） | [health.md](health.md) | 1 |

## SSE 事件类型

对话流式接口 (`POST /py/api/chat/stream`) 使用 SSE (Server-Sent Events) 推送实时事件：

| 事件 | 说明 |
|------|------|
| `run_start` | 对话开始，返回 `conversation_id` 和 `thread_id` |
| `thinking_start` | 深度思考开始 |
| `thinking_end` | 深度思考结束 |
| `token` | 文本增量（流式输出） |
| `reasoning` | 推理内容增量 |
| `tool_start` | 工具调用开始（含 `tool`, `input`, `run_id`） |
| `tool_end` | 工具调用结束（含 `tool`, `output`, `run_id`） |
| `sandbox_provisioning` | 首次 sandbox 工具开始时（一次性），容器/环境准备中，含 `tool`, `run_id` |
| `progress` | 流安静时的 1s 心跳进度，含 `phase`（`thinking`/`tool`/`provisioning`）；仅 `provisioning` 阶段携带 `elapsed_seconds`，可选 `tool`/`run_id` |
| `subagent_progress` | 子代理执行进度 |
| `error` | 错误信息 |
| `run_end` | 对话结束，含 `finish_reason`（`stop` / `cancelled` / `error`） |
| `[DONE]` | 流结束标记 |

## 通用错误响应

| 状态码 | 含义 |
|--------|------|
| 401 | Token 缺失/无效/过期，或用户未注册 |
| 403 | 无权访问该资源（非所有者） |
| 404 | 资源不存在 |
| 400 | 请求参数错误 |
| 500 | 服务端内部错误 |
