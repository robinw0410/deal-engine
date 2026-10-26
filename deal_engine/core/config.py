"""Configuration loading (YAML) and the file layout below data_dir.

Lookup order for the config file: explicit path, $DEAL_ENGINE_CONFIG, ./config.yaml, ./config.example.yaml
(./ = the current working directory).

Relative paths inside the config (data_dir, profile, prompts, json_file paths, web.root,
plugin_paths) are relative to the directory of the config file, never to the installation of
deal-engine. "{data_dir}" expands to the data directory. $DEAL_ENGINE_DATA_DIR overrides data_dir
(relative to the current working directory; the demo uses it to keep its data separate).
"""
import os
import sys
from pathlib import Path

import yaml

PACKAGE = Path(__file__).resolve().parent.parent

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
    "wanted_ads": "reject",
}


class ConfigError(Exception):
    """The configuration cannot work as written (unknown adapter, missing credentials, bad value)."""


def load(path=None):
    candidates = [path, os.environ.get("DEAL_ENGINE_CONFIG"), Path.cwd() / "config.yaml",
                  Path.cwd() / "config.example.yaml"]
    for c in candidates:
        if c and Path(c).exists():
            p = Path(c).resolve()
            break
    else:
        raise ConfigError("No config found. Copy config.example.yaml to config.yaml.")
    cfg = yaml.safe_load(p.read_text()) or {}
    cfg["_path"] = str(p)
    cfg["_base"] = p.parent
    env = os.environ.get("DEAL_ENGINE_DATA_DIR")
    cfg["_data"] = Path(env).resolve() if env else resolve(cfg.get("data_dir") or "data", cfg)
    cfg["locale"] = _locale(cfg.get("locale"), "locale")
    for d in cfg.get("plugin_paths") or []:   # where "module:Class" plugins of this config live
        d = str(resolve(d, cfg))
        if d not in sys.path:
            sys.path.insert(0, d)
    return cfg


def _locale(code, where):
    from .locale import LOCALES
    code = str(code or "en")
    if code not in LOCALES:
        raise ConfigError(f"{where}: unknown locale '{code}' (available: {', '.join(LOCALES)})")
    return code


def resolve(p, cfg):
    """Relative paths are relative to the config file; "{data_dir}" expands to the data directory."""
    s = str(p)
    if "_data" in cfg:
        s = s.replace("{data_dir}", str(cfg["_data"]))
    q = Path(s).expanduser()
    return q if q.is_absolute() else Path(cfg["_base"]) / q


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
        raise ConfigError(f"Unknown search '{name}'. Known: {', '.join(search_names(cfg)) or '-'}")
    sc = {**SEARCH_DEFAULTS, **raw}
    sc["_name"] = name
    sc["_locale"] = _locale(raw.get("locale") or cfg.get("locale"), f"searches.{name}.locale")
    if sc["wanted_ads"] not in ("reject", "accept"):
        raise ConfigError(f"search '{name}': wanted_ads must be 'reject' or 'accept', not {sc['wanted_ads']!r}")
    return sc


def prompt_path(cfg, sc, name):
    """Prompt file for an LLM step: search prompts.<name>, then global prompts.<name>, then the
    built-in prompt for the locale (falls back to English)."""
    p = ((sc or {}).get("prompts") or {}).get(name) or (cfg.get("prompts") or {}).get(name)
    if p:
        q = resolve(p, cfg)
        if not q.exists():
            raise ConfigError(f"prompt file for '{name}' not found: {q}")
        return q
    loc = (sc or {}).get("_locale") or cfg.get("locale") or "en"
    q = PACKAGE / "core" / "prompts" / loc / f"{name}.md"
    return q if q.exists() else PACKAGE / "core" / "prompts" / "en" / f"{name}.md"


def paths(cfg, name, adapter=None):
    d = cfg["_data"]
    web = (cfg.get("web") or {}).get("root", "{data_dir}/web")
    out = {
        "state": d / "state" / f"{name}.json",
        "market": d / "state" / f"{name}-market.json",
        "history": d / "state" / "history.db",
        "deals": d / "state" / "deals.db",
        "report": d / "reports" / f"{name}-latest.md",
        "reports": d / "reports",
        "web": resolve(web, cfg),
    }
    if adapter:
        out["seen"] = d / "state" / f"{name}-{adapter}-seen.json"
        out["work"] = d / "work" / name / adapter
    return out
