"""Command line interface.

  python -m deal_engine run [search ...]            run searches (default: all), evaluator = Claude Code CLI
  python -m deal_engine run --evaluator demo ...    use the demo evaluator (no LLM, only for demo data)
  python -m deal_engine score <search> [--show]     recompute scores (--show: print, don't save)
  python -m deal_engine render [search ...]         render the HTML pages
  python -m deal_engine history [search]            tracking statistics per group
  python -m deal_engine validate <file.json>        check a listings file against docs/listing-format.md
  python -m deal_engine adapters                    list the adapters this config can use

Options: --config PATH (default: $DEAL_ENGINE_CONFIG, ./config.yaml, ./config.example.yaml)
run --json PATH writes the structured results (per search and adapter) to a file.
Exit codes: 0 ok, 1 a search or adapter had problems or failed, 2 configuration error.
"""
import argparse
import json
import sys

from .core import config as config_mod


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m deal_engine", description="deal-engine")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("searches", nargs="*")
    r.add_argument("--evaluator", default="claude", choices=["claude", "demo"])
    r.add_argument("--json", help="write the structured results to this file")
    sub.add_parser("adapters")
    s = sub.add_parser("score")
    s.add_argument("search")
    s.add_argument("--show", action="store_true")
    w = sub.add_parser("render")
    w.add_argument("searches", nargs="*")
    h = sub.add_parser("history")
    h.add_argument("search", nargs="?")
    v = sub.add_parser("validate")
    v.add_argument("file")
    a = ap.parse_args(argv)

    if a.cmd == "validate":
        from .core.listing import normalize
        data = json.loads(open(a.file).read())
        rows = data.get("listings", []) if isinstance(data, dict) else data
        bad = 0
        for i, row in enumerate(rows):
            try:
                normalize(row, "check")
            except ValueError as e:
                bad += 1
                print(f"#{i}: {e}")
        print(f"{len(rows) - bad} valid, {bad} invalid")
        return 1 if bad else 0

    try:
        return _with_config(a)
    except config_mod.ConfigError as e:
        print(f"configuration error: {e}", file=sys.stderr)
        return 2


def _with_config(a):
    cfg = config_mod.load(a.config)
    if a.cmd == "adapters":
        from . import adapters
        for name, where in sorted(adapters.available(cfg).items()):
            print(f"{name:20} {where}")
        return 0
    if a.cmd == "run":
        from .core.run import run_search
        evaluator = a.evaluator
        if evaluator == "demo":
            from .demo.evaluator import evaluate
            evaluator = evaluate
        results, config_errors = [], 0
        for name in a.searches or config_mod.search_names(cfg):
            try:
                results.append(run_search(cfg, name, evaluator))
            except config_mod.ConfigError as e:   # this search cannot run; the others still do
                print(f"{name}: configuration error: {e}", file=sys.stderr)
                config_errors += 1
        for res in results:
            for ar in res.adapters:
                line = f"{res.search} / {ar.name}: {ar.status}"
                if ar.status != "ok":
                    line += f" ({ar.reason}) {ar.error}"
                else:
                    line += f", {ar.found} found, {ar.candidates} candidates, {ar.added} new"
                print(line, file=sys.stderr if ar.status == "failed" else sys.stdout)
            if res.error:
                print(f"{res.search}: {res.error}", file=sys.stderr)
        if a.json:
            with open(a.json, "w") as f:
                json.dump([r.to_dict() for r in results], f, ensure_ascii=False, indent=1)
        if config_errors or any(ar.reason == "config_error" for r in results for ar in r.adapters):
            return 2
        return 0 if all(results) else 1
    if a.cmd == "score":
        from .core import score
        sc = config_mod.search(cfg, a.search)
        score.apply(cfg, sc, config_mod.paths(cfg, a.search)["state"], show=a.show)
        return 0
    if a.cmd == "render":
        from .web import render
        for name in a.searches or config_mod.search_names(cfg):
            render.render(cfg, name)
        return 0
    if a.cmd == "history":
        from .core import history
        history.stats(config_mod.paths(cfg, a.search or "x")["history"], a.search)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
