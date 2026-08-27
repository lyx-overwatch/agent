"""SkillHub Sandbox Provisioner Service.

Dynamically creates and manages per-sandbox Pods in Kubernetes.
Each ``sandbox_id`` gets its own Pod + ClusterIP Service.  The backend
accesses sandboxes directly via the Service DNS name.

The provisioner connects to the host machine's Kubernetes cluster via a
mounted kubeconfig (``~/.kube/config``).  Sandbox Pods run on the host
K8s and are accessed by the backend via ``http://{svc-name}:8080``.

Endpoints:
    POST   /api/sandboxes              — Create a sandbox Pod + Service
    DELETE /api/sandboxes/{sandbox_id} — Destroy a sandbox Pod + Service
    GET    /api/sandboxes/{sandbox_id} — Get sandbox status & URL
    GET    /api/sandboxes              — List all sandboxes
    GET    /health                     — Provisioner health check

Architecture:
    ┌────────────┐  HTTP  ┌─────────────┐  K8s API  ┌──────────────┐
    │  backend   │ ─────▸ │ provisioner │ ────────▸ │  host K8s    │
    │            │        │ :8002       │           │  API server  │
    └────────────┘        └─────────────┘           └──────┬───────┘
                                                           │ creates
                          ┌─────────────┐           ┌──────▼───────┐
                          │   backend   │ ────────▸ │   sandbox    │
                          │             │ ClusterIP │   Pod(s)     │
                          └─────────────┘ DNS name  └──────────────┘

GC (garbage collection):
    A background task periodically scans sandbox Pods and cleans up
    stale / orphaned resources that the backend failed to destroy
    (e.g. due to a crash).  See ``_gc_loop()``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import urllib3
from fastapi import FastAPI, HTTPException
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException
from pydantic import BaseModel, Field

# Suppress only the InsecureRequestWarning from urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class _HealthCheckFilter(logging.Filter):
    """Suppress access logs for /health (liveness/readiness probes)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/health" not in record.getMessage()


# Silence uvicorn.access noise from K8s probes
logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())

# ── Configuration (all tuneable via environment variables) ───────────────

K8S_NAMESPACE = os.environ.get("K8S_NAMESPACE", "skillhub")
SANDBOX_IMAGE = os.environ.get(
    "SANDBOX_IMAGE",
    "swr.cn-south-1.myhuaweicloud.com/fintech-aigc/docker-sandbox:20260813V1.0",
)
# ── Node scheduling (optional) ─────────────────────────────────────────
# Pin sandbox Pods to a specific node so the sandbox image stays cached and
# there is no cold image pull on every new conversation.  Set
# SANDBOX_NODE_LABEL_KEY to a node label key; use the built-in
# ``kubernetes.io/hostname`` label (with the node name as VALUE) to pin to a
# specific node without needing to mutate Node objects.  When empty, no node
# affinity is applied and sandbox Pods may schedule anywhere (original
# behaviour).  Combine with the ``sandbox-image-warmer`` Deployment
# (deploy/sandbox-image-warmer.yaml) to pre-pull the image onto that node.
SANDBOX_NODE_LABEL_KEY = os.environ.get("SANDBOX_NODE_LABEL_KEY", "")
SANDBOX_NODE_LABEL_VALUE = os.environ.get("SANDBOX_NODE_LABEL_VALUE", "true")
# ── Volume configuration ───────────────────────────────────────────────
# SkillHub does NOT mount a skills volume into sandbox Pods.
# Skills are injected dynamically at runtime via the ``read_skill`` tool,
# which writes skill files into ``/mnt/user-data/workspace/.skills/``
# through the sandbox HTTP API — no volume mount needed.
#
# User-data volume: each sandbox Pod uses an emptyDir — ephemeral
# scratch storage that lives and dies with the Pod.  Backend pulls
# agent-generated files from the sandbox HTTP API after each run,
# so no persistent volume is needed.
SAFE_THREAD_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"

# Path to the kubeconfig *inside* the provisioner container.
# Typically the host's ~/.kube/config is mounted here.
# In CCE, leave unset — the provisioner uses in-cluster config automatically.
KUBECONFIG_PATH = os.environ.get("KUBECONFIG_PATH", "")

# ── GC (garbage collection) configuration ─────────────────────────────
# Background task periodically cleans up stale sandbox Pods + Services
# that were left behind by backend crashes or ungraceful shutdowns.
SANDBOX_GC_INTERVAL = int(os.environ.get("SANDBOX_GC_INTERVAL", "300"))  # seconds
# Pods in terminal phases (Failed, Error) are cleaned after this many seconds
SANDBOX_ERROR_CLEANUP_SECONDS = int(os.environ.get("SANDBOX_ERROR_CLEANUP_SECONDS", "300"))
# Running/Pending Pods older than this are considered orphans and cleaned up.
# Default 2 hours — long enough to not interfere with active sessions,
# short enough to prevent resource leaks from accumulating.
SANDBOX_MAX_AGE_SECONDS = int(os.environ.get("SANDBOX_MAX_AGE_SECONDS", "7200"))

# ── Resident sandbox pool ───────────────────────────────────────────────
# On CCE Autopilot there is no image cache / node-level prewarm, so every
# fresh Pod pays a 1–2 minute image pull.  To eliminate that from the agent's
# critical path, the provisioner pre-warms a fixed number of resident sandbox
# Pods at startup (``pool-0`` … ``pool-{N-1}``) with ``restartPolicy: Always``
# and a dedicated label so GC never reaps them.  The backend then leases these
# resident Pods instead of creating one per thread.
SANDBOX_POOL_SIZE = int(os.environ.get("SANDBOX_POOL_SIZE", "3"))
SANDBOX_RESIDENT_LABEL = "sandbox-resident"
# 常驻池健康巡检间隔（秒）。比 GC 的 SANDBOX_GC_INTERVAL 更短：GC 负责清理
# 孤儿资源，健康巡检负责快速发现并重建「已死但没人知道」的 resident Pod
# （典型是被磁盘/内存压力驱逐成 Evicted），保证池子始终有 N 个健康 slot，
# 避免「用户下一次对话时才发现 slot 死了、被迫现场冷启动 1~2 分钟」。
SANDBOX_POOL_HEALTH_INTERVAL = int(os.environ.get("SANDBOX_POOL_HEALTH_INTERVAL", "60"))


def _validate_thread_id(thread_id: str) -> str:
    if not re.match(SAFE_THREAD_ID_PATTERN, thread_id):
        raise ValueError(
            "Invalid thread_id: only alphanumeric characters, hyphens, and underscores are allowed."
        )
    return thread_id


# ── K8s client setup ────────────────────────────────────────────────────

core_v1: k8s_client.CoreV1Api | None = None


def _init_k8s_client() -> k8s_client.CoreV1Api:
    """Load kubeconfig from the mounted host config and return a CoreV1Api.

    Tries the mounted kubeconfig first, then falls back to in-cluster
    config (useful if the provisioner itself runs inside K8s).
    """
    if os.path.exists(KUBECONFIG_PATH):
        if os.path.isdir(KUBECONFIG_PATH):
            raise RuntimeError(
                f"KUBECONFIG_PATH points to a directory, expected a file: {KUBECONFIG_PATH}"
            )
        try:
            k8s_config.load_kube_config(config_file=KUBECONFIG_PATH)
            logger.info(f"Loaded kubeconfig from {KUBECONFIG_PATH}")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load kubeconfig from {KUBECONFIG_PATH}: {exc}"
            ) from exc
    else:
        logger.warning(
            f"Kubeconfig not found at {KUBECONFIG_PATH}; trying in-cluster config"
        )
        try:
            k8s_config.load_incluster_config()
        except Exception as exc:
            raise RuntimeError(
                "Failed to initialize Kubernetes client. "
                f"No kubeconfig at {KUBECONFIG_PATH}, and in-cluster config is unavailable: {exc}"
            ) from exc

    # When connecting from inside Docker to the host's K8s API, the
    # kubeconfig may reference ``localhost`` or ``127.0.0.1``.  We
    # optionally rewrite the server address so it reaches the host.
    k8s_api_server = os.environ.get("K8S_API_SERVER")
    if k8s_api_server:
        configuration = k8s_client.Configuration.get_default_copy()
        configuration.host = k8s_api_server
        # Self-signed certs are common for local clusters
        configuration.verify_ssl = False
        api_client = k8s_client.ApiClient(configuration)
        return k8s_client.CoreV1Api(api_client)

    return k8s_client.CoreV1Api()


def _wait_for_kubeconfig(timeout: int = 30) -> None:
    """Wait for kubeconfig file if configured, then continue with fallback support."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(KUBECONFIG_PATH):
            if os.path.isfile(KUBECONFIG_PATH):
                logger.info(f"Found kubeconfig file at {KUBECONFIG_PATH}")
                return
            if os.path.isdir(KUBECONFIG_PATH):
                raise RuntimeError(
                    "Kubeconfig path is a directory. "
                    f"Please mount a kubeconfig file at {KUBECONFIG_PATH}."
                )
            raise RuntimeError(
                f"Kubeconfig path exists but is not a regular file: {KUBECONFIG_PATH}"
            )
        logger.info(f"Waiting for kubeconfig at {KUBECONFIG_PATH} …")
        time.sleep(2)
    logger.warning(
        f"Kubeconfig not found at {KUBECONFIG_PATH} after {timeout}s; "
        "will attempt in-cluster Kubernetes config"
    )


def _ensure_namespace() -> None:
    """Create the K8s namespace if it does not yet exist."""
    try:
        core_v1.read_namespace(K8S_NAMESPACE)
        logger.info(f"Namespace '{K8S_NAMESPACE}' already exists")
    except ApiException as exc:
        if exc.status == 404:
            ns = k8s_client.V1Namespace(
                metadata=k8s_client.V1ObjectMeta(
                    name=K8S_NAMESPACE,
                    labels={
                        "app.kubernetes.io/name": "skillhub",
                        "app.kubernetes.io/component": "sandbox",
                    },
                )
            )
            core_v1.create_namespace(ns)
            logger.info(f"Created namespace '{K8S_NAMESPACE}'")
        else:
            raise


# ── GC: orphaned sandbox cleanup ────────────────────────────────────────


def _parse_k8s_timestamp(ts: str | None) -> datetime | None:
    """Parse a K8s timestamp string (RFC 3339) into a timezone-aware datetime."""
    if not ts:
        return None
    try:
        # K8s timestamps are RFC 3339, e.g. "2026-08-12T10:30:00Z"
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _pod_age_seconds(pod: k8s_client.V1Pod) -> float | None:
    """Return the Pod's age in seconds based on its creationTimestamp."""
    ts = _parse_k8s_timestamp(pod.metadata.creation_timestamp if pod.metadata else None)
    if ts is None:
        return None
    return (datetime.now(UTC) - ts).total_seconds()


# Pod phases that indicate the sandbox will never become healthy
_TERMINAL_PHASES = frozenset({"Failed", "Error", "Unknown"})

# Resident pool Pod phases that can never recover on their own.
# ``Evicted`` (disk/memory pressure eviction) is terminal for the Pod — K8s
# does not reschedule it — but its Service survives, so the slot looks
# "present" to ``_ensure_resident_sandbox`` and never gets rebuilt without
# an explicit health check.  ``Failed`` / ``Unknown`` are the other dead-ends.
_UNHEALTHY_RESIDENT_PHASES = frozenset({"Evicted", "Failed", "Unknown"})


async def _gc_loop() -> None:
    """Background task that periodically cleans up stale sandbox resources.

    Two categories are cleaned:

    1. **Terminal Pods** (Failed / Error / Unknown): cleaned after
       ``SANDBOX_ERROR_CLEANUP_SECONDS``.  These will never recover.

    2. **Long-running orphans** (Running / Pending): cleaned after
       ``SANDBOX_MAX_AGE_SECONDS``.  A Pod this old without a
       corresponding active backend session is almost certainly an
       orphan from a crashed or ungracefully-killed backend process.

    Each Pod's corresponding Service (if any) is deleted together with
    the Pod.
    """
    # Wait for the server to be fully started before the first scan
    await asyncio.sleep(max(SANDBOX_GC_INTERVAL // 2, 30))

    while True:
        try:
            await _gc_sweep()
        except Exception:
            logger.exception("GC sweep failed — will retry on next interval")

        await asyncio.sleep(SANDBOX_GC_INTERVAL)


async def _gc_sweep() -> None:
    """Single GC sweep: list sandbox Pods, delete stale ones."""
    try:
        pods = core_v1.list_namespaced_pod(
            K8S_NAMESPACE,
            label_selector="app=skillhub-sandbox",
        )
    except ApiException as exc:
        logger.error("GC: failed to list sandbox Pods: %s", exc)
        return

    logger.debug("GC: scanning %d sandbox Pod(s)", len(pods.items))

    cleaned = 0
    for pod in pods.items:
        if not pod.metadata:
            continue

        labels = pod.metadata.labels or {}
        # Resident pool Pods are long-lived by design — never reap them.
        if labels.get(SANDBOX_RESIDENT_LABEL) == "true":
            continue

        sandbox_id = labels.get("sandbox-id")
        if not sandbox_id:
            continue

        phase = (pod.status.phase or "Unknown") if pod.status else "Unknown"
        age = _pod_age_seconds(pod)
        if age is None:
            continue

        should_clean = False
        reason = ""

        if phase in _TERMINAL_PHASES and age > SANDBOX_ERROR_CLEANUP_SECONDS:
            should_clean = True
            reason = f"terminal phase '{phase}' for {age:.0f}s (threshold {SANDBOX_ERROR_CLEANUP_SECONDS}s)"
        elif phase in ("Running", "Pending") and age > SANDBOX_MAX_AGE_SECONDS:
            should_clean = True
            reason = f"phase '{phase}' for {age:.0f}s exceeds max age {SANDBOX_MAX_AGE_SECONDS}s"

        if not should_clean:
            continue

        logger.info(
            "GC: cleaning sandbox '%s' — %s (created %s)",
            sandbox_id, reason,
            pod.metadata.creation_timestamp,
        )

        # Delete Service first (graceful teardown), then Pod
        svc_deleted = False
        try:
            core_v1.delete_namespaced_service(_svc_name(sandbox_id), K8S_NAMESPACE)
            svc_deleted = True
            logger.info("GC: deleted Service %s", _svc_name(sandbox_id))
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("GC: failed to delete Service %s: %s", _svc_name(sandbox_id), exc.reason)

        try:
            core_v1.delete_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
            logger.info("GC: deleted Pod %s", _pod_name(sandbox_id))
            cleaned += 1
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("GC: failed to delete Pod %s: %s", _pod_name(sandbox_id), exc.reason)
            # If Service was deleted but Pod deletion failed, note it
            if svc_deleted:
                logger.warning(
                    "GC: Service %s deleted but Pod %s deletion failed — "
                    "Service will not be recreated without manual intervention",
                    _svc_name(sandbox_id), _pod_name(sandbox_id),
                )

    if cleaned:
        logger.info("GC: sweep complete — cleaned %d sandbox(es)", cleaned)


async def _prewarm_pool() -> None:
    """Create the resident sandbox Pods (``pool-0`` … ``pool-{N-1}``).

    Runs as a background task at startup.  Each Pod's image pull happens once
    here, well before any user request, so the backend can lease a ready Pod
    with no cold-start latency.  Idempotent — existing Pods/Services are left
    untouched.
    """
    logger.info("Prewarming %d resident sandbox Pod(s)…", SANDBOX_POOL_SIZE)
    for index in range(SANDBOX_POOL_SIZE):
        sandbox_id = f"pool-{index}"
        try:
            await asyncio.to_thread(_ensure_resident_sandbox, sandbox_id)
        except Exception:
            logger.exception("Failed to prewarm resident sandbox %s", sandbox_id)
    logger.info("Resident sandbox pool prewarm complete")


def _ensure_resident_sandbox(sandbox_id: str) -> None:
    """Idempotently create a resident Pod + Service for *sandbox_id*."""
    if _get_svc_url(sandbox_id):
        logger.info("Resident sandbox %s already exists — skipping", sandbox_id)
        return

    try:
        core_v1.create_namespaced_pod(K8S_NAMESPACE, _build_pod(sandbox_id, "resident", resident=True))
        logger.info("Created resident Pod %s", _pod_name(sandbox_id))
    except ApiException as exc:
        if exc.status != 409:  # 409 = AlreadyExists
            raise

    try:
        core_v1.create_namespaced_service(K8S_NAMESPACE, _build_service(sandbox_id, resident=True))
        logger.info("Created Service %s", _svc_name(sandbox_id))
    except ApiException as exc:
        if exc.status != 409:
            raise


def _delete_sandbox_resources(sandbox_id: str) -> None:
    """Delete a sandbox's Service and Pod, tolerating already-gone (404)."""
    try:
        core_v1.delete_namespaced_service(_svc_name(sandbox_id), K8S_NAMESPACE)
    except ApiException as exc:
        if exc.status != 404:
            logger.warning("Failed to delete Service %s: %s", _svc_name(sandbox_id), exc.reason)

    try:
        core_v1.delete_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
    except ApiException as exc:
        if exc.status != 404:
            logger.warning("Failed to delete Pod %s: %s", _pod_name(sandbox_id), exc.reason)


def _resident_pod_unhealthy(sandbox_id: str) -> str:
    """Return a reason when a resident Pod needs rebuilding, else empty string.

    Rebuild triggers: the Pod is missing, or it is in a terminal phase
    (``Evicted`` — from disk/memory pressure eviction — ``Failed``, or
    ``Unknown``).  Running and Pending Pods are left alone: image pulls and
    container restarts are handled by ``restartPolicy: Always`` plus the
    backend's ``wait_ready``, and a still-warming Pod is healthy by definition.
    """
    try:
        pod = core_v1.read_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
    except ApiException as exc:
        if exc.status == 404:
            return "pod-missing"
        return ""  # transient API error — retry on next sweep

    status = pod.status
    if status is None:
        return ""
    phase = status.phase or "Unknown"
    reason = status.reason or ""
    if phase in _UNHEALTHY_RESIDENT_PHASES or reason == "Evicted":
        return f"phase={phase} reason={reason}" if reason else f"phase={phase}"
    return ""


async def _resident_pool_health_sweep() -> None:
    """Inspect the resident pool and rebuild any slot that needs it.

    Two actions per ``pool-{i}`` slot:

    * Service missing → the slot was never created, or a previous sweep deleted
      it — recreate it (``_ensure_resident_sandbox`` is idempotent).
    * Pod terminally unhealthy (Evicted/Failed/Unknown) → delete; next sweep
      recreates it.

    Splitting delete from recreate avoids racing the async Pod deletion (a
    recreate issued immediately would see a still-terminating Service and skip).
    """
    for index in range(SANDBOX_POOL_SIZE):
        sandbox_id = f"pool-{index}"
        try:
            has_service = await asyncio.to_thread(_get_svc_url, sandbox_id)
            if not has_service:
                await asyncio.to_thread(_ensure_resident_sandbox, sandbox_id)
                continue

            reason = await asyncio.to_thread(_resident_pod_unhealthy, sandbox_id)
            if reason:
                logger.warning(
                    "Resident pool: removing unhealthy %s (%s) — will rebuild next sweep",
                    sandbox_id, reason,
                )
                await asyncio.to_thread(_delete_sandbox_resources, sandbox_id)
                continue
        except Exception:
            logger.exception("Resident pool health check failed for %s", sandbox_id)


async def _resident_pool_health_loop() -> None:
    """Background task that keeps the resident pool at full health.

    Runs ``_resident_pool_health_sweep`` every ``SANDBOX_POOL_HEALTH_INTERVAL``.
    The first sweep is delayed one interval so the startup prewarm has time to
    create the initial slots.
    """
    await asyncio.sleep(SANDBOX_POOL_HEALTH_INTERVAL)
    while True:
        try:
            await _resident_pool_health_sweep()
        except Exception:
            logger.exception("Resident pool health sweep failed — will retry on next interval")
        await asyncio.sleep(SANDBOX_POOL_HEALTH_INTERVAL)


# ── FastAPI lifespan ─────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global core_v1
    _wait_for_kubeconfig()
    core_v1 = _init_k8s_client()
    _ensure_namespace()

    # Pre-warm the resident sandbox pool (fire-and-forget; image pulls are
    # slow, so we kick them off without blocking startup).
    pool_health_task = None
    if SANDBOX_POOL_SIZE > 0:
        asyncio.create_task(_prewarm_pool())
        # Keep the pool healthy: detect and rebuild Evicted/failed slots.
        pool_health_task = asyncio.create_task(_resident_pool_health_loop())
        logger.info("Resident pool health loop started (interval=%ds)", SANDBOX_POOL_HEALTH_INTERVAL)

    # Start GC background task
    gc_task = asyncio.create_task(_gc_loop())
    logger.info(
        "GC background task started (interval=%ds, error_cleanup=%ds, max_age=%ds)",
        SANDBOX_GC_INTERVAL, SANDBOX_ERROR_CLEANUP_SECONDS, SANDBOX_MAX_AGE_SECONDS,
    )

    logger.info("Provisioner is ready (using host Kubernetes)")
    yield

    # Shutdown: cancel pool health task
    if pool_health_task is not None:
        pool_health_task.cancel()
        try:
            await pool_health_task
        except asyncio.CancelledError:
            logger.info("Resident pool health loop stopped")

    # Shutdown: cancel GC task
    gc_task.cancel()
    try:
        await gc_task
    except asyncio.CancelledError:
        logger.info("GC background task stopped")


app = FastAPI(title="SkillHub Sandbox Provisioner", lifespan=lifespan)


# ── Request / Response models ───────────────────────────────────────────


class CreateSandboxRequest(BaseModel):
    sandbox_id: str
    thread_id: str = Field(pattern=SAFE_THREAD_ID_PATTERN)


class SandboxResponse(BaseModel):
    sandbox_id: str
    sandbox_url: str  # Direct access URL, e.g. http://host.docker.internal:{NodePort}
    status: str
    detail: str = ""  # Human-readable failure reason (empty when healthy)


# ── K8s resource helpers ─────────────────────────────────────────────────


def _pod_name(sandbox_id: str) -> str:
    return f"sandbox-{sandbox_id}"


def _svc_name(sandbox_id: str) -> str:
    return f"sandbox-{sandbox_id}-svc"


def _svc_url(sandbox_id: str) -> str:
    """Build the sandbox URL using the ClusterIP Service DNS name.

    Backend and sandbox Pods run in the same K8s namespace, so the
    short Service name resolves via cluster DNS.
    """
    return f"http://{_svc_name(sandbox_id)}:8080"


def _build_volumes() -> list[k8s_client.V1Volume]:
    """Build the user-data volume for the sandbox Pod — always emptyDir.

    Files are ephemeral (Pod lifetime).  The backend pulls agent-generated
    files via the sandbox HTTP API after each run and uploads them to
    object storage, so persistent volumes are unnecessary.
    """
    return [
        k8s_client.V1Volume(
            name="user-data",
            empty_dir=k8s_client.V1EmptyDirVolumeSource(),
        )
    ]


def _build_volume_mounts() -> list[k8s_client.V1VolumeMount]:
    """Build the user-data volume mount (only mount needed by SkillHub)."""
    return [
        k8s_client.V1VolumeMount(
            name="user-data",
            mount_path="/mnt/user-data",
            read_only=False,
        )
    ]


def _build_init_containers() -> list[k8s_client.V1Container]:
    """Build the init container that pre-creates the user-data directories.

    The sandbox Pod mounts a single empty emptyDir at /mnt/user-data with
    no pre-created subdirectories.  The agent's system prompt and the
    backend's file sync assume /mnt/user-data/{workspace,outputs,uploads}
    exist; without this, the agent's first write to outputs/ (user
    deliverables) fails with "No such file or directory" and it has to
    ``mkdir -p`` manually.  Reuses SANDBOX_IMAGE so no extra image pull is
    needed.

    IMPORTANT: the sandbox HTTP server runs as the image's default user
    (``root``) but executes the agent's shell commands as an unprivileged
    non-root user.  That user is provisioned by the sandbox server's own
    entrypoint at container start, so it is NOT present in the image's
    ``/etc/passwd`` while the init container runs — a ``chown <user>`` here
    fails with exit code 1.  ``mkdir -p`` alone would leave the directories
    as ``root:root drwxr-xr-x`` (umask 022), unwritable by the agent's
    shell.  We therefore ``chmod 777`` them (and the volume root) instead:
    the volume is a per-sandbox, single-tenant emptyDir, so world-writable
    is safe and sidesteps the unknown uid/gid entirely.  World-writable root
    is also what lets the provider clear *every* top-level entry (including
    custom directories a tenant created) between tenants.
    """
    return [
        k8s_client.V1Container(
            name="init-user-data-dirs",
            image=SANDBOX_IMAGE,
            command=[
                "sh", "-c",
                "mkdir -p /mnt/user-data/workspace /mnt/user-data/outputs /mnt/user-data/uploads "
                "&& chmod 777 /mnt/user-data /mnt/user-data/workspace /mnt/user-data/outputs /mnt/user-data/uploads",
            ],
            volume_mounts=_build_volume_mounts(),
        )
    ]


def _build_node_affinity() -> k8s_client.V1Affinity | None:
    """Pin sandbox Pods to labelled nodes when ``SANDBOX_NODE_LABEL_KEY`` is set.

    Returns ``None`` (no affinity) when the label key is unset, preserving the
    original "schedule anywhere" behaviour for clusters without a dedicated
    sandbox node pool.
    """
    if not SANDBOX_NODE_LABEL_KEY:
        return None
    return k8s_client.V1Affinity(
        node_affinity=k8s_client.V1NodeAffinity(
            required_during_scheduling_ignored_during_execution=k8s_client.V1NodeSelector(
                node_selector_terms=[
                    k8s_client.V1NodeSelectorTerm(
                        match_expressions=[
                            k8s_client.V1NodeSelectorRequirement(
                                key=SANDBOX_NODE_LABEL_KEY,
                                operator="In",
                                values=[SANDBOX_NODE_LABEL_VALUE],
                            )
                        ]
                    )
                ]
            )
        )
    )


def _build_pod(sandbox_id: str, thread_id: str, resident: bool = False) -> k8s_client.V1Pod:
    """Construct a Pod manifest for a single sandbox.

    ``resident=True`` builds a long-lived pool Pod: ``restartPolicy: Always``
    (auto-restart on crash) and a ``sandbox-resident`` label so GC skips it.
    """
    thread_id = _validate_thread_id(thread_id)
    labels = {
        "app": "skillhub-sandbox",
        "sandbox-id": sandbox_id,
        "app.kubernetes.io/name": "skillhub",
        "app.kubernetes.io/component": "sandbox",
    }
    if resident:
        labels[SANDBOX_RESIDENT_LABEL] = "true"
    return k8s_client.V1Pod(
        metadata=k8s_client.V1ObjectMeta(
            name=_pod_name(sandbox_id),
            namespace=K8S_NAMESPACE,
            labels=labels,
        ),
        spec=k8s_client.V1PodSpec(
            # Sandbox Pods run with the same ServiceAccount as the provisioner.
            # This is what lets them pull from SWR via the namespace's
            # imagePullSecrets (default-secret) which the provisioner
            # already wired in its own Pod spec.
            service_account_name="skillhub-provisioner",
            security_context=k8s_client.V1PodSecurityContext(
                fs_group=1000,
            ),
            image_pull_secrets=[
                k8s_client.V1LocalObjectReference(name="default-secret"),
            ],
            affinity=_build_node_affinity(),
            # CCE 节点带 node.cce.io/NodePodKey 的 NoSchedule taint（工作负载绑定/独占），
            # 需 toleration 才能调度上去；用 Exists 匹配任意 value。
            tolerations=[
                k8s_client.V1Toleration(
                    key="node.cce.io/NodePodKey",
                    operator="Exists",
                    effect="NoSchedule",
                ),
            ],
            init_containers=_build_init_containers(),
            containers=[
                k8s_client.V1Container(
                    name="sandbox",
                    image=SANDBOX_IMAGE,
                    image_pull_policy="IfNotPresent",
                    ports=[
                        k8s_client.V1ContainerPort(
                            name="http",
                            container_port=8080,
                            protocol="TCP",
                        )
                    ],
                    readiness_probe=k8s_client.V1Probe(
                        http_get=k8s_client.V1HTTPGetAction(
                            path="/v1/sandbox",
                            port=8080,
                        ),
                        initial_delay_seconds=5,
                        period_seconds=5,
                        timeout_seconds=3,
                        failure_threshold=3,
                    ),
                    liveness_probe=k8s_client.V1Probe(
                        http_get=k8s_client.V1HTTPGetAction(
                            path="/v1/sandbox",
                            port=8080,
                        ),
                        initial_delay_seconds=10,
                        period_seconds=10,
                        timeout_seconds=3,
                        failure_threshold=3,
                    ),
                    resources=k8s_client.V1ResourceRequirements(
                        requests={
                            "cpu": "100m",
                            "memory": "256Mi",
                            "ephemeral-storage": "500Mi",
                        },
                        limits={
                            "cpu": "1000m",
                            "memory": "1Gi",
                            "ephemeral-storage": "500Mi",
                        },
                    ),
                    volume_mounts=_build_volume_mounts(),
                    security_context=k8s_client.V1SecurityContext(
                        privileged=False,
                        allow_privilege_escalation=False,
                    ),
                )
            ],
            volumes=_build_volumes(),
            restart_policy="Always" if resident else "Never",
            # Resident pool Pods restart on crash so they stay warm; regular
            # sandbox Pods are ephemeral — the provider creates a fresh Pod
            # per conversation thread.
        ),
    )


def _build_service(sandbox_id: str, resident: bool = False) -> k8s_client.V1Service:
    """Construct a ClusterIP Service manifest.

    ``resident=True`` adds the ``sandbox-resident`` label so the CronJob
    rotation can delete Pool Services (and Pods) together by label selector.
    """
    labels = {
        "app": "skillhub-sandbox",
        "sandbox-id": sandbox_id,
        "app.kubernetes.io/name": "skillhub",
        "app.kubernetes.io/component": "sandbox",
    }
    if resident:
        labels[SANDBOX_RESIDENT_LABEL] = "true"
    return k8s_client.V1Service(
        metadata=k8s_client.V1ObjectMeta(
            name=_svc_name(sandbox_id),
            namespace=K8S_NAMESPACE,
            labels=labels,
        ),
        spec=k8s_client.V1ServiceSpec(
            type="ClusterIP",
            ports=[
                k8s_client.V1ServicePort(
                    name="http",
                    port=8080,
                    target_port=8080,
                    protocol="TCP",
                )
            ],
            selector={
                "sandbox-id": sandbox_id,
            },
        ),
    )


def _get_svc_url(sandbox_id: str) -> str | None:
    """Return the sandbox URL if the Service already exists, otherwise None."""
    try:
        svc = core_v1.read_namespaced_service(_svc_name(sandbox_id), K8S_NAMESPACE)
        # ClusterIP is assigned synchronously — if the Service exists, it's ready
        if svc.spec.cluster_ip:
            return _svc_url(sandbox_id)
    except ApiException:
        pass
    return None


def _get_pod_phase(sandbox_id: str) -> str:
    """Return the Pod phase (Pending / Running / Succeeded / Failed / Unknown)."""
    try:
        pod = core_v1.read_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
        return pod.status.phase or "Unknown"
    except ApiException:
        return "NotFound"


def _get_pod_failure_detail(sandbox_id: str) -> str:
    """Return a short human-readable summary of a sandbox Pod's failure.

    Inspects init-container and container statuses for a waiting/terminated
    ``reason`` (``ImagePullBackOff``, ``CrashLoopBackOff``, ``Error``, ...)
    so the backend can surface *why* a Pod failed instead of only its phase.
    Returns an empty string when the Pod is healthy or unavailable.
    """
    try:
        pod = core_v1.read_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
    except ApiException:
        return ""

    if not pod.status:
        return ""

    statuses = list(pod.status.init_container_statuses or []) + list(
        pod.status.container_statuses or []
    )
    parts: list[str] = []
    for cs in statuses:
        state = cs.state
        if state is None:
            continue
        reason: str = ""
        message: str = ""
        if state.waiting:
            reason = state.waiting.reason or ""
            message = state.waiting.message or ""
        elif state.terminated:
            reason = state.terminated.reason or ""
            message = state.terminated.message or ""
        if not reason:
            continue
        entry = f"{cs.name}: {reason}"
        if message:
            entry += f" ({message[:200]})"
        parts.append(entry)

    return "; ".join(parts)


# ── API endpoints ────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Provisioner health check."""
    return {"status": "ok"}


@app.post("/api/sandboxes", response_model=SandboxResponse)
async def create_sandbox(req: CreateSandboxRequest):
    """Create a sandbox Pod + ClusterIP Service for *sandbox_id*.

    If the sandbox already exists, returns the existing information
    (idempotent).
    """
    sandbox_id = req.sandbox_id
    thread_id = req.thread_id

    logger.info(
        f"Received request to create sandbox '{sandbox_id}' for thread '{thread_id}'"
    )

    # ── Fast path: sandbox already exists ────────────────────────────
    existing_url = _get_svc_url(sandbox_id)
    if existing_url:
        return SandboxResponse(
            sandbox_id=sandbox_id,
            sandbox_url=existing_url,
            status=_get_pod_phase(sandbox_id),
            detail=_get_pod_failure_detail(sandbox_id),
        )

    # ── Create Pod ───────────────────────────────────────────────────
    # A ``pool-`` prefixed id means the backend is (re)creating a resident
    # pool slot on demand — build it as a resident Pod so it stays warm and
    # is never GC'd.  Otherwise build a regular ephemeral Pod.
    try:
        core_v1.create_namespaced_pod(
            K8S_NAMESPACE,
            _build_pod(sandbox_id, thread_id, resident=sandbox_id.startswith("pool-")),
        )
        logger.info(f"Created Pod {_pod_name(sandbox_id)}")
    except ApiException as exc:
        logger.error(
            f"Pod creation failed: status={exc.status} reason={exc.reason!r} body={exc.body!r}"
        )
        if exc.status != 409:  # 409 = AlreadyExists
            raise HTTPException(
                status_code=500,
                detail=f"Pod creation failed: status={exc.status} reason={exc.reason} body={exc.body}",
            )

    # ── Create Service ───────────────────────────────────────────────
    svc_url = None
    try:
        core_v1.create_namespaced_service(K8S_NAMESPACE, _build_service(sandbox_id))
        logger.info(f"Created Service {_svc_name(sandbox_id)}")
        svc_url = _svc_url(sandbox_id)
    except ApiException as exc:
        if exc.status != 409:
            # Roll back the Pod on failure
            logger.error(
                f"Service creation failed: status={exc.status} reason={exc.reason!r} body={exc.body!r}"
            )
            try:
                core_v1.delete_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
            except ApiException:
                pass
            raise HTTPException(
                status_code=500, detail=f"Service creation failed: {exc.reason}"
            )
        # 409 AlreadyExists → someone else created it, read the URL
        svc_url = _svc_url(sandbox_id)

    return SandboxResponse(
        sandbox_id=sandbox_id,
        sandbox_url=svc_url,
        status=_get_pod_phase(sandbox_id),
        detail=_get_pod_failure_detail(sandbox_id),
    )


@app.delete("/api/sandboxes/{sandbox_id}")
async def destroy_sandbox(sandbox_id: str):
    """Destroy a sandbox Pod + Service."""
    errors: list[str] = []

    # ── Delete Service ─────────────────────────────────────────────────
    try:
        core_v1.delete_namespaced_service(_svc_name(sandbox_id), K8S_NAMESPACE)
        logger.info(f"Deleted Service {_svc_name(sandbox_id)}")
    except ApiException as exc:
        if exc.status != 404:
            errors.append(f"service: {exc.reason}")

    # ── Delete Pod ─────────────────────────────────────────────────────
    try:
        core_v1.delete_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
        logger.info(f"Deleted Pod {_pod_name(sandbox_id)}")
    except ApiException as exc:
        if exc.status != 404:
            errors.append(f"pod: {exc.reason}")

    if errors:
        raise HTTPException(
            status_code=500, detail=f"Partial cleanup: {', '.join(errors)}"
        )

    return {"ok": True, "sandbox_id": sandbox_id}


@app.get("/api/sandboxes/{sandbox_id}", response_model=SandboxResponse)
async def get_sandbox(sandbox_id: str):
    """Return current status and URL for a sandbox."""
    svc_url = _get_svc_url(sandbox_id)
    if not svc_url:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")

    return SandboxResponse(
        sandbox_id=sandbox_id,
        sandbox_url=svc_url,
        status=_get_pod_phase(sandbox_id),
        detail=_get_pod_failure_detail(sandbox_id),
    )


@app.get("/api/sandboxes")
async def list_sandboxes():
    """List every sandbox currently managed in the namespace."""
    try:
        services = core_v1.list_namespaced_service(
            K8S_NAMESPACE,
            label_selector="app=skillhub-sandbox",
        )
    except ApiException as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to list services: {exc.reason}"
        )

    sandboxes: list[SandboxResponse] = []
    for svc in services.items:
        sid = (svc.metadata.labels or {}).get("sandbox-id")
        if not sid:
            continue
        sandboxes.append(
            SandboxResponse(
                sandbox_id=sid,
                sandbox_url=_svc_url(sid),
                status=_get_pod_phase(sid),
            )
        )

    return {"sandboxes": sandboxes, "count": len(sandboxes)}
