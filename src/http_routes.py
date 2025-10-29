import os
import mimetypes
import fastapi
import hashlib
import cv2
import random
import requests
from bs4 import BeautifulSoup
from imdb import Cinemagoer
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse
from starlette.requests import Request
from config import FILES_DIR, CACHE_DIR, VIDEO_DIR, PORT, AUTO_SCRAPE
from server_setup import app
from utils import get_public_ip

def _get_high_res_imdb_url(url: str) -> str:
    """
    Converte uma URL de thumbnail do IMDb para sua versão de alta resolução.
    Ex: https://.../MV5BM...@@._V1_..._.jpg -> https://.../MV5BM...@@.jpg
    """
    if url and "@@" in url:
        base_url = url.split("@@")[0]
        return base_url + "@@._V1_.jpg"
    return url

def _fetch_imdb_poster_url(title: str) -> str | None:
    """
    Busca um título no IMDb, faz scraping da página do resultado principal
    e retorna a URL do pôster em alta resolução.
    """
    print(f"Buscando imagem no IMDb para '{title}'...")
    ia = Cinemagoer()
    movies = ia.search_movie(title)

    if not movies:
        print(f"Nenhum resultado encontrado no IMDb para '{title}'.")
        return None

    first_result_id = movies[0].movieID
    movie_page_url = f"https://www.imdb.com/title/tt{first_result_id}/"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    response = requests.get(movie_page_url, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    image_tag = soup.select_one('div[data-testid="hero-media__poster"] img')
    if image_tag:
        # Prioriza o srcset para obter a melhor resolução
        if image_tag.get('srcset'):
            srcset = image_tag['srcset']
            # url1 1000w, url2 1500w, ...
            sources = [s.strip() for s in srcset.split(',')]

            valid_sources = []
            link: str = ""
            size: int = 0

            for name in sources:
                if name.startswith("https://"):
                    link = name
                    continue
                elif name.endswith("w"):
                    size = int(name[name.find(" "):-1])
                    valid_sources.append((link, size))

            best_source_url = max(valid_sources, key=lambda item: item[1])[0]
            return _get_high_res_imdb_url(best_source_url)

        if image_tag.get('src'):
            return _get_high_res_imdb_url(image_tag['src'])
    return None


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

@app.post("/api/upload_image")
async def upload_image(file: fastapi.UploadFile):
    contents = await file.read()

    file_hash = hashlib.sha256(contents).hexdigest()
    _, ext = os.path.splitext(file.filename or "")

    hashed_filename = f"{file_hash}{ext}"
    dest_path = os.path.join(CACHE_DIR, hashed_filename)

    os.makedirs(CACHE_DIR, exist_ok=True)
    
    if not os.path.exists(dest_path):
        with open(dest_path, "wb") as buffer:
            buffer.write(contents)
        print(f"Imagem salva em {dest_path}")
        
    return {"url": f"/{CACHE_DIR}/{hashed_filename}"}


@app.get("/api/get_videos")
async def list_videos(path: str = ""):
    # Sanitize and validate path
    current_path = os.path.abspath(os.path.join(VIDEO_DIR, path))
    if not current_path.startswith(os.path.abspath(VIDEO_DIR)) or not os.path.isdir(current_path):
        return JSONResponse(status_code=404, content={"message": "Caminho não encontrado"})

    try:
        items = []
        # Ignora arquivos/pastas que começam com '.'
        dir_items = [item for item in os.listdir(current_path) if not item.startswith('.')]

        for item_name in sorted(dir_items):
            item_path = os.path.join(current_path, item_name)
            relative_item_path = os.path.join(path, item_name)

            if os.path.isdir(item_path):
                items.append({"name": item_name, "type": "folder", "path": relative_item_path})
            elif item_name.lower().endswith((".mp4", ".mkv", ".webm", ".avi")):
                items.append({"name": item_name, "type": "video", "path": relative_item_path})

        return {"items": items}
    except FileNotFoundError:
        return JSONResponse(status_code=500, content={"message": f"Diretório de vídeo não encontrado: {VIDEO_DIR}"})


@app.get("/api/get_subtitles/{video_path:path}")
async def get_subtitles(video_path: str):
    """
    Encontra os arquivos de legenda (.vtt) para um determinado vídeo.
    """
    # Sanitize and validate path
    full_video_path = os.path.abspath(os.path.join(VIDEO_DIR, video_path))
    if not full_video_path.startswith(os.path.abspath(VIDEO_DIR)) or not os.path.isfile(full_video_path):
        return JSONResponse(status_code=404, content={"message": "Vídeo não encontrado"})

    video_dir = os.path.dirname(full_video_path)
    subs_dir = os.path.join(video_dir, ".subs")

    if not os.path.isdir(subs_dir):
        return {"subtitles": []}

    video_base_name = os.path.splitext(os.path.basename(full_video_path))[0]
    subtitles = []
    for filename in os.listdir(subs_dir):
        # Garante que o arquivo de legenda pertence ao vídeo solicitado
        if filename.lower().endswith(".vtt") and filename.startswith(video_base_name):
            # O nome do arquivo é algo como: "NomeVideo.track_0.pt.vtt"
            parts = os.path.splitext(filename)[0].split('.')
            lang_code = "pt"  # Default
            if len(parts) > 2:
                lang_code = parts[-1] if len(parts[-1]) == 2 else parts[-2]

            # O Plyr precisa de um caminho relativo que o servidor entenda.
            # Usaremos o mount '/videos' que aponta para VIDEO_DIR.
            relative_video_dir = os.path.dirname(video_path)
            subtitle_src = os.path.join("/videos", relative_video_dir, ".subs", filename).replace("\\", "/")

            subtitles.append({"lang": lang_code, "label": lang_code.upper(), "src": subtitle_src})

    for s in subtitles: print(s)
    return {"subtitles": subtitles}


@app.get("/api/get_ip")
async def get_ip_address():
    ip = get_public_ip()
    link = f"http://[{ip}]:{PORT}/" if ":" in ip else f"http://{ip}:{PORT}/"
    return {"ip": ip, "link": link}


@app.post("/api/update_banners")
async def update_banners():
    """
    Percorre recursivamente o diretório de vídeos, buscando pôsteres para pastas (séries)
    e gerando thumbnails para arquivos de vídeo.
    Salva as imagens em uma subpasta '.previews'.
    """
    updated_banners = []

    for root, dirs, files in os.walk(VIDEO_DIR):
        # Ignora pastas .previews e outras pastas ocultas
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        # 1. Processa pastas (para séries/temporadas)
        # Apenas processa a pasta se ela não for a raiz de vídeos
        if root != VIDEO_DIR:
            dir_name = os.path.basename(root)
            preview_dir = os.path.join(root, ".previews")
            banner_path = os.path.join(preview_dir, "banner.png")

            if not os.path.exists(banner_path):
                os.makedirs(preview_dir, exist_ok=True)
                image_url = _fetch_imdb_poster_url(dir_name)
                if image_url:
                    try:
                        image_response = requests.get(image_url)
                        image_response.raise_for_status()
                        with open(banner_path, "wb") as f:
                            f.write(image_response.content)
                        updated_banners.append(dir_name)
                    except Exception as e:
                        print(f"Erro ao baixar o banner para {dir_name}: {e}")

        # 2. Processa arquivos de vídeo
        for filename in files:
            if not filename.lower().endswith((".mp4", ".mkv", ".webm", ".avi")):
                continue

            base_name, _ = os.path.splitext(filename)
            video_path = os.path.join(root, filename)
            preview_dir = os.path.join(root, ".previews")
            banner_path = os.path.join(preview_dir, f"{base_name}_banner.png")

            if os.path.exists(banner_path):
                continue

            os.makedirs(preview_dir, exist_ok=True)
            try:
                print(f"Gerando thumbnail para o vídeo '{filename}'...")
                cap = cv2.VideoCapture(video_path)
                if not cap.isOpened():
                    print(f"Erro ao abrir o vídeo {filename}")
                    continue

                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                # Captura um frame entre 10% e 70% do vídeo
                random_frame_number = random.randint(int(total_frames * 0.1), int(total_frames * 0.7))
                cap.set(cv2.CAP_PROP_POS_FRAMES, random_frame_number)

                success, frame = cap.read()
                if success:
                    cv2.imwrite(banner_path, frame)
                    updated_banners.append(base_name)
                cap.release()
            except Exception as e:
                print(f"Erro ao gerar thumbnail para {base_name}: {e}")

    return {"message": f"Banners atualizados para: {', '.join(updated_banners)}"}


@app.get('/api/scrape_banner')
async def scrape_banner(title: str = ""):
    if not title:
        return JSONResponse(status_code=400, content={"error": "Título não fornecido"})
    if not AUTO_SCRAPE:
        return JSONResponse(status_code=400, content={"error": "Servidor não configurado para o modo auto"})

    image_url = _fetch_imdb_poster_url(title)

    if image_url:
        return {"imageUrl": image_url}
    else:
        # Retorna None no corpo, mas com status 200, pois a busca ocorreu sem erros, apenas não encontrou resultado.
        return {"imageUrl": None}


app.mount(f"/{CACHE_DIR}", StaticFiles(directory=CACHE_DIR), name="cache")
app.mount("/videos", StaticFiles(directory=VIDEO_DIR), name="videos") # Para servir os banners
app.mount("/", StaticFiles(directory=FILES_DIR, html=True), name="static")
