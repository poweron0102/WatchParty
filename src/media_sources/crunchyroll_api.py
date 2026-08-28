from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .errors import SourceUnavailable


class CrunchyrollApi:
    """Small authenticated catalog client. Credentials and tokens remain memory-only."""
    BASE = "https://beta-api.crunchyroll.com"

    def __init__(self, etp_rt: str, locale: str, transport: httpx.AsyncBaseTransport | None = None):
        self._cookie, self.locale = etp_rt, locale
        self._client = httpx.AsyncClient(base_url=self.BASE, transport=transport, timeout=20,
                                         headers={"User-Agent": "WatchParty/1"})
        self._token: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def close(self): await self._client.aclose()

    async def _authenticate(self):
        async with self._lock:
            if self._token and time.monotonic() < self._expires - 30: return
            try:
                response = await self._client.post("/auth/v1/token", data={"grant_type": "etp_rt_cookie"},
                    cookies={"etp_rt": self._cookie}, headers={"Authorization": "Basic Y3Jfd2ViOg=="})
                response.raise_for_status(); payload = response.json()
                self._token = payload["access_token"]; self._expires = time.monotonic() + int(payload.get("expires_in", 300))
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise SourceUnavailable("autenticação do catálogo indisponível") from exc

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._authenticate()
        query = {"locale": self.locale, **(params or {})}
        for attempt in range(3):
            try:
                response = await self._client.get(path, params=query, headers={"Authorization": f"Bearer {self._token}"})
                if response.status_code == 401 and attempt == 0:
                    self._expires = 0; await self._authenticate(); continue
                if response.status_code in (420, 429):
                    await asyncio.sleep(min(float(response.headers.get("Retry-After", 1)), 5)); continue
                response.raise_for_status(); return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                if attempt == 2: raise SourceUnavailable("catálogo temporariamente indisponível") from exc
                await asyncio.sleep(0.25 * (2 ** attempt))
        raise SourceUnavailable("catálogo temporariamente indisponível")
