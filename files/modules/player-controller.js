export class PlayerController {
    constructor(video) {
        this.media = video;
        video.controls = false;
        video.removeAttribute('controls');
        shaka.polyfill.installAll();
        this.engine = new shaka.Player();
        this.ready = this.engine.attach(video);
        this.engine.addEventListener('error', event => {
            console.error('Shaka Player error:', event.detail);
            this.media.dispatchEvent(new CustomEvent('shaka-error', { detail: event.detail }));
        });
        const savedAudio = localStorage.getItem('watchparty.audioLanguage');
        const savedText = localStorage.getItem('watchparty.textLanguage');
        this.engine.configure({ preferredAudioLanguage: savedAudio || '', preferredTextLanguage: savedText || '' });
        this.engine.addEventListener('variantchanged', () => {
            const active = this.engine.getVariantTracks().find(track => track.active);
            if (active?.language) localStorage.setItem('watchparty.audioLanguage', active.language);
        });
        this.engine.addEventListener('textchanged', () => {
            const active = this.engine.getTextTracks().find(track => track.active);
            localStorage.setItem('watchparty.textLanguage', active?.language || 'off');
        });
        this.overlay = new shaka.ui.Overlay(this.engine, video.parentElement, video);
        this.overlay.configure({ overflowMenuButtons: ['quality', 'language', 'captions', 'playback_rate', 'picture_in_picture'] });
        this.engine.configure({ streaming: {
            bufferingGoal: 30, rebufferingGoal: 2,
            retryParameters: { maxAttempts: 4, baseDelay: 1000, backoffFactor: 2, timeout: 45000, stallTimeout: 0 },
        }, abr: { enabled: true } });
    }
    async load(url) {
        this.media.srcObject = null; await this.ready;
        const savedText = localStorage.getItem('watchparty.textLanguage');
        this.engine.configure({ preferredTextLanguage: savedText === 'off' ? '' : (savedText || '') });
        await this.engine.load(url);
        if (savedText === 'off') this.engine.setTextTrackVisibility(false);
    }
    async unload() { await this.ready; await this.engine.unload(); this.media.removeAttribute('src'); }
    get currentTime() { return this.media.currentTime; }
    set currentTime(value) { this.media.currentTime = value; }
    get paused() { return this.media.paused; }
    get muted() { return this.media.muted; }
    set muted(value) { this.media.muted = value; }
    get playbackRate() { return this.media.playbackRate; }
    set playbackRate(value) { this.media.playbackRate = value; }
    play() { return this.media.play(); }
    pause() { return this.media.pause(); }
    on(name, callback) { this.media.addEventListener(name, callback); }
    set source(value) { const url = value?.sources?.[0]?.src; if (url) this.load(url); else this.unload(); }
}
