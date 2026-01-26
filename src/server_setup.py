import asyncio
from contextlib import asynccontextmanager

import fastapi
import socketio


@asynccontextmanager
async def lifespan(_):
    from src.config import USE_CLOUDFLARE
    from src.dns_manager import start_dns_updater

    if USE_CLOUDFLARE:
        asyncio.create_task(start_dns_updater())
    yield

app = fastapi.FastAPI(lifespan=lifespan)
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
