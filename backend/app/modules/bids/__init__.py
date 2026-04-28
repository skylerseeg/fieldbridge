"""Bids module — reads ``mart_bids_history`` (historical bid log).

Each mart row is one (job, bid_date) pair: VanCon's bid amount,
competitor range, rank, outcome flags, and a wide list of competitor
columns (bid_1_comp..bid_17_comp). This module surfaces win/loss
outcomes, margin analysis, competition density, and estimator /
bid-type performance mixes.

``mart_bids_outlook`` (pipeline of upcoming bids) feeds a single
pipeline tile on the summary. The competitors mart is currently
empty and not used.
"""
from app.modules.bids.router import router

__all__ = ["router"]
