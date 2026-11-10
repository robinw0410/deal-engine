"""Market groups: which device group a listing title belongs to, bundle quantities, accessories.

A group in the config looks like
  {"name": "PS5", "keyword": "ps5", "match": "\\bps5\\b", "exclude": "pro|digital", "min": 200, "max": 650}
"match"/"exclude" are case-insensitive regexes on the title, min/max the plausible price range of a
working unit (used to keep broken or mispriced listings out of the market statistics).

Groups are checked in order; the first group whose "match" hits and whose "exclude" does not
wins. An excluded title falls through to the later groups. The optional "veto" (regex) stops
that: if "match" and "veto" both hit, the title gets no group at all ("PS5 headset" must not
fall through to a broader group).

Quantity words, "with/inkl." clauses, the default accessory words and the spare-part rule come from the locale
(core/locale.py); every function takes an optional locale (default English).
"""
import re
from functools import lru_cache

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
        pos = 0
        while (m := rx.search(t, pos)):
            pos = m.end()
            if L.not_qty.search(t[:m.start()]):
                # "Elite Series 2", "PS4", "V2"; search on right after the model number, which may be
                # followed by the quantity ("PlayStation 4 2 Controller")
                pos = m.end(1)
                continue
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


def has_extras(title, loc=None):
    """A device listed together with extras that carry their own value ("PS4 mit 6 Spielen",
    "Switch + Zelda"): fine as a candidate, but not a single unit for the market statistics.
    Only with-clauses count ("ohne Spiele" does not); the extras are the locale's bundle_extras."""
    L = _loc(loc)
    for m in L.with_clause.finditer(title or ""):
        clause = m.group(0)
        for x in L.bundle_extras.finditer(clause):
            joins = list(L.with_word.finditer(clause, 0, x.start()))
            if joins and not L.without.search(joins[-1].group(0)):
                return True   # the last joining word before the extra is not "ohne"/"without"
    return False


# extras that come with a device and count for its candidate threshold: "+ 2 Controller", "mit zwei Controllern"
_EXTRA_ADJ = r"(?:original\w*|orig\.?|weitere\w*|zusätzliche\w*|zusaetzliche\w*|additional|extra|neue\w*|new|wireless|kabellose\w*)\s+"


# right after an extra: that unit is missing, broken or not original and adds nothing ("Controller fehlt",
# "Controller defekt", "Controller (Drift)"); fillers between count and extra ("2 originale Sony Controller")
_GONE = (r"fehl\w*|nicht\s+(?:dabei|enthalten|inkl\w*|vorhanden|original|funktionsf\w+)|keiner\b|missing|not\s+included|"
         r"defekt\w*|kaputt\w*|ohne\s+funktion|funktionslos|(?:mit\s+|stick[- ]?)?drift|broken|faulty|fake|nachbau|"
         r"drittanbieter|third.?party")
_FILLER = r"(?:sony|microsoft|nintendo|xbox|ps[45]|playstation\s*[45]|schwarze?\w*|wei(?:ß|ss)e?\w*|blaue?\w*|rote?\w*)"


@lru_cache(maxsize=256)
def _extras_rx(extra_regex, code):
    L = _loc(code)
    num = r"\d{1,2}|" + "|".join(sorted(map(re.escape, L.number_words), key=len, reverse=True))
    unit = r"(?:" + extra_regex + r")"
    return re.compile(
        r"(?<![\w-])(?:(" + num + r")\s*(?:[x×]\s*)?)?"                          # count: "2", "2x", "zwei"
        r"((?:(?:" + _EXTRA_ADJ[:-len(r"\s+")] + r"|" + _FILLER + r")\s+){0,2})"   # "originale", "Sony", "schwarze"
        # "DualShock 4 Controller", "DualSense Edge Controller": one mention, the model number is no count
        + unit + r"(?:[\s-]*(?:(?:\d|(?!(?:und|and|oder|or|mit|with|plus)\b)[a-zäöüß]+)\b[\s-]*)?" + unit + r")*"
        r"(?:\s*[x×]\s*(\d{1,2})\b)?", re.I)                                       # "Controller x2"


def extras_count(title, extra_regex, loc=None):
    """How many units of an extra the title lists with the device ("PS4 + 2 Controller" = 2, "+ Controller"
    = 1, "mit zwei Controllern" = 2, "+ DualShock 4 Controller" = 1); 0 for "ohne Controller", "Controller
    fehlt/defekt/(Drift)", "Controllerladestation"; "2 Controller (1 defekt)" = 1; at most 8 in total."""
    L = _loc(loc)
    t = title or ""
    n = 0
    for m in _extras_rx(extra_regex, L.code).finditer(t):
        before, after = t[:m.start()], t[m.end():]
        if re.search(L.accessory, m.group(0), re.I):
            continue   # "Controllerladestation"
        if re.match(r"[\s-]*(?:" + L.accessory + r"|stick|tasten?|buttons?|port|buchse|akku|battery|platine)", after, re.I):
            continue   # "Controller Ladestation", "Controller-Stick defekt": not a controller
        if not m.group(1) and re.search(r"\b(?:" + L.negations + r")\s+(?:[\w.-]+\s*(?:,|und|oder|&|/)\s*|\w+\s+)?$",
                                        before, re.I):
            continue   # "ohne Controller", "ohne Kabel und Controller"; not "ohne OVP 2 Controller"
        if m.group(1) and re.search(r"\b(?:" + L.negations + r")\s+$", before, re.I):
            continue   # "keine 2 Controller"
        if re.match(r"[\s:(-]*(?:" + _GONE + r")", after, re.I):
            continue   # "Controller fehlt", "Controller defekt", "Controller (Drift)"
        v = (m.group(1) or m.group(3) or "").lower()
        if m.group(1) and L.not_qty.search(t[:m.start(1)]):
            v = (m.group(3) or "").lower()   # "PS 4 Controller", "Elite Series 2 Controller": model number
        k = L.number_words.get(v) or (int(v) if v.isdigit() else 1)
        d = re.match(r"\s*[(,]?\s*(?:davon\s+)?(\d|ein\w*)\s+(?:\w+\s+)?(?:" + _GONE + r")", after, re.I)
        if d:   # "2 Controller (1 defekt)", "2 Controller, 1 ohne Funktion"
            k -= L.number_words.get(d.group(1).lower()) or (int(d.group(1)) if d.group(1).isdigit() else 1)
        n += max(k, 0)
    return max(0, min(n, 8))


def extras_included(group, name):
    """Units of the extras group `name` that belong to the device itself and are no additional value of
    a bundle: group "extras_included", a number for all extras groups or {"<extras group>": n}; default 1
    (a console comes with one controller, so "PS4 mit 2 Controllern" has one additional controller).
    Only the bundle adjustment of the market statistics uses it (market.bundle_adjust); extras_value()
    and market.extras_resale() count every listed unit, as before."""
    v = (group or {}).get("extras_included", 1)
    if isinstance(v, dict):
        v = v.get(name, 1)
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 1


def extras_value(title, group, market, loc=None):
    """Market value of the extras a device listing includes, for the candidate threshold only:
    group "extras": {"<other group>": "<regex counting its units>"}; n x that group's median (every
    listed unit counts, extras_included is not applied here).
    Extras without market data (or games, which no group covers) add nothing. Returns (eur, [(name, n)])."""
    total, parts = 0, []
    for name, extra_rx in ((group or {}).get("extras") or {}).items():
        m = (market or {}).get(name)
        n = extras_count(title, extra_rx, loc)
        if n and m and m.get("median"):
            total += n * m["median"]
            parts.append((name, n))
    return total, parts


# words between a count (or a with-word) and "games": "3 original PS4 Spiele", "mit vielen Spielen", "2 Nintendo
# Switch games" (not "2 Controller und Spiele")
_GAME_ADJ = (r"original\w*|orig\.?|weitere\w*|zusätzliche\w*|zusaetzliche\w*|additional|extra|neue\w*|new|tolle\w*|"
             r"gute\w*|great|top|verschiedene\w*|diverse\w*|various|different|viele\w*|einige\w*|mehrere\w*|"
             r"etliche\w*|zahlreiche\w*|paar|many|several|some|few|couple\s+of|sony|microsoft|nintendo|"
             r"xbox(?:\s+(?:one|360|series\s+[xs]))?|ps\s?[1-5]|playstation(?:\s*[1-5])?|switch|wii(?:\s?u)?|3?ds|pc")


@lru_cache(maxsize=16)
def _games_rx(code):
    """(mention, directly after a with-word, what follows when the games are not part of the offer)."""
    L = _loc(code)
    num = (r"\d{1,2}|" + "|".join(sorted(map(re.escape, L.number_words), key=len, reverse=True))
           + r"|(?:" + L.game_one + r")(?![\w-])(?!\s+(?:paar|few|couple)\b)")   # "ein paar Spiele" is no count
    mention = re.compile(
        r"(?:(?<![\w.,-])(" + num + r")\s*(?:[x×]\s*)?(?:(?:" + _GAME_ADJ + r")[\s-]+){0,3})?"   # count: "3", "3x", "drei"
        r"(?<![a-zäöüß])(" + L.game_words + r")(?!\w)(?![\s-]*(?:" + L.game_not + r"))", re.I)
    # "mit Spielen", "+ viele Spiele", "inkl. PlayStation 4 Spielen": with-word, fillers, the word for games
    joined = re.compile(r"(" + L.with_words + r")\s*(?:(?:" + _GAME_ADJ + r"|ein|an?|\d{1,2})[\s-]+){0,4}$", re.I)
    gone = re.compile(r"[\s(]*(?:" + L.game_gone + r")", re.I)
    return mention, joined, gone


def _in_with_clause(t, pos, L, joined):
    """The word at `pos` is listed as an extra: it stands in a with-clause of the locale and the last
    joining word before it is not "ohne"/"without" (as in has_extras: "mit Controller, Kabel und Spielen"),
    or it follows a with-word directly or after fillers ("mit vielen Spielen", "+ PlayStation 4 Spiele")."""
    j = joined.search(t[:pos])
    if j and not L.without.search(j.group(1)):
        return True
    for c in L.with_clause.finditer(t):
        if c.start() <= pos < c.end():
            joins = list(L.with_word.finditer(t, c.start(), pos))
            return bool(joins) and not L.without.search(joins[-1].group(0))
    return False


def games_count(title, loc=None, default=2):
    """How many games the title lists with the device, for the flat value per game (market.game_value).

    With a count the mention counts wherever it stands: "mit 3 Spielen" = 3, "+ 6 Spiele" = 6, "PS4, 2
    Controller, 8 Spiele" = 8, "mit drei Spielen" = 3, "zwölf Spiele" = 12, "inkl. einem Spiel" = 1; several
    counted mentions add up ("3 Spiele + 2 Games" = 5), at most 50.
    Without a count it counts only as an extra, i.e. in a with-clause ("mit Spielen", "+ Spiele", "inkl.
    vielen Spielen", "mit Controller, Kabel und Spielen" = `default`, market.games_default; "inkl. Spiel" =
    1), not after "ohne"/"without". "PS4 Spiele", "viele Spiele" or "liest Spiele nicht" alone are 0: without
    a with-word the title describes the device or a fault, not an extra.
    Never counted: a negation before ("ohne Spiele", "keine Spiele", "keine 3 Spiele", "ohne Controller und
    Spiele"); a negation or a verb after (the locale's game_gone: "Spiele nicht dabei", "2 Spiele separat
    erhältlich", "und Spiele laufen nicht"); a circumstance ("stürzt bei Spielen ab", "friert im Spiel
    ein", "zum Spielen": the locale's game_prep / game_verb).

    Only the locale's word for games counts (de "Spiel/Spiele/Spielen/Games", en "game(s)"): a game named
    by its title alone ("Switch + Zelda") is 0, as nothing says how many there are. Not counted: "Spielekonsole",
    "game console", "Game Boy". A model number is no count ("mit PlayStation 4 Spielen" = default, "FC 24
    Spiel" = 1); a number after "Switch" is read as a count here ("Switch 2 Spiele + 3 Spiele" = 5)."""
    L = _loc(loc)
    t = str(title or "")
    mention, joined, gone = _games_rx(L.code)
    counted, plain = [], []
    for m in mention.finditer(t):
        before = t[:m.start()]
        if re.search(r"\b(?:" + L.game_verb + r"|" + L.game_prep + r")\s+$", before, re.I):
            continue   # "zum Spielen", "ready to game", "stürzt bei Spielen ab", "friert im Spiel ein"
        if gone.match(t, m.end()):
            continue   # "Spiele nicht dabei", "Spiele laufen nicht", "2 Spiele separat erhältlich"
        v = (m.group(1) or "").lower()
        if v and L.game_model.search(t[:m.start(1)]):
            v = ""     # "PlayStation 4 Spiele", "PS 5 games": model number
        if re.search(r"\b(?:" + L.negations + r")\s+" + ("$" if v else
                     r"(?:[\w.-]+\s*(?:,|und|oder|and|or|&|/)\s*|\w+\s+)?$"), before, re.I):
            continue   # "ohne Spiele", "keine Spiele", "ohne Controller und Spiele"
        single = bool(L.game_single.fullmatch(m.group(2)))
        if v:
            k = L.number_words.get(v) or (int(v) if v.isdigit() else 1)   # "einem Spiel": 1
            counted.append(1 if single and k > 1 else k)   # "FC 24 Spiel": a title's number, one game
        elif _in_with_clause(t, m.start(2), L, joined):
            plain.append(1 if single else max(0, int(default)))
    n = sum(counted) if counted else max(plain, default=0)
    return max(0, min(n, 50))


PARTS_MODES = ("llm", "skip", "bundles", "accept")


def is_part(title, part_regex=None, loc=None):
    """The listing is a spare part without the device ("Mainboard Lenovo ThinkPad L14", "Akku für
    MacBook Pro"), not a device with a broken or new part ("ThinkPad T480 Display defekt",
    "iPhone 12 neuer Akku", "ThinkPad T480 FHD Display"). Precision over recall: a title that names a
    console is never a part; otherwise the locale's state/spec phrases and then the with-clauses are
    removed, and part_regex (default: the locale's part rule, see core/locale.py) is searched."""
    L = _loc(loc)
    if L.part_veto.search(title or ""):
        return False
    t = L.with_clause.sub(" ", L.part_state.sub(" ", title or ""))
    return bool(re.search(part_regex or L.part, t, re.I))


def is_spare_part(title, loc=None):
    """Strong evidence for a part: a part noun before "Ersatzteil"/"spare part" ("PS2 Leergehäuse Original
    Ersatzteil", "Lüfter Kühler Fan PS4 Ersatzteil", "Controller Port Anschlussleiste Ersatzteil"), or a
    title starting with it ("Ersatzteil für PS4 Gehäuse"). Not: a noun with a state word ("Xbox One S
    Ersatzteile Board defekt", "iPhone 11 Ersatzteil Rahmen verbogen": a device for parts), a device sold
    "als Ersatzteil"/"for parts" (removed first, part_state), anything naming a console (part_veto, also
    "Lüfter für PS4 Konsole Ersatzteil": precision over recall)."""
    L = _loc(loc)
    if L.part_veto.search(title or ""):
        return False
    return bool(L.part_spare.search(L.part_state.sub(" ", title or "")))


def is_part_bundle(title, loc=None):
    """The title offers several parts ("Konvolut Mainboards", "Ersatzteilpaket", "lot of 5 screens");
    quantities count from 2 on, so model numbers ("X230") and "1x" are no bundles."""
    return bool(re.search(_loc(loc).part_bundle, title or "", re.I))


def drop_part(title, mode, kind=None, part_regex=None, loc=None):
    """select() drops the listing as a spare part without the device (search setting `parts`).

    kind: of a plausible LLM classification, None without one.
      llm (default)  only listings the classification calls "part", part bundles are kept (as in
                     0.2.3); the word rule is off
      skip           kind "part", "Ersatzteil" + part noun (is_spare_part, even against a device
                     classification), or no device/bundle classification and the word rule (is_part) hits
      bundles        like skip, but part bundles (is_part_bundle) are kept
      accept         never (a "part" is evaluated like a listing without group)"""
    if mode == "accept":
        return False
    if kind == "part":
        part = True
    elif mode == "llm":
        part = False
    else:   # "Ersatzteil" + part noun wins over a device classification, the word rule does not
        part = is_spare_part(title, loc) or (kind not in ("device", "bundle") and is_part(title, part_regex, loc))
    return part and not (mode in ("llm", "bundles") and is_part_bundle(title, loc))


def market_group(title, price, groups, defect=False, accessory_regex=None, loc=None):
    """Group for market statistics and tracking: no accessories, no bundles, price within the
    group's plausible range (defective units are allowed below the range), no device with extras
    such as games ("PS4 mit 6 Spielen")."""
    g = match_group(title, groups)
    if not g or is_accessory(title, accessory_regex, loc) or bundle_qty(title, g, loc) > 1 or has_extras(title, loc):
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
    Otherwise (kind, group dict or None, qty) with kind device/bundle/accessory/part/other
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
    return (kind if kind in ("accessory", "part", "other") else "other"), None, 1


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
        ex = g.get("extras")
        if ex is not None:
            if not isinstance(ex, dict):
                raise ValueError(f"{where}[{i}] ({g['name']}): 'extras' must map group names to regexes")
            names = {x.get("name") for x in groups if isinstance(x, dict)}
            for name, rx in ex.items():
                if name not in names or name == g["name"]:
                    raise ValueError(f"{where}[{i}] ({g['name']}): extras group '{name}' is not another group")
                if not isinstance(rx, str) or not rx.strip():
                    raise ValueError(f"{where}[{i}] ({g['name']}): extras '{name}' needs a non-empty regex")
                try:
                    c = re.compile(rx, re.I)
                except re.error as e:
                    raise ValueError(f"{where}[{i}] ({g['name']}): invalid regex in extras '{name}': {e}")
                if c.match(""):
                    raise ValueError(f"{where}[{i}] ({g['name']}): extras regex '{name}' matches the empty string")
        inc = g.get("extras_included")
        if inc is not None:
            vals = inc if isinstance(inc, dict) else {None: inc}
            unknown = [k for k in vals if k is not None and k not in (ex or {})]
            if unknown or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in vals.values()):
                raise ValueError(f"{where}[{i}] ({g['name']}): 'extras_included' must be an integer >= 0 or map "
                                 f"extras groups of this group to integers >= 0, not {inc!r}")
