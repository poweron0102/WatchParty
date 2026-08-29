package main

import (
	"encoding/binary"
	"testing"
)

func TestParseSIDXUsesEndOfSIDXBoxForFirstOffset(t *testing.T) {
	const indexStart = int64(100)
	const firstOffset = uint32(7)
	data := make([]byte, 44+5)
	binary.BigEndian.PutUint32(data[0:4], 44)
	copy(data[4:8], "sidx")
	data[8] = 0
	binary.BigEndian.PutUint32(data[16:20], 1000)
	binary.BigEndian.PutUint32(data[24:28], firstOffset)
	binary.BigEndian.PutUint16(data[30:32], 1)
	binary.BigEndian.PutUint32(data[32:36], 123)
	binary.BigEndian.PutUint32(data[36:40], 1000)

	segments, ranges, err := parseSIDX(data, indexStart, indexStart+int64(len(data))-1)
	if err != nil {
		t.Fatal(err)
	}
	if got := ranges[segments[0].Identity]; got != "151-273" {
		t.Fatalf("range = %q, want 151-273", got)
	}
}
