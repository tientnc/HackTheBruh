"""Thin async client over Polymarket's public APIs (no auth required)."""

import json
import time
from typing import Any

import httpx

from app.config import Settings


class PolymarketClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": "HackTheBruh/0.1"},
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        resp = await self.http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # --- health -----------------------------------------------------------

    async def ping(self) -> dict[str, dict[str, Any]]:
        """Hit a cheap endpoint on each upstream service and report latency."""
        s = self.settings
        targets = {
            "gamma": (f"{s.gamma_api_url}/markets", {"limit": 1}),
            "clob": (f"{s.clob_api_url}/ok", None),
            "data": (f"{s.data_api_url}/trades", {"limit": 1}),
        }
        results: dict[str, dict[str, Any]] = {}
        for name, (url, params) in targets.items():
            start = time.perf_counter()
            try:
                resp = await self.http.get(url, params=params)
                results[name] = {
                    "ok": resp.is_success,
                    "status_code": resp.status_code,
                    "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                }
            except httpx.HTTPError as exc:
                results[name] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                }
        return results

    # --- markets (Gamma API) ----------------------------------------------

    async def list_markets(
        self,
        limit: int = 20,
        offset: int = 0,
        active: bool | None = True,
        closed: bool | None = False,
        order: str | None = "volumeNum",
        ascending: bool = False,
    ) -> list[dict[str, Any]]:
        params = {
            "limit": limit,
            "offset": offset,
            "active": _bool(active),
            "closed": _bool(closed),
            "order": order,
            "ascending": _bool(ascending),
        }
        markets = await self._get(f"{self.settings.gamma_api_url}/markets", params)
        return [normalize_market(m) for m in markets]

    async def get_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        markets = await self._get(
            f"{self.settings.gamma_api_url}/markets", {"slug": slug}
        )
        return normalize_market(markets[0]) if markets else None

    # --- trades (Data API v2) ---------------------------------------------

    async def get_trades(
        self,
        condition_id: str | None = None,
        user: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Returns {"data": [...trades], "pagination": {..., "next_cursor"}}."""
        params = {
            "condition": condition_id,
            "user": user,
            "limit": limit,
            "cursor": cursor,
        }
        return await self._get(f"{self.settings.data_api_url}/trades", params)


def _bool(v: bool | None) -> str | None:
    return None if v is None else str(v).lower()


def normalize_market(m: dict[str, Any]) -> dict[str, Any]:
    """Gamma returns some list fields as JSON-encoded strings; decode them."""
    out = dict(m)
    for key in ("outcomes", "outcomePrices", "clobTokenIds"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except json.JSONDecodeError:
                pass
    return out
