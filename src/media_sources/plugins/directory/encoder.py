"""Choose a browser-safe H.264/AAC plan, probing real hardware before using it."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

from media_sources.errors import SourceUnavailable

LOG = logging.getLogger(__name__)
SEGMENT_SECONDS = 4


async def run(command, timeout=30):
    try:
        result = await asyncio.to_thread(subprocess.run, command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceUnavailable('ferramenta de mídia indisponível ou tempo esgotado') from exc
    if result.returncode:
        raise SourceUnavailable('ferramenta de mídia não conseguiu processar a entrada')
    return result.stdout


def ffprobe_path(ffmpeg):
    path = Path(ffmpeg)
    return str(path.with_name('ffprobe.exe' if path.suffix.lower() == '.exe' else 'ffprobe'))


async def probe(ffmpeg, path):
    raw = await run([ffprobe_path(ffmpeg), '-v', 'error', '-show_entries',
        'format=duration,start_time:stream=index,codec_name,codec_type,profile,level,width,height,'
        'pix_fmt,bit_rate,avg_frame_rate,r_frame_rate,sample_rate,channels,start_time:'
        'stream_disposition=attached_pic:stream_tags=language,title', '-of', 'json', str(path)])
    try:
        info = json.loads(raw)
        if not math.isfinite(float(info['format']['duration'])) or float(info['format']['duration']) <= 0:
            raise ValueError('duration')
        return info
    except (KeyError, ValueError, TypeError) as exc:
        raise SourceUnavailable('metadados da mídia local inválidos') from exc


def frame_rate(stream):
    for name in ('avg_frame_rate', 'r_frame_rate'):
        try:
            rate = Fraction(stream.get(name, '0'))
            if 0 < rate <= 240:
                return rate
        except (ValueError, ZeroDivisionError):
            pass
    return Fraction(30)


def copy_video(stream):
    return (stream.get('codec_name') == 'h264' and stream.get('pix_fmt') == 'yuv420p'
            and stream.get('profile') in ('Baseline', 'Constrained Baseline', 'Main', 'High')
            and 0 < int(stream.get('level', 0)) <= 52)


def copy_audio(stream):
    return (stream.get('codec_name') == 'aac' and stream.get('profile') == 'LC'
            and int(stream.get('sample_rate', 0)) in (44100, 48000)
            and 0 < int(stream.get('channels', 0)) <= 2)


def h264_level(stream):
    blocks = math.ceil(stream['width'] / 16) * math.ceil(stream['height'] / 16)
    rate = blocks * float(frame_rate(stream))
    for level, max_blocks, max_rate in ((31, 3600, 108000), (40, 8192, 245760),
            (42, 8704, 522240), (51, 36864, 983040), (52, 36864, 2073600), (62, 139264, 16711680)):
        if blocks <= max_blocks and rate <= max_rate:
            return level
    return 62


def video_options(encoder, stream):
    rate = frame_rate(stream)
    gop = math.ceil(float(rate) * SEGMENT_SECONDS)
    level = h264_level(stream)
    args = ['-c:v', encoder, '-pix_fmt', 'yuv420p', '-profile:v', 'high',
            '-level:v', f'{level // 10}.{level % 10}', '-bf', '0', '-g', str(gop),
            '-r', str(rate), '-fps_mode', 'cfr']
    if encoder == 'libx264':
        args += ['-preset', 'veryfast', '-crf', '20', '-sc_threshold', '0', '-threads', '2']
    elif encoder == 'h264_amf':
        args += ['-quality', 'balanced', '-rc', 'cqp', '-qp_i', '20', '-qp_p', '22']
    elif encoder == 'h264_nvenc':
        args += ['-preset', 'p4', '-rc', 'vbr', '-cq', '21', '-b:v', '0', '-no-scenecut', '1']
    elif encoder == 'h264_qsv':
        args += ['-global_quality', '21', '-look_ahead', '0', '-adaptive_i', '0']
    return args


class EncoderChoice:
    def __init__(self, ffmpeg, hardware):
        self.ffmpeg, self.hardware = ffmpeg, hardware
        self._choices = {}
        self._lock = asyncio.Lock()

    async def choose(self, path, stream):
        if self.hardware == 'software':
            return 'libx264', ()
        key = (stream.get('codec_name'), stream.get('pix_fmt'), stream.get('width'), stream.get('height'))
        async with self._lock:
            if key in self._choices:
                return self._choices[key]
            # A listed encoder is not proof that the driver/device can run it.
            available = (await run([self.ffmpeg, '-hide_banner', '-encoders'])).decode(errors='replace')
            candidates = ('h264_amf', 'h264_nvenc', 'h264_qsv') if sys.platform == 'win32' else ('h264_nvenc', 'h264_qsv')
            for encoder in candidates:
                if encoder not in available:
                    continue
                for acceleration in (('-hwaccel', 'auto'), ()):
                    command = [self.ffmpeg, '-nostdin', '-v', 'error', '-threads', '2', *acceleration,
                        '-i', str(path), '-map', f"0:{stream['index']}", '-an',
                        *video_options(encoder, stream), '-frames:v', '2', '-f', 'null', '-']
                    try:
                        await run(command, timeout=15)
                    except SourceUnavailable:
                        continue
                    self._choices[key] = (encoder, acceleration)
                    LOG.info('Directory playback: encoder=%s, hardware_decode=%s', encoder, bool(acceleration))
                    return self._choices[key]
            LOG.info('Directory playback: hardware unavailable; using libx264')
            self._choices[key] = ('libx264', ())
            return self._choices[key]


async def video_keyframes(ffmpeg, path, stream, duration):
    """Packet inspection only: no decoded images and no output files."""
    raw = await run([ffprobe_path(ffmpeg), '-v', 'error', '-select_streams', str(stream['index']),
        '-show_packets', '-show_entries', 'packet=pts_time,flags', '-of', 'compact=p=0', str(path)], timeout=60)
    starts = []
    offset = float(stream.get('start_time') or 0)
    for line in raw.decode(errors='replace').splitlines():
        fields = dict(part.split('=', 1) for part in line.split('|') if '=' in part)
        if 'K' not in fields.get('flags', ''):
            continue
        try:
            value = max(0.0, float(fields['pts_time']) - offset)
        except (KeyError, ValueError):
            continue
        if math.isfinite(value) and value < duration and (not starts or value > starts[-1] + .001):
            starts.append(value)
    if not starts or starts[0] > .1:
        raise SourceUnavailable('vídeo sem índice de keyframes utilizável')
    starts[0] = 0.0
    return starts


async def avc_codec(ffmpeg, path, stream):
    raw = await run([ffprobe_path(ffmpeg), '-v', 'error', '-select_streams', str(stream['index']),
        '-show_entries', 'stream=extradata', '-show_data', '-of', 'json', str(path)])
    dump = json.loads(raw)['streams'][0].get('extradata', '')
    try:
        data = bytes.fromhex(''.join(line.split(':', 1)[1].split('  ')[0].replace(' ', '')
                                     for line in dump.splitlines() if ':' in line))
        if len(data) >= 4 and data[0] == 1:
            return 'avc1.' + data[1:4].hex()
    except ValueError:
        pass
    profile = {'Baseline': '4200', 'Constrained Baseline': '42e0', 'Main': '4d00', 'High': '6400'}[stream['profile']]
    return f"avc1.{profile}{int(stream['level']):02x}"
