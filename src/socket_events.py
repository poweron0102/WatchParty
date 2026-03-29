from server_setup import sio
from state import server_state


@sio.event
async def connect(sid, environ):
    print(f"Cliente conectado: {sid}")


@sio.event
async def join_room(sid, data):
    # data = {"name": "User", "pfp": "/cache/pic.png"}
    server_state["users"][sid] = data

    # O primeiro a entrar é o host
    if server_state["host_sid"] is None:
        server_state["host_sid"] = sid
        server_state["users"][sid]["isHost"] = True
        # Initialize screen sharing state for a new room
        server_state["is_screen_sharing"] = False
        await sio.emit('set_host', to=sid)

    await sio.emit('update_users', server_state["users"])

    # If screen share is active, sync the new user to it
    if server_state.get("is_screen_sharing"):
        await sio.emit('sync_event', {
            "type": "set_video",
            "video": "screen-share"
        }, to=sid)
        # Tell host to start WebRTC connection to the new user
        await sio.emit('initiate_screen_share_to_peer', {'target_sid': sid}, to=server_state["host_sid"])
    else:
        # Otherwise, send the normal video state
        await sio.emit('sync_state', {
            "video": server_state["current_video"],
            "time": server_state["current_time"],
            "paused": server_state["is_paused"]
        }, to=sid)


@sio.event
async def disconnect(sid):
    print(f"Cliente desconectado: {sid}")
    was_host = sid == server_state["host_sid"]
    if sid in server_state["users"]:
        del server_state["users"][sid]

    # Se o host saiu, elege um novo host (lógica simples)
    if was_host:
        if server_state.get("is_screen_sharing"):
            server_state["is_screen_sharing"] = False
            server_state["current_video"] = None
            await sio.emit('screen_share_stopped')

        if server_state["users"]:
            new_host_sid = list(server_state["users"].keys())[0]
            server_state["host_sid"] = new_host_sid
            server_state["users"][new_host_sid]["isHost"] = True
            await sio.emit('set_host', to=new_host_sid)
        else:
            server_state["host_sid"] = None  # Sala vazia
            server_state["is_screen_sharing"] = False

    # Atualiza a lista de usuários para todos
    await sio.emit('update_users', server_state["users"])
    
    # Notifica os outros que este usuário saiu, para limpar conexões WebRTC
    await sio.emit('peer_disconnected', {'sid': sid}, skip_sid=sid)


@sio.event
async def send_message(sid, message_text):
    user_info = server_state["users"].get(sid, {"name": "Guest"})
    message_data = {
        "sender": user_info.get("name", "Guest"),
        "pfp": user_info.get("pfp", ""),
        "text": message_text
    }
    await sio.emit('new_message', message_data)


# --- Eventos de Sincronização (Apenas Host) ---

@sio.on("transfer_host")
async def handle_transfer_host(sid, new_host_sid):
    if server_state["host_sid"] == sid:
        if new_host_sid in server_state["users"]:
            server_state["host_sid"] = new_host_sid
            server_state["users"][sid]["isHost"] = False
            server_state["users"][new_host_sid]["isHost"] = True
            
            await sio.emit('set_host', to=new_host_sid)
            await sio.emit('remove_host', to=sid)
            
            await sio.emit('update_users', server_state["users"])

@sio.on("webrtc_signal")
async def handle_webrtc_signal(sid, data):
    """
    Encaminha sinais WebRTC (ofertas, respostas, candidatos)
    para um cliente alvo específico.
    data = {"target_sid": "...", "payload": {...}}
    The payload can now include a "purpose" to distinguish streams.
    """
    target_sid = data.get("target_sid")
    if target_sid and target_sid in server_state["users"]:
        payload = data.get("payload", {})
        payload["sender_sid"] = sid
        await sio.emit('webrtc_signal', payload, to=target_sid)

@sio.on("host_set_video")
async def set_video(sid, video_name):
    print(f"Host ou painel de host definiu o vídeo para: {video_name}")
    server_state["current_video"] = video_name
    server_state["current_time"] = 0
    server_state["is_paused"] = True

    await sio.emit('sync_event', {
        "type": "set_video",
        "video": video_name
    })

    if video_name.startswith("http"):
        await sio.emit('new_message', {
            "sender": "System",
            "pfp": "/system_avatar.png",
            "text": f"Reproduzindo vídeo de: {video_name}"
        })
    else:
        last_slash_index = max(video_name.rfind('/'), video_name.rfind('\\'))
        dir_path = video_name[:last_slash_index] + "/" if last_slash_index != -1 else ''
        base_name = video_name[last_slash_index + 1:video_name.rfind('.')] if last_slash_index != -1 else video_name[:video_name.rfind('.')]
        video_preview_path = f'/videos/{dir_path}.previews/{base_name}_banner.png'
        await sio.emit('new_message', {
            "sender": "System",
            "pfp": "/system_avatar.png",
            "text": f"""
                Playing video: {base_name} <br>
                <img src="{video_preview_path}" style="width:100%;height:100%;object-fit:cover;display:block; border-radius: 1rem;">
            """
        })


@sio.on("host_sync")
async def host_sync_event(sid, data):
    # data = {"type": "play" | "pause" | "seek", "time": 123.45}
    if sid != server_state["host_sid"]:
        return

    # Atualiza estado do servidor
    if data["type"] == "play":
        server_state["is_paused"] = False
    elif data["type"] == "pause":
        server_state["is_paused"] = True

    if "time" in data:
        server_state["current_time"] = data["time"]

    # Transmite o evento para todos, *exceto* o host que enviou
    await sio.emit('sync_event', data, skip_sid=sid)


# --- Eventos de Transmissão de Tela ---

@sio.on("start_screen_share")
async def handle_start_screen_share(sid):
    if sid != server_state.get("host_sid"):
        return

    print(f"Host {sid} iniciou a transmissão de tela.")
    server_state["is_screen_sharing"] = True
    server_state["current_video"] = "screen-share"
    server_state["is_paused"] = False

    # Notify all other clients that screen sharing has started
    await sio.emit('sync_event', {"type": "set_video", "video": "screen-share"}, skip_sid=sid)

    # Tell host to initiate WebRTC connection to each peer
    for peer_sid in server_state["users"]:
        if peer_sid != sid:
            await sio.emit('initiate_screen_share_to_peer', {'target_sid': peer_sid}, to=sid)

@sio.on("stop_screen_share")
async def handle_stop_screen_share(sid):
    if sid != server_state.get("host_sid"):
        return
    print(f"Host {sid} parou a transmissão de tela.")
    server_state["is_screen_sharing"] = False
    server_state["current_video"] = None
    await sio.emit('screen_share_stopped')


@sio.on("request_sync")
async def handle_client_sync_request(sid):
    """
    Chamado por um cliente que deseja verificar se seu tempo está correto.
    O servidor responde com o estado atual para que o cliente possa se corrigir.
    """
    # Só responde se houver um host e um vídeo tocando
    host_sid = server_state.get("host_sid")
    if host_sid is None or server_state.get("current_video") is None:
        return

    try:
        host_state = await sio.call('get_host_time', to=host_sid, timeout=2)

        server_state["current_time"] = host_state["time"]
        server_state["is_paused"] = host_state["paused"]

        await sio.emit('force_sync', host_state, to=sid)

    except Exception as e:
        print(f"Não foi possível obter o tempo do host ({host_sid}): {e}")
