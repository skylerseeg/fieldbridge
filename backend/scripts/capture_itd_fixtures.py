"""Operator tool: capture ITD bid-tab abstract PDFs as test fixtures.

One-time-per-quarter-ish job. Fetches a configurable number of bid
abstracts (30 by default) from
``https://apps.itd.idaho.gov/apps/contractors/abst*.pdf`` and writes
them to ``backend/tests/fixtures/itd/`` along with a ``MANIFEST.json``.

Run from ``backend/``::

    python scripts/capture_itd_fixtures.py                 # default 30
    python scripts/capture_itd_fixtures.py --count 50      # max 50
    python scripts/capture_itd_fixtures.py --dry-run       # don't write

Etiquette:

  * UA: ``FieldBridge-Research/1.0 (+https://fieldbridge.io/bot)``
  * Rate limit: 1 request per 3-6 seconds per host
  * Honors robots.txt for both ``itd.idaho.gov`` and
    ``apps.itd.idaho.gov`` before any crawl. Aborts loudly if either
    flips to disallow our UA between runs.

PII scrub policy (per Lead's slice-2 brief):

  1. Capture PDF binary unmodified.
  2. Extract text via pdfplumber; run scrub regexes on the text.
  3. Verify post-scrub: re-run the patterns; any remaining match is
     a regex bug, not a "skip this fixture" signal. Fail loudly.
  4. Document per-fixture scrub byte-count + match-counts in
     MANIFEST.json so the policy is auditable.

The PDF binaries themselves are NOT modified — they're public records,
and a parser running on them in production will re-scrub the extracted
text before any DB write. Fixtures preserve the source-of-truth.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import random
import re
import sys
import urllib.robotparser
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Bootstrap sys.path so we can import the package modules.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import httpx           # noqa: E402
import pdfplumber      # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

log = logging.getLogger("fieldbridge.market_intel.itd_capture")

USER_AGENT = "FieldBridge-Research/1.0 (+https://fieldbridge.io/bot)"
INDEX_URL = "https://itd.idaho.gov/contractor-bidding/"
RATE_LIMIT_MIN_S = 3.0
RATE_LIMIT_MAX_S = 6.0
REQUEST_TIMEOUT_S = 30.0
DEFAULT_COUNT = 30
MAX_COUNT = 50

FIXTURES_DIR = _BACKEND_ROOT / "tests" / "fixtures" / "itd"
MANIFEST_PATH = FIXTURES_DIR / "MANIFEST.json"
FIXTURES_SCHEMA_VERSION = "1"


# ---------------------------------------------------------------------------
# PII scrub patterns. Apply in order; the verify pass re-runs all of
# them and fails the run if anything remains.

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Email: standard form. Case-insensitive on TLD.
    ("email_standard", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+", re.IGNORECASE)),
    # Email obfuscated: "name at domain dot com" / "name [at] domain [dot] com"
    (
        "email_obfuscated",
        re.compile(
            r"\b[\w.+-]+\s*[\[(<]?\s*at\s*[\])>]?\s*[\w-]+\s*[\[(<]?\s*dot\s*[\])>]?\s*[\w.-]+\b",
            re.IGNORECASE,
        ),
    ),
    # International phone with country code: +1-208-555-1234, +44 20 7946 0958, etc.
    (
        "phone_international",
        re.compile(
            r"\+\d{1,3}[\s.-]?\d{1,4}[\s.-]?\d{1,4}[\s.-]?\d{1,9}",
        ),
    ),
    # NANP phone with parens: (208) 555-1234
    (
        "phone_parens",
        re.compile(r"\(\d{3}\)\s*\d{3}[-.\s]?\d{4}(?:\s*(?:x|ext\.?|extension)\s*\d{1,5})?", re.IGNORECASE),
    ),
    # NANP phone with extension: 208-555-1234 ext 123
    (
        "phone_with_ext",
        re.compile(
            r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\s*(?:x|ext\.?|extension)\s*\d{1,5}\b",
            re.IGNORECASE,
        ),
    ),
    # NANP phone bare: 208-555-1234, 208.555.1234, 208 555 1234.
    # NOTE: this also matches naive 10-digit sequences; we run it last
    # after the more specific patterns above have already consumed
    # parens/extension forms.
    (
        "phone_nanp",
        re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
    ),
)


def scrub_text(text: str) -> tuple[str, dict[str, int]]:
    """Apply all PII patterns. Return (scrubbed_text, match_counts)."""
    counts: dict[str, int] = {}
    out = text
    for name, pat in _PII_PATTERNS:
        new, n = pat.subn(f"[REDACTED:{name}]", out)
        if n:
            counts[name] = n
        out = new
    return out, counts


def verify_scrub(scrubbed: str) -> dict[str, int]:
    """Re-run patterns on scrubbed text. Any non-zero count means a
    regex bug — caller should raise. Note we deliberately exclude the
    redaction sentinel itself from the search by stripping it first."""
    sentinel_strip = re.sub(r"\[REDACTED:\w+\]", "", scrubbed)
    leaks: dict[str, int] = {}
    for name, pat in _PII_PATTERNS:
        n = len(pat.findall(sentinel_strip))
        if n:
            leaks[name] = n
    return leaks


# ---------------------------------------------------------------------------
# Robots check

def _robots_for(host_url: str) -> urllib.robotparser.RobotFileParser:
    """Sync robots.txt fetch + parse. Used at script startup so any
    block aborts loudly before we hit a real URL."""
    parsed = urlparse(host_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    # urllib's RobotFileParser uses urllib.request, not httpx, but
    # for the pre-flight check that's fine.
    rp.set_url(robots_url)
    rp.read()
    return rp


# ---------------------------------------------------------------------------
# Index discovery

async def discover_abstract_urls(client: httpx.AsyncClient, count: int) -> list[str]:
    """Fetch the contractor-bidding index page and return the first
    ``count`` ``abst*.pdf`` URLs in DOM order (presumed newest-first
    based on ITD's listing convention)."""
    log.info("fetching index %s", INDEX_URL)
    r = await client.get(INDEX_URL)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    seen: set[str] = set()
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if "abst" in h.lower() and h.lower().endswith(".pdf") and h.startswith("https://"):
            if h in seen:
                continue
            seen.add(h)
            out.append(h)
            if len(out) >= count:
                break
    log.info("found %d abstract URLs", len(out))
    return out


# ---------------------------------------------------------------------------
# Per-fixture capture

@dataclass
class FixtureRecord:
    """One row in MANIFEST.json's ``fixtures`` map."""

    filename: str
    source_url: str
    captured_at: str
    bytes_pdf: int
    sha256: str
    page_count: int
    text_chars_pre_scrub: int
    text_chars_post_scrub: int
    scrub_match_counts: dict[str, int]
    template_version: str  # 'aashtoware_v1' default; bump if a divergent shape appears
    scan_required: bool    # True if pdfplumber's first-page text extraction yielded ~0 chars


async def capture_one(
    client: httpx.AsyncClient,
    url: str,
    out_dir: Path,
    *,
    dry_run: bool,
) -> FixtureRecord:
    log.info("fetching %s", url)
    r = await client.get(url)
    r.raise_for_status()

    pdf_bytes = r.content
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    filename = Path(urlparse(url).path).name  # e.g. "abst25183.pdf"
    out_path = out_dir / filename

    # Extract text via pdfplumber.
    buf = io.BytesIO(pdf_bytes)
    full_text = []
    page_count = 0
    with pdfplumber.open(buf) as pdf:
        page_count = len(pdf.pages)
        # Cap text extraction at first 5 pages — that's enough for the
        # PII scan and the parser only needs page 1 anyway.
        for page in pdf.pages[:5]:
            full_text.append(page.extract_text() or "")
    text = "\n".join(full_text)

    scan_required = len(text.strip()) < 50  # almost-empty text layer = scanned PDF

    scrubbed, counts = scrub_text(text)
    leaks = verify_scrub(scrubbed)
    if leaks:
        # Hard fail per Lead's "strip-then-verify, NOT strip-then-skip" rule.
        raise RuntimeError(
            f"PII scrub regex bug: {filename} has {leaks} matches AFTER scrub. "
            f"Fix the regex and re-run; do not skip the fixture."
        )

    rec = FixtureRecord(
        filename=filename,
        source_url=url,
        captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        bytes_pdf=len(pdf_bytes),
        sha256=sha,
        page_count=page_count,
        text_chars_pre_scrub=len(text),
        text_chars_post_scrub=len(scrubbed),
        scrub_match_counts=counts,
        template_version="aashtoware_v1",
        scan_required=scan_required,
    )

    if not dry_run:
        out_path.write_bytes(pdf_bytes)
        log.info("wrote %s (%d bytes, %d pages)", out_path, len(pdf_bytes), page_count)

    return rec


# ---------------------------------------------------------------------------
# Runner

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--count", type=int, default=DEFAULT_COUNT,
                   help=f"how many abstracts to capture (max {MAX_COUNT})")
    p.add_argument("--dry-run", action="store_true",
                   help="don't write PDFs or MANIFEST")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    if args.count > MAX_COUNT:
        print(f"--count capped at {MAX_COUNT}", file=sys.stderr)
        args.count = MAX_COUNT

    # Robots pre-flight: both hosts must allow our UA.
    for host in ("https://itd.idaho.gov", "https://apps.itd.idaho.gov"):
        rp = _robots_for(host)
        # Smoke-check both the index path and the abstract path.
        for test_url in (
            f"{host}/contractor-bidding/" if "apps." not in host
            else f"{host}/apps/contractors/",
        ):
            allowed = rp.can_fetch(USER_AGENT, test_url)
            log.info("robots: %s allowed=%s", test_url, allowed)
            if not allowed:
                print(
                    f"robots.txt denies {USER_AGENT} on {test_url}; aborting capture",
                    file=sys.stderr,
                )
                return 2

    if not args.dry_run:
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    timeout = httpx.Timeout(REQUEST_TIMEOUT_S, connect=REQUEST_TIMEOUT_S)

    async with httpx.AsyncClient(
        headers=headers, timeout=timeout, follow_redirects=True,
    ) as client:
        urls = await discover_abstract_urls(client, args.count)

        # Inter-request rate limit kicks in BEFORE each fetch other than the first.
        records: list[FixtureRecord] = []
        for i, url in enumerate(urls):
            if i > 0:
                await asyncio.sleep(random.uniform(RATE_LIMIT_MIN_S, RATE_LIMIT_MAX_S))
            try:
                rec = await capture_one(client, url, FIXTURES_DIR, dry_run=args.dry_run)
            except Exception as exc:
                log.error("capture failed for %s: %s", url, exc)
                raise
            records.append(rec)

    manifest = {
        "schema_version": FIXTURES_SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent": USER_AGENT,
        "source": "itd.idaho.gov bid abstracts (AASHTOWare PDF)",
        "index_url": INDEX_URL,
        "scrub_patterns": [name for name, _ in _PII_PATTERNS],
        "fixtures": {rec.filename: asdict(rec) for rec in records},
    }

    if args.dry_run:
        json.dump(manifest, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    print(f"wrote {len(records)} fixtures + MANIFEST.json to {FIXTURES_DIR}",
          file=sys.stderr)

    flagged = [rec.filename for rec in records if rec.scan_required]
    if flagged:
        print(
            f"WARNING: {len(flagged)} fixture(s) appear to be scanned PDFs "
            f"(near-empty text layer). They are written but the parser will "
            f"skip-with-warn. v1.5b OCR fallback can target these:",
            file=sys.stderr,
        )
        for f in flagged:
            print(f"  {f}", file=sys.stderr)

    return 0


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
