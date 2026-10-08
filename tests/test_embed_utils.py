"""clamp_embed/clamp_embeds truncate an embed's text fields to Discord/
Fluxer's limits so a long user- or admin-supplied string (a warning
reason, a staff note, a report, a poll option) can't get a whole
message rejected with INVALID_MESSAGE_DATA, the same class of bug
!help's old single-embed-per-category design hit. Also verifies
FluxerREST actually applies the clamp before sending/editing.
"""
from __future__ import annotations

from bot.embed_utils import (
    DESCRIPTION_LIMIT, FIELD_NAME_LIMIT, FIELD_VALUE_LIMIT, FOOTER_LIMIT, TITLE_LIMIT,
    clamp_embed, clamp_embeds,
)
from bot.rest import FluxerREST


def test_short_embed_is_left_untouched():
    embed = {"title": "Hi", "description": "short", "fields": [{"name": "a", "value": "b"}]}
    before = dict(embed)
    assert clamp_embed(embed) == before


def test_long_description_is_truncated_to_the_limit():
    embed = {"description": "x" * 5000}
    clamp_embed(embed)
    assert len(embed["description"]) == DESCRIPTION_LIMIT
    assert embed["description"].endswith("(truncated)")


def test_long_field_value_is_truncated_to_the_limit():
    embed = {"fields": [{"name": "Note", "value": "y" * 2000}]}
    clamp_embed(embed)
    assert len(embed["fields"][0]["value"]) == FIELD_VALUE_LIMIT
    assert embed["fields"][0]["value"].endswith("(truncated)")


def test_long_field_name_title_and_footer_are_each_truncated():
    embed = {
        "title": "t" * 400,
        "footer": {"text": "f" * 3000},
        "fields": [{"name": "n" * 400, "value": "ok"}],
    }
    clamp_embed(embed)
    assert len(embed["title"]) == TITLE_LIMIT
    assert len(embed["footer"]["text"]) == FOOTER_LIMIT
    assert len(embed["fields"][0]["name"]) == FIELD_NAME_LIMIT
    assert embed["fields"][0]["value"] == "ok"


def test_multiple_oversized_fields_are_each_independently_clamped():
    embed = {"fields": [{"name": "a", "value": "x" * 2000}, {"name": "b", "value": "y" * 1500}]}
    clamp_embed(embed)
    assert len(embed["fields"][0]["value"]) == FIELD_VALUE_LIMIT
    assert len(embed["fields"][1]["value"]) == FIELD_VALUE_LIMIT


def test_clamp_embeds_handles_none_and_empty_list():
    assert clamp_embeds(None) is None
    assert clamp_embeds([]) == []


def test_clamp_embeds_clamps_every_embed_in_the_list():
    embeds = [{"description": "a" * 5000}, {"description": "b" * 5000}]
    clamp_embeds(embeds)
    assert len(embeds[0]["description"]) == DESCRIPTION_LIMIT
    assert len(embeds[1]["description"]) == DESCRIPTION_LIMIT


def test_missing_optional_pieces_dont_raise():
    assert clamp_embed({}) == {}
    assert clamp_embed({"fields": []}) == {"fields": []}
    assert clamp_embed({"footer": {}}) == {"footer": {}}


async def _capture_request(rest):
    calls = []

    async def fake_request(method, path, *, json=None, params=None, retries=3):
        calls.append(json)
        return {"id": "1"}

    rest.request = fake_request
    return calls


async def test_send_message_clamps_embeds_before_sending():
    rest = FluxerREST("tok")
    calls = await _capture_request(rest)
    await rest.send_message("chan1", embeds=[{"description": "z" * 5000}])
    assert len(calls[0]["embeds"][0]["description"]) == DESCRIPTION_LIMIT


async def test_edit_message_clamps_embeds_before_sending():
    rest = FluxerREST("tok")
    calls = await _capture_request(rest)
    await rest.edit_message("chan1", "msg1", embeds=[{"fields": [{"name": "n", "value": "v" * 2000}]}])
    assert len(calls[0]["embeds"][0]["fields"][0]["value"]) == FIELD_VALUE_LIMIT
