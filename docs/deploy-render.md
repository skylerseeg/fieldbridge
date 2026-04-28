# Deploying FieldBridge backend to Render

Operator runbook for standing up `fieldbridge-api` on Render.com. Pairs
with the Vercel-hosted frontend at `fieldbridge.vercel.app`.

> **Prerequisites:** Render account, GitHub repo connected, this branch
> contains `render.yaml`, `fieldbridge/backend/Dockerfile`, and the
> env-driven CORS in `app/core/config.py`. All three are committed in
> the same Phase-1 PR.

---

## Phase 2 — Provision

Estimated time: ~30 minutes (most of it the first Docker build).

### 1. Apply the Blueprint

1. Render dashboard → **New +** → **Blueprint**.
2. Connect the GitHub repo. Pick the branch carrying `render.yaml`
   (currently `claude/add-lan-dev-scripts`; change to `main` once the
   work merges).
3. Render parses `render.yaml`, shows you a preview of the two services
   it'll create (`fieldbridge-api` web service + `fieldbridge-db` Postgres).
   Confirm and **Apply**.

Render kicks off the first Docker build immediately. The DB provisions in
parallel (~60s); the API build takes ~5–8 min the first time because the
Microsoft ODBC layer + the Python deps haven't been cached yet.

### 2. Set the secrets

While the build is running, fill in the secret env vars in the dashboard.
**The build will succeed without these but the app will not work properly
at runtime.** Required minimum for v1 login:

| Env var | Value | Source |
|---|---|---|
| `SECRET_KEY` | A fresh 32-byte random hex string | Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ANTHROPIC_API_KEY` | Your Anthropic API key | https://console.anthropic.com → API Keys |
| `FIELDBRIDGE_ADMIN_EMAIL` | The admin user's email | Pick whatever you'll log in as |
| `FIELDBRIDGE_ADMIN_PASSWORD` | The admin user's initial password | Pick a strong one — you'll change it post-login |

**Do not reuse the dev `SECRET_KEY`.** Each environment gets a fresh key.
A leaked dev key only affects dev tokens; a leaked prod key affects every
session.

Optional for v1 (leave unset, will set when ready):

- All `VISTA_*` vars — needed only when the Trimble Data Xchange contract
  is live and you want backend code paths that touch Vista to function.
- All `AZURE_*` vars — needed only for M365 OAuth login. Password-based
  login works without them.
- `industry_benchmark_api_key`, `notification_webhook_url`, etc. — Phase 3.

### 3. Wait for first deploy to finish

Watch the build log in the Render dashboard. Two failure modes to know about:

- **`pyodbc` build error** — means the Microsoft ODBC repo install in the
  Dockerfile didn't run. Check that the `ACCEPT_EULA=Y apt-get install`
  line is intact and that Render's build environment can reach
  `packages.microsoft.com`.
- **`pip install chromadb` slow or OOM** — the Starter plan's build
  resources are tight. If the build OOMs (rare but possible), bump the
  service to `standard` plan temporarily for the build, then bump back.

Once the build is green, Render runs `uvicorn app.main:app …`. The
service is live when the `/health` endpoint returns 200 — Render
auto-detects this via the `healthCheckPath` in `render.yaml`.

### 4. Seed the VanCon tenant + admin user

The DB is empty on first deploy. Tables get created on app boot via
SQLAlchemy `Base.metadata.create_all` (fired implicitly when modules
import `app.services.excel_marts`). But there's no tenant or user yet,
so login would fail with "Reference tenant not seeded."

**Run the seed script once via Render's web shell:**

1. Render dashboard → `fieldbridge-api` service → **Shell** tab.
2. Run:
   ```
   python -m app.core.seed
   ```
3. Output should confirm one tenant (`vancon`, tier `internal`) and one
   user (the admin email you set above) created. If the script reports
   "tenant already exists", that's also fine — idempotent.

The script reads the admin email + password from the env vars set in
step 2, so it'll create the admin user with credentials you can log in
with.

### 5. Verify the service is reachable

From your laptop:

```bash
curl https://<your-render-url>/health
# → {"status":"ok","env":"production","version":"0.2.0"}
```

(`<your-render-url>` is shown in the dashboard — typically
`https://fieldbridge-api.onrender.com` unless you set a custom domain.)

If `/health` returns the JSON above, the backend is live. Move to Phase 3.

---

## Phase 3 — Wire frontend to backend (5 minutes)

1. **Vercel dashboard** → fieldbridge project → **Settings** → **Environment Variables**.
2. Add:
   - `VITE_API_URL` = `https://fieldbridge-api.onrender.com` (or your custom domain)
   - Apply to **Production** and **Preview** environments.
3. Trigger a redeploy: Vercel dashboard → **Deployments** → latest → ⋯ menu → **Redeploy**.
   - This is critical. Vite inlines env vars **at build time**, so an existing
     build will not pick up the new `VITE_API_URL` until you rebuild.
4. Wait for the redeploy (~1–2 min on Vercel).
5. Open `https://fieldbridge.vercel.app/login`, log in with the admin email/password
   from Phase 2 step 2. You should land on `/dashboard`.

If login still fails, check **DevTools → Network → the auth/login request**:

- **Still 405** → `VITE_API_URL` didn't make it into the build. Check the
  Vercel env var, then redeploy again. Confirm the URL in the request
  starts with `https://fieldbridge-api.onrender.com/api/v1/auth/login`,
  not `https://fieldbridge.vercel.app/api/v1/auth/login`.
- **CORS error** → the Vercel origin isn't in `CORS_ALLOWED_ORIGINS`.
  Update the env var on Render, redeploy the api service.
- **401 Unauthorized** → admin user wasn't seeded, or password is wrong.
  Re-run `python -m app.core.seed` from the Render shell.
- **500 Internal Server Error** → check the api service's runtime logs in
  the Render dashboard. Most common: `DATABASE_URL` not connecting (firewall
  or wrong region), or `SECRET_KEY` not set so JWT sign/verify fails.

---

## Operational notes

### Rotating SECRET_KEY

Changing `SECRET_KEY` invalidates every issued JWT. Users will need to
log in again. Plan downtime windows accordingly. Steps:
1. Generate a new key locally.
2. Update `SECRET_KEY` in the Render dashboard (env vars).
3. Render auto-redeploys when env vars change.
4. Notify users to re-login.

### Rolling back a deploy

Render keeps the previous Docker image. Dashboard → service → **Deploys**
→ pick a prior deploy → **Redeploy**. Takes ~30 seconds.

### Logs

Dashboard → service → **Logs** tab. Stream is live. Filter by severity if
the volume gets high.

### Database backups

Render automatically backs up Postgres daily at the Starter tier. Manual
snapshots are available from the database's dashboard. To restore, create
a new Postgres instance from a snapshot, swap the `DATABASE_URL` env var
on the API service to point at the new instance.

### Cost expectations

- API service (Starter): $7/mo
- Postgres (Starter, 1 GB): $7/mo
- **Total v1: $14/mo**

Bandwidth + build minutes are bundled in the plan. Expect to outgrow
Starter Postgres around 100k tenant rows or 5 GB of media-blob references
— at which point bump to Standard ($19/mo, 10 GB).

### Deploying Phase 4 (workers + redis)

When ready to ship `workers/cron_jobs/supplier_enrichment_job.py` etc.,
extend `render.yaml`:

```yaml
- type: cron
  name: fieldbridge-supplier-enrichment
  runtime: docker
  schedule: "0 */6 * * *"            # every 6 hours
  dockerfilePath: ./fieldbridge/backend/Dockerfile
  dockerContext: ./fieldbridge/backend
  dockerCommand: python -m workers.cron_jobs.supplier_enrichment_job
  envVars:
    - key: DATABASE_URL
      fromDatabase:
        name: fieldbridge-db
        property: connectionString
    # ... (same shared secrets as the web service)
```

n8n: separate service, easiest path is n8n.cloud's hosted offering. Self-hosted
n8n on Render is possible (use their official Docker image as a private web
service) but n8n's auth model + persistent storage is friction; n8n.cloud
is $20/mo and avoids it for v1.
