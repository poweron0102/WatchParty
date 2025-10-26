# /src/config.py

import os
import json

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
    print(f"Aviso: Diretório de vídeos '{VIDEO_DIR}' não encontrado. Saindo...")
    #os.makedirs(VIDEO_DIR, exist_ok=True)
    exit(1)
