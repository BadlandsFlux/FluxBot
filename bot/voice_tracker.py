"""Voice activity tracking.

Tracks time connected to voice channels for the dashboard's activity
stats and for voice XP — deliberately *presence* tracking only (who's
connected, to which channel, for how long), not audio. That's a
completely different, much simpler thing than actually receiving/
transmitting audio, and only needs the `VOICE_STATE_UPDATE` gateway
event Fluxer already sends.

Eligibility rules for earning voice time/XP (per-member, re-evaluated
on every relevant state change):
  - at least 2 humans connected to the same channel (solo time doesn't
    count — no farming XP by sitting alone)
  - the member isn't self-deafened (a reasonable proxy for "not really
    here" without needing actual speaking detection, which would
    require the audio pipeline this deliberately avoids)
  - the channel isn't the guild's configured AFK channel

CAVEAT: the AFK-channel field name (`afk_channel_id` on the guild
object) follows the Discord convention Fluxer mirrors elsewhere but
isn't confirmed from public docs — if your instance names it
differently, update `_afk_channel_id` below.

Accrued time/XP is flushed (persisted to Postgres) whenever eligibility
changes, AND periodically by the scheduler (see bot/scheduler.py) so a
long-running call doesn't lose everything on a crash/restart — at most
one scheduler interval's worth of credit is ever at risk.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Optional

from bot.commands import Bot
from bot.modules import leveling
from common import db

VOICE_XP_MIN_PER_MIN, VOICE_XP_MAX_PER_MIN = 3, 6  # lower than text's ~15-25/message

# In-memory only — rebuilt from live VOICE_STATE_UPDATE events (and a
# best-effort seed from GUILD_CREATE's voice_states, if present) rather
# than persisted, since it's just bookkeeping for "currently connected".
_channel_occupants: dict[tuple[str, str], set[str]] = {}
_member_channel: dict[tuple[str, str], str] = {}
_member_self_deaf: dict[tuple[str, str], bool] = {}
_accrual_start: dict[tuple[str, str], datetime] = {}


def _afk_channel_id(guild: dict) -> Optional[str]:
    afk = guild.get("afk_channel_id")
    return str(afk) if afk else None


async def _flush_member(bot: Bot, guild_id: str, user_id: str, now: datetime, keep_earning: bool) -> None:
    key = (guild_id, user_id)
    start = _accrual_start.get(key)
    if start is None:
        if keep_earning:
            _accrual_start[key] = now
        return

    if keep_earning:
        _accrual_start[key] = now
    else:
        _accrual_start.pop(key, None)

    elapsed_minutes = (now - start).total_seconds() / 60
    if elapsed_minutes <= 0:
        return

    await db.record_voice_minutes(guild_id, user_id, elapsed_minutes)

    xp_amount = round(elapsed_minutes * random.uniform(VOICE_XP_MIN_PER_MIN, VOICE_XP_MAX_PER_MIN))
    if xp_amount > 0:
        try:
            member = await bot.get_member(guild_id, user_id, fresh=False)
            username = member.get("user", member).get("username", "someone")
        except Exception:
            username = "someone"
        await leveling.grant_xp(bot, guild_id, user_id, username, xp_amount)


async def _recompute_channel(bot: Bot, guild_id: str, channel_id: str, now: datetime) -> None:
    occupants = _channel_occupants.get((guild_id, channel_id), set())
    try:
        guild = await bot.get_guild(guild_id)
    except Exception:
        guild = {}
    is_afk_channel = _afk_channel_id(guild) == channel_id
    eligible_base = len(occupants) >= 2 and not is_afk_channel

    for user_id in list(occupants):
        self_deaf = _member_self_deaf.get((guild_id, user_id), False)
        eligible = eligible_base and not self_deaf
        await _flush_member(bot, guild_id, user_id, now, keep_earning=eligible)


async def _process_voice_state(bot: Bot, data: dict) -> None:
    guild_id = data.get("guild_id")
    user_id = data.get("user_id")
    if not guild_id or not user_id:
        return
    guild_id, user_id = str(guild_id), str(user_id)

    raw_channel = data.get("channel_id")
    new_channel = str(raw_channel) if raw_channel else None
    self_deaf = bool(data.get("self_deaf") or data.get("deaf"))
    now = datetime.now(timezone.utc)

    old_channel = _member_channel.get((guild_id, user_id))
    _member_self_deaf[(guild_id, user_id)] = self_deaf

    if old_channel != new_channel:
        if old_channel:
            _channel_occupants.get((guild_id, old_channel), set()).discard(user_id)
        if new_channel:
            _channel_occupants.setdefault((guild_id, new_channel), set()).add(user_id)
            _member_channel[(guild_id, user_id)] = new_channel
        else:
            _member_channel.pop((guild_id, user_id), None)
            await _flush_member(bot, guild_id, user_id, now, keep_earning=False)

    if old_channel:
        await _recompute_channel(bot, guild_id, old_channel, now)
    if new_channel:
        await _recompute_channel(bot, guild_id, new_channel, now)


async def flush_all(bot: Bot) -> None:
    """Called periodically by the scheduler so long sessions accrue
    progressively instead of only crediting on leave."""
    now = datetime.now(timezone.utc)
    for guild_id, user_id in list(_accrual_start.keys()):
        await _flush_member(bot, guild_id, user_id, now, keep_earning=True)


def register(bot: Bot) -> None:

    @bot.on("VOICE_STATE_UPDATE")
    async def on_voice_state_update(data: dict) -> None:
        await _process_voice_state(bot, data)

    @bot.on("GUILD_CREATE")
    async def on_guild_create_seed(data: dict) -> None:
        # Best-effort: if the instance includes already-connected members'
        # voice states in GUILD_CREATE (Discord convention), seed our
        # tracker so a bot restart doesn't lose track of ongoing calls
        # until someone's voice state next changes.
        for vs in data.get("voice_states", []) or []:
            vs = {**vs, "guild_id": data.get("id")}
            await _process_voice_state(bot, vs)
