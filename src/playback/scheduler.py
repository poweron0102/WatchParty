from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .models import SegmentArtifact, SegmentDemand
from .store import SegmentStore


class MaterializationPlanner:
    def __init__(self, store: SegmentStore | None, max_concurrency: int = 4):
        if max_concurrency <= 0: raise ValueError("max_concurrency deve ser positivo")
        self.store, self._slots = store, asyncio.Semaphore(max_concurrency)
        self._flights: dict[tuple[str, SegmentDemand], asyncio.Task[SegmentArtifact]] = {}
        self._lock = asyncio.Lock()

    async def materialize(self, media_id: str, demand: SegmentDemand,
                          factory: Callable[[], Awaitable[SegmentArtifact]], *, publish: bool = True) -> SegmentArtifact:
        if publish and self.store is None: raise RuntimeError("materialização sem cache exige um SegmentStore")
        ready = self.store.locate(media_id, demand) if publish else None
        if ready: return ready
        key = (media_id, demand)
        async with self._lock:
            task = self._flights.get(key)
            if task is None:
                task = asyncio.create_task(self._run(media_id, demand, factory, publish))
                self._flights[key] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._lock:
                    if self._flights.get(key) is task: self._flights.pop(key, None)

    async def _run(self, media_id, demand, factory, publish):
        async with self._slots:
            artifact = await factory()
            return await self.store.publish(media_id, demand, artifact) if publish else artifact
