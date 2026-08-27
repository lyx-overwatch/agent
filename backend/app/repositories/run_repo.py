"""Run (conversation) repository — pure database CRUD."""

from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import desc
from sqlalchemy import select as sa_select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Run


class RunRepo:
    """Data access for the ``runs`` table."""

    @staticmethod
    async def create(
        db: AsyncSession,
        conversation_id: str,
        thread_id: str,
        user_id: str,
    ) -> None:
        """Create a new run record with status ``"active"``.

        Called when the user creates a conversation before sending the first message.
        """
        db.add(
            Run(
                id=conversation_id,
                thread_id=thread_id,
                user_id=user_id,
                status="active",
                created_at=datetime.now(UTC),
            )
        )

    @staticmethod
    async def upsert(
        db: AsyncSession,
        conversation_id: str,
        thread_id: str,
        user_id: str,
        title: str | None = None,
        total_tokens: int = 0,
        cache_read: int = 0,
        cache_creation: int = 0,
        status: str = "completed",
    ) -> None:
        """Update a run record after agent execution completes.

        Sets status, completed_at, total_tokens, and cache metrics on every call.
        Sets title on the first call where it is non-None (the agent-generated
        title from the first turn).

        Args:
            status: Final run status — ``"completed"``, ``"cancelled"``,
                ``"error"``, or ``"step_limit"`` (recoverable interruption).
        """
        values: dict = {
            "status": status,
            "completed_at": datetime.now(UTC),
            "total_tokens": total_tokens,
            "cache_read": cache_read,
            "cache_creation": cache_creation,
        }
        if title is not None:
            values["title"] = title
        result = await db.execute(sa_update(Run).where(Run.id == conversation_id).values(**values).returning(Run.id))
        if result.scalar_one_or_none() is None:
            db.add(
                Run(
                    id=conversation_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    title=title,
                    total_tokens=total_tokens,
                    cache_read=cache_read,
                    cache_creation=cache_creation,
                    status=status,
                    completed_at=datetime.now(UTC),
                )
            )

    @staticmethod
    async def set_title(db: AsyncSession, conversation_id: str, title: str) -> None:
        """Set the conversation title without touching status or completed_at.

        Used for both the preliminary fallback title early in the agent
        execution (so the conversation list never shows "新对话") and the
        AI 标题由后台异步任务在生成完成后写回。
        """
        await db.execute(sa_update(Run).where(Run.id == conversation_id).values(title=title))

    @staticmethod
    async def set_title_pending(db: AsyncSession, conversation_id: str, pending: bool) -> None:
        """Set the ``title_pending`` flag without touching title/status.

        ``True`` marks a conversation whose AI 标题仍在后台异步生成中；
        ``False`` 表示生成结束（无论成功与否）。前端据此在回合结束后
        继续轮询列表，直到标题落地。
        """
        await db.execute(sa_update(Run).where(Run.id == conversation_id).values(title_pending=pending))

    @staticmethod
    async def set_status(db: AsyncSession, conversation_id: str, status: str) -> None:
        """Set the run status without touching title or completed_at.

        Used to mark a conversation as ``"running"`` at the start of a turn so
        the conversation list can show the generating state.  The final status
        is written by :meth:`upsert` when the turn completes.
        """
        await db.execute(sa_update(Run).where(Run.id == conversation_id).values(status=status))

    @staticmethod
    async def get_all(db: AsyncSession, user_id: str | None = None) -> list[Run]:
        """Get all conversations ordered by creation time, newest first.

        A conversation is created when its first message is sent, so new
        conversations float to the top.  Continuing an existing conversation
        does not move it — its position stays where it was first created.

        Args:
            user_id: Optional filter — when provided, only returns that user's conversations.
        """
        stmt = sa_select(Run).order_by(desc(Run.created_at))
        if user_id is not None:
            stmt = stmt.where(Run.user_id == user_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, conversation_id: str) -> Run | None:
        """Get a single run by its conversation id."""
        result = await db.execute(sa_select(Run).where(Run.id == conversation_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def delete(db: AsyncSession, conversation_id: str) -> None:
        """Delete a run record by conversation id."""
        await db.execute(sa_delete(Run).where(Run.id == conversation_id))
