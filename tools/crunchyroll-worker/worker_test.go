package main

import (
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestFirstMediaUsesFirstSegmentRange(t *testing.T) {
	r := &representation{
		Segments:    []segment{{Identity: "sidx-0"}},
		mediaURLs:   map[string]string{"sidx-0": "https://cdn.example/media.mp4"},
		mediaRanges: map[string]string{"sidx-0": "100-199"},
	}

	target, byteRange, ok := firstMedia(r)
	if !ok || target != "https://cdn.example/media.mp4" || byteRange != "100-199" {
		t.Fatalf("first media = (%q, %q, %t)", target, byteRange, ok)
	}
}

func TestInitializationIsReusedWithinPlaybackVersion(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		w.Header().Set("Content-Range", "bytes 0-3/4")
		w.WriteHeader(http.StatusPartialContent)
		_, _ = w.Write([]byte("init"))
	}))
	defer server.Close()

	api := &apiClient{token: "token", expires: time.Now().Add(time.Hour), client: server.Client()}
	w := &worker{api: api}
	found := &representation{ID: "video:v1", initURL: server.URL, initRange: "0-3"}
	version := &versionState{}
	stage := func(string) {}

	first, err := w.initialization(found, version, stage)
	if err != nil {
		t.Fatal(err)
	}
	second, err := w.initialization(found, version, stage)
	if err != nil {
		t.Fatal(err)
	}
	if string(first) != "init" || string(second) != "init" || requests.Load() != 1 {
		t.Fatalf("first=%q second=%q requests=%d", first, second, requests.Load())
	}
}
