# Changelog

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
