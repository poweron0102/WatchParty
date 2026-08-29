import hashlib
import ipaddress
import os
import secrets
import sys
from dataclasses import asdict

import fastapi
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import FileResponse, StreamingResponse
from typing import Literal

from config import (CACHE_DIR, FILES_DIR, ICE_SERVERS, MEDIA_SOURCES, PLAYBACK_CONFIG, PORT,
                    TURN_CONFIGURED, TURN_CREDENTIAL_TTL, TURN_HOST, TURN_PORT, TURN_SECRET,
                    persist_remote_host_admin)
from media_sources import (ByteRangeRequest, CollectionNotFound, InvalidByteRange,
                           MediaItemNotFound, ResourceNotFound, SourceNotFound,
                           SourceReadError, SourceUnavailable)
from rtc_config import build_rtc_config, managed_turn_server
from server_setup import app
from state import server_state
from utils import get_public_ip
from playback import PlaybackModule, PlaybackSelection, ResourceRequest
from playback.models import (InvalidPlaybackResource, MaterializationTimeout, PlaybackExpired,
                             PlaybackNotFound, PlaybackPaused)

PLAYBACK = PlaybackModule(MEDIA_SOURCES.playback_origins(),
                          wait_timeout=PLAYBACK_CONFIG["segment_wait_timeout_seconds"])


class RtcModeUpdate(BaseModel):
    mode: Literal["off", "auto", "relay"]


def _resource_url(source_id: str, resource_id: str, revision: str | None = None) -> str:
    from urllib.parse import urlencode
    values = {"source_id": source_id, "resource_id": resource_id}
    if revision:
        values["v"] = revision
    return "/media/resource?" + urlencode(values)


def _serialize_resource(source_id, resource):
    if resource is None:
        return None
    data = asdict(resource)
    data["url"] = _resource_url(source_id, resource.id, resource.revision)
    return data


def _media_error(exc: Exception):
    if isinstance(exc, SourceNotFound):
        return fastapi.HTTPException(404, "Origem não encontrada.")
    if isinstance(exc, (CollectionNotFound, MediaItemNotFound, ResourceNotFound)):
        return fastapi.HTTPException(404, "Conteúdo não encontrado.")
    if isinstance(exc, InvalidByteRange):
        return fastapi.HTTPException(416, "Intervalo de bytes inválido.")
    if isinstance(exc, (SourceUnavailable, SourceReadError)):
        return fastapi.HTTPException(503, "Origem temporariamente indisponível.")
    return fastapi.HTTPException(500, "Falha ao acessar a origem.")


def _parse_range(value: str | None) -> ByteRangeRequest | None:
    if value is None:
        return None
    if not value.startswith("bytes=") or "," in value:
        raise InvalidByteRange("intervalo inválido")
    spec = value[6:].strip()
    if "-" not in spec:
        raise InvalidByteRange("intervalo inválido")
    start_text, end_text = spec.split("-", 1)
    try:
        if not start_text:
            return ByteRangeRequest(suffix_length=int(end_text))
        return ByteRangeRequest(start=int(start_text), end=int(end_text) if end_text else None)
    except (TypeError, ValueError) as exc:
        raise InvalidByteRange("intervalo inválido") from exc


def _is_loopback(request: Request) -> bool:
    try:
        return bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
    except ValueError:
        return False


def _host_is_loopback(hostname: str | None) -> bool:
    try:
        return hostname == "localhost" or ipaddress.ip_address(hostname or "").is_loopback
    except ValueError:
        return False


def _require_host_access(request: Request) -> None:
    if not server_state["allow_remote_host_admin"] and not (
        _is_loopback(request) and _host_is_loopback(request.url.hostname)
    ):
        raise fastapi.HTTPException(403, "Administração do host restrita ao localhost.")


def _require_local_toggle(request: Request) -> None:
    if not _is_loopback(request) or not _host_is_loopback(request.url.hostname):
        raise fastapi.HTTPException(403, "Esta configuração só pode ser alterada pelo localhost.")
    origin = request.headers.get("origin")
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        if not _host_is_loopback(parsed.hostname):
            raise fastapi.HTTPException(403, "Origem da requisição não permitida.")


@app.get("/")
async def get_index():
    return FileResponse(os.path.join(FILES_DIR, "index.html"))


@app.get("/party")
async def get_party():
    return FileResponse(os.path.join(FILES_DIR, "party.html"))


@app.get("/host")
@app.get("/host.html")
async def get_host_page(request: Request):
    _require_host_access(request)
    return FileResponse(os.path.join(FILES_DIR, "host.html"))


@app.get("/api/sources")
async def list_sources():
    return {"sources": [asdict(summary) for summary in MEDIA_SOURCES.summaries],
            "diagnostics": [asdict(item) for item in MEDIA_SOURCES.diagnostics]}


@app.get("/api/host/remote-access")
async def get_remote_host_access(request: Request):
    _require_host_access(request)
    return {"enabled": bool(server_state["allow_remote_host_admin"]), "canChange": _is_loopback(request)}


@app.put("/api/host/remote-access")
async def set_remote_host_access(request: Request, payload: dict):
    _require_local_toggle(request)
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise fastapi.HTTPException(422, "enabled deve ser booleano.")
    try:
        persist_remote_host_admin(enabled)
    except RuntimeError as exc:
        raise fastapi.HTTPException(500, str(exc)) from exc
    server_state["allow_remote_host_admin"] = enabled
    return {"enabled": enabled, "canChange": True}


@app.get("/host/{source_id}/module.js")
async def get_source_host_module(request: Request, source_id: str):
    _require_host_access(request)
    try:
        module = MEDIA_SOURCES.host_module(source_id)
    except Exception as exc:
        raise _media_error(exc) from exc
    return FileResponse(module, media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.api_route("/host/{source_id}/{action:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def source_host_action(request: Request, source_id: str, action: str):
    _require_host_access(request)
    try:
        source = MEDIA_SOURCES.get(source_id)
    except Exception as exc:
        raise _media_error(exc) from exc
    handler = getattr(source, "handle_host_action", None)
    if handler is None:
        raise fastapi.HTTPException(404, "Ação administrativa não encontrada.")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 64 * 1024 * 1024:
                raise fastapi.HTTPException(413, "Payload administrativo excede 64 MiB.")
        except ValueError:
            raise fastapi.HTTPException(400, "Content-Length inválido.")
    try:
        result = await handler(action.strip("/"), request)
    except fastapi.HTTPException:
        raise
    except KeyError as exc:
        raise fastapi.HTTPException(404, str(exc)) from exc
    except Exception as exc:
        print(f"Falha na ação {source_id}/{action}: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise fastapi.HTTPException(500, "Ação administrativa falhou.") from exc
    if result is None:
        raise fastapi.HTTPException(404, "Ação administrativa não encontrada.")
    return result


@app.get("/api/catalog")
async def browse_catalog(source_id: str, parent_id: str | None = None, cursor: str | None = None):
    try:
        page = await MEDIA_SOURCES.get(source_id).browse(parent_id, cursor)
    except Exception as exc:
        raise _media_error(exc) from exc
    items = []
    for item in page.items:
        data = asdict(item)
        for field in ("image", "poster", "thumbnail"):
            data[field] = _serialize_resource(source_id, getattr(item, field))
        items.append(data)
    return {"items": items, "next_cursor": page.next_cursor}


@app.get("/api/media")
async def get_media(source_id: str, media_id: str):
    try:
        item = await MEDIA_SOURCES.get(source_id).get_item(media_id)
    except Exception as exc:
        raise _media_error(exc) from exc
    data = asdict(item)
    data["video"] = _serialize_resource(source_id, item.video)
    for field in ("image", "poster", "thumbnail"):
        data[field] = _serialize_resource(source_id, getattr(item, field))
    for group in ("audio_tracks", "subtitles"):
        for track in data[group]:
            track["url"] = _resource_url(source_id, track["resource_id"])
    return data


@app.get("/api/search")
async def search_catalog(source_id: str, q: str, cursor: str | None = None):
    try:
        page = await MEDIA_SOURCES.get(source_id).search(q, cursor)
    except Exception as exc:
        raise _media_error(exc) from exc
    items = []
    for item in page.items:
        data = asdict(item)
        for field in ("image", "poster", "thumbnail"):
            data[field] = _serialize_resource(source_id, getattr(item, field))
        items.append(data)
    return {"items": items, "next_cursor": page.next_cursor}


@app.post("/api/playback/select")
async def select_playback(selection: dict):
    try:
        descriptor = await PLAYBACK.select(PlaybackSelection(selection["source_id"], selection["media_id"]))
    except (KeyError, PlaybackNotFound):
        raise fastapi.HTTPException(404, "Playback indisponível.")
    except Exception as exc:
        print(f"Falha ao selecionar playback: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise _media_error(exc) from exc
    data = asdict(descriptor)
    data["manifest"]["url"] = f"/playback/{descriptor.playback_id}/asset/manifest.mpd"
    return data


@app.put("/api/playback/{playback_id}/paused")
async def pause_playback(playback_id: str, payload: dict):
    try: await PLAYBACK.set_download_paused(playback_id, bool(payload.get("paused")))
    except PlaybackExpired: raise fastapi.HTTPException(410, "Apresentação substituída.")
    except PlaybackNotFound: raise fastapi.HTTPException(404, "Playback não encontrado.")
    return {"paused": bool(payload.get("paused"))}


@app.api_route("/playback/{playback_id}/asset/{resource_id}", methods=["GET", "HEAD"])
async def playback_asset(request: Request, playback_id: str, resource_id: str):
    try: opened = await PLAYBACK.open(playback_id, resource_id, ResourceRequest(request.method))
    except PlaybackExpired: raise fastapi.HTTPException(410, "Apresentação substituída.")
    except (PlaybackNotFound, InvalidPlaybackResource): raise fastapi.HTTPException(404, "Recurso não encontrado.")
    except PlaybackPaused: raise fastapi.HTTPException(409, "Materialização pausada.", headers={"X-WatchParty-State": "download-paused"})
    except MaterializationTimeout: raise fastapi.HTTPException(503, "Recurso ainda não está pronto.", headers={"Retry-After": "1"})
    headers = {"Content-Length": str(opened.content_length), "Cache-Control": "private, max-age=31536000, immutable"}
    if resource_id == "manifest.mpd": headers["Cache-Control"] = "private, no-cache"
    if request.method == "HEAD": return fastapi.Response(media_type=opened.content_type, headers=headers)
    return StreamingResponse(opened.chunks, media_type=opened.content_type, headers=headers)


@app.api_route("/media/resource", methods=["GET", "HEAD"])
async def stream_resource(request: Request, source_id: str, resource_id: str, v: str | None = None):
    source = None
    try:
        source = MEDIA_SOURCES.get(source_id)
        requested_range = _parse_range(request.headers.get("range"))
        opened = await source.open_resource(resource_id, requested_range)
    except InvalidByteRange as exc:
        headers = {"Accept-Ranges": "bytes"}
        if source is not None:
            try:
                complete = await source.open_resource(resource_id)
                headers["Content-Range"] = f"bytes */{complete.total_size}"
            except Exception:
                pass
        return fastapi.Response(status_code=416, headers=headers)
    except Exception as exc:
        raise _media_error(exc) from exc
    partial = requested_range is not None
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(opened.content_length)}
    if v:
        etag = hashlib.sha256(v.encode()).hexdigest()
        headers.update({"Cache-Control": "private, max-age=31536000, immutable", "ETag": f'"{etag}"'})
    if partial:
        headers["Content-Range"] = f"bytes {opened.start}-{opened.end}/{opened.total_size}"
    if request.method == "HEAD":
        return fastapi.Response(status_code=206 if partial else 200, media_type=opened.content_type, headers=headers)
    return StreamingResponse(opened.chunks, status_code=206 if partial else 200,
                             media_type=opened.content_type, headers=headers)


@app.get("/api/rtc_config")
async def get_rtc_config():
    turn_server = managed_turn_server(TURN_HOST, TURN_PORT, TURN_SECRET,
                                      secrets.token_urlsafe(12), TURN_CREDENTIAL_TTL)
    return build_rtc_config(ICE_SERVERS, server_state["rtc_mode"], turn_server)


@app.get("/api/rtc_mode")
async def get_rtc_mode():
    return {"mode": server_state["rtc_mode"], "turnConfigured": TURN_CONFIGURED}


@app.put("/api/rtc_mode")
async def update_rtc_mode(update: RtcModeUpdate):
    if update.mode != "off" and not TURN_CONFIGURED:
        raise fastapi.HTTPException(409, "O servidor TURN não está configurado.")
    server_state["rtc_mode"] = update.mode
    return {"mode": update.mode, "turnConfigured": TURN_CONFIGURED}


@app.post("/api/upload_image")
async def upload_image(file: fastapi.UploadFile):
    contents = await file.read()
    file_hash = hashlib.sha256(contents).hexdigest()
    _, ext = os.path.splitext(file.filename or "")
    dest_path = os.path.join(CACHE_DIR, f"{file_hash}{ext}")
    os.makedirs(CACHE_DIR, exist_ok=True)
    if not os.path.exists(dest_path):
        with open(dest_path, "wb") as stream:
            stream.write(contents)
    return {"url": f"/{CACHE_DIR}/{file_hash}{ext}"}


@app.get("/api/get_ip")
async def get_ip_address():
    ip = get_public_ip()
    return {"ip": ip, "link": f"http://[{ip}]:{PORT}/" if ":" in ip else f"http://{ip}:{PORT}/"}


app.mount(f"/{CACHE_DIR}", StaticFiles(directory=CACHE_DIR), name="cache")
app.mount("/", StaticFiles(directory=FILES_DIR, html=True), name="static")
