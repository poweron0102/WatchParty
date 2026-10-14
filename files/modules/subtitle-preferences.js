const locale = value => String(value || 'und').toLowerCase();

// Browser-local choices. Episode IDs restore exact tracks; series choices use
// semantic keys because Crunchyroll version IDs change between episodes.
export class SubtitlePreferences {
    constructor(engine, storage, notify = () => {}) {
        this.engine = engine;
        this.storage = storage;
        this.notify = notify;
        this.context = null;
        this.loading = true;
        this.restoring = 0;
        this.audio = null;
        this.generation = 0;
        engine.addEventListener('textchanged', () => this.remember());
        engine.addEventListener('variantchanged', () => this.audioChanged());
    }

    read(key) {
        try { return JSON.parse(this.storage.getItem(key)); } catch { return null; }
    }

    write(key, value) {
        try { this.storage.setItem(key, JSON.stringify(value)); } catch { /* Playback works without storage. */ }
    }

    key(kind, audio = this.audio) {
        const { source_id, media_id, preference_scope } = this.context;
        return 'watchparty.subtitles.v2.' + JSON.stringify([
            kind, source_id, ['series', 'audio'].includes(kind) ? (preference_scope || media_id) : media_id, audio,
        ]);
    }

    audioLanguage() {
        return locale(this.engine.getVariantTracks().find(track => track.active)?.language);
    }

    metadata(track) {
        return this.context?.tracks?.find(item => item.kind === 'text' &&
            (item.id === track.originalTextId || item.representation_ids?.includes(track.originalTextId)));
    }

    begin(context) {
        this.generation++;
        this.context = context;
        this.loading = true;
        this.audio = null;
        const savedAudio = this.read(this.key('audio', null));
        if (savedAudio?.language) this.engine.configure({ preferredAudio: [{ language: savedAudio.language }] });
        this.engine.configure({ preferredText: [], accessibility: { handleForcedSubtitlesAutomatically: false } });
        return this.generation;
    }

    async loaded(generation = this.generation) {
        if (generation !== this.generation || !this.context) return;
        this.audio = this.audioLanguage();
        await this.restore();
        if (generation === this.generation) this.loading = false;
    }

    unload() {
        this.generation++;
        this.loading = true;
        this.context = null;
        this.audio = null;
    }

    async audioChanged() {
        if (this.loading || !this.context) return;
        const audio = this.audioLanguage();
        if (audio === this.audio) return; // Resolution changes must not change subtitles.
        this.audio = audio;
        const track = this.engine.getVariantTracks().find(item => item.active);
        this.write(this.key('audio', null), { language: track?.language || audio });
        await this.restore();
    }

    remember() {
        if (this.loading || this.restoring || !this.context || !this.audio) return;
        // An audio change may dispatch text events before variantchanged.
        if (this.audioLanguage() !== this.audio) return;
        const track = this.engine.getTextTracks().find(item => item.active);
        const metadata = track && this.metadata(track);
        if (track && !metadata) return;
        const choice = track ? {
            id: metadata.id, language: locale(track.language),
            audio_language: locale(metadata.audio_language), selection_key: metadata.selection_key,
            label: metadata.label, forced: !!track.forced, roles: [...(track.roles || [])].sort(),
        } : { off: true };
        this.write(this.key('episode'), choice);
        // Uploaded subtitles without a semantic key belong to this episode only.
        if (!track || metadata.selection_key) this.write(this.key('series'), choice);
    }

    async restore() {
        const generation = this.generation;
        const exact = this.read(this.key('episode'));
        const choice = exact || this.read(this.key('series'));
        let selected = null;
        if (choice && !choice.off) {
            const matches = this.engine.getTextTracks().filter(track => {
                const metadata = this.metadata(track);
                if (!metadata) return false;
                if (exact) return metadata.id === choice.id;
                return locale(track.language) === choice.language &&
                    locale(metadata.audio_language) === choice.audio_language &&
                    metadata.selection_key === choice.selection_key && !!track.forced === choice.forced &&
                    JSON.stringify([...(track.roles || [])].sort()) === JSON.stringify(choice.roles);
            });
            if (matches.length === 1) selected = matches[0];
            else this.notify('Sua legenda anterior não está disponível para este áudio. Escolha uma legenda no menu.');
        }
        this.restoring++;
        try {
            this.engine.configure({ preferredText: [] });
            this.engine.selectTextTrack(selected);
            // Shaka dispatches selection events asynchronously, including Off.
            await Promise.resolve();
        } finally {
            this.restoring--;
        }
        return generation === this.generation;
    }
}
