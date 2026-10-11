"""Tests for the owner-configurable bot invite link (added so any
logged-in user can invite the bot to another one of their own servers
from the server picker and server switcher, not just from a standalone
owner page)."""
from __future__ import annotations

import dataclasses

import dashboard.app as app_mod
from common import db
from common.config import config


async def test_invite_permissions_round_trip(_db_pool):
    # A singleton row, same as bot_profile/discord_relay_config, not
    # scoped to a per-test guild_id fixture, so this restores whatever
    # was there rather than assuming a pristine 0 to start from.
    original = await db.get_bot_invite_permissions()
    try:
        await db.set_bot_invite_permissions(8)
        assert await db.get_bot_invite_permissions() == 8

        await db.set_bot_invite_permissions(0)
        assert await db.get_bot_invite_permissions() == 0
    finally:
        await db.set_bot_invite_permissions(original)


def test_invite_url_is_none_without_a_configured_oauth_client(monkeypatch):
    monkeypatch.setattr(app_mod, "config", dataclasses.replace(config, oauth_client_id=""))
    assert app_mod._fluxer_invite_url(8) is None


def test_invite_url_shape_matches_the_login_oauth_application(monkeypatch):
    monkeypatch.setattr(
        app_mod, "config",
        dataclasses.replace(config, oauth_client_id="123456", web_base="https://badlands.chat"),
    )
    url = app_mod._fluxer_invite_url(8)
    assert url == "https://badlands.chat/oauth2/authorize?client_id=123456&scope=bot&permissions=8"
