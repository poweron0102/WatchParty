"""Exercise real FFmpeg pipes, cache eviction and the public playback seam."""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from media_sources.plugins.directory.backend import create_source
from media_sources.plugins.directory.memory import MemorySegments
from media_sources.plugins.directory.encoder import EncoderChoice
from media_sources.errors import InvalidSourceConfiguration, SourceUnavailable
from playback.models import SegmentArtifact, SegmentDemand, DemandPriority


class MemoryTests(unittest.TestCase):
    def test_lru_limit_and_in_flight_references(self):
        cache = MemorySegments(8)
        first = SegmentArtifact.from_bytes(b'aaaa', 'video/mp4')
        cache.put(('a',), first)
        cache.put(('b',), SegmentArtifact.from_bytes(b'bbbb', 'video/mp4'))
        self.assertIs(cache.get(('a',)), first)
        cache.put(('c',), SegmentArtifact.from_bytes(b'cccc', 'video/mp4'))
        self.assertIsNone(cache.get(('b',)))
        self.assertEqual(cache.size_bytes, 8)
        cache.put(('huge',), SegmentArtifact.from_bytes(b'x' * 9, 'video/mp4'))
        self.assertIsNone(cache.get(('huge',)))
        cache.clear()
        self.assertEqual(cache.size_bytes, 0)
        self.assertEqual(first.data, b'aaaa', 'eviction must not invalidate an active response')

    def test_source_configuration_rejects_invalid_limits(self):
        with tempfile.TemporaryDirectory() as root:
            for value in (-1, True, 1.5, '256'):
                with self.subTest(value=value), self.assertRaises(InvalidSourceConfiguration):
                    create_source('local', {'path': root, 'memory_cache_bytes': value})


class HardwareTests(unittest.IsolatedAsyncioTestCase):
    async def test_unusable_hardware_falls_back_to_software(self):
        async def unavailable(command, timeout=30):
            if '-encoders' in command:
                return b'h264_amf h264_nvenc h264_qsv'
            raise SourceUnavailable('driver failure')
        stream = dict(index=0, codec_name='hevc', width=1920, height=1080,
                      pix_fmt='yuv420p10le', avg_frame_rate='24000/1001')
        with patch('media_sources.plugins.directory.encoder.run', side_effect=unavailable):
            self.assertEqual(await EncoderChoice('ffmpeg', 'auto').choose('input', stream), ('libx264', ()))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg integration')
class DirectoryPlaybackTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='watchparty-playback-tests-')
        cls.root = Path(cls.temp.name)
        cls.media = 'compatible.mp4'
        command = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=25',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-f', 'lavfi',
            '-i', 'sine=frequency=880:sample_rate=48000', '-t', '13', '-map', '0:v', '-map', '1:a',
            '-map', '2:a', '-c:v', 'libx264', '-preset', 'ultrafast', '-profile:v', 'baseline',
            '-g', '50', '-keyint_min', '50', '-sc_threshold', '0', '-c:a', 'aac', '-y', str(cls.root / cls.media)]
        subprocess.run(command, capture_output=True, check=True, timeout=30)
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(cls.root / cls.media), '-map', '0:v',
            '-map', '0:a:0', '-c:v', 'mpeg4', '-c:a', 'ac3', '-y', str(cls.root / 'incompatible.mkv')],
            capture_output=True, check=True, timeout=30)
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(cls.root / cls.media), '-map', '0:v',
            '-an', '-c:v', 'libx264', '-preset', 'fast', '-g', '50', '-sc_threshold', '0',
            '-bf', '3', '-y', str(cls.root / 'bframes.mp4')], capture_output=True, check=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    async def asyncSetUp(self):
        with patch.object(Path, 'mkdir', side_effect=AssertionError('source requires a writable library')):
            self.source = create_source('local', {'path': str(self.root), 'ffmpeg_path': shutil.which('ffmpeg'),
                                                'hardware_acceleration': 'software'})

    async def asyncTearDown(self):
        await self.source.aclose()

    @staticmethod
    def demand(track, identity, priority=DemandPriority.PLAYBACK):
        return SegmentDemand(track.id, track.representations[0].id, identity, priority)

    async def test_copy_continuous_multi_viewer_and_no_disk_writes(self):
        before = set(self.root.rglob('*'))
        spawn = asyncio.create_subprocess_exec
        with patch.object(Path, 'write_bytes', side_effect=AssertionError('disk write')), \
             patch.object(Path, 'mkdir', side_effect=AssertionError('mkdir')), \
             patch('tempfile.mkstemp', side_effect=AssertionError('temporary disk file')), \
             patch('asyncio.create_subprocess_exec', wraps=spawn) as processes:
            presentation = await self.source.inspect(self.media)
            video = next(t for t in presentation.tracks if t.kind == 'video')
            init = await self.source.materialize(self.media, self.demand(video, 'init'))
            self.assertIsNone(init.path)
            fragments = []
            for i in range(4):
                pair = await asyncio.gather(*(self.source.materialize(self.media, self.demand(video, str(i), p))
                    for p in (DemandPriority.PLAYBACK, DemandPriority.CANONICAL)))
                self.assertIs(pair[0], pair[1])
                fragments.append(pair[0].data)
            self.assertEqual(processes.call_count, 1, 'adjacent segments must reuse one FFmpeg')
            command = processes.call_args.args
            self.assertEqual(command[command.index('-c:v') + 1], 'copy')
            self.assertEqual(command[-1], 'pipe:1')
            self.assertEqual(set(self.root.rglob('*')), before)
        packets = await self.packet_info(init.data + b''.join(fragments))
        self.assertEqual(len(packets), 200)
        self.assertAlmostEqual(float(packets[-1]['dts_time']), 7.96, places=2)

    async def packet_info(self, data):
        def inspect():
            result = subprocess.run(['ffprobe', '-v', 'error', '-i', 'pipe:0', '-show_packets',
                '-show_entries', 'packet=pts_time,dts_time,duration_time', '-of', 'json'],
                input=data, capture_output=True, timeout=20, check=True)
            return json.loads(result.stdout)['packets']
        return await asyncio.to_thread(inspect)

    async def test_seek_after_eviction_restores_absolute_timestamps(self):
        presentation = await self.source.inspect(self.media)
        video = next(t for t in presentation.tracks if t.kind == 'video')
        init = await self.source.materialize(self.media, self.demand(video, 'init'))
        await self.source.release(self.media)
        self.source._playback.cache.clear()
        segment = await self.source.materialize(self.media, self.demand(video, '3'))
        packets = await self.packet_info(init.data + segment.data)
        self.assertAlmostEqual(float(packets[0]['dts_time']), 6.0, places=2)
        self.assertEqual(len(packets), 50)
        await self.source.release(self.media)
        self.source._playback.cache.clear()
        back = await self.source.materialize(self.media, self.demand(video, '1'))
        packets = await self.packet_info(init.data + back.data)
        self.assertAlmostEqual(float(packets[0]['dts_time']), 2.0, places=2)

    async def test_software_transcode_continuous_and_audio_track_selection(self):
        presentation = await self.source.inspect('incompatible.mkv')
        video = next(t for t in presentation.tracks if t.kind == 'video')
        init = await self.source.materialize('incompatible.mkv', self.demand(video, 'init'))
        pieces = [await self.source.materialize('incompatible.mkv', self.demand(video, str(i))) for i in range(3)]
        packets = await self.packet_info(init.data + b''.join(s.data for s in pieces))
        self.assertEqual(len(packets), 300)
        self.assertAlmostEqual(float(packets[-1]['dts_time']), 11.96, places=2)
        original = await self.source.inspect(self.media)
        audio = [t for t in original.tracks if t.kind == 'audio']
        first = await self.source.materialize(self.media, self.demand(audio[0], '0'))
        second = await self.source.materialize(self.media, self.demand(audio[1], '0'))
        self.assertNotEqual(first.sha256, second.sha256, 'different audio tracks must not both map to 0:a:0')

    async def test_zero_cache_keeps_playback_working(self):
        await self.source.aclose()
        self.source = create_source('local', {'path': str(self.root), 'ffmpeg_path': shutil.which('ffmpeg'),
            'hardware_acceleration': 'software', 'memory_cache_bytes': 0})
        presentation = await self.source.inspect(self.media)
        video = next(t for t in presentation.tracks if t.kind == 'video')
        artifact = await self.source.materialize(self.media, self.demand(video, '0'))
        self.assertGreater(artifact.size, 0)
        self.assertEqual(self.source._playback.cache.size_bytes, 0)
        self.assertIsNone(self.source.locate(self.media, self.demand(video, '0')))

    async def test_release_reaps_ffmpeg(self):
        presentation = await self.source.inspect(self.media)
        video = next(t for t in presentation.tracks if t.kind == 'video')
        await self.source.materialize(self.media, self.demand(video, 'init'))
        producer = self.source._playback._producers[0][2]
        await self.source.release(self.media)
        self.assertTrue(producer.task.done())
        self.assertIsNotNone(producer.process.returncode)

    async def test_failed_producer_releases_waiters_and_allows_retry(self):
        presentation = await self.source.inspect(self.media)
        video = next(t for t in presentation.tracks if t.kind == 'video')
        with patch.object(self.source._playback, '_command', return_value=['ffmpeg', '-v', 'error', '-invalid_option']):
            with self.assertRaises(SourceUnavailable):
                await asyncio.wait_for(self.source.materialize(self.media, self.demand(video, '0')), 5)
        artifact = await asyncio.wait_for(self.source.materialize(self.media, self.demand(video, '0')), 5)
        self.assertGreater(artifact.size, 0)

    async def test_idle_producer_stops_without_encoding_the_entire_file(self):
        from media_sources.plugins.directory.producer import SegmentProducer
        with patch.object(SegmentProducer, 'IDLE_SECONDS', .05):
            presentation = await self.source.inspect(self.media)
            video = next(t for t in presentation.tracks if t.kind == 'video')
            await self.source.materialize(self.media, self.demand(video, '0'))
            producer = self.source._playback._producers[0][2]
            await asyncio.wait_for(asyncio.shield(producer.task), 5)
            self.assertLess(producer.next_index, len(video.representations[0].segments))
            self.assertIsNotNone(producer.process.returncode)

    async def test_copy_bframes_preserves_frames_across_segments_and_seeks(self):
        presentation = await self.source.inspect('bframes.mp4')
        video = presentation.tracks[0]
        init = await self.source.materialize('bframes.mp4', self.demand(video, 'init'))
        fragments = [await self.source.materialize('bframes.mp4', self.demand(video, str(i))) for i in range(4)]
        def hashes(data=None, start=None):
            command = ['ffmpeg', '-v', 'error']
            if start is not None and data is None:
                command += ['-ss', str(start)]
            command += ['-i', 'pipe:0' if data else str(self.root / 'bframes.mp4'), '-an']
            command += ['-t', '2' if start is not None else '8', '-f', 'framemd5', '-']
            result = subprocess.run(command, input=data, capture_output=True, check=True, timeout=20)
            return [line.rsplit(b',', 1)[-1].strip() for line in result.stdout.splitlines() if line and not line.startswith(b'#')]
        converted = await asyncio.to_thread(hashes, init.data + b''.join(s.data for s in fragments))
        original = await asyncio.to_thread(hashes)
        self.assertEqual(converted, original)
        await self.source.release('bframes.mp4')
        self.source._playback.cache.clear()
        seek = await self.source.materialize('bframes.mp4', self.demand(video, '3'))
        converted = await asyncio.to_thread(hashes, init.data + seek.data, 6)
        original = await asyncio.to_thread(hashes, None, 6)
        self.assertEqual(converted, original)
