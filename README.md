# FluxBot

A Python moderation bot for [Fluxer](https://fluxer.app) with a FastAPI web dashboard. Works against the official instance or a self-hosted one, just change `FLUXER_API_BASE`.

> **AI Disclosure:** This bot was written with help from AI. I don't have the time to really dig into the API structure and build a proper bot at this moment. This is just a stopgap until a properly featured bot comes out (if ever). Continued support is "best effort" and at will, I promise no commitment.

- **Bot**: kick / ban / unban / timeout / purge, a warning system with auto-escalation (warn to auto-timeout to auto-kick), mod-action logging to a channel, autoroles, reaction roles, welcome **and goodbye** messages, custom tags (`!tagname` shortcuts), per-server command prefixes, info commands (`!avatar`, `!serverinfo`, `!userinfo`, owner-only `!info`), reminders (`!remind`), a leveling/XP system covering **both text and voice activity** (chat XP with a cooldown, plus voice-time XP at a lower rate that only counts when 2+ people are connected, no one's self-deafened, and it's not the AFK channel) with level-up announcements and level-role rewards (`!rank`, `!leaderboard`), timed polls that auto-close with a results tally (`!poll ... 1h`), `!ping` with real gateway/API/DB latency and uptime stats, and fun commands (dice, coinflip, wheel spin). A background scheduler delivers due reminders, closes due polls, and periodically flushes in-progress voice sessions, all independent of the gateway connection. Moderation logic (REST calls, logging, warn escalation) lives in one shared module (`bot/moderation_actions.py`) used by both chat commands and the dashboard's Members tab, so behavior can't drift between the two.
- **Dashboard**: a React SPA (Vite) served by FastAPI as static files, talking to a JSON API (`/api/*`), with real client-side routing, no full-page reloads, live search on the commands page, and a quiet 8-second poll on each server's page so kicks/bans/warnings from chat show up without a manual refresh. A top-bar server switcher shows the current server's name/icon and lets you jump between manageable servers without going back to the picker. Tabbed per-server UI (Overview, Settings, Members, Warnings, Mod Log, Autoroles, Reaction Roles, **Levels**, Tags, **Announce**) with searchable role/channel pickers everywhere instead of raw ID text boxes, real server icons in the picker, a Members tab to search and kick/ban/timeout/warn directly from the browser, welcome/goodbye message configuration behind toggle switches, a leveling tab (leaderboard + level-role reward setup), a custom embed/announcement builder, a reaction-role builder (emoji picker, per-choice label, role picker, embed color) that posts the embed, reacts to it, and starts listening for you, and an Overview tab with **separate 14-day charts for message and voice activity** plus most-active-members lists for each. A public `/commands` page lists every command, always in sync with the bot since it's generated from the same code. Access is via "Login with Fluxer" OAuth2, see "Dashboard access" below.
- **Storage**: Postgres, shared by both processes over a real connection pool (not a shared SQLite file), via `asyncpg`.

Both the bot and the dashboard talk to the Fluxer REST API directly (raw `aiohttp`/gateway handshake) rather than depending on a third-party wrapper's undocumented internals, so self-hosting support is just config.

## Table of contents

- [Project layout](#project-layout)
- [Setup](#setup)
- [Updating](#updating)
- [Running at startup on Ubuntu (systemd)](#running-at-startup-on-ubuntu-systemd)
- [Reverse proxy (nginx)](#reverse-proxy-nginx)
- [Creating the bot application on Fluxer](#creating-the-bot-application-on-fluxer)
- [Self-hosting a Fluxer instance](#self-hosting-a-fluxer-instance)
- [Dashboard access](#dashboard-access)
- [On API completeness](#on-api-completeness)
- [Commands](#commands)
- [What's editable from the dashboard vs. chat-only](#whats-editable-from-the-dashboard-vs-chat-only)

## Project layout

```
common/                config + the shared Postgres data layer (used by both processes)
  config.py            env-driven settings
  db.py                asyncpg pool + all queries (guilds, warnings, mod_actions,
                        reaction_roles, autoroles, tags, reminders, polls,
                        levels, level_roles, activity stats)
  discovery.py         instance discovery + CDN URL helpers (guild icons, avatars)
bot/
  rest.py              REST client (self-host aware, base URL from config)
  client.py            gateway (WebSocket) client, handshake, heartbeats, reconnect
  commands.py          tiny prefix-command framework + dispatcher (also falls back
                        to custom tags when a message doesn't match a built-in command)
  permissions.py       role/permission bit checks
  timeutil.py          snowflake to date, duration + shared duration-string parsing
  moderation_actions.py  shared kick/ban/timeout/warn logic, used by both chat
                        commands and the dashboard's Members tab
  scheduler.py          background loop: delivers due reminders, closes and
                        tallies due polls, flushes in-progress voice sessions,
                        independent of the gateway connection
  voice_tracker.py       voice channel presence tracking for activity stats
                        and voice XP (join/leave/mute events only, no audio)
  modules/
    moderation.py       kick/ban/unban/timeout/purge/warn/warnings/modlog (thin
                        wrappers around moderation_actions.py)
    roles.py            autorole + reaction roles + welcome/goodbye messages
    fun.py              roll/coinflip/wheel/poll (with optional auto-close)
    info.py             avatar/serverinfo/userinfo/info (owner-only)
    tags.py             !tag add/remove/list
    reminders.py         !remind/!reminders/!delreminder
    leveling.py          XP gain on message, level-up + role rewards, !rank/!leaderboard
    activity.py          per-day/per-member message counters for dashboard stats
    utility.py          help/ping
    logging_mod.py       writes mod_actions rows + posts to the log channel
  main.py                entrypoint, also starts the scheduler task
dashboard/
  app.py                FastAPI app, JSON API (/api/*) + serves the built SPA
  oauth.py              OAuth2 "Login with Fluxer" flow
dashboard-frontend/      React SPA (Vite)
  src/
    api.js               fetch wrapper for the backend's /api/* routes
    App.jsx               routing + auth-gate
    context/              GuildsContext (shared guild-list fetch for the picker
                          and the top-bar switcher)
    pages/                Login, GuildPicker, GuildDetail, Commands
    components/           TopBar, GuildSwitcher, Flash (toasts), Spinner, Switch,
                          Combobox (role/channel picker), EmojiPicker, BarChart,
                          ReactionRoleBuilder, AnnouncementBuilder, MembersTab,
                          TagsTab, LevelsTab
    hooks/                useRolesChannels (fetch once per guild), usePolling
                          (visibility-aware interval)
  dist/                  production build, FastAPI serves this (git-ignored,
                          build it yourself)
schema.sql              Postgres schema (idempotent, CREATE TABLE IF NOT EXISTS,
                        plus ALTER TABLE ADD COLUMN IF NOT EXISTS migrations)
run_bot.py / run_dashboard.py
deploy/                systemd unit files + nginx reverse proxy config for running
                        both processes at boot on Ubuntu
```

## Setup

1. **Get the code.**
   ```bash
   git clone https://github.com/BadlandsFlux/FluxBot.git
   cd FluxBot
   ```

2. **Postgres.** Create a database and user:
   ```bash
   createdb fluxerbot
   psql fluxerbot -c "CREATE USER fluxerbot WITH PASSWORD 'fluxerbot';"
   psql fluxerbot -c "GRANT ALL PRIVILEGES ON DATABASE fluxerbot TO fluxerbot;"
   psql fluxerbot -c "GRANT ALL ON SCHEMA public TO fluxerbot;"
   ```
   (Any Postgres works, a managed service, Docker, etc. Just point `DATABASE_URL` at it.)

3. **Env.**
   ```bash
   cp .env.example .env
   ```
   Fill in:
   - `FLUXER_BOT_TOKEN`, your bot's token (see "Creating the bot application on Fluxer" below if you don't have one yet).
   - `BOT_OWNER_ID`, your own Fluxer user ID, gates the owner-only `!info` command.
   - `FLUXER_API_BASE` / `FLUXER_WEB_BASE` / `FLUXER_GATEWAY_URL`, leave as the official instance, or point at your self-hosted domain (see below).
   - `DATABASE_URL`, your Postgres connection string.
   - `FLUXER_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI`, for the dashboard's "Login with Fluxer" button (see "Creating the bot application on Fluxer" below).
   - `DASHBOARD_SESSION_SECRET`, any long random string.

4. **Install deps.**
   ```bash
   pip install -r requirements.txt
   ```

5. **Apply the schema** (optional, both processes also do this automatically on startup):
   ```bash
   python -m common.db
   ```

6. **Build the frontend** (one time, it's a static React build, not a server, so this doesn't need repeating unless you change frontend code):
   ```bash
   cd dashboard-frontend
   npm install
   npm run build      # outputs dashboard-frontend/dist
   cd ..
   ```
   If `dist/` doesn't exist yet, the dashboard will say so at `/` instead of erroring, so it's obvious if you skip this step.

7. **Run.**
   ```bash
   python run_bot.py          # in one terminal
   python run_dashboard.py    # in another
   ```
   Dashboard defaults to `http://localhost:8000`, one process serves both the API and the built frontend, no Node server needed at runtime.

   **Iterating on the frontend?** Run `npm run dev` in `dashboard-frontend/` (Vite on `:5173`, proxying `/api`, `/login`, `/auth` to the FastAPI backend on `:8000`, see `vite.config.js`) alongside `python run_dashboard.py` in another terminal for hot reload, instead of rebuilding on every change. Run `npm run build` again when you're done to update what gets served in production.

## Updating

```bash
git pull
pip install -r requirements.txt          # pick up any new/changed Python deps
python -m common.db                      # apply any new schema migrations (idempotent, safe to always run)
cd dashboard-frontend && npm install && npm run build && cd ..   # rebuild the frontend
```

Then restart both processes, however you're running them, `Ctrl+C` and re-run `python run_bot.py`/`python run_dashboard.py` if running manually, or see the systemd section below for `systemctl restart` if running as a service. There's no harm in running all four commands above even if a given update didn't touch that part (e.g. no new npm deps), they're all safe no-ops in that case.

If you're on the `deploy/` systemd services, run the `git pull`/`pip install`/`python -m common.db`/`npm run build` sequence as whichever user can write to `/opt/fluxbot` (or `sudo -u fluxbot ...` each command), then restart:
```bash
sudo systemctl restart fluxbot-bot.service fluxbot-dashboard.service
```

## Running at startup on Ubuntu (systemd)

`python run_bot.py` and `python run_dashboard.py` running in a terminal stop when you log out. For a real deployment, run both as `systemd` services, they'll start on boot and restart automatically if either crashes.

1. **Put the project somewhere systemd-friendly and create a dedicated user:**
   ```bash
   sudo useradd --system --home /opt/fluxbot --shell /usr/sbin/nologin fluxbot
   sudo mkdir -p /opt/fluxbot
   sudo cp -r . /opt/fluxbot        # from your project directory
   sudo chown -R fluxbot:fluxbot /opt/fluxbot
   ```

2. **Set up a virtualenv as that user** (keeps dependencies isolated from system Python):
   ```bash
   sudo -u fluxbot python3 -m venv /opt/fluxbot/venv
   sudo -u fluxbot /opt/fluxbot/venv/bin/pip install -r /opt/fluxbot/requirements.txt
   ```
   Build the frontend once too (needs Node; see the Setup section above), `dist/` just needs to exist under `/opt/fluxbot/dashboard-frontend/`, it doesn't matter which user built it.

3. **Make sure `/opt/fluxbot/.env` exists and is filled in** (copy from `.env.example`, same as regular setup). Since `fluxbot` is a system user, lock it down:
   ```bash
   sudo chmod 600 /opt/fluxbot/.env
   sudo chown fluxbot:fluxbot /opt/fluxbot/.env
   ```

4. **Install the unit files** (included in this repo under `deploy/`):
   ```bash
   sudo cp deploy/fluxbot-bot.service deploy/fluxbot-dashboard.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

5. **Enable and start both:**
   ```bash
   sudo systemctl enable --now fluxbot-bot.service
   sudo systemctl enable --now fluxbot-dashboard.service
   ```

6. **Check on them:**
   ```bash
   systemctl status fluxbot-bot.service
   journalctl -u fluxbot-bot.service -f          # live logs
   journalctl -u fluxbot-dashboard.service -f
   ```
   Set `LOG_LEVEL` in `.env` to control verbosity for both processes: `DEBUG` for troubleshooting something specific (e.g. voice tracking), `INFO` (the default) for normal operation, or `WARNING`/`ERROR` to only see actual problems. Restart both processes after changing it.

7. **After pulling code changes**, see "Updating" above, then restart:
   ```bash
   sudo systemctl restart fluxbot-bot.service fluxbot-dashboard.service
   ```

If Postgres runs on this same machine, uncomment the `Requires=postgresql.service` line in both unit files before installing them, so they wait for the database on boot. Leave it commented out if Postgres is on a remote host, systemd can't depend on a service running on a different machine.

## Reverse proxy (nginx)

The dashboard listens on plain HTTP (`DASHBOARD_PORT`, default 8000). For a real deployment, put nginx in front of it to handle TLS and expose it on the standard 443 port, a config is included at `deploy/nginx-fluxbot.conf`.

1. **Install nginx and certbot:**
   ```bash
   sudo apt install nginx certbot python3-certbot-nginx
   ```

2. **Point DNS** for your dashboard's domain (e.g. `dashboard.example.com`) at this server, then get a cert:
   ```bash
   sudo certbot --nginx -d dashboard.example.com
   ```
   If you'd rather set up the nginx config first and get the cert after, comment out the `server { listen 443 ... }` block in the config below and change the port-80 block's redirect to a `proxy_pass` instead, so you can reach the dashboard over plain `http://` while DNS/certs are still in progress.

3. **Install the config:**
   ```bash
   sudo cp deploy/nginx-fluxbot.conf /etc/nginx/sites-available/fluxbot
   sudo sed -i 's/dashboard.example.com/your-real-domain.com/g' /etc/nginx/sites-available/fluxbot
   sudo ln -s /etc/nginx/sites-available/fluxbot /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

4. **Bind the dashboard to localhost only**, now that nginx is the public entry point. In `.env`:
   ```
   DASHBOARD_HOST=127.0.0.1
   DASHBOARD_COOKIE_SECURE=true
   ```
   The second line marks the login session cookie `Secure`, meaning the browser will only ever send it over HTTPS, worth turning on now that nginx is terminating TLS in front of you. Leave it `false` only if you're deliberately running without HTTPS (not recommended). Restart the dashboard after changing this, then open your firewall for 80/443 only (not 8000):
   ```bash
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   ```

5. **Update the OAuth2 redirect URI** to match your real domain, both in `.env` (`FLUXER_OAUTH_REDIRECT_URI=https://dashboard.example.com/auth/callback`) and on the Fluxer application itself (see "Creating the bot application on Fluxer" below), then restart the dashboard.

The included config proxies everything to the dashboard, sets the standard `X-Forwarded-*` headers, and long-caches the frontend's content-hashed static assets (`/assets/*`) since a new deploy always gets new filenames from Vite's build.

## Creating the bot application on Fluxer

One Fluxer "Application" gives you everything: the bot token, the OAuth2 client ID/secret for the dashboard's login, and the invite link. Steps, from the actual Fluxer web UI:

1. **Enable Developer Mode** (lets you copy IDs anywhere by right-clicking): User Settings → Advanced → Developer → toggle **Developer Mode** on.

2. **Create the application**: User Settings → Applications → **Create Application**, give it a name (e.g. `FluxBot`).

3. **Get the bot token** for `.env`'s `FLUXER_BOT_TOKEN`: on the application page, under **Secrets & tokens** → **Bot token** → click **Regenerate**. Copy it immediately, it won't be shown again. Treat it like a password; regenerating later breaks anything still using the old one.

4. **Get the OAuth2 credentials** for the dashboard's "Login with Fluxer": still on the application page, **Application ID** at the top is your `FLUXER_OAUTH_CLIENT_ID`; **Client secret** under Secrets & tokens (click Regenerate to reveal it) is your `FLUXER_OAUTH_CLIENT_SECRET`.

5. **Add the dashboard's redirect URI**: under **Redirect URIs**, add exactly what you set as `FLUXER_OAUTH_REDIRECT_URI` in `.env` (e.g. `https://your-dashboard-domain/auth/callback`), then **Add redirect**. This has to match exactly, including scheme and trailing slashes, or the login flow will fail.

6. **Invite the bot to your server**: scroll down to **OAuth2 URL builder**. Check the `bot` scope, then under **Bot permissions** check **Administrator** (simplest, guarantees every command works without fiddling with individual bits), copy the generated **Authorize URL**, and open it in a browser to add the bot to your server. The redirect URI dropdown there doesn't matter for this step, it's only relevant for identify/guilds-scope logins, not a plain bot invite.

   If you'd rather not grant Administrator, the bot only actually needs: Kick Members, Ban Members, Moderate Members (timeout), Manage Roles, Manage Messages, Manage Guild, Send Messages, Embed Links, Add Reactions, View Channel, Read Message History.

## Self-hosting a Fluxer instance

Point these three at your instance and everything else (REST calls, the gateway connection, OAuth login) follows automatically:

```
FLUXER_API_BASE=https://your-domain.com/v1
FLUXER_WEB_BASE=https://your-domain.com
FLUXER_GATEWAY_URL=wss://your-domain.com/gateway   # only if GET /gateway/bot isn't available on your instance
```

## Dashboard access

Anyone can log in with "Login with Fluxer", that just proves who they are. What they can actually *do* is checked live, on every page load, against `GET /users/@me/guilds`:

- A server only shows up in their picker if the bot is installed there **and** they have "Manage Server" permission (or own it) in that server.
- There's no separate allowlist or cached role, demote someone in Fluxer and they lose dashboard access on their next request.
- The `/commands` reference page is public and needs no login, since it's just documentation.

If you want to restrict the dashboard further (e.g. only the bot owner, or an explicit allowlist of user IDs), that check lives in `_require_manage()` in `dashboard/app.py`, straightforward to tighten.

## On API completeness

Fluxer's public API reference is still being filled in (as of mid-2026), and some routes here, particularly the exact moderation endpoints (`ban`/`timeout`/`purge`), member-list pagination, and the OAuth2 guild-list response shape, are implemented following the Discord-like conventions Fluxer is modeled on, since that's the best information available. Everything funnels through a small number of methods:

- REST calls (including member list/kick/ban/timeout): `bot/rest.py`
- Permission bit values: `bot/permissions.py`
- OAuth2 guild permission check: `dashboard/oauth.py::can_manage`
- Media/CDN URL paths (guild icons, avatars) and snowflake to date epoch: `common/discovery.py`, `bot/timeutil.py`
- The guild's AFK-channel field name (assumed `afk_channel_id`, Discord convention) used to exclude AFK-channel time from voice XP/stats: `bot/voice_tracker.py`
- Mention suppression (`allowed_mentions` on outgoing messages, Discord convention): `bot/rest.py`

If your instance's OpenAPI spec (usually at `<api_base>/openapi.json`, or your instance's own `/api-reference` page) disagrees with a path or bit value here, that's the source of truth, the fix is a one-line change in one of those files, not a rewrite.

One concrete limit worth knowing: the dashboard's Members tab fetches up to 500 members per request (Fluxer's member-list endpoint is paginated like Discord's). Large servers won't show every member in search, searching by exact user ID still works around that.

**On that `allowed_mentions` point specifically**: several messages the bot sends embed free text a member fully controls, `!remind`'s reminder text, a member's own username in welcome/goodbye/level-up messages, so every outgoing message defaults to pinging nobody at all (`bot/rest.py`'s `FluxerREST.SAFE_ALLOWED_MENTIONS`) unless the calling code explicitly allow-lists the one specific user ID it intends to notify (`FluxerREST.mention_only(user_id)`). This closes off a real mass-ping griefing path: without it, any member (no special permission needed) could type `@everyone` or mention other members inside free-text fields and have the bot actually broadcast it, especially if the bot's invite permission includes mention-everyone, which Administrator (this README's suggested simple option) does. If you add new code that sends a message with plain `content`, don't forget to either accept the default (nobody gets pinged) or pass `allowed_mentions=bot.rest.mention_only(the_one_user_id)` if a ping is genuinely intended, don't rely on Fluxer's own default, since we don't know what that default is on any given instance.

P.P.S. The [dashboard-frontend](https://github.com/BadlandsFlux/FluxBot/tree/main/dashboard-frontend) page has a readme with all the API endpoints I use. This frontend can be ripped out and used for other projects if you so wish.

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
| `!note add/list/remove @user <text>` | Kick Members | Private staff notes on a member, no escalation, just visibility |
| `!clearwarnings @user` | Kick Members | Clear active warnings |
| `!modlog #channel` | Manage Guild | Set the mod-log channel |
| `!autorole add/remove/list @role` | Manage Guild | Roles auto-given on join |
| `!reactionrole add/remove/list ...` | Manage Guild | Reaction to role mapping |
| `!avatar [@user]` | none | Show a member's avatar |
| `!serverinfo` | none | Member count, owner, boost tier, and more |
| `!userinfo [@user]` | none | Account age, join date, roles, staff rank |
| `!info` | Owner only | Bot-level stats (uptime, latency, server count) |
| `!poll "Q" "A" "B" ... [duration]` | none | Reaction poll, up to 10 options, optional auto-close with tallied results |
| `!tag add/remove/list <name> <content>` | Manage Guild (add/remove) | Custom `!name` shortcuts |
| `!remind <duration> <text>` | none | Set a reminder, e.g. `!remind 2h take out trash` |
| `!reminders` | none | List your pending reminders |
| `!delreminder <id>` | none | Cancel a reminder |
| `!rank [@user]` | none | XP/level progress |
| `!leaderboard` | none | Server XP leaderboard |
| `!ping` | none | Gateway/API/DB latency, uptime, server count |
| `!roll [NdM]`, `!coinflip`, `!wheel a, b, c` | none | Fun stuff |

`!info` is gated by `BOT_OWNER_ID` in `.env` (your own Fluxer user ID), not by any per-server permission, it's meant for you, not server admins.

Tags can also be managed from the dashboard's Tags tab. Once added, invoking `!<tagname>` posts its content, checked as a fallback whenever a message doesn't match a built-in command. Tag names can't collide with a real command name.

## What's editable from the dashboard vs. chat-only

Most day-to-day admin work can be done entirely from the dashboard, no need to touch Fluxer directly:

- **Settings tab**: mod-log channel, command prefix, mute role, welcome/goodbye channel and message (toggle switches), leveling on/off + level-up channel/message, warning-escalation thresholds, all with searchable role/channel pickers instead of raw IDs.
- **Members tab**: search members, kick/ban/timeout/warn with a reason, goes through the same shared logic as chat commands, so it's logged and escalates identically either way.
- **Autoroles / Reaction Roles tabs**: add/remove autoroles, and build reaction-role embeds (the dashboard posts the message, reacts to it, and stores the mapping for you). Reaction-role messages are managed as a unit: delete removes the whole message and every mapping on it, not one emoji at a time.
- **Levels tab**: view the XP leaderboard and configure level-role rewards (level N grants role X).
- **Tags tab**: add/remove custom `!tagname` shortcuts.
- **Announce tab**: compose and send a custom embed (title, description, color, image, footer) to any channel.
- **Warnings / Mod Log tabs**: view and clear warnings, browse full history.
- **Staff notes**: view, add, and remove private notes on any member directly from the Members tab.

A few things are chat-only for now (no dashboard equivalent yet): `!purge`, `!roll`/`!coinflip`/`!wheel`, `!avatar`/`!serverinfo`/`!userinfo`/`!info`, and reminders (`!remind`/`!reminders`/`!delreminder`, inherently personal/ephemeral rather than server config). Starting a poll (`!poll`) is chat-only too, though its auto-close and results tally happen automatically via the background scheduler regardless of how it was started.
