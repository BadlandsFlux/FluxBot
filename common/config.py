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
    # The `websockets` library's own default frame-size cap (1 MiB) can be
    # too small for a single GUILD_CREATE payload on a very large server
    # (many channels/roles inline in one frame), but disabling the cap
    # entirely removes protection against a malicious or compromised
    # gateway sending an oversized frame to exhaust memory. 10 MiB is
    # generous for any legitimate payload while still being a hard ceiling.
    gateway_max_message_bytes: int = int(os.getenv("FLUXER_GATEWAY_MAX_MESSAGE_BYTES", str(10 * 1024 * 1024)))

    # OAuth2 (dashboard login)
    oauth_client_id: str = os.getenv("FLUXER_OAUTH_CLIENT_ID", "")
    oauth_client_secret: str = os.getenv("FLUXER_OAUTH_CLIENT_SECRET", "")
    oauth_redirect_uri: str = os.getenv("FLUXER_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")

    # Dashboard
    session_secret: str = os.getenv("DASHBOARD_SESSION_SECRET", "dev-secret-change-me")
    # Loopback-only by default: only reachable from this machine until you
    # explicitly widen it (e.g. to 0.0.0.0 for LAN testing, or when nginx
    # runs on a different host than the dashboard). Binding to all
    # interfaces by default would mean a fresh install is reachable from
    # the network the moment it starts, before TLS/nginx/anything else is
    # set up.
    dashboard_host: str = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    dashboard_port: int = int(os.getenv("DASHBOARD_PORT", "8000"))
    # Comma-separated IPs/CIDRs uvicorn will trust X-Forwarded-* headers
    # from. Default assumes nginx runs on the same host. If your reverse
    # proxy is on a different machine, set this to its IP.
    trusted_proxy_ips: str = os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1")
    # Set to true once you're actually serving over HTTPS (e.g. behind the
    # nginx config in deploy/) so the session cookie gets the Secure flag.
    # Keep false for plain-http local development, browsers won't send a
    # Secure cookie back over http and you'd get logged out immediately.
    dashboard_cookie_secure: bool = os.getenv("DASHBOARD_COOKIE_SECURE", "false").lower() == "true"
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

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
