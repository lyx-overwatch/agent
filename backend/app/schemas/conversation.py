"""Conversation schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class FileMetadata(BaseModel):
    filename: str
    size: int
    path: str
    extension: str


class CreateConversationResponse(BaseModel):
    conversation_id: str
    thread_id: str
    files: list[FileMetadata] = []


class AddFilesResponse(BaseModel):
    conversation_id: str
    files: list[FileMetadata] = []


class ConversationItem(BaseModel):
    conversation_id: str
    thread_id: str
    title: str | None = None
    status: str
    total_tokens: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class ConversationListResponse(BaseModel):
    conversations: list[ConversationItem]


class ConversationDetail(BaseModel):
    conversation_id: str
    thread_id: str
    title: str | None = None
    status: str
    total_tokens: int = 0


class DeleteConversationResponse(BaseModel):
    conversation_id: str
    deleted: bool


# ── File tree ──────────────────────────────────────────────────────────


class FileTreeNode(BaseModel):
    """递归文件树节点。目录有 children，文件有元数据。"""

    name: str
    type: Literal["directory", "file"]
    virtual_path: str
    children: list[FileTreeNode] | None = None
    size: int | None = None
    extension: str | None = None
    content_type: str | None = None
    previewable: bool = False


class FileTreeRoot(BaseModel):
    """文件树的根节点（outputs / workspace / uploads）。"""

    name: str
    label: str
    type: Literal["directory"] = "directory"
    virtual_path: str
    children: list[FileTreeNode]


class FileTreeResponse(BaseModel):
    conversation_id: str
    roots: list[FileTreeRoot]
