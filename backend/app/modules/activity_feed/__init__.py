"""Activity Feed module — cross-source event stream.

Merges ``ingest_log``, ``usage_events``, and ``llm_insights`` into a
single severity-ranked timeline. No mart of its own.
"""
from app.modules.activity_feed.router import router

__all__ = ["router"]
