"""Price tracking in SQLite (data/state/history.db).

Records on every run which listings exist, at which price, and when they disappear. From that,
insights.py estimates sale prices and time-to-sell. Errors here never abort a run.

  python -m deal_engine history stats [search]
"""
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from statistics import median

from . import clock
from . import locale as locale_mod
from .filters import has_signal, passes
from .groups import (bundle_qty, classified_market_group, drop_part, from_classification, has_extras, is_accessory,
                     match_group)

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


def connect_ro(db):
    """Read-only connection to an existing history.db: no schema is created and nothing is written, the
    database file stays byte for byte as it is (a missing one is an error, not created). The database is
    in WAL mode, though: while such a connection reads, SQLite may create the helper files history.db-shm
    and history.db-wal next to it (and needs write access to the directory for that, unless they exist)."""
    return sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True, timeout=60)


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


def attach_classification(db, items, log=print):
    """Set it["_cls"] on every item (dicts with source, source_id, title): the stored LLM classification
    (grp, qty, kind) of the listing, or None if there is none or the title changed. Read-only, calls no
    model. A missing or unreadable history.db never raises: all items then count as not classified.
    Returns the number of classified items."""
    items = list(items)
    for it in items:
        it["_cls"] = None
    try:
        if not Path(db).exists():
            return 0
        con = connect_ro(db)
        try:
            found = [classification(con, uid(it), it.get("title")) for it in items]
        finally:
            con.close()
    except Exception as e:   # like tracking: never break a run
        log(f"  stored classification not readable, listings count as not classified: {type(e).__name__}: {e}")
        return 0
    for it, cls in zip(items, found):
        it["_cls"] = cls
    return sum(1 for cls in found if cls is not None)


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


def bundles_apart(mc):
    """market.sample other than "all" (market.sample_mode; not imported here, market imports this module):
    the market median of the search comes from the classification, and a device the word rules see listed
    with extras ("PS4 mit 3 Spielen", groups.has_extras) is a bundle there whatever the model says. Such a
    title then never has a tracking group (listing.grp stays NULL: track(), classify.correct_tracking), so
    it stays out of the statistics of disappeared listings (sold_by_group) and is not checked one by one
    (check_gone); it counts only through table classify in the bundle fallback of the market median."""
    return ((mc or {}).get("sample") or "all") != "all"


def _is_bundle(it, sig, c, groups, mc, loc):
    """A bundle by the word rules that can count for the market median (bundles_apart): a device of a
    group listed with extras, with a price, without defect signal and not hit by exclude_regex / the
    locale's market_exclude. c: groups.from_classification of the title. With a plausible classification
    it has to call the listing a device or bundle of a group with quantity 1; without one the word rules
    must give a group and no accessory, spare part or bundle quantity."""
    t = it.get("title") or ""
    if it.get("price") is None or sig or not has_extras(t, loc):
        return False
    if re.search(mc.get("exclude_regex") or loc.market_exclude, t, re.I):
        return False
    if c is not None:
        return c[0] in ("device", "bundle") and c[2] == 1
    g = match_group(t, groups)
    return bool(g) and not is_accessory(t, mc.get("accessory_regex"), loc) and bundle_qty(t, g, loc) == 1 \
        and not drop_part(t, "skip", None, mc.get("part_regex"), loc)


def track(db, sc, items, log=print, earmark_bundles=False):
    """Store search results. With market groups only listings of a group, otherwise everything
    that passes the filters. A stored, plausible LLM classification of the listing (same title)
    decides the group instead of the word rules, also when it says "no group" for a listing that
    is already tracked (the stored group is then cleared, not kept).

    Searches with market.sample other than "all" (bundles_apart; nothing below applies to the others):
    a device listed with extras by the word rules never gets a group. earmark_bundles (update_market
    sets it for the group queries): such bundles (_is_bundle) are stored with grp NULL although the word
    rules do not track them, so that classify.apply classifies their titles and the bundle fallback of
    the market median (market.classified_sample) and market.sample_report see them. They share
    classify.max_per_run with all other titles."""
    mc = sc.get("market") or {}
    groups, flt = mc.get("groups", []), sc.get("filters") or {}
    apart = bool(groups) and bundles_apart(mc)
    loc = locale_mod.get(sc.get("_locale")) if apart else None
    con = connect(db)
    n = n_bundle = 0
    with con:
        for it in items:
            sig = has_signal(it, flt)
            defect = None if sig is None else int(sig)
            exact, c = False, None
            if groups:
                cls = classification(con, uid(it), it["title"])
                c = from_classification(it["title"], cls, groups)
                exact = c is not None
                g = classified_market_group(it["title"], it.get("price"), groups, cls, bool(sig),
                                            mc.get("accessory_regex"), sc.get("_locale"))
                if g and apart and has_extras(it["title"], loc):
                    g = None   # "PS4 mit 3 Spielen" classified as device/bundle of PS4: a bundle, no group
            else:
                g = None
            if groups and not g:
                if apart and earmark_bundles and _is_bundle(it, sig, c, groups, mc, loc):
                    _upsert(con, sc["_name"], it, None, defect, exact=True)
                    n_bundle += 1
                elif exact and con.execute("SELECT 1 FROM listing WHERE uid=?", (uid(it),)).fetchone():
                    _upsert(con, sc["_name"], it, None, defect, exact=True)
                continue
            if not groups and not passes(it, flt):
                continue
            _upsert(con, sc["_name"], it, g["name"] if g else None, defect, exact=exact)
            n += 1
    con.close()
    log(f"  tracking: {n} listings recorded" + (f", {n_bundle} bundles noted for the market sample" if n_bundle else ""))


def check_gone(db, sc, adapter, log=print):
    """Listings that have not shown up in results for 2+ days are checked one by one.
    At most per_group per group and max_checks in total per run, to keep request volume low.
    With market.sample other than "all", bundles without a group (bundles_apart: listings noted for the
    market sample only) are never checked: they cause no request and stay "active" with their last_seen."""
    from ..adapters.base import Blocked, check_result
    from .config import ConfigError
    tc = sc.get("track_checks") or {}
    per_group, max_checks = int(tc.get("per_group", 4)), int(tc.get("max_checks", 30))
    today = clock.today_str()
    cutoff = str(clock.today() - timedelta(days=2))
    con = connect(db)
    rows = con.execute("""SELECT uid, source_id, COALESCE(grp, ''), title FROM listing
                          WHERE search=? AND source=? AND status='active' AND last_seen<=?
                            AND (checked IS NULL OR checked<?)
                          ORDER BY last_seen DESC""", (sc["_name"], adapter.name, cutoff, today)).fetchall()
    mc = sc.get("market") or {}
    if mc.get("groups") and bundles_apart(mc):
        loc = locale_mod.get(sc.get("_locale"))
        rows = [r for r in rows if r[2] or not has_extras(r[3], loc)]
    per, todo = {}, []
    for key, sid, g, _ in rows:
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
