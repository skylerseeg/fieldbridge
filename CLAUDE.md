# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

All application code lives in `fieldbridge/` (the repo root holds only `.claude/`, `.venv/`, and that single project tree). Run every command below from `fieldbridge/` unless noted otherwise.

```
fieldbridge/
├── backend/          FastAPI service (Python 3.12, async SQLAlchemy)
├── frontend/         Vite + React 18 + React Router + TanStack Query + Tailwind + shadcn/ui
├── agents/           Anthropic Claude agent modules (one dir per agent)
├── workers/          cron_jobs/ (Python) and n8n_flows/ (workflow JSON)
├── saas/             VANCON-internal prospect/sales tooling
├── infrastructure/   docker-compose stack (api, frontend, postgres, redis, n8n)
├── data/             CSI code lookups, Vista schema docs, webapp Excel exports
└── docs/             ARCHITECTURE.md
```

## Common Commands

### Backend (FastAPI)

```bash
cd fieldbridge/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env        # fill in real values before running anything

# Seed Postgres + create the VanCon reference tenant and admin user (run once)
python -m app.core.seed

# Dev server on :8000
uvicorn app.main:app --reload

# Tests (CI runs `pytest backend/tests/ -v` — no tests committed yet)
pytest -v
pytest path/to/test_file.py::test_name -v   # single test
```

The backend uses `pyodbc` with the Microsoft ODBC Driver 17 for SQL Server to reach Vista. On a fresh dev machine install `msodbcsql17` before `pip install pyodbc` will work.

### Frontend (Vite)

```bash
cd fieldbridge/frontend
npm install
npm run dev           # :5173, proxies /api/* to VITE_API_PROXY_TARGET (default http://localhost:8000)
npm run build         # tsc --noEmit && vite build, output in dist/
npm run lint          # eslint, strict-max-warnings=0
npm run typecheck     # tsc --noEmit
```

The dev server proxy is configured in `vite.config.ts`, so the browser hits `/api/v1/...` against `:5173` and Vite forwards to the backend — no CORS dance in dev. Prod builds read `VITE_API_URL` at build time; see `docs/auth-env.md` for the full env-var map.

### Full stack via Docker

```bash
cd fieldbridge/infrastructure/docker
docker compose up       # api, frontend, postgres, redis, n8n
```

The compose file mounts `../../.env` into both api and frontend, so the same `.env` at `fieldbridge/.env` drives everything.

### CI

`.github/workflows/ci.yml` runs pytest on push/PR with `DATABASE_URL=sqlite+aiosqlite:///./test.db` — backend code and tests must work against both Postgres (prod/dev) and SQLite (CI). Avoid Postgres-specific SQL or async driver assumptions in tests.

## Architecture — The Big Picture

FieldBridge is a **multi-tenant SaaS wrapper around Trimble Viewpoint Vista ERP** aimed at heavy-civil contractors. Three layers matter:

1. **FastAPI backend** owns the tenant DB (Postgres) and proxies/mirrors Vista data.
2. **Claude agents** under `fieldbridge/agents/*` do domain AI work (coding transactions, parsing bids, writing proposals) and are invoked from backend services.
3. **Vite + React frontend** is a thin client — all business logic lives server-side.

### Multi-tenancy model (read this before touching backend code)

- One row per customer company in `tenants` (`backend/app/models/tenant.py`). VanCon Inc. is the reference tenant with `slug="vancon"` and `tier=INTERNAL`, created by `app/core/seed.py`.
- **Every tenant stores their own Vista SQL credentials, Vista REST API key, and M365/Azure creds on the Tenant row.** Per-tenant connections are produced by `app.core.tenant.get_vista_connection_for_tenant(tenant)` — not the global settings. The global `get_vista_connection()` in `core/database.py` exists only for the single-tenant dev path and should not be used in tenant-scoped endpoints.
- Each tenant also gets an isolated ChromaDB collection (`get_chromadb_collection_name`) and Azure Blob container (`get_blob_container_name`). Preserve that isolation when adding new storage.
- `backend/app/core/config.py` holds global defaults (SECRET_KEY, pricing thresholds, admin bootstrap creds). Tenant-specific fields on `Settings` are only used by `seed.py` to populate the VanCon tenant on first boot.

### Auth

- JWT Bearer, HS256, `SECRET_KEY` from settings. Tokens carry `sub` (user_id), `tenant_id`, `role`, and `type` (`access` or `refresh`). 8-hour access, 30-day refresh.
- FastAPI dependencies in `app/core/auth.py`:
  - `get_current_user` — decodes token, loads `User`
  - `get_current_tenant` — loads the user's `Tenant`
  - `require_role("owner", "cfo", ...)` — role gate; `fieldbridge_admin` always passes
  - `require_admin()` — VANCON-Technologies-only (the operator of the SaaS)
- Roles live in `UserRole` enum (`owner`, `cfo`, `project_manager`, `superintendent`, `foreman`, `mechanic`, `ap_clerk`, `safety_officer`, `fieldbridge_admin`).

### API surface

Routes are mounted under `settings.api_v1_prefix` (`/api/v1`) in `app/main.py`. `app/api/v1/__init__.py` is the single registry — add new endpoints there. Current groupings:

- **Auth / onboarding / admin**: `/auth`, `/onboarding`, `/admin`
- **Vista Pipe (Phase 1)**: `/job-cost`, `/payroll`, `/vendors`, `/equipment`, `/assets`
- **Dollars (Phase 2)**: `/fleet`
- **Intelligence (Phase 3)**: `/dashboard`, `/bids`, `/projects`, `/media`
- **Domain**: `/safety`, `/transport`, `/notifications`
- **VANCON-internal**: `/sales`

Onboarding is a 5-step wizard; `/onboarding/step/{n}` saves credentials and `/onboarding/step/{n}/test` live-tests the connection using `app.core.tenant.test_vista_connection` / `test_vista_api`.

### Services layer (`backend/app/services/*`)

Each subpackage is a bounded service with its own README. Keep the boundaries from `docs/ARCHITECTURE.md`:

| Service | Owns | May call |
|---|---|---|
| `email_bridge` | M365 OAuth, email parse, CSI inference | `vista_sync` (write) |
| `vista_sync` | Vista SQL read + REST write | — |
| `bid_intelligence` | PDF parse, BOM extraction | `email_bridge`, agents |
| `project_memory` | ChromaDB vector store | — |
| `proposal_engine` | Section drafting + assembly | `project_memory`, `media_library` |
| `media_library` | Azure Blob, tagging index | `media_agent` |
| `metering` | Records Claude token usage into `usage_events` | — |

**Vista SQL is read-only.** All writes go through the Vista REST API or CSV import — this is a hard rule from `docs/ARCHITECTURE.md`. Do not add write paths to `vista_sync` that target SQL directly.

### Agents (`fieldbridge/agents/*`)

Each agent directory exports an `agent.py` that talks to `anthropic.Anthropic()` directly. Established conventions, follow them for new agents:

- Default `MODEL = "claude-sonnet-4-20250514"`.
- Use **tool_use with `tool_choice={"type": "tool", "name": ...}`** to force structured JSON output; don't parse free-form text.
- Put the system prompt in a `system=[{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}]` block so prompt caching applies.
- After every Claude call, record usage via `app.services.metering.record_usage(...)` with the agent name. Pricing constants live in `app/models/usage.py` — update them in one place when model pricing changes. The `agent` string you pass becomes the billing/attribution key.
- Agents currently import from `backend.app.services.*` (see `bid_agent/agent.py`), so they must run with the repo root on `sys.path` (see `workers/cron_jobs/supplier_enrichment_job.py` for the pattern).

### Frontend

- Vite + React Router v6 (`src/routes/`, `src/pages/`, `src/modules/`), TanStack Query + Zustand for state, Recharts for charts, `lucide-react` for icons, shadcn/ui primitives (hand-rolled in `src/components/ui/`) over Tailwind.
- `src/lib/api.ts` is the single axios instance. It reads `VITE_API_URL` (empty in dev → hits the Vite proxy on `:5173`), attaches `Bearer ${localStorage.fb_token}` on every request, and silently refreshes on 401 via `POST /auth/refresh`. Use this instead of instantiating new axios clients.
- `src/lib/auth.ts` is the Zustand auth store. Three login paths (`devLogin`, `loginWithAzure`, `loginWithPassword`) all funnel into the same `setSession(accessToken, refreshToken, user)`. See `docs/auth-env.md` for the Azure/M365 env-var setup.

## Conventions

- **Python style**: async SQLAlchemy 2.0 (`Mapped[...]`, `mapped_column`), Pydantic v2 models, FastAPI dependency injection (`Depends(...)`). Router modules name their router `router` (a plain `APIRouter()`) and are wired in `api/v1/__init__.py`.
- **IDs**: UUID4 as `String(36)` primary keys (see `Tenant`, `User`, `UsageEvent`).
- **Env loading**: `pydantic-settings` reads `.env`; fields on `Settings` correspond 1:1 to uppercase env vars. Add new config there, not via `os.getenv`.
- **CORS**: allowed origin is hardcoded to `http://localhost:3000` in `main.py`. In dev this is unused — the Vite dev server on `:5173` proxies `/api/*` to the backend, so the browser origin and API origin match. The value still needs updating before deployed frontends hit the backend directly (no proxy).
- **Never commit `.env`**. `.env.example` is the template; Vista/Azure credentials go into real `.env` files or (prod) Azure Key Vault.
- **Pricing tiers** are enforced off `Tenant.tier` (`starter` ≤25 units, `growth` 26–100, `enterprise` 100+, `internal` for VanCon). `Tenant.monthly_price` is the source of truth.

## Data reference

- `data/vista_schemas/*.md` — documented Vista tables (`apvend`, `emem`, `emwo`). Consult these before writing any query against Vista.
- `data/csi_codes/vista_csi_*.csv` — CSI code lookup tables used by `email_bridge` and coding agents.
- `data/vista_data/*.xlsx` — Excel exports from the legacy VanCon WebApp / Vista mirror, used as the canonical ingest source for the `mart_*` tables until the live Vista REST/SQL pipeline is wired. Renamed from `data_from_webapp/` on 2026-04-28.

## Git workflow

Designated development branch for this environment: **`claude/add-claude-documentation-lWsiM`**. Develop, commit, and push to this branch; do not push elsewhere without explicit permission.
