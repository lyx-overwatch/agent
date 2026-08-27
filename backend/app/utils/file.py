"""File handling utilities for uploads and previews."""

from fastapi import UploadFile

# File extensions that the frontend can preview natively
PREVIEWABLE_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss", ".md", ".log",
    ".sh", ".bash", ".ps1", ".sql", ".r", ".java", ".go", ".rs", ".c", ".cpp", ".h",
    ".pdf",
    ".mp4", ".webm", ".ogg", ".mp3", ".wav", ".flac",
}


async def read_uploaded_files(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    """Read UploadFile objects into (filename, bytes) tuples."""
    result: list[tuple[str, bytes]] = []
    for file in files:
        if file.filename:
            content = await file.read()
            result.append((file.filename, content))
    return result
