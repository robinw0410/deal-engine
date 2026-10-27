"""Market price estimates.

1. From asking prices: median and 25th percentile of working, single units of a group.
   Fresh listings are preferred, because whatever sits online for weeks is overpriced and
   pulls the median up.
2. From disappeared listings (see history.py / insights.py): once a group has enough of them,
   their median replaces the asking-price estimate if it is lower.

Both are estimates. A listing that disappears may have been sold, reserved for weeks or just
deleted; asking prices are not sale prices.
"""
import re
import time
from datetime import timedelta

from . import clock
from . import locale as locale_mod
from .filters import has_signal
from .groups import bundle_qty, has_extras, is_accessory, match_group
from .util import median

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
}


def settings(mc):
    return {**DEFAULTS, **(mc or {})}


def estimate(items, group, groups, flt=None, mc=None, loc=None):
    """{"median", "p25", "n"} for one group from a list of items, or None if too few."""
    s = settings(mc)
    loc = loc if isinstance(loc, locale_mod.Locale) else locale_mod.get(loc or "en")
    excl = s.get("exclude_regex") or loc.market_exclude
    flt = flt or {}
    acc = s.get("accessory_regex")
    fresh_cut = str(clock.today() - timedelta(days=int(s["fresh_days"])))
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


def refresh(old, items_by_group, groups, flt, mc, log=print, loc=None):
    """New market dict from {group name: [items]}; keeps the old value where data is too thin."""
    new = {"_updated": clock.today_str(), "_ts": time.time()}
    for g in groups:
        m = estimate(items_by_group.get(g["name"], []), g, groups, flt, mc, loc)
        if m:
            new[g["name"]] = m
            log(f"  market {g['name']}: median {m['median']} (n={m['n']})")
        elif g["name"] in old:
            new[g["name"]] = old[g["name"]]
            log(f"  market {g['name']}: too little data, keeping previous value")
        else:
            log(f"  market {g['name']}: too little data")
    return new


def resale_from_ask(m, sale_factor):
    """Realistic resale price from asking prices: the lower of p25 and median x sale_factor."""
    return round(min(m.get("p25") or m["median"], m["median"] * float(sale_factor)))


def sold_estimate(sold_prices, ask, min_sold=8, sold_factor=0.93):
    """Resale estimate from disappeared listings; only if enough data, and never above `ask`."""
    if len(sold_prices) < min_sold:
        return None
    est = round(median(sold_prices) * sold_factor)
    return min(est, ask) if isinstance(ask, (int, float)) else est
