"""
Central configuration for the Sense Platform API.

Portable by design: everything comes from environment variables (a .env file in
Docker), NOT AWS Secrets Manager. The platform runs with zero external services;
the AI features (embeddings + /ask) light up automatically only when the relevant
API keys are provided.
"""

import os
from functools import lru_cache
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor


# -----------------------------------------------------------------------------
# Core config
# -----------------------------------------------------------------------------
API_KEY = os.environ.get("SENSE_API_KEY", "")
SITE_NAME = os.environ.get("SITE_NAME", "Sense Platform")

# Comma-separated list of allowed CORS origins. "*" allows all (fine for a
# single-origin self-host where the dashboard is served by this same app).
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]

DEFAULT_TIMEZONE = os.environ.get("DEFAULT_TIMEZONE", "Australia/Brisbane")

# Directory holding the static dashboard (index.html). Served same-origin by
# the API so there's no CORS and no separate web host to run.
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", "/srv/frontend"))

# -----------------------------------------------------------------------------
# Database — DATABASE_URL wins; otherwise assemble from PG* parts.
# sslmode defaults to "disable" (local Docker network); set DB_SSLMODE=require
# when pointing at a managed/remote Postgres.
# -----------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
_PG = {
    "host": os.environ.get("PGHOST", "db"),
    "port": os.environ.get("PGPORT", "5432"),
    "dbname": os.environ.get("PGDATABASE", "sense"),
    "user": os.environ.get("PGUSER", "sense"),
    "password": os.environ.get("PGPASSWORD", "sense"),
    "sslmode": os.environ.get("DB_SSLMODE", "disable"),
}


def get_db():
    """Open a new connection with dict-style rows."""
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return psycopg2.connect(cursor_factory=RealDictCursor, **_PG)


# -----------------------------------------------------------------------------
# AI layer — required.
#   - OPENAI_API_KEY powers reading embeddings + vector search.
#   - ANTHROPIC_API_KEY powers /ask answer generation.
# Both must be set; the app fails fast on startup otherwise (see validate()).
# -----------------------------------------------------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "claude-haiku-4-5-20251001")


@lru_cache(maxsize=1)
def get_openai():
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY)


@lru_cache(maxsize=1)
def get_anthropic():
    import anthropic
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def generate_embedding(text: str) -> list[float]:
    """Return an embedding vector for the given text."""
    resp = get_openai().embeddings.create(model=EMBEDDING_MODEL, input=text)
    return resp.data[0].embedding


# -----------------------------------------------------------------------------
# Startup validation — fail fast when required configuration is missing.
# -----------------------------------------------------------------------------
class ConfigError(RuntimeError):
    """Raised when required configuration is absent."""


def validate() -> None:
    """Raise ConfigError if any required setting is missing. Run on startup."""
    required = {
        "SENSE_API_KEY": API_KEY,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ConfigError(
            "Missing required configuration: "
            + ", ".join(missing)
            + ". Set these in your .env file."
        )
