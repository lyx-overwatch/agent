"""Storage diagnostic request schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StorageUploadRequest(BaseModel):
    """Body for the ``POST /storage/upload`` diagnostic endpoint."""

    content: str = Field(default="hello from skillhub storage test", description="测试文件内容")
    name: str = Field(default="test.txt", description="文件名")
    prefix: str = Field(default="test", description="对象 key 前缀（留空则不带头缀）")
