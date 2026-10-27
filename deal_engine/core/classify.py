"""Assign listing titles to market groups with a small LLM (instead of word rules only).

Two places use it, both only with the LLM evaluator ("claude"):
  - before the candidate selection (preselect(), called from pipeline.collect): the titles that
    are about to be considered as candidates, so that select() compares them with the right group
    (or skips accessories) before anything is evaluated;
  - after the merge (apply()): titles from tracking and the state, to correct the tracking groups.

Only titles that the word rules could match at all go to the model, and each listing only once
(result in history.db, table classify, key "<adapter>-<source_id>"). If the model is unavailable,
the word rules stay in effect. A result is only used if it is plausible: a group named by the
model must have a match regex that hits the title (groups.from_classification), otherwise the
word rules decide. classify.max_per_run limits the titles per search run (Budget, shared by
both steps and all adapters of a run_search).

Search config: classify: {enabled: true, max_per_run: 600, batch: 150, model: haiku}
Prompt: core/prompts/<locale>/classify.md, overridable with prompts.classify in the config.
"""
import json

from . import clock, history, llm
from .groups import classified_market_group, from_classification, match_group, matches_any
from .util import load_json

KINDS = {"device", "bundle", "accessory", "part", "other"}
TITLE_LEN = history.TITLE_LEN   # titles are stored like in the listing table


def settings(sc):
    """The classify settings of a search as a dict, or None if classification is off."""
    cc = (sc or {}).get("classify")
    if not cc:
        return None
    cc = cc if isinstance(cc, dict) else {}
    return None if cc.get("enabled") is False else cc


class Budget:
    """Titles that may still go to the model in this search run (classify.max_per_run)."""

    def __init__(self, n):
        self.left = max(0, int(n))

    def take(self, n):
        k = min(self.left, max(0, n))
        self.left -= k
        return k


def budget(sc):
    """A fresh budget for one search run (run_search creates one and passes it to both steps)."""
    return Budget((settings(sc) or {}).get("max_per_run", 600))


def lookup(con, key, title=None):
    """Stored result (grp, qty, kind) or None. Invalid if the title changed."""
    return history.classification(con, key, title)


def correct_tracking(con, results, groups):
    """Write plausible classifications into the tracking table (listing.grp): only single devices
    count in the group statistics. Implausible results leave the word-rule group alone."""
    with con:
        for key, cls in results.items():
            row = con.execute("SELECT title, price, COALESCE(defect,0) FROM listing WHERE uid=?", (key,)).fetchone()
            if not row or from_classification(row[0], cls, groups) is None:
                continue
            g = classified_market_group(row[0], row[1], groups, cls, bool(row[2]))
            con.execute("UPDATE listing SET grp=? WHERE uid=?", (g["name"] if g else None, key))


def parse(out, n, names):
    res = {}
    for line in out.splitlines():
        line = line.strip().strip(",")
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
            i = int(o["i"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
        if not 1 <= i <= n:
            continue
        g = o.get("g")
        g = g if g in names else None
        k = str(o.get("k") or "").lower()
        k = k if k in KINDS else ("device" if g else "other")
        try:
            q = max(1, min(50, int(o.get("q") or 1)))
        except (TypeError, ValueError):
            q = 1
        res[i] = (g, q, k)
    return res


def classify_titles(cfg, sc, con, items, log=print):
    """Classify (uid, title) pairs with the LLM in batches and store every result in the classify
    table. Returns ({uid: (grp, qty, kind)}, number without result). A failing batch is logged
    and counted, never raised (word rules stay in effect); a missing prompt file is a ConfigError."""
    cc = settings(sc) or {}
    groups = (sc.get("market") or {}).get("groups", [])
    names = {g["name"] for g in groups}
    glist = "\n".join(f"- {g['name']}" for g in groups)
    bs = max(1, int(cc.get("batch", 150)))
    model = model_name(cfg, sc)
    results, failed = {}, 0
    for s in range(0, len(items), bs):
        batch = items[s:s + bs]
        titles = "\n".join(f"{i}: {t[:140]}" for i, (_, t) in enumerate(batch, 1))
        text = llm.prompt(cfg, sc, "classify", GROUPS=glist, TITLES=titles)   # ConfigError if the file is missing
        try:
            out = llm.run(cfg, text, model, tools=(), max_turns=2, timeout_min=10)
            res = parse(out, len(batch), names)
        except Exception as e:   # model unavailable: word rules stay in effect
            log(f"  classify batch {s // bs + 1} failed: {e}")
            failed += len(batch)
            continue
        with con:
            for i, (key, t) in enumerate(batch, 1):
                if i not in res:
                    failed += 1
                    continue
                g, q, k = res[i]
                con.execute("INSERT OR REPLACE INTO classify VALUES (?,?,?,?,?,?)", (key, t, g, q, k, clock.today_str()))
                results[key] = (g, q, k)
    return results, failed


def model_name(cfg, sc):
    return (settings(sc) or {}).get("model") or (cfg.get("llm") or {}).get("classify_model", "haiku")


def _summary(results):
    stats = {}
    for _, _, k in results.values():
        stats[k] = stats.get(k, 0) + 1
    return ", ".join(f"{v} {k}" for k, v in sorted(stats.items()))


def preselect(cfg, sc, titles, db, log=print, budget=None):
    """Classification before the candidate selection.

    titles: {uid: title} of the listings that are about to be considered as candidates. Titles
    that no group's match regex hits are left out; stored results (same title) are reused, at most
    classify.max_per_run new titles go to the model (budget: shared with the other steps of the
    run). New results also correct the tracking table. Returns {uid: (grp, qty, kind)} for every
    title with a result (stored or new); select() checks plausibility, titles without a result
    keep the word rules."""
    cc = settings(sc)
    groups = (sc.get("market") or {}).get("groups", [])
    if cc is None or not groups or not titles:
        return {}
    con = history.connect(db)
    try:
        known, todo = {}, []
        for key, title in titles.items():
            t = (title or "")[:TITLE_LEN]
            if not t or not matches_any(t, groups):
                continue
            r = lookup(con, key, t)
            if r:
                known[key] = r
            else:
                todo.append((key, t))
        budget = budget if budget is not None else Budget(cc.get("max_per_run", 600))
        items = todo[:budget.take(len(todo))]
        new, failed = classify_titles(cfg, sc, con, items, log) if items else ({}, 0)
        if new:
            correct_tracking(con, new, groups)
    finally:
        con.close()
    rest = len(todo) - len(items)
    if items:
        log(f"classify before selection: {len(new)} of {len(items)} titles checked with {model_name(cfg, sc)}"
            + (f" ({_summary(new)})" if new else "")
            + (f", {failed} without result (word rules stay)" if failed else "")
            + (f", {rest} left to the word rules" if rest > 0 else "")
            + (f"; {len(known)} known" if known else ""))
    return {**known, **new}


def apply(cfg, sc, paths, log=print, budget=None):
    """Classify titles from tracking and the state (after the merge) and correct the tracking
    groups. budget: what is left of classify.max_per_run in this search run."""
    cc = settings(sc)
    if cc is None or not paths["history"].exists():
        return 0
    name = sc["_name"]
    groups = (sc.get("market") or {}).get("groups", [])
    con = history.connect(paths["history"])

    # titles from tracking and from the current state that the word rules could match
    todo = {}
    for key, title in con.execute("SELECT uid, title FROM listing WHERE search=? ORDER BY last_seen DESC", (name,)):
        if title and match_group(title, groups) and not lookup(con, key, title):
            todo.setdefault(key, title)
    for l in load_json(paths["state"], {"listings": []}).get("listings", []):
        t = (l.get("title") or "")[:TITLE_LEN]
        if l.get("id") and match_group(t, groups) and not lookup(con, l["id"], t):
            todo[l["id"]] = t
    budget = budget if budget is not None else Budget(cc.get("max_per_run", 600))
    items = list(todo.items())[:budget.take(len(todo))]
    if not items:
        log(f"classify {name}: nothing new" if not todo else f"classify {name}: budget of this run used up, "
            f"{len(todo)} titles next run")
        con.close()
        return 0

    try:
        results, failed = classify_titles(cfg, sc, con, items, log)
        correct_tracking(con, results, groups)
    finally:
        con.close()
    rest = len(todo) - len(items)
    log(f"classify {name}: {len(results)} titles checked with {model_name(cfg, sc)} ({_summary(results)})"
        + (f", {failed} without result" if failed else "") + (f", {rest} next run" if rest > 0 else ""))
    return 0
