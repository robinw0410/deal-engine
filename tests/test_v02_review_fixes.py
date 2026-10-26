"""Regressions for the findings of the 0.2.0 review."""
import json
import subprocess
import sys

import pytest

from deal_engine.core import config as config_mod
from deal_engine.core import locale
from deal_engine.core.run import run_search
from deal_engine.core.score import DEFAULTS, SHIPPING_DEFAULTS, compute, fraud
from plugins_fixture.helpers import REPO, accept_all, listing, quiet, search_cfg, state, write_cfg

BROKEN = """
from deal_engine.adapters.base import Adapter

class Broken(Adapter):
    name = "broken"
    def __init__(self, cfg, sc):
        raise KeyError("missing setting")
"""


def _plugin(tmp_path, name, code):
    (tmp_path / "plugins").mkdir(exist_ok=True)
    (tmp_path / "plugins" / f"{name}.py").write_text(code)


def test_broken_adapter_does_not_stop_the_others(tmp_path):
    _plugin(tmp_path, "review_broken", BROKEN)
    cfg = write_cfg(tmp_path, {"s": search_cfg(adapters=["broken", "json_file"], json_file={"path": "l.json"})},
                    adapters={"broken": "review_broken:Broken"}, plugin_paths=["plugins"])
    (tmp_path / "l.json").write_text(json.dumps([listing("1")]))
    res = run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert [(a.name, a.status, a.reason) for a in res.adapters] == [("broken", "failed", "error"),
                                                                  ("json_file", "ok", "")]
    assert "KeyError" in res.adapters[0].error and len(state(cfg, "s")) == 1


def test_plugin_with_syntax_error_is_a_config_error(tmp_path):
    _plugin(tmp_path, "review_syntax", "def broken(:\n")
    cfg = write_cfg(tmp_path, {"s": search_cfg(adapters=["x"])}, adapters={"x": "review_syntax:X"},
                    plugin_paths=["plugins"])
    res = run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert res.adapters[0].reason == "config_error" and "SyntaxError" in res.adapters[0].error


def test_bad_hook_fails_before_collecting_and_cli_runs_other_searches(tmp_path):
    cfg = write_cfg(tmp_path, {"a": search_cfg(json_file={"path": "l.json"},
                                                 score={"enabled": True, "hooks": ["nomodule_xyz:fn"]}),
                               "b": search_cfg(json_file={"path": "l.json"})})
    (tmp_path / "l.json").write_text(json.dumps([]))
    with pytest.raises(config_mod.ConfigError):
        run_search(cfg, "a", evaluator=accept_all, render=False, log=quiet)
    assert not config_mod.paths(cfg, "a", "json_file")["work"].exists()   # nothing collected
    out = tmp_path / "out.json"
    r = subprocess.run([sys.executable, "-m", "deal_engine", "--config", str(tmp_path / "config.yaml"), "run",
                        "--evaluator", "demo", "--json", str(out)], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 2 and "a: configuration error" in r.stderr
    assert [x["search"] for x in json.loads(out.read_text())] == ["b"]


def test_error_after_merge_is_reported_not_raised(tmp_path, monkeypatch):
    cfg = write_cfg(tmp_path, {"s": search_cfg(json_file={"path": "l.json"})})
    (tmp_path / "l.json").write_text(json.dumps([listing("1")]))
    from deal_engine.core import insights

    def boom(*a, **k):
        raise RuntimeError("insights broke")
    monkeypatch.setattr(insights, "apply", boom)
    res = run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert not res.ok and "insights broke" in res.error and len(state(cfg, "s")) == 1


@pytest.mark.parametrize("code,text,expected", [
    ("de", "Nichts Verdächtiges erkennbar", False),
    ("en", "Nothing suspicious", False),
    ("en", "Not tested but fake photos", True),
    ("de", "nicht original verpackt aber Fake-Bilder", True),
    ("en", "no warranty - prepayment only", True),
    ("de", "keine Vorkasse, kein Fake", False),
])
def test_fraud_negation_edges(code, text, expected):
    assert fraud({"issues": text}, {**DEFAULTS, "_loc": locale.get(code)}) is expected


BASE = {"title": "Console", "price": 100, "market_price": 220, "market_resale_estimate": 220, "repair_parts_eur": 10,
        "repair_hours": 2, "shipping_cost_eur": 0, "risk": "low", "deal_type": "repair"}


@pytest.mark.parametrize("damage", [["keine"], ["Keine sichtbaren Schäden"], ["nichts"]])
def test_german_no_damage_is_no_penalty(damage):
    c = {**DEFAULTS, **SHIPPING_DEFAULTS, "_loc": locale.get("de")}
    assert compute({**BASE, "visible_damage": damage}, c)["score"] == compute(BASE, c)["score"]
    assert compute({**BASE, "visible_damage": ["Riss im Display"]}, c)["exact"] < compute(BASE, c)["exact"]


def test_photo_check_values_shown_in_german():
    de = locale.get("de")
    assert de.value("insufficient photos") == "Fotos unzureichend"
    assert de.value("more damage than described") == "mehr Schäden als beschrieben"


def test_classify_prompt_override_missing_is_a_config_error(tmp_path):
    from deal_engine.core import classify, history
    cfg = write_cfg(tmp_path, {"s": search_cfg(track=True, classify={"enabled": True},
                                               market={"groups": [{"name": "G", "match": "switch"}]},
                                               prompts={"classify": "missing.md"})})
    P = config_mod.paths(cfg, "s")
    sc = config_mod.search(cfg, "s")
    from deal_engine.core.listing import normalize
    history.track(P["history"], sc, [normalize(listing("1"), "json_file")], log=quiet)
    with pytest.raises(config_mod.ConfigError):
        classify.apply(cfg, sc, P, quiet)


def test_evaluation_field_names_are_not_extra_fields():
    from deal_engine.core.listing import normalize
    it = normalize({**listing("1"), "risk": "low", "repair_hours": 1, "deal_type": "flip", "km": 5}, "t")
    assert it["_extra"] == ["km"] and "risk" not in it


def test_ebay_needs_keywords_and_outage_is_no_config_error(monkeypatch):
    import urllib.error
    from deal_engine.adapters import ebay
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    cfg = {"location": {}}
    with pytest.raises(config_mod.ConfigError):
        ebay.EbayAdapter(cfg, {"_name": "s"})                              # no keywords at all
    ad = ebay.EbayAdapter(cfg, {"_name": "s", "keywords": ["x"]})

    def outage(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 503, "down", {}, None)
    monkeypatch.setattr(ebay.urllib.request, "urlopen", outage)
    with pytest.raises(RuntimeError):
        ad._auth()

    def refused(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
    monkeypatch.setattr(ebay.urllib.request, "urlopen", refused)
    with pytest.raises(config_mod.ConfigError):
        ad._auth()


def test_run_demo_rejects_unknown_locale(tmp_path):
    from deal_engine.demo import run_demo
    with pytest.raises(config_mod.ConfigError):
        run_demo.main(["--days", "1", "--quiet", "--locale", "xx", "--data", str(tmp_path / "demo"),
                       "--config", str(REPO / "config.example.yaml")])
