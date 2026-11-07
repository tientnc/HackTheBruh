"""Small read-only client for Gamma and Data API v2; no credentials needed."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"


class ApiError(RuntimeError):
    pass


class Client:
    def __init__(self, timeout=30, retries=3):
        self.timeout = timeout
        self.retries = retries

    def get(self, base, path, **params):
        query = {k: str(v).lower() if isinstance(v, bool) else v
                 for k, v in params.items() if v is not None}
        url = f"{base}{path}?{urlencode(query)}"
        request = Request(url, headers={
            "User-Agent": "HackTheBruh/0.1 (public-data research)",
            "Accept": "application/json",
        })
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as error:
                detail = error.read(500).decode("utf-8", errors="replace")
                if error.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise ApiError(f"HTTP {error.code}: {url}\n{detail}") from error
                try:
                    delay = float(error.headers.get("Retry-After", 2 ** attempt))
                except (TypeError, ValueError):
                    delay = 2 ** attempt
                # Never retry earlier than requested. Long waits are left to the caller.
                if delay > 30:
                    raise ApiError(f"Server requests a {delay:g}s pause; retry later: {url}") from error
                time.sleep(max(0, delay))
            except (URLError, TimeoutError) as error:
                if attempt == self.retries:
                    raise ApiError(f"Cannot reach {url}: {error}") from error
                time.sleep(2 ** attempt)
            except json.JSONDecodeError as error:
                raise ApiError(f"Invalid JSON from {url}") from error


def pages(client, path, params, max_pages=20):
    """Keep filters identical on cursor resumes; retain raw rows, including repeats.

    API rows do not expose a universal fill ID. Deduplicating by transaction hash
    or by identical fields can accidentally erase legitimate fills.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    rows, raw, seen = [], [], set()
    query = dict(params)
    for _ in range(max_pages):
        page = client.get(DATA, path, **query)
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise ApiError(f"Unexpected page schema for {path}")
        pagination = page.get("pagination", {})
        if "has_more" not in pagination or "next_cursor" not in pagination:
            raise ApiError(f"Missing pagination fields for {path}")
        raw.append(page)
        rows.extend(page["data"])
        cursor = pagination["next_cursor"]
        if not pagination["has_more"]:
            if cursor is not None:
                raise ApiError(f"Contradictory pagination for {path}")
            return rows, raw, True
        if not cursor or cursor in seen:
            raise ApiError(f"Missing or repeated cursor for {path}")
        seen.add(cursor)
        query["cursor"] = cursor
    return rows, raw, False
