# PROPOSED CHANGES — Tests/CI Worker Stream

**From**: Lead Agent
**Date**: 2026-04-27
**Priority**: High (silent-failure risk)

## Summary

GitHub Actions is **not running CI** on any commit to this repo. The
workflow file at `fieldbridge/.github/workflows/ci.yml` is inert because
GitHub only registers workflows from `.github/workflows/` at the **repo
root** — not from subdirectories. Confirmed via:

```
$ gh api repos/skylerseeg/fieldbridge_repo/actions/workflows/ci.yml
HTTP 404: Not Found

$ gh workflow list
Dependabot Updates    active
Dependency Graph      active
# (no CI workflow registered)
```

Every backend commit has been merging without lint, typecheck, or
pytest verification. The "Healthy" status for the Tests/CI stream on
the agent_board is therefore wrong on the *enforcement* axis even
though the local test suite is genuinely green.

## What we need

Wire the existing `fieldbridge/.github/workflows/ci.yml` so GitHub
actually runs it on push to `main`/`master` and to `claude/**` branches.
Two options — pick whichever you prefer:

**Option 1 — Move it (smallest diff).** `git mv
fieldbridge/.github/workflows/ci.yml .github/workflows/ci.yml` and
adjust the `defaults.run.working-directory: fieldbridge` already in
the workflow (it's already correct — paths inside the file already
include the `fieldbridge/` prefix where needed).

**Option 2 — Thin root forwarder.** Add `.github/workflows/ci.yml` at
the repo root that just `uses: ./.github/workflows/backend.yml` style
delegation. More indirection; not recommended unless we need different
entry points.

## Acceptance criteria

- `gh workflow list` shows the `CI` workflow
- A push to a `claude/**` branch triggers it
- It runs `backend-lint` (ruff), `backend-test` (pytest), and any
  frontend jobs already declared in the file
- Branch protection rules can target it for required-status-check
  enforcement (separate, follow-on infra task — flag in agent_board)

## Why this isn't the Lead Agent's job

The Lead Agent owns `app/main.py`, `app/core/*`, `app/models/*`, the
mart registry, and frontend integration. CI workflow plumbing lives
in `.github/` and is the Tests/CI Worker's stream per `agent_board.md`.
Filing this here so the next Tests/CI session picks it up.

## Impact on current work

The Lead Agent is proceeding with Steps 1-4 of the env-loader +
predictive_maintenance landings using **local pytest green** as the
verification gate (full unit suite ran to exit 0 immediately before
the `13cdcb3` env-loader commit; new `tests/unit/test_config.py` 3/3
passing). Each subsequent step in that sequence is verified the same
way. agent_board.md will record the gap in its Step 4 update.
