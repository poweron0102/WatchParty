export class PlayerController {
    constructor(video) {
        this.media = video;
        shaka.polyfill.installAll();
        this.engine = new shaka.Player();
        this.engine.attach(video);
        this.overlay = new shaka.ui.Overlay(this.engine, video.parentElement, video);
        this.overlay.configure({ overflowMenuButtons: ['quality', 'language', 'captions', 'playback_rate', 'picture_in_picture'] });
        this.engine.configure({ streaming: { bufferingGoal: 30, rebufferingGoal: 2 }, abr: { enabled: true } });
    }
    async load(url) { this.media.srcObject = null; await this.engine.load(url); }
    async unload() { await this.engine.unload(); this.media.removeAttribute('src'); }
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
