"""Command line interface.

  python -m core run [search ...]            run searches (default: all), evaluator = Claude Code CLI
  python -m core run --evaluator demo ...    use the demo evaluator (no LLM, only for demo data)
  python -m core score <search> [--show]     recompute scores (--show: print, don't save)
  python -m core render [search ...]         render the HTML pages
  python -m core history [search]            tracking statistics per group
  python -m core validate <file.json>        check a listings file against docs/listing-format.md

Options: --config PATH (default: $DEAL_ENGINE_CONFIG, config.yaml, config.example.yaml)
"""
import argparse
import json
import sys

from . import config as config_mod


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m core", description="deal-engine")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("searches", nargs="*")
    r.add_argument("--evaluator", default="claude", choices=["claude", "demo"])
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
        from .listing import normalize
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

    cfg = config_mod.load(a.config)
    if a.cmd == "run":
        from .run import run_search
        evaluator = a.evaluator
        if evaluator == "demo":
            from demo.evaluator import evaluate
            evaluator = evaluate
        ok = True
        for name in a.searches or config_mod.search_names(cfg):
            ok &= run_search(cfg, name, evaluator)
        return 0 if ok else 1
    if a.cmd == "score":
        from . import score
        sc = config_mod.search(cfg, a.search)
        score.apply(cfg, sc, config_mod.paths(cfg, a.search)["state"], show=a.show)
        return 0
    if a.cmd == "render":
        from web import render
        for name in a.searches or config_mod.search_names(cfg):
            render.render(cfg, name)
        return 0
    if a.cmd == "history":
        from . import history
        history.stats(config_mod.paths(cfg, a.search or "x")["history"], a.search)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
