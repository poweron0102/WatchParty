package main

import (
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func virtualAPI(client *http.Client) (*apiClient, *[]time.Duration) {
	now := time.Now()
	waits := []time.Duration{}
	return &apiClient{token: "token", expires: now.Add(time.Hour), client: client,
		clock:   func() time.Time { return now },
		sleeper: func(delay time.Duration) { waits = append(waits, delay); now = now.Add(delay) },
	}, &waits
}

func TestRangeRateLimitHasOneHTTPBudget(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		w.WriteHeader(420)
	}))
	defer server.Close()
	api, waits := virtualAPI(server.Client())
	w := &worker{api: api}
	_, err := w.requestRange(server.URL+"/media?token=secret", "0-9")
	var upstream *upstreamError
	if !errors.As(err, &upstream) || upstream.Status != 420 || upstream.Attempt != 5 || upstream.Operation != "segment" {
		t.Fatalf("unexpected error: %v", err)
	}
	if requests.Load() != 5 {
		t.Fatalf("requests=%d, want 5 (not 15)", requests.Load())
	}
	if fmt.Sprint(*waits) != "[1s 2s 4s 8s]" {
		t.Fatalf("waits=%v", *waits)
	}
	if upstream.RetryAfter != 16*time.Second {
		t.Fatalf("retry=%v", upstream.RetryAfter)
	}
}

func TestRateLimitRecoveryRespectsRetryAfter(t *testing.T) {
	for _, status := range []int{420, 429} {
		for _, date := range []bool{false, true} {
			t.Run(fmt.Sprintf("%d/date=%t", status, date), func(t *testing.T) {
				var requests atomic.Int32
				var api *apiClient
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if requests.Add(1) == 1 {
						value := "3"
						if date {
							value = api.now().UTC().Truncate(time.Second).Add(3 * time.Second).Format(http.TimeFormat)
						}
						w.Header().Set("Retry-After", value)
						w.WriteHeader(status)
						return
					}
					w.Header().Set("Content-Range", "bytes 0-9/10")
					w.WriteHeader(http.StatusPartialContent)
					_, _ = w.Write([]byte("1234567890"))
				}))
				defer server.Close()
				var waits *[]time.Duration
				api, waits = virtualAPI(server.Client())
				w := &worker{api: api}
				data, err := w.requestRange(server.URL, "0-9")
				if err != nil || string(data) != "1234567890" || requests.Load() != 2 {
					t.Fatalf("data=%q requests=%d err=%v", data, requests.Load(), err)
				}
				if len(*waits) != 1 || (*waits)[0] <= 2*time.Second || (*waits)[0] > 3*time.Second {
					t.Fatalf("waits=%v", *waits)
				}
			})
		}
	}
}

func TestHostCooldownIsSharedAndLongWaitFailsWithoutRequests(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		w.Header().Set("Retry-After", "120")
		w.WriteHeader(429)
	}))
	defer server.Close()
	api, waits := virtualAPI(server.Client())
	_, _, err := api.request("GET", server.URL+"/first", nil, nil)
	var upstream *upstreamError
	if !errors.As(err, &upstream) || upstream.RetryAfter != 120*time.Second {
		t.Fatalf("error=%v", err)
	}
	api.sleep(5 * time.Second)
	_, _, err = api.request("GET", server.URL+"/other-segment", nil, nil)
	if !errors.As(err, &upstream) || upstream.RetryAfter != 115*time.Second {
		t.Fatalf("shared cooldown error=%v", err)
	}
	if requests.Load() != 1 || len(*waits) != 1 {
		t.Fatalf("requests=%d waits=%v", requests.Load(), *waits)
	}
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("ok")) }))
	defer other.Close()
	if _, _, err := api.request("GET", other.URL, nil, nil); err != nil {
		t.Fatalf("unrelated host blocked: %v", err)
	}
}

func TestLaterRequestWaitsForSharedCooldown(t *testing.T) {
	api, waits := virtualAPI(&http.Client{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("ok")) }))
	defer server.Close()
	api.client = server.Client()
	api.coolDown(server.Listener.Addr().String(), 420, 4*time.Second)
	data, _, err := api.request("GET", server.URL, nil, nil)
	if err != nil || string(data) != "ok" || fmt.Sprint(*waits) != "[4s]" {
		t.Fatalf("data=%q waits=%v err=%v", data, *waits, err)
	}
}

func TestRangeDoesNotRetryPermanentHTTPFailure(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { requests.Add(1); w.WriteHeader(404) }))
	defer server.Close()
	api, waits := virtualAPI(server.Client())
	w := &worker{api: api}
	_, err := w.requestRange(server.URL, "0-9")
	if err == nil || requests.Load() != 1 || len(*waits) != 0 {
		t.Fatalf("requests=%d waits=%v err=%v", requests.Load(), *waits, err)
	}
}

func TestAuthenticationRateLimitUsesSharedBudget(t *testing.T) {
	var authentications, segments int
	api, waits := virtualAPI(&http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == "/auth/v1/token" {
			authentications++
			return mockResponse(420, ""), nil
		}
		segments++
		return mockResponse(200, "ok"), nil
	})})
	api.token = ""
	_, _, err := api.request("GET", "https://cdn.example/media", nil, nil)
	var upstream *upstreamError
	if !errors.As(err, &upstream) || upstream.Status != 420 || upstream.Operation != "authentication" || upstream.Attempt != 5 {
		t.Fatalf("error=%v", err)
	}
	if authentications != 5 || segments != 0 || fmt.Sprint(*waits) != "[1s 2s 4s 8s]" {
		t.Fatalf("auth=%d segments=%d waits=%v", authentications, segments, *waits)
	}
}

func TestConcurrentRequestsRespectExistingHostCooldown(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { requests.Add(1) }))
	defer server.Close()
	api := &apiClient{token: "token", expires: time.Now().Add(time.Hour), client: server.Client()}
	api.coolDown(server.Listener.Addr().String(), 420, time.Minute)
	var callers sync.WaitGroup
	for i := 0; i < 8; i++ {
		callers.Add(1)
		go func() {
			defer callers.Done()
			_, _, err := api.request("GET", server.URL, nil, nil)
			var upstream *upstreamError
			if !errors.As(err, &upstream) || upstream.Status != 420 || upstream.RetryAfter < 59*time.Second {
				t.Errorf("cooldown was not preserved: %v", err)
			}
		}()
	}
	callers.Wait()
	if requests.Load() != 0 {
		t.Fatalf("requests during cooldown=%d", requests.Load())
	}
}

func TestTransientServerFailureRecoversAndZeroRetryAfterIsAccepted(t *testing.T) {
	var requests int
	api, waits := virtualAPI(&http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		requests++
		if requests == 1 {
			response := mockResponse(503, "")
			response.Header.Set("Retry-After", "0")
			return response, nil
		}
		return mockResponse(200, "ok"), nil
	})})
	data, _, err := api.request("GET", "https://cdn.example/media", nil, nil)
	if err != nil || string(data) != "ok" || requests != 2 || len(*waits) != 1 || (*waits)[0] != 0 {
		t.Fatalf("data=%q requests=%d waits=%v err=%v", data, requests, *waits, err)
	}
}

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
