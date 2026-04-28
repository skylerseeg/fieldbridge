from typing import Annotated
from pydantic_settings import BaseSettings, NoDecode
from pydantic import field_validator
from functools import lru_cache
from pathlib import Path

# Resolve .env locations once, by absolute path, so settings load
# correctly regardless of the process CWD.
#
# This file lives at: fieldbridge/backend/app/core/config.py
#   parents[2] -> fieldbridge/backend  (CLAUDE.md-documented dev location)
#   parents[3] -> fieldbridge          (docker-compose mount + current user setup)
#
# pydantic-settings v2 loads tuples of env files in order, with later entries
# overriding earlier ones. We put backend/.env LAST so the documented per-service
# file wins when both exist, while still picking up the repo-level file alone.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_PARENT = _BACKEND_DIR.parent
_ENV_FILES = (str(_REPO_PARENT / ".env"), str(_BACKEND_DIR / ".env"))


class Settings(BaseSettings):
    environment: str = "development"
    secret_key: str = "changeme-replace-in-production-with-32-char-random-string"

    # SaaS / multi-tenancy
    fieldbridge_admin_email: str = "admin@vancontechnologies.com"
    fieldbridge_admin_password: str = "changeme"
    vancon_tenant_slug: str = "vancon"  # reference customer slug
    api_v1_prefix: str = "/api/v1"
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    ap_mailbox: str = "ap@vanconinc.com"
    lookback_days: int = 365
    vista_sql_host: str = ""
    vista_sql_port: int = 1433
    vista_sql_db: str = ""
    vista_sql_user: str = ""
    vista_sql_password: str = ""
    vista_api_base_url: str = ""
    vista_api_key: str = ""
    database_url: str = "postgresql://fieldbridge:password@localhost:5432/fieldbridge"
    anthropic_api_key: str = ""
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "fieldbridge-media"
    output_dir: str = "./output"

    # Fleet & cost modeling
    equipment_billing_rates: str = ""  # JSON str: {"EX001": 185.0, ...}
    downtime_alert_threshold_hours: float = 4.0
    fleet_pl_overhead_pct: float = 0.15  # 15% overhead allocation

    # Safety
    safety_trir_yellow_threshold: float = 3.0
    safety_trir_red_threshold: float = 6.0
    safety_dart_yellow_threshold: float = 2.0
    safety_dart_red_threshold: float = 4.0

    # Transport
    default_lowboy_max_load_lbs: float = 48000.0
    permit_required_weight_lbs: float = 48000.0

    # Notifications
    notification_webhook_url: str = ""  # optional Teams/Slack webhook

    # Benchmarking (Phase 3)
    industry_benchmark_api_key: str = ""

    # CORS — comma-separated list of origins allowed to call the API.
    # In dev this stays "http://localhost:3000" (the Vite dev-server proxy
    # makes the production CORS dance unnecessary). In prod, set
    # CORS_ALLOWED_ORIGINS to include the Vercel frontend domain, e.g.
    #   CORS_ALLOWED_ORIGINS=https://fieldbridge.vercel.app,http://localhost:3000
    # The validator below splits comma-separated env values into a list,
    # so the env var doesn't need JSON quoting.
    # NoDecode opts this field out of pydantic-settings' default
    # JSON-parsing for env values typed as list/dict. Without it, setting
    # CORS_ALLOWED_ORIGINS=https://a.com,https://b.com would raise
    # JSONDecodeError before our validator ran. With NoDecode, the env
    # value arrives at the validator below as a raw string.
    cors_allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_csv_origins(cls, v):
        """Accept either a list (e.g. from defaults) or a comma-separated str (env)."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    class Config:
        env_file = _ENV_FILES
        # The shared fieldbridge/.env is read by backend, frontend (Vite),
        # and n8n; ignore keys that aren't part of this Settings model rather
        # than refusing to boot.
        extra = "ignore"

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
