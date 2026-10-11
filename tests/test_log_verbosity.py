"""Regression tests for a verbosity bug found in a full-codebase audit of
the logging code: "adding a privileged role" didn't say which user it
was added to. The activity-log embeds named the affected member only in
the embed's `author` block (small, easy to skim past), and `!unban`
logged a raw-ID user dict that rendered as "@unknown" since the target
isn't a guild member to look up anymore.
"""
from __future__ import annotations

import pytest

from bot.commands import Bot
from bot.modules import activity_log
from bot.permissions import PRIVILEGED_PERMISSION_BITS
from common import db


@pytest.fixture(autouse=True)
def _clear_activity_log_caches():
    activity_log._member_roles.clear()
    yield
    activity_log._member_roles.clear()
    for task in list(activity_log._background_tasks):
        task.cancel()


def _field(embed: dict, name: str) -> dict:
    return next(f for f in embed["fields"] if f["name"] == name)


async def test_privileged_role_change_embed_names_the_user_in_a_field(guild_id, monkeypatch):
    bot = Bot("test-token")
    activity_log.register(bot)
    await db.set_activity_log_settings(
        guild_id, log_channel_id="log1", log_message_edits=False, log_message_deletes=False,
        log_member_joins=False, log_member_leaves=False, log_channel_changes=False,
        log_role_changes=False, log_voice_activity=False, log_privileged_role_changes=True,
    )

    role_id = "role1"
    guild = {"id": guild_id, "roles": [{"id": role_id, "permissions": str(PRIVILEGED_PERMISSION_BITS)}]}

    async def fake_get_guild(gid):
        return guild

    sent = []

    async def fake_send_message(channel_id, embeds=None, **kw):
        sent.append((channel_id, embeds[0]))
        return {"id": "msg1"}

    monkeypatch.setattr(bot.rest, "get_guild", fake_get_guild)
    monkeypatch.setattr(bot.rest, "send_message", fake_send_message)

    activity_log._member_roles[(guild_id, "user1")] = frozenset()  # old roles: none
    await bot.gateway._dispatch("GUILD_MEMBER_UPDATE", {
        "guild_id": guild_id,
        "user": {"id": "user1", "username": "victim"},
        "roles": [role_id],
    })

    assert len(sent) == 1
    channel_id, embed = sent[0]
    assert channel_id == "log1"
    assert embed["title"] == "Privileged Role Change"
    # The bug: this field used to not exist at all, leaving the small
    # embed author block as the only place the affected user was named.
    user_field = _field(embed, "User")
    assert user_field["value"] == "<@user1>"


async def test_unban_logs_the_real_username_not_unknown(guild_id):
    from bot import moderation_actions as actions

    class FakeRest:
        def __init__(self):
            self.sent = []
            self.unbanned = []

        async def get_guild_ban(self, guild_id, user_id):
            return {"user": {"id": user_id, "username": "formerly_banned"}, "reason": "time served"}

        async def unban_member(self, guild_id, user_id, reason=""):
            self.unbanned.append(user_id)

        async def send_message(self, channel_id, embeds=None, **kw):
            self.sent.append(embeds[0])
            return {"id": "m1"}

    rest = FakeRest()
    await db.update_guild_settings(guild_id, log_channel_id="modlog1")
    moderator = {"id": "mod1", "username": "staffer"}

    await actions.unban_member(rest, guild_id, "banned_user_1", moderator, reason="appeal accepted")

    assert rest.unbanned == ["banned_user_1"]
    assert len(rest.sent) == 1
    user_field = _field(rest.sent[0], "User")
    assert "formerly_banned" in user_field["value"]
    assert "unknown" not in user_field["value"].lower()


async def test_unban_falls_back_gracefully_when_ban_lookup_fails(guild_id):
    """The user may have left no trace to look up (e.g. the Fluxer API
    doesn't support the ban-info endpoint, or it 404s); the log should
    still go out with whatever's known rather than raising."""
    from bot import moderation_actions as actions
    from bot.rest import FluxerAPIError

    class FakeRest:
        def __init__(self):
            self.sent = []

        async def get_guild_ban(self, guild_id, user_id):
            raise FluxerAPIError(404, "GET", f"/guilds/{guild_id}/bans/{user_id}", "not found")

        async def unban_member(self, guild_id, user_id, reason=""):
            pass

        async def send_message(self, channel_id, embeds=None, **kw):
            self.sent.append(embeds[0])
            return {"id": "m1"}

    rest = FakeRest()
    await db.update_guild_settings(guild_id, log_channel_id="modlog1")
    moderator = {"id": "mod1", "username": "staffer"}

    await actions.unban_member(rest, guild_id, "banned_user_2", moderator, reason="")

    user_field = _field(rest.sent[0], "User")
    assert "banned_user_2" in user_field["value"]
