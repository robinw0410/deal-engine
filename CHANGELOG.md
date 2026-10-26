# Changelog

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
