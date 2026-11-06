"""Wish list page of the deal server (/deals/wishes/): server-rendered HTML, classic forms, no script.

Every value is escaped (html.escape with quotes). The page has one <style> block (the variables and
base styles of deals.html plus a few rules of its own) and no inline style attributes or scripts,
so it is served with a strict Content-Security-Policy (CSP below; the style block is allowed by hash).

Forms post to the page itself (relative action "./"); field `action` is one of ACTIONS, `id` the wish
id (digits only), `csrf` the token (see csrf.py). Search terms come as up to MAX_TERMS fields `terms`,
platforms as checkboxes `platforms`, `active` as a checkbox (absent = inactive).
"""
import base64
import hashlib
import html
import re

from . import texts as texts_mod
from . import wishes

ACTIONS = ("create", "update", "activate", "deactivate", "delete")
OK = {"created", "updated", "activated", "deactivated", "deleted"}
PLATFORM_LABELS = {"ebay": "eBay"}

EXTRA_CSS = """
.wl td{vertical-align:top}
.wl .nm{font-weight:600}
.wl .note{color:var(--muted);font-size:.8rem;white-space:pre-wrap}
.wl .acts{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;align-items:flex-start}
.wl .acts form{margin:0}
.wl tr.off td{opacity:.6}
.terms{display:flex;gap:4px;flex-wrap:wrap}
.terms span{background:var(--acc-soft);color:var(--acc);border-radius:999px;padding:1px 9px;font-size:.8rem}
.s-on{background:var(--ok-bg);color:var(--ok)}.s-off{background:var(--line);color:var(--muted)}
.msg{border-radius:10px;padding:9px 12px;margin:0 0 14px;font-size:.9rem}
.msg.ok{background:var(--ok-bg);color:var(--ok)}.msg.bad{background:var(--bad-bg);color:var(--bad)}
.wform{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow);
 display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.wform .tl{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:6px}
.wform .plats{display:flex;gap:14px;flex-wrap:wrap;padding-top:4px}
.wform .bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
a.btn{display:inline-block;font-size:.9rem;border-radius:8px;padding:7px 14px;border:1px solid var(--line);color:var(--fg);text-decoration:none}
details.del summary{list-style:none;cursor:pointer;color:var(--bad);font-size:.9rem;border:1px solid var(--line);border-radius:8px;padding:7px 14px;background:var(--card)}
details.del summary::-webkit-details-marker{display:none}
details.del[open]{background:var(--bad-bg);border-radius:8px;padding:6px}
details.del p{margin:6px 0;font-size:.82rem;color:var(--bad)}
"""


def esc(v):
    return html.escape("" if v is None else str(v), quote=True)


def base_css(page_template):
    m = re.search(r"<style>(.*?)</style>", page_template, re.S)
    return m.group(1) if m else ""


def css(page_template):
    return base_css(page_template) + EXTRA_CSS


def csp(style):
    h = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
    return ("default-src 'none'; style-src 'sha256-" + h + "'; img-src 'self'; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'")


def price(v, code):
    s = f"{v:,.2f}".replace(".00", "") if v == int(v) else f"{v:,.2f}"
    if code == "de":
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return s + " €"


def price_input(v):
    if v in (None, ""):
        return ""
    if isinstance(v, (int, float)):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def plat_label(p):
    return PLATFORM_LABELS.get(p, p)


def form_values(form):
    """Raw form fields (lists of strings from parse_qs) as values for re-rendering after an error."""
    one = lambda k: (form.get(k) or [""])[0]
    return {"id": one("id") if one("id").isdigit() else None, "name": one("name"), "terms": form.get("terms") or [],
            "max_price": one("max_price"), "platforms": form.get("platforms") or [],
            "active": "active" in form, "note": one("note")}


def render(cfg, style, nav, token, rows, msg=None, msg_ok=True, values=None):
    """The whole page as str. values: wish to prefill the form (with id = edit, without = new)."""
    code = (cfg or {}).get("locale") or "en"
    T = texts_mod.get(code)

    def t(k, **kw):
        s = T[k]
        for a, b in kw.items():
            s = s.replace("{" + a + "}", str(b))
        return esc(s)

    allowed = wishes.platforms(cfg)
    n_active = sum(1 for w in rows if w["active"])
    hidden = f'<input type="hidden" name="csrf" value="{esc(token)}">'

    def small_form(action, wid, label, cls=""):
        return (f'<form method="post" action="./">{hidden}<input type="hidden" name="action" value="{action}">'
                f'<input type="hidden" name="id" value="{int(wid)}">'
                f'<button type="submit"{cls}>{label}</button></form>')

    trs = []
    for w in rows:
        wid = int(w["id"])
        terms = "".join(f"<span>{esc(x)}</span>" for x in w["terms"])
        plats = ", ".join(esc(plat_label(p)) for p in w["platforms"])
        note = f'<div class="note">{esc(w["note"])}</div>' if w["note"] else ""
        state = (f'<span class="pill s-on">{t("w.on")}</span>' if w["active"]
                 else f'<span class="pill s-off">{t("w.off")}</span>')
        toggle = (small_form("deactivate", wid, t("w.deactivate")) if w["active"]
                  else small_form("activate", wid, t("w.activate")))
        delete = (f'<details class="del"><summary>{t("w.delete")}</summary><p>{t("w.delete_q")}</p>'
                  + small_form("delete", wid, t("w.delete_yes"), ' class="danger"') + "</details>")
        trs.append(f'<tr class="{"on" if w["active"] else "off"}"><td><div class="nm">{esc(w["name"])}</div>{note}</td>'
                   f'<td><div class="terms">{terms}</div></td><td class="num">{esc(price(w["max_price"], code))}</td>'
                   f'<td>{plats}</td><td>{state}</td>'
                   f'<td><div class="acts"><a class="btn" href="?edit={wid}#form">{t("w.edit")}</a>{toggle}{delete}</div></td></tr>')
    table = (f'<div class="box"><table class="wl"><thead><tr><th>{t("w.th.name")}</th><th>{t("w.th.terms")}</th>'
             f'<th class="num">{t("w.th.price")}</th><th>{t("w.th.platforms")}</th><th>{t("w.th.state")}</th><th></th>'
             f'</tr></thead><tbody>{"".join(trs)}</tbody></table></div>' if rows
             else f'<div class="box"><div class="empty">{t("w.none")}</div></div>')

    v = values or {"terms": [], "platforms": list(allowed), "active": True}
    editing = v.get("id") not in (None, "")
    terms = list(v.get("terms") or [])[:wishes.MAX_TERMS]
    terms += [""] * (wishes.MAX_TERMS - len(terms))
    term_inputs = "".join(f'<input name="terms" maxlength="{wishes.MAX_TERM}" value="{esc(x)}" '
                          f'placeholder="{t("w.ph.term")}"' + (" required" if i == 0 else "") + ">"
                          for i, x in enumerate(terms))
    plats = "".join(f'<label class="check"><input type="checkbox" name="platforms" value="{esc(p)}"'
                    + (" checked" if p in (v.get("platforms") or []) else "") + f"> {esc(plat_label(p))}</label>"
                    for p in allowed)
    form = (f'<form method="post" action="./" class="wform" id="form">{hidden}'
            f'<input type="hidden" name="action" value="{"update" if editing else "create"}">'
            + (f'<input type="hidden" name="id" value="{int(v["id"])}">' if editing else "")
            + f'<h2 class="wide">{t("w.edit_title") if editing else t("w.new")}</h2>'
            f'<label class="wide">{t("w.f.name")}<input name="name" required maxlength="{wishes.MAX_NAME}" '
            f'value="{esc(v.get("name"))}" placeholder="{t("w.ph.name")}"></label>'
            f'<div class="wide"><label>{t("w.f.terms", max=wishes.MAX_TERMS)}</label><div class="tl">{term_inputs}</div></div>'
            f'<label>{t("w.f.price")}<input name="max_price" required inputmode="decimal" maxlength="12" '
            f'value="{esc(price_input(v.get("max_price")))}"></label>'
            f'<div><label>{t("w.f.platforms")}</label><div class="plats">{plats}</div></div>'
            f'<label class="check"><input type="checkbox" name="active" value="1"'
            + (" checked" if v.get("active") else "") + f'> {t("w.f.active")}</label>'
            f'<label class="wide">{t("w.f.note")}<textarea name="note" rows="3" maxlength="{wishes.MAX_NOTE}" '
            f'placeholder="{t("w.ph.note")}">{esc(v.get("note"))}</textarea></label>'
            f'<div class="bar wide"><button class="primary" type="submit">{t("w.save") if editing else t("w.create")}</button>'
            + (f'<a class="btn" href="./">{t("w.cancel")}</a>' if editing else "") + "</div></form>")

    message = f'<p class="msg {"ok" if msg_ok else "bad"}" role="status">{esc(msg)}</p>' if msg else ""
    return (f'<!doctype html>\n<html lang="{esc(code)}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>{t("w.title")}</title><style>{style}</style></head><body><main>'
            f'<nav class="site">{nav}</nav>'
            f'<div class="head"><div><h1>{t("w.title")}</h1><div class="sub">'
            f'{t("w.sub", max=wishes.MAX_ACTIVE, n=n_active)} · <a href="../">{t("w.back")}</a></div></div></div>'
            f'{message}{table}<div class="section"></div>{form}<footer>{t("w.foot")}</footer></main></body></html>')


def error_page(cfg, style, nav, msg):
    """Small page for 403/413/415: message (escaped) and a link back to the list."""
    code = (cfg or {}).get("locale") or "en"
    T = texts_mod.get(code)
    return (f'<!doctype html>\n<html lang="{esc(code)}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>{esc(T["w.title"])}</title><style>{style}</style></head><body><main>'
            f'<nav class="site">{nav}</nav><p class="msg bad">{esc(msg)}</p>'
            f'<p><a href="./">{esc(T["w.reload"])}</a></p></main></body></html>')
