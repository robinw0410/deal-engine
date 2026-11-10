"""v0.2.15: market.sample device_only: the market median of a group from listings the stored LLM classification
calls a single device (bundles pull the median up, games and accessories the word rules miss count along);
adjusted bundles when devices are thin, a flat value per game, sample_report() for the before/after comparison."""
import json
import sqlite3
from datetime import date, timedelta

import pytest

from deal_engine.core import config as config_mod
from deal_engine.core import history, insights, locale, market, pipeline
from deal_engine.core.config import ConfigError
from deal_engine.core.groups import games_count
from deal_engine.core.listing import normalize
from deal_engine.core.market import (bundle_adjust, estimate, estimate_groups, games_settings, games_value, refresh,
                                     sample_report)
from deal_engine.core.score import DEFAULTS, SHIPPING_DEFAULTS, compute

DE, EN = locale.get("de"), locale.get("en")
TODAY = date(2026, 6, 30)
PAD = {"name": "Controller", "match": r"controller", "exclude": r"\bps4 (slim|pro)\b|\+|\bmit\b|\bohne\b",
       "min": 10, "max": 80}
PS4 = {"name": "PS4", "match": r"\bps4\b", "exclude": r"^\W*controller", "min": 80, "max": 300,
       "extras": {"Controller": r"controller\w*"}}
SWITCH = {"name": "Switch", "match": r"\bswitch\b", "min": 100, "max": 400}
A = {"name": "Console A", "match": r"console a\b", "min": 60, "max": 300}
GROUPS = [PAD, PS4, SWITCH, A]
FLT = {"signal_regex": "defekt|broken"}
DEV = {"sample": "device_only"}
MARKET = {"PS4": {"median": 150, "p25": 140, "n": 30}, "Controller": {"median": 25, "p25": 20, "n": 20}}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("DEAL_ENGINE_TODAY", str(TODAY))


def item(title, price, cls=None, days_old=1, private=True, sid=None):
    it = {"title": title, "price": price, "private": private, "_published": str(TODAY - timedelta(days=days_old)),
          "source": "t", "source_id": sid or f"{title}-{price}-{days_old}"}
    if cls is not None:
        it["_cls"] = cls
    return it


def dev(title, price, grp, **kw):
    return item(title, price, (grp, 1, "device"), **kw)


def bun(title, price, grp, **kw):
    return item(title, price, (grp, 1, "bundle"), **kw)


# ------------------------------------------------------------------ default: unchanged

def test_default_is_sample_all_with_the_old_result_and_keys():
    items = [item("Console A 500GB", p) for p in (100, 110, 120, 130, 140)]
    items += [item("Console A mit 6 Spielen", 200), item("Hülle für Console A", 15), item("Console A defekt", 40)]
    want = {"median": 120, "p25": 110, "n": 5}
    assert estimate(items, A, GROUPS, FLT, None, DE) == want
    assert estimate(items, A, GROUPS, FLT, {"sample": "all"}, DE) == want
    # a classification on the items changes nothing with sample all
    tagged = [{**it, "_cls": ("Console A", 1, "bundle")} for it in items]
    assert estimate(tagged, A, GROUPS, FLT, {}, DE) == want
    new = refresh({}, {"Console A": items}, [A], FLT, {}, lambda s: None, DE)
    assert new["Console A"] == want and set(new) == {"_updated", "_ts", "Console A"}
    assert market.settings(None)["sample"] == "all" and market.sample_mode({}) == "all"
    assert games_settings({}) is None and games_value("PS4 mit 3 Spielen", {}, DE) == (0, 0)


def test_unknown_sample_is_a_config_error(tmp_path):
    with pytest.raises(ValueError):
        estimate([], A, GROUPS, FLT, {"sample": "devices"})
    cfg = {"_data": tmp_path, "_base": tmp_path,
           "searches": {"s": {"adapters": ["x"], "market": {"sample": "devices"}}}}
    with pytest.raises(ConfigError, match="market.sample"):
        config_mod.search(cfg, "s")
    cfg["searches"]["s"]["market"]["sample"] = "device_only"
    assert config_mod.search(cfg, "s")["market"]["sample"] == "device_only"


# ------------------------------------------------------------------ device_only

def test_device_only_counts_only_classified_single_devices_of_the_group():
    items = [dev("Console A 500GB", p, "Console A") for p in (100, 110, 120, 130, 140, 150, 160, 170)]
    noise = [item("Console A 1TB", 90),                                   # not classified yet
             item("Console A 1TB", 90, None),
             bun("Console A Set komplett", 250, "Console A"),              # bundle
             item("Console A Spiel", 20, (None, 1, "accessory")),
             item("Console A Laufwerk", 30, (None, 1, "part")),
             item("Console A Poster", 10, (None, 1, "other")),
             item("Console A 500GB", 95, ("Console A", 2, "device")),      # two units
             item("Console A 500GB", 95, ("Switch", 1, "device")),         # implausible: Switch does not match
             item("Console A Switch", 95, ("Switch", 1, "device")),        # another group
             item("Console A 500GB", 95, "device"),                        # malformed
             dev("Console A defekt", 60, "Console A"),                     # defect signal
             dev("Console A Bastler", 60, "Console A"),                    # market_exclude of the locale
             dev("Console A 500GB", 20, "Console A"),                      # below the group's range
             dev("Console A 500GB", 999, "Console A"),                     # above
             dev("Console A 500GB", None, "Console A")]
    want = {"median": 135, "p25": 120, "n": 8, "sample": "device_only", "n_device": 8, "n_bundle": 0}
    assert estimate(items + noise, A, GROUPS, FLT, DEV, DE) == want
    assert estimate(items, A, GROUPS, FLT, DEV, DE) == want
    # nothing classified: no value, however many listings there are
    assert estimate([item("Console A 500GB", 100)] * 20, A, GROUPS, FLT, DEV, DE) is None
    cs = market.classified_sample(items + noise, A, GROUPS, FLT, DEV, DE)
    assert len(cs["device"]) == 8 and [r[0] for r in cs["bundle"]] == [250]
    assert cs["unclassified"] == 4   # the two without, the implausible and the malformed one


def test_device_only_keeps_fresh_private_and_min_n():
    stale = [dev("Console A", 180, "Console A", days_old=60, private=False) for _ in range(10)]
    fresh = [dev("Console A", 100, "Console A", days_old=2, private=False) for _ in range(8)]
    assert estimate(stale + fresh, A, GROUPS, FLT, DEV, DE)["median"] == 100
    priv = [dev("Console A", 110, "Console A", days_old=60) for _ in range(5)]
    assert estimate(stale + priv, A, GROUPS, FLT, DEV, DE)["median"] == 110
    assert estimate(stale[:4], A, GROUPS, FLT, DEV, DE) is None                      # below min_n
    assert estimate(stale[:4], A, GROUPS, FLT, {**DEV, "min_n": 4}, DE)["n"] == 4
    # fewer than device_min_n devices and no bundles: still a device_only value from min_n on
    assert estimate(stale[:6], A, GROUPS, FLT, DEV, DE) == {
        "median": 180, "p25": 180, "n": 6, "sample": "device_only", "n_device": 6, "n_bundle": 0}


def test_a_classified_device_with_games_is_a_bundle():
    """The word rule (has_extras) overrules a device classification: "mit 6 Spielen" is no single unit."""
    items = [dev("Console A", 150, "Console A") for _ in range(8)] + [dev("Console A mit 6 Spielen", 290, "Console A")] * 8
    m = estimate(items, A, GROUPS, FLT, DEV, DE)
    assert (m["median"], m["n"], m["sample"]) == (150, 8, "device_only")
    cs = market.classified_sample(items, A, GROUPS, FLT, DEV, DE)
    assert len(cs["device"]) == 8 and len(cs["bundle"]) == 8


def test_bundles_pull_the_median_up_and_device_only_removes_them():
    """The observed pattern: devices around 150, bundles around 180, 43 % bundles: mixed about 167."""
    devices = [135, 135, 150, 150, 150, 150, 167, 167]
    bundles = [175, 175, 180, 180, 190, 190]
    items = [dev("Console A 500GB", p, "Console A") for p in devices]
    items += [bun("Console A 500GB Set komplett", p, "Console A") for p in bundles]   # the word rules see a unit
    assert round(len(bundles) / len(items), 2) == 0.43
    mixed = estimate(items, A, GROUPS, FLT, {}, DE)
    only = estimate(items, A, GROUPS, FLT, DEV, DE)
    assert mixed == {"median": 167, "p25": 150, "n": 14}
    assert only == {"median": 150, "p25": 150, "n": 8, "sample": "device_only", "n_device": 8, "n_bundle": 0}


# ------------------------------------------------------------------ games

@pytest.mark.parametrize("title, n, eur", [
    ("Nintendo Switch OLED mit 3 Spielen", 3, 15),
    ("PS4 Slim + 2 Controller + 6 Spiele", 6, 30),
    ("Nintendo Switch mit Spielen", 2, 10),
    ("PS4 ohne Spiele", 0, 0),
])
def test_games_count_and_flat_value(title, n, eur):
    assert games_count(title, DE) == n
    assert games_value(title, DEV, DE) == (eur, n)
    assert games_value(title, {}, DE) == (0, 0)   # without the setting games stay 0


@pytest.mark.parametrize("title, loc, n", [
    ("PS4 mit drei Spielen", DE, 3), ("PS4 inkl. Spiel", DE, 1), ("PS4 mit 1 Spiel", DE, 1),
    ("PS4 keine Spiele dabei", DE, 0), ("PS4 ohne Controller und Spiele", DE, 0),
    ("PS4 + 2 Controller und Spiele", DE, 2), ("PS4 mit 2 Controllern, 3 Spiele", DE, 3),
    ("PS4 mit 3 Spielen + 2 Games", DE, 5), ("PS4 mit 5 PS4-Spielen", DE, 5), ("PS4 3 original PS4 Spiele", DE, 3),
    ("PS4 mit Games", DE, 2), ("PS4 mit vielen Spielen", DE, 2), ("PS4 mit Spielesammlung", DE, 2),
    ("PS4 mit 12 Spielen", DE, 12), ("PS4 ohne OVP 3 Spiele", DE, 3),
    # no count: model numbers (default in a with-clause, nothing without one), a single title without
    # the word, other words
    ("Konsole mit PlayStation 4 Spielen", DE, 2), ("Konsole + Xbox 360 Spiele", DE, 2), ("PS4 mit FC 24 Spiel", DE, 1),
    ("PlayStation 4 Spiele", DE, 0), ("Xbox 360 Spiele", DE, 0), ("PS4 viele Spiele", DE, 0),
    ("Switch + Zelda", DE, 0), ("Sony Spielekonsole PS4", DE, 0), ("PS4 Spiele-Konsole 500GB", DE, 0),
    ("PS4 zum Spielen bereit", DE, 0), ("Game Boy Color", DE, 0), ("PS4 mit 2 Controllern", DE, 0),
    ("Switch OLED with 3 games", EN, 3), ("PS4 + 6 games", EN, 6), ("Switch with games", EN, 2),
    ("PS4 with two games", EN, 2), ("PS4 with game", EN, 1), ("PS4 no games", EN, 0),
    ("PS4 without controller or games", EN, 0), ("PS4 game console", EN, 0), ("Xbox Game Pass", EN, 0),
    ("PS4 mit 3 Spielen", EN, 0),   # German words are not English
])
def test_games_count(title, loc, n):
    assert games_count(title, loc) == n


def test_games_settings():
    assert games_count("PS4 mit Spielen", DE, default=4) == 4
    assert games_value("PS4 mit Spielen", {**DEV, "games_default": 3, "game_value": 4}, DE) == (12, 3)
    assert games_value("PS4 mit 9 Spielen", {**DEV, "game_value_max": 20}, DE) == (20, 9)
    assert games_value("PS4 mit 9 Spielen", {**DEV, "game_value_max": None}, DE) == (45, 9)
    assert games_value("PS4 mit 3 Spielen", {**DEV, "game_value": 2.5}, DE) == (7.5, 3)
    # game_value alone switches the flat value on for the evaluation, 0 switches it off
    assert games_value("PS4 mit 3 Spielen", {"game_value": 5}, DE) == (15, 3)
    assert games_value("PS4 mit 3 Spielen", {**DEV, "game_value": 0}, DE) == (0, 0)
    assert games_settings(DEV) == (5, 30, 2)


# ------------------------------------------------------------------ adjusted bundles

def test_bundle_adjust():
    full = "PS4 Slim + 2 Controller + 6 Spiele"
    assert bundle_adjust(full, 230, PS4, MARKET, DEV, DE) == 230 - 25 - 30   # one controller belongs to the console
    assert bundle_adjust("PS4 mit 3 Spielen", 170, PS4, MARKET, DEV, DE) == 155
    assert bundle_adjust("PS4 mit Spielen", 165, PS4, {}, DEV, DE) == 155
    # nothing to deduct, or controllers without a market price: the bundle cannot be valued
    assert bundle_adjust("PS4 ohne Spiele", 150, PS4, MARKET, DEV, DE) is None
    assert bundle_adjust("PS4 Set komplett", 150, PS4, MARKET, DEV, DE) is None
    assert bundle_adjust(full, 230, PS4, {}, DEV, DE) is None
    assert bundle_adjust(full, 230, PS4, {"Controller": {"n": 3}}, DEV, DE) is None
    # the Switch group has no extras: only the games
    assert bundle_adjust("Nintendo Switch OLED mit 3 Spielen", 250, SWITCH, MARKET, DEV, DE) == 235
    assert bundle_adjust("Nintendo Switch mit Spielen", 250, SWITCH, MARKET, DEV, DE) == 240


def ps4_items(n_dev=5):
    devices = [dev("PS4 500GB", p, "PS4") for p in (140, 150, 150, 155, 160, 150, 150, 150)[:n_dev]]
    bundles = [bun("PS4 Slim + 2 Controller + 6 Spiele", 230, "PS4"),      # 230 - 1 x 25 - 30 = 175
               bun("PS4 mit 3 Spielen", 170, "PS4"),                       # 155
               dev("PS4 mit Spielen", 165, "PS4"),                         # device by the model, games by the rule: 155
               bun("PS4 ohne Spiele", 150, "PS4"),                         # nothing to deduct: left out
               bun("PS4 Set komplett", 150, "PS4"),
               bun("PS4 mit 6 Spielen", 105, "PS4"),                       # 75: below the range after the adjustment
               bun("PS4 Pro mit 3 Spielen", 330, "PS4"),                   # 315: above
               item("PS4 mit 3 Spielen", 170)]                             # not classified
    return devices + bundles


def test_fallback_adjusted_bundles_below_device_min_n():
    m = estimate(ps4_items(), PS4, GROUPS, FLT, DEV, DE, market=MARKET)
    assert m == {"median": 155, "p25": 150, "n": 8, "sample": "adjusted_bundles", "n_device": 5, "n_bundle": 3}
    # enough devices: bundles stay out
    m = estimate(ps4_items(8), PS4, GROUPS, FLT, DEV, DE, market=MARKET)
    assert (m["sample"], m["n"], m["n_device"], m["n_bundle"]) == ("device_only", 8, 8, 0)
    m = estimate(ps4_items(), PS4, GROUPS, FLT, {**DEV, "device_min_n": 5}, DE, market=MARKET)
    assert (m["sample"], m["n"]) == ("device_only", 5)
    # without a controller price the controller bundle is left out, the game bundles stay
    m = estimate(ps4_items(), PS4, GROUPS, FLT, DEV, DE)
    assert (m["sample"], m["n_device"], m["n_bundle"]) == ("adjusted_bundles", 5, 2)
    # fewer than min_n in total: no value
    assert estimate(ps4_items(1), PS4, GROUPS, FLT, DEV, DE, market=MARKET) is None
    assert estimate(ps4_items(2), PS4, GROUPS, FLT, DEV, DE, market=MARKET)["n"] == 5


def test_refresh_uses_the_fresh_controller_median_whatever_the_group_order():
    pads = [dev("Controller schwarz", p, "Controller") for p in (20, 22, 25, 25, 25, 25, 28, 30)]
    by = {"PS4": ps4_items(), "Controller": pads}
    old = {"_updated": "2026-06-29", "Controller": {"median": 70, "p25": 50, "n": 9}}
    for groups in ([PAD, PS4], [PS4, PAD]):
        logs = []
        new = refresh(old, by, groups, FLT, DEV, logs.append, DE)
        assert new["Controller"] == {"median": 25, "p25": 25, "n": 8, "sample": "device_only",
                                     "n_device": 8, "n_bundle": 0, "date": str(TODAY)}
        assert new["PS4"] == {"median": 155, "p25": 150, "n": 8, "sample": "adjusted_bundles",
                              "n_device": 5, "n_bundle": 3, "date": str(TODAY)}
        assert any("PS4: median 155 (n=8), adjusted_bundles: 5 devices + 3 adjusted bundles" in s for s in logs)
    # no new controller value: the previous one is used (230 - 130 - 30 = 70, below the group's range)
    old = {"_updated": "2026-06-29", "Controller": {"median": 130, "p25": 50, "n": 9}}
    new = refresh(old, {"PS4": ps4_items()}, [PS4, PAD], FLT, DEV, lambda s: None, DE)
    assert new["Controller"] == old["Controller"]
    assert (new["PS4"]["n_device"], new["PS4"]["n_bundle"]) == (5, 2)
    # too little data: the previous value stays as it is
    old_ps4 = {"median": 170, "p25": 150, "n": 40}
    new = refresh({**old, "PS4": old_ps4}, {"PS4": ps4_items(1)[:1]}, [PS4, PAD], FLT, DEV, lambda s: None, DE)
    assert new["PS4"] == old_ps4


def test_estimate_groups_with_extras_referring_to_each_other():
    a = {"name": "A", "match": r"\ba\b", "extras": {"B": r"\bb\b"}}
    b = {"name": "B", "match": r"\bb\b", "extras": {"A": r"\ba\b"}}
    items = [dev("a", 100, "A")] * 4 + [bun("a mit 2 Spielen", 110, "A")] * 4
    out = estimate_groups({}, {"A": items, "B": [bun("b mit 2 Spielen", 60, "B")] * 5}, [a, b], {}, DEV, DE)
    assert out["A"]["n"] == 8 and out["B"] == {"median": 50, "p25": 50, "n": 5, "sample": "adjusted_bundles",
                                              "n_device": 0, "n_bundle": 5}


# ------------------------------------------------------------------ evaluation of a bundle offer

def select(title, price, mc=None, signal="defekt"):
    it = normalize({"source_id": "1", "url": "https://example.org/1", "title": title, "price": price,
                    "published": str(TODAY), "shipping_possible": True, "shipping_cost_eur": 0}, "test")
    sc = {"_locale": "de", "filters": {"signal_regex": signal}, "market": {"groups": [PAD, PS4], **(mc or {})}}
    cands, _ = pipeline.select({"1": it}, set(), {}, MARKET, sc, lambda s: None, adapter_name="test")
    return cands[0] if cands else None


def test_select_adds_the_flat_value_of_the_games():
    title = "PS4 Slim + 2 Controller + 6 Spiele"
    base = 128 + 2 * 20   # min(p25, median x 0.85) of the device and of each controller
    old = select(title, 100)
    assert old["market_resale_estimate"] == base and "market_games" not in old
    assert select(title, 100, {"sample": "all"}) == old
    new = select(title, 100, DEV)
    assert new["market_games"] == {"count": 6, "value": 30}
    assert new["market_resale_estimate"] == base + 30
    assert new["market_extras"] == old["market_extras"]
    # threshold (flip ratio 0.7): (150 + 2 x 25) x 0.7 = 140, with the games (150 + 50 + 30) x 0.7 = 161
    assert select(title, 150) is None and select(title, 150, DEV) is not None and select(title, 165, DEV) is None
    # game_value alone is enough, "ohne Spiele" and titles without games get nothing
    assert select("PS4 mit 3 Spielen", 80, {"game_value": 4})["market_games"] == {"count": 3, "value": 12}
    for t in ("PS4 ohne Spiele", "PS4 500GB"):
        c = select(t, 80, DEV)
        assert "market_games" not in c and c["market_resale_estimate"] == 128
    assert "market_games" in pipeline.CARRY


def test_score_names_the_games_when_the_resale_cap_applies():
    c = {**DEFAULTS, **SHIPPING_DEFAULTS, "_loc": DE}
    base = {"title": "PS4 Slim + 2 Controller + 6 Spiele", "price": 115, "market_price": 300, "repair_hours": 1,
            "repair_parts_eur": 0, "shipping_cost_eur": 0, "risk": "low", "deal_type": "flip"}
    pads = [{"group": "Controller", "count": 2, "median": 25, "resale": 20}]
    plain = compute({**base, "market_resale_estimate": 168, "market_extras": pads}, c)
    games = compute({**base, "market_resale_estimate": 198, "market_extras": pads,
                     "market_games": {"count": 6, "value": 30}}, c)
    assert games["profit"] - plain["profit"] == round(198 * 1.05) - round(168 * 1.05)
    assert "(inkl. 2 × Controller à 20 €, Spiele (6) pauschal 30 €)" in games["text"]
    assert "(inkl. 2 × Controller à 20 €)" in plain["text"] and "Spiele" not in plain["text"]
    only = compute({**base, "market_resale_estimate": 158, "market_games": {"count": 6, "value": 30}}, c)
    assert "(inkl. Spiele (6) pauschal 30 €)" in only["text"]
    en = compute({**base, "market_resale_estimate": 158, "market_games": {"count": 6, "value": 30}}, {**c, "_loc": EN})
    assert "(incl. games (6) at a flat 30 €)" in en["text"]
    # cap not binding: the price is the evaluator's; the games in the market estimate are named all the same
    low = compute({**base, "market_price": 150, "market_resale_estimate": 198,
                   "market_games": {"count": 6, "value": 30}}, c)
    assert "Verkauf 150 € (Marktschätzung 198 € inkl. Spiele (6) pauschal 30 €) − Kauf" in low["text"]
    no_games = compute({**base, "market_price": 150, "market_resale_estimate": 198}, c)
    assert "Spiele" not in no_games["text"] and "Marktschätzung" not in no_games["text"]
    # the note changes no number
    assert {k: v for k, v in low.items() if k != "text"} == {k: v for k, v in no_games.items() if k != "text"}
    en = compute({**base, "market_price": 150, "market_resale_estimate": 198,
                  "market_games": {"count": 6, "value": 30}}, {**c, "_loc": EN})
    assert "(market estimate 198 € incl. games (6) at a flat 30 €)" in en["text"]
    # no market estimate, or a value of 0: nothing went into anything, nothing is said
    for extra in ({"market_games": {"count": 6, "value": 30}}, {"market_resale_estimate": 198,
                                                                "market_games": {"count": 6, "value": 0}}):
        assert "Spiele" not in compute({**base, "market_price": 150, **extra}, c)["text"]


def test_insights_adds_the_games_once_per_run_and_drops_them_without_the_setting(tmp_path, monkeypatch):
    P = {"state": tmp_path / "state.json", "history": tmp_path / "h.db", "market": tmp_path / "m.json"}
    history.connect(P["history"]).close()
    P["market"].write_text(json.dumps(MARKET))
    monkeypatch.setattr(insights.history, "sold_by_group", lambda con, n, w: {})
    P["state"].write_text(json.dumps({"listings": [
        {"id": "x", "title": "PS4 Slim + 2 Controller + 6 Spiele", "price": 100},
        {"id": "y", "title": "PS4 500GB", "price": 100}]}))

    def run(mc):
        sc = {"_name": "s", "_locale": "de", "track": True, "market": {"groups": [PAD, PS4], **mc}}
        insights.apply({}, sc, P, log=lambda *a: None)
        return json.loads(P["state"].read_text())["listings"]

    for _ in range(3):
        x, y = run(DEV)
        assert x["market_games"] == {"count": 6, "value": 30}
        assert x["market_resale_estimate"] == 128 + 2 * 20 + 30 and x["market_resale_estimate_ask"] == 128
        assert "market_games" not in y and y["market_resale_estimate"] == 128
    x, _ = run({})
    assert "market_games" not in x and x["market_resale_estimate"] == 128 + 2 * 20


# ------------------------------------------------------------------ sample_report

def history_db(path, rows, search="s"):
    """rows: (uid, title, price, cls or None, extra listing columns)."""
    con = history.connect(path)
    with con:
        for uid, title, price, cls, extra in rows:
            col = {"private": 1, "published": str(TODAY - timedelta(days=3)), "defect": 0,
                   "last_seen": str(TODAY - timedelta(days=1)), "search": search, **extra}
            con.execute("""INSERT INTO listing(uid, source, source_id, search, grp, title, defect, published,
                           first_seen, last_seen, first_price, price, private) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (uid, "t", uid, col["search"], None, title, col["defect"], col["published"],
                         col["published"], col["last_seen"], price, price, col["private"]))
            if cls:
                con.execute("INSERT INTO classify VALUES (?,?,?,?,?,?)",
                            (uid, col.get("cls_title", title), *cls, str(TODAY)))
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()


def test_sample_report_on_a_read_only_history_db(tmp_path):
    db = tmp_path / "history.db"
    devices = [135, 135, 150, 150, 150, 150, 167, 167]
    bundles = [175, 175, 180, 180, 190, 190]
    rows = [(f"t-d{i}", "Console A 500GB", p, ("Console A", 1, "device"), {}) for i, p in enumerate(devices)]
    rows += [(f"t-b{i}", "Console A 500GB Set komplett", p, ("Console A", 1, "bundle"), {}) for i, p in enumerate(bundles)]
    rows += [("t-u1", "Console A 1TB", 160, None, {}),                                              # not classified
             ("t-u2", "Console A 1TB neu", 160, ("Console A", 1, "device"), {"cls_title": "Console A 1TB"}),   # title changed
             ("t-x1", "Console A 500GB", 60, ("Console A", 1, "device"), {"defect": 1}),
             ("t-x2", "Console A 500GB", 60, ("Console A", 1, "device"), {"last_seen": str(TODAY - timedelta(days=40))}),
             ("t-x3", "Console A 500GB", 60, ("Console A", 1, "device"), {"search": "other"}),
             ("t-x4", "Console A 500GB", None, ("Console A", 1, "device"), {})]
    rows += [(f"t-p{i}", "PS4 500GB", p, ("PS4", 1, "device"), {}) for i, p in enumerate((140, 150, 150, 155, 160))]
    rows += [("t-pb1", "PS4 Slim + 2 Controller + 6 Spiele", 230, ("PS4", 1, "bundle"), {}),
             ("t-pb2", "PS4 mit 3 Spielen", 170, ("PS4", 1, "bundle"), {}),
             ("t-pb3", "PS4 mit Spielen", 165, ("PS4", 1, "device"), {})]
    rows += [(f"t-c{i}", "Controller schwarz", p, ("Controller", 1, "device"), {})
             for i, p in enumerate((20, 22, 25, 25, 25, 25, 28, 30))]
    history_db(db, rows)
    before_bytes = db.read_bytes()
    sc = {"_name": "s", "_locale": "de", "filters": FLT, "market": {"groups": [PS4, PAD, A]}}

    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM listing")
    rep = sample_report(con, sc, days=30, loc=None)
    assert con.total_changes == 0
    con.close()
    assert db.read_bytes() == before_bytes
    assert [r["group"] for r in rep] == ["PS4", "Controller", "Console A"]
    assert all(set(r) == {"group", "before", "after", "device", "bundle", "bundle_share", "unclassified"} for r in rep)
    ps4, pad, a = rep
    assert a == {"group": "Console A",
                 "before": {"median": 164, "p25": 150, "n": 16},     # all 14 and the two unclassified at 160
                 "after": {"median": 150, "p25": 150, "n": 8, "sample": "device_only", "n_device": 8, "n_bundle": 0},
                 "device": {"median": 150, "n": 8}, "bundle": {"median": 180, "n": 6},
                 "bundle_share": 0.429, "unclassified": 2}
    assert pad["before"] == {"median": 25, "p25": 25, "n": 8} and pad["after"]["sample"] == "device_only"
    assert pad["bundle"] == {"median": None, "n": 0} and pad["bundle_share"] == 0
    # PS4: the word rules count the five single units; device_only adds the three adjusted bundles
    assert ps4["before"] == {"median": 150, "p25": 150, "n": 5}
    assert ps4["after"] == {"median": 155, "p25": 150, "n": 8, "sample": "adjusted_bundles", "n_device": 5, "n_bundle": 3}
    assert ps4["device"] == {"median": 150, "n": 5} and ps4["bundle"] == {"median": 170, "n": 3}
    assert ps4["bundle_share"] == 0.375 and ps4["unclassified"] == 0

    # the search's own setting is used; a shorter period and another reference day
    con = history.connect_ro(db)
    sc2 = {**sc, "market": {"groups": [PS4, PAD, A], "sample": "device_only", "device_min_n": 3}}
    assert sample_report(con, sc2)[0]["after"]["sample"] == "device_only"
    assert all(r["before"] is None and r["after"] is None and r["device"]["n"] == 0
               for r in sample_report(con, sc, days=30, today=TODAY + timedelta(days=60)))
    assert sample_report(con, {**sc, "_name": "none"})[2] == {
        "group": "Console A", "before": None, "after": None, "device": {"median": None, "n": 0},
        "bundle": {"median": None, "n": 0}, "bundle_share": None, "unclassified": 0}
    text = market.format_sample_report(rep, 30)
    assert "Console A" in text and "adjusted_bundles" in text and "43 %" in text
    con.close()


def test_market_sample_command(tmp_path, capsys):
    from deal_engine.__main__ import main
    cfgf = tmp_path / "config.yaml"
    cfgf.write_text(json.dumps({"data_dir": str(tmp_path / "data"), "searches": {"s": {
        "adapters": ["x"], "market": {"groups": [A]}}}}))
    assert main(["--config", str(cfgf), "market-sample", "s"]) == 1      # no history.db
    assert not (tmp_path / "data" / "state" / "history.db").exists()
    history_db(tmp_path / "data" / "state" / "history.db",
               [(f"t-{i}", "Console A", 150, ("Console A", 1, "device"), {}) for i in range(8)])
    capsys.readouterr()
    assert main(["--config", str(cfgf), "market-sample", "s", "--days", "14"]) == 0
    out = capsys.readouterr().out
    assert "Console A" in out and "device_only" in out and "last 14 days" in out


# ------------------------------------------------------------------ update_market

class Adapter:
    name = "t"

    def __init__(self, by_keyword):
        self.by_keyword, self.warnings = by_keyword, []

    def search(self, query):
        return [{"source_id": sid, "url": f"https://example.org/{sid}", "title": title, "price": price,
                 "published": str(TODAY - timedelta(days=2)), "private": True}
                for sid, title, price in self.by_keyword.get(query.get("keyword"), [])]


def market_setup(tmp_path, mc=None, track=False):
    cfg = {"_data": tmp_path, "_base": tmp_path}
    sc = {"_name": "s", "_locale": "de", "adapters": ["t"], "filters": FLT, "track": track,
          "market": {"groups": [{**A, "keyword": "console a"}], **(DEV if mc is None else mc)}}
    P = config_mod.paths(cfg, "s", "t")
    hits = [(f"d{i}", "Console A 500GB", p) for i, p in enumerate((135, 135, 150, 150, 150, 150, 167, 167))]
    hits += [(f"b{i}", "Console A 500GB Set komplett", p) for i, p in enumerate((175, 175, 180, 180, 190, 190))]
    hits += [("u1", "Console A 1TB", 90)]
    return cfg, sc, P, Adapter({"console a": hits})


def classify_all(db, hits):
    con = history.connect(db)
    with con:
        for sid, title, _ in hits:
            if sid.startswith("u"):
                continue
            kind = "bundle" if sid.startswith("b") else "device"
            con.execute("INSERT INTO classify VALUES (?,?,?,?,?,?)", (f"t-{sid}", title, "Console A", 1, kind, str(TODAY)))
    con.close()


def test_update_market_attaches_the_stored_classification(tmp_path, monkeypatch):
    cfg, sc, P, adapter = market_setup(tmp_path)
    classify_all(P["history"], adapter.by_keyword["console a"])
    seen = {}
    real = pipeline.market_refresh

    def spy(old, by_group, *a, **kw):
        seen.update(by_group)
        return real(old, by_group, *a, **kw)
    monkeypatch.setattr(pipeline, "market_refresh", spy)
    logs = []
    new = pipeline.update_market(cfg, sc, adapter, P, logs.append)
    cls = {it["source_id"]: it["_cls"] for it in seen["Console A"]}
    assert cls["d0"] == ("Console A", 1, "device") and cls["b0"] == ("Console A", 1, "bundle") and cls["u1"] is None
    assert new["Console A"] == {"median": 150, "p25": 150, "n": 8, "sample": "device_only", "n_device": 8,
                                "n_bundle": 0, "date": str(TODAY)}
    assert json.loads(P["market"].read_text())["Console A"] == new["Console A"]
    assert any("market sample device_only: 14 of 15 listings classified" in s for s in logs)
    # a changed title invalidates the stored classification
    adapter.by_keyword["console a"][0] = ("d0", "Console A 500GB wie neu", 135)
    P["market"].unlink()
    new = pipeline.update_market(cfg, sc, adapter, P, lambda s: None)
    assert seen["Console A"][0]["_cls"] is None
    # seven devices left; the bundles name nothing that could be deducted, so they stay out
    assert (new["Console A"]["n"], new["Console A"]["sample"]) == (7, "device_only")


def test_update_market_sample_all_reads_no_classification(tmp_path, monkeypatch):
    cfg, sc, P, adapter = market_setup(tmp_path, mc={})
    classify_all(P["history"], adapter.by_keyword["console a"])
    monkeypatch.setattr(history, "attach_classification", lambda *a, **kw: pytest.fail("not with sample all"))
    new = pipeline.update_market(cfg, sc, adapter, P, lambda s: None)
    assert new["Console A"] == {"median": 167, "p25": 150, "n": 15}   # devices, bundles and the unclassified one


@pytest.mark.parametrize("db", ["missing", "broken", "empty", "no_table"])
def test_update_market_survives_a_missing_or_broken_history_db(tmp_path, db):
    cfg, sc, P, adapter = market_setup(tmp_path)
    P["history"].parent.mkdir(parents=True, exist_ok=True)
    if db == "broken":
        P["history"].write_bytes(b"this is not a database " * 200)
    elif db == "empty":
        P["history"].write_bytes(b"")
    elif db == "no_table":
        sqlite3.connect(P["history"]).close()
        con = sqlite3.connect(P["history"])
        con.execute("CREATE TABLE other(x)")
        con.commit()
        con.close()
    old = {"_updated": "2026-06-01", "Console A": {"median": 170, "p25": 150, "n": 40}}
    P["market"].write_text(json.dumps(old))
    before = P["history"].read_bytes() if P["history"].exists() else None
    logs = []
    new = pipeline.update_market(cfg, sc, adapter, P, logs.append)
    assert new["Console A"] == old["Console A"] and new["_updated"] == str(TODAY)   # nothing classified: old value kept
    assert any("Console A: too little data (device 0, bundle 0, unclassified 15), keeping previous value "
               "(sample all, undated)" in s for s in logs)
    assert (P["history"].read_bytes() if P["history"].exists() else None) == before   # never created or changed
    if db in ("broken", "no_table"):
        assert any("not readable" in s for s in logs)
    # with tracking the database is created by the tracking, the market update still runs
    sc["track"] = True
    P["market"].write_text(json.dumps(old))
    assert pipeline.update_market(cfg, sc, adapter, P, lambda s: None)["Console A"] == old["Console A"]


def test_attach_classification_is_all_or_nothing(tmp_path):
    items = [{"source": "t", "source_id": "1", "title": "Console A", "_cls": ("x", 1, "device")},
             {"source": "t", "title": "no id"}]
    db = tmp_path / "h.db"
    con = history.connect(db)
    con.execute("INSERT INTO classify VALUES ('t-1', 'Console A', 'Console A', 1, 'device', '2026-06-01')")
    con.commit()
    con.close()
    logs = []
    assert history.attach_classification(db, items, logs.append) == 0     # the second item has no id: nothing is used
    assert [it["_cls"] for it in items] == [None, None] and len(logs) == 1
    assert history.attach_classification(db, items[:1], logs.append) == 1
    assert items[0]["_cls"] == ("Console A", 1, "device")
    assert history.attach_classification(tmp_path / "none.db", items[:1]) == 0 and items[0]["_cls"] is None
    assert not (tmp_path / "none.db").exists()
