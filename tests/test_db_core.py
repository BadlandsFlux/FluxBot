"""Integration tests for common/db.py against a real Postgres instance.

Each test gets a fresh `guild_id` (see conftest.py), so these can run in
any order and don't need to clean up their own guild-scoped rows, only
the guild_id fixture's own teardown does (via ON DELETE CASCADE).
"""
from __future__ import annotations

from common import db


async def test_upsert_and_get_guild(guild_id):
    row = await db.get_guild(guild_id)
    assert row is not None
    assert row["command_prefix"] == "!"


async def test_update_guild_settings_only_touches_allowed_fields(guild_id):
    await db.update_guild_settings(guild_id, command_prefix="?", not_a_real_column="ignored")
    row = await db.get_guild(guild_id)
    assert row["command_prefix"] == "?"


async def test_autoroles_add_list_remove(guild_id):
    assert await db.list_autoroles(guild_id) == []
    await db.add_autorole(guild_id, "111")
    await db.add_autorole(guild_id, "222")
    roles = await db.list_autoroles(guild_id)
    assert set(roles) == {"111", "222"}

    await db.remove_autorole(guild_id, "111")
    assert await db.list_autoroles(guild_id) == ["222"]


async def test_autoroles_add_is_idempotent(guild_id):
    await db.add_autorole(guild_id, "111")
    await db.add_autorole(guild_id, "111")
    assert await db.list_autoroles(guild_id) == ["111"]


async def test_reaction_roles_add_list_remove(guild_id):
    await db.add_reaction_role(guild_id, "chan1", "msg1", "🎉", "role1")
    rows = await db.list_reaction_roles(guild_id)
    assert len(rows) == 1
    assert rows[0]["emoji"] == "🎉"
    assert rows[0]["role_id"] == "role1"

    fetched = await db.get_reaction_role(guild_id, "msg1", "🎉")
    assert fetched is not None
    assert fetched["channel_id"] == "chan1"

    await db.remove_reaction_role(guild_id, rows[0]["id"])
    assert await db.list_reaction_roles(guild_id) == []


async def test_reaction_role_is_scoped_per_guild(guild_id):
    # A second, unrelated guild shouldn't see the first guild's mapping,
    # and vice versa, this is exactly the cross-guild hijack class of bug
    # fixed earlier this project's history.
    other_guild_id = guild_id + "1"
    await db.upsert_guild(other_guild_id, name="other pytest guild")
    try:
        await db.add_reaction_role(guild_id, "chan1", "msg1", "🎉", "role1")
        assert await db.get_reaction_role(other_guild_id, "msg1", "🎉") is None
    finally:
        await db.pool().execute("DELETE FROM guilds WHERE guild_id=$1", other_guild_id)


async def test_warnings_add_count_list_clear(guild_id):
    _, count1 = await db.add_warning_and_count(guild_id, "user1", "mod1", "first offense")
    assert count1 == 1
    _, count2 = await db.add_warning_and_count(guild_id, "user1", "mod1", "second offense")
    assert count2 == 2

    rows = await db.list_warnings(guild_id, "user1")
    assert len(rows) == 2
    assert all(r["active"] for r in rows)

    cleared = await db.clear_warnings(guild_id, "user1")
    assert cleared == 2
    rows = await db.list_warnings(guild_id, "user1")
    assert all(not r["active"] for r in rows)


async def test_reminders_add_list_count_remove(guild_id):
    from datetime import datetime, timedelta, timezone

    remind_at = datetime.now(timezone.utc) + timedelta(hours=1)
    assert await db.count_pending_reminders(guild_id, "user1") == 0

    reminder_id = await db.add_reminder(guild_id, "chan1", "user1", "take out the trash", remind_at)
    assert await db.count_pending_reminders(guild_id, "user1") == 1

    rows = await db.list_reminders_for_user(guild_id, "user1")
    assert len(rows) == 1
    assert rows[0]["content"] == "take out the trash"

    # Can't be cancelled by someone else.
    assert await db.remove_reminder(reminder_id, "someone-else") is False
    assert await db.remove_reminder(reminder_id, "user1") is True
    assert await db.count_pending_reminders(guild_id, "user1") == 0
