"""Small time-formatting helpers shared across command modules.

CAVEAT on `snowflake_to_datetime`: Fluxer IDs are snowflake-shaped
(large integers, sortable by creation time), matching the Discord
convention Fluxer mirrors elsewhere, but the exact custom epoch used
isn't confirmed from public docs. This defaults to Discord's epoch
(2015-01-01T00:00:00.000Z) as the best available guess — if your
instance uses a different epoch, account-age/creation-date output
here will be off by a constant amount. Update `FLUXER_EPOCH_MS` if you
find the real value (e.g. via a self-hosted instance's source).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

FLUXER_EPOCH_MS = 1_420_070_400_000  # best-effort guess, see module docstring

DURATION_RE = re.compile(r"^(\d+)([smhdw])$", re.IGNORECASE)
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration_seconds(token: str) -> Optional[int]:
    """Parse a duration like '10m', '2h', '1d', '1w' into seconds. Returns
    None if the token doesn't match."""
    m = DURATION_RE.match(token.lower())
    if not m:
        return None
    value, unit = m.groups()
    return int(value) * DURATION_UNITS[unit]


def snowflake_to_datetime(snowflake_id: str) -> Optional[datetime]:
    try:
        idn = int(snowflake_id)
        ms = (idn >> 22) + FLUXER_EPOCH_MS
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def format_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "Unknown"
    return dt.strftime("%Y-%m-%d")
