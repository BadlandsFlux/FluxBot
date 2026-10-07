"""Client for Fluxer's Admin API (docs.fluxer.app/admin-api), used only
by the dashboard to surface platform-level health, never by the bot
itself. Authenticates with `Authorization: Admin <key>`, a different
scheme than FluxerREST's `Bot <token>` (see bot/rest.py); Fluxer only
accepts the Admin scheme on paths under /v1/admin.

FLUXER_ADMIN_API_KEY is optional: get_gateway_stats() returns None when
it's unset, so a self-hosted instance that doesn't configure (or can't
generate, it needs instance-staff access) an admin key just doesn't
show this feature, rather than failing.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import aiohttp

from common.config import config

log = logging.getLogger(__name__)

# The gateway stats endpoint is documented as "live state" (consecutive
# reads can differ without administrative action) and rate-limited to
# 200 requests/minute per authenticated caller. This is global data, not
# per-guild, so every open dashboard tab sharing one cached read instead
# of each triggering its own fetch keeps well under that limit.
_CACHE_TTL_SECONDS = 20
_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}


async def _fetch() -> dict:
    url = f"{config.api_base}/admin/gateway/stats"
    headers = {"Authorization": f"Admin {config.fluxer_admin_api_key}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"GET /admin/gateway/stats -> HTTP {resp.status}")
            return await resp.json()


async def get_gateway_stats() -> Optional[dict]:
    """The Node Statistics Object from GET /admin/gateway/stats, or None
    if FLUXER_ADMIN_API_KEY isn't configured. A transient failure (bad
    key, network error, rate limit) never raises, since Fluxer platform
    health is supplementary info that shouldn't break a guild's Overview
    page or the Fluxer Status page; it's reported back as
    {"status": "unknown"} instead, distinct from the None/"not
    configured" case.
    """
    if not config.fluxer_admin_api_key:
        return None

    now = time.monotonic()
    if _cache["data"] is not None and (now - _cache["fetched_at"]) < _CACHE_TTL_SECONDS:
        return _cache["data"]

    try:
        data = await _fetch()
    except Exception:
        log.warning("Fluxer admin gateway stats request failed", exc_info=True)
        data = {"status": "unknown"}

    _cache["data"] = data
    _cache["fetched_at"] = now
    return data
