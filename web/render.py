"""Renders data/state/<search>.json + the latest report into a static HTML page.

  python -m core render [search ...]
Output: <web.root>/<slug>/index.html  (web.root default: {data_dir}/web)

PAGES holds per-search page settings. Only an electronics page is included as an example;
other searches get a generic page.
"""
import html
import json
import re
from datetime import date, datetime
from urllib.parse import quote_plus, urlencode

from core import clock
from core import config as config_mod
from core.util import num


def fmt_int(v, suffix=""):
    n = num(v)
    if n is None:
        return esc(v) if v not in (None, "") else "–"
    return f"{n:,.0f}" + suffix


def fmt_eur(v):
    return fmt_int(v, " €")


def esc(v):
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    return html.escape("" if v is None else str(v))


def risk_badge(v):
    s = str(v or "").lower()
    cls = "ok" if s.startswith("low") else "bad" if s.startswith("high") else "unk"
    return f'<span class="pill {cls}">risk {esc(v or "?")}</span>'


def device_badges(l):
    flip = str(l.get("deal_type", "")).lower() == "flip"
    out = f'<span class="pill {"new" if flip else "ok"}">{esc(l.get("deal_type") or "repair")}</span> '
    out += risk_badge(l.get("risk"))
    pc = str(l.get("photo_check", "")).lower()
    if "more damage" in pc:
        out += ' <span class="pill bad">photos: more damage</span>'
    elif "insufficient" in pc:
        out += ' <span class="pill unk">photos insufficient</span>'
    if l.get("shipping_unknown"):
        out += ' <span class="pill unk">shipping unknown</span>'
    if l.get("auction_end"):
        out += f' <span class="pill unk">auction until {esc(l["auction_end"])}</span>'
    if l.get("parts_in_stock"):
        out += ' <span class="pill ok">parts in stock</span>'
    return out


DEVICE_CATS = [
    ("Controllers", r"controller|dualsense|dualshock|joy[- ]?con|gamepad|\belite\b"),
    ("Handhelds", r"steam\s*deck|rog\s*ally|switch\s*lite|\b[23]ds\b|\bvita\b|game\s*boy"),
    ("Consoles", r"\bps[1-5]\b|playstation|xbox|switch|\bwii\b|console"),
    ("Laptops & PCs", r"laptop|notebook|thinkpad|latitude|elitebook|macbook|mini[- ]?pc|optiplex|graphics card|\brtx\b"),
    ("Phones & tablets", r"iphone|ipad|galaxy|pixel|smartphone|tablet"),
    ("Audio & wearables", r"headphones?|airpods|earbuds|watch"),
]


def device_cat(l):
    t = " ".join(str(l.get(k) or "") for k in ("title", "device", "market_group"))
    for name, rx in DEVICE_CATS:
        if re.search(rx, t, re.I):
            return name
    return "Other"


PAGES = {
    "electronics": {
        "slug": "electronics",
        "title": "Electronics",
        "tiers": {"A": "Worth it (score 7+)", "B": "Borderline (5–6)", "C": "Rather not (up to 4)"},
        "table": [
            ("Profit", lambda l: fmt_eur(l.get("expected_profit_eur"))),
            ("€/h", lambda l: fmt_int(l.get("profit_per_hour_eur"))),
        ],
        "meta": lambda l: [esc(l.get("device")), esc(l.get("defect")), esc(l.get("location"))],
        "badges": device_badges,
        "sorts": [("Score", "score", True), ("€/h", "profit_per_hour_eur", True),
                  ("Profit", "expected_profit_eur", True), ("Price", "price", False),
                  ("Distance", "distance_km", False)],
        "facets": {"cat": ("Category", device_cat),
                   "kind": ("Kind", lambda l: str(l.get("deal_type") or "repair").capitalize())},
        "groups": ["cat", "tier", "kind"],
        "chips": ["cat", "kind"],
        "orders": {"cat": [n for n, _ in DEVICE_CATS] + ["Other"]},
        "toggles": [("ship", "shipping possible", lambda l: l.get("shipping_possible") is True),
                    ("near", "≤ 50 km", lambda l: (num(l.get("distance_km")) or 1e9) <= 50)],
        "deal_link": True,
    },
}

# fields shown elsewhere on the card (or internal), not in the detail table
SKIP = {"id", "urls", "title", "price", "price_history", "location", "summary", "score", "tier", "source", "sources",
        "_urls_by_source", "first_seen", "last_seen", "last_check_failed", "status", "why_interesting", "issues",
        "missing_parts", "message_draft", "seller_questions", "parts_in_stock", "score_calc", "score_ai",
        "score_exact", "tier_ai", "negotiation", "relisted", "sold_info", "days_online", "price_drops",
        "market_resale_estimate_ask"}

LABELS = {
    "condition": "Condition", "market_group": "Market group", "shipping_cost_eur": "Shipping/travel to buy (€)",
    "device": "Device", "defect": "Defect", "likely_cause": "Likely cause", "repair_parts_eur": "Parts (€)",
    "repair_hours": "Work (h)", "tools": "Tools", "expected_profit_eur": "Profit (€)",
    "profit_per_hour_eur": "Profit per hour (€)", "risk": "Risk", "auction_end": "Auction ends",
    "deal_type": "Kind", "visible_damage": "Visible on photos", "photo_check": "Photo check",
    "market_price": "Resale price (evaluator)", "distance_km": "Distance (km)",
    "shipping_possible": "Shipping possible", "market_median": "Asking price median (€)",
    "market_n": "Comparison listings", "market_resale_estimate": "Realistic resale price (€)",
    "bundle_qty": "Bundle quantity", "private": "Private seller", "best_offer": "Best offer possible",
    "shipping_unknown": "Shipping cost unknown", "shipping_note": "Shipping",
}


def cfg_for(name, sc=None):
    base = PAGES.get(name)
    if base:
        return base
    return {"slug": name, "title": (sc or {}).get("title") or name, "tiers": {"A": "A", "B": "B", "C": "C"},
            "table": [], "meta": lambda l: [esc(l.get("location"))], "badges": lambda l: "",
            "sorts": [("Score", "score", True), ("Price", "price", False)]}


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


def report_stats(md):
    """Counts entries under New / Price changes / Gone for the status line."""
    counts, current = {"new": 0, "price": 0, "gone": 0}, None
    for line in md.splitlines():
        low = line.lower()
        if re.match(r"^\s*(#+\s*|\*\*)", line):
            current = "new" if "new" in low else "price" if "price" in low else "gone" if "gone" in low else None
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
  var UI = window.DE_UI || {groups:[["tier","Tier"]],chips:[],toggles:[],orders:{}};
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
    var groups = {}; vis.forEach(function(x){ var g = x.f[st.group] || 'Other'; (groups[g] = groups[g] || []).push(x); });
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
    $('count').textContent = vis.length === cards.length ? cards.length + ' listings' : vis.length + ' of ' + cards.length;
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
    function ok(){ b.textContent = 'copied ✓'; }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(ok);
    else { var a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select(); document.execCommand('copy'); a.remove(); ok(); }
  });
  render();
})();
"""


def data_attrs(l, page):
    out = []
    for _, field, _ in page["sorts"]:
        n = num(l.get(field))
        out.append(f'data-{field.replace("_", "")}="{"" if n is None else n}"')
    return " ".join(out)


def parts_note(l):
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
                line += f": about {fmt_eur(x.get('cost_eur'))}"
            if x.get("note"):
                line += f" – {esc(x.get('note'))}"
            if x.get("in_stock"):
                line += ' <span class="pill ok">in stock</span>'
        else:
            line = esc(x)
        items.append(f"<li>{line}</li>")
    return f'<div class="note">Parts to buy:<ul style="margin:4px 0;padding-left:18px">{"".join(items)}</ul></div>'


def compare_links(l, cfg):
    """Links to check comparison prices yourself (configured URL templates with {query})."""
    q = l.get("market_group") or " ".join(re.sub(r"[^\w\s-]", " ", str(l.get("title") or "")).split()[:4])
    q = str(q).strip()
    if not q:
        return ""
    return "".join(f'<a href="{esc(c["url"].replace("{query}", quote_plus(q)))}" rel="noreferrer" '
                   f'target="_blank">{esc(c.get("label") or "compare")} ↗</a>'
                   for c in (cfg.get("web") or {}).get("compare_links") or [] if c.get("url"))


def prompt_text(l):
    """Plain-text summary of a listing to paste into a chat with an assistant for a second opinion."""
    def val(v):
        if isinstance(v, list):
            return "; ".join(json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x)
                             for x in v if x not in (None, ""))
        if isinstance(v, dict):
            return "; ".join(f"{k}: {x}" for k, x in v.items() if x not in (None, ""))
        return str(v)
    out = ["My deal finder rated this listing as follows:", "", f"Title: {l.get('title')}",
           f"Price: {fmt_eur(l.get('price'))}" + (f" (before: {val(l['price_history'])})" if l.get("price_history") else "")]
    for k in ("location", "days_online", "price_drops"):
        if l.get(k) not in (None, "", 0):
            out.append(f"{k.replace('_', ' ')}: {l[k]}")
    if l.get("score") is not None:
        out.append(f"Score: {l.get('score')}/10, tier {l.get('tier', '?')}")
    if l.get("summary"):
        out.append(f"Summary: {l['summary']}")
    for k, v in l.items():
        if k not in SKIP and v not in (None, "", [], {}):
            out.append(f"{LABELS.get(k, k)}: {val(v)}")
    for k in ("issues", "missing_parts", "seller_questions", "score_calc", "negotiation", "sold_info"):
        if l.get(k) not in (None, "", []):
            out.append(f"{k.replace('_', ' ')}: {val(l[k])}")
    out.append("Link: " + " ".join(l.get("urls") or []))
    out += ["", "Please be honest and specific:", "- Are the market and resale prices realistic?",
            "- What is the likely cause of the defect, how hard is the repair, which parts do I need?",
            "- Is it worth buying, and up to which price?", "- What should I ask the seller first?"]
    return "\n".join(out)


def card(l, page, cfg):
    hist = l.get("price_history") or []
    old = ""
    if hist:
        h = hist[-1]
        old = f'<span class="old">{fmt_eur(h.get("price") if isinstance(h, dict) else h)}</span>'
    meta = " · ".join(x for x in page["meta"](l) if x and x != "None")
    badges = page["badges"](l)
    if is_new(l):
        badges = '<span class="pill new">new</span> ' + badges
    if is_reserved(l):
        badges = '<span class="pill bad">reserved</span> ' + badges
    if l.get("relisted"):
        badges += ' <span class="pill unk">relisted</span>'
    if l.get("days_online") is not None and l["days_online"] >= 21:
        badges += f' <span class="pill unk">online {esc(l["days_online"])} days</span>'

    notes = ""
    if l.get("message_draft"):
        notes += (f'<div class="note">Message draft <button type="button" class="copy" data-copy>copy</button>'
                  f'<div style="white-space:pre-line;margin-top:4px">{esc(l["message_draft"])}</div></div>')
    if l.get("why_interesting"):
        notes += f'<div class="note">Why interesting: {esc(l["why_interesting"])}</div>'
    if l.get("issues"):
        notes += f'<div class="note warn">Open questions / issues: {esc(l["issues"])}</div>'
    if l.get("negotiation"):
        notes += f'<div class="note">Negotiation: {esc(l["negotiation"])}</div>'
    if l.get("relisted"):
        notes += f'<div class="note warn">{esc(l["relisted"])}</div>'
    if l.get("sold_info"):
        notes += f'<div class="note">Sale price from tracking: {esc(l["sold_info"])}</div>'
    notes += parts_note(l)
    if l.get("parts_in_stock"):
        notes += f'<div class="note">Already in stock: {esc(l["parts_in_stock"])}</div>'
    if l.get("score_calc"):
        ai = f" (evaluator's own score: {esc(l.get('score_ai'))})" if l.get("score_ai") not in (None, "") else ""
        notes += f'<div class="note">Score calculation: {esc(l["score_calc"])}{ai}</div>'
    rows = "".join(f"<dt>{esc(LABELS.get(k, k))}</dt><dd>{esc(v)}</dd>"
                   for k, v in l.items() if k not in SKIP and v not in (None, "", []))
    links = "".join(f'<a href="{esc(u)}" rel="noreferrer" target="_blank">{esc(host_of(u))} ↗</a>'
                    for u in (l.get("urls") or []))
    links += compare_links(l, cfg)
    links += f'<button type="button" data-copy>copy as prompt</button><textarea hidden>{esc(prompt_text(l))}</textarea>'
    if page.get("deal_link"):
        q = urlencode({k: v for k, v in {
            "item": l.get("title"), "price": l.get("price"), "link": (l.get("urls") or [""])[0],
            "cat": l.get("market_group") or l.get("device") or "", "other": l.get("shipping_cost_eur") or "",
            "lid": l.get("id"), "profit": l.get("expected_profit_eur"), "hours": l.get("repair_hours"),
            "grp": l.get("market_group")}.items() if v not in (None, "")})
        links += f'<a href="../deals/?{esc(q)}">bought → deal list</a>'
    failed = (f'<p class="note warn">Last check failed ({esc(l["last_check_failed"])})</p>'
              if l.get("last_check_failed") else "")
    cls = "card reserved" if is_reserved(l) else "card"
    fac = {"tier": page["tiers"].get(l.get("tier"), "No tier")}
    for k, (_, fn) in page.get("facets", {}).items():
        fac[k] = fn(l)
    tg = {"new": 1 if is_new(l) else 0}
    for k, _, fn in page.get("toggles", []):
        tg[k] = 1 if fn(l) else 0
    qtext = " ".join(str(l.get(k) or "") for k in ("title", "device", "defect", "location", "summary")).lower()
    attrs = (f"{data_attrs(l, page)} data-fac='{esc(json.dumps(fac, ensure_ascii=False))}' "
             f"data-tg='{esc(json.dumps(tg))}' data-q=\"{esc(qtext[:600])}\"")
    return f"""<details class="{cls}" {attrs}>
<summary><span class="score">{esc(l.get('score', '–'))}</span><span class="t">{esc(l.get('title'))}</span>
<span class="p">{old}{fmt_eur(l.get('price'))}</span>
<span class="m">{meta} {badges}</span></summary>
<div class="body"><p>{esc(l.get('summary'))}</p>{notes}{failed}
<dl class="kv">{rows}<dt>Listed</dt><dd>since {esc(l.get('first_seen'))}, checked {esc(l.get('last_seen'))}</dd></dl>
<div class="links">{links}</div></div></details>"""


def render(cfg, name, log=print):
    sc = config_mod.search(cfg, name)
    page = cfg_for(name, sc)
    P = config_mod.paths(cfg, name)
    try:
        listings = json.loads(P["state"].read_text()).get("listings", []) if P["state"].exists() else []
    except ValueError as e:
        log(f"{P['state']}: broken JSON ({e}), page not updated")
        return
    by_score = sorted(listings, key=lambda x: (-(num(x.get("score")) or 0), -(num(x.get("score_exact")) or 0),
                                               num(x.get("price")) or 0))

    txt = P["report"].read_text().strip() if P["report"].exists() else ""
    if txt and txt != "NO_CHANGES":
        st = report_stats(txt)
        status_bits = (f'<span><b>{st["new"]}</b> new</span><span><b>{st["price"]}</b> price changes</span>'
                       f'<span><b>{st["gone"]}</b> gone</span>')
        report = f'<details><summary>Report of the last run</summary><div class="report">{md_to_html(txt)}</div></details>'
    else:
        status_bits, report = "<span>no changes in the last run</span>", ""
    if not P["state"].exists():
        status_bits = "<span>No run for this search yet.</span>"
    stamp = clock.today().strftime("%Y-%m-%d") if clock.today() != date.today() else datetime.now().strftime("%Y-%m-%d %H:%M")

    top = [l for l in by_score if not is_reserved(l)][:5]
    th = "".join(f'<th class="num opt">{esc(lbl)}</th>' for lbl, _ in page["table"])
    trs = []
    for i, l in enumerate(top, 1):
        url = (l.get("urls") or ["#"])[0]
        sub = " · ".join(x for x in [esc(l.get("location")), page["tiers"].get(l.get("tier"), "")] if x)
        tds = "".join(f'<td class="num opt">{f(l)}</td>' for _, f in page["table"])
        trs.append(f'<tr><td class="rank">{i}</td><td class="name"><a href="{esc(url)}" target="_blank" rel="noreferrer">'
                   f'{esc(l.get("title"))}</a><small>{sub}</small></td>{tds}'
                   f'<td class="num">{fmt_eur(l.get("price"))}</td><td class="num"><span class="score">{esc(l.get("score", "–"))}</span></td></tr>')
    top_html = (f'<div class="tablewrap"><table class="top"><thead><tr><th></th><th>Listing</th>{th}'
                f'<th class="num">Price</th><th class="num">Score</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>'
                if trs else "<p>No listings yet.</p>")

    pool = "".join(card(l, page, cfg) for l in by_score)
    fac_labels = {"tier": "Tier", **{k: v[0] for k, v in page.get("facets", {}).items()}}
    ui = {
        "groups": [[k, fac_labels[k]] for k in page.get("groups", ["tier"])],
        "chips": [[k, fac_labels[k]] for k in page.get("chips", [])],
        "toggles": [["new", "only new"]] + [[k, lbl] for k, lbl, _ in page.get("toggles", [])],
        "orders": {"tier": list(page["tiers"].values()) + ["No tier"], **page.get("orders", {})},
    }
    sort_opts = "".join(f'<option value="{f.replace("_", "")}" data-desc="{1 if d else 0}">{esc(lbl)}</option>'
                        for lbl, f, d in page["sorts"])
    nav = "".join(f'<a href="../{cfg_for(n, config_mod.search(cfg, n))["slug"]}/" class="{"active" if n == name else ""}">'
                  f'{esc(cfg_for(n, config_mod.search(cfg, n))["title"])}</a>' for n in config_mod.search_names(cfg))
    if (cfg.get("deals") or {}).get("enabled", True):
        nav += '<a href="../deals/">Deals</a>'

    html_page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>{esc(page['title'])}</title><style>{CSS}</style></head><body><main>
<nav>{nav}</nav>
<header><h1>{esc(page['title'])}</h1>
<div class="status"><span><b>{len(listings)}</b> active listings</span>{status_bits}
<span>as of {stamp}</span>{report}</div></header>
<h2>Top 5 <small>by score</small></h2>
{top_html}
<div class="toolbar"><h2>All listings <small id="count"></small></h2></div>
<div class="controls">
  <input type="search" id="q" placeholder="Search (title, device, location …)" aria-label="Search">
  <div class="row">
    <label>Group by <select id="groupby"></select></label>
    <label>Sort <select id="sort" aria-label="Sort">{sort_opts}</select></label>
    <button type="button" id="reset" class="reset">Reset filters</button>
  </div>
  <div id="chips"></div>
  <div class="toggles" id="toggles"></div>
</div>
<div id="groups"></div>
<p id="empty" class="empty" hidden>No listings for these filters.</p>
<div id="pool" hidden>{pool}</div>
<script>var DE_UI = {json.dumps(ui, ensure_ascii=False)};</script>
<footer>Scores are automatic estimates from listing text, photos and asking prices. Check for yourself before buying.</footer>
</main><script>{JS}</script></body></html>"""

    out = P["web"] / page["slug"]
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "index.html.tmp"
    tmp.write_text(html_page)
    tmp.replace(out / "index.html")
    log(f"rendered: {out / 'index.html'}")
