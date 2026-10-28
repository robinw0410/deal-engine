"""profile may be a single file or a list of files, joined in order with a blank line."""
import pytest

from deal_engine.core import config as config_mod
from deal_engine.core.run import _profile, profile_text
from plugins_fixture.helpers import search_cfg, snapshot_syspath, write_cfg


@pytest.fixture
def conf(tmp_path, monkeypatch):
    snapshot_syspath(monkeypatch)
    monkeypatch.delenv("DEAL_ENGINE_DATA_DIR", raising=False)
    monkeypatch.delenv("DEAL_ENGINE_CONFIG", raising=False)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "main.md").write_text("# Main\n\nRules.\n")
    (tmp_path / "profiles" / "stock.md").write_text("## Stock\n- item\n\n\n")
    return tmp_path


def test_list_joined_in_order_with_blank_line(conf):
    cfg = write_cfg(conf, {"s": search_cfg(profile=["profiles/main.md", "profiles/stock.md"]),
                           "r": search_cfg(profile=["profiles/stock.md", "profiles/main.md"])})
    assert _profile(cfg, config_mod.search(cfg, "s")) == "# Main\n\nRules.\n\n## Stock\n- item\n"
    assert _profile(cfg, config_mod.search(cfg, "r")).startswith("## Stock\n- item\n\n# Main")


def test_single_string_and_one_element_list_unchanged(conf):
    cfg = write_cfg(conf, {"s": search_cfg(profile="profiles/stock.md"),
                           "l": search_cfg(profile=["profiles/stock.md"])})
    raw = (conf / "profiles" / "stock.md").read_text()
    assert _profile(cfg, config_mod.search(cfg, "s")) == raw
    assert _profile(cfg, config_mod.search(cfg, "l")) == raw


def test_no_profile_is_empty_text(conf):
    cfg = write_cfg(conf, {"n": search_cfg(profile=None), "e": search_cfg(profile="")})
    assert _profile(cfg, config_mod.search(cfg, "n")) == ""
    assert _profile(cfg, config_mod.search(cfg, "e")) == ""


def test_public_helper_is_the_same(conf):
    cfg = write_cfg(conf, {"s": search_cfg(profile=["profiles/main.md", "profiles/stock.md"])})
    sc = config_mod.search(cfg, "s")
    assert profile_text is _profile and profile_text(cfg, sc).endswith("## Stock\n- item\n")


def test_missing_file_in_list_raises_config_error(conf):
    cfg = write_cfg(conf, {"s": search_cfg(profile=["profiles/main.md", "profiles/none.md"])})
    with pytest.raises(config_mod.ConfigError, match="profile not found: .*none.md"):
        _profile(cfg, config_mod.search(cfg, "s"))


@pytest.mark.parametrize("bad", [42, {"a": "b"}, [], ["profiles/main.md", 3], ["profiles/main.md", ""]])
def test_invalid_profile_type_rejected_by_config(conf, bad):
    cfg = write_cfg(conf, {"s": search_cfg(profile=bad)})
    with pytest.raises(config_mod.ConfigError, match="profile must be a file path or a list"):
        config_mod.search(cfg, "s")
