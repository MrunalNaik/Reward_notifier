"""Pure parsing functions: HTML in, data out. No browser needed, so testable.

What the site looks like (Next.js app, data streamed via `self.__next_f.push`):

* Gift cards list (/redeem/in/shop): each tile is a rendered
  <a href="/redeem/sku/<id>"> with an <img alt="<title>"> and "<points>pts".
* Product page (/redeem/sku/<id>): the RSC payload has
    {"balance":..,"isSignedIn":true,"userCountry":"in","items":[{...}]}
  where each item has id, title, fullTitle, price, isDisabled, isEligible...
  Out of stock  -> "isDisabled": true
  In stock      -> "isDisabled": "$undefined"
  The rendered page agrees: a disabled "Redeem now" <button> and a visible
  <p>So popular we're restocking! Back soon!</p>.

NOTE: the "So popular we're restocking!" text exists in EVERY product page as a
translation string inside the scripts, so never search raw HTML for it; only
search the rendered markup with <script> blocks stripped (see dom_out_of_stock).
"""
from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import asdict, dataclass

SKU_RE = re.compile(r"/redeem/sku/(\w+)")
RESTOCK_TEXT = "So popular we're restocking"


@dataclass
class Card:
    sku: str
    name: str
    points: int | None
    in_stock: bool
    title: str = ""          # short family title, e.g. "Flipkart Gift Card"
    eligible: bool | None = None
    source: str = "rsc"      # "rsc" (structured data) or "dom" (fallback)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SkuPage:
    signed_in: bool | None
    balance: int | None
    cards: list[Card]


@dataclass
class ListTile:
    sku: str
    title: str
    points: int | None


# --------------------------------------------------------------------------- #
# Page classification
# --------------------------------------------------------------------------- #
def is_error_page(html: str) -> bool:
    """Bing's 'It's not you, it's us' outage/throttle page (no Next.js app)."""
    return "self.__next_f" not in html and (
        "it's us" in html.lower() or "it&#39;s us" in html.lower() or "<title>Bing</title>" in html
    )


def strip_scripts(html: str) -> str:
    return re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)


# --------------------------------------------------------------------------- #
# RSC (React Server Components) payload
# --------------------------------------------------------------------------- #
_PUSH_RE = re.compile(r"self\.__next_f\.push\((\[.*?\])\)\s*</script>", re.S)


def extract_rsc(html: str) -> str:
    """Concatenate the string payloads of all self.__next_f.push([1, "..."]) calls."""
    parts: list[str] = []
    for raw in _PUSH_RE.findall(html):
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if len(arr) > 1 and isinstance(arr[1], str):
            parts.append(arr[1])
    return "".join(parts)


def _json_at(text: str, start: int):
    return json.JSONDecoder().raw_decode(text, start)[0]


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_sku_page(html: str) -> SkuPage | None:
    """Parse a product page. Returns None if the structured data isn't found."""
    rsc = extract_rsc(html)
    idx = rsc.find('"items":[')
    if idx < 0:
        return None
    try:
        items = _json_at(rsc, idx + len('"items":'))
    except json.JSONDecodeError:
        return None

    head = rsc[max(0, idx - 400): idx]
    m_sign = re.search(r'"isSignedIn":(true|false)', head)
    m_bal = re.search(r'"balance":(\d+)', head)

    cards = []
    for it in items:
        if not isinstance(it, dict) or not it.get("id"):
            continue
        eligible = it.get("isEligible")
        cards.append(Card(
            sku=str(it["id"]),
            name=str(it.get("fullTitle") or it.get("title") or it["id"]),
            title=str(it.get("title") or ""),
            points=_int(it.get("price")),
            in_stock=it.get("isDisabled") is not True,
            eligible=eligible if isinstance(eligible, bool) else None,
            source="rsc",
        ))
    return SkuPage(
        signed_in=(m_sign.group(1) == "true") if m_sign else None,
        balance=int(m_bal.group(1)) if m_bal else None,
        cards=cards,
    )


# --------------------------------------------------------------------------- #
# Rendered DOM (fallbacks + list page)
# --------------------------------------------------------------------------- #
def dom_out_of_stock(html: str) -> bool | None:
    """True/False from the rendered product page; None if no Redeem button found."""
    body = strip_scripts(html)
    if RESTOCK_TEXT in body.replace("&#x27;", "'").replace("&#39;", "'"):
        return True
    m = re.search(r"<button\b([^>]*)>(?:(?!</button>).)*?Redeem now", body, re.S)
    if not m:
        return None
    attrs = m.group(1)
    return bool(re.search(r'\sdisabled(=|\s|>|$)|data-disabled="true"', attrs))


_POINTS_RE = re.compile(r"([\d,]+)\s*(?:<[^>]+>\s*)*pts")


def parse_list_page(html: str) -> list[ListTile]:
    """Gift-card tiles from the rendered list page."""
    body = strip_scripts(html)
    tiles: dict[str, ListTile] = {}
    for m in re.finditer(r'<a\b[^>]*href="[^"]*/redeem/sku/(\w+)[^"]*"[^>]*>(.*?)</a>', body, re.S):
        sku, inner = m.group(1), m.group(2)
        alt = re.search(r'alt="([^"]*)"', inner)
        text = [t.strip() for t in re.split(r"<[^>]+>", inner) if t.strip()]
        title = htmllib.unescape(alt.group(1) if alt else (text[0] if text else sku))
        pts = _POINTS_RE.search(inner)
        tiles.setdefault(sku, ListTile(sku, title, _int(pts.group(1).replace(",", "")) if pts else None))
    return list(tiles.values())
