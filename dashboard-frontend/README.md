# FluxBot Dashboard API Reference

Complete list of every HTTP endpoint the React frontend (`dashboard-frontend/`) calls. Generated directly from `dashboard/app.py` and `dashboard-frontend/src/api.js`, so it reflects the real contract, not a description of intent.

Useful as the porting checklist for a backend rewrite (e.g. to C#/ASP.NET): if a rewritten backend implements every route below with matching request/response shapes, the existing React frontend needs zero changes.

## Conventions

- All `/api/*` routes return JSON. Non-2xx responses return `{"detail": "human readable message"}`.
- All `/api/guilds/{guild_id}/*` routes require an active session (see Auth) **and** live verification that the logged-in user has "Manage Server" permission (or owns) that guild, checked via `GET /users/@me/guilds` on the Fluxer API on every request. No caching, no separate allowlist.
- Auth is a signed session cookie (`SessionMiddleware`), not a bearer token, so the frontend's `fetch` calls all use `credentials: "include"`.
- IDs (guild/user/channel/role/message) are all strings, matching Fluxer's snowflake-as-string convention.

---

## Auth (not JSON, browser redirects)

### `GET /login`
No auth required. Redirects (302) to the Fluxer OAuth2 authorize URL. Sets `oauth_state` in the session for CSRF protection.

### `GET /auth/callback`
No auth required. OAuth2 redirect target.

Query params: `code`, `state`, `error` (all optional, set by Fluxer's redirect).

Behavior:
- If `error` present, redirect to `/?login_error={error}`
- If `state` missing/mismatched, redirect to `/?login_error=state_mismatch`
- On success: exchanges `code` for an access token, fetches the user via `/users/@me`, stores `{user, access_token}` in the session, redirects to `/`
- On token/user fetch failure, redirect to `/?login_error=oauth_failed`

### `POST /api/logout`
Requires an existing session (no-op if not logged in). Clears the session.

**Response 200:**
```json
{ "ok": true }
```

---

## Session / identity

### `GET /api/me`
No auth required (returns null user if not logged in, not a 401).

**Response 200 (logged in):**
```json
{ "user": { "id": "123", "username": "someone" }, "bot_name": "FluxBot" }
```
`user` contains whatever Fluxer's `/users/@me` returns, stored as-is in the session.

**Response 200 (logged out):**
```json
{ "user": null }
```

---

## Guild list

### `GET /api/guilds`
Requires login. Returns only guilds where the bot is installed **and** the user has Manage Server.

**Response 200:**
```json
{
  "guilds": [
    { "id": "111", "name": "My Server", "icon_url": "https://.../icons/111/abcd.webp?size=128" }
  ]
}
```
`icon_url` is `null` if the server has no custom icon.

---

## Commands catalog (public, powers `/commands` page)

### `GET /api/commands`
No auth required. Built by actually registering every bot command module in-memory (not hand-maintained), so it can't drift from the real bot.

**Response 200:**
```json
{
  "default_prefix": "!",
  "categories": {
    "Moderation": [
      { "name": "kick", "aliases": [], "help_text": "Kick a member. Usage: !kick @user [reason]", "permission": "Kick Members" }
    ]
  }
}
```
`permission` is a human-readable string: a Fluxer permission name, `"Everyone"`, or `"Owner only"`.

---

## Guild detail (the main dashboard payload)

### `GET /api/guilds/{guild_id}`
**Response 200:**
```json
{
  "guild": {
    "guild_id": "111",
    "name": "My Server",
    "log_channel_id": "222",
    "mute_role_id": null,
    "command_prefix": "!",
    "welcome_channel_id": "333",
    "welcome_message": "Welcome {user} to {server}! 👋",
    "warn_timeout_at": 3,
    "warn_kick_at": 5,
    "warn_timeout_minutes": 60
  },
  "actions": [
    { "id": 1, "user_id": "444", "moderator_id": "555", "action": "kick", "reason": "spam", "created_at": "2026-07-03T12:00:00+00:00" }
  ],
  "warnings": [
    { "id": 1, "user_id": "444", "moderator_id": "555", "reason": "spam", "active": true, "created_at": "2026-07-03T12:00:00+00:00" }
  ],
  "autoroles": ["666", "777"],
  "reaction_roles": [
    { "id": 1, "channel_id": "888", "message_id": "999", "emoji": "🎉", "role_id": "666", "label": "VIP" }
  ],
  "tags": [
    { "id": 1, "name": "rules", "content": "Read the pins.", "created_by": "555", "created_at": "2026-07-03T12:00:00+00:00" }
  ],
  "active_warning_count": 1
}
```
**Errors:** 404 if the bot isn't in that guild (no row in the `guilds` table yet).

`actions` list is capped at 50 most recent (server-side `LIMIT`). `autoroles` is a flat array of role ID strings, not objects.

---

## Settings

### `POST /api/guilds/{guild_id}/settings`
**Request body:**
```json
{
  "log_channel_id": "222",
  "mute_role_id": "",
  "command_prefix": "!",
  "welcome_channel_id": "333",
  "welcome_message": "Welcome {user} to {server}! 👋",
  "warn_timeout_at": 3,
  "warn_kick_at": 5,
  "warn_timeout_minutes": 60
}
```
All fields have defaults (see Pydantic model) so partial bodies are technically accepted, but the frontend always sends the full object. Empty string for `log_channel_id`/`mute_role_id`/`welcome_channel_id` means "unset" (stored as SQL `NULL`). `command_prefix` is truncated server-side to 5 chars, falls back to `"!"` if empty.

**Response 200:**
```json
{ "guild": { "note": "same shape as the guild object above, with updated values" } }
```

---

## Warnings

### `POST /api/guilds/{guild_id}/warnings/{user_id}/clear`
No body.

**Response 200:**
```json
{
  "cleared": 2,
  "warnings": [ "full updated warnings array, same shape as guild detail" ],
  "active_warning_count": 0
}
```

---

## Autoroles

### `POST /api/guilds/{guild_id}/autoroles`
**Request body:**
```json
{ "role_id": "666" }
```
**Errors:** 400 if `role_id` isn't purely numeric.

**Response 200:**
```json
{ "autoroles": ["666", "777"] }
```

### `DELETE /api/guilds/{guild_id}/autoroles/{role_id}`
No body.

**Response 200:**
```json
{ "autoroles": ["777"] }
```

---

## Reaction roles

### `POST /api/guilds/{guild_id}/reactionroles`
Sends a real embed message to the target channel (as the bot), reacts to it with each emoji, and stores the mappings.

**Request body:**
```json
{
  "channel_id": "888",
  "title": "Pick your roles",
  "description": "React below to opt in",
  "color": "5865F2",
  "pairs": [
    { "emoji": "🎉", "label": "VIP", "role_id": "666" },
    { "emoji": "🎮", "label": "Gamer", "role_id": "777" }
  ]
}
```
`color` is a hex string, `#` prefix optional, defaults to `"5865F2"` if omitted/unparseable. `pairs[].label` is optional, defaults to `""`. `channel_id` must be numeric and at least one valid pair required, else 400.

**Response 200:**
```json
{
  "reaction_roles": [ "full updated reaction_roles array for the whole guild" ],
  "failed_reactions": ["🎮"]
}
```
`failed_reactions` lists any emoji that failed to auto-react (mapping is still saved regardless; those need a manual reaction).

**Errors:** 502 if the bot couldn't send the message at all (bad channel, missing permission, etc).

### `DELETE /api/guilds/{guild_id}/reactionroles/{mapping_id}`
Removes a single emoji/role mapping (does **not** delete the message or other mappings on it). `mapping_id` is the row's integer `id`. Kept for API completeness; the current UI doesn't call this (it uses the message-level delete below instead).

**Response 200:**
```json
{ "reaction_roles": [ "updated array" ] }
```

### `DELETE /api/guilds/{guild_id}/reactionroles/message/{message_id}`
Removes **all** mappings tied to that message, and best-effort deletes the actual Fluxer message (failure to delete the message is swallowed; mapping cleanup always proceeds).

**Response 200:**
```json
{ "reaction_roles": [ "updated array, with that message's mappings gone" ] }
```

---

## Roles / channels (picker data)

### `GET /api/guilds/{guild_id}/roles`
Live-fetched from Fluxer (not the local DB) via the bot's own credentials. Excludes `@everyone` (role ID equal to guild ID, Discord convention).

**Response 200:**
```json
{ "roles": [ { "id": "666", "name": "VIP", "color": 16711680 } ] }
```
`color` may be `0`/`null` for the default color.

**Errors:** 502 if Fluxer's guild fetch fails.

### `GET /api/guilds/{guild_id}/channels`
Live-fetched from Fluxer. Filtered to text-like channels (`type == 0` or missing `type`).

**Response 200:**
```json
{ "channels": [ { "id": "888", "name": "general" } ] }
```

---

## Members

### `GET /api/guilds/{guild_id}/members?q=searchterm`
`q` is optional, matches substring of username (case-insensitive) or exact user ID. Fetches up to 500 members from Fluxer per request (no true pagination), returns at most 100 after filtering.

**Response 200:**
```json
{
  "members": [
    { "id": "444", "username": "someone", "avatar": "a1b2c3", "roles": ["666"], "joined_at": "2024-01-01T00:00:00Z" }
  ]
}
```
`avatar` is the raw Fluxer avatar hash (or `null`), not a URL, the frontend doesn't currently render member avatars from this endpoint.

### `POST /api/guilds/{guild_id}/members/{user_id}/kick`
**Request body:** `{ "reason": "spam" }` (reason optional, defaults to `""`)

**Response 200:** `{ "ok": true }`

### `POST /api/guilds/{guild_id}/members/{user_id}/ban`
Same shape as kick.

### `POST /api/guilds/{guild_id}/members/{user_id}/timeout`
**Request body:**
```json
{ "reason": "cooldown", "duration_seconds": 600 }
```
`duration_seconds` defaults to `3600`, must be positive (400 otherwise).

**Response 200:** `{ "ok": true }`

### `POST /api/guilds/{guild_id}/members/{user_id}/untimeout`
**Request body:** `{ "reason": "" }`

**Response 200:** `{ "ok": true }`

### `POST /api/guilds/{guild_id}/members/{user_id}/warn`
**Request body:** `{ "reason": "spam" }`

**Response 200:**
```json
{
  "result": { "active_count": 3, "escalated": "timeout", "timeout_minutes": 60 },
  "warnings": [ "updated warnings array" ],
  "active_warning_count": 3
}
```
`result.escalated` is `null`, `"kick"`, or `"timeout"` depending on whether this warning crossed a threshold. All four member-action endpoints attribute the moderator as the **actual logged-in dashboard user** (from the session), not a generic "System" label, since they go through the same `bot/moderation_actions.py` functions the chat commands use.

**Errors (all 5 member-action endpoints):** 404 if the user isn't a member of the guild; 502 if Fluxer rejects the underlying action.

---

## Tags

### `POST /api/guilds/{guild_id}/tags`
**Request body:**
```json
{ "name": "rules", "content": "Read the pinned message." }
```
`name` is lowercased server-side. **Errors:** 400 if name/content empty, or if `name` collides with a real bot command name.

**Response 200:**
```json
{ "tags": [ "updated tags array" ] }
```

### `DELETE /api/guilds/{guild_id}/tags/{tag_name}`
No body. Silently succeeds even if the tag doesn't exist.

**Response 200:**
```json
{ "tags": [ "updated tags array" ] }
```

---

## Static frontend serving

Not really "API" but part of the same server:

- `GET /assets/*`, serves the built Vite bundle's hashed JS/CSS files as static files.
- `GET /{anything else}`, catch-all. Serves the matching static file if it exists in `dist/` (e.g. `/favicon.svg`), otherwise always serves `dist/index.html` so React Router can handle client-side routes like `/guild/123?tab=members` on a hard refresh.

If `dashboard-frontend/dist` doesn't exist (frontend never built), `GET /` instead returns a 503 with a message telling you to build it.

---

## Full endpoint list (quick reference)

| Method | Path | Auth |
|---|---|---|
| GET | `/login` | none |
| GET | `/auth/callback` | none |
| POST | `/api/logout` | session |
| GET | `/api/me` | none |
| GET | `/api/guilds` | login |
| GET | `/api/commands` | none |
| GET | `/api/guilds/{id}` | manage |
| POST | `/api/guilds/{id}/settings` | manage |
| POST | `/api/guilds/{id}/warnings/{user_id}/clear` | manage |
| POST | `/api/guilds/{id}/autoroles` | manage |
| DELETE | `/api/guilds/{id}/autoroles/{role_id}` | manage |
| POST | `/api/guilds/{id}/reactionroles` | manage |
| DELETE | `/api/guilds/{id}/reactionroles/{mapping_id}` | manage |
| DELETE | `/api/guilds/{id}/reactionroles/message/{message_id}` | manage |
| GET | `/api/guilds/{id}/roles` | manage |
| GET | `/api/guilds/{id}/channels` | manage |
| GET | `/api/guilds/{id}/members` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/kick` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/ban` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/timeout` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/untimeout` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/warn` | manage |
| POST | `/api/guilds/{id}/tags` | manage |
| DELETE | `/api/guilds/{id}/tags/{tag_name}` | manage |
| GET | `/assets/*` | none |
| GET | `/{anything}` | none (SPA catch-all) |

"manage" = logged in **and** live-verified Manage Server permission on that specific guild.
