"""Runtime configuration. Everything overridable via environment variables."""

import os

UNET_URL = os.environ.get("UNET_URL", "http://localhost:8001")
SERVICENOW_URL = os.environ.get("SERVICENOW_URL", "http://localhost:8002")
UIPATH_URL = os.environ.get("UIPATH_URL", "http://localhost:8003")

# Postgres in docker compose; SQLite fallback for bare local runs and CI
LEDGER_DB_URL = os.environ.get("LEDGER_DB_URL", "sqlite:///ledger.db")

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
