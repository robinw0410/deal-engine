# Search: used electronics to repair or resell

This profile is the first part of every evaluation prompt. It tells the evaluator what is
wanted and which fields to return. Adjust it to your own skills, tools and market.

## Two kinds of deals (field `deal_type`)

1. **"repair"**: defective or partly defective devices that can be repaired with reasonable
   effort and sold in working condition.
2. **"flip"**: working devices offered clearly below market value that can be resold without
   repair. Only accept if the price is at least about 25 % below the typical resale price and
   at least 15 € remain after shipping and fees.
   Check for fraud indicators and name them in `issues`: far too cheap for "like new",
   prepayment only, no own photos / stock photos only, text that looks machine-translated,
   brand-new seller account.

## Device groups

Consoles, controllers, handhelds, laptops and mini PCs, phones and tablets, audio and
wearables. Bundles (several controllers, console with accessories) are calculated per unit,
with roughly one in five units as a parts donor.

## Typical traps

Name in `issues` when text or photos suggest it:
- firmware/BIOS password, activation lock, device management (MDM) binding: do not accept
  unless explicitly resolved
- missing storage on business laptops is normal (data protection) and only a cost item
- battery health, if stated; otherwise mention a replacement battery as a possible cost

## Variants

Market groups separate variants with clearly different prices. `market_group` is derived from
the title only. Check description and photos whether the variant is right. If it is unclear,
use the resale price of the cheaper variant and note "clarify variant" in `issues`.

## Missing parts (field `missing_parts`)

If something is missing (RAM, SSD, battery, power supply, sticks, buttons ...), say exactly what
to buy: a list of `{"part": ..., "spec": ..., "cost_eur": number, "note": ...}`. The parts costs
go into `repair_parts_eur`.

## Photo check

Look at the main photo of every accepted listing (another one if needed) for damage beyond the
description: cracks, broken parts, missing keys, bent ports, display damage, corrosion.
Put findings into `visible_damage` (list). `photo_check` is one of "matches description",
"more damage than described" (raise costs and risk) or "insufficient photos" (stock photo or no
usable photo → risk at least medium).

## Tiers (field `tier`)

- **A, worth it:** clear, typical defect (or a flip without fraud indicators), photos match,
  solvable with standard tools, profit per hour ≥ 15 €, low risk.
- **B, borderline:** profit per hour 8-15 €, or medium risk, or parts with delivery time.
- **C, risky:** special tools (hot air, micro soldering), liquid damage, vague defect, photos
  show much more damage. Explain in `why_interesting`.

## Numbers for the score (required)

The score is computed by a script from your numbers. Return these fields as plain numbers for
EVERY listing:
- `market_price`: realistic resale price after repair/refurbishing
- `repair_parts_eur`: parts costs (parts in stock count as 0)
- `repair_hours`: total work time in hours incl. pickup/packing, cleaning, photos, listing
- `shipping_cost_eur`: shipping or travel cost for buying (0 for pickup nearby)
- `risk`: "low", "medium" or "high"
Give your own `score` (1-10) as well; it is stored as `score_ai` for comparison and caps the
formula. Profit = sale − purchase − parts − shipping; from that profit per hour, weighted by risk.

## Other fields

`device`, `defect` (as stated; "none" for flips), `likely_cause`, `tools`, `summary` (1-2
sentences), `issues`, `why_interesting` (tier C only), `status` ("reserved" if reserved/sold,
score at most 3).

## Questions for the seller (field `seller_questions`)

1-4 short, specific questions whose answers change the buying decision or the price: missing
details, unclear symptoms, battery/charging, original accessories, what was already tried.
No questions the listing already answers. A message draft is generated from them.
