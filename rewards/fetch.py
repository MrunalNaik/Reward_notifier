"""Browser-free scraper: plain HTTPS requests, no login needed.

The gift-card list and product pages are server-rendered and include the
stock flag (`isDisabled`) even when signed out, so a simple GET is enough.
This is what runs in the cloud (GitHub Actions). Signed out, the points
balance isn't available.

READ-ONLY: only GET requests are ever made.
"""
from __future__ import annotations

import logging
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import config, parser
from .parser import Card

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
}
RETRIES = 2
RETRY_DELAY = 20


class LoginRequired(Exception):
    pass


class SiteError(Exception):
    pass


@dataclass
class ScrapeResult:
    cards: list[Card]
    balance: int | None = None
    failed_skus: list[str] = field(default_factory=list)  # product pages that couldn't be read


def _get_once(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            html = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise SiteError(f"HTTP {e.code} at {url}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SiteError(f"could not load {url}: {e}") from None
    if parser.is_error_page(html):
        raise SiteError(f"Bing error page at {url}")
    return html


def get(url: str) -> str:
    for attempt in range(RETRIES + 1):
        try:
            return _get_once(url)
        except SiteError as e:
            if attempt == RETRIES:
                raise
            log.info("%s; retrying in %ds", e, RETRY_DELAY)
            time.sleep(RETRY_DELAY)
    raise AssertionError("unreachable")


def scrape() -> ScrapeResult:
    html = get(config.GIFTCARDS_URL)
    tiles = parser.parse_list_page(html)
    if not tiles:
        raise SiteError("no gift cards found on the list page (layout change?)")
    log.info("List page: %d gift cards", len(tiles))

    cards: dict[str, Card] = {}
    failed: list[str] = []
    for tile in tiles:
        if tile.sku in cards:
            continue
        time.sleep(random.uniform(1.5, 4))  # be gentle
        try:
            info = parser.parse_sku_page(get(config.SKU_URL_PREFIX + tile.sku))
        except SiteError as e:
            log.warning("%s: %s", tile.sku, e)
            failed.append(tile.sku)
            continue
        if not info or not info.cards:
            # Signed out, the rendered button is always disabled, so there is
            # no reliable DOM fallback here: treat as unreadable.
            log.warning("%s: no product data found on page", tile.sku)
            failed.append(tile.sku)
            continue
        for c in info.cards:
            if c.points is None:
                c.points = tile.points
            cards[c.sku] = c

    if not cards:
        raise SiteError("no product pages could be read")
    return ScrapeResult(cards=list(cards.values()), balance=None, failed_skus=failed)
