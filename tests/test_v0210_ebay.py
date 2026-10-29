"""v0.2.10 eBay: one category id per request, eBay error text on 4xx, a failing request does not stop the search.

No network: urllib.request.urlopen is replaced by a fake that answers token, search and error requests.
"""
import io
import json
import urllib.error
import urllib.parse

import pytest

from deal_engine.adapters import ebay
from deal_engine.adapters.base import Blocked
from deal_engine.core import pipeline
from deal_engine.core.config import ConfigError

TOKEN = "v^1.1#i^1#TESTTOKEN0123456789"


def item(n):
    return {"legacyItemId": str(n), "itemId": f"v1|{n}|0", "title": f"Item {n}", "price": {"value": "20.0"},
            "buyingOptions": ["FIXED_PRICE"]}


class Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeEbay:
    """answer(params, market) -> list of items, or (code, body) for an HTTP error."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, req, timeout=30):
        url = urllib.parse.urlparse(req.full_url)
        if url.path.endswith("/oauth2/token"):
            return Resp(json.dumps({"access_token": TOKEN, "expires_in": 7200}).encode())
        params = dict(urllib.parse.parse_qsl(url.query))
        market = req.get_header("X-ebay-c-marketplace-id")
        self.calls.append((params, market))
        r = self.answer(params, market)
        if isinstance(r, tuple):
            code, body = r
            raise urllib.error.HTTPError(req.full_url, code, "error", {}, io.BytesIO(json.dumps(body).encode()))
        return Resp(json.dumps({"itemSummaries": r}).encode())


def adapter(monkeypatch, answer, **settings):
    monkeypatch.setenv("EBAY_CLIENT_ID", "my-client-id-123")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "my-client-secret-456")
    fake = FakeEbay(answer)
    monkeypatch.setattr(ebay.urllib.request, "urlopen", fake)
    monkeypatch.setattr(ebay.time, "sleep", lambda s: None)
    sc = {"_name": "s", "ebay": {"markets": ["EBAY_AT", "EBAY_DE"], "keywords": ["cord", "pulli", "brogue"],
                                 **settings}}
    return ebay.EbayAdapter({"location": {}}, sc), fake


BAD_CATEGORY = {"errors": [{"errorId": 12023, "domain": "API_BROWSE", "category": "REQUEST",
                            "message": "Invalid category ID. Bearer " + TOKEN + " only one category"}]}


def test_400_error_text_in_exception_without_token(monkeypatch):
    ad, fake = adapter(monkeypatch, lambda p, m: (400, BAD_CATEGORY))
    with pytest.raises(RuntimeError) as e:
        ad.search({"keyword": "cord"})
    msg = str(e.value)
    assert "HTTP 400" in msg and "errorId 12023" in msg and "Invalid category ID" in msg
    assert TOKEN not in msg and "TESTTOKEN" not in msg and "my-client" not in msg
    assert "EBAY_AT" in msg and "EBAY_DE" in msg


def test_error_text_shortened_and_robust():
    long = {"errors": [{"errorId": i, "message": "x" * 500} for i in range(10)]}
    err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(json.dumps(long).encode()))
    assert len(ebay._error_text(err)) <= 300
    for body in (b"", b"not json", b'{"errors": "nope"}', b"[1, 2]"):
        assert ebay._error_text(urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(body))) == ""
    assert ebay._error_text(urllib.error.HTTPError("u", 400, "bad", {}, None)) == ""
    secret = {"errors": [{"errorId": 1, "message": "key my-client-secret-456 rejected"}]}
    err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(json.dumps(secret).encode()))
    assert "my-client-secret" not in ebay._error_text(err, ("my-client-secret-456",))


def test_one_category_per_request(monkeypatch):
    ad, fake = adapter(monkeypatch, lambda p, m: [item(len(fake.calls))], category_ids="11484, 57989")
    out = ad.search({"keyword": "cord"})
    assert [(p.get("category_ids"), m) for p, m in fake.calls] == [
        ("11484", "EBAY_AT"), ("57989", "EBAY_AT"), ("11484", "EBAY_DE"), ("57989", "EBAY_DE")]
    assert len(out) == 4 and ad.requests == 4 and ad.warnings == []


def test_category_ids_as_list_and_none(monkeypatch):
    ad, fake = adapter(monkeypatch, lambda p, m: [], category_ids=[11484, "11484", 57989])
    ad.search({"keyword": "cord"})
    assert [p["category_ids"] for p, _ in fake.calls] == ["11484", "57989"] * 2
    ad, fake = adapter(monkeypatch, lambda p, m: [])
    ad.search({"keyword": "cord"})
    assert len(fake.calls) == 2 and all("category_ids" not in p for p, _ in fake.calls)


def test_keyword_categories_override(monkeypatch):
    ad, fake = adapter(monkeypatch, lambda p, m: [], category_ids="1",
                       keyword_categories={"Cord ": 57989, "brogue": [53120, 24087]})
    for kw in ("cord", "brogue", "pulli"):
        ad.search({"keyword": kw})
    by_kw = {}
    for p, m in fake.calls:
        by_kw.setdefault(p["q"], []).append(p["category_ids"])
    assert by_kw == {"cord": ["57989"] * 2, "brogue": ["53120", "24087"] * 2, "pulli": ["1"] * 2}


@pytest.mark.parametrize("kc", [["cord"], "cord: 1"])
def test_keyword_categories_must_be_mapping(monkeypatch, kc):
    with pytest.raises(ConfigError):
        adapter(monkeypatch, lambda p, m: [], keyword_categories=kc)


def test_keyword_categories_unknown_term_is_config_error(monkeypatch):
    with pytest.raises(ConfigError) as e:
        adapter(monkeypatch, lambda p, m: [], keyword_categories={"chukka": 11498})
    assert "chukka" in str(e.value)


def test_failing_category_skipped_with_warning(monkeypatch):
    """11498 refused: the term still delivers the other category, the failure becomes a warning."""
    ad, fake = adapter(monkeypatch, lambda p, m: (400, BAD_CATEGORY) if p["category_ids"] == "11498"
                       else [item(m[-2:] + p["category_ids"])], keyword_categories={"brogue": [11498, 24087]})
    out = ad.search({"keyword": "brogue"})
    assert sorted(i["source_id"] for i in out) == ["AT24087", "DE24087"]
    assert len(ad.warnings) == 1
    w = ad.warnings[0]
    assert "category 11498" in w and "errorId 12023" in w and "24087" not in w and TOKEN not in w


def test_429_still_blocks(monkeypatch):
    ad, _ = adapter(monkeypatch, lambda p, m: (429, {"errors": [{"errorId": 1, "message": "limit"}]}))
    with pytest.raises(Blocked):
        ad.search({"keyword": "cord"})


def test_pipeline_skips_failing_term_reports_and_goes_on(monkeypatch):
    def answer(p, m):
        if p["q"] == "cord":
            return (400, BAD_CATEGORY)                                  # whole term fails
        if p["q"] == "brogue" and p.get("category_ids") == "11498":
            return (400, BAD_CATEGORY)                                  # one of its categories fails
        return [item(f"{p['q']}{m[-2:]}{p.get('category_ids', '')}")]
    ad, fake = adapter(monkeypatch, answer, keyword_categories={"brogue": [11498, 24087]})
    logs = []
    items, problems = pipeline.search_all({"location": {}}, ad.sc, ad, log=logs.append)
    assert sorted(items) == ["brogueAT24087", "brogueDE24087", "pulliAT", "pulliDE"]
    assert len(problems) == 2
    assert "'cord'" in problems[0] and "errorId 12023" in problems[0]
    assert "'brogue'" in problems[1] and "category 11498" in problems[1]
    assert ad.warnings == []
    assert "  'pulli': 2 results" in logs


def test_pipeline_429_aborts(monkeypatch):
    ad, _ = adapter(monkeypatch, lambda p, m: (429, {}))
    with pytest.raises(Blocked):
        pipeline.search_all({"location": {}}, ad.sc, ad, log=lambda s: None)


def test_adapter_without_warnings_attribute_still_works():
    class Old:
        name = "old"

        def search(self, q):
            return []
    problems = []
    from deal_engine.core import locale as locale_mod
    pipeline._search(Old(), {"keyword": "x"}, None, 1.3, {}, problems, locale_mod.for_search({}, {}))
    assert problems == []


# ------------------------------------------------------------------ review of 0.2.10
def test_raw_token_in_long_message_scrubbed_before_shortening(monkeypatch):
    long_token = "v^1.1#" + "A" * 400
    body = {"errors": [{"errorId": 1, "message": "x" * 100 + " token " + long_token + " rejected"}]}

    def answer(p, m):
        return (400, body)
    ad, _ = adapter(monkeypatch, answer)
    ad.token, ad.expires = long_token, 10 ** 12
    with pytest.raises(RuntimeError) as e:
        ad.search({"keyword": "cord"})
    assert "AAAAAAAAAA" not in str(e.value) and "***" in str(e.value)
    import base64
    basic = base64.b64encode(b"my-client-id-123:my-client-secret-456").decode()
    err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(json.dumps(
        {"errors": [{"errorId": 2, "message": "y" * 150 + basic}]}).encode()))
    assert basic[:10] not in ebay._error_text(err, (basic,))


@pytest.mark.parametrize("empty", [[], "", " , "])
def test_keyword_categories_empty_ids_is_config_error(monkeypatch, empty):
    with pytest.raises(ConfigError) as e:
        adapter(monkeypatch, lambda p, m: [], keyword_categories={"cord": empty})
    assert "cord" in str(e.value)


def test_keyword_categories_case_and_umlauts(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    sc = {"_name": "s", "ebay": {"keywords": ["Rahmengenäht  Schuhe Herren"],
                                 "keyword_categories": {"rahmengenäht schuhe herren": [53120, 24087]}}}
    ad = ebay.EbayAdapter({"location": {}}, sc)
    assert ad.categories("Rahmengenäht  Schuhe Herren") == ["53120", "24087"]
    assert ad.categories("market group term") == []


def test_last_error_not_carried_to_a_later_request(monkeypatch):
    """First category fails with an error text, second fails without a body: no stale text attached."""
    def answer(p, m):
        return (400, BAD_CATEGORY) if p["category_ids"] == "1" else (400, {})
    ad, _ = adapter(monkeypatch, answer, markets=["EBAY_DE"], category_ids="1,2")
    with pytest.raises(RuntimeError) as e:
        ad.search({"keyword": "cord"})
    first, second = str(e.value).split("; ")
    assert "category 1" in first and "errorId 12023" in first
    assert second == "EBAY_DE, category 2: HTTP 400"


def test_401_twice_reports_error(monkeypatch):
    ad, fake = adapter(monkeypatch, lambda p, m: (401, {"errors": [{"errorId": 1001, "message": "Invalid access token"}]}),
                       markets=["EBAY_DE"])
    with pytest.raises(RuntimeError) as e:
        ad.search({"keyword": "cord"})
    assert len(fake.calls) == 2 and "HTTP 401" in str(e.value) and "errorId 1001" in str(e.value)


def test_5xx_after_retries_skipped_with_warning(monkeypatch):
    ad, fake = adapter(monkeypatch, lambda p, m: (503, {"errors": [{"errorId": 2001, "message": "down"}]})
                       if m == "EBAY_AT" else [item(7)])
    out = ad.search({"keyword": "cord"})
    assert [i["source_id"] for i in out] == ["7"] and len(fake.calls) == 4     # 3 tries on EBAY_AT, 1 on EBAY_DE
    assert "EBAY_AT: HTTP 503 (errorId 2001: down)" in ad.warnings[0]


def test_warnings_reported_even_when_blocked():
    from deal_engine.core import locale as locale_mod

    class Half:
        name = "half"

        def __init__(self):
            self.warnings = []

        def search(self, q):
            self.warnings.append("part failed")
            raise Blocked("429")
    a, problems = Half(), []
    with pytest.raises(Blocked):
        pipeline._search(a, {"keyword": "x"}, None, 1.3, {}, problems, locale_mod.for_search({}, {}))
    assert a.warnings == [] and "part failed" in problems[0]
