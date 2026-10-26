"""Configuration loading (YAML) and the file layout below data_dir.

Lookup order for the config file: explicit path, $DEAL_ENGINE_CONFIG, ./config.yaml, ./config.example.yaml.
$DEAL_ENGINE_DATA_DIR overrides data_dir (the demo uses this to keep its data separate).
"""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

SEARCH_DEFAULTS = {
    "adapters": ["json_file"],
    "keywords": [],
    "filters": {},
    "market": {},
    "score": {},
    "max_new_per_run": 50,
    "batch_size": 25,
    "images": 1,
    "track": True,
    "prefilter": False,
    "classify": False,
}


def load(path=None):
    candidates = [path, os.environ.get("DEAL_ENGINE_CONFIG"), ROOT / "config.yaml", ROOT / "config.example.yaml"]
    for c in candidates:
        if c and Path(c).exists():
            p = Path(c)
            break
    else:
        raise SystemExit("No config found. Copy config.example.yaml to config.yaml.")
    cfg = yaml.safe_load(p.read_text()) or {}
    cfg["_path"] = str(p)
    data = os.environ.get("DEAL_ENGINE_DATA_DIR") or cfg.get("data_dir") or "data"
    cfg["_data"] = resolve(data)
    return cfg


def resolve(p, cfg=None):
    """Relative paths are relative to the repo root; "{data_dir}" expands to the data directory."""
    s = str(p)
    if cfg is not None:
        s = s.replace("{data_dir}", str(cfg["_data"]))
    q = Path(s)
    return q if q.is_absolute() else ROOT / q


def home(cfg):
    loc = cfg.get("location") or {}
    if loc.get("lat") is None or loc.get("lon") is None:
        return None
    return float(loc["lat"]), float(loc["lon"])


def search_names(cfg):
    return list((cfg.get("searches") or {}).keys())


def search(cfg, name):
    raw = (cfg.get("searches") or {}).get(name)
    if raw is None:
        raise SystemExit(f"Unknown search '{name}'. Known: {', '.join(search_names(cfg)) or '-'}")
    sc = {**SEARCH_DEFAULTS, **raw}
    sc["_name"] = name
    return sc


def paths(cfg, name, adapter=None):
    d = cfg["_data"]
    out = {
        "state": d / "state" / f"{name}.json",
        "market": d / "state" / f"{name}-market.json",
        "history": d / "state" / "history.db",
        "deals": d / "state" / "deals.db",
        "report": d / "reports" / f"{name}-latest.md",
        "reports": d / "reports",
        "web": resolve((cfg.get("web") or {}).get("root", "{data_dir}/web"), cfg),
    }
    if adapter:
        out["seen"] = d / "state" / f"{name}-{adapter}-seen.json"
        out["work"] = d / "work" / name / adapter
    return out
