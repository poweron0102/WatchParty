# /src/main.py

import uvicorn
import fastapi
import socketio
import os
import json
import requests
import mimetypes
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse
from starlette.requests import Request

# --- Configuração Inicial ---

# Garante que os diretórios existam
os.makedirs("files", exist_ok=True)
os.makedirs("cache", exist_ok=True)
os.makedirs("videos", exist_ok=True)  # Diretório padrão de vídeos

SAVE_FILE = "save.json"
CACHE_DIR = "cache"
FILES_DIR = "files"

# Carrega configurações ou usa padrões
config = {"port": 8000, "video_dir": "videos"}
if os.path.exists(SAVE_FILE):
    try:
        with open(SAVE_FILE, 'r') as f:
            config.update(json.load(f))
    except json.JSONDecodeError:
        print(f"Aviso: {SAVE_FILE} está corrompido. Usando padrões.")

PORT = config["port"]
VIDEO_DIR = config["video_dir"]
if not os.path.isdir(VIDEO_DIR):
    print(f"Aviso: Diretório de vídeos '{VIDEO_DIR}' não encontrado. Criando...")
    os.makedirs(VIDEO_DIR, exist_ok=True)

# --- Inicialização do App ---

app = fastapi.FastAPI()
# Configura o servidor Socket.IO (ASGI)
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
# Monta o app Socket.IO junto com o FastAPI
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

# --- Estado do Servidor (Simples) ---
# Para um app maior, você usaria salas (rooms)
server_state = {
    "current_video": None,
    "is_paused": True,
    "current_time": 0,
    "host_sid": None,
    "users": {}  # Formato: {sid: {"name": "...", "pfp": "..."}}
}


# --- Função de Descoberta de IP ---

def get_public_ip():
    """Tenta descobrir o IP público, priorizando IPv6."""
    try:
        # api64.ipify.org é um serviço que responde em IPv6
        response = requests.get('https://api64.ipify.org', timeout=3)
        if response.status_code == 200:
            return response.text
    except requests.RequestException:
        pass  # Falha ao tentar IPv6, tenta fallback

    try:
        # icanhazip.com pode retornar IPv4 ou IPv6
        response = requests.get('https://icanhazip.com', timeout=3)
        if response.status_code == 200:
            return response.text
    except requests.RequestException:
        return "127.0.0.1"  # Fallback final

    return "127.0.0.1"  # Fallback se ambos falharem


# --- Endpoints HTTP (FastAPI) ---

# 1. Servir páginas principais
@app.get("/")
async def get_index():
    return FileResponse(os.path.join(FILES_DIR, "index.html"))


@app.get("/party")
async def get_party():
    return FileResponse(os.path.join(FILES_DIR, "party.html"))


@app.get("/host")
async def get_host_page():
    return FileResponse(os.path.join(FILES_DIR, "host.html"))


# 2. Servir arquivos estáticos (JS, CSS, Imagens de perfil)
app.mount(f"/{FILES_DIR}", StaticFiles(directory=FILES_DIR), name="files")
app.mount(f"/{CACHE_DIR}", StaticFiles(directory=CACHE_DIR), name="cache")


# 3. Endpoint de Streaming de Vídeo
@app.get("/video/{video_name}")
async def stream_video(video_name: str, request: Request):
    video_path = os.path.join(VIDEO_DIR, video_name)
    if not os.path.exists(video_path):
        return JSONResponse(status_code=404, content={"message": "Video não encontrado"})

    # O FileResponse do FastAPI/Starlette lida nativamente
    # com 'Range' headers (Byte-Range Requests). Mágico!
    media_type, _ = mimetypes.guess_type(video_path)
    return FileResponse(
        video_path,
        media_type=media_type or "video/mp4",
        headers={"Accept-Ranges": "bytes"}
    )


# 4. Endpoints de API

@app.post("/api/upload_pfp")
async def upload_pfp(file: fastapi.UploadFile):
    # ATENÇÃO: Nomes de arquivo devem ser sanitizados em produção
    # Aqui usamos um nome simples para o exemplo.
    file_path = os.path.join(CACHE_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())
    return {"url": f"/{CACHE_DIR}/{file.filename}"}


@app.get("/api/get_videos")
async def list_videos():
    try:
        # Lista apenas arquivos de vídeo comuns
        videos = [
            f for f in os.listdir(VIDEO_DIR)
            if f.lower().endswith((".mp4", ".mkv", ".webm", ".avi"))
        ]
        return {"videos": videos}
    except FileNotFoundError:
        return JSONResponse(status_code=500, content={"message": f"Diretório de vídeo não encontrado: {VIDEO_DIR}"})


@app.get("/api/get_ip")
async def get_ip_address():
    ip = get_public_ip()
    # Formata o link corretamente para IPv6 (com colchetes)
    link = f"http://[{ip}]:{PORT}/" if ":" in ip else f"http://{ip}:{PORT}/"
    return {"ip": ip, "link": link}


# --- Eventos do Socket.IO (Chat e Sincronização) ---

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
    # Esta função agora é "confiável" e pode ser chamada pela página /host
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

# --- Execução ---

if __name__ == "__main__":
    print("--- Watch Party Server Iniciando ---")
    print(f"Configurações: Porta={PORT}, Diretório de Vídeos={VIDEO_DIR}")
    print(f"Para configurar, acesse: http://localhost:{PORT}/host")

    # Uvicorn rodando em '::' aceita conexões IPv4 (0.0.0.0) e IPv6
    # Isso é crucial para seu requisito de IPv6
    uvicorn.run(socket_app, host="::", port=PORT)