"""Loguru logging configuration for Heyu Agent.

Provides :func:`setup_logging` to initialise loguru with
environment-aware behaviour:

* **local**:       colourful console (stdout) + structured JSON file
* **test / production**: structured JSON to stdout only (no file handlers)

Also intercepts standard-library ``logging`` so that third-party
packages (e.g. ``agent_sdk``) also flow through loguru.

Call ``setup_logging()`` once at application startup.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from pathlib import Path

from loguru import logger


# ── Interceptor ──────────────────────────────────────────────────────────────
class _InterceptHandler(logging.Handler):
    """Forward standard-library ``logging`` records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = str(record.levelno)

        # Find the caller frame so loguru attributes the message to the
        # original logger, not this forwarding handler.
        frame, depth = logging.currentframe(), 2
        logging_file = os.path.normpath(logging.__file__)
        while frame:
            frame_file = os.path.normpath(frame.f_code.co_filename)
            if frame_file == logging_file:
                frame = frame.f_back
                depth += 1
            else:
                break

        # Forward original metadata explicitly so formatters don't have to
        # rely on call-stack inference (which is brittle on Windows due to
        # path-separator mismatches).
        logger.bind(
            name=record.name,
            function=record.funcName,
            line=record.lineno,
        ).opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


# ── Health-check access-log filter ──────────────────────────────────────────
class _HealthCheckAccessFilter(logging.Filter):
    """Suppress uvicorn access logs for health-check endpoints.

    K8s readiness/liveness/startup probes hit ``/health`` every 10–30s and the
    frontend polls ``/py/api/health``; their ``GET ... 200`` access lines drown
    out the request logs that actually matter.
    """

    _HEALTH_PATHS = (" /health ", " /py/api/health ")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(path in msg for path in self._HEALTH_PATHS)


# ── defaults ─────────────────────────────────────────────────────────────────
_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def _format_exception(record: dict) -> str | None:
    """Return a formatted traceback for a record that carries an exception.

    loguru stores the active exception under ``record["exception"]`` as a
    ``(type, value, traceback)`` tuple whenever ``logger.exception()`` or
    ``logger.opt(exception=...)`` is used.  Without explicitly serialising it
    here, the traceback is silently dropped by custom format functions — which
    made production errors like ``"Failed to upload x.txt to storage"``
    undiagnosable.  Returns ``None`` when the record has no exception.
    """
    exc = record.get("exception")
    if not exc:
        return None
    try:
        exc_type, exc_value, exc_tb = exc
        return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    except Exception:  # noqa: BLE001 — fall back to a repr rather than break logging
        return repr(exc)


def _console_format(record: dict) -> str:
    # loguru's colorizer treats '<' as a colour tag; escape user values.
    # Also escape { } because f-string embedding turns them into
    # Loguru format-placeholders (e.g. JSON audit messages like
    # {"timestamp": ...} would trigger KeyError).
    _esc = lambda v: str(v).replace("<", "\\<").replace("{", "{{").replace("}", "}}")  # noqa: E731
    rid = record["extra"].get("request_id") or "-"
    # Prefer metadata forwarded by _InterceptHandler over call-stack inference.
    name = record["extra"].get("name") or record["name"]
    function = record["extra"].get("function") or record["function"]
    line = record["extra"].get("line") or record["line"]
    return (
        f"<green>{record['time']:YYYY-MM-DD HH:mm:ss}</green> | "
        f"<level>{record['level'].name: <8}</level> | "
        f"<yellow>{rid}</yellow> | "
        f"<cyan>{_esc(name)}</cyan>:"
        f"<cyan>{_esc(function)}</cyan>:"
        f"<cyan>{line}</cyan> - "
        f"<level>{_esc(record['message'])}</level>\n"
    ) + (
        f"{_format_exception(record)}\n"
        if _format_exception(record)
        else ""
    )


def _json_stdout_format(record: dict) -> str:
    """Structured JSON for stdout (test / production environments)."""
    name = record["extra"].get("name") or record["name"]
    function = record["extra"].get("function") or record["function"]
    line = record["extra"].get("line") or record["line"]
    payload = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": name,
        "function": function,
        "line": line,
        "request_id": record["extra"].get("request_id", ""),
        "message": record["message"],
    }
    # Surface the exception traceback so structured logs retain the root cause
    # (boto3/S3 errors, etc.) instead of only a bare message.
    exc_text = _format_exception(record)
    if exc_text:
        payload["exception"] = exc_text
    record["extra"]["json"] = json.dumps(payload, ensure_ascii=False)
    return "{extra[json]}\n"


def _json_file_format(record: dict) -> str:
    """Structured JSON for file output (local development)."""
    return _json_stdout_format(record)


def setup_logging(
    *,
    environment: str = "local",
    debug: bool = False,
    log_dir: Path | None = None,
    log_file: Path | None = None,
    file_rotation: str = "5 MB",
    file_retention: int = 5,
) -> None:
    """Configure loguru sinks based on environment.

    ============  ===========================  ===========================
    Environment   Console (stdout)             Filesystem
    ============  ===========================  ===========================
    local         彩色可读格式，INFO 级别        JSON 轮转文件 ``logs/app.log``
    test          JSON 单行格式，INFO 级别       无（由 Docker json-file 收集）
    production    JSON 单行格式，INFO 级别       无（由 Promtail/Loki 收集）
    ============  ===========================  ===========================

    Args:
        environment: One of ``"local"``, ``"test"``, ``"production"``.
        debug: If True, set console level to DEBUG (local only).
        log_dir: Directory for log files (local only, default ``backend/logs``).
        log_file: Specific file path (local only, default ``{log_dir}/app.log``).
        file_rotation: Log rotation rule (local only).
        file_retention: Number of rotated files to keep (local only).
    """
    logger.remove()

    env_lower = environment.lower()

    if env_lower == "local":
        # ── Local: colourful console + JSON file ──────────────────────
        console_level = "DEBUG" if debug else "INFO"

        logger.add(
            sys.stdout,
            format=_console_format,
            level=console_level,
            colorize=True,
        )

        target_dir = log_dir or _LOG_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = log_file or (target_dir / "app.log")

        logger.add(
            target_file,
            rotation=file_rotation,
            retention=file_retention,
            format=_json_file_format,
            level="INFO",
            encoding="utf-8",
        )
    else:
        # ── Test / Production: JSON stdout only ────────────────────────
        # No file handlers — Docker/K8s captures stdout via json-file
        # driver or Promtail/Loki.  This avoids ephemeral-disk data loss
        # and multi-worker file contention.
        logger.add(
            sys.stdout,
            format=_json_stdout_format,
            level="DEBUG" if debug else "INFO",
            colorize=False,
        )

    # 3. intercept standard-library logging (agent_sdk, third-party libs, etc.)
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    # 4. uvicorn writes access lines via its own StreamHandler (not through
    #    _InterceptHandler), so suppress health-check noise directly on its
    #    "uvicorn.access" logger.  Other request logs are left intact.
    logging.getLogger("uvicorn.access").addFilter(_HealthCheckAccessFilter())
