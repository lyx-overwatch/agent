"""view_image tool factory.

Reads an image file, validates its format, and returns base64-encoded
data for the LLM to consume.  The :class:`ViewImageMiddleware` later
injects the result into the message list.

This is a re-implementation (per ADR-010) of
``deerflow.tools.builtins.view_image_tool``.
"""

from __future__ import annotations

import base64
import mimetypes
from collections.abc import Callable
from pathlib import Path

from langchain.tools import BaseTool, ToolRuntime, tool

# Allowed virtual roots for image paths.
_ALLOWED_IMAGE_VIRTUAL_ROOTS = (
    "/mnt/user-data/workspace",
    "/mnt/user-data/uploads",
    "/mnt/user-data/outputs",
)
_ALLOWED_IMAGE_VIRTUAL_ROOTS_TEXT = ", ".join(_ALLOWED_IMAGE_VIRTUAL_ROOTS)

# Maximum image size: 20 MiB.
_MAX_IMAGE_BYTES = 20 * 1024 * 1024

# Extension → MIME mapping (subset of supported formats).
_EXTENSION_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_SUPPORTED_FORMATS_TEXT = ", ".join(_EXTENSION_TO_MIME)


def _is_allowed_virtual_path(image_path: str) -> bool:
    """Check that *image_path* is under one of the allowed virtual roots."""
    return any(
        image_path == root or image_path.startswith(f"{root}/")
        for root in _ALLOWED_IMAGE_VIRTUAL_ROOTS
    )


def _detect_image_mime(image_data: bytes) -> str | None:
    """Detect MIME type from magic bytes."""
    if image_data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if (
        len(image_data) >= 12
        and image_data.startswith(b"RIFF")
        and image_data[8:12] == b"WEBP"
    ):
        return "image/webp"
    return None


def make_view_image_tool(
    tool_name: str = "view_image",
    *,
    path_resolver: Callable[[str], str] | None = None,
) -> BaseTool:
    """Create a ``view_image`` tool.

    Args:
        tool_name: The name registered with the LLM. Default
            ``"view_image"``.
        path_resolver: Optional callable that translates a
            virtual path (e.g. ``/mnt/user-data/workspace/img.png``)
            into a physical filesystem path.  If ``None`` the
            virtual path is treated as a physical path (useful
            for testing or when the caller already maps paths
            before invoking the tool).
    """

    @tool(tool_name, parse_docstring=False)
    def view_image(
        image_path: str,
        runtime: ToolRuntime | None = None,
    ) -> str:
        """Read an image file and make it available for display.

        Use this tool to read an image file and make it available
        for display.

        When to use the view_image tool:
        - When you need to view an image file.

        When NOT to use the view_image tool:
        - For non-image files (use present_files instead)
        - For multiple files at once (use present_files instead)

        Args:
            image_path: Absolute virtual path to the image file.
        """
        if not _is_allowed_virtual_path(image_path):
            return (
                f"Error: Only image paths under "
                f"{_ALLOWED_IMAGE_VIRTUAL_ROOTS_TEXT} are allowed"
            )

        # Resolve virtual → physical
        if path_resolver is not None:
            try:
                physical_path = path_resolver(image_path)
            except Exception as exc:
                return f"Error resolving path: {exc}"
        else:
            physical_path = image_path

        path = Path(physical_path)

        # Validate existence
        if not path.exists():
            return f"Error: Image file not found: {image_path}"
        if not path.is_file():
            return f"Error: Path is not a file: {image_path}"

        # Validate extension
        expected_mime = _EXTENSION_TO_MIME.get(path.suffix.lower())
        if expected_mime is None:
            return (
                f"Error: Unsupported image format: {path.suffix}. "
                f"Supported formats: {_SUPPORTED_FORMATS_TEXT}"
            )

        # MIME from extension
        mime_type, _ = mimetypes.guess_type(physical_path)
        if mime_type is None:
            mime_type = expected_mime

        # Check file size
        try:
            image_size = path.stat().st_size
        except OSError as exc:
            return f"Error reading image metadata: {exc}"
        if image_size > _MAX_IMAGE_BYTES:
            return (
                f"Error: Image file is too large: {image_size} bytes. "
                f"Maximum supported size is {_MAX_IMAGE_BYTES} bytes"
            )

        # Read image data
        try:
            image_data = path.read_bytes()
        except Exception as exc:
            return f"Error reading image file: {exc}"

        # Detect MIME from magic bytes
        detected_mime = _detect_image_mime(image_data)
        if detected_mime is None:
            return "Error: File contents do not match a supported image format"
        if detected_mime != expected_mime:
            return (
                f"Error: Image contents are {detected_mime}, "
                f"but file extension indicates {expected_mime}"
            )
        mime_type = detected_mime

        # Encode
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        # If we have a runtime, update viewed_images state
        if runtime is not None:
            try:
                state = runtime.state
                viewed_images = state.get("viewed_images", {}) if state else {}
                if isinstance(viewed_images, dict):
                    viewed_images = {**viewed_images, image_path: {
                        "base64": image_base64,
                        "mime_type": mime_type,
                    }}
                    # Write back via ToolRuntime (best-effort)
                    try:
                        state["viewed_images"] = viewed_images  # type: ignore[index]
                    except (TypeError, KeyError):
                        pass
            except Exception:
                pass  # best-effort state update

        return (
            f"Successfully read image: {image_path}\n"
            f"Format: {mime_type}\n"
            f"Size: {image_size} bytes\n"
            f"Base64 length: {len(image_base64)} chars"
        )

    return view_image


# Re-export helper for test visibility
__all__ = [
    "make_view_image_tool",
    "_is_allowed_virtual_path",
    "_detect_image_mime",
    "_ALLOWED_IMAGE_VIRTUAL_ROOTS",
    "_MAX_IMAGE_BYTES",
    "_EXTENSION_TO_MIME",
]