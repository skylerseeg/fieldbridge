"""Abstract base classes for bid-network scrapers.

These are signatures, not implementations. The first concrete
implementation lands in the next slice — this module exists so the
``scrapers/`` package has its contract documented before the NAPC
fetcher and parsers are written.

Three contracts:

    Fetcher    — robots-aware, rate-limited HTTP. Wraps httpx.
    PostParser — pure HTML → structured rows. No I/O.
    Pipeline   — orchestrates Fetcher + PostParser + DB write for a
                 single (network, state) tuple.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class FetchedPage:
    """Output of a successful fetch. Inputs to a PostParser."""

    url: str
    final_url: str
    status: int
    html: str
    fetched_at: str  # ISO-8601 UTC


class Fetcher(ABC):
    """Robots-aware, rate-limited HTTP wrapper.

    Concrete subclasses MUST:
      * honor robots.txt for every host
      * self-identify as ``FieldBridge-Research/1.0 (+https://fieldbridge.io/bot)``
      * rate-limit to <= 1 request per 3-6 seconds per host
    """

    @abstractmethod
    async def fetch(self, url: str) -> FetchedPage | None:
        """Return the fetched page, or ``None`` if blocked by robots,
        rate-limited out, or non-2xx."""


class PostParser(ABC):
    """Pure HTML -> structured rows. No network, no DB.

    The output shape is intentionally permissive at this layer; the
    pipeline maps it onto ``BidEvent`` + ``BidResult`` columns. Keeping
    the parser model-agnostic means we can change ORM column names
    without touching parser code."""

    @abstractmethod
    def parse(self, page: FetchedPage) -> dict[str, Any] | None:
        """Return a dict with at least ``bid_event`` and ``bid_results``
        keys, or ``None`` if the page isn't a recognized post."""


class Pipeline(ABC):
    """Orchestrate Fetcher + PostParser + DB write for one state.

    Always writes under ``SHARED_NETWORK_TENANT_ID``. The state-by-state
    split keeps n8n cron staggering simple — one job per state, one
    pipeline per job."""

    @abstractmethod
    async def run_state(self, state: str, db: "AsyncSession") -> dict[str, int]:
        """Execute the full ingest for ``state``. Return a counters
        dict (e.g. ``{"fetched": 12, "parsed": 11, "written": 11}``)
        for n8n logging."""
