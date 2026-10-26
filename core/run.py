"""Runs complete searches: per adapter collect -> prefilter -> evaluate -> merge, then
classify -> insights -> score -> render.

The evaluator is either "claude" (Claude Code CLI, see core/llm.py) or a callable
evaluator(work_dir, cfg, sc) that writes accepted-N.json files (the demo uses its own).
"""
import json

import adapters

from . import classify, insights, llm, pipeline, score
from . import config as config_mod
from .util import load_json, save_json


def _valid_state(p):
    try:
        return isinstance(json.loads(p.read_text()).get("listings"), list)
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return False


def _profile(sc):
    p = sc.get("profile")
    return config_mod.resolve(p).read_text() if p else ""


def llm_prefilter(cfg, sc, work, log=print):
    model = (cfg.get("llm") or {}).get("prefilter_model", "haiku")
    for cf in sorted(work.glob("candidates-*.json")):
        pf = cf.with_name(cf.name.replace("candidates-", "prefilter-"))
        text = _profile(sc) + "\n\n" + llm.prompt("prefilter", CANDIDATES=cf, PREFILTER=pf)
        log(f"  prefilter {cf.name} ({model})")
        try:
            llm.run(cfg, text, model, max_turns=30, timeout_min=20, cwd=cfg["_data"], log_file=work / "llm.log")
        except RuntimeError as e:
            log(f"  prefilter failed, all candidates stay: {e}")
    pipeline.apply_prefilter(work, log)


def llm_evaluate(cfg, sc, work, log=print):
    model = (sc.get("llm") or {}).get("eval_model") or (cfg.get("llm") or {}).get("eval_model", "sonnet")
    parts = ""
    if sc.get("parts_catalog"):   # parts catalogue + stock from the deal list
        from deals.deals_server import prompt_block
        parts = prompt_block(cfg)
    for cf in sorted(work.glob("candidates-*.json")):
        acc = cf.with_name(cf.name.replace("candidates-", "accepted-"))
        if acc.exists():
            continue   # batch empty after prefilter
        text = _profile(sc) + "\n\n" + llm.prompt("evaluate", CANDIDATES=cf, ACCEPTED=acc,
                                                  DATE=load_json(cf, {}).get("date", "")) + parts
        log(f"  evaluating {cf.name} ({model})")
        try:
            llm.run(cfg, text, model, max_turns=150, cwd=cfg["_data"], log_file=work / "llm.log")
        except RuntimeError as e:
            log(f"  evaluation of {cf.name} failed: {e}")


def run_search(cfg, name, evaluator="claude", render=True, log=print):
    sc = config_mod.search(cfg, name)
    P = config_mod.paths(cfg, name)
    if not P["state"].exists():
        save_json(P["state"], {"listings": []})
    parts, failed = [], []
    for an in sc["adapters"]:
        backup = P["state"].read_text()
        part = P["reports"] / f"{name}-part-{an}.md"
        part.unlink(missing_ok=True)
        try:
            adapter = adapters.create(an, cfg, sc)
            work = config_mod.paths(cfg, name, an)["work"]
            n = pipeline.collect(cfg, sc, adapter, log)
            if n:
                if evaluator == "claude":
                    if sc.get("prefilter"):
                        llm_prefilter(cfg, sc, work, log)
                    llm_evaluate(cfg, sc, work, log)
                else:
                    evaluator(work, cfg, sc)
            pipeline.merge(cfg, sc, an, part, log)
            parts.append((an, part))
        except (Exception, SystemExit) as e:
            log(f"{name} / {an} failed: {e}")
            failed.append(an)
        if not _valid_state(P["state"]):
            P["state"].write_text(backup)

    # combine the partial reports
    out, changed = [], False
    for an, part in parts:
        txt = part.read_text() if part.exists() else ""
        if txt.strip() and not txt.startswith("NO_CHANGES"):
            changed = True
            out += [f"## {an}", "", txt.strip(), ""]
        part.unlink(missing_ok=True)
    if failed:
        changed = True
        out.append(f"**Problem:** run failed for {', '.join(failed)}")
    P["report"].parent.mkdir(parents=True, exist_ok=True)
    P["report"].write_text("\n".join(out) + "\n" if changed else "NO_CHANGES\n")

    if parts:
        if evaluator == "claude":
            classify.apply(cfg, sc, P, log)
        insights.apply(cfg, sc, P, log)
        score.apply(cfg, sc, P["state"], log=log)
        if render:
            from web import render as web_render
            web_render.render(cfg, name, log)
    return not failed
