"""Tests for :func:`agent_sdk.tools.view_image.make_view_image_tool`."""

from __future__ import annotations

from pathlib import Path

from agent_sdk.tools.view_image import (
    _ALLOWED_IMAGE_VIRTUAL_ROOTS,
    _MAX_IMAGE_BYTES,
    _detect_image_mime,
    _is_allowed_virtual_path,
    make_view_image_tool,
)


class TestIsAllowedVirtualPath:
    def test_allowed_roots(self) -> None:
        for root in _ALLOWED_IMAGE_VIRTUAL_ROOTS:
            assert _is_allowed_virtual_path(root) is True
            assert _is_allowed_virtual_path(f"{root}/sub/file.png") is True

    def test_disallowed_paths(self) -> None:
        assert _is_allowed_virtual_path("/etc/passwd") is False
        assert _is_allowed_virtual_path("/mnt/user-data") is False
        assert _is_allowed_virtual_path("/mnt/user-data/workspace_evil") is False
        assert _is_allowed_virtual_path("") is False


class TestDetectImageMime:
    def test_jpeg(self) -> None:
        # JPEG magic: FF D8 FF
        data = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        assert _detect_image_mime(data) == "image/jpeg"

    def test_png(self) -> None:
        data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        assert _detect_image_mime(data) == "image/png"

    def test_webp(self) -> None:
        data = b"RIFF\x00\x00\x00\x00WEBP"
        assert _detect_image_mime(data) == "image/webp"

    def test_unknown(self) -> None:
        assert _detect_image_mime(b"garbage") is None
        assert _detect_image_mime(b"") is None


class TestViewImageTool:
    """Integration tests for the view_image tool."""

    def _make_png(self, tmp_path: Path) -> Path:
        """Create a minimal valid PNG file."""
        # Minimal PNG (1x1 pixel, grey)
        import struct
        import zlib

        def _chunk(chunk_type: bytes, data: bytes) -> bytes:
            chunk = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + chunk + crc

        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)  # 1x1, 8-bit greyscale
        idat = zlib.compress(b"\x00\x80")  # filter=0, pixel=128

        png = (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", idat)
            + _chunk(b"IEND", b"")
        )

        file_path = tmp_path / "test.png"
        file_path.write_bytes(png)
        return file_path

    def _make_jpeg(self, tmp_path: Path) -> Path:
        """Create a minimal valid JPEG file."""
        # Minimal JPEG (just SOI + EOI markers)
        file_path = tmp_path / "test.jpg"
        file_path.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09\x09\x08\x0a\x0c\x14\x0d\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c\x20\x24\x2e\x27\x20\x22\x2c\x23\x1c\x1c\x28\x37\x29\x2c\x30\x31\x34\x34\x34\x1f\x27\x39\x3d\x38\x32\x3c\x2e\x33\x34\x32\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01\x7d\x01\x02\x03\x00\x04\x11\x05\x12\x21\x31\x41\x06\x13\x51\x61\x07\x22\x71\x14\x32\x81\x91\xa1\x08\x23\x42\xb1\xc1\x15\x52\xd1\xf0\x24\x33\x62\x72\x82\x09\x0a\x16\x17\x18\x19\x1a\x25\x26\x27\x28\x29\x2a\x34\x35\x36\x37\x38\x39\x3a\x3b\x3c\x3d\x3e\x3f\x48\x49\x4a\x53\x54\x55\x56\x57\x58\x59\x5a\x63\x64\x65\x66\x67\x68\x69\x6a\x73\x74\x75\x76\x77\x78\x79\x7a\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\xa0\x00\xff\xd9")
        return file_path

    def test_successful_png_read(self, tmp_path: Path) -> None:
        png_path = self._make_png(tmp_path)
        tool = make_view_image_tool(
            path_resolver=lambda vp: str(png_path) if "test.png" in vp else vp
        )
        result = tool.invoke({"image_path": "/mnt/user-data/workspace/test.png"})
        assert "Successfully read image" in result
        assert "image/png" in result

    def test_successful_jpeg_read(self, tmp_path: Path) -> None:
        jpg_path = self._make_jpeg(tmp_path)
        tool = make_view_image_tool(
            path_resolver=lambda vp: str(jpg_path) if "test.jpg" in vp else vp
        )
        result = tool.invoke({"image_path": "/mnt/user-data/uploads/test.jpg"})
        assert "Successfully read image" in result
        assert "image/jpeg" in result

    def test_file_not_found(self) -> None:
        tool = make_view_image_tool()
        result = tool.invoke(
            {"image_path": "/mnt/user-data/workspace/nonexistent.png"}
        )
        assert "not found" in result

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        file_path = tmp_path / "test.gif"
        file_path.write_bytes(b"GIF89a")
        tool = make_view_image_tool(
            path_resolver=lambda vp: str(file_path) if "test.gif" in vp else vp
        )
        result = tool.invoke({"image_path": "/mnt/user-data/workspace/test.gif"})
        assert "Unsupported image format" in result

    def test_path_not_allowed(self) -> None:
        tool = make_view_image_tool()
        result = tool.invoke({"image_path": "/etc/passwd"})
        assert "Only image paths under" in result

    def test_path_is_directory(self, tmp_path: Path) -> None:
        dir_path = tmp_path / "subdir"
        dir_path.mkdir()
        tool = make_view_image_tool(
            path_resolver=lambda vp: str(dir_path) if "subdir" in vp else vp
        )
        result = tool.invoke({"image_path": "/mnt/user-data/workspace/subdir"})
        assert "not a file" in result

    def test_mime_mismatch(self, tmp_path: Path) -> None:
        # Create a PNG file with .jpg extension
        png_path = self._make_png(tmp_path)
        fake_jpg = tmp_path / "fake.jpg"
        fake_jpg.write_bytes(png_path.read_bytes())
        tool = make_view_image_tool(
            path_resolver=lambda vp: str(fake_jpg) if "fake.jpg" in vp else vp
        )
        result = tool.invoke({"image_path": "/mnt/user-data/workspace/fake.jpg"})
        assert "Image contents are" in result

    def test_file_too_large(self, tmp_path: Path) -> None:
        # Create a file larger than _MAX_IMAGE_BYTES
        big_path = tmp_path / "big.png"
        big_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (_MAX_IMAGE_BYTES + 1))
        tool = make_view_image_tool(
            path_resolver=lambda vp: str(big_path) if "big.png" in vp else vp
        )
        result = tool.invoke({"image_path": "/mnt/user-data/outputs/big.png"})
        assert "too large" in result

    def test_path_resolver_error(self) -> None:
        def _failing_resolver(_vp: str) -> str:
            raise ValueError("resolver error")

        tool = make_view_image_tool(path_resolver=_failing_resolver)
        result = tool.invoke({"image_path": "/mnt/user-data/workspace/img.png"})
        assert "Error resolving path" in result

    def test_default_tool_name(self) -> None:
        tool = make_view_image_tool()
        assert tool.name == "view_image"

    def test_custom_tool_name(self) -> None:
        tool = make_view_image_tool(tool_name="custom_view")
        assert tool.name == "custom_view"