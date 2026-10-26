"""Texts of the deal list page (deals.html) per locale ("locale: en|de" in the config).

The server fills the "{{key}}" placeholders of the static HTML (escaped), sets <html lang> and
passes the whole table to the page script as window.DE_T. Placeholders like {n} are filled by the
page script. Statuses stay machine values (bought, in progress, ...); "status.<value>" is how they
are shown. "num.locale" is the BCP 47 tag for number formatting (de: 1.234 €).
Unknown keys fall back to English.

  texts.get("de")["tab.overview"]
"""

EN = {
    "num.locale": "en",
    "title": "Deals & Parts", "nav.pages": "Search pages", "nav.deals": "Deals",
    "head.formula": "Profit = sale − purchase − parts − other costs",
    "tab.overview": "Overview", "tab.deals": "Deals", "tab.stock": "Parts",
    "status.bought": "bought", "status.in progress": "in progress", "status.listed": "listed",
    "status.sold": "sold", "status.scrapped": "scrapped",
    # overview
    "ov.by_cat": "By category", "ov.closed_deals": "closed deals", "ov.calib": "Estimate vs. result",
    "th.category": "Category", "th.deals": "Deals", "th.profit": "Profit", "th.avg_deal": "Ø per deal",
    "th.per_hour": "€/h", "th.scrapped": "Scrapped", "th.deal": "Deal", "th.estimated": "estimated",
    "th.actual": "actual", "th.diff": "diff.", "th.hours_est": "h est./actual",
    "tile.profit": "total profit", "tile.rate": "Ø hourly rate", "tile.scrapped": "({n} scrapped)",
    "tile.closed": "closed", "tile.tied": "tied up in {n} open deals", "tile.stock": "stock value",
    "unit.per_h": "/h", "unit.min": "{n} min", "cat.none": "no category",
    "empty.closed": "Nothing closed yet.",
    "cal.avg": "Ø deviation {v} per deal", "cal.few": "meaningful from about 10 deals",
    "empty.cal": "Deals created via \"bought → deal list\" show up here after the sale.",
    # deal list
    "f.open": "open", "f.all": "all", "btn.new_deal": "+ New deal",
    "deal.invested": "invested", "deal.target": " · target {v}",
    "deal.hint": "List at {list}, not below {floor}",
    "empty.open": "No open deals.", "empty.deals": "No deals.",
    "cats.suggest": ["Controller", "Console", "Handheld", "Laptop", "Mini PC", "Phone", "Audio"],
    # parts
    "pf.stock": "in stock", "pf.all": "whole catalogue", "ph.search": "Search …", "aria.search_parts": "Search parts",
    "btn.new_part": "+ Part (catalogue only)", "btn.new_buy": "+ Book purchase",
    "th.part": "Part", "th.fits": "fits", "th.price": "Price", "th.install": "Install", "th.stock": "Stock",
    "part.estimate": "estimate", "btn.purchase": "+ purchase", "btn.edit": "edit",
    "empty.stock": "Nothing in stock. \"whole catalogue\" shows all parts.", "empty.match": "No matches.",
    "parts.foot": "{cnt} parts in stock, worth about {val} · {n} parts in the catalogue",
    "buys.title": "Purchases", "buys.sub": "Unit cost = total ÷ quantity, averaged over several purchases",
    "th.date": "Date", "th.qty": "Qty", "th.total": "Total", "th.per_unit": "per unit", "th.source": "Source",
    "buys.link": "Link ↗", "buys.delete": "Delete purchase", "empty.buys": "No purchases booked yet.",
    "stock.note_pre": "With", "stock.note_post": ("the catalogue can be added to the evaluation prompt: its prices "
                                                  "and installation times replace the evaluator's estimates, parts in "
                                                  "stock count as 0 €. \"estimate\" means: initial value, no purchase "
                                                  "booked yet."),
    # dialogs
    "btn.close": "Close", "btn.cancel": "Cancel", "btn.save": "Save", "btn.delete": "Delete", "btn.add": "Add",
    "dlg.new_deal": "New deal", "dlg.edit_deal": "Edit deal", "dlg.new_part": "New part", "dlg.edit_part": "Edit part",
    "dlg.buy": "Book purchase", "btn.book": "Book",
    "lbl.item": "Item / description", "ph.item": "e.g. handheld console, stick drift", "lbl.category": "Category",
    "lbl.status": "Status", "lbl.buy_price": "Purchase (€)", "lbl.other_cost": "Other (€)",
    "ph.other_cost": "shipping, fees, travel", "dlg.use_parts": "Use parts from stock", "aria.part": "Part",
    "aria.qty": "Quantity", "lbl.parts_cost": "Parts bought separately (€)", "ph.parts_cost": "not from stock",
    "lbl.hours": "Work (h)", "ph.hours": "incl. pickup, listing", "lbl.sell_price": "Sale (€)",
    "lbl.bought_date": "Bought on", "lbl.sold_date": "Sold on", "lbl.link": "Link to the listing",
    "lbl.notes": "Notes", "ph.notes": "What was broken, what did you do?", "lbl.market_group": "Market group",
    "ph.market_group": "automatic from the description",
    "lbl.name": "Name", "ph.part_name": "e.g. thumbstick module", "lbl.fits": "Fits", "ph.fits": "e.g. which devices",
    "lbl.spec": "Specification", "lbl.unit_cost": "Price per unit (€)", "lbl.qty_fix": "Stock (correction only)",
    "lbl.install": "Install time per unit (min)", "lbl.estimated": "price is only an estimate",
    "lbl.supplier": "Supplier (link)", "lbl.note": "Note",
    "lbl.part": "Part", "ph.np_name": "e.g. hall effect stick", "lbl.quantity": "Quantity",
    "lbl.total": "Total incl. shipping (€)", "lbl.source": "Source", "ph.source": "link or shop name",
    "buy.new_opt": "+ new part …", "calc.stock_after": "stock afterwards", "calc.new_avg": "new Ø price",
    "used.none": "none", "aria.remove": "remove", "opt.part": "{name} ({n} available, {price} each)",
    "opt.none": "nothing in stock",
    "hint.ebay": "eBay sold ↗", "hint.after_save": "Price hint after saving",
    "hint.suggest": "Suggestion: list at {list}, not below {floor} → profit {lo} to {hi}",
    "calc.invested": "invested", "calc.stock_parts": "of which stock parts", "calc.profit": "profit",
    "est.text": "Estimate: {v} profit", "est.hours": " in {h} h",
    "confirm.unbuy": "Delete purchase? Stock and unit cost are recalculated.",
    "confirm.deal": "Delete deal? Parts used from stock go back into stock.",
    "confirm.part": "Delete part from the catalogue?",
    "err.load": "Loading failed: {msg}",
    "footer": "Data: state/deals.db in the data directory.",
}

DE = {
    "num.locale": "de-DE",
    "title": "Deals & Teile", "nav.pages": "Suchseiten", "nav.deals": "Deals",
    "head.formula": "Gewinn = Verkauf − Kauf − Teile − sonstige Kosten",
    "tab.overview": "Übersicht", "tab.deals": "Deals", "tab.stock": "Teile",
    "status.bought": "gekauft", "status.in progress": "in Arbeit", "status.listed": "inseriert",
    "status.sold": "verkauft", "status.scrapped": "verschrottet",
    "ov.by_cat": "Nach Kategorie", "ov.closed_deals": "abgeschlossene Deals", "ov.calib": "Schätzung vs. Ergebnis",
    "th.category": "Kategorie", "th.deals": "Deals", "th.profit": "Gewinn", "th.avg_deal": "Ø pro Deal",
    "th.per_hour": "€/Std.", "th.scrapped": "Verschrottet", "th.deal": "Deal", "th.estimated": "geschätzt",
    "th.actual": "tatsächlich", "th.diff": "Diff.", "th.hours_est": "Std. geschätzt/tatsächlich",
    "tile.profit": "Gewinn gesamt", "tile.rate": "Ø Stundenlohn", "tile.scrapped": "({n} verschrottet)",
    "tile.closed": "abgeschlossen", "tile.tied": "gebunden in {n} offenen Deals", "tile.stock": "Lagerwert",
    "unit.per_h": "/Std.", "unit.min": "{n} Min.", "cat.none": "ohne Kategorie",
    "empty.closed": "Noch nichts abgeschlossen.",
    "cal.avg": "Ø Abweichung {v} pro Deal", "cal.few": "aussagekräftig ab etwa 10 Deals",
    "empty.cal": "Deals, die über „gekauft → Deal-Liste“ angelegt wurden, erscheinen hier nach dem Verkauf.",
    "f.open": "offen", "f.all": "alle", "btn.new_deal": "+ Neuer Deal",
    "deal.invested": "investiert", "deal.target": " · Ziel {v}",
    "deal.hint": "Für {list} inserieren, nicht unter {floor}",
    "empty.open": "Keine offenen Deals.", "empty.deals": "Keine Deals.",
    "cats.suggest": ["Controller", "Konsole", "Handheld", "Laptop", "Mini-PC", "Handy", "Audio"],
    "pf.stock": "auf Lager", "pf.all": "ganzer Katalog", "ph.search": "Suchen …", "aria.search_parts": "Teile suchen",
    "btn.new_part": "+ Teil (nur Katalog)", "btn.new_buy": "+ Einkauf buchen",
    "th.part": "Teil", "th.fits": "passt für", "th.price": "Preis", "th.install": "Einbau", "th.stock": "Lager",
    "part.estimate": "Schätzung", "btn.purchase": "+ Einkauf", "btn.edit": "bearbeiten",
    "empty.stock": "Nichts auf Lager. „ganzer Katalog“ zeigt alle Teile.", "empty.match": "Keine Treffer.",
    "parts.foot": "{cnt} Teile auf Lager, Wert etwa {val} · {n} Teile im Katalog",
    "buys.title": "Einkäufe", "buys.sub": "Stückpreis = Gesamt ÷ Menge, gemittelt über mehrere Einkäufe",
    "th.date": "Datum", "th.qty": "Menge", "th.total": "Gesamt", "th.per_unit": "pro Stück", "th.source": "Quelle",
    "buys.link": "Link ↗", "buys.delete": "Einkauf löschen", "empty.buys": "Noch keine Einkäufe gebucht.",
    "stock.note_pre": "Mit", "stock.note_post": ("lässt sich der Katalog in den Bewertungs-Prompt einfügen: seine "
                                                 "Preise und Einbauzeiten ersetzen die Schätzungen der Bewertung, Teile "
                                                 "auf Lager zählen mit 0 €. „Schätzung“ heißt: Anfangswert, noch kein "
                                                 "Einkauf gebucht."),
    "btn.close": "Schließen", "btn.cancel": "Abbrechen", "btn.save": "Speichern", "btn.delete": "Löschen",
    "btn.add": "Hinzufügen",
    "dlg.new_deal": "Neuer Deal", "dlg.edit_deal": "Deal bearbeiten", "dlg.new_part": "Neues Teil",
    "dlg.edit_part": "Teil bearbeiten", "dlg.buy": "Einkauf buchen", "btn.book": "Buchen",
    "lbl.item": "Artikel / Beschreibung", "ph.item": "z. B. Handheld-Konsole, Stick-Drift", "lbl.category": "Kategorie",
    "lbl.status": "Status", "lbl.buy_price": "Kauf (€)", "lbl.other_cost": "Sonstiges (€)",
    "ph.other_cost": "Versand, Gebühren, Fahrt", "dlg.use_parts": "Teile vom Lager verwenden", "aria.part": "Teil",
    "aria.qty": "Menge", "lbl.parts_cost": "Teile extra gekauft (€)", "ph.parts_cost": "nicht vom Lager",
    "lbl.hours": "Arbeit (Std.)", "ph.hours": "inkl. Abholung, Inserat", "lbl.sell_price": "Verkauf (€)",
    "lbl.bought_date": "Gekauft am", "lbl.sold_date": "Verkauft am", "lbl.link": "Link zum Inserat",
    "lbl.notes": "Notizen", "ph.notes": "Was war kaputt, was hast du gemacht?", "lbl.market_group": "Marktgruppe",
    "ph.market_group": "automatisch aus der Beschreibung",
    "lbl.name": "Name", "ph.part_name": "z. B. Stick-Modul", "lbl.fits": "Passt für", "ph.fits": "z. B. welche Geräte",
    "lbl.spec": "Spezifikation", "lbl.unit_cost": "Preis pro Stück (€)", "lbl.qty_fix": "Lager (nur Korrektur)",
    "lbl.install": "Einbauzeit pro Stück (Min.)", "lbl.estimated": "Preis ist nur geschätzt",
    "lbl.supplier": "Bezugsquelle (Link)", "lbl.note": "Notiz",
    "lbl.part": "Teil", "ph.np_name": "z. B. Hall-Effekt-Stick", "lbl.quantity": "Menge",
    "lbl.total": "Gesamt inkl. Versand (€)", "lbl.source": "Quelle", "ph.source": "Link oder Shopname",
    "buy.new_opt": "+ neues Teil …", "calc.stock_after": "Lager danach", "calc.new_avg": "neuer Ø-Preis",
    "used.none": "keine", "aria.remove": "entfernen", "opt.part": "{name} ({n} verfügbar, je {price})",
    "opt.none": "nichts auf Lager",
    "hint.ebay": "eBay verkauft ↗", "hint.after_save": "Preishinweis nach dem Speichern",
    "hint.suggest": "Vorschlag: für {list} inserieren, nicht unter {floor} → Gewinn {lo} bis {hi}",
    "calc.invested": "investiert", "calc.stock_parts": "davon Lagerteile", "calc.profit": "Gewinn",
    "est.text": "Schätzung: {v} Gewinn", "est.hours": " in {h} Std.",
    "confirm.unbuy": "Einkauf löschen? Lager und Stückpreis werden neu berechnet.",
    "confirm.deal": "Deal löschen? Vom Lager verwendete Teile gehen zurück ins Lager.",
    "confirm.part": "Teil aus dem Katalog löschen?",
    "err.load": "Laden fehlgeschlagen: {msg}",
    "footer": "Daten: state/deals.db im Datenverzeichnis.",
}

TEXTS = {"en": EN, "de": DE}


def get(code="en"):
    """Text table of the deal page for a locale code (unknown keys fall back to English)."""
    return {**EN, **TEXTS.get(str(code or "en"), {})}
