"""Regression tests for two bugs found in a full-codebase audit:

1. warn_member() used to escalate on every call where active_count was
   >= a threshold, not just the call that first crosses it, so two
   warnings landing close together (e.g. counts 3 and 4 against a
   kick-at-3 threshold) could both try to kick an already-kicked member.
2. report_actions.set_status() used to always overwrite resolution_note,
   including with None, so a status change made with no note text wiped
   out whatever note was already on record.
"""
from __future__ import annotations

from bot import moderation_actions as actions
from bot import report_actions
from common import db


class FakeRest:
    def __init__(self, owner_id="owner1"):
        self.kicked = []
        self.timed_out = []
        self.guild = {"id": "g1", "owner_id": owner_id, "roles": []}

    async def get_guild(self, guild_id):
        return self.guild

    async def get_guild_member(self, guild_id, user_id):
        return {"user": {"id": user_id}, "roles": []}

    async def kick_member(self, guild_id, user_id, reason=""):
        self.kicked.append(user_id)

    async def timeout_member(self, guild_id, user_id, until, reason=""):
        self.timed_out.append(user_id)

    async def send_message(self, channel_id, content=None, embeds=None, **kw):
        return {"id": "msg1"}


async def test_warn_escalates_exactly_once_per_threshold(guild_id):
    await db.update_guild_settings(guild_id, warn_kick_at=3, warn_timeout_at=2, warn_timeout_minutes=60)
    rest = FakeRest()
    user = {"id": "target1", "username": "tester"}
    moderator = {"id": "owner1", "username": "mod"}  # the guild owner, bypasses the hierarchy check

    r1 = await actions.warn_member(rest, guild_id, user, moderator, "r1")
    assert r1["active_count"] == 1 and r1["escalated"] is None

    r2 = await actions.warn_member(rest, guild_id, user, moderator, "r2")
    assert r2["active_count"] == 2 and r2["escalated"] == "timeout"
    assert rest.timed_out == ["target1"]

    r3 = await actions.warn_member(rest, guild_id, user, moderator, "r3")
    assert r3["active_count"] == 3 and r3["escalated"] == "kick"
    assert rest.kicked == ["target1"]


async def test_warn_does_not_re_escalate_once_past_the_threshold(guild_id):
    """Simulates the race: two warnings landing such that their counts
    (3 and 4) both end up >= warn_kick_at=3. Only the one that actually
    crosses the threshold (count 3) should kick."""
    await db.update_guild_settings(guild_id, warn_kick_at=3, warn_timeout_at=99, warn_timeout_minutes=60)
    rest = FakeRest()
    user = {"id": "target2", "username": "tester2"}
    moderator = {"id": "owner1", "username": "mod"}

    await db.add_warning_and_count(guild_id, "target2", "mod1", "pre1")
    await db.add_warning_and_count(guild_id, "target2", "mod1", "pre2")

    r_a = await actions.warn_member(rest, guild_id, user, moderator, "rA")
    r_b = await actions.warn_member(rest, guild_id, user, moderator, "rB")

    assert r_a["active_count"] == 3 and r_a["escalated"] == "kick"
    assert r_b["active_count"] == 4 and r_b["escalated"] is None
    assert rest.kicked == ["target2"]


async def test_report_status_change_without_a_note_preserves_the_existing_one(guild_id):
    rest = FakeRest()
    report = await db.create_report(guild_id, "reporter1", "something broke", "chan1", "msg1", visibility="public")

    await report_actions.set_status(rest, guild_id, report["id"], "wontfix",
                                     resolution_note="spam account", resolved_by="staff1", notify=False)
    fetched = await db.get_report(guild_id, report["id"])
    assert fetched["resolution_note"] == "spam account"

    await report_actions.set_status(rest, guild_id, report["id"], "open",
                                     resolution_note=None, resolved_by="staff1", notify=False)
    fetched = await db.get_report(guild_id, report["id"])
    assert fetched["status"] == "open"
    assert fetched["resolution_note"] == "spam account"

    await report_actions.set_status(rest, guild_id, report["id"], "resolved",
                                     resolution_note="fixed now", resolved_by="staff1", notify=False)
    fetched = await db.get_report(guild_id, report["id"])
    assert fetched["resolution_note"] == "fixed now"
