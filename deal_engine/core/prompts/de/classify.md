Ordne jeden Inseratstitel einer Gerätegruppe zu.

Gruppen:
{{GROUPS}}

Regeln:
- "g" nur, wenn der Titel ein GERÄT dieser Gruppe anbietet (auch defekt oder für Teile).
- Zubehör (Hüllen, Ladegeräte, Kabel, Halterungen, Grips, Spiele), Kleidung und alles andere:
  "g": null, "k": "accessory" oder "other".
- Ersatzteile ohne das Gerät (Mainboard, Display-Einheit, Akku, Tastatur, Lüfter, Gehäuse,
  Laufwerk) und Konvolute solcher Teile: "g": null, "k": "part". Ein Gerät mit kaputtem, schwachem
  oder neuem Teil ("ThinkPad T480 Display defekt", "iPhone 12 Akku 80 %") ist ein Gerät, kein Teil.
- Konsole mit Controllern/Spielen/Zubehör: die Gruppe der Konsole, "k": "bundle".
- Mehrere gleiche Controller ("3 PS4 Controller", "2x DualSense"): Controller-Gruppe, "q" = Anzahl.
- Drittanbieter- und Nachbauprodukte ("kompatibel", unbekannte Marken): "g": null, außer es gibt
  eine eigene passende Gruppe dafür.
- Immer die spezifischste passende Gruppe; ist die Variante unklar, die allgemeinere.

Antworte NUR mit JSON-Zeilen, eine pro Titel, ohne weiteren Text:
{"i": <Nummer>, "g": "<Gruppenname>" oder null, "q": <Anzahl>, "k": "device"|"bundle"|"accessory"|"part"|"other"}

Titel:
{{TITLES}}
