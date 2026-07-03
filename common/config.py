"""Shared configuration for the bot process and the dashboard process.

Both processes load the same .env so they agree on the DB path, the
Fluxer instance to talk to, and OAuth2 credentials.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # Fluxer instance
    api_base: str = os.getenv("FLUXER_API_BASE", "https://api.fluxer.app/v1").rstrip("/")
    gateway_url: str = os.getenv("FLUXER_GATEWAY_URL", "").strip()
    web_base: str = os.getenv("FLUXER_WEB_BASE", "https://fluxer.app").rstrip("/")

    # Bot
    bot_token: str = os.getenv("FLUXER_BOT_TOKEN", "")
    bot_name: str = os.getenv("BOT_NAME", "FluxBot")
    owner_id: str = os.getenv("BOT_OWNER_ID", "")
    command_prefix: str = os.getenv("COMMAND_PREFIX", "!")
    intents: int = int(os.getenv("FLUXER_INTENTS", "3243773"))
    gateway_version: int = int(os.getenv("FLUXER_GATEWAY_VERSION", "1"))

    # OAuth2 (dashboard login)
    oauth_client_id: str = os.getenv("FLUXER_OAUTH_CLIENT_ID", "")
    oauth_client_secret: str = os.getenv("FLUXER_OAUTH_CLIENT_SECRET", "")
    oauth_redirect_uri: str = os.getenv("FLUXER_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")

    # Dashboard
    session_secret: str = os.getenv("DASHBOARD_SESSION_SECRET", "dev-secret-change-me")
    dashboard_host: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    dashboard_port: int = int(os.getenv("DASHBOARD_PORT", "8000"))

    # Storage — real Postgres service, shared by the bot process and the
    # dashboard process. e.g. postgresql://user:pass@localhost:5432/fluxerbot
    database_url: str = os.getenv("DATABASE_URL", "postgresql://fluxerbot:fluxerbot@localhost:5432/fluxerbot")
    db_pool_min: int = int(os.getenv("DB_POOL_MIN", "1"))
    db_pool_max: int = int(os.getenv("DB_POOL_MAX", "10"))

    @property
    def authorize_url(self) -> str:
        return f"{self.web_base}/oauth2/authorize"

    @property
    def token_url(self) -> str:
        return f"{self.api_base}/oauth2/token"


config = Config()
