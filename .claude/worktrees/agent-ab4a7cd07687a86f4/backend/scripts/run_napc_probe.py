"""Operator tool: probe all 50 NAPC state portals and write the registry.

Run from ``backend/`` so the sys.path bootstrap resolves correctly:

    cd backend
    python scripts/run_napc_probe.py                  # probe all + commit
    python scripts/run_napc_probe.py --states UT,ID   # probe a subset
    python scripts/run_napc_probe.py --dry-run        # don't write JSON

This is a one-time-per-quarter-ish job. It is NOT scheduled — re-run
manually when you suspect a state's portal moved, or every few months
to keep ``state_portal_registry.json`` honest.

Sanity-check after running: the 9 manually-verified portals listed
under "Registry validation" in ``docs/market-intel.md`` should come
back as ``200`` or ``3xx_resolved`` on the matching variant. Anything
else means the probe is broken (egress, headers, NAPC change) — debug
before committing the registry.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure ``backend/`` is on sys.path when invoked as ``python scripts/...``.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.market_intel.scrapers.napc_network.registry import (  # noqa: E402
    REGISTRY_JSON_PATH,
    US_STATES,
    load_registry,
    merge_with_prior,
    probe_all_states,
    write_registry,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--states",
        type=str,
        default=None,
        help="Comma-separated USPS codes; default: all 50",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the registry to stdout without writing the JSON file",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="DEBUG-level logging",
    )
    return p.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    if args.states:
        states = tuple(s.strip().upper() for s in args.states.split(",") if s.strip())
        unknown = [s for s in states if s not in US_STATES]
        if unknown:
            print(f"unknown state codes: {unknown}", file=sys.stderr)
            return 2
    else:
        states = US_STATES

    new_registry = await probe_all_states(states=states)

    prior: dict | None = None
    if REGISTRY_JSON_PATH.exists():
        try:
            prior = load_registry(REGISTRY_JSON_PATH)
        except json.JSONDecodeError as exc:
            print(
                f"warning: prior registry at {REGISTRY_JSON_PATH} is malformed "
                f"({exc}); proceeding without prior diff",
                file=sys.stderr,
            )

    # Partial re-probe support: if --states is a subset, splice the new
    # results into the prior registry's states map instead of replacing
    # the file with just the probed subset. Without this, running with
    # --states MA would clobber the other 49 states.
    if prior is not None and set(states) != set(US_STATES):
        prior_states = dict(prior.get("states", {}))
        prior_states.update(new_registry["states"])
        new_registry["states"] = prior_states
        print(
            f"partial probe: spliced {len(states)} state(s) into the "
            f"existing registry; kept {len(prior_states) - len(states)} "
            f"prior entries unchanged",
            file=sys.stderr,
        )

    merged = merge_with_prior(new_registry, prior)

    if args.dry_run:
        json.dump(merged, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    write_registry(merged, REGISTRY_JSON_PATH)
    print(f"wrote {REGISTRY_JSON_PATH}", file=sys.stderr)

    primary_count = sum(
        1 for s in merged["states"].values() if s["primary_url"]
    )
    print(
        f"probed {len(merged['states'])} states; "
        f"{primary_count} have a primary_url",
        file=sys.stderr,
    )
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
