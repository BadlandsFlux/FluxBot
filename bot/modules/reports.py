"""Member-submitted bug/issue reports.

No command to file one: any non-bot message posted in the configured
report channel (!reportchannel #channel) is automatically captured as
a report. The original message is always removed from that channel
right after capture, public or private alike (best-effort, needs
Manage Messages; if the bot doesn't have it, the report itself is
still saved and tracked, just logged rather than silently left
behind). A report only actually lives on in a second "tracker"
channel (!reporttracker #channel) as a status-tagged embed the bot
keeps edited in place, so people can scroll it and see what's already
been reported before filing another one, and the report channel
itself never ends up holding a mix of raw submissions and bot
clutter -- see bot/report_actions.py for the embed/status logic
shared with the dashboard's Reports tab.

Visibility is the reporter's own per-report choice: include a
"Private: yes" line in the report itself (see
report_actions.REPORT_TEMPLATE, offered as a copy-pasteable starting
point in the channel explainer) to have the tracker entry omit your
identity. _extract_privacy_field below is deliberately loose about
this, any line matching "private: <truthy>" counts, free text with
that one line appended works exactly like the full template. This
only ever affects attribution in the tracker, not whether the
original message gets removed, that already always happens.

    !reportchannel #channel    set where reports are captured from
    !reporttracker #channel    set where the tracker embeds are posted
    !report status <id> <open|duplicate|resolved|wontfix> [note]
    !report list [status]
    !report info <id>
"""
from __future__ import annotations

import logging
import re

from bot import report_actions
from bot.commands import Bot, Context
from bot.modules.moderation import parse_channel_id
from bot.permissions import PERM_KICK_MEMBERS, PERM_MANAGE_GUILD
from bot.rest import FluxerAPIError
from common import db

log = logging.getLogger("fluxbot.reports")

_PRIVATE_FIELD_RE = re.compile(r"^\s*private\s*:\s*(.+?)\s*$", re.IGNORECASE)
_TRUE_VALUES = {"yes", "y", "true", "1"}


def _extract_privacy_field(content: str) -> tuple[str, bool]:
    """Pulls a "Private: yes/no" line out of a submitted report, if
    present anywhere in it, and reports whether it asked for private.
    The line itself is stripped from what gets stored/shown, it's a
    meta-instruction to the bot, not part of the actual report."""
    want_private = False
    kept = []
    for line in content.splitlines():
        m = _PRIVATE_FIELD_RE.match(line)
        if m:
            want_private = m.group(1).strip().lower() in _TRUE_VALUES
            continue
        kept.append(line)
    return "\n".join(kept).strip(), want_private


async def _remove_original_and_notify(bot: Bot, channel_id: str, message_id: str, reporter_id: str,
                                       report_id: int, *, private: bool, extra: str = "") -> None:
    """Every report ends up here: best-effort remove the now-redundant
    original message (it's in the tracker now), then let the reporter
    know by DM, since there's no public message left to reply under."""
    try:
        await bot.rest.delete_message(channel_id, message_id)
    except FluxerAPIError:
        log.warning("Couldn't delete report #%s's original message (missing Manage Messages in the "
                    "report channel?)", report_id)
    if private:
        text = (f"🔒 Got it, report #{report_id} is logged and private: your name won't be shown in "
                f"the tracker, and the original message has been removed from the report channel.{extra}")
    else:
        text = (f"✅ Got it, report #{report_id} is logged in the tracker, and the original message "
                f"has been removed from the report channel.{extra}")
    try:
        dm = await bot.rest.create_dm(reporter_id)
        await bot.rest.send_message(dm["id"], content=text)
    except FluxerAPIError:
        pass  # can't DM them, nothing more to do, the report itself is already saved and tracked


def register(bot: Bot) -> None:

    @bot.on("MESSAGE_CREATE")
    async def on_report_channel_message(data: dict) -> None:
        guild_id = data.get("guild_id")
        if not guild_id:
            return  # DMs, nothing to capture
        guild_id = str(guild_id)
        author = data.get("author", {})
        if author.get("bot") or data.get("webhook_id"):
            return  # our own confirmation reply, a tracker post if the two channels are ever the same, or another bot

        channel_id = str(data.get("channel_id"))
        guild_cfg = await db.get_guild(guild_id)
        report_channel_id = guild_cfg["report_channel_id"] if guild_cfg else None
        if not report_channel_id or channel_id != str(report_channel_id):
            return  # feature off, or this message isn't in the configured channel

        prefix = await bot.get_prefix(guild_id)
        raw_content = (data.get("content") or "").strip()
        if raw_content.startswith(prefix):
            return  # a staff command typed in this channel (e.g. !report status ...), not a report
        content, want_private = _extract_privacy_field(raw_content)
        attachments = data.get("attachments") or []
        if not content and not attachments:
            return  # nothing worth capturing (e.g. a bare "Private: yes" with nothing else, or a sticker)
        if attachments:
            urls = "\n".join(a["url"] for a in attachments if a.get("url"))
            content = f"{content}\n\n{urls}".strip() if content else urls

        message_id = str(data.get("id"))
        reporter_id = str(author.get("id"))

        report = await report_actions.submit_report(
            bot.rest, guild_id, reporter_id, content, channel_id, message_id,
            guild_cfg["report_tracker_channel_id"], visibility="private" if want_private else "public",
        )

        dup_note = (f" This also looks similar to report #{report['possible_duplicate_of']}, "
                    f"which may already cover it." if report["possible_duplicate_of"] else "")

        # Always removed from here, public or private alike, see the module
        # docstring: a report only ever actually lives on in the tracker.
        await _remove_original_and_notify(
            bot, channel_id, message_id, reporter_id, report["id"], private=want_private, extra=dup_note,
        )

    @bot.command("reportchannel", category="Moderation", required_permission=PERM_MANAGE_GUILD,
                 help_text="Set the channel people post bug/issue reports in. Usage: !reportchannel #channel")
    async def reportchannel(ctx: Context) -> None:
        if not ctx.args:
            await ctx.reply("Mention the channel to capture reports from, e.g. `!reportchannel #bug-reports`.")
            return
        channel_id = parse_channel_id(ctx.args[0])
        if not channel_id:
            await ctx.reply(f"Couldn't parse `{ctx.args[0]}` as a channel.")
            return
        await db.update_guild_settings(ctx.guild_id, report_channel_id=channel_id)
        guild_cfg = await db.get_guild(ctx.guild_id)
        await report_actions.post_channel_intro(
            ctx.bot.rest, channel_id, guild_cfg["report_tracker_channel_id"] if guild_cfg else None,
        )
        await ctx.reply(f"📝 Report channel set to <#{channel_id}>. Any message posted there from now on "
                         f"is captured as a report -- I've posted an explainer there too.")

    @bot.command("reporttracker", category="Moderation", required_permission=PERM_MANAGE_GUILD,
                 help_text="Set the channel reports are tracked in. Usage: !reporttracker #channel")
    async def reporttracker(ctx: Context) -> None:
        if not ctx.args:
            await ctx.reply("Mention the channel to track reports in, e.g. `!reporttracker #bug-tracker`.")
            return
        channel_id = parse_channel_id(ctx.args[0])
        if not channel_id:
            await ctx.reply(f"Couldn't parse `{ctx.args[0]}` as a channel.")
            return
        await db.update_guild_settings(ctx.guild_id, report_tracker_channel_id=channel_id)
        await ctx.reply(f"📋 Report tracker channel set to <#{channel_id}>.")

    @bot.command("report", category="Moderation", required_permission=PERM_KICK_MEMBERS,
                 help_text="Manage bug/issue reports. Usage: !report status <id> <open|duplicate|resolved|wontfix> "
                            "[note], !report list [status], !report info <id>")
    async def report(ctx: Context) -> None:
        usage = ("Usage: `!report status <id> <open|duplicate|resolved|wontfix> [note]`, "
                 "`!report list [status]`, `!report info <id>`")
        if not ctx.args:
            await ctx.reply(usage)
            return
        sub = ctx.args[0].lower()

        if sub == "list":
            status = ctx.args[1].lower() if len(ctx.args) > 1 else None
            if status and status not in db.REPORT_STATUSES:
                await ctx.reply(f"Unknown status `{status}`, must be one of: {', '.join(db.REPORT_STATUSES)}")
                return
            rows = await db.list_reports(ctx.guild_id, status=status, limit=15)
            if not rows:
                await ctx.reply(f"No `{status}` reports." if status else "No reports yet.")
                return
            lines = []
            for r in rows:
                snippet = (r["content"] or "")[:60].replace("\n", " ")
                dup = f" (dup of #{r['duplicate_of']})" if r["duplicate_of"] else ""
                lines.append(f"**#{r['id']}** [{r['status']}]{dup}: {snippet}")
            await ctx.embed(f"Reports{' (' + status + ')' if status else ''}", "\n".join(lines))
            return

        if sub == "info":
            if len(ctx.args) < 2 or not ctx.args[1].isdigit():
                await ctx.reply("Usage: `!report info <id>`")
                return
            r = await db.get_report(ctx.guild_id, int(ctx.args[1]))
            if not r:
                await ctx.reply(f"No report #{ctx.args[1]} in this server.")
                return
            fields = [
                {"name": "Status", "value": r["status"], "inline": True},
                {"name": "Reporter", "value": f"<@{r['reporter_id']}>" if r["visibility"] == "public"
                                               else "kept private", "inline": True},
            ]
            if r["duplicate_of"]:
                fields.append({"name": "Duplicate of", "value": f"#{r['duplicate_of']}", "inline": True})
            if r["possible_duplicate_of"]:
                fields.append({"name": "Possible duplicate of", "value": f"#{r['possible_duplicate_of']}",
                                "inline": True})
            if r["resolution_note"]:
                fields.append({"name": "Note", "value": r["resolution_note"], "inline": False})
            await ctx.embed(f"Report #{r['id']}", r["content"] or "", fields=fields)
            return

        if sub == "status":
            if len(ctx.args) < 3 or not ctx.args[1].isdigit():
                await ctx.reply("Usage: `!report status <id> <open|duplicate|resolved|wontfix> [note, or for "
                                 "`duplicate` the original report's id]`")
                return
            report_id = int(ctx.args[1])
            new_status = ctx.args[2].lower()
            rest_args = ctx.args[3:]
            duplicate_of, note = None, None
            if new_status == "duplicate":
                if not rest_args or not rest_args[0].isdigit():
                    await ctx.reply("Usage: `!report status <id> duplicate <original id>`")
                    return
                duplicate_of = int(rest_args[0])
            elif rest_args:
                note = " ".join(rest_args)

            try:
                updated = await report_actions.set_status(
                    ctx.bot.rest, ctx.guild_id, report_id, new_status,
                    duplicate_of=duplicate_of, resolution_note=note, resolved_by=str(ctx.author["id"]),
                )
            except ValueError as e:
                await ctx.reply(str(e))
                return
            await ctx.reply(f"{report_actions.STATUS_EMOJI[new_status]} Report #{updated['id']} marked "
                             f"**{report_actions.STATUS_LABELS[new_status]}**.")
            return

        await ctx.reply(usage)
