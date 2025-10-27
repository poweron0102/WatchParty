import os
import mimetypes
import fastapi
import random
import requests
from bs4 import BeautifulSoup
from imdb import Cinemagoer
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse
from starlette.requests import Request
from src.config import FILES_DIR, CACHE_DIR, VIDEO_DIR, PORT, AUTO_SCRAPE
from src.server_setup import app
from src.utils import get_public_ip

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
    try:
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
        if image_tag and image_tag.get('src'):
            return _get_high_res_imdb_url(image_tag['src'])
    except Exception as e:
        print(f"Erro ao buscar pôster para '{title}': {e}")
    return None


ResultCache: dict[int, list[str]] = {}
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
def _fetch_imdb_preview_image_url(title: str) -> str | None:
    """
    Busca um título no IMDb, faz scraping da página e retorna a URL de uma
    imagem de pré-visualização retangular aleatória.
    """
    try:
        print(f"Buscando imagem de pré-visualização no IMDb para '{title}'...")
        ia = Cinemagoer()
        movies = ia.search_movie(title)

        if not movies:
            print(f"Nenhum resultado encontrado no IMDb para '{title}'.")
            return None

        first_result_id = movies[0].movieID
        if first_result_id in ResultCache:
            return random.choice(ResultCache[first_result_id])

        ResultCache[first_result_id] = []
        movie_page_url = f"https://www.imdb.com/pt/title/tt{first_result_id}/mediaviewer/"

        img_ids: set[str] = set()
        while len(img_ids) < 30:
            print(movie_page_url)
            response = requests.get(movie_page_url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            image_tags = soup.select('img[src][data-image-id]')
            next_img_id: str = None

            if image_tags:
                for tag in image_tags:
                    image_id = tag.get("data-image-id")
                    if "curr" in image_id.split('-'):
                        img_ids.add(image_id.split('-')[0])
                        ResultCache[first_result_id].append(_get_high_res_imdb_url(tag['src']))
                    else:
                        img_id = image_id.split('-')[0]
                        if img_id not in img_ids:
                            next_img_id = img_id
                            break

            if next_img_id:
                movie_page_url = f"https://www.imdb.com/pt/title/tt{first_result_id}/mediaviewer/{next_img_id}/"
            else:
                break
        return random.choice(ResultCache[first_result_id])
    except Exception as e:
        print(f"Erro ao buscar imagem de pré-visualização para '{title}': {e}")
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
    filename = os.path.basename(file.filename or "upload")
    name, ext = os.path.splitext(filename)
    saved_filename = filename
    dest_path = os.path.join(CACHE_DIR, saved_filename)
    i = 1
    while os.path.exists(dest_path):
        saved_filename = f"{name}_{i}{ext}"
        dest_path = os.path.join(CACHE_DIR, saved_filename)
        i += 1
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(dest_path, "wb") as buffer:
        buffer.write(await file.read())
    print(f"Imagem salva em {dest_path}")
    return {"url": f"/{CACHE_DIR}/{saved_filename}"}


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


@app.get("/api/get_ip")
async def get_ip_address():
    ip = get_public_ip()
    link = f"http://[{ip}]:{PORT}/" if ":" in ip else f"http://{ip}:{PORT}/"
    return {"ip": ip, "link": link}


@app.post("/api/update_banners")
async def update_banners():
    updated_banners = []
    # Ignora arquivos/pastas que começam com '.'
    dir_items = [item for item in os.listdir(VIDEO_DIR) if not item.startswith('.')]

    for item_name in dir_items:
        item_path = os.path.join(VIDEO_DIR, item_name)
        title_to_search = item_name

        if os.path.isdir(item_path):
            preview_dir = os.path.join(item_path, ".previews")
            banner_path = os.path.join(preview_dir, "banner.png")
            if os.path.exists(banner_path):
                #continue todo para apagar a bissarrice atual
                pass
            os.makedirs(preview_dir, exist_ok=True)
            image_url = _fetch_imdb_poster_url(title_to_search)

        elif os.path.isfile(item_path): # é um arquivo de vídeo
            base_name, ext = os.path.splitext(item_name)
            if ext.lower() not in [".mp4", ".mkv", ".webm", ".avi"]:
                #continue todo
                pass
            title_to_search = base_name
            preview_dir = os.path.join(VIDEO_DIR, ".previews")
            banner_path = os.path.join(preview_dir, f"{base_name}_banner.png")
            if os.path.exists(banner_path):
                continue
            os.makedirs(preview_dir, exist_ok=True)
            image_url = _fetch_imdb_preview_image_url(title_to_search)

        else:
            continue

        if image_url and banner_path:
            try:
                image_response = requests.get(image_url)
                image_response.raise_for_status()
                with open(banner_path, "wb") as f:
                    f.write(image_response.content)
                updated_banners.append(title_to_search)
            except Exception as e:
                print(f"Erro ao baixar o banner para {title_to_search}: {e}")

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
