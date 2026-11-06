"""Wish list: products someone is looking for, entered on the deal server (/deals/wishes/).

Stored in the deal server's SQLite database (state/deals.db in the data directory, table `wish`),
never in the configuration file. A host application (e.g. a runner) reads the active wishes with
`active(cfg)` and turns them into a search at run time.

A wish:  id (int), name (str), terms (list of 1-5 plain-text search terms), max_price (float, EUR
incl. shipping), platforms (subset of PLATFORMS), active (bool), note (str, "what to look out for"),
created / updated (ISO timestamps).

Limits are enforced here, server side: at most MAX_ACTIVE active wishes, MAX_TERMS terms per wish,
plain text only (no regex syntax is interpreted anywhere; terms are passed to the platforms as
keywords), bounded lengths.
"""
import json
import re
import sqlite3
import time

MAX_ACTIVE = 10
MAX_TERMS = 5
MAX_NAME = 80
MAX_TERM = 60
MAX_NOTE = 500
MAX_PRICE = 100000.0
PLATFORMS = ("willhaben", "ebay")

SCHEMA = """
CREATE TABLE IF NOT EXISTS wish(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  terms TEXT NOT NULL,            -- JSON list of strings
  max_price REAL NOT NULL,
  platforms TEXT NOT NULL,        -- JSON list of strings
  active INTEGER NOT NULL DEFAULT 1,
  note TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL,
  updated TEXT NOT NULL
);
"""

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _text(v, field, max_len, required=True):
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ValueError(f"{field}: text expected")
    v = re.sub(r"\s+", " ", _CTRL.sub(" ", v)).strip()
    if required and not v:
        raise ValueError(f"{field}: required")
    if len(v) > max_len:
        raise ValueError(f"{field}: at most {max_len} characters")
    return v


def platforms(cfg=None):
    """Allowed platforms: cfg wishes.platforms (subset of the configured adapters) or PLATFORMS."""
    p = ((cfg or {}).get("wishes") or {}).get("platforms")
    return tuple(str(x) for x in p) if isinstance(p, list) and p else PLATFORMS


def validate(body, cfg=None):
    """Clean and check a wish from user input (dict). Returns the cleaned dict without id/timestamps.
    Raises ValueError with a message for the user."""
    if not isinstance(body, dict):
        raise ValueError("object expected")
    name = _text(body.get("name"), "name", MAX_NAME)
    raw = body.get("terms")
    if isinstance(raw, str):
        raw = raw.replace(";", "\n").replace(",", "\n").splitlines()
    if not isinstance(raw, list):
        raise ValueError("terms: list expected")
    terms, seen = [], set()
    for t in raw:
        t = _text(t, "term", MAX_TERM, required=False)
        if t and t.casefold() not in seen:
            seen.add(t.casefold())
            terms.append(t)
    if not terms:
        raise ValueError("terms: at least one search term")
    if len(terms) > MAX_TERMS:
        raise ValueError(f"terms: at most {MAX_TERMS}")
    try:
        price = float(str(body.get("max_price", "")).replace(",", ".").replace("€", "").strip())
    except ValueError:
        raise ValueError("max_price: number expected") from None
    if price != price or not 0 < price <= MAX_PRICE:   # NaN, <= 0, too large
        raise ValueError(f"max_price: between 0 and {MAX_PRICE:.0f}")
    allowed = platforms(cfg)
    plats = body.get("platforms")
    if isinstance(plats, str):
        plats = [plats]
    if not isinstance(plats, list) or not plats or not all(isinstance(x, str) for x in plats):
        raise ValueError(f"platforms: at least one of {', '.join(allowed)}")
    unknown = [x for x in plats if x not in allowed]
    if unknown:
        raise ValueError(f"platforms: only {', '.join(allowed)}")
    plats = [x for x in allowed if x in plats]   # fixed order, no duplicates
    active = body.get("active", True)
    if isinstance(active, str):
        active = active.strip().lower() in ("1", "true", "on", "yes", "ja")
    note = _text(body.get("note"), "note", MAX_NOTE, required=False)
    return {"name": name, "terms": terms, "max_price": round(price, 2), "platforms": plats,
            "active": bool(active), "note": note}


def init(con):
    con.executescript(SCHEMA)


def _row(r):
    return {"id": r["id"], "name": r["name"], "terms": json.loads(r["terms"]), "max_price": r["max_price"],
            "platforms": json.loads(r["platforms"]), "active": bool(r["active"]), "note": r["note"],
            "created": r["created"], "updated": r["updated"]}


def rows(con, active_only=False, create=True):
    if create:
        init(con)
    q = "SELECT * FROM wish" + (" WHERE active=1" if active_only else "") + " ORDER BY id"
    return [_row(r) for r in con.execute(q)]


def _check_active(con, exclude_id=None):
    n = con.execute("SELECT COUNT(*) FROM wish WHERE active=1 AND id IS NOT ?", (exclude_id,)).fetchone()[0]
    if n >= MAX_ACTIVE:
        raise ValueError(f"at most {MAX_ACTIVE} active wishes; deactivate one first")


def create(con, body, cfg=None):
    init(con)
    w = validate(body, cfg)
    if w["active"]:
        _check_active(con)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    cur = con.execute("INSERT INTO wish(name, terms, max_price, platforms, active, note, created, updated) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      (w["name"], json.dumps(w["terms"], ensure_ascii=False), w["max_price"],
                       json.dumps(w["platforms"]), int(w["active"]), w["note"], now, now))
    return cur.lastrowid


def update(con, wish_id, body, cfg=None):
    init(con)
    row = con.execute("SELECT * FROM wish WHERE id=?", (int(wish_id),)).fetchone()
    if not row:
        raise KeyError(wish_id)
    w = validate(dict(_row(row), **body), cfg)
    if w["active"] and not row["active"]:
        _check_active(con, int(wish_id))
    con.execute("UPDATE wish SET name=?, terms=?, max_price=?, platforms=?, active=?, note=?, updated=? WHERE id=?",
                (w["name"], json.dumps(w["terms"], ensure_ascii=False), w["max_price"], json.dumps(w["platforms"]),
                 int(w["active"]), w["note"], time.strftime("%Y-%m-%dT%H:%M:%S"), int(wish_id)))


def delete(con, wish_id):
    init(con)
    if con.execute("DELETE FROM wish WHERE id=?", (int(wish_id),)).rowcount == 0:
        raise KeyError(wish_id)


def active(cfg):
    """Active wishes for a host application (read only). [] if the database does not exist yet."""
    from .deals_server import db_path
    p = db_path(cfg)
    if not p.exists():
        return []
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        try:
            return rows(con, active_only=True, create=False)[:MAX_ACTIVE]
        except sqlite3.OperationalError:   # read-only connection, table not created yet
            return []
    finally:
        con.close()
