"""v0.2.1: localized deal list page, copy-as-prompt switch, tool restrictions of the LLM calls."""
import json
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from deal_engine.core import config as config_mod
from deal_engine.core import llm
from deal_engine.core import run as run_mod
from deal_engine.core.config import ConfigError
from deal_engine.deals import deals_server, texts
from deal_engine.web import render
from plugins_fixture.helpers import quiet, search_cfg, write_cfg

FORMER_EN = ("New deal", "Purchases", "Overview", "By category", "Estimate vs. result", "Book purchase",
             "whole catalogue", "Search pages", "Profit = sale", "Delete purchase?", "Loading failed",
             "No open deals", "tied up in", "Item / description", "Use parts from stock", "Bought on",
             "Price hint after saving", "Data: state/deals.db", ">in progress<", ">scrapped<", ">sold<", "Cancel", "Save")


# --- deal page texts ----------------------------------------------------------------------------

def test_text_tables_have_identical_keys():
    assert set(texts.EN) == set(texts.DE)
    assert all(type(texts.EN[k]) is type(texts.DE[k]) for k in texts.EN)
    for k in texts.EN:   # same {placeholders} in both languages
        assert set(re.findall(r"\{\w+\}", str(texts.EN[k]))) == set(re.findall(r"\{\w+\}", str(texts.DE[k]))), k
    for s in deals_server.STATUSES:
        assert f"status.{s}" in texts.EN


def test_page_uses_only_known_keys():
    page = deals_server.PAGE.read_text()
    keys = set(re.findall(r"\{\{([\w. ]+)\}\}", page)) - {"lang", "texts"}
    js = set(re.findall(r'\bth?\("([\w. ]+)"', page))
    assert keys and js and not (keys | js) - set(texts.EN)


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Deal server on an ephemeral port on 127.0.0.1; yields a function that starts it for a locale."""
    started = []

    def start(locale=None):
        top = {"deals": {"enabled": True}}
        if locale:
            top["locale"] = locale
        cfg = write_cfg(tmp_path / (locale or "default"), {"s": search_cfg()}, **top)
        monkeypatch.setattr(deals_server, "CFG", cfg)
        deals_server.init(cfg)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), deals_server.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"
    yield start
    for srv in started:
        srv.shutdown()
        srv.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read().decode()


def call(method, url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def page_texts(page):
    return json.loads(page.split("window.DE_T = ")[1].split(";</script>")[0])


def test_served_page_english_by_default(server):
    page = get(server() + "/deals/")
    assert '<html lang="en">' in page and "{{" not in page
    for s in ("New deal", "Purchases", "Overview", "<title>Deals &amp; Parts</title>"):
        assert s in page, s
    assert page_texts(page) == texts.EN


def test_served_page_german(server):
    base = server("de")
    page = get(base + "/deals/")
    assert '<html lang="de">' in page and "{{" not in page
    for s in ("Neuer Deal", "Einkäufe", "Übersicht", "Nach Kategorie", "Teile vom Lager verwenden",
              "<title>Deals &amp; Teile</title>", "Daten: state/deals.db im Datenverzeichnis."):
        assert s in page, s
    # what can reach the user: the markup (without comments) and the string literals of the page script
    markup, script = page.split("<script>window.DE_T", 1)
    script = script.split("<script>", 1)[1]
    visible = re.sub(r"<!--.*?-->", "", markup, flags=re.S) + "\n".join(re.findall(r'"[^"\n]*"|\'[^\'\n]*\'', script))
    for s in FORMER_EN:
        assert s not in visible, s
    T = page_texts(page)
    assert T["num.locale"] == "de-DE" and T["status.in progress"] == "in Arbeit"
    # statuses: machine values in the form and the API, translated display
    assert '<option value="in progress">in Arbeit</option>' in page
    assert '<option value="scrapped">verschrottet</option>' in page
    data = call("POST", base + "/deals/api/deals", {"item": "Switch Lite", "status": "in progress", "buy_price": "40"})
    assert data["statuses"] == list(deals_server.STATUSES)
    assert [d["status"] for d in data["deals"]] == ["in progress"]
    assert data["deals"][0]["price_hint"]["text"].startswith("kein Marktpreis")   # server-side locale


def test_render_page_escapes_and_fills_everything(monkeypatch):
    monkeypatch.setitem(texts.DE, "footer", "<b>x</b>")
    page = deals_server.render_page({"locale": "de"}).decode()
    assert "&lt;b&gt;x&lt;/b&gt;" in page and "{{" not in page and "</b>\"" not in page.split("DE_T")[1]


# --- copy as prompt -----------------------------------------------------------------------------

def item(**kw):
    return {"id": "x-1", "title": "Item", "price": 10, "score": 5, "tier": "B", "urls": ["https://example.invalid/1"],
            "first_seen": "2026-01-01", "last_seen": "2026-01-02", **kw}


def card_html(tmp_path, searches, **top):
    cfg = write_cfg(tmp_path, searches, deals={"enabled": False}, **top)
    out = {}
    for name in searches:
        page = render.cfg_for(name, config_mod.search(cfg, name), cfg)
        out[name] = render.card(item(), page, cfg)
    return out


def has_prompt(html):
    return "copy as prompt" in html or "<textarea" in html


def test_copy_prompt_off_by_default(tmp_path):
    html = card_html(tmp_path, {"a": search_cfg(), "b": search_cfg(web={"title": "B"})})
    assert not has_prompt(html["a"]) and not has_prompt(html["b"])


def test_copy_prompt_global_and_per_search(tmp_path):
    html = card_html(tmp_path, {"a": search_cfg(), "b": search_cfg(web={"copy_prompt": False})},
                     web={"copy_prompt": True})
    assert "copy as prompt" in html["a"] and "<textarea hidden>" in html["a"]
    assert not has_prompt(html["b"])
    html = card_html(tmp_path, {"a": search_cfg(), "b": search_cfg(web={"copy_prompt": True})})
    assert not has_prompt(html["a"]) and "copy as prompt" in html["b"]


def test_copy_prompt_wrong_type(tmp_path):
    with pytest.raises(ConfigError, match="copy_prompt"):
        card_html(tmp_path, {"a": search_cfg(web={"copy_prompt": "yes"})})
    with pytest.raises(ConfigError, match="web.copy_prompt"):
        card_html(tmp_path, {"a": search_cfg()}, web={"copy_prompt": 1})


# --- LLM tool restrictions ----------------------------------------------------------------------

@pytest.fixture
def calls(monkeypatch):
    seen = []

    class R:
        returncode, stdout, stderr = 0, "", ""

    def fake(cmd, **kw):
        seen.append(cmd)
        return R()
    monkeypatch.setattr(llm.subprocess, "run", fake)
    return seen


def tail(cmd):
    return cmd[cmd.index("--tools"):]


def llm_cfg(tmp_path, extra=None):
    cfg = write_cfg(tmp_path, {"s": search_cfg()},
                    llm={"command": ["claude", "-p"], "extra_args": extra if extra is not None else
                         ["--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}']})
    work = cfg["_data"] / "work"
    work.mkdir(parents=True)
    (work / "candidates-1.json").write_text(json.dumps({"candidates": [], "date": "2026-01-01"}))
    return cfg, config_mod.search(cfg, "s"), work


def test_evaluate_and_prefilter_command(tmp_path, calls):
    cfg, sc, work = llm_cfg(tmp_path)
    run_mod.llm_prefilter(cfg, sc, work, log=quiet)
    run_mod.llm_evaluate(cfg, sc, work, log=quiet)
    assert len(calls) == 2
    for cmd in calls:
        assert tail(cmd) == ["--tools", "Read", "Write", "--allowedTools", "Read", "Write",
                             "--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}',
                             "--disallowedTools", "Bash", "WebFetch", "WebSearch"]


def test_classify_command(tmp_path, calls):
    cfg, _, _ = llm_cfg(tmp_path, extra=[])
    llm.run(cfg, "x", "haiku", tools=(), max_turns=2, timeout_min=10)   # as classify.apply calls it
    assert tail(calls[0]) == ["--tools", "", "--disallowedTools", "Bash", "WebFetch", "WebSearch"]


@pytest.mark.parametrize("extra", [
    ["--allowedTools", "Read", "Bash"], ["--allowedTools", "Bash(git:*)"], ["--tools", "WebFetch"],
    ["--allowed-tools=Read,WebSearch"], ["--model", "x", "--allowedTools", "bash"],
])
def test_extra_args_cannot_allow_dangerous_tools(tmp_path, calls, extra):
    cfg, _, _ = llm_cfg(tmp_path, extra=extra)
    with pytest.raises(ConfigError, match="extra_args"):
        llm.run(cfg, "x", "haiku")
    assert calls == []


def test_extra_args_harmless_ok(tmp_path, calls):
    cfg, _, _ = llm_cfg(tmp_path, extra=["--allowedTools", "Read", "--append-system-prompt", "Bash is not available"])
    llm.run(cfg, "x", "haiku")
    assert calls[0][-4:] == ["--disallowedTools", "Bash", "WebFetch", "WebSearch"]
