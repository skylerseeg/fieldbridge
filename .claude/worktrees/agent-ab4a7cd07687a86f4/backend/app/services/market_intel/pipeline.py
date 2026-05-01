"""Per-state ingest orchestrator for Market Intel.

Glues `Fetcher` + per-network parsers + DB writes for one state. n8n
calls ``ITDPipeline().run_state("ID", db)`` nightly; the return is a
counters dict logged into the n8n run record.

Currently implements the **state_dot/itd** path. Other networks
(NAPC paused, future UDOT/NDOT) will land as sibling Pipeline
classes here, sharing the same `_base.Pipeline` ABC contract.

Tenant scoping: every row written is tenant_id = SHARED_NETWORK_TENANT_ID
(``app.core.seed``). Per-customer reads union their tenant_id with
that sentinel — see ``docs/market-intel.md`` "Tenant scoping".

Idempotency: re-running on the same data is a no-op. The unique
constraint ``(tenant_id, source_url, raw_html_hash)`` on bid_events
gates duplicates; raw_html_hash is the sha256 of the fetched bytes.
The pipeline checks before insert and counts duplicates as
``skipped_already_ingested`` rather than letting them surface as
IntegrityErrors.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed import SHARED_NETWORK_TENANT_ID
from app.models.bid_event import BidEvent
from app.models.bid_result import BidResult
from app.services.market_intel.scrapers._base import (
    FetchedDocument,
    ParsedBidPost,
    Pipeline,
)
from app.services.market_intel.scrapers._fetcher import HttpFetcher
from app.services.market_intel.scrapers.state_dot import itd as itd_parser
from app.services.market_intel.scrapers.state_dot.itd import (
    INDEX_URL,
    PARSE_LEGACY_TEMPLATE,
    PARSE_OK,
    SOURCE_NETWORK,
    discover_idaho_abstract_urls,
    parse_bid_abstract_full,
)

log = logging.getLogger("fieldbridge.market_intel.pipeline")

# Default cap for n8n runs. Set high; ITD publishes ~187 abstracts on
# the index page so this comfortably covers a full nightly sweep.
DEFAULT_URL_LIMIT = 250


def _empty_counters() -> dict[str, int]:
    """The canonical counters dict shape. Asserted on by the e2e test
    so n8n can rely on these keys being present even on empty runs."""
    return {
        "fetched": 0,
        "parsed": 0,
        "written": 0,
        "skipped_robots": 0,
        "skipped_fetch_error": 0,
        "skipped_legacy_template": 0,
        "skipped_parse_error": 0,
        "skipped_already_ingested": 0,
        "duration_ms": 0,
    }


class ITDPipeline(Pipeline):
    """ITD bid-abstract ingest pipeline.

    Holds one ``HttpFetcher`` for the whole run — robots cache and rate
    limiter survive across all per-URL fetches, which is the entire
    point of those classes. Tests inject a mock ``HttpFetcher`` to
    bypass the network.
    """

    def __init__(
        self,
        *,
        fetcher: HttpFetcher | None = None,
        url_limit: int = DEFAULT_URL_LIMIT,
        # Test seam: the e2e test injects a deterministic clock so the
        # ``duration_ms`` counter doesn't make assertions brittle.
        clock: Any = time.monotonic,
    ) -> None:
        self._fetcher = fetcher or HttpFetcher()
        self._url_limit = url_limit
        self._clock = clock

    async def __aenter__(self) -> "ITDPipeline":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self._fetcher.aclose()

    async def run_state(self, state: str, db: AsyncSession) -> dict[str, int]:
        if state != "ID":
            raise ValueError(
                f"ITDPipeline only handles 'ID'; got {state!r}. "
                f"Add a sibling Pipeline class for other states."
            )

        counters = _empty_counters()
        t0 = self._clock()

        # 1. Fetch the index page.
        log.info("itd pipeline: fetching index %s", INDEX_URL)
        index_doc = await self._fetcher.fetch(INDEX_URL)
        if index_doc is None:
            log.warning("itd pipeline: index fetch failed; aborting run")
            counters["duration_ms"] = int((self._clock() - t0) * 1000)
            return counters

        # 2. Discover abstract URLs (DOM order, newest-first).
        index_html = index_doc.content.decode("utf-8", errors="replace")
        urls = discover_idaho_abstract_urls(
            index_html, base_url=index_doc.final_url, limit=self._url_limit,
        )
        log.info("itd pipeline: discovered %d abstract URLs", len(urls))

        # 3. For each URL: pre-check robots, fetch, parse, write.
        for url in urls:
            await self._process_one(url, db, counters)

        counters["duration_ms"] = int((self._clock() - t0) * 1000)
        log.info("itd pipeline: run complete %s", counters)
        return counters

    async def _process_one(
        self, url: str, db: AsyncSession, counters: dict[str, int],
    ) -> None:
        # Pre-check robots so we can count denials separately from
        # other fetch failures. (HttpFetcher.fetch already enforces
        # the deny — this is purely for the counter.)
        if not await self._fetcher.can_fetch(url):
            counters["skipped_robots"] += 1
            return

        doc = await self._fetcher.fetch(url)
        if doc is None:
            counters["skipped_fetch_error"] += 1
            return

        counters["fetched"] += 1

        post, status = parse_bid_abstract_full(doc.content, source_url=url)
        if status == PARSE_LEGACY_TEMPLATE:
            counters["skipped_legacy_template"] += 1
            return
        if post is None or status != PARSE_OK:
            counters["skipped_parse_error"] += 1
            return

        counters["parsed"] += 1

        # 4. Idempotency check + write.
        raw_html_hash = hashlib.sha256(doc.content).hexdigest()
        if await _event_already_ingested(db, url, raw_html_hash):
            counters["skipped_already_ingested"] += 1
            return

        await _write_bid_event(db, post, doc, raw_html_hash)
        counters["written"] += 1


# ---------------------------------------------------------------------------
# DB write helpers

async def _event_already_ingested(
    db: AsyncSession, source_url: str, raw_html_hash: str,
) -> bool:
    """Check the unique-constraint key before insert.

    The DB will reject duplicates anyway, but a pre-check lets us
    count them cleanly without raising IntegrityError at commit
    time (which would also abort any sibling writes in the same
    transaction)."""
    stmt = select(BidEvent.id).where(
        BidEvent.tenant_id == SHARED_NETWORK_TENANT_ID,
        BidEvent.source_url == source_url,
        BidEvent.raw_html_hash == raw_html_hash,
    ).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _write_bid_event(
    db: AsyncSession,
    post: ParsedBidPost,
    doc: FetchedDocument,
    raw_html_hash: str,
) -> None:
    """Write one BidEvent + N BidResults under SHARED_NETWORK_TENANT_ID."""
    event = BidEvent(
        tenant_id=SHARED_NETWORK_TENANT_ID,
        source_url=doc.url,
        source_state=post.source_state,
        source_network=post.source_network,
        solicitation_id=post.solicitation_id,
        raw_html_hash=raw_html_hash,
        project_title=post.project_title,
        project_owner=post.project_owner,
        work_scope=post.work_scope,
        # csi_codes is filled in by a later normalizer pass (slice 4b /
        # v1.5b). Parser doesn't infer; we leave it null here.
        csi_codes=None,
        bid_open_date=post.bid_open_date,
        bid_status=post.bid_status,
        location_city=post.location_city,
        location_county=post.location_county,
        location_state=post.location_state,
    )
    db.add(event)
    # Flush so event.id is assigned before we wire children.
    await db.flush()

    for bidder in post.bidders:
        db.add(
            BidResult(
                tenant_id=SHARED_NETWORK_TENANT_ID,
                bid_event_id=event.id,
                contractor_name=bidder.contractor_name,
                contractor_url=bidder.contractor_url,
                bid_amount=bidder.bid_amount,
                is_low_bidder=bidder.is_low_bidder,
                is_awarded=bidder.is_awarded,
                rank=bidder.rank,
            )
        )

    await db.commit()
