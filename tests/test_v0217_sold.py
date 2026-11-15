"""v0.2.17, part B: the sale price from disappeared listings (history.sold_by_group) counts only disappeared
single devices without defect, from market.source and domestic, once per repost chain (clean settings from
history.sold_settings, insights sold_clean / sold_dedup_days / sold_countries). clean=None is the old
statistic, unchanged."""
import json
import sqlite3

import pytest

from deal_engine.core import history, insights
from deal_engine.core.listing import normalize

PS4 = {"name": "PS4", "match": r"\bps4\b", "exclude": r"\bpro\b", "min": 50, "max": 250}
PAD = {"name": "Controller", "match": r"controller", "exclude": r"\bps4\b.*\b(mit|\+)\b", "min": 10, "max": 80}
SWITCH = {"name": "Switch", "match": r"\bswitch\b", "min": 80, "max": 320}
GROUPS = [PAD, PS4, SWITCH]
FLT = {"signal_regex": r"defekt|kaputt"}
TODAY = "2026-11-15"


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setenv("DEAL_ENGINE_TODAY", TODAY)


def search(**market):
    return {"_name": "s", "_locale": "de", "filters": FLT,
            "market": {"groups": GROUPS, "sample": "device_only", **market}}


class DB:
    def __init__(self, path):
        self.con = history.connect(path)
        self.n = 0

    def add(self, title, price, *, grp=None, cls="device", qty=1, source="willhaben", status="gone",
            first="2026-11-01", last="2026-11-05", defect=0, image=None, location=None, seller=None, uid=None):
        """One listing; cls: kind of a stored classification of the same title (group = grp), None = none."""
        self.n += 1
        uid = uid or f"{source}-{self.n}"
        if image is None:
            image = f"{self.n}/1/{self.n}_{7000000 + self.n}.jpg" if source == "willhaben" else \
                f"https://i.ebayimg.com/images/g/x{self.n}/s-l225.jpg"
        self.con.execute(
            """INSERT INTO listing(uid, source, source_id, search, grp, title, defect, first_seen, last_seen, price,
               status, gone_date, image, location, seller) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, source, uid.split("-", 1)[1], "s", grp, title, defect, first, last, price, status,
             last if status == "gone" else None, image or None, location, seller))
        if cls:
            self.con.execute("INSERT INTO classify VALUES (?,?,?,?,?,?)", (uid, title, grp, qty, cls, first))
        self.con.commit()
        return uid

    def sold(self, sc=None, clean=True, window=60):
        sc = sc or search()
        r = history.sold_by_group(self.con, "s", window, clean=history.sold_settings(sc) if clean else None)
        return {g: sorted(s["p"]) for g, s in r.items()}


@pytest.fixture
def db(tmp_path):
    d = DB(tmp_path / "h.db")
    yield d
    d.con.close()


def legacy(con, search, window_days=60):
    """sold_by_group as of 0.2.16, for the comparison."""
    from datetime import timedelta
    from deal_engine.core import clock
    since = str(clock.today() - timedelta(days=window_days))
    sold = {}
    for grp, price, start, gone in con.execute(
            """SELECT grp, price, COALESCE(published, first_seen), gone_date FROM listing
               WHERE search=? AND status='gone' AND COALESCE(defect,0)=0 AND grp IS NOT NULL
                 AND price IS NOT NULL AND gone_date>=?""", (search, since)):
        s = sold.setdefault(grp, {"p": [], "d": []})
        s["p"].append(price)
        d = history._days(start, gone)
        if d is not None and d >= 0:
            s["d"].append(d)
    return sold


def fill(db):
    db.add("PS4 Slim 500GB", 120, grp="PS4")
    db.add("PS4 mit 2 Controllern und 5 Spielen", 180, grp="PS4", cls="bundle")      # bundle
    db.add("PS4 Spiel FIFA 23", 15, grp="PS4", cls="accessory")                      # accessory, stale grp
    db.add("PS4 Slim defekt", 60, grp="PS4", defect=1)                                # defect flag
    db.add("PS4 Slim HDMI kaputt", 70, grp="PS4")                                     # defect signal, flag 0
    db.add("PS4 Slim 1TB", 260, grp="PS4")                                            # above max
    db.add("PS4 Slim", 110, grp="PS4", source="ebay", location="US 805**")           # eBay abroad
    db.add("PS4 Slim 1TB schwarz", 100, grp="PS4", source="ebay", location="DE 12345 Berlin")
    db.add("PS4 Slim weiss", 95, grp="PS4", source="ebay", location="JP")
    db.add("PS4 Slim grau", 90, grp="PS4", source="ebay", location=None)
    db.add("PS4 Slim ohne Klassifikation", 105, grp="PS4", cls=None)                 # not classified
    db.add("PS4 Slim alt", 99, grp="PS4", first="2026-08-01", last="2026-09-01")     # outside the window
    db.add("PS4 Slim aktiv", 130, grp="PS4", status="active")


def test_clean_none_is_the_old_statistic(db):
    fill(db)
    old = history.sold_by_group(db.con, "s", 60)
    assert old == legacy(db.con, "s", 60)
    assert history.sold_by_group(db.con, "s", 60, clean=None) == old
    assert sorted(old["PS4"]["p"]) == [15, 70, 90, 95, 100, 105, 110, 120, 180, 260]


def test_clean_counts_single_domestic_devices_without_defect(db):
    fill(db)
    # every source (market.source not set): eBay only from AT/DE
    assert db.sold() == {"PS4": [100, 120]}
    # market.source: only that source
    assert db.sold(search(source="willhaben")) == {"PS4": [120]}
    assert db.sold(search(source="ebay")) == {"PS4": [100]}
    # other countries, or none
    sc = {**search(), "insights": {"sold_countries": ["US", "JP"]}}
    assert db.sold(sc) == {"PS4": [95, 110, 120]}
    sc = {**search(), "insights": {"sold_countries": []}}
    assert db.sold(sc) == {"PS4": [120]}


def test_sample_all_uses_the_word_rules_without_classification(db):
    db.add("PS4 Slim 500GB", 120, grp="PS4", cls=None)
    db.add("PS4 + 2 Controller", 150, grp="PS4", cls=None)            # bundle quantity / extras
    db.add("PS4 mit 3 Spielen", 140, grp="PS4", cls=None)             # extras
    db.add("Ladekabel für PS4 Controller", 12, grp="Controller", cls=None)
    db.add("Nintendo Switch Konsole", 150, cls=None)                  # grp NULL in the table: group from the title
    db.add("PS4 Pro 1TB", 160, grp="PS4", cls=None)                   # stale grp, the word rules give none
    assert db.sold(search(sample="all")) == {"PS4": [120], "Switch": [150]}
    assert db.sold(search(sample="device_only")) == {}


def test_stale_group_is_not_trusted(db):
    # tracking stored grp PS4 (old word rules), the classification says it is a controller
    db.add("PS4 Controller DualShock", 30, grp="PS4", cls="device")
    db.con.execute("UPDATE classify SET grp='Controller'")
    db.con.commit()
    assert db.sold() == {"Controller": [30]}
    assert db.sold(clean=False) == {"PS4": [30]}
    # a classification of an older title is invalid
    db.con.execute("UPDATE listing SET title='PS4 Controller DualShock v2'")
    db.con.commit()
    assert db.sold() == {}


def test_repost_chain_counts_once_and_only_if_the_last_link_is_gone(db):
    # same title (normalised) and price within 2 %, no photo stored
    a = db.add("Nintendo Switch V2 rot blau", 150, grp="Switch", first="2026-10-01", last="2026-10-10", image="")
    db.add("nintendo switch v2  rot/blau", 149, grp="Switch", first="2026-10-15", last="2026-11-14",
           status="active", image="")
    assert db.sold() == {}                     # replaced by a repost: not sold
    assert db.sold(clean=False) == {"Switch": [150]}
    db.con.execute("UPDATE listing SET status='gone', gone_date=last_seen WHERE status='active'")
    db.con.commit()
    assert db.sold() == {"Switch": [149]}      # the chain once, price of its last link
    r = history.sold_by_group(db.con, "s", 60, clean=history.sold_settings(search()))
    assert r["Switch"]["d"] == [44]            # 2026-10-01 .. 2026-11-14: from the start of the chain
    # more than sold_dedup_days between the links: two items
    db.con.execute("UPDATE listing SET first_seen='2026-10-30' WHERE uid<>?", (a,))
    db.con.commit()
    assert db.sold() == {"Switch": [149, 150]}
    assert db.sold({**search(), "insights": {"sold_dedup_days": 30}}) == {"Switch": [149]}


def test_parallel_copies_of_a_dealer_count_once(db):
    for i in range(5):   # same title and photo, listed in parallel
        db.add("AKTION! PS4 SLIM KONSOLE", 99.99, grp="PS4", first=f"2026-10-1{i}", last=f"2026-10-2{i}",
               image=f"{i}/2/{i}_-1137064254.jpg")
    assert db.sold() == {"PS4": [99.99]}
    assert db.sold(clean=False) == {"PS4": [99.99] * 5}


def test_same_photo_or_seller_alone_is_no_repost(db):
    # a dealer with one shop photo for different devices: different groups, each counts
    shop = "https://i.ebayimg.com/images/g/SHOP/s-l225.jpg"
    db.add("PS4 Slim 500GB", 120, grp="PS4", source="ebay", location="DE 1", image=shop)
    db.add("Nintendo Switch Konsole", 160, grp="Switch", source="ebay", location="DE 1", image=shop)
    db.add("Xbox Wireless Controller", 30, grp="Controller", source="ebay", location="DE 1", image=shop)
    # same group, but clearly different price: another unit
    db.add("PS4 Slim 1TB", 180, grp="PS4", source="ebay", location="DE 1", image=shop)
    assert db.sold() == {"Controller": [30], "PS4": [120, 180], "Switch": [160]}
    # same photo, same group, price within 10 %: the same item listed again with another title
    db.add("Sony PS4 Slim 500 GB schwarz", 125, grp="PS4", source="ebay", location="DE 1", image=shop,
           first="2026-11-06", last="2026-11-08")
    assert db.sold() == {"Controller": [30], "PS4": [125, 180], "Switch": [160]}


def test_seller_key(db):
    db.add("PS4 Slim 500GB", 120, grp="PS4", seller="u1", first="2026-10-01", last="2026-10-05")
    db.add("Playstation 4 PS4 slim", 115, grp="PS4", seller="u1", first="2026-10-08", last="2026-10-12")
    db.add("Nintendo Switch", 150, grp="Switch", seller="u1", first="2026-10-08", last="2026-10-12")
    db.add("PS4 Slim 500GB", 110, grp="PS4", seller="u2", first="2026-10-08", last="2026-10-12")
    # u1: the PS4 again (same group, price within 10 %) and a Switch; u2 is someone else (other photo)
    assert db.sold() == {"PS4": [110, 115], "Switch": [150]}


def test_generic_title_with_different_photos_is_not_merged(db):
    for i in range(4):
        db.add("PS4 Slim", 100, grp="PS4", first=f"2026-10-0{i + 1}", last=f"2026-10-0{i + 3}")
    assert db.sold() == {"PS4": [100] * 4}
    # the same photo: one item
    db.con.execute("UPDATE listing SET image='9/9/9_123456789.jpg'")
    db.con.commit()
    assert db.sold() == {"PS4": [100]}


def test_sold_settings_and_sold_for_search(tmp_path):
    sc = {**search(source="willhaben"), "insights": {"sold_dedup_days": 7, "sold_countries": "at"}}
    s = history.sold_settings(sc)
    assert s["source"] == "willhaben" and s["dedup_days"] == 7 and s["countries"] == ["AT"]
    assert s["sample"] == "device_only" and s["groups"] == GROUPS and s["locale"] == "de"
    d = history.sold_settings(search())
    assert d["countries"] == ["AT", "DE"] and d["dedup_days"] == 14 and d["source"] is None
    assert insights.DEFAULTS["sold_clean"] is True
    # missing database: {} and nothing created
    logs = []
    assert history.sold_for_search(tmp_path / "none.db", search(), log=logs.append) == {} and not logs
    assert not (tmp_path / "none.db").exists()
    db = DB(tmp_path / "h.db")
    fill(db)
    db.con.close()
    assert {g: sorted(v["p"]) for g, v in history.sold_for_search(tmp_path / "h.db", search()).items()} == \
        {"PS4": [100, 120]}
    raw = {g: sorted(v["p"]) for g, v in history.sold_for_search(tmp_path / "h.db", search(), clean=False).items()}
    assert raw["PS4"] == [15, 70, 90, 95, 100, 105, 110, 120, 180, 260]
    off = {**search(), "insights": {"sold_clean": False}}
    assert {g: sorted(v["p"]) for g, v in history.sold_for_search(tmp_path / "h.db", off).items()} == raw
    # window from the insights settings, or given
    assert history.sold_for_search(tmp_path / "h.db", {**search(), "insights": {"window_days": 5}}) == {}
    assert history.sold_for_search(tmp_path / "h.db", search(), window_days=5) == {}
    # unreadable: {} and a log line, never an exception
    bad = tmp_path / "bad.db"
    bad.write_text("no database")
    assert history.sold_for_search(bad, search(), log=logs.append) == {} and "not readable" in logs[0]


def test_old_database_without_seller_column(tmp_path):
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.executescript(history.SCHEMA.replace("  gone_date TEXT\n", "  gone_date TEXT, location TEXT\n"))
    con.execute("""INSERT INTO listing(uid, source, source_id, search, grp, title, defect, first_seen, last_seen,
                   price, status, gone_date) VALUES ('willhaben-1','willhaben','1','s','PS4','PS4 Slim',0,
                   '2026-11-01','2026-11-05',120,'gone','2026-11-05')""")
    con.execute("INSERT INTO classify VALUES ('willhaben-1','PS4 Slim','PS4',1,'device','2026-11-01')")
    con.commit()
    con.close()
    # read-only: works without the column and does not add it
    assert {g: v["p"] for g, v in history.sold_for_search(p, search()).items()} == {"PS4": [120]}
    con = sqlite3.connect(p)
    assert "seller" not in [r[1] for r in con.execute("PRAGMA table_info(listing)")]
    con.close()
    history.connect(p).close()   # migration
    con = sqlite3.connect(p)
    assert "seller" in [r[1] for r in con.execute("PRAGMA table_info(listing)")]
    con.close()


def test_seller_from_the_listing_is_stored(tmp_path):
    raw = {"source_id": "1", "url": "https://x.test/1", "title": "PS4 Slim", "price": 100, "seller": " u-42 "}
    it = normalize(raw, "willhaben")
    assert it["_seller"] == "u-42" and "seller" not in it and "seller" not in it["_extra"]
    assert normalize({**raw, "seller": None}, "willhaben")["_seller"] is None
    sc = {"_name": "s", "_locale": "de", "filters": {}, "market": {"groups": GROUPS}}
    history.track(tmp_path / "h.db", sc, [it], log=lambda *a: None)
    history.track(tmp_path / "h.db", sc, [{**it, "_seller": None}], log=lambda *a: None)   # kept
    con = history.connect(tmp_path / "h.db")
    assert con.execute("SELECT seller FROM listing").fetchall() == [("u-42",)]
    con.close()


def test_insights_apply_uses_the_clean_statistic(tmp_path, monkeypatch):
    P = {"state": tmp_path / "state.json", "history": tmp_path / "h.db", "market": tmp_path / "m.json"}
    history.connect(P["history"]).close()
    P["market"].write_text(json.dumps({"PS4": {"median": 150, "p25": 140, "n": 30}}))
    P["state"].write_text(json.dumps({"listings": [{"id": "x", "title": "PS4 Slim", "price": 100}]}))
    seen = []

    def fake(con, name, w, clean=None):
        seen.append((w, clean))
        return {}
    monkeypatch.setattr(insights.history, "sold_by_group", fake)
    sc = {**search(), "track": True}
    insights.apply({}, sc, P, log=lambda *a: None)
    assert seen[-1][0] == 60 and seen[-1][1] == history.sold_settings(sc)
    insights.apply({}, {**sc, "insights": {"sold_clean": False, "window_days": 30}}, P, log=lambda *a: None)
    assert seen[-1] == (30, None)
