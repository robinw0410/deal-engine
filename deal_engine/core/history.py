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
    cols = [r[1] for r in con.execute("PRAGMA table_info(listing)")]
    if "location" not in cols:
        con.execute("ALTER TABLE listing ADD COLUMN location TEXT")   # databases from before 0.1.0
    if "seller" not in cols:
        con.execute("ALTER TABLE listing ADD COLUMN seller TEXT")     # databases from before 0.2.17
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
    classification decided it); otherwise a missing word-rule group keeps the stored one.
    seller: the item's optional "_seller" (an adapter's seller key, no name; listing.normalize), only
    used to recognise reposts in sold_by_group; a missing one keeps the stored one."""
    key, p, today = uid(it), it.get("price"), clock.today_str()
    seller = str(it.get("_seller") or "")[:120] or None
    row = con.execute("SELECT price FROM listing WHERE uid=?", (key,)).fetchone()
    if row is None:
        con.execute("""INSERT INTO listing(uid, source, source_id, search, grp, title, defect, published,
                       first_seen, last_seen, first_price, price, private, shipping, distance_km, image, location,
                       seller)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, it["source"], it["source_id"], search, grp, (it.get("title") or "")[:TITLE_LEN], defect,
                     it.get("_published"), today, today, p, p, _flag(it.get("private")),
                     _flag(it.get("shipping_possible")), it.get("distance_km"), it.get("_image"),
                     (it.get("location") or "")[:120] or None, seller))
        if p is not None:
            con.execute("INSERT OR REPLACE INTO price VALUES (?,?,?)", (key, today, p))
        return
    old_p = row[0]
    grp_sql = "?" if exact else "COALESCE(?, grp)"
    con.execute(f"""UPDATE listing SET last_seen=?, price=?, title=?, grp={grp_sql}, defect=?,
                    status='active', gone_date=NULL, image=COALESCE(image, ?), location=COALESCE(location, ?),
                    seller=COALESCE(?, seller)
                    WHERE uid=?""",
                (today, p if p is not None else old_p, (it.get("title") or "")[:TITLE_LEN], grp, defect,
                 it.get("_image"), (it.get("location") or "")[:120] or None, seller, key))
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


def sold_by_group(con, search, window_days=60, clean=None):
    """{group: {"p": [prices], "d": [days online]}} of listings of `search` that disappeared in the last
    `window_days` days.

    clean=None: as before 0.2.17, every non-defective disappeared listing with a price under its stored
    tracking group (listing.grp). clean: the settings of sold_settings(sc); only disappeared single devices
    count, once per repost chain (see _sold_clean)."""
    if clean is not None:
        return _sold_clean(con, search, window_days, clean)
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


SOLD_COUNTRIES = ("AT", "DE")
SOLD_DEDUP_DAYS = 14


def sold_settings(sc):
    """Settings of the cleaned statistics of disappeared listings (sold_by_group clean=...) of search `sc`:
    its market groups, sample, accessory/exclude regexes, defect filters and locale, market.source, and
    from the insights settings (insights.settings) sold_countries and sold_dedup_days."""
    from . import insights   # imports this module
    mc = sc.get("market") or {}
    c = insights.settings(sc)
    try:
        dedup = max(0, int(c.get("sold_dedup_days")))
    except (TypeError, ValueError):
        dedup = SOLD_DEDUP_DAYS
    countries = c.get("sold_countries")
    countries = SOLD_COUNTRIES if countries is None else [countries] if isinstance(countries, str) else countries
    return {"groups": mc.get("groups") or [], "source": mc.get("source") or None,
            "sample": (mc.get("sample") or "all"), "accessory_regex": mc.get("accessory_regex"),
            "exclude_regex": mc.get("exclude_regex"), "filters": sc.get("filters") or {},
            "locale": sc.get("_locale") or "en", "dedup_days": dedup,
            "countries": [str(x).strip().upper() for x in countries]}


def sold_for_search(db, sc, window_days=None, clean=True, log=print):
    """sold_by_group() of search `sc` from history.db `db`, opened read-only (connect_ro). window_days:
    default the search's insights window_days. clean=True: cleaned (sold_settings) unless the search turns
    it off with insights sold_clean: false; clean=False: as before 0.2.17. Never raises: a missing or
    unreadable database gives {} (with a log line if unreadable)."""
    try:
        if not Path(db).exists():
            return {}
        from . import insights
        c = insights.settings(sc)
        w = c["window_days"] if window_days is None else window_days
        con = connect_ro(db)
        try:
            return sold_by_group(con, sc["_name"], w, sold_settings(sc) if clean and c.get("sold_clean") else None)
        finally:
            con.close()
    except Exception as e:   # like tracking: never break a run
        log(f"  sale prices from tracking not readable: {type(e).__name__}: {e}")
        return {}


_COUNTRY = re.compile(r"([A-Z]{2})(?:\s|$)")


def _domestic(source, location, countries):
    """eBay locations start with the country code ("DE 12345 Stadt", "US 805**", "JP"): only the listed
    countries count, an eBay listing without a code does not. Other sources: a leading code is checked
    the same way, a location without one ("2700 Wiener Neustadt") is domestic."""
    m = _COUNTRY.match(location or "")
    if m:
        return m.group(1) in countries
    return source != "ebay"


def _image_key(source, image):
    """The same photo: willhaben stores it under a new path per listing but keeps the part after the last
    "_" ("9/115/498/0969_-1137064254.jpg"), other sources (eBay) reuse the whole URL."""
    if not image:
        return None
    if source == "willhaben" and "_" in image:
        k = image.rsplit("_", 1)[1]
        return k if len(k) >= 6 else image
    return image


def _norm_title(t):
    return " ".join(re.sub(r"[\W_]+", " ", str(t or "").lower()).split())


def _close(a, b, rel):
    return a is not None and b is not None and abs(a - b) <= rel * max(abs(a), abs(b))


def _sold_clean(con, search, window_days, cs):
    """sold_by_group() with clean settings `cs` (sold_settings). A disappeared listing counts only if

      - it is a single device of a group, determined again from the title (listing.grp is not trusted,
        it can be outdated): a plausible stored classification (same title, groups.from_classification,
        so exclude/veto apply) of kind device with quantity 1 and no extras in a with-clause; without
        one (or an implausible one) only with market.sample all, by the word rules as in
        market.estimate (group, no accessory, bundle quantity 1, no extras);
      - not defective: stored flag 0, no defect signal in the title (filters.signal_regex), not hit by
        market.exclude_regex / the locale's market_exclude; price within the group's min/max;
      - from market.source if the search sets one (otherwise every source);
      - domestic (_domestic: eBay only with a country code from sold_countries);
      - it is the last link of its repost chain.

    Repost chains: listings of the same source are one item when, with at most sold_dedup_days between
    the end of one and the start of the next (overlapping ones too: parallel copies of a dealer)
      a) the normalised titles are equal, the prices equal after rounding to whole EUR or within
         +-2 % (a repost keeps the price or cuts it a little; rounding alone would split 149 and 150,
         +-2 % alone 9.99 and 10.20), and neither the photos (_image_key) nor the location texts differ
         where both listings have one: a repost or a dealer's parallel copy reuses the photo, while
         generic titles ("Xbox Series S" for 200 EUR: 10 disappeared willhaben listings, 9 different
         photos in the test data) come from different sellers, or
      b) the same seller key (listing.seller) or the same photo (_image_key), the same group (by
         classification or word rules) and prices within +-10 %. The seller or photo alone is no repost:
         dealers sell many different devices under one account and often with one shop photo.
    A chain counts at most once, and only if its last link (most recently seen; on equal days an active
    one) disappeared in the window: a listing replaced by a repost was not sold. Price of that last
    link, days online from the start of the chain's first link.

    Loads the listings of the search seen in the window (plus sold_dedup_days) once and groups them in
    Python; no correlated subquery."""
    from .market import _in_range   # market imports this module
    loc = locale_mod.get(cs.get("locale") or "en")
    groups = cs.get("groups") or []
    flt = cs.get("filters") or {}
    excl = cs.get("exclude_regex") or loc.market_exclude
    acc = cs.get("accessory_regex")
    countries = set(cs.get("countries") or ())
    source = cs.get("source")
    dedup = int(cs.get("dedup_days", SOLD_DEDUP_DAYS))
    word_only = (cs.get("sample") or "all") == "all"
    since_d = clock.today() - timedelta(days=window_days)
    since, load_since = str(since_d), str(since_d - timedelta(days=dedup))
    has_seller = "seller" in [r[1] for r in con.execute("PRAGMA table_info(listing)")]
    rows = con.execute(
        f"""SELECT l.source, l.title, l.price, COALESCE(l.defect,0), COALESCE(l.published, l.first_seen),
                   l.first_seen, l.last_seen, l.status, l.gone_date, l.image, l.location,
                   {"l.seller" if has_seller else "NULL"}, c.uid, c.title, c.grp, c.qty, c.kind
            FROM listing l LEFT JOIN classify c ON c.uid = l.uid
            WHERE l.search=? AND l.last_seen>=?""", (search, load_since)).fetchall()

    def cls(r):
        t = (r[1] or "")[:TITLE_LEN]
        c = (r[14], r[15] or 1, r[16]) if r[12] is not None and r[13] == t else None
        return t, from_classification(t, c, groups)

    def group_any(i):   # group for the photo/seller rule, kind does not matter
        if i not in g_any:
            t, c = cls(rows[i])
            g = c[1] if c is not None else match_group(t, groups)
            g_any[i] = g["name"] if g else None
        return g_any[i]

    def counted(r):   # the group a disappeared listing counts for, or None
        src, title, price, defect, _, _, _, status, gone = r[:9]
        if status != "gone" or not gone or gone < since or price is None or defect:
            return None
        if (source and src != source) or not _domestic(src, r[10], countries):
            return None
        t, c = cls(r)
        if has_signal({"title": t}, flt) or re.search(excl, t, re.I):
            return None
        if c is not None:
            kind, g, q = c
            if kind != "device" or g is None or q != 1 or has_extras(t, loc):
                return None
        elif word_only:
            g = match_group(t, groups)
            if not g or is_accessory(t, acc, loc) or bundle_qty(t, g, loc) > 1 or has_extras(t, loc):
                return None
        else:
            return None   # market.sample device_only: not classified, not counted
        return g if _in_range(price, g) else None

    # repost chains (union-find over the rows)
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def near(i, j):   # at most `dedup` days from the end of the earlier to the start of the later one
        a, b = (i, j) if (rows[i][5] or "") <= (rows[j][5] or "") else (j, i)
        d = _days(rows[a][6], rows[b][5])
        return d is None or d <= dedup

    by_title, by_key = {}, {}
    keys = [_image_key(r[0], r[9]) for r in rows]
    places = [_norm_title(r[10]) for r in rows]
    for i, r in enumerate(rows):
        if r[2] is None:
            continue
        by_title.setdefault((r[0], _norm_title(r[1])), []).append(i)
        k = keys[i]
        if k:
            by_key.setdefault((r[0], "img", k), []).append(i)
        if r[11]:
            by_key.setdefault((r[0], "seller", r[11]), []).append(i)
    def pairs(idx):
        """(i, j) of one bucket that can be near(): sorted by first_seen, the inner loop stops once a later
        listing starts more than `dedup` days after the end of i (all after it start later still), so a
        dealer with thousands of listings under one key costs about n x the listings per window, not n^2."""
        idx = sorted(idx, key=lambda i: rows[i][5] or "")
        for x, i in enumerate(idx):
            end = rows[i][6]
            for j in idx[x + 1:]:
                d = _days(end, rows[j][5])
                if d is not None and d > dedup:
                    break
                yield i, j

    g_any = {}
    for idx in by_title.values():
        for i, j in pairs(idx):
            pi, pj = rows[i][2], rows[j][2]
            li, lj, ki, kj = places[i], places[j], keys[i], keys[j]
            if (round(pi) == round(pj) or _close(pi, pj, 0.02)) and (not li or not lj or li == lj) \
                    and (not ki or not kj or ki == kj) and near(i, j):
                parent[find(i)] = find(j)
    for idx in by_key.values():
        for i, j in pairs(idx):
            if find(i) == find(j) or not _close(rows[i][2], rows[j][2], 0.10) or not near(i, j):
                continue
            gi = group_any(i)
            if gi is not None and gi == group_any(j):
                parent[find(i)] = find(j)

    chains = {}
    for i in range(len(rows)):
        chains.setdefault(find(i), []).append(i)
    sold = {}
    for members in chains.values():
        last = max(members, key=lambda i: (rows[i][6] or "", rows[i][7] == "active", rows[i][5] or ""))
        g = counted(rows[last])
        if g is None:
            continue
        s = sold.setdefault(g["name"], {"p": [], "d": []})
        s["p"].append(rows[last][2])
        d = _days(min(rows[i][4] or rows[i][5] or "" for i in members), rows[last][8])
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
