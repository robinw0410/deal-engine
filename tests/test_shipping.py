"""Unknown shipping costs are never treated as 0."""
import pytest

from adapters.ebay import to_listing
from core.listing import normalize, shipping_unknown
from core.pipeline import select
from core.score import DEFAULTS, SHIPPING_DEFAULTS, compute

C = {**DEFAULTS, **SHIPPING_DEFAULTS}
GROUP = {"name": "Switch Lite", "match": r"switch\s*lite", "min": 60, "max": 200}
SC = {"filters": {"signal_regex": "defect"}, "market": {"groups": [GROUP], "flip_ratio": 0.7}}
MARKET = {"Switch Lite": {"median": 100, "p25": 90, "n": 10}}


def summary(**kw):
    """Synthetic Browse API item summary."""
    return {"legacyItemId": "123456789012", "title": "Switch Lite", "price": {"value": "60.00", "currency": "EUR"},
            "buyingOptions": ["FIXED_PRICE"], "conditionId": "3000", **kw}


def item(**kw):
    return normalize(to_listing(summary(**kw), "EBAY_DE"), "ebay")


def test_ebay_missing_shipping_cost_is_unknown_not_zero():
    it = item(shippingOptions=[{"shippingCostType": "CALCULATED"}])   # no shippingCost
    assert it["shipping_cost_eur"] is None and shipping_unknown(it)
    assert shipping_unknown(item())                                     # no shippingOptions at all


def test_free_shipping_stays_zero():
    it = item(shippingOptions=[{"shippingCost": {"value": "0.0", "currency": "EUR"}}])
    assert it["shipping_cost_eur"] == 0 and not shipping_unknown(it)


def test_platform_shipping_or_pickup_is_not_unknown():
    assert not shipping_unknown({"shipping_cost_eur": None, "shipping_possible": True, "distance_km": None})
    assert not shipping_unknown({"shipping_cost_eur": None, "shipping_possible": False, "distance_km": 30})


def test_selection_assumes_lump_sum():
    # threshold: 100 x 0.7 = 70. Price 60 passes with free shipping, not with 15 € assumed.
    unknown = item()
    free = item(legacyItemId="123456789013", shippingOptions=[{"shippingCost": {"value": "0", "currency": "EUR"}}])
    cands, _ = select({unknown["source_id"]: unknown, free["source_id"]: free}, set(), {}, MARKET, SC,
                      log=lambda s: None, unknown_cost=15)
    assert [c["source_id"] for c in cands] == [free["source_id"]]
    assert unknown["shipping_unknown"] is True
    assert unknown["shipping_note"] == "shipping unknown, assumed 15 €"
    assert "shipping_unknown" not in free
    cands, _ = select({unknown["source_id"]: unknown}, set(), {}, MARKET, SC, log=lambda s: None, unknown_cost=5)
    assert len(cands) == 1   # configurable


BASE = {"price": 60, "market_price": 120, "market_resale_estimate": 120, "repair_parts_eur": 0,
        "repair_hours": 2, "risk": "low", "deal_type": "flip"}


@pytest.mark.parametrize("given,expected_ship", [
    (None, 15),   # nothing known: lump sum
    (0, 15),      # an evaluator's 0 does not count when the source states nothing
    (9, 9),       # a real estimate is kept
])
def test_score_uses_lump_sum(given, expected_ship):
    l = {**BASE, "shipping_unknown": True, "shipping_cost_eur": given}
    r = compute(l, C)
    assert r["profit"] == 120 - 60 - expected_ship
    if expected_ship == 15:
        assert "shipping unknown, assumed 15 €" in r["text"]


def test_score_known_free_shipping_stays_free():
    assert compute({**BASE, "shipping_cost_eur": 0}, C)["profit"] == 60
