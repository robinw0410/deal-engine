"""v0.2 package layout: everything lives below deal_engine, the CLI runs as python -m deal_engine."""
import importlib
import os
import subprocess
import sys

from pathlib import Path

import pytest

import deal_engine

tomllib = pytest.importorskip("tomllib")

REPO = Path(__file__).resolve().parent.parent
SUBPACKAGES = ["core", "adapters", "web", "deals", "demo"]


@pytest.mark.parametrize("mod", [
    "deal_engine", "deal_engine.core", "deal_engine.adapters", "deal_engine.web", "deal_engine.deals",
    "deal_engine.demo",
    "deal_engine.core.config", "deal_engine.core.plugins", "deal_engine.core.locale", "deal_engine.core.listing",
    "deal_engine.core.filters", "deal_engine.core.groups", "deal_engine.core.pipeline", "deal_engine.core.run",
    "deal_engine.core.score", "deal_engine.core.history", "deal_engine.core.insights", "deal_engine.core.market",
    "deal_engine.core.classify", "deal_engine.core.llm",
    "deal_engine.adapters.base", "deal_engine.adapters.json_file", "deal_engine.adapters.ebay",
    "deal_engine.web.render", "deal_engine.deals.deals_server", "deal_engine.demo.evaluator",
    "deal_engine.demo.generate", "deal_engine.__main__",
])
def test_importable(mod):
    importlib.import_module(mod)


def _run(args, cwd, **env):
    e = {**os.environ, **env}
    return subprocess.run([sys.executable, *args], cwd=cwd, env=e, capture_output=True, text=True, timeout=60)


def test_cli_help():
    r = _run(["-m", "deal_engine", "--help"], REPO)
    assert r.returncode == 0, r.stderr
    for cmd in ("run", "adapters", "score", "render", "history", "validate"):
        assert cmd in r.stdout


def test_cli_run_help_lists_json_option():
    r = _run(["-m", "deal_engine", "run", "--help"], REPO)
    assert r.returncode == 0, r.stderr
    assert "--json" in r.stdout and "--evaluator" in r.stdout


def test_cli_help_from_other_directory(tmp_path):
    r = _run(["-m", "deal_engine", "--help"], tmp_path, PYTHONPATH=str(REPO))
    assert r.returncode == 0, r.stderr


def test_no_toplevel_packages_from_repo_root():
    code = ("import importlib.util, sys; "
            f"bad = [m for m in {SUBPACKAGES!r} if importlib.util.find_spec(m) is not None]; "
            "print(','.join(bad)); sys.exit(1 if bad else 0)")
    r = _run(["-c", code], REPO)
    assert r.returncode == 0, f"top-level packages importable from the repo root: {r.stdout.strip()}"
    for m in SUBPACKAGES:
        assert not (REPO / m / "__init__.py").exists()


def test_pyproject_lists_only_deal_engine_packages():
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    st = data["tool"]["setuptools"]
    pkgs = st["packages"]
    assert pkgs and all(p == "deal_engine" or p.startswith("deal_engine.") for p in pkgs)
    assert {f"deal_engine.{m}" for m in SUBPACKAGES} <= set(pkgs)
    for p in pkgs:
        assert (REPO / p.replace(".", "/") / "__init__.py").exists(), p
    assert all(k.startswith("deal_engine") for k in st.get("package-data", {}))
    assert data["project"]["version"] == deal_engine.__version__ == "0.2.2"


def test_builtin_prompts_ship_with_the_package():
    from deal_engine.core import config as config_mod
    for name in ("evaluate", "prefilter", "classify"):
        p = config_mod.prompt_path({"locale": "en"}, {"_locale": "en"}, name)
        assert p.exists() and p.is_relative_to(REPO / "deal_engine")
    # unknown locale directory falls back to English
    assert config_mod.prompt_path({}, {"_locale": "xx"}, "evaluate").parent.name == "en"
