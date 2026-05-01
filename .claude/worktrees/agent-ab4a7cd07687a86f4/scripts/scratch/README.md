# scripts/scratch/

Local-only scratchpad for throwaway debug/exploration scripts.

This directory and the patterns below are listed in `.gitignore` and will
**never** be committed:

- `scripts/scratch/**` — anything inside this folder
- `*.scratch.py`, `*.scratch.ts`, `*.scratch.js`, `*.scratch.sh` — anywhere in the repo

Use this for one-off `pyodbc` connection probes, ad-hoc Vista queries, copy-paste
REPL experiments, "does this Anthropic call shape work?" tests, and the like.

## When NOT to use scratch

If a script becomes useful enough to keep, promote it:

- Reusable connection / introspection logic → `backend/app/core/tenant.py`
  (`test_vista_connection`, `test_vista_api`, etc.)
- Repeatable maintenance jobs → `workers/cron_jobs/`
- One-shot data migrations / seeds → `backend/app/core/seed.py` or a new
  `backend/scripts/` module that ships with the repo

## Why this exists

We had a `dbc.py` debug script committed to repo root that read Vista SQL
creds from `.env` and dumped database names. The credentials were never
hardcoded (good), but a throwaway debug script in repo root is noise —
and the next one might not be so careful with secrets. This directory
gives that work a home that's invisible to git.
