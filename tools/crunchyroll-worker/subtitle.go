package main

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
)

var assTag = regexp.MustCompile(`\{[^}]*\}`)

func requestedLanguages(values []string) []string {
	seen := map[string]bool{}
	var result []string
	for _, value := range values {
		value = strings.TrimSpace(value)
		key := strings.ToLower(value)
		if value == "" || value == "*" || seen[key] {
			continue
		}
		seen[key] = true
		result = append(result, value)
	}
	return result
}

func availableAudioLanguages(stream playbackResponse, configured []string) []string {
	result := requestedLanguages(configured)
	seen := map[string]bool{}
	for _, value := range result {
		seen[strings.ToLower(value)] = true
	}
	appendLanguage := func(value string) {
		value = strings.TrimSpace(value)
		key := strings.ToLower(value)
		if value != "" && !seen[key] {
			seen[key] = true
			result = append(result, value)
		}
	}
	appendLanguage(stream.AudioLocale)
	for _, version := range stream.Versions {
		appendLanguage(version.AudioLocale)
	}
	return result
}

func languageAllowed(language string, configured []string) bool {
	if len(configured) == 0 {
		return false
	}
	for _, allowed := range configured {
		if allowed == "*" || strings.EqualFold(strings.TrimSpace(allowed), strings.TrimSpace(language)) {
			return true
		}
	}
	return false
}

func subtitleTrack(mediaKey, language, label, target string) track {
	if label == "" {
		label = language
	}
	id := "subtitle:" + strings.ToLower(language)
	rep := representation{ID: id + ":vtt", Bandwidth: 1, Codecs: "wvtt", MimeType: "text/vtt", Initialization: "subtitle", versionID: mediaKey, initURL: target}
	return track{ID: id, Kind: "text", Language: language, Label: label, Representations: []representation{rep}}
}

func subtitleToVTT(raw []byte) []byte {
	text := strings.TrimPrefix(string(raw), "\ufeff")
	if strings.HasPrefix(strings.TrimSpace(text), "WEBVTT") {
		return []byte(text)
	}
	var cues []string
	for _, line := range strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n") {
		if !strings.HasPrefix(line, "Dialogue:") {
			continue
		}
		fields := strings.SplitN(strings.TrimSpace(strings.TrimPrefix(line, "Dialogue:")), ",", 10)
		if len(fields) != 10 {
			continue
		}
		body := assTag.ReplaceAllString(fields[9], "")
		body = strings.ReplaceAll(strings.ReplaceAll(body, `\N`, "\n"), `\n`, "\n")
		cues = append(cues, fmt.Sprintf("%s --> %s\n%s", vttTime(fields[1]), vttTime(fields[2]), body))
	}
	sort.SliceStable(cues, func(i, j int) bool { return cues[i] < cues[j] })
	return []byte("WEBVTT\n\n" + strings.Join(cues, "\n\n") + "\n")
}

func vttTime(value string) string {
	value = strings.TrimSpace(value)
	parts := strings.Split(value, ":")
	if len(parts) != 3 {
		return value
	}
	seconds := strings.Replace(parts[2], ".", ",", 1)
	if dot := strings.Index(seconds, ","); dot >= 0 {
		fraction := seconds[dot+1:] + "000"
		seconds = seconds[:dot] + "." + fraction[:3]
	}
	return fmt.Sprintf("%02s:%s:%s", parts[0], parts[1], seconds)
}
