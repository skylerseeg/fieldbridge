# Auth environment variables

Microsoft 365 SSO landed in the Vite frontend rewrite (Commits 3–4 of
the migration). The agent permission policy (`.claude/settings.json`)
forbids edits to `.env*` files, so this doc tells you which lines to
add manually.

All of the values live in the Azure portal under **App registrations →
(your SPA app) → Overview**.

## Backend — `fieldbridge/.env`

Three fields already exist on `Settings` (`backend/app/core/config.py`)
but ship empty. Populate them:

```dotenv
AZURE_TENANT_ID=<Directory (tenant) ID>
AZURE_CLIENT_ID=<Application (client) ID of the SPA app registration>
# Only used if we ever add a confidential-client flow. Leave empty for
# pure SPA + backend ID-token verification.
AZURE_CLIENT_SECRET=
```

Consumed by `backend/app/api/v1/endpoints/_azure_verify.py` to verify
the RS256 signature on every inbound ID token against
`https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys`.

## Frontend — `fieldbridge/frontend/.env.local`

Vite only exposes variables prefixed with `VITE_` to the browser
bundle, so the names differ from the backend:

```dotenv
VITE_AZURE_CLIENT_ID=<same Application (client) ID as AZURE_CLIENT_ID>
VITE_AZURE_TENANT_ID=<same Directory (tenant) ID as AZURE_TENANT_ID>
# Optional. Defaults to window.location.origin (e.g. http://localhost:5173).
# Must match a "Single-page application" redirect URI on the Azure app
# registration or MSAL will refuse to return.
VITE_AZURE_REDIRECT_URI=http://localhost:5173

# Points the SPA at the FastAPI origin. Leave empty in dev — Vite proxies
# /api/* to VITE_API_PROXY_TARGET (default http://localhost:8000). In prod
# set this to the deployed backend origin.
VITE_API_URL=
```

## Azure portal checklist

1. **App registrations → New registration** — name it `FieldBridge SPA`.
2. **Supported account types** — "Accounts in this organizational
   directory only (single-tenant)". Matches the `tid` pin in
   `_azure_verify.py`.
3. **Redirect URI** — choose **Single-page application (SPA)** and add
   each origin you'll serve from:
   - `http://localhost:5173` (Vite dev)
   - `https://<your-prod-domain>` (prod)
4. **Authentication → Implicit grant and hybrid flows** — leave both
   boxes unchecked. MSAL uses PKCE, not implicit.
5. **Token configuration → Optional claims → ID → email** — add it so
   work/school accounts return an `email` claim (otherwise we fall back
   to `preferred_username`).
6. Copy **Application (client) ID** and **Directory (tenant) ID** to the
   two `.env` files above.

## Sanity check

With both `.env` files populated, bring up the backend + Vite, then from
the SPA's browser console:

```js
// After clicking "Sign in with Microsoft" in the login page:
localStorage.getItem("fb_token")    // → non-empty FieldBridge access JWT
localStorage.getItem("fb_refresh")  // → non-empty refresh JWT
localStorage.getItem("fb_user")     // → JSON with tenant + role
```

401s on subsequent API calls trigger a silent `/auth/refresh` via the
axios interceptor in `src/lib/api.ts`. A 401 on `/auth/refresh` itself
clears the session and redirects to `/login`.

## Seeding an email/password for an existing admin

Commit 4 adds an email/password form alongside Microsoft SSO. The
backend endpoint (`POST /auth/login`) has been there since day one,
but `app/core/seed.py` creates the VanCon admin with an empty
`hashed_password` and the agent policy (`.claude/settings.json`) forbids
editing that seed script. Set an initial password manually once:

### Option A — use the backend helper (recommended)

From `fieldbridge/backend` with the venv active:

```bash
python - <<'PY'
import asyncio
from sqlalchemy import select
from app.core.auth import hash_password
from app.core.database import async_session_maker
from app.models.user import User

EMAIL = "sseegmiller@wedigutah.com"
NEW_PASSWORD = "replace-me-please"

async def main():
    async with async_session_maker() as db:
        user = (await db.execute(
            select(User).where(User.email == EMAIL)
        )).scalar_one()
        user.hashed_password = hash_password(NEW_PASSWORD)
        await db.commit()
        print(f"Updated {user.email}")

asyncio.run(main())
PY
```

This uses `hash_password` (bcrypt via passlib), so the resulting value
is byte-identical to what `/auth/register` would produce.

### Option B — raw SQL

If you'd rather not run Python, generate the hash once and then UPDATE:

```bash
python -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('replace-me-please'))"
# copy the output, then in psql:
```

```sql
UPDATE users
SET hashed_password = '<paste $2b$12$... here>'
WHERE email = 'sseegmiller@wedigutah.com';
```

### Sanity check

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"sseegmiller@wedigutah.com","password":"replace-me-please"}' \
  | jq '.access_token | length'
# → a three-digit number (JWT length). 401 means the hash didn't take.
```

Same flow works for any additional users — `/auth/register` creates a
new tenant+owner pair, but adding a second user to an existing tenant
currently needs an INSERT until the admin user-management UI lands.
