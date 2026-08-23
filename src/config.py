# /src/config.py

import os
import json

from rtc_config import DEFAULT_ICE_SERVERS, normalize_ice_servers, split_ice_servers

# --- Configuração Inicial ---

# Garante que os diretórios existam
os.makedirs("files", exist_ok=True)
os.makedirs("cache", exist_ok=True)
os.makedirs("videos", exist_ok=True)  # Diretório padrão de vídeos

SAVE_FILE = "save.json"
CLOUDFLARE_FILE = "cloudflare.json"
CACHE_DIR = "cache"
FILES_DIR = "files"

# --- Configurações Gerais (save.json) ---
config = {
    "port": 8000,
    "video_dir": "videos",
    "use_cloudflare": False,
    "ice_servers": DEFAULT_ICE_SERVERS
}

if os.path.exists(SAVE_FILE):
    try:
        with open(SAVE_FILE, 'r') as f:
            config.update(json.load(f))
    except json.JSONDecodeError:
        print(f"Aviso: {SAVE_FILE} está corrompido. Usando padrões.")
else:
    with open(SAVE_FILE, 'w') as f:
        f.write(json.dumps({
            "port": 8000,
            "video_dir": "videos",
            "use_cloudflare": False,
            "ice_servers": DEFAULT_ICE_SERVERS
        }, indent=4))

PORT = int(os.getenv("WATCHPARTY_PORT", config["port"]))
BIND_HOST = os.getenv("WATCHPARTY_BIND_HOST", "::").strip() or "::"
VIDEO_DIR = os.getenv("WATCHPARTY_VIDEO_DIR", config["video_dir"])
USE_CLOUDFLARE = config.get("use_cloudflare", False)
ICE_SERVERS = normalize_ice_servers(config.get("ice_servers"))

TURN_HOST = os.getenv("TURN_HOST", "").strip()
TURN_REALM = os.getenv("TURN_REALM", TURN_HOST or "watchparty").strip()
TURN_SECRET = os.getenv("TURN_SECRET", "").strip()
TURN_PORT = int(os.getenv("TURN_PORT", "3478"))
TURN_CREDENTIAL_TTL = int(os.getenv("TURN_CREDENTIAL_TTL", "86400"))
_, CONFIGURED_TURN_SERVERS = split_ice_servers(ICE_SERVERS)
TURN_CONFIGURED = bool(CONFIGURED_TURN_SERVERS or (TURN_HOST and TURN_SECRET))

if not os.path.isdir(VIDEO_DIR):
    print(f"Aviso: Diretório de vídeos '{VIDEO_DIR}' não encontrado. O servidor pode falhar ao iniciar.")
    # exit(1) # Opcional: Impedir saída abrupta se quiser criar a pasta dinamicamente

# --- Configurações Cloudflare (cloudflare.json) ---
cloudflare_conf = {
    "api_token": "SEU_TOKEN_AQUI",
    "zone_id": "SEU_ZONE_ID_AQUI",
    "record_name": "subdominio.seusite.com",
    "proxied": True,
    "check_interval": 120  # Tempo em segundos
}

if USE_CLOUDFLARE:
    if os.path.exists(CLOUDFLARE_FILE):
        try:
            with open(CLOUDFLARE_FILE, 'r') as f:
                loaded_conf = json.load(f)
                cloudflare_conf.update(loaded_conf)
        except json.JSONDecodeError:
            print(f"Aviso: {CLOUDFLARE_FILE} está corrompido. Verifique a sintaxe.")
    else:
        print(f"Criando arquivo padrão {CLOUDFLARE_FILE}...")
        with open(CLOUDFLARE_FILE, 'w') as f:
            json.dump(cloudflare_conf, f, indent=4)

# Exporta variáveis da Cloudflare
CF_API_TOKEN = cloudflare_conf.get("api_token")
CF_ZONE_ID = cloudflare_conf.get("zone_id")
CF_RECORD_NAME = cloudflare_conf.get("record_name")
CF_PROXIED = cloudflare_conf.get("proxied", True)
CF_INTERVAL = cloudflare_conf.get("check_interval", 300)
