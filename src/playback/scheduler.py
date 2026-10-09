from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .models import SegmentArtifact, SegmentDemand
from .store import SegmentStore


class MaterializationPlanner:
    def __init__(self, store: SegmentStore | None, max_concurrency: int = 4):
        if max_concurrency <= 0: raise ValueError("max_concurrency deve ser positivo")
        self.store, self._slots = store, asyncio.Semaphore(max_concurrency)
        self._flights: dict[tuple[str, ...], asyncio.Task[SegmentArtifact]] = {}
        self._lock = asyncio.Lock()

    async def materialize(self, media_id: str, demand: SegmentDemand,
                          factory: Callable[[], Awaitable[SegmentArtifact]], *, publish: bool = True,
                          namespace: str = '') -> SegmentArtifact:
        if publish and self.store is None: raise RuntimeError("materialização sem cache exige um SegmentStore")
        ready = self.store.locate(media_id, demand) if publish else None
        if ready: return ready
        # Priority describes a caller, not the bytes being requested. Namespace
        # prevents an expired presentation or another source sharing a flight.
        key = (namespace, media_id, demand.track_id, demand.representation_id, demand.segment_identity)
        async with self._lock:
            task = self._flights.get(key)
            if task is None:
                task = asyncio.create_task(self._run(media_id, demand, factory, publish))
                self._flights[key] = task
                task.add_done_callback(lambda done: self._finished(key, done))
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._lock:
                    if self._flights.get(key) is task: self._flights.pop(key, None)

    def _finished(self, key, task):
        # A timed-out HTTP caller leaves the shielded download running. Clean up
        # even when there are no callers left to retrieve its eventual failure.
        if self._flights.get(key) is task:
            self._flights.pop(key, None)
        if not task.cancelled():
            task.exception()

    async def _run(self, media_id, demand, factory, publish):
        async with self._slots:
            artifact = await factory()
            return await self.store.publish(media_id, demand, artifact) if publish else artifact

    async def aclose(self):
        tasks = list(self._flights.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
