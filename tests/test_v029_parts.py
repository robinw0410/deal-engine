"""v0.2.9: part word rule (locale de) — eBay "100 % Original Display Für …", enclosures, standalone power supplies.

Came through the elektronik search with `parts: skip`:
  - "100 % Original Display Für IPHONE 15 Pro Max LCD": the leading "100 %" made "Original Display" look
    like the middle of the title, so part_state removed it as a device spec ("iPhone 13 originales
    Display") and the "Display für" rule had nothing left to hit
  - "NAS Gehäuse ohne HDD": "Gehäuse" not at the start and no for-word after it
  - "650W Netzteil": no part word for a power supply
Devices stay: branded NAS without disks, laptops with/without power supply, consoles "Netzteil defekt",
a PC that names its power supply, and the earlier "Ersatzteil" counterexamples."""
import pytest

from deal_engine.core import locale
from deal_engine.core.groups import drop_part, is_part

DE = locale.get("de")

PARTS = [
    "100 % Original Display Für IPHONE 15 Pro Max LCD",
    "NAS Gehäuse ohne HDD",
    "650W Netzteil",
    "be quiet 550W Netzteil",
    "Corsair RM750x 750W ATX Netzteil",
    "2-Bay NAS Gehäuse",
    "NAS Leergehäuse",
    "Externes HDD-Gehäuse 3,5 Zoll",
    "100% Original Akku für iPhone 12",
    "Netzteil für PS5",
]

DEVICES = [
    "Synology DS218 ohne HDD",
    "QNAP TS-251 ohne Festplatten",
    "Synology DS218 NAS Gehäuse ohne HDD",
    "NAS Gehäuse Synology DS918+ ohne HDD",
    "Synology DS220+ 2-Bay NAS ohne Festplatten",
    "Lenovo ThinkPad T480 ohne Netzteil",
    "Dell Latitude 7490 inkl. Netzteil",
    "MacBook Pro 2015 Netzteil fehlt",
    "PS4 Pro Netzteil defekt",
    "Xbox One S Netzteil defekt",
    "PS5 Netzteil kaputt",
    "Gaming PC Ryzen 5 RTX 3060 650W Netzteil",
    "iPhone 12 Pro 100% Akku",
    "100% Akku iPhone 12 Pro 128GB",
    "iPhone 13 100 % Original Display",
    "Xbox One S Ersatzteile Board defekt",
    "iPhone 11 Ersatzteil Rahmen verbogen",
]


@pytest.mark.parametrize("title", PARTS)
def test_parts(title):
    assert is_part(title, loc=DE)
    assert drop_part(title, "skip", None, loc=DE)


@pytest.mark.parametrize("title", DEVICES)
def test_devices(title):
    assert not is_part(title, loc=DE)
    assert not drop_part(title, "skip", None, loc=DE)
    assert not drop_part(title, "skip", "device", loc=DE)


# Classify path: a title that starts with a part noun right before "für"/"for"/"passend" is a part even
# when the classification says "device" (part_spare, groups.is_spare_part)
@pytest.mark.parametrize("title", ["100 % Original Display Für IPHONE 15 Pro Max LCD", "Netzteil für PS5",
                                   "LCD Display für MacBook", "Akku passend für Dyson V8", "Mainboard für ThinkPad T480"])
def test_lead_part_against_device_classification(title):
    assert drop_part(title, "skip", "device", loc=DE)


@pytest.mark.parametrize("title", ["iPhone 13 100 % Original Display", "Xbox One S Ersatzteile Board defekt",
                                   "PS4 Netzteil defekt", "iPhone 11 Ersatzteil Rahmen verbogen",
                                   "Bildschirm für PC 24 Zoll", "Netzteil defekt für PS4 Bastler",
                                   "Display defekt für Bastler iPhone 12"])
def test_lead_part_device_guards(title):
    assert not drop_part(title, "skip", "device", loc=DE)


# Review of 0.2.9: diskless NAS sold as "Leergehäuse", devices that name their "<N>W Netzteil", and
# "<device> Netzteil passend dabei" stay devices (unclassified and classified "device")
REVIEW_DEVICES = [
    "QNAP TS-453 Pro Leergehäuse",
    "Synology DS920+ (Leergehäuse)",
    "Synology DiskStation DS216j Leergehäuse",
    "Synology DS718+ NAS Leergehäuse ohne Festplatten",
    "HP EliteDesk 800 G4 Mini 90W Netzteil dabei",
    "Lenovo ThinkCentre M75q 65W Netzteil",
    "Dell Wyse 5070 65W Netzteil",
    "Prusa MK3S 240W Netzteil",
    "Bambu Lab X1 Carbon 350W Netzteil",
    "Elegoo Neptune 4 Pro 300W Netzteil",
    "Ubiquiti UniFi Switch 24 PoE 250W Netzteil",
    "Cisco Catalyst 2960 Switch 370W Netzteil",
    "UniFi Dream Machine Pro 65W Netzteil",
    "HP ProLiant DL380 Gen9 2x 500W Netzteil",
    "MacBook Pro 2017 61W Netzteil",
    "Dell XPS 15 130W Netzteil",
    "Lenovo ThinkPad T14 135W Netzteil",
    "Alienware m15 R2 240W Netzteil",
    "Acer Nitro 5 135W Netzteil",
    "Steam Deck 45W Netzteil",
    "ThinkPad T480 Netzteil passend dabei",
]


@pytest.mark.parametrize("kind", [None, "device"])
@pytest.mark.parametrize("title", REVIEW_DEVICES)
def test_review_devices(title, kind):
    assert not drop_part(title, "skip", kind, loc=DE)


@pytest.mark.parametrize("title", ["PS2 Leergehäuse Original Ersatzteil", "NAS Leergehäuse", "650W Netzteil",
                                   "be quiet 550W Netzteil", "Corsair RM750x 750W ATX Netzteil"])
def test_review_parts_stay_parts(title):
    assert drop_part(title, "skip", None, loc=DE)
