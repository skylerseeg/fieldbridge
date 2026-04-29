# NAPC scraper — PAUSED

**Status**: production scraping disabled. Do **not** enable a live
fetcher against `*bids.{com,net}` hosts under the FieldBridge UA
without lifting this pause via the "Data source pivot" section in
`docs/market-intel.md`.

## Why

Discovered 2026-04-29 (Lead/Operator decision, see
`docs/agent_board.md` "STRATEGIC PIVOT" entry):

The NAPC portal robots.txt for `*.{state}bids.com|.net` ends with:

```
User-agent: *
Disallow: /
```

…after a curated allowlist of ~21 named search-engine UAs (Googlebot,
Bingbot, Applebot, etc.). `FieldBridge-Research/1.0` is **not** on that
allowlist, so under standard robots.txt semantics any URL on those
hosts is disallowed for our UA. The robots.txt also opens with a
human-language comment — *"Crawling this site is prohibited. Ignoring
this message may make you subject to legal prosecution."* — which is
not a machine-readable rule but signals the operator's intent.

Combined with the `docs/market-intel.md` Risk-flags clause *"Do not
relax these settings without a real reason"*, the engineering decision
is: don't scrape NAPC under our current UA. Three options were
considered:

| Option | Decision |
|---|---|
| **A.** Pivot to state-DOT bid tabs as the v1.5 primary source | **CHOSEN** for the scraper path. State DOTs publish bid tabs under transparency mandates and are robots-permitted by design. Idaho Transportation Department (`itd.idaho.gov`) lands first in `scrapers/state_dot/itd.py`. |
| **B.** Document a one-time fixture-capture override for NAPC | **REJECTED.** Even one-time. The design doc's "real reason" bar isn't met by "we want fixtures," and an override sets a bad precedent. Exposes us legally, technically, and ethically. |
| **C.** Reach out to NAPC for a sanctioned UA / data partnership | **PARALLEL** Lead/Operator track. Decoupled from this branch's slices. Doesn't gate any worker. |

Full rationale + decision matrix: `docs/market-intel.md` -> "Data
source pivot".

## What stays in this directory

- `registry.py` — the 50-state portal probe (`run_napc_probe.py` /
  `state_portal_registry.json`). **Still useful intelligence**: the
  registry tells us where each state's NAPC portal lives, which is
  worth knowing whether or not we crawl it. Re-running the probe
  remains permitted — it's a single GET per host on the public apex,
  and apex liveness is not "crawling" in the sense robots.txt is
  trying to deter.
- This file.

## What is NOT to be added without lifting the pause

- A concrete `Fetcher` (HTTP GETter for individual posts).
- A `parsers/bid_post.py` against captured-from-NAPC HTML fixtures.
- Any `pipeline.py` that reads NAPC URLs for ingestion.

## Lifting the pause

If/when option C succeeds (NAPC grants an explicit UA allowlist
entry, or offers a data-partnership feed), the pause-lift checklist:

1. Update `docs/market-intel.md` "Data source pivot" with the
   sanctioned-UA / partnership terms.
2. Re-run `scripts/run_napc_probe.py` to refresh
   `state_portal_registry.json`.
3. Build a Fetcher that uses the sanctioned UA and respects whatever
   rate limits NAPC stipulates.
4. Build `parsers/bid_post.py` against captured HTML fixtures (live
   capture under the sanctioned UA is now permitted).
5. Wire the network into the pipeline orchestrator alongside
   `state_dot/*` — the canonical `ParsedBidPost` shape from
   `scrapers/_base.py` makes this a drop-in.

Until those steps are explicit and signed off, this directory does
not get a live HTTP path.
