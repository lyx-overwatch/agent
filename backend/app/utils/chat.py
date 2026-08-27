"""Thread / conversation helpers."""


def make_thread_id(conversation_id: str) -> str:
    """Return the LangGraph thread_id for a conversation.

    The thread_id is simply the ``conversation_id`` — it is already a
    globally unique UUID, so no user prefix is needed. Per-user
    isolation is handled separately by the path provider's ``user_id``
    argument, yielding ``users/{user_id}/threads/{conversation_id}/``.
    """
    return conversation_id


def make_config(thread_id: str) -> dict:
    """Build a LangGraph config dict for a given thread."""
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 150}
