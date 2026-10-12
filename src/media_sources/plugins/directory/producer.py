"""One demand-driven FFmpeg process produces a run of adjacent segments."""
from __future__ import annotations

import asyncio
import logging

from media_sources.errors import SourceUnavailable
from playback.models import SegmentArtifact
from .fragmented_mp4 import media_timescale, read_box, timestamp_fragment

LOG = logging.getLogger(__name__)


class SegmentProducer:
    PREFETCH = 2
    IDLE_SECONDS = 15

    def __init__(self, command, track, start_index, publish, changed):
        self.command, self.track = command, track
        self.next_index = start_index
        self.wanted = start_index
        self.publish, self.changed = publish, changed
        self.pending = {}
        self.wake = asyncio.Event()
        self.task = None
        self.process = None
        self.initialized = False
        self.closed = False
        self.error = None

    def can_serve(self, identity):
        if self.closed:
            return False
        if identity in self.pending:
            return True
        if identity == 'init':
            return not self.initialized
        index = int(identity)
        return self.next_index <= index <= self.next_index + self.PREFETCH + 2

    def request(self, identity):
        future = self.pending.get(identity)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            self.pending[identity] = future
        if identity != 'init':
            self.wanted = max(self.wanted, int(identity))
        self.wake.set()
        if self.task is None:
            self.task = asyncio.create_task(self._run())
        return future

    def _deliver(self, identity, data):
        artifact = SegmentArtifact.from_bytes(data, f'{self.track.kind}/mp4')
        self.publish(identity, artifact)
        waiter = self.pending.pop(identity, None)
        if waiter is not None and not waiter.done():
            waiter.set_result(artifact)
        self.changed.set()

    async def _drain_errors(self):
        # Drain without accumulating a log or exposing filenames in HTTP errors.
        while await self.process.stderr.read(8192):
            pass

    async def _run(self):
        stderr = None
        try:
            self.process = await asyncio.create_subprocess_exec(*self.command,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=128 * 1024)
            stderr = asyncio.create_task(self._drain_errors())
            init = bytearray()
            while True:
                box = await read_box(self.process.stdout)
                if box is None:
                    raise SourceUnavailable('FFmpeg não produziu a inicialização')
                init.extend(box)
                if len(init) > 4 * 1024 * 1024:
                    raise SourceUnavailable('inicialização MP4 excessiva')
                if box[4:8] == b'moov':
                    break
            timescale = media_timescale(init)
            self.initialized = True
            self._deliver('init', bytes(init))
            del init
            segments = self.track.representation.segments
            while self.next_index < len(segments):
                if self.next_index > self.wanted + self.PREFETCH:
                    self.wake.clear()
                    try:
                        await asyncio.wait_for(self.wake.wait(), self.IDLE_SECONDS)
                    except TimeoutError:
                        break
                    continue
                moof = await read_box(self.process.stdout)
                if moof is None:
                    break
                if moof[4:8] != b'moof':
                    continue
                mdat = await read_box(self.process.stdout)
                if mdat is None or mdat[4:8] != b'mdat':
                    raise SourceUnavailable('fragmento MP4 incompleto')
                segment = segments[self.next_index]
                data = timestamp_fragment(moof, segment.start, timescale) + mdat
                self.next_index += 1
                self._deliver(segment.identity, data)
                del data, mdat, moof
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.error = SourceUnavailable('falha na produção de segmentos locais')
            LOG.warning('Directory playback producer failed: %s', type(exc).__name__)
        finally:
            self.closed = True
            await self._terminate()
            if stderr:
                await asyncio.gather(stderr, return_exceptions=True)
            for waiter in self.pending.values():
                if not waiter.done():
                    waiter.set_exception(self.error or SourceUnavailable('produção local encerrada; solicite novamente'))
            self.pending.clear()
            self.changed.set()

    async def _terminate(self):
        if self.process is None:
            return
        if self.process.returncode is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass
        # Proactor transports need their pipes drained before wait on Windows.
        while await self.process.stdout.read(64 * 1024):
            pass
        await self.process.wait()

    async def aclose(self):
        if self.task and not self.task.done() and not self.closed:
            self.task.cancel()
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)
