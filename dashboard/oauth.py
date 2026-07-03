"""OAuth2 "Login with Fluxer" flow for the dashboard.

Standard authorization_code grant:
  1. Send the user to `{web_base}/oauth2/authorize?...` with scope
     `identify guilds`.
  2. Fluxer redirects back to our /auth/callback with `?code=...`.
  3. We exchange that code for an access token at
     `POST {api_base}/oauth2/token`.
  4. We use the access token (Bearer) to call `/users/@me` and
     `/users/@me/guilds` to know who's logged in and which servers
     they can manage.

You'll need to register an OAuth2 application against your Fluxer
instance first (`POST /oauth2/applications` while authenticated as
yourself, or via the instance's developer portal if it has one) and
set FLUXER_OAUTH_CLIENT_ID / _SECRET / _REDIRECT_URI in .env. The
redirect URI you register there must match FLUXER_OAUTH_REDIRECT_URI
exactly.
"""
from __future__ import annotations

import secrets
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from common.config import config

SCOPES = "identify guilds"


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": config.oauth_client_id,
        "redirect_uri": config.oauth_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return f"{config.authorize_url}?{urlencode(params)}"


def new_state() -> str:
    return secrets.token_urlsafe(24)


async def exchange_code(code: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.oauth_redirect_uri,
        "client_id": config.oauth_client_id,
        "client_secret": config.oauth_client_secret,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            config.token_url, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_me(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{config.api_base}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_my_guilds(access_token: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{config.api_base}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


MANAGE_GUILD_BIT = 1 << 5
ADMINISTRATOR_BIT = 1 << 3


def can_manage(guild_entry: dict) -> bool:
    """Best-effort: /users/@me/guilds entries typically carry a
    `permissions` bitfield string (Discord convention) for the calling
    user in that guild. Owners can always manage."""
    if guild_entry.get("owner"):
        return True
    try:
        perms = int(guild_entry.get("permissions", 0))
    except (TypeError, ValueError):
        return False
    return bool(perms & (MANAGE_GUILD_BIT | ADMINISTRATOR_BIT))
