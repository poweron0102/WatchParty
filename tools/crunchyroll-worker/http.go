package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
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

func (a *apiClient) authenticate() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.token != "" && time.Until(a.expires) > 30*time.Second {
		return nil
	}
	form := url.Values{"grant_type": {"etp_rt_cookie"}, "device_id": {a.deviceID}, "device_type": {"Chrome on Windows"}}
	req, _ := http.NewRequest(http.MethodPost, "https://www.crunchyroll.com/auth/v1/token", strings.NewReader(form.Encode()))
	req.Header.Set("Authorization", "Basic bm9haWhkZXZtXzZpeWcwYThsMHE6")
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Cookie", "etp_rt="+a.cookie+"; device_id="+a.deviceID)
	req.Header.Set("User-Agent", userAgent)
	resp, err := a.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return fmt.Errorf("authentication failed (HTTP %d)", resp.StatusCode)
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
	a.expires = time.Now().Add(time.Duration(body.Expires) * time.Second)
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
	for attempt := 0; attempt < 5; attempt++ {
		if err := a.authenticate(); err != nil {
			return nil, nil, err
		}
		req, err := http.NewRequest(method, target, bytes.NewReader(body))
		if err != nil {
			return nil, nil, err
		}
		req.Header.Set("Authorization", "Bearer "+a.token)
		req.Header.Set("User-Agent", userAgent)
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		resp, err := a.client.Do(req)
		if err != nil {
			if attempt < 4 {
				time.Sleep(time.Duration(attempt+1) * time.Second)
				continue
			}
			return nil, nil, err
		}
		data, readErr := io.ReadAll(io.LimitReader(resp.Body, 128<<20))
		resp.Body.Close()
		if readErr != nil {
			return nil, nil, readErr
		}
		if resp.StatusCode == 401 && attempt == 0 {
			a.mu.Lock()
			a.expires = time.Time{}
			a.mu.Unlock()
			continue
		}
		if resp.StatusCode == 420 || resp.StatusCode == 429 || resp.StatusCode >= 500 {
			delay := time.Duration(attempt+1) * time.Second
			if seconds, e := strconv.Atoi(resp.Header.Get("Retry-After")); e == nil && seconds > 0 {
				delay = time.Duration(seconds) * time.Second
			}
			if attempt < 4 {
				time.Sleep(delay)
				continue
			}
		}
		if resp.StatusCode/100 != 2 {
			return nil, resp.Header, fmt.Errorf("upstream request failed (HTTP %d)", resp.StatusCode)
		}
		return data, resp.Header, nil
	}
	return nil, nil, fmt.Errorf("upstream retry budget exhausted")
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
	b, _, err := a.request(http.MethodGet, target, nil, nil)
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
	_, _, _ = a.request(http.MethodDelete, "https://www.crunchyroll.com/playback/v1/token/"+url.PathEscape(id)+"/"+url.PathEscape(token), nil, nil)
}

func (a *apiClient) license(contentID, streamToken string, challenge []byte) ([]byte, error) {
	headers := map[string]string{"Content-Type": "application/octet-stream", "X-Cr-Content-Id": contentID, "X-Cr-Video-Token": streamToken, "Origin": "https://static.crunchyroll.com", "Referer": "https://static.crunchyroll.com/"}
	b, _, err := a.request(http.MethodPost, "https://www.crunchyroll.com/license/v1/license/widevine", challenge, headers)
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
