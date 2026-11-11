"""Search page JavaScript: platform bar (#topbar, facet "src"), "All" buttons, list-valued facets,
selection in the URL (?src=vinted,ebay) with history and localStorage. Runs the rendered page in
Chromium through Node + Playwright (tests/platform_filter_driver.js); skips when that is missing."""
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
    item(1, title="Willhaben shirt 1", source="willhaben", sources={"willhaben": "w1"}, cat="shirt"),
    item(2, title="Willhaben trousers 2", source="willhaben", sources={"willhaben": "w2"}, cat="trousers"),
    item(3, title="Willhaben shirt 3", source="willhaben", sources={"willhaben": "w3"}, cat="shirt"),
    item(4, title="Willhaben trousers 4", source="willhaben", sources={"willhaben": "w4"}, cat="trousers"),
    item(5, title="Ebay shirt", source="ebay", sources={"ebay": "e5"}, cat="shirt"),
    item(6, title="Ebay trousers", source="ebay", sources={"ebay": "e6"}, cat="trousers"),
    item(7, title="Vinted trousers", source="vinted", sources={"vinted": "v7"}, cat="trousers"),
    item(8, title="Combo shirt", source="ebay", sources={"ebay": "e8", "vinted": "v8"}, cat="shirt"),
]
ALL = sorted(l["title"] for l in LISTINGS)
WEB = {"slug": "shop", "title": "Shop", "facets": [{"key": "cat", "label": "Category", "field": "cat"}],
       "chips": ["cat"]}


def raw_page(tmp_path):
    cfg = make_cfg(tmp_path, {"shop": {"web": WEB}})
    write_state(tmp_path, "shop", LISTINGS)
    return page_html(tmp_path, cfg, "shop")


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
    return run_driver(tmp, "scenario", raw_page(tmp))


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
    cat = bar(s, "cat")
    assert cat["top"] is False and [(b["text"], b["n"]) for b in cat["buttons"]] == [
        ("All", None), ("shirt", "4"), ("trousers", "4")]
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
    s = scenario["cat"]
    assert s["visible"] == ["Combo shirt", "Ebay shirt"] and "src=ebay" in s["search"]
    assert on(s, "cat") == ["shirt"] and on(s, "src") == ["eBay"]
    assert scenario["search"]["visible"] == ["Combo shirt"]
    s = scenario["reset"]
    assert s["visible"] == ALL and "src=" not in s["search"] and "cat=" not in s["search"]
    assert on(s, "src") == ["All"] and on(s, "cat") == ["All"]


def test_unknown_url_values_ignored(scenario):
    s = scenario["evil"]
    assert s["search"] == "?src=vinted" and s["visible"] == ["Combo shirt", "Vinted trousers"]
    assert "<script" not in s["topbarHTML"] and "onerror" not in s["topbarHTML"] and "<img" not in s["topbarHTML"]
    assert {b["v"] for b in bar(s, "src")["buttons"]} == {None, "willhaben", "ebay", "vinted"}
    assert scenario["dialogs"] == [] and scenario["errors"] == []


def test_page_without_platform_bar(tmp_path):
    """A page without #topbar (as rendered before 0.2.16): the bar goes before the chip rows."""
    page = re.sub(r"<div id=\"topbar\"[^>]*></div>", "", raw_page(tmp_path))
    r = run_driver(tmp_path, "plain", page)
    assert r["errors"] == []
    s = r["initial"]
    assert s["visible"] == ALL and s["search"] == "" and s["poolHidden"] is True
    assert [x["k"] for x in s["rows"]] == ["src", "cat"]
    s = r["cat"]
    assert s["visible"] == ["Combo shirt", "Ebay shirt", "Willhaben shirt 1", "Willhaben shirt 3"]
    assert on(s, "cat") == ["shirt"] and s["search"] == "?cat=shirt"


def test_encoded_comma_in_url(scenario):
    s = scenario["encoded"]   # ?src=ebay%2Cvinted (comma encoded, e.g. by URLSearchParams)
    assert s["visible"] == ["Combo shirt", "Ebay shirt", "Ebay trousers", "Vinted trousers"]
    assert on(s, "src") == ["eBay", "Vinted"]


def test_stale_saved_view(tmp_path):
    """A saved view from an older page (sort and toggle no longer configured) does not empty the list."""
    r = run_driver(tmp_path, "stale", raw_page(tmp_path))
    assert r["errors"] == [] and r["initial"]["visible"] == ALL


def test_script_error_keeps_cards_visible(tmp_path):
    page = raw_page(tmp_path).replace('<div id="groups"></div>', "", 1)   # makes the script fail
    r = run_driver(tmp_path, "broken", page)
    assert r["errors"] and r["visible"] == ALL


def test_config_label_cannot_break_out_of_the_script(tmp_path):
    web = dict(WEB, facets=[{"key": "cat", "label": "<!--<script>", "field": "cat"}])
    cfg = make_cfg(tmp_path, {"shop": {"web": web}})
    write_state(tmp_path, "shop", LISTINGS)
    page = page_html(tmp_path, cfg, "shop")
    ui = re.search(r"<script>var DE_UI = (.*?);</script>", page).group(1)
    assert "<" not in ui and json.loads(ui)["chips"] == [["cat", "<!--<script>"]]
    r = run_driver(tmp_path, "plain", page)
    assert r["errors"] == [] and r["initial"]["visible"] == ALL


def test_without_javascript_all_cards_visible(tmp_path):
    assert run_driver(tmp_path, "nojs", raw_page(tmp_path))["visible"] == ALL


def test_js_syntax(tmp_path):
    if not NODE:
        pytest.skip("node not installed: JavaScript syntax check skipped")
    f = tmp_path / "page.js"
    f.write_text(render.JS)
    p = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
