package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

const userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36"

type apiClient struct {
	cookie, token, deviceID string
	expires                 time.Time
	client                  *http.Client
	mu                      sync.Mutex
	cooldownMu              sync.Mutex
	cooldowns               map[string]hostCooldown
	clock                   func() time.Time
	sleeper                 func(time.Duration)
}

const requestBudget = 30 * time.Second

type upstreamError struct {
	Status     int
	Operation  string
	Attempt    int
	RetryAfter time.Duration
	Reason     string
}

func (e *upstreamError) Error() string {
	return fmt.Sprintf("upstream %s failed (HTTP %d, attempt %d): %s", e.Operation, e.Status, e.Attempt, e.Reason)
}

type responseReadError struct{}

func (*responseReadError) Error() string { return "upstream response incomplete" }

type hostCooldown struct {
	until  time.Time
	status int
}

func (a *apiClient) now() time.Time {
	if a.clock != nil {
		return a.clock()
	}
	return time.Now()
}

func (a *apiClient) sleep(delay time.Duration) {
	if a.sleeper != nil {
		a.sleeper(delay)
	} else {
		time.Sleep(delay)
	}
}

func retryDelay(value string, now time.Time, fallback time.Duration) time.Duration {
	if seconds, err := strconv.ParseInt(strings.TrimSpace(value), 10, 32); err == nil && seconds >= 0 {
		return time.Duration(seconds) * time.Second
	}
	if date, err := http.ParseTime(value); err == nil {
		if delay := date.Sub(now); delay > 0 {
			return delay
		}
		return 0
	}
	return fallback
}

func retrySeconds(delay time.Duration) int64 {
	if delay <= 0 {
		return 1
	}
	return int64((delay + time.Second - 1) / time.Second)
}

func (a *apiClient) coolDown(host string, status int, delay time.Duration) {
	a.cooldownMu.Lock()
	defer a.cooldownMu.Unlock()
	if a.cooldowns == nil {
		a.cooldowns = map[string]hostCooldown{}
	}
	until := a.now().Add(delay)
	if until.After(a.cooldowns[host].until) {
		a.cooldowns[host] = hostCooldown{until, status}
	}
}

func (a *apiClient) waitForHost(host, operation string, attempt int, deadline time.Time) error {
	for {
		a.cooldownMu.Lock()
		cooldown := a.cooldowns[host]
		a.cooldownMu.Unlock()
		delay := cooldown.until.Sub(a.now())
		if delay <= 0 {
			return nil
		}
		if !a.now().Add(delay).Before(deadline) {
			return &upstreamError{cooldown.status, operation, attempt, delay, "host cooldown exceeds request budget"}
		}
		a.sleep(delay)
	}
}

func newAPI(cookie string) *apiClient {
	idBytes := make([]byte, 16)
	_, _ = rand.Read(idBytes)
	deviceID := fmt.Sprintf("%x-%x-%x-%x-%x", idBytes[0:4], idBytes[4:6], idBytes[6:8], idBytes[8:10], idBytes[10:16])
	dialer := &net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}
	transport := &http.Transport{Proxy: http.ProxyFromEnvironment, ForceAttemptHTTP2: true,
		DialContext: func(ctx context.Context, _, address string) (net.Conn, error) {
			return dialer.DialContext(ctx, "tcp4", address)
		}}
	return &apiClient{cookie: cookieValue(cookie), deviceID: deviceID,
		client: &http.Client{Timeout: 20 * time.Second, Transport: transport}}
}

func (a *apiClient) authenticate(ctx context.Context, deadline time.Time, attempt int) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.token != "" && a.expires.Sub(a.now()) > 30*time.Second {
		return nil
	}
	form := url.Values{"grant_type": {"etp_rt_cookie"}, "device_id": {a.deviceID}, "device_type": {"Chrome on Windows"}}
	if err := a.waitForHost("www.crunchyroll.com", "authentication", attempt, deadline); err != nil {
		return err
	}
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, "https://www.crunchyroll.com/auth/v1/token", strings.NewReader(form.Encode()))
	req.Header.Set("Authorization", "Basic bm9haWhkZXZtXzZpeWcwYThsMHE6")
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Cookie", "etp_rt="+a.cookie+"; device_id="+a.deviceID)
	req.Header.Set("User-Agent", userAgent)
	resp, err := a.client.Do(req)
	if err != nil {
		return &upstreamError{Operation: "authentication", Reason: "network request failed"}
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		delay := retryDelay(resp.Header.Get("Retry-After"), a.now(), time.Second<<(attempt-1))
		if resp.StatusCode == 420 || resp.StatusCode == 429 {
			a.coolDown(req.URL.Host, resp.StatusCode, delay)
		}
		return &upstreamError{Status: resp.StatusCode, Operation: "authentication", RetryAfter: delay, Reason: "HTTP request failed"}
	}
	var body struct {
		AccessToken string `json:"access_token"`
		Expires     int    `json:"expires_in"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&body); err != nil {
		return err
	}
	if body.AccessToken == "" {
		return fmt.Errorf("authentication returned no token")
	}
	a.token = body.AccessToken
	a.expires = a.now().Add(time.Duration(body.Expires) * time.Second)
	return nil
}

func cookieValue(value string) string {
	for _, part := range strings.Split(strings.TrimSpace(value), ";") {
		pair := strings.SplitN(strings.TrimSpace(part), "=", 2)
		if len(pair) == 2 && strings.EqualFold(strings.TrimSpace(pair[0]), "etp_rt") {
			return strings.TrimSpace(pair[1])
		}
	}
	return strings.TrimSpace(value)
}

func (a *apiClient) request(method, target string, body []byte, headers map[string]string) ([]byte, http.Header, error) {
	return a.requestFor("segment", method, target, body, headers)
}

func (a *apiClient) requestFor(operation, method, target string, body []byte, headers map[string]string) ([]byte, http.Header, error) {
	parsed, err := url.Parse(target)
	if err != nil || parsed.Host == "" {
		return nil, nil, &upstreamError{Operation: operation, Reason: "invalid request URL"}
	}
	deadline := a.now().Add(requestBudget)
	ctx, cancel := context.WithTimeout(context.Background(), requestBudget)
	defer cancel()
	var last *upstreamError
	for attempt := 0; attempt < 5; attempt++ {
		if err := a.waitForHost(parsed.Host, operation, attempt+1, deadline); err != nil {
			return nil, nil, err
		}
		if !a.now().Before(deadline) {
			if last != nil {
				return nil, nil, last
			}
			return nil, nil, &upstreamError{Operation: operation, Attempt: attempt + 1, Reason: "request budget exhausted"}
		}
		var responseHeaders http.Header
		var data []byte
		if authErr := a.authenticate(ctx, deadline, attempt+1); authErr != nil {
			if !errors.As(authErr, &last) {
				return nil, nil, &upstreamError{Operation: "authentication", Attempt: attempt + 1, Reason: "invalid authentication response"}
			}
			last.Attempt = attempt + 1
		} else {
			// Authentication can wait behind another caller; recheck any host
			// cooldown announced while this request was waiting for its token.
			if err := a.waitForHost(parsed.Host, operation, attempt+1, deadline); err != nil {
				return nil, nil, err
			}
			req, err := http.NewRequestWithContext(ctx, method, target, bytes.NewReader(body))
			if err != nil {
				return nil, nil, &upstreamError{Operation: operation, Reason: "invalid request"}
			}
			a.mu.Lock()
			req.Header.Set("Authorization", "Bearer "+a.token)
			a.mu.Unlock()
			req.Header.Set("User-Agent", userAgent)
			for k, v := range headers {
				req.Header.Set(k, v)
			}
			resp, err := a.client.Do(req)
			if err != nil {
				last = &upstreamError{Operation: operation, Attempt: attempt + 1, Reason: "network request failed"}
			} else {
				responseHeaders = resp.Header
				var readErr error
				data, readErr = io.ReadAll(io.LimitReader(resp.Body, 128<<20))
				resp.Body.Close()
				fmt.Fprintf(os.Stderr, "[cr-worker] operation=%s status=%d attempt=%d\n", operation, resp.StatusCode, attempt+1)
				if resp.StatusCode/100 == 2 {
					if readErr != nil {
						return nil, responseHeaders, &responseReadError{}
					}
					return data, responseHeaders, nil
				}
				if resp.StatusCode == 401 && attempt == 0 {
					a.mu.Lock()
					a.expires = time.Time{}
					a.mu.Unlock()
					continue
				}
				last = &upstreamError{Status: resp.StatusCode, Operation: operation, Attempt: attempt + 1,
					RetryAfter: retryDelay(resp.Header.Get("Retry-After"), a.now(), time.Second<<attempt), Reason: "HTTP request failed"}
			}
		}
		if last.Status == 0 && last.RetryAfter <= 0 {
			last.RetryAfter = time.Second << attempt
		}
		rateLimited := last.Status == 420 || last.Status == 429
		if rateLimited {
			host := parsed.Host
			if last.Operation == "authentication" {
				host = "www.crunchyroll.com"
			}
			a.coolDown(host, last.Status, last.RetryAfter)
		}
		fmt.Fprintf(os.Stderr, "[cr-worker] operation=%s status=%d attempt=%d retry_after=%d\n", last.Operation, last.Status, last.Attempt, retrySeconds(last.RetryAfter))
		if attempt == 4 || !(rateLimited || last.Status >= 500 || last.Status == 0) {
			return nil, responseHeaders, last
		}
		if !a.now().Add(last.RetryAfter).Before(deadline) {
			return nil, responseHeaders, last
		}
		// Rate-limited calls wait through the shared host gate on the next pass.
		if !rateLimited {
			a.sleep(last.RetryAfter)
		}
	}
	return nil, nil, &upstreamError{Operation: operation, Attempt: 5, Reason: "request budget exhausted"}
}

type playbackResponse struct {
	URL         string                      `json:"url"`
	Token       string                      `json:"token"`
	AudioLocale string                      `json:"audio_locale"`
	Subtitles   map[string]playbackSubtitle `json:"subtitles"`
	Versions    []playbackVersion           `json:"versions"`
}

type playbackVersion struct {
	GUID        string `json:"guid"`
	AudioLocale string `json:"audio_locale"`
}

type playbackSubtitle struct {
	Language string `json:"language"`
	Locale   string `json:"locale"`
	URL      string `json:"url"`
}

func (a *apiClient) openPlayback(id, language string) (playbackResponse, error) {
	target := "https://www.crunchyroll.com/playback/v3/" + url.PathEscape(id) + "/web/firefox/play"
	if language != "" {
		target += "?" + url.Values{"preferred_audio_language": {language}}.Encode()
	}
	b, _, err := a.requestFor("playback", http.MethodGet, target, nil, nil)
	var result playbackResponse
	if err == nil {
		err = json.Unmarshal(b, &result)
	}
	return result, err
}

func playbackIDForLanguage(fallback, language string, stream playbackResponse) string {
	for _, version := range stream.Versions {
		if version.GUID != "" && strings.EqualFold(version.AudioLocale, language) {
			return version.GUID
		}
	}
	return fallback
}

func (a *apiClient) release(id, token string) {
	if token == "" {
		return
	}
	_, _, _ = a.requestFor("release", http.MethodDelete, "https://www.crunchyroll.com/playback/v1/token/"+url.PathEscape(id)+"/"+url.PathEscape(token), nil, nil)
}

func (a *apiClient) license(contentID, streamToken string, challenge []byte) ([]byte, error) {
	headers := map[string]string{"Content-Type": "application/octet-stream", "X-Cr-Content-Id": contentID, "X-Cr-Video-Token": streamToken, "Origin": "https://static.crunchyroll.com", "Referer": "https://static.crunchyroll.com/"}
	b, _, err := a.requestFor("license", http.MethodPost, "https://www.crunchyroll.com/license/v1/license/widevine", challenge, headers)
	if err != nil {
		return nil, err
	}
	var result struct {
		License string `json:"license"`
	}
	if err = json.Unmarshal(b, &result); err != nil {
		return nil, err
	}
	return base64.StdEncoding.DecodeString(result.License)
}
