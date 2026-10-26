Ordne jeden Inseratstitel einer Gerätegruppe zu.

Gruppen:
{{GROUPS}}

Regeln:
- "g" nur, wenn der Titel ein GERÄT dieser Gruppe anbietet (auch defekt oder für Teile).
- Zubehör (Hüllen, Ladegeräte, Kabel, Halterungen, Grips, Spiele, einzelne Ersatzteile), Kleidung
  und alles andere: "g": null, "k": "accessory" oder "other".
- Konsole mit Controllern/Spielen/Zubehör: die Gruppe der Konsole, "k": "bundle".
- Mehrere gleiche Controller ("3 PS4 Controller", "2x DualSense"): Controller-Gruppe, "q" = Anzahl.
- Drittanbieter- und Nachbauprodukte ("kompatibel", unbekannte Marken): "g": null, außer es gibt
  eine eigene passende Gruppe dafür.
- Immer die spezifischste passende Gruppe; ist die Variante unklar, die allgemeinere.

Antworte NUR mit JSON-Zeilen, eine pro Titel, ohne weiteren Text:
{"i": <Nummer>, "g": "<Gruppenname>" oder null, "q": <Anzahl>, "k": "device"|"bundle"|"accessory"|"other"}

Titel:
{{TITLES}}
