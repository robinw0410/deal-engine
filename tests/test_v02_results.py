"""v0.2 structured results: RunResult/AdapterResult statuses, report, CLI --json and exit codes."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from deal_engine.adapters.base import Blocked
from deal_engine.core import pipeline
from deal_engine.core.run import AdapterResult, RunResult, run_search
from deal_engine.core.util import save_json
from plugins_fixture import adapters as fx
from plugins_fixture.helpers import (accept_all, listing, no_accepted, quiet, report, search_cfg, state, write_cfg,
                                     write_listings)

REPO = Path(__file__).resolve().parent.parent
FAKE = "plugins_fixture.adapters:FakeAdapter"


@pytest.fixture(autouse=True)
def fresh_fakes(monkeypatch):
    for attr, v in (("ROWS", []), ("CHECK", {}), ("DETAILS", {}), ("SEARCH_RAISES", None), ("CHECKED", [])):
        monkeypatch.setattr(fx.FakeAdapter, attr, v)


def cfg_for(tmp_path, adapters_, **search):
    return write_cfg(tmp_path, {"s": search_cfg(adapters=adapters_, json_file={"path": "{data_dir}/l.json"},
                                                **search)}, adapters={"fake": FAKE})


def run(cfg, evaluator=accept_all):
    return run_search(cfg, "s", evaluator=evaluator, render=False, log=quiet)


def test_ok(tmp_path):
    cfg = cfg_for(tmp_path, ["json_file"])
    write_listings(cfg, [listing("1")], "l.json")
    res = run(cfg)
    assert isinstance(res, RunResult) and res.ok and bool(res) and res.failed == []
    (ar,) = res.adapters
    assert isinstance(ar, AdapterResult) and ar.ok
    assert (ar.status, ar.reason, ar.error, ar.found, ar.candidates, ar.added, ar.requests) == \
        ("ok", "", "", 1, 1, 1, 1)
    assert res.search == "s" and res.changed and Path(res.report).exists()


def test_no_changes_report(tmp_path):
    cfg = cfg_for(tmp_path, ["json_file"])
    write_listings(cfg, [], "l.json")
    res = run(cfg)
    assert res.ok and not res.changed and report(cfg, "s") == "NO_CHANGES\n"


def test_unknown_adapter_failed_config_error(tmp_path):
    cfg = cfg_for(tmp_path, ["json_file", "nope"])
    write_listings(cfg, [listing("1")], "l.json")
    res = run(cfg)
    assert not res and not res.ok
    ok, bad = res.adapters
    assert ok.status == "ok" and ok.added == 1
    assert (bad.name, bad.status, bad.reason) == ("nope", "failed", "config_error")
    assert "unknown adapter 'nope'" in bad.error and "json_file" in bad.error
    assert res.failed == [bad]
    rep = report(cfg, "s")
    assert "**Problem:** nope: unknown adapter 'nope'" in rep and "## json_file" in rep


def test_blocked_is_partial(tmp_path, monkeypatch):
    cfg = cfg_for(tmp_path, ["fake"])
    st = {"listings": [{"id": "fake-9", "title": "kept", "price": 5, "sources": {"fake": "9"}, "urls": []}]}
    save_json(cfg["_data"] / "state" / "s.json", st)
    monkeypatch.setattr(fx.FakeAdapter, "SEARCH_RAISES", Blocked("HTTP 429 rate limit"))
    res = run(cfg)
    (ar,) = res.adapters
    assert (ar.status, ar.reason) == ("partial", "blocked") and "429" in ar.error
    assert not res and fx.FakeAdapter.CHECKED == []
    assert [l["id"] for l in state(cfg, "s")] == ["fake-9"]
    assert "fake blocked: HTTP 429 rate limit" in report(cfg, "s")


def test_blocked_in_check_is_partial(tmp_path, monkeypatch):
    cfg = cfg_for(tmp_path, ["fake"])
    save_json(cfg["_data"] / "state" / "s.json",
              {"listings": [{"id": "fake-9", "title": "kept", "price": 5, "sources": {"fake": "9"}}]})

    def check(self, sid):
        raise Blocked("quota")
    monkeypatch.setattr(fx.FakeAdapter, "check", check)
    res = run(cfg)
    assert (res.adapters[0].status, res.adapters[0].reason) == ("partial", "blocked")
    assert [l["id"] for l in state(cfg, "s")] == ["fake-9"]


def test_evaluation_failed_is_partial(tmp_path):
    cfg = cfg_for(tmp_path, ["json_file"])
    write_listings(cfg, [listing("1"), listing("2")], "l.json")
    res = run(cfg, evaluator=no_accepted)
    (ar,) = res.adapters
    assert (ar.status, ar.reason, ar.candidates, ar.added) == ("partial", "evaluation_failed", 2, 0)
    assert "1 evaluation batch(es) failed" in ar.error
    assert "evaluation of batch 1 failed (2 candidates" in report(cfg, "s")
    # the candidates are retried in the next run
    res = run(cfg)
    assert res.ok and res.adapters[0].added == 2


def test_search_error_is_partial_problems(tmp_path, monkeypatch):
    cfg = cfg_for(tmp_path, ["fake"])
    monkeypatch.setattr(fx.FakeAdapter, "SEARCH_RAISES", RuntimeError("HTTP 500"))
    (ar,) = run(cfg).adapters
    assert (ar.status, ar.reason) == ("partial", "problems") and "HTTP 500" in ar.error
    assert ar.problems and "HTTP 500" in ar.problems[0]


def test_invalid_listings_are_partial_problems(tmp_path):
    cfg = cfg_for(tmp_path, ["json_file"])
    write_listings(cfg, [listing("1"), {"source_id": "2", "title": "no url"}], "l.json")
    (ar,) = run(cfg).adapters
    assert (ar.status, ar.reason, ar.added) == ("partial", "problems", 1)
    assert "1 invalid listings" in ar.error


def test_unexpected_exception_failed_error_and_state_restored(tmp_path, monkeypatch):
    cfg = cfg_for(tmp_path, ["fake", "json_file"])
    write_listings(cfg, [listing("1")], "l.json")
    good = {"listings": [{"id": "fake-9", "title": "kept", "price": 5, "sources": {"fake": "9"}}]}
    save_json(cfg["_data"] / "state" / "s.json", good)
    real = pipeline.reconcile

    def broken(state, items, adapter, *a, **k):
        if adapter.name == "fake":
            state["listings"] = "corrupted"        # saved by collect, then select() crashes on it
            return
        return real(state, items, adapter, *a, **k)
    monkeypatch.setattr(pipeline, "reconcile", broken)
    res = run(cfg)
    fake, js = res.adapters
    assert (fake.status, fake.reason) == ("failed", "error")
    assert fake.error.startswith("AttributeError")
    assert js.status == "ok" and js.added == 1
    # the corrupted state was rolled back before json_file ran
    assert sorted(l["id"] for l in state(cfg, "s")) == ["fake-9", "json_file-1"]
    assert "**Problem:** fake: AttributeError" in report(cfg, "s")


def test_exception_in_collect(tmp_path, monkeypatch):
    cfg = cfg_for(tmp_path, ["fake"])

    def boom(*a, **k):
        raise KeyError("market")
    monkeypatch.setattr(pipeline, "update_market", boom)
    (ar,) = run(cfg).adapters
    assert (ar.status, ar.reason) == ("failed", "error") and "KeyError" in ar.error


def test_config_error_during_collect(tmp_path):
    cfg = cfg_for(tmp_path, ["json_file"])    # listings file does not exist
    (ar,) = run(cfg).adapters
    assert (ar.status, ar.reason) == ("failed", "config_error") and "does not exist" in ar.error


def test_to_dict_json_serializable(tmp_path):
    cfg = cfg_for(tmp_path, ["json_file", "nope"])
    write_listings(cfg, [listing("1"), {"bad": 1}], "l.json")
    d = run(cfg).to_dict()
    s = json.loads(json.dumps(d))
    assert s["ok"] is False and s["search"] == "s" and isinstance(s["report"], str)
    assert [a["name"] for a in s["adapters"]] == ["json_file", "nope"]
    assert s["adapters"][1]["reason"] == "config_error"
    assert set(AdapterResult.__dataclass_fields__) <= set(s["adapters"][0])


def test_bool_of_empty_result():
    assert RunResult(search="x").ok   # no adapters: nothing failed
    assert not RunResult(search="x", adapters=[AdapterResult(name="a", status="partial")])


# --- CLI ------------------------------------------------------------------------------------------

def cli(tmp_path, searches, *args, files=None):
    conf = tmp_path / "conf"
    (conf / "data").mkdir(parents=True, exist_ok=True)
    (conf / "config.yaml").write_text(yaml.safe_dump({"data_dir": "data", "searches": searches}))
    for name, rows in (files or {}).items():
        (conf / "data" / name).write_text(json.dumps(rows))
    out = tmp_path / "out.json"
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    for k in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "DEAL_ENGINE_CONFIG", "DEAL_ENGINE_DATA_DIR"):
        env.pop(k, None)
    r = subprocess.run([sys.executable, "-m", "deal_engine", "--config", str(conf / "config.yaml"), "run",
                        "--json", str(out), *args], cwd=tmp_path, env=env, capture_output=True, text=True,
                       timeout=120)
    return r, (json.loads(out.read_text()) if out.exists() else None)


JS = {"json_file": {"path": "{data_dir}/l.json"}}


def test_cli_ok_exit_0(tmp_path):
    r, data = cli(tmp_path, {"s": search_cfg(**JS)}, files={"l.json": []})
    assert r.returncode == 0, r.stderr
    assert data[0]["ok"] is True and data[0]["adapters"][0]["status"] == "ok"
    assert "s / json_file: ok" in r.stdout


def test_cli_partial_exit_1(tmp_path):
    r, data = cli(tmp_path, {"s": search_cfg(**JS)}, files={"l.json": [{"source_id": "1"}]})
    assert r.returncode == 1, r.stderr
    assert data[0]["adapters"][0]["status"] == "partial" and data[0]["adapters"][0]["reason"] == "problems"


def test_cli_config_error_exit_2(tmp_path):
    r, data = cli(tmp_path, {"s": search_cfg(adapters=["nope"])})
    assert r.returncode == 2
    assert data[0]["adapters"][0]["reason"] == "config_error"
    assert "unknown adapter" in r.stderr


def test_cli_config_error_wins_over_ok_search(tmp_path):
    r, data = cli(tmp_path, {"a": search_cfg(**JS), "b": search_cfg(adapters=["nope"])}, files={"l.json": []})
    assert r.returncode == 2 and [d["search"] for d in data] == ["a", "b"]


def test_cli_demo_evaluator(tmp_path):
    truth = {"1": {"group": "Switch Lite", "kind": "defect", "defect": "stick drift", "parts": 6, "hours": 1.0,
                   "risk": "low", "fraud": False, "typical": 115}}
    r, data = cli(tmp_path, {"s": search_cfg(**JS)}, "--evaluator", "demo", "s",
                  files={"l.json": [listing("1", title="Switch Lite drift", price=30)], "demo-truth.json": truth})
    assert r.returncode == 0, r.stderr
    assert data[0]["adapters"][0]["added"] == 1


def test_cli_unknown_search_exit_2(tmp_path):
    r, data = cli(tmp_path, {"s": search_cfg(**JS)}, "other", files={"l.json": []})
    assert r.returncode == 2 and "Unknown search 'other'" in r.stderr


def test_cli_missing_config_exit_2(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "DEAL_ENGINE_CONFIG"}
    env["PYTHONPATH"] = str(REPO)
    r = subprocess.run([sys.executable, "-m", "deal_engine", "--config", str(tmp_path / "none.yaml"), "run"],
                       cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "configuration error" in r.stderr
