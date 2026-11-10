"""Market price estimates.

1. From asking prices: median and 25th percentile of working, single units of a group.
   Fresh listings are preferred, because whatever sits online for weeks is overpriced and
   pulls the median up.
2. From disappeared listings (see history.py / insights.py): once a group has enough of them,
   their median replaces the asking-price estimate if it is lower.

Both are estimates. A listing that disappears may have been sold, reserved for weeks or just
deleted; asking prices are not sale prices.

Which listings count for 1. is market.sample (per search):
  all (default)  the word rules decide: group, no accessory, no bundle quantity, no extras, price range
  device_only    only listings the stored LLM classification (item field "_cls" = (grp, qty, kind), see
                 history.classification) calls a single device of this group; not yet classified
                 listings do not count, no model is called here. With fewer than device_min_n devices,
                 bundles of the group are added with their price minus the extras (adjusted_bundles):
                 n x the median of the group's "extras" groups and a flat value per game.
sample_report() compares both ways on the listings stored in history.db.
"""
import re
import time
from datetime import date, timedelta

from . import clock
from . import locale as locale_mod
from .filters import has_signal
from .history import TITLE_LEN
from .groups import (bundle_qty, extras_count, from_classification, games_count, has_extras, is_accessory,
                     match_group)
from .util import median, num

DEFAULTS = {
    "refresh_hours": 20,        # recompute at most this often (and at least once per day)
    "fresh_days": 21,           # "fresh" = published within this many days
    "min_fresh": 8,             # use fresh listings only if there are at least this many
    "min_private": 5,           # otherwise private sellers only, if at least this many
    "min_n": 5,                 # below this, no estimate (the previous one is kept)
    "sale_factor": 0.85,        # asking median -> realistic resale price
    "flip_ratio": 0.7,          # working units: candidate only below median x this
    "defect_price_ratio": 0.6,  # defective units: candidate only below median x this
    "max_price_ratio": 0.75,    # searches without defect signal regex
    # exclude_regex: titles never counted as working units (default: market_exclude of the locale)
    "sample": "all",            # which listings count: "all" (word rules) or "device_only" (LLM classification)
    "device_min_n": 8,          # device_only: with fewer single devices, adjusted bundles are added
    "game_value": 5,            # flat value per game of a bundle (only with sample device_only or when set)
    "game_value_max": 30,       # at most this much for all games of one listing
    "games_default": 2,         # "mit Spielen" without a count
}
SAMPLES = ("all", "device_only")


def settings(mc):
    return {**DEFAULTS, **(mc or {})}


def sample_mode(mc):
    """market.sample of a search: "all" (default) or "device_only"; ValueError for anything else."""
    mode = (mc or {}).get("sample") or "all"
    if mode not in SAMPLES:
        raise ValueError(f"market.sample must be one of {', '.join(SAMPLES)}, not {mode!r}")
    return mode


def _plain(x):
    """29.999999 -> 30, 12.5 stays: amounts as written in the config."""
    x = round(float(x), 2)
    return int(x) if x == int(x) else x


def games_settings(mc):
    """(value per game, maximum per listing or None, count for games without a number) if the flat value
    for games applies to this search, otherwise None. It applies with market.sample device_only (defaults
    5 / 30 / 2) or when market.game_value is set, and only if game_value is above 0; a search with
    neither setting is evaluated exactly as before (games count 0)."""
    mc = mc or {}
    if sample_mode(mc) == "all" and mc.get("game_value") is None:
        return None
    s = settings(mc)
    value, cap = num(s.get("game_value")), num(s.get("game_value_max"))
    if not value or value <= 0:
        return None
    try:
        default = max(0, int(s.get("games_default")))
    except (TypeError, ValueError):
        default = DEFAULTS["games_default"]
    return value, cap, default


def games_value(title, mc, loc=None):
    """(eur, count) of the games a title lists (groups.games_count): count x market.game_value, at most
    market.game_value_max. (0, 0) without games or when the flat value does not apply (games_settings)."""
    gs = games_settings(mc)
    if not gs:
        return 0, 0
    value, cap, default = gs
    n = games_count(title, loc, default)
    eur = n * value if cap is None else min(n * value, max(0, cap))
    return (_plain(eur), n) if n and eur > 0 else (0, 0)


def bundle_adjust(title, price, group, market=None, mc=None, loc=None):
    """Price of the device alone in a bundle listing: price minus n x the asking median of every extras
    group of the device group (groups.extras_count, medians from `market`) minus the flat value of the
    games (games_value). None if nothing can be deducted, or if the title lists extras of a group without
    a market price: a bundle whose extras cannot be valued stays out of the statistics instead of pulling
    the median up."""
    ded = 0
    for name, rx in ((group or {}).get("extras") or {}).items():
        n = extras_count(title, rx, loc)
        if not n:
            continue
        m = (market or {}).get(name)
        if not isinstance(m, dict) or not m.get("median"):
            return None
        ded += n * m["median"]
    ded += games_value(title, mc, loc)[0]
    return price - ded if ded > 0 else None


def _day(today):
    if today is None:
        return clock.today()
    return today if isinstance(today, date) else date.fromisoformat(str(today)[:10])


def _in_range(p, group):
    return group.get("min", 0) <= p <= group.get("max", 1e9)


def classified_sample(items, group, groups, flt=None, mc=None, loc=None, today=None):
    """The listings of `items` that count for `group` with market.sample device_only, by the stored LLM
    classification (item field "_cls" = (grp, qty, kind) or None/missing = not classified):

      device   [(price, fresh, private)]         kind device, quantity 1, this group, plausible
               (groups.from_classification), no games in a with-clause (groups.has_extras: there the
               word rule overrules the model), price within the group's range
      bundle   [(price, fresh, private, title)]  kind bundle with quantity 1 of this group, or such a
               device with games; prices as listed (not adjusted, no range check)
      unclassified  number of listings the word rules place in this group that have no (plausible)
               classification; they count nowhere

    Listings without price, with a defect signal or hit by exclude_regex / the locale's market_exclude
    are left out, as with sample all."""
    s = settings(mc)
    loc = loc if isinstance(loc, locale_mod.Locale) else locale_mod.get(loc or "en")
    excl = s.get("exclude_regex") or loc.market_exclude
    flt = flt or {}
    fresh_cut = str(_day(today) - timedelta(days=int(s["fresh_days"])))
    out = {"device": [], "bundle": [], "unclassified": 0}
    for it in items:
        t, p = it.get("title") or "", it.get("price")
        if p is None or has_signal(it, flt) or re.search(excl, t, re.I):
            continue
        cls = it.get("_cls")
        c = from_classification(t, cls, groups) if isinstance(cls, (tuple, list)) and len(cls) == 3 else None
        if c is None:
            if match_group(t, groups) is group:
                out["unclassified"] += 1
            continue
        kind, g, q = c
        if g is None or g.get("name") != group.get("name") or q != 1:
            continue
        fresh, private = (it.get("_published") or "") >= fresh_cut, bool(it.get("private"))
        if kind == "device" and not has_extras(t, loc):
            if _in_range(p, group):
                out["device"].append((p, fresh, private))
        elif p > 0:
            out["bundle"].append((p, fresh, private, t))
    return out


def _pick(rows, s):
    """Fresh listings if there are enough, otherwise private sellers if enough, otherwise all (rows:
    tuples with fresh at [1] and private at [2])."""
    fresh, priv = [r for r in rows if r[1]], [r for r in rows if r[2]]
    return fresh if len(fresh) >= s["min_fresh"] else priv if len(priv) >= s["min_private"] else rows


def _needs_bundles(cs, s):
    return len(cs["device"]) < int(s["device_min_n"]) and bool(cs["bundle"])


def _from_sample(cs, group, mc, loc, market):
    """Estimate from a classified_sample(): the devices, plus the adjusted bundles if there are fewer
    than device_min_n devices."""
    s = settings(mc)
    rows = [(p, fresh, private, False) for p, fresh, private in cs["device"]]
    if _needs_bundles(cs, s):
        for p, fresh, private, t in cs["bundle"]:
            adj = bundle_adjust(t, p, group, market, mc, loc)
            if adj is not None and adj > 0 and _in_range(adj, group):   # range checked after the adjustment
                rows.append((adj, fresh, private, True))
    rows = _pick(rows, s)
    if len(rows) < s["min_n"]:
        return None
    q = sorted(r[0] for r in rows)
    n_bundle = sum(1 for r in rows if r[3])
    return {"median": round(median(q)), "p25": round(q[len(q) // 4]), "n": len(q),
            "sample": "adjusted_bundles" if n_bundle else "device_only",
            "n_device": len(q) - n_bundle, "n_bundle": n_bundle}


def estimate(items, group, groups, flt=None, mc=None, loc=None, market=None, today=None):
    """{"median", "p25", "n"} for one group from a list of items, or None if too few.

    With market.sample device_only (see classified_sample): additionally "sample" ("device_only", or
    "adjusted_bundles" if bundles were added because there were fewer than device_min_n devices),
    "n_device" and "n_bundle" (n = n_device + n_bundle). `market`: the medians of the other groups for
    the bundle adjustment (bundle_adjust); refresh() passes the freshly computed ones.
    today: reference day for "fresh" (default: today)."""
    s = settings(mc)
    loc = loc if isinstance(loc, locale_mod.Locale) else locale_mod.get(loc or "en")
    if sample_mode(mc) != "all":
        return _from_sample(classified_sample(items, group, groups, flt, mc, loc, today), group, mc, loc, market)
    excl = s.get("exclude_regex") or loc.market_exclude
    flt = flt or {}
    acc = s.get("accessory_regex")
    fresh_cut = str(_day(today) - timedelta(days=int(s["fresh_days"])))
    prices_all, prices_fresh, prices_priv = [], [], []
    for it in items:
        t, p = it.get("title") or "", it.get("price")
        if p is None or has_signal(it, flt) or re.search(excl, t, re.I):
            continue
        if match_group(t, groups) is not group or is_accessory(t, acc, loc) or bundle_qty(t, group, loc) > 1:
            continue
        if has_extras(t, loc):   # "PS4 mit 6 Spielen" is not a single unit
            continue
        if not (group.get("min", 0) <= p <= group.get("max", 1e9)):
            continue
        prices_all.append(p)
        if (it.get("_published") or "") >= fresh_cut:
            prices_fresh.append(p)
        if it.get("private"):
            prices_priv.append(p)
    prices = (prices_fresh if len(prices_fresh) >= s["min_fresh"]
              else prices_priv if len(prices_priv) >= s["min_private"] else prices_all)
    if len(prices) < s["min_n"]:
        return None
    q = sorted(prices)
    return {"median": round(median(q)), "p25": round(q[len(q) // 4]), "n": len(q)}


def due(market, mc):
    s = settings(mc)
    if market.get("_updated") != clock.today_str():
        return True
    return (time.time() - market.get("_ts", 0)) >= float(s["refresh_hours"]) * 3600


def estimate_groups(old, items_by_group, groups, flt, mc, loc=None, today=None):
    """{group name: estimate or None} for all groups from {group name: [items]}.

    With market.sample device_only this takes care of the order: groups with enough devices (or without
    bundles) do not depend on other groups and come first; a group that needs adjusted bundles comes
    after the groups its "extras" refer to, so the bundle adjustment uses their freshly computed
    medians, and the previous ones (`old`) where a group has no new value. Groups whose extras refer
    to each other are computed in config order."""
    names = [g["name"] for g in groups]
    if sample_mode(mc) == "all":
        return {g["name"]: estimate(items_by_group.get(g["name"], []), g, groups, flt, mc, loc, today=today)
                for g in groups}
    s = settings(mc)
    ref = {k: v for k, v in (old or {}).items() if isinstance(v, dict)}
    samples = {g["name"]: classified_sample(items_by_group.get(g["name"], []), g, groups, flt, mc, loc, today)
               for g in groups}
    out, pending = {}, []
    for g in groups:
        if _needs_bundles(samples[g["name"]], s):
            pending.append(g)
            continue
        out[g["name"]] = _from_sample(samples[g["name"]], g, mc, loc, None)
    ref.update({k: v for k, v in out.items() if v})
    while pending:
        waiting = {g["name"] for g in pending}
        ready = [g for g in pending if not (set(g.get("extras") or {}) & waiting)] or pending[:1]
        for g in ready:
            m = out[g["name"]] = _from_sample(samples[g["name"]], g, mc, loc, ref)
            if m:
                ref[g["name"]] = m
        done = {g["name"] for g in ready}
        pending = [g for g in pending if g["name"] not in done]
    return {n: out.get(n) for n in names}


def refresh(old, items_by_group, groups, flt, mc, log=print, loc=None):
    """New market dict from {group name: [items]}; keeps the old value where data is too thin."""
    new = {"_updated": clock.today_str(), "_ts": time.time()}
    est = estimate_groups(old, items_by_group, groups, flt, mc, loc)
    for g in groups:
        m = est.get(g["name"])
        if m:
            new[g["name"]] = m
            log(f"  market {g['name']}: median {m['median']} (n={m['n']})"
                + (f", {m['sample']}: {m['n_device']} devices + {m['n_bundle']} adjusted bundles"
                   if "sample" in m else ""))
        elif g["name"] in old:
            new[g["name"]] = old[g["name"]]
            log(f"  market {g['name']}: too little data, keeping previous value")
        else:
            log(f"  market {g['name']}: too little data")
    return new


def resale_from_ask(m, sale_factor):
    """Realistic resale price from asking prices: the lower of p25 and median x sale_factor."""
    return round(min(m.get("p25") or m["median"], m["median"] * float(sale_factor)))


def extras_resale(parts, market, sale_factor):
    """Resale value of the extras a device listing includes (groups.extras_value parts: [(group, n)]):
    n x the realistic resale price of that group, same sale_factor logic as the device (resale_from_ask).
    Returns (eur, [{"group", "count", "median", "resale"}]) for market_extras."""
    total, rows = 0, []
    for name, n in parts:
        m = market.get(name)
        if not m or not m.get("median"):
            continue
        unit = resale_from_ask(m, sale_factor)
        total += n * unit
        rows.append({"group": name, "count": n, "median": m["median"], "resale": unit})
    return total, rows


def sold_estimate(sold_prices, ask, min_sold=8, sold_factor=0.93):
    """Resale estimate from disappeared listings; only if enough data, and never above `ask`."""
    if len(sold_prices) < min_sold:
        return None
    est = round(median(sold_prices) * sold_factor)
    return min(est, ask) if isinstance(ask, (int, float)) else est


def _median_n(prices):
    return {"median": round(median(prices)) if prices else None, "n": len(prices)}


def sample_report(con, sc, days=30, loc=None, today=None, market=None):
    """Before/after comparison of market.sample for one search, from the listings stored in history.db.

    con: sqlite3 connection to history.db. Only SELECTs: nothing is written and no schema is created,
    so a connection opened read-only ("file:...?mode=ro", uri=True) is enough. sc: the search (from
    config.search). Listings of the search seen in the last `days` days (listing.last_seen) with a
    price and without the stored defect flag are used; the classification comes from table classify
    and is valid only for the same title (as in history.classification). loc: locale (default: the
    search's). today: reference day (default: today). market: current market file as a fallback for
    extras groups without enough data of their own (optional).

    Returns one dict per group, in config order:
      group         name
      before        {"median", "p25", "n"} with sample all (the word rules), or None (too little data)
      after         {"median", "p25", "n", "sample", "n_device", "n_bundle"} with the search's
                    market.sample (device_only is used if the search still has all), or None
      device        {"median", "n"} of the single devices by classification (median None if n = 0)
      bundle        {"median", "n"} of the bundles by classification, prices as listed
      bundle_share  n bundles / (n devices + n bundles), None if both are 0
      unclassified  number of listings of the group (word rules) without a plausible classification
    device and bundle count all listings of the period (classified_sample), before/after apply the
    fresh/private selection and min_n like a market update."""
    mc = sc.get("market") or {}
    groups, flt = mc.get("groups") or [], sc.get("filters") or {}
    loc = loc if isinstance(loc, locale_mod.Locale) else locale_mod.get(loc or sc.get("_locale") or "en")
    day = _day(today)
    since = str(day - timedelta(days=int(days)))
    items = []
    for title, price, private, published, defect, c_uid, c_title, grp, qty, kind in con.execute(
            """SELECT l.title, l.price, l.private, l.published, l.defect, c.uid, c.title, c.grp, c.qty, c.kind
               FROM listing l LEFT JOIN classify c ON c.uid = l.uid
               WHERE l.search=? AND l.last_seen>=? AND l.price IS NOT NULL""", (sc["_name"], since)):
        if defect:
            continue
        title = (title or "")[:TITLE_LEN]
        items.append({"title": title, "price": price, "private": bool(private), "_published": published,
                      "_cls": (grp, qty or 1, kind) if c_uid is not None and c_title == title else None})
    by = {g["name"]: items for g in groups}
    mc_after = mc if sample_mode(mc) != "all" else {**mc, "sample": "device_only"}
    before = estimate_groups({}, by, groups, flt, {**mc, "sample": "all"}, loc, day)
    after = estimate_groups(market or {}, by, groups, flt, mc_after, loc, day)
    out = []
    for g in groups:
        cs = classified_sample(items, g, groups, flt, mc_after, loc, day)
        dev, bun = [r[0] for r in cs["device"]], [r[0] for r in cs["bundle"]]
        total = len(dev) + len(bun)
        out.append({"group": g["name"], "before": before[g["name"]], "after": after[g["name"]],
                    "device": _median_n(dev), "bundle": _median_n(bun),
                    "bundle_share": round(len(bun) / total, 3) if total else None,
                    "unclassified": cs["unclassified"]})
    return out


def format_sample_report(rows, days=30):
    """sample_report() as a plain text table (python -m deal_engine market-sample <search>)."""
    def est(m):
        return f"{m['median']:>5} {m['p25']:>5} {m['n']:>4}" if m else f"{'-':>5} {'-':>5} {'-':>4}"

    def med(m):
        return f"{m['median'] if m['median'] is not None else '-':>5} {m['n']:>4}"
    head = (f"{'group':24} | {'all':>5} {'p25':>5} {'n':>4} | {'new':>5} {'p25':>5} {'n':>4} {'sample':16} "
            f"{'dev':>3} {'bun':>3} | {'device':>6} {'n':>3} | {'bundle':>6} {'n':>3} {'share':>5} | {'uncl':>4}")
    lines = [head, "-" * len(head)]
    for r in rows:
        a = r["after"] or {}
        share = f"{r['bundle_share'] * 100:.0f} %" if r["bundle_share"] is not None else "-"
        lines.append(f"{str(r['group'])[:24]:24} | {est(r['before'])} | {est(r['after'])} {a.get('sample', '-'):16} "
                     f"{a.get('n_device', '-'):>3} {a.get('n_bundle', '-'):>3} | {med(r['device']):>10} | "
                     f"{med(r['bundle']):>10} {share:>5} | {r['unclassified']:>4}")
    lines.append(f"\nListings of the last {days} days in history.db, without defective ones. all: word rules "
                 f"(market.sample all); new: the search's market.sample (device_only if it is all). device / "
                 f"bundle: all classified listings of the period, bundle prices as listed. '-': too little data.")
    return "\n".join(lines)
