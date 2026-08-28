from __future__ import annotations

import html
from datetime import timedelta

from .models import OriginPresentation


def _duration(seconds: float) -> str:
    return "PT" + str(timedelta(seconds=seconds).total_seconds()).rstrip("0").rstrip(".") + "S"


def build_mpd(presentation: OriginPresentation, resource_ids: dict[tuple[str, str, str], str]) -> bytes:
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="{_duration(presentation.duration)}" minBufferTime="PT1.5S">',
             '<Period id="p0" start="PT0S">']
    for track in presentation.tracks:
        attrs = [f'id="{html.escape(track.id)}"', f'contentType="{html.escape(track.kind)}"']
        if track.language: attrs.append(f'lang="{html.escape(track.language)}"')
        parts.append(f'<AdaptationSet {" ".join(attrs)}>')
        for rep in track.representations:
            extra = f' width="{rep.width}" height="{rep.height}"' if rep.width and rep.height else ""
            parts.append(f'<Representation id="{html.escape(rep.id)}" bandwidth="{rep.bandwidth}" codecs="{html.escape(rep.codecs)}" mimeType="{html.escape(rep.mime_type)}"{extra}>')
            parts.append('<SegmentList timescale="1000">')
            init_id = resource_ids[(track.id, rep.id, rep.initialization)]
            parts.append(f'<Initialization sourceURL="{init_id}"/>')
            for segment in rep.segments:
                rid = resource_ids[(track.id, rep.id, segment.identity)]
                parts.append(f'<SegmentURL media="{rid}"/>')
            parts.extend(['</SegmentList>', '</Representation>'])
        parts.append('</AdaptationSet>')
    parts.extend(['</Period>', '</MPD>'])
    return ''.join(parts).encode()
