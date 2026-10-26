"""Generator for invented listings. Nothing here comes from a real marketplace.

A small simulated market: every day new listings appear (working, defective, bundles and some
accessory noise), prices follow a log-normal distribution around a typical price per device
group, sellers cut prices after a while, and listings disappear (cheaper ones faster) or get
reserved. The current listings are written to <data_dir>/listings.json in the format of
docs/listing-format.md, so the json_file adapter can read them like any other source.

Hidden "ground truth" per listing (defect, repair effort, fraud) goes to <data_dir>/demo-truth.json
and is only used by demo/evaluator.py.
"""
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

# typical price of a working unit (invented, roughly plausible), defect phrases, repair profile
DEVICES = [
    # name, typical price, title variants, typical defects, (parts €, hours)
    ("PS5", 380, ["PS5 Disc Edition", "PlayStation 5 console", "PS5 825GB"],
     ["no HDMI signal", "overheats and shuts down", "disc drive not working"], (25, 2.5)),
    ("PS4", 130, ["PS4 Slim 500GB", "PlayStation 4 1TB", "PS4 console"],
     ["very loud fan", "no picture", "blue light of death"], (8, 1.5)),
    ("Switch OLED", 240, ["Nintendo Switch OLED", "Switch OLED white"],
     ["joy-con drift", "does not charge", "cracked screen"], (15, 1.2)),
    ("Switch Lite", 110, ["Switch Lite turquoise", "Nintendo Switch Lite"],
     ["stick drift", "battery does not charge", "broken shoulder button"], (6, 1.0)),
    ("DualSense", 45, ["DualSense controller", "PS5 controller DualSense"],
     ["stick drift", "R2 trigger broken", "does not charge"], (4, 0.8)),
    ("Xbox Series S", 190, ["Xbox Series S 512GB", "Xbox Series S console"],
     ["no picture", "turns off after a few minutes", "HDMI port damaged"], (12, 2.0)),
    ("Steam Deck", 330, ["Steam Deck 256GB", "Steam Deck LCD"],
     ["stick drift", "display flickers", "fan noise"], (18, 1.5)),
    ("ThinkPad T480", 210, ["Lenovo ThinkPad T480", "ThinkPad T480 i5"],
     ["without RAM and SSD", "keyboard keys missing", "battery worn out"], (45, 1.0)),
    ("MacBook Air M1", 520, ["MacBook Air M1 8GB", "Apple MacBook Air M1 256GB"],
     ["liquid damage", "display cracked", "battery service"], (90, 2.5)),
]
WORKING = ["like new", "good condition", "barely used", "boxed", "with original box", "works perfectly",
           "minor scratches", ""]
ACCESSORIES = ["case for {d}", "charging station for {d}", "{d} empty box", "screen protector {d}",
               "{d} thumb grips set"]
TOWNS = ["Northfield", "Eastbrook", "Millbrook", "Riverside", "Oakdale", "Hillcrest", "Lakeview", "Stonebridge",
         "Westwood", "Brookhaven", "Fairmont", "Ashford"]
RISKS = ["low", "low", "medium", "medium", "high"]


def _round5(x):
    return max(5, int(round(x / 5.0) * 5))


class World:
    def __init__(self, data_dir, home, seed=7):
        self.dir = Path(data_dir)
        self.home = home
        self.rng = random.Random(seed)
        self.next_id = 100001
        self.listings = {}   # source_id -> listing (incl. internal keys starting with "_")
        self.truth = {}

    # ------------------------------------------------------------------ one listing
    def _place(self):
        r = self.rng
        dist = abs(r.gauss(0, 55)) + 3
        ang = r.uniform(0, 2 * math.pi)
        lat = self.home[0] + dist / 111.0 * math.sin(ang)
        lon = self.home[1] + dist / (111.0 * math.cos(math.radians(self.home[0]))) * math.cos(ang)
        return round(lat, 4), round(lon, 4), r.choice(TOWNS)

    def new_listing(self, day):
        r = self.rng
        name, typical, variants, defects, (parts, hours) = r.choice(DEVICES)
        kind = r.choices(["working", "defect", "bundle", "accessory"], [62, 25, 6, 7])[0]
        sid = str(self.next_id)
        self.next_id += 1
        lat, lon, town = self._place()
        title = r.choice(variants)
        desc = ""
        truth = {"group": name, "kind": kind, "defect": None, "parts": 0, "hours": 0.8, "risk": "low",
                 "fraud": False, "typical": typical}
        price = typical * math.exp(r.gauss(0, 0.18))
        if kind == "working":
            extra = r.choice(WORKING)
            title = f"{title} {extra}".strip()
            desc = f"Selling my {title.lower()}. Everything works. Pickup or shipping."
            if r.random() < 0.06:   # some flips that are too good to be true
                price, truth["fraud"] = typical * r.uniform(0.35, 0.5), True
                desc = "Brand new, never used. Payment in advance by bank transfer only."
        elif kind == "defect":
            d = r.choice(defects)
            title = f"{title} – {d}" if r.random() < 0.6 else f"{title} defective"
            desc = f"Sold as defective: {d}. Otherwise in good condition. For parts or repair."
            price *= r.uniform(0.4, 0.8)
            truth.update(defect=d, parts=round(parts * r.uniform(0.6, 1.5)), hours=round(hours * r.uniform(0.7, 1.6), 1),
                         risk=r.choice(RISKS))
        elif kind == "bundle":
            if name == "DualSense":
                n = r.choice([2, 3, 4])
                title = r.choice([f"{n} DualSense controllers", f"DualSense {n}x", f"{n}x PS5 controller"])
                price *= n * r.uniform(0.45, 0.75)
                truth["qty"] = n
            else:
                title = f"{title} + 2 games + controller"
                price *= r.uniform(1.05, 1.25)
        else:
            title = r.choice(ACCESSORIES).format(d=name)
            price = r.uniform(5, 25)
        listing = {
            "source_id": sid,
            "url": f"https://example.invalid/listing/{sid}",
            "title": title,
            "price": _round5(price) if price > 12 else round(price),
            "location": town,
            "lat": lat, "lon": lon,
            "shipping_possible": r.random() < 0.6,
            "private": r.random() < 0.85,
            "published": str(day),
            "description": desc,
            "images": [],
            "attrs": {"condition": "for parts" if kind == "defect" else "used"},
            "status": "active",
            "_born": str(day),
            "_reserved_until": None,
        }
        self.listings[sid] = listing
        self.truth[sid] = truth
        return listing

    # ------------------------------------------------------------------ time
    def seed(self, start, n=140, spread_days=20):
        for _ in range(n):
            self.new_listing(start - timedelta(days=self.rng.randint(0, spread_days)))

    def step(self, day):
        """Advance the market by one day: sales, reservations, price cuts, new listings."""
        r = self.rng
        for sid, l in list(self.listings.items()):
            if l["_reserved_until"]:
                if str(day) >= l["_reserved_until"]:
                    del self.listings[sid]   # reserved and then sold
                continue
            t = self.truth[sid]
            ratio = t["typical"] / max(l["price"], 1) if t["kind"] == "working" else 1.2
            p_gone = min(0.35, max(0.02, 0.06 * ratio ** 2))
            if r.random() < p_gone:
                del self.listings[sid]
                continue
            if r.random() < 0.015:
                l["status"] = "reserved"
                l["_reserved_until"] = str(day + timedelta(days=r.randint(1, 3)))
                continue
            age = (day - date.fromisoformat(l["published"])).days
            if age >= 4 and r.random() < 0.07:
                l["price"] = _round5(l["price"] * r.uniform(0.85, 0.95))
        for _ in range(max(0, int(r.gauss(13, 3)))):
            self.new_listing(day)

    def write(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        public = [{k: v for k, v in l.items() if not k.startswith("_")} for l in self.listings.values()]
        tmp = self.dir / "listings.json.tmp"
        tmp.write_text(json.dumps({"listings": public}, indent=1))
        tmp.replace(self.dir / "listings.json")
        (self.dir / "demo-truth.json").write_text(json.dumps(self.truth))
