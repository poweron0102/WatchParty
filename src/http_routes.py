import os
import mimetypes
import fastapi
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse
from starlette.requests import Request
from src.config import FILES_DIR, CACHE_DIR, VIDEO_DIR, PORT
from src.server_setup import app
from src.utils import get_public_ip


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


# 3. Endpoint de Streaming de Vídeo
@app.get("/video/{video_name}")
async def stream_video(video_name: str, request: Request):
    video_path = os.path.join(VIDEO_DIR, video_name)
    if not os.path.exists(video_path):
        return JSONResponse(status_code=404, content={"message": "Video não encontrado"})

    media_type, _ = mimetypes.guess_type(video_path)
    return FileResponse(
        video_path,
        media_type=media_type or "video/mp4",
        headers={"Accept-Ranges": "bytes"}
    )


# 4. Endpoints de API

@app.post("/api/upload_pfp")
async def upload_pfp(file: fastapi.UploadFile):
    file_path = os.path.join(CACHE_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())
    return {"url": f"/{CACHE_DIR}/{file.filename}"}


@app.get("/api/get_videos")
async def list_videos():
    try:
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
    link = f"http://[{ip}]:{PORT}/" if ":" in ip else f"http://{ip}:{PORT}/"
    return {"ip": ip, "link": link}


app.mount(f"/{CACHE_DIR}", StaticFiles(directory=CACHE_DIR), name="cache")
app.mount("/", StaticFiles(directory=FILES_DIR, html=True), name="static")

