"""Market groups: which device group a listing title belongs to, bundle quantities, accessories.

A group in the config looks like
  {"name": "PS5", "keyword": "ps5", "match": "\\bps5\\b", "exclude": "pro|digital", "min": 200, "max": 650}
"match"/"exclude" are case-insensitive regexes on the title, min/max the plausible price range of a
working unit (used to keep broken or mispriced listings out of the market statistics).

Quantity words, "with/inkl." clauses and the default accessory words come from the locale
(core/locale.py); every function takes an optional locale (default English).
"""
import re

from . import locale as locale_mod

# Only groups whose name matches this regex are checked for multi-unit bundles ("3 controllers").
BUNDLE_GROUP = re.compile(r"controller|gamepad|dualsense|dualshock|joy[- ]?con|elite", re.I)


def _loc(loc):
    return loc if isinstance(loc, locale_mod.Locale) else locale_mod.get(loc or "en")


def match_group(title, groups):
    t = title or ""
    for g in groups or []:
        if re.search(g["match"], t, re.I) and not (g.get("exclude") and re.search(g["exclude"], t, re.I)):
            return g
    return None


def bundle_qty(title, group=None, loc=None):
    """Number of identical units in a bundle ("3 PS4 controllers", "DualSense 2x", "3 Stück"), otherwise 1.

    Only applies to groups matching BUNDLE_GROUP (or with "bundle": true); for everything else a
    number in the title is far more likely a storage size or model number than a quantity."""
    L = _loc(loc)
    name = group.get("name") if isinstance(group, dict) else group
    forced = isinstance(group, dict) and group.get("bundle") is True
    if name is not None and not forced and not BUNDLE_GROUP.search(str(name)):
        return 1
    t = str(title or "")
    for rx in L.qty_rx:
        for m in rx.finditer(t):
            if L.not_qty.search(t[:m.start()]):
                continue   # "Elite Series 2", "PS4", "V2"
            v = m.group(1).lower()
            n = L.number_words.get(v) or (int(v) if v.isdigit() else 1)
            if 2 <= n <= 20:
                return n
    return 1


def is_accessory(title, accessory_regex=None, loc=None):
    """The listing itself is an accessory. Accessories mentioned as extras of a device don't count."""
    L = _loc(loc)
    t = L.with_clause.sub(" ", title or "")
    return bool(re.search(accessory_regex or L.accessory, t, re.I))


def market_group(title, price, groups, defect=False, accessory_regex=None, loc=None):
    """Group for market statistics and tracking: no accessories, no bundles, price within the
    group's plausible range (defective units are allowed below the range)."""
    g = match_group(title, groups)
    if not g or is_accessory(title, accessory_regex, loc) or bundle_qty(title, g, loc) > 1:
        return None
    if not defect and price is not None and not (g.get("min", 0) <= price <= g.get("max", 1e9)):
        return None
    return g
