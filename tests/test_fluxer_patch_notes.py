"""Fluxer patch notes: the timezone-aware date-window math (including DST,
since that's exactly the kind of thing that's easy to get wrong with a
naive UTC offset), the Conventional-Commits theme grouping, the embed
builder, the per-guild dashboard setting round-trip (channel, send
time, and default timezone), and the scheduler's per-guild gating/
dedupe logic.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import bot.scheduler as scheduler
from bot import fluxer_patch_notes as patch_notes
from bot.commands import Bot
from common import db

CENTRAL = ZoneInfo("America/Chicago")
TOKYO = ZoneInfo("Asia/Tokyo")


# --------------------------------------------------------- window math --
def test_date_window_utc_in_winter_is_cst_minus_six():
    since, until = patch_notes.date_window_utc(date(2026, 1, 15), CENTRAL)
    assert since == "2026-01-15T06:00:00+00:00"
    assert until == "2026-01-16T06:00:00+00:00"


def test_date_window_utc_in_summer_is_cdt_minus_five():
    # Daylight saving: a naive fixed UTC-6 offset would get this wrong.
    since, until = patch_notes.date_window_utc(date(2026, 7, 15), CENTRAL)
    assert since == "2026-07-15T05:00:00+00:00"
    assert until == "2026-07-16T05:00:00+00:00"


def test_date_window_utc_respects_the_given_timezone():
    since, until = patch_notes.date_window_utc(date(2026, 1, 15), TOKYO)
    assert since == "2026-01-14T15:00:00+00:00"
    assert until == "2026-01-15T15:00:00+00:00"


def test_yesterday_in_is_the_day_before_now():
    now = datetime(2026, 3, 10, 0, 5, tzinfo=CENTRAL)
    assert patch_notes.yesterday_in(CENTRAL, now) == date(2026, 3, 9)


def test_yesterday_in_stays_the_previous_day_even_late_in_the_day():
    # The whole point: whether the trigger fires just after midnight or
    # just before it, it always reports the same, complete, prior day.
    now = datetime(2026, 3, 10, 23, 55, tzinfo=CENTRAL)
    assert patch_notes.yesterday_in(CENTRAL, now) == date(2026, 3, 9)


def test_resolve_timezone_known_name():
    assert patch_notes.resolve_timezone("Asia/Tokyo") == TOKYO


def test_resolve_timezone_falls_back_on_unknown_or_missing_name():
    assert patch_notes.resolve_timezone("Not/AZone") == ZoneInfo(patch_notes.DEFAULT_TIMEZONE_NAME)
    assert patch_notes.resolve_timezone(None) == ZoneInfo(patch_notes.DEFAULT_TIMEZONE_NAME)
    assert patch_notes.resolve_timezone("") == ZoneInfo(patch_notes.DEFAULT_TIMEZONE_NAME)


# ---------------------------------------------------------------- grouping --
def test_bucket_for_feat_and_fix_and_unprefixed():
    assert patch_notes._bucket_for("feat(app): show instance branding") == ("✨ Features", "show instance branding")
    assert patch_notes._bucket_for("fix(threads): confirm before leaving") == ("🐛 Fixes", "confirm before leaving")
    assert patch_notes._bucket_for("chore(i18n): refresh catalog") == ("🔧 Maintenance", "refresh catalog")
    assert patch_notes._bucket_for("bump version to 1.2.3") == ("🔧 Maintenance", "bump version to 1.2.3")


def test_bucket_for_only_uses_the_first_message_line():
    message = "fix(app): keep mature content consent\n\nLonger body text here."
    assert patch_notes._bucket_for(message) == ("🐛 Fixes", "keep mature content consent")


# ------------------------------------------------------------ embed builder --
def test_build_patch_notes_embed_with_no_commits():
    embed = patch_notes.build_patch_notes_embed([], date(2026, 10, 8))
    assert "No commits" in embed["description"]
    assert embed["footer"]["text"] == "0 commits"
    assert "2026-10-08" in embed["title"]


def test_build_patch_notes_embed_groups_by_theme_in_order():
    commits = [
        {"commit": {"message": "fix(ui): a fix"}, "html_url": "https://x/1"},
        {"commit": {"message": "feat(app): a feature"}, "html_url": "https://x/2"},
        {"commit": {"message": "chore: cleanup"}, "html_url": "https://x/3"},
    ]
    embed = patch_notes.build_patch_notes_embed(commits, date(2026, 10, 8))
    desc = embed["description"]
    assert embed["footer"]["text"] == "3 commits"
    # Features before Fixes before Maintenance, regardless of input order.
    assert desc.index("✨ Features") < desc.index("🐛 Fixes") < desc.index("🔧 Maintenance")
    assert "[a feature](https://x/2)" in desc
    assert "[a fix](https://x/1)" in desc
    assert "[cleanup](https://x/3)" in desc


def test_build_patch_notes_embed_singular_commit_count():
    commits = [{"commit": {"message": "fix: one thing"}, "html_url": "https://x/1"}]
    embed = patch_notes.build_patch_notes_embed(commits, date(2026, 10, 8))
    assert embed["footer"]["text"] == "1 commit"


# ------------------------------------------------------- settings round-trip --
async def test_fluxer_patch_notes_channel_id_is_settable(guild_id):
    await db.update_guild_settings(guild_id, fluxer_patch_notes_channel_id="chan123")
    row = await db.get_guild(guild_id)
    assert row["fluxer_patch_notes_channel_id"] == "chan123"


async def test_fluxer_patch_notes_trigger_time_defaults_and_is_settable(guild_id):
    row = await db.get_guild(guild_id)
    assert row["fluxer_patch_notes_trigger_hour"] == 0
    assert row["fluxer_patch_notes_trigger_minute"] == 5

    await db.update_guild_settings(
        guild_id, fluxer_patch_notes_trigger_hour=13, fluxer_patch_notes_trigger_minute=30,
    )
    row = await db.get_guild(guild_id)
    assert row["fluxer_patch_notes_trigger_hour"] == 13
    assert row["fluxer_patch_notes_trigger_minute"] == 30


async def test_guild_timezone_defaults_and_is_settable(guild_id):
    row = await db.get_guild(guild_id)
    assert row["timezone"] == "America/Chicago"

    await db.update_guild_settings(guild_id, timezone="Asia/Tokyo")
    row = await db.get_guild(guild_id)
    assert row["timezone"] == "Asia/Tokyo"


async def test_list_guilds_with_fluxer_patch_notes_channel_filters_unset(guild_id):
    await db.update_guild_settings(guild_id, fluxer_patch_notes_channel_id="chan999")
    rows = await db.list_guilds_with_fluxer_patch_notes_channel()
    matching = [r for r in rows if r["guild_id"] == guild_id]
    assert len(matching) == 1
    assert matching[0]["fluxer_patch_notes_channel_id"] == "chan999"
    assert matching[0]["timezone"] == "America/Chicago"


# --------------------------------------------------------------------- log --
async def test_fluxer_patch_notes_log_dedupe_keeps_the_first_count(guild_id):
    report_date = date(2026, 1, 1)
    await db.pool().execute(
        "DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1 AND sent_date=$2", guild_id, report_date,
    )

    assert await db.get_fluxer_patch_notes_log(guild_id, report_date) is None
    await db.record_fluxer_patch_notes_sent(guild_id, report_date, 7)
    row = await db.get_fluxer_patch_notes_log(guild_id, report_date)
    assert row["commit_count"] == 7

    # A second attempt at recording the same (guild, date) must not
    # overwrite it (mirrors two scheduler ticks racing past the dedupe check).
    await db.record_fluxer_patch_notes_sent(guild_id, report_date, 999)
    row = await db.get_fluxer_patch_notes_log(guild_id, report_date)
    assert row["commit_count"] == 7

    await db.pool().execute(
        "DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1 AND sent_date=$2", guild_id, report_date,
    )


# --------------------------------------------------------- scheduler gating --
async def test_send_fluxer_patch_notes_noop_before_any_guild_is_due(monkeypatch):
    monkeypatch.setattr(patch_notes, "now_in", lambda tz: datetime(2026, 5, 1, 11, 59, tzinfo=tz))
    monkeypatch.setattr(db, "list_guilds_with_fluxer_patch_notes_channel", _empty_list)
    generated = []
    monkeypatch.setattr(patch_notes, "generate_patch_notes", lambda d, tz: generated.append(d))

    await scheduler._send_fluxer_patch_notes(Bot("test-token"))
    assert generated == []


async def test_send_fluxer_patch_notes_noop_with_no_channels_configured(monkeypatch):
    monkeypatch.setattr(patch_notes, "now_in", lambda tz: datetime(2026, 5, 2, 0, 1, tzinfo=tz))
    monkeypatch.setattr(db, "list_guilds_with_fluxer_patch_notes_channel", _empty_list)

    fetched = []
    monkeypatch.setattr(patch_notes, "generate_patch_notes", lambda d, tz: fetched.append(d))
    scheduler._last_patch_notes_failure = None

    await scheduler._send_fluxer_patch_notes(Bot("test-token"))
    assert fetched == []  # no guilds configured anywhere -> not worth a GitHub call


async def test_send_fluxer_patch_notes_sends_to_a_due_guild(guild_id, monkeypatch):
    report_date = date(2026, 5, 3)
    await db.pool().execute(
        "DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1 AND sent_date=$2", guild_id, report_date,
    )
    await db.update_guild_settings(
        guild_id, fluxer_patch_notes_channel_id="chan555",
        fluxer_patch_notes_trigger_hour=0, fluxer_patch_notes_trigger_minute=0,
    )
    monkeypatch.setattr(patch_notes, "now_in", lambda tz: datetime(2026, 5, 4, 0, 1, tzinfo=tz))

    async def fake_generate(d, tz):
        return {"title": "fake embed"}, 5

    monkeypatch.setattr(patch_notes, "generate_patch_notes", fake_generate)
    scheduler._last_patch_notes_failure = None

    sent = []

    async def fake_send_message(channel_id, **kw):
        sent.append(channel_id)
        return {"id": "1"}

    bot = Bot("test-token")
    bot.rest.send_message = fake_send_message

    await scheduler._send_fluxer_patch_notes(bot)
    assert "chan555" in sent
    row = await db.get_fluxer_patch_notes_log(guild_id, report_date)
    assert row["commit_count"] == 5

    await db.pool().execute(
        "DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1 AND sent_date=$2", guild_id, report_date,
    )


async def test_send_fluxer_patch_notes_skips_a_guild_not_yet_due(guild_id, monkeypatch):
    report_date = date(2026, 5, 5)
    await db.pool().execute(
        "DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1 AND sent_date=$2", guild_id, report_date,
    )
    await db.update_guild_settings(
        guild_id, fluxer_patch_notes_channel_id="chan777",
        fluxer_patch_notes_trigger_hour=12, fluxer_patch_notes_trigger_minute=0,
    )
    monkeypatch.setattr(patch_notes, "now_in", lambda tz: datetime(2026, 5, 6, 11, 59, tzinfo=tz))
    scheduler._last_patch_notes_failure = None

    sent = []

    async def fake_send_message(channel_id, **kw):
        sent.append(channel_id)
        return {"id": "1"}

    bot = Bot("test-token")
    bot.rest.send_message = fake_send_message

    await scheduler._send_fluxer_patch_notes(bot)
    assert "chan777" not in sent
    assert await db.get_fluxer_patch_notes_log(guild_id, report_date) is None


async def test_send_fluxer_patch_notes_fetches_once_for_two_guilds_due_at_once(
    guild_id, second_guild_id, monkeypatch,
):
    """Two guilds sharing the same timezone and both due in the same
    tick should land in the same (date, tz) bucket, so the scheduler
    only has to fetch GitHub once for both of them."""
    report_date = date(2026, 5, 7)
    for gid in (guild_id, second_guild_id):
        await db.pool().execute(
            "DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1 AND sent_date=$2", gid, report_date,
        )
    await db.update_guild_settings(
        guild_id, fluxer_patch_notes_channel_id="chan-a",
        fluxer_patch_notes_trigger_hour=0, fluxer_patch_notes_trigger_minute=0,
    )
    await db.update_guild_settings(
        second_guild_id, fluxer_patch_notes_channel_id="chan-b",
        fluxer_patch_notes_trigger_hour=0, fluxer_patch_notes_trigger_minute=0,
    )
    monkeypatch.setattr(patch_notes, "now_in", lambda tz: datetime(2026, 5, 8, 0, 1, tzinfo=tz))

    fetch_calls = []

    async def fake_generate(d, tz):
        fetch_calls.append((d, tz))
        return {"title": "fake embed"}, 3

    monkeypatch.setattr(patch_notes, "generate_patch_notes", fake_generate)
    scheduler._last_patch_notes_failure = None

    sent = []

    async def fake_send_message(channel_id, **kw):
        sent.append(channel_id)
        return {"id": "1"}

    bot = Bot("test-token")
    bot.rest.send_message = fake_send_message

    await scheduler._send_fluxer_patch_notes(bot)
    assert len(fetch_calls) == 1  # one GitHub fetch shared by both due guilds
    assert set(sent) == {"chan-a", "chan-b"}

    for gid in (guild_id, second_guild_id):
        await db.pool().execute(
            "DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1 AND sent_date=$2", gid, report_date,
        )


async def test_send_fluxer_patch_notes_fetches_separately_for_different_timezones(
    guild_id, second_guild_id, monkeypatch,
):
    """Two guilds on different timezones can land on the same calendar
    *date label* while still needing separate GitHub windows (the UTC
    window for "2026-05-07" differs between timezones), so they must
    not be batched into a single shared fetch."""
    report_date = date(2026, 5, 7)
    for gid in (guild_id, second_guild_id):
        await db.pool().execute(
            "DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1 AND sent_date=$2", gid, report_date,
        )
    await db.update_guild_settings(
        guild_id, fluxer_patch_notes_channel_id="chan-a", timezone="America/Chicago",
        fluxer_patch_notes_trigger_hour=0, fluxer_patch_notes_trigger_minute=0,
    )
    await db.update_guild_settings(
        second_guild_id, fluxer_patch_notes_channel_id="chan-b", timezone="Asia/Tokyo",
        fluxer_patch_notes_trigger_hour=0, fluxer_patch_notes_trigger_minute=0,
    )
    monkeypatch.setattr(patch_notes, "now_in", lambda tz: datetime(2026, 5, 8, 0, 1, tzinfo=tz))

    fetch_calls = []

    async def fake_generate(d, tz):
        fetch_calls.append((d, tz))
        return {"title": "fake embed"}, 3

    monkeypatch.setattr(patch_notes, "generate_patch_notes", fake_generate)
    scheduler._last_patch_notes_failure = None

    sent = []

    async def fake_send_message(channel_id, **kw):
        sent.append(channel_id)
        return {"id": "1"}

    bot = Bot("test-token")
    bot.rest.send_message = fake_send_message

    await scheduler._send_fluxer_patch_notes(bot)
    assert len(fetch_calls) == 2  # same date label, different tz -> not shareable
    assert set(sent) == {"chan-a", "chan-b"}

    for gid in (guild_id, second_guild_id):
        await db.pool().execute(
            "DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1 AND sent_date=$2", gid, report_date,
        )


async def _empty_list():
    return []
