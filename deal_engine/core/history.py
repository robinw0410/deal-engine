"""Price tracking in SQLite (data/state/history.db).

Records on every run which listings exist, at which price, and when they disappear. From that,
insights.py estimates sale prices and time-to-sell. Errors here never abort a run.

  python -m deal_engine history stats [search]
"""
import sqlite3
from datetime import date, timedelta
from statistics import median

from . import clock
from .filters import has_signal, passes
from .groups import classified_market_group, from_classification

SCHEMA = """
CREATE TABLE IF NOT EXISTS listing(
  uid TEXT PRIMARY KEY,                       -- <adapter>-<source_id>, same as the state id
  source TEXT, source_id TEXT,
  search TEXT, grp TEXT, title TEXT, defect INTEGER,
  published TEXT, first_seen TEXT, last_seen TEXT,
  first_price REAL, price REAL,
  private INTEGER, shipping INTEGER, distance_km INTEGER, image TEXT,
  status TEXT NOT NULL DEFAULT 'active',      -- active | gone
  checked TEXT,                               -- last individual check
  gone_date TEXT
);
CREATE TABLE IF NOT EXISTS price(
  uid TEXT NOT NULL, date TEXT NOT NULL, price REAL,
  PRIMARY KEY (uid, date)
);
CREATE TABLE IF NOT EXISTS classify(
  uid TEXT PRIMARY KEY, title TEXT, grp TEXT, qty INTEGER, kind TEXT, at TEXT
);
CREATE INDEX IF NOT EXISTS ix_listing_grp ON listing(search, grp, status);
CREATE INDEX IF NOT EXISTS ix_listing_seen ON listing(status, last_seen);
"""


def connect(db):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    if "location" not in [r[1] for r in con.execute("PRAGMA table_info(listing)")]:
        con.execute("ALTER TABLE listing ADD COLUMN location TEXT")   # databases from before 0.1.0
    return con


TITLE_LEN = 200   # titles are stored shortened to this length


def uid(it):
    return f"{it['source']}-{it['source_id']}"


def classification(con, key, title=None):
    """Stored LLM classification (grp, qty, kind) of listing `key`, or None. Invalid if the title
    changed (compared shortened like the stored title)."""
    r = con.execute("SELECT title, grp, qty, kind FROM classify WHERE uid=?", (key,)).fetchone()
    if not r or (title is not None and r[0] != (title or "")[:TITLE_LEN]):
        return None
    return r[1], r[2] or 1, r[3]


def _flag(v):
    return None if v is None else int(bool(v))


def _upsert(con, search, it, grp, defect, exact=False):
    """Insert or update a listing. exact: set grp as given, also to NULL (a plausible LLM
    classification decided it); otherwise a missing word-rule group keeps the stored one."""
    key, p, today = uid(it), it.get("price"), clock.today_str()
    row = con.execute("SELECT price FROM listing WHERE uid=?", (key,)).fetchone()
    if row is None:
        con.execute("""INSERT INTO listing(uid, source, source_id, search, grp, title, defect, published,
                       first_seen, last_seen, first_price, price, private, shipping, distance_km, image, location)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, it["source"], it["source_id"], search, grp, (it.get("title") or "")[:TITLE_LEN], defect,
                     it.get("_published"), today, today, p, p, _flag(it.get("private")),
                     _flag(it.get("shipping_possible")), it.get("distance_km"), it.get("_image"),
                     (it.get("location") or "")[:120] or None))
        if p is not None:
            con.execute("INSERT OR REPLACE INTO price VALUES (?,?,?)", (key, today, p))
        return
    old_p = row[0]
    grp_sql = "?" if exact else "COALESCE(?, grp)"
    con.execute(f"""UPDATE listing SET last_seen=?, price=?, title=?, grp={grp_sql}, defect=?,
                    status='active', gone_date=NULL, image=COALESCE(image, ?), location=COALESCE(location, ?)
                    WHERE uid=?""",
                (today, p if p is not None else old_p, (it.get("title") or "")[:TITLE_LEN], grp, defect,
                 it.get("_image"), (it.get("location") or "")[:120] or None, key))
    if p is not None and old_p is not None and abs(p - old_p) >= 1:
        con.execute("INSERT OR REPLACE INTO price VALUES (?,?,?)", (key, today, p))


def track(db, sc, items, log=print):
    """Store search results. With market groups only listings of a group, otherwise everything
    that passes the filters. A stored, plausible LLM classification of the listing (same title)
    decides the group instead of the word rules, also when it says "no group" for a listing that
    is already tracked (the stored group is then cleared, not kept)."""
    mc = sc.get("market") or {}
    groups, flt = mc.get("groups", []), sc.get("filters") or {}
    con = connect(db)
    n = 0
    with con:
        for it in items:
            sig = has_signal(it, flt)
            defect = None if sig is None else int(sig)
            exact = False
            if groups:
                cls = classification(con, uid(it), it["title"])
                exact = from_classification(it["title"], cls, groups) is not None
                g = classified_market_group(it["title"], it.get("price"), groups, cls, bool(sig),
                                            mc.get("accessory_regex"), sc.get("_locale"))
            else:
                g = None
            if groups and not g:
                if exact and con.execute("SELECT 1 FROM listing WHERE uid=?", (uid(it),)).fetchone():
                    _upsert(con, sc["_name"], it, None, defect, exact=True)
                continue
            if not groups and not passes(it, flt):
                continue
            _upsert(con, sc["_name"], it, g["name"] if g else None, defect, exact=exact)
            n += 1
    con.close()
    log(f"  tracking: {n} listings recorded")


def check_gone(db, sc, adapter, log=print):
    """Listings that have not shown up in results for 2+ days are checked one by one.
    At most per_group per group and max_checks in total per run, to keep request volume low."""
    from ..adapters.base import Blocked, check_result
    from .config import ConfigError
    tc = sc.get("track_checks") or {}
    per_group, max_checks = int(tc.get("per_group", 4)), int(tc.get("max_checks", 30))
    today = clock.today_str()
    cutoff = str(clock.today() - timedelta(days=2))
    con = connect(db)
    rows = con.execute("""SELECT uid, source_id, COALESCE(grp, '') FROM listing
                          WHERE search=? AND source=? AND status='active' AND last_seen<=?
                            AND (checked IS NULL OR checked<?)
                          ORDER BY last_seen DESC""", (sc["_name"], adapter.name, cutoff, today)).fetchall()
    per, todo = {}, []
    for key, sid, g in rows:
        if per.get(g, 0) < per_group and len(todo) < max_checks:
            per[g] = per.get(g, 0) + 1
            todo.append((key, sid))
    gone = alive = 0
    try:
        for key, sid in todo:
            try:
                st, price = check_result(adapter.check(sid))
            except (Blocked, ConfigError):
                raise
            except Exception:
                st, price = "unknown", None
            with con:
                if st == "gone":
                    # last seen is the best estimate of when it disappeared
                    con.execute("UPDATE listing SET status='gone', gone_date=last_seen, checked=? WHERE uid=?",
                                (today, key))
                    gone += 1
                elif st in ("active", "reserved"):
                    old = con.execute("SELECT price FROM listing WHERE uid=?", (key,)).fetchone()[0]
                    con.execute("UPDATE listing SET checked=?, last_seen=?, price=COALESCE(?, price) WHERE uid=?",
                                (today, today, price, key))
                    if price is not None and old is not None and abs(price - old) >= 1:
                        con.execute("INSERT OR REPLACE INTO price VALUES (?,?,?)", (key, today, price))
                    alive += 1
                else:
                    con.execute("UPDATE listing SET checked=? WHERE uid=?", (today, key))
    except Blocked as e:
        log(f"tracking check aborted (blocked): {e}")
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    if todo:
        log(f"tracking: checked {len(todo)} missing listings, {gone} gone, {alive} still online "
            f"({len(rows)} open)")


def _days(a, b):
    try:
        return (date.fromisoformat(str(b)[:10]) - date.fromisoformat(str(a)[:10])).days
    except (TypeError, ValueError):
        return None


def sold_by_group(con, search, window_days=60):
    """{group: {"p": [prices], "d": [days online]}} of non-defective listings that disappeared."""
    since = str(clock.today() - timedelta(days=window_days))
    sold = {}
    for grp, price, start, gone in con.execute(
            """SELECT grp, price, COALESCE(published, first_seen), gone_date FROM listing
               WHERE search=? AND status='gone' AND COALESCE(defect,0)=0 AND grp IS NOT NULL
                 AND price IS NOT NULL AND gone_date>=?""", (search, since)):
        s = sold.setdefault(grp, {"p": [], "d": []})
        s["p"].append(price)
        d = _days(start, gone)
        if d is not None and d >= 0:
            s["d"].append(d)
    return sold


def stats(db, search=None):
    con = connect(db)
    q = ("SELECT search, COALESCE(grp, '-'), status, defect, price, COALESCE(published, first_seen), gone_date "
         "FROM listing")
    rows = con.execute(q + (" WHERE search=?" if search else ""), (search,) if search else ()).fetchall()
    con.close()
    since = str(clock.today() - timedelta(days=60))
    by = {}
    for s, g, st, d, p, start, gone in rows:
        b = by.setdefault((s, g), {"active": 0, "gone": 0, "gone_p": [], "days": [], "act_p": []})
        if st == "active":
            b["active"] += 1
            if not d and p:
                b["act_p"].append(p)
        elif gone and gone >= since:
            b["gone"] += 1
            if not d and p:
                b["gone_p"].append(p)
                dd = _days(start, gone)
                if dd is not None and dd >= 0:
                    b["days"].append(dd)
    print(f"{'search/group':38} {'active':>6} {'gone60':>6}  {'median active':>13} {'median gone':>11} {'days online':>11}")
    for (s, g), b in sorted(by.items()):
        def m(xs):
            return f"{median(xs):.0f}" if len(xs) >= 3 else "-"
        print(f"{(s + ' / ' + g)[:38]:38} {b['active']:>6} {b['gone']:>6}  {m(b['act_p']):>13} "
              f"{m(b['gone_p']):>11} {m(b['days']):>11}")
    print("\nPrices exclude defective listings; 'gone' = disappeared in the last 60 days (sold or deleted).")
