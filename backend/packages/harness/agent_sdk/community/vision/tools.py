"""Image-understanding tool — offloads image content to a multimodal model.

This is a SkillHub community tool that plugs a *real* multimodal model into
the agent loop without requiring the main (pure-text) chat model to accept
image input:

1. Locate the image bytes through the sandbox the agent is running in (the
   same source the ``read_file`` tool reads from) rather than the host
   filesystem, so it works for both local and Docker/K8s sandboxes.
2. Read / validate the image bytes and base64-encode them.
3. Ask a dedicated vision-capable model to describe the image and return the
   resulting text to the main LLM.

The main chat model therefore never sees the image itself — no base64 in its
context, and no dependency on the main model supporting image input. This is
deliberately distinct from the SDK's :func:`agent_sdk.tools.view_image.make_view_image_tool`
(which only base64-injects the image via ``ViewImageMiddleware`` without
actually *understanding* it).
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from agent_sdk.sandbox.base import SandboxProvider
from agent_sdk.sandbox.path_resolver import SandboxPathResolver
from langchain.tools import BaseTool, ToolRuntime, tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

#: Maximum image size accepted by the tool (20 MiB).
_MAX_IMAGE_BYTES = 20 * 1024 * 1024

#: Extension → MIME mapping for the formats the tool accepts.
_EXTENSION_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

#: Prompt sent to the vision model alongside the image.
_DESCRIBE_PROMPT = (
    "请详细描述这张图片的内容，包括主体、场景、图中出现的文字（如有），"
    "以及任何值得注意的细节。用与用户相同的语言回答。"
)


def _acquire_sandbox(runtime: ToolRuntime, sandbox_provider: SandboxProvider):
    """Get or acquire the per-thread sandbox from *runtime*.

    Mirrors :func:`agent_sdk.sandbox.tools._ensure_sandbox` but is
    self-contained so this community tool stays free of a dependency on the
    sandbox-tools internals.  Returns the sandbox instance, or ``None`` when
    a ``thread_id`` cannot be resolved.
    """
    # 1) Already bound in runtime state — reuse it.
    sandbox_state = runtime.state.get("sandbox") if runtime.state is not None else None
    if sandbox_state is not None:
        sandbox_id = sandbox_state.get("sandbox_id")
        if sandbox_id is not None:
            sandbox = sandbox_provider.get(sandbox_id)
            if sandbox is not None:
                return sandbox

    # 2) Resolve thread_id (context → config → thread_data fallback).
    thread_id: str | None = None
    if runtime.context is not None:
        thread_id = runtime.context.get("thread_id")
    if thread_id is None and runtime.config is not None:
        thread_id = runtime.config.get("configurable", {}).get("thread_id")
    if thread_id is None and runtime.state is not None:
        from agent_sdk.utils.thread import extract_thread_id

        thread_data = runtime.state.get("thread_data")
        thread_id = extract_thread_id(thread_data) if thread_data else None

    if thread_id is None:
        return None

    # 3) Acquire + stash so later tool calls reuse the same sandbox.
    try:
        sandbox_id = sandbox_provider.acquire(thread_id)
    except Exception:
        logger.warning("Failed to acquire sandbox for view_image", exc_info=True)
        return None

    sandbox = sandbox_provider.get(sandbox_id)
    if sandbox is not None and runtime.state is not None:
        runtime.state["sandbox"] = {"sandbox_id": sandbox_id}
    return sandbox


def make_view_image_tool(
    resolver: SandboxPathResolver,
    model: BaseChatModel,
    *,
    sandbox_provider: SandboxProvider | None = None,
    max_image_bytes: int = _MAX_IMAGE_BYTES,
) -> BaseTool:
    """Build the ``view_image`` tool.

    Args:
        resolver: Resolves sandbox virtual paths to host paths.
        model: A multimodal chat model used to describe the image.
        sandbox_provider: The sandbox backend the agent's file tools use.
            When provided, image bytes are read through the sandbox (the
            correct behaviour for Docker/K8s sandboxes). When ``None``, the
            tool falls back to reading from the host filesystem via
            *resolver* (legacy behaviour, only valid for local sandboxes).
        max_image_bytes: Upper bound on the image size accepted.
    """

    @tool("view_image", parse_docstring=True)
    def view_image(image_path: str, runtime: ToolRuntime) -> str:
        """Understand the content of an image using a multimodal vision model.

        Use this tool when the user uploads an image or asks about the content
        of an image — it returns a natural-language description of what the
        image shows. Do NOT install OCR libraries (tesseract / pytesseract) or
        write image-to-text scripts to read an image; this tool is the correct
        way to understand image content.

        Args:
            image_path: Absolute virtual path to the image file, e.g.
                /mnt/user-data/uploads/photo.png or
                /mnt/user-data/workspace/pptx_images/slide_01.jpg
        """
        if runtime.state is None:
            return "Error: tool runtime state not available for image access"
        thread_data = runtime.state.get("thread_data")

        # ── Read image bytes ─────────────────────────────────────────
        if sandbox_provider is not None:
            sandbox = _acquire_sandbox(runtime, sandbox_provider)
            if sandbox is None:
                return "Error: sandbox not available for image access"

            from agent_sdk.sandbox.local.provider import LocalSandbox

            is_local = isinstance(sandbox, LocalSandbox)
            try:
                if is_local:
                    # Local sandbox shares the host filesystem — translate the
                    # virtual path to a host path before reading.
                    if thread_data is None:
                        return "Error: thread data not available for image access"
                    read_path = resolver.resolve_and_validate_user_data_path(image_path, thread_data)
                else:
                    # Remote sandbox (Docker/K8s) sees the virtual path
                    # directly; only validate it against the policy.
                    resolver.validate_local_tool_path(image_path, thread_data, read_only=True)
                    read_path = image_path
                image_data = sandbox.read_file_bytes(read_path)
            except FileNotFoundError:
                return f"Error: Image file not found: {image_path}"
            except PermissionError as exc:
                return f"Error: {exc}"
            except Exception as exc:
                return f"Error reading image file: {exc}"
        else:
            # Legacy fallback — read from the host filesystem via the resolver.
            if not thread_data:
                return "Error: thread data not available for image access"
            try:
                host_path = resolver.resolve_and_validate_user_data_path(image_path, thread_data)
            except Exception as exc:
                return f"Error resolving image path: {exc}"

            path = Path(host_path)
            if not path.is_file():
                return f"Error: Image file not found: {image_path}"
            try:
                image_data = path.read_bytes()
            except Exception as exc:
                return f"Error reading image file: {exc}"

        if not image_data:
            return f"Error: Image file is empty: {image_path}"

        mime_type = _EXTENSION_TO_MIME.get(Path(image_path).suffix.lower())
        if mime_type is None:
            return (
                f"Error: Unsupported image format: {Path(image_path).suffix}. "
                f"Supported formats: jpg/jpeg/png/webp"
            )

        if len(image_data) > max_image_bytes:
            return (
                f"Error: Image file is too large: {len(image_data)} bytes. "
                f"Maximum supported size is {max_image_bytes} bytes"
            )

        image_base64 = base64.b64encode(image_data).decode("utf-8")

        try:
            message = HumanMessage(
                content=[
                    {"type": "text", "text": _DESCRIBE_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                    },
                ]
            )
            response = model.invoke([message])
        except Exception as exc:
            return f"Error: vision model failed to analyse the image: {exc}"

        content = getattr(response, "content", None) or str(response)
        return str(content)

    return view_image


__all__ = ["make_view_image_tool"]
