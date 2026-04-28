"""Proposals module — reads ``mart_proposals`` + ``mart_proposal_line_items``.

``mart_proposals`` is a thin 4-column header per proposal (job, owner,
bid_type, county). ``mart_proposal_line_items`` carries per-competitor
fee / schedule / reference detail but currently has no foreign key
back to a specific proposal header — it's a tenant-wide competitor
pool. This module surfaces:

  - Proposal headers with derived classifications (bid-type category,
    geography tier) on `/list` + `/{proposal_id}`.
  - Aggregate line-item statistics (competitor frequency, fee ranges)
    on `/summary` + `/insights`.

Once the line-items mart grows a proper ``(job, owner, bid_type)``
linkage, the detail endpoint can attach per-proposal line items.
"""
from app.modules.proposals.router import router

__all__ = ["router"]
