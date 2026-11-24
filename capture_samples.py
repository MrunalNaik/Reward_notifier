"""Capture real page data into ./samples so the parser can be built against it.

Saves:
  samples/shop.html / .png         the Gift cards list (/redeem/in/shop)
  samples/sku_<id>.html / .png     every gift card's product page
  samples/xhr/NNN_*.json     every JSON response the pages loaded
  samples/xhr/index.json     URL, status and file name for each response

Read-only: it loads pages by URL and scrolls; it never clicks anything.
The tests use shop.html, sku_instock.html, sku_outofstock.html and error_page.html;
copy/rename a fresh capture to those names to re-test after a site change.

Usage:
  python capture_samples.py                  # headless, every gift card
  python capture_samples.py --sku 000885000034   # just one product page
  python capture_samples.py --headed         # watch it run
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from playwright.sync_api import Page, Response, sync_playwright

from rewards import browser, config, parser

XHR_DIR = config.SAMPLES_DIR / "xhr"


def slug(url: str) -> str:
    path = re.sub(r"^https?://[^/]+", "", url).split("?")[0]
    return (re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root")[:80]


def scroll_to_bottom(page: Page) -> None:
    """Scroll in steps so lazy-loaded tiles render."""
    last = -1
    for _ in range(30):
        height = page.evaluate("document.body.scrollHeight")
        if height == last:
            break
        last = height
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(700)
    page.evaluate("window.scrollTo(0, 0)")


def load(page: Page, url: str) -> bool:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass  # some pages keep polling; carry on
    if browser.is_login_url(page.url):
        print(f"Redirected to sign-in ({page.url}). Run: python login.py")
        return False
    scroll_to_bottom(page)
    page.wait_for_timeout(1500)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sku", help="capture only this SKU id")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    XHR_DIR.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []

    def on_response(resp: Response) -> None:
        try:
            ctype = resp.headers.get("content-type", "")
            if "json" not in ctype or "bing.com" not in resp.url:
                return
            body = resp.json()
        except Exception:
            return
        name = f"{len(index):03d}_{slug(resp.url)}.json"
        (XHR_DIR / name).write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        index.append({"file": name, "status": resp.status, "method": resp.request.method, "url": resp.url})

    with sync_playwright() as pw:
        ctx = browser.launch(pw, headless=not args.headed)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_response)

        print(f"Loading {config.GIFTCARDS_URL} ...")
        if not load(page, config.GIFTCARDS_URL):
            ctx.close()
            return 2
        html = page.content()
        if parser.is_error_page(html):
            print("Got Bing's 'It's not you, it's us' page; saved as error_page.html. Try again later.")
            (config.SAMPLES_DIR / "error_page.html").write_text(html, encoding="utf-8")
            ctx.close()
            return 3
        (config.SAMPLES_DIR / "shop.html").write_text(html, encoding="utf-8")
        page.screenshot(path=str(config.SAMPLES_DIR / "shop.png"), full_page=True)
        tiles = parser.parse_list_page(html)
        skus = [t.sku for t in tiles]
        print(f"Found {len(skus)} gift cards: " + ", ".join(f"{t.sku} {t.title!r}" for t in tiles))

        for sku in ([args.sku] if args.sku else skus):
            url = config.SKU_URL_PREFIX + sku
            print(f"Loading {url} ...")
            if not load(page, url):
                continue
            html = page.content()
            info = parser.parse_sku_page(html)
            state = "?"
            if info and info.cards:
                state = ", ".join(f"{c.name}: {'in stock' if c.in_stock else 'OUT of stock'}" for c in info.cards)
            print(f"  -> {state}")
            (config.SAMPLES_DIR / f"sku_{sku}.html").write_text(html, encoding="utf-8")
            page.screenshot(path=str(config.SAMPLES_DIR / f"sku_{sku}.png"), full_page=True)
            page.wait_for_timeout(2500)

        ctx.close()

    (XHR_DIR / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    (config.SAMPLES_DIR / "sku_links.txt").write_text("\n".join(skus), encoding="utf-8")
    print(f"Saved {len(index)} JSON responses to {XHR_DIR}")
    print("Done. Samples are in ./samples")
    return 0


if __name__ == "__main__":
    sys.exit(main())
