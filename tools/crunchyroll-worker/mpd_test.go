package main

import "testing"

func TestTimelineNumberAndTime(t *testing.T) {
	raw := []byte(`<MPD mediaPresentationDuration="PT6S"><Period><AdaptationSet contentType="video" mimeType="video/mp4"><SegmentTemplate timescale="1000" startNumber="7" initialization="i-$RepresentationID$.mp4" media="s-$Number%05d$-$Time$.m4s"><SegmentTimeline><S t="1000" d="2000" r="2"/></SegmentTimeline></SegmentTemplate><Representation id="v1" bandwidth="1" width="640" height="360" codecs="avc1"/></AdaptationSet></Period></MPD>`)
	p, _, err := parseMPD(raw, "https://cdn.example/a/manifest.mpd", "version", "ja-JP")
	if err != nil {
		t.Fatal(err)
	}
	r := p.Tracks[0].Representations[0]
	if len(r.Segments) != 3 {
		t.Fatalf("segments=%d", len(r.Segments))
	}
	if got := r.mediaURLs["t-1000"]; got != "https://cdn.example/a/s-00007-1000.m4s" {
		t.Fatal(got)
	}
}

func TestNegativeRepeatUsesDuration(t *testing.T) {
	tmpl := &xTemplate{Timescale: 1, Media: "$Time$"}
	tmpl.Timeline.S = []xS{{D: 2, R: -1}}
	_, _, segments := expand(tmpl, "v", "https://x/", 6)
	if len(segments) != 3 {
		t.Fatalf("segments=%d", len(segments))
	}
}

func TestParserInheritsSegmentTemplateFromPeriod(t *testing.T) {
	raw := []byte(`<MPD mediaPresentationDuration="PT4S"><Period><SegmentTemplate timescale="1" initialization="init.mp4" media="$Time$.m4s"><SegmentTimeline><S d="2" r="1"/></SegmentTimeline></SegmentTemplate><AdaptationSet contentType="video" mimeType="video/mp4"><Representation id="v" bandwidth="1" codecs="avc1"/></AdaptationSet></Period></MPD>`)
	p, _, err := parseMPD(raw, "https://cdn.example/manifest.mpd", "version", "")
	if err != nil {
		t.Fatal(err)
	}
	if len(p.Tracks) != 1 || len(p.Tracks[0].Representations[0].Segments) != 2 {
		t.Fatalf("tracks=%d segments=%d", len(p.Tracks), len(p.Tracks[0].Representations[0].Segments))
	}
}

func TestParserSelectsWidevinePSSHWhenPlayReadyIsAlsoPresent(t *testing.T) {
	raw := []byte(`<MPD mediaPresentationDuration="PT2S" xmlns:cenc="urn:mpeg:cenc:2013"><Period><AdaptationSet contentType="video" mimeType="video/mp4"><ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"><cenc:pssh>d2lkZXZpbmU=</cenc:pssh></ContentProtection><ContentProtection schemeIdUri="urn:uuid:9a04f079-9840-4286-ab92-e65be0885f95"><cenc:pssh>cGxheXJlYWR5</cenc:pssh></ContentProtection><SegmentTemplate timescale="1" initialization="init.mp4" media="$Time$.m4s"><SegmentTimeline><S d="2"/></SegmentTimeline></SegmentTemplate><Representation id="v" bandwidth="1" codecs="avc1"/></AdaptationSet></Period></MPD>`)
	_, pssh, err := parseMPD(raw, "https://example.test/manifest.mpd", "version", "")
	if err != nil {
		t.Fatal(err)
	}
	if pssh != "d2lkZXZpbmU=" {
		t.Fatalf("selected wrong DRM PSSH: %s", pssh)
	}
}

func TestRequestedLanguagesAreOrderedAndDeduplicated(t *testing.T) {
	got := requestedLanguages([]string{"pt-BR", "ja-JP", "pt-BR", "*"})
	if len(got) != 2 || got[0] != "pt-BR" || got[1] != "ja-JP" {
		t.Fatalf("languages=%v", got)
	}
}

func TestRequestedLanguagesUsesOnlyConfiguredValues(t *testing.T) {
	got := requestedLanguages([]string{"pt-BR", "pt-BR", "en-US"})
	if len(got) != 2 || got[0] != "pt-BR" || got[1] != "en-US" {
		t.Fatalf("languages=%v", got)
	}
}

func TestSubtitleTrackIsExposedAsWebVTTResource(t *testing.T) {
	tr := subtitleTrack("episode", "pt-BR", "Português", "https://example.test/subtitle.ass")
	if tr.Kind != "text" || tr.Language != "pt-BR" || len(tr.Representations) != 1 {
		t.Fatalf("track=%+v", tr)
	}
	rep := tr.Representations[0]
	if rep.MimeType != "text/vtt" || rep.Initialization != "subtitle" || rep.initURL == "" {
		t.Fatalf("representation=%+v", rep)
	}
}

func TestASSSubtitleIsConvertedToWebVTT(t *testing.T) {
	raw := []byte("[Events]\nDialogue: 0,0:00:01.20,0:00:03.45,Default,,0,0,0,,{\\i1}Olá\\Nlinha 2")
	got := string(subtitleToVTT(raw))
	if got != "WEBVTT\n\n00:00:01.200 --> 00:00:03.450\nOlá\nlinha 2\n" {
		t.Fatalf("unexpected VTT: %q", got)
	}
}

func TestPlaybackIDUsesTheVersionMatchingRequestedAudio(t *testing.T) {
	stream := playbackResponse{Versions: []playbackVersion{{GUID: "japanese-guid", AudioLocale: "ja-JP"}, {GUID: "portuguese-guid", AudioLocale: "pt-BR"}}}
	if got := playbackIDForLanguage("episode-guid", "pt-BR", stream); got != "portuguese-guid" {
		t.Fatalf("playback id=%q", got)
	}
}
