"""The adapter interface.

An adapter connects deal-engine to one listing source. It needs two methods:

  search(query) -> list of listings in the JSON format of docs/listing-format.md
  check(source_id) -> "active" | "gone" | "reserved"   ("unknown" if the check itself failed)

and may implement details(item, max_images) for data that is only available per listing
(full description, image URLs). Everything else - filtering, market prices, tracking, scoring,
merging - happens in core/ and is the same for all adapters.

Please read "Data sources" in the README before writing an adapter: prefer official APIs, respect
the source's terms of service and robots rules, and never work around access restrictions.
"""


class Blocked(Exception):
    """The source refuses further requests (rate limit, quota). Aborts the run for this adapter."""


class Adapter:
    name = "base"

    def __init__(self, cfg, sc):
        """cfg: whole config, sc: search config. Adapter settings live in sc[self.name]."""
        self.cfg = cfg
        self.sc = sc
        self.settings = sc.get(self.name) or {}
        self.requests = 0

    def search(self, query):
        """query: {"keyword": str or None, "min_price": number or None, "max_price": number or None}.
        keyword None means "everything this adapter is configured for"."""
        raise NotImplementedError

    def check(self, source_id):
        raise NotImplementedError

    def details(self, item, max_images=1):
        """Optional: {"description": ..., "images": [urls], "attrs": {...}, ...} merged into the item."""
        return {}
