"""v0.2.13: wish list on the deal server (/deals/wishes/, /deals/api/wishes) with CSRF protection.

Validation limits of deals.wishes, the server-rendered form page end to end over a real server on
127.0.0.1, the CSRF token / origin checks for all writes and the read-only access for host applications."""
import http.client
import json
import os
import re
import stat
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

import pytest
import yaml

from deal_engine.core import config as config_mod
from deal_engine.deals import csrf, deals_server, texts, wishes, wishes_page


def make_cfg(tmp_path, **top):
    raw = {"data_dir": str(tmp_path), "searches": {}, "deals": {"enabled": True}, **top}
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True))
    return config_mod.load(p)


def wish(**kw):
    return {"name": "Example camera", "terms": ["example camera", "camera x1"], "max_price": "120",
            "platforms": ["ebay"], "active": True, "note": "", **kw}


@pytest.fixture
def mem():
    con = deals_server.sqlite3.connect(":memory:")
    con.row_factory = deals_server.sqlite3.Row
    yield con
    con.close()


# ------------------------------------------------------------------ validation

def test_validate_cleans():
    w = wishes.validate(wish(name="  Example\tcamera \x00 ", terms="a, b; c\nA", max_price="99,50 €",
                             platforms=["ebay", "willhaben", "ebay"], note=" ok\r\n "))
    assert w == {"name": "Example camera", "terms": ["a", "b", "c"], "max_price": 99.5,
                 "platforms": ["willhaben", "ebay"], "active": True, "note": "ok"}


@pytest.mark.parametrize("change, msg", [
    ({"name": ""}, "name"), ({"name": "x" * (wishes.MAX_NAME + 1)}, "name"), ({"name": 5}, "name"),
    ({"terms": []}, "terms"), ({"terms": ["", " "]}, "terms"), ({"terms": "a,b,c,d,e,f"}, "terms"),
    ({"terms": ["t" * (wishes.MAX_TERM + 1)]}, "term"), ({"terms": [1]}, "term"), ({"terms": 3}, "terms"),
    ({"max_price": "nan"}, "max_price"), ({"max_price": "inf"}, "max_price"), ({"max_price": "-5"}, "max_price"),
    ({"max_price": "0"}, "max_price"), ({"max_price": "abc"}, "max_price"), ({"max_price": "1e9"}, "max_price"),
    ({"platforms": []}, "platforms"), ({"platforms": ["elsewhere"]}, "platforms"), ({"platforms": [1]}, "platforms"),
    ({"note": "n" * (wishes.MAX_NOTE + 1)}, "note"),
])
def test_validate_rejects(change, msg):
    with pytest.raises(ValueError, match=msg):
        wishes.validate(wish(**change))


def test_control_characters_never_stored(mem):
    wid = wishes.create(mem, wish(name="a\x1b[31mb\x7f", terms=["x\x00y"], note="l1\nl2\x07"))
    w = wishes.rows(mem)[0]
    assert w["id"] == wid and not re.search(r"[\x00-\x1f\x7f]", w["name"] + "".join(w["terms"]) + w["note"])


def test_platforms_from_config():
    cfg = {"wishes": {"platforms": ["ebay"]}}
    with pytest.raises(ValueError, match="platforms"):
        wishes.validate(wish(platforms=["willhaben"]), cfg)
    assert wishes.validate(wish(), cfg)["platforms"] == ["ebay"]


def test_eleventh_active_wish_rejected_inactive_allowed(mem):
    for i in range(wishes.MAX_ACTIVE):
        wishes.create(mem, wish(name=f"w{i}"))
    with pytest.raises(ValueError, match="active"):
        wishes.create(mem, wish(name="eleven"))
    wid = wishes.create(mem, wish(name="eleven", active=False))
    with pytest.raises(ValueError, match="active"):   # reactivating over the limit
        wishes.update(mem, wid, {"active": True})
    first = wishes.rows(mem)[0]["id"]
    wishes.update(mem, first, {"name": "renamed"})   # editing an active wish at the limit is fine
    wishes.update(mem, first, {"active": False})
    wishes.update(mem, wid, {"active": True})
    assert sum(w["active"] for w in wishes.rows(mem)) == wishes.MAX_ACTIVE


def test_update_delete_unknown(mem):
    with pytest.raises(KeyError):
        wishes.update(mem, 99, {"name": "x"})
    with pytest.raises(KeyError):
        wishes.delete(mem, 99)


def test_active_for_host_application(tmp_path):
    cfg = make_cfg(tmp_path)
    assert wishes.active(cfg) == []                      # no database at all
    assert not deals_server.db_path(cfg).exists()        # and none was created
    con = deals_server.connect(cfg)
    assert wishes.active(cfg) == []                      # database without the wish table
    wishes.create(con, wish(name="on"))
    wishes.create(con, wish(name="off", active=False))
    con.commit()
    con.close()
    got = wishes.active(cfg)
    assert [w["name"] for w in got] == ["on"] and got[0]["terms"] == ["example camera", "camera x1"]


# ------------------------------------------------------------------ server

class Client:
    def __init__(self, port):
        self.port = port

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read().decode()
        finally:
            c.close()

    def page(self, path="/deals/wishes/"):
        status, headers, body = self.req("GET", path)
        assert status == 200
        return body

    def token(self):
        return re.search(r'name="csrf" value="([^"]+)"', self.page()).group(1)

    def post(self, fields, token=True, headers=None):
        fields = dict(fields)
        if token is True:
            fields["csrf"] = self.token()
        elif token:
            fields["csrf"] = token
        h = {"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin", **(headers or {})}
        h = {k: v for k, v in h.items() if v is not None}
        return self.req("POST", "/deals/wishes/", urlencode(fields, doseq=True).encode(), h)


@pytest.fixture
def srv(tmp_path, monkeypatch):
    started = []

    def start(**top):
        cfg = make_cfg(tmp_path, **top)
        monkeypatch.setattr(deals_server, "CFG", cfg)
        deals_server.init(cfg)
        s = ThreadingHTTPServer(("127.0.0.1", 0), deals_server.H)
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        started.append(s)
        return Client(s.server_address[1]), cfg
    yield start
    for s in started:
        s.shutdown()
        s.server_close()


def db_wishes(cfg):
    con = deals_server.connect(cfg)
    try:
        return wishes.rows(con)
    finally:
        con.close()


FORM = {"action": "create", "name": "Example camera", "terms": ["example camera", "camera x1", ""],
        "max_price": "120,50", "platforms": ["willhaben", "ebay"], "active": "1", "note": "with charger"}


def test_page_redirect_headers_and_nav(srv):
    c, cfg = srv()
    status, headers, _ = c.req("GET", "/deals/wishes")
    assert status == 301 and headers["Location"] == "/deals/wishes/"
    status, headers, page = c.req("GET", "/deals/wishes/")
    assert status == 200 and headers["X-Content-Type-Options"] == "nosniff"
    pol = headers["Content-Security-Policy"]
    assert "default-src 'none'" in pol and "form-action 'self'" in pol and "frame-ancestors 'none'" in pol
    assert "<script" not in page and " style=" not in page and "unsafe-inline" not in pol
    nav = re.search(r'<nav class="site">(.*?)</nav>', page).group(1)
    assert 'href="../../deals/"' in nav and 'class="active"' in nav
    assert 'href="wishes/"' in c.page("/deals/")   # link from the deal list
    assert texts.EN["w.title"] in page and texts.EN["w.none"] in page


def test_page_german(srv):
    c, _ = srv(locale="de")
    page = c.page()
    assert 'lang="de"' in page and "Wunschliste" in page and "Höchstpreis" in page


def test_create_edit_deactivate_activate_delete(srv):
    c, cfg = srv()
    status, headers, _ = c.post(FORM)
    assert status == 303 and headers["Location"] == "/deals/wishes/?done=created"
    [w] = db_wishes(cfg)
    assert (w["name"], w["terms"], w["max_price"], w["platforms"], w["active"], w["note"]) == \
        ("Example camera", ["example camera", "camera x1"], 120.5, ["willhaben", "ebay"], True, "with charger")
    page = c.page("/deals/wishes/?done=created")
    assert texts.EN["w.ok.created"] in page and "Example camera" in page and "120.50 €" in page

    edit = c.page(f"/deals/wishes/?edit={w['id']}")
    assert 'value="update"' in edit and 'value="camera x1"' in edit and "with charger</textarea>" in edit

    status, headers, _ = c.post({**FORM, "action": "update", "id": w["id"], "name": "Example camera 2",
                                 "platforms": "ebay", "terms": ["only one"]})
    assert status == 303 and headers["Location"].endswith("done=updated")
    [w] = db_wishes(cfg)
    assert (w["name"], w["terms"], w["platforms"], w["active"]) == ("Example camera 2", ["only one"], ["ebay"], True)

    assert c.post({"action": "deactivate", "id": w["id"]})[0] == 303
    assert db_wishes(cfg)[0]["active"] is False and wishes.active(cfg) == []
    assert c.post({"action": "activate", "id": w["id"]})[0] == 303
    assert db_wishes(cfg)[0]["active"] is True and len(wishes.active(cfg)) == 1

    # unchecked "active" checkbox on edit = inactive
    form = {k: v for k, v in FORM.items() if k != "active"}
    assert c.post({**form, "action": "update", "id": w["id"]})[0] == 303
    assert db_wishes(cfg)[0]["active"] is False

    status, headers, _ = c.post({"action": "delete", "id": w["id"]})
    assert status == 303 and headers["Location"].endswith("done=deleted") and db_wishes(cfg) == []
    status, _, page = c.post({"action": "delete", "id": w["id"]})
    assert status == 404 and texts.EN["w.err.notfound"] in page


def test_validation_error_rerenders_form_escaped(srv):
    c, cfg = srv()
    status, headers, page = c.post({**FORM, "name": "<b>x</b>", "max_price": "-1"})
    assert status == 400 and db_wishes(cfg) == []
    assert "Not saved: max_price" in page and "&lt;b&gt;x&lt;/b&gt;" in page and "<b>x</b>" not in page
    assert "Content-Security-Policy" in headers


def test_limit_through_form(srv):
    c, cfg = srv()
    for i in range(wishes.MAX_ACTIVE):
        assert c.post({**FORM, "name": f"w{i}"})[0] == 303
    status, _, page = c.post({**FORM, "name": "eleven"})
    assert status == 400 and "at most 10 active" in page
    inactive = {k: v for k, v in FORM.items() if k != "active"}
    assert c.post({**inactive, "name": "eleven"})[0] == 303
    eleven = [w for w in db_wishes(cfg) if w["name"] == "eleven"][0]
    assert c.post({"action": "activate", "id": eleven["id"]})[0] == 400
    assert len(wishes.active(cfg)) == wishes.MAX_ACTIVE


def test_too_many_terms_through_form(srv):
    c, cfg = srv()
    status, _, _ = c.post({**FORM, "terms": [f"t{i}" for i in range(6)]})
    assert status == 400 and db_wishes(cfg) == []


def test_name_with_script_is_escaped(srv):
    c, cfg = srv()
    evil = '<script>alert(1)</script>"\'&'
    assert c.post({**FORM, "name": evil, "terms": [evil], "note": evil})[0] == 303
    page = c.page()
    assert "<script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;&quot;&#x27;&amp;" in page
    edit = c.page(f"/deals/wishes/?edit={db_wishes(cfg)[0]['id']}")
    assert "<script>" not in edit and 'value="&lt;script&gt;' in edit


@pytest.mark.parametrize("token", [None, "", "123.abc", "garbage", "1.{}".format("0" * 64)])
def test_post_without_valid_csrf_token_is_refused(srv, token):
    c, cfg = srv()
    status, headers, page = c.post(FORM, token=token)
    assert status == 403 and db_wishes(cfg) == []
    assert texts.EN["w.err.csrf"].split(" (")[0] in page


def test_csrf_token_of_other_secret_or_expired_is_refused(srv, tmp_path):
    c, cfg = srv()
    other = {"_data": tmp_path / "other"}
    assert c.post(FORM, token=csrf.token(other))[0] == 403
    old = csrf.token(cfg, now=csrf.time.time() - csrf.MAX_AGE - 10)
    assert c.post(FORM, token=old)[0] == 403
    future = csrf.token(cfg, now=csrf.time.time() + 3600)
    assert c.post(FORM, token=future)[0] == 403
    tok = c.token()
    ts, mac = tok.split(".")
    assert c.post(FORM, token=f"{int(ts) - 1}.{mac}")[0] == 403      # mac bound to the time
    assert db_wishes(cfg) == []
    assert c.post(FORM, token=tok)[0] == 303


@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
    {"Sec-Fetch-Site": None, "Origin": "https://attacker.example"},
    {"Sec-Fetch-Site": None, "Origin": "null"},
    {"Sec-Fetch-Site": None, "Referer": "https://attacker.example/page"},
])
def test_cross_site_post_is_refused_even_with_token(srv, headers):
    c, cfg = srv()
    status, _, _ = c.post(FORM, headers=headers)
    assert status == 403 and db_wishes(cfg) == []


@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": None},                                              # non-browser client
    {"Sec-Fetch-Site": None, "Origin": "http://127.0.0.1:{port}"},
    {"Sec-Fetch-Site": None, "Referer": "http://127.0.0.1:{port}/deals/wishes/"},
    {"Sec-Fetch-Site": None, "Origin": "http://127.0.0.1:8080"},   # port is not compared (proxy drops it)
])
def test_same_origin_post_is_accepted(srv, headers):
    c, cfg = srv()
    headers = {k: v and v.format(port=c.port) for k, v in headers.items()}
    assert c.post(FORM, headers=headers)[0] == 303 and len(db_wishes(cfg)) == 1


def test_body_too_large(srv):
    c, cfg = srv()
    status, _, page = c.post({**FORM, "note": "x" * (deals_server.MAX_FORM + 1)})
    assert status == 413 and db_wishes(cfg) == [] and texts.EN["w.err.size"] in page


def test_wrong_form_encoding_and_bad_ids(srv):
    c, cfg = srv()
    tok = c.token()
    status, _, _ = c.req("POST", "/deals/wishes/", json.dumps({**FORM, "csrf": tok}).encode(),
                         {"Content-Type": "application/json"})
    assert status == 415
    for bad in ({"action": "delete", "id": "1 OR 1=1"}, {"action": "delete", "id": "-1"},
                {"action": "delete"}, {"action": "drop"}, {"action": "delete", "id": "../1"}):
        assert c.post(bad)[0] == 400
    assert db_wishes(cfg) == []


def test_secret_file_is_private_and_stable(srv, tmp_path):
    c, cfg = srv()
    p = csrf.secret_path(cfg)
    assert p.exists() and stat.S_IMODE(os.stat(p).st_mode) == 0o400   # read-only: no overwrite without chmod
    first = p.read_text()
    tok = c.token()
    csrf._CACHE.clear()
    assert p.read_text() == first and csrf.valid(cfg, tok)   # same secret after a restart
    os.chmod(p, 0o644)
    csrf._CACHE.clear()
    csrf.secret(cfg)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o400
    assert first.strip() not in c.page() and first.strip() not in (tmp_path / "config.yaml").read_text()


# ------------------------------------------------------------------ JSON API

def api(c, method, path, body=None, token=None, ctype="application/json", site="same-origin"):
    h = {"Content-Type": ctype}
    if token:
        h["X-CSRF-Token"] = token
    if site:
        h["Sec-Fetch-Site"] = site
    status, _, text = c.req(method, path, None if body is None else json.dumps(body).encode(), h)
    return status, json.loads(text) if text else None


def test_api_crud(srv):
    c, cfg = srv()
    status, data = api(c, "GET", "/deals/api/wishes")
    assert status == 200 and data["wishes"] == [] and data["max_active"] == 10 and data["csrf"]
    tok = data["csrf"]
    status, data = api(c, "POST", "/deals/api/wishes", wish(), tok)
    assert status == 200 and [w["name"] for w in data["wishes"]] == ["Example camera"]
    wid = data["wishes"][0]["id"]
    status, data = api(c, "PUT", f"/deals/api/wishes/{wid}", {"active": False}, tok)
    assert status == 200 and data["wishes"][0]["active"] is False
    assert api(c, "PUT", f"/deals/api/wishes/{wid}", {"max_price": "nan"}, tok)[0] == 400
    assert api(c, "PUT", "/deals/api/wishes/999", {"name": "x"}, tok)[0] == 404
    assert api(c, "DELETE", f"/deals/api/wishes/{wid}", None, tok)[1]["wishes"] == []
    assert api(c, "DELETE", f"/deals/api/wishes/{wid}", None, tok)[0] == 404


def test_api_writes_need_token_and_json(srv):
    c, cfg = srv()
    tok = api(c, "GET", "/deals/api/wishes")[1]["csrf"]
    assert api(c, "POST", "/deals/api/wishes", wish())[0] == 403
    assert api(c, "POST", "/deals/api/wishes", wish(), "1.bad")[0] == 403
    assert api(c, "POST", "/deals/api/wishes", wish(), tok, site="cross-site")[0] == 403
    assert api(c, "POST", "/deals/api/wishes", wish(), tok, ctype="text/plain; application/json")[0] == 415
    assert db_wishes(cfg) == []


# ------------------------------------------------------------------ existing JSON endpoints

def test_existing_api_refuses_cross_site_and_disguised_content_type(srv):
    c, cfg = srv()
    deal = {"item": "Example item", "buy_price": 10}
    # "text/plain; application/json" is a CORS-safelisted type: a browser sends it cross-site without preflight
    assert api(c, "POST", "/deals/api/deals", deal, ctype="text/plain; application/json", site=None)[0] == 415
    assert api(c, "POST", "/deals/api/deals", deal, site="cross-site")[0] == 403
    assert api(c, "POST", "/deals/api/parts", {"name": "p"}, site=None,
               ctype="application/json")[0] == 200   # non-browser client / same origin still work
    h = {"Content-Type": "application/json", "Origin": "https://attacker.example"}
    assert c.req("POST", "/deals/api/deals", json.dumps(deal).encode(), h)[0] == 403
    status, data = api(c, "GET", "/deals/api/all")
    assert data["deals"] == []


def test_negative_content_length_does_not_hang(srv):
    c, _ = srv()
    status, _, _ = c.req("POST", "/deals/api/parts", b"{}", {"Content-Type": "application/json",
                                                                "Content-Length": "-1"})
    assert status == 400


# ------------------------------------------------------------------ misc

def test_text_keys_present_in_both_languages():
    keys = {k for k in texts.EN if k.startswith("w.")} | {"nav.wishes"}
    assert keys <= set(texts.DE)


def test_page_has_no_inline_handlers():
    style = wishes_page.css(deals_server.PAGE.read_text())
    page = wishes_page.render({}, style, "", "t.0", [{"id": 1, "name": "n", "terms": ["a"], "max_price": 5.0,
                                                       "platforms": ["ebay"], "active": True, "note": ""}])
    assert not re.search(r"\son\w+=", page) and "<script" not in page



def test_forwarded_host_only_when_trusted():
    h = {"Origin": "https://attacker.example", "X-Forwarded-Host": "attacker.example", "Host": "deals.example"}
    assert csrf.same_origin(h) is False                      # client-set X-Forwarded-Host is ignored
    assert csrf.same_origin(h, trust_forwarded_host=True) is True
    assert csrf.same_origin({"Origin": "https://Deals.Example:443", "Host": "deals.example"}) is True


def test_secret_symlink_not_followed(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("00" * 32)
    cfg = {"_data": tmp_path / "data"}
    csrf.secret_path(cfg).parent.mkdir(parents=True)
    csrf.secret_path(cfg).symlink_to(target)
    csrf._CACHE.clear()
    with pytest.raises(OSError):
        csrf.secret(cfg)


def test_price_rounded_before_check_and_update_needs_object():
    with pytest.raises(ValueError):
        wishes.validate({"name": "x", "terms": ["a"], "max_price": "0.001", "platforms": ["ebay"]})
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    i = wishes.create(con, {"name": "x", "terms": ["a"], "max_price": 5, "platforms": ["ebay"]})
    for bad in ([1, 2], "x"):
        with pytest.raises(ValueError):
            wishes.update(con, i, bad)
