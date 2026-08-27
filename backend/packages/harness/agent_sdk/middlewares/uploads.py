"""UploadsMiddleware — inject uploaded-file information into the agent context.

This module is a re-implementation (per ADR-010) of
``deerflow.agents.middlewares.uploads_middleware``.

The middleware reads file metadata from the latest human
message's ``additional_kwargs["files"]`` (set by the frontend
after an upload succeeds) and prepends an ``<uploaded_files>``
block to the last human message so the model knows which
files are available. Historical files (uploaded in earlier
turns of the same thread) are read from the per-thread
uploads directory.

The middleware is brand-neutral in its **logic** but uses
two pieces of *DeerFlow convention* by default:

* The virtual path prefix is ``/mnt/user-data`` — passed in
  by the constructor; a product that wants a different
  prefix overrides it.
* File metadata format (``filename`` / ``size`` / ``path``)
  is the same one the frontend sends. The middleware does
  no business-specific post-processing.

The optional document-outline extraction (used to render
a heading-based "where to look" hint to the model) is left
out of this first cut; it depends on the file-conversion
helpers in :mod:`agent_sdk.utils.file_conversion` (scheduled
for a follow-up batch as an optional extra). The middleware
is fully functional without it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.config import get_config
from langgraph.runtime import Runtime

from agent_sdk.paths.provider import PathProvider
from agent_sdk.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


#: Sentinel prefix used when ``virtual_prefix`` is not supplied.
DEFAULT_VIRTUAL_PREFIX: str = "/mnt/user-data"


class UploadsMiddlewareState(AgentState):
    """State schema for the uploads middleware."""

    uploaded_files: NotRequired[list[dict] | None]


class UploadsMiddleware(AgentMiddleware[UploadsMiddlewareState]):
    """Inject an ``<uploaded_files>`` block into the last human message.

    Args:
        path_provider: Source of the per-thread uploads
            directory.
        virtual_prefix: Virtual path prefix the agent sees
            inside the sandbox (default: ``/mnt/user-data``).
            The middleware builds ``{prefix}/uploads/{filename}``
            paths.
    """

    state_schema = UploadsMiddlewareState

    def __init__(
        self,
        path_provider: PathProvider,
        virtual_prefix: str = DEFAULT_VIRTUAL_PREFIX,
    ) -> None:
        super().__init__()
        self._paths = path_provider
        self._virtual_prefix = virtual_prefix.rstrip("/")

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _format_file_entry(self, file: dict, lines: list[str]) -> None:
        size = int(file.get("size") or 0)
        size_kb = size / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        lines.append(f"- {file['filename']} ({size_str})")
        lines.append(f"  Path: {file['path']}")
        lines.append("")

    def _create_files_message(
        self,
        new_files: list[dict],
        historical_files: list[dict],
    ) -> str:
        """Compose the ``<uploaded_files>...</uploaded_files>`` block."""
        lines: list[str] = ["<uploaded_files>"]
        lines.append("The following files were uploaded in this message:")
        lines.append("")
        if new_files:
            for f in new_files:
                self._format_file_entry(f, lines)
        else:
            lines.append("(empty)")
            lines.append("")

        if historical_files:
            lines.append("The following files were uploaded in previous messages and are still available:")
            lines.append("")
            for f in historical_files:
                self._format_file_entry(f, lines)

        prefix = self._virtual_prefix
        lines.append("To work with these files:")
        lines.append("- Use `grep` to search for keywords when you are not sure which section to look at")
        lines.append(f"  (e.g. `grep(pattern='keyword', path='{prefix}/uploads/')`).")
        lines.append("- Use `glob` to find files by name pattern")
        lines.append(f"  (e.g. `glob(pattern='**/*.md', path='{prefix}/uploads/')`).")
        lines.append("- Only fall back to web search if the file content is clearly insufficient to answer the question.")
        lines.append("</uploaded_files>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # File extraction
    # ------------------------------------------------------------------

    def _files_from_kwargs(
        self,
        message: HumanMessage,
        uploads_dir: Path | None,
    ) -> list[dict] | None:
        """Extract per-file metadata from ``message.additional_kwargs.files``."""
        kwargs_files = (message.additional_kwargs or {}).get("files")
        if not isinstance(kwargs_files, list) or not kwargs_files:
            return None

        files: list[dict] = []
        for f in kwargs_files:
            if not isinstance(f, dict):
                continue
            filename = f.get("filename") or ""
            if not filename or Path(filename).name != filename:
                # Reject paths or empty names — only the bare
                # basename is safe to splice into a sandbox
                # virtual path.
                continue
            if uploads_dir is not None and not (uploads_dir / filename).is_file():
                # Skip files that have been removed since the
                # upload was recorded.
                continue
            files.append(
                {
                    "filename": filename,
                    "size": int(f.get("size") or 0),
                    "path": f"{self._virtual_prefix}/uploads/{filename}",
                    "extension": Path(filename).suffix,
                }
            )
        return files if files else None

    def _historical_files(
        self,
        uploads_dir: Path,
        exclude_names: set[str],
    ) -> list[dict]:
        """List historical uploads (everything in the uploads dir except the new ones)."""
        historical: list[dict] = []
        if not uploads_dir.exists():
            return historical
        for file_path in sorted(uploads_dir.iterdir()):
            if not file_path.is_file():
                continue
            if file_path.name in exclude_names:
                continue
            try:
                stat = file_path.stat()
            except OSError:
                continue
            historical.append(
                {
                    "filename": file_path.name,
                    "size": stat.st_size,
                    "path": f"{self._virtual_prefix}/uploads/{file_path.name}",
                    "extension": file_path.suffix,
                }
            )
        return historical

    # ------------------------------------------------------------------
    # before_agent
    # ------------------------------------------------------------------

    @override
    def before_agent(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
        messages = list(state.get("messages", []))
        if not messages:
            return None

        last_index = len(messages) - 1
        last_message = messages[last_index]
        if not isinstance(last_message, HumanMessage):
            return None

        # Resolve thread_id (context first, then langgraph config).
        thread_id = (runtime.context or {}).get("thread_id")
        if thread_id is None:
            try:
                cfg = get_config()
                thread_id = cfg.get("configurable", {}).get("thread_id")
            except RuntimeError:
                thread_id = None

        uploads_dir: Path | None = None
        if thread_id is not None:
            try:
                uploads_dir = self._paths.get_uploads_dir(thread_id, user_id=get_effective_user_id())
            except Exception:
                # The path provider may validate thread_id and
                # raise. Swallow here so a non-conforming thread
                # id (e.g. an unauth test) does not crash the
                # agent — just skip the uploads injection.
                uploads_dir = None

        new_files = self._files_from_kwargs(last_message, uploads_dir) or []
        new_names = {f["filename"] for f in new_files}
        historical_files = self._historical_files(uploads_dir, new_names) if uploads_dir else []

        if not new_files and not historical_files:
            return None

        files_message = self._create_files_message(new_files, historical_files)

        # Preserve the original content shape (string or list of
        # multimodal blocks). Prepend the files block as a text
        # block in the list case, or as a string in the string
        # case.
        original_content = last_message.content
        if isinstance(original_content, str):
            updated_content = f"{files_message}\n\n{original_content}"
        elif isinstance(original_content, list):
            files_block = {"type": "text", "text": f"{files_message}\n\n"}
            updated_content = [files_block, *original_content]
        else:
            updated_content = original_content

        updated_message = HumanMessage(
            content=updated_content,
            id=last_message.id,
            name=last_message.name,
            additional_kwargs=last_message.additional_kwargs,
        )
        messages[last_index] = updated_message

        logger.debug(
            "UploadsMiddleware: new=%s historical=%s",
            [f["filename"] for f in new_files],
            [f["filename"] for f in historical_files],
        )

        return {
            "uploaded_files": new_files,
            "messages": messages,
        }
