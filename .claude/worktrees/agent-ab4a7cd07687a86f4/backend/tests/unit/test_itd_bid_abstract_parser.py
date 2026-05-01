"""Tests for ``app.services.market_intel.scrapers.state_dot.itd``.

Four test categories per the slice-2 brief:

  * **happy**: parametrize over every ``aashtoware_v1`` fixture in
    ``tests/fixtures/itd/``, assert basic structural invariants
    (title non-empty, ≥1 bidder, rank-1 is low, monotonic ranks,
    every bid_amount > 0).
  * **partial**: synthetic 1-bidder page-1 text → exactly 1 ParsedBidder
    with ``is_low_bidder=True``. No real fixture needed because all
    captured ITD posts are competitively bid (≥2 bidders).
  * **malformed**: empty bytes, non-PDF bytes, every ``itd_legacy``
    fixture (real-world template the parser must skip-with-warn) →
    returns ``None``, never raises.
  * **golden**: ``abst25183.pdf`` — full ParsedBidPost field-by-field
    assertion. Includes the Irregular-Bid notes capture and the
    multi-line vendor-name reassembly. Regression anchor.

The 30 captured fixtures split as 22 v1 + 8 legacy (per
``tests/fixtures/itd/MANIFEST.json``).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.services.market_intel.scrapers._base import (
    FetchedDocument,
    ParsedBidPost,
)
from app.services.market_intel.scrapers.state_dot import itd
from app.services.market_intel.scrapers.state_dot.itd import (
    ITDBidAbstractParser,
    parse_bid_abstract,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "itd"
MANIFEST_PATH = FIXTURES_DIR / "MANIFEST.json"


# ---------------------------------------------------------------------------
# Manifest-driven fixture splits

def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        pytest.skip(
            f"ITD fixtures not committed at {FIXTURES_DIR}; run "
            f"scripts/capture_itd_fixtures.py to generate them"
        )
    return json.loads(MANIFEST_PATH.read_text())


def _fixtures_by_template(template_version: str) -> list[str]:
    manifest = _load_manifest()
    return sorted(
        name for name, rec in manifest["fixtures"].items()
        if rec["template_version"] == template_version
    )


def _read_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


# ---------------------------------------------------------------------------
# (1) HAPPY: every v1 fixture parses to a sane ParsedBidPost

V1_FIXTURES = _fixtures_by_template("aashtoware_v1") if MANIFEST_PATH.exists() else []


@pytest.mark.parametrize("fixture_name", V1_FIXTURES)
def test_v1_fixtures_parse_with_invariants(fixture_name: str) -> None:
    pdf = _read_fixture(fixture_name)
    url = f"https://apps.itd.idaho.gov/apps/contractors/{fixture_name}"
    result = parse_bid_abstract(pdf, url)

    assert result is not None, f"{fixture_name}: parser returned None on a v1 fixture"
    assert isinstance(result, ParsedBidPost)

    # Provenance fields are caller-supplied and sourced consistently.
    assert result.source_url == url
    assert result.source_network == "state_dot_itd"
    assert result.source_state == "ID"
    assert result.location_state == "ID"
    assert result.project_owner == "Idaho Transportation Department"
    assert result.bid_status == "awarded"

    # Required fields on the ORM target.
    assert result.project_title and result.project_title.strip()
    assert result.solicitation_id and result.solicitation_id.strip()
    assert isinstance(result.bid_open_date, date)
    # Letting dates should be vaguely recent (within last ~10 years; if a
    # date parses to e.g. year 9999 we'd fail this).
    assert 2000 <= result.bid_open_date.year <= 2100

    # Bidder list invariants.
    assert len(result.bidders) >= 1, f"{fixture_name}: zero bidders"
    bidders = result.bidders

    # Ranks are 1-indexed, contiguous, monotonic.
    assert [b.rank for b in bidders] == list(range(1, len(bidders) + 1)), (
        f"{fixture_name}: ranks not contiguous from 1"
    )

    # Exactly one is_low_bidder=True, and it's the rank-1 entry.
    low_count = sum(1 for b in bidders if b.is_low_bidder)
    assert low_count == 1, f"{fixture_name}: low_count={low_count}"
    assert bidders[0].is_low_bidder is True

    # Every bid amount is > 0 and parsed as float.
    for b in bidders:
        assert b.bid_amount is not None and b.bid_amount > 0, (
            f"{fixture_name}: bidder #{b.rank} has bid_amount={b.bid_amount}"
        )
        assert b.contractor_name and b.contractor_name.strip()
        assert b.vendor_id and len(b.vendor_id) == 5  # one letter + four digits


# ---------------------------------------------------------------------------
# (2) PARTIAL: synthetic single-bidder text

def test_synthetic_single_bidder_text() -> None:
    """No captured ITD post has only 1 bidder (competitive procurement
    floor), but the parser must handle the case correctly. Construct a
    synthetic page-1 text that imitates the v1 layout with exactly one
    vendor row and assert clean parsing."""
    synthetic = """\
03/01/2026 12:00:00
AASHTOWare Project™ Version 5.03.03 Revision 039
Idaho Transportation Department
Vendor Ranking Page 1 of 1
Call Order: 1 Contract ID: 99999260101 Counties: Ada
Letting Date: March 1, 2026 2:00PM District(s): D3 DC C TestPM
Contract Time: 30 WORKING DAYS Min: Max:
Contract Description: SYNTHETIC TEST PROJECT Project(s): A099(999)
Percent Of Low
Rank Vendor ID/Name Total Bid Bid
1 T0001 SOLO BIDDER CONSTRUCTION CO. $1,234,567.89 100.00%
"""
    result = itd._parse_v1_text(synthetic, source_url="https://example.test/synthetic.pdf")
    assert result is not None
    assert result.project_title == "SYNTHETIC TEST PROJECT"
    assert result.solicitation_id == "99999260101"
    assert result.bid_open_date == date(2026, 3, 1)
    assert result.location_county == "Ada"
    assert len(result.bidders) == 1
    only = result.bidders[0]
    assert only.rank == 1
    assert only.is_low_bidder is True
    assert only.is_awarded is True
    assert only.contractor_name == "SOLO BIDDER CONSTRUCTION CO."
    assert only.vendor_id == "T0001"
    assert only.bid_amount == pytest.approx(1234567.89)
    assert only.notes is None


# ---------------------------------------------------------------------------
# (3) MALFORMED: bad inputs return None without raising

def test_empty_bytes_returns_none() -> None:
    assert parse_bid_abstract(b"", source_url="https://example.test/empty.pdf") is None


def test_non_pdf_bytes_returns_none() -> None:
    """A literal HTML page or random non-PDF blob must return None,
    not raise pdfminer/pdfplumber internals into the pipeline."""
    html = b"<!DOCTYPE html><html><body>not a pdf</body></html>"
    assert parse_bid_abstract(html, source_url="https://example.test/page.html") is None


def test_garbage_bytes_returns_none() -> None:
    assert parse_bid_abstract(b"\x00\x01\x02\x03ABC", source_url="https://example.test/junk") is None


LEGACY_FIXTURES = _fixtures_by_template("itd_legacy") if MANIFEST_PATH.exists() else []


@pytest.mark.parametrize("fixture_name", LEGACY_FIXTURES)
def test_legacy_fixtures_skip_with_none(fixture_name: str) -> None:
    """The 8 legacy 'Official Bid Abstracts' PDFs are real ITD output
    from an older AASHTOWare report template. Slice 2's parser must
    return None on them so the pipeline's fail-soft policy logs a
    warn-and-skip. v1.5b backfill targets these via the
    ``template_version`` filter in MANIFEST.json."""
    pdf = _read_fixture(fixture_name)
    url = f"https://apps.itd.idaho.gov/apps/contractors/{fixture_name}"
    result = parse_bid_abstract(pdf, url)
    assert result is None, (
        f"{fixture_name}: legacy template must return None, got {result!r}"
    )


def test_text_missing_required_field_returns_none() -> None:
    """Page-1 text that LOOKS like a v1 abstract but is missing the
    Contract ID line must return None — better to skip than to write
    a row with a NULL solicitation_id."""
    broken = """\
AASHTOWare Project Idaho Transportation Department
Vendor Ranking
Letting Date: March 1, 2026 2:00PM
Contract Description: BROKEN
Rank Vendor ID/Name Total Bid Bid
1 T0001 ONLY BIDDER $1,000.00 100.00%
"""
    assert itd._parse_v1_text(broken, source_url="https://example.test/broken") is None


# ---------------------------------------------------------------------------
# (4) GOLDEN: full field-by-field on one canonical fixture

GOLDEN_FIXTURE = "abst25183.pdf"


def test_golden_abst25183() -> None:
    """Field-by-field anchor on abst25183.pdf — chosen as canonical
    because it exercises:
      * standard 2-bidder vendor ranking
      * "Irregular Bid" annotation on rank 2 → notes captured, awarded=False
      * multi-line vendor name reassembly ("WADSWORTH BROTHERS
        CONSTRUCTION COMPANY, INC." wrapped across two lines)

    Any change to the parser that breaks this assertion is a real
    regression. If ITD updates the template and this fails legitimately,
    re-capture and update both this test AND the v1 anchor docs in
    ``itd.py``.
    """
    pdf = _read_fixture(GOLDEN_FIXTURE)
    url = f"https://apps.itd.idaho.gov/apps/contractors/{GOLDEN_FIXTURE}"
    result = parse_bid_abstract(pdf, url)

    assert result is not None

    # Top-level fields
    assert result.source_url == url
    assert result.source_network == "state_dot_itd"
    assert result.source_state == "ID"
    assert result.project_title == "I-15, RIVERTON ROAD BRIDGE"
    assert result.project_owner == "Idaho Transportation Department"
    assert result.work_scope == "I-15, RIVERTON ROAD BRIDGE"
    assert result.solicitation_id == "25183260303"
    assert result.bid_open_date == date(2026, 4, 14)
    assert result.bid_status == "awarded"
    assert result.location_county == "Bingham"
    assert result.location_state == "ID"
    assert result.location_city is None

    # Two bidders, in known order
    assert len(result.bidders) == 2

    low = result.bidders[0]
    assert low.rank == 1
    assert low.vendor_id == "C0029"
    assert low.contractor_name == "CANNON BUILDERS, INC."
    assert low.bid_amount == pytest.approx(10_500_921.46)
    assert low.is_low_bidder is True
    assert low.is_awarded is True
    assert low.notes is None

    runner_up = result.bidders[1]
    assert runner_up.rank == 2
    assert runner_up.vendor_id == "W0014"
    assert runner_up.contractor_name == "WADSWORTH BROTHERS CONSTRUCTION COMPANY, INC."
    assert runner_up.bid_amount == pytest.approx(15_677_191.36)
    assert runner_up.is_low_bidder is False
    # Irregular Bid → not awarded; notes captures the flag for audit
    assert runner_up.is_awarded is False
    assert runner_up.notes == "Irregular Bid"


# ---------------------------------------------------------------------------
# PostParser ABC adapter contract

def test_postparser_adapter_returns_parsed_or_none() -> None:
    parser = ITDBidAbstractParser()
    pdf = _read_fixture(GOLDEN_FIXTURE)
    doc = FetchedDocument(
        url=f"https://apps.itd.idaho.gov/apps/contractors/{GOLDEN_FIXTURE}",
        final_url=f"https://apps.itd.idaho.gov/apps/contractors/{GOLDEN_FIXTURE}",
        status=200,
        content=pdf,
        fetched_at="2026-04-29T00:00:00+00:00",
        content_type="application/pdf",
    )
    result = parser.parse(doc)
    assert result is not None
    assert result.solicitation_id == "25183260303"


def test_postparser_adapter_returns_none_on_garbage() -> None:
    parser = ITDBidAbstractParser()
    doc = FetchedDocument(
        url="https://example.test/junk",
        final_url="https://example.test/junk",
        status=200,
        content=b"not a pdf",
        fetched_at="2026-04-29T00:00:00+00:00",
        content_type="application/pdf",
    )
    assert parser.parse(doc) is None
