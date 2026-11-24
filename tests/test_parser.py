"""Parser tests.

Synthetic tests always run. Tests against real captures in ./samples run only
if those files exist (samples/ is git-ignored because it contains account data;
recreate them with `python capture_samples.py`).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rewards import parser

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _sample(name: str) -> str:
    p = SAMPLES / name
    if not p.exists():
        pytest.skip(f"samples/{name} not present")
    return p.read_text(encoding="utf-8")


def _rsc_page(payload: str, body: str = "") -> str:
    push = json.dumps([1, payload])
    return f"<html><body>{body}<script>self.__next_f.push({push})</script></body></html>"


# ---- synthetic ------------------------------------------------------------ #
ITEM = {"id": "000885000034", "title": "Flipkart Gift Card", "fullTitle": "₹1000 Flipkart Gift Card",
        "price": 19320, "isDisabled": True, "isEligible": True}


def _sku_payload(**over) -> str:
    item = {**ITEM, **over}
    return '68:["$","$L6b",null,{"balance":500,"isSignedIn":true,"userCountry":"in","items":[' + \
        json.dumps(item, ensure_ascii=False) + "]}]\n"


def test_sku_out_of_stock():
    info = parser.parse_sku_page(_rsc_page(_sku_payload()))
    assert info.signed_in is True and info.balance == 500
    (c,) = info.cards
    assert (c.sku, c.points, c.in_stock, c.name) == ("000885000034", 19320, False, "₹1000 Flipkart Gift Card")


def test_sku_in_stock_when_isdisabled_undefined():
    info = parser.parse_sku_page(_rsc_page(_sku_payload(isDisabled="$undefined")))
    assert info.cards[0].in_stock is True


def test_signed_out_flag():
    info = parser.parse_sku_page(_rsc_page(_sku_payload().replace('"isSignedIn":true', '"isSignedIn":false')))
    assert info.signed_in is False


def test_restock_text_in_scripts_is_ignored():
    # The translation string lives in every page's scripts; must not count.
    html = _rsc_page('"notAvailable":"So popular we\'re restocking! Back soon!"',
                     body='<button type="button">Redeem now</button>')
    assert parser.dom_out_of_stock(html) is False


def test_dom_disabled_button():
    assert parser.dom_out_of_stock('<button type="button" disabled="">Redeem now</button>') is True


def test_list_page():
    html = ('<a href="/redeem/sku/000885000034" class="x"><div><img alt="Flipkart Gift Card" src="a.jpg">'
            '<p>Flipkart Gift Card</p><span>19,320</span><span>pts</span></div></a>')
    (t,) = parser.parse_list_page(html)
    assert (t.sku, t.title, t.points) == ("000885000034", "Flipkart Gift Card", 19320)


def test_error_page_detected():
    assert parser.is_error_page("<html><title>Bing</title>It's not you, it's us</html>")
    assert not parser.is_error_page(_rsc_page(_sku_payload()))


# ---- real captures --------------------------------------------------------- #
def test_real_list_page():
    tiles = {t.sku: t for t in parser.parse_list_page(_sample("shop.html"))}
    assert tiles["000885000034"].title == "Flipkart Gift Card"
    assert tiles["000885000034"].points == 19320


def test_real_sku_in_stock():
    html = _sample("sku_instock.html")
    info = parser.parse_sku_page(html)
    assert info.signed_in is True
    assert [c.in_stock for c in info.cards] == [True]
    assert parser.dom_out_of_stock(html) is False


def test_real_sku_out_of_stock():
    html = _sample("sku_outofstock.html")
    info = parser.parse_sku_page(html)
    assert [(c.sku, c.in_stock, c.points) for c in info.cards] == [("000885000034", False, 19320)]
    assert parser.dom_out_of_stock(html) is True


def test_real_error_page():
    html = _sample("error_page.html")
    assert parser.is_error_page(html)
    assert parser.parse_list_page(html) == []
