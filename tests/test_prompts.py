"""Built-in prompts per locale, prompt file resolution and the {{WANTED_ADS}} placeholder."""
import re

import pytest
import yaml

from deal_engine.core import config as config_mod
from deal_engine.core import llm
from deal_engine.core import locale as locale_mod

PROMPTS = config_mod.PACKAGE / "core" / "prompts"
STEPS = ["evaluate", "prefilter", "classify"]


def placeholders(path):
    return set(re.findall(r"\{\{([A-Z_]+)\}\}", path.read_text()))


@pytest.mark.parametrize("step", STEPS)
def test_builtin_prompts_exist_with_same_placeholders(step):
    en, de = PROMPTS / "en" / f"{step}.md", PROMPTS / "de" / f"{step}.md"
    assert en.exists() and de.exists()
    assert placeholders(en), f"{en} has no placeholders"
    assert placeholders(de) == placeholders(en)


def write_cfg(tmp_path, searches=None, **top):
    raw = {"data_dir": "data", **top,
           "searches": searches or {"s": {"adapters": ["json_file"], "keywords": ["x"]}}}
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw))
    return config_mod.load(p)


def test_prompt_path_resolution_order(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "global.md").write_text("global")
    (tmp_path / "prompts" / "search.md").write_text("search")
    cfg = write_cfg(tmp_path, prompts={"evaluate": "prompts/global.md"}, searches={
        "own": {"prompts": {"evaluate": "prompts/search.md"}},
        "plain": {},
        "german": {"locale": "de"},
    })
    # search override beats the global one
    assert config_mod.prompt_path(cfg, config_mod.search(cfg, "own"), "evaluate") == tmp_path / "prompts" / "search.md"
    # global override, relative to the config file
    assert config_mod.prompt_path(cfg, config_mod.search(cfg, "plain"), "evaluate") == tmp_path / "prompts" / "global.md"
    assert config_mod.prompt_path(cfg, config_mod.search(cfg, "german"), "evaluate") == tmp_path / "prompts" / "global.md"
    # no override: built-in of the locale
    assert config_mod.prompt_path(cfg, config_mod.search(cfg, "plain"), "prefilter") == PROMPTS / "en" / "prefilter.md"
    assert config_mod.prompt_path(cfg, config_mod.search(cfg, "german"), "prefilter") == PROMPTS / "de" / "prefilter.md"


def test_prompt_path_falls_back_to_english(tmp_path):
    cfg = write_cfg(tmp_path)
    sc = {**config_mod.search(cfg, "s"), "_locale": "xx"}   # a locale without built-in prompts
    for step in STEPS:
        assert config_mod.prompt_path(cfg, sc, step) == PROMPTS / "en" / f"{step}.md"


def test_missing_override_raises(tmp_path):
    cfg = write_cfg(tmp_path, prompts={"evaluate": "prompts/nope.md"})
    with pytest.raises(config_mod.ConfigError):
        config_mod.prompt_path(cfg, config_mod.search(cfg, "s"), "evaluate")
    cfg = write_cfg(tmp_path, searches={"s": {"prompts": {"prefilter": "missing.md"}}})
    with pytest.raises(config_mod.ConfigError):
        config_mod.prompt_path(cfg, config_mod.search(cfg, "s"), "prefilter")


@pytest.mark.parametrize("code", ["en", "de"])
@pytest.mark.parametrize("step", ["evaluate", "prefilter"])
def test_wanted_ads_placeholder(tmp_path, code, step):
    cfg = write_cfg(tmp_path, locale=code, searches={"default": {}, "wanted": {"wanted_ads": "accept"}})
    loc = locale_mod.get(code)
    values = {"CANDIDATES": "c.json", "ACCEPTED": "a.json", "PREFILTER": "p.json", "DATE": "2026-06-01"}
    text = llm.prompt(cfg, config_mod.search(cfg, "default"), step, **values)
    assert loc.t("wanted.reject") in text and loc.t("wanted.accept") not in text
    text = llm.prompt(cfg, config_mod.search(cfg, "wanted"), step, **values)
    assert loc.t("wanted.accept") in text and loc.t("wanted.reject") not in text
    assert "{{" not in text


def test_wanted_ads_invalid_value(tmp_path):
    cfg = write_cfg(tmp_path, searches={"s": {"wanted_ads": "maybe"}})
    with pytest.raises(config_mod.ConfigError):
        config_mod.search(cfg, "s")
