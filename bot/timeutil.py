"""Small time-formatting helpers shared across command modules.

CAVEAT on `snowflake_to_datetime`: Fluxer IDs are snowflake-shaped
(large integers, sortable by creation time), matching the Discord
convention Fluxer mirrors elsewhere, but the exact custom epoch used
isn't confirmed from public docs. This defaults to Discord's epoch
(2015-01-01T00:00:00.000Z) as the best available guess, if your
instance uses a different epoch, account-age/creation-date output
here will be off by a constant amount. Update `FLUXER_EPOCH_MS` if you
find the real value (e.g. via a self-hosted instance's source).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import parsedatetime

FLUXER_EPOCH_MS = 1_420_070_400_000  # best-effort guess, see module docstring

DURATION_RE = re.compile(r"^(\d+)([smhdw])$", re.IGNORECASE)
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

_NLP_CALENDAR = parsedatetime.Calendar()


def parse_duration_seconds(token: str) -> Optional[int]:
    """Parse a duration like '10m', '2h', '1d', '1w' into seconds. Returns
    None if the token doesn't match."""
    m = DURATION_RE.match(token.lower())
    if not m:
        return None
    value, unit = m.groups()
    return int(value) * DURATION_UNITS[unit]


def parse_natural_time(text: str, now: Optional[datetime] = None) -> Optional[tuple[datetime, str]]:
    """Pull a time expression out of free-form text (e.g. 'in 2 hours take
    out the trash', 'tomorrow at 3pm check the oven', or the older rigid
    '2h take out the trash') and return (remind_at_utc, remaining_text)
    with the time expression removed. Returns None if no time expression
    is found, or nothing is left over to use as the message.

    `now` (and therefore the returned datetime) is treated as UTC:
    parsedatetime resolves relative/absolute expressions like '3pm'
    against whatever "now" it's given, so passing a UTC "now" keeps
    everything in UTC rather than the server's local time, there's no
    per-user timezone stored for reminders to resolve against instead.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    matches = _NLP_CALENDAR.nlp(text, sourceTime=now.replace(tzinfo=None))
    if not matches:
        return None
    parsed_dt, _flags, start, end, _matched_text = matches[0]
    remaining = re.sub(r"\s+", " ", text[:start] + " " + text[end:]).strip()
    if not remaining:
        return None
    return parsed_dt.replace(tzinfo=timezone.utc), remaining


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
