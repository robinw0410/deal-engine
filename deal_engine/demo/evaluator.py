"""Rule-based stand-in for the LLM evaluator, for demo data only.

It reads the hidden ground truth of the demo generator (demo-truth.json) and writes
accepted-N.json files in the same format an LLM evaluation would. It is not an AI and cannot
evaluate real listings; it exists so that the whole pipeline can run without an API key.
"""
import random

from ..core import locale as locale_mod
from ..core.util import load_json, save_json

# texts of the demo evaluation per locale (machine values such as deal_type/risk stay English)
TEXTS = {
    "en": {"damage": "scratches on the housing",
           "fraud": "Suspiciously cheap for 'brand new', seller wants prepayment by bank transfer.",
           "clean": "No signs of fraud.", "unclear": " Exact cause unclear.",
           "cause": "typical for this device: {d}", "repair": "Repair", "flip": "Flip",
           "summary": "{kind} candidate: about {profit} € before shipping for {hours} h of work (demo evaluation).",
           "q_repair": ["What exactly happens when you switch it on?", "Has it been opened before?"],
           "q_flip": ["Are all accessories included?"]},
    "de": {"damage": "Kratzer am Gehäuse",
           "fraud": "Verdächtig billig für 'neuwertig', Verkäufer will Vorkasse per Überweisung.",
           "clean": "Keine Auffälligkeiten.", "unclear": " Genaue Ursache unklar.",
           "cause": "typisch für dieses Gerät: {d}", "repair": "Reparatur", "flip": "Flip",
           "summary": "{kind}-Kandidat: etwa {profit} € vor Versand für {hours} Std. Arbeit (Demo-Bewertung).",
           "q_repair": ["Was passiert genau beim Einschalten?", "Wurde es schon einmal geöffnet?"],
           "q_flip": ["Ist das ganze Zubehör dabei?"]},
}

PHOTO = [("matches description", 0.75), ("insufficient photos", 0.15),
         ("more damage than described", 0.10)]


def _pick(rng, options):
    x, acc = rng.random(), 0
    for v, p in options:
        acc += p
        if x < acc:
            return v
    return options[-1][0]


def evaluate(work, cfg, sc):
    truth = load_json(cfg["_data"] / "demo-truth.json", {})
    T = TEXTS.get(locale_mod.for_search(cfg, sc).code, TEXTS["en"])
    for cf in sorted(work.glob("candidates-*.json")):
        acc = []
        for c in load_json(cf, {}).get("candidates", []):
            t = truth.get(c["source_id"])
            if not t or t["kind"] == "accessory":
                continue
            rng = random.Random(c["source_id"])
            repair = bool(t["defect"])
            resale = c.get("market_resale_estimate") or round(t["typical"] * 0.85)
            if t.get("qty"):
                resale = round(resale * t["qty"] * 0.9)
            resale = round(resale * rng.uniform(0.93, 1.05))
            parts = t["parts"] if repair else 0
            hours = t["hours"] if repair else 0.75
            price = c.get("price") or 0
            profit = resale - price - parts
            if profit < 12:
                continue
            photo = _pick(rng, PHOTO)
            damage = [T["damage"]] if photo.startswith("more") else []
            if t["fraud"]:
                issues = T["fraud"]
            else:
                issues = T["clean"] + (T["unclear"] if repair else "")
            ai = max(1, min(10, round(2 + profit / max(hours, 0.5) / 6)))
            item = {
                "source_id": c["source_id"],
                "device": t["group"],
                "deal_type": "repair" if repair else "flip",
                "defect": t["defect"] or "none",
                "likely_cause": (T["cause"].format(d=t["defect"]) if repair else None),
                "market_price": resale,
                "repair_parts_eur": parts,
                "repair_hours": hours,
                "risk": t["risk"] if repair else ("high" if t["fraud"] else "low"),
                "photo_check": photo,
                "visible_damage": damage,
                "issues": issues,
                "summary": T["summary"].format(kind=T["repair" if repair else "flip"], profit=f"{profit:.0f}",
                                               hours=f"{hours:g}"),
                "seller_questions": T["q_repair"] if repair else T["q_flip"],
                "score": ai,
                "tier": "A" if ai >= 7 else "B" if ai >= 5 else "C",
            }
            if repair and "RAM" in (t["defect"] or ""):
                item["missing_parts"] = [{"part": "RAM", "spec": "DDR4 SO-DIMM 2x8 GB", "cost_eur": 30},
                                         {"part": "SSD", "spec": "M.2 NVMe 256 GB", "cost_eur": 20}]
            acc.append({k: v for k, v in item.items() if v is not None})
        save_json(cf.with_name(cf.name.replace("candidates-", "accepted-")), acc)
