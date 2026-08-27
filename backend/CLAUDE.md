# CLAUDE.md — Backend

This file documents the backend design conventions, layered architecture, and coding standards for the SkillHub backend (`backend/`).

## Architecture Overview

The backend is a FastAPI application with a **strict four-layer architecture**:

```
routes/         ←  HTTP 层：解析参数、调用 service、返回响应
services/       ←  业务层：编排逻辑、事务管理、Agent 交互
repositories/   ←  数据层：纯 SQL CRUD，通过 AsyncSession 注入
models/         ←  模型层：SQLModel 表定义（不变）
```

```
backend/app/
├── routes/             # 路由层 — 每个 handler ≤30 行
│   ├── __init__.py     #   register_routers(app)
│   ├── chat.py         #   POST/chat, POST/chat/stream, GET/chat/messages, GET/chat/files
│   ├── conversations.py #  GET/conversations, DELETE/conversations/{id}
│   └── skills.py       #   GET/skills
├── services/           # 服务层 — 业务逻辑 + Agent 编排
│   ├── chat_service.py       # ChatService: execute_sync, execute_stream, get_messages
│   └── conversation_service.py  # ConversationService: list_conversations, delete_conversation
├── repositories/       # 仓库层 — 纯数据库访问
│   ├── run_repo.py          # RunRepo: upsert, get_all, get_by_id, delete
│   └── message_repo.py      # MessageRepo: create, get_by_conversation, delete_by_conversation
├── schemas/            # Pydantic 请求/响应模型
│   ├── chat.py              # ChatRequest, ChatResponse
│   └── conversation.py      # ConversationItem, ConversationListResponse, DeleteConversationResponse
├── utils/              # 跨层共享的工具函数
│   ├── chat.py              # make_thread_id, make_config
│   ├── model.py             # get_model_display_name
│   ├── sse.py               # get_sse_event
│   └── file.py              # read_uploaded_files, PREVIEWABLE_EXTENSIONS
├── models/             # SQLModel 表定义
│   └── database.py          # User, UserSkill, Run, Message + SessionLocal
├── core/               # 核心基础设施
│   ├── agent.py             # Agent 运行时单例 (init/get/shutdown)
│   ├── auth.py              # JWT 签发/验证
│   ├── config.py            # Pydantic BaseSettings (.env)
│   ├── config_loader.py     # YAML 配置加载 (config.yaml)
│   ├── dependencies.py      # FastAPI 认证依赖 (get_current_user)
│   └── state_logger.py      # Agent 状态日志（调试/取证）
└── main.py             # FastAPI 入口 + lifespan
```

## Layer Rules

### 1. Routes（路由层）

**只做三件事：解析参数 → 调用 service → 返回响应。**

```python
@router.post("", response_model=ChatResponse)
async def chat(
    message: str = Form(...),
    conversation_id: str | None = Form(None),
    thinking_enabled: bool = Form(True),
    files: list[UploadFile] = File(default=[]),
):
    svc = ChatService()
    file_data = await read_uploaded_files(files)
    result = await svc.execute_sync(
        message=message,
        conversation_id=conversation_id,
        thinking_enabled=thinking_enabled,
        file_data=file_data,
    )
    return ChatResponse(**result)
```

规则：
- **禁止**直接访问 `SessionLocal`、执行 SQL 查询、调用 `save_state_log`
- **禁止**包含业务逻辑（条件判断仅限于参数校验和异常转换）
- 每个 handler 创建自己的 service 实例（`svc = XxxService()`）
- SSE/文件响应等传输格式转换在此层处理
- `APIRouter` 内部定义 `prefix`，`register_routers` 中统一加 `/py/api` 前缀

### 2. Services（服务层）

**编排业务逻辑，协调 Agent + Repository + 状态日志。**

```python
class ChatService:
    def __init__(self) -> None:
        self._run_repo = RunRepo()
        self._message_repo = MessageRepo()

    async def execute_sync(self, ...) -> dict:
        # 1. 生成 conversation_id / thread_id
        # 2. 保存上传文件
        # 3. 运行 Agent
        # 4. 提取结果
        # 5. 记录状态日志
        # 6. 持久化到数据库
        # 7. 返回 dict
```

规则：
- Service 方法签名使用**原始类型**（`str`, `bool`, `list[tuple[str, bytes]]`），不接收 FastAPI 对象（`UploadFile`、`Request`）
- 数据库会话通过 `async with SessionLocal() as db:` 管理，传入 repo 的 static method
- 对外返回 `dict` 或 `AsyncGenerator[dict, None]`（stream 场景），不返回 Pydantic model
- **可以**调用 `save_state_log`、`get_agent`
- 复杂业务逻辑（如 steps 交错持久化）以私有方法形式留在 service 内

### 3. Repositories（仓库层）

**纯数据库 CRUD，零业务逻辑。**

```python
class RunRepo:
    @staticmethod
    async def upsert(db: AsyncSession, conversation_id: str, ...) -> None:
        result = await db.execute(
            sa_update(Run).where(Run.id == conversation_id).values(...)
        )
        if result.scalar_one_or_none() is None:
            db.add(Run(...))
```

规则：
- 所有方法为 `@staticmethod`，通过 `AsyncSession` 参数注入（**不自己创建 session**）
- 方法命名：`get_by_*`, `get_all`, `create`, `upsert`, `delete`, `delete_by_*`
- **禁止**调用 `db.commit()` — 事务由 service 层管理
- **禁止**包含任何业务判断（如 "如果有则更新，否则插入" 是业务逻辑，应在 service 层）

### 4. Utils（工具层）

**跨层共享的纯函数和常量。**

| 模块 | 内容 | 使用方 |
|---|---|---|
| `chat.py` | `make_thread_id`, `make_config` | routes + services |
| `model.py` | `get_model_display_name` | routes + services |
| `sse.py` | `get_sse_event` | routes |
| `file.py` | `read_uploaded_files`, `PREVIEWABLE_EXTENSIONS` | routes + services |

规则：
- 只有被**多个层**使用的函数才放 utils
- 仅在一个模块内使用的辅助函数留在该模块作为私有函数
- 所有函数通过 `app.utils.__init__` 统一 re-export

## Adding a New Feature

按以下顺序创建文件：

1. **`schemas/`** — 如果需要新的请求/响应模型
2. **`repositories/`** — 如果需要新的数据库操作
3. **`services/`** — 实现业务逻辑
4. **`routes/`** — 添加 handler，注册到 `__init__.py`

示例 PR checklist：
- [ ] Route handler ≤ 30 行
- [ ] Service 不接收 FastAPI 类型（`UploadFile`, `Request`, `Response`）
- [ ] Repository 只接收 `AsyncSession` + 基本类型
- [ ] 数据库事务在 service 层管理（`db.commit()` 只在 service 中调用）
- [ ] `ruff check` 通过

## Database

- **PostgreSQL** 通过 `asyncpg` + SQLAlchemy async engine 访问
- `SessionLocal`（`async_sessionmaker`）在 `models/database.py` 定义
- 数据库 URL 转换：`postgresql://` → `postgresql+asyncpg://` 自动处理
- 三张业务表：`users`, `user_skills`, `runs`, `messages`（SQLModel 定义）
- Alembic 管理迁移：`uv run alembic revision --autogenerate -m "..."`

### 关键模型关系

| 表 | 主键 | 关键外键 | 用途 |
|---|---|---|---|
| `Run` | `id` (UUID, =conversation_id) | `user_id` → users | 对话元数据 |
| `Message` | `id` (UUID) | `conversation_id` → runs.id | 消息 + 工具调用记录 |

## Agent

- 两套实例：`_agent_thinking`（深度思考开启）+ `_agent_normal`（关闭）
- `init_agent(checkpointer)` 在 FastAPI lifespan 中调用
- `get_agent(thinking_enabled=True)` 按请求返回对应实例
- Agent 配置来自 `config.yaml`（通过 `get_agent_config()` 加载）
- 工具执行在子进程 sandbox 中完成（文件操作限制在 `../agent-test/`）

## Authentication

- Java 系统签发 JWT（HS512），Python 端只验证不签发
- `get_current_user` 依赖注入 → 提取 `login_user_key` claim → 查 `users` 表
- 生产路径：`app/core/auth.py` + `app/core/dependencies.py`
- `app/auth/__init__.py` 是实验性 stub，未接入主应用

## Configuration

| 文件 | 用途 | 加载方式 |
|---|---|---|
| `config.yaml` | DeerFlow 运行时（模型、sandbox、memory） | `config_loader.py` (YAML) |
| `.env` | FastAPI 应用设置（API key、DB URL、JWT） | `config.py` (Pydantic Settings) |

## Key Dependencies

- **LangChain** + **LangGraph** — Agent 框架、ReAct 循环
- **FastAPI** + **sse-starlette** — HTTP + SSE 流式
- **SQLModel** + **asyncpg** + **Alembic** — ORM + 异步 PostgreSQL + 迁移
- **httpx** — 异步 HTTP（Java 认证转发）
- **PyJWT** — JWT 验证（HS512）
- **agent-sdk** (本地包) — Agent 工厂、sandbox、middleware、checkpointer

## Coding Style

- Python 3.12+，ruff 格式化，行宽 240
- 规则：E (pycodestyle), F (pyflakes), I (isort), UP (pyupgrade)
- 类型注解：所有公开方法必须有完整类型注解
- 日志：`backend/app/` 使用 loguru（`{}` 占位符）；`agent_sdk/` 使用标准 logging（`%s` 占位符，经 `_InterceptHandler` 转发）。不要混用。
- 文件头：模块级 docstring 描述职责
- 私有函数：`_` 前缀，仅模块内可见的辅助函数和常量

```bash
# Lint
uv run ruff check .

# Format
uv run ruff check --fix . && uv run ruff format .
```

## Dev Commands

```bash
cd backend

# Install
uv sync

# Dev server (port 8001, hot-reload)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# DB migrations
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
uv run alembic downgrade -1

# Tests
uv run pytest tests/ -v
```
