# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Heyu Agent is a multi-user AI Agent + Skill execution platform built on top of DeerFlow. The backend (`backend/`) is a FastAPI service that wraps a LangGraph agent with configurable skills (knowledge + tools). Users register/login by email + password; the backend hashes the password (bcrypt) and issues its own HS512 JWT (with a `login_user_key` claim = user id). Legacy Java-issued tokens (same HS512 secret) remain compatible.

DeerFlow provides the gateway, sandbox infrastructure, memory, summarization, and IM channel integrations. Heyu Agent adds the FastAPI layer with auth, skill management, and the LangGraph ReAct agent loop.

### Source Code Boundaries (Critical)

There are TWO separate codebases under `backend/` — know which one to modify:

| Directory | Role | Modify? |
|---|---|---|
| `backend/packages/harness/agent_sdk/` | **Heyu Agent's own agent_sdk** — our agent runtime, community tools, sandbox | ✅ Yes |
| `backend/deerflow_origin/` | **DeerFlow reference source** — for reference / understanding SDK behavior only | ❌ **NEVER** |
| `backend/app/` | **Heyu Agent FastAPI application** — routes, services, agent config | ✅ Yes |

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

Users register/login by **email + password** (self-contained, no external system):
- `POST /auth/register` — validates email/password, hashes the password with bcrypt, creates a user (`users.email` unique), and issues an access token.
- `POST /auth/login` — looks up the user by email, verifies the bcrypt hash, checks `is_active`, and issues an access token.
- `POST /auth/verify` — validates an existing token and auto-registers the user (first call), returning `user_id` / `role`.

Token format (Python-issued): `Header: {"alg": "HS512", "typ": "JWT"}`, `Claims: {"login_user_key": "<user.id>", "iat": ..., "exp": ...}`. Signed with HMAC512 (HS512) using `SECRET_KEY`, expiring after `access_token_expire_minutes` (default 7 days). Legacy Java-issued tokens (same HS512 secret, no `exp`) remain compatible.

All protected endpoints validate the Bearer token via `get_current_user` dependency (`app/core/dependencies.py`), which decodes the JWT using HS512, extracts `login_user_key` as user_id, and looks up the user.

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
| `POST /auth/register` | `routes/auth.py` | Email register → create user → issue JWT |
| `POST /auth/login` | `routes/auth.py` | Email login → verify password → issue JWT |
| `POST /auth/verify` | `routes/auth.py` | Validate token + auto-register user, return `user_id`/`role` |
| `GET /skills` | `routes/skills.py` | List all registered skill names |
| `GET /health` | `main.py` | Health check (status, model_id, version) |

### Database Models (`app/models/database.py`)

PostgreSQL via asyncpg is **required** (no SQLite fallback in the current code). Default dev connection: `postgresql+asyncpg://postgres:qwer@localhost/agent`.

Key tables via SQLModel + async SQLAlchemy:
- **`users`**: `id` (UUID for email-registered users; Java `login_user_key` for legacy), `username`, `email` (unique), `hashed_password` (bcrypt, nullable for legacy Java users), `role`, `is_active`, `created_at`
- **`user_skills`**: Per-user skill enablement (`user_id` FK, `skill_name`, `enabled`)
- **`runs`**: Agent execution metadata (`thread_id`, `status`, `created_at`); `user_id` FK is commented out

## Project Structure (Key Files)

```
heyu-agent/
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
- **httpx**: Async HTTP client (used by various integrations)
- **PyJWT** (jwt): JWT sign & verify (HS512)
- **redis** (redis-py): Async Redis client via `redis.asyncio` (used by IM channels; the experimental `app/auth/` stub has been removed)

## Phase 2 Roadmap

Planned upgrades not yet implemented:
- Wire `get_current_user` auth dependency into chat routes (currently chat endpoints have no auth)
- Replace hardcoded `"user-"` prefix in `make_thread_id` with actual userId
- Per-user tool filtering based on `user_skills` table
- Dynamic tool loading from `skills/*/tools.py`
- Skill registration/upload API for admins

## 前端（Next.js，`web/`）

前端是 Next.js 16 App Router 项目，位于 `web/`。工作台在 `web/app/agc-agent/`，登录/注册页在根路由 `web/app/page.tsx`（项目名 **Heyu Agent**，与 `dify-cmbc` 无关）。

- 本地开发：`cd web && npm run dev`（默认 3000），后端跑 `make dev`（8001）；`/py/api/*` 通过 `next.config.ts` 反代到后端。
- 前端设计语言：浅色、白卡片、`#0072ff` 主色（hover `#0056cc`）、lucide-react 图标。
