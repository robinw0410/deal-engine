"""v0.2.14: optional search terms on the wish list, suggested terms from a host application.

Migration of a 0.2.13 database, terms_source / terms_updated / terms_regen, set_ai_terms never
overwriting the user's terms (also not after a race), clean_ai_terms, and the page / API end to end
over a real server on 127.0.0.1 (helpers of test_v0213_wishes)."""
import json
import re
import sqlite3

import pytest

from deal_engine.deals import deals_server, texts, wishes
from test_v0213_wishes import FORM, api, db_wishes, make_cfg, srv, wish  # noqa: F401  (srv is a fixture)

OLD_SCHEMA = """
CREATE TABLE wish(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, terms TEXT NOT NULL, max_price REAL NOT NULL,
  platforms TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, note TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL, updated TEXT NOT NULL);
"""


def old_db(cfg):
    """A deals.db as 0.2.13 left it: wish table without the new columns, one wish."""
    con = deals_server.connect(cfg)
    con.executescript(OLD_SCHEMA)
    con.execute("INSERT INTO wish(name, terms, max_price, platforms, active, note, created, updated) "
                "VALUES ('Old wish', '[\"old term\"]', 50, '[\"ebay\"]', 1, '', '2026-11-01T10:00:00', "
                "'2026-11-01T10:00:00')")
    con.commit()
    con.close()


def raw(cfg, sql, args=()):
    con = deals_server.connect(cfg)
    try:
        with con:
            return con.execute(sql, args).fetchall()
    finally:
        con.close()


def one(cfg, wid):
    return [w for w in db_wishes(cfg) if w["id"] == wid][0]


@pytest.fixture
def mem():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    yield con
    con.close()


# ------------------------------------------------------------------ migration

def test_active_on_old_database_read_only_has_defaults(tmp_path):
    cfg = make_cfg(tmp_path)
    old_db(cfg)
    [w] = wishes.active(cfg)
    assert (w["name"], w["terms"]) == ("Old wish", ["old term"])
    assert (w["terms_source"], w["terms_updated"], w["terms_regen"]) == ("user", None, False)
    cols = {r[1] for r in raw(cfg, "PRAGMA table_info(wish)")}
    assert "terms_source" not in cols          # active() is read-only: nothing migrated


def test_init_adds_columns_to_old_database(tmp_path):
    cfg = make_cfg(tmp_path)
    old_db(cfg)
    deals_server.init(cfg)
    deals_server.init(cfg)                      # twice: idempotent
    cols = {r[1] for r in raw(cfg, "PRAGMA table_info(wish)")}
    assert {"terms_source", "terms_updated", "terms_regen"} <= cols
    [w] = db_wishes(cfg)
    assert (w["terms"], w["terms_source"], w["terms_regen"]) == (["old term"], "user", False)
    assert wishes.set_ai_terms(cfg, w["id"], ["new"]) is False   # old terms are the user's


# ------------------------------------------------------------------ data layer

@pytest.mark.parametrize("terms", [[], ["", " "], "", None])
def test_empty_terms_allowed(terms):
    assert wishes.validate(wish(terms=terms if terms is not None else []))["terms"] == []


def test_create_without_terms_is_ai_and_pending(mem):
    wid = wishes.create(mem, wish(terms=[]))
    [w] = wishes.rows(mem)
    assert w["id"] == wid and w["terms"] == [] and w["terms_source"] == "ai" and w["terms_updated"] is None
    assert wishes.needs_terms(w)
    wishes.create(mem, wish(name="with terms"))
    w2 = wishes.rows(mem)[1]
    assert w2["terms_source"] == "user" and w2["terms_updated"] and not wishes.needs_terms(w2)
    assert not wishes.needs_terms(dict(w, active=False))


def test_update_changed_terms_become_user_terms(mem):
    wid = wishes.create(mem, wish(terms=[]))
    wishes.update(mem, wid, {"name": "renamed"})                  # terms unchanged: still "ai"
    assert wishes.rows(mem)[0]["terms_source"] == "ai"
    wishes.update(mem, wid, {"terms": ["mine"]})
    w = wishes.rows(mem)[0]
    assert (w["terms"], w["terms_source"], w["terms_regen"]) == (["mine"], "user", False) and w["terms_updated"]
    wishes.update(mem, wid, {"terms": []})                        # emptied: suggestions again
    w = wishes.rows(mem)[0]
    assert w["terms_source"] == "ai" and wishes.needs_terms(w)


def test_request_regen(mem):
    wid = wishes.create(mem, wish())
    wishes.request_regen(mem, wid)
    w = wishes.rows(mem)[0]
    assert w["terms_regen"] is True and w["terms"] == ["example camera", "camera x1"] and wishes.needs_terms(w)
    with pytest.raises(KeyError):
        wishes.request_regen(mem, 999)


def test_set_ai_terms_rules(tmp_path):
    cfg = make_cfg(tmp_path)
    con = deals_server.connect(cfg)
    with con:
        empty = wishes.create(con, wish(name="empty", terms=[]))
        mine = wishes.create(con, wish(name="mine"))
    con.close()

    assert wishes.set_ai_terms(cfg, empty, ["example camera", "compact camera"]) is True
    w = one(cfg, empty)
    assert (w["terms"], w["terms_source"], w["terms_regen"]) == (["example camera", "compact camera"], "ai", False)
    assert w["terms_updated"] and not wishes.needs_terms(w)
    assert wishes.set_ai_terms(cfg, empty, ["other"]) is False   # already has (suggested) terms, no request

    assert wishes.set_ai_terms(cfg, mine, ["replacement"]) is False
    assert one(cfg, mine)["terms"] == ["example camera", "camera x1"]

    con = deals_server.connect(cfg)
    with con:
        wishes.request_regen(con, mine)
    con.close()
    assert wishes.set_ai_terms(cfg, mine, ["replacement"]) is True   # requested: replaces the user's terms
    w = one(cfg, mine)
    assert (w["terms"], w["terms_source"], w["terms_regen"]) == (["replacement"], "ai", False)

    assert wishes.set_ai_terms(cfg, empty, ["(.*)"]) is False         # nothing valid left: no write
    assert wishes.set_ai_terms(cfg, 999, ["x"]) is False


def test_set_ai_terms_race_user_changed_terms_after_read(tmp_path):
    cfg = make_cfg(tmp_path)
    con = deals_server.connect(cfg)
    with con:
        empty = wishes.create(con, wish(name="empty", terms=[]))
        regen = wishes.create(con, wish(name="regen"))
        wishes.request_regen(con, regen)
    con.close()
    todo = [w for w in wishes.active(cfg) if wishes.needs_terms(w)]   # the host application reads ...
    assert {w["id"] for w in todo} == {empty, regen}
    con = deals_server.connect(cfg)
    with con:                                                         # ... the user edits meanwhile ...
        wishes.update(con, empty, {"terms": ["typed by user"]})
        wishes.update(con, regen, {"terms": ["changed by user"]})
    con.close()
    for w in todo:                                                    # ... the suggestions arrive late
        assert wishes.set_ai_terms(cfg, w["id"], ["model term"]) is False
    assert one(cfg, empty)["terms"] == ["typed by user"] and one(cfg, empty)["terms_source"] == "user"
    assert one(cfg, regen)["terms"] == ["changed by user"] and one(cfg, regen)["terms_regen"] is False


def test_clean_ai_terms():
    long = "x" * (wishes.MAX_TERM + 1)
    got = wishes.clean_ai_terms(["camera.*", "(camera|cam)", "cam[0-9]", "a+b", "x?", "^start", "end$",
                                 "back\\slash", "{1,2}", "<b>", "`cmd`", long, 5, None, ["nested"], {"a": 1},
                                 " Example  Camera ", "example camera", "EXAMPLE CAMERA", "tab\tterm",
                                 "camera x1", "model 2", "model 3", "model 4", "model 5"])
    assert got == ["Example Camera", "tab term", "camera x1", "model 2", "model 3"]
    assert len(got) == wishes.MAX_TERMS
    assert wishes.clean_ai_terms("not a list") == [] and wishes.clean_ai_terms(None) == []
    assert wishes.clean_ai_terms(["", "  ", "\x00"]) == []


# ------------------------------------------------------------------ page and API

def test_form_create_without_terms_label_and_regen(srv):
    c, cfg = srv()
    page = c.page()
    assert texts.EN["w.f.terms_hint"] in page
    form = re.search(r'<form method="post" action="./" class="wform".*?</form>', page, re.S).group(0)
    assert " required" not in re.sub(r'<input name="(name|max_price)" required', "", form)   # terms optional
    status, headers, _ = c.post({**FORM, "terms": ["", "", ""]})
    assert status == 303 and headers["Location"].endswith("done=created")
    [w] = db_wishes(cfg)
    assert w["terms"] == [] and w["terms_source"] == "ai"
    page = c.page()
    assert texts.EN["w.pending"] in page and texts.EN["w.ai"] not in page

    assert wishes.set_ai_terms(cfg, w["id"], ["example camera", "compact <cam>", "camera x1"]) is True
    page = c.page()
    stamp = one(cfg, w["id"])["terms_updated"].replace("T", " ")[:16]
    assert texts.EN["w.ai"] in page and stamp in page and texts.EN["w.pending"] not in page
    assert "<span>example camera</span>" in page and "<cam>" not in page    # syntax characters dropped
    edit = c.page(f"/deals/wishes/?edit={w['id']}")
    assert 'value="example camera"' in edit and texts.EN["w.f.terms_ai"] in edit

    # regen button: without token refused, with token flag + message
    assert 'value="regen"' in page and texts.EN["w.regen"] in page
    status, _, _ = c.post({"action": "regen", "id": w["id"]}, token=None)
    assert status == 403 and one(cfg, w["id"])["terms_regen"] is False
    status, headers, _ = c.post({"action": "regen", "id": w["id"]}, headers={"Sec-Fetch-Site": "cross-site"})
    assert status == 403 and one(cfg, w["id"])["terms_regen"] is False
    status, headers, _ = c.post({"action": "regen", "id": w["id"]})
    assert status == 303 and headers["Location"] == "/deals/wishes/?done=regen"
    assert one(cfg, w["id"])["terms_regen"] is True
    page = c.page("/deals/wishes/?done=regen")
    assert texts.EN["w.ok.regen"] in page and texts.EN["w.pending"] in page
    assert c.post({"action": "regen", "id": 999})[0] == 404

    # editing the suggested terms makes them the user's
    status, _, _ = c.post({**FORM, "action": "update", "id": w["id"], "terms": ["my own term"]})
    assert status == 303
    w = one(cfg, w["id"])
    assert (w["terms"], w["terms_source"], w["terms_regen"]) == (["my own term"], "user", False)
    page = c.page()
    assert texts.EN["w.ai"] not in page and texts.EN["w.pending"] not in page


def test_page_german_labels(srv):
    c, cfg = srv(locale="de")
    assert c.post({**FORM, "terms": []})[0] == 303
    page = c.page()
    assert "Vorschläge ausstehend" in page and "Begriffe neu vorschlagen" in page
    assert "Leer lassen: Vorschläge werden beim nächsten Lauf erzeugt." in page
    wishes.set_ai_terms(cfg, db_wishes(cfg)[0]["id"], ["Beispielkamera"])
    assert "KI-Vorschlag" in c.page()


def test_api_empty_terms_fields_and_regen(srv):
    c, cfg = srv()
    tok = api(c, "GET", "/deals/api/wishes")[1]["csrf"]
    status, data = api(c, "POST", "/deals/api/wishes", wish(terms=[]), tok)
    assert status == 200
    [w] = data["wishes"]
    assert w["terms"] == [] and w["terms_source"] == "ai" and w["terms_updated"] is None and w["terms_regen"] is False
    status, data = api(c, "PUT", f"/deals/api/wishes/{w['id']}", {"terms": ["mine"]}, tok)
    assert status == 200 and data["wishes"][0]["terms_source"] == "user"
    status, data = api(c, "PUT", f"/deals/api/wishes/{w['id']}", {"terms": []}, tok)
    assert status == 200 and data["wishes"][0]["terms"] == [] and data["wishes"][0]["terms_source"] == "ai"

    path = f"/deals/api/wishes/{w['id']}/regen"
    assert api(c, "POST", path)[0] == 403                                   # no token
    assert api(c, "POST", path, None, "1.bad")[0] == 403
    assert api(c, "POST", path, None, tok, site="cross-site")[0] == 403
    h = {"Content-Type": "application/json", "X-CSRF-Token": tok, "Origin": "https://attacker.example"}
    assert c.req("POST", path, b"", h)[0] == 403
    assert api(c, "POST", path, None, tok, ctype="text/plain")[0] == 415
    assert db_wishes(cfg)[0]["terms_regen"] is False
    status, data = api(c, "POST", path, None, tok)
    assert status == 200 and data["wishes"][0]["terms_regen"] is True
    assert api(c, "POST", path, {"ignored": 1}, tok)[0] == 200
    assert api(c, "POST", "/deals/api/wishes/999/regen", None, tok)[0] == 404
    status, data = api(c, "GET", "/deals/api/wishes")
    assert set(data["wishes"][0]) >= {"terms_source", "terms_updated", "terms_regen"}
    assert json.dumps(data)   # serialisable


def test_csp_hash_matches_style(srv):
    c, _ = srv()
    status, headers, page = c.req("GET", "/deals/wishes/")
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    assert deals_server.wishes_page.csp(style) == headers["Content-Security-Policy"]
    assert " style=" not in page and "<script" not in page



def test_stale_edit_form_keeps_suggestions_that_arrived_later(tmp_path):
    import sqlite3
    cfg = {"_data": tmp_path}
    from deal_engine.deals.deals_server import connect
    con = connect(cfg)
    with con:
        i = wishes.create(con, {"name": "Example camera", "terms": [], "max_price": 100, "platforms": ["ebay"]})
    seen = ""   # edit form opened while no terms existed
    assert wishes.set_ai_terms(cfg, i, ["example camera body"])
    with con:   # user saves the stale form (only changes the price)
        wishes.update(con, i, {"name": "Example camera", "terms": [], "max_price": 90, "platforms": ["ebay"],
                               "terms_seen": seen})
    (w,) = wishes.rows(con)
    assert w["terms"] == ["example camera body"] and w["terms_source"] == "ai" and w["max_price"] == 90
    with con:   # form rendered with the current terms_updated: clearing is deliberate
        wishes.update(con, i, {"terms": [], "terms_seen": w["terms_updated"]})
    assert wishes.rows(con)[0]["terms"] == []
    con.close()



def test_stale_form_with_shown_terms_keeps_new_suggestions(tmp_path):
    """Regen requested, form opened with T1, runner stores T2, user only changes the price."""
    cfg = {"_data": tmp_path}
    from deal_engine.deals.deals_server import connect
    con = connect(cfg)
    with con:
        i = wishes.create(con, {"name": "Example camera", "terms": [], "max_price": 100, "platforms": ["ebay"]})
    assert wishes.set_ai_terms(cfg, i, ["old one", "old two"])
    with con:
        wishes.request_regen(con, i)
    w1 = wishes.rows(con)[0]
    form = {"terms_seen": w1["terms_updated"], "terms_shown": json.dumps(w1["terms"])}
    with con:   # T2 arrives later (distinct timestamp even within the same second)
        con.execute("UPDATE wish SET terms_updated='2000-01-01T00:00:00' WHERE id=?", (i,))
    form["terms_seen"] = "2000-01-01T00:00:00"
    assert wishes.set_ai_terms(cfg, i, ["new one"])
    with con:
        wishes.update(con, i, dict(form, terms=["old one", "old two"], max_price=80))
    w = wishes.rows(con)[0]
    assert w["terms"] == ["new one"] and w["terms_source"] == "ai" and w["max_price"] == 80
    with con:   # visibly edited terms in the stale form: the user's terms win
        wishes.update(con, i, dict(form, terms=["my term"]))
    assert wishes.rows(con)[0]["terms"] == ["my term"] and wishes.rows(con)[0]["terms_source"] == "user"
    con.close()


def test_set_ai_terms_refuses_when_wish_changed_meanwhile(tmp_path):
    cfg = {"_data": tmp_path}
    from deal_engine.deals.deals_server import connect
    con = connect(cfg)
    with con:
        i = wishes.create(con, {"name": "Bicycle A", "terms": [], "max_price": 100, "platforms": ["ebay"]})
    read = wishes.rows(con)[0]
    with con:
        wishes.update(con, i, {"name": "Camera Z"})
    assert wishes.set_ai_terms(cfg, i, ["bicycle a"], expect={"name": read["name"], "note": read["note"]}) is False
    assert wishes.needs_terms(wishes.rows(con)[0])
    con.close()


@pytest.mark.parametrize("bad", ['"exact phrase"', "-defekt camera", "camera OR phone", "camera -broken",
                                 "+camera"])
def test_clean_ai_terms_drops_search_operators(bad):
    assert wishes.clean_ai_terms([bad]) == []


def test_clean_ai_terms_strips_invisible_characters():
    assert wishes.clean_ai_terms(["a\u202eb", "x\u200by"]) == ["ab", "xy"]
