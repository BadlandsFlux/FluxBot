"""Async REST client for the Fluxer HTTP API.

Points at `FLUXER_API_BASE` from config, so pointing this whole bot at
a self-hosted instance is just an env var change — nothing here is
hardcoded to the official api.fluxer.app instance.

NOTE ON ENDPOINT COVERAGE: Fluxer's own published API reference is
still being filled in as of mid-2026, and moderation-action routes
(ban/timeout/purge in particular) aren't fully documented yet. The
paths below follow the conventions Fluxer already confirms elsewhere
(guild bans, audit logs, member management). If your instance's
OpenAPI spec (usually served at `<api_base>/openapi.json` or visible
via the instance's own /api-reference page) disagrees with a path
here, that's the source of truth — update the method in question.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import aiohttp

from common.config import config


class FluxerAPIError(RuntimeError):
    def __init__(self, status: int, method: str, path: str, body: Any):
        self.status = status
        self.method = method
        self.path = path
        self.body = body
        super().__init__(f"{method} {path} -> HTTP {status}: {body}")


class FluxerREST:
    def __init__(self, token: str, base_url: Optional[str] = None, gateway_url: Optional[str] = None):
        self.token = token
        self.base_url = (base_url or config.api_base).rstrip("/")
        # If FLUXER_GATEWAY_URL is set (common for self-hosted instances
        # that don't expose GET /gateway/bot, or to pin a specific
        # region/shard), skip discovery and connect straight to it.
        self.gateway_url_hint = gateway_url or (config.gateway_url or None)
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "FluxerREST":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bot {self.token}",
                    "User-Agent": f"{config.bot_name} (https://github.com/your-org/fluxbot, 0.1)",
                }
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def request(self, method: str, path: str, *, json: Any = None,
                       params: Optional[dict] = None, retries: int = 3) -> Any:
        if self._session is None:
            await self.start()
        url = f"{self.base_url}{path}"
        for attempt in range(retries):
            async with self._session.request(method, url, json=json, params=params) as resp:
                if resp.status == 429:
                    body = await resp.json(content_type=None)
                    retry_after = float(body.get("retry_after", 1.0)) if isinstance(body, dict) else 1.0
                    await asyncio.sleep(retry_after)
                    continue
                if resp.status >= 400:
                    body = await resp.text()
                    raise FluxerAPIError(resp.status, method, path, body)
                if resp.status == 204:
                    return None
                return await resp.json(content_type=None)
        raise FluxerAPIError(429, method, path, "rate limited too many times")

    # ---------------------------------------------------------- gateway --
    async def get_gateway_bot(self) -> dict:
        return await self.request("GET", "/gateway/bot")

    # ------------------------------------------------------------- self --
    async def get_current_user(self) -> dict:
        return await self.request("GET", "/users/@me")

    # ----------------------------------------------------------- guilds --
    async def get_guild(self, guild_id: str) -> dict:
        return await self.request("GET", f"/guilds/{guild_id}")

    async def get_guild_member(self, guild_id: str, user_id: str) -> dict:
        return await self.request("GET", f"/guilds/{guild_id}/members/{user_id}")

    async def list_guild_members(self, guild_id: str, limit: int = 100) -> list:
        return await self.request("GET", f"/guilds/{guild_id}/members", params={"limit": limit})

    # ------------------------------------------------------- moderation --
    async def kick_member(self, guild_id: str, user_id: str, reason: str = "") -> None:
        await self.request(
            "DELETE", f"/guilds/{guild_id}/members/{user_id}",
            json={"reason": reason} if reason else None,
        )

    async def ban_member(self, guild_id: str, user_id: str, reason: str = "",
                          delete_message_seconds: int = 0) -> None:
        await self.request(
            "PUT", f"/guilds/{guild_id}/bans/{user_id}",
            json={"reason": reason, "delete_message_seconds": delete_message_seconds},
        )

    async def unban_member(self, guild_id: str, user_id: str, reason: str = "") -> None:
        await self.request(
            "DELETE", f"/guilds/{guild_id}/bans/{user_id}",
            json={"reason": reason} if reason else None,
        )

    async def timeout_member(self, guild_id: str, user_id: str, until_iso: str, reason: str = "") -> None:
        await self.request(
            "PATCH", f"/guilds/{guild_id}/members/{user_id}",
            json={"communication_disabled_until": until_iso, "reason": reason},
        )

    async def remove_timeout(self, guild_id: str, user_id: str, reason: str = "") -> None:
        await self.request(
            "PATCH", f"/guilds/{guild_id}/members/{user_id}",
            json={"communication_disabled_until": None, "reason": reason},
        )

    async def add_member_role(self, guild_id: str, user_id: str, role_id: str) -> None:
        await self.request("PUT", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}")

    async def remove_member_role(self, guild_id: str, user_id: str, role_id: str) -> None:
        await self.request("DELETE", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}")

    # --------------------------------------------------------- messages --
    async def send_message(self, channel_id: str, content: Optional[str] = None,
                            embeds: Optional[list] = None) -> dict:
        payload: dict = {}
        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds
        return await self.request("POST", f"/channels/{channel_id}/messages", json=payload)

    async def edit_message(self, channel_id: str, message_id: str, content: Optional[str] = None,
                            embeds: Optional[list] = None) -> dict:
        payload: dict = {}
        if content is not None:
            payload["content"] = content
        if embeds is not None:
            payload["embeds"] = embeds
        return await self.request("PATCH", f"/channels/{channel_id}/messages/{message_id}", json=payload)

    async def delete_message(self, channel_id: str, message_id: str, reason: str = "") -> None:
        await self.request(
            "DELETE", f"/channels/{channel_id}/messages/{message_id}",
            json={"reason": reason} if reason else None,
        )

    async def bulk_delete_messages(self, channel_id: str, message_ids: list[str]) -> None:
        await self.request(
            "POST", f"/channels/{channel_id}/messages/bulk-delete",
            json={"messages": message_ids},
        )

    async def get_channel_messages(self, channel_id: str, limit: int = 50,
                                    before: Optional[str] = None) -> list:
        params = {"limit": limit}
        if before:
            params["before"] = before
        return await self.request("GET", f"/channels/{channel_id}/messages", params=params)

    async def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> None:
        await self.request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me")
