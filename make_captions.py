import os
import subprocess
import json
import sys

# Lista de extensões de vídeo comuns a serem verificadas
VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm'}


def find_media_streams(video_path):
    """
    Usa o ffprobe para encontrar trilhas de legenda e áudio em um arquivo de vídeo.
    Retorna uma lista de dicionários, cada um representando uma trilha.
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
        # Filtra apenas as trilhas de legenda (subtitle) e áudio (audio)
        return [s for s in streams if s.get('codec_type') in ['subtitle', 'audio']]
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


def extract_audio(video_path, stream_index, output_path):
    """
    Usa o ffmpeg para extrair uma trilha de áudio específica para o formato MP3.
    """
    command = [
        'ffmpeg',
        '-i', video_path,
        '-map', f'0:a:{stream_index}',  # Mapeia a trilha de áudio pelo índice relativo
        '-c:a', 'libmp3lame',  # Converte para o formato MP3
        '-q:a', '2',  # Qualidade do MP3 (0-9, menor é melhor)
        '-y',  # Sobrescreve o arquivo de saída se ele já existir
        output_path
    ]
    try:
        # Usamos DEVNULL para não poluir o console com a saída do ffmpeg
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"    -> Dublagem extraída para: {os.path.basename(output_path)}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [ERRO] Falha ao extrair áudio do vídeo '{os.path.basename(video_path)}': {e}", file=sys.stderr)
        return False


def process_videos_in_directory(root_dir):
    """
    Varre o diretório e subdiretórios em busca de vídeos e extrai suas legendas e dublagens.
    """
    print(f"Iniciando busca por vídeos em: {os.path.abspath(root_dir)}\n")
    videos_found = 0
    subs_extracted = 0
    dubs_extracted = 0

    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            # Pega a extensão do arquivo e a converte para minúsculas
            file_ext = os.path.splitext(filename)[1].lower()

            if file_ext not in VIDEO_EXTENSIONS:
                continue

            videos_found += 1
            video_path = os.path.join(dirpath, filename)
            print(f"Verificando vídeo: {filename}")

            all_streams = find_media_streams(video_path)
            subtitle_streams = [s for s in all_streams if s.get('codec_type') == 'subtitle']
            audio_streams = [s for s in all_streams if s.get('codec_type') == 'audio']

            if not subtitle_streams and len(audio_streams) <= 1:
                print("  - Nenhuma mídia extra (legendas ou dublagens) encontrada.")
                continue

            # --- Processa Legendas ---
            if subtitle_streams:
                print(f"  - Encontradas {len(subtitle_streams)} trilha(s) de legenda.")
                subs_dir = os.path.join(dirpath, '.subs')
                os.makedirs(subs_dir, exist_ok=True)

                for i, stream in enumerate(subtitle_streams):
                    lang = stream.get('tags', {}).get('language', 'und')
                    base_filename = os.path.splitext(filename)[0]
                    output_filename = f"{base_filename}.track_{i}.{lang}.vtt"
                    output_path = os.path.join(subs_dir, output_filename)

                    if extract_subtitle(video_path, i, output_path):
                        subs_extracted += 1

            # --- Processa Dublagens ---
            # Só extrai se houver mais de uma faixa de áudio (considerando que a primeira é a original)
            if len(audio_streams) > 1:
                print(f"  - Encontradas {len(audio_streams)} trilha(s) de áudio (possíveis dublagens).")
                dubs_dir = os.path.join(dirpath, '.dubs')
                os.makedirs(dubs_dir, exist_ok=True)

                for i, stream in enumerate(audio_streams):
                    lang = stream.get('tags', {}).get('language', 'und')
                    base_filename = os.path.splitext(filename)[0]
                    output_filename = f"{base_filename}.track_{i}.{lang}.mp3"
                    output_path = os.path.join(dubs_dir, output_filename)

                    if extract_audio(video_path, i, output_path):
                        dubs_extracted += 1

    print("\n--- Resumo da Operação ---")
    print(f"Vídeos encontrados: {videos_found}")
    print(f"Arquivos de legenda (.vtt) extraídos: {subs_extracted}")
    print(f"Arquivos de dublagem (.mp3) extraídos: {dubs_extracted}")
    print("--------------------------")


if __name__ == "__main__":
    # O script começa a busca a partir do diretório atual
    current_directory = '.'
    process_videos_in_directory(current_directory)
