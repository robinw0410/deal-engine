"""The listing model: every adapter returns listings in the JSON format described in
docs/listing-format.md, and normalize() turns them into the internal item dict.

Internal keys starting with "_" are working data (full text for regex signals, publish date,
first image) and are never written into evaluation batches or the state file.

Fields that are not part of the format (e.g. "km", "year", "ps", "size") are kept as real fields
of the item if their name is lowercase letters/digits/underscores, not reserved, and the value is
a number, a string or a bool. They go into the evaluation batches, can be used by numeric filters
(filters.fields) and are carried into the state; their names are listed in "_extra".
"""
import re

from .util import num, road_km

REQUIRED = ("source_id", "url", "title")
STATUSES = ("active", "reserved")
FORMAT = {"source_id", "url", "title", "price", "location", "lat", "lon", "distance_km", "shipping_possible",
          "shipping_cost", "private", "condition", "for_parts", "auction", "auction_end", "best_offer", "status",
          "attrs", "description", "images", "published"}
# names an adapter must not use for extra fields (state, evaluation and computed fields)
RESERVED = {"id", "source", "sources", "urls", "price_history", "first_seen", "last_seen", "score", "score_ai",
            "score_exact", "score_calc", "tier", "tier_ai", "summary", "issues", "merge_into", "reject",
            "shipping_cost_eur", "shipping_unknown", "shipping_note", "days_online", "price_drops", "relisted",
            "sold_info", "negotiation", "message_draft", "bundle_qty", "last_check_failed",
            # evaluation fields the score formula reads
            "deal_type", "risk", "photo_check", "visible_damage", "market_price", "repair_parts_eur", "repair_hours",
            "expected_profit_eur", "profit_per_hour_eur", "missing_parts", "parts_in_stock", "seller_questions"}
EXTRA_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def _flag(v):
    if v is None or v == "":
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


def _date(v):
    s = str(v or "").strip()
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else None


def extra_fields(raw):
    out = {}
    for k, v in raw.items():
        if k in FORMAT or k in RESERVED or k.startswith("market_") or not EXTRA_NAME.match(str(k)):
            continue
        if isinstance(v, bool) or (isinstance(v, (int, float)) and v == v) or (isinstance(v, str) and len(v) < 300):
            out[k] = v
    return out


def normalize(raw, source, home=None, road_factor=1.3):
    """Validate one listing from an adapter and return the internal item. Raises ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("listing must be an object")
    missing = [k for k in REQUIRED if raw.get(k) in (None, "")]
    if missing:
        raise ValueError(f"listing without {', '.join(missing)}")
    url = str(raw["url"])
    if not re.match(r"https?://", url):
        raise ValueError(f"url must start with http(s):// ({url[:60]})")
    status = str(raw.get("status") or "active").lower()
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    dist = num(raw.get("distance_km"))
    if dist is None and home and raw.get("lat") is not None and raw.get("lon") is not None:
        dist = road_km(raw["lat"], raw["lon"], home, road_factor)
    title = str(raw["title"]).strip()
    desc = str(raw.get("description") or "")
    images = [str(u) for u in (raw.get("images") or []) if u]
    attrs = raw.get("attrs") if isinstance(raw.get("attrs"), dict) else {}
    extra = extra_fields(raw)
    return {
        **extra,
        "source": source,
        "source_id": str(raw["source_id"]),
        "url": url,
        "title": title,
        "price": num(raw.get("price")),
        "location": str(raw.get("location") or ""),
        "distance_km": dist,
        "shipping_possible": _flag(raw.get("shipping_possible")),
        "shipping_cost_eur": num(raw.get("shipping_cost")),
        "private": _flag(raw.get("private")),
        "condition": raw.get("condition"),
        "auction": bool(raw.get("auction")),
        "auction_end": raw.get("auction_end"),
        "best_offer": bool(raw.get("best_offer")),
        "status": status,
        "attrs": {str(k): v for k, v in attrs.items() if len(str(v)) < 300},
        "description": desc[:1800] or None,
        "_extra": sorted(extra),
        "_for_parts": bool(_flag(raw.get("for_parts"))),
        "_text": f"{title} {desc}"[:2000],
        "_body": desc[:2000],
        "_published": _date(raw.get("published")),
        "_image": images[0] if images else None,
        "_img_urls": images,
    }


def shipping_unknown(it):
    """The item has to be shipped, but the cost is not known: no cost stated, no platform shipping
    model (shipping_possible) and no pickup distance. Such a cost is never treated as 0;
    a stated cost of 0 means free shipping."""
    return it.get("shipping_cost_eur") is None and it.get("shipping_possible") is None \
        and it.get("distance_km") is None
