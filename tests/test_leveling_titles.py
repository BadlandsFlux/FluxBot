"""Level titles: title_for_level()'s tier lookup, and that grant_xp()
substitutes {title} into a guild's level-up message the same way it
already does {user}/{username}/{level}.
"""
from __future__ import annotations

from bot.commands import Bot
from bot.modules import leveling
from common import db


def test_title_for_level_level_zero_is_the_first_tier():
    assert leveling.title_for_level(0) == leveling.LEVEL_TITLES[0][1]


def test_title_for_level_just_below_a_threshold_stays_on_the_lower_tier():
    assert leveling.title_for_level(9) == leveling.LEVEL_TITLES[0][1]
    assert leveling.title_for_level(10) == leveling.LEVEL_TITLES[1][1]


def test_title_for_level_matches_the_highest_threshold_reached():
    # Pick a tier in the middle and confirm both ends of its range.
    threshold, title = leveling.LEVEL_TITLES[5]
    next_threshold = leveling.LEVEL_TITLES[6][0]
    assert leveling.title_for_level(threshold) == title
    assert leveling.title_for_level(next_threshold - 1) == title


def test_title_for_level_caps_at_the_top_tier_past_250():
    top_title = leveling.LEVEL_TITLES[-1][1]
    assert leveling.title_for_level(250) == top_title
    assert leveling.title_for_level(999) == top_title


def test_level_titles_cover_up_to_250_in_ascending_order():
    thresholds = [t for t, _ in leveling.LEVEL_TITLES]
    assert thresholds == sorted(thresholds)
    assert thresholds[0] == 0
    assert thresholds[-1] == 250


async def test_grant_xp_substitutes_title_into_the_level_up_message(guild_id):
    await db.update_guild_settings(
        guild_id,
        leveling_enabled=True,
        level_up_channel_id="chan1",
        level_up_message="GG {user} ({username})! Level {level} - {title}",
    )

    sent = []

    async def fake_send_message(channel_id, content=None, **kw):
        sent.append(content)
        return {"id": "1"}

    bot = Bot("test-token")
    bot.rest.send_message = fake_send_message
    bot.rest.mention_only = lambda uid: {"parse": [], "users": [uid]}
    bot.rest.add_member_role = lambda *a, **kw: None  # should not be reached: no level_role configured

    # Enough to guarantee at least one level-up (level 0->1 costs 100 XP).
    await leveling.grant_xp(bot, guild_id, "u1", "tester", amount=200)

    row = await db.get_level(guild_id, "u1")
    assert len(sent) == 1
    assert f"Level {row['level']}" in sent[0]
    assert leveling.title_for_level(row["level"]) in sent[0]
    assert "tester" in sent[0]
