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
    assert c["market_extras"] == [{"group": "Pad", "count": 2, "median": 40, "resale": 34}]
    assert c["market_resale_estimate"] == 170 + 2 * 34   # min(p25 or median, median x 0.85) each
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


# review cases: the regex of a console's controller group, model numbers, missing/broken units, fillers
PS = r"controller\w*|dualshock\w*|dualsense\w*|gamepads?"


@pytest.mark.parametrize("title, n", [
    ("PS4 + 2 Controller + 6 Spiele", 2), ("PS5 + 2 Controller", 2), ("PS4 2 Spiele 1 Controller", 1),
    ("PS4 zwei Spiele und ein Controller", 1), ("PS4 + ein Controller", 1), ("PS4 3 Spiele, 2 Controller", 2),
    ("PS4 + Controller defekt", 0), ("PS4 Controller fehlt", 0), ("PS4 Slim 1 Controller fehlt", 0),
    ("PS4 + Controller kaputt", 0), ("PS4 + Controller ohne Funktion", 0), ("PS4 + Controller (Drift)", 0),
    ("PS4 + Controller mit Drift", 0), ("PS4 Controller nicht dabei", 0), ("PS4 keine Controller", 0),
    ("PS4 + 2 Controller (1 defekt)", 1), ("PS4 + 2 Controller, 1 ohne Funktion", 1),
    ("PS4 + 1 Controller + 1 Controller fehlt", 1), ("PS4 + 2 Controller + 6 Spiele | Stick-Drift", 2),
    ("PS4 + Controllerladestation", 0), ("PS4 + Controller-Ladestation + 2 Controller", 2),
    ("PS4 ohne OVP 2 Controller", 2), ("PS4 ohne Spiele mit 2 Controllern", 2), ("PS4 ohne Kabel und Controller", 0),
    ("PS4 + Controller x2", 2), ("PS4 + 2x Controller", 2),
    ("PS4 + DualShock 4 Controller", 1), ("PS4 + 2 DualShock 4 Controller", 2), ("PS4 mit 2 DualShock-4-Controllern", 2),
    ("PS4 Slim + PlayStation 4 Controller", 1), ("PS4 + PS 4 Controller", 1), ("PS5 + DualSense Controller", 1),
    ("PS5 + 2 DualSense Controller", 2), ("PS4 + zwei originale Dualshock Controller", 2),
    ("PS4 + 2 Original Sony Controller", 2), ("PS4 + 2 schwarze Controller", 2), ("PS4 + Controller + Controller", 2),
    ("Xbox One X + Kinect + 2 Controller", 2), ("PS4 Slim 500GB 2 Controller", 2), ("PS4 + 20 Controller", 8),
])
def test_extras_count_review_cases(title, n):
    assert extras_count(title, PS, DE) == n


@pytest.mark.parametrize("rx", ["", "   ", "a|", None])
def test_extras_regex_must_not_be_empty(rx):
    groups = [GROUPS[0], {**GROUPS[1], "extras": {"Pad": rx}}]
    with pytest.raises(ValueError):
        check_groups(groups)


def test_extras_forward_reference_allowed():
    check_groups([{"name": "Console", "match": "konsole", "extras": {"Pad": PAD}}, {"name": "Pad", "match": "pad"}])
