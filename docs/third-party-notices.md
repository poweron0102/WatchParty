# Third-party notices

## Shaka Player 5.2.0

The locally hosted browser player in `files/vendor/shaka` is Shaka Player 5.2.0.
Its Apache-2.0 license is preserved in that directory.

## crunchyroll-downloader reference

The worker protocol and separation of catalog, playback sessions, MPD inspection and DRM were
designed with reference to the MIT-licensed `crunchyroll-downloader` repository named in the
implementation plan. No source file from that repository is copied into this project in the
current implementation. Any future Go worker code derived from it must retain its MIT license
and attribution.
