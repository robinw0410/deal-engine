"""Bounded backlog of postponed candidates (backlog: {max, max_age_days}, category_caps[].backlog)."""
import pytest

from deal_engine.core import config as config_mod
from deal_engine.core import pipeline
from deal_engine.core.config import ConfigError
from deal_engine.core.listing import normalize
from deal_engine.core.run import run_search
from deal_engine.core.util import load_json
from plugins_fixture import adapters as fx
from plugins_fixture.helpers import accept_all, listing, quiet, search_cfg, write_cfg

FAKE = "plugins_fixture.adapters:FakeAdapter"
TODAY = "2026-06-30"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for attr, v in (("ROWS", []), ("CHECK", {}), ("DETAILS", {}), ("SEARCH_RAISES", None), ("CHECKED", [])):
        monkeypatch.setattr(fx.FakeAdapter, attr, v)
    monkeypatch.setenv("DEAL_ENGINE_TODAY", TODAY)


def _items(rows):
    """rows: (title, published day of June 2026); source_id = index."""
    return {str(i): normalize(listing(str(i), title=t, published=f"2026-06-{d:02d}"), "a")
            for i, (t, d) in enumerate(rows)}


def _select(items, max_new=2, caps=(), backlog=None, adapter=None, seen=None):
    sc = {"filters": {}, "market": {}, "category_caps": list(caps), "max_new_per_run": max_new, "_locale": "en"}
    if backlog is not None:
        sc["backlog"] = backlog
    if adapter is not None:
        sc["a"] = adapter
    out, logs = [], []
    cands, post = pipeline.select(items, set(), seen or {}, {}, sc, logs.append, adapter_name="a", discarded=out)
    return [c["source_id"] for c in cands], post, sorted(c["source_id"] for c in out), logs


# --- select() ---------------------------------------------------------------------------------

def test_without_backlog_nothing_is_discarded():
    items = _items([(f"Item {i}", 1 + i) for i in range(10)])
    cands, post, gone, _ = _select(items)
    assert cands == ["9", "8"] and post == 8 and gone == []


def test_backlog_max_keeps_only_newest_postponed():
    items = _items([(f"Item {i}", 1 + i) for i in range(10)])     # 9 newest
    cands, post, gone, _ = _select(items, backlog={"max": 3})
    assert cands == ["9", "8"] and post == 3
    assert gone == ["0", "1", "2", "3", "4"]                      # the 5 oldest


def test_backlog_max_age_days():
    items = _items([("Old", 1), ("Older", 2), ("Recent", 25), ("Newer", 27), ("Newest", 29), ("No date", 28)])
    items["5"]["_published"] = None                               # unknown age: stays
    cands, post, gone, _ = _select(items, max_new=1, backlog={"max_age_days": 14})   # cut 2026-06-16
    assert cands == ["4"] and post == 3 and gone == ["0", "1"]


def test_backlog_max_zero_discards_all_postponed():
    items = _items([(f"Item {i}", 1 + i) for i in range(5)])
    cands, post, gone, _ = _select(items, backlog={"max": 0})
    assert cands == ["4", "3"] and post == 0 and gone == ["0", "1", "2"]


def test_adapter_backlog_replaces_search_backlog():
    items = _items([(f"Item {i}", 1 + i) for i in range(6)])
    _, post, gone, _ = _select(items, backlog={"max": 0}, adapter={"backlog": {"max": 2}})
    assert post == 2 and gone == ["0", "1"]
    _, post, gone, _ = _select(items, backlog={"max": 0}, adapter={"backlog": {}})   # {}: no limit
    assert post == 4 and gone == []


def test_quota_rest_bounded_by_default_three_times_cap():
    rows = [(f"Phone {i}", 1 + i) for i in range(12)] + [("Laptop", 29)]
    items = _items(rows)
    caps = [{"name": "phones", "regex": "phone", "max_new_per_run": 2}]
    cands, post, gone, logs = _select(items, max_new=10, caps=caps, backlog={"max": 100})
    assert cands == ["12", "11", "10"]                            # laptop + 2 newest phones
    assert post == 6                                              # 3 x 2 newest of the phone rest
    assert gone == sorted(str(i) for i in range(4))               # the 4 oldest phones
    assert "quota 'phones': 6 candidates postponed, 4 discarded (backlog)" in logs


def test_empty_adapter_backlog_switches_quota_default_off():
    items = _items([(f"Phone {i}", 1 + i) for i in range(12)])
    caps = [{"name": "phones", "regex": "phone", "max_new_per_run": 2}]
    cands, post, gone, logs = _select(items, max_new=10, caps=caps, backlog={"max": 100}, adapter={"backlog": {}})
    assert cands == ["11", "10"] and post == 10 and gone == []
    assert "quota 'phones': 10 candidates postponed" in logs
    # an explicit cap backlog still applies
    caps[0]["backlog"] = 3
    _, post, gone, _ = _select(items, max_new=10, caps=caps, backlog={"max": 100}, adapter={"backlog": {}})
    assert post == 3 and len(gone) == 7


def test_backlog_max_keeps_undated_like_newest():
    items = _items([(f"Item {i}", 1 + i) for i in range(6)])
    items["0"]["_published"] = None                               # sorted last, but kept like the newest
    cands, post, gone, _ = _select(items, max_new=1, backlog={"max": 2})
    assert cands == ["5"] and post == 2
    assert gone == ["1", "2", "3"]                                # 0 (undated) and 4 (newest dated) stay


def test_quota_rest_explicit_cap_backlog_without_search_backlog():
    items = _items([(f"Phone {i}", 1 + i) for i in range(6)])
    caps = [{"regex": "phone", "max_new_per_run": 1, "backlog": 2}]
    cands, post, gone, _ = _select(items, max_new=10, caps=caps)
    assert cands == ["5"] and post == 2 and gone == ["0", "1", "2"]


def test_quota_rest_unbounded_without_any_backlog():
    items = _items([(f"Phone {i}", 1 + i) for i in range(6)])
    cands, post, gone, logs = _select(items, max_new=10, caps=[{"regex": "phone", "max_new_per_run": 1}])
    assert cands == ["5"] and post == 5 and gone == []
    assert "quota 'phone': 5 candidates postponed" in logs


def test_quota_rest_and_limit_rest_share_backlog_max():
    rows = [(f"Phone {i}", 10 + i) for i in range(4)] + [(f"Laptop {i}", 1 + i) for i in range(5)]
    items = _items(rows)
    caps = [{"regex": "phone", "max_new_per_run": 1, "backlog": 10}]
    cands, post, gone, _ = _select(items, max_new=2, caps=caps, backlog={"max": 4})
    assert cands == ["3", "8"]                                    # newest phone, newest laptop
    # postponed: phones 2,1,0 (days 12,11,10) and laptops 7..4 (days 4..1): newest 4 stay
    assert post == 4 and gone == ["4", "5", "6"]


def test_select_without_discarded_list_keeps_return_shape():
    items = _items([(f"Item {i}", 1 + i) for i in range(5)])
    sc = {"filters": {}, "market": {}, "max_new_per_run": 2, "_locale": "en", "backlog": {"max": 1}}
    cands, post = pipeline.select(items, set(), {}, {}, sc, quiet)
    assert len(cands) == 2 and post == 1


# --- collect()/run: persisted in seen ---------------------------------------------------------

def _cfg(tmp_path, **search):
    return write_cfg(tmp_path, {"s": search_cfg(adapters=["fake"], **search)}, adapters={"fake": FAKE})


def _run(cfg, evaluator=accept_all):
    return run_search(cfg, "s", evaluator=evaluator, render=False, log=quiet)


def test_discarded_written_to_seen_and_not_back_next_run(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, max_new_per_run=2, backlog={"max": 1})
    rows = [listing(str(i), price=100, published=f"2026-06-{10 + i:02d}") for i in range(6)]
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", rows)
    ar = _run(cfg).adapters[0]
    assert (ar.candidates, ar.postponed, ar.discarded) == (2, 1, 3)
    seen = load_json(config_mod.paths(cfg, "s", "fake")["seen"], {})
    assert {k for k, v in seen.items() if v.get("skipped") == "backlog"} == {"0", "1", "2"}
    assert seen["0"] == {"price": 100, "date": TODAY, "skipped": "backlog"}
    assert seen["5"].get("skipped") is None                       # evaluated normally
    # next run: only the one kept in the backlog is left
    ar = _run(cfg).adapters[0]
    assert (ar.candidates, ar.postponed, ar.discarded) == (1, 0, 0)


def test_discarded_comes_back_after_price_drop(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, max_new_per_run=1, backlog={"max": 0})
    rows = [listing(str(i), price=100, published=f"2026-06-{10 + i:02d}") for i in range(3)]
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", rows)
    assert _run(cfg).adapters[0].discarded == 2
    rows[0] = {**rows[0], "price": 85}
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", rows)
    ar = _run(cfg).adapters[0]
    assert (ar.candidates, ar.discarded) == (1, 0)


def test_discarded_persisted_even_without_evaluation(tmp_path, monkeypatch):
    """Everything over the limit is discarded and no batch is evaluated: seen is still written."""
    cfg = _cfg(tmp_path, max_new_per_run=0, backlog={"max": 0})
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", [listing(str(i), published="2026-06-20") for i in range(3)])
    sc = config_mod.search(cfg, "s")
    from deal_engine import adapters
    logs = []
    c = pipeline.collect(cfg, sc, adapters.create("fake", cfg, sc), logs.append)
    assert (c["candidates"], c["postponed"], c["discarded"], c["batches"]) == (0, 0, 3, 0)
    assert len(load_json(config_mod.paths(cfg, "s", "fake")["seen"], {})) == 3
    assert "0 new candidates for evaluation (3 discarded: backlog)" in logs


def test_log_line_keeps_postponed_text(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, max_new_per_run=1, backlog={"max": 1})
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", [listing(str(i), published=f"2026-06-{10 + i:02d}") for i in range(4)])
    sc = config_mod.search(cfg, "s")
    from deal_engine import adapters
    logs = []
    pipeline.collect(cfg, sc, adapters.create("fake", cfg, sc), logs.append)
    assert "1 new candidates for evaluation (1 postponed to the next run, 2 discarded: backlog)" in logs


# --- config validation ------------------------------------------------------------------------

@pytest.mark.parametrize("search,msg", [
    ({"backlog": 200}, "backlog must be a mapping"),
    ({"backlog": {"max": -1}}, "backlog.max must be an integer"),
    ({"backlog": {"max": "200"}}, "backlog.max must be an integer"),
    ({"backlog": {"max_age_days": 1.5}}, "backlog.max_age_days must be an integer"),
    ({"backlog": {"max": True}}, "backlog.max must be an integer"),
    ({"backlog": {"maximum": 5}}, "unknown key"),
    ({"fake": {"backlog": {"max": "x"}}}, "s.fake.backlog.max"),
    ({"category_caps": [{"regex": "x", "backlog": -2}]}, "category_caps[0].backlog"),
])
def test_config_rejects_bad_backlog(tmp_path, search, msg):
    cfg = _cfg(tmp_path, **search)
    with pytest.raises(ConfigError, match=msg.replace("[", r"\[").replace("]", r"\]")):
        config_mod.search(cfg, "s")


def test_config_accepts_backlog(tmp_path):
    cfg = _cfg(tmp_path, backlog={"max": 200, "max_age_days": 14}, fake={"backlog": {"max": None}},
               category_caps=[{"regex": "x", "backlog": 0}])
    sc = config_mod.search(cfg, "s")
    assert pipeline.backlog_settings(sc, "fake") is None   # no limit at all: switched off
    assert pipeline.backlog_settings(sc) == {"max": 200, "max_age_days": 14}
    assert pipeline.backlog_settings({}, "fake") is None
    assert pipeline.backlog_settings({"backlog": {"max": 5}, "fake": {"backlog": {}}}, "fake") is None
    assert pipeline.backlog_settings({"backlog": {"max": None, "max_age_days": None}}) is None
