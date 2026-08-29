package main

import (
	"encoding/binary"
	"fmt"
	"strconv"
	"strings"
)

func parseByteRange(value string) (int64, int64, error) {
	parts := strings.Split(value, "-")
	if len(parts) != 2 {
		return 0, 0, fmt.Errorf("invalid byte range")
	}
	start, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil {
		return 0, 0, err
	}
	end, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil || end < start {
		return 0, 0, fmt.Errorf("invalid byte range")
	}
	return start, end, nil
}

func parseSIDX(data []byte, indexStart, indexEnd int64) ([]segment, map[string]string, error) {
	if len(data) < 32 {
		return nil, nil, fmt.Errorf("sidx is too short")
	}
	boxSize := int(binary.BigEndian.Uint32(data[0:4]))
	if boxSize == 1 {
		if len(data) < 16 {
			return nil, nil, fmt.Errorf("invalid sidx")
		}
		boxSize = int(binary.BigEndian.Uint64(data[8:16]))
	}
	if string(data[4:8]) != "sidx" || boxSize > len(data) {
		return nil, nil, fmt.Errorf("sidx box not found")
	}
	version := data[8]
	pos := 12
	if pos+8 > len(data) {
		return nil, nil, fmt.Errorf("invalid sidx")
	}
	pos += 4 // reference_ID
	timescale := binary.BigEndian.Uint32(data[pos : pos+4])
	pos += 4
	var earliest, firstOffset uint64
	if version == 0 {
		if pos+8 > len(data) {
			return nil, nil, fmt.Errorf("invalid sidx")
		}
		earliest = uint64(binary.BigEndian.Uint32(data[pos : pos+4]))
		firstOffset = uint64(binary.BigEndian.Uint32(data[pos+4 : pos+8]))
		pos += 8
	} else {
		if pos+16 > len(data) {
			return nil, nil, fmt.Errorf("invalid sidx")
		}
		earliest = binary.BigEndian.Uint64(data[pos : pos+8])
		firstOffset = binary.BigEndian.Uint64(data[pos+8 : pos+16])
		pos += 16
	}
	if pos+2 > len(data) {
		return nil, nil, fmt.Errorf("invalid sidx")
	}
	pos += 2
	count := int(binary.BigEndian.Uint16(data[pos : pos+2]))
	pos += 2
	base := uint64(indexEnd+1) + firstOffset
	current := earliest
	segments := make([]segment, 0, count)
	ranges := make(map[string]string, count)
	for i := 0; i < count; i++ {
		if pos+12 > len(data) {
			return nil, nil, fmt.Errorf("truncated sidx")
		}
		ref := binary.BigEndian.Uint32(data[pos : pos+4])
		dur := binary.BigEndian.Uint32(data[pos+4 : pos+8])
		pos += 12
		if ref&0x80000000 != 0 {
			return nil, nil, fmt.Errorf("nested sidx is unsupported")
		}
		size := uint64(ref)
		start := base
		end := base + size - 1
		id := fmt.Sprintf("sidx-%d", i)
		scale := float64(timescale)
		if scale == 0 {
			scale = 1
		}
		segments = append(segments, segment{id, float64(current) / scale, float64(dur) / scale})
		ranges[id] = fmt.Sprintf("%d-%d", start, end)
		base = end + 1
		current += uint64(dur)
	}
	return segments, ranges, nil
}
