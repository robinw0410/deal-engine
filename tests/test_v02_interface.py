"""v0.2 adapter interface: check() -> (status, price), details() reject, fetch_image(),
per-adapter max_new_per_run, history.check_gone with prices."""
import sqlite3

import pytest

from deal_engine.adapters.base import Adapter, check_result
from deal_engine.core import history, pipeline
from deal_engine.core.listing import normalize
from deal_engine.core.run import run_search
from plugins_fixture import adapters as fx
from plugins_fixture.helpers import (JPEG, PNG, accept_all, batch, listing, quiet, report, search_cfg, state,
                                     work_dir, write_cfg)

FAKE = "plugins_fixture.adapters:FakeAdapter"
FAKE_IMG = "plugins_fixture.adapters:FakeImageAdapter"


@pytest.fixture(autouse=True)
def fresh_fakes(monkeypatch):
    for cls in (fx.FakeAdapter, fx.FakeImageAdapter):
        for attr, v in (("ROWS", []), ("CHECK", {}), ("DETAILS", {}), ("SEARCH_RAISES", None), ("CHECKED", [])):
            monkeypatch.setattr(cls, attr, v)
    monkeypatch.setattr(fx.FakeImageAdapter, "IMAGES", {})
    monkeypatch.setattr(fx.FakeImageAdapter, "FETCHED", [])
    monkeypatch.setenv("DEAL_ENGINE_TODAY", "2026-06-02")


def fake_cfg(tmp_path, adapter="fake", spec=FAKE, **search):
    return write_cfg(tmp_path, {"s": search_cfg(adapters=[adapter], **search)}, adapters={adapter: spec})


def run(cfg, evaluator=accept_all):
    return run_search(cfg, "s", evaluator=evaluator, render=False, log=quiet)


def _day1(tmp_path, monkeypatch, **search):
    cfg = fake_cfg(tmp_path, **search)
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", [listing("1", price=100)])
    res = run(cfg)
    assert res.ok and [l["id"] for l in state(cfg, "s")] == ["fake-1"]
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", [])      # day 2: no longer in the search results
    monkeypatch.setenv("DEAL_ENGINE_TODAY", "2026-06-03")
    return cfg


# --- check() --------------------------------------------------------------------------------------

def test_check_tuple_updates_price(tmp_path, monkeypatch):
    cfg = _day1(tmp_path, monkeypatch)
    monkeypatch.setattr(fx.FakeAdapter, "CHECK", {"1": ("active", 80)})
    res = run(cfg)
    assert res.ok and res.adapters[0].price_changes == 1
    assert fx.FakeAdapter.CHECKED == ["1"]
    (l,) = state(cfg, "s")
    assert l["price"] == 80
    assert l["price_history"] == [{"date": "2026-06-03", "price": 100}]
    assert l["last_seen"] == "2026-06-03"
    assert "Price changes" in report(cfg, "s")


def test_check_tuple_with_string_price(tmp_path, monkeypatch):
    cfg = _day1(tmp_path, monkeypatch)
    monkeypatch.setattr(fx.FakeAdapter, "CHECK", {"1": ["active", "1.234,50 €"]})
    run(cfg)
    assert state(cfg, "s")[0]["price"] == 1234.5


def test_check_plain_string_still_works(tmp_path, monkeypatch):
    cfg = _day1(tmp_path, monkeypatch)
    monkeypatch.setattr(fx.FakeAdapter, "CHECK", {"1": "reserved"})
    res = run(cfg)
    assert res.ok
    (l,) = state(cfg, "s")
    assert l["status"] == "reserved" and l["price"] == 100 and l["price_history"] == []


def test_check_gone_removes(tmp_path, monkeypatch):
    cfg = _day1(tmp_path, monkeypatch)
    monkeypatch.setattr(fx.FakeAdapter, "CHECK", {"1": "gone"})
    res = run(cfg)
    assert state(cfg, "s") == [] and res.adapters[0].gone == 1


def test_check_unknown_status_marks_failed_check(tmp_path, monkeypatch):
    cfg = _day1(tmp_path, monkeypatch)
    monkeypatch.setattr(fx.FakeAdapter, "CHECK", {"1": "nonsense-status"})
    run(cfg)
    (l,) = state(cfg, "s")
    assert l["last_check_failed"] == "2026-06-03"


@pytest.mark.parametrize("r,expected", [
    ("active", ("active", None)),
    ("ACTIVE", ("active", None)),
    ("reserved", ("reserved", None)),
    ("gone", ("gone", None)),
    ("weird", ("unknown", None)),
    (None, ("unknown", None)),
    (("active", 50), ("active", 50.0)),
    (["reserved", "80"], ("reserved", 80.0)),
    (("gone",), ("gone", None)),
    (("active", None), ("active", None)),
    (("active", "n/a"), ("active", None)),
])
def test_check_result(r, expected):
    assert check_result(r) == expected


# --- details() ------------------------------------------------------------------------------------

def test_details_reject_drops_candidate(tmp_path, monkeypatch):
    cfg = fake_cfg(tmp_path)
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", [listing("1"), listing("2"), listing("3")])
    monkeypatch.setattr(fx.FakeAdapter, "DETAILS", {"2": {"reject": "reserved"},
                                                    "3": {"status": "reserved"},
                                                    "1": {"description": "more text", "km": 1200}})
    res = run(cfg)
    ar = res.adapters[0]
    assert res.ok and (ar.found, ar.candidates, ar.rejected, ar.added) == (3, 1, 2, 1)
    b = batch(cfg, "s", "fake")
    assert [c["source_id"] for c in b["candidates"]] == ["1"]
    assert b["candidates"][0]["description"] == "more text" and b["candidates"][0]["km"] == 1200
    assert b["extra"] == {"1": ["km"]}
    assert [l["id"] for l in state(cfg, "s")] == ["fake-1"]


# --- fetch_image() ----------------------------------------------------------------------------------

def test_adapter_fetch_image_used_instead_of_urllib(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "_fetch", lambda u: calls.append(u) or JPEG)
    cfg = fake_cfg(tmp_path, adapter="fimg", spec=FAKE_IMG, images=3)
    urls = ["https://img.invalid/a.jpg", "https://img.invalid/b.jpg", "https://img.invalid/c.png"]
    monkeypatch.setattr(fx.FakeImageAdapter, "ROWS", [listing("1", images=urls)])
    monkeypatch.setattr(fx.FakeImageAdapter, "IMAGES", {urls[0]: JPEG, urls[1]: b"<html>not an image</html>",
                                                        urls[2]: PNG})
    res = run(cfg)
    assert res.ok
    assert calls == []                                 # urllib path never used
    assert fx.FakeImageAdapter.FETCHED == urls
    imgs = batch(cfg, "s", "fimg")["candidates"][0]["images"]
    assert [i.rsplit("/", 1)[1] for i in imgs] == ["1-1.jpg", "1-3.png"]   # the HTML bytes were discarded
    for i in imgs:
        assert (cfg["_data"] / i).exists()
    assert len(list((work_dir(cfg, "s", "fimg") / "img").iterdir())) == 2


def test_without_fetch_image_pipeline_downloads(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "_fetch", lambda u: calls.append(u) or PNG)
    cfg = fake_cfg(tmp_path, images=1)
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", [listing("1", images=["https://img.invalid/a", "https://x/b"])])
    run(cfg)
    assert calls == ["https://img.invalid/a"]        # images: 1
    assert batch(cfg, "s", "fake")["candidates"][0]["images"][0].endswith("1-1.png")


def test_download_images_unit(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_fetch", lambda u: pytest.fail("urllib used"))
    a = fx.FakeImageAdapter({}, {"_name": "s"})
    monkeypatch.setattr(fx.FakeImageAdapter, "IMAGES", {"https://i/1": JPEG, "https://i/2": b"GIF89a" + b"\0" * 10,
                                                        "https://i/3": b"plain text"})
    assert a.has_fetch_image() and not fx.FakeAdapter({}, {"_name": "s"}).has_fetch_image()
    files = pipeline.download_images(["file:///etc/passwd", "https://i/1", "https://i/2", "https://i/3", "https://i/4"],
                                     tmp_path, "x", tmp_path, a)
    assert files == ["x-2.jpg", "x-3.gif"]
    assert "file:///etc/passwd" not in fx.FakeImageAdapter.FETCHED


def test_fetch_image_too_large_discarded(tmp_path, monkeypatch):
    a = fx.FakeImageAdapter({}, {"_name": "s"})
    monkeypatch.setattr(fx.FakeImageAdapter, "IMAGES", {"https://i/1": JPEG + b"\0" * pipeline.MAX_IMAGE_BYTES})
    assert pipeline.download_images(["https://i/1"], tmp_path, "x", tmp_path, a) == []


def test_fetch_image_blocked_propagates(tmp_path):
    class B(Adapter):
        name = "b"

        def fetch_image(self, url):
            raise fx.Blocked("rate limit")
    with pytest.raises(fx.Blocked):
        pipeline.download_images(["https://i/1"], tmp_path, "x", tmp_path, B({}, {}))


# --- max_new_per_run ------------------------------------------------------------------------------

def test_adapter_max_new_per_run_overrides_search(tmp_path, monkeypatch):
    cfg = fake_cfg(tmp_path, max_new_per_run=5, fake={"max_new_per_run": 1})
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", [listing(str(i)) for i in range(1, 4)])
    res = run(cfg)
    ar = res.adapters[0]
    assert (ar.candidates, ar.postponed, ar.added) == (1, 2, 1)
    assert "2 more candidates" in report(cfg, "s")


def test_search_max_new_per_run_without_adapter_setting(tmp_path, monkeypatch):
    cfg = fake_cfg(tmp_path, max_new_per_run=2)
    monkeypatch.setattr(fx.FakeAdapter, "ROWS", [listing(str(i)) for i in range(1, 4)])
    ar = run(cfg).adapters[0]
    assert (ar.candidates, ar.postponed) == (2, 1)


def test_max_new_unit():
    sc = {"max_new_per_run": 7, "a": {"max_new_per_run": 0}, "b": {}}
    assert pipeline.max_new(sc, "a") == 0
    assert pipeline.max_new(sc, "b") == 7
    assert pipeline.max_new(sc, "c") == 7
    assert pipeline.max_new(sc) == 7
    assert pipeline.max_new({}, "a") == 50


# --- history.check_gone ---------------------------------------------------------------------------

class Checker:
    def __init__(self, name, results):
        self.name, self.results, self.calls = name, results, []

    def check(self, sid):
        self.calls.append(sid)
        return self.results[sid]


def test_check_gone_stores_price(tmp_path, monkeypatch):
    db = tmp_path / "history.db"
    sc = {"_name": "s", "filters": {}}
    monkeypatch.setenv("DEAL_ENGINE_TODAY", "2026-06-01")
    items = [normalize(listing(i, price=100), "fake") for i in ("1", "2", "3")]
    history.track(db, sc, items, log=quiet)
    monkeypatch.setenv("DEAL_ENGINE_TODAY", "2026-06-05")
    ad = Checker("fake", {"1": ("active", 70), "2": "gone", "3": ("reserved", None)})
    history.check_gone(db, sc, ad, log=quiet)
    assert sorted(ad.calls) == ["1", "2", "3"]
    con = sqlite3.connect(db)
    rows = {u: (st, p, ls) for u, st, p, ls in con.execute("SELECT uid, status, price, last_seen FROM listing")}
    assert rows["fake-1"] == ("active", 70, "2026-06-05")
    assert rows["fake-2"][0] == "gone"
    assert rows["fake-3"] == ("active", 100, "2026-06-05")    # no price from check: price kept
    prices = con.execute("SELECT date, price FROM price WHERE uid='fake-1' ORDER BY date").fetchall()
    assert prices == [("2026-06-01", 100), ("2026-06-05", 70)]
    # checked today: not checked again the same day
    ad2 = Checker("fake", {"1": ("active", 60)})
    history.check_gone(db, sc, ad2, log=quiet)
    assert ad2.calls == []


def test_check_gone_only_own_adapter(tmp_path, monkeypatch):
    db = tmp_path / "history.db"
    sc = {"_name": "s", "filters": {}}
    monkeypatch.setenv("DEAL_ENGINE_TODAY", "2026-06-01")
    history.track(db, sc, [normalize(listing("1"), "other")], log=quiet)
    monkeypatch.setenv("DEAL_ENGINE_TODAY", "2026-06-05")
    ad = Checker("fake", {})
    history.check_gone(db, sc, ad, log=quiet)
    assert ad.calls == []
