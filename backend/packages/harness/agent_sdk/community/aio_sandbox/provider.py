"""AioSandboxProvider — Docker-based sandbox provider for agent_sdk.

Manages AIO sandbox Docker containers with warm-pool reuse, idle
timeout, cross-process discovery, and graceful shutdown.

Usage::

    from agent_sdk.community.aio_sandbox import AioSandboxProvider

    provider = AioSandboxProvider(
        thread_base_dir=Path("./workspace"),
    )
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import hashlib
import logging
import os
import shlex
import signal
import threading
import time
import uuid
from pathlib import Path
from typing import Any, override

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

from agent_sdk.community.aio_sandbox.backend import (
    LocalContainerBackend,
    RemoteSandboxBackend,
    SandboxBackend,
    SandboxInfo,
)
from agent_sdk.community.aio_sandbox.sandbox import AioSandbox
from agent_sdk.runtime.user_context import get_effective_user_id
from agent_sdk.sandbox.base import Sandbox, SandboxProvider

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────────────
# DEFAULT_IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"
DEFAULT_IMAGE = "swr.cn-south-1.myhuaweicloud.com/fintech-aigc/docker-sandbox:20260813V1.0"
DEFAULT_PORT = 8080
DEFAULT_CONTAINER_PREFIX = "skillhub-sandbox"
DEFAULT_IDLE_TIMEOUT = 600
DEFAULT_REPLICAS = 3
DEFAULT_READINESS_TIMEOUT = 180
VIRTUAL_PATH_PREFIX = "/mnt/user-data"
IDLE_CHECK_INTERVAL = 60

# ── Resident pool (K8s provisioner mode only) ─────────────────────────────
# When provisioner_url is set, the provider can reuse a fixed set of resident
# sandbox Pods instead of creating one per thread.  ``pool_size`` is the number
# of resident Pods (0 disables pooling); ``pool_lease_timeout`` is how long an
# acquire waits (queues) when every Pod is busy before giving up.
DEFAULT_POOL_SIZE = 0
DEFAULT_POOL_LEASE_TIMEOUT = 60
# Recommended minimum idle timeout if an operator explicitly opts into the
# pool-mode crash-leak guard (see the bump logic in ``__init__``).  Pool mode's
# forced idle-return is *destructive* — it clears the slot's volume — so it
# defaults to OFF: the per-run release in the persister already returns every
# slot, and a process crash is recovered by re-adopting the resident Pods at
# startup.  This constant is only a threshold for warning about dangerously
# small explicit values.
DEFAULT_POOL_IDLE_TIMEOUT = 3600
POOL_ID_PREFIX = "pool-"

# Clears the *entire* user-data volume — every top-level entry, including any
# custom directory a tenant created outside the three defaults — so nothing a
# tenant wrote can leak to the next tenant.  The volume root is made
# world-writable by the init container (``chmod 777 /mnt/user-data``), so the
# non-root shell can unlink any top-level entry regardless of which uid created
# it.  ``find -delete`` runs depth-first and removes dotfiles too.
#
# Deliberately does NOT touch /tmp, /var/tmp or /dev/shm: those are system temp
# dirs in the container's own filesystem, not tenant data.  They are bounded by
# the Pod's ephemeral-storage limit (kubelet evicts on overflow) and carry no
# data that needs cross-tenant isolation — wiping them would only risk the
# sandbox server's own runtime files without adding any isolation.
#
# The trailing guard prints ``CLEAR_OK`` only when the user-data volume ends up
# empty, so callers can detect a partial clear and destroy the Pod instead.
POOL_CLEAR_COMMAND = (
    "find /mnt/user-data -mindepth 1 -delete 2>/dev/null; "
    'test -z "$(find /mnt/user-data -mindepth 1 2>/dev/null)" '
    "&& echo CLEAR_OK"
)


# ── File locking (cross-process) ───────────────────────────────────────────


def _lock_file_exclusive(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)


def _unlock_file(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        return
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


# ── Provider ────────────────────────────────────────────────────────────────


class AioSandboxProvider(SandboxProvider):
    """Docker-based sandbox provider using the AIO sandbox image.

    Architecture
    ------------
    Uses a pluggable :class:`SandboxBackend` (local container or remote
    provisioner).  The local backend manages Docker containers directly
    via subprocess; the remote backend delegates to a K8s provisioner.

    Features
    --------
    - Warm pool: released sandboxes stay alive for fast reclaim
    - Idle timeout: background thread destroys idle containers
    - Orphan reconciliation: adopts containers from previous processes
    - Cross-process discovery: deterministic container names
    - Thread-specific volume mounts (workspace, uploads, outputs)

    Parameters
    ----------
    image: AIO sandbox container image.
    base_port: Starting port for local container port allocation.
    container_prefix: Prefix for Docker container names.
    idle_timeout: Seconds before idle containers are destroyed (0 = disabled).
    replicas: Max concurrent containers (soft limit).
    mounts: Static volume mounts from config.
    environment: Environment variables for containers.
    thread_base_dir: Per-thread workspace/uploads/outputs root (container view).
    host_base_dir: Host-side counterpart of ``thread_base_dir`` for volume mount
        sources in Docker-out-of-Docker (DooD) deployments. When unset, the
        provider reads ``SKILLHUB_HOST_BASE_DIR`` from the environment, then
        falls back to ``thread_base_dir`` (no translation, fine for native /
        non-container deployments).
    provisioner_url: If set, use RemoteSandboxBackend instead of local Docker.
    pool_size: Number of resident Pods to reuse (K8s provisioner mode only;
        0 disables pooling and falls back to per-thread Pods).
    pool_lease_timeout: Seconds to queue when every resident Pod is busy.
    """

    uses_thread_data_mounts: bool = True

    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        base_port: int = DEFAULT_PORT,
        container_prefix: str = DEFAULT_CONTAINER_PREFIX,
        idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
        replicas: int = DEFAULT_REPLICAS,
        readiness_timeout: int = DEFAULT_READINESS_TIMEOUT,
        mounts: list | None = None,
        environment: dict[str, str] | None = None,
        thread_base_dir: Path | str | None = None,
        host_base_dir: Path | str | None = None,
        provisioner_url: str = "",
        storage: Any = None,
        pool_size: int = DEFAULT_POOL_SIZE,
        pool_lease_timeout: int = DEFAULT_POOL_LEASE_TIMEOUT,
    ) -> None:
        self._lock = threading.Lock()
        self._sandboxes: dict[str, AioSandbox] = {}
        self._sandbox_infos: dict[str, SandboxInfo] = {}
        self._thread_sandboxes: dict[str, str] = {}
        self._thread_locks: dict[str, threading.Lock] = {}
        self._last_activity: dict[str, float] = {}
        self._warm_pool: dict[str, tuple[SandboxInfo, float]] = {}
        self._shutdown_called = False
        self._idle_stop = threading.Event()
        self._idle_thread: threading.Thread | None = None
        self._storage = storage  # Optional remote storage for workspace restore

        # ── Resident pool state (K8s provisioner mode only) ─────────
        self._pool_size = max(0, int(pool_size))
        self._pool_lease_timeout = max(0, int(pool_lease_timeout))
        self._pool_cond = threading.Condition()
        self._idle_pool: list[str] = []  # resident Pod ids free to lease
        self._pool_slots: set[str] = set()  # live OR being-created pool Pod ids

        self._config = {
            "image": image,
            "port": base_port,
            "container_prefix": container_prefix,
            "idle_timeout": idle_timeout,
            "replicas": replicas,
            "readiness_timeout": readiness_timeout,
            "mounts": mounts or [],
            "environment": self._resolve_env_vars(environment or {}),
            "provisioner_url": provisioner_url,
        }
        self._thread_base_dir = Path(thread_base_dir).resolve() if thread_base_dir else Path("../agent-test").resolve()

        # ── DooD path translation ──────────────────────────────────
        # When running inside Docker with a mounted Docker socket
        # (DooD), the container-side ``thread_base_dir`` differs from
        # the host-side path that the Docker daemon resolves bind
        # mounts against. Volume mount sources MUST use the host
        # path; otherwise the daemon returns "invalid mount
        # configuration".
        #
        # Priority: explicit constructor arg > SKILLHUB_HOST_BASE_DIR
        # env var > thread_base_dir (no translation, fine for native).
        if host_base_dir is not None:
            self._host_base_dir = Path(host_base_dir).resolve()
        elif env_host := os.environ.get("SKILLHUB_HOST_BASE_DIR"):
            self._host_base_dir = Path(env_host).resolve()
            logger.info(
                "AioSandboxProvider: using SKILLHUB_HOST_BASE_DIR={} for volume mounts "
                "(container-side thread_base_dir={})",
                self._host_base_dir, self._thread_base_dir,
            )
        else:
            self._host_base_dir = self._thread_base_dir

        self._backend: SandboxBackend = self._create_backend()

        # Pooling is only meaningful for the remote K8s provisioner backend
        # (resident Pods).  Local Docker uses bind-mounts + warm pool instead.
        self._pool_enabled = self._pool_size > 0 and isinstance(self._backend, RemoteSandboxBackend)

        # Pool mode's forced idle-return is destructive (it clears a slot's
        # volume), so it must never fire on a still-running turn.  The normal
        # release path (persister's per-run finally) already returns every slot,
        # and a process crash is recovered by re-adopting the resident Pods at
        # startup — so the force-return guard is redundant in normal operation
        # and only adds risk.  We therefore leave it DISABLED by default and
        # only warn when an explicit value is dangerously small.
        if self._pool_enabled:
            if idle_timeout == DEFAULT_IDLE_TIMEOUT:
                self._config["idle_timeout"] = 0
                logger.warning(
                    "Pool mode: idle force-return disabled (default idle_timeout=%d). "
                    "Set an explicit large sandbox.idle_timeout to opt into the crash-leak guard.",
                    DEFAULT_IDLE_TIMEOUT,
                )
            elif 0 < idle_timeout < DEFAULT_POOL_IDLE_TIMEOUT:
                logger.warning(
                    "Pool mode: idle_timeout=%d is below the safe minimum %ds — "
                    "a long-running turn could have its files cleared mid-run.",
                    idle_timeout, DEFAULT_POOL_IDLE_TIMEOUT,
                )

        atexit.register(self.shutdown)
        self._register_signal_handlers()
        if self._pool_enabled:
            self._populate_idle_pool()
        else:
            self._reconcile_orphans()

        if self._config["idle_timeout"] > 0:
            self._start_idle_checker()

    # ── Factory methods ────────────────────────────────────────────────

    def _create_backend(self) -> SandboxBackend:
        provisioner_url = self._config.get("provisioner_url")
        if provisioner_url:
            logger.info(f"Using remote sandbox backend with provisioner at {provisioner_url}")
            return RemoteSandboxBackend(provisioner_url=provisioner_url)

        logger.info("Using local container sandbox backend")
        return LocalContainerBackend(
            image=self._config["image"],
            base_port=self._config["port"],
            container_prefix=self._config["container_prefix"],
            config_mounts=self._config["mounts"],
            environment=self._config["environment"],
        )

    @staticmethod
    def _resolve_env_vars(env_config: dict[str, str]) -> dict[str, str]:
        resolved = {}
        for key, value in env_config.items():
            if isinstance(value, str) and value.startswith("$"):
                resolved[key] = os.environ.get(value[1:], "")
            else:
                resolved[key] = str(value)
        return resolved

    # ── Orphan reconciliation ──────────────────────────────────────────

    def _reconcile_orphans(self) -> None:
        try:
            running = self._backend.list_running()
        except Exception as e:
            logger.warning(f"Failed to enumerate running containers during startup reconciliation: {e}")
            return
        if not running:
            return

        current_time = time.time()
        adopted = 0
        for info in running:
            age = current_time - info.created_at if info.created_at > 0 else float("inf")
            with self._lock:
                if info.sandbox_id in self._sandboxes or info.sandbox_id in self._warm_pool:
                    continue
                self._warm_pool[info.sandbox_id] = (info, current_time)
            adopted += 1
            logger.info(f"Adopted orphan container {info.sandbox_id} into warm pool (age: {age:.0f}s)")

        if adopted:
            logger.info(f"Startup reconciliation complete: {adopted} adopted into warm pool, {len(running)} total found")

    def _populate_idle_pool(self) -> None:
        """Discover pre-warmed resident Pods and seed the idle pool.

        Called once at startup in pool mode.  Resident Pods are created by the
        provisioner (or a previous backend process) with ids ``pool-0`` …
        ``pool-{N-1}`` and stay running across backend restarts, so this simply
        re-adopts them via ``list_running()`` instead of creating anything.
        """
        try:
            running = self._backend.list_running()
        except Exception as e:
            logger.warning("Failed to enumerate resident sandboxes during startup: %s", e)
            return

        adopted = 0
        for info in running:
            if not info.sandbox_id.startswith(POOL_ID_PREFIX):
                continue
            with self._pool_cond:
                self._pool_slots.add(info.sandbox_id)
                if info.sandbox_id not in self._idle_pool:
                    self._idle_pool.append(info.sandbox_id)
            with self._lock:
                self._sandbox_infos[info.sandbox_id] = info
            adopted += 1
            logger.info("Adopted resident pool sandbox %s into idle pool", info.sandbox_id)

        if adopted:
            logger.info("Pool startup: %d resident sandbox(es) discovered", adopted)
        else:
            logger.info("Pool startup: no resident sandboxes found (they will be created on demand)")

    # ── Deterministic ID ───────────────────────────────────────────────

    @staticmethod
    def _deterministic_sandbox_id(thread_id: str) -> str:
        return hashlib.sha256(thread_id.encode()).hexdigest()[:8]

    # ── Mount helpers ──────────────────────────────────────────────────

    def _get_extra_mounts(self, thread_id: str | None) -> list[tuple[str, str, bool]]:
        mounts: list[tuple[str, str, bool]] = []
        if thread_id:
            mounts.extend(self._get_thread_mounts(thread_id))
        return mounts

    def _get_thread_mounts(self, thread_id: str) -> list[tuple[str, str, bool]]:
        base = self._host_base_dir
        user_id = get_effective_user_id()
        thread_dir = base / "users" / (user_id or "default") / "threads" / thread_id
        workspace = thread_dir / "workspace"
        uploads = thread_dir / "uploads"
        outputs = thread_dir / "outputs"
        for d in (workspace, uploads, outputs):
            d.mkdir(parents=True, exist_ok=True)

        return [
            (str(workspace), f"{VIRTUAL_PATH_PREFIX}/workspace", False),
            (str(uploads), f"{VIRTUAL_PATH_PREFIX}/uploads", False),
            (str(outputs), f"{VIRTUAL_PATH_PREFIX}/outputs", False),
        ]

    # ── Idle timeout ───────────────────────────────────────────────────

    def _start_idle_checker(self) -> None:
        self._idle_thread = threading.Thread(
            target=self._idle_checker_loop,
            name="sandbox-idle-checker",
            daemon=True,
        )
        self._idle_thread.start()
        logger.info(
            f"Started idle checker thread (timeout: {self._config['idle_timeout']}s)"
        )

    def _idle_checker_loop(self) -> None:
        idle_timeout = self._config["idle_timeout"]
        while not self._idle_stop.wait(timeout=IDLE_CHECK_INTERVAL):
            try:
                self._cleanup_idle_sandboxes(idle_timeout)
            except Exception as e:
                logger.error(f"Error in idle checker loop: {e}")

    def _cleanup_idle_sandboxes(self, idle_timeout: float) -> None:
        if self._pool_enabled:
            self._cleanup_pool_idle(idle_timeout)
            return

        current_time = time.time()
        active_to_destroy: list[str] = []
        warm_to_destroy: list[tuple[str, SandboxInfo]] = []

        with self._lock:
            for sandbox_id, last_activity in self._last_activity.items():
                if current_time - last_activity > idle_timeout:
                    active_to_destroy.append(sandbox_id)
            for sandbox_id, (info, release_ts) in list(self._warm_pool.items()):
                if current_time - release_ts > idle_timeout:
                    warm_to_destroy.append((sandbox_id, info))
                    del self._warm_pool[sandbox_id]

        for sandbox_id in active_to_destroy:
            try:
                with self._lock:
                    last_activity = self._last_activity.get(sandbox_id)
                    if last_activity is None:
                        continue
                    if (time.time() - last_activity) < idle_timeout:
                        continue
                self.destroy(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to destroy idle sandbox {sandbox_id}: {e}")

        for sandbox_id, info in warm_to_destroy:
            try:
                self._backend.destroy(info)
                logger.info(f"Destroyed idle warm-pool sandbox {sandbox_id}")
            except Exception as e:
                logger.error(f"Failed to destroy idle warm-pool sandbox {sandbox_id}: {e}")

    def _cleanup_pool_idle(self, idle_timeout: float) -> None:
        """Return thread-bound resident Pods that have gone idle.

        Unlike the local Docker path, resident Pods are *never* destroyed here —
        they are cleared and returned to the idle pool so another thread can
        lease them.  This doubles as a leak guard: if a run crashes without
        calling ``release``, the stale ``_last_activity`` eventually triggers a
        forced return here.
        """
        current_time = time.time()
        to_return: list[str] = []
        with self._lock:
            for sandbox_id, last_activity in self._last_activity.items():
                if sandbox_id not in self._sandboxes:
                    continue
                if current_time - last_activity > idle_timeout:
                    to_return.append(sandbox_id)

        for sandbox_id in to_return:
            try:
                self.release(sandbox_id)
                logger.info("Returned idle-thread sandbox %s to pool", sandbox_id)
            except Exception as e:
                logger.error("Failed to return idle sandbox %s to pool: %s", sandbox_id, e)

    # ── Signal handling ────────────────────────────────────────────────

    def _register_signal_handlers(self) -> None:
        self._orig_sigterm = signal.getsignal(signal.SIGTERM)
        self._orig_sigint = signal.getsignal(signal.SIGINT)

        def handler(signum, frame):
            self.shutdown()
            original = self._orig_sigterm if signum == signal.SIGTERM else self._orig_sigint
            if callable(original):
                original(signum, frame)
            elif original == signal.SIG_DFL:
                signal.signal(signum, signal.SIG_DFL)
                signal.raise_signal(signum)

        try:
            signal.signal(signal.SIGTERM, handler)
            signal.signal(signal.SIGINT, handler)
        except ValueError:
            logger.debug("Could not register signal handlers (not main thread)")

    # ── Thread locking (in-process) ────────────────────────────────────

    def _get_thread_lock(self, thread_id: str) -> threading.Lock:
        with self._lock:
            if thread_id not in self._thread_locks:
                self._thread_locks[thread_id] = threading.Lock()
            return self._thread_locks[thread_id]

    # ── SandboxProvider ABC ────────────────────────────────────────────

    @override
    def acquire(self, thread_id: str | None = None) -> str:
        if thread_id:
            thread_lock = self._get_thread_lock(thread_id)
            with thread_lock:
                return self._acquire_internal(thread_id)
        return self._acquire_internal(thread_id)

    def _acquire_internal(self, thread_id: str | None) -> str:
        if self._pool_enabled and thread_id:
            return self._acquire_from_pool(thread_id)

        # Layer 1: In-process cache
        if thread_id:
            with self._lock:
                if thread_id in self._thread_sandboxes:
                    existing_id = self._thread_sandboxes[thread_id]
                    if existing_id in self._sandboxes:
                        self._last_activity[existing_id] = time.time()
                        return existing_id
                    del self._thread_sandboxes[thread_id]

        sandbox_id = self._deterministic_sandbox_id(thread_id) if thread_id else str(uuid.uuid4())[:8]

        # Layer 1.5: Warm pool
        if thread_id:
            with self._lock:
                if sandbox_id in self._warm_pool:
                    info, _ = self._warm_pool.pop(sandbox_id)
                    sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
                    self._sandboxes[sandbox_id] = sandbox
                    self._sandbox_infos[sandbox_id] = info
                    self._last_activity[sandbox_id] = time.time()
                    self._thread_sandboxes[thread_id] = sandbox_id
                    logger.info(f"Reclaimed warm-pool sandbox {sandbox_id} at {info.sandbox_url}")
                    return sandbox_id

        # Layer 2: Cross-process discovery + create
        if thread_id:
            return self._discover_or_create_with_lock(thread_id, sandbox_id)
        return self._create_sandbox(thread_id, sandbox_id)

    def _discover_or_create_with_lock(self, thread_id: str, sandbox_id: str) -> str:
        base = self._host_base_dir
        user_id = get_effective_user_id()
        thread_dir = base / "users" / (user_id or "default") / "threads" / thread_id
        thread_dir.mkdir(parents=True, exist_ok=True)
        lock_path = thread_dir / f"{sandbox_id}.lock"

        with open(lock_path, "a", encoding="utf-8") as lock_file:
            locked = False
            try:
                _lock_file_exclusive(lock_file)
                locked = True

                with self._lock:
                    if thread_id in self._thread_sandboxes:
                        existing_id = self._thread_sandboxes[thread_id]
                        if existing_id in self._sandboxes:
                            self._last_activity[existing_id] = time.time()
                            return existing_id
                    if sandbox_id in self._warm_pool:
                        info, _ = self._warm_pool.pop(sandbox_id)
                        sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
                        self._sandboxes[sandbox_id] = sandbox
                        self._sandbox_infos[sandbox_id] = info
                        self._last_activity[sandbox_id] = time.time()
                        self._thread_sandboxes[thread_id] = sandbox_id
                        return sandbox_id

                discovered = self._backend.discover(sandbox_id)
                if discovered is not None:
                    sandbox = AioSandbox(id=discovered.sandbox_id, base_url=discovered.sandbox_url)
                    with self._lock:
                        self._sandboxes[discovered.sandbox_id] = sandbox
                        self._sandbox_infos[discovered.sandbox_id] = discovered
                        self._last_activity[discovered.sandbox_id] = time.time()
                        self._thread_sandboxes[thread_id] = discovered.sandbox_id
                    logger.info(f"Discovered existing sandbox {discovered.sandbox_id} at {discovered.sandbox_url}")
                    return discovered.sandbox_id

                return self._create_sandbox(thread_id, sandbox_id)
            finally:
                if locked:
                    _unlock_file(lock_file)

    # ── Resident pool acquire/release ─────────────────────────────────

    def _acquire_from_pool(self, thread_id: str) -> str:
        """Lease a resident Pod for *thread_id*, queuing when the pool is full.

        Unlike the default path, the sandbox id is a *pool slot* (``pool-N``),
        not a deterministic hash of the thread.  A slot is cleared and the
        thread's files restored from storage before it is handed over, so the
        thread never sees another tenant's data.
        """
        # Layer 1: already bound to this thread → reuse in place (no clear).
        with self._lock:
            if thread_id in self._thread_sandboxes:
                existing_id = self._thread_sandboxes[thread_id]
                if existing_id in self._sandboxes:
                    self._last_activity[existing_id] = time.time()
                    return existing_id
                del self._thread_sandboxes[thread_id]

        deadline = time.time() + self._pool_lease_timeout
        while True:
            with self._pool_cond:
                if self._idle_pool:
                    sandbox_id = self._idle_pool.pop()
                elif len(self._pool_slots) < self._pool_size:
                    sandbox_id = self._next_pool_id()
                    self._pool_slots.add(sandbox_id)  # reserve slot
                else:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        raise RuntimeError(f"No sandbox available in the resident pool (pool_size={self._pool_size}); waited {self._pool_lease_timeout}s")
                    self._pool_cond.wait(timeout=remaining)
                    continue

            try:
                return self._prepare_pool_sandbox(thread_id, sandbox_id)
            except Exception:
                # Release the reserved slot so a later acquire can retry.
                with self._pool_cond:
                    self._pool_slots.discard(sandbox_id)
                    self._pool_cond.notify_all()
                raise

    def _next_pool_id(self) -> str:
        """Return the lowest unused ``pool-N`` id (caller holds ``_pool_cond``)."""
        index = 0
        while f"{POOL_ID_PREFIX}{index}" in self._pool_slots:
            index += 1
        return f"{POOL_ID_PREFIX}{index}"

    def _prepare_pool_sandbox(self, thread_id: str, sandbox_id: str) -> str:
        """Discover/create, clear, restore and bind a pool Pod to *thread_id*."""
        with self._lock:
            info = self._sandbox_infos.get(sandbox_id)
        if info is None:
            info = self._backend.discover(sandbox_id)

        if info is None:
            # Cold-start fallback: the provisioner did not pre-warm this slot.
            info = self._backend.create(thread_id, sandbox_id, extra_mounts=None)

        wait_error = self._backend.wait_ready(info, timeout=self._config["readiness_timeout"])
        if wait_error is not None:
            self._backend.destroy(info)
            raise RuntimeError(wait_error)

        sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)

        # Clear the whole user-data volume (including any custom directories a
        # previous tenant created) before reuse.  On clear failure the Pod is
        # destroyed — never hand a dirty volume to another tenant.
        if not self._clear_sandbox(sandbox):
            self._backend.destroy(info)
            raise RuntimeError(f"Sandbox {sandbox_id} could not be cleared before reuse")

        # Recreate the three per-thread dirs the agent + file sync assume exist
        # (the clear above removed everything, so recreate defensively here).
        try:
            sandbox.execute_command(f"mkdir -p {VIRTUAL_PATH_PREFIX}/workspace {VIRTUAL_PATH_PREFIX}/outputs {VIRTUAL_PATH_PREFIX}/uploads")
        except Exception:
            logger.warning("Failed to ensure sandbox dirs for %s", sandbox_id, exc_info=True)

        # Restore this thread's files from remote storage.
        self._restore_files_from_storage(sandbox, thread_id)

        with self._lock:
            self._sandboxes[sandbox_id] = sandbox
            self._sandbox_infos[sandbox_id] = info
            self._thread_sandboxes[thread_id] = sandbox_id
            self._last_activity[sandbox_id] = time.time()

        logger.info("Prepared pool sandbox %s for thread %s", sandbox_id, thread_id)
        return sandbox_id

    def _clear_sandbox(self, sandbox: AioSandbox) -> bool:
        """Clear a sandbox's per-thread dirs; return True only if fully empty."""
        out = sandbox.execute_command(POOL_CLEAR_COMMAND)
        return "CLEAR_OK" in out

    def _release_pool_sandbox(self, sandbox_id: str) -> None:
        """Clear and return a resident Pod to the idle pool (destroy on failure)."""
        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.get(sandbox_id)
            self._last_activity.pop(sandbox_id, None)
            for tid in [t for t, s in self._thread_sandboxes.items() if s == sandbox_id]:
                del self._thread_sandboxes[tid]

        if sandbox is None:
            return  # already released / not active

        if self._clear_sandbox(sandbox):
            with self._pool_cond:
                if sandbox_id not in self._idle_pool:
                    self._idle_pool.append(sandbox_id)
                self._pool_cond.notify_all()
            logger.info("Released sandbox %s back to idle pool (cleared)", sandbox_id)
            return

        # Clear failed — never hand a dirty Pod to another tenant.
        logger.warning("Sandbox %s failed to clear; destroying Pod to preserve isolation", sandbox_id)
        with self._pool_cond:
            self._pool_slots.discard(sandbox_id)
            self._pool_cond.notify_all()
        with self._lock:
            self._sandbox_infos.pop(sandbox_id, None)
        if info is not None:
            try:
                self._backend.destroy(info)
            except Exception as e:
                logger.error("Failed to destroy sandbox %s: %s", sandbox_id, e)

    def _destroy_pool_sandbox(self, sandbox_id: str) -> None:
        """Destroy a resident Pod and drop it from all pool bookkeeping."""
        with self._lock:
            info = self._sandbox_infos.pop(sandbox_id, None)
            self._sandboxes.pop(sandbox_id, None)
            self._last_activity.pop(sandbox_id, None)
            for tid in [t for t, s in self._thread_sandboxes.items() if s == sandbox_id]:
                del self._thread_sandboxes[tid]
        with self._pool_cond:
            self._pool_slots.discard(sandbox_id)
            if sandbox_id in self._idle_pool:
                self._idle_pool.remove(sandbox_id)
            self._pool_cond.notify_all()
        if info is not None:
            try:
                self._backend.destroy(info)
                logger.info("Destroyed pool sandbox %s", sandbox_id)
            except Exception as e:
                logger.error("Failed to destroy pool sandbox %s: %s", sandbox_id, e)

    @property
    def pool_enabled(self) -> bool:
        """Whether resident Pod pooling is active (K8s provisioner mode only)."""
        return self._pool_enabled

    def release_thread(self, thread_id: str) -> None:
        """Release the sandbox currently bound to *thread_id* (no-op if none)."""
        with self._lock:
            sandbox_id = self._thread_sandboxes.get(thread_id)
        if sandbox_id:
            self.release(sandbox_id)

    def _evict_oldest_warm(self) -> str | None:
        with self._lock:
            if not self._warm_pool:
                return None
            oldest_id = min(self._warm_pool, key=lambda sid: self._warm_pool[sid][1])
            info, _ = self._warm_pool.pop(oldest_id)
        try:
            self._backend.destroy(info)
            logger.info(f"Destroyed warm-pool sandbox {oldest_id}")
        except Exception as e:
            logger.error(f"Failed to destroy warm-pool sandbox {oldest_id}: {e}")
            return None
        return oldest_id

    def _create_sandbox(self, thread_id: str | None, sandbox_id: str) -> str:
        extra_mounts = self._get_extra_mounts(thread_id)

        replicas = self._config["replicas"]
        with self._lock:
            total = len(self._sandboxes) + len(self._warm_pool)
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            if evicted:
                logger.info(f"Evicted warm-pool sandbox {evicted} to stay within replicas={replicas}")
            else:
                logger.warning(
                    f"All {replicas} replica slots are in active use; "
                    f"creating sandbox {sandbox_id} beyond the soft limit"
                )

        info = self._backend.create(thread_id or "", sandbox_id, extra_mounts=extra_mounts or None)

        readiness_timeout = self._config["readiness_timeout"]
        wait_error = self._backend.wait_ready(info, timeout=readiness_timeout)
        if wait_error is not None:
            self._backend.destroy(info)
            raise RuntimeError(wait_error)

        sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
        with self._lock:
            self._sandboxes[sandbox_id] = sandbox
            self._sandbox_infos[sandbox_id] = info
            self._last_activity[sandbox_id] = time.time()
            if thread_id:
                self._thread_sandboxes[thread_id] = sandbox_id

        logger.info(f"Created sandbox {sandbox_id} for thread {thread_id} at {info.sandbox_url}")

        if thread_id:
            # ── Bootstrap per-thread directories ──────────────────────
            # The K8s sandbox Pod mounts a single empty emptyDir at
            # /mnt/user-data with no pre-created subdirectories.  The
            # agent's system prompt, the storage restore below, and the
            # post-run file pull all assume
            # /mnt/user-data/{workspace,outputs,uploads} exist — without
            # this, the agent's writes to outputs/ (user deliverables)
            # fail with "No such file or directory" until it manually
            # runs `mkdir -p`.
            try:
                sandbox.execute_command(
                    "mkdir -p "
                    f"{VIRTUAL_PATH_PREFIX}/workspace "
                    f"{VIRTUAL_PATH_PREFIX}/outputs "
                    f"{VIRTUAL_PATH_PREFIX}/uploads"
                )
            except Exception:
                logger.warning(
                    "Failed to bootstrap sandbox directories for thread %s",
                    thread_id, exc_info=True,
                )

            # ── Restore workspace files from remote storage ──────────
            # When the sandbox runs in a K8s Pod (provisioner mode), its
            # filesystem is a fresh emptyDir — any files from previous
            # turns live only in OBS/S3.  Pull them back so the agent
            # sees a consistent workspace across Pod lifecycles.
            try:
                self._restore_files_from_storage(sandbox, thread_id)
            except Exception:
                logger.warning(
                    "Failed to restore workspace files for thread %s "
                    "(agent may not see previous outputs)",
                    thread_id, exc_info=True,
                )

        return sandbox_id

    def _restore_files_from_storage(self, sandbox: AioSandbox, thread_id: str) -> None:
        """Pull thread files from remote storage into a fresh sandbox.

        Only active for remote (K8s provisioner) sandboxes with a non-local
        storage backend — local Docker sandboxes use bind-mounts and don't
        need explicit restore.

        The mapping from OBS key to sandbox path::

            OBS:  users/{uid}/threads/{tid}/outputs/foo.csv
            →     /mnt/user-data/outputs/foo.csv

        Skill-injection artifacts (``.skills/``) and directory markers are
        skipped. Failures are logged but never raised — a partial restore
        is better than blocking the agent from starting.
        """
        if self._storage is None:
            return

        # Only restore for remote sandbox backends (K8s provisioner mode).
        # Local Docker sandboxes use bind-mounts; files appear automatically.
        if not isinstance(self._backend, RemoteSandboxBackend):
            return

        user_id = get_effective_user_id()
        uid = user_id or "default"
        prefix = f"users/{uid}/threads/{thread_id}/"

        # ── List objects in storage ──────────────────────────────────────
        try:
            objects = self._run_async(self._storage.list_objects(prefix))
        except Exception:
            logger.warning(
                "Failed to list storage objects for thread %s", thread_id,
                exc_info=True,
            )
            return

        if not objects:
            return

        # ── Download + write to sandbox ──────────────────────────────────
        restored = 0
        ensured_dirs: set[str] = set()
        for obj in objects:
            key: str = obj["key"]
            # Skip directory markers (S3 CommonPrefixes)
            if key.endswith("/"):
                continue
            # Skip .skills/ — internal runtime artifacts, not user data
            if "/.skills/" in key:
                continue

            # Map OBS key → sandbox virtual path
            rel = key.removeprefix(prefix)
            if not rel:
                continue
            sandbox_path = f"{VIRTUAL_PATH_PREFIX}/{rel}"

            # Ensure the parent directory exists before writing.  The
            # sandbox's write_file does not create parent directories, and
            # restored keys may live in nested subdirectories (e.g.
            # outputs/charts/foo.png) that the fresh emptyDir lacks.
            parent = sandbox_path.rsplit("/", 1)[0]
            if parent not in ensured_dirs:
                ensured_dirs.add(parent)
                try:
                    sandbox.execute_command(f"mkdir -p {shlex.quote(parent)}")
                except Exception:
                    logger.warning(
                        "Failed to create restore directory %s", parent,
                        exc_info=True,
                    )

            try:
                content = self._run_async(self._storage.download_bytes(key))
                sandbox.update_file(sandbox_path, content)
                restored += 1
                logger.debug("Restored %s → %s", key, sandbox_path)
            except Exception:
                logger.warning(
                    "Failed to restore %s to sandbox", key, exc_info=True,
                )

        if restored:
            logger.info(
                "Restored %d file(s) from remote storage for thread %s",
                restored, thread_id,
            )

    @staticmethod
    def _run_async(coro: Any) -> Any:
        """Run an async coroutine, handling nested event loops.

        When called from a running event loop (e.g. inside an agent tool
        handler), the coroutine is dispatched to a separate thread. When
        called outside an event loop, uses :func:`asyncio.run` directly.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(lambda: asyncio.run(coro)).result(timeout=60)
            return asyncio.run(coro)
        except RuntimeError:
            return asyncio.run(coro)

    @override
    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox is not None:
                self._last_activity[sandbox_id] = time.time()
            return sandbox

    @override
    def release(self, sandbox_id: str) -> None:
        if self._pool_enabled:
            self._release_pool_sandbox(sandbox_id)
            return

        info = None
        thread_ids_to_remove: list[str] = []
        with self._lock:
            self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.pop(sandbox_id, None)
            thread_ids_to_remove = [
                tid for tid, sid in self._thread_sandboxes.items() if sid == sandbox_id
            ]
            for tid in thread_ids_to_remove:
                del self._thread_sandboxes[tid]
            self._last_activity.pop(sandbox_id, None)
            if info and sandbox_id not in self._warm_pool:
                self._warm_pool[sandbox_id] = (info, time.time())
        logger.info(f"Released sandbox {sandbox_id} to warm pool (container still running)")

    def destroy(self, sandbox_id: str) -> None:
        if self._pool_enabled:
            self._destroy_pool_sandbox(sandbox_id)
            return

        info = None
        thread_ids_to_remove: list[str] = []
        with self._lock:
            self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.pop(sandbox_id, None)
            thread_ids_to_remove = [
                tid for tid, sid in self._thread_sandboxes.items() if sid == sandbox_id
            ]
            for tid in thread_ids_to_remove:
                del self._thread_sandboxes[tid]
            self._last_activity.pop(sandbox_id, None)
            if info is None and sandbox_id in self._warm_pool:
                info, _ = self._warm_pool.pop(sandbox_id)
            else:
                self._warm_pool.pop(sandbox_id, None)

        if info:
            self._backend.destroy(info)
            logger.info(f"Destroyed sandbox {sandbox_id}")

    @override
    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            sandbox_ids = list(self._sandboxes.keys())
            warm_items = list(self._warm_pool.items())
            self._warm_pool.clear()

        self._idle_stop.set()
        if self._idle_thread is not None and self._idle_thread.is_alive():
            self._idle_thread.join(timeout=5)
            logger.info("Stopped idle checker thread")

        if self._pool_enabled:
            # Resident Pods are intentionally left running across backend
            # restarts so the sandbox image stays warm on the K8s node.  Only
            # drop in-process references; the next backend instance re-adopts
            # them via list_running().
            with self._lock:
                self._sandboxes.clear()
                self._sandbox_infos.clear()
                self._thread_sandboxes.clear()
            with self._pool_cond:
                self._idle_pool.clear()
                self._pool_slots.clear()
            logger.info("Pool mode shutdown: leaving resident sandbox Pods running")
            return

        logger.info(
            f"Shutting down {len(sandbox_ids)} active + {len(warm_items)} warm-pool sandbox(es)"
        )
        for sandbox_id in sandbox_ids:
            try:
                self.destroy(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to destroy sandbox {sandbox_id} during shutdown: {e}")
        for sandbox_id, (info, _) in warm_items:
            try:
                self._backend.destroy(info)
                logger.info(f"Destroyed warm-pool sandbox {sandbox_id} during shutdown")
            except Exception as e:
                logger.error(f"Failed to destroy warm-pool sandbox {sandbox_id} during shutdown: {e}")