"""The voice XP daily cap: db.add_voice_xp_capped() clamps correctly
against the real Postgres row, and bot/voice_tracker.py's _flush_member
wires it in (or skips it entirely when a guild has turned it off).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bot import voice_tracker
from bot.commands import Bot
from common import db


async def test_add_voice_xp_capped_grants_up_to_the_cap(guild_id):
    granted = await db.add_voice_xp_capped(guild_id, "u1", proposed_xp=500, daily_cap=750)
    assert granted == 500

    # A second grant the same day only gets the remainder.
    granted = await db.add_voice_xp_capped(guild_id, "u1", proposed_xp=400, daily_cap=750)
    assert granted == 250

    # Once at the cap, nothing more is granted today.
    granted = await db.add_voice_xp_capped(guild_id, "u1", proposed_xp=100, daily_cap=750)
    assert granted == 0


async def test_add_voice_xp_capped_is_per_member_and_per_guild(guild_id):
    await db.add_voice_xp_capped(guild_id, "u1", proposed_xp=750, daily_cap=750)
    # A different member in the same guild has their own, unaffected budget.
    granted = await db.add_voice_xp_capped(guild_id, "u2", proposed_xp=500, daily_cap=750)
    assert granted == 500


async def test_add_voice_xp_capped_zero_or_negative_proposed_is_a_noop(guild_id):
    assert await db.add_voice_xp_capped(guild_id, "u1", proposed_xp=0, daily_cap=750) == 0
    assert await db.add_voice_xp_capped(guild_id, "u1", proposed_xp=-10, daily_cap=750) == 0


@pytest.fixture(autouse=True)
def _clear_voice_tracker_state():
    voice_tracker._accrual_start.clear()
    yield
    voice_tracker._accrual_start.clear()


def make_bot():
    bot = Bot("test-token")

    async def fake_get_member(gid, uid, fresh=False):
        return {"user": {"id": uid, "username": "tester"}, "roles": []}

    bot.get_member = fake_get_member
    return bot


async def test_flush_member_caps_a_long_session_when_enabled(guild_id, monkeypatch):
    granted_calls = []

    async def fake_grant_xp(bot, gid, uid, username, amount):
        granted_calls.append(amount)

    monkeypatch.setattr(voice_tracker.leveling, "grant_xp", fake_grant_xp)

    bot = make_bot()
    now = datetime.now(timezone.utc)
    # 5 hours accrued in one flush, comfortably enough (even at the
    # random rate's floor of 3 XP/min) to blow past the 750/day cap.
    voice_tracker._accrual_start[(guild_id, "u1")] = now - timedelta(hours=5)

    await voice_tracker._flush_member(bot, guild_id, "u1", now, keep_earning=False)

    assert len(granted_calls) == 1
    assert granted_calls[0] <= voice_tracker.VOICE_XP_DAILY_CAP_DEFAULT


async def test_flush_member_does_not_cap_when_guild_disables_it(guild_id, monkeypatch):
    await db.update_guild_settings(guild_id, voice_xp_cap_enabled=False)

    granted_calls = []

    async def fake_grant_xp(bot, gid, uid, username, amount):
        granted_calls.append(amount)

    monkeypatch.setattr(voice_tracker.leveling, "grant_xp", fake_grant_xp)

    bot = make_bot()
    now = datetime.now(timezone.utc)
    voice_tracker._accrual_start[(guild_id, "u1")] = now - timedelta(hours=5)

    await voice_tracker._flush_member(bot, guild_id, "u1", now, keep_earning=False)

    assert len(granted_calls) == 1
    # 5 hours * 6 XP/min max = 1800, well over the cap this guild opted out of.
    assert granted_calls[0] > voice_tracker.VOICE_XP_DAILY_CAP_DEFAULT

    # And the cap table was never touched for this guild/member.
    assert await db.add_voice_xp_capped(guild_id, "u1", proposed_xp=10, daily_cap=750) == 10


async def test_flush_member_uses_the_guilds_own_configured_cap_amount(guild_id, monkeypatch):
    await db.update_guild_settings(guild_id, voice_xp_cap_amount=200)

    granted_calls = []

    async def fake_grant_xp(bot, gid, uid, username, amount):
        granted_calls.append(amount)

    monkeypatch.setattr(voice_tracker.leveling, "grant_xp", fake_grant_xp)

    bot = make_bot()
    now = datetime.now(timezone.utc)
    voice_tracker._accrual_start[(guild_id, "u1")] = now - timedelta(hours=5)

    await voice_tracker._flush_member(bot, guild_id, "u1", now, keep_earning=False)

    assert len(granted_calls) == 1
    assert granted_calls[0] <= 200
    assert granted_calls[0] < voice_tracker.VOICE_XP_DAILY_CAP_DEFAULT
