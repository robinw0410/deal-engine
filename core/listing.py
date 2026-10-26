"""The listing model: every adapter returns listings in the JSON format described in
docs/listing-format.md, and normalize() turns them into the internal item dict.

Internal keys starting with "_" are working data (full text for regex signals, publish date,
first image) and are never written into evaluation batches or the state file.
"""
import re

from .util import num, road_km

REQUIRED = ("source_id", "url", "title")
STATUSES = ("active", "reserved")


def _flag(v):
    if v is None or v == "":
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


def _date(v):
    s = str(v or "").strip()
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else None


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
    return {
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
        "_for_parts": bool(_flag(raw.get("for_parts"))),
        "_text": f"{title} {desc}"[:2000],
        "_body": desc[:2000],
        "_published": _date(raw.get("published")),
        "_image": images[0] if images else None,
        "_img_urls": images,
    }
