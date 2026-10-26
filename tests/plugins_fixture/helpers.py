"""Shared helpers for the v0.2 tests: config files, listings, a trivial evaluator."""
import json
import sys
from pathlib import Path

import yaml

from deal_engine.core import config as config_mod
from deal_engine.core.util import load_json, save_json

REPO = Path(__file__).resolve().parents[2]
PROFILE = REPO / "profiles" / "electronics.md"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def quiet(*a, **k):
    pass


def listing(sid, title="Nintendo Switch Lite", price=100, **kw):
    return {"source_id": str(sid), "url": f"https://example.invalid/{sid}", "title": title, "price": price,
            "published": "2026-06-01", "shipping_possible": True, **kw}


def search_cfg(**kw):
    """A small search: no market, no tracking, no score unless given."""
    return {"adapters": ["json_file"], "track": False, "images": 0, **kw}


def write_cfg(folder, searches, **top):
    """Write config.yaml into folder (created) and load it. data_dir defaults to "data"
    (relative, so below folder)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    raw = {"data_dir": "data", "searches": searches, **top}
    p = folder / "config.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True))
    return config_mod.load(p)


def write_listings(cfg, rows, name="listings.json"):
    p = cfg["_data"] / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"listings": rows}))
    return p


def accept_all(work, cfg, sc, extra=None):
    """Evaluator: every candidate is accepted (optionally with extra evaluation fields per source_id)."""
    for cf in sorted(work.glob("candidates-*.json")):
        acc = [{"source_id": c["source_id"], "summary": "ok", "score": 6, "tier": "B",
                **((extra or {}).get(c["source_id"]) or {})}
               for c in load_json(cf, {}).get("candidates", [])]
        save_json(cf.with_name(cf.name.replace("candidates-", "accepted-")), acc)


def no_accepted(work, cfg, sc):
    """Evaluator that fails: writes nothing."""


def state(cfg, name):
    return load_json(config_mod.paths(cfg, name)["state"], {"listings": []})["listings"]


def report(cfg, name):
    return config_mod.paths(cfg, name)["report"].read_text()


def work_dir(cfg, name, adapter):
    return config_mod.paths(cfg, name, adapter)["work"]


def batch(cfg, name, adapter, n=1):
    return load_json(work_dir(cfg, name, adapter) / f"candidates-{n}.json", {})


def snapshot_syspath(monkeypatch):
    """config.load() inserts plugin_paths into sys.path; restore it after the test."""
    monkeypatch.setattr(sys, "path", list(sys.path))
