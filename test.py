# Alya: 31131295
# Get all movies from Alya hides her feelings in russian
import io
import random
from typing import Literal

import requests
from bs4 import BeautifulSoup
from imdb import Cinemagoer
from PIL import Image

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}


def _get_high_res_imdb_url(url: str) -> str:
    """
    Converte uma URL de thumbnail do IMDb para sua versão de alta resolução.
    Ex: https://.../MV5BM...@@._V1_..._.jpg -> https://.../MV5BM...@@.jpg
    """
    if url and "@@" in url:
        base_url = url.split("@@")[0]
        return base_url + "@@._V1_.jpg"
    return url


def _get_image_by_ratio(
    image_urls: list[str],
    ratio: Literal["H", "V", "A"] = "A"
) -> tuple[str, ] | None:
    """
    Filtra uma lista de URLs de imagem pela proporção e retorna uma aleatoriamente.

    Args:
        image_urls: A lista de URLs de imagem para filtrar.
        ratio: A proporção desejada. 'H' para horizontal (largura > altura),
               'V' para vertical (altura > largura), 'A' para qualquer uma.

    Returns:
        Uma única URL de imagem que corresponde ao ratio, ou None se nenhuma for encontrada.
    """
    if not image_urls:
        return None

    if ratio == "A":
        return random.choice(image_urls)

    matching_images = []
    for url in image_urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            # Abre a imagem da memória para obter as dimensões
            image_file = io.BytesIO(response.content)
            with Image.open(image_file) as img:
                width, height = img.size

            # Verifica se a proporção corresponde
            is_horizontal = width > height
            if (ratio == "H" and is_horizontal) or (ratio == "V" and not is_horizontal):
                matching_images.append(url)

        except requests.RequestException as e:
            print(f"Erro ao baixar a imagem {url}: {e}")
        except Exception as e:
            print(f"Erro ao processar a imagem {url}: {e}")

    if not matching_images:
        print(f"Nenhuma imagem com ratio '{ratio}' encontrada. Retornando uma imagem aleatória como fallback.")
        return random.choice(image_urls)

    return random.choice(matching_images)


ResultCache: dict[int, list[str]] = {}
def _fetch_imdb_preview_image_url(title: str) -> str | None:
    """
    Busca um título no IMDb, faz scraping da página e retorna a URL de uma
    imagem de pré-visualização retangular aleatória.
    Ratio = H=Horizontal V=Vertical A=Any
    """
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

    #https://www.imdb.com/pt/title/tt31131295/mediaviewer/
    #f"https://www.imdb.com/title/tt{first_result_id}/"
    #rm3324408065-curr
    #rm3324408065/
    #data-image-id="rm1291818754-prev"
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

    print("======" * 10)
    print(ResultCache[first_result_id])
    return random.choice(ResultCache[first_result_id])


def test() -> str | None:
    """
    Busca um título no IMDb, faz scraping da página do resultado principal
    e retorna a URL do pôster em alta resolução.
    """

    first_result_id = 31131295
    movie_page_url = f"https://www.imdb.com/title/tt{first_result_id}/"

    response = requests.get(movie_page_url, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    image_tag = soup.select_one('div[data-testid="hero-media__poster"] img')
    print(f"Img tag encontrada: {image_tag}")
    if image_tag and image_tag.get('srcset'):
        return _get_high_res_imdb_url(image_tag['src'])
    return None


if __name__ == "__main__":
    print("======" * 10)
    #print(_fetch_imdb_preview_image_url("Alya hides her feelings in russian"))
    print(test())

