"""Fluxer added GUILD_ANNOUNCEMENT (5), GUILD_FORUM (15), and GUILD_MEDIA
(16) channel types alongside GUILD_TEXT (0). This covers:

1. GET /api/guilds/{id}/channels: announcement channels now show up in
   every channel picker (they take a plain message the same as text
   channels do), while forum/media channels only show up when the
   caller explicitly asks for them via include_posts=true (the one
   picker that knows how to post into them -- see below).
2. POST /api/guilds/{id}/embed: routes a forum/media destination through
   bot_rest.start_forum_post (a named post/thread) instead of
   bot_rest.send_message, since Fluxer -- like Discord -- rejects a
   plain message to those channel types with
   CANNOT_SEND_MESSAGES_IN_NON_TEXT_CHANNEL. A forum/media destination
   requires a post title; a text/announcement one doesn't use it at all.
"""
from __future__ import annotations

import dashboard.app as app_mod
from common import db


class _FakeRequest:
    def __init__(self, session):
        self.session = session


def _guild_with_channels(channels):
    return {"id": "g1", "channels": channels}


async def _noop_require_manage(request, guild_id):
    return None


def _owner_request():
    return _FakeRequest({"user": {"id": "mod1"}, "access_token": "tok"})


# ------------------------------------------------------------- channel list --
async def test_default_channel_list_includes_text_and_announcement_not_forum_or_media(monkeypatch):
    monkeypatch.setattr(app_mod, "_require_manage", _noop_require_manage)

    async def fake_get_guild(guild_id):
        return _guild_with_channels([
            {"id": 1, "name": "general", "type": 0},
            {"id": 2, "name": "announcements", "type": 5},
            {"id": 3, "name": "forum-chat", "type": 15},
            {"id": 4, "name": "media-dump", "type": 16},
            {"id": 5, "name": "voice", "type": 2},
            {"id": 6, "name": "legacy", "type": None},
        ])

    monkeypatch.setattr(app_mod.bot_rest, "get_guild", fake_get_guild)

    result = await app_mod.api_guild_channels(_owner_request(), "g1")
    names = {c["name"] for c in result["channels"]}
    assert names == {"general", "announcements", "legacy"}


async def test_include_posts_also_returns_forum_and_media_channels(monkeypatch):
    monkeypatch.setattr(app_mod, "_require_manage", _noop_require_manage)

    async def fake_get_guild(guild_id):
        return _guild_with_channels([
            {"id": 1, "name": "general", "type": 0},
            {"id": 3, "name": "forum-chat", "type": 15},
            {"id": 4, "name": "media-dump", "type": 16},
            {"id": 5, "name": "voice", "type": 2},
        ])

    monkeypatch.setattr(app_mod.bot_rest, "get_guild", fake_get_guild)

    result = await app_mod.api_guild_channels(_owner_request(), "g1", include_posts=True)
    by_name = {c["name"]: c["type"] for c in result["channels"]}
    assert by_name == {"general": 0, "forum-chat": 15, "media-dump": 16}


# --------------------------------------------------------------- send embed --
async def test_send_embed_to_a_text_channel_uses_plain_send_message(guild_id, monkeypatch):
    monkeypatch.setattr(app_mod, "_require_manage", _noop_require_manage)

    async def fake_get_guild(gid):
        return _guild_with_channels([{"id": "111111111111111111", "name": "general", "type": 0}])

    monkeypatch.setattr(app_mod.bot_rest, "get_guild", fake_get_guild)

    sent = []

    async def fake_send_message(channel_id, **kw):
        sent.append(channel_id)
        return {"id": "1"}

    async def fail_start_forum_post(*a, **kw):
        raise AssertionError("should not have started a forum post for a text channel")

    monkeypatch.setattr(app_mod.bot_rest, "send_message", fake_send_message)
    monkeypatch.setattr(app_mod.bot_rest, "start_forum_post", fail_start_forum_post)

    payload = app_mod.EmbedPayload(channel_id="111111111111111111", title="hi")
    result = await app_mod.api_send_embed(_owner_request(), guild_id, payload)
    assert result == {"ok": True}
    assert sent == ["111111111111111111"]


async def test_send_embed_to_a_forum_channel_requires_a_post_title(guild_id, monkeypatch):
    monkeypatch.setattr(app_mod, "_require_manage", _noop_require_manage)

    async def fake_get_guild(gid):
        return _guild_with_channels([{"id": "222222222222222222", "name": "ideas", "type": 15}])

    monkeypatch.setattr(app_mod.bot_rest, "get_guild", fake_get_guild)

    payload = app_mod.EmbedPayload(channel_id="222222222222222222", title="hi")
    try:
        await app_mod.api_send_embed(_owner_request(), guild_id, payload)
        assert False, "should have required a post title for a forum channel"
    except app_mod._ApiError as e:
        assert e.status_code == 400
        assert "title" in e.detail.lower()


async def test_send_embed_to_a_forum_channel_rejects_an_overlong_post_title(guild_id, monkeypatch):
    monkeypatch.setattr(app_mod, "_require_manage", _noop_require_manage)

    async def fake_get_guild(gid):
        return _guild_with_channels([{"id": "222222222222222222", "name": "ideas", "type": 15}])

    monkeypatch.setattr(app_mod.bot_rest, "get_guild", fake_get_guild)

    payload = app_mod.EmbedPayload(channel_id="222222222222222222", post_title="x" * 101, title="hi")
    try:
        await app_mod.api_send_embed(_owner_request(), guild_id, payload)
        assert False, "should have rejected a >100 char post title"
    except app_mod._ApiError as e:
        assert e.status_code == 400
        assert "too long" in e.detail.lower()


async def test_send_embed_to_a_media_channel_starts_a_forum_post(guild_id, monkeypatch):
    monkeypatch.setattr(app_mod, "_require_manage", _noop_require_manage)

    async def fake_get_guild(gid):
        return _guild_with_channels([{"id": "333333333333333333", "name": "screenshots", "type": 16}])

    monkeypatch.setattr(app_mod.bot_rest, "get_guild", fake_get_guild)

    started = []

    async def fake_start_forum_post(channel_id, name=None, **kw):
        started.append((channel_id, name))
        return {"id": "1"}

    async def fail_send_message(*a, **kw):
        raise AssertionError("should not have sent a plain message to a media channel")

    monkeypatch.setattr(app_mod.bot_rest, "start_forum_post", fake_start_forum_post)
    monkeypatch.setattr(app_mod.bot_rest, "send_message", fail_send_message)

    payload = app_mod.EmbedPayload(channel_id="333333333333333333", post_title="New screenshots", title="hi")
    result = await app_mod.api_send_embed(_owner_request(), guild_id, payload)
    assert result == {"ok": True}
    assert started == [("333333333333333333", "New screenshots")]


async def test_send_embed_logs_the_action(guild_id, monkeypatch):
    monkeypatch.setattr(app_mod, "_require_manage", _noop_require_manage)

    async def fake_get_guild(gid):
        return _guild_with_channels([{"id": "111111111111111111", "name": "general", "type": 0}])

    monkeypatch.setattr(app_mod.bot_rest, "get_guild", fake_get_guild)

    async def fake_send_message(channel_id, **kw):
        return {"id": "1"}

    monkeypatch.setattr(app_mod.bot_rest, "send_message", fake_send_message)

    payload = app_mod.EmbedPayload(channel_id="111111111111111111", title="hi")
    await app_mod.api_send_embed(_owner_request(), guild_id, payload)

    actions = await db.list_actions(guild_id, limit=5)
    assert any(a["action"] == "send_embed" for a in actions)
