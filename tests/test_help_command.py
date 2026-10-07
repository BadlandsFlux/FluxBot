"""Regression test for !help: with every real command module registered,
the embed it builds must stay within Fluxer/Discord's per-field (1024
char) and per-embed (6000 char, 25 field) limits. Grouping all commands
in a category into a single field value previously broke this once the
Moderation and Utility categories grew past 1024 chars, failing with
HTTP 400 INVALID_MESSAGE_DATA in production.
"""
from __future__ import annotations

import importlib
import pkgutil

import bot.modules as modules_pkg
from bot.commands import Bot

EMBED_FIELD_VALUE_LIMIT = 1024
EMBED_FIELD_NAME_LIMIT = 256
EMBED_FIELD_COUNT_LIMIT = 25
EMBED_TOTAL_CHAR_LIMIT = 6000


def make_bot_with_all_modules():
    bot = Bot("test-token")
    for modinfo in pkgutil.iter_modules(modules_pkg.__path__):
        mod = importlib.import_module(f"bot.modules.{modinfo.name}")
        if hasattr(mod, "register"):
            mod.register(bot)
    return bot


async def test_help_embed_stays_within_discord_field_limits(guild_id):
    bot = make_bot_with_all_modules()

    sent = []

    async def fake_send_message(channel_id, content=None, embeds=None, **kw):
        sent.append(embeds)
        return {"id": "1"}

    async def fake_get_guild(gid):
        return {"id": gid, "owner_id": "owner1", "roles": []}

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

    assert len(sent) == 1
    embed = sent[0][0]
    fields = embed["fields"]

    assert len(fields) <= EMBED_FIELD_COUNT_LIMIT

    total = len(embed.get("title", "")) + len(embed.get("description", ""))
    for f in fields:
        assert len(f["name"]) <= EMBED_FIELD_NAME_LIMIT
        assert len(f["value"]) <= EMBED_FIELD_VALUE_LIMIT
        total += len(f["name"]) + len(f["value"])
    assert total <= EMBED_TOTAL_CHAR_LIMIT
