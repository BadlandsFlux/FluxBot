"""New achievement categories: warnings, reports, and tags each grant a
badge once the member crosses the configured threshold, and stay granted
(no double-insert, no un-granting) once they have it.
"""
from __future__ import annotations

from bot.modules import achievements
from common import db


async def _earned_keys(guild_id, user_id):
    rows = await db.list_achievements(guild_id, user_id)
    return {r["key"] for r in rows}


async def test_check_warning_achievements_grants_at_the_repeat_offender_threshold(guild_id):
    for _ in range(3):
        await db.add_warning_and_count(guild_id, "u1", "mod1", "being a menace")
    await achievements.check_warning_achievements(guild_id, "u1")
    assert "repeat_offender" in await _earned_keys(guild_id, "u1")
    assert "menace" not in await _earned_keys(guild_id, "u1")


async def test_check_warning_achievements_survives_cleared_warnings(guild_id):
    for _ in range(3):
        await db.add_warning_and_count(guild_id, "u2", "mod1", "reason")
    await db.pool().execute("UPDATE warnings SET active=FALSE WHERE guild_id=$1 AND user_id=$2", guild_id, "u2")
    await achievements.check_warning_achievements(guild_id, "u2")
    assert "repeat_offender" in await _earned_keys(guild_id, "u2")


async def test_check_warning_achievements_below_threshold_grants_nothing(guild_id):
    await db.add_warning_and_count(guild_id, "u3", "mod1", "reason")
    await achievements.check_warning_achievements(guild_id, "u3")
    assert await _earned_keys(guild_id, "u3") == set()


async def test_check_report_achievements_grants_whistleblower_at_five(guild_id):
    for i in range(5):
        await db.create_report(guild_id, "reporter1", f"bug {i}", "chan1", f"msg{i}")
    await achievements.check_report_achievements(guild_id, "reporter1")
    assert "whistleblower" in await _earned_keys(guild_id, "reporter1")


async def test_check_report_achievements_only_counts_this_reporter(guild_id):
    for i in range(5):
        await db.create_report(guild_id, "reporter2", f"bug {i}", "chan1", f"msg{i}")
    await db.create_report(guild_id, "someone_else", "unrelated bug", "chan1", "msg99")
    await achievements.check_report_achievements(guild_id, "someone_else")
    assert await _earned_keys(guild_id, "someone_else") == set()


async def test_check_tag_achievements_grants_wordsmith_at_five(guild_id):
    for i in range(5):
        await db.add_tag(guild_id, f"tag{i}", "content", "author1")
    await achievements.check_tag_achievements(guild_id, "author1")
    assert "wordsmith" in await _earned_keys(guild_id, "author1")


async def test_check_tag_achievements_only_counts_tags_created_by_this_user(guild_id):
    for i in range(4):
        await db.add_tag(guild_id, f"tagA{i}", "content", "author2")
    await db.add_tag(guild_id, "tagB", "content", "author3")
    await achievements.check_tag_achievements(guild_id, "author2")
    assert await _earned_keys(guild_id, "author2") == set()


async def test_grant_achievement_is_idempotent_across_repeated_checks(guild_id):
    for _ in range(3):
        await db.add_warning_and_count(guild_id, "u4", "mod1", "reason")
    await achievements.check_warning_achievements(guild_id, "u4")
    await achievements.check_warning_achievements(guild_id, "u4")
    rows = await db.list_achievements(guild_id, "u4")
    assert len([r for r in rows if r["key"] == "repeat_offender"]) == 1
