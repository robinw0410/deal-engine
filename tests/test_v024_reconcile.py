"""v0.2.4: what the state recheck (pipeline.reconcile) may remove.

- Only hard limits remove a listing from the state: max_price, numeric field filters and the title
  regexes ("no longer matches the criteria"), plus "gone" from the results or check(). Never a market
  price threshold, a bundle quantity (qty x median) or the flip/defect ratios: those only decide about
  new candidates in select(). A price rise above the market threshold therefore keeps the listing.
- The title regexes are judged on the platform's current title when the listing is in the results;
  the stored title may have been rewritten by an evaluator. Without a result: the stored title.
- A listing that also carries a link the engine has no adapter for (only in urls) counts as being on
  another platform: hard limits do not remove it, and "gone" only drops this adapter's link.
"""
from deal_engine.core import pipeline
from deal_engine.core.listing import normalize
from plugins_fixture.helpers import listing, quiet

GROUPS = [{"name": "Gamepad", "keyword": "gamepad", "match": "gamepad", "min": 10, "max": 100}]
SC = {"_locale": "en", "_name": "s",
      "filters": {"max_price": 800, "min_price": 5, "exclude_title_regex": r"\bcable\b|\bbag\b",
                  "signal_regex": "broken"},
      "market": {"groups": GROUPS, "max_price_ratio": 0.5, "defect_price_ratio": 0.5, "flip_ratio": 0.5}}


def _changes():
    return {"price": [], "gone": [], "rule": [], "reserved": [], "problems": []}


class _Adapter:
    name = "a"

    def __init__(self, results=None):
        self.results, self.calls = results or {}, []

    def check(self, sid):
        self.calls.append(sid)
        return self.results.get(sid, ("unknown", None))


def _entry(i, title, price, **kw):
    return {"id": f"a-{i}", "source": "a", "sources": {"a": str(i)}, "_urls_by_source": {"a": f"https://a.invalid/{i}"},
            "urls": [f"https://a.invalid/{i}"], "title": title, "price": price, **kw}


def _bundle(i, price):
    # a bundle far above qty x median x ratio (3 x 40 x 0.5 = 60)
    return _entry(i, f"3x gamepad bundle {i}", price, market_group="Gamepad", market_median=40, market_n=12,
                  bundle_qty=3, score=7)


def test_bundles_above_market_threshold_stay_in_results_and_via_check():
    st = {"listings": [_bundle(1, 300), _bundle(2, 300)]}
    items = {"1": normalize(listing("1", title="3x gamepad bundle 1", price=300), "a")}
    ad = _Adapter({"2": ("active", 300)})
    ch = _changes()
    pipeline.reconcile(st, items, ad, SC, ch, quiet)
    assert [l["id"] for l in st["listings"]] == ["a-1", "a-2"]
    assert ch["rule"] == [] and ch["gone"] == [] and ad.calls == ["2"]


def test_price_rise_above_market_threshold_keeps_listing():
    """A price change only updates the price; select()'s market threshold is not applied again."""
    st = {"listings": [_bundle(1, 50), _bundle(2, 50)]}
    items = {"1": normalize(listing("1", title="3x gamepad bundle 1", price=700), "a")}
    ch = _changes()
    pipeline.reconcile(st, items, _Adapter({"2": ("active", 790)}), SC, ch, quiet)
    assert [(l["id"], l["price"]) for l in st["listings"]] == [("a-1", 700), ("a-2", 790)]
    assert ch["rule"] == [] and len(ch["price"]) == 2


def test_hard_limits_still_apply():
    st = {"listings": [_bundle(1, 900), _entry(2, "gamepad with cable", 20), _entry(3, "gamepad", 20)]}
    ch = _changes()
    pipeline.reconcile(st, {}, _Adapter({"3": ("active", 20)}), SC, ch, quiet)
    assert sorted(l["id"] for l in ch["rule"]) == ["a-1", "a-2"]
    assert [l["id"] for l in st["listings"]] == ["a-3"]


def test_min_price_is_not_a_state_limit():
    """min_price only keeps junk out of the search; a price drop below it does not remove a listing."""
    st = {"listings": [_entry(1, "gamepad", 20)]}
    items = {"1": normalize(listing("1", title="gamepad", price=1), "a")}
    ch = _changes()
    pipeline.reconcile(st, items, _Adapter(), SC, ch, quiet)
    assert [l["price"] for l in st["listings"]] == [1] and ch["rule"] == []


def test_title_judged_on_current_platform_title():
    # stored title rewritten (fails the exclude), platform title passes: stays
    # stored title passes, platform title now fails (seller edited it): removed
    st = {"listings": [_entry(1, "Gamepad bundle: 3 pads, cable, bag", 60), _entry(2, "gamepad bundle", 60)]}
    items = {"1": normalize(listing("1", title="gamepad bundle", price=60), "a"),
             "2": normalize(listing("2", title="gamepad bundle with bag", price=60), "a")}
    ch = _changes()
    pipeline.reconcile(st, items, _Adapter(), SC, ch, quiet)
    assert [l["id"] for l in st["listings"]] == ["a-1"]
    assert [l["id"] for l in ch["rule"]] == ["a-2"]


def test_title_without_result_uses_stored_title_before_check():
    st = {"listings": [_entry(1, "gamepad with cable", 60)]}
    ad = _Adapter({"1": ("active", 60)})
    ch = _changes()
    pipeline.reconcile(st, {}, ad, SC, ch, quiet)
    assert [l["id"] for l in ch["rule"]] == ["a-1"] and ad.calls == []


def test_foreign_link_protects_from_hard_limits():
    """A link of a platform without adapter (only in urls) counts like another source."""
    other = "https://other.invalid/77"
    st = {"listings": [_entry(1, "gamepad with cable", 900, urls=["https://a.invalid/1", other])]}
    ch = _changes()
    pipeline.reconcile(st, {}, _Adapter({"1": ("active", 900)}), SC, ch, quiet)
    assert ch["rule"] == [] and [l["id"] for l in st["listings"]] == ["a-1"]


def test_foreign_link_gone_drops_only_own_link():
    other = "https://other.invalid/77"
    st = {"listings": [_entry(1, "gamepad", 60, urls=["https://a.invalid/1", other]), _entry(2, "gamepad", 60)]}
    ch = _changes()
    pipeline.reconcile(st, {}, _Adapter({"1": ("gone", None), "2": ("gone", None)}), SC, ch, quiet)
    assert [l["id"] for l in ch["gone"]] == ["a-2"]
    (l,) = st["listings"]
    assert l["urls"] == [other] and l["sources"] == {} and "a" not in l["_urls_by_source"]


def test_two_urls_without_url_map_count_as_shared():
    """Without _urls_by_source the own link is unknown: more than one link means another platform."""
    st = {"listings": [{"id": "a-1", "sources": {"a": "1"}, "urls": ["https://a.invalid/1", "https://o.invalid/2"],
                        "title": "gamepad with cable", "price": 60},
                       {"id": "a-2", "sources": {"a": "2"}, "urls": ["https://a.invalid/2"],
                        "title": "gamepad with cable", "price": 60}]}
    ch = _changes()
    pipeline.reconcile(st, {}, _Adapter({"1": ("active", 60)}), SC, ch, quiet)
    assert [l["id"] for l in ch["rule"]] == ["a-2"] and [l["id"] for l in st["listings"]] == ["a-1"]


def test_platform_of_links():
    pf = pipeline._platform
    assert pf("https://www.ebay.at/itm/1") == pf("https://ebay.de/itm/2") == pf("https://m.ebay.co.uk/itm/3") == "ebay"
    assert pf("https://www.willhaben.at/iad/x-1") == "willhaben"
    assert pf("https://a.invalid/1") == "a" and pf("https://other.invalid/2") == "other"
    assert pf("not a link") is None and pf(None) is None


def _relist(price=60, title="gamepad"):
    # an older ad of the same platform was merged in: its link stays, sources has the new id
    return {"id": "a-111", "source": "a", "sources": {"a": "222"}, "_urls_by_source": {"a": "https://a.invalid/222"},
            "urls": ["https://a.invalid/111", "https://a.invalid/222"], "title": title, "price": price}


def test_same_platform_relist_gone_is_gone():
    st = {"listings": [_relist()]}
    ch = _changes()
    pipeline.reconcile(st, {}, _Adapter({"222": ("gone", None)}), SC, ch, quiet)
    assert [l["id"] for l in ch["gone"]] == ["a-111"] and st["listings"] == []


def test_same_platform_relist_hard_limits_apply():
    st = {"listings": [_relist(price=900), _relist(title="gamepad with cable")]}
    st["listings"][1]["id"] = "a-112"
    ch = _changes()
    pipeline.reconcile(st, {}, _Adapter(), SC, ch, quiet)
    assert sorted(l["id"] for l in ch["rule"]) == ["a-111", "a-112"] and st["listings"] == []


class _Ebay(_Adapter):
    name = "ebay"


def test_ebay_at_and_de_are_one_platform():
    l = {"id": "ebay-5", "source": "ebay", "sources": {"ebay": "5"}, "_urls_by_source": {"ebay": "https://www.ebay.at/itm/5"},
         "urls": ["https://www.ebay.at/itm/5", "https://www.ebay.de/itm/5"], "title": "gamepad", "price": 900}
    g = dict(l, id="ebay-6", price=60)
    ch = _changes()
    st = {"listings": [l, g]}
    pipeline.reconcile(st, {}, _Ebay({"5": ("gone", None)}), SC, ch, quiet)
    assert [x["id"] for x in ch["rule"]] == ["ebay-5"] and [x["id"] for x in ch["gone"]] == ["ebay-6"]
    assert st["listings"] == []


def test_foreign_link_still_protects_and_same_platform_links_are_dropped():
    other = "https://other.invalid/77"
    st = {"listings": [dict(_relist(price=900), urls=["https://a.invalid/111", "https://a.invalid/222", other])]}
    ch = _changes()
    pipeline.reconcile(st, {}, _Adapter({"222": ("gone", None)}), SC, ch, quiet)
    assert ch["rule"] == [] and ch["gone"] == []
    (l,) = st["listings"]
    assert l["urls"] == [other] and l["sources"] == {}


def test_other_source_keeps_its_link_on_gone():
    l = {"id": "a-1", "source": "a", "sources": {"a": "1", "b": "9"},
         "_urls_by_source": {"a": "https://a.invalid/1", "b": "https://b.invalid/9"},
         "urls": ["https://a.invalid/1", "https://a.invalid/0", "https://b.invalid/9"], "title": "gamepad", "price": 60}
    st = {"listings": [l]}
    ch = _changes()
    pipeline.reconcile(st, {}, _Adapter({"1": ("gone", None)}), SC, ch, quiet)
    assert ch["gone"] == [] and l["urls"] == ["https://b.invalid/9"] and l["sources"] == {"b": "9"}
