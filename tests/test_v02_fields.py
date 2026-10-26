"""v0.2 extra listing fields (km, year, ps ...) and numeric field filters, category caps."""

import pytest

from deal_engine.core import pipeline
from deal_engine.core.filters import field_value, fields_failed, passes
from deal_engine.core.listing import RESERVED, extra_fields, normalize
from deal_engine.core.run import run_search
from deal_engine.core.util import save_json
from plugins_fixture.helpers import (accept_all, batch, listing, quiet, report, search_cfg, state, write_cfg,
                                     write_listings)

FILTERS = {"fields": {"km": {"max": 60000}, "kw": {"min": 66}}}


def car(sid, **kw):
    return listing(sid, title=f"Car {sid}", price=5000, **kw)


# --- filters.fields ---------------------------------------------------------------------------

@pytest.mark.parametrize("it,expected", [
    ({"km": 50000, "kw": 70}, None),
    ({"km": 60000, "kw": 66}, None),            # bounds are inclusive
    ({"km": 60001, "kw": 70}, "km"),
    ({"km": 10000, "kw": 65}, "kw"),
    ({}, None),                                 # missing values pass by default
    ({"attrs": {"km": "70000"}, "kw": 70}, "km"),   # attrs are used as well
    ({"km": "45.000 km", "kw": "80"}, None),    # strings are parsed
])
def test_fields_failed(it, expected):
    assert fields_failed(it, FILTERS) == expected


def test_missing_fail():
    flt = {"fields": {"year": {"min": 2010, "missing": "fail"}, "km": {"max": 100}}}
    assert fields_failed({}, flt) == "year"
    assert fields_failed({"year": 2009}, flt) == "year"
    assert fields_failed({"year": 2011}, flt) is None
    assert passes({"title": "x", "year": 2011}, flt) and not passes({"title": "x"}, flt)


def test_field_value_prefers_top_level():
    assert field_value({"km": 5, "attrs": {"km": 9}}, "km") == 5
    assert field_value({"attrs": {"km": "9"}}, "km") == 9
    assert field_value({}, "km") is None


def test_no_fields_no_filter():
    assert fields_failed({"km": 1e9}, {}) is None and fields_failed({}, None) is None


# --- extra fields -----------------------------------------------------------------------------

def test_extra_fields_selection():
    raw = {**car("1"), "km": 50000, "year": 2015, "ps": 150, "fuel": "diesel", "automatic": True,
           "score": 9, "id": "x", "tier": "A", "Km": 1, "a-b": 2, "_x": 3, "market_median": 7, "nested": {"a": 1},
           "lst": [1], "nan": float("nan"), "long": "x" * 400, "a" * 42: 1}
    ex = extra_fields(raw)
    assert ex == {"km": 50000, "year": 2015, "ps": 150, "fuel": "diesel", "automatic": True}
    it = normalize(raw, "json_file")
    assert it["_extra"] == ["automatic", "fuel", "km", "ps", "year"]
    assert it["km"] == 50000
    for bad in ("Km", "a-b", "nested", "lst", "nan", "long", "tier", "_x"):
        assert bad not in it
    assert "id" not in it and "score" not in it


def test_reserved_names_cover_state_fields():
    for k in ("id", "score", "tier", "price_history", "sources", "summary", "issues"):
        assert k in RESERVED


def _run(cfg):
    return run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)


def test_extra_fields_in_batch_and_state(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg(json_file={"path": "{data_dir}/l.json"})})
    write_listings(cfg, [{**car("1"), "km": 50000, "year": 2015, "ps": 150, "score": 9, "id": "evil",
                          "Km": 1, "a-b": 2}], "l.json")
    assert _run(cfg).ok
    b = batch(cfg, "s", "json_file")
    (c,) = b["candidates"]
    assert (c["km"], c["year"], c["ps"]) == (50000, 2015, 150)
    for bad in ("Km", "a-b", "score", "id", "_extra"):
        assert bad not in c
    assert b["extra"] == {"1": ["km", "ps", "year"]}
    (l,) = state(cfg, "s")
    assert (l["km"], l["year"], l["ps"]) == (50000, 2015, 150)
    assert l["id"] == "json_file-1" and l["score"] == 6        # from the evaluation, not from the listing
    assert "Km" not in l and "a-b" not in l


def test_evaluation_value_wins_over_extra_field(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg(json_file={"path": "{data_dir}/l.json"})})
    write_listings(cfg, [{**car("1"), "km": 50000}], "l.json")
    run_search(cfg, "s", evaluator=lambda w, c, s: accept_all(w, c, s, {"1": {"km": 51000}}),
               render=False, log=quiet)
    assert state(cfg, "s")[0]["km"] == 51000


def test_field_filter_skips_candidates(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg(json_file={"path": "{data_dir}/l.json"},
                                               filters={"fields": {"km": {"max": 60000},
                                                                   "year": {"min": 2010, "missing": "fail"}}})})
    write_listings(cfg, [{**car("1"), "km": 50000, "year": 2012}, {**car("2"), "km": 70000, "year": 2012},
                         {**car("3"), "km": 1000}, {**car("4"), "attrs": {"km": "65000"}, "year": 2015}], "l.json")
    res = _run(cfg)
    assert res.adapters[0].found == 4 and res.adapters[0].candidates == 1
    assert [l["id"] for l in state(cfg, "s")] == ["json_file-1"]


def test_reconcile_moves_listing_to_rule_after_filter_change(tmp_path):
    def cfg_with(km_max):
        return write_cfg(tmp_path, {"s": search_cfg(json_file={"path": "{data_dir}/l.json"},
                                                    filters={"fields": {"km": {"max": km_max}}})})
    cfg = cfg_with(60000)
    write_listings(cfg, [{**car("1"), "km": 50000}, {**car("2"), "km": 20000}], "l.json")
    _run(cfg)
    assert len(state(cfg, "s")) == 2
    cfg = cfg_with(40000)        # rule change: listing 1 no longer matches
    res = _run(cfg)
    assert [l["id"] for l in state(cfg, "s")] == ["json_file-2"]
    assert res.adapters[0].gone == 1
    rep = report(cfg, "s")
    assert "Car 1" in rep and "no longer matches the criteria" in rep and "**Gone**" in rep


def test_reconcile_unit_rule(tmp_path):
    class A:
        name = "a"

        def check(self, sid):
            raise AssertionError("not called for rule violations")
    st = {"listings": [{"id": "a-1", "sources": {"a": "1"}, "title": "t", "price": 10, "km": 99},
                       {"id": "a-2", "sources": {"a": "2", "b": "9"}, "title": "t2", "price": 10, "km": 99}]}
    ch = {"price": [], "gone": [], "rule": [], "reserved": [], "problems": []}
    items = {"2": normalize(listing("2", price=10), "a")}
    pipeline.reconcile(st, items, A(), {"filters": {"fields": {"km": {"max": 50}}}, "_locale": "en"}, ch, quiet)
    assert [l["id"] for l in ch["rule"]] == ["a-1"]
    # with another source the listing stays (only one source dropped by rule is removed)
    assert [l["id"] for l in st["listings"]] == ["a-2"]


# --- category caps ----------------------------------------------------------------------------

def _items(titles):
    return {str(i): normalize(listing(str(i), title=t, published=f"2026-06-{10 + i:02d}"), "a")
            for i, t in enumerate(titles)}


def _select(items, caps, state_listings=(), max_new=50):
    sc = {"filters": {}, "market": {}, "category_caps": caps, "max_new_per_run": max_new, "_locale": "en"}
    return pipeline.select(items, set(), {}, {}, sc, quiet, adapter_name="a", state_listings=state_listings)


def test_category_cap_max_new_per_run():
    items = _items(["Phone A", "Phone B", "Phone C", "Laptop"])
    cands, post = _select(items, [{"regex": "phone", "max_new_per_run": 2}])
    titles = [c["title"] for c in cands]
    assert sum(t.startswith("Phone") for t in titles) == 2 and "Laptop" in titles
    assert post == 1   # the third phone is held back by the quota and counted as postponed


def test_category_cap_max_share_relative_to_state():
    items = _items(["Phone A", "Phone B", "Phone C", "Phone D", "Laptop"])
    st = [{"title": "Phone old 1"}, {"title": "Phone old 2"}] + [{"title": f"Tablet {i}"} for i in range(6)]
    # allowed = min(5, int(0.3 * (8 + 5)) - 2) = 1
    cands, _ = _select(items, [{"regex": "phone", "max_new_per_run": 5, "max_share": 0.3}], st)
    titles = [c["title"] for c in cands]
    assert sum(t.startswith("Phone") for t in titles) == 1 and "Laptop" in titles


def test_category_cap_share_already_reached():
    items = _items(["Phone A", "Laptop"])
    st = [{"title": f"Phone {i}"} for i in range(5)]
    cands, _ = _select(items, [{"regex": "phone", "max_new_per_run": 5, "max_share": 0.2}], st)
    assert [c["title"] for c in cands] == ["Laptop"]


def test_category_cap_empty_state():
    items = _items(["Phone A", "Phone B", "Phone C"])
    # allowed = min(4, int(0.5 * (0 + 4)) - 0) = 2
    cands, _ = _select(items, [{"regex": "phone", "max_new_per_run": 4, "max_share": 0.5}], [])
    assert len(cands) == 2


def test_category_cap_in_run(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg(json_file={"path": "{data_dir}/l.json"},
                                               category_caps=[{"name": "phones", "regex": "phone",
                                                               "max_new_per_run": 5, "max_share": 0.5}])})
    save_json(cfg["_data"] / "state" / "s.json",
              {"listings": [{"id": "x-1", "title": "Phone old", "sources": {"x": "1"}},
                            {"id": "x-2", "title": "Laptop old", "sources": {"x": "2"}}]})
    write_listings(cfg, [listing(str(i), title=f"Phone {i}") for i in range(6)] + [listing("9", title="Laptop")],
                   "l.json")
    # allowed = min(5, int(0.5 * (2 + 5)) - 1) = 2
    res = _run(cfg)
    phones = [l for l in state(cfg, "s") if l["id"].startswith("json_file-") and "Phone" in l["title"]]
    assert len(phones) == 2 and res.adapters[0].candidates == 3


# --- regressions found during the 0.2.0 work ------------------------------------------------

def test_attrs_only_field_survives_next_run(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg(json_file={"path": "{data_dir}/l.json"},
                                               filters={"fields": {"year": {"min": 2010, "missing": "fail"}}})})
    write_listings(cfg, [listing("1", attrs={"year": "2015"})], "l.json")
    assert _run(cfg).adapters[0].added == 1
    res = _run(cfg)
    assert res.adapters[0].gone == 0
    assert [l["id"] for l in state(cfg, "s")] == ["json_file-1"]


def test_details_fields_follow_extra_field_rules(tmp_path, monkeypatch):
    from plugins_fixture import adapters as fx
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", [listing("1")])
    monkeypatch.setattr(fx.FakeAdapter, "DETAILS", {"1": {"Km": 1, "a-b": 2, "score": 9, "id": "evil", "km": 5}})
    cfg = write_cfg(tmp_path, {"s": search_cfg(adapters=["fake"])},
                    adapters={"fake": "plugins_fixture.adapters:FakeAdapter"})
    run_search(cfg, "s", evaluator=lambda w, c, s: accept_all(w, c, s), render=False, log=quiet)
    b = batch(cfg, "s", "fake")
    assert b["extra"] == {"1": ["km"]}
    (c,) = b["candidates"]
    for bad in ("Km", "a-b", "id"):
        assert bad not in c
    (l,) = state(cfg, "s")
    assert l["km"] == 5 and "Km" not in l and "a-b" not in l
