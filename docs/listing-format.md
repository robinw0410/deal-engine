# Listing format

Every adapter returns listings as JSON objects in this format. The `json_file` adapter reads a
file that is either a list of such objects or `{"listings": [...]}`. Check a file with

```sh
python -m deal_engine validate listings.json
```

## Example

```json
{
  "source_id": "100042",
  "url": "https://example.invalid/listing/100042",
  "title": "Switch Lite – stick drift",
  "price": 55,
  "location": "Northfield",
  "lat": 52.61,
  "lon": 13.28,
  "shipping_possible": true,
  "shipping_cost": null,
  "private": true,
  "published": "2026-10-20",
  "condition": "for parts",
  "for_parts": false,
  "description": "Left stick drifts, otherwise fine. Pickup or shipping.",
  "images": ["https://example.invalid/img/100042-1.jpg"],
  "attrs": {"colour": "turquoise"},
  "status": "active"
}
```

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `source_id` | string | yes | ID of the listing at its source, unique per adapter. Stored ids are `<adapter>-<source_id>`. |
| `url` | string | yes | Link to the listing, `http://` or `https://`. |
| `title` | string | yes | Listing title. Group matching, filters and signals work on it. |
| `price` | number or string | no | Asking price. Strings like `"1.234,50"` or `"€ 80"` are parsed. `null` = unknown. |
| `location` | string | no | Free text shown on the page. |
| `lat`, `lon` | number | no | Item location. With `location.lat/lon` in the config, the road distance is estimated as straight-line km × `road_factor`. |
| `distance_km` | number | no | Use this instead of `lat`/`lon` if the source provides a distance. |
| `shipping_possible` | bool | no | The platform offers shipping with buyer protection. `false` = pickup only. `null` = unknown. |
| `shipping_cost` | number | no | Shipping cost to you, if the source states it. `0` = free shipping. Missing/`null` = unknown: if neither `shipping_possible` nor a distance is known either, the item is marked `shipping_unknown` and `shipping.unknown_cost` (default 15 €) is assumed for candidate selection and score. |
| `private` | bool | no | Private seller (`true`) or business (`false`). Market estimates prefer private offers. |
| `published` | `YYYY-MM-DD` | no | Publication date. Used for `max_age_days`, "fresh" market prices and time online. |
| `condition` | string | no | Condition as stated by the source. |
| `for_parts` | bool | no | The source itself marks the item as for parts / not working (counts as defect signal). |
| `description` | string | no | Full text, cut to 1,800 characters. `body_signal_regex` runs on it. |
| `images` | list of URLs | no | Photos. Up to `images` per search are downloaded for the evaluator (http/https, max 8 MB each). |
| `attrs` | object | no | Additional attributes (values longer than 300 characters are dropped). |
| `auction`, `auction_end`, `best_offer` | bool / string / bool | no | Auction information. |
| `status` | `"active"` or `"reserved"` | no | Default `"active"`. A listing that is no longer returned at all is checked with the adapter's `check()`, which returns `(status, price)`. |

## Extra fields

Any other field whose name consists of lowercase letters, digits and underscores (e.g. `km`,
`year`, `ps`, `size`) and whose value is a number, a string (under 300 characters) or a bool is kept
as a real field: it appears in the evaluation batches, numeric filters can use it
(`filters.fields: {km: {max: 60000}}`) and it is carried into the state entry. Fields named like something deal-engine uses itself are ignored: state and computed fields (`id`,
`score`, `tier`, `summary`, `market_*`, `shipping_cost_eur`, …) and the evaluation fields the score
formula reads (`risk`, `deal_type`, `repair_hours`, `market_price`, …; see `RESERVED` in
`deal_engine/core/listing.py`). Fields with other names or value types (lists, objects) are ignored too.

```json
{"source_id": "77", "url": "https://example.invalid/77", "title": "Touring bike", "price": 4200,
 "km": 38000, "year": 2013, "ps": 120}
```

Do not put personal data of sellers (names, user ids, phone numbers, ratings) into this format -
deal-engine does not need it and does not store it.

## State entries

After evaluation, accepted listings are stored in `data/state/<search>.json` with `id`
(`<adapter>-<source_id>`), `sources` (`{adapter: source_id}`), `urls`, `price`, `price_history`,
`first_seen`, `last_seen`, the evaluation fields (see `profiles/electronics.md`) and the fields
computed by `insights.py` and `score.py`.
