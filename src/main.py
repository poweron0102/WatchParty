import uvicorn

from config import BIND_HOST, MEDIA_SOURCES, PORT
from server_setup import socket_app
import http_routes  # noqa: F401,E402
import socket_events  # noqa: F401,E402


if __name__ == "__main__":
    print("--- Watch Party Server Iniciando ---")
    print(f"Configurações: Porta={PORT}, Origens={len(MEDIA_SOURCES.summaries)}")
    print(f"Para configurar, acesse: http://localhost:{PORT}/host")
    uvicorn.run(socket_app, host=BIND_HOST, port=PORT, log_level="error")
