"""Signed-in browser mode (optional, `check.py --browser`): adds your points balance.

The default is the browser-free rewards/fetch.py.
Loads the gift-cards list, then each product page.

READ-ONLY by construction:
  * pages are reached only with page.goto(url); nothing is ever clicked;
  * a network guard aborts every non-GET request to rewards.bing.com, so even
    an accidental interaction could not place an order.
"""
from __future__ import annotations

import logging
import random
import time

from playwright.sync_api import BrowserContext, Page, Route
from playwright.sync_api import Error as PlaywrightError

from . import browser, config, parser
from .fetch import LoginRequired, ScrapeResult, SiteError  # noqa: F401  (shared types)
from .parser import Card

log = logging.getLogger(__name__)


def _guard(route: Route) -> None:
    req = route.request
    if req.method != "GET" and "rewards.bing.com" in req.url:
        log.debug("blocked %s %s", req.method, req.url)
        route.abort()
    else:
        route.continue_()


def _load(page: Page, url: str, wait_selector: str | None = None) -> str:
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except PlaywrightError as e:
        # net::ERR_CONNECTION_RESET, timeouts, DNS... -> the site, not us
        raise SiteError(f"could not load {url}: {str(e).splitlines()[0]}") from None
    if browser.is_login_url(page.url):
        raise LoginRequired(f"redirected to {page.url}")
    if resp is not None and resp.status >= 500:
        raise SiteError(f"HTTP {resp.status} at {url}")
    if browser.is_login_url(page.url):
        raise LoginRequired(f"redirected to {page.url}")
    if wait_selector:
        try:
            page.wait_for_selector(wait_selector, timeout=20_000)
        except Exception:
            pass
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    if browser.is_login_url(page.url):
        raise LoginRequired(f"redirected to {page.url}")
    return page.content()


def _load_checked(page: Page, url: str, wait_selector: str | None) -> str:
    html = _load(page, url, wait_selector)
    if parser.is_error_page(html):
        raise SiteError(f"Bing error page at {url}")
    return html


def _load_with_retry(page: Page, url: str, wait_selector: str | None = None) -> str:
    try:
        return _load_checked(page, url, wait_selector)
    except SiteError as e:
        log.info("%s; retrying in 20s", e)
        time.sleep(20)
        return _load_checked(page, url, wait_selector)


def _save_debug(name: str, html: str) -> None:
    try:
        config.LOG_DIR.mkdir(exist_ok=True)
        (config.LOG_DIR / name).write_text(html, encoding="utf-8")
    except Exception:
        pass


def scrape(ctx: BrowserContext) -> ScrapeResult:
    ctx.route("**/*", _guard)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    html = _load_with_retry(page, config.GIFTCARDS_URL, "a[href*='/redeem/sku/']")
    tiles = parser.parse_list_page(html)
    if not tiles:
        _save_debug("last_failure_list.html", html)
        raise SiteError("no gift cards found on the list page (layout change or not signed in?)")
    log.info("List page: %d gift cards", len(tiles))

    cards: dict[str, Card] = {}
    balance: int | None = None
    failed: list[str] = []

    for tile in tiles:
        if tile.sku in cards:  # already covered as a variant of an earlier page
            continue
        time.sleep(random.uniform(2, 5))  # be gentle
        url = config.SKU_URL_PREFIX + tile.sku
        try:
            sku_html = _load_with_retry(page, url, "button")
        except SiteError as e:
            log.warning("%s: %s", tile.sku, e)
            failed.append(tile.sku)
            continue

        info = parser.parse_sku_page(sku_html)
        if info and info.signed_in is False:
            raise LoginRequired("product page reports isSignedIn=false")
        if info and info.cards:
            balance = info.balance if info.balance is not None else balance
            for c in info.cards:
                if c.points is None:
                    c.points = tile.points
                cards[c.sku] = c
            continue

        # Fallback: read the rendered page.
        oos = parser.dom_out_of_stock(sku_html)
        if oos is None:
            log.warning("%s: couldn't determine stock state", tile.sku)
            _save_debug(f"last_failure_sku_{tile.sku}.html", sku_html)
            failed.append(tile.sku)
            continue
        cards[tile.sku] = Card(sku=tile.sku, name=tile.title, title=tile.title,
                               points=tile.points, in_stock=not oos, source="dom")

    if not cards:
        raise SiteError("no product pages could be read")
    return ScrapeResult(cards=list(cards.values()), balance=balance, failed_skus=failed)
