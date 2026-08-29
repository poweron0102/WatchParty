package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type worker struct {
	mu         sync.Mutex
	output     sync.Mutex
	api        *apiClient
	opts       options
	active     map[string]*mediaState
	writer     *json.Encoder
	lastDemand time.Time
	stop       chan struct{}
	stopOnce   sync.Once
}

func newWorker(out io.Writer) *worker {
	return &worker{active: map[string]*mediaState{}, writer: json.NewEncoder(out), lastDemand: time.Now(), stop: make(chan struct{})}
}
func (w *worker) emit(e event) { w.output.Lock(); defer w.output.Unlock(); _ = w.writer.Encode(e) }
func (w *worker) fail(c command, code string, err error) {
	fmt.Fprintf(os.Stderr, "[cr-worker] command=%s media=%s code=%s error=%s\n", c.Command, c.MediaKey, code, sanitize(err))
	e := response(c, "failed")
	e.Code = code
	e.Message = sanitize(err)
	w.emit(e)
}
func sanitize(err error) string {
	if err == nil {
		return "unknown failure"
	}
	s := err.Error()
	if len(s) > 240 {
		s = s[:240]
	}
	return s
}

func (w *worker) handle(c command) {
	if c.Version != protocolVersion {
		w.fail(c, "unsupported_version", errors.New("unsupported protocol version"))
		return
	}
	w.emit(response(c, "started"))
	switch c.Command {
	case "activate":
		w.api = newAPI(c.ETPRT)
		w.opts = c.Options
		if w.opts.WorkerIdleSeconds <= 0 {
			w.opts.WorkerIdleSeconds = 120
		}
		e := response(c, "completed")
		w.emit(e)
	case "inspect_version":
		stage := func(name string) { e := response(c, "stage"); e.Stage = name; w.emit(e) }
		p, err := w.inspect(c.MediaKey, stage)
		if err != nil {
			w.fail(c, "inspect_failed", err)
			return
		}
		e := response(c, "completed")
		e.Presentation = &p
		w.emit(e)
	case "materialize":
		stage := func(name string) { e := response(c, "stage"); e.Stage = name; w.emit(e) }
		path, ctype, digest, err := w.materialize(c.MediaKey, c.Demand, stage)
		if err != nil {
			w.fail(c, "materialize_failed", err)
			return
		}
		e := response(c, "asset")
		e.Path = path
		e.ContentType = ctype
		e.SHA256 = digest
		w.emit(e)
	case "cancel_queued":
		w.emit(response(c, "completed"))
	case "release":
		w.release(c.MediaKey)
		w.emit(response(c, "released"))
	case "shutdown":
		w.release("")
		w.emit(response(c, "completed"))
		w.stopOnce.Do(func() { close(w.stop) })
	default:
		w.fail(c, "unknown_command", errors.New("unknown command"))
	}
}

func (w *worker) inspect(mediaKey string, stage func(string)) (presentation, error) {
	w.mu.Lock()
	if state := w.active[mediaKey]; state != nil {
		p := state.present
		w.mu.Unlock()
		return publicPresentation(p), nil
	}
	w.mu.Unlock()
	if w.api == nil {
		return presentation{}, errors.New("worker is not activated")
	}
	stage("open_playback")
	var p presentation
	versions := map[string]*versionState{}
	seenAudio := map[string]bool{}
	seenSubtitle := map[string]bool{}
	discovery, err := w.api.openPlayback(mediaKey, "")
	if err != nil {
		return presentation{}, err
	}
	w.api.release(mediaKey, discovery.Token)
	// Only query languages explicitly configured by the server. Automatically
	// expanding the list from discovery can open several extra playback
	// sessions and trigger Crunchyroll's rate limiting (HTTP 420).
	languages := requestedLanguages(w.opts.AudioLanguages)
	if len(languages) == 0 {
		languages = []string{""}
	}
	for index, requested := range languages {
		playbackID := playbackIDForLanguage(mediaKey, requested, discovery)
		queryLanguage := ""
		if playbackID == mediaKey {
			queryLanguage = requested
		}
		stream, err := w.api.openPlayback(playbackID, queryLanguage)
		if err != nil {
			if index == 0 {
				return presentation{}, err
			}
			continue
		}
		stage("download_manifest")
		raw, _, err := w.api.request("GET", stream.URL, nil, map[string]string{
			"Origin": "https://static.crunchyroll.com", "Referer": "https://static.crunchyroll.com/",
		})
		if err != nil {
		}
		if err != nil {
			w.api.release(mediaKey, stream.Token)
			if index == 0 {
				return presentation{}, err
			}
			continue
		}
		language := stream.AudioLocale
		if language == "" {
			language = requested
		}
		versionID := fmt.Sprintf("%s@%s", playbackID, language)
		parsed, pssh, err := parseMPD(raw, stream.URL, versionID, language)
		if err != nil {
			w.api.release(mediaKey, stream.Token)
			if index == 0 {
				return presentation{}, err
			}
			continue
		}
		if err := w.expandSegmentBases(&parsed); err != nil {
			w.api.release(mediaKey, stream.Token)
			if index == 0 {
				return presentation{}, err
			}
			continue
		}
		keepSession := false
		for _, tr := range parsed.Tracks {
			if tr.Kind == "video" && index > 0 {
				continue
			}
			if tr.Kind == "audio" {
				key := strings.ToLower(tr.Language)
				if seenAudio[key] {
					continue
				}
				seenAudio[key] = true
			}
			p.Tracks = append(p.Tracks, tr)
			keepSession = true
		}
		for key, subtitle := range stream.Subtitles {
			locale := subtitle.Locale
			if locale == "" {
				locale = subtitle.Language
			}
			if locale == "" {
				locale = key
			}
			if seenSubtitle[strings.ToLower(locale)] || subtitle.URL == "" {
				continue
			}
			seenSubtitle[strings.ToLower(locale)] = true
			p.Tracks = append(p.Tracks, subtitleTrack(mediaKey, locale, subtitle.Language, subtitle.URL))
		}
		if keepSession {
			versions[versionID] = &versionState{contentID: playbackID, language: language, stream: stream, pssh: pssh}
		} else {
			w.api.release(playbackID, stream.Token)
		}
		if p.Duration == 0 {
			p.Duration = parsed.Duration
		}
		p.RevisionSeed += parsed.RevisionSeed
	}
	if len(p.Tracks) == 0 {
		return presentation{}, errors.New("no playable tracks were discovered")
	}
	p.Title = mediaKey
	chooseCanonical(&p, w.opts.VideoQuality)
	state := &mediaState{mediaKey: mediaKey, present: p, versions: versions}
	w.mu.Lock()
	w.active[mediaKey] = state
	w.lastDemand = time.Now()
	w.mu.Unlock()
	return publicPresentation(p), nil
}

func (w *worker) expandSegmentBases(p *presentation) error {
	for ti := range p.Tracks {
		for ri := range p.Tracks[ti].Representations {
			r := &p.Tracks[ti].Representations[ri]
			if r.initRange == "" || len(r.Segments) != 0 {
				continue
			}
			start, end, err := parseByteRange(r.initRange)
			if err != nil {
				return err
			}
			_ = start
			_ = end
			// SegmentBase metadata is carried in the representation URL/range fields by parseMPD.
			indexRange := r.mediaRanges["__index__"]
			if indexRange == "" {
				return fmt.Errorf("segment base has no index range")
			}
			is, ie, err := parseByteRange(indexRange)
			if err != nil {
				return err
			}
			data, err := w.requestRange(r.initURL, indexRange)
			if err != nil {
				return err
			}
			segments, ranges, err := parseSIDX(data, is, ie)
			if err != nil {
				return err
			}
			delete(r.mediaRanges, "__index__")
			r.Segments, r.mediaRanges = segments, ranges
			for _, segment := range segments {
				r.mediaURLs[segment.Identity] = r.initURL
			}
		}
	}
	return nil
}

func publicPresentation(p presentation) presentation {
	copyP := p
	copyP.Tracks = append([]track(nil), p.Tracks...)
	for i := range copyP.Tracks {
		copyP.Tracks[i].Representations = append([]representation(nil), p.Tracks[i].Representations...)
		for j := range copyP.Tracks[i].Representations {
			copyP.Tracks[i].Representations[j].initURL = ""
			copyP.Tracks[i].Representations[j].mediaURLs = nil
			copyP.Tracks[i].Representations[j].versionID = ""
		}
	}
	return copyP
}
func chooseCanonical(p *presentation, quality string) {
	limit := 0
	fmt.Sscanf(strings.TrimSuffix(quality, "p"), "%d", &limit)
	bestHeight, bestID := -1, ""
	for _, t := range p.Tracks {
		if t.Kind != "video" {
			continue
		}
		for _, r := range t.Representations {
			height := 0
			if r.Height != nil {
				height = *r.Height
			}
			if height <= limit && height > bestHeight {
				bestHeight = height
				bestID = r.ID
			}
		}
	}
	p.CanonicalVideoRepresentation = bestID
}

func (w *worker) materialize(mediaKey string, d demand, stage func(string)) (string, string, string, error) {
	stage("inspect")
	_, err := w.inspect(mediaKey, stage)
	if err != nil {
		return "", "", "", err
	}
	w.mu.Lock()
	state := w.active[mediaKey]
	w.lastDemand = time.Now()
	var found *representation
	for ti := range state.present.Tracks {
		for ri := range state.present.Tracks[ti].Representations {
			r := &state.present.Tracks[ti].Representations[ri]
			if state.present.Tracks[ti].ID == d.TrackID && r.ID == d.RepresentationID {
				found = r
			}
		}
	}
	w.mu.Unlock()
	if found == nil {
		return "", "", "", errors.New("unknown representation")
	}
	if strings.HasPrefix(d.TrackID, "subtitle:") {
		stage("download_subtitle")
		raw, _, downloadErr := w.api.request("GET", found.initURL, nil, map[string]string{"Origin": "https://static.crunchyroll.com", "Referer": "https://static.crunchyroll.com/"})
		if downloadErr != nil {
			return "", "", "", downloadErr
		}
		clearSubtitle := subtitleToVTT(raw)
		stage("publish")
		return w.publish(clearSubtitle, "text/vtt", "subtitle")
	}
	version := state.versions[found.versionID]
	if version == nil {
		return "", "", "", errors.New("playback version is unavailable")
	}
	version.licenseMu.Lock()
	if version.keys == nil {
		stage("acquire_license")
		version.keys, err = acquireLicense(w.api, w.opts, version.contentID, version.stream.Token, version.pssh)
	}
	version.licenseMu.Unlock()
	if err != nil {
		return "", "", "", err
	}
	init, err := w.initialization(found, version, stage)
	if err != nil {
		return "", "", "", err
	}
	var clear []byte
	if d.SegmentIdentity == "init" {
		stage("download_bootstrap_media")
		first, firstRange, ok := firstMedia(found)
		if !ok {
			return "", "", "", errors.New("representation has no media segments")
		}
		media, e := w.requestRange(first, firstRange)
		if e != nil {
			return "", "", "", e
		}
		stage("decrypt")
		clear, _, e = decryptFragment(init, media, version.keys)
		if e != nil {
			return "", "", "", decryptError(found, d, init, media, e)
		}
	} else {
		stage("download_media")
		target := found.mediaURLs[d.SegmentIdentity]
		if target == "" {
			return "", "", "", errors.New("unknown segment")
		}
		media, e := w.requestRange(target, found.mediaRanges[d.SegmentIdentity])
		if e != nil {
			return "", "", "", e
		}
		stage("decrypt")
		_, clear, e = decryptFragment(init, media, version.keys)
		if e != nil {
			return "", "", "", decryptError(found, d, init, media, e)
		}
	}
	stage("publish")
	return w.publish(clear, found.MimeType, "segment")
}

func (w *worker) initialization(found *representation, version *versionState, stage func(string)) ([]byte, error) {
	version.initMu.Lock()
	defer version.initMu.Unlock()
	if init := version.inits[found.ID]; init != nil {
		stage("reuse_init")
		return init, nil
	}
	stage("download_init")
	init, err := w.requestRange(found.initURL, found.initRange)
	if err != nil {
		return nil, err
	}
	if version.inits == nil {
		version.inits = map[string][]byte{}
	}
	version.inits[found.ID] = init
	return init, nil
}

func firstMedia(found *representation) (string, string, bool) {
	for _, segment := range found.Segments {
		if target := found.mediaURLs[segment.Identity]; target != "" {
			return target, found.mediaRanges[segment.Identity], true
		}
	}
	return "", "", false
}

func decryptError(found *representation, d demand, init, media []byte, err error) error {
	return fmt.Errorf("decrypt failed track=%s representation=%s segment=%s init_bytes=%d media_bytes=%d media_range=%s: %w",
		d.TrackID, found.ID, d.SegmentIdentity, len(init), len(media), found.mediaRanges[d.SegmentIdentity], err)
}

func (w *worker) requestRange(target, value string) ([]byte, error) {
	headers := map[string]string{"Origin": "https://static.crunchyroll.com", "Referer": "https://static.crunchyroll.com/"}
	if value == "" {
		data, _, err := w.api.request("GET", target, nil, headers)
		return data, err
	}
	start, end, err := parseByteRange(value)
	if err != nil {
		return nil, err
	}
	expected := end - start + 1
	headers["Range"] = "bytes=" + value
	const attempts = 3
	var lastErr error
	for attempt := 0; attempt < attempts; attempt++ {
		data, responseHeaders, requestErr := w.api.request("GET", target, nil, headers)
		if requestErr == nil {
			if validationErr := validateRangeResponse(value, expected, data, responseHeaders); validationErr == nil {
				return data, nil
			} else {
				lastErr = validationErr
			}
		} else {
			lastErr = requestErr
		}
		if attempt+1 < attempts {
			time.Sleep(time.Duration(attempt+1) * 250 * time.Millisecond)
		}
	}
	return nil, fmt.Errorf("byte range %s failed after %d attempts: %w", value, attempts, lastErr)
}

func validateRangeResponse(value string, expected int64, data []byte, headers http.Header) error {
	contentRange := strings.TrimSpace(headers.Get("Content-Range"))
	if contentRange == "" {
		return fmt.Errorf("CDN ignored byte range %s (missing Content-Range)", value)
	}
	parts := strings.SplitN(contentRange, "/", 2)
	if len(parts) != 2 {
		return fmt.Errorf("invalid Content-Range %q for byte range %s", contentRange, value)
	}
	rangeParts := strings.Fields(parts[0])
	if len(rangeParts) != 2 || strings.ToLower(rangeParts[0]) != "bytes" {
		return fmt.Errorf("invalid Content-Range %q for byte range %s", contentRange, value)
	}
	start, end, err := parseByteRange(rangeParts[1])
	if err != nil {
		return fmt.Errorf("invalid Content-Range %q for byte range %s", contentRange, value)
	}
	requestedStart, requestedEnd, err := parseByteRange(value)
	if err != nil {
		return err
	}
	if start != requestedStart || end != requestedEnd {
		return fmt.Errorf("CDN returned Content-Range %q, expected bytes %d-%d", contentRange, requestedStart, requestedEnd)
	}
	if int64(len(data)) != expected {
		return fmt.Errorf("byte range %s returned %d bytes, expected %d", value, len(data), expected)
	}
	return nil
}

func (w *worker) publish(clear []byte, contentType, prefix string) (string, string, string, error) {
	digestBytes := sha256.Sum256(clear)
	digest := hex.EncodeToString(digestBytes[:])
	dir := filepath.Join(w.opts.CachePath, ".crunchyroll", "incoming")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", "", "", err
	}
	name := digest + ".mp4"
	path := filepath.Join(dir, name)
	tmp, err := os.CreateTemp(dir, prefix+"-*.tmp")
	if err != nil {
		return "", "", "", err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if _, err = tmp.Write(clear); err == nil {
		err = tmp.Sync()
	}
	closeErr := tmp.Close()
	if err == nil {
		err = closeErr
	}
	if err == nil {
		err = os.Rename(tmpName, path)
	}
	if err != nil && !os.IsExist(err) {
		return "", "", "", err
	}
	return path, contentType, digest, nil
}
func (w *worker) release(mediaKey string) {
	w.mu.Lock()
	states := []*mediaState{}
	if mediaKey == "" {
		for _, s := range w.active {
			states = append(states, s)
		}
		w.active = map[string]*mediaState{}
	} else if s := w.active[mediaKey]; s != nil {
		states = append(states, s)
		delete(w.active, mediaKey)
	}
	w.mu.Unlock()
	for _, s := range states {
		for _, v := range s.versions {
			w.api.release(v.contentID, v.stream.Token)
		}
	}
}
func (w *worker) idle() {
	for {
		time.Sleep(time.Second)
		w.mu.Lock()
		idle := w.api != nil && time.Since(w.lastDemand) > time.Duration(w.opts.WorkerIdleSeconds)*time.Second
		w.mu.Unlock()
		if idle {
			w.release("")
			w.stopOnce.Do(func() { close(w.stop) })
			return
		}
	}
}

var _ = json.Valid
