# FluxBot

A Python moderation bot for [Fluxer](https://fluxer.app) with a FastAPI web
dashboard. Works against the official instance or a self-hosted one — just
change `FLUXER_API_BASE`.

- **Bot**: kick / ban / unban / timeout / purge, a warning system with
  auto-escalation (warn → auto-timeout → auto-kick), mod-action logging to a
  channel, autoroles, reaction roles, and a few fun commands (dice, coinflip,
  wheel spin).
- **Dashboard**: FastAPI app, "Login with Fluxer" via OAuth2, per-server
  settings, warning history, and a mod-action audit log.
- **Storage**: Postgres, shared by both processes over a real connection pool
  (not a shared SQLite file) — `asyncpg`.

Both the bot and the dashboard talk to the Fluxer REST API directly (raw
`aiohttp`/gateway handshake) rather than depending on a third-party wrapper's
undocumented internals, so self-hosting support is just config.

## Project layout

```
common/            config + the shared Postgres data layer (used by both processes)
bot/
  rest.py          REST client (self-host aware — base URL from config)
  client.py        gateway (WebSocket) client — handshake, heartbeats, reconnect
  commands.py       tiny prefix-command framework + dispatcher
  permissions.py    role/permission bit checks
  modules/
    moderation.py   kick/ban/unban/timeout/purge/warn/warnings/modlog
    roles.py        autorole + reaction roles
    fun.py          roll/coinflip/wheel
    utility.py      help/ping
    logging_mod.py  writes mod_actions rows + posts to the log channel
  main.py            entrypoint
dashboard/
  app.py            FastAPI app + routes
  oauth.py          OAuth2 "Login with Fluxer" flow
  templates/, static/
schema.sql          Postgres schema (idempotent — CREATE TABLE IF NOT EXISTS)
run_bot.py / run_dashboard.py
```

## Setup

1. **Postgres.** Create a database and user:
   ```bash
   createdb fluxerbot
   psql fluxerbot -c "CREATE USER fluxerbot WITH PASSWORD 'fluxerbot';"
   psql fluxerbot -c "GRANT ALL PRIVILEGES ON DATABASE fluxerbot TO fluxerbot;"
   psql fluxerbot -c "GRANT ALL ON SCHEMA public TO fluxerbot;"
   ```
   (Any Postgres works — a managed service, Docker, etc. Just point
   `DATABASE_URL` at it.)

2. **Env.**
   ```bash
   cp .env.example .env
   ```
   Fill in:
   - `FLUXER_BOT_TOKEN` — your bot's token.
   - `FLUXER_API_BASE` / `FLUXER_WEB_BASE` / `FLUXER_GATEWAY_URL` — leave as
     the official instance, or point at your self-hosted domain (see below).
   - `DATABASE_URL` — your Postgres connection string.
   - `FLUXER_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` — for the
     dashboard's "Login with Fluxer" button (see OAuth section below).
   - `DASHBOARD_SESSION_SECRET` — any long random string.

3. **Install deps.**
   ```bash
   pip install -r requirements.txt
   ```

4. **Apply the schema** (optional — both processes also do this
   automatically on startup):
   ```bash
   python -m common.db
   ```

5. **Run.**
   ```bash
   python run_bot.py          # in one terminal
   python run_dashboard.py    # in another
   ```
   Dashboard defaults to `http://localhost:8000`.

## Self-hosting a Fluxer instance

Point these three at your instance and everything else (REST calls, the
gateway connection, OAuth login) follows automatically:

```
FLUXER_API_BASE=https://your-domain.com/api/v1
FLUXER_WEB_BASE=https://your-domain.com
FLUXER_GATEWAY_URL=wss://your-domain.com/gateway   # only if GET /gateway/bot isn't available on your instance
```

## Setting up "Login with Fluxer"

The dashboard needs an OAuth2 application registered against your Fluxer
instance (`POST /oauth2/applications`, authenticated as a user account —
consult your instance's admin/API docs for the exact flow, since this isn't
fully standardized yet). Set the redirect URI there to match
`FLUXER_OAUTH_REDIRECT_URI` exactly, then copy the client ID/secret into
`.env`.

## ⚠️ On API completeness

Fluxer's public API reference is still being filled in (as of mid-2026), and
some routes here — particularly the exact moderation endpoints
(`ban`/`timeout`/`purge`) and the OAuth2 guild-list response shape — are
implemented following the Discord-like conventions Fluxer is modeled on,
since that's the best information available. Everything funnels through a
small number of methods:

- REST calls: `bot/rest.py`
- Permission bit values: `bot/permissions.py`
- OAuth2 guild permission check: `dashboard/oauth.py::can_manage`

If your instance's OpenAPI spec (usually at `<api_base>/openapi.json`, or
your instance's own `/api-reference` page) disagrees with a path or bit
value here, that's the source of truth — the fix is a one-line change in one
of those three files, not a rewrite.

## Commands

Run `!help` in Fluxer once the bot is running for the live list. Summary:

| Command | Permission | Description |
|---|---|---|
| `!kick @user [reason]` | Kick Members | Kick a member |
| `!ban @user [reason]` | Ban Members | Ban a member |
| `!unban <id> [reason]` | Ban Members | Unban by ID |
| `!timeout @user <dur> [reason]` | Moderate Members | e.g. `10m`, `2h`, `1d` |
| `!untimeout @user [reason]` | Moderate Members | Remove a timeout |
| `!purge <count>` | Manage Messages | Bulk delete recent messages |
| `!warn @user [reason]` | Kick Members | Warn (auto-escalates per guild settings) |
| `!warnings @user` | — | List a member's warnings |
| `!clearwarnings @user` | Kick Members | Clear active warnings |
| `!modlog #channel` | Manage Guild | Set the mod-log channel |
| `!autorole add/remove/list @role` | Manage Guild | Roles auto-given on join |
| `!reactionrole add/remove/list ...` | Manage Guild | Reaction → role mapping |
| `!roll [NdM]`, `!coinflip`, `!wheel a, b, c` | — | Fun stuff |

Warning escalation thresholds (`warn_timeout_at`, `warn_kick_at`,
`warn_timeout_minutes`) are per-guild and editable from the dashboard.
