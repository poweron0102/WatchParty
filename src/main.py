import uvicorn
import asyncio
from config import PORT, VIDEO_DIR
from server_setup import socket_app
from dns_manager import start_dns_updater
import http_routes                     # Importante para importar as rotas
import socket_events                   # Importante para importar as rotas
from src.config import USE_CLOUDFLARE



if __name__ == "__main__":
    print("--- Watch Party Server Iniciando ---")
    print(f"Configurações: Porta={PORT}, Diretório de Vídeos={VIDEO_DIR}")
    print(f"Para configurar, acesse: http://localhost:{PORT}/host")

    uvicorn.run(socket_app, host="::", port=PORT, log_level="error")