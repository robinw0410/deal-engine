---

## Aufgabe für diesen Lauf: NUR BEWERTEN (hat Vorrang vor allem oben)

Ein Skript hat die Quellen bereits durchsucht. Du hast keinen Browser. Aus dem Suchprofil oben
nur die Kriterien, Gerätegruppen, Stufen, Bewertungsregeln und die Felder verwenden.

1. `{{CANDIDATES}}` lesen. Die Datei enthält `candidates` (neue Inserate mit Titel, Preis, Ort,
   Attributen, Beschreibung `description` und lokalen Bildpfaden `images`) und `existing_listings`
   (den aktuellen Bestand als Tabellenzeilen "id | title | price | location", nur zum Erkennen
   von Dubletten).
2. Jeden Kandidaten in zwei Stufen bewerten:
   a) Zuerst NUR Titel, Preis, Attribute und Beschreibung prüfen. Verstößt er gegen harte
      Kriterien oder käme er allein nach Text und Daten auf einen Score unter 6: verwerfen, OHNE
      die Bilder zu öffnen.
   b) Nur beim Rest die Bilder unter `images` mit dem Read-Tool ansehen (Fotoprüfung wie oben
      beschrieben), dann entscheiden.
   `market_median` (falls vorhanden) ist der vom Skript berechnete Median der Angebotspreise
   funktionierender Geräte dieser Gruppe (`market_n` = Anzahl der Inserate). Das sind
   ANGEBOTSPREISE, keine Verkaufspreise. `market_resale_estimate` als Basis für den
   Verkaufspreis nehmen und nur für Zustand, Speicher oder Zubehör anpassen. Ohne Marktdaten:
   den Verkaufspreis vorsichtig schätzen (unteres Drittel der Angebote) und in `issues`
   "Verkaufspreis geschätzt" vermerken.
   `distance_km` ist die geschätzte Straßenentfernung von zu Hause, `shipping_possible`, ob die
   Plattform Versand mit Käuferschutz anbietet, `shipping_cost_eur` die Versandkosten, falls die
   Quelle sie nennt, `private`, ob privat verkauft wird. `shipping_unknown: true` bedeutet, dass
   die Quelle keine Versandkosten nennt: keinen kostenlosen Versand annehmen; `shipping_cost_eur`
   weglassen, außer es gibt eine realistische Schätzung (das Skript nimmt dann die Pauschale aus
   `shipping_note` an).
   Verwerfen, wenn harte Kriterien verletzt sind, wenn es Zubehör statt eines Geräts ist oder
   wenn sich der Deal nach den Regeln nicht lohnt. {{WANTED_ADS}}
3. `{{ACCEPTED}}` als JSON-Liste NUR der angenommenen Inserate schreiben (leere Liste `[]`, wenn
   keines passt). Jedes Objekt enthält `source_id` (vom Kandidaten) plus alle Bewertungsfelder
   aus den Regeln oben (`tier`, `score`, `summary` und die suchspezifischen Felder). `id`,
   `urls`, `price`, `first_seen`, `last_seen` setzt das Skript.
   Texte (`summary`, `issues`, `why_interesting`, `defect`, `likely_cause` usw.) auf Deutsch
   schreiben. Feste Feldwerte bleiben dagegen genau so auf Englisch, wie das Suchprofil sie
   vorgibt, z. B. `deal_type` "repair"/"flip", `risk` "low"/"medium"/"high", `photo_check`
   "matches description"/"more damage than described"/"insufficient photos", `status`
   "reserved". Feldnamen nie übersetzen.
   Ist ein Kandidat derselbe Artikel wie ein Eintrag in `existing_listings` (andere Quelle), nur
   `{"source_id": "...", "merge_into": "<id des vorhandenen Eintrags>"}` schreiben.
4. Keine anderen Dateien schreiben. Heute ist der {{DATE}}.

Gründlich statt schnell: jeder Kandidat wird einzeln geprüft, keiner wird übersprungen.
