"""v0.2.6: extras of a device (controllers with a console) raise its candidate threshold: (device median + n x the
extra group's median) x ratio. Games and extras without market data add nothing; the evaluation is unchanged."""
import pytest

from deal_engine.core import clock, locale, pipeline
from deal_engine.core.config import ConfigError
from deal_engine.core.groups import check_groups, extras_count, extras_value
from deal_engine.core.listing import normalize

DE, EN = locale.get("de"), locale.get("en")
PAD = r"controller\w*|gamepads?|pads?"
GROUPS = [
    {"name": "Pad", "match": r"\bpad\b|controller", "exclude": r"\bkonsole\b|\bconsole\b|\+|\bmit\b|\bwith\b"},
    {"name": "Console", "match": r"\bkonsole\b|\bconsole\b", "extras": {"Pad": PAD}},
]
MARKET = {"Console": {"median": 200, "n": 30}, "Pad": {"median": 40, "n": 20}}


@pytest.mark.parametrize("title, loc, n", [
    ("Konsole + 2 Controller + 6 Spiele", DE, 2),
    ("Konsole + Controller", DE, 1),
    ("Konsole mit zwei Controllern", DE, 2),
    ("Konsole mit 2 originalen Controllern", DE, 2),
    ("Konsole 1TB 2 Controller", DE, 2),
    ("Konsole inkl. 2x Gamepad", DE, 2),
    ("Konsole, 1 Controller, Kabel", DE, 1),
    ("Konsole ohne Controller", DE, 0),
    ("Konsole kein Controller dabei", DE, 0),
    ("Konsole + 6 Spiele", DE, 0),
    ("Konsole 500GB", DE, 0),
    ("Konsole + 2 Controller + Controller Ladestation", DE, 2),   # the charging station is no controller
    ("Konsole mit Controller-Stick defekt", DE, 0),
    ("Console with two controllers", EN, 2),
    ("Console without controller", EN, 0),
    ("Konsole + 20 Controller", DE, 8),                          # capped
])
def test_extras_count(title, loc, n):
    assert extras_count(title, PAD, loc) == n


def test_extras_value_needs_market_data():
    g = GROUPS[1]
    assert extras_value("Konsole + 2 Controller", g, MARKET, DE) == (80, [("Pad", 2)])
    assert extras_value("Konsole + 2 Controller", g, {"Console": MARKET["Console"]}, DE) == (0, [])
    assert extras_value("Konsole + 2 Controller", GROUPS[0], MARKET, DE) == (0, [])   # no extras configured


def select(title, price, groups=GROUPS, market=MARKET, signal=None):
    it = normalize({"source_id": "1", "url": "https://example.org/1", "title": title, "price": price,
                    "published": clock.today_str(), "shipping_possible": True, "shipping_cost_eur": 0}, "test")
    flt = {"signal_regex": signal} if signal else {}
    sc = {"_locale": "de", "filters": flt, "market": {"groups": groups}}
    cands, _ = pipeline.select({"1": it}, set(), {}, market, sc, lambda s: None, adapter_name="test")
    return cands[0] if cands else None


def test_threshold_adds_controllers():
    # flip ratio 0.7: (200 + 2 x 40) x 0.7 = 196; without extras 200 x 0.7 = 140
    c = select("Konsole + 2 Controller + 6 Spiele", 190, signal="defekt")
    assert c is not None and c["market_group"] == "Console"
    assert c["market_extras"] == [{"group": "Pad", "count": 2, "median": 40}]
    assert select("Konsole + 2 Controller + 6 Spiele", 200, signal="defekt") is None


@pytest.mark.parametrize("title", ["Konsole + 6 Spiele", "Konsole ohne Controller", "Konsole 500GB"])
def test_threshold_without_extras_unchanged(title):
    assert select(title, 140, signal="defekt") is not None
    assert select(title, 150, signal="defekt") is None


def test_extras_off_without_config():
    plain = [GROUPS[0], {k: v for k, v in GROUPS[1].items() if k != "extras"}]
    assert select("Konsole + 2 Controller", 150, groups=plain, signal="defekt") is None


@pytest.mark.parametrize("extras, msg", [
    ("Pad", "must map"), ({"Nope": PAD}, "not another group"), ({"Console": PAD}, "not another group"),
    ({"Pad": "("}, "invalid regex"),
])
def test_extras_config_checked(extras, msg):
    groups = [GROUPS[0], {**GROUPS[1], "extras": extras}]
    with pytest.raises((ValueError, ConfigError), match=msg):
        check_groups(groups)
