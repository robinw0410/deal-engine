"""The adapter interface.

An adapter connects deal-engine to one listing source:

  search(query)               -> list of listings in the JSON format of docs/listing-format.md
  check(source_id)            -> (status, price): status "active" | "reserved" | "gone" | "unknown"
                                 ("unknown" if the check itself failed), price the current price or None
  details(item, max_images)   optional, data only available per listing (description, image URLs,
                                 more fields). Return {"reject": "reason"} to drop the candidate before
                                 evaluation (e.g. reserved in the meantime).
  fetch_image(url)            optional, download one photo with the adapter's own rate and headers;
                                 return the bytes or None. Without it the pipeline downloads photos itself.

Raise Blocked when the source refuses further requests (rate limit, quota): the run for this
adapter stops and the problem is reported. Raise ConfigError (deal_engine.core.config) in
__init__ when the adapter cannot run with the configuration (missing credentials, missing
settings); it never falls back to anything else.

An adapter can append short messages to self.warnings when part of a search failed but the rest
is usable (e.g. one of several requests); the pipeline reports them as problems of the run and goes on.

Settings of an adapter live in the search config under its name (sc[self.name]); the generic
key max_new_per_run there overrides the search's max_new_per_run for this adapter.

Please read "Data sources" in the README before writing an adapter: prefer official APIs, respect
the source's terms of service and robots rules, and never work around access restrictions.
"""
from ..core.config import ConfigError  # noqa: F401  (re-exported for adapters)


class Blocked(Exception):
    """The source refuses further requests (rate limit, quota). Aborts the run for this adapter."""


STATUSES = ("active", "reserved", "gone", "unknown")


class Adapter:
    name = "base"

    def __init__(self, cfg, sc):
        """cfg: whole config, sc: search config. Adapter settings live in sc[self.name]."""
        self.cfg = cfg
        self.sc = sc
        self.settings = sc.get(self.name) or {}
        self.requests = 0
        self.warnings = []      # partial failures, reported by the pipeline as problems

    def search(self, query):
        """query: {"keyword": str or None, "min_price": number or None, "max_price": number or None}.
        keyword None means "everything this adapter is configured for"."""
        raise NotImplementedError

    def check(self, source_id):
        """(status, current price or None)."""
        raise NotImplementedError

    def details(self, item, max_images=1):
        """Optional: {"description": ..., "images": [urls], "attrs": {...}, <more fields>} merged into the
        item, or {"reject": "reason"} to drop the candidate."""
        return {}

    def fetch_image(self, url):
        """Optional: bytes of one photo, or None. Only called if a subclass overrides it."""
        return None

    def has_fetch_image(self):
        return type(self).fetch_image is not Adapter.fetch_image


def check_result(r):
    """Normalize what check() returned to (status, price)."""
    from ..core.util import num
    if isinstance(r, (tuple, list)) and r:
        st, price = r[0], (num(r[1]) if len(r) > 1 else None)
    else:
        st, price = r, None
    st = str(st or "unknown").lower()
    return (st if st in STATUSES else "unknown"), price
