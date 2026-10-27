# Changelog

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
