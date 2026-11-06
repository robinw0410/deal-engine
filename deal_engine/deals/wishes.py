"""Wish list: products someone is looking for, entered on the deal server (/deals/wishes/).

Stored in the deal server's SQLite database (state/deals.db in the data directory, table `wish`),
never in the configuration file. A host application (e.g. a runner) reads the active wishes with
`active(cfg)` and turns them into a search at run time.

A wish:  id (int), name (str), terms (list of 0-5 plain-text search terms), max_price (float, EUR
incl. shipping), platforms (subset of PLATFORMS), active (bool), note (str, "what to look out for"),
created / updated (ISO timestamps), terms_source ("user" | "ai"), terms_updated (ISO timestamp of the
last change of the terms or None), terms_regen (bool: new suggestions requested).

Terms are optional. A wish without terms, or with terms_regen set, needs suggestions: the deal server
never calls a model itself; a host application (runner) generates them and stores them with
`set_ai_terms`, which never overwrites terms the user entered (terms_source "user") unless the user
asked for new suggestions (`request_regen`, the "suggest again" button).

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
  updated TEXT NOT NULL,
  terms_source TEXT NOT NULL DEFAULT 'user',
  terms_updated TEXT,
  terms_regen INTEGER NOT NULL DEFAULT 0
);
"""
# columns added after 0.2.13 (ALTER TABLE for existing databases)
COLUMNS = {"terms_source": "TEXT NOT NULL DEFAULT 'user'", "terms_updated": "TEXT",
           "terms_regen": "INTEGER NOT NULL DEFAULT 0"}
# characters with a meaning in regular expressions or search syntax: not allowed in suggested terms
_SYNTAX = re.compile(r"[\\^$*+?()\[\]{}|<>`]")

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
    if len(terms) > MAX_TERMS:
        raise ValueError(f"terms: at most {MAX_TERMS}")
    try:
        price = float(str(body.get("max_price", "")).replace(",", ".").replace("€", "").strip())
    except ValueError:
        raise ValueError("max_price: number expected") from None
    price = round(price, 2) if price == price else price   # round first, then check (0.001 -> 0)
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
    have = {r[1] for r in con.execute("PRAGMA table_info(wish)")}
    for col, decl in COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE wish ADD COLUMN {col} {decl}")


def _row(r):
    keys = r.keys()
    return {"id": r["id"], "name": r["name"], "terms": json.loads(r["terms"]), "max_price": r["max_price"],
            "platforms": json.loads(r["platforms"]), "active": bool(r["active"]), "note": r["note"],
            "created": r["created"], "updated": r["updated"],
            "terms_source": r["terms_source"] if "terms_source" in keys else "user",
            "terms_updated": r["terms_updated"] if "terms_updated" in keys else None,
            "terms_regen": bool(r["terms_regen"]) if "terms_regen" in keys else False}


def needs_terms(w):
    """True for an active wish that needs suggested terms (none yet, or new ones requested)."""
    return bool(w.get("active")) and (not w.get("terms") or bool(w.get("terms_regen")))


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
    cur = con.execute("INSERT INTO wish(name, terms, max_price, platforms, active, note, created, updated, "
                      "terms_source, terms_updated, terms_regen) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                      (w["name"], json.dumps(w["terms"], ensure_ascii=False), w["max_price"],
                       json.dumps(w["platforms"]), int(w["active"]), w["note"], now, now,
                       "user" if w["terms"] else "ai", now if w["terms"] else None))
    return cur.lastrowid


def update(con, wish_id, body, cfg=None):
    """Change a wish. body may carry "terms_seen": the terms_updated the edit form was rendered with.
    If suggested terms arrived after that (terms_source "ai", terms_updated differs) and the form sends
    no terms, the suggestions are kept instead of being cleared by the stale form."""
    init(con)
    # take the write lock before reading, so set_ai_terms cannot slip in between read and write
    con.execute("UPDATE wish SET id=id WHERE id=?", (int(wish_id),))
    row = con.execute("SELECT * FROM wish WHERE id=?", (int(wish_id),)).fetchone()
    if not row:
        raise KeyError(wish_id)
    if not isinstance(body, dict):
        raise ValueError("object expected")
    old = _row(row)
    body = dict(body)
    seen = body.pop("terms_seen", None)
    if (seen is not None and old["terms_source"] == "ai" and old["terms"] and str(seen) != (old["terms_updated"] or "")
            and not [t for t in (body.get("terms") or []) if str(t).strip()]
            and not (isinstance(body.get("terms"), str) and body["terms"].strip())):
        body["terms"] = old["terms"]   # stale form: suggestions arrived after it was opened
    w = validate(dict(old, **body), cfg)
    if w["active"] and not row["active"]:
        _check_active(con, int(wish_id))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    source, tupd, regen = old["terms_source"], old["terms_updated"], old["terms_regen"]
    if w["terms"] != old["terms"]:   # the user changed the terms: theirs from now on (empty = suggest)
        source, tupd, regen = ("user" if w["terms"] else "ai"), now, False
    con.execute("UPDATE wish SET name=?, terms=?, max_price=?, platforms=?, active=?, note=?, updated=?, "
                "terms_source=?, terms_updated=?, terms_regen=? WHERE id=?",
                (w["name"], json.dumps(w["terms"], ensure_ascii=False), w["max_price"], json.dumps(w["platforms"]),
                 int(w["active"]), w["note"], now, source, tupd, int(regen), int(wish_id)))


def request_regen(con, wish_id):
    """The "suggest terms again" button: only sets a flag; the next run of the host application
    generates new terms (they replace the current ones then, also the user's)."""
    init(con)
    if con.execute("UPDATE wish SET terms_regen=1 WHERE id=?", (int(wish_id),)).rowcount == 0:
        raise KeyError(wish_id)


def clean_ai_terms(terms):
    """Suggested terms (from a model): plain text, bounded, no regex/search syntax, deduplicated,
    at most MAX_TERMS. Invalid entries are dropped. Returns the list (may be empty)."""
    out, seen = [], set()
    for t in terms if isinstance(terms, list) else []:
        if not isinstance(t, str):
            continue
        try:
            t = _text(t, "term", MAX_TERM, required=False)
        except ValueError:
            continue
        if t and not _SYNTAX.search(t) and t.casefold() not in seen:
            seen.add(t.casefold())
            out.append(t)
    return out[:MAX_TERMS]


def set_ai_terms(cfg, wish_id, terms):
    """Store suggested terms for a wish (terms_source "ai", terms_updated now, terms_regen cleared).
    Checked in one transaction: only if the wish has no terms or new suggestions were requested, so
    terms the user entered or changed meanwhile are never overwritten. Returns True if stored."""
    from .deals_server import connect
    terms = clean_ai_terms(terms)
    if not terms:
        return False
    con = connect(cfg)
    try:
        init(con)
        con.isolation_level = None
        con.execute("BEGIN IMMEDIATE")
        try:
            row = con.execute("SELECT * FROM wish WHERE id=?", (int(wish_id),)).fetchone()
            w = _row(row) if row else None
            ok = bool(w) and (not w["terms"] or w["terms_regen"])
            if ok:
                con.execute("UPDATE wish SET terms=?, terms_source='ai', terms_updated=?, terms_regen=0 WHERE id=?",
                            (json.dumps(terms, ensure_ascii=False), time.strftime("%Y-%m-%dT%H:%M:%S"), int(wish_id)))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        return ok
    finally:
        con.close()


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
