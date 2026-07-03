"""Fluxer instance discovery + media (avatar/icon) URL helpers.

Self-hosted instances expose a discovery document at
`/api/.well-known/fluxer` on the instance's web root that lists the
instance's actual service endpoints, including its media proxy
(`endpoints.media`). We fetch that once and cache it, so avatar/icon
URLs work correctly against any instance rather than hardcoding the
official one.

CAVEAT: Fluxer's media-proxy path *segments* (e.g. whether a guild
icon lives at `/icons/{guild_id}/{hash}` vs some other layout) aren't
fully confirmed from public docs at the time of writing — what *is*
confirmed is the query-parameter contract (`size`, `format`, `quality`,
`animated`) documented for the "Get user or guild avatar" / "Get guild
icon" endpoints. The path layout here follows the Discord-style
convention Fluxer's docs structure mirrors. If your instance serves
icons/avatars from a different path, update `guild_icon_url` /
`user_avatar_url` below — everything else (dashboard, bot commands)
just calls these two functions.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

from common.config import config

_media_base: Optional[str] = None
_media_base_checked_at: float = 0.0
_CACHE_TTL = 3600  # re-check discovery hourly, instances rarely change this


async def get_media_base() -> str:
    """Return the instance's media proxy base URL, cached for an hour."""
    global _media_base, _media_base_checked_at
    now = time.monotonic()
    if _media_base and (now - _media_base_checked_at) < _CACHE_TTL:
        return _media_base

    fallback = config.api_base.rsplit("/v1", 1)[0] or config.web_base
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{config.web_base}/api/.well-known/fluxer")
            resp.raise_for_status()
            data = resp.json()
            media = data.get("endpoints", {}).get("media")
            _media_base = media.rstrip("/") if media else fallback
    except Exception:
        _media_base = fallback
    _media_base_checked_at = now
    return _media_base


def guild_icon_url(media_base: str, guild_id: str, icon_hash: Optional[str],
                    size: int = 128) -> Optional[str]:
    if not icon_hash:
        return None
    return f"{media_base}/icons/{guild_id}/{icon_hash}.webp?size={size}"


def user_avatar_url(media_base: str, user_id: str, avatar_hash: Optional[str],
                     size: int = 256) -> Optional[str]:
    if not avatar_hash:
        return None
    animated = avatar_hash.startswith("a_")
    ext = "gif" if animated else "webp"
    url = f"{media_base}/avatars/{user_id}/{avatar_hash}.{ext}?size={size}"
    if animated:
        url += "&animated=true"
    return url
