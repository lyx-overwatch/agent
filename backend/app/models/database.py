import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Text
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel

from app.core.config import settings

# SQLAlchemy async engine requires +asyncpg driver prefix;
# the raw DATABASE_URL uses postgresql:// for psycopg / checkpointer compatibility.
_db_url = settings.database_url
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    _db_url,
    echo=settings.debug,
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,  # recycle connections after 1 hour to avoid stale connections
    pool_pre_ping=True,  # verify connection is alive before using it
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class User(SQLModel, table=True):
    """本地用户表 —— 首次鉴权时自动从 Java Token 注册。

    ``id`` 即 Java 端 JWT 中的 ``login_user_key``，由 Java 主系统分配。
    本平台不自行签发用户标识，也不存储密码。
    """

    __tablename__ = "users"

    id: str = Field(primary_key=True, max_length=100)  # = login_user_key
    username: str | None = Field(default=None, max_length=50, index=True)
    email: str | None = Field(default=None, max_length=200)
    is_active: bool = Field(default=True)
    role: str = Field(default="user", max_length=20)  # "user" | "admin"（管理员由运维手动置位）
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )


class UserSkill(SQLModel, table=True):
    """记录每个用户启用的 Skill（知识/工具）。"""

    __tablename__ = "user_skills"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="users.id", max_length=100, index=True)
    skill_name: str = Field(max_length=100)
    enabled: bool = Field(default=True)


class Skill(SQLModel, table=True):
    """用户创作（自定义）技能的元数据。

    技能文件本体存 OBS（key 前缀 ``storage_key`` = ``skills/custom/<name>``），
    本表只记录元数据与审核状态。内置技能不落此表（随镜像打包在 ``skills/<name>/``
    文件系统里，按存储位置天然区分）。

    技能文件在 OBS 里按 ``name`` 全局唯一存一份（单副本共享）；「谁拥有 / 谁能用」
    由本表 ``author_id`` 与 ``user_skills`` 表表达，不复制文件。
    """

    __tablename__ = "skills"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True, max_length=36)
    name: str = Field(max_length=100, unique=True, index=True)  # 与 SKILL.md frontmatter 一致，全局唯一
    display_name: str = Field(default="", max_length=200)  # 名称展示，上传不传则默认 = name
    description: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))  # 来自 SKILL.md frontmatter
    author_id: str = Field(foreign_key="users.id", max_length=100, index=True)  # 创建者
    author_name: str | None = Field(default=None, max_length=100)  # 作者显示名（本阶段可空）
    review_status: str = Field(default="draft", max_length=20)  # "draft" | "pending" | "approved" | "rejected"
    review_note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))  # 审核驳回原因（reject 时写入）
    reviewed_by: str | None = Field(default=None, max_length=100)  # 审核人（user_id）
    reviewed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))  # 审核时间
    version: str = Field(default="1.0.0", max_length=50)  # 版本（暂存，无多版本流程）
    storage_key: str = Field(default="", max_length=500)  # OBS 对象 key 前缀 skills/custom/<name>
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )


class Run(SQLModel, table=True):
    """记录每次 Agent 执行的元数据。

    ``id`` 即 ``conversation_id``，是业务层对话的唯一标识（UUID），前端和后端统一使用。
    ``thread_id`` 是 LangGraph 内部标识，与 ``conversation_id`` 相同。
    """

    __tablename__ = "runs"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True, max_length=36)
    user_id: str | None = Field(default=None, foreign_key="users.id", max_length=100, index=True)
    # LangGraph thread_id（与 conversation_id 相同）
    thread_id: str = Field(max_length=150, index=True)
    title: str | None = Field(default=None, max_length=100)  # 对话标题（首条用户消息截断）
    title_pending: bool = Field(default=False)  # 标题是否仍在后台异步生成中（生成完成后置 False）
    total_tokens: int = Field(default=0)  # 累计 token 消耗
    cache_read: int = Field(default=0)  # 累计缓存命中 token 数（已缓存，仅按 20% 计费）
    cache_creation: int = Field(default=0)  # 累计写入缓存的 token 数
    status: str = Field(default="running", max_length=20)
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class Message(SQLModel, table=True):
    """记录对话中的每条消息和工具调用。"""

    __tablename__ = "messages"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True, max_length=36)
    user_id: str | None = Field(default=None, foreign_key="users.id", max_length=100, index=True)
    conversation_id: str = Field(max_length=36, index=True, foreign_key="runs.id")
    thread_id: str = Field(max_length=150, index=True)
    role: str = Field(max_length=20)  # "user", "assistant", "tool", "system"
    content: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    event_type: str | None = Field(default=None, max_length=50)  # "message", "tool_call", "thinking"
    tool_name: str | None = Field(default=None, max_length=100)
    tool_input: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    tool_output: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    file_metadata: str | None = Field(default=None, sa_column=Column(Text, nullable=True))  # JSON array of uploaded file info
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))  # subagent task description for display
    duration_ms: int | None = Field(default=None, nullable=True)  # execution time for subagent tool calls
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )


# ── 数据库工具函数 ────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def get_or_create_user(db: AsyncSession, user_id: str) -> tuple[User, bool]:
    """如果用户不存在则自动注册。

    Returns:
        ``(user, is_new)`` —— ``is_new=True`` 表示本次新注册。
    """
    result = await db.execute(sa_select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        return user, False

    # 不存在 → 自动注册（username 暂时用 user_id，后续可从 Java 补充）
    user = User(id=user_id, username=user_id, is_active=True)
    db.add(user)
    await db.flush()
    return user, True
