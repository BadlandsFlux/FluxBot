"""Keeps embeds inside Discord/Fluxer's length limits.

An embed with a description over 4096 chars, a field value over 1024,
or similar gets the whole message rejected with HTTP 400
INVALID_MESSAGE_DATA (the shape of bug !help's old single-embed-per-
category design hit once the command list grew past it). Most embeds
aren't naturally splittable into pages the way !help's command list
is (see bot/modules/utility.py's _chunk_field_value for that case), so
this truncates instead: a long user- or admin-supplied string (a
warning reason, a staff note, a report, a poll option) can't take the
whole message down with it.

Doesn't bound the overall ~6000-char embed total across title/
description/fields/footer combined, only each piece individually,
since none of this bot's current embeds build up enough fields to
realistically hit that aggregate cap once each piece is itself capped.
"""
from __future__ import annotations

from typing import Optional

TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
FOOTER_LIMIT = 2048
_SUFFIX = "… (truncated)"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cutoff = max(0, limit - len(_SUFFIX))
    return text[:cutoff].rstrip() + _SUFFIX


def clamp_embed(embed: dict) -> dict:
    """Truncates one embed dict's text fields in place and returns it."""
    if embed.get("title"):
        embed["title"] = _truncate(str(embed["title"]), TITLE_LIMIT)
    if embed.get("description"):
        embed["description"] = _truncate(str(embed["description"]), DESCRIPTION_LIMIT)
    footer = embed.get("footer")
    if footer and footer.get("text"):
        footer["text"] = _truncate(str(footer["text"]), FOOTER_LIMIT)
    for field in embed.get("fields") or []:
        if field.get("name"):
            field["name"] = _truncate(str(field["name"]), FIELD_NAME_LIMIT)
        if field.get("value"):
            field["value"] = _truncate(str(field["value"]), FIELD_VALUE_LIMIT)
    return embed


def clamp_embeds(embeds: Optional[list]) -> Optional[list]:
    """Same, for the `embeds=[...]` list every send/edit call takes."""
    if not embeds:
        return embeds
    return [clamp_embed(e) for e in embeds]
