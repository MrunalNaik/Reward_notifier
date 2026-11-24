"""Browser-free fetcher, with the network mocked out."""
from __future__ import annotations

import json

import pytest

from rewards import config, fetch


def _sku_html(sku: str, disabled) -> str:
    item = {"id": sku, "title": f"Card {sku}", "fullTitle": f"Card {sku}", "price": 1000,
            "isDisabled": disabled}
    payload = '1:["$","$L6b",null,{"balance":0,"isSignedIn":false,"items":[' + json.dumps(item) + "]}]\n"
    return f"<html><script>self.__next_f.push({json.dumps([1, payload])})</script></html>"


LIST_HTML = ('<html><script>self.__next_f.push([1,""])</script>'
             '<a href="/redeem/sku/A1"><img alt="Card A1"><span>1,000</span>pts</a>'
             '<a href="/redeem/sku/B2"><img alt="Card B2"><span>1,000</span>pts</a></html>')


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)


def test_scrape_reads_stock_without_login(monkeypatch):
    pages = {config.GIFTCARDS_URL: LIST_HTML,
             config.SKU_URL_PREFIX + "A1": _sku_html("A1", True),
             config.SKU_URL_PREFIX + "B2": _sku_html("B2", "$undefined")}
    monkeypatch.setattr(fetch, "_get_once", lambda url: pages[url])
    r = fetch.scrape()
    assert {c.sku: c.in_stock for c in r.cards} == {"A1": False, "B2": True}
    assert r.failed_skus == [] and r.balance is None


def test_failed_product_page_is_reported_not_dropped_silently(monkeypatch):
    def get(url):
        if url.endswith("B2"):
            raise fetch.SiteError("HTTP 503")
        return LIST_HTML if url == config.GIFTCARDS_URL else _sku_html("A1", True)
    monkeypatch.setattr(fetch, "_get_once", get)
    r = fetch.scrape()
    assert [c.sku for c in r.cards] == ["A1"] and r.failed_skus == ["B2"]


def test_retries_then_succeeds(monkeypatch):
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) < 3:
            raise fetch.SiteError("HTTP 503")
        return "ok"
    monkeypatch.setattr(fetch, "_get_once", flaky)
    assert fetch.get("u") == "ok" and len(calls) == 3


def test_list_page_down_raises_site_error(monkeypatch):
    def down(url):
        raise fetch.SiteError("HTTP 503")
    monkeypatch.setattr(fetch, "_get_once", down)
    with pytest.raises(fetch.SiteError):
        fetch.scrape()
