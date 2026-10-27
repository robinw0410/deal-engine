"""Hard filters for listings (the "filters" block of a search) and the defect signal.

Numeric filters on any field (listing fields, extra fields such as km/ps/year, or attrs):

  filters:
    fields:
      km: {max: 60000}
      kw: {min: 66}
      year: {min: 2010, missing: fail}   # without a value the listing fails (default: passes)

Filter hooks (filters.hooks: ["module:function", ...]) are hard filters in code, for rules a regex cannot
express. Each is called with the normalized listing before the candidate selection and returns None/False
(passes) or a reason (fails), e.g. a clothing size read from the title. They do not run on the state, but on the
listings of the history tracking of searches without market groups (history.track uses passes()).
A hook that raises lets the listing pass; select() logs how often.
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


def title_failed(title, flt):
    """"exclude" or "include" if the title fails that title regex of the filters, otherwise None.
    Both are searched case-insensitively anywhere in the full title (re.search): a pattern without
    word boundaries also hits inside words ("such" in "Suchmaschine")."""
    title = title or ""
    flt = flt or {}
    if flt.get("exclude_title_regex") and re.search(flt["exclude_title_regex"], title, re.I):
        return "exclude"
    if flt.get("include_title_regex") and not re.search(flt["include_title_regex"], title, re.I):
        return "include"
    return None


_HOOKS = {}


def load_hooks(flt):
    """[(spec, function)] of filters.hooks; ConfigError if one cannot be loaded."""
    from . import plugins
    specs = (flt or {}).get("hooks") or []
    if isinstance(specs, str) or not isinstance(specs, (list, tuple)):
        from .config import ConfigError
        raise ConfigError(f"filters.hooks must be a list of 'module:function', not {specs!r}")
    key = tuple(map(str, specs))
    if key not in _HOOKS:
        hooks = [(spec, plugins.load(spec, "filter hook")) for spec in key]
        for spec, fn in hooks:
            if not callable(fn):
                from .config import ConfigError
                raise ConfigError(f"filter hook '{spec}' is not callable")
        _HOOKS[key] = hooks
    return _HOOKS[key]


# {spec: [count, last error]} of hooks that raised; select() logs and clears it. A broken hook must not
# break a run (like score hooks): the listing passes that hook.
HOOK_ERRORS = {}


def hook_failed(it, flt):
    """"<spec>: <reason>" of the first filter hook that rejects the listing, otherwise None."""
    for spec, fn in load_hooks(flt):
        try:
            r = fn(it)
        except Exception as e:
            err = HOOK_ERRORS.setdefault(spec, [0, ""])
            err[0] += 1
            err[1] = f"{type(e).__name__}: {e}"
            continue
        if r:
            return spec if r is True else f"{spec}: {r}"
    return None


def passes(it, flt):
    """True if the listing passes all hard filters. Missing values never fail a filter
    (except numeric field filters with missing: fail)."""
    if flt.get("max_age_days") and it.get("_published"):
        if it["_published"] < str(clock.today() - timedelta(days=int(flt["max_age_days"]))):
            return False
    if title_failed(it.get("title"), flt):
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
    if fields_failed(it, flt) is not None:
        return False
    return hook_failed(it, flt) is None   # last: code, may be slower than the rules above


def has_signal(it, flt):
    """Defect/repair signal in title or description ("broken", "for parts" ...), or the platform
    itself marks the item as for parts. None if the search defines no signal regex."""
    t_rx, b_rx = flt.get("signal_regex"), flt.get("body_signal_regex")
    if not t_rx:
        return None
    return bool(it.get("_for_parts") or re.search(t_rx, it.get("title") or "", re.I)
                or (b_rx and re.search(b_rx, it.get("_body") or "", re.I)))
