import os
import subprocess
import json
import sys

# Lista de extensões de vídeo comuns a serem verificadas
VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm'}


def find_subtitle_streams(video_path):
    """
    Usa o ffprobe para encontrar trilhas de legenda em um arquivo de vídeo.
    Retorna uma lista de dicionários, cada um representando uma trilha de legenda.
    """
    command = [
        'ffprobe',
        '-v', 'error',
        '-print_format', 'json',
        '-show_streams',
        video_path
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        streams = json.loads(result.stdout).get('streams', [])
        # Filtra apenas as trilhas de legenda (subtitle)
        return [s for s in streams if s.get('codec_type') == 'subtitle']
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"  [ERRO] Falha ao analisar o vídeo '{os.path.basename(video_path)}': {e}", file=sys.stderr)
        return []


def extract_subtitle(video_path, stream_index, output_path):
    """
    Usa o ffmpeg para extrair uma trilha de legenda específica para o formato VTT.
    """
    command = [
        'ffmpeg',
        '-i', video_path,
        '-map', f'0:s:{stream_index}',  # Mapeia a trilha de legenda pelo índice
        '-c:s', 'webvtt',  # Converte para o formato WebVTT
        '-y',  # Sobrescreve o arquivo de saída se ele já existir
        output_path
    ]
    try:
        # Usamos DEVNULL para não poluir o console com a saída do ffmpeg
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"    -> Legenda extraída para: {os.path.basename(output_path)}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [ERRO] Falha ao extrair legenda do vídeo '{os.path.basename(video_path)}': {e}", file=sys.stderr)
        return False


def process_videos_in_directory(root_dir):
    """
    Varre o diretório e subdiretórios em busca de vídeos e extrai suas legendas.
    """
    print(f"Iniciando busca por vídeos em: {os.path.abspath(root_dir)}\n")
    videos_found = 0
    subs_extracted = 0

    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            # Pega a extensão do arquivo e a converte para minúsculas
            file_ext = os.path.splitext(filename)[1].lower()

            if file_ext in VIDEO_EXTENSIONS:
                videos_found += 1
                video_path = os.path.join(dirpath, filename)
                print(f"Verificando vídeo: {filename}")

                subtitle_streams = find_subtitle_streams(video_path)

                if not subtitle_streams:
                    print("  - Nenhuma legenda embutida encontrada.")
                    continue

                print(f"  - Encontradas {len(subtitle_streams)} trilha(s) de legenda.")

                # Cria a pasta .subs no mesmo diretório do vídeo
                subs_dir = os.path.join(dirpath, '.subs')
                os.makedirs(subs_dir, exist_ok=True)

                # Extrai cada trilha de legenda encontrada
                for stream in subtitle_streams:
                    stream_index = stream['index']
                    # O ffprobe não fornece o índice relativo ao tipo de stream,
                    # então precisamos calcular.
                    subtitle_track_index = stream_index - sum(1 for s in subtitle_streams if s['index'] < stream_index)

                    lang = stream.get('tags', {}).get('language', 'und')  # 'und' para idioma indefinido
                    title = stream.get('tags', {}).get('title', '')

                    # Monta um nome de arquivo descritivo para a legenda
                    base_filename = os.path.splitext(filename)[0]
                    output_filename = f"{base_filename}.track_{subtitle_track_index}.{lang}"
                    if title:
                        # Remove caracteres inválidos para nomes de arquivo
                        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).rstrip()
                        output_filename += f".{safe_title}"
                    output_filename += ".vtt"

                    output_path = os.path.join(subs_dir, output_filename)

                    if extract_subtitle(video_path, subtitle_track_index, output_path):
                        subs_extracted += 1

    print("\n--- Resumo da Operação ---")
    print(f"Vídeos encontrados: {videos_found}")
    print(f"Arquivos de legenda (.vtt) extraídos: {subs_extracted}")
    print("--------------------------")


if __name__ == "__main__":
    # O script começa a busca a partir do diretório atual
    current_directory = '.'
    process_videos_in_directory(current_directory)
