"""Background scheduler.

A single polling loop (checked every ~15s) that:
  - delivers reminders whose time has come
  - closes polls whose auto-close time has passed, tallying reactions
    and editing the original message with final results

Runs as its own asyncio task alongside the gateway connection in
bot/main.py — deliberately simple (poll-the-DB) rather than precise
per-item scheduling, since a bot's reminder/poll volume doesn't need
sub-second accuracy.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from bot.commands import Bot
from bot.modules.fun import NUMBER_EMOJI
from bot.modules import leveling, trivia as trivia_module
from bot import voice_tracker
from common import db

log = logging.getLogger("fluxbot.scheduler")

CHECK_INTERVAL = 15  # seconds


def _bar(pct: float, width: int = 12) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


async def _deliver_reminders(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    for r in await db.list_due_reminders(now):
        try:
            await bot.rest.send_message(
                r["channel_id"], content=f"⏰ <@{r['user_id']}> reminder: {r['content']}",
                allowed_mentions=bot.rest.mention_only(r["user_id"]),
            )
        except Exception:
            log.warning("Failed to deliver reminder %s", r["id"])
        await db.mark_reminder_delivered(r["id"])


async def _close_polls(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    for p in await db.list_due_polls(now):
        try:
            options = json.loads(p["options"]) if isinstance(p["options"], str) else p["options"]
            message = await bot.rest.get_message(p["channel_id"], p["message_id"])
            counts = {i: 0 for i in range(len(options))}
            for reaction in message.get("reactions", []):
                emoji_obj = reaction.get("emoji", {})
                emoji_name = emoji_obj.get("name") if isinstance(emoji_obj, dict) else emoji_obj
                if emoji_name in NUMBER_EMOJI:
                    idx = NUMBER_EMOJI.index(emoji_name)
                    if idx in counts:
                        # -1 to exclude the bot's own seed reaction on each option
                        counts[idx] = max(0, reaction.get("count", 0) - 1)

            total = sum(counts.values()) or 1
            lines = []
            for i, opt in enumerate(options):
                n = counts.get(i, 0)
                pct = (n / total) * 100
                lines.append(f"{NUMBER_EMOJI[i]} {opt}\n{_bar(pct)} {n} vote{'s' if n != 1 else ''} ({pct:.0f}%)")

            embed = {
                "title": f"📊 {p['question']} — Poll closed",
                "description": "\n\n".join(lines),
                "color": 0x95A5A6,
                "footer": {"text": f"{total if total != 1 or sum(counts.values()) else 0} total votes"},
            }
            await bot.rest.edit_message(p["channel_id"], p["message_id"], content="", embeds=[embed])
        except Exception:
            log.warning("Failed to close poll %s", p["id"])
        await db.mark_poll_closed(p["id"])


async def _close_trivia(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    bot_id = str(bot.gateway.user["id"]) if bot.gateway.user else None
    for t in await db.list_due_trivia(now):
        try:
            options = json.loads(t["options"]) if isinstance(t["options"], str) else t["options"]
            correct_emoji = trivia_module.NUMBER_EMOJI[t["correct_index"]]
            reactors = await bot.rest.get_reaction_users(t["channel_id"], t["message_id"], correct_emoji)
            winners = [str(u["id"]) for u in reactors if str(u.get("id")) != bot_id]

            for user_id in winners:
                try:
                    member = await bot.get_member(t["guild_id"], user_id, fresh=False)
                    username = member.get("user", member).get("username", "someone")
                except Exception:
                    username = "someone"
                await leveling.grant_xp(bot, t["guild_id"], user_id, username, trivia_module.XP_REWARD)

            winner_text = (
                ", ".join(f"<@{uid}>" for uid in winners) if winners else "nobody got it this time"
            )
            embed = {
                "title": f"🧠 {t['question']}",
                "description": f"Correct answer: {correct_emoji} **{options[t['correct_index']]}**\n\n{winner_text}",
                "color": 0x2ecc71,
                "footer": {"text": f"+{trivia_module.XP_REWARD} XP each" if winners else "Trivia closed"},
            }
            await bot.rest.edit_message(
                t["channel_id"], t["message_id"], content="", embeds=[embed],
                allowed_mentions=bot.rest.mention_only(*winners),
            )
        except Exception:
            log.warning("Failed to close trivia %s", t["id"])
        await db.mark_trivia_closed(t["id"])


async def _update_bot_status(bot: Bot) -> None:
    started_at_wall = datetime.now(timezone.utc) - timedelta(seconds=bot.uptime_seconds)
    guild_count = await bot.guild_count()
    await db.update_bot_status(started_at_wall, bot.gateway.latency_ms, guild_count)


async def run_scheduler(bot: Bot) -> None:
    while True:
        try:
            await _deliver_reminders(bot)
            await _close_polls(bot)
            await _close_trivia(bot)
            await voice_tracker.flush_all(bot)
            await _update_bot_status(bot)
        except Exception:
            log.exception("Scheduler tick failed")
        await asyncio.sleep(CHECK_INTERVAL)
