"""Computed deal score (searches with score.enabled).

The evaluator (an LLM, or the demo evaluator) delivers the numbers: resale price, parts, hours,
shipping, risk. This module turns them into profit, profit per hour and a 1-10 score. It runs
over the whole state after every run, so price changes are reflected immediately. The
evaluator's own opinion is kept as score_ai and caps the formula (the evaluator sees things
that have no number).

The score is a heuristic. The weights below are tuned for small electronics repair/flip deals
and are meant to be adjusted in the config.
"""
import re

from .util import load_json, num, save_json

DEFAULTS = {
    "points": [[0, 1], [8, 4], [15, 6], [25, 7], [40, 8]],   # expected profit per hour -> base score
    "profit_bonus": [[40, 1], [80, 2]],                       # expected profit -> bonus
    "success": {"low": 0.95, "medium": 0.8, "high": 0.55},    # probability the deal works out, by risk
    "salvage": 0.7,               # if it fails: resell broken at ~70 % of the purchase price
    "max_score_high_risk": 7,
    "max_score_no_market": 7,     # without market data the resale price is only the evaluator's guess
    "photo_worse_factor": 0.8,    # photos show more damage than described: success x0.8 ...
    "max_score_photo_worse": 6,   # ... and at most 6
    "photo_poor_factor": 0.85, "max_score_photo_poor": 5,    # stock photos / no usable photos
    "damage_penalty": 0.5, "damage_penalty_max": 2,          # per visible damage on the photos
    "min_hours": {"flip": 1.5, "repair": 1.0},  # incl. photos, listing, messages, handover
    "resale_cap": 1.05,           # evaluator's resale price at most 105 % of the market estimate
    "max_gap_ai": 1,              # formula at most this much above the evaluator's own score
    "fraud_regex": r"fraud|fake|prepayment|stock photo|scam|unrealistically cheap|too cheap|suspicious",
    "max_score_fraud": 3,
    "min_profit": {"flip": 15, "repair": 10},
    "stock_bonus": 0.5,           # parts already in stock
    "target_score": 6,            # price ceiling: highest price that still reaches this score
    "draft_min_score": 5,         # message draft from this score on
}
SHIPPING_DEFAULTS = {
    "pickup_km": 60,              # pick up yourself up to this distance, beyond that ship if possible
    "drive_kmh": 70, "km_cost": 0.25,   # pickup: driving time there and back, cost per km
    "ship_in_cost": 6,            # parcel to you, if the evaluator gives nothing
    "buyer_protection_fee_pct": 0.04, "buyer_protection_fee_min": 0.99,
    "unknown_cost": 15,           # shipping cost the source does not state ("shipping unknown"), never 0
}

def settings(cfg, sc):
    return {**DEFAULTS, **SHIPPING_DEFAULTS, **(cfg.get("shipping") or {}), **(sc.get("score") or {})}


def fraud(l, c):
    """Fraud indicators according to the evaluator. Negated mentions ("no signs of fraud",
    "not a scam") are ignored: up to three words between the negation and the indicator."""
    neg = re.compile(r"\b(no|not|without|none|non|zero)\b[\s-]+(\w+[\s-]+){0,3}?(?=\w*(" + c["fraud_regex"] + "))",
                     re.I)
    text = f"{l.get('issues') or ''} {l.get('summary') or ''}"
    text = neg.sub(" NEGATED_", text)
    return bool(re.search(r"(?<!NEGATED_)(" + c["fraud_regex"] + ")", text, re.I))


def interp(x, pts):
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def eur(v):
    return f"{v:,.0f} €"


def _kind(l):
    return "flip" if str(l.get("deal_type") or "").lower() == "flip" else "repair"


def compute(l, c, caps=True):
    """caps=False: economics only, without the uncertainty caps (used for the price ceiling)."""
    price, resale = num(l.get("price")), num(l.get("market_price"))
    hours = num(l.get("repair_hours"))
    if price is None or resale is None or hours is None:
        return None
    parts = num(l.get("repair_parts_eur")) or 0
    ship = num(l.get("shipping_cost_eur")) or 0
    est = num(l.get("market_resale_estimate"))
    kind = _kind(l)
    # logistics: platform shipping with buyer protection, or pickup (driving time + fuel)
    dist, ship_ok = num(l.get("distance_km")), l.get("shipping_possible")
    travel_h, how = 0.0, ""
    if ship_ok:
        fee = max(c["buyer_protection_fee_min"], price * c["buyer_protection_fee_pct"])
        ship = max(ship, round(c["ship_in_cost"] + fee, 2))
        how = "shipping"
    elif dist is not None and (dist <= c["pickup_km"] or ship_ok is False):
        travel_h = 2 * dist / c["drive_kmh"]
        ship = max(ship, round(2 * dist * c["km_cost"]))
        how = f"pickup {dist:.0f} km"
    elif l.get("shipping_unknown") and not ship:
        # the source states no shipping cost: assume the lump sum (also over an evaluator's 0)
        ship, how = float(c["unknown_cost"]), f"shipping unknown, assumed {c['unknown_cost']:g} €"
    capped = f" (bundle x{l['bundle_qty']})" if l.get("bundle_qty") else ""
    if est and resale > est * c["resale_cap"]:
        resale, capped = round(est * c["resale_cap"]), capped + " (capped at market estimate)"
    mh = c["min_hours"]
    hours = max(hours, mh.get(kind, 1.0) if isinstance(mh, dict) else mh) + travel_h
    profit = resale - price - parts - ship
    risk = str(l.get("risk") or "").lower()
    p = next((v for k, v in c["success"].items() if risk.startswith(k)), c["success"]["medium"])
    pc = str(l.get("photo_check") or "").lower()
    photo_worse = "more damage" in pc
    photo_poor = "insufficient" in pc or "stock photo" in pc or "no usable" in pc
    if photo_worse:
        p *= c["photo_worse_factor"]
    elif photo_poor:
        p *= c["photo_poor_factor"]
    loss = price * (1 - c["salvage"]) + parts + ship   # loss if it does not work out
    ev = p * profit - (1 - p) * loss                   # expected profit
    per_h = profit / hours
    s = interp(ev / hours, c["points"])
    bonus = max([b for t, b in c["profit_bonus"] if ev >= t] or [0])
    s += bonus
    if l.get("parts_in_stock"):
        s += c["stock_bonus"]
    notes = []
    dmg = [x for x in (l.get("visible_damage") or []) if str(x).strip() and not re.match(r"(?i)(none|no)\b", str(x).strip())] \
        if isinstance(l.get("visible_damage"), list) else []
    if dmg:
        pen = min(c["damage_penalty_max"], c["damage_penalty"] * len(dmg))
        s -= pen
        notes.append(f"{len(dmg)} visible damages -{pen:g}")
    if caps and photo_worse and s > c["max_score_photo_worse"]:
        s = c["max_score_photo_worse"]
        notes.append(f"photos: more damage, max {c['max_score_photo_worse']}")
    if caps and photo_poor and s > c["max_score_photo_poor"]:
        s = c["max_score_photo_poor"]
        notes.append(f"photos insufficient, max {c['max_score_photo_poor']}")
    if profit < c["min_profit"].get(kind, 10):
        s = min(s, 3)
        notes.append(f"below minimum profit ({kind})")
    if caps and risk.startswith("high") and s > c["max_score_high_risk"]:
        s = c["max_score_high_risk"]
        notes.append(f"high risk: max {c['max_score_high_risk']}")
    ai = num(l.get("score_ai"))
    if caps and ai is not None and s > ai + c["max_gap_ai"]:
        s = ai + c["max_gap_ai"]
        notes.append(f"formula and evaluator disagree: max evaluator+{c['max_gap_ai']}")
    if caps and fraud(l, c) and s > c["max_score_fraud"]:
        s = c["max_score_fraud"]
        notes.append("fraud indicators")
    if caps and not est and s > c["max_score_no_market"]:
        s = c["max_score_no_market"]
        notes.append(f"resale price without market data: max {c['max_score_no_market']}")
    if caps and str(l.get("status") or "").lower().startswith("reserv"):
        s = min(s, 3)
        notes.append("reserved")
    score = int(max(1, min(10, s)) + 0.5)
    text = (f"sell {eur(resale)}{capped} - buy {eur(price)} - parts {eur(parts)} - "
            f"{'travel' if how.startswith('pickup') else 'shipping'} {eur(ship)}{' (' + how + ')' if how else ''} "
            f"= {eur(profit)} in {round(hours, 2)} h ({eur(per_h)}/h) · risk {risk or '?'}: works out {p * 100:.0f} %, "
            f"otherwise -{eur(loss)} → expected {eur(ev)} ({eur(ev / hours)}/h)"
            + (f" · profit bonus +{bonus}" if bonus else "")
            + (f" · parts in stock +{c['stock_bonus']:g}" if l.get("parts_in_stock") else "")
            + (" · " + ", ".join(notes) if notes else "") + f" → {score}")
    return {"notes": notes, "score": score, "exact": round(max(1, min(10, s)), 2), "profit": round(profit),
            "per_hour": round(per_h, 1), "expected": round(ev), "text": text}


def max_price(l, c):
    """Highest purchase price (steps of 5) at which the deal still reaches target_score."""
    target = c["target_score"]
    base = compute({**l, "price": 0}, c, caps=False)
    if base is None or base["score"] < target:
        return None
    lo, hi = 0, int(num(l.get("market_price")) or 0)
    while lo < hi:   # largest price with score >= target
        mid = (lo + hi + 1) // 2
        r = compute({**l, "price": mid}, c, caps=False)
        if r and r["score"] >= target:
            lo = mid
        else:
            hi = mid - 1
    return lo // 5 * 5


def opening_discount(days_online):
    if days_online is None:
        return 0.10
    return 0.05 if days_online < 3 else 0.10 if days_online < 14 else 0.15 if days_online < 30 else 0.20


def negotiation(l, c):
    price = num(l.get("price"))
    if price is None:
        return None
    d = l.get("days_online")
    offer = int(price * (1 - opening_discount(d)) // 5 * 5)
    mx = max_price(l, c)
    parts = [f"online for {d} days" if d is not None else "time online unknown"]
    if l.get("price_drops"):
        parts.append(f"reduced {l['price_drops']}x")
    if l.get("relisted"):
        parts.append("relisted")
    head = ", ".join(parts)
    if fraud(l, c):
        return f"{head} → fraud indicators: only with pickup and a function test, no prepayment"
    cur = compute(l, c)
    capped = [n for n in (cur["notes"] if cur else []) if "max" in n]
    if mx is not None and mx >= price and capped and cur["score"] < c["target_score"]:
        todo = ("read the issues, the evaluator sees problems" if any("evaluator" in n for n in capped)
                else "ask for more photos and the condition" if any("photo" in n for n in capped)
                else "clarify details")
        return (f"{head} → worth it up to {mx} € by the numbers, but the score is capped ({'; '.join(capped)}): "
                f"{todo}, then open at about {min(offer, mx)} €")
    if mx is None:
        return f"{head} → hardly worth it even for free (score {c['target_score']} not reachable)"
    if mx >= price:
        return f"{head} → open at about {offer} €, worth it (score ≥ {c['target_score']}) up to {mx} €"
    if mx >= price * 0.75:
        return f"{head} → offer at most {mx} € (above that score < {c['target_score']})"
    return f"{head} → only worth it up to {mx} €, price too far above"


def draft(l, c):
    """Message draft to the seller: the evaluator's questions plus an offer."""
    price = num(l.get("price"))
    if price is None:
        return None
    mx = max_price(l, c)
    worth = (num(l.get("score")) or 0) >= c["draft_min_score"] or (mx is not None and mx >= price * 0.75)
    if not worth or mx is None:
        return None
    offer = int(min(price * (1 - opening_discount(l.get("days_online"))), mx) // 5 * 5)
    title = re.sub(r"\s*[|,(–-].*$", "", str(l.get("title") or "the item")).strip()[:60] or "the item"
    qs = l.get("seller_questions") or []
    qs = [qs] if isinstance(qs, str) else [str(q).strip() for q in qs if str(q).strip()]
    pc = str(l.get("photo_check") or "").lower()
    if fraud(l, c):
        qs.insert(0, "Could you send a photo of the device switched on, next to a note with today's date?")
    elif "insufficient" in pc or "stock photo" in pc:
        qs.insert(0, "Could you send a few more photos, especially of the device itself and any damage?")
    out = ["Hi!", f"I'm interested in {title}."]
    if qs:
        out.append("A few quick questions:\n" + "\n".join(f"- {q}" for q in qs[:4]))
    out.append(f"Would {offer} € work for you?" if offer < price else "Is there any room on the price?")
    if l.get("shipping_possible"):
        out.append("I'd like to buy via the platform's shipping with buyer protection.")
    elif fraud(l, c):
        out.append("I'd like to pick it up and test it briefly on site.")
    elif l.get("distance_km") is not None:
        out.append("I could pick it up in the next few days and test it briefly.")
    out.append("Thanks!")
    return "\n\n".join(out)


def apply(cfg, sc, state_path, show=False, log=print):
    """Rescore the whole state of a search. Returns (computed, changed)."""
    if not (sc.get("score") or {}).get("enabled"):
        return 0, 0
    c = settings(cfg, sc)
    state = load_json(state_path, {"listings": []})
    n_calc = n_changed = 0
    for l in state.get("listings", []):
        if "score_ai" not in l:
            l["score_ai"] = l.get("score")
        r = compute(l, c)
        if r is None:
            l["score"] = l.get("score_ai")
            if l.get("tier_ai"):
                l["tier"] = l["tier_ai"]
            l["score_calc"] = "evaluator score (numbers for the formula are missing)"
            continue
        n_calc += 1
        if r["score"] != num(l.get("score")):
            n_changed += 1
        l["score"] = r["score"]
        if "tier_ai" not in l:
            l["tier_ai"] = l.get("tier")
        l["tier"] = "A" if r["score"] >= 7 else "B" if r["score"] >= 5 else "C"
        l["score_exact"] = r["exact"]
        l["expected_profit_eur"] = r["profit"]
        l["profit_per_hour_eur"] = r["per_hour"]
        l["score_calc"] = r["text"]
        neg = negotiation(l, c)
        if neg:
            l["negotiation"] = neg
        msg = draft(l, c)
        if msg:
            l["message_draft"] = msg
        else:
            l.pop("message_draft", None)
        if show:
            print(f"{r['score']:>2} (eval {l.get('score_ai')})  {str(l.get('title'))[:50]:50}  {r['text']}")
    if not show:
        save_json(state_path, state)
    log(f"score {sc['_name']}: {n_calc} computed, {n_changed} changed, "
        f"{len(state.get('listings', [])) - n_calc} without numbers (evaluator score)")
    return n_calc, n_changed
