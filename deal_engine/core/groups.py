"""Market groups: which device group a listing title belongs to, bundle quantities, accessories.

A group in the config looks like
  {"name": "PS5", "keyword": "ps5", "match": "\\bps5\\b", "exclude": "pro|digital", "min": 200, "max": 650}
"match"/"exclude" are case-insensitive regexes on the title, min/max the plausible price range of a
working unit (used to keep broken or mispriced listings out of the market statistics).

Groups are checked in order; the first group whose "match" hits and whose "exclude" does not
wins. An excluded title falls through to the later groups. The optional "veto" (regex) stops
that: if "match" and "veto" both hit, the title gets no group at all ("PS5 headset" must not
fall through to a broader group).

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
    """First group whose match hits and whose exclude does not; None if a matching group's veto hits."""
    t = title or ""
    for g in groups or []:
        if not re.search(g["match"], t, re.I):
            continue
        if g.get("veto") and re.search(g["veto"], t, re.I):
            return None   # no fall-through to later (broader) groups
        if not (g.get("exclude") and re.search(g["exclude"], t, re.I)):
            return g
    return None


def matches_any(title, groups):
    """Some group's match regex hits (ignoring exclude and veto): a title the LLM classification may
    assign to a group although the word rules give none."""
    t = title or ""
    return any(re.search(g["match"], t, re.I) for g in groups or [])


def is_bundle_group(group):
    """Quantities are only read for controller-like groups (BUNDLE_GROUP) or groups with "bundle": true."""
    return isinstance(group, dict) and (group.get("bundle") is True or bool(BUNDLE_GROUP.search(str(group.get("name")))))


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


def from_classification(title, cls, groups):
    """Interpret a stored LLM classification (grp, qty, kind) of `title`.

    Returns None when there is none or when it is implausible, i.e. the model names a group whose
    match regex does not hit the title or whose veto does (exclude is ignored here: the model may
    overrule a fall-through, but never assign a group that does not fit or that the config rules out
    for this title); the word rules decide then.
    Otherwise (kind, group dict or None, qty) with kind device/bundle/accessory/other
    (device/bundle without a known group count as other)."""
    if not cls:
        return None
    grp, q, kind = cls
    if kind in ("device", "bundle"):
        if not grp:
            return "other", None, 1
        g = next((x for x in groups or [] if x["name"] == grp), None)
        if not g or not re.search(g["match"], title or "", re.I) \
                or (g.get("veto") and re.search(g["veto"], title or "", re.I)):
            return None
        try:
            q = max(1, int(q or 1))
        except (TypeError, ValueError):
            q = 1
        return kind, g, q
    return (kind if kind in ("accessory", "other") else "other"), None, 1


def classified_market_group(title, price, groups, cls, defect=False, accessory_regex=None, loc=None):
    """market_group() with a plausible LLM classification taking precedence over the word rules:
    only single devices (or bundles of quantity 1) of a group, price within its range unless defective."""
    r = from_classification(title, cls, groups)
    if r is None:
        return market_group(title, price, groups, defect, accessory_regex, loc)
    _, g, q = r
    if g is None or q > 1:
        return None
    if not defect and price is not None and not (g.get("min", 0) <= price <= g.get("max", 1e9)):
        return None
    return g


def check_groups(groups, where="market.groups"):
    """ValueError with a readable message if a group has no name/match or an invalid regex."""
    for i, g in enumerate(groups or []):
        if not isinstance(g, dict) or not g.get("name") or not g.get("match"):
            raise ValueError(f"{where}[{i}]: every group needs 'name' and 'match'")
        for k in ("match", "exclude", "veto"):
            if g.get(k) is None:
                continue
            try:
                re.compile(str(g[k]), re.I)
            except re.error as e:
                raise ValueError(f"{where}[{i}] ({g['name']}): invalid regex in '{k}': {e}")
