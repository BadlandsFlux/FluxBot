"""Tests for !trivia: the shared answer-shuffle (bot/modules/trivia.py's
_shuffle_answer), the embed's countdown/reward fields, the one-round-per
-server limit, and the per-member daily XP cap (db.add_trivia_xp_capped,
wired into bot/scheduler.py's _close_trivia).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bot.modules.trivia as trivia_mod
from bot import scheduler
from bot.commands import Bot
from common import db


# ------------------------------------------------------------- shuffling --

def test_shuffle_answer_places_correct_in_every_slot_eventually():
    # Before this fix, the local QUESTIONS bank's hand-authored option
    # order was used as-is -- never shuffled -- so the correct answer sat
    # at whatever index it happened to be written at. 400 draws makes a
    # false failure here astronomically unlikely if the shuffle is real.
    seen = {_shuffle_index() for _ in range(400)}
    assert seen == {0, 1, 2, 3}


def _shuffle_index():
    options, idx = trivia_mod._shuffle_answer("correct", ["a", "b", "c"])
    assert options[idx] == "correct"
    return idx


def test_random_local_question_is_no_longer_skewed_toward_the_same_slot():
    # The QUESTIONS bank itself never authored "correct" as the first
    # option (index 0) -- without shuffling at selection time, index 0
    # would never appear here no matter how many draws.
    seen = {trivia_mod._random_local_question()["correct"] for _ in range(400)}
    assert 0 in seen


def test_random_local_question_options_still_contain_the_correct_answer():
    q = trivia_mod._random_local_question()
    assert q["options"][q["correct"]]
    assert len(q["options"]) == 4
    assert q["category"] is None and q["difficulty"] is None


# -------------------------------------------------------------- dispatch --

def make_bot():
    bot = Bot("test-token")
    trivia_mod.register(bot)
    return bot


FIXED_QUESTION = {
    "q": "What's 2+2?", "options": ["3", "4", "5", "6"], "correct": 1,
    "category": "Science", "difficulty": "easy",
}


async def run_trivia(bot, guild_id, channel_id="chan1", author_id="u1", monkeypatch=None):
    sent_embeds = []
    replies = []
    added_reactions = []

    async def fake_send_message(cid, content=None, embeds=None, **kw):
        if embeds:
            sent_embeds.append(embeds[0])
        else:
            replies.append(content)
        return {"id": f"msg-{len(sent_embeds)}"}

    async def fake_add_reaction(cid, message_id, emoji):
        added_reactions.append(emoji)

    async def fake_get_guild(gid):
        return {"id": gid, "owner_id": "someone-else", "roles": []}

    async def fake_get_member(gid, user_id):
        return {"user": {"id": user_id}, "roles": []}

    bot.rest.send_message = fake_send_message
    bot.rest.add_reaction = fake_add_reaction
    bot.rest.get_guild = fake_get_guild
    bot.rest.get_guild_member = fake_get_member

    if monkeypatch is not None:
        monkeypatch.setattr(trivia_mod, "_fetch_question_from_api", _fake_fetch_none)
        monkeypatch.setattr(trivia_mod, "_random_local_question", lambda: dict(FIXED_QUESTION))

    message = {
        "content": "!trivia", "author": {"id": author_id, "username": "tester"},
        "guild_id": guild_id, "channel_id": channel_id,
    }
    await bot._on_message(message)

    return sent_embeds, replies, added_reactions


async def _fake_fetch_none():
    return None


async def test_trivia_embed_has_countdown_and_reward_fields(guild_id, monkeypatch):
    bot = make_bot()
    sent_embeds, replies, added_reactions = await run_trivia(bot, guild_id, monkeypatch=monkeypatch)

    assert replies == []
    assert len(sent_embeds) == 1
    embed = sent_embeds[0]
    field_names = [f["name"] for f in embed["fields"]]
    assert "Closes" in field_names
    assert "Reward" in field_names
    assert "Category" in field_names

    closes_field = next(f for f in embed["fields"] if f["name"] == "Closes")
    assert closes_field["value"].startswith("<t:") and closes_field["value"].endswith(":R>")

    reward_field = next(f for f in embed["fields"] if f["name"] == "Reward")
    assert reward_field["value"] == f"+{trivia_mod.XP_REWARD} XP"

    assert embed["color"] == trivia_mod._DIFFICULTY_COLORS["easy"]
    assert len(added_reactions) == 4


async def test_second_trivia_in_the_same_server_is_rejected_while_one_is_open(guild_id, monkeypatch):
    bot = make_bot()
    sent_embeds, replies, _ = await run_trivia(bot, guild_id, monkeypatch=monkeypatch)
    assert len(sent_embeds) == 1

    sent_embeds2, replies2, _ = await run_trivia(bot, guild_id, monkeypatch=monkeypatch)
    assert sent_embeds2 == []
    assert len(replies2) == 1
    assert "already running" in replies2[0]


async def test_trivia_allowed_again_in_a_different_server(guild_id, second_guild_id, monkeypatch):
    bot = make_bot()
    await run_trivia(bot, guild_id, monkeypatch=monkeypatch)
    sent_embeds2, replies2, _ = await run_trivia(bot, second_guild_id, monkeypatch=monkeypatch)
    assert len(sent_embeds2) == 1
    assert replies2 == []


# -------------------------------------------------------------- XP cap --

async def test_add_trivia_xp_capped_grants_up_to_the_cap(guild_id):
    granted = await db.add_trivia_xp_capped(guild_id, "u1", proposed_xp=100, daily_cap=150)
    assert granted == 100
    granted = await db.add_trivia_xp_capped(guild_id, "u1", proposed_xp=100, daily_cap=150)
    assert granted == 50
    granted = await db.add_trivia_xp_capped(guild_id, "u1", proposed_xp=25, daily_cap=150)
    assert granted == 0


async def test_add_trivia_xp_capped_is_per_member_and_per_guild(guild_id):
    await db.add_trivia_xp_capped(guild_id, "u1", proposed_xp=150, daily_cap=150)
    granted = await db.add_trivia_xp_capped(guild_id, "u2", proposed_xp=100, daily_cap=150)
    assert granted == 100


async def test_add_trivia_xp_capped_zero_or_negative_proposed_is_a_noop(guild_id):
    assert await db.add_trivia_xp_capped(guild_id, "u1", proposed_xp=0, daily_cap=150) == 0
    assert await db.add_trivia_xp_capped(guild_id, "u1", proposed_xp=-5, daily_cap=150) == 0


def make_scheduler_bot(winner_ids):
    bot = Bot("test-token")
    bot.gateway.user = {"id": "bot-id"}

    async def fake_get_reaction_users(channel_id, message_id, emoji):
        return [{"id": uid} for uid in winner_ids]

    async def fake_edit_message(channel_id, message_id, **kw):
        return {"id": message_id}

    async def fake_get_member(gid, uid, fresh=False):
        return {"user": {"id": uid, "username": "tester"}, "roles": []}

    bot.rest.get_reaction_users = fake_get_reaction_users
    bot.rest.edit_message = fake_edit_message
    bot.get_member = fake_get_member
    return bot


async def _seed_due_trivia(guild_id, correct_index=1) -> None:
    close_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.add_trivia_question(
        guild_id, "chan1", "msg1", "What's 2+2?", ["3", "4", "5", "6"], correct_index, close_at,
    )


async def test_close_trivia_caps_a_winners_xp_for_the_day(guild_id, monkeypatch):
    await _seed_due_trivia(guild_id)
    await db.update_guild_settings(guild_id, trivia_xp_cap_amount=10)  # smaller than XP_REWARD

    granted_calls = []

    async def fake_grant_xp(bot, gid, uid, username, amount):
        granted_calls.append(amount)

    monkeypatch.setattr(scheduler.leveling, "grant_xp", fake_grant_xp)

    bot = make_scheduler_bot(["winner1"])
    await scheduler._close_trivia(bot)

    assert granted_calls == [10]


async def test_close_trivia_does_not_cap_when_guild_disables_it(guild_id, monkeypatch):
    await _seed_due_trivia(guild_id)
    await db.update_guild_settings(guild_id, trivia_xp_cap_enabled=False, trivia_xp_cap_amount=10)

    granted_calls = []

    async def fake_grant_xp(bot, gid, uid, username, amount):
        granted_calls.append(amount)

    monkeypatch.setattr(scheduler.leveling, "grant_xp", fake_grant_xp)

    bot = make_scheduler_bot(["winner1"])
    await scheduler._close_trivia(bot)

    assert granted_calls == [trivia_mod.XP_REWARD]
