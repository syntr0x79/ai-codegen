"""Worker heartbeat -- periodic write to DB while job is running."""
from __future__ import annotations

import asyncio
import logging

from src.db import Database

logger = logging.getLogger(__name__)


class Heartbeat:
    def __init__(self, db: Database, worker_id: str):
        self.db = db
        self.worker_id = worker_id
        self._task: asyncio.Task | None = None
        self._step_id: int | None = None

    async def start(self, step_id: int) -> None:
        self._step_id = step_id
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._step_id:
            try:
                await self.db._pool.execute(
                    "DELETE FROM worker_heartbeats WHERE step_id = $1", self._step_id
                )
            except Exception:
                pass
            self._step_id = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.db._pool.execute(
                    """INSERT INTO worker_heartbeats (step_id, worker_id, last_heartbeat)
                       VALUES ($1, $2, now())
                       ON CONFLICT (step_id)
                       DO UPDATE SET last_heartbeat = now(), worker_id = $2""",
                    self._step_id, self.worker_id,
                )
            except Exception as e:
                logger.warning(f"Heartbeat write failed: {e}")
            await asyncio.sleep(30)
