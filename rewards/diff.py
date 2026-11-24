"""Compare the current scrape with the previous state.

State shape (state.json):
{
  "cards": {sku: {..Card fields.., "first_seen": iso, "last_seen": iso, "listed": bool}},
  "last_ok": iso, "login_alert_sent": bool, "consecutive_errors": int,
  "error_alert_sent": bool
}
SKUs are never dropped from state, so a card that briefly disappears and comes
back isn't reported as "new" again.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .parser import Card


@dataclass
class Changes:
    new: list[Card] = field(default_factory=list)        # never seen before
    restocked: list[Card] = field(default_factory=list)  # out of stock -> in stock
    gone_oos: list[Card] = field(default_factory=list)   # in stock -> out of stock (logged, not alerted)
    removed: list[str] = field(default_factory=list)     # listed before, not listed now

    @property
    def alertable(self) -> bool:
        return bool(self.new or self.restocked)


def compare(prev_cards: dict[str, dict], current: list[Card]) -> Changes:
    ch = Changes()
    cur_skus = {c.sku for c in current}
    for c in current:
        old = prev_cards.get(c.sku)
        if old is None:
            ch.new.append(c)
        elif c.in_stock and (not old.get("in_stock") or not old.get("listed", True)):
            # back in stock, or reappeared in the catalogue while in stock
            ch.restocked.append(c)
        elif not c.in_stock and old.get("in_stock") and old.get("listed", True):
            ch.gone_oos.append(c)
    for sku, old in prev_cards.items():
        if old.get("listed", True) and sku not in cur_skus:
            ch.removed.append(sku)
    return ch


def merge(prev_cards: dict[str, dict], current: list[Card], now_iso: str) -> dict[str, dict]:
    out = {sku: {**v, "listed": False} for sku, v in prev_cards.items()}
    for c in current:
        old = prev_cards.get(c.sku, {})
        out[c.sku] = {
            **c.to_dict(),
            "first_seen": old.get("first_seen", now_iso),
            "last_seen": now_iso,
            "listed": True,
        }
    return out
