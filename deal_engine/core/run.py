"""Runs complete searches: per adapter collect (with the LLM evaluator and classify enabled: titles
classified before the candidate selection) -> prefilter -> evaluate -> merge, then
classify -> insights -> score -> render.

The evaluator is either "claude" (Claude Code CLI, see deal_engine/core/llm.py) or a callable
evaluator(work_dir, cfg, sc) that writes accepted-N.json files (the demo uses its own).

run_search() returns a RunResult with one AdapterResult per adapter:
  status  "ok"       collected, evaluated and merged without problems
          "partial"  ran, but with problems (blocked, an evaluation batch failed, failed queries)
          "failed"   did not run (reason "config_error": unknown adapter, missing credentials ...;
                     "error": unexpected exception)
"""
import json
from dataclasses import asdict, dataclass, field

from .. import adapters
from . import classify, insights, llm, pipeline, score
from . import config as config_mod
from . import locale as locale_mod
from .config import ConfigError
from .util import load_json, save_json


@dataclass
class AdapterResult:
    name: str
    status: str = "ok"          # ok | partial | failed
    reason: str = ""            # "" | blocked | evaluation_failed | problems | config_error | error
    error: str = ""             # message for failed/partial
    found: int = 0
    candidates: int = 0
    rejected: int = 0
    postponed: int = 0
    discarded: int = 0          # postponed candidates beyond the backlog (written to seen)
    added: int = 0
    merged: int = 0
    price_changes: int = 0
    gone: int = 0
    requests: int = 0
    problems: list = field(default_factory=list)

    @property
    def ok(self):
        return self.status == "ok"


@dataclass
class RunResult:
    search: str
    adapters: list = field(default_factory=list)
    report: str = ""
    changed: bool = False
    error: str = ""             # a step after the merge failed (classify, insights, score, render)

    @property
    def ok(self):
        return not self.error and all(a.status == "ok" for a in self.adapters)

    @property
    def failed(self):
        return [a for a in self.adapters if a.status == "failed"]

    def __bool__(self):
        return self.ok

    def to_dict(self):
        return {**asdict(self), "ok": self.ok}


def _valid_state(p):
    try:
        return isinstance(json.loads(p.read_text()).get("listings"), list)
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return False


def _profile(cfg, sc):
    p = sc.get("profile")
    if not p:
        return ""
    q = config_mod.resolve(p, cfg)
    if not q.exists():
        raise ConfigError(f"search '{sc['_name']}': profile not found: {q}")
    return q.read_text()


def llm_prefilter(cfg, sc, work, log=print):
    model = (sc.get("llm") or {}).get("prefilter_model") or (cfg.get("llm") or {}).get("prefilter_model", "haiku")
    for cf in sorted(work.glob("candidates-*.json")):
        pf = cf.with_name(cf.name.replace("candidates-", "prefilter-"))
        text = _profile(cfg, sc) + "\n\n" + llm.prompt(cfg, sc, "prefilter", CANDIDATES=cf, PREFILTER=pf)
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
        from ..deals.deals_server import prompt_block
        parts = prompt_block(cfg, locale_mod.for_search(cfg, sc))
    for cf in sorted(work.glob("candidates-*.json")):
        acc = cf.with_name(cf.name.replace("candidates-", "accepted-"))
        if acc.exists():
            continue   # batch empty after prefilter
        text = _profile(cfg, sc) + "\n\n" + llm.prompt(cfg, sc, "evaluate", CANDIDATES=cf, ACCEPTED=acc,
                                                       DATE=load_json(cf, {}).get("date", "")) + parts
        log(f"  evaluating {cf.name} ({model})")
        try:
            llm.run(cfg, text, model, max_turns=150, cwd=cfg["_data"], log_file=work / "llm.log")
        except RuntimeError as e:
            log(f"  evaluation of {cf.name} failed: {e}")


def run_search(cfg, name, evaluator="claude", render=True, log=print):
    sc = config_mod.search(cfg, name)
    loc = locale_mod.for_search(cfg, sc)
    P = config_mod.paths(cfg, name)
    # check what can only fail later (score hooks, page config) before anything is collected
    score.load_hooks(score.settings(cfg, sc))
    if render:
        from ..web import render as web_render
        web_render.cfg_for(name, sc, cfg)
    if not P["state"].exists():
        save_json(P["state"], {"listings": []})
    result = RunResult(search=name)
    parts = []
    # classify.max_per_run counts for the whole search run: all adapters and the step after the merge
    cls_budget = classify.budget(sc)
    for an in sc["adapters"]:
        ar = AdapterResult(name=an)
        result.adapters.append(ar)
        backup = P["state"].read_text()
        part = P["reports"] / f"{name}-part-{an}.md"
        part.unlink(missing_ok=True)
        try:
            adapter = adapters.create(an, cfg, sc)
        except ConfigError as e:
            ar.status, ar.reason, ar.error = "failed", "config_error", str(e)
            log(f"{name} / {an}: {e}")
            continue
        except Exception as e:   # a broken adapter must not stop the other adapters
            ar.status, ar.reason, ar.error = "failed", "error", f"{type(e).__name__}: {e}"
            log(f"{name} / {an}: adapter cannot be created: {ar.error}")
            continue
        try:
            work = config_mod.paths(cfg, name, an)["work"]
            # with the LLM evaluator, titles are classified before the candidate selection
            classify_first = evaluator == "claude" and classify.settings(sc) is not None
            c = pipeline.collect(cfg, sc, adapter, log, classify_first=classify_first, classify_budget=cls_budget)
            for k in ("found", "candidates", "rejected", "postponed", "requests"):
                setattr(ar, k, c[k])
            ar.discarded = c.get("discarded", 0)
            if c["batches"]:
                if evaluator == "claude":
                    if sc.get("prefilter"):
                        llm_prefilter(cfg, sc, work, log)
                    llm_evaluate(cfg, sc, work, log)
                else:
                    evaluator(work, cfg, sc)
            m = pipeline.merge(cfg, sc, an, part, log)
            for k in ("added", "merged", "price_changes", "gone"):
                setattr(ar, k, m[k])
            ar.problems = m["problems"]
            if c["blocked"]:
                ar.status, ar.reason, ar.error = "partial", "blocked", c["blocked"]
            elif m["failed_batches"]:
                ar.status, ar.reason = "partial", "evaluation_failed"
                ar.error = f"{m['failed_batches']} evaluation batch(es) failed"
            elif m["problems"]:
                ar.status, ar.reason, ar.error = "partial", "problems", "; ".join(m["problems"])[:500]
            parts.append((an, part))
        except ConfigError as e:
            ar.status, ar.reason, ar.error = "failed", "config_error", str(e)
            log(f"{name} / {an}: {e}")
        except Exception as e:
            ar.status, ar.reason, ar.error = "failed", "error", f"{type(e).__name__}: {e}"
            log(f"{name} / {an} failed: {ar.error}")
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
    for a in result.failed:
        changed = True
        out.append(f"**{loc.t('rep.problem')}:** {a.name}: {a.error}")
    P["report"].parent.mkdir(parents=True, exist_ok=True)
    P["report"].write_text("\n".join(out) + "\n" if changed else "NO_CHANGES\n")
    result.report, result.changed = str(P["report"]), changed

    if parts:
        try:
            if evaluator == "claude":
                classify.apply(cfg, sc, P, log, budget=cls_budget)
            insights.apply(cfg, sc, P, log)
            score.apply(cfg, sc, P["state"], log=log)
            if render:
                web_render.render(cfg, name, log)
        except Exception as e:   # the merged state is kept; the step is reported
            result.error = f"{type(e).__name__}: {e}"
            log(f"{name}: after the merge: {result.error}")
    return result
