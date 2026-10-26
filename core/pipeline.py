"""Adapter-neutral pipeline for one search and one adapter:

  collect   search, update market prices, reconcile the state (price changes, gone, reserved),
            pick new candidates and write evaluation batches
  prefilter apply a cheap model's prefilter result to the batches (optional)
  merge     take the evaluations into the state and write a short markdown report

Work files per search and adapter in data/work/<search>/<adapter>/:
  candidates-N.json  {"date", "candidates": [...], "existing_listings": [...]}
  prefilter-N.json   {"drop": [{"source_id", "reason"}]}            (written by the prefilter model)
  accepted-N.json    [{"source_id", <evaluation fields>} | {"source_id", "merge_into"}]
  changes.json       price changes, gone, reserved, problems of this run
"""
import re
import shutil
import urllib.request
from datetime import timedelta

from adapters.base import Blocked

from . import clock, history
from . import config as config_mod
from .filters import has_signal, passes
from .groups import bundle_qty, is_accessory, match_group
from .listing import normalize
from .market import due as market_due, refresh as market_refresh, resale_from_ask, settings as market_settings
from .util import eur, load_json, num, save_json

# fields copied from a candidate into a new state entry (if the evaluation did not set them)
CARRY = ("distance_km", "shipping_possible", "shipping_cost_eur", "private", "condition", "auction_end",
         "best_offer", "market_median", "market_group", "market_n", "market_resale_estimate")
# fields the evaluation must not overwrite
PROTECTED = {"id", "urls", "url", "source", "source_id", "sources", "price", "price_history", "first_seen",
             "last_seen", "merge_into"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _search(adapter, query, home, road_factor, items, problems):
    try:
        raw = adapter.search(query)
    except Blocked:
        raise
    except Exception as e:
        problems.append(f"{adapter.name} search '{query.get('keyword') or '*'}' failed: {e}")
        return 0
    bad = 0
    for r in raw:
        try:
            it = normalize(r, adapter.name, home, road_factor)
        except ValueError:
            bad += 1
            continue
        items.setdefault(it["source_id"], it)
    if bad:
        problems.append(f"{adapter.name}: {bad} invalid listings ignored (see docs/listing-format.md)")
    return len(raw)


def search_all(cfg, sc, adapter, extra=(), log=print):
    """All configured queries of a search, deduplicated by source_id."""
    home = config_mod.home(cfg)
    rf = float((cfg.get("location") or {}).get("road_factor", 1.3))
    flt = sc.get("filters") or {}
    kws = (sc.get(adapter.name) or {}).get("keywords") or sc.get("keywords") or []
    queries = [{"keyword": k} for k in kws] or [{"keyword": None}]
    items, problems = {}, []
    for q in list(queries) + list(extra):
        q = {"min_price": flt.get("min_price"), "max_price": flt.get("max_price"), **q}
        n = _search(adapter, q, home, rf, items, problems)
        if q.get("keyword"):
            log(f"  '{q['keyword']}': {n} results")
    return items, problems


def update_market(cfg, sc, adapter, P, log=print):
    """Market prices per group from dedicated queries (working units of each group)."""
    mc = sc.get("market") or {}
    groups = mc.get("groups") or []
    market = load_json(P["market"], {})
    source = mc.get("source") or sc["adapters"][0]
    if not groups or adapter.name != source or not market_due(market, mc):
        return market
    log("updating market prices ...")
    home = config_mod.home(cfg)
    rf = float((cfg.get("location") or {}).get("road_factor", 1.3))
    by_group, problems = {}, []
    for g in groups:
        items = {}
        _search(adapter, {"keyword": g.get("keyword"), "max_price": g.get("max")}, home, rf, items, problems)
        if sc.get("track"):
            try:
                history.track(P["history"], sc, items.values(), log=lambda s: None)
            except Exception as e:   # tracking must never break a run
                log(f"  tracking error: {e}")
        by_group[g["name"]] = list(items.values())
    new = market_refresh(market, by_group, groups, sc.get("filters") or {}, mc, log)
    save_json(P["market"], new)
    return new


def reconcile(state, items, adapter, sc, changes, log=print):
    """Compare the stored listings of this adapter with the current results."""
    flt = sc.get("filters") or {}
    today = clock.today_str()
    keep = []
    for l in state.get("listings", []):
        sources = l.get("sources") or {}
        sid = sources.get(adapter.name)
        if not sid:
            keep.append(l)
            continue
        # hard limits (e.g. after a rule change)
        p = num(l.get("price"))
        if flt.get("max_price") is not None and p is not None and p > flt["max_price"] and len(sources) == 1:
            changes["rule"].append(l)
            continue
        it = items.get(sid)
        if it is not None:
            st = it["status"]
        else:
            try:
                st = adapter.check(sid)
            except Blocked:
                raise
            except Exception:
                st = "unknown"
        if st == "gone":
            others = {k: v for k, v in sources.items() if k != adapter.name}
            if others:
                l["sources"] = others
                l["urls"] = [u for u in l.get("urls", []) if u != l.get("_urls_by_source", {}).get(adapter.name)]
                l.setdefault("_urls_by_source", {}).pop(adapter.name, None)
                keep.append(l)
            else:
                changes["gone"].append(l)
            continue
        if st == "unknown":
            l["last_check_failed"] = today
            keep.append(l)
            continue
        l.pop("last_check_failed", None)
        l["last_seen"] = today
        title = (it or {}).get("title") or ""
        if (st == "reserved" or re.search(r"\b(reserved|sold)\b", title, re.I)) and l.get("status") != "reserved":
            l["status"] = "reserved"
            l["score"] = min(num(l.get("score")) or 3, 3)
            changes["reserved"].append(l)
        if it:
            newp, oldp = it.get("price"), num(l.get("price"))
            if newp is not None and oldp is not None and abs(newp - oldp) >= 1:
                l.setdefault("price_history", []).append({"date": today, "price": oldp})
                l["price"] = newp
                changes["price"].append({"title": l.get("title"), "url": (l.get("urls") or [""])[0],
                                         "old": oldp, "new": newp})
        keep.append(l)
    # a sudden mass disappearance is far more likely an outage or a changed source than reality
    n_total = sum(1 for l in state.get("listings", []) if (l.get("sources") or {}).get(adapter.name))
    if len(changes["gone"]) > max(5, 0.3 * n_total):
        changes["problems"].append(
            f"{len(changes['gone'])} of {n_total} {adapter.name} listings look offline. That is implausibly "
            "many (outage or changed source?), so nothing was removed.")
        for l in changes["gone"]:
            l["last_check_failed"] = today
        keep += changes["gone"]
        changes["gone"] = []
    state["listings"] = keep


def select(items, known, seen, market, sc, log=print):
    """New candidates: pass the filters, are not known, are cheap enough relative to the market."""
    flt = sc.get("filters") or {}
    mc = sc.get("market") or {}
    s = market_settings(mc)
    groups = mc.get("groups") or []
    cands, too_expensive, no_signal = [], 0, 0
    for sid, it in items.items():
        if sid in known or it["status"] != "active" or not passes(it, flt):
            continue
        prev = seen.get(sid)
        # seen before: only again after a price drop of at least 10 %
        if prev and not (it.get("price") is not None and prev.get("price") and it["price"] <= prev["price"] * 0.9):
            continue
        sig = has_signal(it, flt)
        g = match_group(it["title"], groups) if groups else None
        if g and is_accessory(it["title"], mc.get("accessory_regex")):
            continue   # "case for <device>" is not a deal on the device
        m = market.get(g["name"]) if g else None
        if m:
            it["market_group"], it["market_median"], it["market_n"] = g["name"], m["median"], m["n"]
            it["market_resale_estimate"] = resale_from_ask(m, s["sale_factor"])
            ratio = s["max_price_ratio"] if sig is None else s["defect_price_ratio"] if sig else s["flip_ratio"]
            total = (it.get("price") or 0) + (it.get("shipping_cost_eur") or 0)
            qty = bundle_qty(it["title"], g)   # "3 controllers" is compared with 3 x the unit median
            if it.get("price") is not None and total > m["median"] * qty * float(ratio):
                too_expensive += 1
                continue
        elif sig is False:
            no_signal += 1   # no defect signal and no market price to judge a flip
            continue
        cands.append(it)
    if no_signal:
        log(f"{no_signal} listings without defect signal and without market price skipped")
    if too_expensive:
        log(f"{too_expensive} candidates above the market price threshold skipped")
    cands.sort(key=lambda x: (x.get("_published") or "", x["source_id"]), reverse=True)

    # quotas (e.g. phones): at most n per run and max_share of the state
    for cap in sc.get("category_caps") or []:
        rx = cap["regex"]
        allowed = int(cap.get("max_new_per_run", 5))
        kept, n_cap = [], 0
        for it in cands:
            if re.search(rx, it["title"], re.I):
                if n_cap >= allowed:
                    continue
                n_cap += 1
            kept.append(it)
        if len(kept) < len(cands):
            log(f"quota '{cap.get('name', rx)}': {len(cands) - len(kept)} candidates postponed")
        cands = kept
    max_new = int(sc.get("max_new_per_run", 50))
    return cands[:max_new], max(0, len(cands) - max_new)


def download_images(urls, folder, prefix, root):
    """Download listing photos for the evaluator (only http/https, size-limited)."""
    files = []
    for i, u in enumerate(urls):
        if not re.match(r"https?://", str(u)):
            continue
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "deal-engine (image fetch for evaluation)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                if not str(r.headers.get("Content-Type", "")).startswith("image/"):
                    continue
                data = r.read(MAX_IMAGE_BYTES + 1)
        except Exception:
            continue
        if not data or len(data) > MAX_IMAGE_BYTES:
            continue
        ext = ".png" if data[:4] == b"\x89PNG" else ".webp" if data[8:12] == b"WEBP" else ".jpg"
        fp = folder / f"{prefix}-{i + 1}{ext}"
        fp.write_bytes(data)
        files.append(str(fp.relative_to(root)))
    return files


def collect(cfg, sc, adapter, log=print):
    name = sc["_name"]
    P = config_mod.paths(cfg, name, adapter.name)
    work = P["work"]
    shutil.rmtree(work, ignore_errors=True)
    (work / "img").mkdir(parents=True, exist_ok=True)
    state = load_json(P["state"], {"listings": []})
    changes = {"price": [], "gone": [], "rule": [], "reserved": [], "problems": []}
    mc = sc.get("market") or {}
    ready, skipped = [], 0
    try:
        market = update_market(cfg, sc, adapter, P, log)
        # flips: extra queries for working units clearly below the market median
        extra = [{"keyword": g["keyword"], "max_price": int(market[g["name"]]["median"] * market_settings(mc)["flip_ratio"])}
                 for g in mc.get("groups") or [] if g.get("flip") and g.get("keyword") and market.get(g["name"])]
        log(f"searching {adapter.name} ...")
        items, probs = search_all(cfg, sc, adapter, extra, log)
        changes["problems"] += probs
        if sc.get("track"):
            try:
                history.track(P["history"], sc, items.values(), log)
            except Exception as e:
                log(f"  tracking error: {e}")
        log(f"{len(items)} listings found, {adapter.requests} requests")

        reconcile(state, items, adapter, sc, changes, log)
        save_json(P["state"], state)

        known = {(l.get("sources") or {}).get(adapter.name) for l in state["listings"]}
        seen = load_json(P["seen"], {})
        cands, skipped = select(items, known, seen, market, sc, log)
        log(f"{len(cands)} new candidates for evaluation" + (f" ({skipped} postponed to the next run)" if skipped else ""))

        for it in cands:
            try:
                extra_info = adapter.details(it, int(sc.get("images", 1))) or {}
            except Blocked:
                raise
            except Exception:
                extra_info = {}
            img_urls = extra_info.pop("images", None) or it.get("_img_urls") or []
            for k, v in extra_info.items():
                if k == "attrs" and isinstance(v, dict):
                    it["attrs"].update(v)
                elif v not in (None, ""):
                    it[k] = v
            it["images"] = download_images(img_urls[:int(sc.get("images", 1))], work / "img", it["source_id"],
                                           cfg["_data"]) if int(sc.get("images", 1)) > 0 else []
            ready.append(it)
        if sc.get("track"):
            try:
                history.check_gone(P["history"], sc, adapter, log)
            except Blocked:
                raise
            except Exception as e:
                log(f"  tracking error: {e}")
    except Blocked as e:
        changes["problems"].append(f"{adapter.name} blocked: {e}. Run aborted, state not fully checked.")
        log(str(e))
        ready, skipped = [], 0

    existing = ["id | title | price | location"] + [
        " | ".join(str(x if x is not None else "") for x in (l.get("id"), l.get("title"), l.get("price"), l.get("location")))
        for l in state["listings"]]
    bs = int(sc.get("batch_size", 25))
    batches = [ready[i:i + bs] for i in range(0, len(ready), bs)]
    for n, b in enumerate(batches, 1):
        b = [{k: v for k, v in c.items() if not k.startswith("_") and v not in (None, "", [], {})} for c in b]
        save_json(work / f"candidates-{n}.json", {"date": clock.today_str(), "candidates": b,
                                                  "existing_listings": existing})
    save_json(work / "changes.json", {**changes, "skipped": skipped, "requests": adapter.requests,
                                      "batches": len(batches)})
    log(f"{len(batches)} batch(es) for evaluation, {adapter.requests} requests in total")
    return len(batches)


def apply_prefilter(work, log=print):
    """Drop what the prefilter model marked as obvious junk from the batches."""
    total = dropped_n = 0
    for cf in sorted(work.glob("candidates-*.json")):
        n = cf.stem.split("-")[1]
        data = load_json(cf, {})
        cands = data.get("candidates", [])
        total += len(cands)
        pf = load_json(work / f"prefilter-{n}.json", None)
        if not isinstance(pf, dict) or not isinstance(pf.get("drop"), list):
            log(f"prefilter batch {n}: no valid output, all {len(cands)} candidates stay")
            continue
        reasons = {str(d.get("source_id")): str(d.get("reason", ""))[:80] for d in pf["drop"] if isinstance(d, dict)}
        keep = [c for c in cands if c["source_id"] not in reasons]
        drop = [{"source_id": c["source_id"], "price": c.get("price"), "title": c.get("title"),
                 "reason": reasons[c["source_id"]]} for c in cands if c["source_id"] in reasons]
        data["candidates"] = keep
        save_json(cf, data)
        save_json(work / f"dropped-{n}.json", drop)
        if not keep:
            save_json(work / f"accepted-{n}.json", [])
        dropped_n += len(drop)
        log(f"prefilter batch {n}: {len(drop)} of {len(cands)} dropped")
    log(f"prefilter: {dropped_n} of {total} dropped, {total - dropped_n} go to evaluation")


def merge(cfg, sc, adapter_name, report_path, log=print):
    """Take the evaluations (accepted-N.json) into the state and write the report."""
    P = config_mod.paths(cfg, sc["_name"], adapter_name)
    work, today = P["work"], clock.today_str()
    state = load_json(P["state"], {"listings": []})
    changes = load_json(work / "changes.json", {})
    seen = load_json(P["seen"], {})
    ids = {l.get("id") for l in state["listings"]}
    added, merged, problems = [], [], list(changes.get("problems", []))

    for cf in sorted(work.glob("candidates-*.json")):
        n = cf.stem.split("-")[1]
        batch = load_json(cf, {}).get("candidates", [])
        acc = load_json(work / f"accepted-{n}.json", None)
        if isinstance(acc, dict):
            acc = acc.get("listings") or acc.get("accepted")
        if not isinstance(acc, list):
            problems.append(f"evaluation of batch {n} failed ({len(batch)} candidates, retried next run)")
            continue
        by_id = {c["source_id"]: c for c in batch}
        for a in acc:
            if not isinstance(a, dict):
                continue
            c = by_id.get(str(a.get("source_id") or ""))
            if not c:
                continue
            if a.get("merge_into"):
                tgt = next((l for l in state["listings"] if l.get("id") == a["merge_into"]), None)
                if tgt:
                    if c["url"] not in tgt.setdefault("urls", []):
                        tgt["urls"].append(c["url"])
                    tgt.setdefault("sources", {})[adapter_name] = c["source_id"]
                    tgt.setdefault("_urls_by_source", {})[adapter_name] = c["url"]
                    merged.append(tgt)
                continue
            lid = f"{adapter_name}-{c['source_id']}"
            if lid in ids:
                continue
            entry = {"id": lid, "source": adapter_name, "sources": {adapter_name: c["source_id"]},
                     "_urls_by_source": {adapter_name: c["url"]}, "urls": [c["url"]], "title": c["title"],
                     "price": c.get("price"), "price_history": [], "location": c.get("location"),
                     "first_seen": today, "last_seen": today}
            for k, v in a.items():
                if k not in PROTECTED:
                    entry[k] = v
            for k in CARRY:
                if c.get(k) is not None and k not in entry:
                    entry[k] = c[k]
            state["listings"].append(entry)
            ids.add(lid)
            added.append(entry)
        for c in batch:
            seen[c["source_id"]] = {"price": c.get("price"), "date": today}

    for df in sorted(work.glob("dropped-*.json")):
        for c in load_json(df, []):
            seen[c["source_id"]] = {"price": c.get("price"), "date": today}
    cutoff = str(clock.today() - timedelta(days=60))
    seen = {k: v for k, v in seen.items() if v.get("date", today) >= cutoff}
    save_json(P["seen"], seen)
    save_json(P["state"], state)

    lines = []
    if added:
        lines.append("**New**")
        for e in sorted(added, key=lambda x: -(num(x.get("score")) or 0)):
            lines.append(f"- [{e.get('title')}]({e['urls'][0]}) – {eur(e.get('price'))}, {e.get('location') or ''} – "
                         f"score {e.get('score', '?')}, tier {e.get('tier', '?')}: {e.get('summary', '')}")
    if changes.get("price"):
        lines += ([""] if lines else []) + ["**Price changes**"]
        for c in changes["price"]:
            lines.append(f"- [{c['title']}]({c['url']}): {eur(c['old'])} → {eur(c['new'])}")
    if changes.get("gone") or changes.get("rule"):
        lines += ([""] if lines else []) + ["**Gone**"]
        for l in changes.get("gone", []):
            lines.append(f"- {l.get('title')} ({eur(l.get('price'))}) – no longer online")
        for l in changes.get("rule", []):
            lines.append(f"- {l.get('title')} ({eur(l.get('price'))}) – no longer matches the criteria")
    if changes.get("reserved"):
        lines += ([""] if lines else []) + ["**Reserved**"]
        for l in changes["reserved"]:
            lines.append(f"- {l.get('title')}")
    if merged:
        lines.append(f"Duplicates merged: {len(merged)}")
    if changes.get("skipped"):
        lines.append(f"Note: {changes['skipped']} more candidates will be evaluated in the next run.")
    if problems:
        lines.append("**Problem:** " + "; ".join(problems))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n" if lines else "NO_CHANGES\n")
    gone = len(changes.get("gone", [])) + len(changes.get("rule", []))
    log(f"merged: {len(added)} new, {len(merged)} merged, {len(changes.get('price', []))} price changes, "
        f"{gone} gone, {len(problems)} problems")
    return len(added)
