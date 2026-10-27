Assign each listing title to a device group.

Groups:
{{GROUPS}}

Rules:
- "g" only if the title offers a DEVICE of this group (also broken or for parts).
- Accessories (cases, chargers, cables, mounts, grips, games), clothing and everything else:
  "g": null, "k": "accessory" or "other".
- Spare parts without the device (mainboard, display unit, battery, keyboard, fan, housing, drive)
  and lots of such parts: "g": null, "k": "part". A device with a broken, weak or new part
  ("ThinkPad T480 display broken", "iPhone 12 battery 80%") is a device, not a part.
- Console with controllers/games/accessories: the console's group, "k": "bundle".
- Several identical controllers ("3 PS4 controllers", "2x DualSense"): controller group, "q" = count.
- Third-party and imitation products ("compatible", unknown brands): "g": null, unless there is a
  matching group of their own.
- Always the most specific matching group; if the variant is unclear, the more general one.

Answer ONLY with JSON lines, one per title, no other text:
{"i": <number>, "g": "<group name>" or null, "q": <count>, "k": "device"|"bundle"|"accessory"|"part"|"other"}

Titles:
{{TITLES}}
