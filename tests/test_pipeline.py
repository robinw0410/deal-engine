"""End-to-end: json_file adapter, demo evaluator, two simulated days."""
import json

import yaml

from core import config as config_mod
from core.listing import normalize
from core.run import run_search

import pytest


def write_cfg(tmp_path):
    raw = yaml.safe_load(open(config_mod.ROOT / "config.example.yaml"))
    raw["data_dir"] = str(tmp_path)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw))
    return config_mod.load(p)


def listing(sid, title, price, **kw):
    return {"source_id": sid, "url": f"https://example.invalid/{sid}", "title": title, "price": price,
            "published": "2026-06-01", "shipping_possible": True, **kw}


def day(tmp_path, monkeypatch, d, rows):
    monkeypatch.setenv("DEAL_ENGINE_TODAY", d)
    (tmp_path / "listings.json").write_text(json.dumps({"listings": rows}))


def test_two_days(tmp_path, monkeypatch):
    from demo.evaluator import evaluate
    cfg = write_cfg(tmp_path)
    working = [listing(str(i), "Nintendo Switch Lite", 110 + i) for i in range(1, 9)]
    deal = listing("100", "Switch Lite – stick drift", 45)
    truth = {"100": {"group": "Switch Lite", "kind": "defect", "defect": "stick drift", "parts": 6, "hours": 1.0,
                     "risk": "low", "fraud": False, "typical": 115}}
    (tmp_path / "demo-truth.json").write_text(json.dumps(truth))

    day(tmp_path, monkeypatch, "2026-06-02", working + [deal])
    assert run_search(cfg, "electronics", evaluator=evaluate, render=False, log=lambda s: None)
    state = json.loads((tmp_path / "state" / "electronics.json").read_text())["listings"]
    assert [l["id"] for l in state] == ["json_file-100"]
    assert state[0]["market_group"] == "Switch Lite"
    assert "score_calc" in state[0]

    # next day: price drop, and one working unit disappears
    day(tmp_path, monkeypatch, "2026-06-03", working[1:] + [{**deal, "price": 40}])
    assert run_search(cfg, "electronics", evaluator=evaluate, render=True, log=lambda s: None)
    state = json.loads((tmp_path / "state" / "electronics.json").read_text())["listings"]
    assert state[0]["price"] == 40
    assert state[0]["price_history"] == [{"date": "2026-06-03", "price": 45}]
    report = (tmp_path / "reports" / "electronics-latest.md").read_text()
    assert "**Price changes**" in report
    assert (tmp_path / "web" / "electronics" / "index.html").exists()

    # third day: the deal is gone
    day(tmp_path, monkeypatch, "2026-06-04", working[1:])
    run_search(cfg, "electronics", evaluator=evaluate, render=False, log=lambda s: None)
    assert json.loads((tmp_path / "state" / "electronics.json").read_text())["listings"] == []
    assert "no longer online" in (tmp_path / "reports" / "electronics-latest.md").read_text()


FAKE_LLM = """
import re, sys, json
prompt = sys.stdin.read()
assert "--model" in sys.argv and "Search: used electronics" in prompt
cands = re.search(r"Read `([^`]+candidates-\\d+\\.json)`", prompt).group(1)
acc = re.search(r"Write `([^`]+accepted-\\d+\\.json)`", prompt).group(1)
ids = [c["source_id"] for c in json.load(open(cands))["candidates"]]
json.dump([{"source_id": i, "score": 6, "summary": "fake", "deal_type": "repair", "market_price": 120,
            "repair_parts_eur": 5, "repair_hours": 1, "risk": "low"} for i in ids], open(acc, "w"))
"""


def test_llm_evaluation_plumbing(tmp_path, monkeypatch):
    """The 'claude' evaluator path with a fake command instead of the real CLI."""
    import sys
    cfg = write_cfg(tmp_path)
    fake = tmp_path / "fake_llm.py"
    fake.write_text(FAKE_LLM)
    cfg["llm"] = {"command": [sys.executable, str(fake)], "extra_args": []}
    working = [listing(str(i), "Nintendo Switch Lite", 110 + i) for i in range(1, 9)]
    day(tmp_path, monkeypatch, "2026-06-02", working + [listing("100", "Switch Lite – stick drift", 45)])
    assert run_search(cfg, "electronics", evaluator="claude", render=False, log=lambda s: None)
    state = json.loads((tmp_path / "state" / "electronics.json").read_text())["listings"]
    assert [l["summary"] for l in state] == ["fake"]


def test_normalize_rejects_invalid():
    with pytest.raises(ValueError):
        normalize({"title": "x", "url": "https://e.invalid/1"}, "t")          # no source_id
    with pytest.raises(ValueError):
        normalize({"source_id": "1", "title": "x", "url": "ftp://x"}, "t")    # bad url
    it = normalize({"source_id": 1, "title": " x ", "url": "https://e.invalid/1", "price": "1.234,50",
                    "lat": 52.6, "lon": 13.4}, "t", home=(52.52, 13.405))
    assert it["price"] == 1234.5 and it["title"] == "x" and it["distance_km"] > 0
