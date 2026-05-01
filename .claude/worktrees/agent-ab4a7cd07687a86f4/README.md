# FieldBridge

**Vista ERP + Field Operations Bridge for Heavy Civil Contractors**

Built at VanCon Inc. | Dog-food → Productize → SaaS

---

## Architecture

```
fieldbridge/
├── backend/          # FastAPI — API + service layer
│   └── app/
│       ├── api/v1/   # REST endpoints
│       ├── core/     # Config, DB, auth
│       ├── models/   # SQLAlchemy models
│       ├── schemas/  # Pydantic schemas
│       ├── services/ # Business logic modules
│       │   ├── vista_sync/        # Vista ERP read/write
│       │   ├── bid_intelligence/  # Drawing + spec parser → quote comparison
│       │   ├── project_memory/    # Searchable project experience DB
│       │   ├── proposal_engine/   # AI proposal writer
│       │   ├── design_automation/ # InDesign / media AI
│       │   ├── media_library/     # Photo/video AI tagging
│       │   └── email_bridge/      # M365 supplier enrichment
│       └── utils/
├── agents/           # Anthropic Claude agent definitions
│   ├── bid_agent/          # Material list extraction + quote comparison
│   ├── proposal_agent/     # Proposal writing assistant
│   ├── media_agent/        # Media tagging + library search
│   └── project_search_agent/ # Natural language project DB search
├── workers/          # Background jobs
│   ├── n8n_flows/    # n8n workflow JSONs
│   └── cron_jobs/    # Scheduled Python jobs
├── frontend/         # Vite + React Router + TanStack Query + Tailwind + shadcn/ui
│   └── src/
│       ├── components/
│       │   ├── ui/          # shadcn primitives (button, card, input, ...)
│       │   ├── shell/       # Sidebar, Topbar, TenantSwitcher, nav config
│       │   └── dashboard/   # PerformanceCard, FleetInsightsCard, AgentAlertsCard
│       ├── layouts/         # AppShell (sidebar + topbar + <Outlet />)
│       ├── modules/         # Per-feature page trees (home, fleet, bids, ...)
│       ├── pages/           # Standalone pages (LoginPage)
│       ├── routes/          # Router config + RequireAuth gate
│       └── lib/             # api, auth store, msal, queryClient, utils
├── agents/           # Agent prompts + tool definitions
├── infrastructure/   # Docker, K8s, Terraform
├── data/
│   ├── csi_codes/          # Vista CSI 4-digit lookup tables
│   ├── vista_schemas/      # Vista table schemas (apvend, emem, etc.)
│   └── sample_fixtures/    # Dev/test data
└── docs/             # Architecture + API docs
```

## Modules → Roadmap

| Module | v1 | v2 | v3 |
|--------|----|----|-----|
| `email_bridge` — Supplier auto-fill from M365 | ✓ | | |
| `vista_sync` — Read/write Vista SQL + REST | ✓ | ✓ | ✓ |
| `bid_intelligence` — Drawing/spec → quote comparison | | ✓ | |
| `project_memory` — Searchable project experience DB | | ✓ | |
| `proposal_engine` — AI proposal writer | | ✓ | |
| `media_library` — AI photo/video tagging + search | | | ✓ |
| `design_automation` — InDesign AI integration | | | ✓ |

## Quick Start

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # fill in your values
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Environment

Copy `.env.example` → `.env` and populate all values before running.
Never commit `.env` — it is gitignored.
