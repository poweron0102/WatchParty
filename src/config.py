import json
import os

from media_sources import InvalidSourceConfiguration, build_source_registry
from rtc_config import DEFAULT_ICE_SERVERS, normalize_ice_servers, split_ice_servers

os.makedirs("files", exist_ok=True)
os.makedirs("cache", exist_ok=True)
SAVE_FILE, CLOUDFLARE_FILE, CACHE_DIR, FILES_DIR = "save.json", "cloudflare.json", "cache", "files"
DEFAULT_PLAYBACK = {
    "buffer_ahead_seconds": 30, "buffer_behind_seconds": 30,
    "segment_wait_timeout_seconds": 30, "soft_sync_drift_seconds": 0.25,
    "hard_sync_drift_seconds": 2.0, "inactive_playback_grace_seconds": 0,
}
defaults = {"port": 8000, "use_cloudflare": False, "ice_servers": DEFAULT_ICE_SERVERS,
            "playback": DEFAULT_PLAYBACK, "sources": []}
config = dict(defaults)
if os.path.exists(SAVE_FILE):
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as stream:
            loaded = json.load(stream)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Não foi possível ler {SAVE_FILE}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{SAVE_FILE} deve conter um objeto JSON")
    config.update(loaded)
else:
    with open(SAVE_FILE, "w", encoding="utf-8") as stream:
        json.dump(defaults, stream, ensure_ascii=False, indent=4)

PORT = int(os.getenv("WATCHPARTY_PORT", config["port"]))
BIND_HOST = os.getenv("WATCHPARTY_BIND_HOST", "::").strip() or "::"
USE_CLOUDFLARE = bool(config.get("use_cloudflare", False))
PLAYBACK_CONFIG = dict(DEFAULT_PLAYBACK)
raw_playback = config.get("playback", {})
if not isinstance(raw_playback, dict) or set(raw_playback) - set(DEFAULT_PLAYBACK):
    raise RuntimeError("Configuração playback inválida")
PLAYBACK_CONFIG.update(raw_playback)
for key, value in PLAYBACK_CONFIG.items():
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or (key != "inactive_playback_grace_seconds" and value == 0):
        raise RuntimeError(f"Configuração playback inválida em {key}")
if PLAYBACK_CONFIG["inactive_playback_grace_seconds"] != 0:
    raise RuntimeError("inactive_playback_grace_seconds deve ser zero neste ciclo")
ICE_SERVERS = normalize_ice_servers(config.get("ice_servers"))
try:
    MEDIA_SOURCES = build_source_registry(config.get("sources"))
except InvalidSourceConfiguration as exc:
    raise RuntimeError(f"Configuração de origens inválida em {SAVE_FILE}: {exc}") from exc

TURN_HOST = os.getenv("TURN_HOST", "").strip()
TURN_REALM = os.getenv("TURN_REALM", TURN_HOST or "watchparty").strip()
TURN_SECRET = os.getenv("TURN_SECRET", "").strip()
TURN_PORT = int(os.getenv("TURN_PORT", "3478"))
TURN_CREDENTIAL_TTL = int(os.getenv("TURN_CREDENTIAL_TTL", "86400"))
_, CONFIGURED_TURN_SERVERS = split_ice_servers(ICE_SERVERS)
TURN_CONFIGURED = bool(CONFIGURED_TURN_SERVERS or (TURN_HOST and TURN_SECRET))

cloudflare_conf = {"api_token": "SEU_TOKEN_AQUI", "zone_id": "SEU_ZONE_ID_AQUI", "record_name": "subdominio.seusite.com", "proxied": True, "check_interval": 120}
if USE_CLOUDFLARE and os.path.exists(CLOUDFLARE_FILE):
    try:
        with open(CLOUDFLARE_FILE, "r", encoding="utf-8") as stream:
            cloudflare_conf.update(json.load(stream))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Aviso: não foi possível ler {CLOUDFLARE_FILE}: {exc}")
CF_API_TOKEN = cloudflare_conf.get("api_token")
CF_ZONE_ID = cloudflare_conf.get("zone_id")
CF_RECORD_NAME = cloudflare_conf.get("record_name")
CF_PROXIED = cloudflare_conf.get("proxied", True)
CF_INTERVAL = cloudflare_conf.get("check_interval", 300)
