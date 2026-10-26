"""Runs the complete pipeline on invented data, without any account, API key or LLM.

  python -m demo.run_demo [--days 21] [--data data/demo]

Deletes and recreates the demo data directory, simulates --days days of a small market (one
run per day with the demo evaluator), seeds the deal list, and renders the pages. Afterwards:

  python -m deals.deals_server --config config.example.yaml --web-root data/demo/web
  (make demo does both)
"""
import argparse
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m demo.run_demo")
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--data", default="data/demo")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    data = (ROOT / a.data).resolve()
    if data.exists():
        if not (data / "demo-truth.json").exists() and any(data.iterdir()):
            sys.exit(f"{data} exists and does not look like demo data, not deleting it")
        shutil.rmtree(data)
    os.environ["DEAL_ENGINE_DATA_DIR"] = str(data)
    os.environ["DEAL_ENGINE_CONFIG"] = str(ROOT / "config.example.yaml")

    from core import config as config_mod
    from core.run import run_search
    from demo.evaluator import evaluate
    from demo.generate import World
    from demo.seed_deals import seed

    cfg = config_mod.load()
    home = config_mod.home(cfg) or (52.52, 13.405)
    start = date.today() - timedelta(days=a.days - 1)
    world = World(data, home)
    world.seed(start)

    def log(s):
        if not a.quiet:
            print("   ", s)

    for i in range(a.days):
        day = start + timedelta(days=i)
        os.environ["DEAL_ENGINE_TODAY"] = str(day)
        if i:
            world.step(day)
        world.write()
        print(f"[demo] day {i + 1}/{a.days} ({day}): {len(world.listings)} listings on the simulated market")
        for name in config_mod.search_names(cfg):
            run_search(cfg, name, evaluator=evaluate, render=(i == a.days - 1), log=log)
    seed(cfg)
    os.environ.pop("DEAL_ENGINE_TODAY", None)
    print(f"[demo] done. Data in {data}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
