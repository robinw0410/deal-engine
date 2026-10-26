"""Hard filters for listings (the "filters" block of a search) and the defect signal."""
import re
from datetime import timedelta

from . import clock


def passes(it, flt):
    """True if the listing passes all hard filters. Missing values never fail a filter."""
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
    return True


def has_signal(it, flt):
    """Defect/repair signal in title or description ("broken", "for parts" ...), or the platform
    itself marks the item as for parts. None if the search defines no signal regex."""
    t_rx, b_rx = flt.get("signal_regex"), flt.get("body_signal_regex")
    if not t_rx:
        return None
    return bool(it.get("_for_parts") or re.search(t_rx, it.get("title") or "", re.I)
                or (b_rx and re.search(b_rx, it.get("_body") or "", re.I)))
