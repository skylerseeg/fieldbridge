"""NAPC ``{state}bids.{com,net}`` portal scrapers.

Risk-flagged areas (full design: ``docs/market-intel.md``):

  * NAPC's contractor directory pages (``/directory/*``) are out of
    scope. Only bid-event pages are crawled.
  * Robots.txt is honored at fetch time. The registry probe is HEAD on
    the apex only — no robots fetch needed.
  * No PII (contact emails / phones) is stored, even if encountered.
"""
