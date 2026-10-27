"""v0.2.3: title filters.

- filters.title_failed(): the one place where include_title_regex / exclude_title_regex are applied
  (passes() and reconcile() use it). Both are re.search, case-insensitive, anywhere in the full title,
  so a pattern without word boundaries also hits inside words.
- reconcile(): a listing in the state that no longer matches the title regexes (rule change) is
  dropped like one above max_price, instead of staying in the state forever.
"""
import re

import pytest

from deal_engine.core import pipeline
from deal_engine.core.filters import passes, title_failed
from deal_engine.core.listing import normalize
from deal_engine.core.run import run_search
from plugins_fixture.helpers import accept_all, listing, quiet, report, search_cfg, state, write_cfg, write_listings

LOOSE = {"include_title_regex": "want|seek"}
STRICT = {"include_title_regex": r"\b(want(ed)?|seek(ing)?)\b", "exclude_title_regex": r"selling|\bsale\b"}
# a sale listing stuffed with words for search engines: "want"/"seek" only occur inside other words
STUFFED = "Used car parts, all models, call now. For search engines: wantonly cheap, seekers welcome"
WANTED = ["Wanted: battery cover for remote", "Seeking knob for oven", "want a clip for my bag"]


@pytest.mark.parametrize("title,flt,expected", [
    ("Wanted: knob", {}, None),
    ("Wanted: knob", {"include_title_regex": "wanted"}, None),
    ("Knob for sale", {"include_title_regex": "wanted"}, "include"),
    ("Wanted: knob, sale", {"include_title_regex": "wanted", "exclude_title_regex": r"\bsale\b"}, "exclude"),
    ("WANTED knob", {"include_title_regex": "wanted"}, None),          # case-insensitive
    ("", {"include_title_regex": "wanted"}, "include"),
    (None, {"exclude_title_regex": "x"}, None),
    ("anything", None, None),
])
def test_title_failed(title, flt, expected):
    assert title_failed(title, flt) == expected


def test_substring_pitfall_and_word_boundaries():
    """The loose include hits inside words of the stuffed sale title; word boundaries fix that."""
    assert title_failed(STUFFED, LOOSE) is None
    assert title_failed(STUFFED, STRICT) == "include"
    for t in WANTED:
        assert title_failed(t, STRICT) is None, t


@pytest.mark.parametrize("title", [STUFFED, "Selling knobs", "Knob sale", "Old radio"])
def test_passes_uses_title_failed(title):
    it = {"title": title, "price": 10}
    assert passes(it, STRICT) is (title_failed(title, STRICT) is None) is False


@pytest.mark.parametrize("adapter_name", ["ebay", "willhaben", "json_file"])
def test_select_applies_title_filters_for_any_adapter(adapter_name):
    titles = [STUFFED, "Selling knobs"] + WANTED
    items = {str(i): normalize(listing(str(i), title=t, price=10), adapter_name) for i, t in enumerate(titles)}
    sc = {"filters": STRICT, "_locale": "en", "_name": "s"}
    cands, _ = pipeline.select(items, set(), {}, {}, sc, quiet, adapter_name=adapter_name)
    assert sorted(c["title"] for c in cands) == sorted(WANTED)


class _Adapter:
    name = "a"

    def check(self, sid):
        raise AssertionError("not called for rule violations")


def test_reconcile_drops_listing_failing_title_regex():
    st = {"listings": [{"id": "a-1", "sources": {"a": "1"}, "title": STUFFED, "price": 10},
                       {"id": "a-2", "sources": {"a": "2", "b": "9"}, "title": STUFFED, "price": 10},
                       {"id": "a-3", "sources": {"a": "3"}, "title": WANTED[0], "price": 10}]}
    ch = {"price": [], "gone": [], "rule": [], "reserved": [], "problems": []}
    items = {sid: normalize(listing(sid, title=t, price=10), "a") for sid, t in (("2", STUFFED), ("3", WANTED[0]))}
    pipeline.reconcile(st, items, _Adapter(), {"filters": STRICT, "_locale": "en"}, ch, quiet)
    assert [l["id"] for l in ch["rule"]] == ["a-1"]
    # another source keeps the listing, like for the other hard limits
    assert [l["id"] for l in st["listings"]] == ["a-2", "a-3"]


def test_reconcile_without_title_filters_keeps_everything():
    st = {"listings": [{"id": "a-1", "sources": {"a": "1"}, "title": STUFFED, "price": 10}]}
    ch = {"price": [], "gone": [], "rule": [], "reserved": [], "problems": []}
    items = {"1": normalize(listing("1", title=STUFFED, price=10), "a")}
    pipeline.reconcile(st, items, _Adapter(), {"filters": {}, "_locale": "en"}, ch, quiet)
    assert ch["rule"] == [] and len(st["listings"]) == 1


def test_run_after_title_rule_change(tmp_path):
    """Run with the loose include (the stuffed title gets in), tighten it: the next run drops it."""
    def cfg_with(flt):
        return write_cfg(tmp_path, {"s": search_cfg(json_file={"path": "{data_dir}/l.json"}, filters=flt)})

    rows = [listing("1", title=STUFFED, price=10), listing("2", title=WANTED[0], price=10)]
    cfg = cfg_with(LOOSE)
    write_listings(cfg, rows, "l.json")
    run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert sorted(l["title"] for l in state(cfg, "s")) == sorted([STUFFED, WANTED[0]])
    cfg = cfg_with(STRICT)
    res = run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert [l["title"] for l in state(cfg, "s")] == [WANTED[0]]
    assert res.adapters[0].gone == 1
    assert re.search(r"Used car parts.*no longer matches the criteria", report(cfg, "s"))


def _changes():
    return {"price": [], "gone": [], "rule": [], "reserved": [], "problems": []}


def test_reconcile_keeps_listing_without_title():
    """Without a stored title there is nothing to judge: an include must not remove it."""
    st = {"listings": [{"id": "a-1", "sources": {"a": "1"}, "price": 10},
                       {"id": "a-2", "sources": {"a": "2"}, "title": "", "price": 10}]}
    ch = _changes()
    items = {sid: normalize(listing(sid, title=WANTED[0], price=10), "a") for sid in ("1", "2")}
    pipeline.reconcile(st, items, _Adapter(), {"filters": STRICT, "_locale": "en"}, ch, quiet)
    assert ch["rule"] == [] and [l["id"] for l in st["listings"]] == ["a-1", "a-2"]


@pytest.mark.parametrize("locale_code,word", [("en", "title filters"), ("de", "Titel-Filtern")])
def test_reconcile_title_rule_mass_guard(locale_code, word):
    """A too broad title regex would empty the adapter's stock: nothing removed, reported as a problem."""
    n = 10
    st = {"listings": [{"id": f"a-{i}", "sources": {"a": str(i)}, "title": f"Old radio {i}", "price": 10}
                       for i in range(n)]}
    items = {str(i): normalize(listing(str(i), title=f"Old radio {i}", price=10), "a") for i in range(n)}
    ch = _changes()
    pipeline.reconcile(st, items, _Adapter(), {"filters": {"exclude_title_regex": "radio"}, "_locale": locale_code},
                       ch, quiet)
    assert ch["rule"] == [] and len(st["listings"]) == n
    assert len(ch["problems"]) == 1 and "10" in ch["problems"][0] and word in ch["problems"][0]


def test_reconcile_title_rule_below_guard_removes():
    """Few removals (at most max(5, 30 %)) go through as usual."""
    st = {"listings": [{"id": f"a-{i}", "sources": {"a": str(i)}, "title": t, "price": 10}
                       for i, t in enumerate(["Old radio"] * 5 + ["Wanted: knob"] * 15)]}
    items = {str(i): normalize(listing(str(i), title=l["title"], price=10), "a")
             for i, l in enumerate(st["listings"])}
    ch = _changes()
    pipeline.reconcile(st, items, _Adapter(), {"filters": {"exclude_title_regex": "radio"}, "_locale": "en"}, ch, quiet)
    assert len(ch["rule"]) == 5 and len(st["listings"]) == 15 and ch["problems"] == []


def test_price_rule_not_guarded_by_title_guard():
    """The guard only holds back title removals; max_price removals behave as before."""
    st = {"listings": [{"id": f"a-{i}", "sources": {"a": str(i)}, "title": "Old radio", "price": 999}
                       for i in range(10)]}
    ch = _changes()
    pipeline.reconcile(st, {}, _Adapter(), {"filters": {"max_price": 50, "exclude_title_regex": "radio"},
                                             "_locale": "en"}, ch, quiet)
    assert len(ch["rule"]) == 10 and st["listings"] == [] and ch["problems"] == []
