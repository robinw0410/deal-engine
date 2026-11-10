# Changelog

## 0.2.15 – 2026-11-10

### Added

- **`market.sample: device_only`** (per search, default `all` = unchanged): median, p25 and n of a
  market group only from listings the stored LLM classification calls `device` with quantity 1 of
  this group (plausible as in `groups.from_classification`). Bundles, accessories, parts, `other`
  and listings not classified yet do not count; a classified device whose title lists games after a
  with-word counts as a bundle. Defect signal, `market_exclude`, the group's price range, the
  fresh/private selection and `min_n` apply as before. No model is called at the market update:
  `update_market` attaches the stored classification to the items as `_cls`
  (**`history.attach_classification`**, read-only; a missing or unreadable `history.db` means
  "not classified", never an aborted run). An unknown `sample` value is a configuration error.
- **Adjusted bundles**: with fewer than **`market.device_min_n`** (default 8) single devices,
  bundles of the group are added at their price minus the extras (**`market.bundle_adjust`**):
  n × the asking median of the group's `extras` groups (the median computed in the same update,
  otherwise the previous one; **`market.estimate_groups`** orders the groups accordingly) and a flat
  value per game. Adjusted prices must be above 0 and within the group's range; a bundle with
  nothing to deduct or with extras that have no market price is left out.
- **Flat value for games**: **`market.game_value`** (default 5 € per game), **`market.game_value_max`**
  (default 30 € per listing), **`market.games_default`** (default 2 for "mit Spielen" without a
  count). **`groups.games_count(title, loc, default)`** counts them with the locale's words (de
  "Spiel/Spiele/Spielen/Games", en "game(s)"): "mit 3 Spielen" = 3, "+ 6 Spiele" = 6, "ohne Spiele" =
  0, number words; a game named only by its title, "Spielekonsole"/"game console" and model numbers
  are no count.
- **Evaluation of bundle offers**: the same flat value is added to the candidate threshold and to
  `market_resale_estimate` (selection and insights, next to the extras). The listing carries
  **`market_games`** (`{count, value}`), `score_calc` names it when the resale cap applies ("Spiele
  (6) pauschal 30 €"), and the evaluation prompts say it is already in the estimate. Only with
  `sample: device_only` or when `game_value` is set (0 switches it off); searches with neither
  setting are evaluated exactly as before.
- **Market file**: with `device_only` a group entry also has `"sample"` (`"device_only"` |
  `"adjusted_bundles"`), `"n_device"` and `"n_bundle"` (`n` = both); with `all` the format is
  unchanged.
- **`market.sample_report(con, sc, days=30, loc=None, today=None, market=None)`**: before/after per
  group from the listings in `history.db` (read-only connection is enough): `before` with `all`,
  `after` with the search's setting (`device_only` if it still has `all`), `device` and `bundle`
  (median and n by classification), `bundle_share`, `unclassified`. Command line:
  `python -m deal_engine market-sample <search> [--days 30]`; `history.connect_ro(db)`.

## 0.2.14 – 2026-11-06

### Added

- **Optional search terms on the wish list**: a wish can be saved without search terms (0–5 instead of
  1–5, form and JSON API). The deal server never calls a model itself; a host application generates
  the missing terms and stores them with **`wishes.set_ai_terms(cfg, wish_id, terms)`**: the terms are
  cleaned with **`wishes.clean_ai_terms`** (plain text, no regex or search syntax, bounded length, no
  duplicates, at most 5; invalid entries are dropped) and written in one transaction only if the wish
  has no terms or new suggestions were requested, so terms the user entered (also meanwhile) are never
  overwritten. `wishes.needs_terms(w)` tells which active wishes need suggestions.
- **New wish fields** `terms_source` (`"user"` | `"ai"`), `terms_updated` (time of the last change of
  the terms) and `terms_regen` (new suggestions requested), in `wishes.active(cfg)` and the JSON API.
  A wish created without terms gets `terms_source` `"ai"`; changing the terms in the form or API makes
  them the user's (`"user"`; emptied again: `"ai"`, suggestions pending).
- **"Suggest terms again"** button per wish (form action `regen` with CSRF token) and
  `POST /deals/api/wishes/<id>/regen` (header `X-CSRF-Token`, `application/json`, same-origin check):
  **`wishes.request_regen(con, id)`** only sets `terms_regen`; the next run of the host application
  replaces the terms. The page labels suggested terms "AI suggestion" with their time and shows
  "Suggestions pending" for wishes without terms or with a pending request; the form explains that
  empty terms are suggested on the next run and that changed suggestions become the user's own.

### Changed

- **Database migration**: `wishes.init` adds the three columns to an existing `wish` table of 0.2.13
  (`ALTER TABLE`, defaults `"user"`, none, no request); `wishes.active(cfg)` on a database that has not
  been migrated yet (read-only) returns the defaults.

## 0.2.13 – 2026-11-06

### Added

- **Wish list on the deal server** (`/deals/wishes/`, linked from the deal list): products to look for
  with name, 1–5 plain-text search terms, maximum price incl. shipping, platforms, active and a note.
  Server-rendered HTML forms (no JavaScript, strict Content-Security-Policy, same navigation and styles
  as the deal list, texts in en/de); after a change the page redirects (303) with a message, invalid
  input is shown again with the error. At most 10 active wishes and 5 terms per wish, enforced on the
  server (`deal_engine.deals.wishes`). JSON API at `/deals/api/wishes` (GET, POST, PUT/DELETE
  `/<id>`). Stored in `state/deals.db` (table `wish`).
- **`wishes.active(cfg)`**: the active wishes for a host application, read-only; `[]` without database.
- **CSRF protection**: wish list writes need a token (hidden form field `csrf` or header
  `X-CSRF-Token`): `<time>.<HMAC-SHA256>` with a random key created on first start in
  `state/deals-secret` (mode 0400, so a process without a shell, e.g. an LLM evaluator with a
  file-write tool, cannot overwrite it; symlinks are not followed), valid for 24 h.

### Fixed

- **Write requests to the deal server could be sent from other sites**: the JSON check accepted any
  `Content-Type` containing `application/json`, e.g. `text/plain; application/json`, which a browser
  sends cross-site without a CORS preflight; together with the cookie / basic auth of a reverse proxy,
  another web page could add deals, parts and purchases. The media type must now be exactly
  `application/json`, and every POST/PUT/DELETE a browser marks as cross-site (`Sec-Fetch-Site` other
  than `same-origin`, or an `Origin`/`Referer` whose host differs from `Host`, compared without port;
  `X-Forwarded-Host` only with `deals.trust_forwarded_host: true`) is refused with 403. A negative `Content-Length` no longer blocks the request thread.
- Responses of the deal server also carry `X-Frame-Options: DENY`, `Referrer-Policy: same-origin` and
  `Content-Length`.

## 0.2.12 – 2026-11-04

### Fixed

- **Deal list navigation led to the site root**: the deal list linked "Search pages" to `../` and
  itself to `./`. Behind a reverse proxy whose `/` is another site, "Search pages" led nowhere. The deal
  list now has the navigation of the search pages: one link per search of the config (`../<slug>/`,
  title, config order), then the deal list (`../deals/`, active). No link points to the site root any more.
  Without searches in the config the navigation is the deal list alone; broken `web` settings of a search
  leave the deal list usable (deal-list link only, reason on stderr). The text `nav.pages` is gone.

### Added

- **`render.nav_links(cfg, active, loc)` / `render.nav_html(…)`**: the shared navigation of the search
  pages and the deal list (`active`: a search name or `render.DEALS`). The deal-list link appears unless
  `deals.enabled: false` (on the deal list itself always). Search pages are unchanged apart from the
  deal-list link now having an (empty) `class` like the other links.

## 0.2.11 – 2026-10-29

### Added

- **`category_caps[].category` with `category_hook`**: a quota can count listings by a category the
  search's hook returns (`category_hook: "module:function"`, listing -> name or None) instead of a title
  regex; `category` takes one name or a list. `max_share` counts the state through the same hook.
- **`priority_hook`** (`"module:function"`, listing -> number): higher first when candidates are picked
  (before quotas and `max_new_per_run`) and when the backlog is bounded; same priority: newest first.
- With a `category_hook`, `backlog.max` discards evenly across categories (per category the
  preferred and newest stay) instead of only the oldest overall.
- Hooks that raise are logged and count as no category / priority 0; unloadable hooks are a
  `ConfigError` before collecting. A quota needs exactly one of `regex` / `category` (`ConfigError`).

## 0.2.10 – 2026-10-29

### Fixed

- **eBay `category_ids` with several ids gave HTTP 400**: the Browse API takes one category id per
  request. Several ids (`"a,b"` or a list) now mean one request per id and marketplace.
- **eBay errors are readable**: on HTTP 4xx (and 5xx after retries) the `errors[]` of the response
  (`errorId`, message; shortened, without token or key) is part of the message.
- **One failing eBay request no longer drops the whole term**: failed requests of a term are skipped and
  reported as problems (status `partial`); the term fails only if all its requests failed. Other terms
  ran on before and still do. HTTP 429 still stops the adapter.

### Added

- **`ebay.keyword_categories`**: category id(s) per search term, overriding `category_ids`; a key that is
  not a configured search term or has no id is a `ConfigError`. Queries of other terms (e.g. market groups)
  use `category_ids`.
- **`Adapter.warnings`**: adapters can report partial failures of a search; the pipeline moves them into
  the run's problems.

## 0.2.9 – 2026-10-28

### Added

- **`profile` as a list of files** (`profile: ["profiles/a.md", "profiles/b.md"]`): joined in order with a
  blank line, for the prefilter and the evaluation; a string works as before. A missing file is the same
  `ConfigError` as before, a wrong type or an empty list is a `ConfigError` at load time.
  `deal_engine.core.run.profile_text(cfg, sc)` returns this joined text for scripts that build their own
  prompts.

### Fixed

- **Spare parts that passed `parts: skip`** (locale de):
  - a leading "100 % " no longer counts as the middle of a title, so "100 % Original Display Für IPHONE
    15 Pro Max LCD" is a part again ("iPhone 13 100 % Original Display" stays a device);
  - a title starting (after "100 %", "original", "neu" …) with a part noun followed by "für/for/passend"
    ("Display für …", "Netzteil für PS5", "Mainboard für ThinkPad T480") is a part also when the
    classification says device; console titles and "Netzteil defekt für PS4 Bastler" stay devices;
  - new part words: "HDD-/SSD-/Festplatten-/NVMe-Gehäuse"; "NAS Gehäuse" and "Leergehäuse" at the start
    of a title without a NAS brand or model (Synology, QNAP, DS218, TS-251 … "ohne HDD" or "QNAP TS-453
    Pro Leergehäuse" stay devices); a standalone PC power supply when the title starts with the wattage,
    ATX/SFX or a PSU brand and then the wattage ("650W Netzteil", "Corsair RM750x 750W ATX Netzteil"),
    while "<model> 65W Netzteil" (mini PC, laptop, printer, switch …) and titles naming a PC, laptop,
    NAS, console or PC component stay devices; "Netzteil" also counts with "für/passend", while
    "<device> Netzteil passend dabei" stays a device.

## 0.2.8 – 2026-10-27

### Fixed

- **Score of device bundles with extras.** `market_extras` only raised the candidate threshold; the
  resale estimate (and with it the score's 105 % resale cap) still counted the device alone, so
  "PS4 Slim + 2 Controller + 6 Spiele" fell to score 1 ("below minimum profit").
  `market_resale_estimate` now adds n × the extra group's resale estimate (`market.extras_resale`,
  same sale_factor logic as the device; games still 0), at the selection and in the insights after
  the sold-price and bundle steps; `market_extras` rows carry `resale`.
- **Spare parts with "Ersatzteil".** Titles like "PS2 Leergehäuse Original Ersatzteil", "Lüfter Kühler
  Fan … Ersatzteil", "Laufwerksblende … Ersatzteil" or "Controller Port Anschlussleiste Ersatzteil"
  passed `parts: skip` (compound nouns, or the classification said device). A part noun before
  "Ersatzteil"/"spare part", or a title starting with it (locale `part_spare`,
  `groups.is_spare_part`), is now a part, also against a device classification. A noun followed by a
  state word ("Ersatzteile Board defekt", "Ersatzteil Rahmen verbogen"), devices sold "als
  Ersatzteil", "Ersatzteilspender" and console titles stay devices.
- `score_calc` names the extras ("inkl. 2 × DualShock 4 à 26 €") when the resale cap applies, i.e.
  when the price comes from the market estimate; the evaluation prompt says the extras are already in
  `market_resale_estimate`.

## 0.2.7 – 2026-10-27

### Added

- **Filter hooks** (`filters.hooks: ["module:function"]`): hard filters in code, called with the
  normalized listing in `filters.passes()` after the declarative filters; a truthy return value (a
  reason) rejects the listing before the selection and the evaluation. Loaded and checked at the
  start of a run like score hooks (`filters.load_hooks`, ConfigError for a non-list, an unloadable
  or not callable spec); `filters.hook_failed()` names the rejecting hook, `select()` logs how many
  listings the hooks rejected (with examples). A hook that raises lets the listing pass (logged), like
  score hooks. Not applied to the stored listings; applied to the history tracking of searches without
  market groups.

## 0.2.6 – 2026-10-27

### Added

- **Extras in the candidate threshold** (group setting `extras: {"<group>": "<regex>"}`). A device
  listed with extras that have their own market group ("PS4 + 2 Controller + 6 Spiele") was compared
  with the median of the device alone. The threshold is now (device median + n × the extra group's
  median) × ratio; n is counted from the title (`groups.extras_count`: numbers and number words,
  "+ Controller" = 1, negations and accessory/part words right after it = 0, at most 8). Extras
  without market data and games add nothing. Candidate selection only; the candidate carries
  `market_extras` (refreshed with the market data on every run, not shown on the page). Groups are
  checked at load (other group, non-empty regex that does not match the empty string). Without
  `extras` nothing changes.
- Counting rule: a model number is no count ("DualShock 4 Controller", "PS 4 Controller" = 1; brand
  and unit word right after each other are one mention); a unit followed by "fehlt", "nicht dabei",
  "defekt", "kaputt", "ohne Funktion", "Drift" or "fake" counts 0, "2 Controller (1 defekt)" counts 1;
  "Controllerladestation" counts 0; up to two fillers between count and unit ("2 originale Sony
  Controller"), "Controller x2"; a negation reaches "ohne Kabel und Controller" but not "ohne OVP 2
  Controller".

## 0.2.5 – 2026-10-27

### Fixed

- **Comma lists after a with-word** ("Switch mit Spielen, Hülle und Tasche", "PS4 Slim mit Controller,
  Kabel, Hülle") made the bundle an accessory: the with-clause needed a space before the comma, so
  ", Hülle" stayed. Items of a with-clause chain may now also carry a quantity ("+ 2 Controller + 6
  Spiele").
- **Devices with games in the market statistics.** A device listed with extras of their own value
  ("PS4 mit 6 Spielen", "Konsole + Zelda") counted as a single unit and raised the group median.
  `groups.has_extras()` (locale `bundle_extras` after a with-word; "ohne Spiele" does not count) keeps
  them out of `market.estimate()` and `groups.market_group()`; as candidates they are unchanged.

## 0.2.4 – 2026-10-27

### Added

- **Bounded backlog of postponed candidates** (`backlog: {max: N, max_age_days: D}` per search,
  overridable per adapter; `{}` switches it off). Candidates postponed beyond the per-run limit or
  by a category quota were re-considered on every run and the count grew with the search pool.
  Postponed candidates beyond the newest `max` or published more than `max_age_days` ago are now
  discarded: written to `seen` with `"skipped": "backlog"`, they come back only after the seen
  retention or with a price drop of 10 %. A quota's rest is bounded by `category_caps[].backlog`
  (default 3 × its `max_new_per_run` when a backlog is set). Logged as "… postponed, … discarded:
  backlog"; `AdapterResult.discarded`. Without `backlog` nothing changes.
- **Spare parts without the device** (`parts: llm|skip|bundles|accept`, default `llm`). The
  classification has a kind `part`; `llm` drops what the model calls a part (part lots stay, as in
  0.2.3), `skip` adds a word rule (`groups.is_part`, locale `part`/`part_state`/`part_bundle`,
  overridable with `market.part_regex`) for titles like "Mainboard ThinkPad …" or "Display für
  iPhone 12", `bundles` keeps part lots, `accept` evaluates parts. The word rule prefers precision:
  devices with a broken or listed part ("ThinkPad T480 Display defekt", "… FHD Display", "PS5
  Laufwerk Edition", "MacBook Pro defektes Logicboard") and anything with console/Konsole stay.

### Fixed

- `reconcile()` only applies hard limits (max_price, field filters, title regexes), never a market
  threshold or bundle quantity; covered by tests. The title rule judges the current platform title
  when the listing is in the search results (the stored title may come from the evaluation).
- `reconcile()`: links of another platform (by host, ignoring www./m. and the TLD) protect a listing
  from removal as before; links of the same platform (a merged relist, ebay.at next to ebay.de) do
  not. When a listing is gone, all links of its platform are removed, and a listing without any
  remaining source or foreign link counts as gone.

## 0.2.3 – 2026-10-27

### Fixed

- **Model numbers read as bundle quantities.** "PlayStation 5 Controller" counted as five
  controllers, "PlayStation 4 Controller" as four and "Xbox Elite 2 Controller" as two, so the
  listing was kept out of the controller group's statistics and compared with the wrong price.
  Locales `en`/`de`: `not_qty` += playstation, elite.
- `bundle_qty()`: after a skipped model number the search continues right behind it, so a quantity
  that follows directly is found ("PlayStation 4 2 Controller" = 2, before: 1).
- Locales `en`/`de`: "x2"/"×3" after the noun is a quantity ("Controller x2", "DualSense ×3").
- **Title filters now also apply to the stored listings.** `reconcile()` checked only `max_price` and
  field filters, so a listing that entered the state under an older, looser
  `include_title_regex`/`exclude_title_regex` stayed there for good. It is now removed like a
  `max_price` violation (reported as no longer matching the criteria), except when it has no stored
  title or another source. If more than max(5, 30 %) of an adapter's listings would go at once, nothing
  is removed and the run reports a problem (`prob.title_rule`): a too broad regex cannot wipe the
  state.
- **Evaluator tier restored when a score hook cap goes away.** Without formula numbers only the
  evaluator's score was kept (`score_ai`), not its tier: a listing capped by a hook kept the capped
  tier after the cap no longer applied. `tier_ai` is now stored on the first run as well.

### Added

- `filters.title_failed(title, filters)`: "exclude", "include" or None; used by `passes()` and
  `reconcile()`.

## 0.2.2 – 2026-10-27

### Fixed

- **Wrong market groups for candidates.** Candidates were grouped by word rules only (the LLM
  classification ran after the merge), and a title excluded by one group fell through to the
  next, broader group: "DualSense for PS5 console" ended up in "PS5" (resale ~400 €), "PS5
  headset" in "PS5", "Switch 2 controller" in "Nintendo Switch". Fixed by the group `veto` and
  the classification before the selection (see Added).
- **Implausible model groups are ignored.** A title the word rules place in "DualSense"
  ("DualSense funktionsfähig") was shown with the PS5 price: the stored LLM classification (e.g. a
  shifted index in a batch of 150 titles) overrode the word rules in the insights. A model group is
  now only used if its `match` regex hits the title and its `veto` does not (`exclude` is ignored for
  this check) — in
  the candidate selection, in the insights and in the tracking table; otherwise the word rules
  decide (`groups.from_classification()`).
- **Tracking keeps the model's decision.** `history.track()` uses a stored, plausible
  classification (same title) instead of the word-rule group, and a group the model removed is no
  longer restored by the word rules on the next run (`COALESCE`). Results of the classification
  before the selection reach `listing.grp` as well.
- Locale `de`/`en`: charging stations, docks, stands, kits and cables ("charging station",
  "charging dock", "charging cable", …) and "docking station"/"dockingstation" are accessory words.
  A bare "charging" is not ("Switch Lite Charging Port defekt" stays a repair candidate).
- Locale `de`/`en`: "ohne"/"without" clauses no longer make a device an accessory ("PS5 Konsole
  ohne Fernbedienung", "Switch Lite ohne Ladekabel").
- Locales `en`/`de`: a number after "Switch" is not a bundle quantity ("Nintendo Switch 2 Pro
  Controller" is one controller, not two).

### Added

- **Group `veto`** (regex, case-insensitive): if a group's `match` and `veto` both hit,
  `match_group()` returns `None` at once, without falling through to later groups. Documented in
  the README ([Market groups](README.md#market-groups)) and in `config.example.yaml`. Note: a
  veto leaves a title without group; products that have no group of their own (e.g. a new console
  generation) are then not compared with any market price until you add a group with its own price
  range.
- **Classification before the candidate selection.** With `classify` enabled and the LLM
  evaluator (`claude`), `pipeline.collect(..., classify_first=True)` (set by `run_search`)
  classifies the titles of the listings it is about to consider as candidates before `select()`:
  only titles that some group's `match` hits, not classified yet (table `classify` in
  `history.db`, same title, key `<adapter>-<source_id>`). `select()` then uses a plausible stored
  classification: `device`/`bundle` → that group (and quantity for controller-like groups),
  `accessory` → skipped, `other` → no group, no market comparison. If the model is unavailable, the
  word rules stay in effect (logged, the run does not fail). With a callable evaluator (demo,
  tests) no model is called.
- `classify.max_per_run` is a budget per search run (`classify.Budget`), shared by all adapters'
  classification before the selection and the step after the merge.
- Group regexes (`match`, `exclude`, `veto`) are compiled when a search is loaded
  (`config.search()`); an invalid regex or a group without `name`/`match` is a `ConfigError`.
- `classify.classify_titles(cfg, sc, con, [(uid, title), …])` (batches, parsing and storing, used by
  both classification steps), `classify.preselect()`, `classify.settings()`,
  `classify.correct_tracking()`, `history.classification()`, `groups.from_classification()`,
  `groups.classified_market_group()`, `groups.check_groups()`, `groups.matches_any()`,
  `groups.is_bundle_group()`, `pipeline.considered()`; `pipeline.select(..., classified=...)`,
  `pipeline.collect(..., classify_budget=...)`.

### Security

- `llm.extra_args` (and `llm.command`) must not contain `--dangerously-skip-permissions`,
  `--allow-dangerously-skip-permissions`, `--permission-mode bypassPermissions` or `--settings`
  (a settings file can set `permissions.defaultMode: bypassPermissions`); also as `--flag=value`,
  as one argument with a space, in any letter case: configuration error. The flags are matched as
  literal tokens, so a text argument that merely mentions one is rejected too. `llm.run()` checks
  the complete command line before every call.

## 0.2.1 – 2026-10-27

### Security

- Every LLM call now gets `--disallowedTools Bash WebFetch WebSearch` in addition to the explicit
  `--tools` list (Read/Write for evaluation and prefilter, none for classification), also when
  `llm.extra_args` are set. `llm.extra_args` that allow Bash, WebFetch or WebSearch via
  `--tools`/`--allowedTools` are a configuration error.

### Added

- **Deal list localized:** the deal list page (`deal_engine/deals/deals.html`) follows the config
  `locale` (`en`/`de`): all headings, buttons, labels, placeholders, confirmations, empty states,
  status names and number/currency formatting (de: `1.234 €`). Texts live in
  `deal_engine/deals/texts.py`. Statuses are still stored as machine values (`bought`,
  `in progress`, `listed`, `sold`, `scrapped`). This fixes the "Not localized" note of 0.2.0.
- **`web.copy_prompt`** (global, overridable per search with `searches.<name>.web.copy_prompt`)
  switches the "copy as prompt" button of the search pages.
- `--locale` option of the deal server (overrides the config locale); `make serve-demo-de` uses it,
  so the German demo shows the German deal list and price hints.

### Changed

- **Breaking:** the "copy as prompt" button (and its hidden prompt text) is off by default; set
  `web.copy_prompt: true` to get it back.

## 0.2.0 – 2026-10-26

Extensibility release: adapters, filters, language, prompts, page layout and score adjustments can
be added or changed from the outside, without editing deal-engine.

### Breaking changes

- **Package name:** everything lives under `deal_engine.*` (`deal_engine.core`, `.adapters`,
  `.web`, `.deals`, `.demo`). There are no top-level packages `core`, `adapters`, `web`, `deals`,
  `demo` any more. CLI: `python -m deal_engine …` (was `python -m core …`), deal list:
  `python -m deal_engine.deals.deals_server`, eBay probe: `python -m deal_engine.adapters.ebay`,
  demo: `python -m deal_engine.demo.run_demo`.
- **Relative paths** in the config (`data_dir`, `profile`, `json_file.path`, `prompts`,
  `plugin_paths`, `web.root`) are resolved relative to the config file, no longer relative to the
  installation. The config is looked up in the current working directory (not the repository).
  `--web-root` of the deal server is relative to the working directory.
- **Adapter interface:** `check(source_id)` returns `(status, price)` (price may be `None`);
  a plain status string is still accepted. Configuration problems raise
  `deal_engine.core.config.ConfigError` instead of `SystemExit` (eBay without credentials, missing
  `json_file.path`, unknown adapter).
- **`run_search()`** returns a `RunResult` (per adapter `status` ok/partial/failed, `reason`, `error`,
  counts) instead of `True`/`False`; `bool(result)` is true only if every adapter is `ok`.
  `pipeline.collect()` and `pipeline.merge()` return dicts with counts.
- **CLI exit codes:** 0 ok, 1 an adapter had problems or failed, 2 configuration error
  (e.g. eBay without credentials).
- **Prompts** moved to `deal_engine/core/prompts/<locale>/` (`evaluate.md`, `prefilter.md`, and the
  classification prompt, which was inline before). `llm.prompt()` takes `(cfg, sc, name, …)`.
- **Web pages:** the built-in electronics page layout moved from `web/render.py` into the config
  (`searches.<name>.web`); a search without `web` gets the generic page.
- Score: `compute()` returns cap keys (`caps`, `cap_notes`); the negotiation hint no longer parses
  note texts. `fraud_regex` has no global default any more, it comes from the locale.
- Downloaded photos must be JPEG, PNG, WebP or GIF (checked by content); anything else is skipped.

### Added

- **Adapter registry:** adapters by config (`adapters: {name: "module:Class"}` plus
  `plugin_paths`), by entry point (group `deal_engine.adapters`) or built in.
  `python -m deal_engine adapters` lists them.
- **Adapter interface:** `details()` may return `{"reject": "reason"}` to drop a candidate before
  evaluation; optional `fetch_image(url)` downloads photos with the adapter's own rate and
  headers; `max_new_per_run` per adapter (`searches.<name>.<adapter>.max_new_per_run`).
  `check()` prices update the state and the tracking database.
- **Filters:** numeric min/max filters on any field (`filters.fields: {km: {max: 60000}}`, optional
  `missing: fail`), also applied to stored listings (they leave the state as "no longer matches").
  Extra listing fields (`km`, `year`, `ps`, …) are real fields: in the evaluation batches, usable by
  filters and carried into the state. `category_caps` support `max_share`.
- **Locale** `en`/`de` (`locale:` globally or per search): bundle quantities ("3 Stück",
  "drei Controller"), "inkl./mit" clauses for accessory detection, default accessory and
  market-exclude words, fraud negations ("keine Vorkasse"), stop words for relist detection,
  report, score calculation, negotiation hint, message draft, insights, price hints, parts block,
  page texts and field labels. Machine values in the state stay English.
- **Prompts** overridable per config path (`prompts: {evaluate: …, prefilter: …, classify: …}`,
  globally or per search); German built-in prompts.
- **`wanted_ads: reject | accept`** per search; the evaluation and prefilter prompts follow it
  (for searches that look for wanted ads).
- **Web page per search from the config:** slug, title, tier names, top-table columns, card meta,
  badges, sorts, facets, groups, toggles, deal link.
- **Score hooks:** `score.hooks: ["module:function"]`, called after the calculation for every
  listing, may change the score and add a note.
- `make demo-de`: the demo with the German locale.

### Not localized

- The deal list page (`deal_engine/deals/deals.html`) is still English; only the price hints and the parts
  block it gets from the server follow the locale.

## 0.1.1 – 2026-10-26

- eBay adapter verified against the live Browse API (token, search on EBAY_AT and EBAY_DE,
  getItem, check) with the probe command.
- Unknown shipping costs are no longer treated as 0: such items are marked `shipping_unknown`
  ("shipping unknown, assumed 15 €") and `shipping.unknown_cost` (default 15 €) is used for
  candidate selection and score. A stated cost of 0 still means free shipping.

## 0.1.0 – 2026-10-26

First public release.

- Platform-neutral core: listing format and validation, filters, market groups with bundle and
  accessory detection, market price estimates from asking prices and from disappeared listings,
  price tracking (SQLite), insights (time online, price drops, relisted items), score formula
  with price ceiling, negotiation hint and message draft.
- Optional LLM steps through the Claude Code CLI: evaluation, prefilter, group classification.
- Adapters: `json_file`, `ebay` (official Browse API, item data only, with a live probe command).
- Deal list and parts inventory with listing price hints; static page per search.
- Demo mode (`make demo`) with invented listings over simulated days; tests (`make test`).
