"""v0.2 adapter registry: config "module:Class", entry points, built-ins, errors."""
import sys
import textwrap

import pytest

from deal_engine import adapters
from deal_engine.adapters.base import Adapter
from deal_engine.core import plugins
from deal_engine.core.config import ConfigError
from deal_engine.core.run import RunResult, run_search
from plugins_fixture import adapters as fx
from plugins_fixture.helpers import accept_all, quiet, search_cfg, snapshot_syspath, state, write_cfg

PLUGIN = '''
from deal_engine.adapters.base import Adapter


class ShopAdapter(Adapter):
    name = "shop_internal"

    def search(self, query):
        self.requests += 1
        return [{"source_id": str(i), "url": f"https://shop.invalid/{i}", "title": f"Thing {i}",
                 "price": 10 * i, "shipping_possible": True} for i in (1, 2)]

    def check(self, source_id):
        return "active"


class Plain:
    name = "plain"
'''


@pytest.fixture
def plugin_cfg(tmp_path, monkeypatch):
    snapshot_syspath(monkeypatch)
    monkeypatch.delitem(sys.modules, "tests_plugin_mod", raising=False)
    cfg_dir = tmp_path / "conf"
    (cfg_dir / "plugins").mkdir(parents=True)
    (cfg_dir / "plugins" / "tests_plugin_mod.py").write_text(textwrap.dedent(PLUGIN))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)   # plugin_paths are relative to the config file, not the cwd
    cfg = write_cfg(cfg_dir, {"s": search_cfg(adapters=["shop"], shop={"opt": 1})},
                    adapters={"shop": "tests_plugin_mod:ShopAdapter", "plain": "tests_plugin_mod:Plain"},
                    plugin_paths=["plugins"])
    yield cfg
    sys.modules.pop("tests_plugin_mod", None)


def _sc(cfg, name="s"):
    from deal_engine.core import config as config_mod
    return config_mod.search(cfg, name)


# --- (a) config registration -------------------------------------------------------------------

def test_config_adapter_created_under_registered_name(plugin_cfg):
    a = adapters.create("shop", plugin_cfg, _sc(plugin_cfg))
    assert isinstance(a, sys.modules["tests_plugin_mod"].ShopAdapter) and isinstance(a, Adapter)
    assert a.name == "shop"
    assert a.settings == {"opt": 1}     # settings come from sc[<registered name>]
    # the original class is not modified
    assert sys.modules["tests_plugin_mod"].ShopAdapter.name == "shop_internal"


def test_config_adapter_listed_as_available(plugin_cfg):
    av = adapters.available(plugin_cfg)
    assert av["shop"].startswith("config") and "tests_plugin_mod:ShopAdapter" in av["shop"]
    assert av["json_file"] == "built in" and av["ebay"] == "built in"


def test_config_adapter_same_name_keeps_class(tmp_path, monkeypatch):
    cfg = write_cfg(tmp_path, {"s": search_cfg()}, adapters={"fake_class_name": "plugins_fixture.adapters:FakeAdapter"})
    a = adapters.create("fake_class_name", cfg, _sc(cfg))
    assert type(a) is fx.FakeAdapter


def test_config_overrides_builtin_name(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg()}, adapters={"json_file": "plugins_fixture.adapters:FakeAdapter"})
    a = adapters.create("json_file", cfg, _sc(cfg))
    assert isinstance(a, fx.FakeAdapter) and a.name == "json_file"


# --- (b) entry points --------------------------------------------------------------------------

class FakeEP:
    def __init__(self, name, value, obj=None, error=None):
        self.name, self.value, self._obj, self._error = name, value, obj, error

    def load(self):
        if self._error:
            raise self._error
        return self._obj


def _patch_eps(monkeypatch, eps):
    seen = []

    def fake(group):
        seen.append(group)
        return {e.name: e for e in eps} if group == adapters.GROUP else {}
    monkeypatch.setattr(plugins, "entry_points", fake)
    return seen


def test_entry_point_adapter(tmp_path, monkeypatch):
    seen = _patch_eps(monkeypatch, [FakeEP("epshop", "plugins_fixture.adapters:FakeAdapter", fx.FakeAdapter)])
    cfg = write_cfg(tmp_path, {"s": search_cfg()})
    a = adapters.create("epshop", cfg, _sc(cfg))
    assert isinstance(a, fx.FakeAdapter) and a.name == "epshop"
    assert "deal_engine.adapters" in seen
    assert adapters.available(cfg)["epshop"] == "entry point plugins_fixture.adapters:FakeAdapter"


def test_entry_point_load_error_is_config_error(tmp_path, monkeypatch):
    _patch_eps(monkeypatch, [FakeEP("broken", "x.y:Z", error=ImportError("no module x"))])
    cfg = write_cfg(tmp_path, {"s": search_cfg()})
    with pytest.raises(ConfigError, match="broken.*cannot be loaded"):
        adapters.create("broken", cfg, _sc(cfg))


def test_config_wins_over_entry_point(tmp_path, monkeypatch):
    _patch_eps(monkeypatch, [FakeEP("shop", "x:Y", fx.NotAnAdapter)])
    cfg = write_cfg(tmp_path, {"s": search_cfg()}, adapters={"shop": "plugins_fixture.adapters:FakeAdapter"})
    assert isinstance(adapters.create("shop", cfg, _sc(cfg)), fx.FakeAdapter)


def test_entry_point_non_adapter_rejected(tmp_path, monkeypatch):
    _patch_eps(monkeypatch, [FakeEP("bad", "x:Y", fx.NotAnAdapter)])
    cfg = write_cfg(tmp_path, {"s": search_cfg()})
    with pytest.raises(ConfigError, match="subclass"):
        adapters.create("bad", cfg, _sc(cfg))


def test_real_entry_points_returns_dict():
    assert isinstance(plugins.entry_points("deal_engine.adapters.none-such"), dict)


def test_broken_metadata_does_not_break(monkeypatch):
    import importlib.metadata

    def boom():
        raise RuntimeError("broken metadata")
    monkeypatch.setattr(importlib.metadata, "entry_points", boom)
    assert plugins.entry_points("deal_engine.adapters") == {}


# --- (c) errors --------------------------------------------------------------------------------

def test_unknown_adapter_lists_available(plugin_cfg):
    with pytest.raises(ConfigError) as e:
        adapters.create("nope", plugin_cfg, _sc(plugin_cfg))
    msg = str(e.value)
    assert "nope" in msg
    for n in ("json_file", "ebay", "shop"):
        assert n in msg


def test_non_adapter_class_rejected(plugin_cfg):
    with pytest.raises(ConfigError, match="subclass"):
        adapters.create("plain", plugin_cfg, _sc(plugin_cfg))


@pytest.mark.parametrize("spec", ["nocolon", ":Cls", "mod:", ""])
def test_bad_spec(tmp_path, spec):
    cfg = write_cfg(tmp_path, {"s": search_cfg()}, adapters={"x": spec or "nocolon"})
    with pytest.raises(ConfigError, match="module:attribute"):
        adapters.create("x", cfg, _sc(cfg))


def test_plugins_load_errors():
    with pytest.raises(ConfigError, match="module:attribute"):
        plugins.load("nocolon")
    with pytest.raises(ConfigError, match="cannot be imported"):
        plugins.load("no_such_module_xyz:Thing")
    with pytest.raises(ConfigError, match="not found"):
        plugins.load("plugins_fixture.adapters:Missing")
    assert plugins.load("plugins_fixture.adapters:FakeAdapter") is fx.FakeAdapter
    assert plugins.load("plugins_fixture.adapters:FakeAdapter.search") is fx.FakeAdapter.search


def test_non_class_object_rejected(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg()}, adapters={"f": "plugins_fixture.helpers:quiet"})
    with pytest.raises(ConfigError):
        adapters.create("f", cfg, _sc(cfg))


# --- (d) end to end ----------------------------------------------------------------------------

def test_run_search_with_config_adapter(plugin_cfg):
    res = run_search(plugin_cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert isinstance(res, RunResult) and res.ok and bool(res)
    ar = res.adapters[0]
    assert (ar.name, ar.status, ar.found, ar.candidates, ar.added) == ("shop", "ok", 2, 2, 2)
    st = state(plugin_cfg, "s")
    assert sorted(l["id"] for l in st) == ["shop-1", "shop-2"]
    assert all(l["source"] == "shop" and l["sources"] == {"shop": l["id"][5:]} for l in st)
    # second run: nothing new, the stored listings stay (check is not needed, they are still found)
    res = run_search(plugin_cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert res.ok and res.adapters[0].added == 0 and len(state(plugin_cfg, "s")) == 2
