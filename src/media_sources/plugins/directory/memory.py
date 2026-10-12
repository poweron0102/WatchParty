"""Byte-bounded LRU shared by all viewers of one directory source."""
from collections import OrderedDict

from playback.models import SegmentArtifact


class MemorySegments:
    def __init__(self, max_bytes: int):
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
            raise ValueError('memory_cache_bytes deve ser um inteiro não negativo')
        self.max_bytes = max_bytes
        self.size_bytes = 0
        self._entries: OrderedDict[tuple, SegmentArtifact] = OrderedDict()

    def get(self, key):
        artifact = self._entries.get(key)
        if artifact is not None:
            self._entries.move_to_end(key)
        return artifact

    def put(self, key, artifact: SegmentArtifact):
        previous = self._entries.pop(key, None)
        if previous is not None:
            self.size_bytes -= previous.size
        # Oversized segments are delivered to waiters, never retained by the LRU.
        if artifact.size > self.max_bytes:
            return
        while self._entries and self.size_bytes + artifact.size > self.max_bytes:
            _, removed = self._entries.popitem(last=False)
            self.size_bytes -= removed.size
        self._entries[key] = artifact
        self.size_bytes += artifact.size

    def clear(self):
        self._entries.clear()
        self.size_bytes = 0
