"""Keeps embeds inside Discord/Fluxer's length limits.

An embed with a description over 4096 chars, a field value over 1024,
or similar gets the whole message rejected with HTTP 400
INVALID_MESSAGE_DATA (the shape of bug !help's old single-embed-per-
category design hit once the command list grew past it). Most embeds
aren't naturally splittable into pages the way !help's command list
is (see chunk_lines for that case), so this truncates instead: a long
user- or admin-supplied string (a warning reason, a staff note, a
report, a poll option) can't take the whole message down with it.

Also bounds the ~6000-char embed total across title/description/
fields/footer combined, and the 25-field cap: either one gets the
whole message rejected the same way, and an embed can clear both even
with every individual piece already within its own limit -- several
fields each near their own 1024-char cap adds up fast (a lesson Fluxer
patch notes learned the hard way: busy-day commit lists spread over
enough fields hit this long before any single field did).
"""
from __future__ import annotations

from typing import Optional

TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
FOOTER_LIMIT = 2048
TOTAL_LIMIT = 6000
MAX_FIELDS = 25
_SUFFIX = "… (truncated)"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cutoff = max(0, limit - len(_SUFFIX))
    return text[:cutoff].rstrip() + _SUFFIX


def _total_len(embed: dict) -> int:
    total = len(embed.get("title") or "") + len(embed.get("description") or "")
    total += len((embed.get("footer") or {}).get("text") or "")
    for field in embed.get("fields") or []:
        total += len(field.get("name") or "") + len(field.get("value") or "")
    return total


def _clamp_total(embed: dict) -> None:
    fields = embed.get("fields")
    dropped = False
    if fields:
        if len(fields) > MAX_FIELDS:
            del fields[MAX_FIELDS:]
            dropped = True
        # Drop whole fields from the end rather than shaving a little off
        # each one: keeps the earlier (first-seen, generally more
        # relevant) content intact instead of mangling everything a bit.
        while fields and _total_len(embed) > TOTAL_LIMIT:
            fields.pop()
            dropped = True
    if dropped:
        footer = embed.setdefault("footer", {})
        existing = footer.get("text") or ""
        note = f"{existing} (truncated)" if existing else "(truncated)"
        footer["text"] = _truncate(note, FOOTER_LIMIT)
    # Last resort, only reachable if title+description+footer alone (with
    # no fields left to drop) still clear 6000 -- shave the description.
    overflow = _total_len(embed) - TOTAL_LIMIT
    if overflow > 0 and embed.get("description"):
        embed["description"] = _truncate(embed["description"], max(0, len(embed["description"]) - overflow))


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
    _clamp_total(embed)
    return embed


def clamp_embeds(embeds: Optional[list]) -> Optional[list]:
    """Same, for the `embeds=[...]` list every send/edit call takes."""
    if not embeds:
        return embeds
    return [clamp_embed(e) for e in embeds]


def chunk_lines(lines: list[str], limit: int = FIELD_VALUE_LIMIT) -> list[str]:
    """Groups `lines` (each one joined by "\\n") into chunks that each fit
    within `limit` chars, for content that's naturally splittable across
    several embed fields instead of truncated -- !help's per-category
    command list, Fluxer patch notes' per-theme commit list. A single
    line longer than `limit` on its own still ends up over it; callers
    with that risk should run it through clamp_embed/clamp_embeds too."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        added_len = len(line) + (1 if current else 0)
        if current and current_len + added_len > limit:
            chunks.append("\n".join(current))
            current, current_len = [line], len(line)
        else:
            current.append(line)
            current_len += added_len
    if current:
        chunks.append("\n".join(current))
    return chunks
