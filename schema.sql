-- Fluxer moderation bot — Postgres schema
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
