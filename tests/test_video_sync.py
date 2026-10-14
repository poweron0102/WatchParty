"""Resume and load races at the actual sync/controller call boundary."""
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
PRELUDE = r'''
import assert from 'node:assert/strict';
import {PlayerController} from './player-controller.mjs';
import {handleSyncEvent, handleSyncState, handleForceSync, syncState} from './video-sync.mjs';
const tick = async () => { for (let i=0; i<15; i++) await Promise.resolve(); };
const deferred = () => { let resolve; const promise = new Promise(r => resolve=r); return {promise, resolve}; };
let timers = new Map(), nextTimer = 0;
globalThis.setTimeout = callback => { timers.set(++nextTimer, callback); return nextTimer; };
globalThis.clearTimeout = id => timers.delete(id);
const settle = () => { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(f => f()); };
globalThis.localStorage = {getItem: () => null, setItem() {}};
class Engine extends EventTarget {
    constructor() { super(); this.loads = []; }
    async attach(video) { this.video = video; }
    configure() {}
    getVariantTracks() { return []; }
    async load(url, startTime = null) {
        this.loads.push({url, startTime});
        // Real Shaka schedules its initial seek beyond the load promise.
        this.initialSeek = () => { this.video.currentTime = startTime ?? 0; };
    }
    async unload() { this.video.currentTime = 0; }
}
class Overlay { static TrackLabelFormat = {LABEL: 'label'}; configure() {} }
globalThis.shaka = {polyfill: {installAll() {}}, Player: Engine, ui: {Overlay}};
const video = new EventTarget();
Object.assign(video, {currentTime: 0, paused: true, srcObject: null, parentElement: {},
    removeAttribute() {}, pause() { this.paused = true; }, async play() { this.paused = false; }});
const player = new PlayerController(video);
const selection = id => ({source_id: 'test', media_id: id});
globalThis.fetch = async (_url, options) => ({ok: true, json: async () => ({
    manifest: {url: JSON.parse(options.body).media_id + '.mpd'},
})});
const event = data => handleSyncEvent(data, player, null, null, {value: false}, null, null, () => null, () => {});
'''


def run_case(body):
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        for name in ('video-sync', 'player-controller'):
            source = (ROOT / f'files/modules/{name}.js').read_text(encoding='utf-8')
            source = source.replace("./notifications.js", "./notifications.mjs")
            source = source.replace("./screen-share.js", "./screen-share.mjs")
            source = source.replace("./subtitle-preferences.js", "./subtitle-preferences.mjs")
            (folder / f'{name}.mjs').write_text(source, encoding='utf-8')
        (folder / 'notifications.mjs').write_text('export function showNotification() {}', encoding='utf-8')
        (folder / 'screen-share.mjs').write_text(
            "export const isScreenShareVideo = video => video === 'screen-share';", encoding='utf-8')
        (folder / 'subtitle-preferences.mjs').write_text(
            'export class SubtitlePreferences { begin() {} async loaded() {} unload() {} }', encoding='utf-8')
        (folder / 'case.mjs').write_text(PRELUDE + textwrap.dedent(body), encoding='utf-8')
        result = subprocess.run([NODE, str(folder / 'case.mjs')], capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise AssertionError(result.stderr)


@unittest.skipUnless(NODE, 'Node unavailable')
class VideoResumeTests(unittest.TestCase):
    def test_selected_episode_keeps_resume_after_shaka_initial_seek(self):
        run_case('''
            await event({type:'set_video', video:selection('episode'), time:180});
            player.engine.initialSeek();
            settle();
            assert.equal(player.currentTime, 180, 'late initial seek must preserve resume');
            assert.equal(player.paused, true);
            assert.equal(syncState.isSyncing, false);
        ''')

    def test_joining_viewer_loads_at_room_time_and_preserves_play_state(self):
        run_case('''
            await handleSyncState({video:selection('episode'), time:240, paused:false}, player);
            player.engine.initialSeek();
            settle();
            assert.equal(player.currentTime, 240);
            assert.equal(player.paused, false);
        ''')

    def test_slow_selection_blocks_force_sync_and_exposes_saved_host_time(self):
        run_case('''
            const pending = deferred();
            const originalFetch = fetch;
            globalThis.fetch = async (...args) => { await pending.promise; return originalFetch(...args); };
            const loading = event({type:'set_video', video:selection('episode'), time:180});
            await tick(); settle();
            assert.equal(syncState.isSyncing, true, 'guard must outlast the load');
            assert.deepEqual(syncState.loadingState, {time:180, paused:true});
            syncState.syncRequestTime = Date.now();
            handleForceSync({time:0, paused:false}, player, {value:false}, {});
            assert.equal(player.paused, true);
            pending.resolve(); await loading;
            player.engine.initialSeek(); settle();
            assert.equal(player.currentTime, 180);
            assert.equal(syncState.loadingState, null);
            assert.equal(syncState.isSyncing, false);
        ''')

    def test_older_selection_response_cannot_replace_new_episode(self):
        run_case('''
            const first = deferred();
            const originalFetch = fetch;
            globalThis.fetch = async (...args) => {
                if (JSON.parse(args[1].body).media_id === 'first') await first.promise;
                return originalFetch(...args);
            };
            const old = event({type:'set_video', video:selection('first'), time:180});
            await tick();
            await event({type:'set_video', video:selection('second'), time:240});
            first.resolve(); await old;
            player.engine.initialSeek(); settle();
            assert.deepEqual(player.engine.loads.map(load => load.url), ['second.mpd']);
            assert.equal(player.currentTime, 240);
            assert.equal(syncState.currentVideo.media_id, 'second');
        ''')

    def test_old_load_completion_cannot_release_new_load_guard(self):
        run_case('''
            const firstLoad = deferred(), secondFetch = deferred();
            const originalLoad = player.engine.load.bind(player.engine);
            player.engine.load = async (...args) => { await originalLoad(...args); await firstLoad.promise; };
            const old = event({type:'set_video', video:selection('first'), time:180});
            await tick();
            const originalFetch = fetch;
            globalThis.fetch = async (...args) => { await secondFetch.promise; return originalFetch(...args); };
            const current = event({type:'set_video', video:selection('second'), time:240});
            await tick(); firstLoad.resolve(); await old; settle();
            assert.equal(syncState.isSyncing, true);
            assert.deepEqual(syncState.loadingState, {time:240, paused:true});
            secondFetch.resolve(); await current; player.engine.initialSeek(); settle();
            assert.equal(player.currentTime, 240);
            assert.equal(syncState.isSyncing, false);
        ''')

    def test_controls_received_during_load_apply_to_new_episode(self):
        run_case('''
            const pending = deferred();
            const originalFetch = fetch;
            globalThis.fetch = async (...args) => { await pending.promise; return originalFetch(...args); };
            const loading = event({type:'set_video', video:selection('episode'), time:180});
            await tick();
            await event({type:'play'});
            await event({type:'seek', time:210});
            settle();
            assert.equal(syncState.isSyncing, true);
            assert.equal(player.paused, true, 'previous media must not start');
            pending.resolve(); await loading; player.engine.initialSeek(); settle();
            assert.equal(player.currentTime, 210);
            assert.equal(player.paused, false);
        ''')

    def test_load_failure_releases_guard_without_losing_future_selection(self):
        run_case('''
            const originalFetch = fetch;
            globalThis.fetch = async () => { throw new Error('offline'); };
            await event({type:'set_video', video:selection('episode'), time:180}); settle();
            assert.equal(syncState.isSyncing, false);
            assert.equal(syncState.loadingState, null);
            globalThis.fetch = originalFetch;
            await event({type:'set_video', video:selection('episode'), time:180});
            player.engine.initialSeek(); settle();
            assert.equal(player.currentTime, 180);
        ''')

    def test_missing_resume_starts_at_zero(self):
        run_case('''
            await event({type:'set_video', video:selection('unwatched')});
            player.engine.initialSeek(); settle();
            assert.equal(player.currentTime, 0);
        ''')
