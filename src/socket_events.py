import uuid
import html
import ipaddress
from urllib.parse import urlencode, urlparse

from config import MEDIA_SOURCES
from media_sources import MediaSourceError
from server_setup import sio
from state import server_state


SCREEN_SHARE_VIDEO_ID = "screen-share"


def _is_host(sid):
    return sid == server_state.get("host_sid")


def _is_control_panel(sid):
    environ = sio.get_environ(sid) or {}
    referer = urlparse(environ.get("HTTP_REFERER", ""))
    if referer.path.rstrip("/") not in {"/host", "/host.html"}:
        return False
    if server_state.get("allow_remote_host_admin"):
        return True
    try:
        peer_is_local = ipaddress.ip_address(environ.get("REMOTE_ADDR", "")).is_loopback
        referer_is_local = referer.hostname == "localhost" or ipaddress.ip_address(referer.hostname or "").is_loopback
        return peer_is_local and referer_is_local
    except ValueError:
        return False


async def _stop_active_screen_share(reset_video=True):
    if not server_state.get("is_screen_sharing"):
        server_state["screen_share_session_id"] = None
        return

    session_id = server_state.get("screen_share_session_id")
    server_state["is_screen_sharing"] = False
    server_state["screen_share_session_id"] = None

    if reset_video:
        server_state["current_video"] = None
        server_state["current_time"] = 0
        server_state["is_paused"] = True

    await sio.emit("screen_share_stopped", {"session_id": session_id})


@sio.event
async def connect(sid, environ):
    print(f"Cliente conectado: {sid}")


@sio.event
async def join_room(sid, data):
    server_state["users"][sid] = data or {}

    if server_state["host_sid"] is None:
        server_state["host_sid"] = sid
        server_state["users"][sid]["isHost"] = True
        await sio.emit("set_host", to=sid)

    await sio.emit("update_users", server_state["users"])

    if server_state.get("is_screen_sharing"):
        session_id = server_state.get("screen_share_session_id")
        await sio.emit("sync_event", {
            "type": "set_video",
            "video": SCREEN_SHARE_VIDEO_ID,
            "session_id": session_id
        }, to=sid)

        host_sid = server_state.get("host_sid")
        if host_sid and host_sid in server_state["users"] and host_sid != sid:
            await sio.emit("initiate_screen_share_to_peer", {
                "target_sid": sid,
                "session_id": session_id
            }, to=host_sid)
        return

    await sio.emit("sync_state", {
        "video": server_state["current_video"],
        "time": server_state["current_time"],
        "paused": server_state["is_paused"],
        "session_id": None
    }, to=sid)


@sio.event
async def disconnect(sid):
    print(f"Cliente desconectado: {sid}")
    was_host = _is_host(sid)

    if sid in server_state["users"]:
        del server_state["users"][sid]

    if was_host:
        await _stop_active_screen_share(reset_video=True)

        if server_state["users"]:
            new_host_sid = list(server_state["users"].keys())[0]
            server_state["host_sid"] = new_host_sid
            server_state["users"][new_host_sid]["isHost"] = True
            await sio.emit("set_host", to=new_host_sid)
        else:
            server_state["host_sid"] = None
            server_state["is_screen_sharing"] = False
            server_state["screen_share_session_id"] = None

    await sio.emit("update_users", server_state["users"])
    await sio.emit("peer_disconnected", {"sid": sid}, skip_sid=sid)


@sio.event
async def send_message(sid, message_text):
    user_info = server_state["users"].get(sid, {"name": "Guest"})
    message_data = {
        "sender": user_info.get("name", "Guest"),
        "pfp": user_info.get("pfp", ""),
        "text": message_text
    }
    await sio.emit("new_message", message_data)


@sio.on("transfer_host")
async def handle_transfer_host(sid, new_host_sid):
    if not _is_host(sid):
        return

    if new_host_sid not in server_state["users"]:
        return

    await _stop_active_screen_share(reset_video=True)

    server_state["host_sid"] = new_host_sid
    server_state["users"][sid]["isHost"] = False
    server_state["users"][new_host_sid]["isHost"] = True

    await sio.emit("set_host", to=new_host_sid)
    await sio.emit("remove_host", to=sid)
    await sio.emit("update_users", server_state["users"])


@sio.on("webrtc_signal")
async def handle_webrtc_signal(sid, data):
    target_sid = data.get("target_sid")
    if not target_sid or target_sid not in server_state["users"]:
        return

    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        return

    if payload.get("purpose") == "screen":
        session_id = payload.get("session_id")
        if not server_state.get("is_screen_sharing"):
            return
        if session_id != server_state.get("screen_share_session_id"):
            return

    payload["sender_sid"] = sid
    await sio.emit("webrtc_signal", payload, to=target_sid)


@sio.on("host_set_video")
async def set_video(sid, selection):
    if not (_is_host(sid) or _is_control_panel(sid)):
        return
    if not isinstance(selection, dict):
        return
    source_id, media_id = selection.get("source_id"), selection.get("media_id")
    if not isinstance(source_id, str) or not isinstance(media_id, str):
        return
    try:
        item = await MEDIA_SOURCES.get(source_id).get_item(media_id)
    except MediaSourceError:
        await sio.emit("media_selection_error", {"message": "Não foi possível selecionar esse item."}, to=sid)
        return
    selection = {"source_id": source_id, "media_id": media_id}
    print(f"Seleção de mídia definida na origem {source_id}")

    if server_state.get("is_screen_sharing"):
        await _stop_active_screen_share(reset_video=False)

    server_state["current_video"] = selection
    server_state["current_time"] = 0
    server_state["is_paused"] = True
    server_state["is_screen_sharing"] = False
    server_state["screen_share_session_id"] = None

    await sio.emit("sync_event", {
        "type": "set_video",
        "video": selection,
        "session_id": None
    })

    image = ""
    if item.image:
        image_url = "/media/resource?" + urlencode({"source_id": source_id, "resource_id": item.image.id})
        image = f'<br><img src="{html.escape(image_url)}" style="width:100%;height:100%;object-fit:cover;display:block;border-radius:1rem;">'
    await sio.emit("new_message", {
        "sender": "System",
        "pfp": "/system_avatar.png",
        "text": f"Reproduzindo: {html.escape(item.title)}{image}"
    })


@sio.on("host_sync")
async def host_sync_event(sid, data):
    if not _is_host(sid):
        return

    if server_state.get("is_screen_sharing"):
        return

    if data["type"] == "play":
        server_state["is_paused"] = False
    elif data["type"] == "pause":
        server_state["is_paused"] = True

    if "time" in data:
        server_state["current_time"] = data["time"]

    await sio.emit("sync_event", data, skip_sid=sid)


@sio.on("start_screen_share")
async def handle_start_screen_share(sid):
    if not _is_host(sid):
        return

    if server_state.get("is_screen_sharing"):
        await _stop_active_screen_share(reset_video=False)

    session_id = uuid.uuid4().hex
    print(f"Host {sid} iniciou a transmissao de tela ({session_id}).")

    server_state["is_screen_sharing"] = True
    server_state["screen_share_session_id"] = session_id
    server_state["current_video"] = None
    server_state["current_time"] = 0
    server_state["is_paused"] = False

    await sio.emit("sync_event", {
        "type": "set_video",
        "video": SCREEN_SHARE_VIDEO_ID,
        "session_id": session_id
    }, skip_sid=sid)

    for peer_sid in server_state["users"]:
        if peer_sid != sid:
            await sio.emit("initiate_screen_share_to_peer", {
                "target_sid": peer_sid,
                "session_id": session_id
            }, to=sid)


@sio.on("stop_screen_share")
async def handle_stop_screen_share(sid, data=None):
    if not _is_host(sid):
        return

    requested_session_id = data.get("session_id") if isinstance(data, dict) else None
    active_session_id = server_state.get("screen_share_session_id")
    if requested_session_id and active_session_id and requested_session_id != active_session_id:
        return

    print(f"Host {sid} parou a transmissao de tela.")
    await _stop_active_screen_share(reset_video=True)


@sio.on("request_sync")
async def handle_client_sync_request(sid):
    host_sid = server_state.get("host_sid")
    if host_sid is None or server_state.get("current_video") is None:
        return

    if server_state.get("is_screen_sharing"):
        return

    try:
        host_state = await sio.call("get_host_time", to=host_sid, timeout=2)

        server_state["current_time"] = host_state["time"]
        server_state["is_paused"] = host_state["paused"]

        await sio.emit("force_sync", host_state, to=sid)

    except Exception as e:
        print(f"Nao foi possivel obter o tempo do host ({host_sid}): {e}")
