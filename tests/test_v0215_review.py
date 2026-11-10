"""v0.2.15, review findings: word-rule bundles are noted for the classification (without a tracking group,
without single checks), dated market entries and a log line that says what is kept, only the additional
controllers are deducted from a bundle, games_count ignores fault descriptions, the score always names the
games, sample_report sorts every listing once, the numbers of the sample settings are checked."""
import json
import re
import time
from datetime import date, timedelta

import pytest

from deal_engine.core import classify, config as config_mod, history, llm, locale, market, pipeline
from deal_engine.core.config import ConfigError
from deal_engine.core.groups import check_groups, extras_included, extras_value, games_count
from deal_engine.core.market import bundle_adjust, classified_sample, estimate_groups, refresh, sample_report

DE, EN = locale.get("de"), locale.get("en")
TODAY = date(2026, 6, 30)
PAD = {"name": "Controller", "keyword": "controller", "match": r"controller",
       "exclude": r"\bps4 (slim|pro)\b|\+|\bmit\b|\bohne\b", "min": 10, "max": 80}
PS4 = {"name": "PS4", "keyword": "ps4", "match": r"\bps4\b", "exclude": r"^\W*controller", "min": 80, "max": 300,
       "extras": {"Controller": r"controller\w*"}}
SWITCH = {"name": "Switch", "keyword": "switch", "match": r"\bswitch\b", "min": 100, "max": 400}
GROUPS = [PAD, PS4, SWITCH]
FLT = {"signal_regex": "defekt|broken|laut"}
DEV = {"sample": "device_only"}
MARKET = {"PS4": {"median": 150, "p25": 140, "n": 30}, "Controller": {"median": 25, "p25": 20, "n": 20}}
BUNDLES = ["Nintendo Switch OLED mit 3 Spielen", "PS4 Slim + 2 Controller + 6 Spiele", "Nintendo Switch mit Spielen"]


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("DEAL_ENGINE_TODAY", str(TODAY))


def quiet(*a):
    pass


def it(sid, title, price, **kw):
    return {"source": "t", "source_id": sid, "title": title, "price": price, "private": True,
            "_published": str(TODAY - timedelta(days=2)), **kw}


def search(mc=None, **kw):
    return {"_name": "s", "_locale": "de", "adapters": ["t"], "filters": FLT, "track": True,
            "market": {"groups": GROUPS, **(DEV if mc is None else mc)}, **kw}


def rows(db, cols="uid, grp"):
    con = history.connect(db)
    try:
        return con.execute(f"SELECT {cols} FROM listing ORDER BY uid").fetchall()
    finally:
        con.close()


def fake_llm(answers, calls):
    def run(cfg, text, model, tools=("Read", "Write"), **kw):
        out = []
        for i, t in re.findall(r"^(\d+): (.*)$", text, re.M):
            calls.append(t)
            g, q, k = answers.get(t, (None, 1, "other"))
            out.append(json.dumps({"i": int(i), "g": g, "q": q, "k": k}))
        return "\n".join(out)
    return run


# ------------------------------------------------------------------ 1. word-rule bundles are noted and classified

HITS = [it("d1", "PS4 500GB", 150), it("b1", BUNDLES[0], 250), it("b2", BUNDLES[1], 230), it("b3", BUNDLES[2], 240),
        it("x1", "PS4 mit 3 Spielen Lüfter laut", 60),       # defect signal
        it("x2", "PS4 mit 3 Spielen", None),                 # no price
        it("x3", "PS4 Hülle mit Spiel", 20),                 # accessory by the word rules
        it("x4", "PS4 mit 3 Spielen Bastler", 60),           # market_exclude of the locale
        it("x5", "Toaster mit 3 Spielen", 20),               # no group
        it("x6", "2 Controller inkl. Spiel", 40),            # bundle quantity
        it("x7", "Mainboard PS4 mit Spiel", 40)]             # spare part by the word rules


def test_track_notes_word_rule_bundles_of_the_group_queries_without_a_group(tmp_path):
    db = tmp_path / "h.db"
    logs = []
    history.track(db, search(), HITS, logs.append, earmark_bundles=True)
    assert rows(db) == [("t-b1", None), ("t-b2", None), ("t-b3", None), ("t-d1", "PS4")]
    assert logs == ["  tracking: 1 listings recorded, 3 bundles noted for the market sample"]
    # only the group queries note them: the tracking of the search results keeps the word rules
    db2 = tmp_path / "h2.db"
    history.track(db2, search(), HITS, logs.append)
    assert rows(db2) == [("t-d1", "PS4")] and logs[-1] == "  tracking: 1 listings recorded"


@pytest.mark.parametrize("mc", [{}, {"sample": "all"}, {"sample": None}, {"game_value": 5}])
def test_sample_all_tracks_exactly_as_before(tmp_path, mc):
    """With sample all the flag changes nothing: same rows, same groups, same log line, and a classified
    word-rule bundle keeps the group the classification gives it (as before)."""
    dumps = []
    for i, flag in enumerate((False, True)):
        db = tmp_path / f"h{i}.db"
        con = history.connect(db)
        con.execute("INSERT INTO classify VALUES ('t-b2', ?, 'PS4', 1, 'bundle', '2026-06-01')", (BUNDLES[1],))
        con.commit()
        con.close()
        logs = []
        history.track(db, search(mc), HITS + [it("b9", "PS4 + 3 games", 200)], logs.append, earmark_bundles=flag)
        dumps.append((rows(db, "*"), logs))
    assert dumps[0] == dumps[1]
    assert [(r[0], r[4]) for r in dumps[0][0]] == [("t-b2", "PS4"), ("t-d1", "PS4")]
    assert dumps[0][1] == ["  tracking: 2 listings recorded"]


def test_noted_bundles_are_classified_keep_no_group_and_stay_out_of_the_sales_statistics(tmp_path, monkeypatch):
    cfg = {"_data": tmp_path, "_base": tmp_path}
    sc = search(classify={"enabled": True})
    P = config_mod.paths(cfg, "s", "t")
    hits = HITS + [it("k1", "PS4 Set komplett", 200)]   # a bundle only the model sees: tracked by the word rules
    history.track(P["history"], sc, hits, quiet, earmark_bundles=True)
    answers = {BUNDLES[0]: ("Switch", 1, "bundle"), BUNDLES[1]: ("PS4", 1, "bundle"), BUNDLES[2]: ("Switch", 1, "device"),
               "PS4 500GB": ("PS4", 1, "device"), "PS4 Set komplett": ("PS4", 1, "bundle")}
    calls = []
    monkeypatch.setattr(llm, "run", fake_llm(answers, calls))
    budget = classify.Budget(600)
    classify.apply(cfg, sc, P, quiet, budget=budget)
    assert sorted(calls) == sorted(answers) and budget.left == 600 - 5   # they share max_per_run
    con = history.connect(P["history"])
    assert dict(con.execute("SELECT uid, kind FROM classify")) == {
        "t-b1": "bundle", "t-b2": "bundle", "t-b3": "device", "t-d1": "device", "t-k1": "bundle"}
    con.close()
    # word-rule bundles keep grp NULL whatever the model says; the bundle only the model sees keeps its
    # group as before
    want = [("t-b1", None), ("t-b2", None), ("t-b3", None), ("t-d1", "PS4"), ("t-k1", "PS4")]
    assert rows(P["history"]) == want
    for flag in (True, False):   # later runs (group queries and search results) do not bring a group back
        history.track(P["history"], sc, hits, quiet, earmark_bundles=flag)
        assert rows(P["history"]) == want
    classify.apply(cfg, sc, P, quiet)
    assert len(calls) == 5 and rows(P["history"]) == want
    # even if they disappeared they would not count as sold units of the group
    con = history.connect(P["history"])
    con.execute("UPDATE listing SET status='gone', gone_date=?", (str(TODAY),))
    con.commit()
    assert {g: s["p"] for g, s in history.sold_by_group(con, "s").items()} == {"PS4": [150, 200]}
    con.close()


def test_correct_tracking_sets_the_group_of_a_classified_word_rule_bundle_only_with_sample_all(tmp_path):
    """Unchanged for sample all (and for callers without the search): bundle with quantity 1 -> its group."""
    for sc, want in ((None, "PS4"), (search({}), "PS4"), (search({"sample": "all"}), "PS4"), (search(), None)):
        db = tmp_path / f"{len(list(tmp_path.iterdir()))}.db"
        history.track(db, search(), [it("b2", BUNDLES[1], 230), it("k1", "PS4 Set komplett", 200)], quiet,
                      earmark_bundles=True)
        con = history.connect(db)
        res = {"t-b2": ("PS4", 1, "bundle"), "t-k1": ("PS4", 1, "bundle")}
        if sc is None:
            classify.correct_tracking(con, res, GROUPS)
        else:
            classify.correct_tracking(con, res, GROUPS, sc)
        assert dict(con.execute("SELECT uid, grp FROM listing")) == {"t-b2": want, "t-k1": "PS4"}
        con.close()


class CheckAdapter:
    name = "t"

    def __init__(self):
        self.checked = []

    def check(self, sid):
        self.checked.append(sid)
        return "active"


def test_check_gone_makes_no_request_for_noted_bundles(tmp_path):
    db = tmp_path / "h.db"
    sc = search()
    history.track(db, sc, HITS, quiet, earmark_bundles=True)
    con = history.connect(db)
    # a listing without group that is no bundle (its classification cleared the group): checked as before
    con.execute("INSERT INTO listing(uid, source, source_id, search, grp, title, status) "
                "VALUES ('t-n1', 't', 'n1', 's', NULL, 'PS4 Poster', 'active')")
    con.execute("UPDATE listing SET last_seen=?", (str(TODAY - timedelta(days=5)),))
    con.commit()
    con.close()
    ad = CheckAdapter()
    logs = []
    history.check_gone(db, sc, ad, logs.append)
    assert sorted(ad.checked) == ["d1", "n1"]
    assert logs == ["tracking: checked 2 missing listings, 0 gone, 2 still online (2 open)"]
    assert dict(rows(db, "uid, checked"))["t-b1"] is None
    # sample all: nothing is excluded (such rows only exist there if something else stored them)
    con = history.connect(db)
    con.execute("UPDATE listing SET last_seen=?, checked=NULL", (str(TODAY - timedelta(days=5)),))
    con.commit()
    con.close()
    ad = CheckAdapter()
    history.check_gone(db, search({}), ad, quiet)
    assert sorted(ad.checked) == ["b1", "b2", "b3", "d1", "n1"]   # per_group (4) for the rows without group, and d1


class Adapter:
    name = "t"

    def __init__(self, by_keyword):
        self.by_keyword, self.warnings = by_keyword, []

    def search(self, query):
        return [{"source_id": sid, "url": f"https://example.org/{sid}", "title": title, "price": price,
                 "published": str(TODAY - timedelta(days=2)), "private": True}
                for sid, title, price in self.by_keyword.get(query.get("keyword"), [])]


def test_update_market_counts_word_rule_bundles_after_they_were_classified(tmp_path, monkeypatch):
    """First update: the group query notes the bundles; classify.apply classifies them; the next update
    adds them as adjusted bundles. Before the fix the fallback never saw them."""
    cfg = {"_data": tmp_path, "_base": tmp_path}
    sc = search(classify={"enabled": True})
    P = config_mod.paths(cfg, "s", "t")
    ps4 = [(f"d{i}", "PS4 500GB", p) for i, p in enumerate((140, 150, 150, 155, 160))]
    ps4 += [("b1", "PS4 Slim + 2 Controller + 6 Spiele", 230), ("b2", "PS4 mit 3 Spielen", 170),
            ("b3", "PS4 mit Spielen", 165)]
    pads = [(f"c{i}", "Controller schwarz", p) for i, p in enumerate((20, 22, 25, 25, 25, 25, 28, 30))]
    adapter = Adapter({"ps4": ps4, "controller": pads})
    logs = []
    first = pipeline.update_market(cfg, sc, adapter, P, logs.append)
    assert "PS4" not in first and "Controller" not in first
    assert any("market PS4: too little data (device 0, bundle 0, unclassified 8)" in s for s in logs)
    assert dict(rows(P["history"]))["t-b1"] is None and len(rows(P["history"])) == 16
    answers = {"PS4 500GB": ("PS4", 1, "device"), "Controller schwarz": ("Controller", 1, "device"),
               **{t: ("PS4", 1, "bundle") for _, t, _ in ps4[5:]}}
    monkeypatch.setattr(llm, "run", fake_llm(answers, []))
    classify.apply(cfg, sc, P, quiet)
    P["market"].unlink()
    new = pipeline.update_market(cfg, sc, adapter, P, quiet)
    # 230 - 1 x 25 - 30 = 175, 170 - 15 = 155, 165 - 10 = 155
    assert new["PS4"] == {"median": 155, "p25": 150, "n": 8, "sample": "adjusted_bundles", "n_device": 5,
                          "n_bundle": 3, "date": str(TODAY)}
    assert {uid: grp for uid, grp in rows(P["history"]) if uid[2] == "b"} == {"t-b1": None, "t-b2": None, "t-b3": None}
    # with sample all the same queries track and count what they always did
    cfg2 = {"_data": tmp_path / "all", "_base": tmp_path}
    P2 = config_mod.paths(cfg2, "s", "t")
    old = pipeline.update_market(cfg2, search({}), adapter, P2, quiet)
    assert old["PS4"] == {"median": 150, "p25": 150, "n": 5} and len(rows(P2["history"])) == 13


def test_sample_report_sees_noted_bundles(tmp_path):
    db = tmp_path / "h.db"
    sc = search()
    devices = [it(f"d{i}", "PS4 500GB", p) for i, p in enumerate((140, 150, 150, 155, 160))]
    history.track(db, sc, devices + [it("b2", BUNDLES[1], 230), it("b4", "PS4 mit 3 Spielen", 170)], quiet,
                  earmark_bundles=True)
    con = history.connect(db)
    with con:
        for i in range(5):
            con.execute("INSERT INTO classify VALUES (?, 'PS4 500GB', 'PS4', 1, 'device', '2026-06-29')", (f"t-d{i}",))
    ps4 = sample_report(con, sc, market=MARKET)[1]
    assert (ps4["device"]["n"], ps4["bundle"]["n"], ps4["unclassified"]) == (5, 0, 2)   # noted, not classified yet
    with con:
        con.execute("INSERT INTO classify VALUES ('t-b2', ?, 'PS4', 1, 'bundle', '2026-06-29')", (BUNDLES[1],))
        con.execute("INSERT INTO classify VALUES ('t-b4', 'PS4 mit 3 Spielen', 'PS4', 1, 'device', '2026-06-29')")
    ps4 = sample_report(con, sc, market=MARKET)[1]
    con.close()
    assert ps4["bundle"] == {"median": 200, "n": 2} and ps4["unclassified"] == 0
    assert ps4["before"] == {"median": 150, "p25": 150, "n": 5}
    assert ps4["after"] == {"median": 155, "p25": 150, "n": 7, "sample": "adjusted_bundles", "n_device": 5, "n_bundle": 2}


# ------------------------------------------------------------------ 2. dated entries, the log says what is kept

def dev(title, price, grp):
    return {**it(f"{title}-{price}", title, price), "_cls": (grp, 1, "device")}


def bun(title, price, grp):
    return {**it(f"{title}-{price}", title, price), "_cls": (grp, 1, "bundle")}


def test_refresh_dates_new_entries_and_names_what_it_keeps():
    pads = [dev("Controller schwarz", p, "Controller") for p in (20, 22, 25, 25, 25, 25, 28, 30)]
    thin = [dev("PS4 500GB", 150, "PS4")] * 3 + [bun("PS4 Set komplett", 200, "PS4"), it("u", "PS4 1TB", 150)]
    old = {"_updated": "2026-06-01", "PS4": {"median": 170, "p25": 150, "n": 40}}
    logs = []
    new = refresh(old, {"PS4": thin, "Controller": pads}, GROUPS, FLT, DEV, logs.append, DE)
    assert new["Controller"] == {"median": 25, "p25": 25, "n": 8, "sample": "device_only", "n_device": 8,
                                 "n_bundle": 0, "date": str(TODAY)}
    assert new["PS4"] == old["PS4"] and "Switch" not in new        # the old mixed value, as it was written
    assert logs == ["  market Controller: median 25 (n=8), device_only: 8 devices + 0 adjusted bundles",
                    "  market PS4: too little data (device 3, bundle 1, unclassified 1), keeping previous value "
                    "(sample all, undated)",
                    "  market Switch: too little data (device 0, bundle 0, unclassified 0)"]
    # a kept device_only entry keeps its old date, and the log names it
    later = {"_updated": "2026-06-10", "PS4": {"median": 150, "p25": 140, "n": 9, "sample": "adjusted_bundles",
                                                "n_device": 6, "n_bundle": 3, "date": "2026-06-10"}}
    logs = []
    new = refresh(later, {"PS4": thin}, [PS4], FLT, DEV, logs.append, DE)
    assert new["PS4"] == later["PS4"] and new["_updated"] == str(TODAY)
    assert logs == ["  market PS4: too little data (device 3, bundle 1, unclassified 1), keeping previous value "
                    "(sample adjusted_bundles, 2026-06-10)"]
    # an entry of the first 0.2.15 format (sample, no date)
    logs = []
    refresh({"PS4": {"median": 150, "p25": 140, "n": 9, "sample": "device_only", "n_device": 9, "n_bundle": 0}},
            {"PS4": thin}, [PS4], FLT, DEV, logs.append, DE)
    assert logs[0].endswith("keeping previous value (sample device_only, undated)")


def test_refresh_with_sample_all_keeps_format_and_log():
    items = [it(str(i), "PS4 500GB", p) for i, p in enumerate((100, 110, 120, 130, 140))]
    old = {"Switch": {"median": 200, "p25": 180, "n": 12, "sample": "device_only", "n_device": 12, "n_bundle": 0,
                      "date": "2026-06-01"}}
    for mc in ({}, {"sample": "all"}):
        logs = []
        new = refresh(old, {"PS4": items}, GROUPS, FLT, mc, logs.append, DE)
        assert new["PS4"] == {"median": 120, "p25": 110, "n": 5} and new["Switch"] == old["Switch"]
        assert logs == ["  market Controller: too little data", "  market PS4: median 120 (n=5)",
                        "  market Switch: too little data, keeping previous value"]


# ------------------------------------------------------------------ 3. only the additional controllers

def test_bundle_adjust_deducts_only_additional_controllers():
    assert bundle_adjust("PS4 mit 2 Controllern", 180, PS4, MARKET, DEV, DE) == 180 - 25
    assert bundle_adjust("PS4 mit Controller", 180, PS4, MARKET, DEV, DE) is None      # nothing additional
    assert bundle_adjust("PS4 mit Controller und 3 Spielen", 180, PS4, MARKET, DEV, DE) == 165
    assert bundle_adjust("PS4 Slim + 2 Controller + 6 Spiele", 200, PS4, MARKET, DEV, DE) == 200 - 25 - 30
    assert bundle_adjust("PS4 mit 4 Controllern", 200, PS4, MARKET, DEV, DE) == 200 - 3 * 25
    # the one that belongs to the console needs no market price, an additional one does
    assert bundle_adjust("PS4 mit Controller und 3 Spielen", 180, PS4, {}, DEV, DE) == 165
    assert bundle_adjust("PS4 mit 2 Controllern und 3 Spielen", 180, PS4, {}, DEV, DE) is None
    # the evaluation of an offer still counts every listed unit (unchanged)
    assert extras_value("PS4 mit 2 Controllern", PS4, MARKET, DE) == (50, [("Controller", 2)])
    assert extras_value("PS4 mit Controller", PS4, MARKET, DE) == (25, [("Controller", 1)])


def test_extras_included_per_group():
    assert extras_included(PS4, "Controller") == 1 and extras_included({}, "x") == 1
    none = {**PS4, "extras_included": 0}                 # e.g. an extra that never comes with the device
    assert bundle_adjust("PS4 mit 2 Controllern", 180, none, MARKET, DEV, DE) == 130
    assert bundle_adjust("PS4 mit Controller", 180, none, MARKET, DEV, DE) == 155
    two = {**PS4, "extras_included": {"Controller": 2}}
    assert bundle_adjust("PS4 mit 2 Controllern", 180, two, MARKET, DEV, DE) is None
    assert bundle_adjust("PS4 mit 3 Controllern", 180, two, MARKET, DEV, DE) == 155
    assert extras_included({**PS4, "extras_included": {"Other": 3}}, "Controller") == 1
    check_groups([PAD, none, {**SWITCH, "extras_included": 0}])
    check_groups([PAD, two])
    for bad in (-1, 1.5, True, "1", {"Controller": -1}, {"Controller": "1"}, {"Switch": 1}):
        with pytest.raises(ValueError, match="extras_included"):
            check_groups([PAD, {**PS4, "extras_included": bad}, SWITCH])


# ------------------------------------------------------------------ 4. games in fault descriptions

@pytest.mark.parametrize("title, n", [
    # faults and games that are not part of the offer
    ("PS4 liest Spiele nicht", 0), ("PS5 defekt - Laufwerk zieht Spiele nicht ein", 0), ("PS4 wirft Spiele aus", 0),
    ("PS4 Slim defekt, Spiele laufen nicht", 0), ("PS4 stürzt bei Spielen ab", 0), ("PS4 Pro laut bei Spielen", 0),
    ("PS4 friert im Spiel ein", 0), ("Spiele nicht dabei", 0), ("Spiele separat erhältlich", 0),
    ("PS4 2 Spiele nicht dabei", 0), ("PS4 keine 3 Spiele", 0), ("PS4 stürzt bei 2 Spielen ab", 0),
    ("PS4 defekt und Spiele laufen nicht", 0), ("PS4 Spiele werden nicht erkannt", 0),
    ("PS4 mit Spielen (nicht getestet)", 0), ("PS4 ohne viele Spiele", 0), ("PS4 3 Spiele separat erhältlich", 0),
    ("PS4 Spiele", 0), ("PS4 viele Spiele", 0),
    # counted mentions, wherever they stand
    ("zwölf Spiele", 12), ("PS4 mit elf Spielen", 11), ("Switch 2 Spiele + 3 Spiele", 5), ("PS4, 2 Controller, 8 Spiele", 8),
    ("PS4 zwei Spiele", 2), ("Nintendo Switch OLED mit 3 Spielen", 3), ("PS4 Slim + 2 Controller + 6 Spiele", 6),
    ("Switch inkl. 2 Spiele und Hülle", 2), ("PS4 inkl. 3 Spielen, nicht getestet", 3), ("PS4 mit einem Spiel", 1),
    # without a count: only in a with-clause
    ("Nintendo Switch mit Spielen", 2), ("PS4 + Spiele", 2), ("PS4 ohne Spiele", 0), ("PS4 mit vielen Spielen", 2),
    ("PS4 mit ein paar Spielen", 2), ("PS4 mit Controller, Kabel und Spielen", 2), ("PS4 ohne Kabel mit Spielen", 2),
    ("PS4 mit 2 Controllern und vielen tollen Spielen", 2),
    # model numbers are no count
    ("Konsole mit PlayStation 4 Spielen", 2), ("PlayStation 4 Spiele", 0), ("Konsole mit Xbox One Spielen", 2),
    ("Xbox One + 3 Spiele", 3),
])
def test_games_count_de(title, n):
    assert games_count(title, DE) == n


@pytest.mark.parametrize("title, n", [
    ("PS4 doesn't read games", 0), ("PS4 freezes in games", 0), ("PS4 games not included", 0),
    ("PS4 with games sold separately", 0), ("PS 5 games", 0), ("Xbox One games", 0),
    ("PS5 with twelve games", 12), ("console with PS 5 games", 2), ("PS4 with a game", 1),
    ("PS4 with a few games", 2), ("PS4, 2 controllers, 8 games", 8),
])
def test_games_count_en(title, n):
    assert games_count(title, EN) == n


def test_new_number_words_do_not_change_the_other_rules():
    from deal_engine.core.groups import bundle_qty, extras_count
    assert bundle_qty("zwölf Controller", PAD, DE) == 12 and bundle_qty("PS4 Controller", PAD, DE) == 1
    assert extras_count("PS4 mit zwei Controllern", r"controller\w*", DE) == 2
    assert bundle_qty("Switch 2 Controller", PAD, DE) == 1     # "switch" stays a model word for quantities


# ------------------------------------------------------------------ 6. sample_report: every listing once

def many_groups(n):
    gs = [{"name": f"G{i:02d}", "match": rf"\bg{i:02d}\b", "min": 50, "max": 500} for i in range(n - 2)]
    gs.append({"name": "Pad", "match": r"\bpad\b", "exclude": r"\+|\bmit\b", "min": 5, "max": 90})
    gs.append({"name": "Any", "match": r"\bg\d\d\b|\bconsole\b", "min": 50, "max": 500,
               "extras": {"Pad": r"pads?"}})            # a broad last group: fall-through and extras
    return gs


def big_db(path, n_rows, n_groups):
    """A synthetic history.db: devices, bundles, word-rule bundles, classifications that name another
    group, implausible and missing ones, changed titles, defects, old rows."""
    kinds = [("G{g} 500GB", "device"), ("G{g} Set komplett", "bundle"), ("G{g} mit 3 Spielen", "bundle"),
             ("G{g} + 2 Pad + 6 Spiele", "bundle"), ("G{g} 1TB", None), ("G{g} mit Spielen", "device"),
             ("Pad schwarz", "device"), ("console G{g}", "other"), ("G{g} Hülle", "accessory")]
    con = history.connect(path)
    with con:
        for i in range(n_rows):
            g = i % (n_groups - 2)
            t, kind = kinds[i % len(kinds)]
            title = t.format(g=f"{g:02d}")
            price = 100 + (i * 37) % 200 if "Pad schwarz" != title else 20 + i % 30
            seen = TODAY - timedelta(days=45 if i % 23 == 0 else i % 20)
            con.execute("""INSERT INTO listing(uid, source, source_id, search, grp, title, defect, published,
                           first_seen, last_seen, first_price, price, private) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"t-{i}", "t", str(i), "s", None, title, int(i % 29 == 0), str(TODAY - timedelta(days=i % 40)),
                         str(seen), str(seen), price, None if i % 31 == 0 else price, i % 3 != 0))
            if kind:
                grp = "Pad" if title == "Pad schwarz" else f"G{g:02d}"
                if i % 13 == 0:
                    grp = "Any"                                   # the model overrules the fall-through
                elif i % 17 == 0:
                    grp = f"G{(g + 1) % (n_groups - 2):02d}"      # implausible: that group does not match
                con.execute("INSERT INTO classify VALUES (?,?,?,?,?,?)",
                            (f"t-{i}", title + (" neu" if i % 19 == 0 else ""), grp if kind in ("device", "bundle") else None,
                             2 if i % 11 == 0 else 1, kind, str(TODAY)))
    con.close()


def report_reference(con, sc, days=30, today=None, market_file=None):
    """sample_report() as it was first written: all listings of the search for every group."""
    mc = sc["market"]
    groups, flt, day = mc["groups"], sc.get("filters") or {}, today or TODAY
    since = str(day - timedelta(days=days))
    items = []
    for title, price, private, published, defect, c_uid, c_title, grp, qty, kind in con.execute(
            """SELECT l.title, l.price, l.private, l.published, l.defect, c.uid, c.title, c.grp, c.qty, c.kind
               FROM listing l LEFT JOIN classify c ON c.uid = l.uid
               WHERE l.search=? AND l.last_seen>=? AND l.price IS NOT NULL""", (sc["_name"], since)):
        if defect:
            continue
        items.append({"title": title, "price": price, "private": bool(private), "_published": published,
                      "_cls": (grp, qty or 1, kind) if c_uid is not None and c_title == title else None})
    by = {g["name"]: items for g in groups}
    mc_after = mc if market.sample_mode(mc) != "all" else {**mc, "sample": "device_only"}
    before = estimate_groups({}, by, groups, flt, {**mc, "sample": "all"}, DE, day)
    after = estimate_groups(market_file or {}, by, groups, flt, mc_after, DE, day)
    out = []
    for g in groups:
        cs = classified_sample(items, g, groups, flt, mc_after, DE, day)
        d, b = [r[0] for r in cs["device"]], [r[0] for r in cs["bundle"]]
        med = lambda xs: {"median": round(market.median(xs)) if xs else None, "n": len(xs)}   # noqa: E731
        out.append({"group": g["name"], "before": before[g["name"]], "after": after[g["name"]], "device": med(d),
                    "bundle": med(b), "bundle_share": round(len(b) / (len(d) + len(b)), 3) if d or b else None,
                    "unclassified": cs["unclassified"]})
    return out


@pytest.mark.parametrize("mc", [{}, {"sample": "device_only", "device_min_n": 30}, {"min_n": 3, "game_value": 8}])
def test_sample_report_is_the_same_as_with_all_listings_for_every_group(tmp_path, mc):
    db = tmp_path / "h.db"
    groups = many_groups(12)
    big_db(db, 900, len(groups))
    sc = {"_name": "s", "_locale": "de", "filters": FLT, "market": {"groups": groups, **mc}}
    con = history.connect_ro(db)
    fallback = {"Pad": {"median": 30, "p25": 25, "n": 9}}
    for kw in ({}, {"days": 10}):
        got = sample_report(con, sc, market=fallback, **kw)
        assert got == report_reference(con, sc, market_file=fallback, **kw)
    con.close()
    assert any(r["after"] and r["after"]["sample"] == "adjusted_bundles" for r in got) or "device_min_n" not in mc
    assert sum(r["device"]["n"] for r in got) > 50 and sum(r["bundle"]["n"] for r in got) > 50
    assert sum(r["unclassified"] for r in got) > 50 and any(r["before"] for r in got)


def test_sample_report_runtime_with_many_groups(tmp_path):
    """3000 listings and 50 groups took about 20 s when every group got all listings."""
    db = tmp_path / "h.db"
    groups = many_groups(50)
    big_db(db, 3000, len(groups))
    sc = {"_name": "s", "_locale": "de", "filters": FLT, "market": {"groups": groups, "sample": "device_only"}}
    con = history.connect_ro(db)
    t0 = time.perf_counter()
    rep = sample_report(con, sc)
    took = time.perf_counter() - t0
    con.close()
    assert len(rep) == 50 and sum(r["device"]["n"] + r["bundle"]["n"] for r in rep) > 500
    assert took < 2, f"sample_report took {took:.1f} s"      # about 0.1 s; the old way needs several seconds here


# ------------------------------------------------------------------ 7. numbers of the sample settings

def cfg_with(tmp_path, mc):
    return {"_data": tmp_path, "_base": tmp_path, "searches": {"s": {"adapters": ["x"], "market": mc}}}


@pytest.mark.parametrize("key, value", [
    ("device_min_n", None), ("device_min_n", -1), ("device_min_n", "8"), ("device_min_n", 2.5), ("device_min_n", True),
    ("games_default", None), ("games_default", -2), ("games_default", "zwei"),
    ("game_value", None), ("game_value", -5), ("game_value", "5 €"), ("game_value", float("nan")),
    ("game_value_max", -1), ("game_value_max", "30"), ("game_value_max", [30]),
])
def test_invalid_numbers_are_a_config_error(tmp_path, key, value):
    for sample in ("device_only", "all"):
        with pytest.raises(ConfigError, match=rf"search 's': market\.{key} must be "):
            config_mod.search(cfg_with(tmp_path, {"sample": sample, key: value}), "s")
    with pytest.raises(ValueError, match=key):
        market.check_settings({key: value})


def test_valid_numbers_and_missing_settings_pass(tmp_path):
    mc = {"sample": "device_only", "device_min_n": 0, "games_default": 3, "game_value": 2.5, "game_value_max": None}
    assert config_mod.search(cfg_with(tmp_path, mc), "s")["market"] == mc
    for mc in ({}, {"sample": "device_only"}, {"game_value": 0, "game_value_max": 0}, {"game_value_max": 12.5}):
        market.check_settings(mc)
    market.check_settings(None)


def test_an_empty_device_min_n_does_not_break_the_market_update(tmp_path):
    """A search built without config.search (a host application): null means the default, not a TypeError."""
    mc = {**DEV, "device_min_n": None, "games_default": None}
    assert market.settings(mc)["device_min_n"] == 8 and market.settings(mc)["games_default"] == 2
    items = [dev("PS4 500GB", 150, "PS4")] * 5 + [bun("PS4 mit 3 Spielen", 170, "PS4")] * 2
    new = refresh({}, {"PS4": items}, [PS4], FLT, mc, quiet, DE)
    assert (new["PS4"]["n_device"], new["PS4"]["n_bundle"]) == (5, 2)
    cfg = {"_data": tmp_path, "_base": tmp_path}
    sc = search(mc, track=False)
    adapter = Adapter({"ps4": [(f"d{i}", "PS4 500GB", 150) for i in range(5)]})
    assert "_updated" in pipeline.update_market(cfg, sc, adapter, config_mod.paths(cfg, "s", "t"), quiet)


# ------------------------------------------------------------------ 8. connect_ro

def test_connect_ro_leaves_the_database_file_unchanged(tmp_path):
    db = tmp_path / "history.db"
    history.track(db, search(), HITS, quiet, earmark_bundles=True)
    con = history.connect(db)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    before = db.read_bytes()
    con = history.connect_ro(db)
    assert con.execute("SELECT COUNT(*) FROM listing").fetchone()[0] == 4
    with pytest.raises(Exception):
        con.execute("DELETE FROM listing")
    con.close()
    assert db.read_bytes() == before
    # only the WAL helper files may appear next to it
    assert {p.name for p in tmp_path.iterdir()} <= {"history.db", "history.db-shm", "history.db-wal"}
    with pytest.raises(Exception):
        history.connect_ro(tmp_path / "missing.db").execute("SELECT 1")
    assert not (tmp_path / "missing.db").exists()
