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
        await conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
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
    "goodbye_channel_id", "goodbye_message",
    "leveling_enabled", "level_up_channel_id", "level_up_message",
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
async def add_reaction_role(guild_id: str, channel_id: str, message_id: str, emoji: str, role_id: str,
                             label: str = "") -> None:
    await pool().execute(
        """
        INSERT INTO reaction_roles (guild_id, channel_id, message_id, emoji, role_id, label)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (message_id, emoji) DO UPDATE SET role_id = EXCLUDED.role_id, label = EXCLUDED.label
        """,
        guild_id, channel_id, message_id, emoji, role_id, label,
    )


async def get_reaction_role(message_id: str, emoji: str) -> Optional[asyncpg.Record]:
    return await pool().fetchrow(
        "SELECT * FROM reaction_roles WHERE message_id=$1 AND emoji=$2", message_id, emoji,
    )


async def list_reaction_roles(guild_id: str) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM reaction_roles WHERE guild_id=$1 ORDER BY id DESC", guild_id,
    )


async def get_reaction_roles_by_message(guild_id: str, message_id: str) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM reaction_roles WHERE guild_id=$1 AND message_id=$2", guild_id, message_id,
    )


async def remove_reaction_role(guild_id: str, row_id: int) -> None:
    await pool().execute("DELETE FROM reaction_roles WHERE guild_id=$1 AND id=$2", guild_id, row_id)


async def remove_reaction_roles_by_message(guild_id: str, message_id: str) -> int:
    result = await pool().execute(
        "DELETE FROM reaction_roles WHERE guild_id=$1 AND message_id=$2", guild_id, message_id,
    )
    return int(result.split()[-1])



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


# ---------------------------------------------------------------- reminders --
async def add_reminder(guild_id: str, channel_id: str, user_id: str, content: str,
                        remind_at) -> int:
    row = await pool().fetchrow(
        """
        INSERT INTO reminders (guild_id, channel_id, user_id, content, remind_at)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        guild_id, channel_id, user_id, content, remind_at,
    )
    return row["id"]


async def list_due_reminders(now) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM reminders WHERE NOT delivered AND remind_at <= $1 ORDER BY remind_at", now,
    )


async def mark_reminder_delivered(reminder_id: int) -> None:
    await pool().execute("UPDATE reminders SET delivered=TRUE WHERE id=$1", reminder_id)


async def list_reminders_for_user(guild_id: str, user_id: str) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM reminders WHERE guild_id=$1 AND user_id=$2 AND NOT delivered ORDER BY remind_at",
        guild_id, user_id,
    )


async def remove_reminder(reminder_id: int, user_id: str) -> bool:
    result = await pool().execute(
        "DELETE FROM reminders WHERE id=$1 AND user_id=$2", reminder_id, user_id,
    )
    return result.split()[-1] != "0"


# -------------------------------------------------------------------- polls --
async def add_poll(guild_id: str, channel_id: str, message_id: str, question: str,
                    options: list[str], close_at) -> int:
    import json
    row = await pool().fetchrow(
        """
        INSERT INTO polls (guild_id, channel_id, message_id, question, options, close_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        guild_id, channel_id, message_id, question, json.dumps(options), close_at,
    )
    return row["id"]


async def list_due_polls(now) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM polls WHERE NOT closed AND close_at IS NOT NULL AND close_at <= $1", now,
    )


async def mark_poll_closed(poll_id: int) -> None:
    await pool().execute("UPDATE polls SET closed=TRUE WHERE id=$1", poll_id)


# ------------------------------------------------------------------ leveling --
async def get_level(guild_id: str, user_id: str) -> Optional[asyncpg.Record]:
    return await pool().fetchrow(
        "SELECT * FROM levels WHERE guild_id=$1 AND user_id=$2", guild_id, user_id,
    )


async def add_xp(guild_id: str, user_id: str, amount: int) -> asyncpg.Record:
    """Add XP and return the resulting row (including updated level, computed
    by the caller before calling this — this just persists it)."""
    row = await pool().fetchrow(
        """
        INSERT INTO levels (guild_id, user_id, xp, level, last_xp_at)
        VALUES ($1, $2, $3, 0, now())
        ON CONFLICT (guild_id, user_id) DO UPDATE SET
            xp = levels.xp + $3, last_xp_at = now()
        RETURNING *
        """,
        guild_id, user_id, amount,
    )
    return row


async def set_level(guild_id: str, user_id: str, level: int) -> None:
    await pool().execute(
        "UPDATE levels SET level=$3 WHERE guild_id=$1 AND user_id=$2", guild_id, user_id, level,
    )


async def get_leaderboard(guild_id: str, limit: int = 10) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM levels WHERE guild_id=$1 ORDER BY xp DESC LIMIT $2", guild_id, limit,
    )


async def get_rank(guild_id: str, user_id: str) -> Optional[int]:
    row = await pool().fetchrow(
        """
        SELECT rank FROM (
            SELECT user_id, RANK() OVER (ORDER BY xp DESC) AS rank
            FROM levels WHERE guild_id=$1
        ) ranked WHERE user_id=$2
        """,
        guild_id, user_id,
    )
    return row["rank"] if row else None


async def add_level_role(guild_id: str, level: int, role_id: str) -> None:
    await pool().execute(
        """
        INSERT INTO level_roles (guild_id, level, role_id) VALUES ($1, $2, $3)
        ON CONFLICT (guild_id, level) DO UPDATE SET role_id = EXCLUDED.role_id
        """,
        guild_id, level, role_id,
    )


async def remove_level_role(guild_id: str, level: int) -> None:
    await pool().execute("DELETE FROM level_roles WHERE guild_id=$1 AND level=$2", guild_id, level)


async def list_level_roles(guild_id: str) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM level_roles WHERE guild_id=$1 ORDER BY level", guild_id,
    )


async def get_level_role_for(guild_id: str, level: int) -> Optional[asyncpg.Record]:
    return await pool().fetchrow(
        "SELECT * FROM level_roles WHERE guild_id=$1 AND level=$2", guild_id, level,
    )


# ---------------------------------------------------------------------- stats --
async def record_message(guild_id: str, user_id: str) -> None:
    await pool().execute(
        """
        INSERT INTO guild_daily_stats (guild_id, day, message_count)
        VALUES ($1, CURRENT_DATE, 1)
        ON CONFLICT (guild_id, day) DO UPDATE SET message_count = guild_daily_stats.message_count + 1
        """,
        guild_id,
    )
    await pool().execute(
        """
        INSERT INTO member_message_counts (guild_id, user_id, message_count)
        VALUES ($1, $2, 1)
        ON CONFLICT (guild_id, user_id) DO UPDATE SET message_count = member_message_counts.message_count + 1
        """,
        guild_id, user_id,
    )


async def get_daily_stats(guild_id: str, days: int = 14) -> list[asyncpg.Record]:
    return await pool().fetch(
        """
        SELECT day, message_count, voice_minutes FROM guild_daily_stats
        WHERE guild_id=$1 AND day >= CURRENT_DATE - $2::int
        ORDER BY day
        """,
        guild_id, days,
    )


async def get_top_members(guild_id: str, limit: int = 5) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM member_message_counts WHERE guild_id=$1 ORDER BY message_count DESC LIMIT $2",
        guild_id, limit,
    )


async def get_member_message_count(guild_id: str, user_id: str) -> int:
    row = await pool().fetchrow(
        "SELECT message_count FROM member_message_counts WHERE guild_id=$1 AND user_id=$2",
        guild_id, user_id,
    )
    return row["message_count"] if row else 0


async def get_total_messages(guild_id: str, days: int = 30) -> int:
    row = await pool().fetchrow(
        """
        SELECT COALESCE(SUM(message_count), 0) AS total FROM guild_daily_stats
        WHERE guild_id=$1 AND day >= CURRENT_DATE - $2::int
        """,
        guild_id, days,
    )
    return row["total"]


async def record_voice_minutes(guild_id: str, user_id: str, minutes: float) -> None:
    if minutes <= 0:
        return
    await pool().execute(
        """
        INSERT INTO guild_daily_stats (guild_id, day, voice_minutes)
        VALUES ($1, CURRENT_DATE, $2)
        ON CONFLICT (guild_id, day) DO UPDATE SET voice_minutes = guild_daily_stats.voice_minutes + $2
        """,
        guild_id, minutes,
    )
    await pool().execute(
        """
        INSERT INTO member_voice_minutes (guild_id, user_id, minutes)
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id, user_id) DO UPDATE SET minutes = member_voice_minutes.minutes + $3
        """,
        guild_id, user_id, minutes,
    )


async def get_top_voice_members(guild_id: str, limit: int = 5) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM member_voice_minutes WHERE guild_id=$1 ORDER BY minutes DESC LIMIT $2",
        guild_id, limit,
    )


async def get_member_voice_minutes(guild_id: str, user_id: str) -> float:
    row = await pool().fetchrow(
        "SELECT minutes FROM member_voice_minutes WHERE guild_id=$1 AND user_id=$2",
        guild_id, user_id,
    )
    return float(row["minutes"]) if row else 0.0


if __name__ == "__main__":
    # `python -m common.db` — one-off convenience to create the schema
    # without starting the bot or dashboard.
    import asyncio

    async def _main() -> None:
        await init_pool()
        print(f"Schema applied to {config.database_url}")
        await close_pool()

    asyncio.run(_main())
