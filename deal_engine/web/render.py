"""Renders data/state/<search>.json + the latest report into a static HTML page.

  python -m deal_engine render [search ...]
Output: <web.root>/<slug>/index.html  (web.root default: {data_dir}/web)

Page settings come from searches.<name>.web in the config (columns, badges, sorts, facets,
toggles, ...; see config.example.yaml). A search without them gets a generic page. Texts of the
page come from UI below (per locale, falls back to English), field labels and machine values
from deal_engine.core.locale.
"""
import html
import json
import re
from datetime import date, datetime
from urllib.parse import quote_plus, urlencode

from deal_engine.core import clock
from deal_engine.core import config as config_mod
from deal_engine.core import locale as locale_mod
from deal_engine.core.config import ConfigError
from deal_engine.core.util import num

UI = {
    "en": {
        "st.active": "active listings", "st.new": "new", "st.price": "price changes", "st.gone": "gone",
        "st.no_changes": "no changes in the last run", "st.no_run": "No run for this search yet.",
        "st.asof": "as of {stamp}", "st.report": "Report of the last run",
        "top": "Top 5", "top.by": "by score", "th.listing": "Listing", "th.price": "Price", "th.score": "Score",
        "top.none": "No listings yet.", "all": "All listings", "search": "Search (title, device, location …)",
        "search.aria": "Search", "groupby": "Group by", "sort": "Sort", "reset": "Reset filters",
        "empty": "No listings for these filters.", "nav.deals": "Deals",
        "footer": "Scores are automatic estimates from listing text, photos and asking prices. "
                  "Check for yourself before buying.",
        "tier": "Tier", "no_tier": "No tier", "other": "Other", "only_new": "only new",
        "js.listings": "listings", "js.of": "of", "js.copied": "copied ✓",
        "pill.new": "new", "pill.relisted": "relisted", "pill.online": "online {n} days", "pill.in_stock": "in stock",
        "b.risk": "risk {v}", "b.photos_damage": "photos: more damage", "b.photos_insufficient": "photos insufficient",
        "b.ship_unknown": "shipping unknown", "b.auction": "auction until {v}", "b.parts_stock": "parts in stock",
        "note.draft": "Message draft", "copy": "copy", "note.why": "Why interesting",
        "note.issues": "Open questions / issues", "note.negotiation": "Negotiation",
        "note.sold": "Sale price from tracking", "note.parts": "Parts to buy", "parts.about": "about {v}",
        "note.stock": "Already in stock", "note.score": "Score calculation",
        "note.score_ai": "evaluator's own score: {v}", "failed": "Last check failed ({v})",
        "listed": "Listed", "listed.since": "since {first}, checked {last}", "compare": "compare",
        "copy_prompt": "copy as prompt", "deal_link": "bought → deal list", "yes": "yes", "no": "no",
        # "copy as prompt" text
        "p.intro": "My deal finder rated this listing as follows:", "p.title": "Title", "p.price": "Price",
        "p.before": "before", "p.score": "Score: {score}/10, tier {tier}", "p.summary": "Summary", "p.link": "Link",
        "p.ask": ["Please be honest and specific:", "- Are the market and resale prices realistic?",
                  "- What is the likely cause of the defect, how hard is the repair, which parts do I need?",
                  "- Is it worth buying, and up to which price?", "- What should I ask the seller first?"],
        "f.days_online": "days online", "f.price_drops": "price drops", "f.issues": "issues",
        "f.missing_parts": "missing parts", "f.seller_questions": "seller questions", "f.score_calc": "score calc",
        "f.negotiation": "negotiation", "f.sold_info": "sold info",
    },
    "de": {
        "st.active": "aktive Inserate", "st.new": "neu", "st.price": "Preisänderungen", "st.gone": "weg",
        "st.no_changes": "keine Änderungen im letzten Lauf", "st.no_run": "Für diese Suche gab es noch keinen Lauf.",
        "st.asof": "Stand {stamp}", "st.report": "Bericht des letzten Laufs",
        "top": "Top 5", "top.by": "nach Score", "th.listing": "Inserat", "th.price": "Preis", "th.score": "Score",
        "top.none": "Noch keine Inserate.", "all": "Alle Inserate", "search": "Suchen (Titel, Gerät, Ort …)",
        "search.aria": "Suchen", "groupby": "Gruppieren nach", "sort": "Sortierung", "reset": "Filter zurücksetzen",
        "empty": "Keine Inserate für diese Filter.", "nav.deals": "Deals",
        "footer": "Scores sind automatische Schätzungen aus Inseratstext, Fotos und Angebotspreisen. "
                  "Vor dem Kauf selbst prüfen.",
        "tier": "Stufe", "no_tier": "Keine Stufe", "other": "Sonstiges", "only_new": "nur neue",
        "js.listings": "Inserate", "js.of": "von", "js.copied": "kopiert ✓",
        "pill.new": "neu", "pill.relisted": "neu eingestellt", "pill.online": "seit {n} Tagen online",
        "pill.in_stock": "auf Lager",
        "b.risk": "Risiko {v}", "b.photos_damage": "Fotos: mehr Schaden", "b.photos_insufficient": "Fotos unzureichend",
        "b.ship_unknown": "Versand unbekannt", "b.auction": "Auktion bis {v}", "b.parts_stock": "Teile auf Lager",
        "note.draft": "Nachrichtenentwurf", "copy": "kopieren", "note.why": "Warum interessant",
        "note.issues": "Offene Fragen / Probleme", "note.negotiation": "Verhandlung",
        "note.sold": "Verkaufspreis aus dem Tracking", "note.parts": "Zu kaufende Teile", "parts.about": "etwa {v}",
        "note.stock": "Schon auf Lager", "note.score": "Score-Berechnung",
        "note.score_ai": "eigener Score der Bewertung: {v}", "failed": "Letzte Prüfung fehlgeschlagen ({v})",
        "listed": "Inseriert", "listed.since": "seit {first}, geprüft {last}", "compare": "vergleichen",
        "copy_prompt": "als Prompt kopieren", "deal_link": "gekauft → Deal-Liste", "yes": "ja", "no": "nein",
        "p.intro": "Mein Deal-Finder hat dieses Inserat so bewertet:", "p.title": "Titel", "p.price": "Preis",
        "p.before": "vorher", "p.score": "Score: {score}/10, Stufe {tier}", "p.summary": "Zusammenfassung",
        "p.link": "Link",
        "p.ask": ["Bitte sei ehrlich und konkret:", "- Sind Markt- und Wiederverkaufspreise realistisch?",
                  "- Was ist die wahrscheinliche Ursache des Defekts, wie schwer ist die Reparatur, welche Teile "
                  "brauche ich?", "- Lohnt sich der Kauf, und bis zu welchem Preis?",
                  "- Was sollte ich den Verkäufer zuerst fragen?"],
        "f.days_online": "Tage online", "f.price_drops": "Preissenkungen", "f.issues": "Probleme",
        "f.missing_parts": "fehlende Teile", "f.seller_questions": "Fragen an den Verkäufer",
        "f.score_calc": "Score-Berechnung", "f.negotiation": "Verhandlung", "f.sold_info": "Verkaufsinfo",
    },
}


# fields shown elsewhere on the card (or internal), not in the detail table
SKIP = {"id", "urls", "title", "price", "price_history", "location", "summary", "score", "tier", "source", "sources",
        "_urls_by_source", "first_seen", "last_seen", "last_check_failed", "status", "why_interesting", "issues",
        "missing_parts", "message_draft", "seller_questions", "parts_in_stock", "score_calc", "score_ai",
        "score_exact", "tier_ai", "negotiation", "relisted", "sold_info", "days_online", "price_drops",
        "market_resale_estimate_ask", "market_extras"}


def ui(loc, key, **kw):
    s = UI.get(loc.code, {}).get(key, UI["en"].get(key, key))
    return s.format(**kw) if kw else s


def txt(v, loc):
    """A label from the config: a plain string, or one per locale ({en: Profit, de: Gewinn})."""
    if isinstance(v, dict):
        return str(v.get(loc.code) or v.get("en") or next(iter(v.values()), ""))
    return "" if v is None else str(v)


def fmt_int(v, loc=None, suffix=""):
    n = num(v)
    if n is None:
        return esc(v) if v not in (None, "") else "–"
    return (loc or locale_mod.get()).num(n) + suffix


def fmt_eur(v, loc=None):
    return fmt_int(v, loc, " €")


def esc(v):
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    return html.escape("" if v is None else str(v))


def show(v, loc):
    """A field value as shown: machine values and booleans translated."""
    if isinstance(v, bool):
        return ui(loc, "yes" if v else "no")
    if isinstance(v, list):
        return ", ".join(str(show(x, loc)) for x in v)
    return loc.value(v)


def risk_badge(v, loc):
    s = str(v or "").lower()
    cls = "ok" if s.startswith("low") else "bad" if s.startswith("high") else "unk"
    return f'<span class="pill {cls}">{esc(ui(loc, "b.risk", v=show(v, loc) if v else "?"))}</span>'


def _b_deal_type(l, loc):
    flip = str(l.get("deal_type", "")).lower() == "flip"
    return f'<span class="pill {"new" if flip else "ok"}">{esc(show(l.get("deal_type") or "repair", loc))}</span>'


def _b_photo_check(l, loc):
    pc = str(l.get("photo_check", "")).lower()   # machine value, English in every locale
    if "more damage" in pc:
        return f'<span class="pill bad">{esc(ui(loc, "b.photos_damage"))}</span>'
    if "insufficient" in pc:
        return f'<span class="pill unk">{esc(ui(loc, "b.photos_insufficient"))}</span>'
    return ""


BADGES = {
    "deal_type": _b_deal_type,
    "risk": lambda l, loc: risk_badge(l.get("risk"), loc),
    "photo_check": _b_photo_check,
    "shipping_unknown": lambda l, loc: (f'<span class="pill unk">{esc(ui(loc, "b.ship_unknown"))}</span>'
                                        if l.get("shipping_unknown") else ""),
    "auction_end": lambda l, loc: (f'<span class="pill unk">{esc(ui(loc, "b.auction", v=l["auction_end"]))}</span>'
                                   if l.get("auction_end") else ""),
    "parts_in_stock": lambda l, loc: (f'<span class="pill ok">{esc(ui(loc, "b.parts_stock"))}</span>'
                                      if l.get("parts_in_stock") else ""),
}


def field_badge(spec):
    """Generic badge: {field, label: "text with {value}", class: ok|bad|unk|new, when: value or [values]}."""
    field, cls, label, when = spec["field"], spec.get("class") or "unk", spec.get("label") or "{value}", spec.get("when")
    whens = None if when is None else when if isinstance(when, list) else [when]

    def badge(l, loc):
        v = l.get(field)
        if whens is None:
            if v in (None, "", [], {}, False):
                return ""
        elif v not in whens and str(v).lower() not in [str(w).lower() for w in whens]:
            return ""
        return f'<span class="pill {cls}">{esc(txt(label, loc).replace("{value}", str(show(v, loc))))}</span>'
    return badge


def regex_facet(rules, fields, other):
    def fn(l, loc):
        t = " ".join(str(l.get(k) or "") for k in fields)
        return next((lbl for lbl, rx in rules if rx.search(t)), other)
    return fn


def value_facet(field, default, cap):
    def fn(l, loc):
        v = l.get(field)
        v = default if v in (None, "") else v
        s = ui(loc, "other") if v in (None, "") else str(show(v, loc))
        return s.capitalize() if cap else s
    return fn


def toggle_fn(t):
    field = t["field"]
    if "equals" in t:
        return lambda l: l.get(field) == t["equals"]
    lo, hi = t.get("min"), t.get("max")

    def fn(l):
        n = num(l.get(field))
        return n is not None and (lo is None or n >= lo) and (hi is None or n <= hi)
    return fn


FORMATS = ("eur", "int", "text")
TYPE_NAMES = {str: "a string", int: "a number", float: "a number", dict: "a mapping", list: "a list",
              bool: "true or false"}
LABEL = (str, dict, int, float)   # plain text or one text per locale


def cfg_for(name, sc=None, cfg=None):
    """Resolved page settings of a search: searches.<name>.web with defaults for everything missing
    (no web section = generic page). Raises ConfigError when a setting has a clearly wrong type;
    unknown keys are ignored."""
    sc = sc or {}
    loc = locale_mod.for_search(cfg, sc)
    web = sc.get("web") or {}

    def bad(msg):
        raise ConfigError(f"search '{name}': web{msg}")

    def check(v, typ, path):
        if not isinstance(v, typ) or (isinstance(v, bool) and bool not in (typ if isinstance(typ, tuple) else (typ,))):
            want = " or ".join(dict.fromkeys(TYPE_NAMES[t] for t in (typ if isinstance(typ, tuple) else (typ,))))
            bad(f"{path} must be {want}, not {type(v).__name__} ({v!r})")
        return v

    def get(key, typ, default):
        return default if web.get(key) is None else check(web[key], typ, f".{key}")

    def entries(key, default, need=("field",), kinds=dict):
        lst = get(key, list, default)
        for i, x in enumerate(lst):
            check(x, kinds, f".{key}[{i}]")
            if isinstance(x, dict):
                for k in need:
                    check(x.get(k), str, f".{key}[{i}].{k}")
                if x.get("label") is not None:
                    check(x["label"], LABEL, f".{key}[{i}].label")
        return lst

    if not isinstance(web, dict):
        bad(f" must be a mapping, not {type(web).__name__}")
    std = {"score": ui(loc, "th.score"), "price": ui(loc, "th.price")}

    def label(x, field):
        return txt(x.get("label"), loc) or std.get(field) or loc.label(field)

    page = {"slug": str(get("slug", (str, int), name)), "title": txt(get("title", LABEL, sc.get("title") or name), loc),
            "tiers": {str(k): txt(v, loc) for k, v in get("tiers", dict, {"A": "A", "B": "B", "C": "C"}).items()},
            "deal_link": get("deal_link", bool, False), "loc": loc}
    # "copy as prompt" button: off unless web.copy_prompt (global) or searches.<name>.web.copy_prompt
    glob = ((cfg or {}).get("web") or {}).get("copy_prompt")
    if glob is not None and not isinstance(glob, bool):
        raise ConfigError(f"web.copy_prompt must be true or false, not {type(glob).__name__} ({glob!r})")
    page["copy_prompt"] = get("copy_prompt", bool, bool(glob))

    page["columns"] = []
    for i, c in enumerate(entries("columns", [])):
        fmt = c.get("format") or "text"
        if fmt not in FORMATS:
            bad(f".columns[{i}].format must be one of {', '.join(FORMATS)}, not {fmt!r}")
        page["columns"].append((label(c, c["field"]), c["field"], fmt))

    page["meta"] = [check(m, str, f".meta[{i}]") for i, m in enumerate(get("meta", list, ["location"]))]

    page["badges"] = []
    for i, b in enumerate(entries("badges", [], kinds=(str, dict))):
        if isinstance(b, str):
            if b not in BADGES:
                bad(f".badges[{i}]: unknown badge {b!r} (built-in: {', '.join(BADGES)})")
            page["badges"].append(BADGES[b])
        else:
            if b.get("class", "unk") not in ("ok", "bad", "unk", "new"):
                bad(f".badges[{i}].class must be ok, bad, unk or new, not {b.get('class')!r}")
            page["badges"].append(field_badge(b))

    sorts = entries("sorts", [{"field": "score", "desc": True}, {"field": "price"}])
    page["sorts"] = [(label(s, s["field"]), s["field"], check(s.get("desc", False), bool, f".sorts[{i}].desc"))
                     for i, s in enumerate(sorts)]

    page["facets"], orders = {}, {}
    for i, f in enumerate(entries("facets", [], need=())):
        key = check(f.get("key") or f.get("field"), str, f".facets[{i}].key")
        if key == "tier":
            bad(f".facets[{i}]: 'tier' is built in, use another key")
        if f.get("rules") is not None:
            fields = check(f.get("from") or ["title"], list, f".facets[{i}].from")
            compiled = []
            for j, r in enumerate(check(f["rules"], list, f".facets[{i}].rules")):
                if not (isinstance(r, list) and len(r) == 2 and isinstance(r[1], str)):
                    bad(f".facets[{i}].rules[{j}] must be [label, regex], not {r!r}")
                try:
                    compiled.append((txt(r[0], loc), re.compile(r[1], re.I)))
                except re.error as e:
                    bad(f".facets[{i}].rules[{j}]: invalid regex ({e})")
            other = txt(f.get("other"), loc) or ui(loc, "other")
            fn = regex_facet(compiled, fields, other)
            orders[key] = [lbl for lbl, _ in compiled] + [other]   # regex categories keep their rule order
        elif f.get("field") is not None:
            fn = value_facet(check(f["field"], str, f".facets[{i}].field"), f.get("default"), bool(f.get("capitalize")))
        else:
            bad(f".facets[{i}] needs 'field' (value of a field) or 'rules' (regex categories)")
        page["facets"][key] = (txt(f.get("label"), loc) or loc.label(f.get("field") or key), fn)

    known = {"tier", *page["facets"]}
    for key, default in (("groups", ["tier"]), ("chips", [])):
        page[key] = get(key, list, default)
        for k in page[key]:
            if k not in known:
                bad(f".{key}: unknown facet {k!r} (known: {', '.join(sorted(known))})")
    if "tier" not in page["groups"]:   # tier is always available
        page["groups"] = page["groups"] + ["tier"]
    for k, vals in get("orders", dict, {}).items():
        orders[str(k)] = [txt(v, loc) for v in check(vals, list, f".orders.{k}")]
    page["orders"] = orders

    page["toggles"] = []
    for i, t in enumerate(entries("toggles", [])):
        if not any(k in t for k in ("equals", "min", "max")):
            bad(f".toggles[{i}] needs 'equals', 'min' or 'max'")
        for k in ("min", "max"):
            if t.get(k) is not None:
                check(t[k], (int, float), f".toggles[{i}].{k}")
        key = str(t.get("key") or t["field"])
        if key == "new":
            bad(f".toggles[{i}]: 'new' is built in, use another key")
        page["toggles"].append((key, label(t, t["field"]), toggle_fn(t)))
    return page


def host_of(url):
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0]


def md_inline(s):
    s = html.escape(s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" rel="noreferrer" target="_blank">\1</a>', s)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)


def md_to_html(md):
    out, in_list = [], False
    for line in md.splitlines():
        if re.match(r"^\s*[-*] ", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + md_inline(re.sub(r"^\s*[-*] ", "", line)) + "</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"^#{1,4} (.*)", line)
        if m:
            out.append(f"<h4>{md_inline(m.group(1))}</h4>")
        elif line.strip():
            out.append(f"<p>{md_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def report_stats(md, loc=None):
    """Counts entries under the New / Price changes / Gone headings of the report (in the report's
    locale, English always recognized) for the status line."""
    heads = []
    for l in dict.fromkeys([loc or locale_mod.get(), locale_mod.get()]):
        heads += [(l.t(f"rep.{k}").lower(), k) for k in ("new", "price", "gone")]
    heads.sort(key=lambda h: -len(h[0]))
    counts, current = {"new": 0, "price": 0, "gone": 0}, None
    for line in md.splitlines():
        m = re.match(r"^\s*(?:#+\s*|\*\*)(.*)", line)
        if m:
            head = m.group(1).replace("*", "").strip().lower()
            current = next((k for h, k in heads if head.startswith(h)), None)
        elif current and re.match(r"^\s*[-*] ", line):
            counts[current] += 1
    return counts


def is_reserved(l):
    return str(l.get("status", "")).lower().startswith(("reserv", "sold"))


def is_new(l):
    return l.get("first_seen") == clock.today_str()


CSS = """
:root{--bg:#f4f2ec;--card:#fffdf8;--fg:#1f2420;--muted:#6c6f68;--line:#e2ded3;--acc:#2f5d46;--acc-soft:#e3ece5;
 --ok:#2f6b4f;--ok-bg:#e2efe6;--bad:#9b3b26;--bad-bg:#f5e3dc;--unk:#7a6522;--unk-bg:#f3ecd6;--new:#1f5f8b}
@media (prefers-color-scheme:dark){:root{--bg:#141614;--card:#1c1f1c;--fg:#e9ebe6;--muted:#999d94;--line:#2e322d;
 --acc:#8cc6a4;--acc-soft:#22302a;--ok:#8cc6a4;--ok-bg:#1f3128;--bad:#e79a82;--bad-bg:#3a2520;--unk:#d9c27a;--unk-bg:#343020;--new:#7fb8e0}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:920px;margin:0 auto;padding:16px 16px 48px}
a{color:var(--acc)}
nav{display:flex;gap:6px;margin-bottom:18px;flex-wrap:wrap}
nav a{padding:6px 12px;border-radius:999px;text-decoration:none;color:var(--muted);border:1px solid var(--line);font-size:.9rem}
nav a.active{background:var(--acc);border-color:var(--acc);color:var(--card)}
header h1{font:600 1.6rem/1.2 Georgia,"Iowan Old Style",serif;margin:0 0 4px}
.status{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;color:var(--muted);font-size:.85rem;margin-bottom:22px}
.status b{color:var(--fg)}.status details{flex-basis:100%}
.status summary{cursor:pointer;color:var(--acc);width:max-content}
.report{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:4px 14px;margin-top:8px;color:var(--fg);font-size:.9rem}
.report h4{margin:10px 0 2px;font-size:.9rem}.report ul{margin:4px 0;padding-left:18px}
h2{font:600 1.05rem/1.3 Georgia,serif;margin:28px 0 10px;display:flex;align-items:baseline;gap:8px}
h2 small{font:400 .8rem system-ui,sans-serif;color:var(--muted)}
.tablewrap{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
table.top{width:100%;border-collapse:collapse;font-size:.9rem}
table.top th{text-align:left;font-weight:500;color:var(--muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;padding:10px 10px 6px;border-bottom:1px solid var(--line)}
table.top td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
table.top tr:last-child td{border-bottom:0}
table.top .rank{color:var(--muted);width:1.5em}table.top .name a{color:var(--fg);font-weight:600;text-decoration:none}
table.top .name small{display:block;color:var(--muted);font-weight:400}
table.top .num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
@media (max-width:620px){table.top .opt{display:none}}
.score{display:inline-grid;place-items:center;min-width:2em;height:1.7em;border-radius:6px;background:var(--acc-soft);color:var(--acc);font-weight:700;font-size:.85rem}
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:30px 0 4px;flex-wrap:wrap}
.toolbar h2{margin:0}
details.tier{margin-top:12px}
details.tier>summary{list-style:none;cursor:pointer;display:flex;align-items:baseline;gap:8px;padding:10px 2px;border-bottom:1px solid var(--line);font:600 1rem Georgia,serif}
details.tier>summary::-webkit-details-marker{display:none}
details.tier>summary::before{content:"›";display:inline-block;transition:transform .15s;color:var(--muted);font-family:system-ui}
details.tier[open]>summary::before{transform:rotate(90deg)}
details.tier>summary small{font:400 .8rem system-ui,sans-serif;color:var(--muted)}
.list{display:flex;flex-direction:column;gap:8px;margin-top:10px}
details.card{background:var(--card);border:1px solid var(--line);border-radius:10px}
details.card>summary{list-style:none;cursor:pointer;padding:10px 12px;display:grid;grid-template-columns:auto 1fr auto;gap:2px 10px;align-items:center}
details.card>summary::-webkit-details-marker{display:none}
details.card .t{font-weight:600;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
details.card .p{font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums;text-align:right}
details.card .m{grid-column:2/4;color:var(--muted);font-size:.82rem;display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center}
details.card.reserved{opacity:.55}
.pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:.72rem;font-weight:600;white-space:nowrap}
.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.bad{background:var(--bad-bg);color:var(--bad)}
.pill.unk{background:var(--unk-bg);color:var(--unk)}.pill.new{background:var(--new);color:var(--card)}
.body{padding:0 12px 12px;border-top:1px solid var(--line);font-size:.9rem}
.body p{margin:10px 0}
.note{border-left:3px solid var(--unk);padding:2px 10px;margin:8px 0;color:var(--fg)}
.note.warn{border-color:var(--bad)}
.kv{display:grid;grid-template-columns:minmax(120px,38%) 1fr;gap:3px 12px;font-size:.85rem;margin:10px 0}
.kv dt{color:var(--muted)}.kv dd{margin:0}
.links{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.links a,.links button{font:inherit;font-size:.82rem;padding:4px 10px;border-radius:8px;background:var(--acc-soft);text-decoration:none;border:0;color:var(--acc);cursor:pointer}
.old{color:var(--muted);text-decoration:line-through;font-weight:400;font-size:.8rem;margin-right:4px}
.note .copy{font:inherit;font-size:.75rem;padding:1px 8px;margin-left:6px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
footer{margin-top:40px;color:var(--muted);font-size:.78rem}
.controls{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;margin:8px 0 6px;display:flex;flex-direction:column;gap:8px}
.controls input[type=search]{font:inherit;width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--fg)}
.controls .row{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;font-size:.82rem;color:var(--muted)}
.controls select{font:inherit;font-size:.85rem;padding:4px 6px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--fg);margin-left:4px}
.reset{font:inherit;font-size:.8rem;border:0;background:none;color:var(--acc);cursor:pointer;padding:2px 0;margin-left:auto}
.fchips{display:flex;flex-wrap:wrap;gap:5px;align-items:center}
.fchips .lbl{font-size:.75rem;color:var(--muted);margin-right:2px}
.fchip,.tgl{font:inherit;font-size:.78rem;padding:3px 10px;border-radius:999px;border:1px solid var(--line);background:var(--bg);color:var(--fg);cursor:pointer}
.fchip small{color:var(--muted);margin-left:3px}
.fchip.on,.tgl.on{background:var(--acc);border-color:var(--acc);color:var(--card)}
.fchip.on small{color:var(--card)}
.toggles{display:flex;flex-wrap:wrap;gap:5px}
.empty{color:var(--muted);text-align:center;padding:20px 0}
"""

JS = """
(function(){
  var UI = window.DE_UI || {groups:[["tier","Tier"]],chips:[],toggles:[],orders:{},t:{}};
  var T = UI.t || {};
  var pool = document.getElementById('pool'), out = document.getElementById('groups');
  var cards = [].slice.call(pool.children).map(function(el){
    return {el:el, f:JSON.parse(el.dataset.fac||'{}'), t:JSON.parse(el.dataset.tg||'{}'), q:el.dataset.q||''};
  });
  var KEY = 'de-view-' + location.pathname, st;
  try { st = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch(e) { st = null; }
  st = st || {};
  st.q = ''; st.group = st.group || UI.groups[0][0]; st.chips = st.chips || {}; st.tg = st.tg || {};
  var $ = function(id){ return document.getElementById(id); };
  function save(){ try { localStorage.setItem(KEY, JSON.stringify({group:st.group, chips:st.chips, tg:st.tg, sort:$('sort').value})); } catch(e) {} }
  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }

  $('groupby').innerHTML = UI.groups.map(function(g){ return '<option value="'+g[0]+'">'+esc(g[1])+'</option>'; }).join('');
  $('groupby').value = st.group;
  if (st.sort) $('sort').value = st.sort;

  function counts(fk){ var c = {}; cards.forEach(function(x){ var v = x.f[fk]; c[v] = (c[v]||0)+1; }); return c; }
  function ordered(fk, vals){
    var o = (UI.orders||{})[fk];
    return vals.sort(function(a,b){
      if (o) { var ia=o.indexOf(a), ib=o.indexOf(b); if (ia<0) ia=999; if (ib<0) ib=999; if (ia!==ib) return ia-ib; }
      return a.localeCompare(b);
    });
  }
  $('chips').innerHTML = UI.chips.map(function(c){
    var cnt = counts(c[0]), vals = ordered(c[0], Object.keys(cnt));
    if (vals.length < 2) return '';
    return '<div class="fchips" data-k="'+c[0]+'"><span class="lbl">'+esc(c[1])+':</span>' + vals.map(function(v){
      return '<button type="button" class="fchip" data-v="'+esc(v)+'">'+esc(v)+'<small>'+cnt[v]+'</small></button>';
    }).join('') + '</div>';
  }).join('');
  $('toggles').innerHTML = UI.toggles.map(function(t){ return '<button type="button" class="tgl" data-k="'+t[0]+'">'+esc(t[1])+'</button>'; }).join('');

  function syncButtons(){
    [].forEach.call(document.querySelectorAll('.fchips'), function(row){
      var k = row.dataset.k, on = st.chips[k] || [];
      [].forEach.call(row.querySelectorAll('.fchip'), function(b){ b.classList.toggle('on', on.indexOf(b.dataset.v) >= 0); });
    });
    [].forEach.call(document.querySelectorAll('.tgl'), function(b){ b.classList.toggle('on', !!st.tg[b.dataset.k]); });
  }

  function sortCards(list){
    var o = $('sort').options[$('sort').selectedIndex], key = o.value, desc = o.dataset.desc === '1';
    return list.sort(function(a,b){
      var x = parseFloat(a.el.dataset[key]), y = parseFloat(b.el.dataset[key]);
      if (isNaN(x)) x = desc ? -Infinity : Infinity; if (isNaN(y)) y = desc ? -Infinity : Infinity;
      return desc ? y-x : x-y;
    });
  }

  function render(){
    var q = st.q.trim().toLowerCase().split(/\\s+/).filter(Boolean);
    var vis = cards.filter(function(x){
      for (var k in st.chips) { var on = st.chips[k]; if (on && on.length && on.indexOf(x.f[k]) < 0) return false; }
      for (var t in st.tg) { if (st.tg[t] && !x.t[t]) return false; }
      for (var i=0; i<q.length; i++) { if (x.q.indexOf(q[i]) < 0) return false; }
      return true;
    });
    var groups = {}; vis.forEach(function(x){ var g = x.f[st.group] || T.other || 'Other'; (groups[g] = groups[g] || []).push(x); });
    var names = ordered(st.group, Object.keys(groups));
    if (!(UI.orders||{})[st.group] && st.group !== 'tier') names.sort(function(a,b){ return groups[b].length - groups[a].length || a.localeCompare(b); });
    out.innerHTML = '';
    names.forEach(function(n, i){
      var d = document.createElement('details'); d.className = 'tier'; d.open = names.length <= 4 || i < 2;
      d.innerHTML = '<summary>'+esc(n)+' <small>'+groups[n].length+'</small></summary><div class="list"></div>';
      var list = d.querySelector('.list');
      sortCards(groups[n]).forEach(function(x){ list.appendChild(x.el); });
      out.appendChild(d);
    });
    $('empty').hidden = vis.length > 0;
    $('count').textContent = vis.length === cards.length ? cards.length + ' ' + (T.listings || 'listings') : vis.length + ' ' + (T.of || 'of') + ' ' + cards.length;
    syncButtons(); save();
  }

  $('q').addEventListener('input', function(){ st.q = this.value; render(); });
  $('groupby').addEventListener('change', function(){ st.group = this.value; render(); });
  $('sort').addEventListener('change', render);
  $('chips').addEventListener('click', function(e){
    var b = e.target.closest('.fchip'); if (!b) return;
    var k = b.parentNode.dataset.k, v = b.dataset.v, on = st.chips[k] = st.chips[k] || [], i = on.indexOf(v);
    if (i >= 0) on.splice(i, 1); else on.push(v); render();
  });
  $('toggles').addEventListener('click', function(e){
    var b = e.target.closest('.tgl'); if (!b) return; st.tg[b.dataset.k] = !st.tg[b.dataset.k]; render();
  });
  $('reset').addEventListener('click', function(){ st.chips = {}; st.tg = {}; st.q = ''; $('q').value = ''; render(); });
  document.addEventListener('click', function(e){
    var b = e.target.closest('[data-copy]'); if (!b) return;
    var t = b.nextElementSibling.value || b.nextElementSibling.innerText;
    function ok(){ b.textContent = T.copied || 'copied ✓'; }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(ok);
    else { var a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select(); document.execCommand('copy'); a.remove(); ok(); }
  });
  render();
})();
"""


def sort_key(field):
    return re.sub(r"[^a-z0-9]", "", field.lower())


def data_attrs(l, page):
    out = []
    for _, field, _ in page["sorts"]:
        n = num(l.get(field))
        out.append(f'data-{sort_key(field)}="{"" if n is None else n}"')
    return " ".join(out)


def parts_note(l, loc):
    parts = l.get("missing_parts") or []
    if not parts:
        return ""
    items = []
    for x in parts:
        if isinstance(x, dict):
            line = f"<b>{esc(x.get('part'))}</b>"
            if x.get("spec"):
                line += f" ({esc(x.get('spec'))})"
            if x.get("cost_eur") not in (None, ""):
                line += f": {esc(ui(loc, 'parts.about', v=fmt_eur(x.get('cost_eur'), loc)))}"
            if x.get("note"):
                line += f" – {esc(x.get('note'))}"
            if x.get("in_stock"):
                line += f' <span class="pill ok">{esc(ui(loc, "pill.in_stock"))}</span>'
        else:
            line = esc(x)
        items.append(f"<li>{line}</li>")
    return (f'<div class="note">{esc(ui(loc, "note.parts"))}:<ul style="margin:4px 0;padding-left:18px">'
            f'{"".join(items)}</ul></div>')


def compare_links(l, cfg, loc=None):
    """Links to check comparison prices yourself (configured URL templates with {query})."""
    q = l.get("market_group") or " ".join(re.sub(r"[^\w\s-]", " ", str(l.get("title") or "")).split()[:4])
    q = str(q).strip()
    if not q:
        return ""
    loc = loc or locale_mod.for_search(cfg)
    return "".join(f'<a href="{esc(c["url"].replace("{query}", quote_plus(q)))}" rel="noreferrer" '
                   f'target="_blank">{esc(txt(c.get("label"), loc) or ui(loc, "compare"))} ↗</a>'
                   for c in (cfg.get("web") or {}).get("compare_links") or [] if c.get("url"))


def prompt_text(l, loc=None):
    """Plain-text summary of a listing to paste into a chat with an assistant for a second opinion."""
    loc = loc or locale_mod.get()

    def val(v):
        if isinstance(v, list):
            return "; ".join(json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(show(x, loc))
                             for x in v if x not in (None, ""))
        if isinstance(v, dict):
            return "; ".join(f"{k}: {x}" for k, x in v.items() if x not in (None, ""))
        return str(show(v, loc))

    def name(k):
        return loc.label(k) if k in loc.labels else ui(loc, f"f.{k}")
    out = [ui(loc, "p.intro"), "", f"{ui(loc, 'p.title')}: {l.get('title')}",
           f"{ui(loc, 'p.price')}: {fmt_eur(l.get('price'), loc)}"
           + (f" ({ui(loc, 'p.before')}: {val(l['price_history'])})" if l.get("price_history") else "")]
    for k in ("location", "days_online", "price_drops"):
        if l.get(k) not in (None, "", 0):
            out.append(f"{name(k)}: {l[k]}")
    if l.get("score") is not None:
        out.append(ui(loc, "p.score", score=l.get("score"), tier=l.get("tier", "?")))
    if l.get("summary"):
        out.append(f"{ui(loc, 'p.summary')}: {l['summary']}")
    for k, v in l.items():
        if k not in SKIP and v not in (None, "", [], {}):
            out.append(f"{loc.label(k)}: {val(v)}")
    for k in ("issues", "missing_parts", "seller_questions", "score_calc", "negotiation", "sold_info"):
        if l.get(k) not in (None, "", []):
            out.append(f"{name(k)}: {val(l[k])}")
    out.append(f"{ui(loc, 'p.link')}: " + " ".join(l.get("urls") or []))
    out += [""] + list(ui(loc, "p.ask"))
    return "\n".join(out)


def fmt_cell(l, field, fmt, loc):
    v = l.get(field)
    if fmt == "eur":
        return fmt_eur(v, loc)
    if fmt == "int":
        return fmt_int(v, loc)
    return "–" if v in (None, "", []) else esc(show(v, loc))


def card(l, page, cfg):
    loc = page["loc"]
    hist = l.get("price_history") or []
    old = ""
    if hist:
        h = hist[-1]
        old = f'<span class="old">{fmt_eur(h.get("price") if isinstance(h, dict) else h, loc)}</span>'
    meta = " · ".join(x for x in (esc(show(l.get(f), loc)) for f in page["meta"]) if x and x != "None")
    badges = " ".join(b for b in (fn(l, loc) for fn in page["badges"]) if b)
    pill = lambda cls, text: f'<span class="pill {cls}">{esc(text)}</span>'
    if is_new(l):
        badges = pill("new", ui(loc, "pill.new")) + " " + badges
    if is_reserved(l):
        badges = pill("bad", loc.value("reserved")) + " " + badges
    if l.get("relisted"):
        badges += " " + pill("unk", ui(loc, "pill.relisted"))
    if l.get("days_online") is not None and l["days_online"] >= 21:
        badges += " " + pill("unk", ui(loc, "pill.online", n=l["days_online"]))

    def note(key, v, cls="note"):
        return f'<div class="{cls}">{esc(ui(loc, key))}: {esc(v)}</div>'
    notes = ""
    if l.get("message_draft"):
        notes += (f'<div class="note">{esc(ui(loc, "note.draft"))} <button type="button" class="copy" data-copy>'
                  f'{esc(ui(loc, "copy"))}</button>'
                  f'<div style="white-space:pre-line;margin-top:4px">{esc(l["message_draft"])}</div></div>')
    if l.get("why_interesting"):
        notes += note("note.why", l["why_interesting"])
    if l.get("issues"):
        notes += note("note.issues", l["issues"], "note warn")
    if l.get("negotiation"):
        notes += note("note.negotiation", l["negotiation"])
    if l.get("relisted"):
        notes += f'<div class="note warn">{esc(l["relisted"])}</div>'
    if l.get("sold_info"):
        notes += note("note.sold", l["sold_info"])
    notes += parts_note(l, loc)
    if l.get("parts_in_stock"):
        notes += note("note.stock", l["parts_in_stock"])
    if l.get("score_calc"):
        ai = (f" ({esc(ui(loc, 'note.score_ai', v=l.get('score_ai')))})"
              if l.get("score_ai") not in (None, "") else "")
        notes += f'<div class="note">{esc(ui(loc, "note.score"))}: {esc(l["score_calc"])}{ai}</div>'
    rows = "".join(f"<dt>{esc(loc.label(k))}</dt><dd>{esc(show(v, loc))}</dd>"
                   for k, v in l.items() if k not in SKIP and v not in (None, "", []))
    links = "".join(f'<a href="{esc(u)}" rel="noreferrer" target="_blank">{esc(host_of(u))} ↗</a>'
                    for u in (l.get("urls") or []))
    links += compare_links(l, cfg, loc)
    if page.get("copy_prompt"):
        links += (f'<button type="button" data-copy>{esc(ui(loc, "copy_prompt"))}</button>'
                  f'<textarea hidden>{esc(prompt_text(l, loc))}</textarea>')
    if page.get("deal_link"):
        q = urlencode({k: v for k, v in {
            "item": l.get("title"), "price": l.get("price"), "link": (l.get("urls") or [""])[0],
            "cat": l.get("market_group") or l.get("device") or "", "other": l.get("shipping_cost_eur") or "",
            "lid": l.get("id"), "profit": l.get("expected_profit_eur"), "hours": l.get("repair_hours"),
            "grp": l.get("market_group")}.items() if v not in (None, "")})
        links += f'<a href="../deals/?{esc(q)}">{esc(ui(loc, "deal_link"))}</a>'
    failed = (f'<p class="note warn">{esc(ui(loc, "failed", v=l["last_check_failed"]))}</p>'
              if l.get("last_check_failed") else "")
    cls = "card reserved" if is_reserved(l) else "card"
    fac = {"tier": page["tiers"].get(l.get("tier"), ui(loc, "no_tier"))}
    for k, (_, fn) in page["facets"].items():
        fac[k] = fn(l, loc)
    tg = {"new": 1 if is_new(l) else 0}
    for k, _, fn in page["toggles"]:
        tg[k] = 1 if fn(l) else 0
    qtext = " ".join(str(l.get(k) or "") for k in ("title", "device", "defect", "location", "summary")).lower()
    attrs = (f"{data_attrs(l, page)} data-fac='{esc(json.dumps(fac, ensure_ascii=False))}' "
             f"data-tg='{esc(json.dumps(tg))}' data-q=\"{esc(qtext[:600])}\"")
    listed = ui(loc, "listed.since", first=l.get("first_seen"), last=l.get("last_seen"))
    return f"""<details class="{cls}" {attrs}>
<summary><span class="score">{esc(l.get('score', '–'))}</span><span class="t">{esc(l.get('title'))}</span>
<span class="p">{old}{fmt_eur(l.get('price'), loc)}</span>
<span class="m">{meta} {badges}</span></summary>
<div class="body"><p>{esc(l.get('summary'))}</p>{notes}{failed}
<dl class="kv">{rows}<dt>{esc(ui(loc, "listed"))}</dt><dd>{esc(listed)}</dd></dl>
<div class="links">{links}</div></div></details>"""


def render(cfg, name, log=print):
    sc = config_mod.search(cfg, name)
    page = cfg_for(name, sc, cfg)
    loc = page["loc"]
    t = lambda key, **kw: esc(ui(loc, key, **kw))
    P = config_mod.paths(cfg, name)
    try:
        listings = json.loads(P["state"].read_text()).get("listings", []) if P["state"].exists() else []
    except ValueError as e:
        log(f"{P['state']}: broken JSON ({e}), page not updated")
        return
    by_score = sorted(listings, key=lambda x: (-(num(x.get("score")) or 0), -(num(x.get("score_exact")) or 0),
                                               num(x.get("price")) or 0))

    txt_ = P["report"].read_text().strip() if P["report"].exists() else ""
    if txt_ and txt_ != "NO_CHANGES":
        st = report_stats(txt_, loc)
        status_bits = (f'<span><b>{st["new"]}</b> {t("st.new")}</span><span><b>{st["price"]}</b> {t("st.price")}</span>'
                       f'<span><b>{st["gone"]}</b> {t("st.gone")}</span>')
        report = (f'<details><summary>{t("st.report")}</summary>'
                  f'<div class="report">{md_to_html(txt_)}</div></details>')
    else:
        status_bits, report = f"<span>{t('st.no_changes')}</span>", ""
    if not P["state"].exists():
        status_bits = f"<span>{t('st.no_run')}</span>"
    stamp = clock.today().strftime("%Y-%m-%d") if clock.today() != date.today() else datetime.now().strftime("%Y-%m-%d %H:%M")

    top = [l for l in by_score if not is_reserved(l)][:5]
    th = "".join(f'<th class="num opt">{esc(lbl)}</th>' for lbl, _, _ in page["columns"])
    trs = []
    for i, l in enumerate(top, 1):
        url = (l.get("urls") or ["#"])[0]
        sub = " · ".join(x for x in [esc(l.get("location")), esc(page["tiers"].get(l.get("tier"), ""))] if x)
        tds = "".join(f'<td class="num opt">{fmt_cell(l, f, fmt, loc)}</td>' for _, f, fmt in page["columns"])
        trs.append(f'<tr><td class="rank">{i}</td><td class="name"><a href="{esc(url)}" target="_blank" rel="noreferrer">'
                   f'{esc(l.get("title"))}</a><small>{sub}</small></td>{tds}'
                   f'<td class="num">{fmt_eur(l.get("price"), loc)}</td><td class="num"><span class="score">{esc(l.get("score", "–"))}</span></td></tr>')
    top_html = (f'<div class="tablewrap"><table class="top"><thead><tr><th></th><th>{t("th.listing")}</th>{th}'
                f'<th class="num">{t("th.price")}</th><th class="num">{t("th.score")}</th></tr></thead>'
                f'<tbody>{"".join(trs)}</tbody></table></div>'
                if trs else f"<p>{t('top.none')}</p>")

    pool = "".join(card(l, page, cfg) for l in by_score)
    fac_labels = {"tier": ui(loc, "tier"), **{k: v[0] for k, v in page["facets"].items()}}
    js_ui = {
        "groups": [[k, fac_labels[k]] for k in page["groups"]],
        "chips": [[k, fac_labels[k]] for k in page["chips"]],
        "toggles": [["new", ui(loc, "only_new")]] + [[k, lbl] for k, lbl, _ in page["toggles"]],
        "orders": {"tier": list(page["tiers"].values()) + [ui(loc, "no_tier")], **page["orders"]},
        "t": {**{k: ui(loc, f"js.{k}") for k in ("listings", "of", "copied")}, "other": ui(loc, "other")},
    }
    sort_opts = "".join(f'<option value="{sort_key(f)}" data-desc="{1 if d else 0}">{esc(lbl)}</option>'
                        for lbl, f, d in page["sorts"])
    pages = {n: cfg_for(n, config_mod.search(cfg, n), cfg) for n in config_mod.search_names(cfg)}
    nav = "".join(f'<a href="../{esc(p["slug"])}/" class="{"active" if n == name else ""}">{esc(p["title"])}</a>'
                  for n, p in pages.items())
    if (cfg.get("deals") or {}).get("enabled", True):
        nav += f'<a href="../deals/">{t("nav.deals")}</a>'

    html_page = f"""<!doctype html><html lang="{esc(loc.code)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>{esc(page['title'])}</title><style>{CSS}</style></head><body><main>
<nav>{nav}</nav>
<header><h1>{esc(page['title'])}</h1>
<div class="status"><span><b>{len(listings)}</b> {t("st.active")}</span>{status_bits}
<span>{t("st.asof", stamp=stamp)}</span>{report}</div></header>
<h2>{t("top")} <small>{t("top.by")}</small></h2>
{top_html}
<div class="toolbar"><h2>{t("all")} <small id="count"></small></h2></div>
<div class="controls">
  <input type="search" id="q" placeholder="{t("search")}" aria-label="{t("search.aria")}">
  <div class="row">
    <label>{t("groupby")} <select id="groupby"></select></label>
    <label>{t("sort")} <select id="sort" aria-label="{t("sort")}">{sort_opts}</select></label>
    <button type="button" id="reset" class="reset">{t("reset")}</button>
  </div>
  <div id="chips"></div>
  <div class="toggles" id="toggles"></div>
</div>
<div id="groups"></div>
<p id="empty" class="empty" hidden>{t("empty")}</p>
<div id="pool" hidden>{pool}</div>
<script>var DE_UI = {json.dumps(js_ui, ensure_ascii=False).replace("</", "<\\/")};</script>
<footer>{t("footer")}</footer>
</main><script>{JS}</script></body></html>"""

    out = P["web"] / page["slug"]
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "index.html.tmp"
    tmp.write_text(html_page)
    tmp.replace(out / "index.html")
    log(f"rendered: {out / 'index.html'}")
