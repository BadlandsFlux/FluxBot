"""Fluxer patch notes: the timezone-aware date-window math (including DST,
since that's exactly the kind of thing that's easy to get wrong with a
naive UTC offset), the Conventional-Commits theme grouping, the embed
builder, the per-guild dashboard setting round-trip (channel, send
time, and default timezone), the scheduler's per-guild gating/dedupe
logic, and the on-demand !patchnotes command built on the same pieces.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import bot.modules.info as info_mod
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
    assert embed["footer"]["text"] == "3 commits"
    field_names = [f["name"] for f in embed["fields"]]
    # Features before Fixes before Maintenance, regardless of input order.
    assert field_names.index("✨ Features") < field_names.index("🐛 Fixes") < field_names.index("🔧 Maintenance")
    by_name = {f["name"]: f["value"] for f in embed["fields"]}
    assert "[a feature](https://x/2)" in by_name["✨ Features"]
    assert "[a fix](https://x/1)" in by_name["🐛 Fixes"]
    assert "[cleanup](https://x/3)" in by_name["🔧 Maintenance"]


def test_build_patch_notes_embed_singular_commit_count():
    commits = [{"commit": {"message": "fix: one thing"}, "html_url": "https://x/1"}]
    embed = patch_notes.build_patch_notes_embed(commits, date(2026, 10, 8))
    assert embed["footer"]["text"] == "1 commit"


# ------------------------------------------------------- range embed builder --
def test_format_moment_strips_leading_zeroes():
    # Jan 5 (not "Jan 05"), 6:05 AM (not "06:05 AM") -- only strftime's
    # always-zero-padded fields (%M) should keep a leading zero.
    dt = datetime(2026, 1, 5, 6, 5, tzinfo=CENTRAL)
    assert patch_notes._format_moment(dt) == "Jan 5, 2026 6:05 AM CST"


def test_format_moment_handles_noon_and_midnight():
    assert patch_notes._format_moment(datetime(2026, 1, 5, 0, 0, tzinfo=CENTRAL)) == "Jan 5, 2026 12:00 AM CST"
    assert patch_notes._format_moment(datetime(2026, 1, 5, 12, 0, tzinfo=CENTRAL)) == "Jan 5, 2026 12:00 PM CST"


def test_build_patch_notes_range_embed_with_no_commits():
    since = datetime(2026, 10, 23, 18, 5, tzinfo=CENTRAL)
    until = datetime(2026, 10, 24, 9, 30, tzinfo=CENTRAL)
    embed = patch_notes.build_patch_notes_range_embed([], since, until)
    assert "No commits" in embed["description"]
    assert embed["footer"]["text"] == "0 commits"
    assert "Oct 23, 2026 6:05 PM" in embed["title"]
    assert "Oct 24, 2026 9:30 AM" in embed["title"]


def test_build_patch_notes_range_embed_groups_by_theme_in_order():
    since = datetime(2026, 10, 23, 18, 5, tzinfo=CENTRAL)
    until = datetime(2026, 10, 24, 9, 30, tzinfo=CENTRAL)
    commits = [
        {"commit": {"message": "fix(ui): a fix"}, "html_url": "https://x/1"},
        {"commit": {"message": "feat(app): a feature"}, "html_url": "https://x/2"},
    ]
    embed = patch_notes.build_patch_notes_range_embed(commits, since, until)
    assert embed["footer"]["text"] == "2 commits"
    field_names = [f["name"] for f in embed["fields"]]
    assert field_names.index("✨ Features") < field_names.index("🐛 Fixes")


def test_build_patch_notes_embed_overflows_a_busy_day_into_continuation_fields():
    # Previously this many commits in one theme built a single description
    # string that cleared Discord's 4096-char cap and got silently cut off
    # by clamp_embeds; now it spreads across "(cont.)" fields instead, each
    # safely under the 1024-char per-field cap.
    commits = [
        {"commit": {"message": f"fix(area{i}): a fairly descriptive fix description number {i}"},
         "html_url": f"https://x/{i}"}
        for i in range(80)
    ]
    embed = patch_notes.build_patch_notes_embed(commits, date(2026, 10, 8))
    assert embed["footer"]["text"] == "80 commits"
    fix_fields = [f for f in embed["fields"] if f["name"].startswith("🐛 Fixes")]
    assert len(fix_fields) > 1
    assert fix_fields[0]["name"] == "🐛 Fixes"
    assert fix_fields[1]["name"] == "🐛 Fixes (cont.)"
    for f in embed["fields"]:
        assert len(f["value"]) <= 1024
    # Every commit still shows up somewhere, just split across fields.
    all_values = "\n".join(f["value"] for f in embed["fields"])
    assert "[a fairly descriptive fix description number 0](https://x/0)" in all_values
    assert "[a fairly descriptive fix description number 79](https://x/79)" in all_values


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


async def test_get_latest_fluxer_patch_notes_log_none_when_never_sent(guild_id):
    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1", guild_id)
    assert await db.get_latest_fluxer_patch_notes_log(guild_id) is None


async def test_get_latest_fluxer_patch_notes_log_returns_the_most_recent(guild_id):
    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1", guild_id)
    await db.record_fluxer_patch_notes_sent(guild_id, date(2026, 6, 1), 2)
    await db.record_fluxer_patch_notes_sent(guild_id, date(2026, 6, 2), 7)

    row = await db.get_latest_fluxer_patch_notes_log(guild_id)
    assert row["sent_date"] == date(2026, 6, 2)
    assert row["commit_count"] == 7

    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1", guild_id)


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


# --------------------------------------------------------- !patchnotes command --
async def run_patchnotes(bot, guild_id, author_id="u1"):
    """Dispatches !patchnotes and returns (sent_embeds, replies)."""
    sent_embeds = []
    replies = []

    async def fake_send_message(channel_id, content=None, embeds=None, **kw):
        if embeds:
            sent_embeds.append(embeds[0])
        else:
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
        "content": "!patchnotes", "author": {"id": author_id, "username": "tester"},
        "guild_id": guild_id, "channel_id": "chan1",
    }
    await bot._on_message(message)
    return sent_embeds, replies


async def test_patchnotes_uses_the_last_automated_send_as_since(guild_id, monkeypatch):
    bot_obj = Bot("test-token")
    info_mod.register(bot_obj)

    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1", guild_id)
    await db.record_fluxer_patch_notes_sent(guild_id, date(2026, 6, 1), 2)
    log_row = await db.get_latest_fluxer_patch_notes_log(guild_id)

    captured = {}

    async def fake_fetch(since, until):
        captured["since"] = since
        captured["until"] = until
        return []

    monkeypatch.setattr(patch_notes, "fetch_commits_in_range", fake_fetch)
    monkeypatch.setattr(patch_notes, "now_in", lambda tz: datetime(2026, 6, 2, 15, 0, tzinfo=tz))

    sent_embeds, replies = await run_patchnotes(bot_obj, guild_id)
    assert replies == []
    assert len(sent_embeds) == 1
    assert captured["since"] == log_row["sent_at"].astimezone(CENTRAL)
    assert captured["until"] == datetime(2026, 6, 2, 15, 0, tzinfo=CENTRAL)

    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1", guild_id)


async def test_patchnotes_falls_back_to_start_of_today_when_never_sent(guild_id, monkeypatch):
    bot_obj = Bot("test-token")
    info_mod.register(bot_obj)
    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1", guild_id)

    captured = {}

    async def fake_fetch(since, until):
        captured["since"] = since
        captured["until"] = until
        return []

    monkeypatch.setattr(patch_notes, "fetch_commits_in_range", fake_fetch)
    monkeypatch.setattr(patch_notes, "now_in", lambda tz: datetime(2026, 6, 2, 15, 30, tzinfo=tz))

    await run_patchnotes(bot_obj, guild_id)
    assert captured["since"] == datetime(2026, 6, 2, 0, 0, tzinfo=CENTRAL)
    assert captured["until"] == datetime(2026, 6, 2, 15, 30, tzinfo=CENTRAL)


async def test_patchnotes_sends_the_range_embed_it_built(guild_id, monkeypatch):
    bot_obj = Bot("test-token")
    info_mod.register(bot_obj)
    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1", guild_id)

    commits = [{"commit": {"message": "feat(app): a feature"}, "html_url": "https://x/1"}]

    async def fake_fetch(since, until):
        return commits

    monkeypatch.setattr(patch_notes, "fetch_commits_in_range", fake_fetch)
    monkeypatch.setattr(patch_notes, "now_in", lambda tz: datetime(2026, 6, 2, 15, 30, tzinfo=tz))

    sent_embeds, replies = await run_patchnotes(bot_obj, guild_id)
    assert replies == []
    assert len(sent_embeds) == 1
    assert sent_embeds[0]["footer"]["text"] == "1 commit"
    assert "[a feature](https://x/1)" in sent_embeds[0]["fields"][0]["value"]


async def test_patchnotes_replies_with_an_error_on_fetch_failure(guild_id, monkeypatch):
    bot_obj = Bot("test-token")
    info_mod.register(bot_obj)
    await db.pool().execute("DELETE FROM fluxer_patch_notes_log WHERE guild_id=$1", guild_id)

    async def fake_fetch(since, until):
        raise RuntimeError("GitHub is down")

    monkeypatch.setattr(patch_notes, "fetch_commits_in_range", fake_fetch)
    monkeypatch.setattr(patch_notes, "now_in", lambda tz: datetime(2026, 6, 2, 15, 30, tzinfo=tz))

    sent_embeds, replies = await run_patchnotes(bot_obj, guild_id)
    assert sent_embeds == []
    assert len(replies) == 1 and "Couldn't fetch" in replies[0]
