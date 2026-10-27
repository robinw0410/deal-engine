"""v0.2.2: group veto, LLM classification before the candidate selection, locale fixes,
permission-skipping flags in llm.extra_args.

The three titles come from a shadow run of a German search ("elektronik") that got wrong market
groups; GROUPS copies the relevant groups of that config (as fixed, with vetoes)."""
import json
import re
import time

import pytest

from deal_engine import adapters
from deal_engine.core import classify, clock, llm, locale, pipeline
from deal_engine.core import config as config_mod
from deal_engine.core import run as run_mod
from deal_engine.core.config import ConfigError
from deal_engine.core.groups import bundle_qty, is_accessory, market_group, match_group
from deal_engine.core.listing import normalize
from deal_engine.core.util import save_json
from plugins_fixture.helpers import accept_all, batch, listing, quiet, search_cfg, write_cfg

THIRD_PARTY = (r"powera|power a|8bitdo|nacon|hori\b|turtle beach|razer|gulikit|ipega|gamesir|bigben|snakebyte|"
               r"thrustmaster|pdp\b|afterglow|rock candy|easysmx|kompatibel|compatible|nachbau|replica|klon|clone|"
               r"drittanbieter|third.?party|no.?name|china|generic|ähnlich|aehnlich|fake|nicht original|kein original")
# "PS5 + DualSense", "Switch mit 2 Joy-Cons", consoles, storage sizes: not a single controller
NOT_SINGLE = (r"^\W*(sony\s+|microsoft\s+|nintendo\s+)?(ps[45]|playstation\s*[45]|xbox\s+(series\s+[xs]|one(\s+[xs])?)|"
              r"switch)\b[^+]*?(\+|\bmit\b|\binkl\.?|\bund\b|&)\s*(\d+\s*)?(x\s*)?(original\s+)?(dualsense|dualshock|"
              r"controller|pro\s*controller|joy[- ]?cons?)|konsole|console|\bdisc\b|digital edition|\b\d+\s?(tb|gb)\b")
HAIR = r"goldwell|shampoo|spülung|spuelung|conditioner|haarpflege"
# vetoes: accessory words only without mit/inkl/+/ohne before them; part words only when the title
# starts with the part, "<part> für", or without with/ohne and without console/defect context
ACC = r"kopfh|headset|pulse|kamera|camera|\bvr2?\b|fernbedienung|media\s*remote"
PART = r"laufwerk|lüfter|luefter|kühl|kuehl|standfu"
WITH = r"\b(mit|inkl|inklusive|samt|plus|und|ohne)\b|[+&]"
CTX = r"\b(konsole|console|defekt\w*|kaputt|laut|leise|gereinigt|liest|überhitz\w*|ueberhitz\w*|bundle)\b|\d+\s*(gb|tb)\b"
PS5_VETO = (rf"^(?!.*({WITH}).*({ACC})).*({ACC})"
            rf"|^\W*((original|sony|neu\w*)\s+)*(disc[- ]?)?({PART})"
            rf"|({PART})\w*\s+(für|fuer|for)\b"
            rf"|^(?!.*({WITH})|.*({CTX})).*({PART})"
            r"|^\W*(sony\s+)?(ps5\s+|playstation\s*5\s+)?(dualsense|controller)")
SWITCH_VETO = (r"\bswitch\s*2\b|^(?!.*(\b(mit|inkl|und|konsole|console)\b|[+&])).*(?<!ohne )\bcontroller"
               r"(?![- ]?(stick|tasten?|knöpfe|knoepfe|port|anschluss|buchse))")
TABLET_ONLY = (r"nur\s*(das\s*)?(tablet|konsole|gerät|geraet|display)|ohne\s*(joy|dock|zubehör|zubehoer|controller)|"
               r"tablet\s*only|\bhandheld\s*only")
NETWORK = r"netzwerk|gigabit|\blan\b|poe|managed|tp-?link|netgear|cisco"

GROUPS = [
    {"name": "DualSense Edge", "keyword": "dualsense edge", "match": r"dualsense\s*edge",
     "exclude": f"{HAIR}|{THIRD_PARTY}|{NOT_SINGLE}", "min": 70, "max": 250},
    {"name": "DualSense", "keyword": "dualsense", "match": r"dualsense|ps5[- ]controller",
     "exclude": f"{HAIR}|edge|{THIRD_PARTY}|{NOT_SINGLE}", "min": 20, "max": 90},
    {"name": "Switch Pro Controller", "keyword": "switch pro controller", "match": r"pro[- ]controller",
     "exclude": f"{THIRD_PARTY}|{NOT_SINGLE}", "min": 20, "max": 80},
    {"name": "PS5 Pro", "keyword": "ps5 pro", "match": r"(ps5|playstation 5)\s*pro", "veto": PS5_VETO,
     "min": 400, "max": 900},
    {"name": "PS5 Slim Digital", "keyword": "ps5 slim digital", "match": r"(ps5|playstation\s*5).*(slim.*digital|digital.*slim)",
     "exclude": "pro|spiel|game|portal|lenkrad", "veto": PS5_VETO, "min": 200, "max": 550},
    {"name": "PS5 Slim", "keyword": "ps5 slim", "match": r"(ps5|playstation\s*5).*slim",
     "exclude": "pro|digital|spiel|game|portal|lenkrad", "veto": PS5_VETO, "min": 250, "max": 600},
    {"name": "PS5 Digital", "keyword": "ps5 digital", "match": r"(ps5|playstation\s*5).*digital",
     "exclude": "pro|slim|spiel|game|portal|lenkrad", "veto": PS5_VETO, "min": 180, "max": 500},
    {"name": "PS5", "keyword": "ps5", "match": r"\bps5\b|playstation 5",
     "exclude": "pro|spiel|game|portal|lenkrad|slim|digital", "veto": PS5_VETO, "min": 200, "max": 650},
    {"name": "Switch nur Tablet", "keyword": "switch ohne",
     "match": r"switch.*(nur\s*(das\s*)?(tablet|konsole|gerät|geraet|display)|ohne\s*(joy|dock|zubehör|zubehoer|controller)|"
              r"tablet\s*only|\bhandheld\s*only)",
     "exclude": f"oled|lite|spiel|game|hülle|{NETWORK}", "veto": SWITCH_VETO, "min": 60, "max": 220},
    {"name": "Switch OLED", "keyword": "switch oled", "match": r"switch.*oled|oled.*switch", "exclude": TABLET_ONLY,
     "veto": SWITCH_VETO, "min": 150, "max": 380},
    {"name": "Switch Lite", "keyword": "switch lite", "match": r"switch\s*lite", "veto": SWITCH_VETO, "min": 60, "max": 220},
    {"name": "Nintendo Switch", "keyword": "nintendo switch", "match": r"nintendo\s*switch|\bswitch\s*(konsole|v1|v2)\b|^switch\b",
     "exclude": f"oled|lite|spiel|game|hülle|port|{NETWORK}|{TABLET_ONLY}", "veto": SWITCH_VETO, "min": 100, "max": 320},
]
DE = locale.get("de")
MARKET = {"DualSense": {"median": 60, "p25": 55, "n": 12}, "PS5": {"median": 400, "p25": 380, "n": 20},
          "Nintendo Switch": {"median": 180, "p25": 170, "n": 15}}


# --- the shadow-run titles --------------------------------------------------------------------------

@pytest.mark.parametrize("title, group", [
    ("DualSense funktionsfähig", "DualSense"),
    ("Ps5 kopfhörer", None),                          # headset: PS5 veto
    ("Switch 2 Controller originalverpackt", None),   # no Switch 2 group: Switch veto
    ("DualSense für PS5 Konsole funktionsfähig", None),   # DualSense excluded ("Konsole"), PS5 vetoed
    ("PS5 mit 2 Controllern", "PS5"), ("PS5 Disc + DualSense", "PS5"),
    ("Nintendo Switch", "Nintendo Switch"), ("Switch mit 2 Controllern", "Nintendo Switch"),
    ("Switch ohne Controller nur Tablet", "Switch nur Tablet"), ("Switch OLED Controller", None),
    # consoles that only mention a part, an extra or a defect keep their group
    ("PS5 Lüfter laut", "PS5"), ("PS5 Laufwerk defekt", "PS5"), ("PS5 mit Standfuß", "PS5"), ("PS5 + VR2", "PS5"),
    ("PS5 inkl. Kamera", "PS5"), ("Switch Lite Controller-Stick defekt", "Switch Lite"),
    ("Nintendo Switch OLED Konsole Pro Controller", "Switch OLED"),
    # accessories and parts do not
    ("PS5 Pulse 3D Headset", None), ("PS VR2 für PS5", None), ("PS5 Kamera", None), ("PS5 Laufwerk", None),
    ("Lüfter für PS5", None), ("PS5 Standfuß", None), ("PS5 Kühlstation", None), ("PlayStation 5 Controller", None),
    ("Nintendo Switch Controller", None),
])
def test_shadow_run_groups(title, group):
    g = match_group(title, GROUPS)
    assert (g and g["name"]) == group


def test_shadow_run_titles_in_select():
    items = {}
    for sid, title, price in (("1", "DualSense funktionsfähig", 25), ("2", "Ps5 kopfhörer", 25),
                              ("3", "Switch 2 Controller originalverpackt", 40)):
        items[sid] = normalize(listing(sid, title, price), "json_file")
    sc = {"_name": "s", "_locale": "de", "market": {"groups": GROUPS}}
    cands, _ = pipeline.select(items, set(), {}, MARKET, sc, quiet, loc=DE)
    by = {c["title"]: c for c in cands}
    assert by["DualSense funktionsfähig"]["market_group"] == "DualSense"
    assert by["DualSense funktionsfähig"]["market_resale_estimate"] == round(60 * 0.85)
    for t in ("Ps5 kopfhörer", "Switch 2 Controller originalverpackt"):
        assert "market_group" not in by[t] and "market_resale_estimate" not in by[t]


# --- veto semantics ----------------------------------------------------------------------------------

def test_veto_stops_the_fall_through():
    groups = [{"name": "A", "match": "ps5", "exclude": "slim", "veto": "headset"}, {"name": "B", "match": "ps5"}]
    assert match_group("PS5", groups)["name"] == "A"
    assert match_group("PS5 Slim", groups)["name"] == "B"     # exclude: falls through
    assert match_group("PS5 Headset", groups) is None          # veto: no group at all
    assert match_group("PS5 Slim HEADSET", groups) is None     # veto wins over exclude, case-insensitive
    assert match_group("Headset", groups) is None
    # a veto only counts when the group's match hits
    groups = [{"name": "A", "match": "switch", "veto": "controller"}, {"name": "B", "match": "controller"}]
    assert match_group("Xbox Controller", groups)["name"] == "B"
    assert market_group("Switch Controller", 50, groups, loc=DE) is None


# --- classification before the selection -----------------------------------------------------------

LLM_ANSWERS = {"DualSense für PS5 Konsole funktionsfähig": ("DualSense", 1, "device"),
               "Ps5 kopfhörer": (None, 1, "accessory")}


def fake_llm(answers, calls):
    def run(cfg, text, model, tools=("Read", "Write"), **kw):
        calls.append({"text": text, "tools": tools, "model": model})
        out = []
        for i, t in re.findall(r"^(\d+): (.*)$", text, re.M):
            g, q, k = answers.get(t, (None, 1, "other"))
            out.append(json.dumps({"i": int(i), "g": g, "q": q, "k": k}))
        return "\n".join(out)
    return run


def cls_setup(tmp_path, rows, **kw):
    sc_kw = {"locale": "de", "json_file": {"path": "l.json"}, "classify": {"enabled": True, "model": "haiku"},
             "market": {"groups": GROUPS}, **kw}
    cfg = write_cfg(tmp_path, {"s": search_cfg(**sc_kw)})
    (tmp_path / "l.json").write_text(json.dumps([listing(*r) for r in rows]))
    save_json(config_mod.paths(cfg, "s")["market"], {**MARKET, "_updated": clock.today_str(), "_ts": time.time()})
    sc = config_mod.search(cfg, "s")
    return cfg, sc, adapters.create("json_file", cfg, sc)


ROWS = [("1", "DualSense für PS5 Konsole funktionsfähig", 25), ("2", "Ps5 kopfhörer", 25), ("3", "Toaster", 10)]


def test_preselect_classification_decides_the_group(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "run", fake_llm(LLM_ANSWERS, calls))
    cfg, sc, ad = cls_setup(tmp_path, ROWS)
    c = pipeline.collect(cfg, sc, ad, quiet, classify_first=True)
    cands = {x["title"]: x for x in batch(cfg, "s", "json_file")["candidates"]}
    assert c["candidates"] == 2 and set(cands) == {"DualSense für PS5 Konsole funktionsfähig", "Toaster"}
    d = cands["DualSense für PS5 Konsole funktionsfähig"]
    assert d["market_group"] == "DualSense" and d["market_resale_estimate"] == 51   # not the PS5 price
    assert "market_group" not in cands["Toaster"]
    assert len(calls) == 1 and calls[0]["tools"] == () and calls[0]["model"] == "haiku"
    assert "Toaster" not in calls[0]["text"]   # no group could match it: not sent to the model
    # stored in history.db under <adapter>-<source_id>; the next run does not ask again
    from deal_engine.core import history
    con = history.connect(config_mod.paths(cfg, "s")["history"])
    assert classify.lookup(con, "json_file-1", "DualSense für PS5 Konsole funktionsfähig") == ("DualSense", 1, "device")
    assert classify.lookup(con, "json_file-2", "Ps5 kopfhörer") == (None, 1, "accessory")
    con.close()
    pipeline.collect(cfg, sc, ad, quiet, classify_first=True)
    assert len(calls) == 1 and batch(cfg, "s", "json_file")["candidates"]


def test_preselect_respects_max_per_run_and_other(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "run", fake_llm({"PS5 Konsole Gutschein": (None, 1, "other")}, calls))
    rows = [("1", "PS5 Konsole Gutschein", 100), ("2", "Ps5 kopfhörer", 25)]
    cfg, sc, ad = cls_setup(tmp_path, rows, classify={"enabled": True, "max_per_run": 1})
    pipeline.collect(cfg, sc, ad, quiet, classify_first=True)
    assert len(re.findall(r"^\d+: ", calls[0]["text"], re.M)) == 1
    # "other": no group, no market comparison (the word rules would compare it with the PS5 median)
    assert match_group("PS5 Konsole Gutschein", GROUPS)["name"] == "PS5"
    titles = {x["title"]: x for x in batch(cfg, "s", "json_file")["candidates"]}
    assert set(titles) == {"PS5 Konsole Gutschein", "Ps5 kopfhörer"}
    assert all("market_group" not in x for x in titles.values())


def test_preselect_bundle_quantity(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "run", fake_llm({"DualSense Paket": ("DualSense", 3, "bundle")}, calls))
    cfg, sc, ad = cls_setup(tmp_path, [("1", "DualSense Paket", 100)])
    pipeline.collect(cfg, sc, ad, quiet, classify_first=True)
    c = batch(cfg, "s", "json_file")["candidates"]
    assert len(c) == 1 and c[0]["market_group"] == "DualSense"   # 100 + 15 shipping <= 3 x 60 x 0.75


def test_llm_failure_keeps_word_rules(tmp_path, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("LLM command not found: claude")
    monkeypatch.setattr(llm, "run", broken)
    cfg, sc, ad = cls_setup(tmp_path, ROWS)
    lines = []
    c = pipeline.collect(cfg, sc, ad, lines.append, classify_first=True)
    assert c["candidates"] == 3 and not c["problems"]
    cands = {x["title"]: x for x in batch(cfg, "s", "json_file")["candidates"]}
    assert all("market_group" not in x for x in cands.values())   # word rules: veto, no group
    assert any("classify batch 1 failed" in s for s in lines)


def test_unexpected_error_in_preselect_keeps_word_rules(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise ValueError("database is locked")
    monkeypatch.setattr(classify, "preselect", boom)
    cfg, sc, ad = cls_setup(tmp_path, ROWS)
    lines = []
    assert pipeline.collect(cfg, sc, ad, lines.append, classify_first=True)["candidates"] == 3
    assert any("word rules stay" in s for s in lines)


def test_no_llm_call_without_classify_first_or_with_demo_evaluator(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("no LLM call expected")
    monkeypatch.setattr(llm, "run", forbidden)
    cfg, sc, ad = cls_setup(tmp_path, ROWS)
    assert pipeline.collect(cfg, sc, ad, quiet)["candidates"] == 3
    res = run_mod.run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert res.ok


def test_run_search_tells_collect_to_classify_first(tmp_path, monkeypatch):
    seen = []
    real = pipeline.collect

    def spy(cfg, sc, adapter, log=print, classify_first=False, classify_budget=None):
        seen.append(classify_first)
        return real(cfg, sc, adapter, log, classify_first=classify_first, classify_budget=classify_budget)
    monkeypatch.setattr(pipeline, "collect", spy)
    monkeypatch.setattr(llm, "run", fake_llm(LLM_ANSWERS, []))
    cfg, _, _ = cls_setup(tmp_path, ROWS)
    run_mod.run_search(cfg, "s", evaluator="claude", render=False, log=quiet)
    run_mod.run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    cfg2 = write_cfg(tmp_path / "off", {"s": search_cfg(json_file={"path": "l.json"}, classify={"enabled": False})})
    (tmp_path / "off" / "l.json").write_text("[]")
    run_mod.run_search(cfg2, "s", evaluator="claude", render=False, log=quiet)
    assert seen == [True, False, False]


# --- locale -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("code", ["en", "de"])
def test_locale_charging_and_docking_station_are_accessories(code):
    for t in ("PS5 DualSense Charging Station", "Nintendo Switch Docking Station", "Switch Dockingstation"):
        assert is_accessory(t, loc=code), t
    assert not is_accessory("PS5 mit Charging Station" if code == "de" else "PS5 with charging station", loc=code)


@pytest.mark.parametrize("code", ["en", "de"])
def test_locale_switch_number_is_not_a_quantity(code):
    g = {"name": "Switch Pro Controller"}
    assert bundle_qty("Nintendo Switch 2 Pro Controller", g, code) == 1
    assert bundle_qty("Switch 2 Pro Controller", g, code) == 1
    assert bundle_qty("2 Switch Pro Controller", g, code) == 2


def test_charging_station_title_is_skipped_in_select():
    items = {"1": normalize(listing("1", "PS5 DualSense Charging Station", 15), "json_file")}
    sc = {"_name": "s", "_locale": "de", "market": {"groups": GROUPS}}
    assert match_group("PS5 DualSense Charging Station", GROUPS)["name"] == "DualSense"
    assert pipeline.select(items, set(), {}, MARKET, sc, quiet, loc=DE)[0] == []


# --- llm: permission-skipping flags ------------------------------------------------------------------

@pytest.mark.parametrize("extra", [
    ["--dangerously-skip-permissions"], ["--DANGEROUSLY-SKIP-PERMISSIONS"], ["--allow-dangerously-skip-permissions"],
    ["--dangerously-skip-permissions=true"], ["--permission-mode", "bypassPermissions"],
    ["--permission-mode=bypassPermissions"], ["--Permission-Mode", "BYPASSPERMISSIONS"],
    ["--permission-mode bypassPermissions"], ["--model", "x", "--permission-mode", "bypasspermissions"],
])
def test_extra_args_cannot_skip_permissions(tmp_path, monkeypatch, extra):
    with pytest.raises(ConfigError):
        llm.check_extra_args(extra)
    called = []
    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: called.append(a))
    cfg = write_cfg(tmp_path, {"s": search_cfg()}, llm={"extra_args": extra})
    with pytest.raises(ConfigError):
        llm.run(cfg, "x", "haiku")
    assert called == []


def test_command_cannot_skip_permissions(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: called.append(a))
    cfg = write_cfg(tmp_path, {"s": search_cfg()}, llm={"command": ["claude", "-p", "--dangerously-skip-permissions"]})
    with pytest.raises(ConfigError):
        llm.run(cfg, "x", "haiku")
    assert called == []


def test_other_permission_modes_are_fine(monkeypatch):
    llm.check_extra_args(["--permission-mode", "default", "--append-system-prompt", "never bypassPermissions"])
    llm.check_extra_args(["--permission-mode=plan"])


# --- review fixes: plausibility of model groups ---------------------------------------------------

def test_implausible_model_group_falls_back_to_word_rules_in_select(tmp_path, monkeypatch):
    """The shadow-run "DualSense funktionsfähig" -> PS5 (resale ~400): the word rules give DualSense in
    every config version, so the PS5 came from the model (e.g. a shifted index in a large batch). A
    model group whose match regex does not hit the title is ignored."""
    calls = []
    monkeypatch.setattr(llm, "run", fake_llm({"DualSense funktionsfähig": ("PS5", 1, "device")}, calls))
    cfg, sc, ad = cls_setup(tmp_path, [("1", "DualSense funktionsfähig", 25)])
    pipeline.collect(cfg, sc, ad, quiet, classify_first=True)
    c = batch(cfg, "s", "json_file")["candidates"]
    assert len(calls) == 1 and c[0]["market_group"] == "DualSense" and c[0]["market_resale_estimate"] == 51


def test_implausible_model_group_is_ignored_in_insights_and_tracking(tmp_path, monkeypatch):
    """The 0.2.1 path: classify.apply after the merge, then insights let the model override the
    word rules. insights and the tracking correction now ignore a group whose match does not fit."""
    from deal_engine.core import history, insights
    monkeypatch.setattr(llm, "run", fake_llm({"DualSense funktionsfähig": ("PS5", 1, "device"),
                                              "DualSense weiß": ("DualSense", 1, "device")}, []))
    cfg, sc, ad = cls_setup(tmp_path, [("1", "DualSense funktionsfähig", 25), ("2", "DualSense weiß", 30)],
                            track=True)
    res = run_mod.run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert res.ok
    P = config_mod.paths(cfg, "s")
    classify.apply(cfg, sc, P, quiet)
    con = history.connect(P["history"])
    assert classify.lookup(con, "json_file-1", "DualSense funktionsfähig") == ("PS5", 1, "device")   # stored as answered
    assert dict(con.execute("SELECT uid, grp FROM listing")) == {"json_file-1": "DualSense", "json_file-2": "DualSense"}
    con.close()
    insights.apply(cfg, sc, P, quiet)
    st = {l["title"]: l for l in json.loads(P["state"].read_text())["listings"]}
    assert st["DualSense funktionsfähig"]["market_group"] == "DualSense"
    assert st["DualSense funktionsfähig"]["market_resale_estimate"] == 51


def test_from_classification():
    from deal_engine.core.groups import from_classification
    assert from_classification("DualSense funktionsfähig", ("PS5", 1, "device"), GROUPS) is None
    assert from_classification("DualSense für PS5 Konsole", ("DualSense", 1, "device"), GROUPS)[1]["name"] == "DualSense"
    assert from_classification("Ps5 kopfhörer", (None, 1, "accessory"), GROUPS) == ("accessory", None, 1)
    assert from_classification("PS5 Gutschein", (None, 1, "device"), GROUPS) == ("other", None, 1)
    assert from_classification("PS5", ("Unknown", 1, "device"), GROUPS) is None
    assert from_classification("PS5", None, GROUPS) is None


# --- review fixes: tracking keeps the model's decision --------------------------------------------

def test_tracking_follows_the_classification_across_runs(tmp_path, monkeypatch):
    from deal_engine.core import history
    calls = []
    monkeypatch.setattr(llm, "run", fake_llm({"PS5 Konsole Gutschein": (None, 1, "other")}, calls))
    cfg, sc, ad = cls_setup(tmp_path, [("1", "PS5 Konsole Gutschein", 300)], track=True)
    P = config_mod.paths(cfg, "s")

    def grp():
        con = history.connect(P["history"])
        try:
            return con.execute("SELECT grp FROM listing WHERE uid='json_file-1'").fetchone()[0]
        finally:
            con.close()
    pipeline.collect(cfg, sc, ad, quiet, classify_first=True)   # tracked as PS5 by word rules, then corrected
    assert grp() is None
    for _ in range(2):   # later runs: the word rules (PS5) must not come back via COALESCE
        pipeline.collect(cfg, sc, ad, quiet, classify_first=True)
        classify.apply(cfg, sc, P, quiet)
        assert grp() is None
    assert len(calls) == 1


def test_tracking_uses_word_rules_without_or_with_implausible_classification(tmp_path):
    from deal_engine.core import history
    sc = {"_name": "s", "_locale": "de", "market": {"groups": GROUPS}}
    db = tmp_path / "h.db"
    its = [normalize(listing("1", "PS5 Konsole", 300), "json_file"), normalize(listing("2", "DualSense weiß", 40), "json_file")]
    con = history.connect(db)
    with con:
        con.execute("INSERT INTO classify VALUES ('json_file-2', 'DualSense weiß', 'PS5', 1, 'device', '2026-01-01')")
    con.close()
    history.track(db, sc, its, log=quiet)
    con = history.connect(db)
    assert dict(con.execute("SELECT uid, grp FROM listing")) == {"json_file-1": "PS5", "json_file-2": "DualSense"}
    con.close()


# --- review fixes: locale ---------------------------------------------------------------------------

@pytest.mark.parametrize("title, group", [("Switch Lite Charging Port defekt", "Switch Lite"),
                                          ("DualSense Charging Port defekt", "DualSense")])
def test_charging_port_repairs_stay_candidates(title, group):
    assert not is_accessory(title, loc="de") and not is_accessory(title, loc="en")
    items = {"1": normalize(listing("1", title, 20), "json_file")}
    sc = {"_name": "s", "_locale": "de", "market": {"groups": GROUPS}}
    cands, _ = pipeline.select(items, set(), {}, {**MARKET, "Switch Lite": {"median": 120, "n": 9}}, sc, quiet, loc=DE)
    assert len(cands) == 1 and cands[0]["market_group"] == group


@pytest.mark.parametrize("code, title", [("de", "PS5 Konsole ohne Fernbedienung"), ("de", "Switch Lite ohne Ladekabel"),
                                         ("en", "Switch Lite without charger")])
def test_without_clause_is_not_an_accessory(code, title):
    assert not is_accessory(title, loc=code)
    assert is_accessory(title.split(" ohne ")[-1].split(" without ")[-1], loc=code)


@pytest.mark.parametrize("code", ["en", "de"])
def test_charging_accessories(code):
    for t in ("DualSense Charging Station", "Controller Charging Dock", "Charging Stand", "USB-C Charging Cable"):
        assert is_accessory(t, loc=code), t


# --- review fixes: classification budget per search run --------------------------------------------

def test_budget_is_shared_by_the_whole_run(tmp_path, monkeypatch):
    calls = []
    fake = fake_llm({}, calls)
    monkeypatch.setattr(llm, "run", lambda cfg, text, model, tools=("Read", "Write"), **kw:
                        fake(cfg, text, model, tools, **kw) if tools == () else "")
    rows = [("1", "PS5 Konsole A", 100), ("2", "PS5 Konsole B", 100), ("3", "PS5 Konsole C", 100)]
    cfg, _, _ = cls_setup(tmp_path, rows, track=True, classify={"enabled": True, "max_per_run": 2, "batch": 1})
    run_mod.run_search(cfg, "s", evaluator="claude", render=False, log=quiet)
    sent = [t for c in calls if c["tools"] == () for t in re.findall(r"^\d+: (.*)$", c["text"], re.M)]
    assert len(sent) == 2   # preselect took both, nothing left for the step after the merge
    b = classify.Budget(3)
    assert (b.take(2), b.take(5), b.take(1), b.left) == (2, 1, 0, 0)


# --- review fixes: config validation, --settings ------------------------------------------------

@pytest.mark.parametrize("key", ["match", "exclude", "veto"])
def test_invalid_group_regex_is_a_config_error(tmp_path, key):
    g = {"name": "G", "match": "ps5", key: "(unclosed"}
    cfg = write_cfg(tmp_path, {"s": search_cfg(market={"groups": [g]})})
    with pytest.raises(ConfigError, match=f"invalid regex in '{key}'"):
        config_mod.search(cfg, "s")


def test_group_without_match_is_a_config_error(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg(market={"groups": [{"name": "G"}]})})
    with pytest.raises(ConfigError, match="'name' and 'match'"):
        config_mod.search(cfg, "s")


@pytest.mark.parametrize("args", [["--settings", "x.json"], ["--settings=x.json"], ["--SETTINGS", "{}"],
                                  ["--settings {\"permissions\": {\"defaultMode\": \"bypassPermissions\"}}"],
                                  ["--append-system-prompt", "never use --dangerously-skip-permissions"]])
def test_settings_flag_and_literal_tokens_are_rejected(tmp_path, monkeypatch, args):
    with pytest.raises(ConfigError):
        llm.check_extra_args(args)
    called = []
    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: called.append(a))
    cfg = write_cfg(tmp_path, {"s": search_cfg()}, llm={"command": ["claude", "-p", *args]})
    with pytest.raises(ConfigError):
        llm.run(cfg, "x", "haiku")
    assert called == []


def test_model_group_vetoed_for_the_title_is_rejected():
    """The model may overrule a fall-through exclude, but not the target group's veto: the shadow
    run's "DualSense ... Konsole" title must never be priced as a PS5 because the model said so."""
    from deal_engine.core.groups import from_classification
    t = "DualSense für PS5 Konsole funktionsfähig"
    assert from_classification(t, ("PS5", 1, "device"), GROUPS) is None
    kind, g, _ = from_classification(t, ("DualSense", 1, "device"), GROUPS)
    assert (kind, g["name"]) == ("device", "DualSense")
    assert from_classification("Ps5 kopfhörer", ("PS5", 1, "device"), GROUPS) is None
