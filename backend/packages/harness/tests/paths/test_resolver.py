"""Unit tests for :class:`agent_sdk.paths.resolver.VirtualPathResolver`.

The resolver is the only place that knows how to translate between
virtual sandbox paths and physical host paths. It mirrors the
``resolve_virtual_path`` behavior in
``backend.config.paths.Paths`` (re-implemented per ADR-010).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_sdk.paths import DefaultPathProvider, VirtualPathResolver
from agent_sdk.presets.deerflow import DeerFlowPathProvider


class TestResolverWithDeerFlow:
    @pytest.fixture
    def setup(self, tmp_path: Path) -> tuple[DeerFlowPathProvider, VirtualPathResolver, str]:
        provider = DeerFlowPathProvider(base_dir=tmp_path)
        return provider, VirtualPathResolver(provider), "t1"

    def test_virtualize_workspace_file(self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]) -> None:
        provider, resolver, tid = setup
        physical = provider.get_workspace_dir(tid) / "notes.md"
        assert resolver.virtualize(physical, tid) == "/mnt/user-data/workspace/notes.md"

    def test_virtualize_uploads_file(self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]) -> None:
        provider, resolver, tid = setup
        physical = provider.get_uploads_dir(tid) / "report.pdf"
        assert resolver.virtualize(physical, tid) == "/mnt/user-data/uploads/report.pdf"

    def test_virtualize_outputs_file(self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]) -> None:
        provider, resolver, tid = setup
        physical = provider.get_outputs_dir(tid) / "result.txt"
        assert resolver.virtualize(physical, tid) == "/mnt/user-data/outputs/result.txt"

    def test_virtualize_nested_file(self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]) -> None:
        provider, resolver, tid = setup
        physical = provider.get_workspace_dir(tid) / "sub" / "deep" / "x.py"
        assert resolver.virtualize(physical, tid) == "/mnt/user-data/workspace/sub/deep/x.py"

    def test_virtualize_outside_user_data_passes_through(
        self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]
    ) -> None:
        _, resolver, tid = setup
        outside = Path("/etc/hostname")
        assert resolver.virtualize(outside, tid) == str(outside)

    def test_resolve_workspace_path(self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]) -> None:
        provider, resolver, tid = setup
        physical = resolver.resolve("/mnt/user-data/workspace/notes.md", tid)
        assert physical == (provider.get_workspace_dir(tid) / "notes.md").resolve()

    def test_resolve_uploads_path(self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]) -> None:
        provider, resolver, tid = setup
        physical = resolver.resolve("/mnt/user-data/uploads/file.pdf", tid)
        assert physical == (provider.get_uploads_dir(tid) / "file.pdf").resolve()

    def test_resolve_outputs_path(self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]) -> None:
        provider, resolver, tid = setup
        physical = resolver.resolve("/mnt/user-data/outputs/chart.png", tid)
        assert physical == (provider.get_outputs_dir(tid) / "chart.png").resolve()

    def test_resolve_non_virtual_path_passes_through(
        self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]
    ) -> None:
        _, resolver, tid = setup
        # A path that does not start with the virtual prefix is returned
        # as a Path unchanged.
        assert resolver.resolve("/etc/hostname", tid) == Path("/etc/hostname")

    def test_resolve_rejects_similar_prefix(self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]) -> None:
        # ``/mnt/user-dataX/...`` must NOT be treated as a match for
        # ``/mnt/user-data``. The check uses a segment-boundary
        # comparison rather than a naive prefix match.
        _, resolver, tid = setup
        # Should pass through as a regular Path, not be resolved.
        result = resolver.resolve("/mnt/user-dataX/notes.md", tid)
        assert result == Path("/mnt/user-dataX/notes.md")

    def test_resolve_rejects_path_traversal(
        self, setup: tuple[DeerFlowPathProvider, VirtualPathResolver, str]
    ) -> None:
        _, resolver, tid = setup
        with pytest.raises(ValueError, match="path traversal"):
            resolver.resolve("/mnt/user-data/../etc/passwd", tid)


class TestResolverWithDefaultProvider:
    @pytest.fixture
    def setup(self, tmp_path: Path) -> tuple[DefaultPathProvider, VirtualPathResolver, str]:
        provider = DefaultPathProvider(base_dir=tmp_path)
        return provider, VirtualPathResolver(provider), "t1"

    def test_virtual_prefix_is_brand_neutral(self, setup: tuple[DefaultPathProvider, VirtualPathResolver, str]) -> None:
        _, resolver, _ = setup
        assert resolver.virtual_prefix == "/agent-data"

    def test_virtualize_uses_default_prefix(
        self, setup: tuple[DefaultPathProvider, VirtualPathResolver, str]
    ) -> None:
        provider, resolver, tid = setup
        physical = provider.get_workspace_dir(tid) / "x.txt"
        assert resolver.virtualize(physical, tid) == "/agent-data/workspace/x.txt"

    def test_resolve_uses_default_prefix(
        self, setup: tuple[DefaultPathProvider, VirtualPathResolver, str]
    ) -> None:
        provider, resolver, tid = setup
        physical = resolver.resolve("/agent-data/outputs/x.txt", tid)
        assert physical == (provider.get_outputs_dir(tid) / "x.txt").resolve()


class TestResolverRoundTrip:
    """Resolving then virtualizing a path should return the same string."""

    @pytest.mark.parametrize("subdir", ["workspace", "uploads", "outputs"])
    def test_round_trip(self, tmp_path: Path, subdir: str) -> None:
        provider = DeerFlowPathProvider(base_dir=tmp_path)
        resolver = VirtualPathResolver(provider)
        tid = "abc"
        original_virtual = f"/mnt/user-data/{subdir}/file.txt"
        physical = resolver.resolve(original_virtual, tid)
        again_virtual = resolver.virtualize(physical, tid)
        assert again_virtual == original_virtual
