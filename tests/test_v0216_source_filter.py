"""0.2.16: platform of every card (data-source, facet "src", badge), the top bar, DE_UI for the
filter bar and the URL, web.top, and a page that shows every card without JavaScript."""
import html as html_mod
import json
import re

import pytest

from deal_engine.core import config as config_mod
from deal_engine.core.config import ConfigError
from deal_engine.web import render
from test_render import item, make_cfg, page_html, write_state

CLOTHES = {"facets": [{"key": "cat", "label": {"en": "Category", "de": "Kategorie"}, "field": "category"}],
           "groups": ["tier", "cat"], "chips": ["cat"]}


def de_ui(html):
    return json.loads(html.split("var DE_UI = ")[1].split(";</script>")[0])


def cards(html):
    """{title: (data-source, data-fac as dict, summary html)} of all cards."""
    out = {}
    for m in re.finditer(r'<details class="card[^"]*" ([^>]*)>\s*<summary>(.*?)</summary>', html, re.S):
        attrs, summary = m.group(1), m.group(2)
        src = re.search(r'data-source="([^"]*)"', attrs).group(1)
        fac = json.loads(html_mod.unescape(re.search(r"data-fac='([^']*)'", attrs).group(1)))
        title = html_mod.unescape(re.search(r'<span class="t">(.*?)</span>', summary).group(1))
        out[title] = (src, fac, summary)
    return out


LISTINGS = [
    item(1, title="Shirt", id="willhaben-1", source="willhaben", sources={"willhaben": "1"},
         urls=["https://www.willhaben.at/iad/1"], category="shirt"),
    item(2, title="Jacket", id="ebay-2", source="ebay", sources={"ebay": "2"},
         urls=["https://www.ebay.at/itm/2"], category="jacket"),
    item(3, title="Both", id="willhaben-3", source="willhaben", sources={"willhaben": "3", "ebay": "4"},
         urls=["https://www.willhaben.at/iad/3", "https://www.ebay.de/itm/4"]),
    item(4, title="Feed", id="json_file-5", source="json_file", sources={"json_file": "5"},
         urls=["https://example.invalid/5"]),
    item(5, title="Browser link", id="vinted-6", urls=["https://www.vinted.at/items/6-shirt"]),
    item(6, title="Browser id", id="aurena-7", urls=[]),
    item(7, title="Unknown", id="x-8", urls=[]),
]


@pytest.fixture
def page(tmp_path):
    cfg = make_cfg(tmp_path, {"clothes": {"adapters": ["willhaben", "ebay"], "web": CLOTHES}})
    write_state(tmp_path, "clothes", LISTINGS)
    return page_html(tmp_path, cfg, "clothes")


def test_data_source_and_facet_per_card(page):
    c = cards(page)
    assert c["Shirt"][0] == "willhaben" and c["Shirt"][1]["src"] == "willhaben"
    assert c["Jacket"][0] == "ebay" and c["Jacket"][1]["src"] == "ebay"
    assert c["Both"][0] == "willhaben ebay" and c["Both"][1]["src"] == ["willhaben", "ebay"]
    assert c["Feed"][0] == "json_file" and c["Feed"][1]["src"] == "json_file"
    assert c["Browser link"][0] == "vinted"     # no source: platform of the link's host
    assert c["Browser id"][0] == "aurena"       # no source, no link: known prefix of the id
    assert c["Unknown"][0] == "other"
    assert c["Shirt"][1]["cat"] == "shirt" and c["Shirt"][1]["tier"] == "B"   # other facets unchanged
    assert len(c) == len(LISTINGS)


def test_platform_badge_in_summary(page):
    c = cards(page)
    assert '<span class="pill src src-willhaben">willhaben</span>' in c["Shirt"][2]
    assert '<span class="pill src src-ebay">eBay</span>' in c["Jacket"][2]
    both = c["Both"][2]
    assert both.count('class="pill src ') == 2 and ">eBay<" in both and ">willhaben<" in both
    assert '<span class="pill src src-vinted">Vinted</span>' in c["Browser link"][2]
    assert '<span class="pill src src-json_file">JSON file</span>' in c["Feed"][2]
    assert '<span class="pill src src-other">Other</span>' in c["Unknown"][2]


def test_topbar_pool_visible_and_de_ui(page):
    assert '<div id="topbar" class="topbar"></div>' in page
    assert page.index('id="topbar"') < page.index('class="controls"')
    assert '<div id="pool" class="list pool">' in page and 'id="pool" hidden' not in page
    assert "[hidden]{display:none!important}" in page   # .list must not beat pool.hidden
    # with JavaScript the flat pool is hidden from the start (no flash before grouping)
    assert ".js #pool{display:none}" in page and "documentElement.className += ' js'" in page
    assert "<noscript><style>.controls,.topbar{display:none}</style></noscript>" in page
    ui = de_ui(page)
    assert ui["top"] == ["src"]
    assert ui["chips"] == [["cat", "Category"]] and all(c[0] != "src" for c in ui["chips"])
    assert ui["url"] == ["src", "cat"]
    assert ui["labels"]["src"] == {"aurena": "Aurena", "ebay": "eBay", "json_file": "JSON file", "other": "Other",
                                   "vinted": "Vinted", "willhaben": "willhaben"}
    assert ui["t"]["all"] == "All" and ui["t"]["platform"] == "Platform"
    assert ui["names"]["src"] == "Platform" and ui["names"]["cat"] == "Category"
    assert ui["groups"] == [["tier", "Tier"], ["cat", "Category"]]


def test_german_texts(tmp_path):
    cfg = make_cfg(tmp_path, {"s": {}}, locale="de")
    write_state(tmp_path, "s", [item(1, source="json_file", sources={"json_file": "1"})])
    ui = de_ui(page_html(tmp_path, cfg, "s"))
    assert ui["t"]["all"] == "Alle" and ui["t"]["platform"] == "Plattform"
    assert ui["labels"]["src"] == {"json_file": "JSON-Datei"}
    assert ui["top"] == ["src"] and ui["url"] == ["src"] and ui["chips"] == []


def test_web_top_moves_facets_out_of_chips(tmp_path):
    web = {**CLOTHES, "top": ["src", "cat"]}
    cfg = make_cfg(tmp_path, {"clothes": {"web": web}})
    write_state(tmp_path, "clothes", LISTINGS[:2])
    p = render.cfg_for("clothes", config_mod.search(cfg, "clothes"), cfg)
    assert p["top"] == ["src", "cat"] and p["chips"] == []
    ui = de_ui(page_html(tmp_path, cfg, "clothes"))
    assert ui["top"] == ["src", "cat"] and ui["chips"] == [] and ui["url"] == ["src", "cat"]


def test_web_top_empty_keeps_src_in_url(tmp_path):
    cfg = make_cfg(tmp_path, {"clothes": {"web": {**CLOTHES, "top": []}}})
    write_state(tmp_path, "clothes", LISTINGS[:1])
    ui = de_ui(page_html(tmp_path, cfg, "clothes"))
    assert ui["top"] == [] and ui["chips"] == [["cat", "Category"]] and ui["url"] == ["src", "cat"]


@pytest.mark.parametrize("web, msg", [
    ({"top": ["size"]}, "web.top: unknown facet 'size'"),
    ({"top": "src"}, "web.top must be a list"),
    ({"top": [{"key": "src"}]}, "web.top: unknown facet"),
    ({"facets": [{"key": "src", "field": "source"}]}, "'src' is built in"),
    ({"facets": [{"field": "src"}]}, "'src' is built in"),
    ({"groups": ["src"]}, "can filter, not group"),
])
def test_web_top_validation(tmp_path, web, msg):
    cfg = make_cfg(tmp_path, {"s": {"web": web}})
    with pytest.raises(ConfigError, match=re.escape(msg)):
        render.cfg_for("s", config_mod.search(cfg, "s"), cfg)


def test_src_allowed_in_chips_and_top_with_tier(tmp_path):
    cfg = make_cfg(tmp_path, {"s": {"web": {"top": ["tier"], "chips": ["src"]}}})
    p = render.cfg_for("s", config_mod.search(cfg, "s"), cfg)
    assert p["top"] == ["tier"] and p["chips"] == ["src"]


def test_odd_source_names_are_escaped(tmp_path):
    evil = 'x"><script>alert(1)</script>'
    cfg = make_cfg(tmp_path, {"s": {}})
    write_state(tmp_path, "s", [item(1, source=evil, sources={evil: "1"}),
                                item(2, title="</script><b>", source="Shop Name", sources={"Shop Name": "2"})])
    html = page_html(tmp_path, cfg, "s")
    assert "<script>alert" not in html and "</script><b>" not in html
    c = cards(html)
    assert c["Item 1"][0] == "xscriptalert1script"
    assert c["</script><b>"][0] == "shopname" and ">Shopname</span>" in c["</script><b>"][2]
    ui = de_ui(html)
    assert ui["labels"]["src"]["shopname"] == "Shopname"


def test_sources_of():
    so = render.sources_of
    assert so({"source": "willhaben"}) == ["willhaben"]
    assert so({"source": "willhaben", "sources": {"ebay": "1"}, "urls": []}) == ["ebay"]   # source is the first one
    # every adapter gone, links of another platform left: their platforms
    assert so({"source": "ebay", "sources": {}, "urls": ["https://m.willhaben.at/1"]}) == ["willhaben"]
    assert so({"urls": ["https://www.vinted.de/items/1", "https://www.ebay.co.uk/itm/2"]}) == ["vinted", "ebay"]
    assert so({"id": "shop-1"}) == ["other"]
    # a link of another platform added to an adapter's listing (e.g. by a browser run) counts too
    wh = "https://www.willhaben.at/iad/1"
    assert so({"sources": {"willhaben": "1"}, "_urls_by_source": {"willhaben": wh},
               "urls": [wh, "https://www.aurena.at/posten/2"]}) == ["willhaben", "aurena"]
    assert so({"sources": {"json_file": "1"}, "_urls_by_source": {"json_file": "https://example.invalid/1"},
               "urls": ["https://example.invalid/1"]}) == ["json_file"]
    # without _urls_by_source only known platforms are added from the links
    assert so({"sources": {"json_file": "1"}, "urls": ["https://example.invalid/1",
                                                       "https://www.vinted.at/items/3"]}) == ["json_file", "vinted"]
    assert so({"sources": {"shop": "1"}, "urls": ["https://shop.example/1"]}, known={"shop"}) == ["shop"]
    assert so({"id": "shop-1"}, known={"shop"}) == ["shop"]
    assert so({}) == ["other"]
