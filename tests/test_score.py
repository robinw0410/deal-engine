import pytest

from deal_engine.core.score import DEFAULTS, SHIPPING_DEFAULTS, compute, interp, max_price

C = {**DEFAULTS, **SHIPPING_DEFAULTS}

BASE = {"title": "Console – no picture", "price": 100, "market_price": 220, "market_resale_estimate": 220,
        "repair_parts_eur": 10, "repair_hours": 2, "shipping_cost_eur": 0, "risk": "low", "deal_type": "repair"}


def test_interp():
    pts = [[0, 1], [10, 5], [20, 6]]
    assert interp(-5, pts) == 1
    assert interp(5, pts) == 3
    assert interp(15, pts) == 5.5
    assert interp(99, pts) == 6


def test_profit_and_per_hour():
    r = compute(BASE, C)
    assert r["profit"] == 220 - 100 - 10            # no shipping, no distance known
    assert r["per_hour"] == pytest.approx(110 / 2, abs=0.1)
    assert 1 <= r["score"] <= 10


def test_missing_numbers_give_none():
    assert compute({**BASE, "repair_hours": None}, C) is None
    assert compute({**BASE, "market_price": None}, C) is None


def test_platform_shipping_adds_fee():
    r = compute({**BASE, "shipping_possible": True}, C)
    # 6 € parcel + max(0.99, 4 % of 100) = 10 €
    assert r["profit"] == 220 - 100 - 10 - 10


def test_pickup_adds_travel_cost_and_time():
    r = compute({**BASE, "shipping_possible": False, "distance_km": 35}, C)
    assert r["profit"] == 220 - 100 - 10 - round(2 * 35 * 0.25)
    # 2 h work + 1 h driving
    assert r["per_hour"] == pytest.approx(r["profit"] / 3, abs=0.1)


def test_resale_capped_at_market_estimate():
    r = compute({**BASE, "market_price": 400}, C)
    assert r["profit"] == round(220 * 1.05) - 100 - 10


def test_caps():
    good = compute(BASE, C)["score"]
    assert compute({**BASE, "risk": "high"}, C)["score"] <= min(good, C["max_score_high_risk"])
    assert compute({**BASE, "status": "reserved"}, C)["score"] <= 3
    assert compute({**BASE, "market_resale_estimate": None}, C)["score"] <= C["max_score_no_market"]
    assert compute({**BASE, "issues": "seller insists on prepayment"}, C)["score"] <= C["max_score_fraud"]
    assert compute({**BASE, "score_ai": 3}, C)["score"] <= 3 + C["max_gap_ai"]
    assert compute({**BASE, "photo_check": "more damage than described"}, C)["score"] <= C["max_score_photo_worse"]


def test_below_minimum_profit():
    r = compute({**BASE, "price": 205}, C)
    assert r["score"] <= 3


def test_higher_price_never_scores_higher():
    scores = [compute({**BASE, "price": p}, C, caps=False)["score"] for p in range(0, 220, 10)]
    assert scores == sorted(scores, reverse=True)


def test_max_price_reaches_target():
    mx = max_price(BASE, C)
    assert mx is not None and mx % 5 == 0
    assert compute({**BASE, "price": mx}, C, caps=False)["score"] >= C["target_score"]
    assert compute({**BASE, "price": mx + 10}, C, caps=False)["score"] < C["target_score"]
