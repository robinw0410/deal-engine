"""v0.2 eBay without credentials: a configuration error, never a fallback to another adapter."""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
import yaml

from deal_engine import adapters
from deal_engine.core import config as config_mod
from deal_engine.core.config import ConfigError
from deal_engine.core.run import run_search
from deal_engine.core.util import save_json
from plugins_fixture.helpers import accept_all, listing, quiet, report, search_cfg, state, work_dir, write_cfg, write_listings

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def no_keys_no_network(monkeypatch):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)

    def no_network(*a, **k):
        raise AssertionError("network access in a test")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)


def cfg_for(tmp_path, adapters_):
    cfg = write_cfg(tmp_path, {"s": search_cfg(adapters=adapters_, json_file={"path": "{data_dir}/l.json"},
                                               ebay={"markets": ["EBAY_DE"]})})
    write_listings(cfg, [listing("1"), listing("2")], "l.json")
    return cfg


@pytest.mark.parametrize("env", [{}, {"EBAY_CLIENT_ID": "id"}, {"EBAY_CLIENT_SECRET": "secret"},
                                 {"EBAY_CLIENT_ID": "  ", "EBAY_CLIENT_SECRET": " "}])
def test_create_without_keys_is_config_error(tmp_path, monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    cfg = cfg_for(tmp_path, ["ebay"])
    with pytest.raises(ConfigError) as e:
        adapters.create("ebay", cfg, config_mod.search(cfg, "s"))
    assert "EBAY_CLIENT_ID" in str(e.value) and "EBAY_CLIENT_SECRET" in str(e.value)


def test_create_with_keys_needs_no_network(tmp_path, monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    cfg = cfg_for(tmp_path, ["ebay"])
    cfg["searches"]["s"]["keywords"] = ["switch lite"]   # the Browse API needs search terms
    a = adapters.create("ebay", cfg, config_mod.search(cfg, "s"))
    assert a.name == "ebay" and a.markets == ["EBAY_DE"]


def test_run_marks_ebay_failed_without_substitute(tmp_path):
    cfg = cfg_for(tmp_path, ["ebay"])
    before = {"listings": [{"id": "ebay-5", "title": "old", "price": 9, "sources": {"ebay": "5"}}]}
    save_json(config_mod.paths(cfg, "s")["state"], before)
    state_text = config_mod.paths(cfg, "s")["state"].read_text()
    logs = []
    res = run_search(cfg, "s", evaluator=accept_all, render=False, log=logs.append)
    (ar,) = res.adapters
    assert (ar.name, ar.status, ar.reason) == ("ebay", "failed", "config_error")
    assert "EBAY_CLIENT_ID" in ar.error and "EBAY_CLIENT_SECRET" in ar.error
    assert not res and res.failed == [ar]
    # nothing else ran in its place
    assert config_mod.paths(cfg, "s")["state"].read_text() == state_text
    assert not work_dir(cfg, "s", "json_file").exists()
    assert not work_dir(cfg, "s", "ebay").exists()
    assert (ar.found, ar.candidates, ar.added, ar.requests) == (0, 0, 0, 0)
    rep = report(cfg, "s")
    assert rep.startswith("**Problem:** ebay: EBAY_CLIENT_ID and EBAY_CLIENT_SECRET must be set")
    assert "json_file" not in rep
    assert any("EBAY_CLIENT_ID" in s for s in logs)


def test_run_with_json_file_and_ebay(tmp_path):
    cfg = cfg_for(tmp_path, ["json_file", "ebay"])
    res = run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    js, eb = res.adapters
    assert js.status == "ok" and js.added == 2
    assert (eb.status, eb.reason) == ("failed", "config_error")
    st = state(cfg, "s")
    assert sorted(l["id"] for l in st) == ["json_file-1", "json_file-2"]
    assert all(set(l["sources"]) == {"json_file"} for l in st)
    assert "**Problem:** ebay:" in report(cfg, "s")
    assert not (cfg["_data"] / "state" / "s-ebay-seen.json").exists()


def test_no_fallback_anywhere_in_code():
    """The adapter registry has no default/fallback adapter."""
    src = (REPO / "deal_engine" / "adapters" / "__init__.py").read_text()
    assert "def create" in src
    import inspect
    body = inspect.getsource(adapters.create) + inspect.getsource(adapters.adapter_class)
    assert "json_file" not in body


def test_cli_ebay_without_keys_exit_2(tmp_path):
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "config.yaml").write_text(yaml.safe_dump(
        {"data_dir": "data", "searches": {"s": search_cfg(adapters=["ebay"], json_file={"path": "l.json"})}}))
    (conf / "l.json").write_text(json.dumps([listing("1")]))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EBAY_", "DEAL_ENGINE_"))}
    env["PYTHONPATH"] = str(REPO)
    out = tmp_path / "out.json"
    r = subprocess.run([sys.executable, "-m", "deal_engine", "--config", str(conf / "config.yaml"), "run",
                        "--json", str(out)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
    assert "EBAY_CLIENT_ID" in r.stderr
    d = json.loads(out.read_text())
    assert d[0]["adapters"] == [d[0]["adapters"][0]] and d[0]["adapters"][0]["name"] == "ebay"
    assert d[0]["adapters"][0]["added"] == 0
    assert not (conf / "data" / "work").exists()
