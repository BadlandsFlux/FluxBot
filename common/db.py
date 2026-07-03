"""Shared Postgres data layer.

Both the bot process and the dashboard (FastAPI) process import this
module, call `await init_pool()` once at startup, and then share the
same connection pool pattern against the same real Postgres service —
no more file-locking games like SQLite+WAL, both processes can write
concurrently.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import asyncpg

from common.config import config

_pool: Optional[asyncpg.Pool] = None

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


async def init_pool() -> asyncpg.Pool:
    """Create the shared connection pool and ensure the schema exists.

    Safe to call from both the bot and the dashboard on startup — the
    DDL in schema.sql is all `CREATE TABLE IF NOT EXISTS`.
    """
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(
        dsn=config.database_url,
        min_size=config.db_pool_min,
        max_size=config.db_pool_max,
    )
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_PATH.read_text())
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call `await init_pool()` at startup first.")
    return _pool


# ---------------------------------------------------------------- guilds --
async def upsert_guild(guild_id: str, name: str = "", icon: Optional[str] = None) -> None:
    await pool().execute(
        """
        INSERT INTO guilds (guild_id, name, icon, updated_at)
        VALUES ($1, $2, $3, now())
        ON CONFLICT (guild_id) DO UPDATE SET
            name = EXCLUDED.name,
            icon = COALESCE(EXCLUDED.icon, guilds.icon),
            updated_at = now()
        """,
        guild_id, name, icon,
    )


async def get_guild(guild_id: str) -> Optional[asyncpg.Record]:
    return await pool().fetchrow("SELECT * FROM guilds WHERE guild_id = $1", guild_id)


async def list_guilds() -> list[asyncpg.Record]:
    return await pool().fetch("SELECT * FROM guilds ORDER BY name")


_ALLOWED_SETTINGS = {
    "log_channel_id", "mute_role_id", "command_prefix",
    "welcome_channel_id", "welcome_message",
    "warn_timeout_at", "warn_kick_at", "warn_timeout_minutes",
}


async def update_guild_settings(guild_id: str, **fields: Any) -> None:
    sets = {k: v for k, v in fields.items() if k in _ALLOWED_SETTINGS}
    if not sets:
        return
    cols = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(sets))
    await pool().execute(
        f"UPDATE guilds SET {cols}, updated_at = now() WHERE guild_id = $1",
        guild_id, *sets.values(),
    )


# -------------------------------------------------------------- warnings --
async def add_warning(guild_id: str, user_id: str, moderator_id: str, reason: str) -> int:
    row = await pool().fetchrow(
        """
        INSERT INTO warnings (guild_id, user_id, moderator_id, reason)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        guild_id, user_id, moderator_id, reason,
    )
    return row["id"]


async def count_active_warnings(guild_id: str, user_id: str) -> int:
    row = await pool().fetchrow(
        "SELECT COUNT(*) AS c FROM warnings WHERE guild_id=$1 AND user_id=$2 AND active",
        guild_id, user_id,
    )
    return row["c"]


async def list_warnings(guild_id: str, user_id: Optional[str] = None) -> list[asyncpg.Record]:
    if user_id:
        return await pool().fetch(
            "SELECT * FROM warnings WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at DESC",
            guild_id, user_id,
        )
    return await pool().fetch(
        "SELECT * FROM warnings WHERE guild_id=$1 ORDER BY created_at DESC LIMIT 200",
        guild_id,
    )


async def clear_warnings(guild_id: str, user_id: str) -> int:
    result = await pool().execute(
        "UPDATE warnings SET active=FALSE WHERE guild_id=$1 AND user_id=$2 AND active",
        guild_id, user_id,
    )
    # asyncpg returns e.g. "UPDATE 3"
    return int(result.split()[-1])


# ------------------------------------------------------------ mod actions --
async def log_action(guild_id: str, action: str, user_id: str = "", moderator_id: str = "",
                      reason: str = "") -> None:
    await pool().execute(
        """
        INSERT INTO mod_actions (guild_id, user_id, moderator_id, action, reason)
        VALUES ($1, $2, $3, $4, $5)
        """,
        guild_id, user_id, moderator_id, action, reason,
    )


async def list_actions(guild_id: str, limit: int = 100) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM mod_actions WHERE guild_id=$1 ORDER BY created_at DESC LIMIT $2",
        guild_id, limit,
    )


# -------------------------------------------------------- reaction roles --
async def add_reaction_role(guild_id: str, channel_id: str, message_id: str, emoji: str, role_id: str) -> None:
    await pool().execute(
        """
        INSERT INTO reaction_roles (guild_id, channel_id, message_id, emoji, role_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (message_id, emoji) DO UPDATE SET role_id = EXCLUDED.role_id
        """,
        guild_id, channel_id, message_id, emoji, role_id,
    )


async def get_reaction_role(message_id: str, emoji: str) -> Optional[asyncpg.Record]:
    return await pool().fetchrow(
        "SELECT * FROM reaction_roles WHERE message_id=$1 AND emoji=$2", message_id, emoji,
    )


async def list_reaction_roles(guild_id: str) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM reaction_roles WHERE guild_id=$1 ORDER BY id DESC", guild_id,
    )


async def remove_reaction_role(row_id: int) -> None:
    await pool().execute("DELETE FROM reaction_roles WHERE id=$1", row_id)


# -------------------------------------------------------------- autoroles --
async def add_autorole(guild_id: str, role_id: str) -> None:
    await pool().execute(
        "INSERT INTO autoroles (guild_id, role_id) VALUES ($1, $2) "
        "ON CONFLICT (guild_id, role_id) DO NOTHING",
        guild_id, role_id,
    )


async def remove_autorole(guild_id: str, role_id: str) -> None:
    await pool().execute(
        "DELETE FROM autoroles WHERE guild_id=$1 AND role_id=$2", guild_id, role_id,
    )


async def list_autoroles(guild_id: str) -> list[str]:
    rows = await pool().fetch("SELECT role_id FROM autoroles WHERE guild_id=$1", guild_id)
    return [r["role_id"] for r in rows]


# --------------------------------------------------------------------- tags --
async def add_tag(guild_id: str, name: str, content: str, created_by: str = "") -> None:
    await pool().execute(
        """
        INSERT INTO tags (guild_id, name, content, created_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (guild_id, name) DO UPDATE SET content = EXCLUDED.content
        """,
        guild_id, name.lower(), content, created_by,
    )


async def get_tag(guild_id: str, name: str) -> Optional[asyncpg.Record]:
    return await pool().fetchrow(
        "SELECT * FROM tags WHERE guild_id=$1 AND name=$2", guild_id, name.lower(),
    )


async def list_tags(guild_id: str) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM tags WHERE guild_id=$1 ORDER BY name", guild_id,
    )


async def remove_tag(guild_id: str, name: str) -> bool:
    result = await pool().execute(
        "DELETE FROM tags WHERE guild_id=$1 AND name=$2", guild_id, name.lower(),
    )
    return result.split()[-1] != "0"


if __name__ == "__main__":
    # `python -m common.db` — one-off convenience to create the schema
    # without starting the bot or dashboard.
    import asyncio

    async def _main() -> None:
        await init_pool()
        print(f"Schema applied to {config.database_url}")
        await close_pool()

    asyncio.run(_main())
