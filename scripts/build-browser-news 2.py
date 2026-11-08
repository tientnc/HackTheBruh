"""Archive a small set of Google News headlines for each Lobby replay snapshot."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree


DATA = Path(__file__).resolve().parents[1] / "frontend" / "src" / "data"


def topic(question):
    title = re.sub(r"^Will\s+", "", question, flags=re.IGNORECASE).rstrip("?")
    for pattern, query in (
        (r"(\d+-year Treasury yield)", None),
        (r"Bank of (Mexico|Russia|Japan|England|Canada)", None),
        (r"Federal Reserve|\bFed\b|FOMC", '"Federal Reserve" interest rates'),
        (r"WTI Crude Oil", 'WTI crude oil futures'),
        (r"Gold \(", 'gold futures'),
        (r"Silver \(", 'silver futures'),
        (r"S&P 500", '"S&P 500"'),
        (r"Warner Bros", '"Warner Bros" acquisition'),
    ):
        if match := re.search(pattern, title, re.IGNORECASE):
            return query or f'"{match[0]}"'
    title = re.split(r"\s+(?:before|by|on|in)\s+(?:(?:end|the end) of\s+)?(?:\d{4}|January|February|March|April|May|June|July|August|September|October|November|December)\b", title, maxsplit=1)[0]
    if match := re.match(r"(.+?)(?:['’]s)?\s+(?:not\s+)?(?:market cap|valuation|IPO|be the (?:\S+-)?largest|hit|close|reach|dip|beat)\b", title):
        subject = re.split(r"\s+\(", match[1], maxsplit=1)[0].removesuffix("'s").removesuffix("’s")
        context = "IPO" if "IPO" in title else "valuation" if "valuation" in title else "stock"
        return f'"{subject}" {context}'
    return title


def fetch_headlines(key):
    query, cutoff = key
    first = cutoff - timedelta(days=7)
    url = "https://news.google.com/rss/search?" + urlencode({
        "q": f"{query} after:{first - timedelta(days=1)} before:{cutoff}",
        "hl": "en-US", "gl": "US", "ceid": "US:en",
    })
    try:
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as response:
            items = ElementTree.fromstring(response.read()).findall("./channel/item")
    except (OSError, ElementTree.ParseError):
        return None

    stories = []
    for item in items:
        try:
            day = parsedate_to_datetime(item.findtext("pubDate", "")).astimezone(timezone.utc).date()
        except (TypeError, ValueError):
            continue
        publisher = item.findtext("source", "")
        title = item.findtext("title", "").removesuffix(f" - {publisher}")
        link = item.findtext("link", "")
        parsed = urlsplit(link)
        if not (first <= day < cutoff and title and parsed.scheme == "https" and parsed.hostname == "news.google.com"):
            continue
        stories.append({"title": title, "publisher": publisher, "date": day.isoformat(), "url": link})

    selected = []
    seen = set()
    for story in sorted(stories, key=lambda story: story["date"], reverse=True):
        normalized = re.sub(r"\W+", " ", story["title"].lower()).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        selected.append(story)
        if len(selected) == 3:
            break
    return selected


def main():
    markets = json.loads((DATA / "markets.json").read_text(encoding="utf-8"))
    keys = {
        (market["id"], snapshot["snapshot_at"]): (
            topic(market["question"]), date.fromisoformat(snapshot["snapshot_at"][:10])
        )
        for market in markets for snapshot in market["snapshots"].values()
    }
    requests = sorted(set(keys.values()))
    with ThreadPoolExecutor(max_workers=6) as pool:
        feeds = dict(zip(requests, pool.map(fetch_headlines, requests)))
    archive = {}
    for (market, timestamp), key in keys.items():
        if feeds[key] is not None:
            archive.setdefault(market, {})[timestamp] = feeds[key]
    covered = sum(bool(feeds[key]) for key in keys.values())
    print(f"{covered}/{len(keys)} snapshots with headlines, {sum(feed is None for feed in feeds.values())} request failures")
    if not covered:
        raise SystemExit("No headlines retrieved")
    (DATA / "browser-news.json").write_text(json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
