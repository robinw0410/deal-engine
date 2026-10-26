"""Listings from a local JSON file (docs/listing-format.md).

Useful for the demo, for tests, and for feeding listings that you collect some other way
(an export, a feed you are allowed to use, manual entries). The file is either a list of
listings or {"listings": [...]}.

Search config:
  json_file:
    path: "{data_dir}/listings.json"

check(): a listing that is no longer in the file counts as gone; otherwise its status and price.
"""
import json
import re

from ..core.config import ConfigError, resolve
from .base import Adapter


class JsonFileAdapter(Adapter):
    name = "json_file"

    def __init__(self, cfg, sc):
        super().__init__(cfg, sc)
        if not self.settings.get("path"):
            raise ConfigError(f"search '{sc['_name']}': json_file.path is not set")
        self.path = resolve(self.settings["path"], cfg)
        self._cache = None

    def _all(self):
        if self._cache is None:
            self.requests += 1
            try:
                data = json.loads(self.path.read_text())
            except FileNotFoundError:
                raise ConfigError(f"json_file: {self.path} does not exist")
            rows = data.get("listings", []) if isinstance(data, dict) else data
            self._cache = {str(r.get("source_id")): r for r in rows if isinstance(r, dict)}
        return self._cache

    def search(self, query):
        kw = [w for w in re.split(r"\s+", str(query.get("keyword") or "").lower()) if w]
        lo, hi = query.get("min_price"), query.get("max_price")
        out = []
        for r in self._all().values():
            title = str(r.get("title") or "").lower()
            if kw and not all(w in title for w in kw):
                continue
            p = r.get("price")
            if isinstance(p, (int, float)) and ((lo is not None and p < lo) or (hi is not None and p > hi)):
                continue
            out.append(r)
        return out

    def check(self, source_id):
        r = self._all().get(str(source_id))
        if r is None:
            return "gone", None
        return ("reserved" if str(r.get("status") or "").lower() == "reserved" else "active"), r.get("price")
