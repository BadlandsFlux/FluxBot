"""Shared Postgres data layer.

Both the bot process and the dashboard (FastAPI) process import this
module, call `await init_pool()` once at startup, and then share the
same connection pool pattern against the same real Postgres service,
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

    Safe to call from both the bot and the dashboard on startup, the
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
        raise RuntimeError("DB pool not initialised, call `await init_pool()` at startup first.")
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


async def clear_all_warnings(guild_id: str) -> int:
    """Danger Zone: deactivate every active warning server-wide."""
    result = await pool().execute(
        "UPDATE warnings SET active=FALSE WHERE guild_id=$1 AND active", guild_id,
    )
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


async def get_reaction_role(guild_id: str, message_id: str, emoji: str) -> Optional[asyncpg.Record]:
    return await pool().fetchrow(
        "SELECT * FROM reaction_roles WHERE guild_id=$1 AND message_id=$2 AND emoji=$3", guild_id, message_id, emoji,
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


async def wipe_all_reaction_roles(guild_id: str) -> int:
    """Danger Zone: delete every reaction-role mapping for this guild. Does
    not touch the actual Fluxer messages, just the DB-side mappings, so
    reacting to an old message afterward simply won't do anything anymore."""
    result = await pool().execute("DELETE FROM reaction_roles WHERE guild_id=$1", guild_id)
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


async def count_pending_reminders(guild_id: str, user_id: str) -> int:
    row = await pool().fetchrow(
        "SELECT COUNT(*) AS n FROM reminders WHERE guild_id=$1 AND user_id=$2 AND NOT delivered",
        guild_id, user_id,
    )
    return row["n"]


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
    by the caller before calling this, this just persists it)."""
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


async def reset_all_xp(guild_id: str) -> int:
    """Danger Zone: wipe every member's level/XP for this guild back to
    zero. Doesn't touch message/voice activity stats, those are a
    separate concern from leveling."""
    result = await pool().execute("DELETE FROM levels WHERE guild_id=$1", guild_id)
    return int(result.split()[-1])


async def reset_user_xp(guild_id: str, user_id: str) -> None:
    """Reset a single member's level/XP back to zero (dashboard admin
    correction, distinct from the Danger Zone's server-wide reset)."""
    await pool().execute("DELETE FROM levels WHERE guild_id=$1 AND user_id=$2", guild_id, user_id)


async def adjust_xp(guild_id: str, user_id: str, delta: int) -> asyncpg.Record:
    """Add (or, with a negative delta, remove) a specific amount of XP for
    one member, clamped at zero. Caller is responsible for recomputing and
    persisting `level` from the returned xp (see bot/modules/leveling.py's
    level_for_xp), this function only touches the raw xp value."""
    row = await pool().fetchrow(
        """
        INSERT INTO levels (guild_id, user_id, xp, level, last_xp_at)
        VALUES ($1, $2, GREATEST(0, $3), 0, now())
        ON CONFLICT (guild_id, user_id) DO UPDATE SET
            xp = GREATEST(0, levels.xp + $3)
        RETURNING *
        """,
        guild_id, user_id, delta,
    )
    return row


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
    await pool().execute(
        """
        INSERT INTO activity_heatmap (guild_id, day_of_week, hour, message_count)
        VALUES ($1, EXTRACT(DOW FROM now())::smallint, EXTRACT(HOUR FROM now())::smallint, 1)
        ON CONFLICT (guild_id, day_of_week, hour) DO UPDATE SET message_count = activity_heatmap.message_count + 1
        """,
        guild_id,
    )


async def get_activity_heatmap(guild_id: str) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT day_of_week, hour, message_count FROM activity_heatmap WHERE guild_id=$1", guild_id,
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


async def get_member_message_counts(guild_id: str, user_ids: list[str]) -> dict[str, int]:
    """Batch version of get_member_message_count, one query instead of N,
    for building a member list with counts attached."""
    if not user_ids:
        return {}
    rows = await pool().fetch(
        "SELECT user_id, message_count FROM member_message_counts WHERE guild_id=$1 AND user_id = ANY($2::text[])",
        guild_id, user_ids,
    )
    return {r["user_id"]: r["message_count"] for r in rows}


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


async def get_wrapped_stats(guild_id: str) -> dict:
    """Everything !wrapped needs, gathered in one place rather than
    scattering individual getter calls through the command handler."""
    total_messages_row = await pool().fetchrow(
        "SELECT COALESCE(SUM(message_count), 0) AS total FROM member_message_counts WHERE guild_id=$1", guild_id,
    )
    total_voice_row = await pool().fetchrow(
        "SELECT COALESCE(SUM(minutes), 0) AS total FROM member_voice_minutes WHERE guild_id=$1", guild_id,
    )
    top_chatter = await pool().fetchrow(
        "SELECT * FROM member_message_counts WHERE guild_id=$1 ORDER BY message_count DESC LIMIT 1", guild_id,
    )
    top_voice = await pool().fetchrow(
        "SELECT * FROM member_voice_minutes WHERE guild_id=$1 ORDER BY minutes DESC LIMIT 1", guild_id,
    )
    members_with_xp_row = await pool().fetchrow(
        "SELECT COUNT(*) AS n FROM levels WHERE guild_id=$1 AND xp > 0", guild_id,
    )
    achievements_row = await pool().fetchrow(
        "SELECT COUNT(*) AS n FROM achievements WHERE guild_id=$1", guild_id,
    )
    return {
        "total_messages": total_messages_row["total"],
        "total_voice_minutes": float(total_voice_row["total"]),
        "top_chatter_id": top_chatter["user_id"] if top_chatter else None,
        "top_chatter_count": top_chatter["message_count"] if top_chatter else 0,
        "top_voice_id": top_voice["user_id"] if top_voice else None,
        "top_voice_minutes": float(top_voice["minutes"]) if top_voice else 0.0,
        "members_with_xp": members_with_xp_row["n"],
        "achievements_unlocked": achievements_row["n"],
    }


async def get_member_voice_minutes(guild_id: str, user_id: str) -> float:
    row = await pool().fetchrow(
        "SELECT minutes FROM member_voice_minutes WHERE guild_id=$1 AND user_id=$2",
        guild_id, user_id,
    )
    return float(row["minutes"]) if row else 0.0


# ------------------------------------------------------------ achievements --
async def grant_achievement(guild_id: str, user_id: str, key: str) -> bool:
    """Returns True if this was newly granted, False if they already had it."""
    result = await pool().execute(
        """
        INSERT INTO achievements (guild_id, user_id, key) VALUES ($1, $2, $3)
        ON CONFLICT (guild_id, user_id, key) DO NOTHING
        """,
        guild_id, user_id, key,
    )
    return result.split()[-1] != "0"


async def list_achievements(guild_id: str, user_id: str) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM achievements WHERE guild_id=$1 AND user_id=$2 ORDER BY earned_at", guild_id, user_id,
    )


# ------------------------------------------------------------------ trivia --
async def add_trivia_question(guild_id: str, channel_id: str, message_id: str, question: str,
                               options: list[str], correct_index: int, close_at) -> int:
    import json
    row = await pool().fetchrow(
        """
        INSERT INTO trivia_questions (guild_id, channel_id, message_id, question, options, correct_index, close_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        guild_id, channel_id, message_id, question, json.dumps(options), correct_index, close_at,
    )
    return row["id"]


async def list_due_trivia(now) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM trivia_questions WHERE NOT closed AND close_at <= $1", now,
    )


async def mark_trivia_closed(trivia_id: int) -> None:
    await pool().execute("UPDATE trivia_questions SET closed=TRUE WHERE id=$1", trivia_id)


# ---------------------------------------------------------------------- afk --
async def set_afk(guild_id: str, user_id: str, reason: str) -> None:
    await pool().execute(
        """
        INSERT INTO afk_status (guild_id, user_id, reason, since)
        VALUES ($1, $2, $3, now())
        ON CONFLICT (guild_id, user_id) DO UPDATE SET reason = EXCLUDED.reason, since = now()
        """,
        guild_id, user_id, reason,
    )


async def get_afk(guild_id: str, user_id: str) -> Optional[asyncpg.Record]:
    return await pool().fetchrow(
        "SELECT * FROM afk_status WHERE guild_id=$1 AND user_id=$2", guild_id, user_id,
    )


async def clear_afk(guild_id: str, user_id: str) -> bool:
    result = await pool().execute(
        "DELETE FROM afk_status WHERE guild_id=$1 AND user_id=$2", guild_id, user_id,
    )
    return result.split()[-1] != "0"


async def list_afk_for_users(guild_id: str, user_ids: list[str]) -> list[asyncpg.Record]:
    if not user_ids:
        return []
    return await pool().fetch(
        "SELECT * FROM afk_status WHERE guild_id=$1 AND user_id = ANY($2::text[])",
        guild_id, user_ids,
    )


# ------------------------------------------------------------- staff notes --
async def add_staff_note(guild_id: str, user_id: str, note: str, created_by: str) -> int:
    row = await pool().fetchrow(
        """
        INSERT INTO staff_notes (guild_id, user_id, note, created_by)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        guild_id, user_id, note, created_by,
    )
    return row["id"]


async def list_staff_notes(guild_id: str, user_id: str) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM staff_notes WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at DESC",
        guild_id, user_id,
    )


async def remove_staff_note(guild_id: str, note_id: int) -> bool:
    result = await pool().execute(
        "DELETE FROM staff_notes WHERE guild_id=$1 AND id=$2", guild_id, note_id,
    )
    return result.split()[-1] != "0"


# ------------------------------------------------------ xp channel exclusion --
async def add_xp_excluded_channel(guild_id: str, channel_id: str) -> None:
    await pool().execute(
        "INSERT INTO xp_excluded_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        guild_id, channel_id,
    )


async def remove_xp_excluded_channel(guild_id: str, channel_id: str) -> None:
    await pool().execute(
        "DELETE FROM xp_excluded_channels WHERE guild_id=$1 AND channel_id=$2", guild_id, channel_id,
    )


async def list_xp_excluded_channels(guild_id: str) -> list[str]:
    rows = await pool().fetch(
        "SELECT channel_id FROM xp_excluded_channels WHERE guild_id=$1", guild_id,
    )
    return [r["channel_id"] for r in rows]


async def is_xp_excluded_channel(guild_id: str, channel_id: str) -> bool:
    row = await pool().fetchrow(
        "SELECT 1 FROM xp_excluded_channels WHERE guild_id=$1 AND channel_id=$2", guild_id, channel_id,
    )
    return row is not None


# -------------------------------------------------------- xp role multipliers --
async def set_xp_role_multiplier(guild_id: str, role_id: str, multiplier: float) -> None:
    await pool().execute(
        """
        INSERT INTO xp_role_multipliers (guild_id, role_id, multiplier) VALUES ($1, $2, $3)
        ON CONFLICT (guild_id, role_id) DO UPDATE SET multiplier = EXCLUDED.multiplier
        """,
        guild_id, role_id, multiplier,
    )


async def remove_xp_role_multiplier(guild_id: str, role_id: str) -> None:
    await pool().execute(
        "DELETE FROM xp_role_multipliers WHERE guild_id=$1 AND role_id=$2", guild_id, role_id,
    )


async def list_xp_role_multipliers(guild_id: str) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM xp_role_multipliers WHERE guild_id=$1 ORDER BY multiplier DESC", guild_id,
    )


async def get_xp_multiplier_for_roles(guild_id: str, role_ids: list[str]) -> float:
    """Highest multiplier among the member's roles, not stacked/multiplied
    together, so having several boosted roles doesn't compound into a
    runaway rate. 1.0 (no change) if the member has no multiplier-carrying
    role or the guild has none configured."""
    if not role_ids:
        return 1.0
    row = await pool().fetchrow(
        "SELECT MAX(multiplier) AS m FROM xp_role_multipliers WHERE guild_id=$1 AND role_id = ANY($2::text[])",
        guild_id, role_ids,
    )
    return float(row["m"]) if row and row["m"] is not None else 1.0


# -------------------------------------------------------------- command usage --
async def record_command_usage(guild_id: str, command_name: str) -> None:
    await pool().execute(
        """
        INSERT INTO command_usage (guild_id, command_name, count) VALUES ($1, $2, 1)
        ON CONFLICT (guild_id, command_name) DO UPDATE SET count = command_usage.count + 1
        """,
        guild_id, command_name,
    )


async def get_top_commands(guild_id: str, limit: int = 10) -> list[asyncpg.Record]:
    return await pool().fetch(
        "SELECT * FROM command_usage WHERE guild_id=$1 ORDER BY count DESC LIMIT $2", guild_id, limit,
    )


# --------------------------------------------------------------- bot status --
async def update_bot_status(started_at, gateway_latency_ms: Optional[float], guild_count: int) -> None:
    await pool().execute(
        """
        INSERT INTO bot_status (id, started_at, last_heartbeat_at, gateway_latency_ms, guild_count)
        VALUES ('bot', $1, now(), $2, $3)
        ON CONFLICT (id) DO UPDATE SET
            started_at = EXCLUDED.started_at,
            last_heartbeat_at = now(),
            gateway_latency_ms = EXCLUDED.gateway_latency_ms,
            guild_count = EXCLUDED.guild_count
        """,
        started_at, gateway_latency_ms, guild_count,
    )


async def get_bot_status() -> Optional[asyncpg.Record]:
    return await pool().fetchrow("SELECT * FROM bot_status WHERE id='bot'")


# -------------------------------------------------------------- activity log --
async def get_activity_log_settings(guild_id: str) -> Optional[asyncpg.Record]:
    return await pool().fetchrow("SELECT * FROM activity_log_settings WHERE guild_id=$1", guild_id)


async def set_activity_log_settings(
    guild_id: str, *, log_channel_id: Optional[str],
    log_message_edits: bool, log_message_deletes: bool,
    log_member_joins: bool, log_member_leaves: bool,
    log_channel_changes: bool, log_role_changes: bool, log_voice_activity: bool,
    log_privileged_role_changes: bool,
) -> None:
    await pool().execute(
        """
        INSERT INTO activity_log_settings (
            guild_id, log_channel_id, log_message_edits, log_message_deletes,
            log_member_joins, log_member_leaves, log_channel_changes, log_role_changes, log_voice_activity,
            log_privileged_role_changes
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (guild_id) DO UPDATE SET
            log_channel_id = EXCLUDED.log_channel_id,
            log_message_edits = EXCLUDED.log_message_edits,
            log_message_deletes = EXCLUDED.log_message_deletes,
            log_member_joins = EXCLUDED.log_member_joins,
            log_member_leaves = EXCLUDED.log_member_leaves,
            log_channel_changes = EXCLUDED.log_channel_changes,
            log_role_changes = EXCLUDED.log_role_changes,
            log_voice_activity = EXCLUDED.log_voice_activity,
            log_privileged_role_changes = EXCLUDED.log_privileged_role_changes
        """,
        guild_id, log_channel_id, log_message_edits, log_message_deletes,
        log_member_joins, log_member_leaves, log_channel_changes, log_role_changes, log_voice_activity,
        log_privileged_role_changes,
    )


async def add_ignored_log_user(guild_id: str, user_id: str) -> None:
    await pool().execute(
        "INSERT INTO activity_log_ignored_users (guild_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        guild_id, user_id,
    )


async def remove_ignored_log_user(guild_id: str, user_id: str) -> None:
    await pool().execute(
        "DELETE FROM activity_log_ignored_users WHERE guild_id=$1 AND user_id=$2", guild_id, user_id,
    )


async def list_ignored_log_users(guild_id: str) -> list[str]:
    rows = await pool().fetch("SELECT user_id FROM activity_log_ignored_users WHERE guild_id=$1", guild_id)
    return [r["user_id"] for r in rows]


async def is_ignored_log_user(guild_id: str, user_id: str) -> bool:
    row = await pool().fetchrow(
        "SELECT 1 FROM activity_log_ignored_users WHERE guild_id=$1 AND user_id=$2", guild_id, user_id,
    )
    return row is not None
async def set_bot_avatar(image_bytes: bytes, mimetype: str) -> None:
    await pool().execute(
        """
        INSERT INTO bot_profile (id, avatar_bytes, avatar_mimetype, updated_at)
        VALUES ('bot', $1, $2, now())
        ON CONFLICT (id) DO UPDATE SET
            avatar_bytes = EXCLUDED.avatar_bytes,
            avatar_mimetype = EXCLUDED.avatar_mimetype,
            updated_at = now()
        """,
        image_bytes, mimetype,
    )


async def get_bot_avatar() -> Optional[asyncpg.Record]:
    return await pool().fetchrow("SELECT * FROM bot_profile WHERE id='bot'")


# ------------------------------------------------------------ discord relay --
async def add_discord_relay_mapping(fluxer_guild_id: str, discord_channel_id: str, fluxer_channel_id: str,
                                     direction: str = "discord_to_fluxer", show_attribution: bool = True,
                                     created_by: Optional[str] = None) -> None:
    # The UNIQUE constraint is on (discord_channel_id, fluxer_channel_id)
    # alone, not scoped to a guild, since a mapping legitimately belongs
    # to whichever Fluxer guild owns that fluxer_channel_id, not
    # something a second guild should ever be able to reassign. Checked
    # explicitly rather than letting ON CONFLICT DO UPDATE blindly take
    # over an existing row: found this exact gap via testing (two
    # different test guilds happened to reuse the same fake channel ids,
    # and the second guild's "add" silently repointed the first guild's
    # mapping, not just updated its own).
    existing = await pool().fetchrow(
        "SELECT fluxer_guild_id FROM discord_relay_mappings WHERE discord_channel_id=$1 AND fluxer_channel_id=$2",
        discord_channel_id, fluxer_channel_id,
    )
    if existing and existing["fluxer_guild_id"] != fluxer_guild_id:
        raise ValueError("This exact Discord/Fluxer channel pairing is already mapped under a different server.")
    await pool().execute(
        """
        INSERT INTO discord_relay_mappings (fluxer_guild_id, discord_channel_id, fluxer_channel_id, direction, show_attribution, created_by)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (discord_channel_id, fluxer_channel_id)
        DO UPDATE SET direction = EXCLUDED.direction, show_attribution = EXCLUDED.show_attribution,
            enabled = TRUE, created_by = EXCLUDED.created_by
        """,
        fluxer_guild_id, discord_channel_id, fluxer_channel_id, direction, show_attribution, created_by,
    )


async def remove_discord_relay_mapping(mapping_id: int, fluxer_guild_id: str) -> None:
    # Scoped to the guild too, not just the row id, so a dashboard user
    # can only ever remove a mapping that actually belongs to a guild
    # they manage, not an arbitrary id.
    await pool().execute(
        "DELETE FROM discord_relay_mappings WHERE id=$1 AND fluxer_guild_id=$2", mapping_id, fluxer_guild_id,
    )


async def set_discord_relay_mapping_enabled(mapping_id: int, fluxer_guild_id: str, enabled: bool) -> None:
    # Same guild-scoping as remove, above, for the same reason.
    await pool().execute(
        "UPDATE discord_relay_mappings SET enabled=$3 WHERE id=$1 AND fluxer_guild_id=$2",
        mapping_id, fluxer_guild_id, enabled,
    )


async def list_discord_relay_mappings_for_guild(fluxer_guild_id: str) -> list[asyncpg.Record]:
    # Deliberately not filtered by enabled here, the dashboard needs to
    # show (and let someone re-enable) a paused mapping, not just active
    # ones.
    return await pool().fetch(
        "SELECT * FROM discord_relay_mappings WHERE fluxer_guild_id=$1 ORDER BY created_at", fluxer_guild_id,
    )


async def get_discord_relay_mapping(mapping_id: int, fluxer_guild_id: str) -> Optional[asyncpg.Record]:
    return await pool().fetchrow(
        "SELECT * FROM discord_relay_mappings WHERE id=$1 AND fluxer_guild_id=$2", mapping_id, fluxer_guild_id,
    )


async def get_discord_relay_mapping_by_id(mapping_id: int) -> Optional[asyncpg.Record]:
    """Unscoped lookup, used internally by the relay's own edit/delete
    sync (bot/discord_relay.py), not exposed through any dashboard
    endpoint. Those go through the guild-scoped version above instead."""
    return await pool().fetchrow("SELECT * FROM discord_relay_mappings WHERE id=$1", mapping_id)


async def list_discord_relay_mappings_for_discord_channel(discord_channel_id: str) -> list[asyncpg.Record]:
    """What the relay calls on every incoming DISCORD message: which
    Fluxer channel(s), if any, is this Discord channel mapped to, and in
    which direction. Only enabled rows with direction 'discord_to_fluxer'
    or 'both' actually forward that way, filtered here rather than by
    the caller so every call site can't forget the check."""
    return await pool().fetch(
        """
        SELECT * FROM discord_relay_mappings
        WHERE discord_channel_id=$1 AND direction IN ('discord_to_fluxer', 'both') AND enabled
        """,
        discord_channel_id,
    )


async def list_discord_relay_mappings_for_fluxer_channel(fluxer_channel_id: str) -> list[asyncpg.Record]:
    """The Fluxer-side mirror of the function above: what the relay
    calls on every incoming FLUXER message, to find which Discord
    channel(s) it should also go to. Same direction and enabled
    filtering, just the other two direction values."""
    return await pool().fetch(
        """
        SELECT * FROM discord_relay_mappings
        WHERE fluxer_channel_id=$1 AND direction IN ('fluxer_to_discord', 'both') AND enabled
        """,
        fluxer_channel_id,
    )


async def list_all_watched_discord_channels() -> list[str]:
    """Every distinct Discord channel ID with at least one enabled
    Discord-to-Fluxer (or both-direction) mapping, called once at relay
    startup so the client knows what it's supposed to be watching for."""
    rows = await pool().fetch(
        "SELECT DISTINCT discord_channel_id FROM discord_relay_mappings WHERE direction IN ('discord_to_fluxer', 'both') AND enabled",
    )
    return [r["discord_channel_id"] for r in rows]


# ---------------------------------------------------- discord relay: token --
async def get_discord_relay_token() -> Optional[str]:
    row = await pool().fetchrow("SELECT bot_token FROM discord_relay_config WHERE id='relay'")
    return row["bot_token"] if row else None


async def set_discord_relay_token(token: Optional[str]) -> None:
    """token=None clears it (falls back to DISCORD_BOT_TOKEN, if any),
    same as leaving the dashboard field blank."""
    await pool().execute(
        """
        INSERT INTO discord_relay_config (id, bot_token, updated_at) VALUES ('relay', $1, now())
        ON CONFLICT (id) DO UPDATE SET bot_token = EXCLUDED.bot_token, updated_at = now()
        """,
        token,
    )


# --------------------------------------------------- discord relay: status --
async def update_discord_relay_status(*, connected: bool, discord_username: Optional[str] = None,
                                       discord_bot_id: Optional[str] = None, error: Optional[str] = None) -> None:
    await pool().execute(
        """
        INSERT INTO discord_relay_status (id, connected, discord_username, discord_bot_id, last_connected_at, last_error, last_error_at, updated_at)
        VALUES ('relay', $1::boolean, $2::text, $4::text, CASE WHEN $1::boolean THEN now() ELSE NULL END,
                $3::text, CASE WHEN $3::text IS NOT NULL THEN now() ELSE NULL END, now())
        ON CONFLICT (id) DO UPDATE SET
            connected = EXCLUDED.connected,
            discord_username = COALESCE(EXCLUDED.discord_username, discord_relay_status.discord_username),
            discord_bot_id = COALESCE(EXCLUDED.discord_bot_id, discord_relay_status.discord_bot_id),
            last_connected_at = CASE WHEN EXCLUDED.connected THEN now() ELSE discord_relay_status.last_connected_at END,
            last_error = COALESCE(EXCLUDED.last_error, discord_relay_status.last_error),
            last_error_at = CASE WHEN EXCLUDED.last_error IS NOT NULL THEN now() ELSE discord_relay_status.last_error_at END,
            updated_at = now()
        """,
        connected, discord_username, error, discord_bot_id,
    )


async def get_discord_relay_status() -> Optional[asyncpg.Record]:
    return await pool().fetchrow("SELECT * FROM discord_relay_status WHERE id='relay'")


# ----------------------------------------- discord relay: message linking --
async def add_relay_message_link(mapping_id: int, source_platform: str, source_message_id: str,
                                  target_platform: str, target_message_id: str, target_channel_id: str,
                                  sent_via_webhook: bool = False) -> None:
    await pool().execute(
        """
        INSERT INTO discord_relay_message_links
            (mapping_id, source_platform, source_message_id, target_platform, target_message_id, target_channel_id, sent_via_webhook)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        mapping_id, source_platform, source_message_id, target_platform, target_message_id, target_channel_id, sent_via_webhook,
    )


async def get_relay_message_links(source_platform: str, source_message_id: str) -> list[asyncpg.Record]:
    """Every relayed copy of a given source message, so an edit or
    delete can find and mirror the change wherever it landed."""
    return await pool().fetch(
        "SELECT * FROM discord_relay_message_links WHERE source_platform=$1 AND source_message_id=$2",
        source_platform, source_message_id,
    )


async def delete_relay_message_link(link_id: int) -> None:
    await pool().execute("DELETE FROM discord_relay_message_links WHERE id=$1", link_id)


# --------------------------------------------------- discord relay: webhooks --
async def get_relay_webhook(platform: str, channel_id: str) -> Optional[asyncpg.Record]:
    return await pool().fetchrow(
        "SELECT * FROM discord_relay_webhooks WHERE platform=$1 AND channel_id=$2", platform, channel_id,
    )


async def save_relay_webhook(platform: str, channel_id: str, webhook_id: str, webhook_token: str) -> None:
    await pool().execute(
        """
        INSERT INTO discord_relay_webhooks (platform, channel_id, webhook_id, webhook_token)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (platform, channel_id) DO UPDATE SET webhook_id = EXCLUDED.webhook_id, webhook_token = EXCLUDED.webhook_token
        """,
        platform, channel_id, webhook_id, webhook_token,
    )


async def delete_relay_webhook(platform: str, channel_id: str) -> None:
    """Called when execution fails because the webhook no longer
    exists (deleted from the channel's integrations directly), so the
    next attempt creates a fresh one instead of retrying a dead one
    forever."""
    await pool().execute("DELETE FROM discord_relay_webhooks WHERE platform=$1 AND channel_id=$2", platform, channel_id)


async def prune_old_relay_message_links(older_than_days: int = 30) -> int:
    """Called periodically by the scheduler. An edit/delete arriving for
    a message old enough to have already been pruned just doesn't get
    mirrored, the same graceful-miss behavior as message_cache.py's
    aged-out entries, not an error condition."""
    result = await pool().execute(
        "DELETE FROM discord_relay_message_links WHERE created_at < now() - ($1 || ' days')::interval",
        str(older_than_days),
    )
    # asyncpg's execute() returns a string like "DELETE 42"
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


if __name__ == "__main__":
    # `python -m common.db`, one-off convenience to create the schema
    # without starting the bot or dashboard.
    import asyncio

    async def _main() -> None:
        await init_pool()
        print(f"Schema applied to {config.database_url}")
        await close_pool()

    asyncio.run(_main())
