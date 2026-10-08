-- Fluxer moderation bot, Postgres schema
-- Apply with: psql "$DATABASE_URL" -f schema.sql
-- (or just run `python -m common.db` once, which executes this same DDL)
--
-- IMPORTANT when adding a column to a table that already exists in this
-- file (as opposed to a brand new table): editing the CREATE TABLE block
-- alone is NOT enough. CREATE TABLE IF NOT EXISTS is a no-op against a
-- table that already exists in the OLD, pre-your-change shape, so anyone
-- who set this up before your change and just re-runs this file (which
-- is the entire point of it being safe to always run on update) will
-- never actually get the new column, and the app will crash the moment
-- it tries to read or write it. Pair every such change with a matching
-- `ALTER TABLE x ADD COLUMN IF NOT EXISTS ...` statement placed AFTER
-- that table's own CREATE TABLE (search for "Migration" further down for
-- the established pattern and placement). This has already caused a
-- real production outage once, from six columns added this way without
-- a matching migration, please don't let it happen again.

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
    report_channel_id         TEXT,  -- see reports table below; feature is off until this is set
    report_tracker_channel_id TEXT,
    voice_xp_cap_enabled  BOOLEAN NOT NULL DEFAULT TRUE,  -- see member_voice_xp_daily below
    voice_xp_cap_amount   INTEGER NOT NULL DEFAULT 750,
    fluxer_patch_notes_channel_id TEXT,  -- see fluxer_patch_notes_config/log below; off until set
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
    -- The embed's own title/description/color, at the time it was last
    -- sent or edited. Duplicated onto every row for the same message_id
    -- (same tradeoff as reports' tracker_channel_id/tracker_message_id, a
    -- handful of rows per message makes a separate messages table more
    -- machinery than the redundancy it'd save) rather than lost entirely:
    -- without these, editing or resending a reaction-role message would
    -- have nothing to reconstruct the embed from except the bare
    -- emoji/role/label mappings, losing whatever title/description text
    -- staff originally wrote.
    title       TEXT NOT NULL DEFAULT 'Pick your roles',
    description TEXT NOT NULL DEFAULT '',
    color       INTEGER NOT NULL DEFAULT 5793266, -- 0x5865F2
    -- Scoped by guild_id, not just (message_id, emoji): a message id is
    -- unique per platform, not per guild the bot manages, so an
    -- unscoped constraint let a manager of ANY guild overwrite ANOTHER
    -- guild's mapping just by guessing/knowing its message id + emoji
    -- (`!reactionrole add <someone else's message id> <emoji> @role`),
    -- silently hijacking it. See the migration below for upgrading a
    -- database created before this was caught.
    UNIQUE(guild_id, message_id, emoji)
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

-- Presence of a row opts a member out of the level-up announcement (!levelnotify
-- off), same "exclusion list" shape as xp_excluded_channels below. A member can
-- opt out before ever earning XP, so this can't just be a column on `levels`,
-- that row may not exist yet.
CREATE TABLE IF NOT EXISTS level_notify_optouts (
    guild_id    TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
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

-- Per-member, per-day voice XP already granted, so voice_tracker.py can
-- clamp a member to VOICE_XP_DAILY_CAP XP/day (when guilds.voice_xp_cap_enabled
-- is on) without an unattended 24/7 voice session being able to out-earn a
-- normal couple-hours-a-day habit by nearly an order of magnitude. Keyed by
-- `day` rather than reset by a scheduled job: a new day just gets a fresh
-- row, nothing to clear. Rows are small and left in place as history rather
-- than pruned, same as guild_daily_stats above.
CREATE TABLE IF NOT EXISTS member_voice_xp_daily (
    guild_id        TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL,
    day             DATE NOT NULL,
    xp_earned       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, day)
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

-- Migration for databases created before a reaction-role message's own
-- title/description/color were stored (needed to edit or resend one).
ALTER TABLE reaction_roles ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT 'Pick your roles';
ALTER TABLE reaction_roles ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';
ALTER TABLE reaction_roles ADD COLUMN IF NOT EXISTS color INTEGER NOT NULL DEFAULT 5793266; -- 0x5865F2

-- Migration for databases created before goodbye messages existed.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS goodbye_channel_id TEXT;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS goodbye_message TEXT NOT NULL DEFAULT
    '{username} left {server}. 👋';

-- Migration for databases created before leveling existed.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS leveling_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS level_up_channel_id TEXT;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS level_up_message TEXT NOT NULL DEFAULT
    'GG {user}, you reached level {level}! 🎉';

-- Migration for databases created before the bug/issue report system
-- existed: the two channels it's built around (see the reports table
-- further down), both optional, the feature stays off until a report
-- channel is configured.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS report_channel_id TEXT;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS report_tracker_channel_id TEXT;

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

-- Presence of a row disables that command (by its canonical name, not an
-- alias) in that guild, same "exclusion list" shape as xp_excluded_channels.
-- A couple of commands (see NEVER_DISABLED_COMMANDS in bot/commands.py)
-- are never allowed to end up disabled, so a server can't lock itself out
-- of managing or discovering commands from chat.
CREATE TABLE IF NOT EXISTS disabled_commands (
    guild_id      TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    command_name  TEXT NOT NULL,
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
    -- When the Discord side last went down. Set on_disconnect, read on
    -- the next on_ready to bound how far back the Discord-to-Fluxer
    -- backfill needs to look (exactly how long it was actually down,
    -- not some fixed window every single reconnect regardless of how
    -- brief), capped at 24h either way, matching how long a queued
    -- Fluxer-to-Discord message is kept before being given up on.
    -- Cleared once a reconnect's backfill pass has run, so a second
    -- quick reconnect right after doesn't redundantly re-scan the same
    -- window.
    last_disconnected_at TIMESTAMPTZ,
    last_error           TEXT,
    last_error_at        TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Singleton row, same pattern as discord_relay_config: a bot-wide,
-- owner-only setting (what time of day the Fluxer patch-notes digest
-- goes out), not scoped to any one guild. Central time, not UTC, since
-- that's the timezone the digest's "day" is always computed in (see
-- bot/fluxer_patch_notes.py) regardless of where the bot itself runs.
CREATE TABLE IF NOT EXISTS fluxer_patch_notes_config (
    id             TEXT PRIMARY KEY DEFAULT 'config',
    trigger_hour   INTEGER NOT NULL DEFAULT 0,  -- 0-23, America/Chicago
    trigger_minute INTEGER NOT NULL DEFAULT 5,  -- 0-59
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per calendar day (America/Chicago) the digest has actually
-- been generated and sent for. Doubles as the scheduler's dedupe guard
-- (a bot restart mid-day must not re-send) and as the cache key so the
-- content is fetched from GitHub once per day and fanned out to every
-- guild with a channel configured, not fetched once per guild.
CREATE TABLE IF NOT EXISTS fluxer_patch_notes_log (
    sent_date     DATE PRIMARY KEY,
    commit_count  INTEGER NOT NULL,
    sent_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per Fluxer message that couldn't be delivered to Discord
-- because the relay's Discord connection was down at the time, not
-- some other, unrelated failure (a bad channel id, missing permission,
-- etc, those aren't retried, retrying them would just fail the same
-- way again). Already fully prepared at the time it's queued, mention
-- translation, the reply prefix, and so on have already been applied,
-- so draining this later is just "attempt delivery with what's already
-- here", not "rebuild the message from scratch". Attachments are
-- stored as their original Fluxer CDN url/filename rather than the
-- raw bytes, re-downloaded at delivery time, to avoid holding
-- arbitrarily large blobs in this table for a queue that's meant to be
-- short-lived. Drained in full on every relay reconnect (oldest first,
-- to preserve conversation order), and anything left after 24 hours
-- (network partition lasting that long, or the target channel/webhook
-- genuinely broken) is dropped rather than retried forever, see
-- bot/scheduler.py for the periodic cleanup backstop in case a drain
-- attempt never gets the chance to run at all.
CREATE TABLE IF NOT EXISTS discord_relay_outbound_queue (
    id                BIGSERIAL PRIMARY KEY,
    mapping_id        BIGINT REFERENCES discord_relay_mappings(id) ON DELETE CASCADE,
    source_message_id TEXT NOT NULL,
    target_channel_id TEXT NOT NULL,
    content           TEXT,
    embeds_json       TEXT,
    attachments_json  TEXT,
    username          TEXT,
    avatar_url        TEXT,
    fallback_content  TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_relay_outbound_queue_created_at ON discord_relay_outbound_queue(created_at);

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
    -- Webhook-sent messages have to be edited/deleted through the
    -- webhook's own endpoint (PATCH/DELETE /webhooks/{id}/{token}/
    -- messages/{message_id}), not the regular message endpoint, the
    -- bot doesn't "own" a message a webhook sent the way it owns one
    -- it sent directly.
    sent_via_webhook     BOOLEAN NOT NULL DEFAULT FALSE,
    -- The EXACT webhook that sent this specific message, captured at
    -- send time, not "whatever webhook is currently on file for this
    -- channel". If that webhook is ever deleted and recreated (its id/
    -- token rotate), a later edit or delete needs the ORIGINAL
    -- credentials, a message only exists under the webhook that
    -- actually sent it, not under a same-channel replacement. NULL for
    -- a link created before this column existed or when
    -- sent_via_webhook is false; the edit/delete sync falls back to
    -- the channel's current webhook for those.
    webhook_id           TEXT,
    webhook_token        TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_relay_links_source ON discord_relay_message_links(source_platform, source_message_id);

-- One row per (platform, channel), a webhook the relay created so it
-- can post messages showing the ORIGINAL author's real username and
-- avatar (Discord and Fluxer both support this on webhook-sent
-- messages, not on regular bot-token-sent ones, matching how every
-- real Discord bridge does this). Lazily created the first time a
-- channel needs one, reused after that. Deleted and recreated here if
-- execution ever fails with a "this webhook doesn't exist anymore"
-- error (someone removed it from the channel's integrations directly).
CREATE TABLE IF NOT EXISTS discord_relay_webhooks (
    id              BIGSERIAL PRIMARY KEY,
    platform        TEXT NOT NULL CHECK (platform IN ('discord', 'fluxer')),
    channel_id      TEXT NOT NULL,
    webhook_id      TEXT NOT NULL,
    webhook_token   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (platform, channel_id)
);

-- One row per (mapping, source message) currently being relayed,
-- claimed via INSERT ... ON CONFLICT DO NOTHING (see
-- common/db.py's claim_relay_send) before the actual send is
-- attempted, deleted once the send either succeeds (superseded by the
-- discord_relay_message_links row that records it) or fails outright
-- (releases the claim so a retry isn't permanently blocked). Exists
-- because the reconnect backfill (a REST history scan) and the live
-- gateway's own message handler can both end up processing the SAME
-- Discord message through the SAME mapping around the moment of
-- reconnect, and a plain "check if already relayed, then send" is a
-- check-then-act race: both could see "not yet relayed" before either
-- has actually sent anything. The primary key makes the claim itself
-- atomic, closing that gap; a stale claim (its owning process crashed
-- between claiming and finishing) is swept up by the scheduler's
-- prune_stale_relay_send_claims after a few minutes, see
-- bot/scheduler.py.
CREATE TABLE IF NOT EXISTS discord_relay_send_claims (
    mapping_id          BIGINT NOT NULL,
    source_platform     TEXT NOT NULL CHECK (source_platform IN ('discord', 'fluxer')),
    source_message_id   TEXT NOT NULL,
    claimed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (mapping_id, source_platform, source_message_id)
);
CREATE INDEX IF NOT EXISTS idx_relay_send_claims_claimed_at ON discord_relay_send_claims(claimed_at);

-- Self-service Discord <-> Fluxer account linking (bot/modules/
-- account_links.py, bot/discord_relay.py's live-mention resolution).
-- One Discord account maps to at most one Fluxer account and vice
-- versa (both sides UNIQUE), a 1:1 identity link, not a many-to-one
-- "who do we ping" ambiguity. Bot-wide, not per-guild: the same
-- person is the same person across every server this bot bridges.
-- Verified via a short-lived code exchanged between the two
-- platforms (see account_link_codes below), never just typed in by
-- either side unverified, that would let anyone redirect someone
-- else's pings to themselves.
CREATE TABLE IF NOT EXISTS account_links (
    discord_user_id   TEXT PRIMARY KEY,
    fluxer_user_id    TEXT NOT NULL UNIQUE,
    linked_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per in-progress link attempt, started from the Fluxer side
-- (!link) and redeemed from the Discord side (DMing the relay bot
-- !link <code>). code is the whole point of this table: short,
-- typeable, single-use proof that whoever redeems it on Discord is
-- the same person who ran !link on Fluxer (or at least someone they
-- shared the code with, the same trust model as e.g. a 2FA backup
-- code or an email verification link). Expired/consumed codes are
-- swept by the scheduler, same backstop pattern as everything else
-- time-bounded in this schema.
CREATE TABLE IF NOT EXISTS account_link_codes (
    code              TEXT PRIMARY KEY,
    fluxer_user_id    TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at        TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_account_link_codes_expires_at ON account_link_codes(expires_at);

-- Member-submitted bug/issue reports. Captured automatically from a
-- dedicated channel (guilds.report_channel_id), no command needed to
-- post one, see bot/modules/reports.py. The original message is
-- always removed from that channel right after capture, regardless
-- of visibility, a report only actually lives on in the second
-- "tracker" channel (guilds.report_tracker_channel_id) as a
-- status-tagged embed the bot keeps edited in place, so members and
-- staff can see what's already been reported before filing another
-- one instead of everyone re-reporting the same thing blind.
CREATE TABLE IF NOT EXISTS reports (
    id                     BIGSERIAL PRIMARY KEY,
    guild_id               TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    reporter_id            TEXT NOT NULL,
    content                TEXT NOT NULL,
    -- 'public' (default): attributed to the reporter in the tracker.
    -- 'private': the reporter included a "Private: yes" line in the
    -- report itself (see bot/modules/reports.py's _extract_privacy_field),
    -- so the tracker entry omits their identity. Doesn't affect the
    -- submit_channel_id/submit_message_id below: the original message
    -- is always removed from the report channel regardless of
    -- visibility, see this table's own comment at the top.
    visibility             TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'private')),
    status                 TEXT NOT NULL DEFAULT 'open'
                               CHECK (status IN ('open', 'duplicate', 'resolved', 'wontfix')),
    -- Set once staff confirms (!report status <id> duplicate <of_id>,
    -- or the dashboard) this is the same issue as another report.
    duplicate_of           BIGINT REFERENCES reports(id),
    -- Set automatically at submission time by a basic text-similarity
    -- check against currently-open reports (bot/report_actions.py's
    -- find_possible_duplicate). A *guess* surfaced to staff in the
    -- tracker, not a confirmed link: never closes the report or sets
    -- duplicate_of on its own.
    possible_duplicate_of  BIGINT REFERENCES reports(id),
    -- Where the report was originally posted. Historical record only:
    -- the message itself is always deleted from this channel right
    -- after being captured (best-effort, needs Manage Messages),
    -- public or private alike, so the report channel never ends up
    -- holding a mix of raw submissions and bot clutter, only the
    -- tracker channel below is where a report is actually visible
    -- afterward. These ids are still needed at capture time to issue
    -- that delete call, and kept on the row afterward only as a
    -- record of where it came from.
    submit_channel_id      TEXT NOT NULL,
    submit_message_id      TEXT NOT NULL,
    -- Both recorded at post time, not re-derived from the guild's
    -- CURRENT report_tracker_channel_id when a later edit is needed:
    -- if that setting is ever reconfigured, an older report's tracker
    -- entry still lives in the channel it was actually posted to.
    -- Same reasoning as discord_relay_message_links remembering the
    -- exact webhook that sent it rather than "whichever one is
    -- currently on file for that channel", see that table's comment.
    tracker_channel_id     TEXT,
    tracker_message_id     TEXT,
    resolution_note        TEXT,
    resolved_by            TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(guild_id, submit_message_id)
);
CREATE INDEX IF NOT EXISTS idx_reports_guild_status  ON reports(guild_id, status);
CREATE INDEX IF NOT EXISTS idx_reports_guild_created ON reports(guild_id, created_at DESC);

-- The two-way conversation on a report: staff replying to the reporter,
-- and the reporter replying back, see bot/report_actions.py's
-- add_staff_reply and bot/modules/reports.py's DM-reply handler. Always
-- delivered/received by DM (the reporter never has a dashboard login,
-- and there's no public message left for them to reply under once the
-- original is removed, see the reports table's own comment above), so
-- every row that corresponds to an actual DM carries that DM's message
-- id in dm_message_id. That's not just a record: it's how the next
-- inbound DM from the reporter gets matched back to the right report at
-- all, by reading the message_reference on their reply and looking up
-- which report that referenced message id belongs to (reports.id is
-- otherwise invisible to them, there's no "type the report number"
-- step). 'system' rows (the initial submission confirmation, status-
-- change notifications) are anchors for that matching only, not part of
-- the human conversation a report's dashboard page or !report info
-- shows -- without them, replying to anything other than the most
-- recent staff message would fail to match.
CREATE TABLE IF NOT EXISTS report_replies (
    id            BIGSERIAL PRIMARY KEY,
    report_id     BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    author_type   TEXT NOT NULL CHECK (author_type IN ('staff', 'reporter', 'system')),
    -- The staff member's or reporter's own id for 'staff'/'reporter' rows.
    -- Unused (NULL) for 'system' rows, there's no human author.
    author_id     TEXT,
    content       TEXT NOT NULL,
    -- Unique per row when set (never reused across reports/replies), so
    -- a lookup by this id alone is enough to find the report it belongs
    -- to with no further scoping needed, see get_report_by_dm_message.
    dm_message_id TEXT UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_report_replies_report ON report_replies(report_id, created_at);

-- Migrations for columns added to already-existing tables after this
-- schema's earlier migration block (further up this file) was last
-- updated. That block runs early, before several of the tables below
-- even exist yet in a fresh run, so these have to live down here
-- instead, after every CREATE TABLE they depend on has already run.
-- Each one is what let a table with the OLD, pre-this-column shape
-- (any database that was already running before the corresponding
-- feature shipped) come back in sync, CREATE TABLE IF NOT EXISTS on
-- its own only helps a database that doesn't have the table AT ALL
-- yet, it's a no-op against a table that already exists in an older
-- shape, which is exactly why these are needed as their own explicit
-- step.

-- Migration for databases created before privileged-role-change
-- logging existed (activity_log_settings originally shipped without
-- this toggle).
ALTER TABLE activity_log_settings ADD COLUMN IF NOT EXISTS log_privileged_role_changes BOOLEAN NOT NULL DEFAULT FALSE;

-- Migration for databases created before the Discord relay's
-- enable/disable toggle, attribution toggle, and creator audit trail
-- existed (discord_relay_mappings originally shipped without these).
ALTER TABLE discord_relay_mappings ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE discord_relay_mappings ADD COLUMN IF NOT EXISTS show_attribution BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE discord_relay_mappings ADD COLUMN IF NOT EXISTS created_by TEXT;

-- Migration for databases created before the relay's Discord bot id
-- (used to build the invite link) was tracked on its status row.
ALTER TABLE discord_relay_status ADD COLUMN IF NOT EXISTS discord_bot_id TEXT;

-- Migration for databases created before relayed messages could be
-- sent via a webhook (for real avatar/username display), needed so
-- edit/delete sync knows which endpoint a given relayed message has
-- to go through.
ALTER TABLE discord_relay_message_links ADD COLUMN IF NOT EXISTS sent_via_webhook BOOLEAN NOT NULL DEFAULT FALSE;

-- Migration for databases created before each link stored the EXACT
-- webhook that sent it (see the column comments above for why: a
-- lookup against "whatever webhook is currently on file for this
-- channel" breaks the moment that webhook is ever recreated).
ALTER TABLE discord_relay_message_links ADD COLUMN IF NOT EXISTS webhook_id TEXT;
ALTER TABLE discord_relay_message_links ADD COLUMN IF NOT EXISTS webhook_token TEXT;

-- Migration for databases created before the relay tracked when it
-- last went down, needed to bound the Discord-to-Fluxer backfill
-- window on reconnect.
ALTER TABLE discord_relay_status ADD COLUMN IF NOT EXISTS last_disconnected_at TIMESTAMPTZ;

-- Migration for databases created before reaction_roles was scoped
-- per-guild (see that table's own comment above): widens the old
-- UNIQUE(message_id, emoji) to UNIQUE(guild_id, message_id, emoji).
-- Always safe to apply, the old constraint already guaranteed no two
-- rows share a (message_id, emoji) pair, so adding guild_id to the
-- tuple can never conflict with existing data. Postgres has no
-- `ADD CONSTRAINT ... IF NOT EXISTS`, so this checks pg_constraint
-- itself to stay idempotent on every startup like everything else here.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'reaction_roles_guild_id_message_id_emoji_key'
    ) THEN
        ALTER TABLE reaction_roles DROP CONSTRAINT IF EXISTS reaction_roles_message_id_emoji_key;
        ALTER TABLE reaction_roles ADD CONSTRAINT reaction_roles_guild_id_message_id_emoji_key
            UNIQUE (guild_id, message_id, emoji);
    END IF;
END $$;

-- Migration for databases created before the "react within 10 minutes to
-- go private" report flow was replaced by the "Private: yes" line (see
-- the reports table's own comment above). That redesign dropped
-- privacy_deadline from the CREATE TABLE block above, but a column drop
-- (unlike an added column) needs its own explicit step same as an add
-- does: CREATE TABLE IF NOT EXISTS never touches a table that already
-- exists in the old shape, so any database bootstrapped before this
-- change still has the old NOT NULL privacy_deadline column sitting
-- there with nothing left in the app that ever sets it, and every
-- report submission fails with a not-null violation. Safe to always
-- run: a no-op on any database that never had the column.
ALTER TABLE reports DROP COLUMN IF EXISTS privacy_deadline;

-- Migration for databases created before the voice XP daily cap existed.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS voice_xp_cap_enabled BOOLEAN NOT NULL DEFAULT TRUE;

-- Migration for databases created before the cap amount was configurable
-- (it used to be a hardcoded 750 in bot/voice_tracker.py).
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS voice_xp_cap_amount INTEGER NOT NULL DEFAULT 750;

-- Migration for databases created before the Fluxer patch-notes digest existed.
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS fluxer_patch_notes_channel_id TEXT;
