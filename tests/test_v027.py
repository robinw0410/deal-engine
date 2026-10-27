"""v0.2.7: filter hooks (filters.hooks: ["module:function"]) are hard filters in code, run before the selection."""
import sys
import types

import pytest

from deal_engine.core import clock, filters, pipeline
from deal_engine.core.config import ConfigError
from deal_engine.core.listing import normalize


@pytest.fixture
def hook_module(monkeypatch):
    """Module "fh_<n>" with reject(listing): rejects titles containing "small" (reason), "tiny" (True)."""
    calls = []

    def reject(listing):
        calls.append(listing["title"])
        t = listing["title"].lower()
        return "size S" if "small" in t else True if "tiny" in t else None

    name = f"fh_{id(calls)}"
    mod = types.ModuleType(name)
    mod.reject = reject
    monkeypatch.setitem(sys.modules, name, mod)
    return name, calls


def item(title, price=50):
    return normalize({"source_id": "1", "url": "https://example.org/1", "title": title, "price": price,
                      "published": clock.today_str(), "shipping_possible": True, "shipping_cost_eur": 0}, "test")


def test_hook_rejects_and_passes(hook_module):
    name, calls = hook_module
    flt = {"hooks": [f"{name}:reject"]}
    assert filters.hook_failed(item("Jacket small"), flt) == f"{name}:reject: size S"
    assert filters.hook_failed(item("Jacket tiny"), flt) == f"{name}:reject"
    assert filters.hook_failed(item("Jacket large"), flt) is None
    assert not filters.passes(item("Jacket small"), flt)
    assert filters.passes(item("Jacket large"), flt)


def test_hook_runs_after_cheap_filters(hook_module):
    name, calls = hook_module
    flt = {"hooks": [f"{name}:reject"], "max_price": 100, "exclude_title_regex": "wanted"}
    assert not filters.passes(item("Jacket large", 150), flt)
    assert not filters.passes(item("wanted: jacket"), flt)
    assert calls == []


def test_select_skips_rejected(hook_module):
    name, _ = hook_module
    sc = {"_locale": "en", "filters": {"hooks": [f"{name}:reject"]}, "market": {}}
    items = {"1": item("Jacket small"), "2": {**item("Jacket large"), "source_id": "2"}}
    cands, _ = pipeline.select(items, set(), {}, {}, sc, lambda s: None, adapter_name="test")
    assert [c["title"] for c in cands] == ["Jacket large"]


def test_no_hooks_no_change():
    assert filters.load_hooks({}) == [] and filters.hook_failed(item("Jacket small"), {}) is None


@pytest.mark.parametrize("hooks", ["mod:fn", {"a": 1}])
def test_hooks_must_be_a_list(hooks):
    with pytest.raises(ConfigError, match="list"):
        filters.load_hooks({"hooks": hooks})


@pytest.mark.parametrize("spec", ["no_such_module_xyz:fn", "nocolon", "json:no_such_attr"])
def test_hook_load_errors(spec):
    with pytest.raises(ConfigError):
        filters.load_hooks({"hooks": [spec]})


def test_hook_exception_lets_listing_pass_and_is_logged(monkeypatch):
    mod = types.ModuleType("fh_broken")
    mod.boom = lambda listing: 1 / 0
    monkeypatch.setitem(sys.modules, "fh_broken", mod)
    sc = {"_locale": "en", "filters": {"hooks": ["fh_broken:boom"]}, "market": {}}
    lines = []
    cands, _ = pipeline.select({"1": item("Jacket")}, set(), {}, {}, sc, lines.append, adapter_name="test")
    assert len(cands) == 1
    assert any("filter hook fh_broken:boom failed 1 times" in l and "ZeroDivisionError" in l for l in lines)
    assert filters.HOOK_ERRORS == {}


def test_hook_not_callable(monkeypatch):
    mod = types.ModuleType("fh_nc")
    mod.f = 42
    monkeypatch.setitem(sys.modules, "fh_nc", mod)
    with pytest.raises(ConfigError, match="not callable"):
        filters.load_hooks({"hooks": ["fh_nc:f"]})


def test_select_logs_hook_rejections(hook_module):
    name, _ = hook_module
    sc = {"_locale": "en", "filters": {"hooks": [f"{name}:reject"]}, "market": {}}
    lines = []
    pipeline.select({"1": item("Jacket small")}, set(), {}, {}, sc, lines.append, adapter_name="test")
    assert any(l.startswith("1 listings rejected by filter hooks") and "size S" in l for l in lines)
