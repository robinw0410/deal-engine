"""Fills the deal list of the demo with invented deals and parts (for screenshots and trying it out)."""
import secrets
from datetime import timedelta

from core import clock
from deals import deals_server as ds

PARTS = [
    # name, fits, spec, stock, total paid, install minutes
    ("Thumbstick module", "game controllers", "potentiometer module, solder-in", 6, 9.0, 45),
    ("Thermal paste (portion)", "consoles, laptops", "standard thermal compound", 10, 8.0, 40),
    ("USB-C charging port", "handhelds, controllers", "replacement port", 3, 7.5, 50),
    ("Laptop RAM 8 GB", "laptops", "DDR4 SO-DIMM", 2, 36.0, 5),
]
DEALS = [
    # item, category, status, buy, other, hours, sell, days ago, used part index/qty
    ("DualSense controller – stick drift", "Controller", "sold", 18, 4.5, 1.2, 42, 18, (0, 1)),
    ("PS4 Slim – very loud fan", "Console", "sold", 55, 0, 2.0, 115, 14, (1, 1)),
    ("Switch Lite – battery does not charge", "Handheld", "listed", 45, 6.2, 1.5, None, 6, (2, 1)),
    ("ThinkPad T480 without RAM and SSD", "Laptop", "in progress", 120, 0, None, None, 3, (3, 1)),
    ("Xbox Series S – no picture", "Console", "scrapped", 60, 6.5, 2.5, 25, 21, None),
]


def seed(cfg):
    ds.CFG = cfg
    ds.init(cfg)
    con = ds.connect(cfg)
    today = clock.today()
    with con:
        ids = []
        for name, fits, spec, qty, total, mins in PARTS:
            cur = con.execute("INSERT INTO part(name, device, spec, install_min, qty, estimated) VALUES (?,?,?,?,0,0)",
                              (name, fits, spec, mins))
            ds.add_purchase(con, {"part_id": cur.lastrowid, "qty": qty, "total_cost": total,
                                  "date": str(today - timedelta(days=25)), "source": "demo shop"})
            ids.append(cur.lastrowid)
        for item, cat, status, buy, other, hours, sell, ago, part in DEALS:
            d = {"id": secrets.token_hex(6), "item": item, "category": cat, "status": status, "buy_price": buy,
                 "other_cost": other, "hours": hours, "sell_price": sell,
                 "bought_date": str(today - timedelta(days=ago)),
                 "sold_date": str(today - timedelta(days=max(0, ago - 7))) if status in ("sold", "scrapped") else None,
                 "est_profit": round((sell or 0) - buy - other - 5) if sell else None, "est_hours": hours}
            ds.save_deal(con, d)
            if part:
                ds.set_deal_parts(con, d["id"], [{"part_id": ids[part[0]], "qty": part[1]}])
    con.close()
