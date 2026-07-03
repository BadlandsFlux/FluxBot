# FluxBot

A Python moderation bot for [Fluxer](https://fluxer.app) with a FastAPI web dashboard. Works against the official instance or a self-hosted one, just change `FLUXER_API_BASE`.

- **Bot**: kick / ban / unban / timeout / purge, a warning system with auto-escalation (warn to auto-timeout to auto-kick), mod-action logging to a channel, autoroles, reaction roles, welcome messages, custom tags (`!tagname` shortcuts), per-server command prefixes, info commands (`!avatar`, `!serverinfo`, `!userinfo`, owner-only `!info`), `!poll`, `!ping` with real gateway/API/DB latency and uptime stats, and fun commands (dice, coinflip, wheel spin). Moderation logic (REST calls, logging, warn escalation) lives in one shared module (`bot/moderation_actions.py`) used by both chat commands and the dashboard's Members tab, so behavior can't drift between the two.
- **Dashboard**: a React SPA (Vite) served by FastAPI as static files, talking to a JSON API (`/api/*`), with real client-side routing, no full-page reloads, live search on the commands page, and a quiet 8-second poll on each server's page so kicks/bans/warnings from chat show up without a manual refresh. Tabbed per-server UI (Overview, Settings, **Members**, Warnings, Mod Log, Autoroles, Reaction Roles, **Tags**) with searchable role/channel pickers everywhere instead of raw ID text boxes, real server icons in the picker, a **Members tab to search and kick/ban/timeout/warn directly from the browser**, welcome-message configuration, and a **reaction-role builder** where you pick a channel, add emoji-to-role rows, and it posts the embed, reacts to it, and starts listening for you. A public `/commands` page lists every command, always in sync with the bot since it's generated from the same code. Access is via "Login with Fluxer" OAuth2, see "Dashboard access" below.
- **Storage**: Postgres, shared by both processes over a real connection pool (not a shared SQLite file), via `asyncpg`.

Both the bot and the dashboard talk to the Fluxer REST API directly (raw `aiohttp`/gateway handshake) rather than depending on a third-party wrapper's undocumented internals, so self-hosting support is just config.

## Project layout

```
common/                config + the shared Postgres data layer (used by both processes)
  config.py            env-driven settings
  db.py                asyncpg pool + all queries (guilds, warnings, mod_actions,
                        reaction_roles, autoroles, tags)
  discovery.py         instance discovery + CDN URL helpers (guild icons, avatars)
bot/
  rest.py              REST client (self-host aware, base URL from config)
  client.py            gateway (WebSocket) client, handshake, heartbeats, reconnect
  commands.py          tiny prefix-command framework + dispatcher (also falls back
                        to custom tags when a message doesn't match a built-in command)
  permissions.py       role/permission bit checks
  timeutil.py          snowflake to date, duration formatting
  moderation_actions.py  shared kick/ban/timeout/warn logic, used by both chat
                        commands and the dashboard's Members tab
  modules/
    moderation.py       kick/ban/unban/timeout/purge/warn/warnings/modlog (thin
                        wrappers around moderation_actions.py)
    roles.py            autorole + reaction roles + welcome messages on join
    fun.py              roll/coinflip/wheel/poll
    info.py             avatar/serverinfo/userinfo/info (owner-only)
    tags.py             !tag add/remove/list
    utility.py          help/ping
    logging_mod.py       writes mod_actions rows + posts to the log channel
  main.py                entrypoint
dashboard/
  app.py                FastAPI app, JSON API (/api/*) + serves the built SPA
  oauth.py              OAuth2 "Login with Fluxer" flow
dashboard-frontend/      React SPA (Vite)
  src/
    api.js               fetch wrapper for the backend's /api/* routes
    App.jsx               routing + auth-gate
    pages/                Login, GuildPicker, GuildDetail, Commands
    components/           TopBar, Flash (toasts), Spinner, Combobox (role/channel
                          picker), ReactionRoleBuilder, MembersTab, TagsTab
    hooks/                useRolesChannels (fetch once per guild), usePolling
                          (visibility-aware interval)
  dist/                  production build, FastAPI serves this (git-ignored,
                          build it yourself)
schema.sql              Postgres schema (idempotent, CREATE TABLE IF NOT EXISTS,
                        plus ALTER TABLE ADD COLUMN IF NOT EXISTS migrations)
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
   (Any Postgres works, a managed service, Docker, etc. Just point `DATABASE_URL` at it.)

2. **Env.**
   ```bash
   cp .env.example .env
   ```
   Fill in:
   - `FLUXER_BOT_TOKEN`, your bot's token.
   - `BOT_OWNER_ID`, your own Fluxer user ID, gates the owner-only `!info` command.
   - `FLUXER_API_BASE` / `FLUXER_WEB_BASE` / `FLUXER_GATEWAY_URL`, leave as the official instance, or point at your self-hosted domain (see below).
   - `DATABASE_URL`, your Postgres connection string.
   - `FLUXER_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI`, for the dashboard's "Login with Fluxer" button (see OAuth section below).
   - `DASHBOARD_SESSION_SECRET`, any long random string.

3. **Install deps.**
   ```bash
   pip install -r requirements.txt
   ```

4. **Apply the schema** (optional, both processes also do this automatically on startup):
   ```bash
   python -m common.db
   ```

5. **Build the frontend** (one time, it's a static React build, not a server, so this doesn't need repeating unless you change frontend code):
   ```bash
   cd dashboard-frontend
   npm install
   npm run build      # outputs dashboard-frontend/dist
   cd ..
   ```
   If `dist/` doesn't exist yet, the dashboard will say so at `/` instead of erroring, so it's obvious if you skip this step.

6. **Run.**
   ```bash
   python run_bot.py          # in one terminal
   python run_dashboard.py    # in another
   ```
   Dashboard defaults to `http://localhost:8000`, one process serves both the API and the built frontend, no Node server needed at runtime.

   **Iterating on the frontend?** Run `npm run dev` in `dashboard-frontend/` (Vite on `:5173`, proxying `/api`, `/login`, `/auth` to the FastAPI backend on `:8000`, see `vite.config.js`) alongside `python run_dashboard.py` in another terminal for hot reload, instead of rebuilding on every change. Run `npm run build` again when you're done to update what gets served in production.

## Self-hosting a Fluxer instance

Point these three at your instance and everything else (REST calls, the gateway connection, OAuth login) follows automatically:

```
FLUXER_API_BASE=https://your-domain.com/api/v1
FLUXER_WEB_BASE=https://your-domain.com
FLUXER_GATEWAY_URL=wss://your-domain.com/gateway   # only if GET /gateway/bot isn't available on your instance
```

## Setting up "Login with Fluxer"

The dashboard needs an OAuth2 application registered against your Fluxer instance (`POST /oauth2/applications`, authenticated as a user account, consult your instance's admin/API docs for the exact flow, since this isn't fully standardized yet). Set the redirect URI there to match `FLUXER_OAUTH_REDIRECT_URI` exactly, then copy the client ID/secret into `.env`.

## Dashboard access

Anyone can log in with "Login with Fluxer", that just proves who they are. What they can actually *do* is checked live, on every page load, against `GET /users/@me/guilds`:

- A server only shows up in their picker if the bot is installed there **and** they have "Manage Server" permission (or own it) in that server.
- There's no separate allowlist or cached role, demote someone in Fluxer and they lose dashboard access on their next request.
- The `/commands` reference page is public and needs no login, since it's just documentation.

If you want to restrict the dashboard further (e.g. only the bot owner, or an explicit allowlist of user IDs), that check lives in `_require_manage()` in `dashboard/app.py`, straightforward to tighten.

## ⚠️ On API completeness

Fluxer's public API reference is still being filled in (as of mid-2026), and some routes here, particularly the exact moderation endpoints (`ban`/`timeout`/`purge`), member-list pagination, and the OAuth2 guild-list response shape, are implemented following the Discord-like conventions Fluxer is modeled on, since that's the best information available. Everything funnels through a small number of methods:

- REST calls (including member list/kick/ban/timeout): `bot/rest.py`
- Permission bit values: `bot/permissions.py`
- OAuth2 guild permission check: `dashboard/oauth.py::can_manage`
- Media/CDN URL paths (guild icons, avatars) and snowflake to date epoch: `common/discovery.py`, `bot/timeutil.py`

If your instance's OpenAPI spec (usually at `<api_base>/openapi.json`, or your instance's own `/api-reference` page) disagrees with a path or bit value here, that's the source of truth, the fix is a one-line change in one of those files, not a rewrite.

One concrete limit worth knowing: the dashboard's Members tab fetches up to 500 members per request (Fluxer's member-list endpoint is paginated like Discord's). Large servers won't show every member in search, searching by exact user ID still works around that.

## Commands

Run `!help` in Fluxer once the bot is running for the live, per-server list (it shows your server's actual prefix and groups commands by category), or visit the dashboard's `/commands` page, same source, always in sync.

| Command | Permission | Description |
|---|---|---|
| `!kick @user [reason]` | Kick Members | Kick a member |
| `!ban @user [reason]` | Ban Members | Ban a member |
| `!unban <id> [reason]` | Ban Members | Unban by ID |
| `!timeout @user <dur> [reason]` | Moderate Members | e.g. `10m`, `2h`, `1d` |
| `!untimeout @user [reason]` | Moderate Members | Remove a timeout |
| `!purge <count>` | Manage Messages | Bulk delete recent messages |
| `!warn @user [reason]` | Kick Members | Warn (auto-escalates per guild settings) |
| `!warnings @user` | none | List a member's warnings |
| `!clearwarnings @user` | Kick Members | Clear active warnings |
| `!modlog #channel` | Manage Guild | Set the mod-log channel |
| `!autorole add/remove/list @role` | Manage Guild | Roles auto-given on join |
| `!reactionrole add/remove/list ...` | Manage Guild | Reaction to role mapping |
| `!avatar [@user]` | none | Show a member's avatar |
| `!serverinfo` | none | Member count, owner, boost tier, and more |
| `!userinfo [@user]` | none | Account age, join date, roles, staff rank |
| `!info` | Owner only | Bot-level stats (uptime, latency, server count) |
| `!poll "Q" "A" "B" ...` | none | Reaction poll, up to 10 options |
| `!tag add/remove/list <name> <content>` | Manage Guild (add/remove) | Custom `!name` shortcuts |
| `!ping` | none | Gateway/API/DB latency, uptime, server count |
| `!roll [NdM]`, `!coinflip`, `!wheel a, b, c` | none | Fun stuff |

`!info` is gated by `BOT_OWNER_ID` in `.env` (your own Fluxer user ID), not by any per-server permission, it's meant for you, not server admins.

Tags can also be managed from the dashboard's Tags tab. Once added, invoking `!<tagname>` posts its content, checked as a fallback whenever a message doesn't match a built-in command. Tag names can't collide with a real command name.

## What's editable from the dashboard vs. chat-only

Most day-to-day admin work can be done entirely from the dashboard, no need to touch Fluxer directly:

- **Settings tab**: mod-log channel, command prefix, mute role, welcome channel/message, warning-escalation thresholds, all with searchable role/channel pickers instead of raw IDs.
- **Members tab**: search members, kick/ban/timeout/warn with a reason, goes through the same shared logic as chat commands, so it's logged and escalates identically either way.
- **Autoroles / Reaction Roles tabs**: add/remove autoroles, and build reaction-role embeds (the dashboard posts the message, reacts to it, and stores the mapping for you).
- **Tags tab**: add/remove custom `!tagname` shortcuts.
- **Warnings / Mod Log tabs**: view and clear warnings, browse full history.

A few things are chat-only for now (no dashboard equivalent yet): `!purge`, `!poll`, `!roll`/`!coinflip`/`!wheel`, and `!avatar`/`!serverinfo`/`!userinfo`/`!info`.
