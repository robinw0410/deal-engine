"""Assign listing titles to market groups with a small LLM (instead of word rules only).

Only titles that the word rules could match at all go to the model, and each listing only once
(result in history.db, table classify). If the model is unavailable, the word rules stay in
effect. The result corrects the groups in the tracking data and is used by insights.py.

Search config: classify: {enabled: true, max_per_run: 600, batch: 150, model: haiku}
"""
import json

from . import clock, history, llm
from .groups import match_group
from .util import load_json

KINDS = {"device", "bundle", "accessory", "other"}

PROMPT = """Assign each listing title to a device group.

Groups:
{groups}

Rules:
- "g" only if the title offers a DEVICE of this group (also broken or for parts).
- Accessories (cases, chargers, cables, mounts, grips, games, single spare parts), clothing and
  everything else: "g": null, "k": "accessory" or "other".
- Console with controllers/games/accessories: the console's group, "k": "bundle".
- Several identical controllers ("3 PS4 controllers", "2x DualSense"): controller group, "q" = count.
- Third-party and imitation products ("compatible", unknown brands): "g": null, unless there is a
  matching group of their own.
- Always the most specific matching group; if the variant is unclear, the more general one.

Answer ONLY with JSON lines, one per title, no other text:
{{"i": <number>, "g": "<group name>" or null, "q": <count>, "k": "device"|"bundle"|"accessory"|"other"}}

Titles:
{titles}
"""


def lookup(con, key, title=None):
    """Stored result (grp, qty, kind) or None. Invalid if the title changed."""
    r = con.execute("SELECT title, grp, qty, kind FROM classify WHERE uid=?", (key,)).fetchone()
    if not r or (title is not None and r[0] != title):
        return None
    return r[1], r[2] or 1, r[3]


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


def apply(cfg, sc, paths, log=print):
    cc = sc.get("classify")
    if not cc or not paths["history"].exists():
        return 0
    cc = cc if isinstance(cc, dict) else {}
    if cc.get("enabled") is False:
        return 0
    name = sc["_name"]
    groups = (sc.get("market") or {}).get("groups", [])
    names = {g["name"] for g in groups}
    con = history.connect(paths["history"])

    # titles from tracking and from the current state that the word rules could match
    todo = {}
    for key, title in con.execute("SELECT uid, title FROM listing WHERE search=? ORDER BY last_seen DESC", (name,)):
        if title and match_group(title, groups) and not lookup(con, key, title):
            todo.setdefault(key, title)
    for l in load_json(paths["state"], {"listings": []}).get("listings", []):
        t = l.get("title") or ""
        if l.get("id") and match_group(t, groups) and not lookup(con, l["id"], t):
            todo[l["id"]] = t
    items = list(todo.items())[:int(cc.get("max_per_run", 600))]
    if not items:
        log(f"classify {name}: nothing new")
        return 0

    glist = "\n".join(f"- {g['name']}" for g in groups)
    bs = int(cc.get("batch", 150))
    model = cc.get("model") or (cfg.get("llm") or {}).get("classify_model", "haiku")
    done = failed = 0
    stats = {}
    for s in range(0, len(items), bs):
        batch = items[s:s + bs]
        titles = "\n".join(f"{i}: {t[:140]}" for i, (_, t) in enumerate(batch, 1))
        try:
            out = llm.run(cfg, PROMPT.format(groups=glist, titles=titles), model, tools=(), max_turns=2,
                          timeout_min=10)
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
                # correct tracking: only single devices count in the group statistics
                row = con.execute("SELECT price, COALESCE(defect,0) FROM listing WHERE uid=?", (key,)).fetchone()
                grp = g if (g and k in ("device", "bundle") and q == 1) else None
                if grp and row and not row[1]:
                    gd = next(x for x in groups if x["name"] == grp)
                    if row[0] is not None and not (gd.get("min", 0) <= row[0] <= gd.get("max", 1e9)):
                        grp = None
                con.execute("UPDATE listing SET grp=? WHERE uid=?", (grp, key))
                stats[k] = stats.get(k, 0) + 1
                done += 1
    con.close()
    rest = len(todo) - len(items)
    log(f"classify {name}: {done} titles checked with {model} "
        f"({', '.join(f'{v} {k}' for k, v in sorted(stats.items()))})"
        + (f", {failed} without result" if failed else "") + (f", {rest} next run" if rest > 0 else ""))
    return 0
