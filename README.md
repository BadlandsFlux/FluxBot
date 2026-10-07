# FluxBot

A self-hosted moderation and community bot for [Fluxer](https://fluxer.app), paired with a full web dashboard so most day-to-day admin work never needs a chat command. Works against the official instance or a self-hosted one, just point `FLUXER_API_BASE` wherever you'd like.

> **AI Disclosure:** This bot was written with help from AI. I don't have the time to really dig into the API structure and build a proper bot at this moment. This is just a stopgap until a properly featured bot comes out (if ever). Continued support is "best effort" and at will, I promise no commitment.

## What you get

- **Moderation**: kick, ban, timeout, purge, and an auto-escalating warning system (warn → timeout → kick), all logged to a channel. Chat commands and the dashboard's Members tab share the same logic, so behavior never drifts between the two.
- **Leveling & engagement**: XP from chat and voice activity, level-up announcements, level-role rewards, achievements, a leaderboard, visual `!rank` cards, an all-time "wrapped" recap image, and live trivia.
- **Roles & welcomes**: autoroles, reaction roles, welcome/goodbye messages, custom `!tag` shortcuts, and a per-server command prefix.
- **Bug/issue reports**: members post in a dedicated channel, no command needed. Tracked in a second channel as a status-tagged embed, with automatic duplicate flagging and an option to stay anonymous.
- **Activity logging**: message edits/deletes, member joins/leaves, channel/role changes, voice activity, and privileged-role grants, each independently togglable to its own channel.
- **Discord relay**: bridges Discord channels to Fluxer channels, one way or both, with attachments, edits/deletes, and translated mentions, configured entirely from the dashboard.
- **A real dashboard**: a full React app with live search, near-real-time updates from chat, a Members tab you can moderate straight from, a leaderboard/level-role editor, a custom embed builder, a public status page, and more.
- **Self-hostable end to end**: the bot and dashboard both talk to the Fluxer REST API directly (no third-party wrapper's undocumented internals), Postgres for storage, and every Fluxer-specific URL is a config value.

## Table of contents

- [Setup](#setup)
- [Updating](#updating)
- [Running at startup on Ubuntu (systemd)](#running-at-startup-on-ubuntu-systemd)
- [Docker](#docker)
- [Reverse proxy (nginx)](#reverse-proxy-nginx)
- [Creating the bot application on Fluxer](#creating-the-bot-application-on-fluxer)
- [Self-hosting a Fluxer instance](#self-hosting-a-fluxer-instance)
- [Dashboard access](#dashboard-access)
- [Commands](#commands)
- [Project layout](#project-layout)

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
   - `FLUXER_BOT_TOKEN`, your bot's token (see [Creating the bot application on Fluxer](#creating-the-bot-application-on-fluxer) if you don't have one yet).
   - `BOT_OWNER_ID`, your own Fluxer user ID, gates the owner-only `!info` command and the dashboard's Bot Profile and Discord Relay Setup pages.
   - `DISCORD_BOT_TOKEN` (optional), only needed for the Discord relay feature, and can be set from the dashboard instead once the bot's running, so it's fine to leave blank here.
   - `FLUXER_API_BASE` / `FLUXER_WEB_BASE` / `FLUXER_GATEWAY_URL`, leave as the official instance, or point at your self-hosted domain (see [Self-hosting a Fluxer instance](#self-hosting-a-fluxer-instance)).
   - `DATABASE_URL`, your Postgres connection string.
   - `FLUXER_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI`, for the dashboard's "Login with Fluxer" button.
   - `DASHBOARD_SESSION_SECRET`, any long random string.

4. **Install deps.**
   ```bash
   pip install -r requirements.txt
   ```

5. **Apply the schema** (optional, both processes also do this automatically on startup):
   ```bash
   python -m common.db
   ```

6. **Build the frontend** (one time, a static build, not a server, so this doesn't need repeating unless you change frontend code):
   ```bash
   cd dashboard-frontend
   npm install
   npm run build      # outputs dashboard-frontend/dist
   cd ..
   ```
   If `dist/` doesn't exist yet, the dashboard will say so at `/` instead of erroring.

7. **Run.**
   ```bash
   python run_bot.py          # in one terminal
   python run_dashboard.py    # in another
   ```
   Dashboard defaults to `http://localhost:8000`, one process serves both the API and the built frontend, no Node server needed at runtime.

   **Iterating on the frontend?** Run `npm run dev` in `dashboard-frontend/` (Vite on `:5173`, proxying `/api`, `/login`, `/auth` to the FastAPI backend on `:8000`) alongside `python run_dashboard.py` for hot reload. Run `npm run build` again when you're done, to update what gets served in production.

## Updating

```bash
git pull
pip install -r requirements.txt          # pick up any new/changed Python deps
python -m common.db                      # apply any new schema migrations (idempotent)
cd dashboard-frontend && npm install && npm run build && cd ..   # rebuild the frontend
```

Then restart both processes. All four commands above are safe no-ops if a given update didn't touch that part.

If you're on the `deploy/` systemd services, run that sequence as whichever user can write to `/opt/fluxbot` (or `sudo -u fluxbot ...` each command), then:
```bash
sudo systemctl restart fluxbot-bot.service fluxbot-dashboard.service
```

If you're on Docker (see [Docker](#docker)), updating is just:
```bash
git pull
docker compose up -d --build
```

## Running at startup on Ubuntu (systemd)

`python run_bot.py` / `run_dashboard.py` running in a terminal stop when you log out. For a real deployment, run both as `systemd` services, they'll start on boot and restart automatically if either crashes.

1. **Put the project somewhere systemd-friendly and create a dedicated user:**
   ```bash
   sudo useradd --system --home /opt/fluxbot --shell /usr/sbin/nologin fluxbot
   sudo mkdir -p /opt/fluxbot
   sudo cp -r . /opt/fluxbot        # from your project directory
   sudo chown -R fluxbot:fluxbot /opt/fluxbot
   ```

2. **Set up a virtualenv as that user:**
   ```bash
   sudo -u fluxbot python3 -m venv /opt/fluxbot/venv
   sudo -u fluxbot /opt/fluxbot/venv/bin/pip install -r /opt/fluxbot/requirements.txt
   ```
   Build the frontend once too (needs Node; see [Setup](#setup)), `dist/` just needs to exist under `/opt/fluxbot/dashboard-frontend/`.

3. **Make sure `/opt/fluxbot/.env` exists and is filled in**, then lock it down:
   ```bash
   sudo chmod 600 /opt/fluxbot/.env
   sudo chown fluxbot:fluxbot /opt/fluxbot/.env
   ```

4. **Install the unit files** (included under `deploy/`):
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
   `LOG_LEVEL` in `.env` controls verbosity for both processes (`DEBUG`/`INFO`/`WARNING`/`ERROR`); restart both after changing it.

7. **After pulling code changes**, see [Updating](#updating), then restart as in step 5's commands.

If Postgres runs on this same machine, uncomment `Requires=postgresql.service` in both unit files before installing them. Leave it commented out if Postgres is on a remote host.

## Docker

An alternative to the systemd path above, not a replacement for it, use whichever fits how you host things.

```bash
cp .env.example .env   # fill in FLUXER_BOT_TOKEN, the OAuth2 creds, DASHBOARD_SESSION_SECRET, etc.
docker compose up -d --build
```

This brings up three containers: `postgres` (data in a named volume), `bot`, and `dashboard` (both built from the same multi-stage `Dockerfile`: a Node stage compiles the frontend, a Python stage runs the processes). It overrides two things from your `.env`: `DATABASE_URL` points at the `postgres` service's Docker DNS name instead of `localhost`, and `DASHBOARD_HOST` becomes `0.0.0.0` so the published port is reachable. Everything else in `.env` is used as-is. Schema setup is automatic, same as the non-Docker path.

```bash
docker compose logs -f bot          # or dashboard / postgres
docker compose down                 # stop everything, keeps the postgres_data volume
docker compose down -v              # stop everything AND delete the database
docker compose up -d --build        # after pulling code changes, rebuild and restart
```

**Already have a Postgres you'd rather use** (a managed service, one instance shared across several apps)? Set `DATABASE_URL` in `.env` to that instance and bring the stack up with the external-db override instead, which skips starting the bundled `postgres` service and uses `DATABASE_URL` exactly as given:
```bash
docker compose -f docker-compose.yml -f docker-compose.external-db.yml up -d --build
```

TLS/reverse-proxying still isn't part of this, same as bare-metal: put nginx in front of the published dashboard port yourself if you want HTTPS, and set `DASHBOARD_COOKIE_SECURE=true`/`TRUSTED_PROXY_IPS` to match, see [Reverse proxy (nginx)](#reverse-proxy-nginx).

## Reverse proxy (nginx)

The dashboard listens on plain HTTP (`DASHBOARD_PORT`, default 8000). For a real deployment, put nginx in front of it to handle TLS and expose it on 443, a config is included at `deploy/nginx-fluxbot.conf`.

1. **Install nginx and certbot:**
   ```bash
   sudo apt install nginx certbot python3-certbot-nginx
   ```

2. **Point DNS** for your dashboard's domain (e.g. `dashboard.example.com`) at this server, then get a cert:
   ```bash
   sudo certbot --nginx -d dashboard.example.com
   ```
   To set up nginx first and get the cert after, comment out the `server { listen 443 ... }` block below and change the port-80 block's redirect to a `proxy_pass` instead, so you can reach the dashboard over plain `http://` while DNS/certs are in progress.

3. **Install the config:**
   ```bash
   sudo cp deploy/nginx-fluxbot.conf /etc/nginx/sites-available/fluxbot
   sudo sed -i 's/dashboard.example.com/your-real-domain.com/g' /etc/nginx/sites-available/fluxbot
   sudo ln -s /etc/nginx/sites-available/fluxbot /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

4. **Confirm the dashboard is bound to localhost only** (the default since `.env.example`):
   ```
   DASHBOARD_HOST=127.0.0.1
   DASHBOARD_COOKIE_SECURE=true
   ```
   The second line marks the session cookie `Secure` (HTTPS-only), worth turning on now that nginx terminates TLS in front of you. Restart the dashboard, then open your firewall for 80/443 only (not 8000):
   ```bash
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   ```

5. **Update the OAuth2 redirect URI** to match your real domain, both in `.env` (`FLUXER_OAUTH_REDIRECT_URI=https://dashboard.example.com/auth/callback`) and on the Fluxer application itself, then restart. This also fixes `DASHBOARD_PUBLIC_URL` (derived from the redirect URI unless set explicitly), used by the Discord relay's avatar proxy.

The included config proxies everything to the dashboard, sets the standard `X-Forwarded-*` headers, and long-caches the frontend's content-hashed static assets.

## Creating the bot application on Fluxer

One Fluxer "Application" gives you everything: the bot token, the OAuth2 client ID/secret for the dashboard's login, and the invite link.

1. **Enable Developer Mode** (lets you copy IDs by right-clicking): User Settings → Advanced → Developer → toggle **Developer Mode** on.
2. **Create the application**: User Settings → Applications → **Create Application**.
3. **Get the bot token** for `.env`'s `FLUXER_BOT_TOKEN`: **Secrets & tokens** → **Bot token** → **Regenerate**. Copy it immediately, it won't be shown again. Treat it like a password.
4. **Get the OAuth2 credentials**: **Application ID** at the top is `FLUXER_OAUTH_CLIENT_ID`; **Client secret** under Secrets & tokens is `FLUXER_OAUTH_CLIENT_SECRET`.
5. **Add the dashboard's redirect URI**: under **Redirect URIs**, add exactly what you set as `FLUXER_OAUTH_REDIRECT_URI` (e.g. `https://your-dashboard-domain/auth/callback`). Has to match exactly, including trailing slashes.
6. **Invite the bot to your server**: under **OAuth2 URL builder**, check the `bot` scope, then under **Bot permissions** check what the bot actually uses: Kick Members, Ban Members, Moderate Members (timeout), Manage Roles, Manage Messages, Manage Guild, Send Messages, Embed Links, Add Reactions, View Channel, Read Message History. Open the generated Authorize URL to add the bot.

   Least privilege matters here independently of the bot's own hierarchy/self/owner protections: a smaller permission set is a smaller blast radius if the bot's token is ever compromised. Checking **Administrator** instead guarantees every command works, at the cost of that reduced blast radius.

## Self-hosting a Fluxer instance

Point these three at your instance and everything else (REST calls, the gateway connection, OAuth login) follows automatically:

```
FLUXER_API_BASE=https://your-domain.com/v1
FLUXER_WEB_BASE=https://your-domain.com
FLUXER_GATEWAY_URL=wss://your-domain.com/gateway   # only if GET /gateway/bot isn't available on your instance
```

## Dashboard access

Anyone can log in with "Login with Fluxer", that just proves who they are. What they can actually *do* is checked live, on every page load, against `GET /users/@me/guilds`:

- A server only shows up in their picker if the bot is installed there **and** they have "Manage Server" permission (or own it).
- No separate allowlist or cached role: demote someone in Fluxer and they lose dashboard access on their next request.
- The `/commands` reference page is public, no login needed.

To restrict the dashboard further (e.g. only the bot owner, or an explicit allowlist), that check lives in `_require_manage()` in `dashboard/app.py`.

## Commands

Run `!help` in Fluxer for the live, per-server list, or visit the dashboard's `/commands` page, same source, always in sync.

Kick/ban/timeout/warn refuse to act on yourself, the server owner, or anyone whose highest role outranks or ties yours, regardless of your raw permission bit.

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
| `!note add/list/remove @user <text>` | Kick Members | Private staff notes, no escalation |
| `!clearwarnings @user` | Kick Members | Clear active warnings |
| `!modlog #channel` | Manage Guild | Set the mod-log channel |
| `!autorole add/remove/list @role [page]` | Manage Guild | Roles auto-given on join, list is paginated (20/page) |
| `!reactionrole add/remove/list ...` | Manage Guild | Reaction to role mapping, list is paginated (10/page) and filterable by `@role`/`#channel` |
| `!avatar [@user]` | none | Show a member's avatar |
| `!serverinfo` | none | Member count, owner, boost tier, and more |
| `!userinfo [@user]` | none | Account age, join date, roles, staff rank |
| `!info` | Owner only | Bot-level stats (uptime, latency, server count) |
| `!poll "Q" "A" "B" ... [duration]` | none | Reaction poll, up to 10 options, optional auto-close with tallied results |
| `!tag add/remove/list <name> <content>` | Manage Guild (add/remove) | Custom `!name` shortcuts |
| `!remind <duration> <text>` | none | e.g. `!remind 2h take out trash` (10 pending max per person) |
| `!reminders` | none | List your pending reminders |
| `!delreminder <id>` | none | Cancel a reminder |
| `!rank [@user]` | none | Visual rank card (avatar, level, XP bar, stats) |
| `!leaderboard` | none | Server XP leaderboard |
| `!wrapped` | none | All-time server recap image |
| `!achievements [@user]` | none | Milestone badges earned |
| `!mydata` | none | Everything the bot has stored about you (DMs it) |
| `!ping` | none | Gateway/API/DB latency, uptime, server count |
| `!afk [reason]` | none | Mark yourself away; auto-clears on your next message |
| `!roll [NdM]`, `!coinflip`, `!wheel a, b, c` | none | Fun stuff |
| `!trivia` | none | Multiple-choice trivia, closes in 30s, correct answers earn XP |
| `!link` | none | Start linking your Discord and Fluxer accounts (DMs you a code) |
| `!unlink` | none | Remove your account link |
| `!linkstatus` | none | Show whether you're currently linked |
| `!reportchannel #channel` | Manage Guild | Set the channel reports are captured from |
| `!reporttracker #channel` | Manage Guild | Set the channel reports are tracked in |
| `!report status <id> <open\|duplicate\|resolved\|wontfix> [note]` | Kick Members | Update a report's status |
| `!report reply <id> <message>` | Kick Members | DM the reporter and record it as part of the report's thread |
| `!report list [status]` | Kick Members | List reports, optionally filtered |
| `!report info <id>` | Kick Members | Full detail on one report, including its most recent replies |

`!info` is gated by `BOT_OWNER_ID` in `.env`, not a per-server permission, it's meant for you, not server admins.

Tags can also be managed from the dashboard's Tags tab. Invoking `!<tagname>` posts its content as a fallback whenever a message doesn't match a built-in command; tag names can't collide with a real command name.

## Project layout

```
common/                config + the shared Postgres data layer (used by both processes)
  config.py            env-driven settings
  db.py                asyncpg pool + all queries
  discovery.py         instance discovery + CDN URL helpers (guild icons, avatars)
bot/
  rest.py              REST client (self-host aware, base URL from config)
  client.py            gateway (WebSocket) client, handshake, heartbeats, reconnect
  commands.py          tiny prefix-command framework + dispatcher (falls back to
                        custom tags when a message doesn't match a built-in command)
  permissions.py       role/permission bit checks
  timeutil.py          snowflake to date, duration string parsing
  moderation_actions.py  shared kick/ban/timeout/warn logic (chat + dashboard)
  report_actions.py    shared report status/tracker-embed/reply logic (chat + dashboard)
  scheduler.py          background loop: reminders, polls, voice session flushing
  voice_tracker.py       voice presence tracking for activity stats and voice XP
  discord_relay.py      the Discord-side bridge (gateway client, webhook relay)
  modules/
    moderation.py       kick/ban/unban/timeout/purge/warn/warnings/modlog
    roles.py            autorole + reaction roles + welcome/goodbye messages
    fun.py              roll/coinflip/wheel/poll
    info.py             avatar/serverinfo/userinfo/info (owner-only)
    tags.py             !tag add/remove/list
    reminders.py         !remind/!reminders/!delreminder
    leveling.py          XP gain, level-up + role rewards, !rank/!leaderboard
    activity.py          per-day/per-member message counters for dashboard stats
    utility.py          help/ping
    logging_mod.py       writes mod_actions rows + posts to the log channel
    account_links.py     !link/!unlink/!linkstatus, Discord <-> Fluxer linking
    reports.py            captures bug/issue reports, tracker embed, duplicate
                        detection, two-way reply thread over DM,
                        !reportchannel/!reporttracker/!report
  main.py                entrypoint, also starts the scheduler task
dashboard/
  app.py                FastAPI app, JSON API (/api/*) + serves the built SPA
  oauth.py              OAuth2 "Login with Fluxer" flow
dashboard-frontend/      React SPA (Vite), see its own README for the full API reference
  src/
    api.js               fetch wrapper for the backend's /api/* routes
    App.jsx               routing + auth-gate
    context/              GuildsContext (shared guild-list fetch for the picker
                          and the top-bar switcher)
    pages/                Login, GuildPicker, GuildDetail, ReportDetail,
                          BotProfile, DiscordRelaySetup, Commands, Status
    components/           one per dashboard tab/widget (MembersTab, LevelsTab,
                          ReportsTab, DiscordRelayTab, ActivityLogTab, TagsTab,
                          ReactionRoleBuilder, EmbedBuilder, DangerZone, …)
    hooks/                useRolesChannels, usePolling
  dist/                  production build, FastAPI serves this (git-ignored)
schema.sql              Postgres schema (idempotent, safe to re-run)
run_bot.py / run_dashboard.py
deploy/                systemd unit files + nginx reverse proxy config
Dockerfile              multi-stage build (Node for the frontend, Python for bot + dashboard)
docker-compose.yml      bot + dashboard + Postgres, alternative to deploy/
```

Fluxer's own API docs are at [fluxer.dev](https://fluxer.dev). [`dashboard-frontend/README.md`](dashboard-frontend/README.md) has the full HTTP API reference for this project's own dashboard backend, every endpoint the frontend calls, useful as a porting checklist for a backend rewrite, or if you want to reuse the frontend for something else.
