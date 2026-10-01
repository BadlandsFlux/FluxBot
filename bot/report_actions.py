"""Shared bug/issue report actions.

Both the chat command (bot/modules/reports.py's `!report status ...`)
and the dashboard's Reports tab call into these functions, so the
tracker embed and the reporter's DM can never drift between "staff
typed a command" and "staff clicked a button" -- same shared-logic
principle as bot/moderation_actions.py.

`rest` is duck-typed throughout: anything with the same async methods
as `bot.rest.FluxerREST` works, in practice either a running bot's
`Bot.rest` or the dashboard's standalone `bot_rest` client.
"""
from __future__ import annotations

import difflib
import logging
from typing import Optional

import asyncpg

from bot.rest import FluxerAPIError
from common import db

log = logging.getLogger("fluxbot.report_actions")

STATUS_LABELS = {"open": "Open", "duplicate": "Duplicate", "resolved": "Resolved", "wontfix": "Won't Fix"}
STATUS_COLORS = {"open": 0xF1C40F, "duplicate": 0x95A5A6, "resolved": 0x2ECC71, "wontfix": 0xE74C3C}
STATUS_EMOJI = {"open": "📝", "duplicate": "♻️", "resolved": "✅", "wontfix": "🚫"}

# A basic ratio() match, not a semantic/embedding comparison -- cheap,
# zero extra dependencies (stdlib difflib), and good enough to catch
# the common case (two people pasting nearly the same error message
# or describing the same thing in very similar words). Deliberately
# conservative (0.6, not lower): this only ever produces a *hint* for
# staff to confirm in the tracker, never auto-closes anything on its
# own, so a missed duplicate is a much cheaper mistake than a wrong
# auto-flag training people to ignore the hint.
_SIMILARITY_THRESHOLD = 0.6


# The literal text offered as a copy-pasteable starting point in the
# channel explainer below. Only the "Private:" line is ever actually
# parsed (see bot/modules/reports.py's _extract_privacy_field) -- the
# rest is just a suggested shape, a report posted as plain free text
# with no template at all works exactly the same.
REPORT_TEMPLATE = "Title: \nDescription: \nSteps to reproduce: \nPrivate: no"


def build_channel_intro_embed(tracker_channel_id: Optional[str] = None) -> dict:
    lines = [
        "**Post anything here and it becomes a report**, no command needed. Free text works, or copy "
        "the template below and fill it in.",
        ("Set `Private: yes` in your report to keep it private from the moment you post it: your name "
         "never shows up anywhere and the message is removed right away, no window where it's sitting "
         "there attributed. Forgot to set it? React 🔒 on your own report within 10 minutes instead and "
         "I'll do the same thing after the fact."),
    ]
    if tracker_channel_id:
        lines.append(f"Check <#{tracker_channel_id}> first to see if your issue is already being "
                      f"tracked, that saves everyone from duplicate reports.")
    return {
        "title": "📝 How to report a bug or issue",
        "description": "\n\n".join(lines),
        "color": 0x5865F2,
        "fields": [{
            "name": "Template (optional)",
            "value": f"```\n{REPORT_TEMPLATE}\n```",
            "inline": False,
        }],
    }


async def post_channel_intro(rest, channel_id: str, tracker_channel_id: Optional[str] = None) -> None:
    """Posted once whenever the report channel is set or changed (see
    bot/modules/reports.py's !reportchannel and dashboard/app.py's
    settings endpoint) -- an explainer embed so someone landing in the
    channel doesn't have to already know this bot's convention of
    "just post here, no command" to use it."""
    try:
        await rest.send_message(channel_id, embeds=[build_channel_intro_embed(tracker_channel_id)])
    except FluxerAPIError:
        log.warning("Failed to post the report-channel explainer to %s", channel_id)


async def find_possible_duplicate(guild_id: str, content: str) -> Optional[int]:
    """Best-effort guess at an existing OPEN report covering the same
    issue, by raw text similarity. Returns that report's id, or None
    if nothing clears the threshold."""
    candidates = await db.get_open_reports_for_dedup(guild_id)
    if not candidates:
        return None
    needle = content.strip().lower()
    best_id: Optional[int] = None
    best_ratio = 0.0
    for row in candidates:
        ratio = difflib.SequenceMatcher(None, needle, (row["content"] or "").strip().lower()).ratio()
        if ratio > best_ratio:
            best_ratio, best_id = ratio, row["id"]
    return best_id if best_ratio >= _SIMILARITY_THRESHOLD else None


def build_tracker_embed(report: asyncpg.Record) -> dict:
    status = report["status"]
    title = f"{STATUS_EMOJI[status]} Report #{report['id']}: {STATUS_LABELS[status]}"
    if status == "duplicate" and report["duplicate_of"]:
        title += f" of #{report['duplicate_of']}"

    fields = []
    if report["visibility"] == "public":
        fields.append({"name": "Reported by", "value": f"<@{report['reporter_id']}>", "inline": True})
    else:
        fields.append({"name": "Reported by", "value": "Kept private by the reporter", "inline": True})

    if status == "open" and report["possible_duplicate_of"]:
        fields.append({
            "name": "⚠️ Possible duplicate",
            "value": f"Looks similar to #{report['possible_duplicate_of']}, check before filing another one.",
            "inline": False,
        })

    if report["resolution_note"]:
        fields.append({"name": "Note", "value": report["resolution_note"][:1000], "inline": False})

    embed = {
        "title": title,
        "description": (report["content"] or "")[:3000],
        "color": STATUS_COLORS[status],
        "fields": fields,
        "footer": {"text": f"Report #{report['id']}"},
    }
    if report["created_at"]:
        embed["timestamp"] = report["created_at"].isoformat()
    return embed


async def post_to_tracker(rest, tracker_channel_id: str, report: asyncpg.Record) -> Optional[dict]:
    try:
        return await rest.send_message(tracker_channel_id, embeds=[build_tracker_embed(report)])
    except FluxerAPIError:
        log.warning("Failed to post report #%s to tracker channel %s", report["id"], tracker_channel_id)
        return None


async def sync_tracker_entry(rest, report: asyncpg.Record) -> None:
    """Re-renders the already-posted tracker embed in place after
    anything about the report changes (status, visibility). A no-op
    if this report was never successfully posted to a tracker in the
    first place (no tracker channel configured at submission time, or
    the initial post failed)."""
    if not report["tracker_channel_id"] or not report["tracker_message_id"]:
        return
    try:
        await rest.edit_message(report["tracker_channel_id"], report["tracker_message_id"],
                                 embeds=[build_tracker_embed(report)])
    except FluxerAPIError:
        log.warning("Failed to update tracker entry for report #%s", report["id"])


async def submit_report(rest, guild_id: str, reporter_id: str, content: str, submit_channel_id: str,
                         submit_message_id: str, tracker_channel_id: Optional[str], *,
                         visibility: str = "public") -> asyncpg.Record:
    """The one place a new report is created, tying together the
    duplicate-guess, the DB row, and the initial tracker post."""
    possible_dup = await find_possible_duplicate(guild_id, content)
    report = await db.create_report(
        guild_id, reporter_id, content, submit_channel_id, submit_message_id,
        visibility=visibility, possible_duplicate_of=possible_dup,
    )
    if tracker_channel_id:
        message = await post_to_tracker(rest, tracker_channel_id, report)
        if message:
            await db.set_report_tracker_message(guild_id, report["id"], tracker_channel_id, str(message["id"]))
            report = await db.get_report(guild_id, report["id"])
    return report


async def privatize_report(rest, guild_id: str, report_id: int) -> Optional[asyncpg.Record]:
    updated = await db.mark_report_private(guild_id, report_id)
    if updated:
        await sync_tracker_entry(rest, updated)
    return updated


async def _notify_reporter(rest, report: asyncpg.Record) -> None:
    status = report["status"]
    if status == "duplicate":
        text = (f"♻️ Your report #{report['id']} was marked as a duplicate of #{report['duplicate_of']}, "
                "looks like someone already flagged this, thanks for reporting it anyway!")
    elif status == "resolved":
        text = f"✅ Your report #{report['id']} has been marked resolved. Thanks for reporting it!"
    else:  # wontfix
        text = f"🚫 Your report #{report['id']} was reviewed and marked as won't-fix."
    if report["resolution_note"]:
        text += f"\n\nNote from staff: {report['resolution_note']}"
    try:
        dm = await rest.create_dm(report["reporter_id"])
        await rest.send_message(dm["id"], content=text)
    except FluxerAPIError:
        pass  # can't DM them, nothing more to do, the status change itself already landed


async def set_status(rest, guild_id: str, report_id: int, status: str, *, duplicate_of: Optional[int] = None,
                      resolution_note: Optional[str] = None, resolved_by: Optional[str] = None,
                      notify: bool = True) -> asyncpg.Record:
    if status not in db.REPORT_STATUSES:
        raise ValueError(f"Unknown status {status!r}, must be one of {', '.join(db.REPORT_STATUSES)}")

    if status == "duplicate":
        if not duplicate_of:
            raise ValueError("Marking a report duplicate needs the id of the original, "
                              "e.g. `!report status 12 duplicate 7`.")
        if duplicate_of == report_id:
            raise ValueError("A report can't be a duplicate of itself.")
        original = await db.get_report(guild_id, duplicate_of)
        if not original:
            raise ValueError(f"No report #{duplicate_of} in this server to mark #{report_id} a duplicate of.")
    else:
        duplicate_of = None  # only meaningful alongside status == "duplicate"

    updated = await db.set_report_status(
        guild_id, report_id, status,
        duplicate_of=duplicate_of, resolution_note=resolution_note, resolved_by=resolved_by,
    )
    if not updated:
        raise ValueError(f"No report #{report_id} in this server.")

    await sync_tracker_entry(rest, updated)
    if notify and status in ("resolved", "wontfix", "duplicate"):
        await _notify_reporter(rest, updated)

    return updated
