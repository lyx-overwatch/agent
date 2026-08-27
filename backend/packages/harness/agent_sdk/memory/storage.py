"""MemoryStorage ABC.

This is a re-implementation (per ADR-010) of the memory storage
interface. The shape mirrors the original
``backend.agents.memory.storage.MemoryStorage`` so that byte-level
golden fixtures can be compared, but the SDK version is
**generic over the schema type** (``T = MemorySchema``) and does
not import the original ABC.
"""

from __future__ import annotations

import abc
import json
import logging
import threading
from pathlib import Path
from typing import Generic, TypeVar

from agent_sdk.memory.schema import MemorySchema

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=MemorySchema)


class MemoryStorage(abc.ABC, Generic[T]):
    """Abstract base class for memory storage providers.

    Methods are generic over :class:`MemorySchema` so that concrete
    storage backends (file-based, in-memory, Redis, etc.) can be
    type-checked at the boundary.
    """

    @abc.abstractmethod
    def load(self) -> T:
        """Load memory, returning a :class:`MemorySchema` instance."""
        ...

    @abc.abstractmethod
    def reload(self) -> T:
        """Force a reload from the backing store, bypassing any cache."""
        ...

    @abc.abstractmethod
    def save(self, memory: T) -> bool:
        """Persist memory. Returns ``True`` on success."""
        ...


class FileMemoryStorage(MemoryStorage[T]):
    """File-based memory storage.

    Stores the schema as JSON in a single file. The file path is
    provided by the caller; :class:`FileMemoryStorage` does not
    know about base directories or user IDs — those concerns
    belong to a :class:`PathProvider` in the caller.
    """

    def __init__(self, file_path: Path | str, schema_cls: type[T]) -> None:
        self._file_path = Path(file_path)
        self._schema_cls = schema_cls
        self._cache: T | None = None
        self._cache_mtime: float | None = None
        self._lock = threading.Lock()

    def load(self) -> T:
        with self._lock:
            if self._cache is not None and self._cache_mtime is not None:
                try:
                    mtime = self._file_path.stat().st_mtime
                except FileNotFoundError:
                    return self._schema_cls.empty()
                if mtime == self._cache_mtime:
                    return self._cache
            return self._read_from_disk()

    def reload(self) -> T:
        with self._lock:
            return self._read_from_disk()

    def save(self, memory: T) -> bool:
        with self._lock:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            data = memory.to_dict()
            tmp = self._file_path.with_suffix(self._file_path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._file_path)
            try:
                self._cache_mtime = self._file_path.stat().st_mtime
            except FileNotFoundError:
                self._cache_mtime = None
            self._cache = memory
            return True

    def _read_from_disk(self) -> T:
        try:
            raw = self._file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            empty = self._schema_cls.empty()
            self._cache = empty
            self._cache_mtime = None
            return empty
        data = json.loads(raw)
        schema = self._schema_cls.from_dict(data)
        self._cache = schema
        try:
            self._cache_mtime = self._file_path.stat().st_mtime
        except FileNotFoundError:
            self._cache_mtime = None
        return schema
