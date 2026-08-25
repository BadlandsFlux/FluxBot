"""In-memory cache of recent message content.

Fluxer's gateway (like Discord's) doesn't include the OLD content in a
MESSAGE_UPDATE event, and MESSAGE_DELETE doesn't include any content at
all, just the message_id. Showing "before" text on an edit or "what got
deleted" requires having already cached the content ourselves from the
original MESSAGE_CREATE.

This is a runtime cache only, not persisted to the database: it resets
on every bot restart, and a message that was never cached (bot was down
when it was sent, or it's aged out) shows as "content not available"
rather than the actual text. That's an accepted tradeoff, the same one
essentially every Discord logging bot makes, persisting full message
history would be a much bigger, more invasive feature (and its own
privacy consideration) than "recent edits/deletes while the bot's been
running."

Bounded globally (not per-guild) via bot/bounded_cache.py, so memory use
has a hard ceiling regardless of how many guilds, how much traffic, or
how long the process has been up without a restart.
"""
from __future__ import annotations

from typing import Optional

from bot.bounded_cache import BoundedDict

MAX_CACHED_MESSAGES = 5000

_cache: BoundedDict[str, dict] = BoundedDict(max_size=MAX_CACHED_MESSAGES)


def remember(message_id: str, *, guild_id: str, channel_id: str,
             author_id: str, author_username: str, content: str) -> None:
    _cache[message_id] = {
        "guild_id": guild_id,
        "channel_id": channel_id,
        "author_id": author_id,
        "author_username": author_username,
        "content": content,
    }


def get(message_id: str) -> Optional[dict]:
    return _cache.get(message_id)


def update_content(message_id: str, new_content: str) -> None:
    """Called after logging an edit, so a second edit to the same message
    diffs against the most recent version, not the original."""
    entry = _cache.get(message_id)
    if entry:
        entry["content"] = new_content


def forget(message_id: str) -> None:
    _cache.pop(message_id, None)
