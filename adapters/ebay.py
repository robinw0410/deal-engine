"""eBay adapter via the official Browse API (no scraping).

Stores item data only (title, price, condition, shipping cost, item location, item number,
description, images, item aspects). No eBay user data: no seller name, user id or feedback.

Credentials come from the environment: EBAY_CLIENT_ID, EBAY_CLIENT_SECRET (an application key
set from the eBay Developers Program, client-credentials grant). You need your own key, and your
use has to comply with the eBay API License Agreement and the API call limits of your key.

Search config:
  ebay:
    markets: [EBAY_DE]          # marketplace ids
    conditions: [3000, 7000]    # eBay condition ids (3000 used, 7000 for parts / not working)
    limit: 50
    include_auctions: false
    category_ids: ""            # optional
    keywords: [...]             # optional, otherwise the search's keywords
Location for shipping costs: location.postal_code / location.country in the config.
"""
import base64
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .base import Adapter, Blocked

API = "https://api.ebay.com"
DOMAIN = {"EBAY_AT": "www.ebay.at", "EBAY_DE": "www.ebay.de", "EBAY_US": "www.ebay.com",
          "EBAY_GB": "www.ebay.co.uk", "EBAY_FR": "www.ebay.fr", "EBAY_IT": "www.ebay.it",
          "EBAY_ES": "www.ebay.es", "EBAY_NL": "www.ebay.nl"}
FOR_PARTS = {"7000"}


def _money(m):
    try:
        return float(m["value"]) if isinstance(m, dict) and m.get("value") not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _ship(obj):
    costs = [_money(o.get("shippingCost")) for o in (obj.get("shippingOptions") or [])]
    costs = [c for c in costs if c is not None]
    return min(costs) if costs else None


def _loc(obj):
    loc = obj.get("itemLocation") or {}
    return " ".join(str(x) for x in (loc.get("country"), loc.get("postalCode"), loc.get("city")) if x).strip()


def to_listing(s, market):
    """Browse API item summary -> listing (docs/listing-format.md)."""
    legacy = str(s.get("legacyItemId") or "")
    if not legacy:
        m = re.search(r"\|(\d+)\|", str(s.get("itemId") or ""))
        legacy = m.group(1) if m else ""
    opts = s.get("buyingOptions") or []
    auction = "AUCTION" in opts and "FIXED_PRICE" not in opts
    price = (_money(s.get("currentBidPrice")) if auction else None) or _money(s.get("price"))
    return {
        "source_id": legacy,
        "url": f"https://{DOMAIN.get(market, 'www.ebay.com')}/itm/{legacy}",
        "title": s.get("title") or "",
        "price": price,
        "location": _loc(s),
        "shipping_possible": None,        # shipping is handled by eBay, shipping_cost says what it costs
        "shipping_cost": _ship(s),
        "condition": s.get("condition"),
        "for_parts": str(s.get("conditionId") or "") in FOR_PARTS,
        "auction": auction,
        "auction_end": s.get("itemEndDate") if auction else None,
        "best_offer": "BEST_OFFER" in opts,
        "published": str(s.get("itemCreationDate") or "")[:10] or None,
        "description": str(s.get("shortDescription") or ""),
        "images": [u for u in [(s.get("image") or {}).get("imageUrl")] if u],
        "attrs": {k: v for k, v in {"condition": s.get("condition"), "buying options": ", ".join(opts),
                                    "marketplace": market}.items() if v},
        "_item_id": s.get("itemId"),
        "_market": market,
    }


class EbayAdapter(Adapter):
    name = "ebay"

    def __init__(self, cfg, sc):
        super().__init__(cfg, sc)
        self.cid = os.environ.get("EBAY_CLIENT_ID", "").strip()
        self.secret = os.environ.get("EBAY_CLIENT_SECRET", "").strip()
        if not self.cid or not self.secret:
            raise SystemExit("EBAY_CLIENT_ID / EBAY_CLIENT_SECRET are not set")
        self.api = str(self.settings.get("api") or API).rstrip("/")
        loc = cfg.get("location") or {}
        self.zip, self.country = str(loc.get("postal_code") or ""), str(loc.get("country") or "")
        self.markets = self.settings.get("markets") or ["EBAY_DE"]
        self.token, self.expires = None, 0
        self._ids = {}     # legacy id -> (RESTful item id, market) for details()

    # ------------------------------------------------------------------ HTTP
    def _auth(self):
        if self.token and time.time() < self.expires - 120:
            return self.token
        basic = base64.b64encode(f"{self.cid}:{self.secret}".encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                       "scope": "https://api.ebay.com/oauth/api_scope"}).encode()
        req = urllib.request.Request(f"{self.api}/identity/v1/oauth2/token", data=body, method="POST", headers={
            "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise SystemExit(f"eBay token request failed: HTTP {e.code}")
        self.token, self.expires = d["access_token"], time.time() + int(d.get("expires_in", 7200))
        return self.token

    def _get(self, path, params=None, market=None):
        """(json, status). 404 -> (None, 404). 429 -> Blocked."""
        market = market or self.markets[0]
        url = self.api + path + ("?" + urllib.parse.urlencode(params, safe=":[]{}|,.") if params else "")
        headers = {"X-EBAY-C-MARKETPLACE-ID": market, "Accept": "application/json"}
        if self.zip and self.country:
            headers["X-EBAY-C-ENDUSERCTX"] = urllib.parse.quote(
                f"contextualLocation=country={self.country},zip={self.zip}", safe="=")
        for attempt in range(3):
            if self.requests:
                time.sleep(0.4)
            self.requests += 1
            req = urllib.request.Request(url, headers={**headers, "Authorization": f"Bearer {self._auth()}"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read() or b"{}"), r.status
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self.token = None
                    continue
                if e.code == 404:
                    return None, 404
                if e.code == 429:
                    raise Blocked("eBay API: call limit reached (HTTP 429)")
                if e.code >= 500 and attempt < 2:
                    time.sleep(10)
                    continue
                return None, e.code
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                if attempt < 2:
                    time.sleep(5)
                    continue
                return None, 0
        return None, 0

    # ------------------------------------------------------------------ interface
    def search(self, query):
        parts = []
        if self.settings.get("currency", "EUR"):
            parts.append(f"priceCurrency:{self.settings.get('currency', 'EUR')}")
        if self.country:
            parts.append(f"deliveryCountry:{self.country}")
        lo, hi = query.get("min_price"), query.get("max_price")
        if lo is not None or hi is not None:
            parts.insert(0, f"price:[{lo if lo is not None else ''}..{hi if hi is not None else ''}]")
        if self.settings.get("conditions"):
            parts.append("conditionIds:{" + "|".join(str(c) for c in self.settings["conditions"]) + "}")
        kw = query.get("keyword")
        if not kw:
            return []   # the Browse API needs a query; configure keywords
        out = []
        for market in self.markets:
            params = {"q": kw, "limit": int(self.settings.get("limit", 50)), "sort": "newlyListed",
                      "filter": ",".join(parts)}
            if self.settings.get("category_ids"):
                params["category_ids"] = self.settings["category_ids"]
            d, st = self._get("/buy/browse/v1/item_summary/search", params, market)
            if d is None and st not in (200, 404):
                raise RuntimeError(f"eBay search '{kw}' ({market}): HTTP {st}")
            for s in (d or {}).get("itemSummaries") or []:
                li = to_listing(s, market)
                if not li["source_id"] or li["price"] is None or not li["title"]:
                    continue
                if li["auction"] and not self.settings.get("include_auctions"):
                    continue
                self._ids[li["source_id"]] = (li.pop("_item_id"), li.pop("_market"))
                out.append(li)
        return out

    def check(self, source_id):
        d, st = self._get("/buy/browse/v1/item/get_item_by_legacy_id", {"legacy_item_id": source_id})
        if st == 404:
            return "gone"
        if not d:
            return "unknown"
        end = str(d.get("itemEndDate") or "")
        if end:
            try:
                if datetime.fromisoformat(end.replace("Z", "+00:00")) < datetime.now(timezone.utc):
                    return "gone"
            except ValueError:
                pass
        av = [str(a.get("estimatedAvailabilityStatus") or "") for a in d.get("estimatedAvailabilities") or []]
        if av and all(a == "OUT_OF_STOCK" for a in av):
            return "gone"
        return "active"

    def details(self, item, max_images=1):
        """Item details: description, images, aspects. No seller data."""
        item_id, market = self._ids.get(item["source_id"], (None, None))
        if not item_id:
            return {}
        d, _ = self._get(f"/buy/browse/v1/item/{urllib.parse.quote(str(item_id), safe='')}", market=market)
        if not d:
            return {}
        desc = d.get("description") or d.get("shortDescription") or ""
        desc = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", str(desc), flags=re.S | re.I)
        desc = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", desc))).strip()
        if d.get("conditionDescription"):
            desc = f"Condition according to the listing: {d['conditionDescription']}. {desc}"
        imgs = [(d.get("image") or {}).get("imageUrl")] + [x.get("imageUrl") for x in d.get("additionalImages") or []]
        attrs = {}
        for a in d.get("localizedAspects") or []:
            if a.get("name") and a.get("value") and len(attrs) < 25:
                attrs[a["name"]] = str(a["value"])[:120]
        out = {"description": desc[:1800], "images": [u for u in imgs if u][:max_images], "attrs": attrs}
        if _ship(d) is not None:
            out["shipping_cost_eur"] = _ship(d)
        if d.get("itemLocation"):
            out["location"] = _loc(d)
        return out


def probe(argv=None):
    """Live check of the adapter: token, one search per marketplace, one getItem, one check().
    Prints item data only and writes nothing. Credentials only from the environment."""
    import argparse
    import time as _time
    ap = argparse.ArgumentParser(prog="python -m adapters.ebay")
    ap.add_argument("keyword")
    ap.add_argument("--markets", nargs="+", default=["EBAY_DE"])
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--country", help="delivery country (default: location.country from the config)")
    ap.add_argument("--zip", help="delivery postal code (default: location.postal_code from the config)")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    from core import config as config_mod
    cfg = config_mod.load(a.config)
    loc = dict(cfg.get("location") or {})
    if a.country:
        loc["country"] = a.country
    if a.zip:
        loc["postal_code"] = a.zip
    cfg = {**cfg, "location": loc}
    sc = {"_name": "probe", "ebay": {"markets": a.markets, "limit": a.limit, "include_auctions": True}}
    ad = EbayAdapter(cfg, sc)
    t = _time.time()
    ad._auth()
    print(f"token ok ({_time.time() - t:.1f}s)")
    found = []
    for m in a.markets:
        ad.markets = [m]
        res = ad.search({"keyword": a.keyword})
        print(f"{m} '{a.keyword}': {len(res)} items")
        for li in res:
            print(f"  {li['source_id']}  {li['price']} + {li['shipping_cost']} shipping  {li['title'][:60]}  "
                  f"| {li['condition']} | {li['location']}")
        found += res
    if found:
        it = {"source_id": found[0]["source_id"]}
        d = ad.details(it, 6)
        print(f"getItem {it['source_id']}: description {len(d.get('description', ''))} chars, "
              f"{len(d.get('images', []))} images, {len(d.get('attrs', {}))} aspects, location {d.get('location')!r}")
        print(f"check {it['source_id']}: {ad.check(it['source_id'])}")
    print(f"{ad.requests} API requests")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(probe())
