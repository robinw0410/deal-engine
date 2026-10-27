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
from . import locale as locale_mod
from .groups import bundle_qty, extras_value, from_classification, is_accessory, match_group
from .market import extras_resale, resale_from_ask, settings as market_settings, sold_estimate
from .score import negotiation_head, opening_discount
from .util import load_json, median, save_json

DEFAULTS = {"min_sold": 8, "window_days": 60, "sold_factor": 0.93, "relist_days": 45, "bundle_discount": 0.9}


def days(a, b=None):
    try:
        return ((b or clock.today()) - date.fromisoformat(str(a)[:10])).days
    except (TypeError, ValueError):
        return None


def tokens(t, loc=None):
    stop = (loc or locale_mod.get("en")).stop_words
    return {w for w in re.findall(r"\w+", str(t).lower()) if len(w) > 1 and w not in stop}


def similar(a, b, threshold=0.75, loc=None):
    ta, tb = tokens(a, loc), tokens(b, loc)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= threshold


def _place(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def find_relist(con, search, key, relist_days=45, loc=None):
    """A disappeared listing that is probably the same item as listing `key`, or None.

    Only listings of the same source that disappeared before `key` appeared are considered.
    Strong signal: the same photo URL. Otherwise everything has to match: same location text,
    same market group, price within ±15 % and a title similarity (Jaccard) of at least 0.75.
    Distance from home alone is no evidence: two towns 40 km away can be 80 km apart."""
    row = con.execute("SELECT source, COALESCE(published, first_seen), title, grp, price, image, location "
                      "FROM listing WHERE uid=?", (key,)).fetchone()
    if not row:
        return None
    source, start, title, grp, price, image, location = row
    since = str(clock.today() - timedelta(days=relist_days))
    for o in con.execute("""SELECT title, price, gone_date, COALESCE(published, first_seen), image, location, grp
                            FROM listing WHERE search=? AND source=? AND status='gone' AND uid<>?
                              AND gone_date>=? AND gone_date<=?
                            ORDER BY gone_date DESC""", (search, source, key, since, start)):
        o_title, o_price, o_gone, o_start, o_img, o_loc, o_grp = o
        if image and o_img and image == o_img:
            return {"title": o_title, "price": o_price, "gone": o_gone, "start": o_start, "by": "photo"}
        same_place = bool(_place(location)) and _place(location) == _place(o_loc)
        close_price = bool(o_price and price and 0.85 <= price / o_price <= 1.15)
        if same_place and close_price and grp is not None and grp == o_grp and similar(title, o_title, loc=loc):
            return {"title": o_title, "price": o_price, "gone": o_gone, "start": o_start, "by": "text"}
    return None


def classified(con, key, title):
    """Stored LLM classification (grp, qty, kind) if present and the title is unchanged."""
    return history.classification(con, key, title)


def apply(cfg, sc, paths, log=print):
    if not sc.get("track") or not paths["history"].exists():
        return 0
    name = sc["_name"]
    loc = locale_mod.for_search(cfg, sc)
    c = {**DEFAULTS, **(sc.get("insights") or {})}
    state = load_json(paths["state"], {"listings": []})
    mc = sc.get("market") or {}
    ms = market_settings(mc)
    groups = mc.get("groups", [])
    market = load_json(paths["market"], {})
    formula = bool((sc.get("score") or {}).get("enabled"))
    con = history.connect(paths["history"])
    sold = history.sold_by_group(con, name, c["window_days"])

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

        # 2. relisted? (see find_relist)
        l.pop("relisted", None)
        rel = find_relist(con, name, key, c["relist_days"], loc) if row else None
        if rel:
            l["relisted"] = loc.t("ins.relisted", by=loc.t("ins.by_photo" if rel["by"] == "photo" else "ins.by_text"),
                                  gone=rel["gone"], start=rel["start"], price=loc.num(rel["price"] or 0))
            od = days(rel["start"])
            if od is not None and (l["days_online"] is None or od > l["days_online"]):
                l["days_online"] = od
            n_relist += 1

        # 3a. market group and asking-price estimate, fresh on every run
        qty, extras_eur = 1, 0
        if groups:
            grp = match_group(l.get("title") or "", groups)
            if grp and is_accessory(l.get("title"), mc.get("accessory_regex"), loc):
                grp = None
            qty = bundle_qty(l.get("title"), grp, loc) if grp else 1
            cls = from_classification(l.get("title"), classified(con, key, l.get("title")), groups)
            if cls:   # a plausible LLM classification wins over the word rules
                _, grp, cq = cls
                qty = cq if grp else 1
            m = market.get(grp["name"]) if grp else None
            if m:
                l["market_group"], l["market_median"], l["market_n"] = grp["name"], m["median"], m["n"]
                l["market_resale_estimate_ask"] = resale_from_ask(m, ms["sale_factor"])
                l["market_resale_estimate"] = l["market_resale_estimate_ask"]
                _, parts = extras_value(l.get("title"), grp, market, loc)   # fresh medians, as at the selection
                extras_eur, rows = extras_resale(parts, market, ms["sale_factor"])
                if rows:
                    l["market_extras"] = rows
                else:
                    l.pop("market_extras", None)
            else:
                for k in ("market_group", "market_median", "market_n", "market_resale_estimate",
                          "market_resale_estimate_ask", "market_extras"):
                    l.pop(k, None)
                if grp:
                    l["market_group"] = grp["name"]
        l.pop("sold_info", None)

        # 3b. sale price from disappeared listings (only if lower than the asking-price estimate)
        s = sold.get(l.get("market_group"))
        est = sold_estimate(s["p"], l.get("market_resale_estimate_ask"), c["min_sold"], c["sold_factor"]) if s else None
        if est is not None:
            l["market_resale_estimate"] = est
            l["sold_info"] = (loc.t("ins.sold", n=len(s["p"]), days=c["window_days"], median=loc.num(median(s["p"])))
                              + (loc.t("ins.sold_days", d=f"{median(s['d']):.0f}") if s["d"] else ""))
            n_sold += 1

        # 3c. bundle: unit price x quantity x bundle discount
        l.pop("bundle_qty", None)
        if qty > 1 and isinstance(l.get("market_resale_estimate"), (int, float)):
            l["bundle_qty"] = qty
            l["market_resale_estimate"] = round(l["market_resale_estimate"] * qty * c["bundle_discount"])

        # 3d. extras that come with the device ("PS4 + 2 Controller"): + n x their resale estimate
        if extras_eur and isinstance(l.get("market_resale_estimate"), (int, float)):
            l["market_resale_estimate"] = round(l["market_resale_estimate"] + extras_eur)

        # negotiation hint without score formula (with formula score.py writes a better one)
        if not formula and isinstance(l.get("price"), (int, float)):
            offer = int(l["price"] * (1 - opening_discount(l["days_online"])) // 5 * 5)
            l["negotiation"] = loc.t("neg.simple", head=negotiation_head(l, loc), offer=loc.num(offer))
    con.close()
    save_json(paths["state"], state)
    ready = sorted(g for g, s in sold.items() if len(s["p"]) >= c["min_sold"])
    log(f"insights {name}: {n_relist} relisted, sale price from tracking for {n_sold} listings "
        f"({len(ready)} groups with enough data{': ' + ', '.join(ready[:8]) if ready else ''})")
    return 0
