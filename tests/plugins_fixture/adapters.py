"""Configurable test adapters. Tests set the class attributes with monkeypatch."""
from deal_engine.adapters.base import Adapter, Blocked


class FakeAdapter(Adapter):
    name = "fake_class_name"          # deliberately differs from the registered name
    ROWS = []                         # search() results
    CHECK = {}                        # source_id -> what check() returns
    DETAILS = {}                      # source_id -> what details() returns
    SEARCH_RAISES = None              # exception instance raised by search()
    CHECKED = []                      # source_ids check() was called with

    def search(self, query):
        self.requests += 1
        if self.SEARCH_RAISES is not None:
            raise self.SEARCH_RAISES
        return [dict(r) for r in self.ROWS]

    def check(self, source_id):
        type(self).CHECKED.append(source_id)
        return self.CHECK.get(source_id, ("gone", None))

    def details(self, item, max_images=1):
        return dict(self.DETAILS.get(item["source_id"]) or {})


class FakeImageAdapter(FakeAdapter):
    IMAGES = {}                       # url -> bytes
    FETCHED = []

    def fetch_image(self, url):
        type(self).FETCHED.append(url)
        return self.IMAGES.get(url)


class NotAnAdapter:
    name = "nope"

    def __init__(self, cfg, sc):
        pass


__all__ = ["FakeAdapter", "FakeImageAdapter", "NotAnAdapter", "Blocked"]
