import os
import mimetypes
import fastapi
import requests
from imdb import Cinemagoer
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
@app.get("/video/{video_path:path}")
async def stream_video(video_path: str, request: Request):
    # Sanitize and validate path to prevent directory traversal
    full_video_path = os.path.abspath(os.path.join(VIDEO_DIR, video_path))
    if not full_video_path.startswith(os.path.abspath(VIDEO_DIR)):
        return JSONResponse(status_code=403, content={"message": "Acesso negado"})

    if not os.path.exists(full_video_path):
        return JSONResponse(status_code=404, content={"message": "Video não encontrado"})

    media_type, _ = mimetypes.guess_type(full_video_path)
    return FileResponse(
        full_video_path,
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
async def list_videos(path: str = ""):
    # Sanitize and validate path
    current_path = os.path.abspath(os.path.join(VIDEO_DIR, path))
    if not current_path.startswith(os.path.abspath(VIDEO_DIR)) or not os.path.isdir(current_path):
        return JSONResponse(status_code=404, content={"message": "Caminho não encontrado"})

    try:
        items = []
        for item_name in sorted(os.listdir(current_path)):
            item_path = os.path.join(current_path, item_name)
            relative_item_path = os.path.join(path, item_name)

            if os.path.isdir(item_path):
                items.append({"name": item_name, "type": "folder", "path": relative_item_path})
            elif item_name.lower().endswith((".mp4", ".mkv", ".webm", ".avi")):
                items.append({"name": item_name, "type": "video", "path": relative_item_path})
        
        return {"items": items}
    except FileNotFoundError:
        return JSONResponse(status_code=500, content={"message": f"Diretório de vídeo não encontrado: {VIDEO_DIR}"})


@app.get("/api/get_ip")
async def get_ip_address():
    ip = get_public_ip()
    link = f"http://[{ip}]:{PORT}/" if ":" in ip else f"http://{ip}:{PORT}/"
    return {"ip": ip, "link": link}


@app.post("/api/update_banners")
async def update_banners():
    ia = Cinemagoer()
    updated_banners = []
    for item_name in os.listdir(VIDEO_DIR):
        item_path = os.path.join(VIDEO_DIR, item_name)
        if os.path.isdir(item_path):
            try:
                movies = ia.search_movie(item_name)
                if movies:
                    movie_id = movies[0].movieID
                    movie = ia.get_movie(movie_id)
                    poster_url = movie.get('cover url')
                    if poster_url:
                        response = requests.get(poster_url)
                        if response.status_code == 200:
                            with open(os.path.join(item_path, "banner.png"), "wb") as f:
                                f.write(response.content)
                            updated_banners.append(item_name)
            except Exception as e:
                print(f"Erro ao processar {item_name}: {e}")
    return {"message": f"Banners atualizados para: {', '.join(updated_banners)}"}


app.mount(f"/{CACHE_DIR}", StaticFiles(directory=CACHE_DIR), name="cache")
app.mount("/videos", StaticFiles(directory=VIDEO_DIR), name="videos") # Para servir os banners
app.mount("/", StaticFiles(directory=FILES_DIR, html=True), name="static")
