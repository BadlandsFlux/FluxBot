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

CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_mod_actions_guild   ON mod_actions(guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reaction_roles_msg  ON reaction_roles(message_id);
CREATE INDEX IF NOT EXISTS idx_tags_guild          ON tags(guild_id);

-- Migration for databases created before command_prefix existed.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS command_prefix TEXT NOT NULL DEFAULT '!';

-- Migration for databases created before welcome messages existed.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS welcome_channel_id TEXT;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS welcome_message TEXT NOT NULL DEFAULT
    'Welcome {user} to {server}! 👋';

-- Migration for databases created before reaction role labels existed.
ALTER TABLE reaction_roles ADD COLUMN IF NOT EXISTS label TEXT NOT NULL DEFAULT '';
