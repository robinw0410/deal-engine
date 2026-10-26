"""Adapter registry. Add your own adapter here (see adapters/base.py)."""
from .base import Adapter, Blocked  # noqa: F401


def create(name, cfg, sc):
    if name == "json_file":
        from .json_file import JsonFileAdapter
        return JsonFileAdapter(cfg, sc)
    if name == "ebay":
        from .ebay import EbayAdapter
        return EbayAdapter(cfg, sc)
    raise SystemExit(f"Unknown adapter '{name}' (available: json_file, ebay)")
