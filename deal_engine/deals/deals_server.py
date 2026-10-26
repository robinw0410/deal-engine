"""Deal list + parts inventory.

Tracks purchases (deals), the parts used for them, a parts catalogue with stock, and part
purchases (unit cost = moving average). For open deals it shows a listing price hint from the
market data of one search (deals.market_search in the config).

  python -m deal_engine.deals.deals_server [--config PATH] [--port N] [--web-root DIR]
  python -m deal_engine.deals.deals_server --prompt-block SEARCH    parts catalogue as a prompt section

Binds to 127.0.0.1 only and has no authentication. Do not expose it to a network without
putting authentication in front of it (e.g. a reverse proxy).
With --web-root, the rendered search pages are served at / as well (handy for the demo).
"""
import argparse
import json
import mimetypes
import re
import secrets
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..core import clock, history
from ..core import locale as locale_mod
from ..core import config as config_mod
from ..core.groups import match_group
from ..core.market import settings as market_settings
from ..core.util import load_json, median

PAGE = Path(__file__).resolve().parent / "deals.html"
LOCK = threading.Lock()
CFG = {}

STATUSES = ("bought", "in progress", "listed", "sold", "scrapped")
DEAL_FIELDS = {
    "item": str, "category": str, "link": str, "notes": str, "status": str,
    "bought_date": str, "sold_date": str,
    "buy_price": float, "parts_cost": float, "other_cost": float, "hours": float, "sell_price": float,
    "listing_id": str, "est_profit": float, "est_hours": float, "market_group": str,
}
PART_FIELDS = {
    "name": str, "device": str, "spec": str, "unit_cost": float, "qty": int,
    "install_min": int, "estimated": int, "link": str, "notes": str,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS deal(
  id TEXT PRIMARY KEY, item TEXT NOT NULL, category TEXT, link TEXT, notes TEXT,
  status TEXT NOT NULL DEFAULT 'bought', bought_date TEXT, sold_date TEXT,
  buy_price REAL, parts_cost REAL, other_cost REAL, hours REAL, sell_price REAL,
  listing_id TEXT, est_profit REAL, est_hours REAL, market_group TEXT
);
CREATE TABLE IF NOT EXISTS part(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, device TEXT, spec TEXT,
  unit_cost REAL, qty INTEGER NOT NULL DEFAULT 0, install_min INTEGER,
  estimated INTEGER NOT NULL DEFAULT 0, link TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS deal_part(
  deal_id TEXT NOT NULL REFERENCES deal(id) ON DELETE CASCADE,
  part_id INTEGER NOT NULL REFERENCES part(id),
  qty INTEGER NOT NULL, unit_cost REAL,
  PRIMARY KEY (deal_id, part_id)
);
CREATE TABLE IF NOT EXISTS purchase(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  part_id INTEGER NOT NULL REFERENCES part(id),
  qty INTEGER NOT NULL, total_cost REAL NOT NULL,
  date TEXT, source TEXT, notes TEXT
);
"""


# ---------------------------------------------------------------------------- database
def db_path(cfg=None):
    cfg = cfg or CFG
    return cfg["_data"] / "state" / "deals.db"


def connect(cfg=None):
    p = db_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init(cfg=None):
    con = connect(cfg)
    con.executescript(SCHEMA)
    con.close()


def clean(body, fields, base=None, required="item"):
    d = dict(base or {})
    for k, typ in fields.items():
        if k not in body:
            continue
        v = body[k]
        if v in (None, ""):
            d[k] = None
            continue
        if typ in (float, int):
            try:
                v = typ(float(str(v).replace(",", ".")))
            except ValueError:
                raise ValueError(f"{k}: not a number")
            if typ is float:
                v = round(v, 2)
            if not (-100000 <= v <= 100000) or (v < 0 and k != "est_profit"):
                raise ValueError(f"{k}: implausible value")
        else:
            v = str(v)[:1000].strip()
            if k.endswith("_date") and v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                raise ValueError(f"{k}: date as YYYY-MM-DD")
            if k == "link" and v and not re.match(r"https?://", v):
                raise ValueError("link: must start with http(s)://")
        d[k] = v
    if not d.get(required):
        raise ValueError(f"{required} is missing")
    return d


# ---------------------------------------------------------------------------- price hint
def market_data(cfg=None):
    """Market groups, current market prices and sale data from tracking for deals.market_search."""
    cfg = cfg or CFG
    name = (cfg.get("deals") or {}).get("market_search")
    if not name or name not in (cfg.get("searches") or {}):
        return [], {}, {}, {}
    sc = config_mod.search(cfg, name)
    P = config_mod.paths(cfg, name)
    market = load_json(P["market"], {})
    sold = {}
    if P["history"].exists():
        try:
            con = history.connect(P["history"])
            sold = history.sold_by_group(con, name, 60)
            con.close()
        except sqlite3.Error:
            pass
    mc = sc.get("market") or {}
    return mc.get("groups", []), market, sold, market_settings(mc)


def price_hint(d, groups, market, sold, ms, loc=None):
    """Suggested listing price and lower bound for a deal."""
    loc = loc or locale_mod.get((CFG or {}).get("locale"))
    grp = d.get("market_group")
    if not grp:
        g = match_group(d.get("item") or "", groups)
        grp = g["name"] if g else None
    m = market.get(grp) if grp else None
    if not m:
        return {"group": grp, "list": None, "floor": None,
                "text": loc.t("hint.none")}
    floor = min(m.get("p25") or m["median"], m["median"] * float(ms.get("sale_factor", 0.85)))
    s = sold.get(grp)
    src = loc.t("hint.offers", n=m["n"])
    days = None
    if s and len(s["p"]) >= 8:
        floor = min(floor, median(s["p"]) * 0.93)
        src = loc.t("hint.both", gone=len(s["p"]), n=m["n"])
        days = median(s["d"]) if s["d"] else None
    lst = max(m["median"], floor * 1.12)

    def r5(x):
        return int(round(x / 5.0) * 5)
    return {"group": grp, "list": r5(lst), "floor": r5(floor), "days": days,
            "text": loc.t("hint.text", list=r5(lst), floor=r5(floor), group=grp, src=src,
                          days=loc.t("hint.days", d=f"{days:.0f}") if days is not None else "")}


def deal_rows(con):
    parts = {}
    for r in con.execute("""SELECT dp.deal_id, dp.part_id, dp.qty, dp.unit_cost, p.name
                            FROM deal_part dp JOIN part p ON p.id = dp.part_id"""):
        parts.setdefault(r["deal_id"], []).append(dict(r))
    out = []
    groups, market, sold, ms = market_data()
    for r in con.execute("SELECT * FROM deal ORDER BY COALESCE(bought_date, '') DESC, rowid DESC"):
        d = dict(r)
        d["price_hint"] = price_hint(d, groups, market, sold, ms)
        d["parts"] = parts.get(d["id"], [])
        d["stock_parts_cost"] = round(sum((p["unit_cost"] or 0) * p["qty"] for p in d["parts"]), 2)
        out.append(d)
    return out


def set_deal_parts(con, deal_id, wanted):
    """Set the parts of a deal; stock is adjusted by the difference."""
    have = {r["part_id"]: r["qty"] for r in con.execute("SELECT part_id, qty FROM deal_part WHERE deal_id=?", (deal_id,))}
    want = {}
    for x in wanted or []:
        pid, q = int(x.get("part_id")), int(x.get("qty") or 0)
        if q > 0:
            want[pid] = want.get(pid, 0) + q
    for pid in set(have) | set(want):
        diff = want.get(pid, 0) - have.get(pid, 0)
        if diff == 0:
            continue
        p = con.execute("SELECT name, qty, unit_cost FROM part WHERE id=?", (pid,)).fetchone()
        if not p:
            raise ValueError("part not found")
        if diff > 0 and p["qty"] < diff:
            raise ValueError(f"{p['name']}: only {p['qty']} in stock")
        con.execute("UPDATE part SET qty = qty - ? WHERE id=?", (diff, pid))
        if pid in want:
            con.execute("""INSERT INTO deal_part(deal_id, part_id, qty, unit_cost) VALUES (?,?,?,?)
                           ON CONFLICT(deal_id, part_id) DO UPDATE SET qty=excluded.qty""",
                        (deal_id, pid, want[pid], p["unit_cost"]))
        else:
            con.execute("DELETE FROM deal_part WHERE deal_id=? AND part_id=?", (deal_id, pid))


def add_purchase(con, b):
    """Book a part purchase: increase stock, unit cost becomes the moving average."""
    try:
        q = int(b.get("qty") or 0)
        total = round(float(str(b.get("total_cost") or "").replace(",", ".")), 2)
    except ValueError:
        raise ValueError("quantity and total price must be numbers")
    if not (1 <= q <= 10000) or not (0 <= total <= 100000):
        raise ValueError("quantity at least 1, price not negative")
    d = {k: (str(b.get(k) or "").strip()[:500] or None) for k in ("date", "source", "notes")}
    if d["date"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["date"]):
        raise ValueError("date as YYYY-MM-DD")
    if b.get("part_id") in (None, "", "new"):
        np = clean(b.get("new_part") or {}, PART_FIELDS, required="name")
        cur = con.execute("INSERT INTO part(name, device, spec, install_min, qty, estimated) VALUES (?,?,?,?,0,0)",
                          (np["name"], np.get("device"), np.get("spec"), np.get("install_min")))
        pid = cur.lastrowid
    else:
        pid = int(b["part_id"])
    row = con.execute("SELECT qty, unit_cost, estimated FROM part WHERE id=?", (pid,)).fetchone()
    if not row:
        raise ValueError("part not found")
    old_q = max(row["qty"], 0)
    if old_q > 0 and row["unit_cost"] is not None and not row["estimated"]:
        unit = (old_q * row["unit_cost"] + total) / (old_q + q)
    else:
        unit = total / q
    con.execute("UPDATE part SET qty = qty + ?, unit_cost = ?, estimated = 0 WHERE id=?", (q, round(unit, 2), pid))
    con.execute("INSERT INTO purchase(part_id, qty, total_cost, date, source, notes) VALUES (?,?,?,?,?,?)",
                (pid, q, total, d.get("date") or clock.today_str(), d.get("source"), d.get("notes")))


def remove_purchase(con, purchase_id):
    pu = con.execute("SELECT * FROM purchase WHERE id=?", (purchase_id,)).fetchone()
    if not pu:
        raise KeyError
    pa = con.execute("SELECT qty, unit_cost FROM part WHERE id=?", (pu["part_id"],)).fetchone()
    if pa["qty"] < pu["qty"]:
        raise ValueError(f"Parts from this purchase are already used (stock {pa['qty']}). "
                         "Correct the stock on the part instead.")
    rest = pa["qty"] - pu["qty"]
    con.execute("DELETE FROM purchase WHERE id=?", (purchase_id,))
    # unit cost = average of the remaining purchases (usually a wrong entry is deleted right away)
    q, tot = con.execute("SELECT SUM(qty), SUM(total_cost) FROM purchase WHERE part_id=?", (pu["part_id"],)).fetchone()
    unit = round(tot / q, 2) if q else pa["unit_cost"]
    con.execute("UPDATE part SET qty=?, unit_cost=? WHERE id=?", (rest, unit, pu["part_id"]))


def purchase_rows(con):
    return [dict(r) for r in con.execute("""SELECT pu.*, p.name FROM purchase pu JOIN part p ON p.id = pu.part_id
                                            ORDER BY pu.date DESC, pu.id DESC LIMIT 100""")]


def save_deal(con, d):
    if d.get("status") and d["status"] not in STATUSES:
        raise ValueError("invalid status")
    d["status"] = d.get("status") or "bought"
    d["bought_date"] = d.get("bought_date") or clock.today_str()
    if d["status"] == "sold" and not d.get("sold_date"):
        d["sold_date"] = clock.today_str()
    cols = ["id"] + list(DEAL_FIELDS)
    con.execute(f"""INSERT INTO deal({','.join(cols)}) VALUES ({','.join('?' * len(cols))})
                    ON CONFLICT(id) DO UPDATE SET {','.join(f'{c}=excluded.{c}' for c in cols[1:])}""",
                [d.get(c) for c in cols])


def all_data(con):
    return {"deals": deal_rows(con), "parts": [dict(r) for r in con.execute("SELECT * FROM part ORDER BY device, name")],
            "purchases": purchase_rows(con), "groups": [g["name"] for g in market_data()[0]],
            "statuses": list(STATUSES)}


# ---------------------------------------------------------------------------- prompt section
def prompt_block(cfg, loc=None):
    """Parts catalogue and stock as a section for the evaluation prompt (texts from the locale)."""
    loc = loc or locale_mod.get(cfg.get("locale"))
    if not db_path(cfg).exists():
        return ""
    con = connect(cfg)
    rows = con.execute("SELECT * FROM part ORDER BY qty > 0 DESC, device, name").fetchall()
    con.close()
    if not rows:
        return ""
    lines = ["", "", f"## {loc.t('parts.title')}", "", loc.t("parts.intro"), "",
             loc.t("parts.header"), "|---|---|---|---|---|---|"]
    for r in rows:
        price = "" if r["unit_cost"] is None else f"{r['unit_cost']:g} €" + (loc.t("parts.estimate") if r["estimated"] else "")
        mins = "" if r["install_min"] is None else f"{r['install_min']} min"
        lines.append(f"| {r['name']} | {r['device'] or ''} | {r['spec'] or ''} | {price} | {mins} | {r['qty']} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "deals"
    web_root = None

    def log_message(self, *a):
        pass

    def send(self, code, obj=None, ctype="application/json", raw=None):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/json")) else ""))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        p = urlparse(self.path).path
        if p == "/deals" or p.startswith("/deals/"):
            return re.sub(r"^/deals", "", p.rstrip("/")) or "/"
        return None

    def static(self):
        """Serve the rendered search pages (read-only, inside web_root only)."""
        if not self.web_root:
            return self.send(404, {"error": "not found"})
        rel = unquote(urlparse(self.path).path).lstrip("/")
        target = (self.web_root / rel).resolve()
        if target.is_dir():
            target = target / "index.html"
        if self.web_root not in target.parents and target != self.web_root or not target.is_file():
            if rel == "":
                links = "".join(f'<li><a href="{d.name}/">{d.name}</a></li>'
                                for d in sorted(self.web_root.iterdir()) if (d / "index.html").exists())
                return self.send(200, ctype="text/html", raw=f"<ul>{links}<li><a href='deals/'>deals</a></li></ul>".encode())
            return self.send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        return self.send(200, ctype=ctype, raw=target.read_bytes())

    def body(self):
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise PermissionError("Content-Type must be application/json")
        n = int(self.headers.get("Content-Length") or 0)
        if n > 50000:
            raise ValueError("too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def tx(self, fn):
        """Write access in one transaction; the response is the complete current data."""
        try:
            with LOCK:
                con = connect()
                try:
                    with con:
                        fn(con)
                    self.send(200, all_data(con))
                finally:
                    con.close()
        except PermissionError as e:
            self.send(415, {"error": str(e)})
        except (ValueError, json.JSONDecodeError, sqlite3.IntegrityError) as e:
            self.send(400, {"error": str(e)})
        except KeyError:
            self.send(404, {"error": "entry not found"})

    def do_GET(self):
        r = self.route()
        if r is None:
            return self.static()
        if r == "/":
            if not urlparse(self.path).path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", "/deals/")
                self.end_headers()
                return
            return self.send(200, ctype="text/html", raw=PAGE.read_bytes())
        if r == "/api/all":
            return self.tx(lambda con: None)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        r = self.route()
        if r == "/api/deals":
            def add(con):
                b = self.body()
                d = clean(b, DEAL_FIELDS)
                d["id"] = secrets.token_hex(6)
                save_deal(con, d)
                set_deal_parts(con, d["id"], b.get("parts"))
            return self.tx(add)
        if r == "/api/parts":
            def addp(con):
                p = clean(self.body(), PART_FIELDS, required="name")
                p["qty"] = p.get("qty") or 0
                cols = [c for c in PART_FIELDS if c in p]
                con.execute(f"INSERT INTO part({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [p[c] for c in cols])
            return self.tx(addp)
        if r == "/api/purchases":
            return self.tx(lambda con: add_purchase(con, self.body()))
        m = re.fullmatch(r"/api/parts/(\d+)/adjust", r or "")
        if m:
            def adj(con):
                delta = int(self.body().get("delta") or 0)
                row = con.execute("SELECT qty FROM part WHERE id=?", (int(m.group(1)),)).fetchone()
                if not row:
                    raise KeyError
                if row["qty"] + delta < 0:
                    raise ValueError("stock cannot become negative")
                con.execute("UPDATE part SET qty = qty + ? WHERE id=?", (delta, int(m.group(1))))
            return self.tx(adj)
        self.send(404, {"error": "not found"})

    def do_PUT(self):
        r = self.route() or ""
        m = re.fullmatch(r"/api/deals/([0-9a-f]{12})", r)
        if m:
            def upd(con):
                row = con.execute("SELECT * FROM deal WHERE id=?", (m.group(1),)).fetchone()
                if not row:
                    raise KeyError
                b = self.body()
                d = clean(b, DEAL_FIELDS, dict(row))
                save_deal(con, d)
                if "parts" in b:
                    set_deal_parts(con, d["id"], b["parts"])
            return self.tx(upd)
        m = re.fullmatch(r"/api/parts/(\d+)", r)
        if m:
            def updp(con):
                row = con.execute("SELECT * FROM part WHERE id=?", (int(m.group(1)),)).fetchone()
                if not row:
                    raise KeyError
                p = clean(self.body(), PART_FIELDS, dict(row), required="name")
                if (p.get("qty") or 0) < 0:
                    raise ValueError("stock cannot become negative")
                cols = list(PART_FIELDS)
                con.execute(f"UPDATE part SET {','.join(c + '=?' for c in cols)} WHERE id=?",
                            [p.get(c) for c in cols] + [int(m.group(1))])
            return self.tx(updp)
        self.send(404, {"error": "not found"})

    def do_DELETE(self):
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self.send(415, {"error": "Content-Type must be application/json"})
        r = self.route() or ""
        m = re.fullmatch(r"/api/deals/([0-9a-f]{12})", r)
        if m:
            def rm(con):
                if not con.execute("SELECT 1 FROM deal WHERE id=?", (m.group(1),)).fetchone():
                    raise KeyError
                set_deal_parts(con, m.group(1), [])   # parts go back into stock
                con.execute("DELETE FROM deal WHERE id=?", (m.group(1),))
            return self.tx(rm)
        m = re.fullmatch(r"/api/purchases/(\d+)", r)
        if m:
            return self.tx(lambda con: remove_purchase(con, int(m.group(1))))
        m = re.fullmatch(r"/api/parts/(\d+)", r)
        if m:
            def rmp(con):
                if con.execute("SELECT 1 FROM deal_part WHERE part_id=? UNION SELECT 1 FROM purchase WHERE part_id=?",
                               (int(m.group(1)), int(m.group(1)))).fetchone():
                    raise ValueError("part has purchases or is used in a deal; set its stock to 0 instead")
                if con.execute("DELETE FROM part WHERE id=?", (int(m.group(1)),)).rowcount == 0:
                    raise KeyError
            return self.tx(rmp)
        self.send(404, {"error": "not found"})


def main(argv=None):
    global CFG
    ap = argparse.ArgumentParser(prog="python -m deal_engine.deals.deals_server")
    ap.add_argument("--config")
    ap.add_argument("--port", type=int)
    ap.add_argument("--web-root", help="also serve the rendered pages from this directory at /")
    ap.add_argument("--prompt-block", action="store_true", help="print the parts catalogue as a prompt section")
    a = ap.parse_args(argv)
    CFG = config_mod.load(a.config)
    if a.prompt_block:
        sys.stdout.write(prompt_block(CFG))
        return 0
    init()
    if a.web_root:
        H.web_root = Path(a.web_root).resolve()   # command line: relative to the working directory
    port = a.port or int((CFG.get("deals") or {}).get("port", 8081))
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"deals: http://127.0.0.1:{port}/deals/" + (f"  pages: http://127.0.0.1:{port}/" if a.web_root else ""))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
