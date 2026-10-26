"""Insights from the tracking database for the listings of a search.

1. Time online and price drops per listing (for the negotiation hint)
2. Relisted items (the same item was online before and disappeared)
3. Market group, resale estimate from asking prices, and - once a group has enough data -
   the sale price from disappeared listings (replaces the asking-price estimate if lower)
4. Bundles: unit resale price x quantity x bundle discount

Runs after every run, before score.py. Only for searches with "track: true".
"""
import re
from datetime import date, timedelta

from . import clock, history
from .groups import bundle_qty, is_accessory, match_group
from .market import resale_from_ask, settings as market_settings, sold_estimate
from .score import opening_discount
from .util import load_json, median, save_json

DEFAULTS = {"min_sold": 8, "window_days": 60, "sold_factor": 0.93, "relist_days": 45, "bundle_discount": 0.9}
STOP = {"broken", "defect", "defective", "selling", "sale", "new", "top", "condition", "with", "and", "incl",
        "boxed", "used", "for", "the"}


def days(a, b=None):
    try:
        return ((b or clock.today()) - date.fromisoformat(str(a)[:10])).days
    except (TypeError, ValueError):
        return None


def tokens(t):
    return {w for w in re.findall(r"[a-z0-9]+", str(t).lower()) if len(w) > 1 and w not in STOP}


def similar(a, b):
    ta, tb = tokens(a), tokens(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.6


def classified(con, key, title):
    """Stored LLM classification (grp, qty, kind) if present and the title is unchanged."""
    r = con.execute("SELECT title, grp, qty, kind FROM classify WHERE uid=?", (key,)).fetchone()
    return (r[1], r[2] or 1, r[3]) if r and r[0] == title else None


def apply(cfg, sc, paths, log=print):
    if not sc.get("track") or not paths["history"].exists():
        return 0
    name = sc["_name"]
    c = {**DEFAULTS, **(sc.get("insights") or {})}
    state = load_json(paths["state"], {"listings": []})
    mc = sc.get("market") or {}
    ms = market_settings(mc)
    groups = mc.get("groups", [])
    market = load_json(paths["market"], {})
    formula = bool((sc.get("score") or {}).get("enabled"))
    con = history.connect(paths["history"])
    sold = history.sold_by_group(con, name, c["window_days"])
    today = clock.today()

    n_sold = n_relist = 0
    for l in state.get("listings", []):
        key = l.get("id")
        row = con.execute("SELECT published, first_seen, title, grp, price, image, distance_km FROM listing "
                          "WHERE uid=?", (key,)).fetchone()
        # 1. time online and price drops
        start = (row[0] or row[1]) if row else l.get("first_seen")
        l["days_online"] = days(start)
        hist = [p for (p,) in con.execute("SELECT price FROM price WHERE uid=? ORDER BY date", (key,))]
        drops = sum(1 for a, b in zip(hist, hist[1:]) if b < a)
        drops = max(drops, sum(1 for h in (l.get("price_history") or []) if isinstance(h, dict)
                                and (h.get("price") or 0) > (l.get("price") or 0)))
        l["price_drops"] = drops

        # 2. relisted? Same first image is certain; otherwise title, group, distance and price must match
        l.pop("relisted", None)
        if row:
            for o_title, o_price, o_gone, o_start, o_img, o_dist, o_grp in con.execute(
                    """SELECT title, price, gone_date, COALESCE(published, first_seen), image, distance_km, grp
                       FROM listing WHERE search=? AND status='gone' AND uid<>? AND gone_date>=?
                       ORDER BY gone_date DESC""", (name, key, str(today - timedelta(days=c["relist_days"])))):
                same_img = bool(row[5] and o_img and row[5] == o_img)
                near = row[6] is not None and o_dist is not None and abs(row[6] - o_dist) <= 3
                close_price = bool(o_price and row[4] and 0.85 <= row[4] / o_price <= 1.15)
                if same_img or (near and close_price and row[3] == o_grp and similar(row[2], o_title)):
                    l["relisted"] = (f"probably relisted: a similar listing was online until {o_gone} "
                                     f"(since {o_start}, last {o_price:.0f} €)")
                    od = days(o_start)
                    if od is not None and (l["days_online"] is None or od > l["days_online"]):
                        l["days_online"] = od
                    n_relist += 1
                    break

        # 3a. market group and asking-price estimate, fresh on every run
        qty = 1
        if groups:
            grp = match_group(l.get("title") or "", groups)
            if grp and is_accessory(l.get("title"), mc.get("accessory_regex")):
                grp = None
            qty = bundle_qty(l.get("title"), grp) if grp else 1
            cls = classified(con, key, l.get("title"))
            if cls:   # the LLM classification wins over the word rules
                cg, cq, ck = cls
                grp = next((g for g in groups if g["name"] == cg), None) if ck in ("device", "bundle") else None
                qty = cq if grp else 1
            m = market.get(grp["name"]) if grp else None
            if m:
                l["market_group"], l["market_median"], l["market_n"] = grp["name"], m["median"], m["n"]
                l["market_resale_estimate_ask"] = resale_from_ask(m, ms["sale_factor"])
                l["market_resale_estimate"] = l["market_resale_estimate_ask"]
            else:
                for k in ("market_group", "market_median", "market_n", "market_resale_estimate",
                          "market_resale_estimate_ask"):
                    l.pop(k, None)
                if grp:
                    l["market_group"] = grp["name"]
        l.pop("sold_info", None)

        # 3b. sale price from disappeared listings (only if lower than the asking-price estimate)
        s = sold.get(l.get("market_group"))
        est = sold_estimate(s["p"], l.get("market_resale_estimate_ask"), c["min_sold"], c["sold_factor"]) if s else None
        if est is not None:
            l["market_resale_estimate"] = est
            l["sold_info"] = (f"{len(s['p'])} listings of this group disappeared in {c['window_days']} days, "
                              f"median {median(s['p']):.0f} €"
                              + (f", online for {median(s['d']):.0f} days on average" if s["d"] else ""))
            n_sold += 1

        # 3c. bundle: unit price x quantity x bundle discount
        l.pop("bundle_qty", None)
        if qty > 1 and isinstance(l.get("market_resale_estimate"), (int, float)):
            l["bundle_qty"] = qty
            l["market_resale_estimate"] = round(l["market_resale_estimate"] * qty * c["bundle_discount"])

        # negotiation hint without score formula (with formula score.py writes a better one)
        if not formula and isinstance(l.get("price"), (int, float)):
            d = l["days_online"]
            offer = int(l["price"] * (1 - opening_discount(d)) // 5 * 5)
            l["negotiation"] = (f"{'online for ' + str(d) + ' days' if d is not None else 'time online unknown'}"
                                f"{', reduced ' + str(drops) + 'x' if drops else ''} → open at about {offer:,} €")
    con.close()
    save_json(paths["state"], state)
    ready = sorted(g for g, s in sold.items() if len(s["p"]) >= c["min_sold"])
    log(f"insights {name}: {n_relist} relisted, sale price from tracking for {n_sold} listings "
        f"({len(ready)} groups with enough data{': ' + ', '.join(ready[:8]) if ready else ''})")
    return 0
