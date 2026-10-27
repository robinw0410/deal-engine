"""v0.2.5: devices with extras (games) stay out of the market statistics, comma lists after "with" are extras."""
import pytest

from deal_engine.core import locale
from deal_engine.core.groups import has_extras, is_accessory, market_group
from deal_engine.core.market import estimate

DE, EN = locale.get("de"), locale.get("en")
GROUPS = [{"name": "Console", "match": r"\bconsole\b|\bkonsole\b", "min": 50, "max": 400}]


@pytest.mark.parametrize("title, loc, expected", [
    ("Konsole mit 6 Spielen", DE, True),
    ("Konsole Slim + 2 Controller + 6 Spiele", DE, True),
    ("Konsole mit 2 Controllern und 3 Spielen", DE, True),
    ("Konsole inkl. FIFA 23", DE, True),
    ("Konsole + Zelda", DE, True),
    ("Konsole mit Spielen, Hülle und Tasche", DE, True),
    ("Konsole mit Controller", DE, False),
    ("Konsole ohne Spiele", DE, False),
    ("Konsole mit Controller ohne Spiele", DE, False),
    ("Spielekonsole 500GB", DE, False),
    ("FIFA 23 für Konsole", DE, False),          # the game is the listing, not an extra (no with-clause)
    ("Console with 3 games", EN, True),
    ("Console and Mario Kart", EN, True),
    ("Console without games", EN, False),
    ("Console with controller", EN, False),
])
def test_has_extras(title, loc, expected):
    assert has_extras(title, loc) is expected


@pytest.mark.parametrize("title", [
    "Konsole mit Spielen, Hülle und Tasche",
    "Konsole Lite mit 3 Spielen, Tasche",
    "Konsole Slim mit Controller, Kabel, Hülle",
    "Konsole OLED inkl. Hülle, Ladestation",
])
def test_comma_list_after_with_is_no_accessory(title):
    """Before 0.2.5 the comma needed a space before it: ", Hülle" stayed and made the bundle an accessory."""
    assert not is_accessory(title, loc=DE)


@pytest.mark.parametrize("title", ["Konsole Hülle", "Hülle, Tasche für Konsole", "Ladestation mit Kabel"])
def test_accessories_stay_accessories(title):
    assert is_accessory(title, loc=DE)


def test_market_group_skips_devices_with_extras():
    assert market_group("Konsole mit 6 Spielen", 150, GROUPS, loc=DE) is None
    assert market_group("Konsole mit Controller", 150, GROUPS, loc=DE)["name"] == "Console"


def test_estimate_counts_single_units_only():
    singles = [{"title": "Konsole 500GB", "price": p} for p in (100, 110, 120, 130, 140)]
    bundles = [{"title": "Konsole mit 6 Spielen", "price": p} for p in (250, 260, 270, 280, 290, 300)]
    est = estimate(singles + bundles, GROUPS[0], GROUPS, mc={"min_n": 3, "min_fresh": 99, "min_private": 99}, loc=DE)
    assert est == {"median": 120, "p25": 110, "n": 5}
