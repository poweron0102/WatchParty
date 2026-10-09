"""Read bounded ISO BMFF boxes from a non-seekable FFmpeg pipe."""
import asyncio

from media_sources.errors import SourceUnavailable

MAX_BOX_BYTES = 64 * 1024 * 1024


def boxes(data, start=0, end=None):
    end = len(data) if end is None else end
    while start + 8 <= end:
        size = int.from_bytes(data[start:start + 4], 'big')
        header = 8
        if size == 1:
            size = int.from_bytes(data[start + 8:start + 16], 'big')
            header = 16
        elif size == 0:
            size = end - start
        if size < header or start + size > end:
            raise SourceUnavailable('box MP4 inválido')
        yield data[start + 4:start + 8], start, start + header, start + size
        start += size


async def read_box(stream):
    try:
        header = await asyncio.wait_for(stream.readexactly(8), 60)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            return None
        raise SourceUnavailable('cabeçalho MP4 incompleto') from exc
    size = int.from_bytes(header[:4], 'big')
    if size == 1:
        header += await asyncio.wait_for(stream.readexactly(8), 60)
        size = int.from_bytes(header[8:16], 'big')
    if size < len(header) or size > MAX_BOX_BYTES:
        raise SourceUnavailable('fragmento MP4 excede o limite de leitura')
    return header + await asyncio.wait_for(stream.readexactly(size - len(header)), 60)


def media_timescale(init):
    def descend(start, end):
        for kind, _, payload, stop in boxes(init, start, end):
            if kind == b'mdhd':
                offset = payload + (20 if init[payload] == 1 else 12)
                return int.from_bytes(init[offset:offset + 4], 'big')
            if kind in (b'moov', b'trak', b'mdia'):
                result = descend(payload, stop)
                if result:
                    return result
    value = descend(0, len(init))
    if not value:
        raise SourceUnavailable('MP4 sem escala de tempo')
    return value


def timestamp_fragment(moof: bytes, start: float, timescale: int) -> bytes:
    """FFmpeg resets tfdt on a seek; restore the presentation's absolute clock."""
    result = bytearray(moof)
    for kind, _, payload, end in boxes(result):
        if kind != b'moof':
            continue
        for child, _, inner, stop in boxes(result, payload, end):
            if child != b'traf':
                continue
            for field, _, value, _ in boxes(result, inner, stop):
                if field == b'tfdt':
                    width = 8 if result[value] == 1 else 4
                    result[value + 4:value + 4 + width] = round(start * timescale).to_bytes(width, 'big')
                    return bytes(result)
    raise SourceUnavailable('fragmento MP4 sem timestamp')


def _split_fragmented_mp4(data: bytes) -> tuple[bytes, bytes]:
    for kind, start, _, _ in boxes(data):
        if kind in (b'moof', b'styp', b'sidx'):
            return data[:start], data[start:]
    raise SourceUnavailable('FFmpeg não produziu fMP4 fragmentado')
