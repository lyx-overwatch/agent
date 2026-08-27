"""ThreadState — the brand-neutral base state schema.

The :class:`ThreadState` TypedDict is what :func:`create_agent`
hands to langgraph by default. It extends
:class:`langchain.agents.AgentState` (which provides
``messages`` and ``jump_to``) with three pieces:

* ``artifacts`` — a list of artifact paths the agent has
  produced. Merged by :func:`merge_artifacts` (preserves order,
  deduplicates).
* ``viewed_images`` — a mapping of ``image_path → {base64,
  mime_type}`` so the ``view_image`` middleware can avoid
  re-loading the same image. Merged by
  :func:`merge_viewed_images`; an empty ``{}`` value clears the
  map (used by the vision middleware after it has rendered the
  images into the LLM context).
* The brand-specific fields (``sandbox``, ``thread_data``,
  ``title``, ``todos``, ``uploaded_files``) are declared as
  ``NotRequired`` so a DeerFlow preset (or any other product)
  can extend this schema without conflicting with the SDK.

The reducers below are *behaviour-equivalent* to
``deerflow.agents.thread_state`` — verified by golden fixtures
in ``tests/runtime/test_thread_state.py`` — but the SDK
re-implements them (per ADR-010) rather than importing the
backend's helpers.
"""

from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict

from langchain.agents import AgentState


class SandboxState(TypedDict):
    """The shape of the ``sandbox`` slot of :class:`ThreadState`.

    Defined as ``NotRequired`` on :class:`ThreadState`; a
    :class:`SandboxMiddleware` fills it in at runtime.
    """

    sandbox_id: NotRequired[str | None]


class ThreadDataState(TypedDict):
    """The shape of the ``thread_data`` slot of :class:`ThreadState`.

    Holds the per-thread filesystem roots that the
    :class:`ThreadDataMiddleware` populates. The fields are
    populated lazily and are ``NotRequired`` so empty state
    (no thread yet) is valid.
    """

    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]


class ViewedImageData(TypedDict):
    """An entry in the ``viewed_images`` reducer.

    Attributes:
        base64: Base64-encoded image bytes.
        mime_type: MIME type, e.g. ``"image/png"``.
    """

    base64: str
    mime_type: str


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Reducer for the ``artifacts`` slot.

    Merges two lists, deduplicates while preserving the order
    of first appearance. Mirrors ``merge_artifacts`` in
    ``deerflow.agents.thread_state`` (per ADR-010 re-implementation,
    not import).
    """
    if existing is None:
        return list(new) if new else []
    if new is None:
        return list(existing)
    # ``dict.fromkeys`` preserves insertion order and dedupes
    return list(dict.fromkeys(list(existing) + list(new)))


def merge_viewed_images(
    existing: dict[str, ViewedImageData] | None,
    new: dict[str, ViewedImageData] | None,
) -> dict[str, ViewedImageData]:
    """Reducer for the ``viewed_images`` slot.

    Special case: if *new* is an empty dict, the reducer clears
    the map. This is the convention the vision middleware uses
    to signal "I have just rendered the images; you can drop
    them from the state."

    For non-empty *new*, the reducer performs a shallow merge
    with new values winning on key collision.
    """
    if existing is None:
        return dict(new) if new else {}
    if new is None:
        return dict(existing)
    if len(new) == 0:
        # Empty new dict = clear signal
        return {}
    return {**existing, **new}


class ThreadState(AgentState):
    """The brand-neutral base state schema for an SDK agent.

    Built on top of :class:`langchain.agents.AgentState` (which
    already provides ``messages`` and ``jump_to``). The slots
    below are the ones the SDK's built-in middlewares read or
    write; downstream products are free to extend this TypedDict
    by composition (langgraph state reducers are compatible
    with subclassing / ``TypedDict`` inheritance).

    Slots:

    * ``artifacts`` — list of artifact paths the agent has
      produced. Merged by :func:`merge_artifacts`.
    * ``viewed_images`` — image path → base64/mime map. Merged
      by :func:`merge_viewed_images`.
    * ``sandbox`` — sandbox metadata (filled in by
      ``SandboxMiddleware``). NotRequired so empty state is
      valid.
    * ``thread_data`` — per-thread filesystem roots (filled in
      by ``ThreadDataMiddleware``). NotRequired.
    * ``title`` — auto-generated thread title. NotRequired.
    * ``todos`` — current todo list. NotRequired.
    * ``uploaded_files`` — per-thread file uploads. NotRequired.
    """

    # Annotated slots use reducers; the rest are NotRequired so
    # products that don't need them can keep state small.
    artifacts: Annotated[list[str], merge_artifacts]
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]
    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]
    title: NotRequired[str | None]
    todos: NotRequired[list[Any] | None]
    uploaded_files: NotRequired[list[dict[str, Any]] | None]
