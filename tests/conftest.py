"""Shared pytest fixtures.

Tests run against a real Postgres instance (DATABASE_URL, e.g. the CI
workflow's postgres service container) rather than mocking the DB
layer: asyncpg/Postgres behavior (constraints, ON CONFLICT, CASCADE
deletes) is part of what's worth testing here, not something a mock
would stand in for. `db.init_pool()` already applies schema.sql itself
(it's all idempotent `CREATE TABLE IF NOT EXISTS`), so no separate
migration step is needed before running the suite.
"""
from __future__ import annotations

import uuid

import pytest

from common import db


@pytest.fixture(autouse=True)
async def _db_pool():
    # Function-scoped (one connect/disconnect per test) rather than
    # session-scoped: pytest-asyncio gives each test its own event loop by
    # default, and an asyncpg pool created in one loop can't be reused from
    # another. Connecting per test is cheap against a local Postgres and
    # avoids having to pin a shared loop scope just for this.
    await db.init_pool()
    yield
    await db.close_pool()


@pytest.fixture
async def guild_id(_db_pool):
    """A fresh guild row per test, cleaned up afterward. ON DELETE CASCADE
    on every guild-scoped table means this one delete also drops every
    autorole/reaction-role/warning/etc row the test created along the way."""
    gid = str(uuid.uuid4().int & ((1 << 63) - 1))
    await db.upsert_guild(gid, name="pytest guild")
    yield gid
    await db.pool().execute("DELETE FROM guilds WHERE guild_id=$1", gid)


@pytest.fixture
async def second_guild_id(_db_pool):
    """A second fresh guild row, for tests that need two distinct guilds
    at once (e.g. verifying a shared fetch batches across guilds due in
    the same scheduler tick)."""
    gid = str(uuid.uuid4().int & ((1 << 63) - 1))
    await db.upsert_guild(gid, name="pytest guild 2")
    yield gid
    await db.pool().execute("DELETE FROM guilds WHERE guild_id=$1", gid)
