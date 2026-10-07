"""Tests for !help: the embed must stay within Fluxer/Discord's per-field
(1024 char) and per-embed (6000 char, 25 field) limits, show only the
commands the invoking member can actually run, and support paging through
multiple categories via reaction clicks.
"""
from __future__ import annotations

import dataclasses
import importlib
import pkgutil

import pytest

import bot.modules as modules_pkg
import bot.modules.utility as utility_mod
from bot.commands import Bot
from bot.permissions import PERM_BAN_MEMBERS
from common.config import config

EMBED_FIELD_VALUE_LIMIT = 1024
EMBED_FIELD_NAME_LIMIT = 256
EMBED_FIELD_COUNT_LIMIT = 25
EMBED_TOTAL_CHAR_LIMIT = 6000


@pytest.fixture(autouse=True)
def _clear_help_sessions():
    # _help_sessions is a module-level BoundedDict so paginated !help state
    # survives across reaction clicks; without clearing it, one test's
    # session (keyed by the same fake message id tests use) leaks into the
    # next.
    utility_mod._help_sessions.clear()
    yield
    utility_mod._help_sessions.clear()


def make_bot_with_all_modules():
    bot = Bot("test-token")
    for modinfo in pkgutil.iter_modules(modules_pkg.__path__):
        mod = importlib.import_module(f"bot.modules.{modinfo.name}")
        if hasattr(mod, "register"):
            mod.register(bot)
    return bot


def assert_embed_within_limits(embed: dict) -> None:
    fields = embed["fields"]
    assert len(fields) <= EMBED_FIELD_COUNT_LIMIT
    total = len(embed.get("title", "")) + len(embed.get("description", "")) + len(embed.get("footer", {}).get("text", ""))
    for f in fields:
        assert len(f["name"]) <= EMBED_FIELD_NAME_LIMIT
        assert len(f["value"]) <= EMBED_FIELD_VALUE_LIMIT
        total += len(f["name"]) + len(f["value"])
    assert total <= EMBED_TOTAL_CHAR_LIMIT


async def run_help(bot, guild_id, author_id="u1", owner_id="owner1"):
    """Dispatches !help and returns (sent_embeds_log, add_reaction_log, message_id)."""
    sent_embeds = []
    added_reactions = []

    async def fake_send_message(channel_id, content=None, embeds=None, **kw):
        sent_embeds.append(embeds)
        return {"id": "msg1"}

    async def fake_get_guild(gid):
        return {"id": gid, "owner_id": owner_id, "roles": []}

    async def fake_get_member(gid, user_id):
        return {"user": {"id": user_id}, "roles": []}

    async def fake_add_reaction(channel_id, message_id, emoji):
        added_reactions.append(emoji)

    bot.rest.send_message = fake_send_message
    bot.rest.get_guild = fake_get_guild
    bot.rest.get_guild_member = fake_get_member
    bot.rest.add_reaction = fake_add_reaction

    message = {
        "content": "!help", "author": {"id": author_id, "username": "tester"},
        "guild_id": guild_id, "channel_id": "chan1",
    }
    await bot._on_message(message)
    return sent_embeds, added_reactions


async def dispatch_reaction(bot, **data):
    for handler in bot.gateway._handlers.get("MESSAGE_REACTION_ADD", []):
        await handler(data)


async def test_help_embed_stays_within_discord_field_limits(guild_id, monkeypatch):
    # The fullest possible view (guild owner, and bot owner so owner_only
    # commands show too) is the one most likely to overflow a field/embed,
    # since nothing gets filtered out.
    monkeypatch.setattr(utility_mod, "config", dataclasses.replace(config, owner_id="owner1"))
    bot = make_bot_with_all_modules()
    sent_embeds, _ = await run_help(bot, guild_id, author_id="owner1", owner_id="owner1")

    assert len(sent_embeds) == 1
    for embed in sent_embeds[0]:
        assert_embed_within_limits(embed)


def test_visible_commands_hides_gated_and_owner_only_from_a_regular_member(monkeypatch):
    monkeypatch.setattr(utility_mod, "config", dataclasses.replace(config, owner_id="the-owner"))
    bot = make_bot_with_all_modules()
    # Neither the guild owner nor the configured bot owner, and holds no
    # roles, so every permission-gated and owner-only command should be
    # filtered out; ordinary Everyone-level commands should still show.
    guild = {"id": "g1", "owner_id": "someone-else", "roles": []}
    member = {"user": {"id": "regular-user"}, "roles": []}
    visible_names = {c.name for c in utility_mod._visible_commands(bot, guild, member, "regular-user")}

    assert "ban" not in visible_names
    assert "kick" not in visible_names
    assert "voicedebug" not in visible_names  # owner_only
    assert "ping" in visible_names


def test_visible_commands_guild_owner_sees_moderation_but_not_bot_owner_only(monkeypatch):
    monkeypatch.setattr(utility_mod, "config", dataclasses.replace(config, owner_id="nobody"))
    bot = make_bot_with_all_modules()
    guild = {"id": "g1", "owner_id": "owner1", "roles": []}
    member = {"user": {"id": "owner1"}, "roles": []}
    visible_names = {c.name for c in utility_mod._visible_commands(bot, guild, member, "owner1")}

    assert "ban" in visible_names  # guild-owner bypass in is_moderator()
    assert "voicedebug" not in visible_names  # still not the configured bot owner


async def test_help_single_page_sends_no_nav_reactions(guild_id, monkeypatch):
    monkeypatch.setattr(utility_mod, "config", dataclasses.replace(config, owner_id="nobody"))
    bot = Bot("test-token")
    # Register only utility.py: with nothing else loaded, a regular member
    # should only see help/ping, a single category/page.
    utility_mod.register(bot)
    sent_embeds, added_reactions = await run_help(bot, guild_id, author_id="u1", owner_id="someone-else")

    assert len(sent_embeds) == 1
    assert added_reactions == []
    assert len(utility_mod._help_sessions) == 0


async def test_help_pagination_adds_nav_reactions_and_pages_through(guild_id, monkeypatch):
    monkeypatch.setattr(utility_mod, "config", dataclasses.replace(config, owner_id="owner1"))
    bot = make_bot_with_all_modules()
    sent_embeds, added_reactions = await run_help(bot, guild_id, author_id="owner1", owner_id="owner1")

    assert added_reactions == [utility_mod.HELP_PREV_EMOJI, utility_mod.HELP_NEXT_EMOJI]
    session = utility_mod._help_sessions["msg1"]
    assert session.page == 0
    total_pages = len(session.pages)
    assert total_pages > 1

    edited = []

    async def fake_edit_message(channel_id, message_id, content=None, embeds=None, **kw):
        edited.append(embeds[0])

    async def fake_remove_user_reaction(channel_id, message_id, emoji, user_id):
        pass

    bot.rest.edit_message = fake_edit_message
    bot.rest.remove_user_reaction = fake_remove_user_reaction

    await dispatch_reaction(bot, message_id="msg1", emoji={"name": utility_mod.HELP_NEXT_EMOJI},
                             user_id="owner1", guild_id=guild_id)
    assert session.page == 1
    assert edited[-1] == session.pages[1]

    await dispatch_reaction(bot, message_id="msg1", emoji={"name": utility_mod.HELP_PREV_EMOJI},
                             user_id="owner1", guild_id=guild_id)
    assert session.page == 0

    # Wraps backward from the first page to the last.
    await dispatch_reaction(bot, message_id="msg1", emoji={"name": utility_mod.HELP_PREV_EMOJI},
                             user_id="owner1", guild_id=guild_id)
    assert session.page == total_pages - 1

    # Wraps forward from the last page back to the first.
    await dispatch_reaction(bot, message_id="msg1", emoji={"name": utility_mod.HELP_NEXT_EMOJI},
                             user_id="owner1", guild_id=guild_id)
    assert session.page == 0


async def test_help_reaction_ignores_other_users(guild_id, monkeypatch):
    monkeypatch.setattr(utility_mod, "config", dataclasses.replace(config, owner_id="owner1"))
    bot = make_bot_with_all_modules()
    await run_help(bot, guild_id, author_id="owner1", owner_id="owner1")
    session = utility_mod._help_sessions["msg1"]

    edited = []

    async def fake_edit_message(*a, **kw):
        edited.append(1)

    bot.rest.edit_message = fake_edit_message

    await dispatch_reaction(bot, message_id="msg1", emoji={"name": utility_mod.HELP_NEXT_EMOJI},
                             user_id="someone-else-entirely", guild_id=guild_id)
    assert session.page == 0
    assert edited == []


async def test_help_reaction_ignores_unrelated_emoji(guild_id, monkeypatch):
    monkeypatch.setattr(utility_mod, "config", dataclasses.replace(config, owner_id="owner1"))
    bot = make_bot_with_all_modules()
    await run_help(bot, guild_id, author_id="owner1", owner_id="owner1")
    session = utility_mod._help_sessions["msg1"]

    edited = []

    async def fake_edit_message(*a, **kw):
        edited.append(1)

    bot.rest.edit_message = fake_edit_message

    await dispatch_reaction(bot, message_id="msg1", emoji={"name": "\U0001F44D"},
                             user_id="owner1", guild_id=guild_id)
    assert session.page == 0
    assert edited == []


async def test_help_reaction_on_unknown_message_is_noop(guild_id, monkeypatch):
    monkeypatch.setattr(utility_mod, "config", dataclasses.replace(config, owner_id="owner1"))
    bot = make_bot_with_all_modules()
    await dispatch_reaction(bot, message_id="not-a-real-help-message",
                             emoji={"name": utility_mod.HELP_NEXT_EMOJI}, user_id="owner1", guild_id=guild_id)
    # No exception, nothing to assert beyond "didn't crash".


def test_visible_commands_filters_out_gated_commands_for_a_regular_member():
    bot = Bot("test-token")

    @bot.command("secret", category="Moderation", required_permission=PERM_BAN_MEMBERS)
    async def secret(ctx) -> None:
        pass

    guild = {"id": "g1", "owner_id": "the-owner", "roles": []}
    member = {"user": {"id": "u1"}, "roles": []}
    visible = utility_mod._visible_commands(bot, guild, member, "u1")
    assert visible == []


async def test_help_no_commands_available_sends_plain_message(guild_id, monkeypatch):
    monkeypatch.setattr(utility_mod, "_visible_commands", lambda *a, **kw: [])
    bot = Bot("test-token")
    utility_mod.register(bot)
    replies = []

    async def fake_send_message(channel_id, content=None, embeds=None, **kw):
        replies.append(content)
        return {"id": "msg1"}

    async def fake_get_guild(gid):
        return {"id": gid, "owner_id": "someone-else", "roles": []}

    async def fake_get_member(gid, user_id):
        return {"user": {"id": user_id}, "roles": []}

    bot.rest.send_message = fake_send_message
    bot.rest.get_guild = fake_get_guild
    bot.rest.get_guild_member = fake_get_member

    message = {
        "content": "!help", "author": {"id": "u1", "username": "tester"},
        "guild_id": guild_id, "channel_id": "chan1",
    }
    await bot._on_message(message)

    assert replies == ["No commands are available to you in this server."]
