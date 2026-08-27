"""Shared skill archive installation logic.

This module is a re-implementation (per ADR-010) of
``deerflow.skills.installer``.  The SDK version is **pure
business logic** — no FastAPI/HTTP/config-singleton
dependencies.  Every input (skills root, security scanner,
etc.) is an explicit argument.

Callers that need the backend's LLM-based security scanner
can inject a callback; the default is a conservative
"always block" fallback that rejects executable content and
requires a project-specific scanner to be wired in.

Public surface
--------------
* :class:`SkillAlreadyExistsError` — raised when a skill
  with the same name is already installed
* :class:`SkillSecurityScanError` — raised when a skill
  archive fails security scanning
* :func:`ainstall_skill_from_archive` — async install from a
  ``.zip`` ZIP archive
* :func:`install_skill_from_archive` — sync wrapper
* :func:`is_unsafe_zip_member` / :func:`is_symlink_member`
  / :func:`safe_extract_skill_archive` — low-level helpers
  for ZIP safety
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import posixpath
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from agent_sdk.skills.validation import parse_skill_frontmatter, validate_skill_frontmatter

logger = logging.getLogger(__name__)

#: Sub-directories whose contents should be security-scanned.
_PROMPT_INPUT_DIRS = {"references", "templates"}

#: File suffixes that should be security-scanned when inside a
#: prompt-input directory.
_PROMPT_INPUT_SUFFIXES = frozenset({".json", ".markdown", ".md", ".rst", ".txt", ".yaml", ".yml"})

#: Callback signature for a security scanner.
#:
#: * ``content`` — the file text to screen
#: * ``executable`` — ``True`` when the file lives under
#:   ``scripts/`` (stricter scanning)
#: * ``location`` — human-readable label for diagnostics
#:
#: Must return an object with a ``decision`` attribute (one of
#: ``"allow"`` / ``"warn"`` / ``"block"``) and a ``reason``
#: attribute (a human-readable string).
SecurityScanner = Callable[[str, bool, str], Awaitable[object]]


# ------------------------------------------------------------------
# Errors
# ------------------------------------------------------------------


class SkillAlreadyExistsError(ValueError):
    """Raised when a skill with the same name is already installed."""


class SkillSecurityScanError(ValueError):
    """Raised when a skill archive fails security scanning."""


class MultiSkillArchiveError(ValueError):
    """Raised when an archive bundles more than one skill.

    A ``.zip`` archive must contain exactly one skill.  This error
    carries the names of the offending skill directories so the app
    layer can render a friendly, actionable message.
    """

    def __init__(self, skill_names: list[str]) -> None:
        self.skill_names = skill_names
        super().__init__(f"Archive contains multiple skills: {', '.join(skill_names)}")


# ------------------------------------------------------------------
# ZIP safety helpers
# ------------------------------------------------------------------


def is_unsafe_zip_member(info: zipfile.ZipInfo) -> bool:
    """Return True if the zip member path is absolute or attempts directory traversal."""
    name = info.filename
    if not name:
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    path = PurePosixPath(normalized)
    if path.is_absolute():
        return True
    if PureWindowsPath(name).is_absolute():
        return True
    if ".." in path.parts:
        return True
    return False


def is_symlink_member(info: zipfile.ZipInfo) -> bool:
    """Detect symlinks based on the external attributes stored in the ZipInfo."""
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _should_ignore_archive_entry(path: Path) -> bool:
    """Return True for macOS metadata dirs and dotfiles."""
    return path.name.startswith(".") or path.name == "__MACOSX"


def _topmost_skill_roots(temp_path: Path) -> list[Path]:
    """Return topmost directories that directly contain a ``SKILL.md``.

    A directory is "topmost" when none of its ancestors (within the
    extracted archive) also contains a ``SKILL.md``.  This distinguishes
    "N skills bundled into one archive" (N topmost roots) from a single
    skill that happens to have a nested ``SKILL.md`` (one topmost root —
    that case is rejected later by the security scanner).
    """
    roots: set[Path] = set()
    for skill_md in temp_path.rglob("SKILL.md"):
        rel = skill_md.relative_to(temp_path)
        if any(part.startswith(".") or part == "__MACOSX" for part in rel.parts):
            continue
        roots.add(skill_md.parent)

    return [d for d in sorted(roots, key=lambda p: (len(p.parts), str(p))) if not any(d != other and d.is_relative_to(other) for other in roots)]


def _resolve_skill_dir_from_archive(temp_path: Path) -> Path:
    """Locate the skill root directory from extracted archive contents.

    Filters out macOS metadata (__MACOSX) and dotfiles (.DS_Store).

    Returns:
        Path to the skill directory.

    Raises:
        ValueError: If the archive is empty after filtering.
        MultiSkillArchiveError: If the archive bundles more than one skill
            (several top-level skill dirs, or a wrapper dir holding several
            skill dirs).
    """
    items = [p for p in temp_path.iterdir() if not _should_ignore_archive_entry(p)]
    if not items:
        raise ValueError("Skill archive is empty")

    # Detect multiple skills bundled into one archive.  Scan recursively so
    # we catch both "N top-level dirs each with SKILL.md" and "a single
    # wrapper dir containing N skill dirs" — otherwise these fall through to
    # a confusing "SKILL.md not found" later.
    roots = _topmost_skill_roots(temp_path)
    if len(roots) >= 2:
        raise MultiSkillArchiveError([r.name for r in roots])

    if len(items) == 1 and items[0].is_dir():
        return items[0]
    return temp_path


def safe_extract_skill_archive(
    zip_ref: zipfile.ZipFile,
    dest_path: Path,
    max_total_size: int = 512 * 1024 * 1024,
) -> None:
    """Safely extract a skill archive with security protections.

    Protections:
    - Reject absolute paths and directory traversal (..).
    - Skip symlink entries instead of materialising them.
    - Enforce a hard limit on total uncompressed size (zip bomb defence).

    Raises:
        ValueError: If unsafe members or size limit exceeded.
    """
    dest_root = dest_path.resolve()
    total_written = 0

    for info in zip_ref.infolist():
        if is_unsafe_zip_member(info):
            raise ValueError(f"Archive contains unsafe member path: {info.filename!r}")

        if is_symlink_member(info):
            logger.warning("Skipping symlink entry in skill archive: %s", info.filename)
            continue

        normalized_name = posixpath.normpath(info.filename.replace("\\", "/"))
        member_path = dest_root.joinpath(*PurePosixPath(normalized_name).parts)
        if not member_path.resolve().is_relative_to(dest_root):
            raise ValueError(f"Zip entry escapes destination: {info.filename!r}")
        member_path.parent.mkdir(parents=True, exist_ok=True)

        if info.is_dir():
            member_path.mkdir(parents=True, exist_ok=True)
            continue

        with zip_ref.open(info) as src, member_path.open("wb") as dst:
            while chunk := src.read(65536):
                total_written += len(chunk)
                if total_written > max_total_size:
                    raise ValueError("Skill archive is too large or appears highly compressed.")
                dst.write(chunk)


# ------------------------------------------------------------------
# Scanning helpers
# ------------------------------------------------------------------


def _is_script_support_file(rel_path: Path) -> bool:
    """Return True when *rel_path* lives under ``scripts/``."""
    return bool(rel_path.parts) and rel_path.parts[0] == "scripts"


def _should_scan_support_file(rel_path: Path) -> bool:
    """Return True when *rel_path* should be security-scanned."""
    if _is_script_support_file(rel_path):
        return True
    return bool(rel_path.parts) and rel_path.parts[0] in _PROMPT_INPUT_DIRS and rel_path.suffix.lower() in _PROMPT_INPUT_SUFFIXES


#: Conservative fallback scanner — blocks executable content,
#: warns on everything else.  Projects should replace this with a
#: real LLM-based or rule-based scanner.
async def _default_scan_content(content: str, executable: bool = False, location: str = "SKILL.md") -> object:
    """Default no-op security scanner.

    Always returns ``"allow"`` for non-executable content and
    ``"block"`` for executables (conservative default).  Projects
    should wire a real scanner via the *scan_content* argument of
    :func:`ainstall_skill_from_archive`.
    """
    if executable:
        return _ScanResult("block", "Executable content requires a security scanner; none configured.")
    return _ScanResult("allow", "No security scanner configured.")


class _ScanResult:
    """Minimal result object returned by the default scanner."""

    __slots__ = ("decision", "reason")

    def __init__(self, decision: str, reason: str) -> None:
        self.decision = decision
        self.reason = reason


async def _scan_skill_file_or_raise(
    skill_dir: Path,
    path: Path,
    skill_name: str,
    *,
    executable: bool,
    scan_content: SecurityScanner,
) -> None:
    """Run the security scanner against a single file; raise on block/failure."""
    rel_path = path.relative_to(skill_dir).as_posix()
    location = f"{skill_name}/{rel_path}"
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise SkillSecurityScanError(f"Security scan failed for skill '{skill_name}': {location} must be valid UTF-8") from e

    try:
        result = await scan_content(content, executable, location)
    except Exception as e:
        raise SkillSecurityScanError(f"Security scan failed for {location}: {e}") from e

    decision = getattr(result, "decision", None)
    reason = str(getattr(result, "reason", "") or "No reason provided.")
    if decision == "block":
        if rel_path == "SKILL.md":
            raise SkillSecurityScanError(f"Security scan blocked skill '{skill_name}': {reason}")
        raise SkillSecurityScanError(f"Security scan blocked {location}: {reason}")
    if executable and decision != "allow":
        raise SkillSecurityScanError(f"Security scan rejected executable {location}: {reason}")
    if decision not in {"allow", "warn"}:
        raise SkillSecurityScanError(f"Security scan failed for {location}: invalid scanner decision {decision!r}")


async def _scan_skill_archive_contents_or_raise(
    skill_dir: Path,
    skill_name: str,
    *,
    scan_content: SecurityScanner,
) -> None:
    """Run the security scanner against all installable text and script files."""
    skill_md = skill_dir / "SKILL.md"
    await _scan_skill_file_or_raise(skill_dir, skill_md, skill_name, executable=False, scan_content=scan_content)

    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue

        rel_path = path.relative_to(skill_dir)
        if rel_path == Path("SKILL.md"):
            continue
        if path.name == "SKILL.md":
            raise SkillSecurityScanError(f"Security scan failed for skill '{skill_name}': nested SKILL.md is not allowed at {skill_name}/{rel_path.as_posix()}")
        if not _should_scan_support_file(rel_path):
            continue

        await _scan_skill_file_or_raise(
            skill_dir,
            path,
            skill_name,
            executable=_is_script_support_file(rel_path),
            scan_content=scan_content,
        )


# ------------------------------------------------------------------
# Staged install helpers
# ------------------------------------------------------------------


def _move_staged_skill_into_reserved_target(staging_target: Path, target: Path) -> None:
    """Atomically move a staged skill into its final location.

    Uses a reserve-then-commit strategy: creates the target
    directory first (to reserve the name), then moves children
    in.  If anything fails after reservation, the reserved
    directory is cleaned up.
    """
    installed = False
    reserved = False
    try:
        target.mkdir(mode=0o700)
        reserved = True
        for child in staging_target.iterdir():
            shutil.move(str(child), target / child.name)
        installed = True
    except FileExistsError as e:
        raise SkillAlreadyExistsError(f"Skill '{target.name}' already exists") from e
    finally:
        if reserved and not installed and target.exists():
            shutil.rmtree(target)


# ------------------------------------------------------------------
# Staged skill (for cloud / object-storage upload)
# ------------------------------------------------------------------


@dataclass
class StagedSkill:
    """A validated + security-scanned skill archive, extracted to disk.

    SkillHub is a cloud agent — custom skills are uploaded to object
    storage (OBS), not installed to a local ``custom/`` directory.
    :func:`astage_skill_archive` returns this so the app layer can
    upload each file and then remove *root*.
    """

    name: str
    description: str
    version: str
    root: Path  # temporary extraction root — caller MUST rmtree after upload
    files: list[tuple[str, Path]]  # (rel_path posix, absolute local file path)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def _check_archive_path(path: Path) -> None:
    """Validate that *path* is an existing ``.zip`` file."""
    if not path.is_file():
        if not path.exists():
            raise FileNotFoundError(f"Skill file not found: {path}")
        raise ValueError(f"Path is not a file: {path}")
    if path.suffix != ".zip":
        raise ValueError("File must have .zip extension")


def _extract_skill_archive(path: Path, dest_path: Path) -> Path:
    """Open, safely extract, and resolve the skill directory from *path*."""
    try:
        zf = zipfile.ZipFile(path, "r")
    except FileNotFoundError:
        raise FileNotFoundError(f"Skill file not found: {path}") from None
    except (zipfile.BadZipFile, IsADirectoryError):
        raise ValueError("File is not a valid ZIP archive") from None

    with zf:
        safe_extract_skill_archive(zf, dest_path)
    return _resolve_skill_dir_from_archive(dest_path)


def _validate_skill_dir(skill_dir: Path) -> str:
    """Validate the SKILL.md frontmatter and return the skill name."""
    is_valid, message, skill_name = validate_skill_frontmatter(skill_dir)
    if not is_valid:
        raise ValueError(f"Invalid skill: {message}")
    if not skill_name or "/" in skill_name or "\\" in skill_name or ".." in skill_name:
        raise ValueError(f"Invalid skill name: {skill_name}")
    return skill_name


async def _scan_skill_dir(skill_dir: Path, skill_name: str, scan_content: SecurityScanner) -> None:
    """Run the security scanner over the skill directory; raise on block."""
    await _scan_skill_archive_contents_or_raise(skill_dir, skill_name, scan_content=scan_content)


async def ainstall_skill_from_archive(
    zip_path: str | Path,
    *,
    skills_root: Path,
    scan_content: SecurityScanner | None = None,
) -> dict:
    """Install a skill from a ``.zip`` archive (ZIP).

    Args:
        zip_path: Path to the ``.zip`` file.
        skills_root: Root directory that contains ``custom/``
            (the installed skill is placed under
            ``<skills_root>/custom/<skill_name>/``).
        scan_content: Optional security scanner callback.
            When ``None`` the default conservative scanner is
            used (blocks executables, allows everything else).

    Returns:
        Dict with ``success``, ``skill_name``, ``message``.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is invalid (wrong extension,
            bad ZIP, invalid frontmatter, duplicate name).
        SkillAlreadyExistsError: If a skill with the same name
            is already installed.
        SkillSecurityScanError: If the security scanner blocks
            the archive or scanner execution fails.
    """
    path = Path(zip_path)
    _check_archive_path(path)

    if scan_content is None:
        scan_content = _default_scan_content

    custom_dir = skills_root / "custom"
    custom_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        skill_dir = _extract_skill_archive(path, tmp_path)
        skill_name = _validate_skill_dir(skill_dir)

        target = custom_dir / skill_name
        if target.exists():
            raise SkillAlreadyExistsError(f"Skill '{skill_name}' already exists")

        await _scan_skill_dir(skill_dir, skill_name, scan_content)

        with tempfile.TemporaryDirectory(prefix=f".installing-{skill_name}-", dir=custom_dir) as staging_root:
            staging_target = Path(staging_root) / skill_name
            shutil.copytree(skill_dir, staging_target)
            _move_staged_skill_into_reserved_target(staging_target, target)
        logger.info("Skill %r installed to %s", skill_name, target)

    return {
        "success": True,
        "skill_name": skill_name,
        "message": f"Skill '{skill_name}' installed successfully",
    }


async def astage_skill_archive(
    zip_path: str | Path,
    *,
    scan_content: SecurityScanner | None = None,
) -> StagedSkill:
    """Extract + validate + security-scan a ``.zip`` archive for upload.

    Unlike :func:`ainstall_skill_from_archive`, this does **not** install
    into a local ``custom/`` directory. It extracts to a temporary
    directory (``tempfile.mkdtemp``), validates the frontmatter, runs the
    security scanner, and returns a :class:`StagedSkill` whose *files*
    map each relative path to its absolute on-disk location.

    The caller is responsible for uploading *files* to object storage and
    then removing *root* (``shutil.rmtree``) once done.

    Args:
        zip_path: Path to the ``.zip`` file.
        scan_content: Optional security scanner callback (defaults to the
            conservative fallback when ``None``).

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is invalid (wrong extension, bad ZIP,
            invalid frontmatter).
        SkillSecurityScanError: If the security scanner blocks the archive
            or scanner execution fails.
    """
    path = Path(zip_path)
    _check_archive_path(path)

    if scan_content is None:
        scan_content = _default_scan_content

    root = Path(tempfile.mkdtemp(prefix="skill-upload-"))
    try:
        skill_dir = _extract_skill_archive(path, root)
        skill_name = _validate_skill_dir(skill_dir)
        await _scan_skill_dir(skill_dir, skill_name, scan_content)

        frontmatter = parse_skill_frontmatter(skill_dir)
        description = str(frontmatter.get("description", "")).strip()
        version = str(frontmatter.get("version", "")).strip() or "1.0.0"

        files: list[tuple[str, Path]] = []
        for p in sorted(skill_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(skill_dir)
            if any(part.startswith(".") or part == "__MACOSX" for part in rel.parts):
                continue
            files.append((rel.as_posix(), p))

        return StagedSkill(
            name=skill_name,
            description=description,
            version=version,
            root=root,
            files=files,
        )
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


async def astage_skill_markdown(
    content: str,
    *,
    scan_content: SecurityScanner | None = None,
) -> StagedSkill:
    """Stage a single ``SKILL.md`` Markdown document (no archive) for upload.

    Unlike :func:`astage_skill_archive`, this accepts a bare Markdown
    string (e.g. an uploaded ``.md`` file). It writes the text to a
    temporary directory as ``SKILL.md``, validates the frontmatter,
    runs the security scanner, and returns a :class:`StagedSkill`
    whose *files* contains just ``SKILL.md``.

    Args:
        content: The Markdown document text (UTF-8), including any YAML
            frontmatter.
        scan_content: Optional security scanner callback (defaults to the
            conservative fallback when ``None``).

    Raises:
        ValueError: If the frontmatter is missing or invalid.
        SkillSecurityScanError: If the security scanner blocks the content
            or scanner execution fails.
    """
    if scan_content is None:
        scan_content = _default_scan_content

    root = Path(tempfile.mkdtemp(prefix="skill-upload-"))
    try:
        skill_dir = root
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        skill_name = _validate_skill_dir(skill_dir)
        await _scan_skill_dir(skill_dir, skill_name, scan_content)

        frontmatter = parse_skill_frontmatter(skill_dir)
        description = str(frontmatter.get("description", "")).strip()
        version = str(frontmatter.get("version", "")).strip() or "1.0.0"

        return StagedSkill(
            name=skill_name,
            description=description,
            version=version,
            root=root,
            files=[("SKILL.md", skill_dir / "SKILL.md")],
        )
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def _run_async_install(coro):
    """Bridge async install to sync callers — handles nested event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def install_skill_from_archive(
    zip_path: str | Path,
    *,
    skills_root: Path,
    scan_content: SecurityScanner | None = None,
) -> dict:
    """Install a skill from a ``.zip`` archive (ZIP) — sync wrapper.

    See :func:`ainstall_skill_from_archive` for full documentation.
    """
    return _run_async_install(ainstall_skill_from_archive(zip_path, skills_root=skills_root, scan_content=scan_content))


__all__ = [
    "SkillAlreadyExistsError",
    "SkillSecurityScanError",
    "MultiSkillArchiveError",
    "SecurityScanner",
    "StagedSkill",
    "ainstall_skill_from_archive",
    "astage_skill_archive",
    "install_skill_from_archive",
    "is_symlink_member",
    "is_unsafe_zip_member",
    "safe_extract_skill_archive",
]
