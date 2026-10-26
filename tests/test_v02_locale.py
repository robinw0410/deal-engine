"""v0.2 locales: German vs English rules and texts."""

import pytest

from deal_engine.core import config as config_mod
from deal_engine.core import locale as locale_mod
from deal_engine.core import score
from deal_engine.core.groups import bundle_qty, is_accessory, market_group
from deal_engine.core.run import run_search
from plugins_fixture.helpers import accept_all, listing, quiet, report, search_cfg, state, write_cfg, write_listings

DS = {"name": "DualSense", "match": "dualsense|controller", "min": 20, "max": 90}


# --- quantities and accessories -----------------------------------------------------------------

@pytest.mark.parametrize("title,de,en", [
    ("3 Stück DualSense", 3, 3),
    ("drei Controller", 3, 1),
    ("Controller 3 Stück", 3, 1),        # English does not know "Stück"
    ("2 Stk. DualSense", 2, 1),
    ("zwei DualSense Controller", 2, 1),
    ("DualSense 2x", 2, 2),
    ("3 PS4 controllers", 3, 3),
    ("three controllers", 3, 3),          # English number words also work in German
    ("Elite Series 2 Controller", 1, 1),
    ("PS5 DualSense Controller", 1, 1),
])
def test_bundle_qty(title, de, en):
    assert bundle_qty(title, DS, "de") == de
    assert bundle_qty(title, DS, "en") == en


def test_bundle_qty_accepts_locale_object_and_default():
    assert bundle_qty("drei Controller", DS, locale_mod.get("de")) == 3
    assert bundle_qty("drei Controller", DS) == 1           # default English


def test_bundle_qty_only_for_bundle_groups():
    assert bundle_qty("3 Stück Switch", {"name": "Switch"}, "de") == 1
    assert bundle_qty("3 Stück Switch", {"name": "Switch", "bundle": True}, "de") == 3


@pytest.mark.parametrize("title,de,en", [
    ("PS5 Controller mit Ladekabel", False, False),
    ("Ladekabel für PS5 Controller", True, False),
    ("PS5 inkl. Kabel + Hülle", False, False),
    ("Hülle für Switch Lite", True, False),
    ("Switch Lite with charger", False, False),
    ("Charger for Switch Lite", True, True),
])
def test_is_accessory(title, de, en):
    assert is_accessory(title, None, "de") is de
    assert is_accessory(title, None, "en") is en


def test_market_group_uses_locale():
    groups = [DS]
    assert market_group("drei Controller", 90, groups, loc="de") is None       # bundle
    assert market_group("drei Controller", 50, groups, loc="en") is DS


# --- fraud ----------------------------------------------------------------------------------------

def _settings(code):
    return score.settings({"locale": code}, {"_locale": code, "score": {}})


@pytest.mark.parametrize("issues,expected", [
    ("keine Vorkasse, kein Fake", False),
    ("Kein Betrug erkennbar.", False),
    ("ohne Vorkasse, Abholung möglich", False),
    ("Verkäufer will Vorkasse", True),
    ("Fotos sind Stockfotos", True),
    ("Verdächtig günstig", True),
    ("Keine Vorkasse, aber die Fotos wirken fake", True),
    ("No signs of fraud.", False),
    ("Seller wants prepayment", True),
])
def test_fraud_german(issues, expected):
    assert score.fraud({"issues": issues}, _settings("de")) is expected


def test_fraud_english_does_not_know_german_words():
    assert score.fraud({"issues": "Verkäufer will Vorkasse"}, _settings("en")) is False


# --- texts ----------------------------------------------------------------------------------------

DEAL = {"id": "x-1", "title": "PS5 Controller, Stick Drift", "price": 50, "market_price": 150, "repair_hours": 1,
        "repair_parts_eur": 10, "risk": "low", "deal_type": "repair", "shipping_possible": True,
        "market_resale_estimate": 150, "score": 7, "seller_questions": ["Seit wann?"], "days_online": 5}


def test_draft_and_negotiation_german():
    c = _settings("de")
    d = score.draft(DEAL, c)
    assert d.startswith("Hallo!") and "Ich interessiere mich für PS5 Controller." in d
    assert "Ein paar kurze Fragen:" in d and "Danke!" in d and "Käuferschutz" in d
    n = score.negotiation(DEAL, c)
    assert n.startswith("seit 5 Tagen online") and "einsteigen" in n
    calc = score.compute(DEAL, c)["text"]
    assert calc.startswith("Verkauf ") and "Std." in calc and "Risiko niedrig" in calc


def test_draft_and_negotiation_english():
    c = _settings("en")
    d = score.draft(DEAL, c)
    assert d.startswith("Hi!") and "Thanks!" in d and "Hallo" not in d
    assert score.negotiation(DEAL, c).startswith("online for 5 days")
    assert "risk low" in score.compute(DEAL, c)["text"]


def test_fraud_draft_german():
    d = score.draft({**DEAL, "issues": "Verkäufer will Vorkasse"}, _settings("de"))
    assert "Zettel mit dem heutigen Datum" in d
    assert "Betrugsmerkmale" in score.negotiation({**DEAL, "issues": "Verkäufer will Vorkasse"}, _settings("de"))


@pytest.mark.parametrize("v,de,en", [
    (1234, "1.234 €", "1,234 €"),
    (5, "5 €", "5 €"),
    (1234567, "1.234.567 €", "1,234,567 €"),
    (None, "?", "?"),
    ("80", "80 €", "80 €"),
])
def test_eur(v, de, en):
    assert locale_mod.get("de").eur(v) == de
    assert locale_mod.get("en").eur(v) == en


def test_eur_digits():
    assert locale_mod.get("de").eur(1234.5, 2) == "1.234,50 €"
    assert locale_mod.get("en").eur(1234.5, 2) == "1,234.50 €"


def test_texts_and_fallback():
    de, en = locale_mod.get("de"), locale_mod.get("en")
    assert (de.t("rep.new"), de.t("rep.price"), de.t("rep.gone")) == ("Neu", "Preisänderungen", "Weg")
    assert (en.t("rep.new"), en.t("rep.price"), en.t("rep.gone")) == ("New", "Price changes", "Gone")
    assert de.t("draft.offer", offer=40) == "Wären 40 € für dich in Ordnung?"
    assert de.t("no.such.key") == "no.such.key"
    assert de.label("km") == "Kilometer" and de.label("unknown_field") == "unknown_field"
    assert de.value("high") == "hoch" and de.value("HIGH") == "hoch" and de.value(3) == 3
    # every English text exists in German
    assert set(locale_mod.EN["texts"]) <= set(locale_mod.DE["texts"])
    # placeholders match
    import string
    for k, s in locale_mod.EN["texts"].items():
        f = lambda x: sorted({n for _, n, _, _ in string.Formatter().parse(x) if n})
        assert f(s) == f(locale_mod.DE["texts"][k]), k


def test_unknown_locale():
    with pytest.raises(ValueError, match="unknown locale"):
        locale_mod.get("xx")


def test_search_locale_overrides_global(tmp_path):
    cfg = write_cfg(tmp_path, {"de": search_cfg(locale="de"), "en": search_cfg()}, locale="en")
    assert config_mod.search(cfg, "de")["_locale"] == "de"
    assert config_mod.search(cfg, "en")["_locale"] == "en"
    assert locale_mod.for_search(cfg, config_mod.search(cfg, "de")).code == "de"
    cfg2 = write_cfg(tmp_path / "b", {"s": search_cfg()}, locale="de")
    assert config_mod.search(cfg2, "s")["_locale"] == "de"
    assert write_cfg(tmp_path / "c", {"s": search_cfg()})["locale"] == "en"


# --- report ---------------------------------------------------------------------------------------

def test_merge_report_german(tmp_path, monkeypatch):
    cfg = write_cfg(tmp_path, {"s": search_cfg(locale="de", json_file={"path": "{data_dir}/l.json"})})
    monkeypatch.setenv("DEAL_ENGINE_TODAY", "2026-06-02")
    write_listings(cfg, [listing("1", title="Teurer Laptop", price=1500), listing("2", title="Weg bald")], "l.json")
    assert run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    rep = report(cfg, "s")
    assert "**Neu**" in rep and "1.500 €" in rep and "Score 6, Stufe B" in rep
    monkeypatch.setenv("DEAL_ENGINE_TODAY", "2026-06-03")
    write_listings(cfg, [listing("1", title="Teurer Laptop", price=1234)], "l.json")
    assert run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    rep = report(cfg, "s")
    assert "**Preisänderungen**" in rep and "1.500 € → 1.234 €" in rep
    assert "**Weg**" in rep and "nicht mehr online" in rep
    assert "Price changes" not in rep


def test_merge_report_english(tmp_path, monkeypatch):
    cfg = write_cfg(tmp_path, {"s": search_cfg(json_file={"path": "{data_dir}/l.json"})})
    write_listings(cfg, [listing("1", price=1500)], "l.json")
    run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    rep = report(cfg, "s")
    assert "**New**" in rep and "1,500 €" in rep and "score 6, tier B" in rep


def test_shipping_unknown_note_german(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg(locale="de", json_file={"path": "{data_dir}/l.json"})})
    row = listing("1")
    row.pop("shipping_possible")
    write_listings(cfg, [row], "l.json")
    run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert state(cfg, "s")[0]["shipping_note"] == "Versand unbekannt, 15 € angenommen"


def test_unknown_locale_in_config_is_config_error(tmp_path):
    cfg = write_cfg(tmp_path, {"s": search_cfg(locale="fr", json_file={"path": "l.json"})})
    with pytest.raises(config_mod.ConfigError):
        run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
