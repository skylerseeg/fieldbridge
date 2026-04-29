# FieldBridge backend — production container.
#
# Base: Python 3.12 on Debian 12 (Bookworm) slim. Picked to match
# CLAUDE.md's documented Python version and to pair cleanly with
# Microsoft's msodbcsql17 .deb package, which targets Debian 12.
#
# This is a single-stage build for now. Once the image stabilizes we
# can split into a builder stage to drop apt build-essentials from
# the final image (~150 MB savings). Not worth the complexity until
# Render build times become annoying.
FROM python:3.12-slim-bookworm

# Pin the working directory so $PYTHONPATH math (parents[2], parents[3]
# in app/core/config.py and elsewhere) lands on consistent paths.
WORKDIR /app

# System-level dependencies. Three groups, separated for review clarity:
#   1. curl + gnupg     — needed to fetch the Microsoft signing key.
#   2. msodbcsql17 + unixodbc-dev  — Vista SQL connector. Without these,
#      pip install pyodbc fails with a missing odbc.h header.
#   3. build-essential  — fallback for any C extension that doesn't ship
#      a manylinux wheel for python 3.12 yet.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        ca-certificates \
        build-essential \
        libffi-dev \
        unixodbc-dev \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python-level dependencies. Copy requirements.txt FIRST so this layer
# only invalidates when deps change — application code edits below
# don't trigger a re-install.
#
# Build context is the REPO ROOT (see render.yaml dockerContext: .) so
# we have to path-prefix everything we copy.
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# Application code. Two trees, both required at runtime:
#   * backend/  — FastAPI app. WORKDIR drops into here so `app.main:app`
#                 resolves cleanly for uvicorn.
#   * agents/   — Anthropic Claude agent modules. 15+ endpoint files in
#                 backend/app/api/v1/endpoints/ do `from agents.*` at
#                 module load time, so this MUST be on PYTHONPATH or
#                 uvicorn crashes on import.
COPY backend /app/backend
COPY agents  /app/agents

# Excel mart source-of-truth files (28 .xlsx, ~13 MB) — used by
# `python -m app.core.ingest --tenant vancon --all` to populate the
# `mart_*` tables until live Vista SQL/REST is wired. The parents[3]
# math in app/core/ingest.py and app/services/project_memory/ resolves
# to /app/data here, matching the repo-root layout.
COPY data /app/data

# `app/*` resolves under /app/backend (cwd-relative once WORKDIR shifts);
# `agents/*` resolves under /app. Both must be on sys.path.
ENV PYTHONPATH=/app:/app/backend
WORKDIR /app/backend

# Render injects $PORT at runtime; we default to 8000 for local docker
# compose / docker run convenience. Bind 0.0.0.0 so external traffic
# reaches uvicorn.
ENV PORT=8000
EXPOSE 8000

# Run as a non-root user. Uses a fixed UID so volume mounts behave the
# same across hosts that don't share a passwd file.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin fieldbridge \
    && chown -R fieldbridge:fieldbridge /app
USER fieldbridge

# Sh -c is used so $PORT expands at runtime. uvicorn won't expand env
# vars in its CLI args otherwise.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
