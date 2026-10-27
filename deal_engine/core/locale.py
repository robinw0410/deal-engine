"""Language-dependent rules and texts ("locale: en" or "locale: de" in the config, per search
overridable with searches.<name>.locale).

A locale holds:
  - regexes for listing titles: bundle quantities ("3 controllers", "3 Stück"), accessory
    clauses ("with charger", "inkl. Kabel"), default accessory, spare-part and market-exclude words,
    negations for fraud indicators ("no prepayment", "keine Vorkasse")
  - stop words for title similarity (relist detection)
  - the texts deal-engine writes: report, score calculation, negotiation hint, message draft,
    insights, price hints, parts block, page texts and field labels

Machine values in the state stay English in every locale (deal_type repair/flip, risk
low/medium/high, photo_check, status reserved); only what is shown is translated.
Unknown keys fall back to English.

  loc = locale.get("de")        # or locale.for_search(cfg, sc)
  loc.t("draft.offer", offer=40)
"""
import re

# Spare parts without the device (groups.is_part, search setting `parts`). Precision over recall:
# a device wrongly taken for a part is lost, a part taken for a device only costs an evaluation.
# First removed from the title ("part_state"): phrases about a part of a device that is sold —
#   "for parts", "als Ersatzteilspender"; spec phrases in the middle ("FHD Display", "13,3 Zoll
#   Touchscreen", "Retina Display", "Laufwerk Edition", "mit Disc Laufwerk"); a state before a part
#   word in the middle ("defektes Logicboard") or after one anywhere ("Display defekt", "Mainboard
#   Wasserschaden", "Akku 85 %"); with-clauses with a part ("mit neuem Gehäuse", "with IPS display").
# Then, unless the title names a console ("part_veto"), it is a part if
#   - a strong part word stands anywhere                    ("... ThinkPad L14 Mainboard i5")
#   - it starts with a part word (after "original", "new"…)  ("Akku für MacBook", "Display Lenovo T480")
#   - a part word is followed by a for-word                  ("Tastatur DE für ThinkPad", "iPhone 12 Display Ersatz")
#   - "replacement"/"Ersatz" stands right before a part word ("Ersatz-Akku", "replacement screen")
_NB = r"(?![\w-])"


def _part_rx(strong, start, follow, for_words, fluff):
    return (r"(?<![\w-])(?:" + strong + r")"
            + r"|^\W*(?:(?:" + fluff + r")\s+)*(?:" + start + r"|" + strong + r")" + _NB
            + r"|(?<![\w-])(?:" + follow + r")" + _NB + r"\W+(?:[\w.-]+\s+){0,2}?(?:" + for_words + r")(?!\w)"
            + r"|(?<![\w-])(?:ersatz|replacement)[- ]?(?:" + follow + r")" + _NB)


def _part_state_rx(sold_for_parts, spec, with_words, before, parts, after):
    mid = r"(?<=\S\s)"   # in the middle of a title: "Neuer Akku für MacBook" (at the start) is a part
    return (r"(?<![\w-])(?:" + sold_for_parts + r")(?!\w)"
            + r"|(?<![\w-])(?:" + with_words + r")\s+(?:(?:" + before + r"|" + spec + r"|[\w.-]+)\s+){0,2}?(?:"
            + parts + r")" + _NB
            + r"|" + mid + r"(?:(?:" + spec + r")\s+){1,3}(?:" + parts + r")" + _NB
            + r"|" + mid + r"(?:" + before + r")\s+(?:[\w.-]+\s+)?(?:" + parts + r")" + _NB
            + r"|(?<![\w-])(?:" + parts + r")" + _NB + r"\W*(?:[\w.-]+\s+)?(?:" + after + r")(?!\w)")


_QTY2 = r"(?<![\w.,])(?:[2-9]|[1-9]\d{1,2})\s*(?:x|×|pcs\.?|pieces?|stk\.?|stück|stueck)(?!\w)"

_STRONG_EN = (r"main ?boards?|mother ?boards?|logic ?boards?|system ?boards?|(?:display|screen|lcd) assembl(?:y|ies)|"
              r"(?:lcd|oled) (?:panel|module)s?|digitizers?|hinges?|charging ports?|flex cables?|palm ?rests?|"
              r"bottom (?:case|cover)s?")
_WEAK_EN = (r"displays?|lcd|screens?|touch ?screens?|batter(?:y|ies)|housings?|keyboards?|fans?|coolers?|"
            r"heat ?sinks?|cameras?|speakers?|(?:disc |optical |blu-?ray )?drives?")
_START_EN = (r"display(?!\s*port)|lcd|screen|touch ?screen|batter(?:y|ies)(?!\s+(?:powered|operated|charger|pack))|"
             r"housing|spare parts?|replacement parts?")
_FOR_EN = r"for|fits|compatible|replacement"
_FLUFF_EN = r"original|orig\.?|oem|genuine|new|brand|used|replacement|\d+\s*(?:x|pcs\.?)|lot|bundle|of"
_SOLD_EN = (r"(?:for|as)\s+(?:spare\s+)?(?:parts|spares|repair)(?:\s+or\s+repairs?)?|spares\s+(?:or|and|/)\s+repairs?|"
            r"parts\s+donor|(?:disc|disk|blu-?ray)\s+drive\s+(?:edition|version)|"
            r"(?:with|incl\.?|including)\s+(?:(?:disc|disk|blu-?ray)\s+)?drive")
_SPEC_EN = (r"fhd|full ?hd|uhd|qhd|wqhd|hd\+?|ips|retina|oled|amoled|lcd|led|4k|2k|touch|matte?|glossy|"
            r"\d+(?:[.,]\d+)?\s*(?:\"|”|''|inch|in\b|zoll|hz)")
_WITH_EN = r"with|incl\.?|including|without|and|\+|&"
_BEFORE_EN = r"broken|cracked|dead|faulty|damaged|defective|new|weak|bad|replaced|swollen|loose"
_AFTER_EN = (r"broken|cracked|dead|faulty|damaged|defective|weak|bad|replaced|swollen|missing|not|no|issues?|"
             r"problems?|flickering|lines|loose|water damage|short|error|fault|\d+\s*%")
_BUNDLE_EN = r"\blot\b|\bbundle\b|\bbulk\b|\bseveral\b|\bmultiple\b|\bassorted\b|\bcollection\b|" + _QTY2
_VETO_EN = r"(?<![\w-])consoles?(?![\w-])"

_STRONG_DE = (_STRONG_EN + r"|mainboards?|platinen?|display[- ]?einheit(?:en)?|bildschirm[- ]?einheit(?:en)?|"
              r"(?:lcd|oled|display)[- ]?(?:panel|einheit|modul)\w*|scharnier\w*|ladebuchse\w*|flex ?kabel\w*|"
              r"handauflage\w*|bodenplatte\w*|unterschale\w*|oberschale\w*|rückschale\w*|rueckschale\w*|"
              r"(?:notebook|laptop)-?(?:tastatur|akku|display|lüfter|luefter)\w*")
_WEAK_DE = (_WEAK_EN + r"|akkus?|batterien?|bildschirm|gehäuse|gehaeuse|tastatur(?:en)?|lüfter|luefter|kühler|kuehler|"
            r"kameras?|lautsprecher|(?:disc[- ]?|disk[- ]?|blu-?ray[- ]?)?laufwerk\w*")
_START_DE = (_START_EN + r"|akkus?(?!\s+(?:staub\w*|sauger|schrauber|bohr\w*|rasen\w*|mäher|maeher|säge|saege|lampe|"
             r"leuchte|radio|lautsprecher|box|heckenschere|trimmer|gebläse|geblaese|laubbläser|werkzeug\w*|"
             r"ladegerät))|batterie|gehäuse|gehaeuse|lüfter|luefter|kühler|kuehler|laufwerk|ersatzteil\w*")
_FOR_DE = _FOR_EN + r"|für|fuer|passend|passt|kompatibel|ersatz"
_FLUFF_DE = _FLUFF_EN + r"|neu\w*|ersatz|gebraucht|\d+\s*(?:stk\.?|stück|stueck)|konvolut|sammlung|posten"
_SOLD_DE = (_SOLD_EN + r"|(?:als|für|fuer|zum|zu)\s+(?:(?:ersatz)?teile?\w*|bastler\w*|ausschlachten)|"
            r"(?:ersatz)?teile[- ]?spender|bastler\w*|"
            r"(?:disc|disk|blu-?ray)?[- ]?laufwerk[- ]?(?:edition|version|variante)|"
            r"(?:mit|inkl\.?|inklusive|samt)\s+(?:(?:disc|disk|blu-?ray)[- ]?)?laufwerk")
_SPEC_DE = _SPEC_EN + r"|matt|spiegelnd|entspiegelt"
_WITH_DE = _WITH_EN + r"|mit|inkl\.?|inklusive|samt|plus|ohne|und"
_BEFORE_DE = (_BEFORE_EN + r"|defekte?[rsnm]?|kaputte?[rsnm]?|gebrochene?[rsnm]?|gesprungene?[rsnm]?|"
              r"zerkratzte?[rsnm]?|beschädigte?[rsnm]?|beschaedigte?[rsnm]?|neue?[rsnm]?|neuwertige?[rsnm]?|"
              r"schwache?[rsnm]?|aufgeblähte?[rsnm]?|aufgeblaehte?[rsnm]?|getauschte?[rsnm]?|lockere?[rsnm]?|"
              r"originale?[rsnm]?")
_AFTER_DE = (_AFTER_EN + r"|defekt\w*|kaputt\w*|gebrochen|gesprungen|zersprungen|zerkratzt|beschädigt|beschaedigt|"
             r"schwach|tot|platt|aufgebläht|aufgeblaeht|getauscht|gewechselt|erneuert|flackert|flimmert|streifen|"
             r"risse?|pixelfehler|dunkel|nicht|kein\w*|fehlt|tauschen|wechseln|wasserschaden|fehler\w*|"
             r"kurzschluss|locker|ohne\s+funktion|funktionslos|probleme?|startet|liest|lädt|laedt")
_BUNDLE_DE = (_BUNDLE_EN + r"|konvolut|sammlung|\bposten\b|\bpaket\b|teilepaket|ersatzteilpaket|\bmehrere\b|"
              r"\bdiverse\b")
_VETO_DE = r"(?<![\w-])(?:konsole\w*|consoles?)(?![\w-])"

EN = {
    "number_words": {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                     "ten": 10, "pair": 2},
    "qty_units": r"x|×|pcs\.?|pieces?|units?",
    "qty_nouns": r"controllers?|gamepads?|dualsense|dualshock|pads",
    "not_qty": r"(series|gen\.?|generation|version|model|mk|v|ps|edition|rev\.?|switch|playstation|elite)\s*$",
    "with_words": r"\bwith\b|\bwithout\b|\bincl\b\.?|\bincluding\b|\+|&|\band\b",
    # extras that make a device listing a bundle ("PS4 with 6 games"): not counted as a single unit in the
    # market statistics (groups.has_extras)
    "bundle_extras": r"\bgames?\b|fifa|call of duty|zelda|mario|pok[eé]mon",
    "without": r"^\W*(without|ohne)\b",
    "accessory": (r"\bcase\b|\bcover\b|skin|sleeve|\bstand\b|holder|mount|charging\s*(station|dock|stand|kit|cable|kabel)|charger|"
                  r"\bcable\b|\busb\b|empty box|\bbox only\b|packaging|dummy|power ?bank|battery pack|"
                  r"screen protector|\bbag\b|sticker|steering wheel|remote|\bgrips?\b|thumb ?grips?|"
                  r"\bcaps\b|docking ?station|\bdock only\b"),
    "market_exclude": (r"broken|defect|faulty|for parts|not working|wanted|buying|swap|trade|repair|"
                       r"locked|icloud|blacklist"),
    # spare parts without the device (see _part_rx above); "part" is replaced by market.part_regex
    "part": _part_rx(_STRONG_EN, _START_EN, _WEAK_EN, _FOR_EN, _FLUFF_EN),
    "part_state": _part_state_rx(_SOLD_EN, _SPEC_EN, _WITH_EN, _BEFORE_EN, _STRONG_EN + "|" + _WEAK_EN, _AFTER_EN),
    "part_bundle": _BUNDLE_EN,
    "part_veto": _VETO_EN,
    "negations": r"no|not|without|none|non|zero|nothing",
    # a negation does not reach past these words ("not tested but fake photos")
    "conjunctions": r"but|however|although|yet",
    # entries of visible_damage that mean "no damage"
    "no_damage": r"(none|no|nothing)\b",
    "reserved_title": r"\b(reserved|sold)\b",
    "fraud": r"fraud|fake|prepayment|stock photo|scam|unrealistically cheap|too cheap|suspicious",
    "stop_words": {"broken", "defect", "defective", "selling", "sale", "new", "top", "condition", "with", "and",
                   "incl", "boxed", "used", "for", "the"},
    "decimal": ".", "thousands": ",",
    "texts": {
        # report (markdown, also shown on the page)
        "rep.new": "New", "rep.price": "Price changes", "rep.gone": "Gone", "rep.reserved": "Reserved",
        "rep.line": "- [{title}]({url}) – {price}, {location} – score {score}, tier {tier}: {summary}",
        "rep.gone_offline": "- {title} ({price}) – no longer online",
        "rep.gone_rule": "- {title} ({price}) – no longer matches the criteria",
        "rep.merged": "Duplicates merged: {n}",
        "rep.skipped": "Note: {n} more candidates will be evaluated in the next run.",
        "rep.problem": "Problem",
        "prob.search": "{adapter} search '{query}' failed: {error}",
        "prob.invalid": "{adapter}: {n} invalid listings ignored (see docs/listing-format.md)",
        "prob.offline": ("{n} of {total} {adapter} listings look offline. That is implausibly many "
                         "(outage or changed source?), so nothing was removed."),
        "prob.title_rule": ("{n} of {total} {adapter} listings no longer match the title filters. That is "
                            "implausibly many (title regex too broad?), so nothing was removed."),
        "prob.blocked": "{adapter} blocked: {error}. Run aborted, state not fully checked.",
        "prob.eval": "evaluation of batch {n} failed ({count} candidates, retried next run)",
        "ship.unknown": "shipping unknown, assumed {cost} €",
        # score calculation
        "score.text": ("sell {resale}{capped} - buy {price} - parts {parts} - {logistics} {ship}{how} "
                       "= {profit} in {hours} h ({per_h}/h) · risk {risk}: works out {p} %, otherwise -{loss} "
                       "→ expected {ev} ({ev_h}/h)"),
        "score.travel": "travel", "score.shipping": "shipping",
        "score.how_shipping": "shipping", "score.how_pickup": "pickup {km} km",
        "score.bundle": " (bundle x{n})", "score.capped_market": " (capped at market estimate)",
        "score.bonus": " · profit bonus +{n}", "score.stock": " · parts in stock +{n}",
        "score.no_numbers": "evaluator score (numbers for the formula are missing)",
        "note.damage": "{n} visible damages -{pen}",
        "note.photo_worse": "photos: more damage, max {m}",
        "note.photo_poor": "photos insufficient, max {m}",
        "note.min_profit": "below minimum profit ({kind})",
        "note.high_risk": "high risk: max {m}",
        "note.ai_gap": "formula and evaluator disagree: max evaluator+{m}",
        "note.fraud": "fraud indicators",
        "note.no_market": "resale price without market data: max {m}",
        "note.reserved": "reserved",
        # negotiation hint
        "neg.online": "online for {d} days", "neg.unknown": "time online unknown", "neg.reduced": "reduced {n}x",
        "neg.relisted": "relisted",
        "neg.fraud": "{head} → fraud indicators: only with pickup and a function test, no prepayment",
        "neg.capped": ("{head} → worth it up to {mx} € by the numbers, but the score is capped ({caps}): "
                       "{todo}, then open at about {offer} €"),
        "neg.todo_evaluator": "read the issues, the evaluator sees problems",
        "neg.todo_photos": "ask for more photos and the condition",
        "neg.todo_details": "clarify details",
        "neg.free": "{head} → hardly worth it even for free (score {t} not reachable)",
        "neg.open": "{head} → open at about {offer} €, worth it (score ≥ {t}) up to {mx} €",
        "neg.at_most": "{head} → offer at most {mx} € (above that score < {t})",
        "neg.too_high": "{head} → only worth it up to {mx} €, price too far above",
        "neg.simple": "{head} → open at about {offer} €",
        # message draft to the seller
        "draft.hi": "Hi!", "draft.interest": "I'm interested in {title}.", "draft.item": "the item",
        "draft.questions": "A few quick questions:", "draft.offer": "Would {offer} € work for you?",
        "draft.room": "Is there any room on the price?",
        "draft.ship": "I'd like to buy via the platform's shipping with buyer protection.",
        "draft.pickup_test": "I'd like to pick it up and test it briefly on site.",
        "draft.pickup": "I could pick it up in the next few days and test it briefly.",
        "draft.thanks": "Thanks!",
        "draft.q_fraud": "Could you send a photo of the device switched on, next to a note with today's date?",
        "draft.q_photos": "Could you send a few more photos, especially of the device itself and any damage?",
        # insights
        "ins.relisted": "probably relisted ({by}): a listing was online until {gone} (since {start}, last {price} €)",
        "ins.by_photo": "same photo", "ins.by_text": "same place, similar title and price",
        "ins.sold": "{n} listings of this group disappeared in {days} days, median {median} €",
        "ins.sold_days": ", online for {d} days on average",
        # deal list price hint and parts catalogue for the evaluation prompt
        "hint.none": "no market price for this group – compare sold listings yourself",
        "hint.offers": "{n} current offers", "hint.both": "{gone} disappeared + {n} current offers",
        "hint.text": "list at {list} €, not below {floor} € ({group}, {src}{days})",
        "hint.days": ", gone after {d} days on average",
        "parts.title": "Parts catalogue and stock",
        "parts.intro": ("Use these prices and installation times instead of your own estimates when a part fits "
                        "(time per unit).\nParts with stock > 0 are already here:\n"
                        "- count them with 0 € for profit and buying decision, at most up to the stock quantity\n"
                        "- list them in `parts_in_stock`, e.g. [\"Thumbstick module x2\"]; set `\"in_stock\": true` "
                        "on the\n  part in `missing_parts`"),
        "parts.header": "| Part | fits | specification | price/unit | install | stock |",
        "parts.estimate": " (estimate)",
        # wanted/buying ads, inserted into the evaluation and prefilter prompts ({{WANTED_ADS}})
        "wanted.reject": "Wanted, buying, swap and rental ads are not offers: discard them.",
        "wanted.accept": ("Wanted ads (someone looking for an item or a service) are exactly what this search is "
                          "for: do NOT discard a listing because it is a wanted ad. Still discard pure buying "
                          "ads of dealers (\"we buy everything\")."),
    },
    # field labels on the page
    "labels": {
        "condition": "Condition", "market_group": "Market group", "shipping_cost_eur": "Shipping/travel to buy (€)",
        "device": "Device", "defect": "Defect", "likely_cause": "Likely cause", "repair_parts_eur": "Parts (€)",
        "repair_hours": "Work (h)", "tools": "Tools", "expected_profit_eur": "Profit (€)",
        "profit_per_hour_eur": "Profit per hour (€)", "risk": "Risk", "auction_end": "Auction ends",
        "deal_type": "Kind", "visible_damage": "Visible on photos", "photo_check": "Photo check",
        "market_price": "Resale price (evaluator)", "distance_km": "Distance (km)",
        "shipping_possible": "Shipping possible", "market_median": "Asking price median (€)",
        "market_n": "Comparison listings", "market_resale_estimate": "Realistic resale price (€)",
        "bundle_qty": "Bundle quantity", "private": "Private seller", "best_offer": "Best offer possible",
        "shipping_unknown": "Shipping cost unknown", "shipping_note": "Shipping", "location": "Location",
        "km": "Mileage (km)", "year": "Year", "ps": "Power (PS)",
    },
    # how machine values are shown
    "values": {"repair": "repair", "flip": "flip", "low": "low", "medium": "medium", "high": "high",
               "reserved": "reserved", "active": "active"},
}

DE = {
    "number_words": {"zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8,
                     "neun": 9, "zehn": 10, **EN["number_words"]},
    "qty_units": r"x|×|stk\.?|stück|stueck|pcs\.?|pieces?",
    "qty_nouns": r"controllers?|gamepads?|dualsense|dualshock|pads",
    "not_qty": r"(series|serie|gen\.?|generation|version|modell|model|mk|v|ps|edition|rev\.?|switch|playstation|elite)\s*$",
    "with_words": (r"\bmit\b|\bohne\b|\binkl\b\.?|\binklusive\b|\bsamt\b|\bplus\b|\bund\b|\bwith\b|\bwithout\b|\bincl\b\.?|"
                   r"\bincluding\b|\+|&"),
    "bundle_extras": r"\bspiel\w*|\bgames?\b|fifa|\bfc\s?2\d|call of duty|zelda|mario|pok[eé]mon",
    "without": r"^\W*(ohne|without)\b",
    "accessory": (r"hülle|huelle|\bcase\b|skin|ständer|staender|halterung|ladestation|ladekabel|\bkabel\b|karton|"
                  r"verpackung|attrappe|powerbank|power bank|akku ?pack|ladegerät|ladegeraet|charger|\bstand\b|"
                  r"\bcover\b|folie|tasche|aufkleber|lenkrad|fernbedienung|\bgrips?\b|aufsatz|thumb ?grips?|kappen|"
                  r"lade ?dock|docking ?station|charging\s*(station|dock|stand|kit|cable|kabel)|\busb\b|halter\b|leerkarton|nur (die )?ovp"),
    "market_exclude": (r"defekt|bastler|für teile|fuer teile|ersatzteil|kaputt|drift|suche|ankauf|tausch|reparatur|"
                       r"gesperrt|icloud|broken|defect|for parts|not working|wanted|repair"),
    "negations": r"kein|keine|keinen|keiner|keines|keinerlei|nicht|nichts|ohne|nie|no|not|without|none|nothing",
    "part": _part_rx(_STRONG_DE, _START_DE, _WEAK_DE, _FOR_DE, _FLUFF_DE),
    "part_state": _part_state_rx(_SOLD_DE, _SPEC_DE, _WITH_DE, _BEFORE_DE, _STRONG_DE + "|" + _WEAK_DE, _AFTER_DE),
    "part_bundle": _BUNDLE_DE,
    "part_veto": _VETO_DE,
    "conjunctions": r"aber|jedoch|doch|sondern|but|however",
    "no_damage": r"(keine?|keinerlei|nichts|ohne|none|no|nothing)\b",
    "reserved_title": r"\b(reserviert|verkauft|angezahlt|reserved|sold)\b",
    "fraud": (r"betrug\w*|fake|vorkasse|stockfoto\w*|scam|verdächtig\w*|verdaechtig\w*|unrealistisch (billig|günstig)|"
              r"zu billig|fraud|prepayment|stock photo|suspicious|too cheap"),
    "stop_words": {"defekt", "verkaufe", "verkauf", "neu", "neuwertig", "top", "zustand", "mit", "und", "inkl",
                   "ovp", "gebraucht", "für", "fuer", "der", "die", "das", "an", "bastler", *EN["stop_words"]},
    "decimal": ",", "thousands": ".",
    "texts": {
        "rep.new": "Neu", "rep.price": "Preisänderungen", "rep.gone": "Weg", "rep.reserved": "Reserviert",
        "rep.line": "- [{title}]({url}) – {price}, {location} – Score {score}, Stufe {tier}: {summary}",
        "rep.gone_offline": "- {title} ({price}) – nicht mehr online",
        "rep.gone_rule": "- {title} ({price}) – passt nicht mehr zu den Kriterien",
        "rep.merged": "Dubletten zusammengeführt: {n}",
        "rep.skipped": "Hinweis: {n} weitere Kandidaten werden im nächsten Lauf bewertet.",
        "rep.problem": "Problem",
        "prob.search": "{adapter}: Suche '{query}' fehlgeschlagen: {error}",
        "prob.invalid": "{adapter}: {n} ungültige Inserate ignoriert (siehe docs/listing-format.md)",
        "prob.offline": ("{n} von {total} {adapter}-Inseraten wirken offline. Das ist unplausibel viel "
                         "(Störung oder geänderte Quelle?), daher nichts entfernt."),
        "prob.title_rule": ("{n} von {total} {adapter}-Inseraten passen nicht mehr zu den Titel-Filtern. Das "
                            "ist unplausibel viel (Titel-Regex zu breit?), daher nichts entfernt."),
        "prob.blocked": "{adapter} blockiert: {error}. Lauf abgebrochen, Bestand nicht vollständig geprüft.",
        "prob.eval": "Bewertung von Batch {n} fehlgeschlagen ({count} Kandidaten, nächstes Mal erneut)",
        "ship.unknown": "Versand unbekannt, {cost} € angenommen",
        "score.text": ("Verkauf {resale}{capped} − Kauf {price} − Teile {parts} − {logistics} {ship}{how} "
                       "= {profit} in {hours} Std. ({per_h}/Std.) · Risiko {risk}: klappt zu {p} %, sonst −{loss} "
                       "→ erwartet {ev} ({ev_h}/Std.)"),
        "score.travel": "Fahrt", "score.shipping": "Versand",
        "score.how_shipping": "Versand", "score.how_pickup": "Abholung {km} km",
        "score.bundle": " (Paket x{n})", "score.capped_market": " (gedeckelt auf Marktschätzung)",
        "score.bonus": " · Gewinn-Bonus +{n}", "score.stock": " · Teile auf Lager +{n}",
        "score.no_numbers": "Score der Bewertung (Zahlen für die Formel fehlen)",
        "note.damage": "{n} sichtbare Schäden −{pen}",
        "note.photo_worse": "Fotos: mehr Schäden, max. {m}",
        "note.photo_poor": "Fotos unzureichend, max. {m}",
        "note.min_profit": "unter Mindestgewinn ({kind})",
        "note.high_risk": "Risiko hoch: max. {m}",
        "note.ai_gap": "Formel und Bewertung uneinig: max. Bewertung+{m}",
        "note.fraud": "Betrugsmerkmale",
        "note.no_market": "Verkaufspreis ohne Marktdaten: max. {m}",
        "note.reserved": "reserviert",
        "neg.online": "seit {d} Tagen online", "neg.unknown": "Online-Dauer unbekannt", "neg.reduced": "{n}× reduziert",
        "neg.relisted": "neu eingestellt",
        "neg.fraud": "{head} → Betrugsmerkmale: nur bei Abholung mit Funktionstest, keine Vorkasse",
        "neg.capped": ("{head} → rechnerisch lohnend bis {mx} €, aber der Score ist gedeckelt ({caps}): "
                       "{todo}, dann mit ca. {offer} € einsteigen"),
        "neg.todo_evaluator": "Hinweise lesen, die Bewertung sieht Probleme",
        "neg.todo_photos": "nach mehr Fotos und dem Zustand fragen",
        "neg.todo_details": "Details klären",
        "neg.free": "{head} → lohnt sich selbst geschenkt kaum (Score {t} nicht erreichbar)",
        "neg.open": "{head} → mit ca. {offer} € einsteigen, lohnend (Score ≥ {t}) bis {mx} €",
        "neg.at_most": "{head} → höchstens {mx} € bieten (darüber Score < {t})",
        "neg.too_high": "{head} → lohnt sich nur bis {mx} €, Preis zu weit darüber",
        "neg.simple": "{head} → mit ca. {offer} € einsteigen",
        "draft.hi": "Hallo!", "draft.interest": "Ich interessiere mich für {title}.", "draft.item": "den Artikel",
        "draft.questions": "Ein paar kurze Fragen:", "draft.offer": "Wären {offer} € für dich in Ordnung?",
        "draft.room": "Ist beim Preis noch etwas möglich?",
        "draft.ship": "Ich würde gern über den Versand der Plattform mit Käuferschutz kaufen.",
        "draft.pickup_test": "Ich würde es gern abholen und kurz vor Ort testen.",
        "draft.pickup": "Ich könnte es in den nächsten Tagen abholen und kurz testen.",
        "draft.thanks": "Danke!",
        "draft.q_fraud": "Kannst du ein Foto vom eingeschalteten Gerät neben einem Zettel mit dem heutigen Datum schicken?",
        "draft.q_photos": "Kannst du noch ein paar Fotos schicken, vor allem vom Gerät selbst und von Schäden?",
        "ins.relisted": "vermutlich neu eingestellt ({by}): ein Inserat war bis {gone} online (seit {start}, zuletzt {price} €)",
        "ins.by_photo": "gleiches Foto", "ins.by_text": "gleicher Ort, ähnlicher Titel und Preis",
        "ins.sold": "{n} Inserate dieser Gruppe in {days} Tagen verschwunden, Median {median} €",
        "ins.sold_days": ", im Schnitt {d} Tage online",
        "hint.none": "kein Marktpreis für diese Gruppe – verkaufte Inserate selbst vergleichen",
        "hint.offers": "{n} aktuelle Angebote", "hint.both": "{gone} verschwunden + {n} aktuelle Angebote",
        "hint.text": "für {list} € inserieren, nicht unter {floor} € ({group}, {src}{days})",
        "hint.days": ", im Schnitt nach {d} Tagen weg",
        "parts.title": "Teilekatalog und Lager",
        "parts.intro": ("Nutze diese Preise und Einbauzeiten statt eigener Schätzungen, wenn ein Teil passt "
                        "(Zeit pro Stück).\nTeile mit Lager > 0 sind schon da:\n"
                        "- mit 0 € für Gewinn und Kaufentscheidung rechnen, höchstens bis zur Lagermenge\n"
                        "- in `parts_in_stock` auflisten, z. B. [\"Stick-Modul x2\"]; beim Teil in `missing_parts`\n"
                        "  `\"in_stock\": true` setzen"),
        "parts.header": "| Teil | passt für | Spezifikation | Preis/Stk. | Einbau | Lager |",
        "parts.estimate": " (Schätzung)",
        "wanted.reject": "Such-, Ankaufs-, Tausch- und Mietinserate sind keine Angebote: verwerfen.",
        "wanted.accept": ("Such-Inserate (jemand sucht einen Gegenstand oder eine Leistung) sind genau das Ziel "
                          "dieser Suche: ein Inserat NICHT verwerfen, weil es ein Such-Inserat ist. Reine "
                          "Ankaufsinserate von Händlern (\"kaufe alles\") trotzdem verwerfen."),
    },
    "labels": {
        "condition": "Zustand", "market_group": "Marktgruppe", "shipping_cost_eur": "Versand/Fahrt beim Kauf (€)",
        "device": "Gerät", "defect": "Defekt", "likely_cause": "Wahrscheinliche Ursache", "repair_parts_eur": "Teile (€)",
        "repair_hours": "Arbeit (Std.)", "tools": "Werkzeug", "expected_profit_eur": "Gewinn (€)",
        "profit_per_hour_eur": "Gewinn pro Stunde (€)", "risk": "Risiko", "auction_end": "Auktionsende",
        "deal_type": "Art", "visible_damage": "Auf Fotos sichtbar", "photo_check": "Fotoprüfung",
        "market_price": "Verkaufspreis (Bewertung)", "distance_km": "Entfernung (km)",
        "shipping_possible": "Versand möglich", "market_median": "Median Angebotspreise (€)",
        "market_n": "Vergleichsinserate", "market_resale_estimate": "Realistischer Verkaufspreis (€)",
        "bundle_qty": "Stückzahl im Paket", "private": "Privatverkauf", "best_offer": "Preisvorschlag möglich",
        "shipping_unknown": "Versandkosten unbekannt", "shipping_note": "Versand", "location": "Ort",
        "km": "Kilometer", "year": "Baujahr", "ps": "Leistung (PS)",
    },
    "values": {"repair": "Reparatur", "flip": "Flip", "low": "niedrig", "medium": "mittel", "high": "hoch",
               "reserved": "reserviert", "active": "aktiv", "matches description": "passt zur Beschreibung",
               "more damage than described": "mehr Schäden als beschrieben",
               "insufficient photos": "Fotos unzureichend"},
}

LOCALES = {"en": EN, "de": DE}


class Locale:
    def __init__(self, code):
        if code not in LOCALES:
            raise ValueError(f"unknown locale '{code}' (available: {', '.join(LOCALES)})")
        self.code = code
        d = {**EN, **LOCALES[code]}
        self.texts = {**EN["texts"], **LOCALES[code].get("texts", {})}
        self.labels = {**EN["labels"], **LOCALES[code].get("labels", {})}
        self.values = {**EN["values"], **LOCALES[code].get("values", {})}
        self.number_words = d["number_words"]
        self.stop_words = set(d["stop_words"])
        num = r"(\d{1,2}|" + "|".join(sorted(self.number_words, key=len, reverse=True)) + ")"
        self.qty_rx = [
            # "3 PS4 controllers", "2x DualSense", "drei defekte Controller"
            re.compile(r"(?<![\w.,])" + num + r"\s*(?:" + d["qty_units"] + r")?\s+(?:[\w-]+\s+){0,2}?(?:"
                       + d["qty_nouns"] + r")\b", re.I),
            # "DualSense 2x", "Controller 3 Stück"
            re.compile(r"(?<![\w.,])" + num + r"\s*(?:" + d["qty_units"] + r")(?!\w)", re.I),
            # "Controller x2", "DualSense ×3"
            re.compile(r"(?<![\w.,])[x×]\s*" + num + r"(?!\w)", re.I),
        ]
        self.not_qty = re.compile(d["not_qty"], re.I)
        # "Switch Lite with charger", "PS5 inkl. Kabel + Hülle": accessories that come WITH a device
        self.with_clause = re.compile(r"(?:" + d["with_words"] + r")\s*(?:\d+\s*)?(?:x\s*)?(?:[\w.-]+\s+){0,2}?"
                                      r"[\w.-]+(?:\s*(?:" + d["with_words"] + r"|,)\s*(?:\d+\s*)?(?:x\s*)?[\w.-]+)*", re.I)
        self.accessory = d["accessory"]
        self.bundle_extras = re.compile(d["bundle_extras"], re.I)
        self.without = re.compile(d["without"], re.I)
        self.with_word = re.compile(d["with_words"], re.I)
        self.part = d["part"]
        self.part_state = re.compile(d["part_state"], re.I)
        self.part_bundle = d["part_bundle"]
        self.part_veto = re.compile(d["part_veto"], re.I)
        self.market_exclude = d["market_exclude"]
        self.negations = d["negations"]
        self.conjunctions = d["conjunctions"]
        self.no_damage = re.compile(d["no_damage"], re.I)
        self.reserved_title = re.compile(d["reserved_title"], re.I)
        self.fraud = d["fraud"]
        self.decimal, self.thousands = d["decimal"], d["thousands"]

    def t(self, key, **kw):
        s = self.texts.get(key, key)
        return s.format(**kw) if kw else s

    def label(self, field):
        return self.labels.get(field, field)

    def value(self, v):
        return self.values.get(v.lower(), v) if isinstance(v, str) else v

    def num(self, v, digits=0):
        s = f"{v:,.{digits}f}"
        return s.replace(",", "\0").replace(".", self.decimal).replace("\0", self.thousands)

    def eur(self, v, digits=0):
        from .util import num
        n = num(v)
        return f"{self.num(n, digits)} €" if n is not None else "?"


_CACHE = {}


def get(code="en"):
    code = str(code or "en")
    if code not in _CACHE:
        _CACHE[code] = Locale(code)
    return _CACHE[code]


def for_search(cfg, sc=None):
    return get((sc or {}).get("_locale") or (cfg or {}).get("locale") or "en")
