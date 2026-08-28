package main

import (
	"bytes"
	"fmt"
	"os"

	"github.com/Eyevinn/mp4ff/mp4"
	widevine "github.com/iyear/gowidevine"
	"github.com/iyear/gowidevine/widevinepb"
)

type licenseContext struct{ keys []*widevine.Key }

func loadDevice(o options) (*widevine.Device, error) {
	if o.WidevineDevicePath != "" {
		f, e := os.Open(o.WidevineDevicePath)
		if e != nil {
			return nil, e
		}
		return widevine.NewDevice(widevine.FromWVD(f))
	}
	if o.ClientIDPath == "" || o.PrivateKeyPath == "" {
		return nil, fmt.Errorf("widevine device is not configured")
	}
	client, e := os.ReadFile(o.ClientIDPath)
	if e != nil {
		return nil, e
	}
	key, e := os.ReadFile(o.PrivateKeyPath)
	if e != nil {
		return nil, e
	}
	return widevine.NewDevice(widevine.FromRaw(client, key))
}

func acquireLicense(api *apiClient, o options, contentID, token, psshText string) (*licenseContext, error) {
	device, err := loadDevice(o)
	if err != nil {
		return nil, err
	}
	raw, err := decodePSSH(psshText)
	if err != nil {
		return nil, err
	}
	pssh, err := widevine.NewPSSH(raw)
	if err != nil {
		return nil, err
	}
	cdm := widevine.NewCDM(device)
	challenge, parse, err := cdm.GetLicenseChallenge(pssh, widevinepb.LicenseType_AUTOMATIC, false)
	if err != nil {
		return nil, err
	}
	license, err := api.license(contentID, token, challenge)
	if err != nil {
		return nil, err
	}
	keys, err := parse(license)
	if err != nil {
		return nil, err
	}
	return &licenseContext{keys: keys}, nil
}

func decryptFragment(init, media []byte, context *licenseContext) ([]byte, []byte, error) {
	joined := make([]byte, 0, len(init)+len(media))
	joined = append(joined, init...)
	joined = append(joined, media...)
	file, err := mp4.DecodeFile(bytes.NewReader(joined))
	if err != nil {
		return nil, nil, err
	}
	if file.Init == nil {
		return nil, nil, fmt.Errorf("fragment has no init")
	}
	info, err := mp4.DecryptInit(file.Init)
	if err != nil {
		return nil, nil, err
	}
	var kid []byte
	for _, track := range info.TrackInfos {
		if track.Sinf != nil && track.Sinf.Schi != nil && track.Sinf.Schi.Tenc != nil {
			kid = []byte(track.Sinf.Schi.Tenc.DefaultKID)
			break
		}
	}
	var key []byte
	for _, candidate := range context.keys {
		if bytes.Equal(candidate.ID, kid) {
			key = candidate.Key
			break
		}
	}
	if len(key) == 0 {
		return nil, nil, fmt.Errorf("license has no key matching fragment KID")
	}
	for _, segment := range file.Segments {
		if err = mp4.DecryptSegment(segment, info, key); err != nil && err.Error() != "no senc box in traf" {
			return nil, nil, err
		}
	}
	var clearInit, clearMedia bytes.Buffer
	if err = file.Init.Encode(&clearInit); err != nil {
		return nil, nil, err
	}
	for _, segment := range file.Segments {
		if err = segment.Encode(&clearMedia); err != nil {
			return nil, nil, err
		}
	}
	return clearInit.Bytes(), clearMedia.Bytes(), nil
}
