package main

import "sync"

type presentation struct {
	Title                        string  `json:"title"`
	Duration                     float64 `json:"duration"`
	RevisionSeed                 string  `json:"revision_seed"`
	CanonicalVideoRepresentation string  `json:"canonical_video_representation,omitempty"`
	Tracks                       []track `json:"tracks"`
}

type track struct {
	ID              string           `json:"id"`
	Kind            string           `json:"kind"`
	Language        string           `json:"language,omitempty"`
	Label           string           `json:"label,omitempty"`
	Default         bool             `json:"default,omitempty"`
	Representations []representation `json:"representations"`
}

type representation struct {
	ID             string    `json:"id"`
	Bandwidth      int64     `json:"bandwidth"`
	Codecs         string    `json:"codecs"`
	MimeType       string    `json:"mime_type"`
	Initialization string    `json:"initialization"`
	Width          *int      `json:"width,omitempty"`
	Height         *int      `json:"height,omitempty"`
	Segments       []segment `json:"segments"`
	versionID      string
	initURL        string
	mediaURLs      map[string]string
	mediaRanges    map[string]string
	initRange      string
}

type segment struct {
	Identity string  `json:"identity"`
	Start    float64 `json:"start"`
	Duration float64 `json:"duration"`
}

type versionState struct {
	contentID string
	language  string
	stream    playbackResponse
	pssh      string
	keys      *licenseContext
	licenseMu sync.Mutex
	initMu    sync.Mutex
	inits     map[string][]byte
}

type mediaState struct {
	mediaKey string
	present  presentation
	versions map[string]*versionState
}
