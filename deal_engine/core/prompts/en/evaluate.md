---

## Task for this run: EVALUATE ONLY (takes precedence over everything above)

A script has already searched the sources. You have no browser. From the search profile above,
use only the criteria, device groups, tiers, evaluation rules and the fields.

1. Read `{{CANDIDATES}}`. It contains `candidates` (new listings with title, price, location,
   attributes, description `description` and local image paths `images`) and `existing_listings`
   (the current state as table rows "id | title | price | location", only to detect duplicates).
2. Evaluate every candidate in two stages:
   a) First check ONLY title, price, attributes and description. If it violates hard criteria or
      would score below 6 on text and data alone: discard it WITHOUT opening the images.
   b) Only for the rest, look at the images under `images` with the Read tool (photo check as
      described above), then decide.
   `market_median` (if present) is the median asking price of working units of this group,
   computed by the script (`market_n` = number of listings). These are ASKING prices, not sale
   prices. Use `market_resale_estimate` as the base for the resale price and adjust it only for
   condition, storage or accessories. If `market_extras` is present, the listed extras (n ×
   `resale`, e.g. extra controllers) are already included in `market_resale_estimate`: do not add
   them again. Without market data: estimate the resale price
   conservatively (lower third of the offers) and note "resale price estimated" in `issues`.
   `distance_km` is the estimated road distance from home, `shipping_possible` whether the
   platform offers shipping with buyer protection, `shipping_cost_eur` the shipping cost if the
   source states it, `private` whether the seller is private. `shipping_unknown: true` means the
   source states no shipping cost: do not assume free shipping; leave `shipping_cost_eur` out
   unless you have a realistic estimate (the script then assumes the lump sum in `shipping_note`).
   Discard if hard criteria are violated, if it is an accessory instead of a device, or if the deal
   does not pay off according to the rules. {{WANTED_ADS}}
3. Write `{{ACCEPTED}}` as a JSON list of ONLY the accepted listings (empty list `[]` if none
   fits). Every object contains `source_id` (from the candidate) plus all evaluation fields from
   the rules above (`tier`, `score`, `summary` and the search-specific fields). `id`, `urls`,
   `price`, `first_seen`, `last_seen` are set by the script.
   If a candidate is the same item as an entry in `existing_listings` (other source), write only
   `{"source_id": "...", "merge_into": "<id of the existing entry>"}`.
4. Do not write any other files. Today is {{DATE}}.

Thorough rather than fast: every candidate is checked individually, none is skipped.
