"""Small helpers shared by all modules: JSON files, number parsing, statistics, distances."""
import json
import re
from math import asin, cos, radians, sin, sqrt
from pathlib import Path


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(p, data, compact=False):
    """Atomic write (temp file + rename), so a crash never leaves half a state file."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) if compact
                   else json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(p)


def num(v):
    """Parse prices like 1234, "1.234,50", "1,234.50", "€ 80" or "-12" into a float (None if impossible)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    neg = s.startswith("-")
    s = s.replace("-", "")
    if not s or s in ".,":
        return None
    if "," in s and "." in s:
        # the separator that comes last is the decimal separator
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
        s = s.replace(".", "")   # "1.234" is a thousands separator, not 1.234
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        return None


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)


def haversine_km(a, b):
    (lat1, lon1), (lat2, lon2) = a, b
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def road_km(lat, lon, home, factor=1.3):
    """Straight-line distance from home times a factor, as a rough road distance."""
    try:
        return round(haversine_km(home, (float(lat), float(lon))) * factor)
    except (TypeError, ValueError):
        return None


def eur(v, digits=0):
    n = num(v)
    return f"{n:,.{digits}f} €" if n is not None else "?"
