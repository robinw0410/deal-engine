"""v0.2 score hooks: config score.hooks ["module:function"] run after the score calculation."""
import itertools
import sys
import textwrap

import pytest

from deal_engine.core import config as config_mod
from deal_engine.core import score
from deal_engine.core.config import ConfigError
from deal_engine.core.util import load_json, save_json
from plugins_fixture.helpers import search_cfg, snapshot_syspath, write_cfg

HOOKS = '''
CALLS = []


def record(listing, info):
    CALLS.append((listing.get("id"), {k: v for k, v in info.items() if k not in ("settings", "locale")},
                  info.get("settings"), info.get("locale")))


def cap4(listing, info):
    return {"score": min(info["score"], 4), "note": "capped by hook"}


def none(listing, info):
    return None


def empty(listing, info):
    return {}


def note_only(listing, info):
    return {"note": "just a note"}


def boom(listing, info):
    raise ValueError("hook exploded")


def high(listing, info):
    return {"score": 42}


def mutate_info(listing, info):
    info["score"] = 1
    info["caps"].append("x")
'''

DEAL = {"id": "x-1", "title": "PS5 Controller drift", "price": 50, "market_price": 150, "repair_hours": 1,
        "repair_parts_eur": 10, "risk": "low", "deal_type": "repair", "shipping_possible": True,
        "market_resale_estimate": 150, "score": 8, "tier": "A"}
NO_NUMBERS = {"id": "x-2", "title": "Something", "price": 30, "score": 6, "tier": "B"}

_n = itertools.count()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    snapshot_syspath(monkeypatch)
    mod = f"v02_hooks_{next(_n)}"
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / f"{mod}.py").write_text(textwrap.dedent(HOOKS))
    monkeypatch.chdir(tmp_path / "plugins")   # irrelevant cwd; plugin_paths resolve against the config

    def make(hooks, listings, **score_kw):
        cfg = write_cfg(tmp_path, {"s": search_cfg(score={"enabled": True, "hooks": [f"{mod}:{h}" for h in hooks],
                                                          **score_kw})}, plugin_paths=["plugins"])
        sc = config_mod.search(cfg, "s")
        p = config_mod.paths(cfg, "s")["state"]
        save_json(p, {"listings": [dict(l) for l in listings]})
        logs = []
        score.apply(cfg, sc, p, log=logs.append)
        return {l["id"]: l for l in load_json(p, {})["listings"]}, logs, sys.modules.get(mod)
    yield make
    sys.modules.pop(mod, None)


def test_baseline_without_hooks(setup):
    st, _, _ = setup([], [DEAL])
    assert st["x-1"]["score"] >= 5 and "hook" not in st["x-1"]["score_calc"]


def test_hook_caps_score(setup):
    base, _, _ = setup([], [DEAL])
    st, _, _ = setup(["cap4"], [DEAL])
    l = st["x-1"]
    assert base["x-1"]["score"] > 4
    assert l["score"] == 4 and l["tier"] == "C" and l["score_exact"] == 4
    assert l["score_calc"].endswith(" · capped by hook → 4")
    assert l["score_calc"].startswith(base["x-1"]["score_calc"].rsplit(" → ", 1)[0])
    assert l["tier_ai"] == "A" and l["score_ai"] == 8      # evaluator values are kept


def test_hook_returning_none_changes_nothing(setup):
    base, _, _ = setup([], [DEAL, NO_NUMBERS])
    for h in ("none", "empty"):
        st, logs, _ = setup([h], [DEAL, NO_NUMBERS])
        for k in ("score", "tier", "score_calc", "score_exact"):
            assert st["x-1"].get(k) == base["x-1"].get(k), (h, k)
            assert st["x-2"].get(k) == base["x-2"].get(k), (h, k)


def test_hook_note_only(setup):
    base, _, _ = setup([], [DEAL])
    st, _, _ = setup(["note_only"], [DEAL])
    assert st["x-1"]["score"] == base["x-1"]["score"]
    assert "just a note" in st["x-1"]["score_calc"]


def test_hook_exception_logged_and_ignored(setup):
    base, _, _ = setup([], [DEAL])
    st, logs, _ = setup(["boom", "cap4"], [DEAL])
    assert any("hook exploded" in s and "ValueError" in s and "x-1" in s for s in logs)
    assert st["x-1"]["score"] == 4                 # the next hook still runs
    st, logs, _ = setup(["boom"], [DEAL])
    assert st["x-1"]["score"] == base["x-1"]["score"]


def test_hook_score_clamped(setup):
    st, _, _ = setup(["high"], [DEAL])
    assert st["x-1"]["score"] == 10 and st["x-1"]["tier"] == "A"


def test_hook_info_is_a_copy(setup):
    base, _, _ = setup([], [DEAL])
    st, _, mod = setup(["mutate_info", "record"], [DEAL])
    assert st["x-1"]["score"] == base["x-1"]["score"]
    assert mod.CALLS[0][1]["score"] == base["x-1"]["score"]   # a hook's changes to info do not leak


def test_hook_info_contents(setup):
    st, _, mod = setup(["record"], [{**DEAL, "risk": "high"}, NO_NUMBERS])
    calls = {i: (info, s, loc) for i, info, s, loc in mod.CALLS}
    info, settings, loc = calls["x-1"]
    assert info["computed"] is True
    assert "high_risk" in info["caps"]
    assert isinstance(info["notes"], list) and any("high risk" in n for n in info["notes"])
    assert info["score"] == st["x-1"]["score"] and isinstance(info["exact"], (int, float))
    assert settings["max_score_high_risk"] == 7 and loc.code == "en"


def test_hook_called_without_formula_numbers(setup):
    st, _, mod = setup(["record"], [NO_NUMBERS])
    ((lid, info, _, _),) = mod.CALLS
    assert lid == "x-2" and info["computed"] is False and info["caps"] == [] and info["score"] == 6
    st, _, _ = setup(["cap4"], [NO_NUMBERS])
    l = st["x-2"]
    assert l["score"] == 4 and l["tier"] == "C"
    assert l["score_calc"] == "evaluator score (numbers for the formula are missing) · capped by hook"


def test_bad_hook_spec_is_config_error(setup):
    with pytest.raises(ConfigError, match="score hook"):
        setup(["missing_fn"], [DEAL])


def test_hooks_default_empty():
    assert score.DEFAULTS["hooks"] == []
    assert score.load_hooks({"hooks": []}) == []
