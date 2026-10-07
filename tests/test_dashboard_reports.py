"""Regression tests for dashboard-side bugs found in a full-codebase
audit:

1. open_report_count was summed over a 100-row-limited list_reports()
   page, undercounting a guild with a bigger open-report backlog.
2. list_actions()/list_reports()'s before_id "load more" cursor was
   keyed on id while the query sorted by (created_at, id), a mismatch
   that could in principle skip a row under concurrent inserts.
3. _maybe_post_report_intro only re-posted the explainer embed when
   report_channel_id itself changed, leaving a stale tracker-channel
   reference in it if only report_tracker_channel_id changed.
4. api_send_embed validated field count/length but not title,
   description, footer, or author_name against Discord's embed limits.
"""
from __future__ import annotations

import inspect

import dashboard.app as app_mod
from common import db


async def test_count_reports_by_status_is_a_true_count(guild_id):
    for i in range(5):
        await db.create_report(guild_id, f"reporter{i}", f"issue {i}", "chan1", f"msg{i}", visibility="public")
    resolved_report = await db.create_report(guild_id, "reporterX", "resolved issue", "chan1", "msgX",
                                              visibility="public")
    await db.set_report_status(guild_id, resolved_report["id"], "resolved")

    assert await db.count_reports_by_status(guild_id, "open") == 5

    # The bug this replaces: summing a limited page undercounts once
    # there are more open reports than the page size.
    limited_page = await db.list_reports(guild_id, limit=3)
    assert sum(1 for r in limited_page if r["status"] == "open") < 5


def test_pagination_cursor_matches_the_sort_key():
    for fn in (db.list_actions, db.list_reports):
        src = inspect.getsource(fn)
        assert "ORDER BY id DESC" in src
        assert "created_at DESC, id DESC" not in src


async def test_report_intro_reposts_on_tracker_channel_change_too(monkeypatch):
    sent = []

    async def fake_send_message(channel_id, content=None, embeds=None, **kw):
        sent.append(channel_id)
        return {"id": "1"}

    monkeypatch.setattr(app_mod.bot_rest, "send_message", fake_send_message)

    previous = {"report_channel_id": "chan100", "report_tracker_channel_id": "tracker1"}
    unchanged = {"report_channel_id": "chan100", "report_tracker_channel_id": "tracker1"}
    await app_mod._maybe_post_report_intro(previous, unchanged)
    assert sent == []

    tracker_changed = {"report_channel_id": "chan100", "report_tracker_channel_id": "tracker2"}
    await app_mod._maybe_post_report_intro(previous, tracker_changed)
    assert sent == ["chan100"]


def test_embed_payload_length_validation():
    Payload = app_mod.EmbedPayload

    app_mod._validate_embed_payload(Payload(channel_id="123", title="fine", description="also fine"))

    for kwargs, field_name in [
        ({"title": "x" * 300}, "Title"),
        ({"title": "t", "description": "x" * 5000}, "Description"),
        ({"title": "t", "footer": "x" * 2100}, "Footer"),
        ({"title": "t", "author_name": "x" * 300}, "Author"),
    ]:
        try:
            app_mod._validate_embed_payload(Payload(channel_id="123", **kwargs))
            assert False, f"should have rejected an oversized {field_name}"
        except app_mod._ApiError as e:
            assert e.status_code == 400
            assert field_name in e.detail
