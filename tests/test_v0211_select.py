"""v0.2.11: category_caps[].category via the search's category_hook, priority_hook orders candidates and backlog."""
import pytest

from deal_engine.core import config as config_mod
from deal_engine.core import pipeline
from deal_engine.core.config import ConfigError
from deal_engine.core.listing import normalize
from plugins_fixture.helpers import listing, search_cfg, write_cfg

TODAY = "2026-06-30"
CAT, PRIO = "plugins_fixture.hooks:first_word", "plugins_fixture.hooks:starred"


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setenv("DEAL_ENGINE_TODAY", TODAY)
    pipeline._SELECT_HOOKS.clear()          # hooks are cached by spec; tests patch them
    yield
    pipeline._SELECT_HOOKS.clear()


def _items(rows):
    """rows: (title, published day of June 2026); source_id = index."""
    return {str(i): normalize(listing(str(i), title=t, published=f"2026-06-{d:02d}"), "a")
            for i, (t, d) in enumerate(rows)}


def _select(items, max_new=10, caps=(), backlog=None, state=(), **hooks):
    sc = {"filters": {}, "market": {}, "category_caps": list(caps), "max_new_per_run": max_new, "_locale": "en",
          **hooks}
    if backlog is not None:
        sc["backlog"] = backlog
    out, logs = [], []
    cands, post = pipeline.select(items, set(), {}, {}, sc, logs.append, adapter_name="a", discarded=out,
                                  state_listings=list(state))
    return [c["source_id"] for c in cands], post, sorted(c["source_id"] for c in out), logs


def test_category_caps_by_hook():
    # 6 shoes (newest), 2 knits, 2 unknown ('?')
    items = _items([(f"Shoes {i}", 20 + i) for i in range(6)] + [("Knit a", 10), ("Knit b", 9),
                                                                  ("? x", 8), ("? y", 7)])
    caps = [{"name": "shoes", "category": "shoes", "max_new_per_run": 2},
            {"name": "bags+knit", "category": ["knit", "bag"], "max_new_per_run": 1}]
    cands, post, gone, logs = _select(items, caps=caps, category_hook=CAT)
    assert cands == ["5", "4", "6", "8", "9"]          # 2 shoes, 1 knit, unknown ones unlimited here
    assert post == 5 and any("quota 'shoes': 4" in l for l in logs)


def test_category_none_matches_no_cap_and_regex_caps_still_work():
    items = _items([("? phone", 3), ("? phone 2", 2), ("Shoes", 1)])
    caps = [{"regex": "phone", "max_new_per_run": 1}, {"category": "shoes", "max_new_per_run": 0}]
    cands, post, _, _ = _select(items, caps=caps, category_hook=CAT)
    assert cands == ["0"] and post == 2


def test_category_cap_max_share_counts_state_by_hook():
    items = _items([("Shoes a", 3), ("Shoes b", 2)])
    state = [{"title": "Shoes old"}] * 3 + [{"title": "Knit old"}] * 5
    caps = [{"category": "shoes", "max_new_per_run": 2, "max_share": 0.5}]
    cands, _, _, _ = _select(items, caps=caps, state=state, category_hook=CAT)
    assert cands == ["0", "1"]          # int(0.5 * (8 + 2)) - 3 = 2
    state = [{"title": "Shoes old"}] * 5 + [{"title": "Knit old"}] * 3
    cands, _, _, _ = _select(items, caps=caps, state=state, category_hook=CAT)
    assert cands == []                  # int(0.5 * 10) - 5 = 0


def test_priority_first_then_newest():
    items = _items([("Plain new", 29), ("Star * old", 2), ("Plain mid", 15), ("Star * mid", 14)])
    cands, post, _, _ = _select(items, max_new=3, priority_hook=PRIO)
    assert cands == ["3", "1", "0"] and post == 1


def test_priority_takes_quota_slots_first():
    items = _items([("Shoes new", 29), ("Shoes * old", 3)])
    cands, _, _, _ = _select(items, caps=[{"category": "shoes", "max_new_per_run": 1}],
                             category_hook=CAT, priority_hook=PRIO)
    assert cands == ["1"]


def test_backlog_keeps_preferred_first():
    items = _items([(f"Plain {i}", 20 + i) for i in range(5)] + [("Star * a", 2), ("Star * b", 1)])
    cands, post, gone, _ = _select(items, max_new=1, backlog={"max": 3}, priority_hook=PRIO)
    assert cands == ["5"]                       # preferred and newest of the preferred
    assert post == 3 and gone == ["0", "1", "2"]   # kept: star b, plain 4, plain 3


def test_without_hooks_order_unchanged():
    items = _items([("A", 1), ("B", 3), ("C", 2)])
    assert _select(items, max_new=2)[0] == ["1", "2"]


def test_broken_hook_logged_not_raised(monkeypatch):
    items = _items([("Shoes", 2), ("Knit", 1)])
    cands, _, _, logs = _select(items, caps=[{"category": "shoes", "max_new_per_run": 0}],
                                category_hook="plugins_fixture.hooks:broken",
                                priority_hook="plugins_fixture.hooks:broken")
    assert cands == ["0", "1"]
    assert any("plugins_fixture.hooks:broken failed" in l and "ValueError: boom" in l for l in logs)


def test_non_numeric_priority_is_zero(monkeypatch):
    import plugins_fixture.hooks as h
    monkeypatch.setattr(h, "starred", lambda it: "high")
    items = _items([("A", 1), ("B", 2)])
    cands, _, _, logs = _select(items, priority_hook=PRIO)
    assert cands == ["1", "0"] and any("not a number: 'high'" in l for l in logs)


def test_unhashable_category_does_not_crash(monkeypatch):
    import plugins_fixture.hooks as h
    monkeypatch.setattr(h, "first_word", lambda it: ["shoes"])
    items = _items([(f"Shoes {i}", 1 + i) for i in range(5)])
    cands, post, gone, logs = _select(items, max_new=1, caps=[{"category": "x", "max_new_per_run": 1}],
                                      backlog={"max": 2}, category_hook=CAT)
    assert cands == ["4"] and post == 2 and len(gone) == 2


def test_unnamed_category_cap_logged_by_category():
    items = _items([("Shoes a", 2), ("Shoes b", 1)])
    _, _, _, logs = _select(items, caps=[{"category": "shoes", "max_new_per_run": 1}], category_hook=CAT)
    assert any("quota 'shoes': 1" in l for l in logs)


# --- config ------------------------------------------------------------------------------------
@pytest.mark.parametrize("caps, hooks, msg", [
    ([{"max_new_per_run": 1}], {}, "either regex or category"),
    ([{"regex": "x", "category": "y"}], {"category_hook": CAT}, "either regex or category"),
    ([{"category": "y"}], {}, "needs searches.s.category_hook"),
    ([{"category": []}], {"category_hook": CAT}, "name or a list"),
    ([{"category": ["a", 3]}], {"category_hook": CAT}, "name or a list"),
    (["phones"], {}, "must be a mapping"),
    ([], {"priority_hook": ["x:y"]}, "priority_hook must be"),
])
def test_config_errors(tmp_path, caps, hooks, msg):
    cfg = write_cfg(tmp_path, {"s": search_cfg(category_caps=caps, **hooks)})
    with pytest.raises(ConfigError) as e:
        config_mod.search(cfg, "s")
    assert msg in str(e.value)


def test_select_hooks_load_errors():
    with pytest.raises(ConfigError):
        pipeline.select_hooks({"category_hook": "plugins_fixture.hooks:missing"})
    with pytest.raises(ConfigError):
        pipeline.select_hooks({"priority_hook": "plugins_fixture.hooks:NOT_CALLABLE"})
    assert pipeline.select_hooks({}) == (None, None)


def test_backlog_max_cuts_evenly_across_categories():
    # 10 new shoes, 3 old knits; max_new 0: all postponed; backlog.max 6 keeps 3 + 3, not the 6 newest shoes
    items = _items([(f"Shoes {i}", 20 + i) for i in range(10)] + [(f"Knit {i}", 1 + i) for i in range(3)])
    cands, post, gone, _ = _select(items, max_new=0, backlog={"max": 6}, category_hook=CAT)
    assert cands == [] and post == 6
    assert gone == sorted(["0", "1", "2", "3", "4", "5", "6"])        # oldest 7 shoes; all knits stay
    _, post, gone, _ = _select(items, max_new=0, backlog={"max": 6})   # without hook: newest overall
    assert gone == sorted(["0", "1", "2", "3", "10", "11", "12"])


def test_backlog_max_preferred_before_category_balance():
    items = _items([(f"Shoes * {i}", 20 + i) for i in range(4)] + [(f"Knit {i}", 1 + i) for i in range(4)])
    _, post, gone, _ = _select(items, max_new=0, backlog={"max": 4}, category_hook=CAT, priority_hook=PRIO)
    assert gone == ["4", "5", "6", "7"]                               # all knits, the preferred shoes stay
