package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func mockResponse(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}
}

func TestInspectFailureReleasesTokenUsingVersionID(t *testing.T) {
	for _, failure := range []string{"manifest_http", "manifest_parse", "segment_index"} {
		t.Run(failure, func(t *testing.T) {
			var releases []string
			api, _ := virtualAPI(&http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
				switch {
				case r.Method == "DELETE":
					releases = append(releases, r.URL.Path)
					return mockResponse(204, ""), nil
				case strings.Contains(r.URL.Path, "/original/"):
					return mockResponse(200, `{"token":"discovery","versions":[{"guid":"pt-version","audio_locale":"pt-BR"}]}`), nil
				case strings.Contains(r.URL.Path, "/pt-version/"):
					return mockResponse(200, `{"token":"pt-token","audio_locale":"pt-BR","url":"https://cdn.example/manifest"}`), nil
				default:
					if failure == "manifest_http" {
						return mockResponse(404, ""), nil
					}
					if failure == "manifest_parse" {
						return mockResponse(200, "invalid MPD"), nil
					}
					return mockResponse(200, `<MPD><Period><AdaptationSet contentType="audio" mimeType="audio/mp4"><Representation id="a" bandwidth="1" codecs="mp4a"><SegmentBase indexRange="broken"><Initialization range="0-9"/></SegmentBase></Representation></AdaptationSet></Period></MPD>`), nil
				}
			})})
			w := newWorker(io.Discard)
			w.api, w.opts = api, options{AudioLanguages: []string{"pt-BR"}}
			if _, err := w.inspect("original", func(string) {}); err == nil {
				t.Fatal("inspection should fail")
			}
			if len(releases) != 2 || releases[0] != "/playback/v1/token/original/discovery" || releases[1] != "/playback/v1/token/pt-version/pt-token" {
				t.Fatalf("wrong release IDs: %v", releases)
			}
			if len(w.active) != 0 {
				t.Fatal("failed presentation was published")
			}
		})
	}
}

func TestInspectionWithoutPlayableTracksReleasesOpenedSession(t *testing.T) {
	var releases int
	api, _ := virtualAPI(&http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == "DELETE" {
			releases++
			return mockResponse(204, ""), nil
		}
		if strings.Contains(r.URL.Path, "/playback/v3/") {
			return mockResponse(200, `{"token":"session","url":"https://cdn.example/manifest"}`), nil
		}
		return mockResponse(200, `<MPD><Period/></MPD>`), nil
	})})
	w := newWorker(io.Discard)
	w.api = api
	if _, err := w.inspect("original", func(string) {}); err == nil {
		t.Fatal("inspection should fail")
	}
	if releases != 2 || len(w.active) != 0 {
		t.Fatalf("releases=%d active=%d", releases, len(w.active))
	}
}

func TestFailureEventContainsSafeStructuredMetadata(t *testing.T) {
	var output bytes.Buffer
	w := newWorker(&output)
	w.fail(command{Version: 1, RequestID: "request", MediaKey: "media", Demand: demand{SegmentIdentity: "sidx-16"}}, "materialize_failed",
		fmt.Errorf("wrapped: %w", &upstreamError{Status: 420, Operation: "segment", Attempt: 5, RetryAfter: 1500 * time.Millisecond, Reason: "HTTP request failed"}), "download_media")
	var e event
	if err := json.Unmarshal(output.Bytes(), &e); err != nil {
		t.Fatal(err)
	}
	if e.Version != 1 || e.Status != 420 || e.Operation != "segment" || e.Attempt != 5 || e.RetryAfter != 2 || e.Stage != "download_media" {
		t.Fatalf("event=%+v", e)
	}
	w.opts.PrivateKeyPath = "private-secret.pem"
	w.api = &apiClient{cookie: "cookie-secret", token: "token-secret"}
	message := w.safeError(errors.New("private-secret.pem cookie-secret token-secret https://cdn.example/?token=url-secret"))
	for _, secret := range []string{"private-secret.pem", "cookie-secret", "token-secret", "url-secret"} {
		if strings.Contains(message, secret) {
			t.Fatalf("secret leaked: %q", message)
		}
	}
}

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
