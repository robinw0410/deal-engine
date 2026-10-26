import pytest

from core.groups import bundle_qty, market_group, match_group

CONTROLLER = {"name": "DualSense", "match": "dualsense|ps5 controller", "min": 20, "max": 90}
CONSOLE = {"name": "PS5", "match": r"\bps5\b", "exclude": "controller|dualsense", "min": 250, "max": 600}
GROUPS = [CONSOLE, CONTROLLER]


@pytest.mark.parametrize("title,qty", [
    ("3 PS4 controllers", 3),
    ("DualSense 2x", 2),
    ("2x DualSense white", 2),
    ("five broken gamepads", 5),
    ("4 pcs DualSense", 4),
    ("Xbox Elite Series 2 controller", 1),   # model number, not a quantity
    ("PS4 controller", 1),
    ("DualSense controller V2", 1),
    ("DualSense controller", 1),
    ("DualSense 1x", 1),                     # 1 is not a bundle
])
def test_bundle_qty_controllers(title, qty):
    assert bundle_qty(title, CONTROLLER) == qty


def test_bundle_qty_only_for_bundle_groups():
    # "2 TB" or "PS5 2x games" on a console group is no quantity
    assert bundle_qty("PS5 2x games", CONSOLE) == 1


def test_market_group_excludes_bundles_accessories_and_outliers():
    assert market_group("DualSense controller", 45, GROUPS)["name"] == "DualSense"
    assert market_group("3x DualSense", 120, GROUPS) is None           # bundle
    assert market_group("charging station for DualSense", 15, GROUPS) is None   # accessory
    assert market_group("DualSense controller", 5, GROUPS) is None     # below the plausible range
    assert market_group("DualSense controller", 5, GROUPS, defect=True)["name"] == "DualSense"


@pytest.mark.parametrize("title,acc", [
    ("charging station for DualSense", True),
    ("case for Switch Lite", True),
    ("DualSense thumb grips set", True),
    ("Charger with cable for PS5", True),
    ("Switch Lite white with charger", False),      # accessory that comes with the device
    ("PS5 incl. cable + case", False),
    ("Steam Deck with case and charger", False),
])
def test_accessory_vs_device_with_accessories(title, acc):
    from core.groups import is_accessory
    assert is_accessory(title) is acc


def test_match_group_exclude():
    assert match_group("PS5 controller", GROUPS)["name"] == "DualSense"
    assert match_group("PS5 Disc Edition", GROUPS)["name"] == "PS5"
    assert match_group("Toaster", GROUPS) is None
