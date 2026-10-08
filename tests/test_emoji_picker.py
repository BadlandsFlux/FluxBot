"""Emoji picker backend support: the CDN URL helper and the dashboard's
guild-custom-emoji -> JSON shape, including the two string formats a pick
can resolve to (the `name:id` reaction form Fluxer's docs confirm, and
the `<:name:id>` / `<a:name:id>` text-insertion form this codebase
assumes by the same convention it already uses elsewhere).
"""
from __future__ import annotations

import dashboard.app as app_mod
from common.discovery import emoji_url


def test_emoji_url_static():
    url = emoji_url("https://media.example", "123", animated=False, size=64)
    assert url == "https://media.example/emojis/123.webp?size=64"


def test_emoji_url_animated_uses_gif_and_animated_flag():
    url = emoji_url("https://media.example", "123", animated=True, size=64)
    assert url == "https://media.example/emojis/123.gif?size=64&animated=true"


def test_guild_emoji_to_json_static():
    result = app_mod._guild_emoji_to_json({"id": "555", "name": "party_parrot", "animated": False},
                                           "https://media.example")
    assert result == {
        "id": "555",
        "name": "party_parrot",
        "animated": False,
        "url": "https://media.example/emojis/555.webp?size=64",
        "reaction": "party_parrot:555",
        "tag": "<:party_parrot:555>",
    }


def test_guild_emoji_to_json_animated_tag_gets_the_a_prefix():
    result = app_mod._guild_emoji_to_json({"id": "777", "name": "spin", "animated": True},
                                           "https://media.example")
    assert result["tag"] == "<a:spin:777>"
    assert result["reaction"] == "spin:777"
    assert result["url"].endswith("/emojis/777.gif?size=64&animated=true")


def test_guild_emoji_to_json_falls_back_to_a_default_name():
    result = app_mod._guild_emoji_to_json({"id": "999", "animated": False}, "https://media.example")
    assert result["name"] == "emoji"
    assert result["reaction"] == "emoji:999"
