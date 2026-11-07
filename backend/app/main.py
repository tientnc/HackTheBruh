from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request

from app.config import get_settings
from app.polymarket import PolymarketClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.polymarket = PolymarketClient(get_settings())
    yield
    await app.state.polymarket.close()


app = FastAPI(title="HackTheBruh API", version="0.1.0", lifespan=lifespan)


def get_client(request: Request) -> PolymarketClient:
    return request.app.state.polymarket


async def _upstream(coro):
    """Translate upstream failures into a 502 instead of a 500."""
    try:
        return await coro
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            502, f"Polymarket returned {exc.response.status_code}: {exc.response.text[:300]}"
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Polymarket unreachable: {exc}")


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness of this API itself."""
    return {"status": "ok"}


@app.get("/polymarket/ping")
async def polymarket_ping(client: PolymarketClient = Depends(get_client)) -> dict[str, Any]:
    """Check reachability and latency of each Polymarket upstream API."""
    services = await client.ping()
    return {"ok": all(s["ok"] for s in services.values()), "services": services}


@app.get("/markets")
async def list_markets(
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active: bool | None = True,
    closed: bool | None = False,
    order: str | None = Query("volumeNum", description="Gamma field to sort by: volumeNum, volume24hr, liquidityNum, endDate (use *Num fields; string fields sort lexically)"),
    ascending: bool = False,
    client: PolymarketClient = Depends(get_client),
) -> list[dict[str, Any]]:
    return await _upstream(
        client.list_markets(limit, offset, active, closed, order, ascending)
    )


@app.get("/markets/{slug}")
async def get_market(slug: str, client: PolymarketClient = Depends(get_client)) -> dict[str, Any]:
    market = await _upstream(client.get_market_by_slug(slug))
    if market is None:
        raise HTTPException(404, f"No market with slug '{slug}'")
    return market


@app.get("/trades")
async def get_trades(
    condition_id: str | None = Query(None, description="Market conditionId (0x...)"),
    user: str | None = Query(None, description="Wallet (proxy) address"),
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = Query(None, description="pagination.next_cursor from a previous call"),
    client: PolymarketClient = Depends(get_client),
) -> dict[str, Any]:
    """Wallet-level trades. Filter by market, by wallet, or neither (global feed)."""
    return await _upstream(client.get_trades(condition_id, user, limit, cursor))
