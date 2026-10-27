"""v0.2.8: extras raise the resale estimate (and so the score's resale cap); "Ersatzteil" + part noun is a part."""
import pytest

from deal_engine.core import locale
from deal_engine.core.groups import drop_part, is_spare_part
from deal_engine.core.market import extras_resale
from deal_engine.core.score import DEFAULTS, SHIPPING_DEFAULTS, compute

DE, EN = locale.get("de"), locale.get("en")


# ------------------------------------------------------------------ extras in the resale estimate

def test_extras_resale_same_sale_factor_logic():
    market = {"Pad": {"median": 40, "p25": 30, "n": 20}, "Cam": {"median": 50, "n": 9}}
    eur, rows = extras_resale([("Pad", 2), ("Cam", 1), ("None", 3)], market, 0.85)
    assert eur == 2 * 30 + 42
    assert rows == [{"group": "Pad", "count": 2, "median": 40, "resale": 30},
                    {"group": "Cam", "count": 1, "median": 50, "resale": 42}]


def test_score_cap_includes_extras_and_text_names_them():
    c = {**DEFAULTS, **SHIPPING_DEFAULTS, "_loc": DE}
    base = {"title": "Konsole + 2 Controller", "price": 115, "market_price": 200, "repair_hours": 1,
            "repair_parts_eur": 0, "shipping_cost_eur": 0, "risk": "low", "deal_type": "flip"}
    alone = compute({**base, "market_resale_estimate": 120}, c)
    with_pads = compute({**base, "market_resale_estimate": 120 + 2 * 26,
                         "market_extras": [{"group": "Pad", "count": 2, "median": 30, "resale": 26}]}, c)
    # resale cap 105 %: 126 for the console alone, 181 with both pads (the evaluator says 200)
    assert with_pads["profit"] - alone["profit"] == round((120 + 52) * 1.05) - round(120 * 1.05)
    assert "inkl. 2 × Pad à 26" in with_pads["text"]
    assert "inkl." not in alone["text"]
    # cap not binding: the price is the evaluator's, so no "inkl." next to it
    low = compute({**base, "market_price": 150, "market_resale_estimate": 172,
                   "market_extras": [{"group": "Pad", "count": 2, "median": 30, "resale": 26}]}, c)
    assert "inkl." not in low["text"]


def test_insights_adds_extras_once_per_run(tmp_path, monkeypatch):
    """Over several runs, with sold data and as a classified bundle: the extras are added exactly once."""
    import json
    from deal_engine.core import history, insights
    pad = r"controller\w*|gamepads?|pads?"
    groups = [{"name": "Pad", "match": r"\bpad\b|controller", "exclude": r"\bkonsole\b|\+|\bmit\b"},
              {"name": "Console", "match": r"\bkonsole\b", "extras": {"Pad": pad}}]
    P = {"state": tmp_path / "state.json", "history": tmp_path / "h.db", "market": tmp_path / "m.json"}
    history.connect(P["history"]).close()
    P["market"].write_text(json.dumps({"Console": {"median": 200, "n": 30}, "Pad": {"median": 40, "n": 20}}))
    sc = {"_name": "s", "_locale": "de", "track": True, "market": {"groups": groups}}

    def run(title, sold=None, cls=None):
        P["state"].write_text(json.dumps({"listings": [{"id": "x", "title": title, "price": 100}]}))
        monkeypatch.setattr(insights.history, "sold_by_group", lambda con, n, w: sold or {})
        monkeypatch.setattr(insights, "classified", lambda con, k, t: cls)
        out = []
        for _ in range(3):
            insights.apply({}, sc, P, log=lambda *a: None)
            out.append(json.loads(P["state"].read_text())["listings"][0])
        return out

    plain = run("Konsole + 2 Controller")
    assert [l["market_resale_estimate"] for l in plain] == [170 + 2 * 34] * 3
    assert plain[-1]["market_extras"] == [{"group": "Pad", "count": 2, "median": 40, "resale": 34}]
    sold = run("Konsole + 2 Controller", sold={"Console": {"p": [150] * 10, "d": []}})
    assert [l["market_resale_estimate"] for l in sold] == [round(150 * 0.93) + 68] * 3
    assert "market_extras" not in run("Konsole + 2 Controller", cls=(None, 1, "other"))[-1]


# ------------------------------------------------------------------ spare parts: "Ersatzteil" + part noun

@pytest.mark.parametrize("title", [
    "PS2 Fat Leergehäuse Original Ersatzteil schwarz",
    "Lüfter Kühler Fan Slim Original Ersatzteil",
    "Sony Pro Lüfter Kühler Fan CUH-7016B Ersatzteil",
    "Slim Laufwerksblende Original Ersatzteil",
    "Controller Port USB Anschlussleiste Ersatzteil",
    "Netzteil Platine Original Ersatzteil",
    "Ladebuchse Board Ersatzteil",
])
def test_spare_part_with_part_noun_de(title):
    assert is_spare_part(title, DE)
    assert drop_part(title, "skip", "device", loc=DE)   # wins over a device classification
    assert not drop_part(title, "llm", "device", loc=DE)


@pytest.mark.parametrize("title", [
    "iPhone 5s 16GB Konvolut Ersatzteil/defekt",       # whole devices, sold as spare/defective
    "Tablet als Ersatzteil",
    "Laptop Gehäuse defekt Ersatzteil",
    "Laptop Ersatzteil Lüfter defekt",
    "Handheld Original Ersatzteil",
    "Notebook Ersatzteilspender Board ok",
    "MacBook Pro 2015 Ersatzteil Spender",
    "Konsole Ersatzteil Gehäuse",
    "Game Boy Gehäuse neu",                              # no "Ersatzteil": the general word rule decides
    # review: "<device> Ersatzteil <part> <state>" is a whole device for parts
    "Xbox One S Ersatzteile Board defekt",
    "MacBook Air A1466 Ersatzteil Board ok Gehäuse Dellen",
    "PS5 Slim Ersatzteil Lüfter laut",
    "Thinkpad T480 Ersatzteile: Gehäuse ok, Board defekt",
    "iPhone 11 Ersatzteil Rahmen verbogen",
    "MacBook Pro 13 Ersatzteil Deckel Dellen",
    "Xbox Series S Ersatzteil Abdeckung fehlt",
    "Xbox One Ersatzteil HDMI Port defekt",
    "PS4 Pro Ersatzteil HDMI Buchse kaputt",
    "Gameboy Color Ersatzteil Gehäuse vergilbt",
    "Huawei P30 Ersatzteil – Display und Rahmen ok",
    "Nintendo Switch Lite Ersatzteil Gehäuse",           # ambiguous: stays (precision over recall)
    "Lüfter für PS4 Konsole Original Ersatzteil",        # console veto
])
def test_devices_stay_de(title):
    assert not is_spare_part(title, DE)


@pytest.mark.parametrize("title, expected", [
    ("Original replacement part fan cooler", True),
    ("Spare part housing shell", True),
    ("Laptop for spare parts", False),
    ("iPhone 8 spare parts frame bent", False),
    ("MacBook Air spare parts board ok housing dented", False),
    ("Console spare part fan", False),
])
def test_spare_part_en(title, expected):
    assert is_spare_part(title, EN) is expected
