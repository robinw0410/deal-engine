"""v0.2.4: spare parts without the device are dropped before the evaluation (search setting `parts`).

A repair search ("defekt", eBay "for parts or not working") also finds single parts: "Mainboard
<laptop> …", displays, batteries. They pass the defect signal and, without a market price of
their own, the candidate selection. The word rule (groups.is_part) and the classification kind
"part" let select() drop them; devices with a broken or new part stay."""
import json

import pytest

from deal_engine.core import classify, config as config_mod, locale, pipeline
from deal_engine.core.config import ConfigError
from deal_engine.core.groups import drop_part, from_classification, is_part, is_part_bundle
from deal_engine.core.listing import normalize
from plugins_fixture.helpers import listing, quiet, search_cfg, write_cfg

DE, EN = locale.get("de"), locale.get("en")

PARTS_DE = [
    'Mainboard Lenovo ThinkPad L14 Gen 1 Ryzen 5 Pro funktioniert',
    'MOTHERBOARD Lenovo ThinkPad T480 i5-8350U',
    'Lenovo ThinkPad T480 Mainboard i5-8250U getestet',
    'Defektes Mainboard ThinkPad L14',
    'MacBook Pro 13 A1708 Logicboard 8GB',
    'Display für iPhone 12',
    'Original Akku für MacBook Pro A1708',
    'Akku Lenovo ThinkPad T480 01AV422',
    'Neuer Akku für Dell Latitude 5490',
    'Display-Einheit Surface Pro 7',
    'LCD Display Assembly Lenovo ThinkPad T14 FHD',
    'iPhone 12 Display Ersatz OLED',
    'Ersatz-Akku Nintendo Switch',
    'Tastatur DE für Lenovo ThinkPad T470',
    'Lüfter Kühler PS5',
    'Scharniere MacBook Air 2017',
    'Ersatzteil Gehäuse Nintendo Switch Lite',
    'Laptop-Tastatur HP EliteBook 840 G5',
    'Gehäuse für PS4 Pro',
    'Steam Deck Mainboard 512GB',
    'Mainboard ohne CPU Lenovo ThinkPad',
    'Laufwerk für PS5',
    'ThinkPad X230 Mainboard i5',
    'Lenovo X1 Carbon Mainboard',
    'ASUS Mainboard X570',
    '1x Akku Lenovo T480',
    'Akku 1 Stück Lenovo',
]
# devices must stay: precision over recall (a device taken for a part is lost, a part taken for a
# device only costs an evaluation). Spec phrases, states before/after a part, disc-drive editions,
# consoles, with-clauses with a part.
DEVICES_DE = [
    'Lenovo ThinkPad T480 i5 8GB 256GB FHD Display',
    'ThinkPad T14 Gen 2 Touchscreen',
    'MacBook Pro 13 Retina Display',
    'HP EliteBook 840 G6 Laptop mit FHD Display',
    'Dell Latitude 7490 FHD Touch Display',
    'MacBook Pro defektes Logicboard',
    'ThinkPad T480 gebrochenes Scharnier',
    'Switch Lite defekte Ladebuchse',
    'PS5 defektes Laufwerk',
    'MacBook Air Mainboard Wasserschaden',
    'iPhone 12 Mainboard Fehler',
    'Switch Mainboard Kurzschluss',
    'PS5 Laufwerk ohne Funktion',
    'ThinkPad Scharnier locker',
    'Lenovo ThinkPad Mainboard Fehler startet nicht',
    'PS5 Laufwerk Edition',
    'PS5 Slim Laufwerk Edition 1TB',
    'Sony PS5 Laufwerk Version inkl. Controller',
    'PlayStation 5 Konsole mit Disc Laufwerk',
    'PS5 Konsole Laufwerk',
    'Xbox Series X disc drive edition',
    'Gameboy Color mit IPS Display',
    'GBA SP IPS Display',
    'Nintendo Switch mit neuer Ladebuchse',
    'Game Boy mit neuem Gehäuse und Display',
    'ThinkPad T480 Display defekt',
    'iPhone 12 Akku schwach',
    'iPhone 12 128GB Akku 85%',
    'MacBook Pro 2017 Logicboard defekt',
    'Lenovo ThinkPad T480 i5 8GB ohne Akku',
    'MacBook Air mit neuem Akku',
    'iPhone 11 neuer Akku, Display gebrochen',
    'Display defekt iPhone 12 Pro',
    'Nintendo Switch Lite Display gebrochen',
    'PS4 Pro 1TB Laufwerk liest nicht',
    'Dell Latitude 5490 defekt als Ersatzteilspender',
    'ThinkPad T480 für Bastler / Ersatzteile',
    'Steam Deck 512GB Lüfter laut',
    'Akku Staubsauger Dyson V8',
    'Samsung Galaxy S20 FE Fan Edition',
    'Logitech MX Keys Tastatur',
    'iPad Air 4 Touchscreen reagiert nicht',
    'Lenovo Legion Go Display Riss',
    'Grafikkarte RTX 3070 defekt',
    'Lenovo ThinkPad X1 Carbon Gen 9 14 Zoll WQHD Display',
    'Dell XPS 13 9310 4K Touch Display i7',
    'HP ProBook 450 G8 15,6" FHD IPS',
    'Microsoft Surface Pro 7 Touchscreen 128GB',
    'Asus ZenBook 14 OLED Display',
    'MacBook Air M1 13,3 Zoll Retina Display 256GB',
    'Lenovo Yoga 7 Touchscreen Convertible',
    'Samsung Galaxy S21 AMOLED Display 128GB',
    'iPhone 13 Pro OLED Display 256GB',
    'iPad Pro 11 Liquid Retina Display',
    'Nintendo Switch OLED Modell weiß',
    'Steam Deck OLED 1TB',
    'Lenovo Legion 5 RTX 3060 165Hz Display',
    'MSI Gaming Laptop 144Hz Display defekt',
    'Acer Aspire 5 Notebook mit Akku und Netzteil',
    'HP Pavilion Laptop mit neuer Tastatur',
    'ThinkPad T470 mit neuem Akku und SSD',
    'MacBook Pro 2015 mit neuem Display',
    'iPhone 12 mit neuem Akku 100%',
    'Nintendo Switch Lite mit neuem Display',
    'PS4 Slim mit neuem Lüfter',
    'Xbox One S mit Laufwerk',
    'PS5 Disc Laufwerk Version',
    'Game Boy Advance IPS Display Mod',
    'Gameboy Color Backlight IPS Display',
    'Nintendo 3DS XL mit neuem Gehäuse',
    'ThinkPad T480 Akku defekt startet nicht',
    'Lenovo ThinkPad L14 defekt startet nicht',
    'Dell Latitude 7480 Mainboard defekt',
    'HP EliteBook Display gebrochen sonst ok',
]
# parts the rule leaves to the evaluation on purpose (no "ends with a part word" rule)
MISSED_DE = [
    'PS5 Lüfter',
    'MacBook Pro A1708 Display',
    'PS4 Laufwerk KEM-490',
    'Laptop Tastatur HP EliteBook 840 G5',
]

PARTS_EN = [
    "Motherboard for Dell XPS 13 9360",
    "Replacement screen iPhone 11",
    "Battery for MacBook Air A1466",
    "Lenovo ThinkPad T14 LCD panel FHD",
    "Hinge set for HP EliteBook",
    "Genuine battery Lenovo ThinkPad X1 Carbon",
]
DEVICES_EN = [
    "MacBook Air cracked screen",
    "iPhone 11 battery 82%",
    "ThinkPad T480 for parts or repair",
    "Dell XPS 13 broken display",
    "Battery powered fan",
    "MacBook Pro 2016 logic board dead",
    "Surface Pro 7 with new battery",
    "Dell XPS 13 9310 4K touch display",
    "MacBook Pro 13 Retina display 512GB",
    "Xbox Series X disc drive edition",
    "PlayStation 5 console with disc drive",
    "MacBook Pro broken logic board",
    "Game Boy Color with IPS display",
]


@pytest.mark.parametrize("title", PARTS_DE)
def test_word_rule_parts_de(title):
    assert is_part(title, loc=DE)


@pytest.mark.parametrize("title", DEVICES_DE)
def test_word_rule_devices_with_a_part_de(title):
    assert not is_part(title, loc=DE)


@pytest.mark.parametrize("title", MISSED_DE)
def test_word_rule_leaves_doubtful_parts_to_the_evaluation(title):
    assert not is_part(title, loc=DE)


@pytest.mark.parametrize("title", PARTS_EN)
def test_word_rule_parts_en(title):
    assert is_part(title, loc=EN)


@pytest.mark.parametrize("title", DEVICES_EN)
def test_word_rule_devices_with_a_part_en(title):
    assert not is_part(title, loc=EN)


def test_part_bundles():
    for t in ("Konvolut Mainboards ThinkPad", "Ersatzteilpaket Nintendo Switch", "5x Display iPhone 12",
              "Sammlung Akkus Laptop"):
        assert is_part(t, loc=DE) and is_part_bundle(t, loc=DE), t
    assert is_part_bundle("Lot of 5 screens iPhone 11", loc=EN)
    assert not is_part_bundle("Mainboard ThinkPad L14", loc=DE)
    # model numbers and single items are no quantities
    for t in ("ThinkPad X230 Mainboard i5", "Lenovo X1 Carbon Mainboard", "ASUS Mainboard X570", "ThinkPad X260 Akku",
              "1x Akku Lenovo T480", "Akku 1 Stück Lenovo"):
        assert not is_part_bundle(t, loc=DE), t
    assert is_part_bundle("3 Stück Akku ThinkPad", loc=DE)


def test_part_regex_replaces_the_locale_rule_but_keeps_the_state_removal():
    rx = r"\bplatine\b"
    assert is_part("Platine Controller", rx, DE)
    assert not is_part("Mainboard ThinkPad L14", rx, DE)            # locale words no longer apply
    assert not is_part("Controller Platine defekt", rx, DE)         # state phrase removed first


@pytest.mark.parametrize("mode,kind,title,dropped", [
    ("llm", "part", "Mainboard ThinkPad", True),
    ("llm", "part", "Konvolut Mainboards", False),      # part lots stay, as in 0.2.3
    ("llm", None, "Mainboard ThinkPad", False),           # word rule off by default
    ("llm", "other", "Mainboard ThinkPad", False),
    ("skip", None, "Mainboard ThinkPad", True),
    ("skip", "other", "Mainboard ThinkPad", True),
    ("skip", "device", "Mainboard ThinkPad", False),      # a plausible device classification wins
    ("skip", None, "ThinkPad T480 Display defekt", False),
    ("skip", "part", "Konvolut Mainboards", True),
    ("bundles", "part", "Konvolut Mainboards", False),
    ("bundles", None, "Konvolut Mainboards", False),
    ("bundles", None, "Mainboard ThinkPad", True),
    ("accept", "part", "Mainboard ThinkPad", False),
    ("accept", None, "Mainboard ThinkPad", False),
])
def test_drop_part_modes(mode, kind, title, dropped):
    assert drop_part(title, mode, kind, None, DE) is dropped


def test_classification_kind_part():
    groups = [{"name": "ThinkPad T480", "match": "t480"}]
    assert from_classification("Display ThinkPad T480", (None, 1, "part"), groups) == ("part", None, 1)
    assert "part" in classify.KINDS
    assert classify.parse('{"i": 1, "g": null, "q": 1, "k": "part"}', 1, {"ThinkPad T480"}) == {1: (None, 1, "part")}


@pytest.mark.parametrize("code", ["en", "de"])
def test_classify_prompt_knows_kind_part(code):
    from deal_engine.core.config import PACKAGE
    text = (PACKAGE / "core" / "prompts" / code / "classify.md").read_text()
    assert '"part"' in text and '"accessory"|"part"|"other"' in text


# --- select() -----------------------------------------------------------------------------------

GROUPS = [{"name": "ThinkPad T480", "match": r"t480", "min": 100, "max": 400},
          {"name": "iPhone 12", "match": r"iphone\s*12", "min": 150, "max": 500}]
MARKET = {"ThinkPad T480": {"median": 250, "n": 10}, "iPhone 12": {"median": 300, "n": 10}}
TITLES = {
    "1": "Mainboard Lenovo ThinkPad L14 Gen 1 Ryzen 5 Pro funktioniert",   # no group
    "2": "MOTHERBOARD Lenovo ThinkPad T480 i5-8350U",                                  # group, cheap
    "3": "ThinkPad T480 Display defekt",
    "4": "Display für iPhone 12",
    "5": "iPhone 12 Akku schwach",
    "6": "Konvolut Mainboards ThinkPad",
}


def run_select(parts=None, classified=None, part_regex=None):
    items = {}
    for sid, title in TITLES.items():
        it = normalize(listing(sid, title, 60), "json_file")
        it["_for_parts"] = True   # eBay condition "for parts or not working": a defect signal
        items[sid] = it
    mc = {"groups": GROUPS, **({"part_regex": part_regex} if part_regex else {})}
    sc = {"_name": "s", "_locale": "de", "filters": {"signal_regex": "defekt"}, "market": mc,
          **({"parts": parts} if parts else {})}
    logs = []
    cands, _ = pipeline.select(items, set(), {}, MARKET, sc, logs.append, loc=DE, classified=classified)
    return {c["source_id"] for c in cands}, logs


def test_select_default_keeps_word_rule_parts():
    assert run_select()[0] == set(TITLES)   # as before 0.2.4


def test_select_skip_drops_parts_and_keeps_devices():
    got, logs = run_select("skip")
    assert got == {"3", "5"}
    assert any("4 listings skipped as spare parts" in l for l in logs)


def test_select_bundles_keeps_part_lots():
    assert run_select("bundles")[0] == {"3", "5", "6"}


def test_select_accept_keeps_everything():
    assert run_select("accept", {"2": (None, 1, "part")})[0] == set(TITLES)


def test_select_classification_part_and_device():
    cls = {"2": (None, 1, "part"), "3": ("ThinkPad T480", 1, "device"), "4": ("iPhone 12", 1, "device")}
    # default: only the classification drops
    assert run_select(None, cls)[0] == set(TITLES) - {"2"}
    # skip: the model's plausible "device" wins over the word rule ("4"), its "part" drops ("2")
    assert run_select("skip", cls)[0] == {"3", "4", "5"}


def test_select_accept_part_has_no_market_group():
    items = {"2": normalize(listing("2", TITLES["2"], 60), "json_file")}
    items["2"]["_for_parts"] = True
    sc = {"_name": "s", "_locale": "de", "filters": {"signal_regex": "defekt"}, "market": {"groups": GROUPS},
          "parts": "accept"}
    cands, _ = pipeline.select(items, set(), {}, MARKET, sc, quiet, loc=DE, classified={"2": (None, 1, "part")})
    assert len(cands) == 1 and "market_group" not in cands[0]


def test_select_part_regex_override():
    assert run_select("skip", part_regex=r"^motherboard")[0] == set(TITLES) - {"2"}


# --- config -------------------------------------------------------------------------------------

def test_config_default_and_validation(tmp_path):
    cfg = write_cfg(tmp_path, {"a": search_cfg(), "b": search_cfg(parts="bundles", market={"part_regex": "board"})})
    assert config_mod.search(cfg, "a")["parts"] == "llm"
    assert config_mod.search(cfg, "b")["parts"] == "bundles"
    cfg = write_cfg(tmp_path / "x", {"bad": search_cfg(parts="drop")})
    with pytest.raises(ConfigError, match="parts must be one of"):
        config_mod.search(cfg, "bad")
    cfg = write_cfg(tmp_path / "y", {"bad": search_cfg(parts="skip", market={"part_regex": "(board"})})
    with pytest.raises(ConfigError, match="part_regex"):
        config_mod.search(cfg, "bad")


def test_collect_drops_parts_before_the_evaluation(tmp_path):
    rows = [listing(1, "Mainboard Lenovo ThinkPad L14 defekt Ryzen 5", 50),
            listing(2, "Lenovo ThinkPad L14 defekt startet nicht", 90),
            listing(3, "Akku für Lenovo ThinkPad L14 defekt", 20)]
    (tmp_path / "l.json").write_text(json.dumps(rows))
    cfg = write_cfg(tmp_path, {"s": search_cfg(locale="de", parts="skip", json_file={"path": "l.json"},
                                               filters={"signal_regex": "defekt|startet nicht"})})
    from deal_engine import adapters
    sc = config_mod.search(cfg, "s")
    c = pipeline.collect(cfg, sc, adapters.create("json_file", cfg, sc), quiet)
    assert c["candidates"] == 1
