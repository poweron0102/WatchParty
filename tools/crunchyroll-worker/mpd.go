package main

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/xml"
	"fmt"
	"net/url"
	"strconv"
	"strings"
)

type xMPD struct {
	XMLName  xml.Name   `xml:"MPD"`
	Duration string     `xml:"mediaPresentationDuration,attr"`
	Base     string     `xml:"BaseURL"`
	Template *xTemplate `xml:"SegmentTemplate"`
	Periods  []xPeriod  `xml:"Period"`
}
type xPeriod struct {
	Base     string     `xml:"BaseURL"`
	Template *xTemplate `xml:"SegmentTemplate"`
	Sets     []xSet     `xml:"AdaptationSet"`
}
type xSet struct {
	ID          string        `xml:"id,attr"`
	ContentType string        `xml:"contentType,attr"`
	MimeType    string        `xml:"mimeType,attr"`
	Codecs      string        `xml:"codecs,attr"`
	Lang        string        `xml:"lang,attr"`
	Base        string        `xml:"BaseURL"`
	Template    *xTemplate    `xml:"SegmentTemplate"`
	SegmentBase *xSegmentBase `xml:"SegmentBase"`
	Reps        []xRep        `xml:"Representation"`
	Protections []xProtection `xml:"ContentProtection"`
}
type xSegmentBase struct {
	IndexRange     string           `xml:"indexRange,attr"`
	Initialization *xInitialization `xml:"Initialization"`
}
type xInitialization struct {
	Range string `xml:"range,attr"`
}
type xRep struct {
	ID          string        `xml:"id,attr"`
	MimeType    string        `xml:"mimeType,attr"`
	Codecs      string        `xml:"codecs,attr"`
	Bandwidth   int64         `xml:"bandwidth,attr"`
	Width       *int          `xml:"width,attr"`
	Height      *int          `xml:"height,attr"`
	Base        string        `xml:"BaseURL"`
	Template    *xTemplate    `xml:"SegmentTemplate"`
	SegmentBase *xSegmentBase `xml:"SegmentBase"`
	Protections []xProtection `xml:"ContentProtection"`
}
type xTemplate struct {
	Timescale      uint64 `xml:"timescale,attr"`
	PTO            uint64 `xml:"presentationTimeOffset,attr"`
	StartNumber    uint64 `xml:"startNumber,attr"`
	Media          string `xml:"media,attr"`
	Initialization string `xml:"initialization,attr"`
	Timeline       struct {
		S []xS `xml:"S"`
	} `xml:"SegmentTimeline"`
}
type xS struct {
	T *uint64 `xml:"t,attr"`
	D uint64  `xml:"d,attr"`
	R int64   `xml:"r,attr"`
}
type xProtection struct {
	Scheme string `xml:"schemeIdUri,attr"`
	KID    string `xml:"default_KID,attr"`
	PSSH   string `xml:"pssh"`
}

func isWidevineProtection(protection xProtection) bool {
	scheme := strings.ToLower(strings.TrimSpace(protection.Scheme))
	return strings.Contains(scheme, "widevine") || strings.Contains(scheme, "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed")
}

func parseDuration(v string) float64 {
	if !strings.HasPrefix(v, "PT") {
		return 0
	}
	v = strings.TrimPrefix(v, "PT")
	total := 0.0
	number := ""
	for _, r := range v {
		if (r >= '0' && r <= '9') || r == '.' {
			number += string(r)
			continue
		}
		n, _ := strconv.ParseFloat(number, 64)
		number = ""
		if r == 'H' {
			total += n * 3600
		} else if r == 'M' {
			total += n * 60
		} else if r == 'S' {
			total += n
		}
	}
	return total
}
func resolve(base, child string) string {
	if child == "" {
		return base
	}
	b, e := url.Parse(base)
	if e != nil {
		return child
	}
	c, e := url.Parse(strings.TrimSpace(child))
	if e != nil {
		return child
	}
	return b.ResolveReference(c).String()
}
func expand(template *xTemplate, repID, base string, totalDuration float64) (string, map[string]string, []segment) {
	if template == nil {
		return "", nil, nil
	}
	scale := template.Timescale
	if scale == 0 {
		scale = 1
	}
	number := template.StartNumber
	if number == 0 {
		number = 1
	}
	current := uint64(0)
	urls := map[string]string{}
	out := []segment{}
	for index, item := range template.Timeline.S {
		if item.T != nil {
			current = *item.T
		}
		repeat := item.R
		if repeat < 0 {
			if item.D == 0 {
				repeat = 0
			} else {
				repeat = int64(totalDuration*float64(scale)-float64(current))/int64(item.D) - 1
			}
		}
		for i := int64(0); i <= repeat; i++ {
			identity := fmt.Sprintf("t-%d", current)
			media := substitute(template.Media, repID, number, current)
			urls[identity] = resolve(base, media)
			out = append(out, segment{identity, (float64(current) - float64(template.PTO)) / float64(scale), float64(item.D) / float64(scale)})
			current += item.D
			number++
		}
		_ = index
	}
	return resolve(base, substitute(template.Initialization, repID, number, current)), urls, out
}
func substitute(v, id string, number, t uint64) string {
	v = strings.ReplaceAll(v, "$RepresentationID$", id)
	v = strings.ReplaceAll(v, "$Time$", strconv.FormatUint(t, 10))
	v = strings.ReplaceAll(v, "$Number$", strconv.FormatUint(number, 10))
	for width := 1; width <= 12; width++ {
		v = strings.ReplaceAll(v, fmt.Sprintf("$Number%%0%dd$", width), fmt.Sprintf("%0*d", width, number))
	}
	return v
}

func parseMPD(raw []byte, manifestURL, versionID, language string) (presentation, string, error) {
	var doc xMPD
	if err := xml.Unmarshal(raw, &doc); err != nil {
		return presentation{}, "", err
	}
	duration := parseDuration(doc.Duration)
	result := presentation{Duration: duration}
	var pssh string
	for pi, p := range doc.Periods {
		periodBase := resolve(resolve(manifestURL, doc.Base), p.Base)
		for si, set := range p.Sets {
			kind := set.ContentType
			if kind == "" {
				if strings.HasPrefix(set.MimeType, "video/") {
					kind = "video"
				} else if strings.HasPrefix(set.MimeType, "audio/") {
					kind = "audio"
				} else if strings.HasPrefix(set.MimeType, "text/") {
					kind = "text"
				}
			}
			if kind != "video" && kind != "audio" {
				continue
			}
			tr := track{ID: fmt.Sprintf("%s:p%d:s%d", versionID, pi, si), Kind: kind, Language: set.Lang, Label: set.Lang}
			if kind == "audio" && language != "" {
				tr.Language = language
				tr.Label = language
			}
			setBase := resolve(periodBase, set.Base)
			for _, cp := range set.Protections {
				if isWidevineProtection(cp) && strings.TrimSpace(cp.PSSH) != "" {
					pssh = strings.TrimSpace(cp.PSSH)
				}
			}
			for _, rep := range set.Reps {
				tmpl := rep.Template
				if tmpl == nil {
					tmpl = set.Template
				}
				if tmpl == nil {
					tmpl = p.Template
				}
				if tmpl == nil {
					tmpl = doc.Template
				}
				repBase := resolve(setBase, rep.Base)
				initURL, mediaURLs, segs := expand(tmpl, rep.ID, repBase, duration)
				var mediaRanges map[string]string
				initRange := ""
				if rep.SegmentBase != nil {
					initURL, mediaURLs, segs = repBase, map[string]string{}, nil
					mediaRanges = map[string]string{}
					if rep.SegmentBase.Initialization != nil {
						initRange = rep.SegmentBase.Initialization.Range
					}
					if rep.SegmentBase.IndexRange != "" {
						mediaRanges["__index__"] = rep.SegmentBase.IndexRange
					}
				}
				mime := rep.MimeType
				if mime == "" {
					mime = set.MimeType
				}
				codecs := rep.Codecs
				if codecs == "" {
					codecs = set.Codecs
				}
				rr := representation{ID: tr.ID + ":" + rep.ID, Bandwidth: rep.Bandwidth, Codecs: codecs, MimeType: mime, Initialization: "init", Width: rep.Width, Height: rep.Height, Segments: segs, versionID: versionID, initURL: initURL, mediaURLs: mediaURLs, mediaRanges: mediaRanges, initRange: initRange}
				tr.Representations = append(tr.Representations, rr)
				for _, cp := range rep.Protections {
					if isWidevineProtection(cp) && strings.TrimSpace(cp.PSSH) != "" {
						pssh = strings.TrimSpace(cp.PSSH)
					}
				}
			}
			if len(tr.Representations) > 0 {
				result.Tracks = append(result.Tracks, tr)
			}
		}
	}
	h := sha256.Sum256(raw)
	result.RevisionSeed = hex.EncodeToString(h[:])
	return result, pssh, nil
}

func decodePSSH(value string) ([]byte, error) {
	value = strings.TrimSpace(value)
	return base64.StdEncoding.DecodeString(value)
}
