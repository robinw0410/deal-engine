"""Hard filters for listings (the "filters" block of a search) and the defect signal.

Numeric filters on any field (listing fields, extra fields such as km/ps/year, or attrs):

  filters:
    fields:
      km: {max: 60000}
      kw: {min: 66}
      year: {min: 2010, missing: fail}   # without a value the listing fails (default: passes)
"""
import re
from datetime import timedelta

from . import clock
from .util import num


def field_value(it, field):
    v = it.get(field)
    if v is None:
        v = (it.get("attrs") or {}).get(field)
    return num(v)


def fields_failed(it, flt):
    """Name of the first numeric field filter the listing fails, or None."""
    for field, rule in ((flt or {}).get("fields") or {}).items():
        rule = rule or {}
        v = field_value(it, field)
        if v is None:
            if str(rule.get("missing", "pass")) == "fail":
                return field
            continue
        if rule.get("min") is not None and v < float(rule["min"]):
            return field
        if rule.get("max") is not None and v > float(rule["max"]):
            return field
    return None


def passes(it, flt):
    """True if the listing passes all hard filters. Missing values never fail a filter
    (except numeric field filters with missing: fail)."""
    title = it.get("title") or ""
    if flt.get("max_age_days") and it.get("_published"):
        if it["_published"] < str(clock.today() - timedelta(days=int(flt["max_age_days"]))):
            return False
    if flt.get("exclude_title_regex") and re.search(flt["exclude_title_regex"], title, re.I):
        return False
    if flt.get("include_title_regex") and not re.search(flt["include_title_regex"], title, re.I):
        return False
    p = it.get("price")
    if p is not None:
        if flt.get("max_price") is not None and p > flt["max_price"]:
            return False
        if flt.get("min_price") is not None and p < flt["min_price"]:
            return False
    # pickup only and too far away
    if flt.get("max_pickup_km") is not None and it.get("shipping_possible") is False \
            and (it.get("distance_km") or 0) > flt["max_pickup_km"]:
        return False
    return fields_failed(it, flt) is None


def has_signal(it, flt):
    """Defect/repair signal in title or description ("broken", "for parts" ...), or the platform
    itself marks the item as for parts. None if the search defines no signal regex."""
    t_rx, b_rx = flt.get("signal_regex"), flt.get("body_signal_regex")
    if not t_rx:
        return None
    return bool(it.get("_for_parts") or re.search(t_rx, it.get("title") or "", re.I)
                or (b_rx and re.search(b_rx, it.get("_body") or "", re.I)))
