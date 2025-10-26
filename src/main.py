import uvicorn

from src.config import PORT, VIDEO_DIR
from src.server_setup import socket_app
import src.http_routes                     # Importante para importar as rotas
import src.socket_events                   # Importante para importar as rotas


if __name__ == "__main__":
    print("--- Watch Party Server Iniciando ---")
    print(f"Configurações: Porta={PORT}, Diretório de Vídeos={VIDEO_DIR}")
    print(f"Para configurar, acesse: http://localhost:{PORT}/host")

    uvicorn.run(socket_app, host="::", port=PORT)
