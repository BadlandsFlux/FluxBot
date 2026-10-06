# FluxBot Dashboard API Reference

Every HTTP endpoint the React frontend (this directory) calls, generated directly from `dashboard/app.py` and `src/api.js`.

Useful as a porting checklist for a backend rewrite (e.g. to C#/ASP.NET): implement every route below with matching request/response shapes, and this frontend needs zero changes. It can also be reused as a standalone dashboard for another project, same way.

## Conventions

- All `/api/*` routes return JSON. Non-2xx responses return `{"detail": "human readable message"}`.
- Every `/api/guilds/{guild_id}/*` route requires an active session **and** live verification that the logged-in user has "Manage Server" permission (or owns) that guild, checked via `GET /users/@me/guilds` on the Fluxer API on every request. No caching, no separate allowlist.
- A few routes are **owner-only** instead (`/api/bot-profile/avatar`, `/api/discord-relay/config`): gated to whoever `BOT_OWNER_ID` in `.env` is set to, regardless of which guilds they manage.
- Auth is a signed session cookie (`SessionMiddleware`), not a bearer token, so every frontend `fetch` call uses `credentials: "include"`.
- IDs (guild/user/channel/role/message) are all strings, matching Fluxer's snowflake-as-string convention.

---

## Auth (not JSON, browser redirects)

### `GET /login`
No auth required. Redirects (302) to the Fluxer OAuth2 authorize URL. Sets `oauth_state` in the session for CSRF protection.

### `GET /auth/callback`
No auth required. OAuth2 redirect target. Query params: `code`, `state`, `error` (all optional, set by Fluxer's redirect).

- `error` present → redirect to `/?login_error={error}`
- `state` missing/mismatched → redirect to `/?login_error=state_mismatch`
- Success → exchanges `code` for an access token, fetches the user via `/users/@me`, stores `{user, access_token}` in the session, redirects to `/`
- Token/user fetch failure → redirect to `/?login_error=oauth_failed`

### `POST /api/logout`
No-op if not logged in. Clears the session. **Response:** `{ "ok": true }`

---

## Session / identity

### `GET /api/me`
No auth required (returns a null user if not logged in, not a 401).

```json
{ "user": { "id": "123", "username": "someone" }, "bot_name": "FluxBot", "is_owner": false }
```
`user` is whatever Fluxer's `/users/@me` returns, stored as-is. Logged out: `{ "user": null }`. `is_owner` is whether this user's id matches `BOT_OWNER_ID`.

---

## Guild list

### `GET /api/guilds`
Requires login. Returns only guilds where the bot is installed **and** the user has Manage Server.

```json
{ "guilds": [ { "id": "111", "name": "My Server", "icon_url": "https://.../icons/111/abcd.webp?size=128" } ] }
```
`icon_url` is `null` if the server has no custom icon. **Errors:** 401 if the Fluxer access token itself has expired (clears the session, distinct from "you manage zero servers").

---

## Commands catalog (public, powers `/commands`)

### `GET /api/commands`
No auth required. Built by actually registering every bot command module in-memory, so it can't drift from the real bot.

```json
{
  "default_prefix": "!",
  "categories": { "Moderation": [ { "name": "kick", "aliases": [], "help_text": "...", "permission": "Kick Members" } ] }
}
```
`permission` is a human-readable string: a Fluxer permission name, `"Everyone"`, or `"Owner only"`.

---

## Public status (powers `/status`)

### `GET /api/status`
No auth required.

```json
{
  "bot_online": true,
  "bot_uptime_seconds": 12345.6,
  "gateway_latency_ms": 42,
  "guild_count": 7,
  "dashboard_db_ok": true,
  "dashboard_db_latency_ms": 3
}
```
`bot_online` is false if the bot's last heartbeat is more than 60s old. Every `bot_*` field is `null` when offline. `dashboard_db_ok` reflects whether this dashboard process can reach Postgres right now, independent of the bot.

---

## Guild detail (the main dashboard payload)

### `GET /api/guilds/{guild_id}`
```json
{
  "guild": { "guild_id": "111", "name": "My Server", "command_prefix": "!", "...": "see Settings below for every field" },
  "actions": [ { "id": 1, "user_id": "444", "username": "someone", "moderator_id": "555", "moderator_username": "mod", "action": "kick", "reason": "spam", "created_at": "2026-07-03T12:00:00+00:00" } ],
  "warnings": [ { "id": 1, "user_id": "444", "username": "someone", "moderator_id": "555", "moderator_username": "mod", "reason": "spam", "active": true, "created_at": "..." } ],
  "autoroles": ["666", "777"],
  "reaction_roles": [ { "id": 1, "channel_id": "888", "message_id": "999", "emoji": "🎉", "role_id": "666", "label": "VIP" } ],
  "tags": [ { "id": 1, "name": "rules", "content": "Read the pins.", "created_by": "555", "created_at": "..." } ],
  "reports": [ { "id": 1, "reporter_id": "444", "reporter_username": "someone", "content": "...", "visibility": "public", "status": "open", "duplicate_of": null, "possible_duplicate_of": null, "resolution_note": null, "created_at": "...", "updated_at": "...", "reply_count": 2, "needs_staff_reply": true } ],
  "active_warning_count": 1,
  "open_report_count": 1
}
```
**Errors:** 404 if the bot isn't in that guild. `actions` is capped at 50 most recent and `reports` at 100 (see the "Load more" endpoints just below for paging past either). `autoroles` is a flat array of role ID strings. A `private` report's `reporter_id`/`reporter_username` are `null`.

---

## Mod log (load more)

### `GET /api/guilds/{guild_id}/actions?before_id=123&limit=50`
Pages past the first 50 actions guild detail already embeds. `before_id` (optional) is the `id` of the oldest action already shown, not an `OFFSET`, so a new action landing at the top mid-pagination can't shift or duplicate a page that's already been fetched. `limit` is clamped to 1-100.
```json
{ "actions": [ "same shape as guild detail's actions array" ], "has_more": true }
```

---

## Settings

### `POST /api/guilds/{guild_id}/settings`
```json
{
  "log_channel_id": "222", "mute_role_id": "", "command_prefix": "!",
  "welcome_channel_id": "333", "welcome_message": "Welcome {user} to {server}! 👋",
  "goodbye_channel_id": "", "goodbye_message": "{username} left {server}. 👋",
  "leveling_enabled": true, "level_up_channel_id": "", "level_up_message": "GG {user}, you reached level {level}! 🎉",
  "warn_timeout_at": 3, "warn_kick_at": 5, "warn_timeout_minutes": 60,
  "report_channel_id": "", "report_tracker_channel_id": ""
}
```
Every field has a default (the frontend always sends the full object). An empty string for a `*_channel_id`/`mute_role_id` field means "unset" (stored as `NULL`). `command_prefix` is truncated server-side to 5 chars, falls back to `"!"` if empty. Setting `report_channel_id` to a new value also posts a one-time explainer embed into that channel. Whichever fields actually changed (diffed against the row before the save, so resubmitting the form unchanged logs nothing) get written to Mod Log as a `settings_update` action, naming just those fields, e.g. `Changed: warn-timeout threshold, mute role`.

**Response:** `{ "guild": { "...": "same shape as the guild object in guild detail, updated" } }`

---

## Warnings

### `POST /api/guilds/{guild_id}/warnings/{user_id}/clear`
No body.
```json
{ "cleared": 2, "warnings": [ "full updated warnings array" ], "active_warning_count": 0 }
```

---

## Autoroles

### `POST /api/guilds/{guild_id}/autoroles`
`{ "role_id": "666" }` → `{ "autoroles": ["666", "777"] }`
**Errors:** 400 if `role_id` isn't numeric, or if that role carries moderation/admin permissions (blocked as a privilege-escalation path, not just discouraged).

### `DELETE /api/guilds/{guild_id}/autoroles/{role_id}`
No body. → `{ "autoroles": ["777"] }`

---

## Reaction roles

### `POST /api/guilds/{guild_id}/reactionroles`
Sends a real embed message to the target channel (as the bot), reacts to it with each emoji, and stores the mappings.
```json
{
  "channel_id": "888", "title": "Pick your roles", "description": "React below to opt in", "color": "5865F2",
  "pairs": [ { "emoji": "🎉", "label": "VIP", "role_id": "666" }, { "emoji": "🎮", "label": "Gamer", "role_id": "777" } ]
}
```
`color` is hex, `#` optional, defaults to `5865F2`. `pairs[].label` is optional. The embed never includes the role itself (no `<@&role_id>` mention), only the emoji and, if given, the label, the role is purely an internal mapping. **Errors:** 400 if `channel_id` isn't numeric, no valid pairs given, or any paired role carries moderation/admin permissions; 502 if the bot couldn't send the message at all.

```json
{ "reaction_roles": [ "full updated array" ], "failed_reactions": ["🎮"] }
```
`failed_reactions` lists any emoji that failed to auto-react (mapping is still saved; needs a manual reaction). Each entry in `reaction_roles` also carries that message's `title`/`description`/`color` (duplicated onto every row for the same `message_id`), not just the one emoji/role/label it represents.

### `PATCH /api/guilds/{guild_id}/reactionroles/message/{message_id}`
Edits an existing message in place: same body shape as create (`channel_id` is accepted but ignored, the channel can't change here). Edits the live embed via Fluxer's message-edit endpoint, reconciles reactions (adds new emoji, removes the bot's own reaction for any dropped), and updates the stored mappings and embed text to match. **Errors:** 404 if that message has no mappings (anymore); 400 same as create; 502 if Fluxer rejects the edit (the message may have been deleted, try resend instead). → same shape as create.

### `POST /api/guilds/{guild_id}/reactionroles/message/{message_id}/resend`
Posts a brand new message with the same embed and mappings an existing one has, re-reacts to it, then moves the mappings over to the new message id (and best-effort deletes the old message). No body. Mainly for when the original message was deleted and reacting to it is no longer possible at all. **Errors:** 404 if that message has no mappings (anymore); 502 if the bot couldn't post the new message. → same shape as create.

### `DELETE /api/guilds/{guild_id}/reactionroles/{mapping_id}`
Removes one emoji/role mapping, not the message or its other mappings. Kept for API completeness; the UI uses the message-level delete below instead. → `{ "reaction_roles": [ "updated array" ] }`

### `DELETE /api/guilds/{guild_id}/reactionroles/message/{message_id}`
Removes **all** mappings tied to that message, and best-effort deletes the actual Fluxer message. → `{ "reaction_roles": [ "updated array, that message's mappings gone" ] }`

---

## Reports

### `POST /api/guilds/{guild_id}/reports/channels`
A narrower alternative to the full Settings form, so the Reports tab can set just these two without risking a reset of everything else. Logs a `settings_update` Mod Log entry the same way Settings does, only when a channel actually changed.
```json
{ "report_channel_id": "222", "report_tracker_channel_id": "333" }
```
**Response:** `{ "guild": { "...": "same shape as Settings' response" } }`

### `POST /api/guilds/{guild_id}/reports/{report_id}/status`
```json
{ "status": "resolved", "duplicate_of": null, "note": "Fixed in the next patch." }
```
`status` is one of `open` / `duplicate` / `resolved` / `wontfix`. `duplicate_of` (a report id) is required when `status` is `"duplicate"`. **Errors:** 400 on an unknown status, a missing/self-referential/nonexistent `duplicate_of`.

**Response:** `{ "reports": [ "full updated reports array, same shape as guild detail" ] }`

### `GET /api/guilds/{guild_id}/reports/{report_id}`
Backs the per-report detail page (a GitHub-issue-style view for the report's full two-way conversation with its reporter).
```json
{
  "report": { "id": 1, "...": "same shape as guild detail's reports array" },
  "replies": [ { "id": 1, "author_type": "staff", "author_id": "555", "author_username": "mod", "content": "Can you share more details?", "created_at": "..." } ]
}
```
`author_type` is `"staff"` or `"reporter"` (a third internal `"system"` type exists in storage for DM-reply matching but is never returned here). On a `private` report, a `"reporter"`-authored reply's `author_id`/`author_username` are `null`, same privacy guarantee as the report itself. **Errors:** 404 if the report doesn't exist in this guild.

### `POST /api/guilds/{guild_id}/reports/{report_id}/replies`
Sends a reply to the reporter by DM (mirrored into the tracker channel too) and records it in the thread.
```json
{ "content": "Can you share more details?" }
```
**Errors:** 400 if `content` is empty; 400/404 via the same report-lookup errors as the status endpoint.

**Response:** same shape as the GET above, plus `"delivered": true`, whether the DM actually reached the reporter (still recorded either way, e.g. if they have DMs closed).

### `GET /api/guilds/{guild_id}/reports/list?before_id=123&limit=50&status=open`
"Load more" for the Reports tab, same `before_id` cursor as the Mod Log one above (not `/reports`, which is reserved for `/reports/{report_id}`'s own GET). `status` is optional, same four values as the status endpoint.
```json
{ "reports": [ "same shape as guild detail's reports array" ], "has_more": true }
```

---

## Roles / channels (picker data)

### `GET /api/guilds/{guild_id}/roles`
Live-fetched from Fluxer via the bot's own credentials. Excludes `@everyone` (role ID equal to guild ID).
```json
{ "roles": [ { "id": "666", "name": "VIP", "color": 16711680 } ] }
```
`color` may be `0`/`null` for the default color. **Errors:** 502 if Fluxer's guild fetch fails.

### `GET /api/guilds/{guild_id}/channels`
Live-fetched from Fluxer. Filtered to text-like channels (`type == 0` or missing).
```json
{ "channels": [ { "id": "888", "name": "general" } ] }
```

---

## Members

### `GET /api/guilds/{guild_id}/members?q=searchterm&offset=0&limit=100`
`q` is optional: substring of username (case-insensitive) or exact user ID. Fetches up to 500 members from Fluxer per request and filters in memory; `offset`/`limit` (limit clamped to 1-200, default 100) page through that same filtered, up-to-500 slice for "Load more", not a real cursor into Fluxer's own member list.
```json
{
  "members": [ { "id": "444", "username": "someone", "avatar": "a1b2c3", "avatar_url": "https://.../avatars/444/a1b2c3.webp?size=64", "roles": ["666"], "joined_at": "2024-01-01T00:00:00Z", "message_count": 231 } ],
  "has_more": true
}
```
`avatar` is the raw Fluxer avatar hash (or `null`), not a URL; `avatar_url` is the ready-to-use image URL built from it (also `null` when there's no avatar). `message_count` is this guild's own tracked total.

### `POST /api/guilds/{guild_id}/members/{user_id}/kick`
`{ "reason": "spam" }` (optional, defaults to `""`) → `{ "ok": true }`

### `POST /api/guilds/{guild_id}/members/{user_id}/ban`
Same shape as kick.

### `POST /api/guilds/{guild_id}/members/{user_id}/timeout`
```json
{ "reason": "cooldown", "duration_seconds": 600 }
```
`duration_seconds` defaults to `3600`, must be positive. → `{ "ok": true }`

### `POST /api/guilds/{guild_id}/members/{user_id}/untimeout`
`{ "reason": "" }` → `{ "ok": true }`

### `POST /api/guilds/{guild_id}/members/{user_id}/warn`
`{ "reason": "spam" }`
```json
{ "result": { "active_count": 3, "escalated": "timeout", "timeout_minutes": 60 }, "warnings": [ "updated array" ], "active_warning_count": 3 }
```
`result.escalated` is `null`, `"kick"`, or `"timeout"`. All five member-action endpoints attribute the moderator as the actual logged-in dashboard user, going through the same `bot/moderation_actions.py` functions the chat commands use.

**Errors (all five):** 404 if the user isn't a member; 403 if the action is blocked (targeting yourself, the owner, or someone whose highest role outranks or ties yours); 502 if Fluxer rejects the action.

---

## Staff notes

### `GET /api/guilds/{guild_id}/members/{user_id}/notes`
```json
{ "notes": [ { "id": 1, "user_id": "444", "note": "Known to post late at night, be lenient", "created_by": "555", "created_at": "..." } ] }
```

### `POST /api/guilds/{guild_id}/members/{user_id}/notes`
`{ "note": "..." }` → same shape as GET, updated. **Errors:** 400 if empty.

### `DELETE /api/guilds/{guild_id}/members/{user_id}/notes/{note_id}`
No body. → same shape as GET, updated.

---

## Tags

### `POST /api/guilds/{guild_id}/tags`
`{ "name": "rules", "content": "Read the pinned message." }`. `name` is lowercased server-side. **Errors:** 400 if name/content empty, or `name` collides with a real command name.
→ `{ "tags": [ "updated array" ] }`

### `DELETE /api/guilds/{guild_id}/tags/{tag_name}`
No body. Silently succeeds even if the tag doesn't exist. → `{ "tags": [ "updated array" ] }`

---

## Stats (powers the Overview tab's charts)

### `GET /api/guilds/{guild_id}/stats?days=14`
`days` is clamped to 1-90.
```json
{
  "daily": [ { "date": "2026-07-03", "count": 120, "voice_minutes": 45 } ],
  "top_members": [ { "user_id": "444", "username": "someone", "count": 80 } ],
  "top_voice_members": [ { "user_id": "444", "username": "someone", "minutes": 300 } ],
  "total_messages_30d": 3400,
  "top_commands": [ { "name": "rank", "count": 50 } ],
  "heatmap": [ { "day": 0, "hour": 14, "count": 12 } ]
}
```
`heatmap.day` follows `EXTRACT(DOW ...)`/JS `Date#getDay()` convention: 0 = Sunday … 6 = Saturday, so the frontend indexes straight into it.

---

## Leveling

### `GET /api/guilds/{guild_id}/levels`
```json
{
  "leaderboard": [ { "user_id": "444", "username": "someone", "xp": 1200, "level": 5 } ],
  "level_roles": [ { "id": 1, "level": 5, "role_id": "666" } ],
  "excluded_channels": ["999"],
  "role_multipliers": [ { "role_id": "777", "multiplier": 1.5 } ]
}
```
`leaderboard` is capped at 20.

### `POST /api/guilds/{guild_id}/level-roles`
`{ "level": 5, "role_id": "666" }`. **Errors:** 400 if `level < 1` or the role carries moderation/admin permissions. → `{ "level_roles": [ "updated array" ] }`

### `DELETE /api/guilds/{guild_id}/level-roles/{level}`
No body. → `{ "level_roles": [ "updated array" ] }`

### `POST /api/guilds/{guild_id}/levels/excluded-channels`
`{ "channel_id": "999" }` → `{ "excluded_channels": [ "updated array" ] }`

### `DELETE /api/guilds/{guild_id}/levels/excluded-channels/{channel_id}`
No body. → `{ "excluded_channels": [ "updated array" ] }`

### `POST /api/guilds/{guild_id}/levels/multipliers`
`{ "role_id": "777", "multiplier": 1.5 }`. **Errors:** 400 if `multiplier` isn't in `(0, 10]`. → `{ "role_multipliers": [ "updated array" ] }`

### `DELETE /api/guilds/{guild_id}/levels/multipliers/{role_id}`
No body. → `{ "role_multipliers": [ "updated array" ] }`

### `POST /api/guilds/{guild_id}/levels/{user_id}/reset`
No body. Resets that member's XP/level to zero, logs a `xp_reset` mod action. → `{ "leaderboard": [ "updated array" ] }`

### `POST /api/guilds/{guild_id}/levels/{user_id}/adjust`
`{ "amount": 100 }` (negative to remove). **Errors:** 400 if `amount == 0`. Logs an `xp_adjust` mod action. → `{ "leaderboard": [ "updated array" ] }`

---

## Activity log

### `GET /api/guilds/{guild_id}/activity-log`
```json
{
  "log_channel_id": "222", "log_message_edits": false, "log_message_deletes": false,
  "log_member_joins": false, "log_member_leaves": false, "log_channel_changes": false,
  "log_role_changes": false, "log_voice_activity": false, "log_privileged_role_changes": false,
  "ignored_users": ["444"]
}
```
Everything defaults to `false`/unset until configured.

### `POST /api/guilds/{guild_id}/activity-log`
Same shape as the GET response, minus `ignored_users`. → the GET shape, updated. Logs a `settings_update` Mod Log entry listing whichever toggles/channel actually changed (a first-time setup, going from completely unconfigured, reads as every field having changed).

### `POST /api/guilds/{guild_id}/activity-log/ignored-users`
`{ "user_id": "444" }`. **Errors:** 400 if not numeric. → the GET shape, updated.

### `DELETE /api/guilds/{guild_id}/activity-log/ignored-users/{user_id}`
No body. → the GET shape, updated.

---

## Discord relay

### `GET /api/guilds/{guild_id}/discord-relay`
```json
{
  "mappings": [ { "id": 1, "discord_channel_id": "aaa", "fluxer_channel_id": "888", "direction": "both", "enabled": true, "show_attribution": true, "created_by": "555", "created_at": "..." } ],
  "relay_configured": true,
  "relay_status": { "connected": true, "discord_username": "FluxBot#1234" },
  "invite_url": "https://discord.com/api/oauth2/authorize?client_id=...&permissions=...&scope=bot"
}
```
`direction` is one of `discord_to_fluxer` / `fluxer_to_discord` / `both`. `relay_status`/`invite_url` are `null` until the relay bot has connected at least once.

### `POST /api/guilds/{guild_id}/discord-relay`
```json
{ "discord_channel_id": "aaa", "fluxer_channel_id": "888", "direction": "discord_to_fluxer", "show_attribution": true }
```
**Errors:** 400 if either ID isn't numeric or `direction` is invalid; 409 on a duplicate mapping. → `{ "mappings": [ "updated array" ] }`

### `DELETE /api/guilds/{guild_id}/discord-relay/{mapping_id}`
No body. → `{ "mappings": [ "updated array" ] }`

### `POST /api/guilds/{guild_id}/discord-relay/{mapping_id}/toggle`
`{ "enabled": false }` → `{ "mappings": [ "updated array" ] }`

### `POST /api/guilds/{guild_id}/discord-relay/{mapping_id}/test`
No body. Sends a test message directly to whichever channel(s) the mapping targets, bypassing the relay's own event handling, not a full round-trip through live relay logic.
```json
{ "results": { "fluxer": "sent", "discord": "failed (HTTP 403), check the bot is actually in that server with permission to post there" } }
```
Only includes the `fluxer`/`discord` key relevant to the mapping's direction. **Errors:** 404 if the mapping doesn't exist for this guild.

### `GET /api/discord-relay/config`
**Owner-only, bot-wide** (not scoped to one guild).
```json
{
  "token_configured": true, "token_source": "dashboard",
  "status": { "connected": true, "discord_username": "FluxBot#1234", "last_connected_at": "...", "last_error": null, "last_error_at": null }
}
```
`token_source` is `"dashboard"`, `"env"`, or `null`. The token value itself is never returned. `status` is `null` if nothing's ever been configured.

### `POST /api/discord-relay/config`
**Owner-only.** `{ "token": "..." }` (empty string clears it, dashboard-set token takes precedence over `DISCORD_BOT_TOKEN` in `.env`). → `{ "ok": true }`

---

## Embed

### `POST /api/guilds/{guild_id}/embed`
```json
{
  "channel_id": "888", "title": "Heads up", "url": "", "description": "Server maintenance tonight.",
  "color": "5865F2", "image_url": "", "thumbnail_url": "", "footer": "",
  "author_name": "", "author_icon_url": "", "author_url": "", "timestamp": false,
  "fields": [{ "name": "Starts", "value": "10pm EST", "inline": true }]
}
```
Every field beyond `channel_id` is optional. `fields` is capped at 25 entries (256 chars for `name`, 1024 for `value`), matching Discord/Fluxer's own embed limits. A field with only one of `name`/`value` filled in is a 400; one with both blank is silently dropped.

**Errors:** 400 if `channel_id` isn't numeric, both `title`/`description` are empty, or a `fields` entry is invalid; 502 if Fluxer rejects the message. Logs a `send_embed` mod action. → `{ "ok": true }`

---

## Danger zone

Each of these is a bulk, irreversible, guild-wide action. The frontend gates them behind typing "CONFIRM"; the API itself does not.

### `POST /api/guilds/{guild_id}/danger/clear-all-warnings`
No body. → `{ "cleared": 12 }`

### `POST /api/guilds/{guild_id}/danger/reset-all-xp`
No body. → `{ "reset": 340 }`

### `POST /api/guilds/{guild_id}/danger/wipe-reaction-roles`
No body. → `{ "wiped": 6, "reaction_roles": [] }`

---

## Bot profile (owner-only, bot-wide)

### `POST /api/bot-profile/avatar`
Multipart form upload, field name `file`. PNG/JPEG/WEBP only, 8 MiB max.
```json
{ "ok": true, "fluxer_updated": true, "fluxer_error": null }
```
The dashboard's own favicon/top-bar icon always updates once the image is valid. Setting the bot's actual Fluxer avatar is attempted separately and best-effort (some instances reject it); `fluxer_updated`/`fluxer_error` report that outcome independently of the favicon succeeding. **Errors:** 400 on a bad content type, empty file, or over the size cap.

### `GET /favicon.ico` / `GET /api/bot-profile/icon`
No auth required. Both serve the same uploaded image (falling back to a static default if nothing's been set), just for two different spots in the UI (the browser tab, and the dashboard's own top bar).

---

## Discord relay avatar proxy

### `GET /api/discord-relay/avatar-proxy?url=...`
No auth required. Re-serves an avatar image from Discord's CDN so it can be shown in the dashboard without a browser-side CORS issue. `url` must be `https://cdn.discordapp.com/...` or `https://media.discordapp.net/...`, anything else is rejected, this is a strict allowlist, not an open proxy (an open one would be a real SSRF vector on a public-facing service). **Errors:** 400 for a disallowed host, 502 if Discord's CDN doesn't return 200.

---

## Static frontend serving

Not really "API," but part of the same server:

- `GET /assets/*`, serves the built Vite bundle's hashed JS/CSS files.
- `GET /{anything else}`, catch-all: serves the matching static file if it exists in `dist/`, otherwise always serves `dist/index.html` so React Router can handle client-side routes (e.g. `/guild/123?tab=members`) on a hard refresh.

If `dashboard-frontend/dist` doesn't exist (frontend never built), `GET /` returns a 503 telling you to build it.

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
| GET | `/api/status` | none |
| GET | `/api/guilds/{id}` | manage |
| GET | `/api/guilds/{id}/actions` | manage |
| POST | `/api/guilds/{id}/settings` | manage |
| POST | `/api/guilds/{id}/warnings/{user_id}/clear` | manage |
| POST | `/api/guilds/{id}/autoroles` | manage |
| DELETE | `/api/guilds/{id}/autoroles/{role_id}` | manage |
| POST | `/api/guilds/{id}/reactionroles` | manage |
| PATCH | `/api/guilds/{id}/reactionroles/message/{message_id}` | manage |
| POST | `/api/guilds/{id}/reactionroles/message/{message_id}/resend` | manage |
| DELETE | `/api/guilds/{id}/reactionroles/{mapping_id}` | manage |
| DELETE | `/api/guilds/{id}/reactionroles/message/{message_id}` | manage |
| POST | `/api/guilds/{id}/reports/channels` | manage |
| POST | `/api/guilds/{id}/reports/{report_id}/status` | manage |
| GET | `/api/guilds/{id}/reports/{report_id}` | manage |
| POST | `/api/guilds/{id}/reports/{report_id}/replies` | manage |
| GET | `/api/guilds/{id}/reports/list` | manage |
| GET | `/api/guilds/{id}/roles` | manage |
| GET | `/api/guilds/{id}/channels` | manage |
| GET | `/api/guilds/{id}/members` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/kick` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/ban` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/timeout` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/untimeout` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/warn` | manage |
| GET | `/api/guilds/{id}/members/{user_id}/notes` | manage |
| POST | `/api/guilds/{id}/members/{user_id}/notes` | manage |
| DELETE | `/api/guilds/{id}/members/{user_id}/notes/{note_id}` | manage |
| POST | `/api/guilds/{id}/tags` | manage |
| DELETE | `/api/guilds/{id}/tags/{tag_name}` | manage |
| GET | `/api/guilds/{id}/stats` | manage |
| GET | `/api/guilds/{id}/levels` | manage |
| POST | `/api/guilds/{id}/level-roles` | manage |
| DELETE | `/api/guilds/{id}/level-roles/{level}` | manage |
| POST | `/api/guilds/{id}/levels/excluded-channels` | manage |
| DELETE | `/api/guilds/{id}/levels/excluded-channels/{channel_id}` | manage |
| POST | `/api/guilds/{id}/levels/multipliers` | manage |
| DELETE | `/api/guilds/{id}/levels/multipliers/{role_id}` | manage |
| POST | `/api/guilds/{id}/levels/{user_id}/reset` | manage |
| POST | `/api/guilds/{id}/levels/{user_id}/adjust` | manage |
| GET | `/api/guilds/{id}/activity-log` | manage |
| POST | `/api/guilds/{id}/activity-log` | manage |
| POST | `/api/guilds/{id}/activity-log/ignored-users` | manage |
| DELETE | `/api/guilds/{id}/activity-log/ignored-users/{user_id}` | manage |
| GET | `/api/guilds/{id}/discord-relay` | manage |
| POST | `/api/guilds/{id}/discord-relay` | manage |
| DELETE | `/api/guilds/{id}/discord-relay/{mapping_id}` | manage |
| POST | `/api/guilds/{id}/discord-relay/{mapping_id}/toggle` | manage |
| POST | `/api/guilds/{id}/discord-relay/{mapping_id}/test` | manage |
| GET | `/api/discord-relay/config` | owner |
| POST | `/api/discord-relay/config` | owner |
| GET | `/api/discord-relay/avatar-proxy` | none |
| POST | `/api/guilds/{id}/embed` | manage |
| POST | `/api/guilds/{id}/danger/clear-all-warnings` | manage |
| POST | `/api/guilds/{id}/danger/reset-all-xp` | manage |
| POST | `/api/guilds/{id}/danger/wipe-reaction-roles` | manage |
| POST | `/api/bot-profile/avatar` | owner |
| GET | `/favicon.ico` | none |
| GET | `/api/bot-profile/icon` | none |
| GET | `/assets/*` | none |
| GET | `/{anything}` | none (SPA catch-all) |

"manage" = logged in **and** live-verified Manage Server permission on that specific guild. "owner" = logged in as whoever `BOT_OWNER_ID` is set to, bot-wide.
