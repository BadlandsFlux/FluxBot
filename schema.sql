-- Fluxer moderation bot, Postgres schema
-- Apply with: psql "$DATABASE_URL" -f schema.sql
-- (or just run `python -m common.db` once, which executes this same DDL)

CREATE TABLE IF NOT EXISTS guilds (
    guild_id              TEXT PRIMARY KEY,
    name                  TEXT NOT NULL DEFAULT '',
    icon                  TEXT,
    log_channel_id        TEXT,
    mute_role_id          TEXT,
    command_prefix        TEXT NOT NULL DEFAULT '!',
    warn_timeout_at       INTEGER NOT NULL DEFAULT 3,   -- warn count that triggers auto-timeout
    warn_kick_at          INTEGER NOT NULL DEFAULT 5,   -- warn count that triggers auto-kick
    warn_timeout_minutes  INTEGER NOT NULL DEFAULT 60,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS warnings (
    id            BIGSERIAL PRIMARY KEY,
    guild_id      TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id       TEXT NOT NULL,
    moderator_id  TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mod_actions (
    id            BIGSERIAL PRIMARY KEY,
    guild_id      TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id       TEXT,
    moderator_id  TEXT,
    action        TEXT NOT NULL,   -- kick / ban / unban / timeout / untimeout / warn / purge
    reason        TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reaction_roles (
    id          BIGSERIAL PRIMARY KEY,
    guild_id    TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    channel_id  TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    emoji       TEXT NOT NULL,
    role_id     TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    UNIQUE(message_id, emoji)
);

CREATE TABLE IF NOT EXISTS autoroles (
    id        BIGSERIAL PRIMARY KEY,
    guild_id  TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    role_id   TEXT NOT NULL,
    UNIQUE(guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS tags (
    id           BIGSERIAL PRIMARY KEY,
    guild_id     TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    content      TEXT NOT NULL,
    created_by   TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS reminders (
    id            BIGSERIAL PRIMARY KEY,
    guild_id      TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    channel_id    TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    content       TEXT NOT NULL,
    remind_at     TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered     BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS polls (
    id            BIGSERIAL PRIMARY KEY,
    guild_id      TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    channel_id    TEXT NOT NULL,
    message_id    TEXT NOT NULL,
    question      TEXT NOT NULL,
    options       JSONB NOT NULL,   -- ["Option A", "Option B", ...] in emoji order
    close_at      TIMESTAMPTZ,      -- NULL = never auto-closes
    closed        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS levels (
    guild_id        TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL,
    xp              BIGINT NOT NULL DEFAULT 0,
    level           INTEGER NOT NULL DEFAULT 0,
    last_xp_at      TIMESTAMPTZ,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS level_roles (
    id          BIGSERIAL PRIMARY KEY,
    guild_id    TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    level       INTEGER NOT NULL,
    role_id     TEXT NOT NULL,
    UNIQUE(guild_id, level)
);

CREATE TABLE IF NOT EXISTS guild_daily_stats (
    guild_id        TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    day             DATE NOT NULL,
    message_count   BIGINT NOT NULL DEFAULT 0,
    voice_minutes   DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, day)
);

CREATE TABLE IF NOT EXISTS member_message_counts (
    guild_id        TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL,
    message_count   BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS member_voice_minutes (
    guild_id        TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL,
    minutes         DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_mod_actions_guild   ON mod_actions(guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reaction_roles_msg  ON reaction_roles(message_id);
CREATE INDEX IF NOT EXISTS idx_tags_guild          ON tags(guild_id);
CREATE INDEX IF NOT EXISTS idx_reminders_due        ON reminders(remind_at) WHERE NOT delivered;
CREATE INDEX IF NOT EXISTS idx_polls_due            ON polls(close_at) WHERE NOT closed;
CREATE INDEX IF NOT EXISTS idx_levels_guild_xp      ON levels(guild_id, xp DESC);
CREATE INDEX IF NOT EXISTS idx_guild_daily_stats    ON guild_daily_stats(guild_id, day);
CREATE INDEX IF NOT EXISTS idx_member_msg_counts    ON member_message_counts(guild_id, message_count DESC);
CREATE INDEX IF NOT EXISTS idx_member_voice_minutes ON member_voice_minutes(guild_id, minutes DESC);

-- Migration for databases created before command_prefix existed.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS command_prefix TEXT NOT NULL DEFAULT '!';

-- Migration for databases created before welcome messages existed.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS welcome_channel_id TEXT;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS welcome_message TEXT NOT NULL DEFAULT
    'Welcome {user} to {server}! 👋';

-- Migration for databases created before reaction role labels existed.
ALTER TABLE reaction_roles ADD COLUMN IF NOT EXISTS label TEXT NOT NULL DEFAULT '';

-- Migration for databases created before goodbye messages existed.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS goodbye_channel_id TEXT;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS goodbye_message TEXT NOT NULL DEFAULT
    '{username} left {server}. 👋';

-- Migration for databases created before leveling existed.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS leveling_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS level_up_channel_id TEXT;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS level_up_message TEXT NOT NULL DEFAULT
    'GG {user}, you reached level {level}! 🎉';

-- Migration for databases created before voice activity tracking existed.
ALTER TABLE guild_daily_stats ADD COLUMN IF NOT EXISTS voice_minutes DOUBLE PRECISION NOT NULL DEFAULT 0;

-- Migration: voice_minutes/minutes were originally BIGINT, which silently
-- truncates every fractional-minute write (the scheduler credits ~0.25
-- minutes per 15s tick) down to 0, so the total could never move no matter
-- how long someone stayed connected. Safe no-op if already the right type.
ALTER TABLE guild_daily_stats ALTER COLUMN voice_minutes TYPE DOUBLE PRECISION;
ALTER TABLE member_voice_minutes ALTER COLUMN minutes TYPE DOUBLE PRECISION;

-- One-time repair for rows created before common/db.py explicitly read this
-- file as UTF-8. Path.read_text() with no encoding argument uses the
-- platform's default locale encoding, which on Windows is commonly cp1252,
-- not UTF-8, so every emoji below got mangled into mojibake (e.g. "🎉"
-- became "ðŸŽ‰") the moment a guild row was created on an affected install.
-- Matches the exact corrupted byte sequence only, not a prefix, so a
-- legitimate custom message that happens to start with similar wording
-- (e.g. "Welcome {user} to {server}! Enjoy your stay...") is never touched.
UPDATE guilds SET welcome_message = 'Welcome {user} to {server}! 👋'
    WHERE welcome_message = 'Welcome {user} to {server}! ðŸ‘‹';
UPDATE guilds SET goodbye_message = '{username} left {server}. 👋'
    WHERE goodbye_message = '{username} left {server}. ðŸ‘‹';
UPDATE guilds SET level_up_message = 'GG {user}, you reached level {level}! 🎉'
    WHERE level_up_message = 'GG {user}, you reached level {level}! ðŸŽ‰';

CREATE TABLE IF NOT EXISTS achievements (
    guild_id    TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
    key         TEXT NOT NULL,
    earned_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id, key)
);
CREATE TABLE IF NOT EXISTS trivia_questions (
    id              BIGSERIAL PRIMARY KEY,
    guild_id        TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    channel_id      TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    question        TEXT NOT NULL,
    options         JSONB NOT NULL,
    correct_index   INTEGER NOT NULL,
    close_at        TIMESTAMPTZ NOT NULL,
    closed          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trivia_due ON trivia_questions(close_at) WHERE NOT closed;
CREATE TABLE IF NOT EXISTS afk_status (
    guild_id    TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT 'AFK',
    since       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS staff_notes (
    id          BIGSERIAL PRIMARY KEY,
    guild_id    TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
    note        TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_staff_notes_guild_user ON staff_notes(guild_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_staff_notes_guild_user ON staff_notes(guild_id, user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS xp_excluded_channels (
    guild_id    TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    channel_id  TEXT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS xp_role_multipliers (
    guild_id    TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    role_id     TEXT NOT NULL,
    multiplier  NUMERIC NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS command_usage (
    guild_id      TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    command_name  TEXT NOT NULL,
    count         BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, command_name)
);

-- Singleton row: the bot and dashboard run as separate processes (see
-- deploy/*.service), so the dashboard's public status page can't read the
-- bot's in-memory gateway state directly. The bot writes its own liveness
-- here periodically; the dashboard reads it and treats a stale
-- last_heartbeat_at as "the bot is down", not just "the dashboard is up".
CREATE TABLE IF NOT EXISTS bot_status (
    id                  TEXT PRIMARY KEY DEFAULT 'bot',
    started_at          TIMESTAMPTZ NOT NULL,
    last_heartbeat_at   TIMESTAMPTZ NOT NULL,
    gateway_latency_ms  DOUBLE PRECISION,
    guild_count         INTEGER NOT NULL DEFAULT 0
);

-- One row per (day of week, hour) bucket, 168 max per guild, not per
-- individual message, so this stays small regardless of server activity
-- volume. day_of_week follows Postgres's EXTRACT(DOW ...) convention:
-- 0 = Sunday ... 6 = Saturday. Bucketed in UTC (same as everything else in
-- this project), not each admin's local time.
CREATE TABLE IF NOT EXISTS activity_heatmap (
    guild_id       TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    day_of_week    SMALLINT NOT NULL,
    hour           SMALLINT NOT NULL,
    message_count  BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, day_of_week, hour)
);

-- Configurable server-activity logging (message edits/deletes, member
-- join/leave, channel/role changes, voice activity), distinct from the
-- existing mod_actions log which only covers actions this bot itself took.
-- Everything defaults OFF: a brand new guild row shouldn't suddenly start
-- posting to a channel that was never actually configured.
CREATE TABLE IF NOT EXISTS activity_log_settings (
    guild_id             TEXT PRIMARY KEY REFERENCES guilds(guild_id) ON DELETE CASCADE,
    log_channel_id       TEXT,
    log_message_edits    BOOLEAN NOT NULL DEFAULT FALSE,
    log_message_deletes  BOOLEAN NOT NULL DEFAULT FALSE,
    log_member_joins     BOOLEAN NOT NULL DEFAULT FALSE,
    log_member_leaves    BOOLEAN NOT NULL DEFAULT FALSE,
    log_channel_changes  BOOLEAN NOT NULL DEFAULT FALSE,
    log_role_changes     BOOLEAN NOT NULL DEFAULT FALSE,
    log_voice_activity   BOOLEAN NOT NULL DEFAULT FALSE,
    -- Distinct from log_role_changes: that one is about role OBJECTS
    -- (created/updated/deleted), this is about a MEMBER gaining or
    -- losing a role that carries elevated permissions (see
    -- bot/permissions.py's PRIVILEGED_PERMISSION_BITS), a much smaller,
    -- security-relevant subset worth being able to watch independently
    -- of general role-object noise.
    log_privileged_role_changes BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS activity_log_ignored_users (
    guild_id    TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- Singleton row, same pattern as bot_status: the bot's own avatar (set via
-- the dashboard, applied to the bot's Fluxer profile) and the dashboard's
-- favicon are the same uploaded image, stored here so the favicon can be
-- served dynamically without a frontend rebuild.
CREATE TABLE IF NOT EXISTS bot_profile (
    id               TEXT PRIMARY KEY DEFAULT 'bot',
    avatar_bytes     BYTEA NOT NULL,
    avatar_mimetype  TEXT NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One Discord channel can feed multiple Fluxer channels (e.g. two
-- different communities both wanting the same announcements), so this
-- isn't unique on discord_channel_id alone, it's unique on the pairing.
-- One Discord bot token/connection (DISCORD_BOT_TOKEN) serves every
-- mapping across every Fluxer guild, matching how the Fluxer bot token
-- itself is a single bot-wide credential.
CREATE TABLE IF NOT EXISTS discord_relay_mappings (
    id                   BIGSERIAL PRIMARY KEY,
    discord_channel_id   TEXT NOT NULL,
    fluxer_guild_id      TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    fluxer_channel_id    TEXT NOT NULL,
    -- 'discord_to_fluxer' (the original ask: Discord's own announcement-
    -- following aggregates into one channel, relay it onward), or
    -- 'both' for two-way. 'fluxer_to_discord' alone is supported too
    -- (symmetry, and there's no real reason to disallow it) even though
    -- it's not the motivating use case.
    direction            TEXT NOT NULL DEFAULT 'discord_to_fluxer'
                          CHECK (direction IN ('discord_to_fluxer', 'fluxer_to_discord', 'both')),
    -- Pause a mapping without losing its configuration (and without the
    -- UNIQUE constraint below fighting you if you want to briefly stop,
    -- then resume, the exact same pairing).
    enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    -- Prefixes relayed content with "[Discord] username:" (or the Fluxer
    -- equivalent), so it's clear who actually said something and from
    -- where. Defaults on: the safer, more transparent default, most
    -- relevant for two-way (a live conversation bridge) but not withheld
    -- from one-way mappings either, someone forwarding an announcement
    -- channel may still want to know who originally posted it.
    show_attribution     BOOLEAN NOT NULL DEFAULT TRUE,
    -- The Fluxer user id of whoever configured this mapping. Not an
    -- access-control mechanism, this is a SHARED relay bot: nothing in
    -- this schema verifies that whoever adds a fluxer_to_discord (or
    -- both) mapping actually has any real claim to discord_channel_id,
    -- only that they manage the Fluxer guild the mapping is filed
    -- under. If this bot is ever hosted for multiple UNRELATED Fluxer
    -- communities, any of their managers can direct the shared bot to
    -- post into any Discord channel it happens to have access to
    -- (Discord channel ids aren't secret in any strong sense), a real
    -- trust boundary worth understanding before enabling that for
    -- people you don't already trust with each other. This column is
    -- purely for after-the-fact accountability if that's ever misused,
    -- it doesn't prevent it.
    created_by           TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (discord_channel_id, fluxer_channel_id)
);
CREATE INDEX IF NOT EXISTS idx_discord_relay_discord_channel ON discord_relay_mappings(discord_channel_id);
CREATE INDEX IF NOT EXISTS idx_discord_relay_fluxer_guild ON discord_relay_mappings(fluxer_guild_id);
CREATE INDEX IF NOT EXISTS idx_discord_relay_fluxer_channel ON discord_relay_mappings(fluxer_channel_id);

-- Singleton row, same pattern as bot_profile/bot_status: lets the bot
-- owner set the Discord relay's bot token from the dashboard instead of
-- only via DISCORD_BOT_TOKEN in .env. Not encrypted at rest, same risk
-- posture this project already takes with everything else in Postgres
-- (mod actions, warnings, bot_profile's image bytes, none of it is
-- encrypted either, Postgres access is already a trust boundary here),
-- but never returned by any GET endpoint, only settable, so it can't
-- leak back out through the dashboard's own API. Falls back to the env
-- var if this row doesn't exist or its token is null.
CREATE TABLE IF NOT EXISTS discord_relay_config (
    id          TEXT PRIMARY KEY DEFAULT 'relay',
    bot_token   TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Singleton row, same pattern as bot_status: the relay client updates
-- this on connect/disconnect/error so the dashboard can show whether
-- it's actually working right now, not just whether it's configured.
CREATE TABLE IF NOT EXISTS discord_relay_status (
    id                   TEXT PRIMARY KEY DEFAULT 'relay',
    connected            BOOLEAN NOT NULL DEFAULT FALSE,
    discord_username     TEXT,
    -- The bot's own Discord user id, same value as its OAuth2 client id
    -- for practically every real Discord bot, used to build the invite
    -- link shown to other guild managers (see discord_relay_invite_url
    -- in dashboard/app.py). Populated once available in on_ready.
    discord_bot_id       TEXT,
    last_connected_at    TIMESTAMPTZ,
    last_error           TEXT,
    last_error_at        TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Links a relayed message back to its source, so an edit or delete on
-- one platform can find and mirror the change on the other. One source
-- message can have several rows here (fanning out to multiple targets,
-- same as mappings themselves can). Pruned periodically by the
-- scheduler (see bot/scheduler.py) rather than kept forever, a message
-- from months ago being edited is vanishingly unlikely to matter and
-- there's no value in an unbounded, ever-growing table for it.
CREATE TABLE IF NOT EXISTS discord_relay_message_links (
    id                   BIGSERIAL PRIMARY KEY,
    mapping_id           BIGINT REFERENCES discord_relay_mappings(id) ON DELETE SET NULL,
    source_platform      TEXT NOT NULL CHECK (source_platform IN ('discord', 'fluxer')),
    source_message_id    TEXT NOT NULL,
    target_platform      TEXT NOT NULL CHECK (target_platform IN ('discord', 'fluxer')),
    target_message_id    TEXT NOT NULL,
    target_channel_id    TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_relay_links_source ON discord_relay_message_links(source_platform, source_message_id);
