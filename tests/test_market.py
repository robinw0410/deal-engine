from datetime import date, timedelta

import pytest

from deal_engine.core.market import estimate, resale_from_ask, sold_estimate

G = {"name": "Switch Lite", "match": r"switch\s*lite", "min": 60, "max": 200}
GROUPS = [G]
FLT = {"signal_regex": "defect|broken"}
TODAY = date(2026, 6, 30)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("DEAL_ENGINE_TODAY", str(TODAY))


def item(title, price, days_old=1, private=True):
    return {"title": title, "price": price, "private": private,
            "_published": str(TODAY - timedelta(days=days_old))}


def test_median_and_p25():
    items = [item("Switch Lite", p) for p in (100, 110, 120, 130, 140)]
    assert estimate(items, G, GROUPS, FLT) == {"median": 120, "p25": 110, "n": 5}


def test_too_few_listings():
    assert estimate([item("Switch Lite", 100)] * 4, G, GROUPS, FLT) is None


def test_excludes_defects_accessories_bundles_and_outliers():
    items = [item("Switch Lite", p) for p in (100, 110, 120, 130, 140)]
    items += [item("Switch Lite broken", 30), item("Switch Lite defect", 70),   # defect signal
              item("case for Switch Lite", 15),                                  # accessory
              item("Switch Lite", 900),                                          # outside min/max
              item("Switch Lite wanted", 50)]                                    # wanted ad
    assert estimate(items, G, GROUPS, FLT)["n"] == 5


def test_prefers_fresh_listings():
    stale = [item("Switch Lite", 180, days_old=60) for _ in range(10)]
    fresh = [item("Switch Lite", 100, days_old=2) for _ in range(8)]
    assert estimate(stale + fresh, G, GROUPS, FLT)["median"] == 100


def test_falls_back_to_private_then_all():
    stale_private = [item("Switch Lite", 110, days_old=60) for _ in range(5)]
    stale_business = [item("Switch Lite", 190, days_old=60, private=False) for _ in range(6)]
    assert estimate(stale_private + stale_business, G, GROUPS, FLT)["median"] == 110
    assert estimate(stale_business, G, GROUPS, FLT)["median"] == 190


def test_resale_from_ask():
    assert resale_from_ask({"median": 100, "p25": 90}, 0.85) == 85
    assert resale_from_ask({"median": 100, "p25": 80}, 0.85) == 80
    assert resale_from_ask({"median": 100}, 0.85) == 85


def test_sold_estimate():
    prices = [100, 105, 110, 95, 100, 102, 98, 101]
    assert sold_estimate(prices[:7], 120) is None                 # not enough data
    assert sold_estimate(prices, 120) == round(100.5 * 0.93)       # median of disappeared x factor
    assert sold_estimate(prices, 80) == 80                         # never above the asking estimate
