"""Abstract base classes + canonical output dataclasses for bid-network
scrapers.

These are signatures + types, not concrete implementations. Each
network's concrete parser (``napc_network``, ``state_dot/itd``, future
``state_dot/udot``…) lives in its own subpackage and produces
``ParsedBidPost`` instances, which the pipeline orchestrator (slice 4)
maps onto ``BidEvent`` + ``BidResult`` ORM rows.

Four contracts in this module:

    FetchedDocument — output of a fetch (HTML or PDF bytes).
    ParsedBidder    — one bidder on a post. Pure data.
    ParsedBidPost   — one bid event + its bidder list. Pure data.
    Fetcher / PostParser / Pipeline — protocol ABCs the pipeline reads.

ParsedBidPost is intentionally network-agnostic. The pipeline doesn't
know whether a post came from NAPC's HTML portal, ITD's PDF abstract,
or UDOT's Excel bid tab — it sees the same dataclass either way.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fetch output

@dataclass
class FetchedDocument:
    """Output of a successful fetch.

    ``content`` is bytes — for HTML sources it's UTF-8-encoded markup;
    for PDF sources it's the raw PDF binary. Parsers know which to
    expect and decode accordingly.
    """

    url: str
    final_url: str
    status: int
    content: bytes
    fetched_at: str  # ISO-8601 UTC
    content_type: str | None = None  # e.g. "text/html", "application/pdf"


# Backward-compat alias for the slice-1 NAPC scaffold which referenced
# FetchedPage (HTML-only). Slice 3's concrete fetcher will produce
# FetchedDocument; the alias keeps imports stable until then.
FetchedPage = FetchedDocument


# ---------------------------------------------------------------------------
# Parser output (canonical, source-agnostic)

@dataclass(frozen=True)
class ParsedBidder:
    """One bidder's submission on a single bid post.

    Maps onto ``app.models.bid_result.BidResult`` columns one-for-one.
    The pipeline orchestrator does the conversion; parsers never touch
    the ORM. Frozen so accidental mutation can't smuggle bad data into
    a DB write.
    """

    contractor_name: str
    bid_amount: float | None
    rank: int | None
    is_low_bidder: bool
    is_awarded: bool
    contractor_url: str | None = None
    # Source-network-specific contractor identifier (e.g. AASHTOWare
    # "Vendor ID" on ITD abstracts: "C0029"). Useful for canonical
    # contractor resolution downstream; ignored if missing.
    vendor_id: str | None = None
    # Free-text annotations the source flagged on this bid (e.g.
    # "Irregular Bid" on ITD). Surfaced for human review; not
    # propagated into BidResult columns.
    notes: str | None = None


@dataclass(frozen=True)
class ParsedBidPost:
    """One bid event plus its full bidder list.

    Maps onto ``app.models.bid_event.BidEvent`` (top-level) + a list of
    ``app.models.bid_result.BidResult`` rows (the ``bidders`` tuple).
    Frozen + tuple-typed bidders so accidental mutation can't slip
    through to DB write paths.
    """

    # Provenance — set by the parser from caller-supplied context
    source_url: str
    source_network: str        # 'napc' | 'state_dot_itd' | 'state_dot_udot' …
    source_state: str          # 2-letter USPS

    # Project
    project_title: str
    project_owner: str | None = None
    work_scope: str | None = None
    solicitation_id: str | None = None

    # Timeline
    bid_open_date: date | None = None
    # Open-vs-closed-vs-awarded-vs-cancelled. ITD bid abstracts are
    # always 'awarded' or 'closed' since they're post-bid. NAPC posts
    # span the full lifecycle.
    bid_status: str | None = None

    # Geography
    location_city: str | None = None
    location_county: str | None = None
    location_state: str | None = None  # 2-letter USPS, redundant with source_state but ORM-mapped

    # Bidders
    bidders: tuple[ParsedBidder, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Protocol ABCs

class Fetcher(ABC):
    """Robots-aware, rate-limited HTTP wrapper.

    Concrete subclasses MUST:
      * honor robots.txt for every host
      * self-identify as ``FieldBridge-Research/1.0 (+https://fieldbridge.io/bot)``
      * rate-limit to <= 1 request per 3-6 seconds per host
    """

    @abstractmethod
    async def fetch(self, url: str) -> FetchedDocument | None:
        """Return the fetched document, or ``None`` if blocked by
        robots, rate-limited out, or non-2xx."""


class PostParser(ABC):
    """Pure source-format → ``ParsedBidPost``. No network, no DB.

    Subclasses pick one source format (HTML for NAPC, PDF for ITD).
    Returns ``None`` when the input isn't a recognized post — never
    raises on malformed input.
    """

    @abstractmethod
    def parse(self, doc: FetchedDocument) -> ParsedBidPost | None:
        """Return the parsed post, or ``None`` if unparseable."""


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
