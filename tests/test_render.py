"""Static search page: page settings from searches.<name>.web, generic page, German page."""
import json
import re
from pathlib import Path

import pytest
import yaml

from deal_engine.core import config as config_mod
from deal_engine.core.config import ConfigError
from deal_engine.web import render

ROOT = Path(__file__).resolve().parent.parent


def make_cfg(tmp_path, searches, locale="en"):
    raw = {"data_dir": str(tmp_path), "locale": locale, "deals": {"enabled": False}, "searches": searches}
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True))
    return config_mod.load(p)


def write_state(tmp_path, name, listings, report=None):
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / f"{name}.json").write_text(json.dumps({"listings": listings}))
    if report is not None:
        (tmp_path / "reports").mkdir(exist_ok=True)
        (tmp_path / "reports" / f"{name}-latest.md").write_text(report)


def page_html(tmp_path, cfg, name):
    render.render(cfg, name, log=lambda s: None)
    slug = render.cfg_for(name, config_mod.search(cfg, name), cfg)["slug"]
    return (tmp_path / "web" / slug / "index.html").read_text()


def item(i, **kw):
    return {"id": f"x-{i}", "title": f"Item {i}", "price": 100 + i, "score": 5, "tier": "B", "location": "Town",
            "urls": [f"https://example.invalid/{i}"], "first_seen": "2026-01-01", "last_seen": "2026-01-02", **kw}


BIKES = {
    "slug": "bikes", "title": "Motorbikes",
    "tiers": {"A": "Great", "B": "Okay", "C": "Meh"},
    "columns": [{"label": "Touring", "field": "touring_score", "format": "int"},
                {"label": "Mileage", "field": "km", "format": "int"}],
    "meta": ["year", "location"],
    "badges": ["risk", {"field": "abs", "label": "ABS", "class": "ok", "when": True}],
    "sorts": [{"label": "Score", "field": "score", "desc": True},
              {"label": "Touring score", "field": "touring_score", "desc": True}],
    "facets": [{"key": "brand", "label": "Brand", "field": "brand", "default": "unknown", "capitalize": True},
               {"key": "style", "label": "Style", "from": ["title"], "rules": [["Enduro", "gs|enduro"]],
                "other": "Road"}],
    "groups": ["brand"], "chips": ["brand", "style"],
    "toggles": [{"key": "a2", "label": "A2 license", "field": "ps", "max": 48},
                {"key": "abs", "label": "with ABS", "field": "abs", "equals": True}],
    "deal_link": False,
    "unknown_key": "ignored",
}


def test_config_driven_page(tmp_path):
    cfg = make_cfg(tmp_path, {"moto": {"title": "Ignored", "web": BIKES}})
    write_state(tmp_path, "moto", [
        item(1, touring_score=8.6, km=23000, year=2019, brand="bmw", ps=48, abs=True, title="BMW F 750 GS"),
        item(2, touring_score=4, km=51000, year=2012, brand=None, ps=95, abs=False)])
    page = render.cfg_for("moto", config_mod.search(cfg, "moto"), cfg)
    assert page["slug"] == "bikes" and page["title"] == "Motorbikes"
    assert page["groups"] == ["brand", "tier"]   # tier is always available
    html = page_html(tmp_path, cfg, "moto")
    assert "<title>Motorbikes</title>" in html
    assert '<th class="num opt">Touring</th>' in html and '<td class="num opt">9</td>' in html
    assert '<td class="num opt">23,000</td>' in html
    assert '<option value="touringscore" data-desc="1">Touring score</option>' in html
    assert 'data-touringscore="8.6"' in html
    assert "2019 · Town" in html
    assert '<span class="pill ok">ABS</span>' in html and html.count(">ABS</span>") == 1
    html = html.replace("&quot;", '"')   # card facets/toggles are JSON in attributes
    assert '"brand": "Bmw"' in html and '"brand": "Unknown"' in html
    assert '"style": "Enduro"' in html and '"style": "Road"' in html
    assert '"a2": 1' in html and '"abs": 0' in html
    ui = json.loads(html.split("var DE_UI = ")[1].split(";</script>")[0])
    assert ui["toggles"][1:] == [["a2", "A2 license"], ["abs", "with ABS"]]
    assert ui["orders"]["style"] == ["Enduro", "Road"]
    assert ui["orders"]["tier"] == ["Great", "Okay", "Meh", "No tier"]
    assert "deal list" not in html


def test_generic_page(tmp_path):
    cfg = make_cfg(tmp_path, {"misc": {"title": "Misc stuff"}})
    write_state(tmp_path, "misc", [item(1, deal_type="flip", risk="high")])
    page = render.cfg_for("misc", config_mod.search(cfg, "misc"))
    assert page["slug"] == "misc" and page["columns"] == [] and page["badges"] == []
    assert [s[1] for s in page["sorts"]] == ["score", "price"]
    html = page_html(tmp_path, cfg, "misc")
    assert "<h1>Misc stuff</h1>" in html and 'lang="en"' in html
    assert "All listings" in html and "risk high" not in html and "deal list" not in html
    assert '<option value="score" data-desc="1">Score</option>' in html


def test_example_config_electronics_page(tmp_path):
    raw = yaml.safe_load((ROOT / "config.example.yaml").read_text())
    sc = {**raw["searches"]["electronics"], "_locale": "en"}
    page = render.cfg_for("electronics", sc)
    assert page["slug"] == "electronics" and page["deal_link"] is True
    assert [c[0] for c in page["columns"]] == ["Profit", "€/h"]
    assert [s[0] for s in page["sorts"]] == ["Score", "€/h", "Profit", "Price", "Distance"]
    l = {"title": "Sony DualSense controller", "deal_type": "flip", "distance_km": 0, "shipping_possible": True}
    assert page["facets"]["cat"][1](l, page["loc"]) == "Controllers"
    assert page["facets"]["kind"][1](l, page["loc"]) == "Flip"
    assert [fn(l) for _, _, fn in page["toggles"]] == [True, True]


def test_german_page(tmp_path):
    raw = yaml.safe_load((ROOT / "config.example.yaml").read_text())
    el = raw["searches"]["electronics"]
    web = {**el["web"], "copy_prompt": True}   # off by default since 0.2.1
    cfg = make_cfg(tmp_path, {"electronics": {"title": "Elektronik", "web": web}}, locale="de")
    report = ("**Neu**\n- [A](https://x.invalid/1) – 10 €\n- [B](https://x.invalid/2) – 12 €\n\n"
              "**Preisänderungen**\n- [C](https://x.invalid/3): 20 € → 15 €\n\n**Weg**\n- D (5 €) – nicht mehr online\n")
    write_state(tmp_path, "electronics", [
        item(1, deal_type="repair", risk="low", expected_profit_eur=1234, shipping_possible=True,
             message_draft="Hallo", missing_parts=[{"part": "Lüfter", "cost_eur": 12}], score_calc="x")],
        report)
    html = page_html(tmp_path, cfg, "electronics")
    assert 'lang="de"' in html
    for s in ("Alle Inserate", "nach Score", "Gruppieren nach", "Filter zurücksetzen", "Keine Inserate",
              "Nachrichtenentwurf", "Zu kaufende Teile", "Score-Berechnung", "als Prompt kopieren",
              "gekauft → Deal-Liste", "Risiko niedrig", ">Reparatur<", "Gewinn (€)", "Versand möglich",
              "<b>2</b> neu", "<b>1</b> Preisänderungen", "<b>1</b> weg", "1.234 €", "Lohnt sich", "Kategorie",
              '"listings": "Inserate"', "kopiert ✓", "Mein Deal-Finder"):
        assert s in html, s
    for s in ("All listings", "Top 5 <small>by score", "Group by", "Reset filters", "No listings", "Message draft",
              "Parts to buy", "Score calculation", "copy as prompt", "risk low", "active listings", "Why interesting",
              "Shipping possible", "Please be honest"):
        assert s not in html, s


def test_report_stats_localized():
    from deal_engine.core import locale
    de = locale.get("de")
    md = "**Neu**\n- a\n- b\n**Preisänderungen**\n- c\n**Weg**\n- d\n- e\n- f\n**Reserviert**\n- g\n"
    assert render.report_stats(md, de) == {"new": 2, "price": 1, "gone": 3}
    md_en = "**New**\n- a\n**Price changes**\n- b\n- c\n**Gone**\n- d\n"
    assert render.report_stats(md_en) == {"new": 1, "price": 2, "gone": 1}
    assert render.report_stats(md_en, de) == {"new": 1, "price": 2, "gone": 1}


@pytest.mark.parametrize("web, msg", [
    ("electronics", "web must be a mapping"),
    ({"columns": {"field": "x"}}, "web.columns must be a list"),
    ({"columns": [{"label": "X"}]}, "web.columns[0].field must be a string"),
    ({"columns": [{"field": "x", "format": "money"}]}, "format must be one of"),
    ({"sorts": [{"field": "price", "desc": "yes"}]}, "web.sorts[0].desc must be true or false"),
    ({"badges": ["sparkle"]}, "unknown badge 'sparkle'"),
    ({"toggles": [{"field": "km", "max": "50"}]}, "web.toggles[0].max must be a number"),
    ({"facets": [{"key": "c", "rules": [["A", "("]]}]}, "invalid regex"),
    ({"groups": ["nope"]}, "unknown facet 'nope'"),
    ({"deal_link": "true"}, "web.deal_link must be true or false"),
    ({"tiers": ["A", "B"]}, "web.tiers must be a mapping"),
])
def test_config_errors(tmp_path, web, msg):
    cfg = make_cfg(tmp_path, {"s": {"web": web}})
    with pytest.raises(ConfigError, match=re.escape(msg)) as e:
        render.cfg_for("s", config_mod.search(cfg, "s"), cfg)
    assert str(e.value).startswith("search 's': web")
