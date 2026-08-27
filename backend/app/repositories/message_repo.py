"""Message repository — pure database CRUD."""

import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Message


class MessageRepo:
    """Data access for the ``messages`` table."""

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        conversation_id: str,
        thread_id: str,
        role: str,
        content: str = "",
        event_type: str | None = None,
        tool_name: str | None = None,
        tool_input: str | None = None,
        tool_output: str | None = None,
        file_metadata: str | None = None,
        description: str | None = None,
        duration_ms: int | None = None,
        created_at=None,
    ) -> Message:
        """Insert a single message record."""
        msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            thread_id=thread_id,
            role=role,
            content=content,
            event_type=event_type,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            file_metadata=file_metadata,
            description=description,
            duration_ms=duration_ms,
            created_at=created_at,
        )
        db.add(msg)
        return msg

    @staticmethod
    async def get_by_conversation(db: AsyncSession, conversation_id: str) -> list[Message]:
        """Get all messages for a conversation, ordered by creation time."""
        result = await db.execute(
            sa_select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def delete_by_conversation(db: AsyncSession, conversation_id: str) -> None:
        """Delete all messages belonging to a conversation."""
        await db.execute(sa_delete(Message).where(Message.conversation_id == conversation_id))
