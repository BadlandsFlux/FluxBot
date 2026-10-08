"""Fluxer patch notes: the Central-time window math (including DST, since
that's exactly the kind of thing that's easy to get wrong with a naive
UTC offset), the Conventional-Commits theme grouping, the embed builder,
the dashboard setting round-trip, and the scheduler's gating/dedupe
logic.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import bot.scheduler as scheduler
from bot import fluxer_patch_notes as patch_notes
from bot.commands import Bot
from common import db


# --------------------------------------------------------- window math --
def test_central_date_window_utc_in_winter_is_cst_minus_six():
    since, until = patch_notes.central_date_window_utc(date(2026, 1, 15))
    assert since == "2026-01-15T06:00:00+00:00"
    assert until == "2026-01-16T06:00:00+00:00"


def test_central_date_window_utc_in_summer_is_cdt_minus_five():
    # Daylight saving: a naive fixed UTC-6 offset would get this wrong.
    since, until = patch_notes.central_date_window_utc(date(2026, 7, 15))
    assert since == "2026-07-15T05:00:00+00:00"
    assert until == "2026-07-16T05:00:00+00:00"


def test_yesterday_in_central_is_the_day_before_now():
    now = datetime(2026, 3, 10, 0, 5, tzinfo=ZoneInfo("America/Chicago"))
    assert patch_notes.yesterday_in_central(now) == date(2026, 3, 9)


def test_yesterday_in_central_stays_the_previous_day_even_late_in_the_day():
    # The whole point: whether the trigger fires just after midnight or
    # just before it, it always reports the same, complete, prior day.
    now = datetime(2026, 3, 10, 23, 55, tzinfo=ZoneInfo("America/Chicago"))
    assert patch_notes.yesterday_in_central(now) == date(2026, 3, 9)


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


async def test_list_guilds_with_fluxer_patch_notes_channel_filters_unset(guild_id):
    await db.update_guild_settings(guild_id, fluxer_patch_notes_channel_id="chan999")
    rows = await db.list_guilds_with_fluxer_patch_notes_channel()
    matching = [r for r in rows if r["guild_id"] == guild_id]
    assert len(matching) == 1
    assert matching[0]["fluxer_patch_notes_channel_id"] == "chan999"


# --------------------------------------------------------- config + log --
async def test_fluxer_patch_notes_config_defaults_and_round_trip():
    # The config row is a bot-wide singleton, not guild-scoped like most
    # fixtures here, so it can't rely on a fresh-per-test row: wipe it
    # first to actually exercise get_fluxer_patch_notes_config's
    # insert-with-defaults path, rather than assuming nothing else
    # (another test, a live manual check) has ever touched it.
    await db.pool().execute("DELETE FROM fluxer_patch_notes_config WHERE id='config'")
    cfg = await db.get_fluxer_patch_notes_config()
    assert cfg["trigger_hour"] == 0
    assert cfg["trigger_minute"] == 5

    await db.set_fluxer_patch_notes_config(13, 30)
    cfg = await db.get_fluxer_patch_notes_config()
    assert cfg["trigger_hour"] == 13
    assert cfg["trigger_minute"] == 30

    # Restore the default so other tests in this module see a clean slate.
    await db.set_fluxer_patch_notes_config(0, 5)


async def test_fluxer_patch_notes_log_dedupe_keeps_the_first_count():
    report_date = date(2026, 1, 1)
    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE sent_date=$1", report_date)

    assert await db.get_fluxer_patch_notes_log(report_date) is None
    await db.record_fluxer_patch_notes_sent(report_date, 7)
    row = await db.get_fluxer_patch_notes_log(report_date)
    assert row["commit_count"] == 7

    # A second attempt at recording the same date must not overwrite it
    # (mirrors two scheduler ticks racing past the dedupe check).
    await db.record_fluxer_patch_notes_sent(report_date, 999)
    row = await db.get_fluxer_patch_notes_log(report_date)
    assert row["commit_count"] == 7

    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE sent_date=$1", report_date)


# --------------------------------------------------------- scheduler gating --
async def test_send_fluxer_patch_notes_noop_before_trigger_time(monkeypatch):
    await db.set_fluxer_patch_notes_config(12, 0)
    monkeypatch.setattr(patch_notes, "central_now",
                         lambda: datetime(2026, 5, 1, 11, 59, tzinfo=ZoneInfo("America/Chicago")))
    generated = []
    monkeypatch.setattr(patch_notes, "generate_patch_notes", lambda d: generated.append(d))

    await scheduler._send_fluxer_patch_notes(Bot("test-token"))
    assert generated == []
    await db.set_fluxer_patch_notes_config(0, 5)


async def test_send_fluxer_patch_notes_records_zero_count_with_no_channels_configured(monkeypatch):
    report_date = date(2026, 5, 1)
    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE sent_date=$1", report_date)
    await db.set_fluxer_patch_notes_config(0, 0)
    monkeypatch.setattr(patch_notes, "central_now",
                         lambda: datetime(2026, 5, 2, 0, 1, tzinfo=ZoneInfo("America/Chicago")))
    monkeypatch.setattr(db, "list_guilds_with_fluxer_patch_notes_channel", _empty_list)

    fetched = []
    monkeypatch.setattr(patch_notes, "generate_patch_notes", lambda d: fetched.append(d))
    scheduler._last_patch_notes_attempt = None

    await scheduler._send_fluxer_patch_notes(Bot("test-token"))
    assert fetched == []  # no channels anywhere -> not worth a GitHub call
    row = await db.get_fluxer_patch_notes_log(report_date)
    assert row["commit_count"] == 0

    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE sent_date=$1", report_date)
    await db.set_fluxer_patch_notes_config(0, 5)


async def test_send_fluxer_patch_notes_sends_to_every_configured_guild(guild_id, monkeypatch):
    report_date = date(2026, 5, 3)
    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE sent_date=$1", report_date)
    await db.update_guild_settings(guild_id, fluxer_patch_notes_channel_id="chan555")
    await db.set_fluxer_patch_notes_config(0, 0)
    monkeypatch.setattr(patch_notes, "central_now",
                         lambda: datetime(2026, 5, 4, 0, 1, tzinfo=ZoneInfo("America/Chicago")))

    async def fake_generate(d):
        return {"title": "fake embed"}, 5

    monkeypatch.setattr(patch_notes, "generate_patch_notes", fake_generate)
    scheduler._last_patch_notes_attempt = None

    sent = []

    async def fake_send_message(channel_id, **kw):
        sent.append(channel_id)
        return {"id": "1"}

    bot = Bot("test-token")
    bot.rest.send_message = fake_send_message

    await scheduler._send_fluxer_patch_notes(bot)
    assert "chan555" in sent
    row = await db.get_fluxer_patch_notes_log(report_date)
    assert row["commit_count"] == 5

    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE sent_date=$1", report_date)
    await db.set_fluxer_patch_notes_config(0, 5)


async def _empty_list():
    return []
