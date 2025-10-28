# /src/socket_events.py

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
        await sio.emit('set_host', to=sid)  # Avisa o cliente que ele é o host

    # Envia a lista de usuários atualizada para todos
    await sio.emit('update_users', server_state["users"])

    # Envia o estado atual do vídeo para o novo usuário
    await sio.emit('sync_state', {
        "video": server_state["current_video"],
        "time": server_state["current_time"],
        "paused": server_state["is_paused"]
    }, to=sid)


@sio.event
async def disconnect(sid):
    print(f"Cliente desconectado: {sid}")
    if sid in server_state["users"]:
        del server_state["users"][sid]

    # Se o host saiu, elege um novo host (lógica simples)
    if sid == server_state["host_sid"]:
        if server_state["users"]:
            new_host_sid = list(server_state["users"].keys())[0]
            server_state["host_sid"] = new_host_sid
            await sio.emit('set_host', to=new_host_sid)
        else:
            server_state["host_sid"] = None  # Sala vazia

    # Atualiza a lista de usuários para todos
    await sio.emit('update_users', server_state["users"])


@sio.event
async def send_message(sid, message_text):
    user_info = server_state["users"].get(sid, {"name": "Guest"})
    message_data = {
        "sender": user_info.get("name", "Guest"),
        "pfp": user_info.get("pfp", ""),
        "text": message_text  # Lembre-se de sanitizar HTML em produção
    }
    await sio.emit('new_message', message_data)


# --- Eventos de Sincronização (Apenas Host) ---

@sio.on("host_set_video")
async def set_video(sid, video_name):
    print(f"Host ou painel de host definiu o vídeo para: {video_name}")
    server_state["current_video"] = video_name
    server_state["current_time"] = 0
    server_state["is_paused"] = True

    # Envia evento para TODOS (incluindo o host)
    await sio.emit('sync_event', {
        "type": "set_video",
        "video": video_name
    })


@sio.on("host_sync")
async def host_sync_event(sid, data):
    # data = {"type": "play" | "pause" | "seek", "time": 123.45}
    if sid != server_state["host_sid"]:
        return  # Ignora se não for o host

    # Atualiza estado do servidor
    if data["type"] == "play":
        server_state["is_paused"] = False
    elif data["type"] == "pause":
        server_state["is_paused"] = True

    if "time" in data:
        server_state["current_time"] = data["time"]

    # Transmite o evento para todos, *exceto* o host que enviou
    await sio.emit('sync_event', data, skip_sid=sid)


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
        # Usa sio.call para pedir o tempo atual diretamente ao host.
        # Isso espera (await) uma resposta do cliente host.
        # O timeout evita que o servidor fique travado se o host não responder.
        host_state = await sio.call('get_host_time', to=host_sid, timeout=2)

        # Atualiza o estado do servidor com a informação mais recente
        server_state["current_time"] = host_state["time"]
        server_state["is_paused"] = host_state["paused"]

        # Envia o estado "fresco" de volta para o cliente que solicitou
        await sio.emit('force_sync', host_state, to=sid)

    except Exception as e:
        # Pode ocorrer um TimeoutError se o host não responder a tempo.
        print(f"Não foi possível obter o tempo do host ({host_sid}): {e}")
