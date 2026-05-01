"""State-DOT bid-tab scrapers.

State Departments of Transportation publish bid tabulations as part of
public-records transparency mandates. Unlike NAPC, these sources are
robots-permitted by design and the data is unambiguously public record.

One module per DOT. Each parses that DOT's specific bid-tab format
(PDF for ITD, mixed for UDOT/NDOT, etc.) into the canonical
``ParsedBidPost`` shape from ``scrapers/_base.py``.

Active modules:

  * ``itd``  — Idaho Transportation Department (AASHTOWare PDF abstracts)

Planned (v1.5b):

  * ``udot`` — Utah DOT
  * ``ndot`` — Nevada DOT

Why this lives alongside ``napc_network/`` instead of replacing it: see
``backend/app/services/market_intel/scrapers/napc_network/_napc_paused.md``.
"""
