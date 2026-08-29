package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestCookieValueAcceptsRawAndCopiedCookie(t *testing.T) {
	if got := cookieValue("raw-value"); got != "raw-value" {
		t.Fatal(got)
	}
	if got := cookieValue("other=x; etp_rt=secret-value; Path=/"); got != "secret-value" {
		t.Fatal(got)
	}
}

func TestRequestRangeRetriesTruncatedResponse(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Range"); got != "bytes=0-9" {
			t.Errorf("Range = %q", got)
		}
		if requests.Add(1) == 1 {
			w.Header().Set("Content-Range", "bytes 0-9/10")
			w.Header().Set("Content-Length", "10")
			w.WriteHeader(http.StatusPartialContent)
			_, _ = w.Write([]byte("123"))
			return
		}
		w.Header().Set("Content-Range", "bytes 0-9/10")
		w.WriteHeader(http.StatusPartialContent)
		_, _ = w.Write([]byte("1234567890"))
	}))
	defer server.Close()

	api := &apiClient{token: "token", expires: time.Now().Add(time.Hour), client: server.Client()}
	w := &worker{api: api}
	data, err := w.requestRange(server.URL, "0-9")
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "1234567890" {
		t.Fatalf("data = %q", data)
	}
	if got := requests.Load(); got != 2 {
		t.Fatalf("requests = %d, want 2", got)
	}
}

func TestRequestRangeRejectsMismatchedContentRange(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Range", "bytes 1-10/20")
		w.WriteHeader(http.StatusPartialContent)
		_, _ = fmt.Fprint(w, "1234567890")
	}))
	defer server.Close()

	api := &apiClient{token: "token", expires: time.Now().Add(time.Hour), client: server.Client()}
	w := &worker{api: api}
	_, err := w.requestRange(server.URL, "0-9")
	if err == nil {
		t.Fatal("expected Content-Range validation error")
	}
}
