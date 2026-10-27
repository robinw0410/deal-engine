"""v0.2.3: the number in a model name ("PlayStation 5", "Xbox Elite 2") is not a bundle quantity, a quantity
right after it still counts ("PlayStation 4 2 Controller"), and "x2" / "×3" are quantities too."""
import pytest

from deal_engine.core.groups import bundle_qty, market_group

PAD = {"name": "DualSense", "match": r"dualsense|playstation\s*5|ps5", "min": 20, "max": 90}
XBOX = {"name": "Xbox Controller", "match": r"xbox", "min": 15, "max": 80}


@pytest.mark.parametrize("code", ["en", "de"])
@pytest.mark.parametrize("title", ["PlayStation 5 Controller", "PlayStation 5 Gamepad", "PlayStation 4 Controller white",
                                   "Playstation 4 Controller", "Sony PlayStation 5 Controller white"])
def test_playstation_number_is_not_a_quantity(code, title):
    assert bundle_qty(title, PAD, code) == 1


@pytest.mark.parametrize("code", ["en", "de"])
@pytest.mark.parametrize("title", ["Xbox 360 Controller", "Xbox One Controller", "Xbox Series X Controller",
                                   "Xbox Elite 2 Controller", "Xbox Elite Series 2 Controller"])
def test_xbox_model_names_are_not_a_quantity(code, title):
    assert bundle_qty(title, XBOX, code) == 1


@pytest.mark.parametrize("code", ["en", "de"])
@pytest.mark.parametrize("title, n", [("3 PS4 Controller", 3), ("2x DualSense", 2), ("2 PlayStation 5 Controller", 2),
                                      ("PlayStation 5 Controller 2x", 2), ("2 Xbox One Controller", 2),
                                      ("Xbox Controller 3x", 3)])
def test_real_bundles_still_count(code, title, n):
    assert bundle_qty(title, PAD, code) == n


def test_german_piece_count_after_playstation():
    assert bundle_qty("PlayStation 5 Controller 2 Stück", PAD, "de") == 2
    assert bundle_qty("PlayStation 5 Controller 3 Stk", PAD, "de") == 3


def test_single_playstation_controller_gets_a_market_group():
    assert market_group("PlayStation 5 Controller", 45, [PAD], loc="de") is PAD
    assert market_group("2 PlayStation 5 Controller", 90, [PAD], loc="de") is None


@pytest.mark.parametrize("code", ["en", "de"])
@pytest.mark.parametrize("title, n", [("PlayStation 4 2 Controller", 2), ("Playstation 5 Controller x2", 2),
                                      ("Controller x2", 2), ("DualSense ×3", 3), ("PS4 Controller x 2", 2),
                                      ("Xbox Elite Series 2 Controller x2", 2)])
def test_quantity_after_a_skipped_model_number_or_with_leading_x(code, title, n):
    assert bundle_qty(title, PAD, code) == n


@pytest.mark.parametrize("code", ["en", "de"])
@pytest.mark.parametrize("title", ["Controller x1", "Controller x25", "Xbox One X Controller", "Xbox Series X Controller",
                                   "Ryzen 7 5800X3D", "PS5 Controller V2"])
def test_leading_x_without_a_quantity(code, title):
    assert bundle_qty(title, PAD, code) == 1
