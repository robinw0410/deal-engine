"""Search page JavaScript: platform bar (#topbar, facet "src"), "All" buttons, list-valued facets,
selection in the URL (?src=vinted,ebay) with history and localStorage. Runs the rendered page in
Chromium through Node + Playwright (tests/platform_filter_driver.js); skips when that is missing."""
import html as html_mod
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from deal_engine.web import render
from test_render import item, make_cfg, page_html, write_state

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "platform_filter_driver.js"
NODE = shutil.which("node")

LISTINGS = [
    item(1, title="Willhaben shirt 1", source="willhaben", sources={"willhaben": "w1"}, kat="hemd"),
    item(2, title="Willhaben trousers 2", source="willhaben", sources={"willhaben": "w2"}, kat="hose"),
    item(3, title="Willhaben shirt 3", source="willhaben", sources={"willhaben": "w3"}, kat="hemd"),
    item(4, title="Willhaben trousers 4", source="willhaben", sources={"willhaben": "w4"}, kat="hose"),
    item(5, title="Ebay shirt", source="ebay", sources={"ebay": "e5"}, kat="hemd"),
    item(6, title="Ebay trousers", source="ebay", sources={"ebay": "e6"}, kat="hose"),
    item(7, title="Vinted trousers", source="vinted", sources={"vinted": "v7"}, kat="hose"),
    item(8, title="Combo shirt", source="ebay", sources={"ebay": "e8", "vinted": "v8"}, kat="hemd"),
]
ALL = sorted(l["title"] for l in LISTINGS)
WEB = {"slug": "shop", "title": "Shop", "facets": [{"key": "kat", "label": "Category", "field": "kat"}],
       "chips": ["kat"]}


def raw_page(tmp_path):
    cfg = make_cfg(tmp_path, {"shop": {"web": WEB}})
    write_state(tmp_path, "shop", LISTINGS)
    return page_html(tmp_path, cfg, "shop")


def with_platforms(page):
    """The rendered page with the platform data the page JavaScript expects (data-source and "src"
    in data-fac on the cards, DE_UI.top/labels/url/t.all/t.platform, #topbar, #pool without hidden).
    PRE-MERGE STAND-IN: each step only runs when render.py does not produce that part yet; once
    render.py does, the page is used unchanged."""
    by_title = {l["title"]: l for l in LISTINGS}

    def src_of(title):
        srcs = list(by_title[html_mod.unescape(title)]["sources"])
        return srcs if len(srcs) > 1 else srcs[0]

    if "data-source=" not in page:   # PRE-MERGE STAND-IN: platform on the cards
        def card(m):
            src = src_of(m.group(4))
            fac = json.loads(html_mod.unescape(m.group(2)))
            fac.setdefault("src", src)
            keys = " ".join(src) if isinstance(src, list) else src
            return (m.group(1).replace("<details ", f'<details data-source="{keys}" ', 1)
                    + html_mod.escape(json.dumps(fac, ensure_ascii=False)) + m.group(3) + m.group(4))
        page, n = re.subn(r"""(<details class="card[^"]*" [^>]*?data-fac=')([^']*)('[^>]*>\s*<summary>"""
                          r"""<span class="score">[^<]*</span><span class="t">)([^<]*)""", card, page)
        assert n == len(LISTINGS)
    m = re.search(r"<script>var DE_UI = (.*?);</script>", page)
    ui = json.loads(m.group(1))
    if "top" not in ui:   # PRE-MERGE STAND-IN: DE_UI fields of the platform bar
        ui.update(top=["src"], url=["src"], labels={"src": {"willhaben": "willhaben", "ebay": "eBay", "vinted": "Vinted"}})
        ui["t"].update({"all": "All", "platform": "Platform"})
        page = page.replace(m.group(0), "<script>var DE_UI = "
                            + json.dumps(ui, ensure_ascii=False).replace("</", "<\\/") + ";</script>")
    if 'id="topbar"' not in page:   # PRE-MERGE STAND-IN: container of the bar
        page = page.replace('<div class="controls">', '<div id="topbar"></div>\n<div class="controls">', 1)
    page = page.replace('<div id="pool" hidden>', '<div id="pool">')   # PRE-MERGE STAND-IN (no-op after)
    return page


def run_driver(tmp_path, mode, page):
    if not NODE:
        pytest.skip("node not installed: browser test of the page JavaScript skipped")
    f = tmp_path / "page.html"
    f.write_text(page)
    try:
        p = subprocess.run([NODE, str(DRIVER), mode, str(f)], capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        pytest.fail("browser driver timed out")
    if p.returncode == 3:
        pytest.skip(f"Playwright/Chromium for Node not available: {p.stderr.strip()[:300]}")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def bar(snap, key):
    return next(r for r in snap["rows"] if r["k"] == key)


def on(snap, key):
    return [b["text"] for b in bar(snap, key)["buttons"] if b["on"]]


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("platform")
    return run_driver(tmp, "scenario", with_platforms(raw_page(tmp)))


def test_bar_shows_platforms_with_counts(scenario):
    s = scenario["initial"]
    assert scenario["errors"] == [] and scenario["dialogs"] == []
    assert s["poolHidden"] is True and s["topbarHidden"] is False
    src = bar(s, "src")
    assert src["top"] is True
    # most listings first; the listing on eBay and Vinted counts for both
    assert [(b["text"], b["n"]) for b in src["buttons"]] == [("All", None), ("willhaben", "4"), ("eBay", "3"),
                                                            ("Vinted", "2")]
    assert src["buttons"][0]["all"] and on(s, "src") == ["All"]
    kat = bar(s, "kat")
    assert kat["top"] is False and [(b["text"], b["n"]) for b in kat["buttons"]] == [
        ("All", None), ("hemd", "4"), ("hose", "4")]
    assert s["visible"] == ALL and s["search"] == "?foo=1"


def test_select_platforms_url_and_history(scenario):
    s = scenario["vinted"]
    assert s["visible"] == ["Combo shirt", "Vinted trousers"]
    assert s["search"] == "?foo=1&src=vinted" and on(s, "src") == ["Vinted"]
    s = scenario["vinted_ebay"]
    assert s["visible"] == ["Combo shirt", "Ebay shirt", "Ebay trousers", "Vinted trousers"]
    assert s["search"] == "?foo=1&src=vinted,ebay" and on(s, "src") == ["eBay", "Vinted"]
    assert s["count"] == "4 of 8"
    s = scenario["back"]   # back button restores the previous selection
    assert s["visible"] == ["Combo shirt", "Vinted trousers"] and s["search"] == "?foo=1&src=vinted"
    assert on(s, "src") == ["Vinted"]
    assert scenario["forward"]["visible"] == scenario["vinted_ebay"]["visible"]
    s = scenario["all"]
    assert s["visible"] == ALL and s["search"] == "?foo=1" and on(s, "src") == ["All"]


def test_url_wins_then_local_storage(scenario):
    s = scenario["url_ebay"]
    assert s["visible"] == ["Combo shirt", "Ebay shirt", "Ebay trousers"] and on(s, "src") == ["eBay"]
    s = scenario["stored"]   # no parameter: saved view, written back into the URL
    assert s["visible"] == ["Combo shirt", "Ebay shirt", "Ebay trousers"] and s["search"] == "?src=ebay"


def test_combined_with_chips_search_and_reset(scenario):
    s = scenario["kat"]
    assert s["visible"] == ["Combo shirt", "Ebay shirt"] and "src=ebay" in s["search"]
    assert on(s, "kat") == ["hemd"] and on(s, "src") == ["eBay"]
    assert scenario["search"]["visible"] == ["Combo shirt"]
    s = scenario["reset"]
    assert s["visible"] == ALL and "src=" not in s["search"] and "kat=" not in s["search"]
    assert on(s, "src") == ["All"] and on(s, "kat") == ["All"]


def test_unknown_url_values_ignored(scenario):
    s = scenario["evil"]
    assert s["search"] == "?src=vinted" and s["visible"] == ["Combo shirt", "Vinted trousers"]
    assert "<script" not in s["topbarHTML"] and "onerror" not in s["topbarHTML"] and "<img" not in s["topbarHTML"]
    assert {b["v"] for b in bar(s, "src")["buttons"]} == {None, "willhaben", "ebay", "vinted"}
    assert scenario["dialogs"] == [] and scenario["errors"] == []


def test_page_without_platform_data(tmp_path):
    """Pages as rendered before the platform bar (no #topbar, no "src"): chips work, no bar, no URL."""
    page = raw_page(tmp_path)
    if 'id="topbar"' in page:   # after the merge: same check on a page without platform data
        page = re.sub(r"<div id=\"topbar\"[^>]*></div>", "", page)
    r = run_driver(tmp_path, "plain", page)
    assert r["errors"] == []
    s = r["initial"]
    assert s["visible"] == ALL and s["search"] == "" and s["poolHidden"] is True
    if 'data-source=' not in page:
        assert [x["k"] for x in s["rows"]] == ["kat"]
    s = r["kat"]
    assert s["visible"] == ["Combo shirt", "Ebay shirt", "Willhaben shirt 1", "Willhaben shirt 3"]
    assert on(s, "kat") == ["hemd"] and "src=" not in s["search"]


def test_without_javascript_all_cards_visible(tmp_path):
    page = raw_page(tmp_path)
    if '<div id="pool" hidden>' in page:
        pytest.skip("render.py still renders #pool hidden (comes with the platform filter render changes)")
    assert run_driver(tmp_path, "nojs", page)["visible"] == ALL


def test_js_syntax(tmp_path):
    if not NODE:
        pytest.skip("node not installed: JavaScript syntax check skipped")
    f = tmp_path / "page.js"
    f.write_text(render.JS)
    p = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
