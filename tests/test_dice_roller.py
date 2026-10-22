"""Tests for the D&D-oriented !roll command: multi-group dice notation
(count/sides/keep-highest-or-lowest/modifier), the bare-!roll standard
polyhedral set, and the reaction-based reroll (whole roll or a single
group) built on the same MESSAGE_REACTION_ADD pattern as !help paging.
"""
from __future__ import annotations

import random

import pytest

import bot.modules.fun as fun_mod
from bot.commands import Bot


@pytest.fixture(autouse=True)
def _clear_roll_sessions():
    fun_mod._roll_sessions.clear()
    yield
    fun_mod._roll_sessions.clear()


# --------------------------------------------------------------- parsing --

def test_parse_simple_group():
    group = fun_mod._parse_dice_spec("2d6")
    assert group.count == 2 and group.sides == 6
    assert group.keep_mode is None and group.modifier == 0


def test_parse_modifier():
    group = fun_mod._parse_dice_spec("1d20+5")
    assert group.count == 1 and group.sides == 20 and group.modifier == 5


def test_parse_negative_modifier():
    group = fun_mod._parse_dice_spec("3d4-2")
    assert group.modifier == -2


def test_parse_keep_highest():
    group = fun_mod._parse_dice_spec("4d6kh3")
    assert group.keep_mode == "kh" and group.keep_n == 3


def test_parse_keep_lowest_case_insensitive():
    group = fun_mod._parse_dice_spec("2D20KL1")
    assert group.count == 2 and group.sides == 20
    assert group.keep_mode == "kl" and group.keep_n == 1


def test_parse_advantage_expands_to_2d20kh1():
    group = fun_mod._parse_dice_spec("adv")
    assert group.count == 2 and group.sides == 20
    assert group.keep_mode == "kh" and group.keep_n == 1
    assert group.label == "adv"  # the field name shows what was typed


def test_parse_disadvantage_with_modifier():
    group = fun_mod._parse_dice_spec("disadvantage+2")
    assert group.keep_mode == "kl" and group.keep_n == 1 and group.modifier == 2


def test_parse_bare_d_defaults_count_to_one():
    group = fun_mod._parse_dice_spec("d20")
    assert group.count == 1 and group.sides == 20


@pytest.mark.parametrize("spec", ["", "notdice", "2x6", "d", "6d"])
def test_parse_rejects_bad_format(spec):
    assert isinstance(fun_mod._parse_dice_spec(spec), str)


def test_parse_rejects_too_many_dice():
    assert isinstance(fun_mod._parse_dice_spec("101d6"), str)


def test_parse_rejects_too_few_dice():
    assert isinstance(fun_mod._parse_dice_spec("0d6"), str)


def test_parse_allows_dice_count_cap():
    group = fun_mod._parse_dice_spec("100d6")
    assert group.count == 100


def test_parse_rejects_sides_out_of_range():
    assert isinstance(fun_mod._parse_dice_spec("1d1"), str)
    assert isinstance(fun_mod._parse_dice_spec("1d1001"), str)


def test_parse_rejects_modifier_out_of_range():
    assert isinstance(fun_mod._parse_dice_spec("1d6+1001"), str)


def test_parse_rejects_keep_n_greater_than_count():
    assert isinstance(fun_mod._parse_dice_spec("2d6kh3"), str)


def test_parse_rejects_keep_n_zero():
    assert isinstance(fun_mod._parse_dice_spec("2d6kh0"), str)


# ---------------------------------------------------------- DiceGroup math --

def test_total_sums_all_dice_when_no_keep_mode(monkeypatch):
    values = iter([4, 6])
    monkeypatch.setattr(random, "randint", lambda a, b: next(values))
    group = fun_mod._parse_dice_spec("2d6")
    assert group.rolls == [4, 6]
    assert group.total == 10


def test_total_applies_modifier():
    group = fun_mod._parse_dice_spec("2d6+3")
    assert group.total == sum(group.rolls) + 3


def test_keep_highest_drops_the_rest(monkeypatch):
    values = iter([3, 5, 1, 6])
    monkeypatch.setattr(random, "randint", lambda a, b: next(values))
    group = fun_mod._parse_dice_spec("4d6kh3")
    assert group.rolls == [3, 5, 1, 6]
    assert group.total == 3 + 5 + 6  # drops the 1


def test_keep_lowest_drops_the_rest(monkeypatch):
    values = iter([3, 5, 1, 6])
    monkeypatch.setattr(random, "randint", lambda a, b: next(values))
    group = fun_mod._parse_dice_spec("4d6kl1")
    assert group.total == 1


def test_format_marks_dropped_dice_with_strikethrough(monkeypatch):
    values = iter([3, 5, 1, 6])
    monkeypatch.setattr(random, "randint", lambda a, b: next(values))
    group = fun_mod._parse_dice_spec("4d6kh3")
    text = group.format()
    assert "~~1~~" in text
    assert "~~3~~" not in text and "~~5~~" not in text and "~~6~~" not in text


def test_format_highlights_nat20_and_nat1(monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 20)
    nat20 = fun_mod._parse_dice_spec("1d20")
    assert "\U0001F4A5" in nat20.format()

    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    nat1 = fun_mod._parse_dice_spec("1d20")
    assert "\U0001F4A2" in nat1.format()


def test_format_truncates_large_counts_but_keeps_kept_dice_visible(monkeypatch):
    # 100 dice, keep the single highest; the kept die must still show up in
    # the first DISPLAY_CAP pips even though it's buried deep in roll order.
    rolls = [1] * 99 + [6]
    values = iter(rolls)
    monkeypatch.setattr(random, "randint", lambda a, b: next(values))
    group = fun_mod._parse_dice_spec("100d6kh1")
    text = group.format()
    assert "6" in text
    assert "more" in text
    assert group.total == 6


def test_reroll_regenerates_rolls():
    group = fun_mod._parse_dice_spec("5d6")
    first = list(group.rolls)
    # Not guaranteed to differ, but rolls must be freshly generated (same
    # length, drawn the same way) rather than stale state reused.
    group.reroll()
    assert len(group.rolls) == len(first)
    assert all(1 <= r <= 6 for r in group.rolls)


# -------------------------------------------------------------- dispatch --

def make_bot():
    bot = Bot("test-token")
    fun_mod.register(bot)
    return bot


async def run_roll(bot, guild_id, content, author_id="u1"):
    sent_embeds = []
    added_reactions = []
    replies = []

    async def fake_send_message(channel_id, content=None, embeds=None, **kw):
        if embeds:
            sent_embeds.append(embeds[0])
        else:
            replies.append(content)
        return {"id": "msg1"}

    async def fake_get_guild(gid):
        return {"id": gid, "owner_id": "someone-else", "roles": []}

    async def fake_get_member(gid, user_id):
        return {"user": {"id": user_id}, "roles": []}

    async def fake_add_reaction(channel_id, message_id, emoji):
        added_reactions.append(emoji)

    bot.rest.send_message = fake_send_message
    bot.rest.get_guild = fake_get_guild
    bot.rest.get_guild_member = fake_get_member
    bot.rest.add_reaction = fake_add_reaction

    message = {
        "content": content, "author": {"id": author_id, "username": "tester"},
        "guild_id": guild_id, "channel_id": "chan1",
    }
    await bot._on_message(message)
    return sent_embeds, added_reactions, replies


async def dispatch_reaction(bot, **data):
    for handler in bot.gateway._handlers.get("MESSAGE_REACTION_ADD", []):
        await handler(data)


async def test_bare_roll_shows_standard_dice_set(guild_id):
    bot = make_bot()
    sent_embeds, added_reactions, replies = await run_roll(bot, guild_id, "!roll")

    assert replies == []
    assert len(sent_embeds) == 1
    embed = sent_embeds[0]
    assert embed["title"] == "🎲 Standard dice set"
    assert [f["name"] for f in embed["fields"]] == fun_mod.STANDARD_DICE
    assert fun_mod.REROLL_ALL_EMOJI in added_reactions
    assert added_reactions.count(fun_mod.REROLL_ALL_EMOJI) == 1
    # One number reaction per standard die, since there are 7 > 1 groups.
    assert len(added_reactions) == 1 + len(fun_mod.STANDARD_DICE)


async def test_single_group_roll_gets_no_number_reactions(guild_id):
    bot = make_bot()
    sent_embeds, added_reactions, replies = await run_roll(bot, guild_id, "!roll 2d6")

    assert replies == []
    embed = sent_embeds[0]
    assert embed["title"] == "🎲 Dice roll"
    assert len(embed["fields"]) == 1
    assert embed["fields"][0]["name"] == "2d6"
    assert "description" not in embed  # no grand total needed for one group
    assert added_reactions == [fun_mod.REROLL_ALL_EMOJI]


async def test_multi_group_roll_shows_grand_total_and_numbered_reactions(guild_id):
    bot = make_bot()
    sent_embeds, added_reactions, replies = await run_roll(bot, guild_id, "!roll 2d6 1d20+5")

    assert replies == []
    embed = sent_embeds[0]
    assert len(embed["fields"]) == 2
    assert embed["fields"][0]["name"] == "2d6"
    assert embed["fields"][1]["name"] == "1d20+5"
    assert "Grand total" in embed["description"]
    assert added_reactions == [fun_mod.REROLL_ALL_EMOJI, fun_mod.NUMBER_EMOJI[0], fun_mod.NUMBER_EMOJI[1]]


async def test_invalid_spec_replies_with_error_and_sends_no_embed(guild_id):
    bot = make_bot()
    sent_embeds, added_reactions, replies = await run_roll(bot, guild_id, "!roll notdice")

    assert sent_embeds == []
    assert added_reactions == []
    assert len(replies) == 1 and "Can't parse" in replies[0]


async def test_too_many_groups_rejected(guild_id):
    bot = make_bot()
    too_many = " ".join(["1d6"] * (fun_mod.MAX_GROUPS + 1))
    sent_embeds, added_reactions, replies = await run_roll(bot, guild_id, f"!roll {too_many}")

    assert sent_embeds == []
    assert replies == [f"Keep it to {fun_mod.MAX_GROUPS} dice groups or fewer per roll."]


async def test_reroll_all_reaction_rerolls_every_group(guild_id, monkeypatch):
    bot = make_bot()
    await run_roll(bot, guild_id, "!roll 2d6 1d20")
    session = fun_mod._roll_sessions["msg1"]
    original_rolls = [list(g.rolls) for g in session.groups]

    edited = []

    async def fake_edit_message(channel_id, message_id, content=None, embeds=None, **kw):
        edited.append(embeds[0])

    async def fake_remove_user_reaction(channel_id, message_id, emoji, user_id):
        pass

    bot.rest.edit_message = fake_edit_message
    bot.rest.remove_user_reaction = fake_remove_user_reaction

    monkeypatch.setattr(random, "randint", lambda a, b: a)  # force a different, deterministic roll
    await dispatch_reaction(bot, message_id="msg1", emoji={"name": fun_mod.REROLL_ALL_EMOJI},
                             user_id="u1", guild_id=guild_id)

    assert len(edited) == 1
    for group, before in zip(session.groups, original_rolls):
        assert group.rolls == [1] * len(before)  # randint(a, b) -> a == 1 every time


async def test_reroll_single_group_leaves_the_other_untouched(guild_id, monkeypatch):
    bot = make_bot()
    await run_roll(bot, guild_id, "!roll 2d6 1d20")
    session = fun_mod._roll_sessions["msg1"]
    second_group_before = list(session.groups[1].rolls)

    async def fake_edit_message(*a, **kw):
        pass

    async def fake_remove_user_reaction(*a, **kw):
        pass

    bot.rest.edit_message = fake_edit_message
    bot.rest.remove_user_reaction = fake_remove_user_reaction

    monkeypatch.setattr(random, "randint", lambda a, b: a)
    await dispatch_reaction(bot, message_id="msg1", emoji={"name": fun_mod.NUMBER_EMOJI[0]},
                             user_id="u1", guild_id=guild_id)

    assert session.groups[0].rolls == [1, 1]
    assert session.groups[1].rolls == second_group_before  # untouched


async def test_reroll_reaction_ignores_other_users(guild_id):
    bot = make_bot()
    await run_roll(bot, guild_id, "!roll 2d6")
    session = fun_mod._roll_sessions["msg1"]
    before = list(session.groups[0].rolls)

    edited = []

    async def fake_edit_message(*a, **kw):
        edited.append(1)

    bot.rest.edit_message = fake_edit_message

    await dispatch_reaction(bot, message_id="msg1", emoji={"name": fun_mod.REROLL_ALL_EMOJI},
                             user_id="someone-else-entirely", guild_id=guild_id)

    assert edited == []
    assert session.groups[0].rolls == before


async def test_reroll_reaction_ignores_unrelated_emoji(guild_id):
    bot = make_bot()
    await run_roll(bot, guild_id, "!roll 2d6")

    edited = []

    async def fake_edit_message(*a, **kw):
        edited.append(1)

    bot.rest.edit_message = fake_edit_message

    await dispatch_reaction(bot, message_id="msg1", emoji={"name": "\U0001F44D"},
                             user_id="u1", guild_id=guild_id)
    assert edited == []


async def test_reroll_reaction_on_unknown_message_is_noop(guild_id):
    bot = make_bot()
    await dispatch_reaction(bot, message_id="not-a-real-roll-message",
                             emoji={"name": fun_mod.REROLL_ALL_EMOJI}, user_id="u1", guild_id=guild_id)
    # No exception, nothing to assert beyond "didn't crash".


async def test_single_group_roll_ignores_number_reaction(guild_id):
    # With only one group there's no number reaction seeded, so a number
    # emoji (e.g. echoed from some other message) must not be treated as a
    # valid reroll trigger.
    bot = make_bot()
    await run_roll(bot, guild_id, "!roll 2d6")

    edited = []

    async def fake_edit_message(*a, **kw):
        edited.append(1)

    bot.rest.edit_message = fake_edit_message

    await dispatch_reaction(bot, message_id="msg1", emoji={"name": fun_mod.NUMBER_EMOJI[0]},
                             user_id="u1", guild_id=guild_id)
    assert edited == []
