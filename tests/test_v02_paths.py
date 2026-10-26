"""v0.2 paths: everything relative in a config is relative to the config file's directory."""
import json
import sys

import pytest

from deal_engine import adapters
from deal_engine.core import config as config_mod
from deal_engine.core.run import run_search
from plugins_fixture.helpers import PROFILE, accept_all, listing, quiet, search_cfg, snapshot_syspath, write_cfg


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    snapshot_syspath(monkeypatch)
    monkeypatch.delenv("DEAL_ENGINE_DATA_DIR", raising=False)
    monkeypatch.delenv("DEAL_ENGINE_CONFIG", raising=False)
    conf, cwd = tmp_path / "conf", tmp_path / "cwd"
    conf.mkdir()
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return conf, cwd


def test_data_dir_relative_to_config(dirs):
    conf, cwd = dirs
    cfg = write_cfg(conf, {"s": search_cfg()}, data_dir="mydata")
    assert cfg["_data"] == conf / "mydata"
    assert config_mod.paths(cfg, "s")["state"] == conf / "mydata" / "state" / "s.json"
    assert config_mod.paths(cfg, "s")["web"] == conf / "mydata" / "web"


def test_default_data_dir(dirs):
    conf, _ = dirs
    (conf / "config.yaml").write_text("searches: {s: {}}\n")
    cfg = config_mod.load(conf / "config.yaml")
    assert cfg["_data"] == conf / "data"


def test_load_by_relative_path_from_cwd(dirs):
    conf, cwd = dirs
    (cwd / "sub").mkdir()
    (cwd / "sub" / "c.yaml").write_text("data_dir: d\nsearches: {s: {}}\n")
    cfg = config_mod.load("sub/c.yaml")
    assert cfg["_data"] == cwd / "sub" / "d" and cfg["_base"] == cwd / "sub"


def test_data_dir_env_override(dirs, monkeypatch):
    conf, cwd = dirs
    monkeypatch.setenv("DEAL_ENGINE_DATA_DIR", "envdata")      # relative to the cwd
    cfg = write_cfg(conf, {"s": search_cfg(json_file={"path": "{data_dir}/l.json"})}, data_dir="mydata")
    assert cfg["_data"] == cwd / "envdata"
    a = adapters.create("json_file", cfg, config_mod.search(cfg, "s"))
    assert a.path == cwd / "envdata" / "l.json"


def test_data_dir_env_override_absolute(dirs, monkeypatch, tmp_path):
    conf, _ = dirs
    monkeypatch.setenv("DEAL_ENGINE_DATA_DIR", str(tmp_path / "abs"))
    cfg = write_cfg(conf, {"s": search_cfg()})
    assert cfg["_data"] == tmp_path / "abs"


def test_data_dir_placeholder_expansion(dirs):
    conf, _ = dirs
    cfg = write_cfg(conf, {"s": search_cfg()}, data_dir="d", web={"root": "{data_dir}/site"})
    assert config_mod.resolve("{data_dir}/x.json", cfg) == conf / "d" / "x.json"
    assert config_mod.paths(cfg, "s")["web"] == conf / "d" / "site"
    assert config_mod.resolve("rel/x", cfg) == conf / "rel" / "x"
    assert config_mod.resolve("/abs/x", cfg).as_posix() == "/abs/x"


def test_json_file_path_relative_to_config(dirs):
    conf, _ = dirs
    cfg = write_cfg(conf, {"s": search_cfg(json_file={"path": "feeds/l.json"})})
    a = adapters.create("json_file", cfg, config_mod.search(cfg, "s"))
    assert a.path == conf / "feeds" / "l.json"


def test_json_file_missing_path_is_config_error(dirs):
    conf, _ = dirs
    cfg = write_cfg(conf, {"s": search_cfg()})
    with pytest.raises(config_mod.ConfigError, match="json_file.path"):
        adapters.create("json_file", cfg, config_mod.search(cfg, "s"))


def test_profile_relative_to_config(dirs):
    from deal_engine.core.run import _profile
    conf, _ = dirs
    (conf / "profiles").mkdir()
    (conf / "profiles" / "p.md").write_text("PROFILE TEXT")
    cfg = write_cfg(conf, {"s": search_cfg(profile="profiles/p.md"), "abs": search_cfg(profile=str(PROFILE)),
                           "missing": search_cfg(profile="profiles/none.md")})
    assert _profile(cfg, config_mod.search(cfg, "s")) == "PROFILE TEXT"
    assert _profile(cfg, config_mod.search(cfg, "abs")) == PROFILE.read_text()
    with pytest.raises(config_mod.ConfigError, match="profile not found"):
        _profile(cfg, config_mod.search(cfg, "missing"))


def test_prompts_relative_to_config(dirs):
    conf, _ = dirs
    (conf / "prompts").mkdir()
    (conf / "prompts" / "eval.md").write_text("custom")
    (conf / "prompts" / "s_eval.md").write_text("search custom")
    cfg = write_cfg(conf, {"s": search_cfg(prompts={"evaluate": "prompts/s_eval.md"}), "t": search_cfg(),
                           "bad": search_cfg(prompts={"evaluate": "prompts/none.md"})},
                    prompts={"evaluate": "prompts/eval.md"})
    assert config_mod.prompt_path(cfg, config_mod.search(cfg, "s"), "evaluate") == conf / "prompts" / "s_eval.md"
    assert config_mod.prompt_path(cfg, config_mod.search(cfg, "t"), "evaluate") == conf / "prompts" / "eval.md"
    # not overridden: built-in prompt
    assert config_mod.prompt_path(cfg, config_mod.search(cfg, "t"), "prefilter").name == "prefilter.md"
    with pytest.raises(config_mod.ConfigError, match="not found"):
        config_mod.prompt_path(cfg, config_mod.search(cfg, "bad"), "evaluate")


def test_plugin_paths_relative_to_config(dirs):
    conf, cwd = dirs
    (conf / "plug").mkdir()
    (cwd / "plug").mkdir()   # a same-named directory in the cwd must not be used
    cfg = write_cfg(conf, {"s": search_cfg()}, plugin_paths=["plug"])
    assert str(conf / "plug") in sys.path
    assert str(cwd / "plug") not in sys.path
    assert cfg["_base"] == conf


def test_end_to_end_with_cwd_elsewhere(dirs):
    conf, cwd = dirs
    cfg = write_cfg(conf, {"s": search_cfg(json_file={"path": "{data_dir}/l.json"}, profile="p.md")})
    (conf / "p.md").write_text("x")
    (conf / "data").mkdir()
    (conf / "data" / "l.json").write_text(json.dumps([listing("1")]))
    res = run_search(cfg, "s", evaluator=accept_all, render=False, log=quiet)
    assert res.ok and res.adapters[0].added == 1
    assert (conf / "data" / "state" / "s.json").exists()
    assert list(cwd.iterdir()) == []      # nothing written into the cwd


def test_no_config_found(dirs, monkeypatch):
    with pytest.raises(config_mod.ConfigError, match="No config"):
        config_mod.load()


def test_config_from_env(dirs, monkeypatch):
    conf, _ = dirs
    (conf / "c.yaml").write_text("searches: {s: {}}\n")
    monkeypatch.setenv("DEAL_ENGINE_CONFIG", str(conf / "c.yaml"))
    assert config_mod.load()["_path"] == str(conf / "c.yaml")
