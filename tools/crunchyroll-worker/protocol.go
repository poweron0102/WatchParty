package main

import "encoding/json"

const protocolVersion = 1

type command struct {
	Version       int     `json:"version"`
	Command       string  `json:"command"`
	RequestID     string  `json:"request_id"`
	CorrelationID string  `json:"correlation_id"`
	MediaKey      string  `json:"media_key,omitempty"`
	ETPRT         string  `json:"etp_rt,omitempty"`
	Options       options `json:"options,omitempty"`
	Demand        demand  `json:"demand,omitempty"`
}

type options struct {
	CachePath          string   `json:"cache_path"`
	Locale             string   `json:"locale"`
	AudioLanguages     []string `json:"audio_languages"`
	SubtitleLanguages  []string `json:"subtitle_languages"`
	VideoQuality       string   `json:"video_quality"`
	WorkerIdleSeconds  int      `json:"worker_idle_seconds"`
	WidevineDevicePath string   `json:"widevine_device_path"`
	ClientIDPath       string   `json:"client_id_path"`
	PrivateKeyPath     string   `json:"private_key_path"`
}

type demand struct {
	TrackID          string `json:"track_id"`
	RepresentationID string `json:"representation_id"`
	SegmentIdentity  string `json:"segment_identity"`
	Priority         int    `json:"priority"`
}

type event struct {
	Version       int           `json:"version"`
	Event         string        `json:"event"`
	RequestID     string        `json:"request_id"`
	CorrelationID string        `json:"correlation_id"`
	MediaKey      string        `json:"media_key,omitempty"`
	Stage         string        `json:"stage,omitempty"`
	Code          string        `json:"code,omitempty"`
	Message       string        `json:"message,omitempty"`
	Path          string        `json:"path,omitempty"`
	ContentType   string        `json:"content_type,omitempty"`
	SHA256        string        `json:"sha256,omitempty"`
	Presentation  *presentation `json:"presentation,omitempty"`
}

func response(c command, name string) event {
	return event{Version: protocolVersion, Event: name, RequestID: c.RequestID,
		CorrelationID: c.CorrelationID, MediaKey: c.MediaKey}
}

func decodeCommand(line []byte) (command, error) {
	var c command
	err := json.Unmarshal(line, &c)
	return c, err
}
