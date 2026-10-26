"""Market groups: which device group a listing title belongs to, bundle quantities, accessories.

A group in the config looks like
  {"name": "PS5", "keyword": "ps5", "match": "\\bps5\\b", "exclude": "pro|digital", "min": 200, "max": 650}
"match"/"exclude" are case-insensitive regexes on the title, min/max the plausible price range of a
working unit (used to keep broken or mispriced listings out of the market statistics).
"""
import re

# Accessories and packaging never count as a device of a group. Overridable per search
# with market.accessory_regex.
ACCESSORY = (r"\bcase\b|\bcover\b|skin|sleeve|\bstand\b|holder|mount|charging (station|dock)|charger|"
             r"\bcable\b|\busb\b|empty box|\bbox only\b|packaging|dummy|power ?bank|battery pack|"
             r"screen protector|\bbag\b|sticker|steering wheel|remote|\bgrips?\b|thumb ?grips?|"
             r"\bcaps\b|docking station|\bdock only\b")
# Only groups whose name matches this regex are checked for multi-unit bundles ("3 controllers").
BUNDLE_GROUP = re.compile(r"controller|gamepad|dualsense|dualshock|joy[- ]?con|elite", re.I)
WORDNUM = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "pair": 2}
_NUM = r"(\d{1,2}|two|three|four|five|six|seven|eight|nine|ten)"
QTY_RX = [
    # "3 PS4 controllers", "2x DualSense", "five broken gamepads"
    re.compile(r"(?<![\w.,])" + _NUM + r"\s*(?:x|×|pcs\.?|pieces?|units?)?\s+(?:[\w-]+\s+){0,2}?"
               r"(?:controllers?|gamepads?|dualsense|dualshock|pads)\b", re.I),
    # "DualSense 2x", "controller 3 pcs"
    re.compile(r"(?<![\w.,])" + _NUM + r"\s*(?:x|×|pcs\.?|pieces?|units)(?!\w)", re.I),
]
# a number right after these words is a model/version, not a quantity ("Elite Series 2", "PS4", "V2")
NOT_QTY = re.compile(r"(series|gen\.?|generation|version|model|mk|v|ps|edition|rev\.?)\s*$", re.I)


def match_group(title, groups):
    t = title or ""
    for g in groups or []:
        if re.search(g["match"], t, re.I) and not (g.get("exclude") and re.search(g["exclude"], t, re.I)):
            return g
    return None


def bundle_qty(title, group=None):
    """Number of identical units in a bundle ("3 PS4 controllers", "DualSense 2x"), otherwise 1.

    Only applies to groups matching BUNDLE_GROUP; for everything else a number in the title is far
    more likely a storage size or model number than a quantity."""
    name = group.get("name") if isinstance(group, dict) else group
    if name is not None and not BUNDLE_GROUP.search(str(name)):
        return 1
    t = str(title or "")
    for rx in QTY_RX:
        for m in rx.finditer(t):
            if NOT_QTY.search(t[:m.start()]):
                continue
            v = m.group(1).lower()
            n = WORDNUM.get(v) or (int(v) if v.isdigit() else 1)
            if 2 <= n <= 20:
                return n
    return 1


# "Switch Lite with charger", "PS5 incl. cable + case": accessories that come WITH a device
WITH_CLAUSE = re.compile(r"(\bwith\b|\bincl\b\.?|\bincluding\b|\+|&|\band\b)\s*(?:\d+\s*)?(?:x\s*)?(?:[\w.-]+\s+){0,2}?"
                         r"[\w.-]+(?:\s+(?:and|&|\+|,)\s*[\w.-]+)*", re.I)


def is_accessory(title, accessory_regex=None):
    """The listing itself is an accessory. Accessories mentioned as extras of a device don't count."""
    t = WITH_CLAUSE.sub(" ", title or "")
    return bool(re.search(accessory_regex or ACCESSORY, t, re.I))


def market_group(title, price, groups, defect=False, accessory_regex=None):
    """Group for market statistics and tracking: no accessories, no bundles, price within the
    group's plausible range (defective units are allowed below the range)."""
    g = match_group(title, groups)
    if not g or is_accessory(title, accessory_regex) or bundle_qty(title, g) > 1:
        return None
    if not defect and price is not None and not (g.get("min", 0) <= price <= g.get("max", 1e9)):
        return None
    return g
