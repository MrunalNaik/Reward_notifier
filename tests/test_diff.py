from rewards.diff import compare, merge
from rewards.parser import Card


def card(sku, in_stock, name=None):
    return Card(sku=sku, name=name or sku, points=1000, in_stock=in_stock)


def test_first_run_everything_is_new():
    ch = compare({}, [card("a", True), card("b", False)])
    assert [c.sku for c in ch.new] == ["a", "b"]


def test_restock_detected():
    prev = merge({}, [card("a", False)], "t1")
    ch = compare(prev, [card("a", True)])
    assert [c.sku for c in ch.restocked] == ["a"] and not ch.new


def test_no_alert_when_unchanged():
    prev = merge({}, [card("a", True), card("b", False)], "t1")
    ch = compare(prev, [card("a", True), card("b", False)])
    assert not ch.alertable and not ch.gone_oos and not ch.removed


def test_going_out_of_stock_is_not_alertable():
    prev = merge({}, [card("a", True)], "t1")
    ch = compare(prev, [card("a", False)])
    assert [c.sku for c in ch.gone_oos] == ["a"] and not ch.alertable


def test_removed_then_back_is_restock_not_new():
    s1 = merge({}, [card("a", True), card("b", True)], "t1")
    ch = compare(s1, [card("a", True)])
    assert ch.removed == ["b"]
    s2 = merge(s1, [card("a", True)], "t2")
    assert s2["b"]["listed"] is False and s2["b"]["first_seen"] == "t1"
    ch = compare(s2, [card("a", True), card("b", True)])
    assert not ch.new and [c.sku for c in ch.restocked] == ["b"]
    # removed again on next run isn't reported twice
    assert compare(s2, [card("a", True)]).removed == []


def test_reappearing_out_of_stock_is_silent():
    s1 = merge(merge({}, [card("b", True)], "t1"), [], "t2")
    ch = compare(s1, [card("b", False)])
    assert not ch.alertable
