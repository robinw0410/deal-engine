# Changelog

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
