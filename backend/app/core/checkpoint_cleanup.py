"""LangGraph checkpoint 表清理（keep_latest 语义）。

生产环境使用 ``AsyncPostgresSaver`` 持久化 agent 状态，checkpoint 表
（``checkpoints`` / ``checkpoint_blobs`` / ``checkpoint_writes``）会随每次
节点切换持续写入，且 ``langgraph-checkpoint-postgres`` 后端没有内置 TTL 清理
（其 ``prune`` / ``aprun`` 在 postgres 后端尚未实现）。

本模块提供后台任务，周期性删除「写入时间超过保留期」的**中间快照**，但每个
thread（严格说是 ``(thread_id, checkpoint_ns)``）**永远保留最新一条**。最新
checkpoint 的 ``channel_versions`` 引用了完整的累积 state（primitive 值内联在
``checkpoint`` JSONB、复杂值如 messages 存 ``checkpoint_blobs``），因此续聊时
agent 仍能完整恢复上下文，不会「失忆」。

语义取舍：

* 保留：每个 thread 最新一条 checkpoint（= 续聊恢复能力）。
* 删除：超过 TTL 的旧快照 + 它们专属的 ``checkpoint_writes`` + 不再被任何
  剩余 checkpoint 引用的孤儿 ``checkpoint_blobs``。
* 失去：回退到很久之前某个中间步骤的「时间旅行」能力（几乎不被使用）。

前提：checkpointer 的 ``connection_string`` 与主业务库 ``DATABASE_URL``
指向同一个 PostgreSQL 数据库，因此直接复用 SQLAlchemy ``engine`` 执行清理。
若未来拆分数据库，需改用 checkpointer 自身的连接池。
"""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import bindparam, text

from app.models.database import engine

#: 单次清理最多处理的 checkpoint 数，避免超长事务锁表。
_MAX_CHECKPOINTS_PER_BATCH = 1000

# 找出「超过 TTL 且不是 thread 最新一条」的 checkpoint。
# checkpoint_id 是 uuid6（时间有序），字典序即时间序，故用 ORDER BY
# checkpoint_id DESC 取每个 (thread, ns) 的最新一条（与 langgraph 自身一致）。
_SELECT_EXPIRED_CHECKPOINTS = text(
    """
    SELECT thread_id, checkpoint_ns, checkpoint_id
    FROM (
        SELECT thread_id,
               checkpoint_ns,
               checkpoint_id,
               (checkpoint ->> 'ts')::timestamptz AS ts,
               row_number() OVER (
                   PARTITION BY thread_id, checkpoint_ns
                   ORDER BY checkpoint_id DESC
               ) AS rn
        FROM checkpoints
    ) ranked
    WHERE ranked.rn > 1
      AND ranked.ts < now() - make_interval(days => :ttl_days)
    ORDER BY ranked.ts
    LIMIT :batch
    """
)

# 删除旧 checkpoint 专属的中间写入与快照行；IN 用 expanding 展开为参数列表，
# thread_id 条件用于命中 thread_id 索引，避免全表扫描。
_DELETE_WRITES = text(
    """
    DELETE FROM checkpoint_writes
    WHERE thread_id IN :thread_ids
      AND checkpoint_id IN :checkpoint_ids
    """
).bindparams(bindparam("thread_ids", expanding=True), bindparam("checkpoint_ids", expanding=True))

_DELETE_CHECKPOINTS = text(
    """
    DELETE FROM checkpoints
    WHERE thread_id IN :thread_ids
      AND checkpoint_id IN :checkpoint_ids
    """
).bindparams(bindparam("thread_ids", expanding=True), bindparam("checkpoint_ids", expanding=True))

# 删除孤儿 blob：不再被任何**剩余** checkpoint 的 channel_versions 引用的
# (channel, version)。checkpoint_blobs 按 (channel, version) 全局累积，多个
# checkpoint 可能共享同一 channel 的同一 version，故只能删「无人引用」的。
_DELETE_ORPHAN_BLOBS = text(
    """
    DELETE FROM checkpoint_blobs b
    WHERE b.thread_id IN :thread_ids
      AND NOT EXISTS (
          SELECT 1
          FROM checkpoints c
          WHERE c.thread_id = b.thread_id
            AND c.checkpoint_ns = b.checkpoint_ns
            AND c.checkpoint -> 'channel_versions' ->> b.channel = b.version
      )
    """
).bindparams(bindparam("thread_ids", expanding=True))


async def cleanup_expired_checkpoints(ttl_days: int, *, batch: int = _MAX_CHECKPOINTS_PER_BATCH) -> int:
    """删除「写入时间超过 ``ttl_days`` 天」的中间 checkpoint，保留每 thread 最新一条。

    Args:
        ttl_days: 保留天数。只删除 ``ts`` 早于 ``now() - ttl_days`` 的 checkpoint，
            且永远跳过每个 thread 的最新一条。
        batch: 单次最多处理的 checkpoint 数。

    Returns:
        本次删除的 checkpoint 数量（0 表示没有可清理的数据）。
    """
    async with engine.connect() as conn:
        result = await conn.execute(_SELECT_EXPIRED_CHECKPOINTS, {"ttl_days": ttl_days, "batch": batch})
        rows = result.fetchall()
        if not rows:
            return 0

        checkpoint_ids = [row[2] for row in rows]
        thread_ids = list({row[0] for row in rows})

        # 结束上面的只读查询事务；下面的删除走独立事务，一起提交，
        # 避免 checkpoint 删了而 blobs/writes 残留。
        await conn.commit()

        await conn.execute(_DELETE_WRITES, {"thread_ids": thread_ids, "checkpoint_ids": checkpoint_ids})
        await conn.execute(_DELETE_CHECKPOINTS, {"thread_ids": thread_ids, "checkpoint_ids": checkpoint_ids})
        await conn.execute(_DELETE_ORPHAN_BLOBS, {"thread_ids": thread_ids})
        await conn.commit()

    return len(checkpoint_ids)


async def run_cleanup_loop(
    ttl_days: int,
    interval_seconds: int,
    stop_event: asyncio.Event,
) -> None:
    """周期性执行 checkpoint 清理，直到 ``stop_event`` 被设置。

    首次清理在 ``interval_seconds`` 后触发（不阻塞应用启动）。
    """
    logger.info("Checkpoint cleanup started: ttl={}d, interval={}s", ttl_days, interval_seconds)
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            logger.info("Checkpoint cleanup stopped.")
            return
        except TimeoutError:
            pass

        try:
            removed = await cleanup_expired_checkpoints(ttl_days)
            if removed:
                logger.info("Checkpoint cleanup removed {} expired checkpoint(s)", removed)
        except Exception:
            logger.exception("Checkpoint cleanup iteration failed")
