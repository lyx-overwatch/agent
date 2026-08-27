"""Sandbox backend — Docker/Apple Container lifecycle manager.

Provides:
- ``SandboxInfo`` dataclass
- ``SandboxBackend`` ABC
- ``LocalContainerBackend`` — Docker/Apple Container lifecycle manager
- ``RemoteSandboxBackend`` — K8s provisioner HTTP client
- ``wait_for_sandbox_ready`` helper
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import socket
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ── SandboxInfo ────────────────────────────────────────────────────────────


@dataclass
class SandboxInfo:
    """Persisted sandbox metadata for cross-process discovery."""

    sandbox_id: str
    sandbox_url: str
    container_name: str | None = None
    container_id: str | None = None
    created_at: float = field(default_factory=time.time)


# ── Health check ───────────────────────────────────────────────────────────

#: Container ``waiting`` reasons that mean a sandbox Pod will never become
#: ready even though its phase stays ``Pending`` (image pull / config errors).
#: The Pod phase alone only flips to ``Failed`` for a terminated container;
#: these back-off states keep the Pod Pending indefinitely.
_FATAL_WAITING_REASONS = {
    "ImagePullBackOff",
    "ErrImagePull",
    "InvalidImageName",
    "CreateContainerConfigError",
    "CreateContainerError",
    "RunContainerError",
    "CrashLoopBackOff",
}


def wait_for_sandbox_ready(sandbox_url: str, timeout: int = 30) -> bool:
    """Poll sandbox health endpoint until ready or timeout."""
    import requests

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(f"{sandbox_url}/v1/sandbox", timeout=5)
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    return False


# ── Network helpers ────────────────────────────────────────────────────────

_allocated_ports: set[int] = set()


def get_free_port(start_port: int = 8080) -> int:
    """Find a free TCP port starting from *start_port*."""
    for port in range(start_port, start_port + 100):
        if port in _allocated_ports:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                _allocated_ports.add(port)
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found")


def release_port(port: int) -> None:
    """Release a previously allocated port."""
    _allocated_ports.discard(port)


# ── Docker timestamp parsing ───────────────────────────────────────────────


def _parse_docker_timestamp(raw: str) -> float:
    """Parse Docker's ISO 8601 timestamp into a Unix epoch float."""
    if not raw:
        return 0.0
    try:
        s = raw.strip()
        if "." in s:
            dot_pos = s.index(".")
            tz_start = dot_pos + 1
            while tz_start < len(s) and s[tz_start].isdigit():
                tz_start += 1
            frac = s[dot_pos + 1 : tz_start][:6]
            tz_suffix = s[tz_start:]
            s = s[: dot_pos + 1] + frac + tz_suffix
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _extract_host_port(inspect_entry: dict, container_port: int) -> int | None:
    """Extract host port from docker inspect output."""
    try:
        ports = (inspect_entry.get("NetworkSettings") or {}).get("Ports") or {}
        bindings = ports.get(f"{container_port}/tcp") or []
        if bindings:
            host_port = bindings[0].get("HostPort")
            if host_port:
                return int(host_port)
    except (ValueError, TypeError, AttributeError):
        pass
    return None


# ── Mount formatting ───────────────────────────────────────────────────────


def _format_container_mount(runtime: str, host_path: str, container_path: str, read_only: bool) -> list[str]:
    """Format a bind-mount argument for the selected runtime."""
    # Normalize Windows backslashes to forward slashes for Docker compatibility
    normalized_host = host_path.replace("\\", "/")
    if runtime == "docker":
        mount_spec = f"type=bind,src={normalized_host},dst={container_path}"
        if read_only:
            mount_spec += ",readonly"
        return ["--mount", mount_spec]
    mount_spec = f"{normalized_host}:{container_path}"
    if read_only:
        mount_spec += ":ro"
    return ["-v", mount_spec]


def _redact_container_command_for_log(cmd: list[str]) -> list[str]:
    """Return a container command with environment values redacted."""
    redacted: list[str] = []
    redact_next_env = False
    for arg in cmd:
        if redact_next_env:
            if "=" in arg:
                key = arg.split("=", 1)[0]
                redacted.append(f"{key}=<redacted>" if key else "<redacted>")
            else:
                redacted.append(arg)
            redact_next_env = False
            continue
        if arg in {"-e", "--env"}:
            redacted.append(arg)
            redact_next_env = True
            continue
        if arg.startswith("--env="):
            value = arg.removeprefix("--env=")
            if "=" in value:
                key = value.split("=", 1)[0]
                redacted.append(f"--env={key}=<redacted>" if key else "--env=<redacted>")
            else:
                redacted.append(arg)
            continue
        redacted.append(arg)
    return redacted


def _format_container_command_for_log(cmd: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(cmd)
    return shlex.join(cmd)


# ── SandboxBackend ABC ─────────────────────────────────────────────────────


class SandboxBackend(ABC):
    """Abstract base for sandbox provisioning backends."""

    @abstractmethod
    def create(
        self, thread_id: str, sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
    ) -> SandboxInfo: ...

    @abstractmethod
    def destroy(self, info: SandboxInfo) -> None: ...

    @abstractmethod
    def is_alive(self, info: SandboxInfo) -> bool: ...

    @abstractmethod
    def discover(self, sandbox_id: str) -> SandboxInfo | None: ...

    def list_running(self) -> list[SandboxInfo]:
        return []

    def wait_ready(self, info: SandboxInfo, timeout: int = 30) -> str | None:
        """Wait for a sandbox to become ready.

        Returns ``None`` when ready, otherwise a human-readable error string
        describing why it failed.  The default implementation polls the
        sandbox's own HTTP health endpoint; backends that can observe the
        underlying container/Pod state (e.g. :class:`RemoteSandboxBackend`)
        override this to fail fast on terminal failures instead of waiting
        out the full timeout.
        """
        if wait_for_sandbox_ready(info.sandbox_url, timeout=timeout):
            return None
        return (
            f"Sandbox {info.sandbox_id} failed to become ready within "
            f"{timeout}s at {info.sandbox_url}"
        )


# ── LocalContainerBackend ──────────────────────────────────────────────────


class LocalContainerBackend(SandboxBackend):
    """Backend that manages sandbox containers locally using Docker or Apple Container."""

    def __init__(
        self,
        *,
        image: str,
        base_port: int,
        container_prefix: str,
        config_mounts: list,
        environment: dict[str, str],
    ):
        self._image = image
        self._base_port = base_port
        self._container_prefix = container_prefix
        self._config_mounts = config_mounts
        self._environment = environment
        self._runtime = self._detect_runtime()

    @property
    def runtime(self) -> str:
        return self._runtime

    def _detect_runtime(self) -> str:
        import platform

        if platform.system() == "Darwin":
            try:
                result = subprocess.run(
                    ["container", "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    logger.info(f"Detected Apple Container: {result.stdout.strip()}")
                    return "container"
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.info("Apple Container not available, falling back to Docker")
        return "docker"

    # ── SandboxBackend interface ───────────────────────────────────────

    def create(
        self, thread_id: str, sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
    ) -> SandboxInfo:
        container_name = f"{self._container_prefix}-{sandbox_id}"
        _next_start = self._base_port
        container_id: str | None = None
        port: int = 0

        for _attempt in range(10):
            port = get_free_port(start_port=_next_start)
            try:
                container_id = self._start_container(container_name, port, extra_mounts)
                break
            except RuntimeError as exc:
                release_port(port)
                err = str(exc).lower()
                if "port is already allocated" in err or "address already in use" in err:
                    logger.warning(f"Port {port} rejected, retrying with next port")
                    _next_start = port + 1
                    continue
                if "is already in use by container" in err or "conflict. the container name" in err:
                    logger.warning(f"Container {container_name} already in use, attempting discovery")
                    existing = self.discover(sandbox_id)
                    if existing is not None:
                        return existing
                raise
        else:
            raise RuntimeError("Could not start sandbox container: all candidate ports are already allocated")

        sandbox_host = os.environ.get("SKILLHUB_SANDBOX_HOST", os.environ.get("DEER_FLOW_SANDBOX_HOST", "localhost"))
        return SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url=f"http://{sandbox_host}:{port}",
            container_name=container_name,
            container_id=container_id,
        )

    def destroy(self, info: SandboxInfo) -> None:
        stop_target = info.container_id or info.container_name
        if stop_target:
            self._stop_container(stop_target)
        try:
            port = urlparse(info.sandbox_url).port
            if port:
                release_port(port)
        except Exception:
            pass

    def is_alive(self, info: SandboxInfo) -> bool:
        if info.container_name:
            return self._is_container_running(info.container_name)
        return False

    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        container_name = f"{self._container_prefix}-{sandbox_id}"
        if not self._is_container_running(container_name):
            return None
        port = self._get_container_port(container_name)
        if port is None:
            return None
        sandbox_host = os.environ.get("SKILLHUB_SANDBOX_HOST", os.environ.get("DEER_FLOW_SANDBOX_HOST", "localhost"))
        sandbox_url = f"http://{sandbox_host}:{port}"
        if not wait_for_sandbox_ready(sandbox_url, timeout=5):
            return None
        return SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url=sandbox_url,
            container_name=container_name,
        )

    def list_running(self) -> list[SandboxInfo]:
        try:
            result = subprocess.run(
                [
                    self._runtime, "ps",
                    "--filter", f"name={self._container_prefix}-",
                    "--format", "{{.Names}}",
                ],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return []
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return []

        container_names = [
            n.strip() for n in result.stdout.strip().splitlines()
            if n.strip().startswith(self._container_prefix + "-")
        ]
        if not container_names:
            return []

        inspections = self._batch_inspect(container_names)
        sandbox_host = os.environ.get("SKILLHUB_SANDBOX_HOST", os.environ.get("DEER_FLOW_SANDBOX_HOST", "localhost"))
        infos: list[SandboxInfo] = []

        for container_name in container_names:
            data = inspections.get(container_name)
            if data is None:
                continue
            created_at, host_port = data
            sandbox_id = container_name[len(self._container_prefix) + 1:]
            sandbox_url = f"http://{sandbox_host}:{host_port}" if host_port else ""
            infos.append(SandboxInfo(
                sandbox_id=sandbox_id,
                sandbox_url=sandbox_url,
                container_name=container_name,
                created_at=created_at,
            ))

        logger.info(f"Found {len(infos)} running sandbox container(s)")
        return infos

    def _batch_inspect(self, container_names: list[str]) -> dict[str, tuple[float, int | None]]:
        if not container_names:
            return {}
        try:
            result = subprocess.run(
                [self._runtime, "inspect", *container_names],
                capture_output=True, text=True, timeout=15,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return {}
        if result.returncode != 0:
            return {}
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return {}
        out: dict[str, tuple[float, int | None]] = {}
        for entry in payload:
            name = (entry.get("Name") or "").lstrip("/")
            if not name:
                continue
            created_at = _parse_docker_timestamp(entry.get("Created", ""))
            host_port = _extract_host_port(entry, 8080)
            out[name] = (created_at, host_port)
        return out

    # ── Container operations ───────────────────────────────────────────

    def _start_container(
        self, container_name: str, port: int,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
    ) -> str:
        cmd = [self._runtime, "run"]
        if self._runtime == "docker":
            cmd.extend(["--security-opt", "seccomp=unconfined"])
        cmd.extend(["--rm", "-d", "-p", f"{port}:8080", "--name", container_name])

        for key, value in self._environment.items():
            cmd.extend(["-e", f"{key}={value}"])

        for mount in self._config_mounts:
            cmd.extend(_format_container_mount(
                self._runtime, mount.host_path, mount.container_path, mount.read_only,
            ))

        if extra_mounts:
            for host_path, container_path, read_only in extra_mounts:
                cmd.extend(_format_container_mount(
                    self._runtime, host_path, container_path, read_only,
                ))

        cmd.append(self._image)

        log_cmd = _format_container_command_for_log(_redact_container_command_for_log(cmd))
        logger.info(f"Starting container using {self._runtime}: {log_cmd}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            container_id = result.stdout.strip()
            logger.info(f"Started container {container_name} (ID: {container_id})")
            return container_id
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to start sandbox container: {e.stderr}") from e

    def _stop_container(self, container_id: str) -> None:
        try:
            subprocess.run(
                [self._runtime, "stop", container_id],
                capture_output=True, text=True, timeout=10,
            )
            logger.info(f"Stopped container {container_id}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to stop container {container_id}: {e.stderr}")

    def _is_container_running(self, container_name: str) -> bool:
        try:
            result = subprocess.run(
                [self._runtime, "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0 and result.stdout.strip().lower() == "true"
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def _get_container_port(self, container_name: str) -> int | None:
        try:
            result = subprocess.run(
                [self._runtime, "port", container_name, "8080"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                port_str = result.stdout.strip().split(":")[-1]
                return int(port_str)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
            pass
        return None


# ── RemoteSandboxBackend ───────────────────────────────────────────────────


class RemoteSandboxBackend(SandboxBackend):
    """Backend that delegates sandbox lifecycle to a provisioner service.

    All Pod creation, destruction, and discovery are handled by the
    provisioner.  This backend is a thin HTTP client.
    """

    def __init__(self, provisioner_url: str):
        self._provisioner_url = provisioner_url.rstrip("/")

    def create(
        self, thread_id: str, sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
    ) -> SandboxInfo:
        import requests

        try:
            resp = requests.post(
                f"{self._provisioner_url}/api/sandboxes",
                json={"sandbox_id": sandbox_id, "thread_id": thread_id},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return SandboxInfo(sandbox_id=sandbox_id, sandbox_url=data["sandbox_url"])
        except requests.RequestException as exc:
            raise RuntimeError(f"Provisioner create failed: {exc}") from exc

    def destroy(self, info: SandboxInfo) -> None:
        import requests

        try:
            requests.delete(
                f"{self._provisioner_url}/api/sandboxes/{info.sandbox_id}",
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.warning(f"Provisioner destroy failed for {info.sandbox_id}: {exc}")

    def is_alive(self, info: SandboxInfo) -> bool:
        import requests

        try:
            resp = requests.get(
                f"{self._provisioner_url}/api/sandboxes/{info.sandbox_id}",
                timeout=10,
            )
            return resp.ok and resp.json().get("status") == "Running"
        except requests.RequestException:
            return False

    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        import requests

        try:
            resp = requests.get(
                f"{self._provisioner_url}/api/sandboxes/{sandbox_id}",
                timeout=10,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return SandboxInfo(sandbox_id=sandbox_id, sandbox_url=data["sandbox_url"])
        except requests.RequestException as exc:
            logger.debug(f"Provisioner discover failed for {sandbox_id}: {exc}")
            return None

    def list_running(self) -> list[SandboxInfo]:
        """Return all sandboxes currently managed by the provisioner.

        Used by the provider's resident-pool reconciliation at startup to
        re-adopt pre-warmed ``pool-N`` Pods that survive backend restarts.
        """
        import requests

        try:
            resp = requests.get(f"{self._provisioner_url}/api/sandboxes", timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning("Provisioner list failed: %s", exc)
            return []

        infos: list[SandboxInfo] = []
        for item in data.get("sandboxes", []):
            sid = item.get("sandbox_id")
            url = item.get("sandbox_url")
            if not sid or not url:
                continue
            infos.append(SandboxInfo(sandbox_id=sid, sandbox_url=url))
        return infos

    def wait_ready(self, info: SandboxInfo, timeout: int = 30) -> str | None:
        """Wait for a remote sandbox Pod to become ready.

        Polls both the sandbox's own HTTP health endpoint AND the
        provisioner's Pod phase.  If the Pod enters a terminal failure phase
        (``Failed``/``Succeeded`` — a long-running sandbox server should
        never exit), fail fast with the Pod's failure reason instead of
        silently polling a dead HTTP endpoint for the full timeout.

        Threading note: this method is intentionally synchronous.  It is
        invoked from ``_create_sandbox``, which runs on a worker thread
        (langchain executes synchronous ``@tool`` functions via
        ``run_in_executor``), so the ``requests`` + ``sleep`` polling below
        never blocks the event loop that serves ``/health``.  Poll every 2 s
        (not 1 s) to halve the load on the provisioner during the
        potentially minutes-long image-pull window.
        """
        import requests

        deadline = time.time() + timeout
        while time.time() < deadline:
            # 1) Provisioner status — can report a terminal phase long
            #    before the HTTP health probe would time out.
            try:
                resp = requests.get(
                    f"{self._provisioner_url}/api/sandboxes/{info.sandbox_id}",
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    phase = data.get("status") or ""
                    detail = (data.get("detail") or "").strip()
                    if phase in ("Failed", "Succeeded"):
                        reason = detail or f"Pod phase {phase}"
                        return (
                            f"Sandbox {info.sandbox_id} entered terminal "
                            f"phase {phase!r}: {reason}"
                        )
                    # A Pod can remain Pending forever when its container is
                    # stuck in a fatal waiting state (e.g. ImagePullBackOff).
                    # Surface those immediately too.
                    if detail and phase != "Running":
                        for reason in _FATAL_WAITING_REASONS:
                            if reason in detail:
                                return (
                                    f"Sandbox {info.sandbox_id} stuck in "
                                    f"{reason!r}: {detail}"
                                )
            except requests.RequestException:
                pass  # provisioner unreachable — fall back to HTTP probe

            # 2) Sandbox HTTP health probe.
            try:
                r = requests.get(f"{info.sandbox_url}/v1/sandbox", timeout=5)
                if r.status_code == 200:
                    return None
            except requests.RequestException:
                pass

            time.sleep(2)

        return (
            f"Sandbox {info.sandbox_id} failed to become ready within "
            f"{timeout}s at {info.sandbox_url}"
        )