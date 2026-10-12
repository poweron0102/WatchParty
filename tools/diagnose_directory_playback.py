"""Isolated browser check, without importing save.json or modifying the library.

python tools/diagnose_directory_playback.py --root PATH --media RELATIVE_PATH
Open http://127.0.0.1:8769. Ctrl+C stops and reaps the FFmpeg producers.
"""
import argparse
import sys
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from media_sources.plugins.directory.backend import create_source
from playback import PlaybackModule, PlaybackSelection, ResourceRequest

HTML = '''<!doctype html><meta charset="utf-8"><title>Local playback diagnostic</title>
<video id="video" controls muted style="width:min(900px,100%)"></video>
<p><button id="start">Play</button><button id="seek60">Seek 60s</button>
<button id="seek600">Seek 600s</button><button id="back">Back to 10s</button></p>
<pre id="stats"></pre><script src="/shaka.js"></script><script>
const video=document.getElementById('video');
const errors=[]; let stalls=0, started=false, engine;
video.addEventListener('waiting',()=>{if(started)stalls++;});
video.addEventListener('playing',()=>{started=true;});
document.getElementById('start').onclick=async()=>{
 try {
  if(!engine){shaka.polyfill.installAll();engine=new shaka.Player();await engine.attach(video);
   engine.addEventListener('error',e=>errors.push({code:e.detail.code,data:e.detail.data}));
   engine.configure({streaming:{bufferingGoal:30,rebufferingGoal:2}});
   const descriptor=await (await fetch('/select')).json();await engine.load(descriptor.url);}
  await video.play();
 }catch(e){errors.push({message:String(e),code:e.code,data:e.data});}
};
document.getElementById('seek60').onclick=()=>video.currentTime=60;
document.getElementById('seek600').onclick=()=>video.currentTime=600;
document.getElementById('back').onclick=()=>video.currentTime=10;
setInterval(async()=>{
 const ranges=Array.from({length:video.buffered.length},(_,i)=>[video.buffered.start(i),video.buffered.end(i)]);
 const server=await (await fetch('/status')).json();
 document.getElementById('stats').textContent=JSON.stringify({time:video.currentTime,duration:video.duration,
  paused:video.paused,readyState:video.readyState,stalls,errors,buffered:ranges,server},null,2);
},1000);
</script>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--media', required=True)
    parser.add_argument('--port', type=int, default=8769)
    parser.add_argument('--memory-cache-bytes', type=int, default=16 * 1024 * 1024)
    args = parser.parse_args()
    source = create_source('diagnostic', {'path': args.root, 'memory_cache_bytes': args.memory_cache_bytes})
    playback = PlaybackModule({'diagnostic': source})
    async def page(request):
        return web.Response(text=HTML, content_type='text/html')
    async def shaka(request):
        return web.FileResponse(ROOT / 'files/vendor/shaka/shaka-player.ui.js')
    async def select(request):
        descriptor = await playback.select(PlaybackSelection('diagnostic', args.media))
        return web.json_response({'url': f'/playback/{descriptor.playback_id}/asset/manifest.mpd'})
    async def asset(request):
        try:
            opened = await playback.open(request.match_info['playback'], request.match_info['resource'], ResourceRequest())
            data = b''.join([part async for part in opened.chunks])
            return web.Response(body=data, content_type=opened.content_type)
        except Exception as exc:
            print('asset failed:', type(exc).__name__, flush=True)
            return web.Response(status=503, text=type(exc).__name__)
    async def status(request):
        adapter = source._playback
        return web.json_response({'cache_bytes': adapter.cache.size_bytes, 'cache_limit': adapter.cache.max_bytes,
            'producers': [{'track': t, 'next': p.next_index, 'closed': p.closed,
                           'pid': p.process.pid if p.process else None} for _, t, p in adapter._producers]})
    async def close(app):
        await playback.aclose()
    app = web.Application()
    app.router.add_get('/', page)
    app.router.add_get('/shaka.js', shaka)
    app.router.add_get('/select', select)
    app.router.add_get('/status', status)
    app.router.add_get('/playback/{playback}/asset/{resource}', asset)
    app.on_cleanup.append(close)
    web.run_app(app, host='127.0.0.1', port=args.port, access_log=None)


if __name__ == '__main__':
    main()
