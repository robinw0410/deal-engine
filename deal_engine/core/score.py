"""Computed deal score (searches with score.enabled).

The evaluator (an LLM, or the demo evaluator) delivers the numbers: resale price, parts, hours,
shipping, risk. This module turns them into profit, profit per hour and a 1-10 score. It runs
over the whole state after every run, so price changes are reflected immediately. The
evaluator's own opinion is kept as score_ai and caps the formula (the evaluator sees things
that have no number).

The score is a heuristic. The weights below are tuned for small electronics repair/flip deals
and are meant to be adjusted in the config. Texts (calculation, negotiation hint, message draft)
and the fraud negations come from the locale.

Score hooks (score.hooks: ["module:function", ...]) run after the calculation for every listing:

  def hook(listing, info):
      # info: score, exact, computed (formula or evaluator score), caps (cap keys that applied,
      #       e.g. "high_risk", "fraud", "ai_gap"), notes, settings, locale
      return None                         # nothing to change
      return {"score": 4, "note": "..."}  # new score (1-10, rounded) and a note for score_calc

The tier is derived from the final score (A ≥ 7, B ≥ 5, else C) after the hooks.
"""
import re

from . import locale as locale_mod
from . import plugins
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
    # fraud_regex / fraud_negations: default from the locale
    "max_score_fraud": 3,
    "min_profit": {"flip": 15, "repair": 10},
    "stock_bonus": 0.5,           # parts already in stock
    "target_score": 6,            # price ceiling: highest price that still reaches this score
    "draft_min_score": 5,         # message draft from this score on
    "hooks": [],                  # "module:function" called after the calculation, see above
}
SHIPPING_DEFAULTS = {
    "pickup_km": 60,              # pick up yourself up to this distance, beyond that ship if possible
    "drive_kmh": 70, "km_cost": 0.25,   # pickup: driving time there and back, cost per km
    "ship_in_cost": 6,            # parcel to you, if the evaluator gives nothing
    "buyer_protection_fee_pct": 0.04, "buyer_protection_fee_min": 0.99,
    "unknown_cost": 15,           # shipping cost the source does not state ("shipping unknown"), never 0
}


def settings(cfg, sc):
    c = {**DEFAULTS, **SHIPPING_DEFAULTS, **(cfg.get("shipping") or {}), **(sc.get("score") or {})}
    c["_loc"] = locale_mod.for_search(cfg, sc)
    return c


def _loc(c):
    return c.get("_loc") or locale_mod.get("en")


def fraud(l, c):
    """Fraud indicators according to the evaluator. Negated mentions ("no signs of fraud",
    "keine Vorkasse") are ignored: up to three words between the negation and the indicator."""
    loc = _loc(c)
    rx = c.get("fraud_regex") or loc.fraud
    negs = c.get("fraud_negations") or loc.negations
    conj = c.get("fraud_conjunctions") or loc.conjunctions
    # negation, then up to three words (no conjunction, no dash in between), then the indicator
    neg = re.compile(r"\b(" + negs + r")\b[\s-]+((?!(?:" + conj + r")\b)\w+\s+){0,3}?(?=\w*(" + rx + "))", re.I)
    text = f"{l.get('issues') or ''} {l.get('summary') or ''}"
    text = neg.sub(" NEGATED_", text)
    return bool(re.search(r"(?<!NEGATED_)(" + rx + ")", text, re.I))


def interp(x, pts):
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def _kind(l):
    return "flip" if str(l.get("deal_type") or "").lower() == "flip" else "repair"


def compute(l, c, caps=True):
    """caps=False: economics only, without the uncertainty caps (used for the price ceiling)."""
    loc = _loc(c)
    eur = loc.eur
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
    travel_h, how, pickup = 0.0, "", False
    if ship_ok:
        fee = max(c["buyer_protection_fee_min"], price * c["buyer_protection_fee_pct"])
        ship = max(ship, round(c["ship_in_cost"] + fee, 2))
        how = loc.t("score.how_shipping")
    elif dist is not None and (dist <= c["pickup_km"] or ship_ok is False):
        travel_h = 2 * dist / c["drive_kmh"]
        ship = max(ship, round(2 * dist * c["km_cost"]))
        how, pickup = loc.t("score.how_pickup", km=f"{dist:.0f}"), True
    elif l.get("shipping_unknown") and not ship:
        # the source states no shipping cost: assume the lump sum (also over an evaluator's 0)
        ship, how = float(c["unknown_cost"]), loc.t("ship.unknown", cost=f"{c['unknown_cost']:g}")
    capped = loc.t("score.bundle", n=l["bundle_qty"]) if l.get("bundle_qty") else ""
    extras = [x for x in (l.get("market_extras") or []) if isinstance(x, dict) and x.get("resale")]
    if est and resale > est * c["resale_cap"]:
        resale, capped = round(est * c["resale_cap"]), capped + loc.t("score.capped_market")
        if extras:   # the capped price comes from the market estimate, which includes the extras
            capped += loc.t("score.extras", items=", ".join(
                loc.t("score.extra_item", n=x.get("count", 1), group=x.get("group", "?"), eur=eur(x["resale"]))
                for x in extras))
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
    notes, cap_keys, cap_notes = [], [], {}
    dmg = [x for x in (l.get("visible_damage") or []) if str(x).strip() and not loc.no_damage.match(str(x).strip())] \
        if isinstance(l.get("visible_damage"), list) else []
    if dmg:
        pen = min(c["damage_penalty_max"], c["damage_penalty"] * len(dmg))
        s -= pen
        notes.append(loc.t("note.damage", n=len(dmg), pen=f"{pen:g}"))

    def cap(key, limit, note):
        nonlocal s
        if s > limit:
            s = limit
            notes.append(note)
            cap_keys.append(key)
            cap_notes[key] = note

    if caps and photo_worse:
        cap("photo_worse", c["max_score_photo_worse"], loc.t("note.photo_worse", m=c["max_score_photo_worse"]))
    if caps and photo_poor:
        cap("photo_poor", c["max_score_photo_poor"], loc.t("note.photo_poor", m=c["max_score_photo_poor"]))
    if profit < c["min_profit"].get(kind, 10):
        s = min(s, 3)
        notes.append(loc.t("note.min_profit", kind=loc.value(kind)))
        cap_keys.append("min_profit")
    if caps and risk.startswith("high"):
        cap("high_risk", c["max_score_high_risk"], loc.t("note.high_risk", m=c["max_score_high_risk"]))
    ai = num(l.get("score_ai"))
    if caps and ai is not None:
        cap("ai_gap", ai + c["max_gap_ai"], loc.t("note.ai_gap", m=c["max_gap_ai"]))
    if caps and fraud(l, c):
        cap("fraud", c["max_score_fraud"], loc.t("note.fraud"))
    if caps and not est:
        cap("no_market", c["max_score_no_market"], loc.t("note.no_market", m=c["max_score_no_market"]))
    if caps and str(l.get("status") or "").lower().startswith("reserv"):
        s = min(s, 3)
        notes.append(loc.t("note.reserved"))
        cap_keys.append("reserved")
    score = int(max(1, min(10, s)) + 0.5)
    text = (loc.t("score.text", resale=eur(resale), capped=capped, price=eur(price), parts=eur(parts),
                  logistics=loc.t("score.travel" if pickup else "score.shipping"), ship=eur(ship),
                  how=f" ({how})" if how else "", profit=eur(profit), hours=loc.num(round(hours, 2), 2).rstrip("0").rstrip(loc.decimal),
                  per_h=eur(per_h), risk=loc.value(risk) if risk else "?", p=f"{p * 100:.0f}", loss=eur(loss),
                  ev=eur(ev), ev_h=eur(ev / hours))
            + (loc.t("score.bonus", n=bonus) if bonus else "")
            + (loc.t("score.stock", n=f"{c['stock_bonus']:g}") if l.get("parts_in_stock") else "")
            + (" · " + ", ".join(notes) if notes else "") + f" → {score}")
    return {"notes": notes, "caps": cap_keys, "cap_notes": cap_notes, "score": score, "exact": round(max(1, min(10, s)), 2),
            "profit": round(profit), "per_hour": round(per_h, 1), "expected": round(ev), "text": text}


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


def negotiation_head(l, loc):
    d = l.get("days_online")
    parts = [loc.t("neg.online", d=d) if d is not None else loc.t("neg.unknown")]
    if l.get("price_drops"):
        parts.append(loc.t("neg.reduced", n=l["price_drops"]))
    if l.get("relisted"):
        parts.append(loc.t("neg.relisted"))
    return ", ".join(parts)


def negotiation(l, c):
    loc = _loc(c)
    price = num(l.get("price"))
    if price is None:
        return None
    offer = int(price * (1 - opening_discount(l.get("days_online"))) // 5 * 5)
    mx = max_price(l, c)
    head = negotiation_head(l, loc)
    t = c["target_score"]
    if fraud(l, c):
        return loc.t("neg.fraud", head=head)
    cur = compute(l, c)
    cap_keys = [k for k in (cur["caps"] if cur else []) if k not in ("min_profit", "reserved")]
    if mx is not None and mx >= price and cap_keys and cur["score"] < t:
        capped = [cur["cap_notes"][k] for k in cap_keys]
        todo = (loc.t("neg.todo_evaluator") if "ai_gap" in cap_keys
                else loc.t("neg.todo_photos") if {"photo_worse", "photo_poor"} & set(cap_keys)
                else loc.t("neg.todo_details"))
        return loc.t("neg.capped", head=head, mx=mx, caps="; ".join(capped), todo=todo, offer=min(offer, mx))
    if mx is None:
        return loc.t("neg.free", head=head, t=t)
    if mx >= price:
        return loc.t("neg.open", head=head, offer=offer, t=t, mx=mx)
    if mx >= price * 0.75:
        return loc.t("neg.at_most", head=head, mx=mx, t=t)
    return loc.t("neg.too_high", head=head, mx=mx)


def draft(l, c):
    """Message draft to the seller: the evaluator's questions plus an offer."""
    loc = _loc(c)
    price = num(l.get("price"))
    if price is None:
        return None
    mx = max_price(l, c)
    worth = (num(l.get("score")) or 0) >= c["draft_min_score"] or (mx is not None and mx >= price * 0.75)
    if not worth or mx is None:
        return None
    offer = int(min(price * (1 - opening_discount(l.get("days_online"))), mx) // 5 * 5)
    item = loc.t("draft.item")
    title = re.sub(r"\s*[|,(–-].*$", "", str(l.get("title") or item)).strip()[:60] or item
    qs = l.get("seller_questions") or []
    qs = [qs] if isinstance(qs, str) else [str(q).strip() for q in qs if str(q).strip()]
    pc = str(l.get("photo_check") or "").lower()
    if fraud(l, c):
        qs.insert(0, loc.t("draft.q_fraud"))
    elif "insufficient" in pc or "stock photo" in pc:
        qs.insert(0, loc.t("draft.q_photos"))
    out = [loc.t("draft.hi"), loc.t("draft.interest", title=title)]
    if qs:
        out.append(loc.t("draft.questions") + "\n" + "\n".join(f"- {q}" for q in qs[:4]))
    out.append(loc.t("draft.offer", offer=offer) if offer < price else loc.t("draft.room"))
    if l.get("shipping_possible"):
        out.append(loc.t("draft.ship"))
    elif fraud(l, c):
        out.append(loc.t("draft.pickup_test"))
    elif l.get("distance_km") is not None:
        out.append(loc.t("draft.pickup"))
    out.append(loc.t("draft.thanks"))
    return "\n\n".join(out)


def load_hooks(c):
    return [(spec, plugins.load(spec, "score hook")) for spec in c.get("hooks") or []]


def _tier(score):
    return "A" if score >= 7 else "B" if score >= 5 else "C"


def run_hooks(l, hooks, info, log=print):
    """Apply the score hooks to one listing; returns the notes they added."""
    added = []
    for spec, fn in hooks:
        try:
            r = fn(l, {**info, "caps": list(info["caps"]), "notes": list(info["notes"])})
        except Exception as e:   # a broken hook must not break the run
            log(f"  score hook {spec} failed for {l.get('id')}: {type(e).__name__}: {e}")
            continue
        if not r:
            continue
        if r.get("score") is not None and num(r["score"]) is not None:
            new = num(r["score"])
            info["exact"] = round(max(1, min(10, new)), 2)
            info["score"] = int(max(1, min(10, new)) + 0.5)
        if r.get("note"):
            added.append(str(r["note"]))
    return added


def apply(cfg, sc, state_path, show=False, log=print):
    """Rescore the whole state of a search. Returns (computed, changed)."""
    if not (sc.get("score") or {}).get("enabled"):
        return 0, 0
    c = settings(cfg, sc)
    loc = _loc(c)
    hooks = load_hooks(c)
    state = load_json(state_path, {"listings": []})
    n_calc = n_changed = 0
    for l in state.get("listings", []):
        if "score_ai" not in l:
            l["score_ai"] = l.get("score")
        r = compute(l, c)
        if r is None:
            # keep the evaluator's tier once, like score_ai: when a hook cap no longer applies on a
            # later run (e.g. a field was added), the evaluator's tier comes back, not the capped one
            if "tier_ai" not in l and l.get("tier"):
                l["tier_ai"] = l["tier"]
            l["score"] = l.get("score_ai")
            if l.get("tier_ai"):
                l["tier"] = l["tier_ai"]
            l["score_calc"] = loc.t("score.no_numbers")
            if hooks and num(l.get("score")) is not None:
                info = {"score": num(l["score"]), "exact": num(l["score"]), "computed": False, "caps": [],
                        "notes": [], "settings": c, "locale": loc}
                notes = run_hooks(l, hooks, info, log)
                if info["score"] != num(l["score"]) or notes:
                    l["score"], l["tier"] = info["score"], _tier(info["score"])
                    l["score_calc"] += "".join(f" · {n}" for n in notes)
            continue
        n_calc += 1
        info = {"score": r["score"], "exact": r["exact"], "computed": True, "caps": list(r["caps"]),
                "notes": list(r["notes"]), "settings": c, "locale": loc}
        notes = run_hooks(l, hooks, info, log) if hooks else []
        if info["score"] != num(l.get("score")):
            n_changed += 1
        l["score"] = info["score"]
        if "tier_ai" not in l:
            l["tier_ai"] = l.get("tier")
        l["tier"] = _tier(info["score"])
        l["score_exact"] = info["exact"]
        l["expected_profit_eur"] = r["profit"]
        l["profit_per_hour_eur"] = r["per_hour"]
        l["score_calc"] = r["text"] + "".join(f" · {n} → {info['score']}" for n in notes)
        neg = negotiation(l, c)
        if neg:
            l["negotiation"] = neg
        msg = draft(l, c)
        if msg:
            l["message_draft"] = msg
        else:
            l.pop("message_draft", None)
        if show:
            print(f"{info['score']:>2} (eval {l.get('score_ai')})  {str(l.get('title'))[:50]:50}  {l['score_calc']}")
    if not show:
        save_json(state_path, state)
    log(f"score {sc['_name']}: {n_calc} computed, {n_changed} changed, "
        f"{len(state.get('listings', [])) - n_calc} without numbers (evaluator score)")
    return n_calc, n_changed
