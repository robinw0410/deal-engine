"""v0.2.3 score: without formula numbers the evaluator's tier is kept as tier_ai, so a hook cap that no
longer applies on a later run gives back the evaluator's tier (not the capped one)."""
import itertools
import textwrap

import pytest

from deal_engine.core import config as config_mod
from deal_engine.core import score
from deal_engine.core.util import load_json, save_json
from plugins_fixture.helpers import search_cfg, snapshot_syspath, write_cfg

HOOK = '''
def cap_unless_checked(listing, info):
    if listing.get("checked"):
        return None
    if info["score"] > 3:
        return {"score": 3, "note": "not checked"}
    return None
'''

NO_NUMBERS = {"id": "x-1", "title": "Something", "price": 30, "score": 6, "tier": "B"}
_n = itertools.count()


@pytest.fixture
def run(tmp_path, monkeypatch):
    snapshot_syspath(monkeypatch)
    mod = f"v023_score_{next(_n)}"
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / f"{mod}.py").write_text(textwrap.dedent(HOOK))
    cfg = write_cfg(tmp_path, {"s": search_cfg(score={"enabled": True, "hooks": [f"{mod}:cap_unless_checked"]})},
                    plugin_paths=["plugins"])
    sc = config_mod.search(cfg, "s")
    p = config_mod.paths(cfg, "s")["state"]

    def apply(listings=None, edit=None):
        if listings is not None:
            save_json(p, {"listings": [dict(l) for l in listings]})
        if edit:
            st = load_json(p, {})
            for l in st["listings"]:
                edit(l)
            save_json(p, st)
        score.apply(cfg, sc, p, log=lambda s: None)
        return load_json(p, {})["listings"][0]
    return apply


def test_cap_sets_tier_and_keeps_evaluator_values(run):
    l = run([NO_NUMBERS])
    assert (l["score"], l["tier"]) == (3, "C")
    assert (l["score_ai"], l["tier_ai"]) == (6, "B")
    assert "not checked" in l["score_calc"]


def test_cap_is_stable_over_runs(run):
    run([NO_NUMBERS])
    l = run()
    assert (l["score"], l["tier"], l["score_ai"], l["tier_ai"]) == (3, "C", 6, "B")


def test_tier_comes_back_when_cap_goes_away(run):
    run([NO_NUMBERS])
    l = run(edit=lambda l: l.update(checked=True))      # e.g. a re-evaluation added the missing field
    assert (l["score"], l["tier"]) == (6, "B")
    assert "not checked" not in l["score_calc"]


def test_without_cap_tier_unchanged(run):
    l = run([dict(NO_NUMBERS, checked=True)])
    assert (l["score"], l["tier"], l["tier_ai"]) == (6, "B", "B")


def test_new_evaluator_tier_wins_when_tier_ai_updated(run):
    """A re-evaluation that writes score/tier must also write score_ai/tier_ai."""
    run([NO_NUMBERS])
    l = run(edit=lambda l: l.update(score=8, tier="A", score_ai=8, tier_ai="A", checked=True))
    assert (l["score"], l["tier"]) == (8, "A")


def test_listing_without_tier(run):
    l = run([{k: v for k, v in NO_NUMBERS.items() if k != "tier"} | {"checked": True}])
    assert l["score"] == 6 and "tier_ai" not in l
