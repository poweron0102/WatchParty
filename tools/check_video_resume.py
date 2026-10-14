"""Exercise resume with the bundled Shaka, real DASH segments and headless Edge.

Uses a generated video and temporary browser profile; does not read save.json.
"""
import asyncio
import json
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from aiohttp import ClientSession, web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from media_sources.plugins.directory.backend import create_source
from playback import PlaybackModule, PlaybackSelection, ResourceRequest

HTML = '''<!doctype html><meta charset="utf-8">
<div><video id="player" muted></video></div>
<script src="/vendor/shaka/shaka-player.ui.js"></script>
<script type="module">
import {PlayerController} from '/modules/player-controller.js';
import {handleSyncEvent, handleSyncState, syncState} from '/modules/video-sync.js';
window.player = new PlayerController(document.querySelector('video'));
window.syncState = syncState;
window.run = async (mode) => {
    const selection = {source_id:'test', media_id:'episode.mp4'};
    const samples = [];
    const timer = setInterval(() => samples.push({time:player.currentTime, syncing:syncState.isSyncing}), 50);
    if (mode === 'set_video') {
        handleSyncEvent({type:'set_video', video:selection, time:18}, player, null, null,
            {value:true}, null, null, () => null, () => {});
    } else {
        handleSyncState({video:selection, time:18, paused:true}, player);
    }
    await new Promise(resolve => setTimeout(resolve, 2500));
    clearInterval(timer);
    return {time:player.currentTime, samples};
};
</script>'''


async def main():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        folder = Path(temporary)
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
            '-i', 'testsrc2=size=160x90:rate=25', '-t', '40', '-c:v', 'libx264',
            '-preset', 'ultrafast', '-g', '50', '-bf', '0', str(folder / 'episode.mp4')],
            check=True, capture_output=True, timeout=30)
        source = create_source('test', {'path': str(folder), 'hardware_acceleration': 'software'})
        playback = PlaybackModule({'test': source})
        async def page(request):
            return web.Response(text=HTML, content_type='text/html')
        async def select(request):
            # Slow enough to exercise suppression throughout asynchronous loading.
            await asyncio.sleep(.7)
            descriptor = await playback.select(PlaybackSelection('test', 'episode.mp4'))
            return web.json_response({'manifest': {'url': f'/playback/{descriptor.playback_id}/asset/manifest.mpd'}})
        async def asset(request):
            opened = await playback.open(request.match_info['playback'], request.match_info['resource'], ResourceRequest())
            data = b''.join([part async for part in opened.chunks])
            return web.Response(body=data, content_type=opened.content_type)
        app = web.Application()
        app.router.add_get('/', page)
        app.router.add_post('/api/playback/select', select)
        app.router.add_get('/playback/{playback}/asset/{resource}', asset)
        app.router.add_static('/', ROOT / 'files')
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            debug_port = available.getsockname()[1]
        browser = shutil.which('msedge') or r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
        process = subprocess.Popen([browser, '--headless=new', '--disable-gpu', '--no-sandbox',
            '--disable-breakpad', '--disable-crash-reporter', '--no-first-run',
            '--no-default-browser-check', '--remote-debugging-port=' + str(debug_port),
            '--user-data-dir=' + str(folder / 'browser'), 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            async with ClientSession() as session:
                for _ in range(100):
                    try:
                        async with session.get(f'http://127.0.0.1:{debug_port}/json/list') as response:
                            tabs = await response.json()
                        target = next(t for t in tabs if t['type'] == 'page')
                        break
                    except (OSError, StopIteration):
                        await asyncio.sleep(.1)
                else:
                    raise RuntimeError('Browser did not start')
                async with session.ws_connect(target['webSocketDebuggerUrl']) as ws:
                    identifier = 0
                    async def command(method, params):
                        nonlocal identifier
                        identifier += 1
                        await ws.send_json({'id': identifier, 'method': method, 'params': params})
                        while True:
                            message = await ws.receive_json(timeout=20)
                            if message.get('id') == identifier:
                                if 'error' in message:
                                    raise RuntimeError(message['error'])
                                return message.get('result', {})
                    async def evaluate(expression):
                        result = await command('Runtime.evaluate', {'expression': expression,
                            'awaitPromise': True, 'returnByValue': True})
                        if 'exceptionDetails' in result:
                            raise RuntimeError(result['exceptionDetails'])
                        return result['result'].get('value')
                    await command('Page.navigate', {'url': f'http://127.0.0.1:{port}/'})
                    for _ in range(100):
                        if await evaluate('typeof window.run === "function"'):
                            break
                        await asyncio.sleep(.1)
                    try:
                        for mode in ('set_video', 'sync_state'):
                            result = await evaluate(f'run({json.dumps(mode)})')
                            times = [s['time'] for s in result['samples']]
                            print(json.dumps({'mode': mode, 'final_time': result['time'],
                                'max_time': max(times), 'syncing_during_load': result['samples'][11]['syncing']}), flush=True)
                            assert abs(result['time'] - 18) < .5, 'Resume jumped back to the start'
                            assert result['samples'][11]['syncing'], 'Load guard ended before loading finished'
                    finally:
                        if not ws.closed:
                            await ws.send_json({'id': identifier + 1, 'method': 'Browser.close', 'params': {}})
        finally:
            try:
                await asyncio.to_thread(process.wait, 5)
            except subprocess.TimeoutExpired:
                process.terminate()
                await asyncio.to_thread(process.wait, 10)
            await playback.aclose()
            await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
