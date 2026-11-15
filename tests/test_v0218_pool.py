"""v0.2.18: the market median of a group from a rolling pool (the current hits of the market queries + the
listings of the last market.pool_days days in history.db, the same selection as market.sample_report), with
the period in the market file; a median of fewer than market.median_min_n listings caps the candidate
threshold no longer (threshold_ref basis "sold": flip_ratio x the resale value from the sold prices)."""
import json
from datetime import date, timedelta

import pytest

from deal_engine.core import history, market, pipeline
from deal_engine.core.market import check_settings, history_items, pool_since, sample_report
from deal_engine.core.pipeline import add_pool, threshold_ref

from test_v0215_market_sample import A, classify_all, market_setup

TODAY = date(2026, 6, 30)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("DEAL_ENGINE_TODAY", str(TODAY))


def store(db, rows, search="s"):
    """rows: (sid, title, price, days since last seen, kind or None, defect)"""
    con = history.connect(db)
    with con:
        for sid, title, price, ago, kind, defect in rows:
            seen = str(TODAY - timedelta(days=ago))
            con.execute("INSERT INTO listing(uid, source, source_id, search, grp, title, defect, published, first_seen,"
                        " last_seen, first_price, price, private, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (f"t-{sid}", "t", sid, search, "Console A", title, int(defect), seen, seen, seen, price,
                         price, 1, "active"))
            if kind:
                con.execute("INSERT INTO classify VALUES (?,?,?,?,?,?)", (f"t-{sid}", title, "Console A", 1, kind, seen))
    con.close()


STORED = ([(f"h{i}", "Console A 500GB", 200, 3 + i, "device", False) for i in range(10)]
          + [("h-old", "Console A 500GB", 900, 31, "device", False),        # before the pool period
             ("h-def", "Console A 500GB", 20, 2, "device", True),           # stored defect flag
             ("h-other", "Console A 500GB", 20, 2, "device", False)])       # stored under another search


# ------------------------------------------------------------------ settings

def test_defaults_and_settings():
    s = market.settings({})
    assert s["pool_days"] == 30 and s["median_min_n"] == 10
    assert market.settings({"pool_days": None, "median_min_n": None})["pool_days"] == 30
    assert pool_since({}, TODAY) == "2026-05-31" and pool_since({"pool_days": 7}, TODAY) == "2026-06-23"
    assert pool_since({"pool_days": 0}, TODAY) is None


@pytest.mark.parametrize("k, v", [("pool_days", -1), ("pool_days", 1.5), ("pool_days", True),
                                  ("median_min_n", "10"), ("median_min_n", -2)])
def test_check_settings_rejects(k, v):
    with pytest.raises(ValueError, match=k):
        check_settings({k: v})


def test_check_settings_accepts():
    check_settings({"pool_days": 0, "median_min_n": 0})
    check_settings({"pool_days": 60, "median_min_n": 15})


# ------------------------------------------------------------------ the pool

def test_history_items_selection(tmp_path):
    db = tmp_path / "h.db"
    store(db, STORED[:-1])
    store(db, STORED[-1:], search="other")
    sc = {"_name": "s", "market": {"groups": [A]}}
    con = history.connect_ro(db)
    by = history_items(con, sc, "2026-05-31")
    con.close()
    uids = [it["uid"] for it in by["Console A"]]
    assert sorted(uids) == sorted(f"t-h{i}" for i in range(10))          # not old, not defect, not other search
    it = by["Console A"][0]
    assert it["_cls"] == ("Console A", 1, "device") and it["private"] is True and it["price"] == 200


def test_add_pool_merges_once_per_listing(tmp_path):
    db = tmp_path / "h.db"
    store(db, STORED[:-1])
    sc = {"_name": "s", "market": {"groups": [A]}}
    cur = [{"source": "t", "source_id": "h0", "title": "Console A 500GB", "price": 150},     # also stored: once
           {"source": "t", "source_id": "new", "title": "Console A 500GB", "price": 140}]
    out, pool = add_pool({"Console A": cur}, db, sc, today=TODAY)
    names = [it.get("uid") or history.uid(it) for it in out["Console A"]]
    assert names.count("t-h0") == 1 and len(names) == 11
    assert out["Console A"][0]["price"] == 150                                      # the current hit wins
    assert pool == {"since": "2026-05-31", "days": 30, "listings": {"Console A": (2, 9)}}


def test_add_pool_off_or_without_database(tmp_path):
    cur = {"Console A": [{"source": "t", "source_id": "1", "title": "Console A", "price": 1}]}
    sc = {"_name": "s", "market": {"groups": [A], "pool_days": 0}}
    store(tmp_path / "h.db", STORED)
    assert add_pool(cur, tmp_path / "h.db", sc) == (cur, None)
    sc["market"]["pool_days"] = 30
    assert add_pool(cur, tmp_path / "missing.db", sc) == (cur, None)
    assert not (tmp_path / "missing.db").exists()
    (tmp_path / "broken.db").write_bytes(b"not a database " * 100)
    logs = []
    assert add_pool(cur, tmp_path / "broken.db", sc, logs.append) == (cur, None)
    assert any("current hits only" in s for s in logs)


def test_add_pool_reads_only(tmp_path):
    db = tmp_path / "h.db"
    store(db, STORED)
    con = history.connect(db)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("PRAGMA journal_mode=DELETE")
    con.close()
    before = db.read_bytes()
    add_pool({}, db, {"_name": "s", "market": {"groups": [A]}})
    assert db.read_bytes() == before


def test_update_market_median_from_the_pool(tmp_path):
    cfg, sc, P, adapter = market_setup(tmp_path)
    classify_all(P["history"], adapter.by_keyword["console a"])
    store(P["history"], STORED[:-1])
    logs = []
    new = pipeline.update_market(cfg, sc, adapter, P, logs.append)
    m = new["Console A"]
    # current: 8 devices 135..167 (median 150); stored: 10 devices at 200 -> 18 devices, median 200
    assert (m["median"], m["n"], m["n_device"], m["sample"]) == (200, 18, 18, "device_only")
    assert (m["since"], m["days"], m["listings"], m["date"]) == ("2026-05-31", 30, [15, 10], str(TODAY))
    assert any("market Console A: median 200 (n=18, 30 days since 2026-05-31: 15 current + 10 stored listings)" in s
               for s in logs)
    assert json.loads(P["market"].read_text())["Console A"]["listings"] == [15, 10]


def test_update_market_without_pool_as_before(tmp_path):
    cfg, sc, P, adapter = market_setup(tmp_path, mc={"sample": "device_only", "pool_days": 0})
    classify_all(P["history"], adapter.by_keyword["console a"])
    store(P["history"], STORED)
    m = pipeline.update_market(cfg, sc, adapter, P, lambda s: None)["Console A"]
    assert (m["median"], m["n"]) == (150, 8) and "since" not in m and "listings" not in m


def test_pool_equals_sample_report_on_stored_listings(tmp_path):
    """The pool of the run and scripts/market_sample.py (sample_report) select the same listings."""
    db = tmp_path / "h.db"
    store(db, STORED)
    sc = {"_name": "s", "_locale": "de", "filters": {}, "market": {"groups": [A], "sample": "device_only"}}
    con = history.connect_ro(db)
    rep = sample_report(con, sc, days=30, today=TODAY)[0]["after"]
    con.close()
    by, _ = add_pool({}, db, sc, today=TODAY)
    est = market.estimate_groups({}, by, [A], {}, sc["market"], "de", TODAY)["Console A"]
    assert est == rep and est["n"] == 10


# ------------------------------------------------------------------ threshold on a thin median

SC = {"_locale": "de", "market": {"groups": [A]}}


def test_thin_median_follows_the_sold_prices():
    # 3DS from the report of 15.11.: median 65 (n=5), cleaned sold 130 (n=11)
    m = {"median": 65, "p25": 55, "n": 5}
    ref, basis = threshold_ref(m, [130] * 11, SC)
    assert basis == "sold" and ref == round(130 * 0.93)                     # resale value 121
    assert ref * 0.7 == pytest.approx(84.7)                                 # threshold 0.7 x resale value (was 41)
    # thin and lower sold prices: below the median as well
    assert threshold_ref({"median": 300, "p25": 280, "n": 4}, [200] * 9, SC) == (186, "sold")


def test_reliable_median_still_caps():
    m = {"median": 65, "p25": 55, "n": 10}
    ref, basis = threshold_ref(m, [130] * 11, SC)
    assert basis == "resale" and ref == pytest.approx(55 / 0.85)            # never looser than before
    assert threshold_ref(m, [130] * 11, {**SC, "market": {"groups": [A], "median_min_n": 11}})[1] == "sold"
    assert threshold_ref({**m, "n": 3}, [130] * 11, {**SC, "market": {"groups": [A], "median_min_n": 0}})[1] == "resale"


def test_thin_median_without_enough_sold_prices_stays_on_the_median():
    m = {"median": 65, "p25": 55, "n": 3}
    assert threshold_ref(m, [130] * 7, SC) == (65, "median")
    assert threshold_ref(m, None, SC) == (65, "median")
    assert threshold_ref({"median": 65, "p25": 55}, [130] * 11, SC)[1] == "sold"    # no n: thin
    assert threshold_ref(m, [130] * 11, {**SC, "market": {"groups": [A], "threshold_basis": "median"}}) == (65, "median")


def test_select_logs_the_sold_basis():
    from deal_engine.core.listing import normalize
    it = normalize({"source_id": "1", "url": "https://example.org/1", "title": "Console A", "price": 80,
                    "published": str(TODAY), "shipping_possible": True, "shipping_cost_eur": 0}, "test")
    logs = []
    cands, _ = pipeline.select({"1": it}, set(), {}, {"Console A": {"median": 65, "p25": 55, "n": 5}},
                               {**SC, "filters": {"signal_regex": "defekt"}}, logs.append,
                               sold={"Console A": {"p": [130] * 11, "d": [3] * 11}})
    assert len(cands) == 1                                                   # 80 <= 0.7 x 121
    assert cands[0]["market_threshold_basis"] == "sold" and cands[0]["market_threshold_ref"] == 121
    assert cands[0]["market_resale_estimate"] == 121
    assert any("1 on the sold prices alone (thin median: Console A)" in s for s in logs)


def test_pool_only_from_market_source(tmp_path):
    db = tmp_path / "h.db"
    store(db, STORED[:3])
    con = history.connect(db)
    with con:
        con.execute("UPDATE listing SET source='ebay' WHERE uid='t-h0'")
    con.close()
    con = history.connect_ro(db)
    try:
        both = history_items(con, {"_name": "s", "market": {"groups": [A]}}, "2026-05-31")["Console A"]
        wh = history_items(con, {"_name": "s", "market": {"groups": [A], "source": "t"}}, "2026-05-31")["Console A"]
    finally:
        con.close()
    assert len(both) == 3 and sorted(it["uid"] for it in wh) == ["t-h1", "t-h2"]


def test_add_pool_dedupes_per_group(tmp_path):
    """A hit of group B's query that belongs to A keeps its stored copy in A's list (each list is estimated
    on its own, so nothing counts twice)."""
    db = tmp_path / "h.db"
    store(db, STORED[:2])
    sc = {"_name": "s", "market": {"groups": [A]}}
    hit = {"source": "t", "source_id": "h0", "title": "Console A 500GB", "price": 200}
    out, pool = add_pool({"Other": [hit], "Console A": []}, db, sc, today=TODAY)
    assert sorted(it["uid"] for it in out["Console A"]) == ["t-h0", "t-h1"]
    assert pool["listings"] == {"Other": (1, 0), "Console A": (0, 2)}


def test_thin_median_resale_estimate_follows_the_sold_prices(tmp_path):
    """select() and insights give a listing on the sold basis the resale value from the sold prices, not
    the asking-price estimate (otherwise the score would rate the new candidates as a loss)."""
    from deal_engine.core import insights
    from deal_engine.core.listing import normalize
    it = normalize({"source_id": "1", "url": "https://example.org/1", "title": "Console A", "price": 80,
                    "published": str(TODAY), "shipping_possible": True, "shipping_cost_eur": 0}, "test")
    sc = {**SC, "_name": "s", "filters": {"signal_regex": "defekt"}}
    thin = {"Console A": {"median": 65, "p25": 55, "n": 5}}
    (c,), _ = pipeline.select({"1": it}, set(), {}, thin, sc, lambda s: None,
                              sold={"Console A": {"p": [130] * 11, "d": [3] * 11}})
    assert c["market_resale_estimate"] == 121
    # insights: sold estimate without the asking cap when the median is thin, capped when it is reliable
    db = tmp_path / "h.db"
    con = history.connect(db)
    with con:
        for i in range(11):
            d = str(TODAY - timedelta(days=5 + i))
            con.execute("INSERT INTO listing(uid, source, source_id, search, grp, title, defect, published, first_seen,"
                        " last_seen, first_price, price, private, status, gone_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (f"t-s{i}", "t", f"s{i}", "s", "Console A", f"Console A Nr {i}", 0, d, d, d, 130, 130, 1,
                         "gone", d))
    con.close()
    P = {"state": tmp_path / "state.json", "history": db, "market": tmp_path / "m.json"}
    for m, want in ((thin, 121), ({"Console A": {"median": 65, "p25": 55, "n": 10}}, 55)):
        P["market"].write_text(json.dumps(m))
        P["state"].write_text(json.dumps({"listings": [{"id": "t-1", "title": "Console A", "price": 80}]}))
        insights.apply({}, {**sc, "market": {"groups": [A]}, "track": True}, P, log=lambda *a: None)
        assert json.loads(P["state"].read_text())["listings"][0]["market_resale_estimate"] == want
