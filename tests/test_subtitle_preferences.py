"""Exercise browser-local subtitle choices against Shaka's asynchronous events."""
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
PRELUDE = r"""
import assert from 'node:assert/strict';
import { SubtitlePreferences } from './preferences.mjs';
class Engine extends EventTarget {
    constructor() { super(); this.audio = 'ja-JP'; this.text = []; this.configuration = {}; }
    configure(value) { Object.assign(this.configuration, value); }
    getVariantTracks() { return [{active: true, language: this.audio}]; }
    getTextTracks() { return this.text; }
    selectTextTrack(track) {
        for (const item of this.text) item.active = item === track;
        queueMicrotask(() => this.dispatchEvent(new Event('textchanged')));
    }
    async changeAudio(value) {
        this.audio = value;
        this.dispatchEvent(new Event('variantchanged'));
        await tick();
    }
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };
const storage = {
    data: new Map(), getItem(key) { return this.data.get(key) ?? null; },
    setItem(key, value) { this.data.set(key, value); },
};
const engine = new Engine();
const notices = [];
const preferences = new SubtitlePreferences(engine, storage, message => notices.push(message));
function context(episode, series='series:one', source='crunch') {
    return {source_id: source, media_id: episode, preference_scope: series, tracks: [
        {id: episode+':ja-pt', kind:'text', audio_language:'ja-JP', language:'pt-BR', selection_key:'pt-BR', representation_ids:[episode+':ja-pt:vtt']},
        {id: episode+':pt-pt', kind:'text', audio_language:'pt-BR', language:'pt-BR', selection_key:'pt-BR', representation_ids:[episode+':pt-pt:vtt']},
    ]};
}
async function load(value) {
    preferences.begin(value);
    engine.text = value.tracks.map((item, id) => ({id, active:false, language:item.language,
        originalTextId:item.representation_ids[0], forced:false, roles:['subtitle']}));
    await preferences.loaded();
}
async function choose(index) { engine.selectTextTrack(index === null ? null : engine.text[index]); await tick(); }
const active = () => engine.text.find(item => item.active)?.originalTextId ?? null;
"""


def run_case(body):
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        (folder / "preferences.mjs").write_text(
            (ROOT / "files/modules/subtitle-preferences.js").read_text(encoding="utf-8"), encoding="utf-8")
        (folder / "case.mjs").write_text(PRELUDE + textwrap.dedent(body), encoding="utf-8")
        result = subprocess.run([NODE, str(folder / "case.mjs")], capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise AssertionError(result.stderr)


@unittest.skipUnless(NODE, "Node unavailable")
class SubtitlePreferenceTests(unittest.TestCase):
    def test_manual_choice_is_remembered_separately_for_each_audio(self):
        run_case("""
            await load(context('episode:1'));
            assert.equal(active(), null);
            assert.equal(storage.data.size, 0, 'automatic Off must not overwrite preferences');
            await choose(1); // All origins are selectable, even with Japanese audio.
            await engine.changeAudio('pt-BR');
            assert.equal(active(), null);
            await choose(0);
            await engine.changeAudio('ja-JP');
            assert.equal(active(), 'episode:1:pt-pt:vtt');
            await engine.changeAudio('pt-BR');
            assert.equal(active(), 'episode:1:ja-pt:vtt');
        """)

    def test_next_episode_restores_semantic_choice_from_the_same_origin(self):
        run_case("""
            await load(context('episode:1'));
            await choose(1);
            await load(context('episode:2'));
            assert.equal(active(), 'episode:2:pt-pt:vtt');
            assert.equal(notices.length, 0);
            await load(context('episode:3', 'series:two'));
            assert.equal(active(), null, 'another series must not inherit the choice');
            await load(context('episode:3', 'series:one', 'another-source'));
            assert.equal(active(), null, 'another source must not inherit the choice');
        """)

    def test_missing_saved_track_stays_off_without_overwriting_choice(self):
        run_case("""
            await load(context('episode:1')); await choose(1);
            const next = context('episode:2'); next.tracks.pop();
            await load(next);
            assert.equal(active(), null);
            assert.equal(notices.length, 1);
            await load(context('episode:3'));
            assert.equal(active(), 'episode:3:pt-pt:vtt');
        """)

    def test_exact_episode_choice_cannot_silently_switch_to_another_track(self):
        run_case("""
            await load(context('episode:1')); await choose(0);
            const changed = context('episode:1');
            changed.tracks[0].id = 'replacement'; changed.tracks[0].representation_ids = ['replacement:vtt'];
            await load(changed);
            assert.equal(active(), null); assert.equal(notices.length, 1);
        """)

    def test_explicit_off_survives_next_episode_and_resolution_changes(self):
        run_case("""
            await load(context('episode:1')); await choose(0); await choose(null);
            await load(context('episode:2'));
            assert.equal(active(), null);
            assert.equal(engine.configuration.accessibility.handleForcedSubtitlesAutomatically, false);
            assert.deepEqual(engine.configuration.preferredText, []);
            const size = storage.data.size;
            engine.dispatchEvent(new Event('variantchanged')); await tick();
            assert.equal(active(), null); assert.equal(storage.data.size, size);
            assert.equal(notices.length, 0);
        """)

    def test_ambiguous_equivalent_tracks_stay_off(self):
        run_case("""
            await load(context('episode:1')); await choose(0);
            const next = context('episode:2');
            next.tracks.push({...next.tracks[0], id:'duplicate', representation_ids:['duplicate:vtt']});
            await load(next);
            assert.equal(active(), null); assert.equal(notices.length, 1);
        """)

    def test_storage_failure_does_not_interrupt_playback(self):
        run_case("""
            storage.getItem = () => { throw new Error('blocked'); };
            storage.setItem = () => { throw new Error('quota'); };
            await load(context('episode:1')); await choose(0);
            assert.equal(active(), 'episode:1:ja-pt:vtt');
        """)

    def test_audio_choice_is_restored_for_its_series(self):
        run_case("""
            await load(context('episode:1')); await engine.changeAudio('pt-BR');
            preferences.begin(context('episode:2'));
            assert.equal(engine.configuration.preferredAudio[0].language, 'pt-BR');
        """)

    def test_outdated_load_completion_does_not_enable_preference_recording(self):
        run_case("""
            const old = preferences.begin(context('episode:1'));
            preferences.begin(context('episode:2'));
            await preferences.loaded(old);
            assert.equal(preferences.loading, true);
            assert.equal(storage.data.size, 0);
        """)
