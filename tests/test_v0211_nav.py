"""v0.2.11: one site navigation for the search pages and the deal list.

The deal list linked "../" ("Search pages") and "./": behind a reverse proxy whose "/" is some other
site, "Search pages" led nowhere. Now both page kinds use render.nav_links/nav_html: one link per
search of the config (../<slug>/), then the deal list (../deals/), the current page marked active."""
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
import yaml

from deal_engine.core import config as config_mod
from deal_engine.deals import deals_server
from deal_engine.web import render

SEARCHES = {
    "alpha": {"title": "Alpha", "adapters": ["json_file"], "keywords": ["a"], "web": {"slug": "first"}},
    "beta": {"title": "Beta", "adapters": ["json_file"], "keywords": ["b"]},
    "gamma": {"adapters": ["json_file"], "keywords": ["c"], "web": {"slug": "third", "title": "Gamma page"}},
}
SLUGS = {"alpha": "first", "beta": "beta", "gamma": "third"}
TITLES = {"alpha": "Alpha", "beta": "Beta", "gamma": "Gamma page"}


def make_cfg(tmp_path, searches=SEARCHES, **top):
    raw = {"data_dir": str(tmp_path), "searches": searches, **top}
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True))
    return config_mod.load(p)


def nav_of(page):
    """[(href, label, active)] of the first <nav> of a page."""
    m = re.search(r"<nav[^>]*>(.*?)</nav>", page, re.S)
    assert m, "no <nav>"
    return [(h, lbl, c == "active")
            for h, c, lbl in re.findall(r'<a href="([^"]*)" class="([^"]*)">([^<]*)</a>', m.group(1))]


def search_page(tmp_path, cfg, name):
    render.render(cfg, name, log=lambda s: None)
    return (tmp_path / "web" / SLUGS[name] / "index.html").read_text()


def deal_page(cfg):
    return deals_server.render_page(cfg).decode()


def no_root_links(page):
    nav = re.search(r"<nav[^>]*>(.*?)</nav>", page, re.S).group(1)
    for bad in ('href="../"', 'href="./"', 'href="/"', 'href=""'):
        assert bad not in nav, bad


# ------------------------------------------------------------------ deal list

def test_deal_list_has_the_pages_of_the_config_and_is_active(tmp_path):
    page = deal_page(make_cfg(tmp_path))
    assert nav_of(page) == [("../first/", "Alpha", False), ("../beta/", "Beta", False),
                            ("../third/", "Gamma page", False), ("../deals/", "Deals", True)]
    no_root_links(page)
    assert "{{" not in page


def test_deal_list_nav_equals_search_page_nav(tmp_path):
    cfg = make_cfg(tmp_path)
    hrefs = lambda page: [h for h, _, _ in nav_of(page)]
    deals = hrefs(deal_page(cfg))
    for name in SEARCHES:
        assert hrefs(search_page(tmp_path, cfg, name)) == deals


def test_deal_list_served_over_http(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, deals={"enabled": True})
    monkeypatch.setattr(deals_server, "CFG", cfg)
    deals_server.init(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), deals_server.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/deals/", timeout=5) as r:
            page = r.read().decode()
    finally:
        srv.shutdown()
        srv.server_close()
    assert [h for h, _, a in nav_of(page)] == ["../first/", "../beta/", "../third/", "../deals/"]
    assert [lbl for _, lbl, a in nav_of(page) if a] == ["Deals"]
    no_root_links(page)


def test_deal_list_without_searches_links_only_itself(tmp_path):
    assert nav_of(deal_page(make_cfg(tmp_path, searches={}))) == [("../deals/", "Deals", True)]
    assert nav_of(deal_page(None)) == [("../deals/", "Deals", True)]   # no config at all (CFG empty)


def test_deal_list_keeps_itself_when_deals_disabled(tmp_path):
    page = deal_page(make_cfg(tmp_path, deals={"enabled": False}))
    assert nav_of(page)[-1] == ("../deals/", "Deals", True) and len(nav_of(page)) == 4


def test_deal_list_with_broken_web_settings_still_renders(tmp_path, capsys):
    bad = {**SEARCHES, "beta": {**SEARCHES["beta"], "web": {"columns": "not a list"}}}
    page = deal_page(make_cfg(tmp_path, searches=bad))
    assert nav_of(page) == [("../deals/", "Deals", True)]
    assert "navigation without search pages" in capsys.readouterr().err


def test_deal_list_nav_is_escaped(tmp_path):
    s = {"x": {"title": "A <b> & \"c\"", "adapters": ["json_file"], "keywords": ["x"]}}
    page = deal_page(make_cfg(tmp_path, searches=s))
    assert ('../x/', "A &lt;b&gt; &amp; &quot;c&quot;", False) in nav_of(page)
    assert "<b>" not in re.search(r"<nav[^>]*>(.*?)</nav>", page, re.S).group(1)


def test_deal_list_nav_localized(tmp_path):
    s = {"x": {"title": {"en": "Things", "de": "Dinge"}, "adapters": ["json_file"], "keywords": ["x"]}}
    page = deal_page(make_cfg(tmp_path, searches=s, locale="de"))
    assert nav_of(page) == [("../x/", "Dinge", False), ("../deals/", "Deals", True)]


# ------------------------------------------------------------------ search pages

@pytest.mark.parametrize("name", list(SEARCHES))
def test_search_page_links_all_other_pages_and_the_deal_list(tmp_path, name):
    nav = nav_of(search_page(tmp_path, make_cfg(tmp_path), name))
    assert [h for h, _, _ in nav] == [f"../{SLUGS[n]}/" for n in SEARCHES] + ["../deals/"]
    assert [lbl for _, lbl, _ in nav] == [TITLES[n] for n in SEARCHES] + ["Deals"]
    assert [h for h, _, a in nav if a] == [f"../{SLUGS[name]}/"]


def test_search_page_without_deal_list_when_disabled(tmp_path):
    nav = nav_of(search_page(tmp_path, make_cfg(tmp_path, deals={"enabled": False}), "beta"))
    assert "../deals/" not in [h for h, _, _ in nav] and len(nav) == 3


def test_nav_links_api(tmp_path):
    cfg = make_cfg(tmp_path)
    assert render.nav_links(cfg, "beta") == [("../first/", "Alpha", False), ("../beta/", "Beta", True),
                                             ("../third/", "Gamma page", False), ("../deals/", "Deals", False)]
    assert render.nav_links(cfg, render.DEALS)[-1] == ("../deals/", "Deals", True)
    assert render.nav_links({}) == [("../deals/", "Deals", False)]


def test_page_template_has_no_root_link():
    tpl = deals_server.PAGE.read_text()
    assert "{{nav}}" in tpl and 'href="../"' not in tpl and 'href="./"' not in tpl
