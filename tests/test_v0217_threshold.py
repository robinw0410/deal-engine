"""v0.2.17: the candidate threshold of select() uses the resale value instead of the raw asking median when
the group has enough cleaned sold prices (market.threshold_basis "resale", market.threshold_min_sold).

ref_unit = min(resale_from_ask, sold_estimate) / sale_factor, never above the median;
threshold = (ref_unit x qty + extras + games) x ratio. Too few sold prices, threshold_basis "median",
sold=None or a failed load: the median, exactly as before."""
import json

import pytest

from deal_engine import adapters
from deal_engine.core import clock, history, pipeline
from deal_engine.core import config as config_mod
from deal_engine.core.config import ConfigError
from deal_engine.core.listing import normalize
from deal_engine.core.market import check_settings
from plugins_fixture.helpers import listing, quiet, search_cfg, write_cfg

PAD = r"controller\w*|gamepads?|pads?"
GROUPS = [
    {"name": "Pad", "match": r"\bpad\b|controller", "exclude": r"\bkonsole\b|\+|\bmit\b", "bundle": True},
    {"name": "Console", "match": r"\bkonsole\b", "extras": {"Pad": PAD}},
]
MARKET = {"Console": {"median": 200, "p25": 180, "n": 30}, "Pad": {"median": 40, "p25": 36, "n": 20}}
# Console: resale_from_ask = min(180, 200 x 0.85) = 170; sold median 150 x 0.93 = 140 -> ref 140 / 0.85 = 164.7
SOLD = {"Console": {"p": [150] * 10, "d": [3] * 10}, "Pad": {"p": [30] * 10, "d": [2] * 10}}
REF_CONSOLE = 140 / 0.85
# Pad: ask min(36, 34) = 34; sold 30 x 0.93 = 28 -> ref 28 / 0.85 = 32.9


def sc_of(market=None, insights=None):
    sc = {"_locale": "de", "filters": {"signal_regex": "defekt"}, "market": {"groups": GROUPS, **(market or {})}}
    if insights:
        sc["insights"] = insights
    return sc


def select(title, price, sold=SOLD, market=None, insights=None, log=None):
    it = normalize({"source_id": "1", "url": "https://example.org/1", "title": title, "price": price,
                    "published": clock.today_str(), "shipping_possible": True, "shipping_cost_eur": 0}, "test")
    cands, _ = pipeline.select({"1": it}, set(), {}, MARKET, sc_of(market, insights), log or quiet,
                               adapter_name="test", sold=sold)
    return cands[0] if cands else None


# --- threshold_ref ----------------------------------------------------------------------------

def test_threshold_ref_resale_with_enough_sold():
    ref, basis = pipeline.threshold_ref(MARKET["Console"], SOLD["Console"]["p"], sc_of())
    assert basis == "resale" and ref == pytest.approx(REF_CONSOLE)


@pytest.mark.parametrize("prices", [None, [], [150] * 7])
def test_threshold_ref_median_without_enough_sold(prices):
    assert pipeline.threshold_ref(MARKET["Console"], prices, sc_of()) == (200, "median")


def test_threshold_ref_basis_median_setting():
    sc = sc_of({"threshold_basis": "median"})
    assert pipeline.threshold_ref(MARKET["Console"], SOLD["Console"]["p"], sc) == (200, "median")


def test_threshold_ref_min_sold_setting():
    sc = sc_of({"threshold_min_sold": 12})
    assert pipeline.threshold_ref(MARKET["Console"], [150] * 10, sc) == (200, "median")
    sc = sc_of({"threshold_min_sold": 3})
    # 3 sold prices: enough for threshold_min_sold, but below insights.min_sold (8) -> no sold estimate,
    # so no resale basis (review 0.2.17): the median, as without sold data
    assert pipeline.threshold_ref(MARKET["Console"], [150] * 3, sc) == (200, "median")


def test_threshold_ref_uses_insights_settings():
    # sold_factor 0.8 from the search's insights settings: 150 x 0.8 = 120 -> 120 / 0.85
    ref, _ = pipeline.threshold_ref(MARKET["Console"], [150] * 10, sc_of(insights={"sold_factor": 0.8}))
    assert ref == pytest.approx(120 / 0.85)
    # insights.min_sold above the sold count: no sold estimate -> median basis
    assert pipeline.threshold_ref(MARKET["Console"], [150] * 10, sc_of(insights={"min_sold": 20})) == (200, "median")


def test_threshold_ref_never_above_median():
    # rounding in resale_from_ask: round(101 x 0.85) = 86, 86 / 0.85 = 101.2 > 101 -> capped at the median
    m = {"median": 101, "n": 10}
    ref, basis = pipeline.threshold_ref(m, [500] * 10, sc_of())
    assert basis == "resale" and ref == 101
    # sold prices above the asking prices never raise it
    ref, _ = pipeline.threshold_ref(MARKET["Console"], [400] * 10, sc_of())
    assert ref <= 200


# --- select() ---------------------------------------------------------------------------------

def test_enough_sold_stricter_threshold():
    # flip_ratio 0.7: median 200 x 0.7 = 140, resale 164.7 x 0.7 = 115.3
    assert select("Konsole 1TB", 130, sold={}) is not None
    assert select("Konsole 1TB", 130) is None
    c = select("Konsole 1TB", 115)
    assert c is not None
    assert (c["market_threshold_basis"], c["market_threshold_ref"]) == ("resale", 165)
    assert c["market_median"] == 200   # shown median unchanged


def test_too_few_sold_as_before():
    sold = {"Console": {"p": [150] * 7, "d": []}}
    c = select("Konsole 1TB", 130, sold=sold)
    assert c is not None
    assert (c["market_threshold_basis"], c["market_threshold_ref"]) == ("median", 200)
    assert select("Konsole 1TB", 141, sold=sold) is None


def test_basis_median_as_before():
    c = select("Konsole 1TB", 130, market={"threshold_basis": "median"})
    assert c is not None and c["market_threshold_basis"] == "median"
    assert select("Konsole 1TB", 141, market={"threshold_basis": "median"}) is None


def test_defect_ratio():
    # defect_price_ratio 0.6: median 120, resale 164.7 x 0.6 = 98.8
    assert select("Konsole defekt", 110, sold=None) is not None
    assert select("Konsole defekt", 110) is None
    assert select("Konsole defekt", 98) is not None


def test_no_signal_regex_uses_max_price_ratio():
    it = normalize({"source_id": "1", "url": "https://example.org/1", "title": "Konsole", "price": 140,
                    "published": clock.today_str(), "shipping_possible": True, "shipping_cost_eur": 0}, "test")
    sc = {"_locale": "de", "market": {"groups": GROUPS}}
    # max_price_ratio 0.75: median 150, resale 123.5
    assert pipeline.select({"1": dict(it)}, set(), {}, MARKET, sc, quiet, sold=None)[0]
    assert not pipeline.select({"1": dict(it)}, set(), {}, MARKET, sc, quiet, sold=SOLD)[0]


def test_qty_more_than_one():
    # 3 pads, flip 0.7: median 3 x 40 x 0.7 = 84, resale 3 x 32.9 x 0.7 = 69.2
    c = select("3x Controller", 75, sold=None)
    assert c is not None and c["market_group"] == "Pad"
    assert select("3x Controller", 75) is None
    c = select("3x Controller", 69)
    assert c is not None and c["market_threshold_basis"] == "resale" and c["market_threshold_ref"] == 33


def test_extras_keep_their_median():
    # (ref + 2 x 40) x 0.7: median (200 + 80) x 0.7 = 196, resale (164.7 + 80) x 0.7 = 171.3
    assert select("Konsole + 2 Controller", 180, sold=None) is not None
    assert select("Konsole + 2 Controller", 180) is None
    c = select("Konsole + 2 Controller", 171)
    assert c is not None and c["market_extras"]


def test_sold_none_and_garbage():
    assert select("Konsole 1TB", 130, sold=None)["market_threshold_basis"] == "median"
    assert select("Konsole 1TB", 130, sold="broken")["market_threshold_basis"] == "median"
    assert select("Konsole 1TB", 130, sold={"Console": "broken"})["market_threshold_basis"] == "median"


def test_log_line_counts_groups():
    lines = []
    select("Konsole 1TB", 100, sold={"Console": SOLD["Console"]}, log=lines.append)
    assert "market threshold: 1 group(s) on the resale basis (Console), 1 on the median" in lines
    lines = []
    select("Konsole 1TB", 100, sold=None, log=lines.append)
    assert not any("market threshold" in s for s in lines)   # no sold data passed: nothing to report
    select("Konsole 1TB", 100, sold={}, log=lines.append)     # loading failed in collect(): all on the median
    assert "market threshold: 0 group(s) on the resale basis, 2 on the median" in lines


# --- settings -------------------------------------------------------------------------------------

def test_check_settings():
    check_settings({"threshold_basis": "resale", "threshold_min_sold": 8})
    check_settings({"threshold_basis": "median"})
    with pytest.raises(ValueError, match="threshold_basis"):
        check_settings({"threshold_basis": "sold"})
    for bad in (0, -1, 2.5, True, "8"):
        with pytest.raises(ValueError, match="threshold_min_sold"):
            check_settings({"threshold_min_sold": bad})


def test_config_validation(tmp_path):
    cfg = write_cfg(tmp_path, {"bad": search_cfg(market={"threshold_basis": "ask"})})
    with pytest.raises(ConfigError, match="threshold_basis"):
        config_mod.search(cfg, "bad")


# --- collect(): loading once, failures fall back to the median ------------------------------------

def _collect(tmp_path, monkeypatch, sold_fn, market=None, insights=None):
    rows = [listing(1, "Konsole 1TB", 130), listing(2, "Konsole 500GB", 100)]
    (tmp_path / "l.json").write_text(json.dumps(rows))
    cfg = write_cfg(tmp_path, {"s": search_cfg(locale="de", json_file={"path": "l.json"},
                                               filters={"signal_regex": "defekt"},
                                               market={"groups": GROUPS, **(market or {})},
                                               **({"insights": insights} if insights else {}))})
    sc = config_mod.search(cfg, "s")
    monkeypatch.setattr(pipeline, "update_market", lambda *a, **k: MARKET)
    monkeypatch.setattr(history, "sold_for_search", sold_fn, raising=False)
    lines = []
    c = pipeline.collect(cfg, sc, adapters.create("json_file", cfg, sc), lines.append)
    return c, lines


def test_collect_loads_sold_once(tmp_path, monkeypatch):
    calls = []

    def fake(db, sc, window_days=None, clean=True, log=print):
        calls.append((db, sc["_name"]))
        return SOLD

    c, lines = _collect(tmp_path, monkeypatch, fake)
    assert c["candidates"] == 1   # 130 above 115.3, 100 below
    assert len(calls) == 1 and str(calls[0][0]).endswith("history.db")


def test_collect_broken_loading_falls_back(tmp_path, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("disk on fire")

    c, lines = _collect(tmp_path, monkeypatch, broken)
    assert c["candidates"] == 2   # median threshold 140
    assert any("not loaded, median basis" in s and "disk on fire" in s for s in lines)


def test_collect_basis_median_does_not_load(tmp_path, monkeypatch):
    calls = []
    c, _ = _collect(tmp_path, monkeypatch, lambda *a, **k: calls.append(1) or SOLD, {"threshold_basis": "median"})
    assert c["candidates"] == 2 and not calls


def test_no_threshold_log_line_without_sold_data():
    """select() without sold= (plain calls, tests of other projects) logs nothing about the basis."""
    from deal_engine.core import pipeline as _p
    lines = []
    sc = {"_name": "t", "filters": {}, "market": {"groups": [{"name": "G", "match": "g", "min": 1, "max": 999}]}}
    _p.select({}, set(), {}, {"G": {"median": 100, "p25": 90, "n": 10}}, sc, log=lines.append)
    assert not any("market threshold" in s for s in lines)


def test_collect_does_not_load_sold_prices_when_sold_clean_is_off(tmp_path, monkeypatch):
    """insights.sold_clean false gives the old statistic (bundles, reposts): it must not move the threshold."""
    calls = []
    c, _ = _collect(tmp_path, monkeypatch, lambda *a, **k: calls.append(1) or SOLD, insights={"sold_clean": False})
    assert c["candidates"] == 2 and not calls   # median threshold 140, nothing loaded
