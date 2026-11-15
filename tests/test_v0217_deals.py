"""v0.2.17: deals keep the listing they came from (listing id, market group, score, expected profit and
hours, taken over from the state of the searches), deals.db gets a score column."""
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from deal_engine.core import config as config_mod
from deal_engine.core import history
from deal_engine.core.util import save_json
from deal_engine.deals import deals_server
from deal_engine.web import render
from plugins_fixture.helpers import search_cfg, write_cfg

# optional: a copy of a real deals.db from before 0.2.17 (opened read-only, then copied into tmp_path)
REAL_DEALS = Path(os.environ.get("DEAL_ENGINE_TEST_DEALS_DB") or "/nonexistent/deals.db")

# schema of a deals.db before 0.2.17 (same as the real deals_cooy.db)
OLD_SCHEMA = """
CREATE TABLE deal(
  id TEXT PRIMARY KEY, item TEXT NOT NULL, category TEXT, link TEXT, notes TEXT,
  status TEXT NOT NULL DEFAULT 'bought', bought_date TEXT, sold_date TEXT,
  buy_price REAL, parts_cost REAL, other_cost REAL, hours REAL, sell_price REAL,
  listing_id TEXT, est_profit REAL, est_hours REAL, market_group TEXT
);
"""

LISTING = {"id": "willhaben-1035270840", "source": "willhaben", "sources": {"willhaben": "1035270840"},
           "title": "Nintendo Switch OLED", "price": 125, "score": 7, "tier": "A",
           "market_group": "Switch OLED", "expected_profit_eur": 29.5, "repair_hours": 0.5,
           "urls": ["https://www.willhaben.at/iad/kaufen-und-verkaufen/d/switch-oled-1035270840/"]}


def make_cfg(tmp_path):
    return write_cfg(tmp_path, {"s": search_cfg(), "t": search_cfg()},
                     deals={"enabled": True, "market_search": "s"})


def write_state(cfg, name, listings):
    save_json(config_mod.paths(cfg, name)["state"], {"listings": listings})


@pytest.fixture
def srv(tmp_path, monkeypatch):
    """(cfg, base url) of a deal server on an ephemeral port."""
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(deals_server, "CFG", cfg)
    deals_server.init(cfg)
    s = ThreadingHTTPServer(("127.0.0.1", 0), deals_server.H)
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield cfg, f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()
    s.server_close()


def call(method, url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def status_of(method, url, body):
    try:
        call(method, url, body)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    return 200, None


def item(data, name):
    (d,) = [d for d in data["deals"] if d["item"] == name]
    return d


def only(data):
    assert len(data["deals"]) == 1
    return data["deals"][0]


def columns(con):
    return [r[1] for r in con.execute("PRAGMA table_info(deal)")]


# --- migration ----------------------------------------------------------------------------------

def test_migration_of_old_db_adds_score(tmp_path):
    cfg = make_cfg(tmp_path)
    p = deals_server.db_path(cfg)
    p.parent.mkdir(parents=True)
    con = sqlite3.connect(p)
    con.executescript(OLD_SCHEMA)
    con.execute("INSERT INTO deal(id, item, status, buy_price, market_group) VALUES ('aaaaaaaaaaaa', 'Old', 'sold', 30, 'G')")
    con.commit()
    con.close()
    deals_server.init(cfg)
    deals_server.init(cfg)   # idempotent
    con = sqlite3.connect(p)
    assert columns(con).count("score") == 1
    assert con.execute("SELECT item, buy_price, market_group, score FROM deal").fetchall() == [("Old", 30.0, "G", None)]
    con.close()


@pytest.mark.skipif(not REAL_DEALS.exists(), reason="DEAL_ENGINE_TEST_DEALS_DB not set")
def test_migration_of_real_db_copy(tmp_path):
    cfg = make_cfg(tmp_path)
    p = deals_server.db_path(cfg)
    p.parent.mkdir(parents=True)
    # read-only and immutable: neither the database nor its -wal/-shm files are touched
    src = sqlite3.connect(REAL_DEALS.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    dst = sqlite3.connect(p)
    src.backup(dst)
    src.close()
    before = dst.execute("SELECT * FROM deal ORDER BY id").fetchall()
    assert "score" not in columns(dst)
    dst.close()
    deals_server.init(cfg)
    con = sqlite3.connect(p)
    assert "score" in columns(con)
    after = con.execute("SELECT * FROM deal ORDER BY id").fetchall()
    assert [r[:-1] for r in after] == before and all(r[-1] is None for r in after)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()


# --- create: taken over from the listing --------------------------------------------------------

def test_create_with_lid_fills_from_state(srv):
    cfg, base = srv
    write_state(cfg, "t", [LISTING])   # found in any search, not only the market search
    d = only(call("POST", base + "/deals/api/deals", {"item": "Switch OLED", "buy_price": "125",
                                                      "listing_id": LISTING["id"], "market_group": "",
                                                      "est_profit": "", "est_hours": "", "score": ""}))
    assert (d["listing_id"], d["market_group"], d["score"], d["est_profit"], d["est_hours"]) == \
           ("willhaben-1035270840", "Switch OLED", 7.0, 29.5, 0.5)


def test_form_values_win(srv):
    cfg, base = srv
    write_state(cfg, "s", [LISTING])
    d = only(call("POST", base + "/deals/api/deals", {"item": "x", "listing_id": LISTING["id"],
                                                      "market_group": "Switch Lite", "est_profit": "12",
                                                      "score": "4"}))
    assert (d["market_group"], d["est_profit"], d["score"], d["est_hours"]) == ("Switch Lite", 12.0, 4.0, 0.5)


def test_unknown_lid_still_created(srv):
    cfg, base = srv
    write_state(cfg, "s", [LISTING])
    d = only(call("POST", base + "/deals/api/deals", {"item": "x", "listing_id": "willhaben-999"}))
    assert d["listing_id"] == "willhaben-999"
    assert all(d[k] is None for k in ("market_group", "score", "est_profit", "est_hours"))


def test_no_state_files_at_all(srv):
    _, base = srv
    d = only(call("POST", base + "/deals/api/deals", {"item": "x", "listing_id": "ebay-123"}))
    assert d["listing_id"] == "ebay-123" and d["score"] is None


@pytest.mark.parametrize("lid", ["willhaben", "Willhaben-1", "willhaben-1/../x", "x-" + "1" * 201, "a b-1",
                                 "willhaben-1 2", "-1"])
def test_invalid_lid_refused(srv, lid):
    _, base = srv
    code, err = status_of("POST", base + "/deals/api/deals", {"item": "x", "listing_id": lid})
    assert code == 400 and "listing_id" in err["error"]
    with urllib.request.urlopen(base + "/deals/api/all", timeout=5) as r:
        assert json.loads(r.read())["deals"] == []


@pytest.mark.parametrize("score,ok", [("0", True), ("10", True), ("7,5", True), ("10.5", False), ("-1", False),
                                      ("abc", False)])
def test_score_range(srv, score, ok):
    _, base = srv
    code, _ = status_of("POST", base + "/deals/api/deals", {"item": "x", "score": score})
    assert (code == 200) is ok


def test_bad_state_values_skipped(srv):
    cfg, base = srv
    write_state(cfg, "s", [{**LISTING, "score": 42, "expected_profit_eur": "viel", "repair_hours": [1],
                            "market_group": "Switch OLED"}])
    d = only(call("POST", base + "/deals/api/deals", {"item": "x", "listing_id": LISTING["id"]}))
    assert d["market_group"] == "Switch OLED"
    assert (d["score"], d["est_profit"], d["est_hours"]) == (None, None, None)


def test_link_gives_listing_id(srv):
    cfg, base = srv
    write_state(cfg, "s", [LISTING])
    link = LISTING["urls"][0].rstrip("/") + "#top"   # trailing slash and fragment do not matter
    d = only(call("POST", base + "/deals/api/deals", {"item": "x", "link": link}))
    assert d["listing_id"] == LISTING["id"] and d["score"] == 7.0 and d["link"] == link


def test_ambiguous_link_gives_nothing(srv):
    cfg, base = srv
    write_state(cfg, "s", [LISTING])
    write_state(cfg, "t", [{**LISTING, "id": "ebay-5"}])
    d = only(call("POST", base + "/deals/api/deals", {"item": "x", "link": LISTING["urls"][0]}))
    assert d["listing_id"] is None and d["score"] is None


def test_same_listing_in_two_searches_is_one(srv):
    cfg, base = srv
    write_state(cfg, "s", [LISTING])
    write_state(cfg, "t", [{**LISTING, "score": 3}])
    d = only(call("POST", base + "/deals/api/deals", {"item": "x", "link": LISTING["urls"][0]}))
    assert d["listing_id"] == LISTING["id"] and d["score"] == 7.0   # market search first


def test_history_gives_group_when_gone_from_state(srv):
    cfg, base = srv
    con = history.connect(config_mod.paths(cfg, "s")["history"])
    con.execute("INSERT INTO listing(uid, source, source_id, search, grp, title) VALUES (?,?,?,?,?,?)",
                ("willhaben-77", "willhaben", "77", "s", "PS5", "PS5 Konsole"))
    con.commit()
    con.close()
    d = only(call("POST", base + "/deals/api/deals", {"item": "x", "listing_id": "willhaben-77"}))
    assert d["market_group"] == "PS5" and d["score"] is None


# --- edit -----------------------------------------------------------------------------------------

def test_put_does_not_look_up(srv):
    cfg, base = srv
    d = only(call("POST", base + "/deals/api/deals", {"item": "x", "listing_id": LISTING["id"]}))
    assert d["score"] is None
    write_state(cfg, "s", [LISTING])   # listing appears later: an edit does not fill anything
    d = only(call("PUT", base + f"/deals/api/deals/{d['id']}", {"notes": "n", "link": LISTING["urls"][0]}))
    assert (d["notes"], d["listing_id"], d["score"], d["market_group"]) == ("n", LISTING["id"], None, None)
    # clearing a value in the edit form stays cleared
    d = only(call("PUT", base + f"/deals/api/deals/{d['id']}", {"listing_id": LISTING["id"], "market_group": ""}))
    assert d["market_group"] is None


def test_put_with_new_listing_id_fills_empty_fields(srv):
    cfg, base = srv
    write_state(cfg, "s", [LISTING])
    d = only(call("POST", base + "/deals/api/deals", {"item": "x", "est_profit": "5"}))
    assert d["listing_id"] is None
    # a new listing replaces the estimates the request does not send (review 0.2.17) ...
    d2 = only(call("PUT", base + f"/deals/api/deals/{d['id']}", {"listing_id": LISTING["id"]}))
    assert (d2["listing_id"], d2["score"], d2["market_group"], d2["est_profit"], d2["est_hours"]) == \
           (LISTING["id"], 7.0, "Switch OLED", 29.5, 0.5)
    # ... values sent along win
    d3 = item(call("POST", base + "/deals/api/deals", {"item": "y"}), "y")
    d3 = item(call("PUT", base + f"/deals/api/deals/{d3['id']}", {"listing_id": LISTING["id"], "est_profit": "5"}), "y")
    assert (d3["est_profit"], d3["score"]) == (5.0, 7.0)


def test_source_ids_with_dots_and_long_ids_are_valid(srv):
    _, base = srv
    for lid in ("json_file-ab.cd:12", "my-adapter-" + "x" * 150):
        d = item(call("POST", base + "/deals/api/deals", {"item": lid, "listing_id": lid}), lid)
        assert d["listing_id"] == lid


def test_put_invalid_lid_refused(srv):
    _, base = srv
    d = only(call("POST", base + "/deals/api/deals", {"item": "x"}))
    code, _ = status_of("PUT", base + f"/deals/api/deals/{d['id']}", {"listing_id": "../etc"})
    assert code == 400


# --- page and search pages -------------------------------------------------------------------------

def test_page_takes_score_from_url():
    page = deals_server.render_page({"locale": "de"}).decode()
    assert '<input type="hidden" name="score">' in page
    assert 'score: q.get("score")' in page and 'listing_id: q.get("lid")' in page
    assert 'th("deal.score"' in page


def test_card_deal_link_has_score_and_lid(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg(web={"deal_link": True})}, deals={"enabled": True})
    page = render.cfg_for("s", config_mod.search(cfg, "s"), cfg)
    html = render.card({**LISTING, "first_seen": "2026-01-01", "last_seen": "2026-01-02"}, page, cfg)
    href = html.split('href="../deals/?')[1].split('"')[0].replace("&amp;", "&")
    q = {k: v[0] for k, v in parse_qs(href).items()}
    assert q["score"] == "7" and q["lid"] == LISTING["id"] and q["grp"] == "Switch OLED"
    assert q["profit"] == "29.5" and q["hours"] == "0.5"
    assert urlparse(q["link"]).netloc == "www.willhaben.at"


@pytest.mark.parametrize("score", ["?", "hoch", 11, -1, None, True])
def test_card_deal_link_without_usable_score(tmp_path, score):
    cfg = write_cfg(tmp_path, {"s": search_cfg(web={"deal_link": True})}, deals={"enabled": True})
    page = render.cfg_for("s", config_mod.search(cfg, "s"), cfg)
    html = render.card({**LISTING, "score": score, "first_seen": "2026-01-01", "last_seen": "2026-01-02"}, page, cfg)
    href = html.split('href="../deals/?')[1].split('"')[0].replace("&amp;", "&")
    assert "score" not in parse_qs(href) and parse_qs(href)["lid"] == [LISTING["id"]]
