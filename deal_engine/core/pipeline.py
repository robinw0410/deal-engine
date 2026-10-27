"""Adapter-neutral pipeline for one search and one adapter:

  collect   search, update market prices, reconcile the state (price changes, gone, reserved),
            optionally classify the titles of possible candidates with the LLM (classify_first),
            pick new candidates and write evaluation batches
  prefilter apply a cheap model's prefilter result to the batches (optional)
  merge     take the evaluations into the state and write a short markdown report

Work files per search and adapter in data/work/<search>/<adapter>/:
  candidates-N.json  {"date", "candidates": [...], "existing_listings": [...], "extra": {source_id: [fields]}}
  prefilter-N.json   {"drop": [{"source_id", "reason"}]}            (written by the prefilter model)
  accepted-N.json    [{"source_id", <evaluation fields>} | {"source_id", "merge_into"}]
  changes.json       price changes, gone, reserved, problems of this run
"""
import re
import shutil
import urllib.request
from datetime import timedelta

from ..adapters.base import Blocked, check_result
from . import classify, clock, history
from . import config as config_mod
from . import locale as locale_mod
from .config import ConfigError
from .filters import fields_failed, has_signal, passes, title_failed
from .groups import bundle_qty, from_classification, is_accessory, is_bundle_group, match_group
from .listing import EXTRA_NAME, RESERVED, normalize, shipping_unknown
from .market import due as market_due, refresh as market_refresh, resale_from_ask, settings as market_settings
from .util import load_json, num, save_json

# fields copied from a candidate into a new state entry (if the evaluation did not set them);
# extra fields of the listing (km, year, ...) are carried as well
CARRY = ("distance_km", "shipping_possible", "shipping_cost_eur", "shipping_unknown", "shipping_note", "private",
         "condition", "auction_end", "best_offer", "market_median", "market_group", "market_n",
         "market_resale_estimate")
UNKNOWN_SHIPPING_COST = 15   # default for shipping.unknown_cost
# fields the evaluation must not overwrite
PROTECTED = {"id", "urls", "url", "source", "source_id", "sources", "price", "price_history", "first_seen",
             "last_seen", "merge_into"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# fields of the listing format that details() may set or refine
DETAIL_FIELDS = {"description", "location", "condition", "shipping_cost_eur", "shipping_possible", "distance_km",
                 "private", "auction_end", "best_offer"}


def details_key_ok(it, k):
    """details() may set format fields it refines and extra fields under the same rules as normalize()."""
    if k in DETAIL_FIELDS:
        return True
    return bool(EXTRA_NAME.match(str(k))) and k not in RESERVED and not k.startswith("market_") \
        and k not in ("source", "source_id", "url", "title", "price", "status", "images", "attrs") \
        and (k in it["_extra"] or k not in it)


def _image_ext(data):
    """File extension for image bytes, or None if they are no JPEG/PNG/WebP/GIF."""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"\x89PNG":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:4] == b"GIF8":
        return ".gif"
    return None


def _search(adapter, query, home, road_factor, items, problems, loc):
    try:
        raw = adapter.search(query)
    except (Blocked, ConfigError):
        raise
    except Exception as e:
        problems.append(loc.t("prob.search", adapter=adapter.name, query=query.get("keyword") or "*", error=e))
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
        problems.append(loc.t("prob.invalid", adapter=adapter.name, n=bad))
    return len(raw)


def search_all(cfg, sc, adapter, extra=(), log=print):
    """All configured queries of a search, deduplicated by source_id."""
    home = config_mod.home(cfg)
    rf = float((cfg.get("location") or {}).get("road_factor", 1.3))
    flt = sc.get("filters") or {}
    loc = locale_mod.for_search(cfg, sc)
    kws = (sc.get(adapter.name) or {}).get("keywords") or sc.get("keywords") or []
    queries = [{"keyword": k} for k in kws] or [{"keyword": None}]
    items, problems = {}, []
    for q in list(queries) + list(extra):
        q = {"min_price": flt.get("min_price"), "max_price": flt.get("max_price"), **q}
        n = _search(adapter, q, home, rf, items, problems, loc)
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
    loc = locale_mod.for_search(cfg, sc)
    by_group, problems = {}, []
    for g in groups:
        items = {}
        _search(adapter, {"keyword": g.get("keyword"), "max_price": g.get("max")}, home, rf, items, problems, loc)
        if sc.get("track"):
            try:
                history.track(P["history"], sc, items.values(), log=lambda s: None)
            except Exception as e:   # tracking must never break a run
                log(f"  tracking error: {e}")
        by_group[g["name"]] = list(items.values())
    new = market_refresh(market, by_group, groups, sc.get("filters") or {}, mc, log, loc)
    save_json(P["market"], new)
    return new


def reconcile(state, items, adapter, sc, changes, log=print, loc=None):
    """Compare the stored listings of this adapter with the current results."""
    loc = loc or locale_mod.get(sc.get("_locale"))
    flt = sc.get("filters") or {}
    today = clock.today_str()
    keep, title_rule = [], []
    for l in state.get("listings", []):
        sources = l.get("sources") or {}
        sid = sources.get(adapter.name)
        if not sid:
            keep.append(l)
            continue
        # hard limits (e.g. after a rule change)
        p = num(l.get("price"))
        too_expensive = flt.get("max_price") is not None and p is not None and p > flt["max_price"]
        if (too_expensive or fields_failed(l, flt)) and len(sources) == 1:
            changes["rule"].append(l)
            continue
        # title regexes: a listing that got into the state under an older, looser regex must not stay
        # there; without a stored title there is nothing to judge, so it stays (mass guard below)
        if l.get("title") and len(sources) == 1 and title_failed(l["title"], flt):
            title_rule.append(l)
            continue
        it = items.get(sid)
        newp = None
        if it is not None:
            st, newp = it["status"], it.get("price")
        else:
            try:
                st, newp = check_result(adapter.check(sid))
            except (Blocked, ConfigError):
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
        if (st == "reserved" or loc.reserved_title.search(title)) and l.get("status") != "reserved":
            l["status"] = "reserved"
            l["score"] = min(num(l.get("score")) or 3, 3)
            changes["reserved"].append(l)
        oldp = num(l.get("price"))
        if newp is not None and oldp is None:
            l["price"] = newp   # no price stored so far: take it, nothing to compare
        elif newp is not None and oldp is not None and abs(newp - oldp) >= 1:
            l.setdefault("price_history", []).append({"date": today, "price": oldp})
            l["price"] = newp
            changes["price"].append({"title": l.get("title"), "url": (l.get("urls") or [""])[0],
                                     "old": oldp, "new": newp})
        keep.append(l)
    # a sudden mass disappearance is far more likely an outage or a changed source than reality
    n_total = sum(1 for l in state.get("listings", []) if (l.get("sources") or {}).get(adapter.name))
    if len(changes["gone"]) > max(5, 0.3 * n_total):
        changes["problems"].append(loc.t("prob.offline", n=len(changes["gone"]), total=n_total, adapter=adapter.name))
        for l in changes["gone"]:
            l["last_check_failed"] = today
        keep += changes["gone"]
        changes["gone"] = []
    # same guard for the title regexes: one too broad exclude (or too narrow include) must not wipe
    # the adapter's whole stock in one run
    if len(title_rule) > max(5, 0.3 * n_total):
        changes["problems"].append(loc.t("prob.title_rule", n=len(title_rule), total=n_total, adapter=adapter.name))
        keep += title_rule
    else:
        changes["rule"] += title_rule
    state["listings"] = keep


def mark_shipping(it, unknown_cost, loc=None):
    """Flag (or unflag) an item whose shipping cost is unknown; returns the cost to assume."""
    if shipping_unknown(it):
        it["shipping_unknown"] = True
        it["shipping_note"] = (loc or locale_mod.get("en")).t("ship.unknown", cost=f"{unknown_cost:g}")
        return float(unknown_cost)
    it.pop("shipping_unknown", None)
    it.pop("shipping_note", None)
    return it.get("shipping_cost_eur") or 0


def max_new(sc, adapter_name=None):
    """max_new_per_run of the adapter (sc[adapter].max_new_per_run), otherwise of the search."""
    own = (sc.get(adapter_name) or {}).get("max_new_per_run") if adapter_name else None
    return int(own if own is not None else sc.get("max_new_per_run", 50))


def considered(sid, it, known, seen, flt):
    """The listing is looked at by select() at all: active, passes the filters, not in the state, and
    not seen before (or seen, but 10 % cheaper now)."""
    if sid in known or it["status"] != "active" or not passes(it, flt):
        return False
    prev = seen.get(sid)
    return not prev or (it.get("price") is not None and bool(prev.get("price")) and it["price"] <= prev["price"] * 0.9)


def select(items, known, seen, market, sc, log=print, unknown_cost=UNKNOWN_SHIPPING_COST, adapter_name=None,
           state_listings=(), loc=None, classified=None):
    """New candidates: pass the filters, are not known, are cheap enough relative to the market.
    Unknown shipping costs count as unknown_cost, never as 0. Returns (candidates, postponed).

    classified: {source_id: (group name, qty, kind)} from the LLM classification; if plausible
    (groups.from_classification: a named group's match regex hits the title) it replaces the word
    rules for that listing: device/bundle -> that group (qty for controller-like groups),
    accessory -> skipped, other -> no group (no market comparison). Implausible: word rules."""
    loc = loc or locale_mod.get(sc.get("_locale"))
    flt = sc.get("filters") or {}
    mc = sc.get("market") or {}
    s = market_settings(mc)
    groups = mc.get("groups") or []
    classified = classified or {}
    cands, too_expensive, no_signal, n_cls = [], 0, 0, 0
    for sid, it in items.items():
        if not considered(sid, it, known, seen, flt):
            continue
        sig = has_signal(it, flt)
        c = from_classification(it["title"], classified.get(sid), groups)
        if c:
            kind, g, cq = c
            if kind == "accessory":
                n_cls += 1
                continue
            qty = cq if is_bundle_group(g) else 1
        else:
            g = match_group(it["title"], groups) if groups else None
            if g and is_accessory(it["title"], mc.get("accessory_regex"), loc):
                continue   # "case for <device>" is not a deal on the device
            qty = None
        m = market.get(g["name"]) if g else None
        ship = mark_shipping(it, unknown_cost, loc)
        if m:
            it["market_group"], it["market_median"], it["market_n"] = g["name"], m["median"], m["n"]
            it["market_resale_estimate"] = resale_from_ask(m, s["sale_factor"])
            ratio = s["max_price_ratio"] if sig is None else s["defect_price_ratio"] if sig else s["flip_ratio"]
            total = (it.get("price") or 0) + ship
            if qty is None:
                qty = bundle_qty(it["title"], g, loc)   # "3 controllers" is compared with 3 x the unit median
            if it.get("price") is not None and total > m["median"] * qty * float(ratio):
                too_expensive += 1
                continue
        elif sig is False:
            no_signal += 1   # no defect signal and no market price to judge a flip
            continue
        cands.append(it)
    if n_cls:
        log(f"{n_cls} listings skipped as accessories (LLM classification)")
    if no_signal:
        log(f"{no_signal} listings without defect signal and without market price skipped")
    if too_expensive:
        log(f"{too_expensive} candidates above the market price threshold skipped")
    cands.sort(key=lambda x: (x.get("_published") or "", x["source_id"]), reverse=True)

    # quotas (e.g. phones): at most max_new_per_run per run, and with max_share at most this share
    # of the state (counting the new ones)
    n_state, capped = len(state_listings), 0
    for cap in sc.get("category_caps") or []:
        rx = cap["regex"]
        allowed = int(cap.get("max_new_per_run", 5))
        if cap.get("max_share") is not None:
            # approximation: share of the state as if max_new_per_run matching listings were added
            # (exact shares would block everything while the state is still small)
            in_state = sum(1 for l in state_listings if re.search(rx, str(l.get("title") or ""), re.I))
            allowed = min(allowed, max(0, int(float(cap["max_share"]) * (n_state + allowed)) - in_state))
        kept, n_cap = [], 0
        for it in cands:
            if re.search(rx, it["title"], re.I):
                if n_cap >= allowed:
                    continue
                n_cap += 1
            kept.append(it)
        if len(kept) < len(cands):
            log(f"quota '{cap.get('name', rx)}': {len(cands) - len(kept)} candidates postponed")
            capped += len(cands) - len(kept)
        cands = kept
    limit = max_new(sc, adapter_name)
    return cands[:limit], max(0, len(cands) - limit) + capped


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "deal-engine (image fetch for evaluation)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if not str(r.headers.get("Content-Type", "")).startswith("image/"):
            return None
        return r.read(MAX_IMAGE_BYTES + 1)


def download_images(urls, folder, prefix, root, adapter=None):
    """Download listing photos for the evaluator (only http/https, size-limited). Uses the adapter's
    fetch_image() if it has one (its own rate and headers)."""
    files = []
    own = adapter is not None and adapter.has_fetch_image()
    for i, u in enumerate(urls):
        if not re.match(r"https?://", str(u)):
            continue
        try:
            data = adapter.fetch_image(u) if own else _fetch(u)
        except Blocked:
            raise
        except Exception:
            continue
        if not data or len(data) > MAX_IMAGE_BYTES:
            continue
        ext = _image_ext(data)
        if not ext:
            continue
        fp = folder / f"{prefix}-{i + 1}{ext}"
        fp.write_bytes(data)
        files.append(str(fp.relative_to(root)))
    return files


def collect(cfg, sc, adapter, log=print, classify_first=False, classify_budget=None):
    """Returns {"found", "candidates", "rejected", "postponed", "batches", "requests", "blocked", "problems"}.

    classify_first: classify the titles of the listings select() will look at with the LLM before
    selecting (core/classify.py, needs classify enabled in the search); run_search sets it with the
    LLM evaluator only. If the model is unavailable, the word rules decide. classify_budget: the
    classify.Budget of the search run (max_per_run for all adapters and the step after the merge)."""
    name = sc["_name"]
    loc = locale_mod.for_search(cfg, sc)
    P = config_mod.paths(cfg, name, adapter.name)
    work = P["work"]
    shutil.rmtree(work, ignore_errors=True)
    (work / "img").mkdir(parents=True, exist_ok=True)
    state = load_json(P["state"], {"listings": []})
    changes = {"price": [], "gone": [], "rule": [], "reserved": [], "problems": []}
    mc = sc.get("market") or {}
    ready, skipped, rejected, found, blocked = [], 0, 0, 0, None
    try:
        market = update_market(cfg, sc, adapter, P, log)
        # flips: extra queries for working units clearly below the market median
        extra = [{"keyword": g["keyword"], "max_price": int(market[g["name"]]["median"] * market_settings(mc)["flip_ratio"])}
                 for g in mc.get("groups") or [] if g.get("flip") and g.get("keyword") and market.get(g["name"])]
        log(f"searching {adapter.name} ...")
        items, probs = search_all(cfg, sc, adapter, extra, log)
        found = len(items)
        changes["problems"] += probs
        if sc.get("track"):
            try:
                history.track(P["history"], sc, items.values(), log)
            except Exception as e:
                log(f"  tracking error: {e}")
        log(f"{len(items)} listings found, {adapter.requests} requests")

        reconcile(state, items, adapter, sc, changes, log, loc)
        save_json(P["state"], state)

        known = {(l.get("sources") or {}).get(adapter.name) for l in state["listings"]}
        seen = load_json(P["seen"], {})
        unknown_cost = float((cfg.get("shipping") or {}).get("unknown_cost", UNKNOWN_SHIPPING_COST))
        classified = {}
        if classify_first and classify.settings(sc) is not None and (mc.get("groups") or []):
            flt = sc.get("filters") or {}
            titles = {history.uid(it): it["title"] for sid, it in items.items() if considered(sid, it, known, seen, flt)}
            try:
                by_uid = classify.preselect(cfg, sc, titles, P["history"], log, budget=classify_budget)
            except ConfigError:
                raise
            except Exception as e:   # never break a run over the classification: word rules stay
                log(f"  classification before selection failed, word rules stay: {type(e).__name__}: {e}")
                by_uid = {}
            classified = {it["source_id"]: by_uid[history.uid(it)] for it in items.values() if history.uid(it) in by_uid}
        cands, skipped = select(items, known, seen, market, sc, log, unknown_cost, adapter.name,
                                state["listings"], loc, classified=classified)
        log(f"{len(cands)} new candidates for evaluation" + (f" ({skipped} postponed to the next run)" if skipped else ""))

        n_img = int(sc.get("images", 1))
        for it in cands:
            try:
                extra_info = adapter.details(it, n_img) or {}
            except (Blocked, ConfigError):
                raise
            except Exception:
                extra_info = {}
            reason = extra_info.pop("reject", None) or (
                extra_info.get("status") if extra_info.get("status") in ("reserved", "gone") else None)
            if reason:
                rejected += 1
                log(f"  {it['source_id']} dropped before evaluation: {reason}")
                continue
            extra_info.pop("status", None)
            img_urls = extra_info.pop("images", None) or it.get("_img_urls") or []
            for k, v in extra_info.items():
                if k == "attrs" and isinstance(v, dict):
                    it["attrs"].update(v)
                elif v in (None, "") or not details_key_ok(it, k):
                    continue
                else:
                    it[k] = v
                    if k not in DETAIL_FIELDS and k not in it["_extra"]:
                        it["_extra"].append(k)
            mark_shipping(it, unknown_cost, loc)   # details may have delivered the shipping cost
            it["images"] = download_images(img_urls[:n_img], work / "img", it["source_id"], cfg["_data"],
                                           adapter) if n_img > 0 else []
            ready.append(it)
        if sc.get("track"):
            try:
                history.check_gone(P["history"], sc, adapter, log)
            except (Blocked, ConfigError):
                raise
            except Exception as e:
                log(f"  tracking error: {e}")
    except Blocked as e:
        blocked = str(e)
        changes["problems"].append(loc.t("prob.blocked", adapter=adapter.name, error=e))
        log(str(e))
        ready, skipped = [], 0

    existing = ["id | title | price | location"] + [
        " | ".join(str(x if x is not None else "") for x in (l.get("id"), l.get("title"), l.get("price"), l.get("location")))
        for l in state["listings"]]
    bs = int(sc.get("batch_size", 25))
    batches = [ready[i:i + bs] for i in range(0, len(ready), bs)]
    for n, b in enumerate(batches, 1):
        extra = {c["source_id"]: c["_extra"] for c in b if c.get("_extra")}
        b = [{k: v for k, v in c.items() if not k.startswith("_") and v not in (None, "", [], {})} for c in b]
        save_json(work / f"candidates-{n}.json", {"date": clock.today_str(), "candidates": b,
                                                  "existing_listings": existing, "extra": extra})
    save_json(work / "changes.json", {**changes, "skipped": skipped, "requests": adapter.requests,
                                      "batches": len(batches)})
    log(f"{len(batches)} batch(es) for evaluation, {adapter.requests} requests in total")
    return {"found": found, "candidates": len(ready), "rejected": rejected, "postponed": skipped,
            "batches": len(batches), "requests": adapter.requests, "blocked": blocked,
            "problems": list(changes["problems"])}


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
    """Take the evaluations (accepted-N.json) into the state and write the report.
    Returns {"added", "merged", "price_changes", "gone", "reserved", "failed_batches", "problems"}."""
    loc = locale_mod.for_search(cfg, sc)
    P = config_mod.paths(cfg, sc["_name"], adapter_name)
    work, today = P["work"], clock.today_str()
    state = load_json(P["state"], {"listings": []})
    changes = load_json(work / "changes.json", {})
    seen = load_json(P["seen"], {})
    ids = {l.get("id") for l in state["listings"]}
    added, merged, problems, failed = [], [], list(changes.get("problems", [])), 0

    for cf in sorted(work.glob("candidates-*.json")):
        n = cf.stem.split("-")[1]
        data = load_json(cf, {})
        batch, extra = data.get("candidates", []), data.get("extra") or {}
        acc = load_json(work / f"accepted-{n}.json", None)
        if isinstance(acc, dict):
            acc = acc.get("listings") or acc.get("accepted")
        if not isinstance(acc, list):
            problems.append(loc.t("prob.eval", n=n, count=len(batch)))
            failed += 1
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
            for k in (*CARRY, *extra.get(c["source_id"], [])):
                if c.get(k) is not None and k not in entry:
                    entry[k] = c[k]
            # field filters also look into attrs; keep those values so the filter still works on the state
            for k in ((sc.get("filters") or {}).get("fields") or {}):
                if k not in entry and (c.get("attrs") or {}).get(k) is not None:
                    entry[k] = c["attrs"][k]
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

    eur = loc.eur
    lines = []
    if added:
        lines.append(f"**{loc.t('rep.new')}**")
        for e in sorted(added, key=lambda x: -(num(x.get("score")) or 0)):
            lines.append(loc.t("rep.line", title=e.get("title"), url=e["urls"][0], price=eur(e.get("price")),
                               location=e.get("location") or "", score=e.get("score", "?"), tier=e.get("tier", "?"),
                               summary=e.get("summary", "")))
    if changes.get("price"):
        lines += ([""] if lines else []) + [f"**{loc.t('rep.price')}**"]
        for c in changes["price"]:
            lines.append(f"- [{c['title']}]({c['url']}): {eur(c['old'])} → {eur(c['new'])}")
    if changes.get("gone") or changes.get("rule"):
        lines += ([""] if lines else []) + [f"**{loc.t('rep.gone')}**"]
        for l in changes.get("gone", []):
            lines.append(loc.t("rep.gone_offline", title=l.get("title"), price=eur(l.get("price"))))
        for l in changes.get("rule", []):
            lines.append(loc.t("rep.gone_rule", title=l.get("title"), price=eur(l.get("price"))))
    if changes.get("reserved"):
        lines += ([""] if lines else []) + [f"**{loc.t('rep.reserved')}**"]
        for l in changes["reserved"]:
            lines.append(f"- {l.get('title')}")
    if merged:
        lines.append(loc.t("rep.merged", n=len(merged)))
    if changes.get("skipped"):
        lines.append(loc.t("rep.skipped", n=changes["skipped"]))
    if problems:
        lines.append(f"**{loc.t('rep.problem')}:** " + "; ".join(problems))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n" if lines else "NO_CHANGES\n")
    gone = len(changes.get("gone", [])) + len(changes.get("rule", []))
    log(f"merged: {len(added)} new, {len(merged)} merged, {len(changes.get('price', []))} price changes, "
        f"{gone} gone, {len(problems)} problems")
    return {"added": len(added), "merged": len(merged), "price_changes": len(changes.get("price", [])),
            "gone": gone, "reserved": len(changes.get("reserved", [])), "failed_batches": failed,
            "problems": problems}
