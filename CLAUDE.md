# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SkillHub is a multi-user AI Agent + Skill execution platform built on top of DeerFlow. The backend (`backend/`) is a FastAPI service that wraps a LangGraph agent with configurable skills (knowledge + tools). Authentication is delegated to an external Java system; the Java system issues JWT tokens (HMAC512/HS512 signed, with `login_user_key` claim containing userId). This project verifies those tokens and does NOT issue its own JWT or store passwords locally.

DeerFlow provides the gateway, sandbox infrastructure, memory, summarization, and IM channel integrations. SkillHub adds the FastAPI layer with custom auth, skill management, and the LangGraph ReAct agent loop.

### Source Code Boundaries (Critical)

There are TWO separate codebases under `backend/` — know which one to modify:

| Directory | Role | Modify? |
|---|---|---|
| `backend/packages/harness/agent_sdk/` | **SkillHub's own agent_sdk** — our agent runtime, community tools, sandbox | ✅ Yes |
| `backend/deerflow_origin/` | **DeerFlow reference source** — for reference / understanding SDK behavior only | ❌ **NEVER** |
| `backend/app/` | **SkillHub FastAPI application** — routes, services, agent config | ✅ Yes |

When adding a new tool (e.g., web search), put it in `backend/packages/harness/agent_sdk/community/<tool-name>/tools.py`, following the same pattern as existing community tools. Then wire it in `backend/app/core/agent.py`.

## Development Commands

### Backend (from `backend/`)

```bash
# Install dependencies
uv sync

# Run dev server (hot-reload on port 8001)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# Lint
uvx ruff check .
uvx ruff format --check .

# Format
uvx ruff check . --fix && uvx ruff format .

# Database migrations
uv run alembic revision --autogenerate -m "description"   # create migration
uv run alembic upgrade head                                # apply migrations
uv run alembic downgrade -1                                # rollback one

# Run tests (tests/ directory does not exist yet — create it first)
uv run pytest tests/ -v
```

### Backend (from `backend/`)

```bash
make help          # List all available commands
make install       # uv sync
make dev           # Start backend dev server with hot-reload
make gateway       # Start uvicorn directly (no reload)
make test          # Run pytest
make lint          # Ruff lint check
make format        # Ruff format

```

### Ruff config

Line length is **240** (not the default 88), targets Python 3.12, and enables rules: E (pycodestyle), F (pyflakes), I (isort), UP (pyupgrade).

### Logging: Two different logger types — know which one you're editing

The project has **two different logging systems** with **different format syntax**:

| Code area | Logger type | Format syntax | Intercepted by |
|---|---|---|---|
| `backend/app/` | **loguru** (`from loguru import logger`) | `{}` braces | N/A (direct) |
| `backend/packages/harness/agent_sdk/` | **standard `logging`** (`import logging`) | `%s` / `%d` / `%r` | `_InterceptHandler` → loguru |
| `backend/skills/` | **standard `logging`** (`import logging`) | `%s` / `%d` / `%r` | Not intercepted (standalone scripts) |

**Why agent_sdk uses `%s` — and that's correct:**

Agent_sdk uses standard `logging`. All its log records flow through
`_InterceptHandler.emit()` in `app/utils/logger_config.py`, which calls
`record.getMessage()` — this resolves `%s` placeholders automatically
before passing the formatted string to loguru. **Do NOT change `%s`
to `{}` in agent_sdk code** — that would break the SDK's portability
and standard `logging` compatibility.

```python
# ✅ Correct in backend/app/ (loguru) — {} braces
logger.info("User {} logged in", user_id)

# ✅ Correct in agent_sdk/ (standard logging) — %s formatting
logger.info("User %s logged in", user_id)
#   ↑ _InterceptHandler → record.getMessage() → "User 123 logged in" → loguru

# ❌ Wrong in backend/app/ (loguru) — %s prints as literal text
logger.info("User %s logged in", user_id)

# ❌ Wrong in agent_sdk/ (standard logging) — {} is not standard logging syntax
logger.info("User {} logged in", user_id)
```

**Exception logging:**
- loguru: use `logger.exception()` or `logger.opt(exception=True).warning()`
- standard logging: use `logger.exception()` or `logger.error("...", exc_info=True)`

## Architecture

### Two Config Layers

There are two separate configuration systems — know which one to edit:

1. **`config.yaml`** (repo root): DeerFlow runtime config — LLM models, tools (web_search, file ops), sandbox provider, skills container path, memory (debounce, storage), summarization thresholds, IM channel credentials, agents API settings. Generated from `config.example.yaml` via `make config`.

2. **`.env`** (in `backend/`): FastAPI application settings — `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `MODEL_ID`, `SECRET_KEY`, `ALGORITHM` (default HS512), `LOGIN_USER_KEY`, `JAVA_AUTH_URL`, `DATABASE_URL`, `SKILLS_DIR`, plus optional API keys (`TAVILY_API_KEY`, `JINA_API_KEY`, `VOLCENGINE_API_KEY`). Template at `.env.example`.

### Agent Execution Loop

The agent is built via **`agent_sdk.create_agent`** in `app/core/agent.py`, which assembles a LangGraph StateGraph with a ReAct loop internally. Two singleton instances are created at startup (thinking-enabled / normal) and selected per-request by the `thinking_enabled` flag.

- **Model**: Created from `config.yaml` model configs via `agent_sdk`; supports MiniMax/DeepSeek proxies through `ANTHROPIC_BASE_URL`.
- **Tools**: Sandbox tools (`bash`, `ls`, `glob`, `grep`, `read_file`, `write_file`, `str_replace`) provided by `agent_sdk.sandbox.make_sandbox_tools`, bound to a local subprocess sandbox.
- **System Prompt**: Hardcoded in `_build_agent()` with role, critical reminders, working directory layout, and capabilities.
- **Checkpointer**: Configured via `config.yaml` → `checkpointer.type`: `memory` (InMemorySaver, dev only), `sqlite`, or `postgres`. Production uses PostgreSQL — agent conversation context survives restarts. Initialized in `main.py` lifespan via `agent_sdk.runtime.checkpointer.make_checkpointer`.
- **Thread IDs**: Derived from `conversation_id` via `make_thread_id()` in `utils/chat.py`: format `"user-{conversation_id}"`. This is the LangGraph thread_id used for checkpointing. The `"user-"` prefix is a hardcoded placeholder — TODO to use actual userId once auth is wired into chat routes.

### conversation_id vs thread_id

| Concept | Scope | Usage |
|---|---|---|
| `conversation_id` | Business layer | DB persistence (runs/messages tables), message history API, file serving |
| `thread_id` | LangGraph layer | Agent state checkpointing via checkpointer; `= "user-" + conversation_id` |

Both are 1:1. The frontend receives `conversation_id` in the `run_start` SSE event and passes it back on subsequent requests to continue the same conversation.

### Skill System

Skills live at `backend/skills/{skill-name}/SKILL.md` (path configured in `config.yaml` → `skills.path`). Each skill directory may also contain `scripts/`, `templates/`, `references/`, or `assets/` subdirectories.

Skill loading and sandbox execution are delegated to **agent-sdk** (configured via `config.yaml`'s `skills` and `sandbox` sections). The Python-level skill registry (`app/skills/`) has been removed in favor of the SDK's built-in skill management.

### Environment Strategy

The project maintains **three distinct runtime environments** with different goals and constraints:

| Environment | Goal | Logging | Deployment |
|---|---|---|---|
| **Local dev** | Day-to-day feature development, debugging | File-based (`backend/logs/`) — human-readable text,保留现有模式 | `uv run uvicorn` or `make dev` |
| **Test / staging** | Pre-production validation, integration tests | JSON stdout → Docker json-file driver → future log collector (TBD) | Docker Compose or temp K8s |
| **Production** | Serving real users | JSON stdout → Promtail/Loki or cloud log service | Final K8s manifests (planned) |

### Local Development Logging

Local dev **keeps the current file-based logging** (`RotatingFileHandler` writing to `backend/logs/app.log`). This is intentional:
- Developers can `tail -f` or open files directly in their editor.
- No extra infrastructure (Loki, Grafana) needed to run the backend.
- `state_logger.py` continues writing JSON forensics to `backend/logs/{conversation_id}/`.

**Do not change the local dev logging setup without explicit approval.**

### Test / Production Logging

Test and production environments run inside containers. The canonical pattern is:
1. FastAPI outputs **structured JSON logs to stdout only**.
2. Docker / container runtime captures stdout.
3. A log collector (Promtail, Fluent Bit, etc.) ships container logs to a centralized store (Loki, Elasticsearch, cloud service).
4. **No file handlers inside the container** — avoids multi-worker contention and ephemeral-disk data loss.

This switch is **config-driven** (e.g., via `ENVIRONMENT` env var or Pydantic Settings) so the same Docker image works in all three environments without rebuild.

## Authentication Flow

Login (`POST /auth/login`) follows a three-step pattern:
1. Forward credentials to the external Java auth URL (`java_auth_url` config) via httpx
2. Upsert the user locally in the `users` table (no password stored — the `hashed_password` column was dropped in migration `b9f3a1c72d08`)
3. Return the Java-issued JWT token directly (Python does NOT issue its own tokens)

Java token format: `Header: {"alg": "HS512", "typ": "JWT"}`, `Claims: {"login_user_key": "<userId>", "timestamp": <epochMillis>}`. Signed with HMAC512 (HS512). No expiration.

All protected endpoints validate the Bearer token via `get_current_user` dependency (`app/core/dependencies.py`), which decodes the Java-issued JWT using HS512, extracts `login_user_key` as user_id, and looks up the user.

**`app/auth/__init__.py`** is an **experimental stub** — it creates a Redis client, mocks Java token creation, and provides `check_is_authenticated()` that validates sessions against Redis. It is **not wired into the main application** and uses hardcoded `USER_ID = 'user123'`. The production auth path is through `app/core/auth.py` and `app/core/dependencies.py`.

### API Routes

| Route | File | Description |
|---|---|---|
| `POST /chat` | `routes/chat.py` | Synchronous chat (waits for full agent execution) |
| `POST /chat/stream` | `routes/chat.py` | SSE streaming (token + tool events in real time); accepts optional `conversation_id` to continue existing conversation |
| `GET /chat/messages/{conversation_id}` | `routes/chat.py` | Retrieve structured message history (user/assistant/tool/reasoning) |
| `GET /chat/files/{conversation_id}` | `routes/chat.py` | Serve files from agent workspace/outputs/uploads |
| `GET /chat/files/{conversation_id}/info` | `routes/chat.py` | File metadata (size, MIME type, previewable flag) |
| `GET /conversations` | `routes/conversations.py` | List all conversations ordered by recent activity |
| `DELETE /conversations/{conversation_id}` | `routes/conversations.py` | Delete a conversation, its messages, and state logs |
| `POST /auth/login` | `routes/auth.py` | Login → proxy to Java → upsert user → issue JWT |
| `GET /skills` | `routes/skills.py` | List all registered skill names |
| `GET /health` | `main.py` | Health check (status, model_id, version) |

### Database Models (`app/models/database.py`)

PostgreSQL via asyncpg is **required** (no SQLite fallback in the current code). Default dev connection: `postgresql+asyncpg://postgres:qwer@localhost/agent`.

Three tables via SQLModel + async SQLAlchemy:
- **`users`**: `id`, `username` (unique), `email` (unique), `is_active`, `created_at` — no password column
- **`user_skills`**: Per-user skill enablement (`user_id` FK, `skill_name`, `enabled`)
- **`runs`**: Agent execution metadata (`thread_id`, `status`, `created_at`); `user_id` FK is commented out

## Project Structure (Key Files)

```
skill-hub/
├── config.yaml              # DeerFlow runtime config (models, tools, sandbox, checkpointer, memory)
├── config.example.yaml      # Documented config template
├── backend/
│   ├── Makefile             # Backend dev commands (install, dev, test, lint, format)
│   ├── app/
│   │   ├── main.py          # FastAPI app, lifespan (checkpointer init), route registration
│   │   ├── core/
│   │   │   ├── agent.py     # Agent singleton (agent_sdk.create_agent, init/get/shutdown)
│   │   │   ├── auth.py      # JWT create/decode
│   │   │   ├── config.py    # Pydantic Settings (reads .env)
│   │   │   ├── config_loader.py  # YAML config loader (AgentConfig, CheckpointerConfig, etc.)
│   │   │   └── state_logger.py   # State log persistence to disk
│   │   ├── routes/
│   │   │   ├── chat.py      # Chat (sync + SSE streaming) + messages + file serving
│   │   │   ├── conversations.py  # Conversation list + delete
│   │   │   └── skills.py    # Skill listing
│   │   ├── services/
│   │   │   ├── chat_service.py        # Agent execution orchestration + DB persistence
│   │   │   └── conversation_service.py # Conversation lifecycle (list, delete)
│   │   ├── repositories/
│   │   │   ├── message_repo.py  # Messages table CRUD
│   │   │   └── run_repo.py      # Runs table CRUD
│   │   ├── schemas/
│   │   │   ├── chat.py          # Chat request/response schemas
│   │   │   └── conversation.py  # Conversation schemas
│   │   ├── models/
│   │   │   └── database.py  # SQLModel tables + db helpers
│   │   └── utils/
│   │       ├── chat.py      # make_thread_id, make_config, read_uploaded_files
│   │       ├── sse.py       # get_sse_event helper
│   │       ├── model.py     # get_model_display_name
│   │       └── file.py      # PREVIEWABLE_EXTENSIONS
│   ├── migrations/          # Alembic migrations
│   ├── pyproject.toml
│   ├── ruff.toml            # line-length 240, target py312
│   └── alembic.ini
├── backend/skills/          # Skill definitions (each dir has SKILL.md + optional scripts/)
└── docs/                    # Architecture docs (Chinese)
```

## Key Dependencies

- **agent-sdk**: Agent runtime assembly (create_agent, sandbox tools, checkpointer, skill loading, path resolution)
- **LangChain** + **LangGraph**: Underlying agent framework used by agent-sdk (ReAct orchestration, checkpointing, streaming)
- **FastAPI** + **uvicorn**: HTTP server with SSE streaming (sse-starlette no longer used — SSE is hand-rolled via StreamingResponse)
- **SQLModel** + **asyncpg** + **Alembic**: ORM, async PostgreSQL, migrations
- **httpx**: Async HTTP client for Java auth forwarding
- **PyJWT** (jwt): JWT verification (HS512, matching Java HMAC512)
- **redis** (redis-py): Async Redis client via `redis.asyncio` (used by IM channels; the experimental `app/auth/` stub has been removed)

## Phase 2 Roadmap

Planned upgrades not yet implemented:
- Wire `get_current_user` auth dependency into chat routes (currently chat endpoints have no auth)
- Replace hardcoded `"user-"` prefix in `make_thread_id` with actual userId
- Per-user tool filtering based on `user_skills` table
- Dynamic tool loading from `skills/*/tools.py`
- Skill registration/upload API for admins

## 前端开发与验证规则（重要）

> 本项目有两套前端，默认只在其中一套工作，**不要混淆**：

| 前端 | 路径 | 用途 | 何时用 |
|---|---|---|---|
| **调试页** | `frontend/debug-agent.html` | 单文件调试页，直连后端 API | **默认**——新增/改动功能都在这里验证测试 |
| **迁移项目** | `dify-cmbc/web` | SkillHub → dify 的正式迁移（Next.js/React） | **仅当用户明确要求迁移**时才动 |

- 默认做前端都在 `frontend/debug-agent.html`，**除非用户主动要求迁移到 Next.js 项目**。
- **新增的功能，都要先在 `frontend/debug-agent.html` 验证测试通过**，再考虑是否迁移。
- `debug-agent.html` 是纯 HTML + 内联 JS/CSS 单文件，不依赖构建；后端本地跑 `make dev`（端口 8001）即可联调。

## Frontend 迁移协作规则（重要）

> 涉及 SkillHub 前端迁移到 `dify-cmbc/web`（对齐文档见 `docs/move-to-cmbweb/`）的工作：

- **开始实现前，必须先与用户对齐**：先复述理解 + 列出差异/疑问/待确认点，等用户补充细节并确认后再动手写代码；不要拿到任务就直接开工。
- 迁移代码统一落在 `dify-cmbc/web/app/agc-agent/`（不是 `(commonLayout)` 下）。
- 图标用 `lucide-react`，尽量与 `public/phase1/pages/*.html` 视觉/图标一致。
- 不改动 `dify-cmbc/web` 原有功能：仅新增 `app/agc-agent/` 目录与必要依赖（如 lucide-react）。
