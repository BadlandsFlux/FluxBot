from __future__ import annotations

import asyncio
import base64
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from bot import moderation_actions
from bot import report_actions
from bot.bounded_cache import BoundedDict
from bot.moderation_actions import ModerationBlocked
from bot import fluxer_patch_notes, voice_tracker
from bot.commands import Bot as BotFramework, NEVER_DISABLED_COMMANDS
from bot.discord_relay import INVITE_PERMISSIONS as DISCORD_RELAY_INVITE_PERMISSIONS
from bot.modules import account_links, achievements, command_toggles, fun, info as info_module, leveling, moderation, mydata, reminders, reports, roles, staffnotes, tags, trivia, utility
from bot.modules import afk as afk_module
from bot.permissions import permission_name, role_is_privileged
from bot.rest import FluxerAPIError, FluxerREST
from common.url_safety import is_safe_external_url
from common import db, fluxer_admin
from common.config import config
from common.discovery import emoji_url, get_media_base, guild_icon_url, user_avatar_url
from dashboard import oauth

log = logging.getLogger("fluxbot.dashboard")

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = BASE_DIR.parent / "dashboard-frontend" / "dist"

# A REST client authenticated as the bot itself, used for dashboard actions
# that need to act *as* the bot (sending the reaction-role embed message,
# reacting to it). This talks to Fluxer over plain HTTP; it doesn't need the
# bot's gateway connection, so it works whether or not the bot process is
# currently running.
bot_rest = FluxerREST(config.bot_token)


def _build_command_catalog() -> list:
    """Build the command list by actually registering every command module
    against a throwaway Bot instance, so /api/commands can never drift from
    what the bot really responds to. No network calls happen here; Bot() and
    command registration are both purely in-memory."""
    catalog_bot = BotFramework("catalog-builder-unused-token")
    moderation.register(catalog_bot)
    roles.register(catalog_bot)
    fun.register(catalog_bot)
    utility.register(catalog_bot)
    info_module.register(catalog_bot)
    tags.register(catalog_bot)
    reminders.register(catalog_bot)
    leveling.register(catalog_bot)
    voice_tracker.register(catalog_bot)
    achievements.register(catalog_bot)
    trivia.register(catalog_bot)
    afk_module.register(catalog_bot)
    staffnotes.register(catalog_bot)
    mydata.register(catalog_bot)
    account_links.register(catalog_bot)
    reports.register(catalog_bot)
    command_toggles.register(catalog_bot)
    seen = set()
    commands = []
    for cmd in catalog_bot.commands.values():
        if cmd.name in seen:
            continue
        seen.add(cmd.name)
        commands.append(cmd)
    return sorted(commands, key=lambda c: (c.category, c.name))


COMMAND_CATALOG = _build_command_catalog()

# Every registered name AND alias resolves to its Command, so looking up a
# per-guild toggle by whichever name an admin typed or clicked always lands
# on the same canonical cmd.name the bot's own dispatcher disables.
_COMMANDS_BY_NAME = {}
for _cmd in COMMAND_CATALOG:
    _COMMANDS_BY_NAME[_cmd.name] = _cmd
    for _alias in _cmd.aliases:
        _COMMANDS_BY_NAME[_alias] = _cmd


_KNOWN_PLACEHOLDER_SECRETS = {"dev-secret-change-me", "change_me_to_a_long_random_string"}


def _check_session_secret() -> None:
    secret = config.session_secret
    if secret in _KNOWN_PLACEHOLDER_SECRETS or len(secret) < 16:
        raise SystemExit(
            "DASHBOARD_SESSION_SECRET is missing or still set to a placeholder value. "
            "This key signs login sessions, since this project is open source, anyone "
            "can see the placeholder values and forge sessions if you leave one in place. "
            "Set DASHBOARD_SESSION_SECRET in .env to a long random string, e.g.: "
            "python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )


def _check_network_exposure() -> None:
    """Not fatal, unlike the session-secret check: DASHBOARD_HOST=0.0.0.0
    with DASHBOARD_COOKIE_SECURE=false might be a deliberate, understood
    choice (quick LAN testing before TLS is set up), not necessarily a
    mistake. But it's exactly the combination that sends the session
    cookie in plaintext to whoever can reach the dashboard over the
    network, so it's worth a loud warning rather than a silent footgun."""
    if config.dashboard_host not in ("127.0.0.1", "localhost", "::1") and not config.dashboard_cookie_secure:
        log.warning(
            "DASHBOARD_HOST=%s (reachable from the network) but DASHBOARD_COOKIE_SECURE is not "
            "enabled. The login session cookie will be sent in plaintext to anyone who can reach "
            "this dashboard, not just you. If you're not behind TLS/nginx yet, either set "
            "DASHBOARD_HOST=127.0.0.1 until you are, or set DASHBOARD_COOKIE_SECURE=true once you "
            "actually are. See the README's \"Reverse proxy (nginx)\" section.",
            config.dashboard_host,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_session_secret()
    _check_network_exposure()
    await db.init_pool()
    await bot_rest.start()
    yield
    await bot_rest.close()
    await db.close_pool()


app = FastAPI(title=f"{config.bot_name} Dashboard", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.session_secret, same_site="lax",
                    https_only=config.dashboard_cookie_secure)
# The built frontend is served same-origin (see the catch-all route below),
# so this CORS entry only matters if you run `npm run dev` (Vite on 5173)
# against this API directly during frontend development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_user(request: Request) -> Optional[dict]:
    return request.session.get("user")


class _ApiError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


@app.exception_handler(_ApiError)
async def _handle_api_error(request: Request, exc: _ApiError):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def require_login(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise _ApiError(401, "Not logged in.")
    return user


async def _require_manage(request: Request, guild_id: str) -> None:
    access_token = request.session.get("access_token")
    if not access_token:
        raise _ApiError(401, "Not logged in.")
    try:
        my_guilds = await oauth.fetch_my_guilds(access_token)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 401:
            request.session.clear()
            raise _ApiError(401, "Your session has expired, please log in again.")
        raise _ApiError(502, "Couldn't verify your Fluxer permissions right now.")
    entry = next((g for g in my_guilds if str(g.get("id")) == guild_id), None)
    if not entry or not oauth.can_manage(entry):
        raise _ApiError(403, "You don't have permission to manage this server.")


def _is_owner(user: Optional[dict]) -> bool:
    return bool(user and config.owner_id and str(user.get("id")) == config.owner_id)


def _require_owner(request: Request) -> dict:
    """Bot-wide settings (the avatar, elsewhere anything else that isn't
    scoped to one server) are gated to whoever BOT_OWNER_ID is configured
    as, not just anyone who happens to manage some server the bot is in."""
    user = require_login(request)
    if not _is_owner(user):
        raise _ApiError(403, "This is restricted to the bot owner.")
    return user


# -------------------------------------------------------------------- auth --
@app.get("/login")
async def login(request: Request):
    state = oauth.new_state()
    request.session["oauth_state"] = state
    return RedirectResponse(oauth.build_authorize_url(state))


@app.get("/auth/callback")
async def auth_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None,
                         error: Optional[str] = None):
    if error:
        # error is whatever the OAuth provider (or anyone who crafts their
        # own link to this endpoint) puts in the query string, reflecting
        # it straight into the redirect is exactly the kind of "uncontrolled
        # data" CodeQL's URL-redirection query flags, and is needless
        # besides: the frontend only ever shows one of a few fixed messages
        # anyway (see Login.jsx's ERROR_MESSAGES), never the raw value.
        log.info("OAuth provider returned an error on callback: %s", error)
        return RedirectResponse("/?login_error=provider_error")
    expected_state = request.session.pop("oauth_state", None)
    if not code or not state or state != expected_state:
        return RedirectResponse("/?login_error=state_mismatch")
    try:
        token_data = await oauth.exchange_code(code)
        access_token = token_data["access_token"]
        me = await oauth.fetch_me(access_token)
    except httpx.HTTPStatusError as e:
        log.warning("OAuth exchange failed: %s", e)
        return RedirectResponse("/?login_error=oauth_failed")
    request.session["user"] = me
    request.session["access_token"] = access_token
    return RedirectResponse("/")


@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


# --------------------------------------------------------------------- api --
@app.get("/api/me")
async def api_me(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"user": None}, status_code=200)
    return {"user": user, "bot_name": config.bot_name, "is_owner": _is_owner(user)}


@app.get("/api/guilds")
async def api_guilds(request: Request):
    require_login(request)
    access_token = request.session.get("access_token")
    try:
        my_guilds = await oauth.fetch_my_guilds(access_token)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 401:
            # The Fluxer access token itself has expired or been revoked
            # (the local session cookie can easily still look "logged in"
            # long after that happens, since it isn't re-validated against
            # Fluxer on every page load, only when something actually
            # needs the token). Previously this fell through to an empty
            # guild list, indistinguishable from "you genuinely manage
            # zero servers", leaving someone stuck on a confusing "No
            # manageable servers found" page with no indication they
            # just need to log back in. Clearing the session here and
            # returning 401 lets the frontend tell those two situations
            # apart and prompt a fresh login instead.
            request.session.clear()
            raise _ApiError(401, "Your session has expired, please log in again.")
        raise _ApiError(502, "Couldn't load your servers from Fluxer right now, try again in a moment.")

    bot_guild_ids = {g["guild_id"] for g in await db.list_guilds()}
    manageable = [g for g in my_guilds if str(g.get("id")) in bot_guild_ids and oauth.can_manage(g)]

    media_base = await get_media_base()
    result = []
    for g in manageable:
        result.append({
            "id": str(g.get("id")),
            "name": g.get("name"),
            "icon_url": guild_icon_url(media_base, str(g.get("id")), g.get("icon")),
        })
    return {"guilds": result}


@app.get("/api/commands")
async def api_commands():
    by_category: dict[str, list] = {}
    for cmd in COMMAND_CATALOG:
        by_category.setdefault(cmd.category, []).append({
            "name": cmd.name,
            "aliases": cmd.aliases,
            "help_text": cmd.help_text,
            "permission": "Owner only" if cmd.owner_only else permission_name(cmd.required_permission),
        })
    return {"default_prefix": config.command_prefix, "categories": by_category}


@app.get("/api/guilds/{guild_id}/commands")
async def api_guild_commands(request: Request, guild_id: str):
    await _require_manage(request, guild_id)
    disabled = set(await db.list_disabled_commands(guild_id))
    by_category: dict[str, list] = {}
    for cmd in COMMAND_CATALOG:
        by_category.setdefault(cmd.category, []).append({
            "name": cmd.name,
            "aliases": cmd.aliases,
            "help_text": cmd.help_text,
            "permission": "Owner only" if cmd.owner_only else permission_name(cmd.required_permission),
            "enabled": cmd.name not in disabled,
            "locked": cmd.owner_only or cmd.name in NEVER_DISABLED_COMMANDS,
        })
    return {"categories": by_category}


@app.post("/api/guilds/{guild_id}/commands/{command_name}/disable")
async def api_disable_command(request: Request, guild_id: str, command_name: str):
    await _require_manage(request, guild_id)
    command = _COMMANDS_BY_NAME.get(command_name.lower())
    if not command:
        raise _ApiError(404, f"No command named '{command_name}'.")
    if command.owner_only or command.name in NEVER_DISABLED_COMMANDS:
        raise _ApiError(400, f"'{command.name}' can't be disabled.")
    await db.disable_command(guild_id, command.name)
    return {"disabled_commands": await db.list_disabled_commands(guild_id)}


@app.post("/api/guilds/{guild_id}/commands/{command_name}/enable")
async def api_enable_command(request: Request, guild_id: str, command_name: str):
    await _require_manage(request, guild_id)
    command = _COMMANDS_BY_NAME.get(command_name.lower())
    if not command:
        raise _ApiError(404, f"No command named '{command_name}'.")
    await db.enable_command(guild_id, command.name)
    return {"disabled_commands": await db.list_disabled_commands(guild_id)}


# A stale heartbeat (no update in well over one scheduler tick) means the
# bot process is down, disconnected, or wedged, not just "the dashboard
# happens to be up." 60s is generous relative to the 15s tick interval.
_BOT_STALE_AFTER_SECONDS = 60


@app.get("/api/status")
async def api_public_status():
    """Public, no login required, same spirit as /api/commands: "is the bot
    down or is it just me" shouldn't require an account to check."""
    db_start = time.monotonic()
    try:
        await db.list_guilds()
        db_latency_ms = (time.monotonic() - db_start) * 1000
        db_ok = True
    except Exception:
        db_latency_ms = None
        db_ok = False

    bot_row = await db.get_bot_status() if db_ok else None
    bot_online = False
    if bot_row:
        age = (datetime.now(timezone.utc) - bot_row["last_heartbeat_at"]).total_seconds()
        bot_online = age < _BOT_STALE_AFTER_SECONDS

    return {
        "bot_online": bot_online,
        "bot_uptime_seconds": (
            (datetime.now(timezone.utc) - bot_row["started_at"]).total_seconds() if bot_online and bot_row else None
        ),
        "gateway_latency_ms": round(bot_row["gateway_latency_ms"]) if bot_online and bot_row and bot_row["gateway_latency_ms"] else None,
        "guild_count": bot_row["guild_count"] if bot_online and bot_row else None,
        "dashboard_db_ok": db_ok,
        "dashboard_db_latency_ms": round(db_latency_ms) if db_latency_ms is not None else None,
    }


def _guild_to_json(row) -> dict:
    return {
        "guild_id": row["guild_id"],
        "name": row["name"],
        "log_channel_id": row["log_channel_id"],
        "mute_role_id": row["mute_role_id"],
        "command_prefix": row["command_prefix"],
        "welcome_channel_id": row["welcome_channel_id"],
        "welcome_message": row["welcome_message"],
        "goodbye_channel_id": row["goodbye_channel_id"],
        "goodbye_message": row["goodbye_message"],
        "leveling_enabled": row["leveling_enabled"],
        "level_up_channel_id": row["level_up_channel_id"],
        "level_up_message": row["level_up_message"],
        "warn_timeout_at": row["warn_timeout_at"],
        "warn_kick_at": row["warn_kick_at"],
        "warn_timeout_minutes": row["warn_timeout_minutes"],
        "report_channel_id": row["report_channel_id"],
        "report_tracker_channel_id": row["report_tracker_channel_id"],
        "voice_xp_cap_enabled": row["voice_xp_cap_enabled"],
        "voice_xp_cap_amount": row["voice_xp_cap_amount"],
        "fluxer_patch_notes_channel_id": row["fluxer_patch_notes_channel_id"],
        "fluxer_patch_notes_trigger_hour": row["fluxer_patch_notes_trigger_hour"],
        "fluxer_patch_notes_trigger_minute": row["fluxer_patch_notes_trigger_minute"],
        "timezone": row["timezone"],
    }


def _warning_to_json(row, names: dict) -> dict:
    return {
        "id": row["id"], "user_id": row["user_id"], "username": names.get(row["user_id"], row["user_id"]),
        "moderator_id": row["moderator_id"],
        "moderator_username": names.get(row["moderator_id"], row["moderator_id"]),
        "reason": row["reason"], "active": row["active"],
        "created_at": row["created_at"].isoformat(),
    }


def _action_to_json(row, names: dict) -> dict:
    return {
        "id": row["id"], "user_id": row["user_id"],
        "username": names.get(row["user_id"], row["user_id"]) if row["user_id"] else None,
        "moderator_id": row["moderator_id"],
        "moderator_username": names.get(row["moderator_id"], row["moderator_id"]) if row["moderator_id"] else None,
        "action": row["action"], "reason": row["reason"],
        "created_at": row["created_at"].isoformat(),
    }


def _reaction_role_to_json(row) -> dict:
    return {
        "id": row["id"], "channel_id": row["channel_id"], "message_id": row["message_id"],
        "emoji": row["emoji"], "role_id": row["role_id"], "label": row["label"],
        "title": row["title"], "description": row["description"], "color": row["color"],
    }


def _tag_to_json(row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "content": row["content"],
        "created_by": row["created_by"], "created_at": row["created_at"].isoformat(),
    }


def _report_to_json(row, names: Optional[dict] = None, reply_summary: Optional[dict] = None) -> dict:
    names = names or {}
    is_public = row["visibility"] == "public"
    summary = (reply_summary or {}).get(row["id"])
    return {
        "id": row["id"],
        "reporter_id": row["reporter_id"] if is_public else None,
        "reporter_username": names.get(row["reporter_id"], row["reporter_id"]) if is_public else None,
        "content": row["content"],
        "visibility": row["visibility"],
        "status": row["status"],
        "duplicate_of": row["duplicate_of"],
        "possible_duplicate_of": row["possible_duplicate_of"],
        "resolution_note": row["resolution_note"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "reply_count": summary["reply_count"] if summary else 0,
        # True once the reporter has replied and staff haven't answered
        # back yet, so the Reports tab can badge "needs a reply" instead
        # of staff having to open every report to find out whose turn
        # it is to respond.
        "needs_staff_reply": bool(summary) and summary["last_author_type"] == "reporter",
    }


def _report_reply_to_json(row, names: Optional[dict] = None, *, show_reporter_identity: bool = True) -> dict:
    """Same privacy rule as _report_to_json's reporter_username: a
    reporter-authored reply on a report marked private stays
    attributed to "the reporter", never their real id/username, even
    though only staff with dashboard access ever see this thread --
    private means private, not just hidden from other members."""
    names = names or {}
    author_id = row["author_id"]
    hide = row["author_type"] == "reporter" and not show_reporter_identity
    return {
        "id": row["id"],
        "author_type": row["author_type"],
        "author_id": None if hide else author_id,
        "author_username": None if hide else (names.get(author_id, author_id) if author_id else None),
        "content": row["content"],
        "created_at": row["created_at"].isoformat(),
    }


@app.get("/api/guilds/{guild_id}")
async def api_guild_detail(request: Request, guild_id: str):
    await _require_manage(request, guild_id)
    guild_cfg = await db.get_guild(guild_id)
    if guild_cfg is None:
        raise _ApiError(404, "The bot isn't in this server (yet).")

    actions = await db.list_actions(guild_id, limit=50)
    warnings = await db.list_warnings(guild_id)
    autoroles = await db.list_autoroles(guild_id)
    reaction_roles = await db.list_reaction_roles(guild_id)
    guild_tags = await db.list_tags(guild_id)
    reports_list = await db.list_reports(guild_id, limit=100)

    all_ids = {a["user_id"] for a in actions if a["user_id"]} | {a["moderator_id"] for a in actions if a["moderator_id"]}
    all_ids |= {w["user_id"] for w in warnings} | {w["moderator_id"] for w in warnings}
    all_ids |= {r["reporter_id"] for r in reports_list if r["visibility"] == "public"}
    names = await _resolve_usernames(guild_id, list(all_ids))
    reply_summary = await db.get_report_reply_counts(guild_id)
    # A true count, not a sum over reports_list: that's limited to 100
    # rows, so a guild with a larger open-report backlog would otherwise
    # undercount this badge.
    open_report_count = await db.count_reports_by_status(guild_id, "open")

    member_count = None
    try:
        live_guild = await bot_rest.get_guild(guild_id)
        member_count = live_guild.get("member_count")
    except FluxerAPIError:
        pass  # Overview shows "-" rather than failing the whole page over it.

    fluxer_stats = await fluxer_admin.get_gateway_stats()

    return {
        "guild": _guild_to_json(guild_cfg),
        "actions": [_action_to_json(a, names) for a in actions],
        "warnings": [_warning_to_json(w, names) for w in warnings],
        "autoroles": autoroles,
        "reaction_roles": [_reaction_role_to_json(r) for r in reaction_roles],
        "tags": [_tag_to_json(t) for t in guild_tags],
        "active_warning_count": sum(1 for w in warnings if w["active"]),
        "reports": [_report_to_json(r, names, reply_summary) for r in reports_list],
        "open_report_count": open_report_count,
        "member_count": member_count,
        "fluxer_status": fluxer_stats["status"] if fluxer_stats else None,
    }


@app.get("/api/guilds/{guild_id}/actions")
async def api_guild_actions(request: Request, guild_id: str, before_id: Optional[int] = None, limit: int = 50):
    """"Load more" for Mod Log, past the first page guild detail already
    embeds. before_id is the oldest action id already shown; fetching
    limit+1 and trimming is how has_more is known without a second
    COUNT query."""
    await _require_manage(request, guild_id)
    limit = max(1, min(limit, 100))
    rows = await db.list_actions(guild_id, limit=limit + 1, before_id=before_id)
    has_more = len(rows) > limit
    rows = rows[:limit]
    ids = {r["user_id"] for r in rows if r["user_id"]} | {r["moderator_id"] for r in rows if r["moderator_id"]}
    names = await _resolve_usernames(guild_id, list(ids))
    return {"actions": [_action_to_json(a, names) for a in rows], "has_more": has_more}


@app.get("/api/guilds/{guild_id}/reports/list")
async def api_list_reports_page(request: Request, guild_id: str, before_id: Optional[int] = None,
                                 limit: int = 50, status: Optional[str] = None):
    """"Load more" for the Reports tab, same before_id cursor as actions
    above. A separate path from /reports/{report_id} (not /reports
    itself) so it can't collide with that detail route."""
    await _require_manage(request, guild_id)
    limit = max(1, min(limit, 100))
    rows = await db.list_reports(guild_id, status=status, limit=limit + 1, before_id=before_id)
    has_more = len(rows) > limit
    rows = rows[:limit]
    names = await _resolve_usernames(guild_id, list({r["reporter_id"] for r in rows if r["visibility"] == "public"}))
    reply_summary = await db.get_report_reply_counts(guild_id)
    return {"reports": [_report_to_json(r, names, reply_summary) for r in rows], "has_more": has_more}


class SettingsPayload(BaseModel):
    log_channel_id: str = ""
    mute_role_id: str = ""
    command_prefix: str = "!"
    welcome_channel_id: str = ""
    welcome_message: str = "Welcome {user} to {server}! 👋"
    goodbye_channel_id: str = ""
    goodbye_message: str = "{username} left {server}. 👋"
    leveling_enabled: bool = True
    level_up_channel_id: str = ""
    level_up_message: str = "GG {user}, you reached level {level}! 🎉"
    voice_xp_cap_enabled: bool = True
    voice_xp_cap_amount: int = 750
    warn_timeout_at: int = 3
    warn_kick_at: int = 5
    warn_timeout_minutes: int = 60
    report_channel_id: str = ""
    report_tracker_channel_id: str = ""
    fluxer_patch_notes_channel_id: str = ""
    fluxer_patch_notes_trigger_hour: int = 0
    fluxer_patch_notes_trigger_minute: int = 5
    timezone: str = fluxer_patch_notes.DEFAULT_TIMEZONE_NAME


def _diff_fields(previous, updated, field_labels: dict[str, str]) -> list[str]:
    """Human-readable labels for whichever of field_labels' columns
    actually changed between previous and updated (both dict-like, e.g.
    asyncpg.Record; previous may be None for a config row that didn't
    exist yet, in which case every set field reads as "changed", which
    is accurate for a first-time setup). Used to log an audit-trail
    mod_actions row for config changes made from the dashboard, the one
    category of change that wasn't visible in Mod Log at all before:
    kicks/bans/warns/etc. always were, but "who changed the mute role"
    or the warn thresholds left no trace."""
    changed = []
    for column, label in field_labels.items():
        old = previous[column] if previous is not None else None
        if old != updated[column] and label not in changed:
            changed.append(label)
    return changed


async def _log_config_change(guild_id: str, actor_id: str, changed_labels: list[str]) -> None:
    if not changed_labels:
        return  # e.g. the form was submitted with no actual change, nothing to record
    await db.log_action(guild_id, "settings_update", moderator_id=actor_id,
                         reason=f"Changed: {', '.join(changed_labels)}")


_SETTINGS_FIELD_LABELS = {
    "log_channel_id": "mod-log channel",
    "mute_role_id": "mute role",
    "command_prefix": "command prefix",
    "welcome_channel_id": "welcome channel",
    "welcome_message": "welcome message",
    "goodbye_channel_id": "goodbye channel",
    "goodbye_message": "goodbye message",
    "leveling_enabled": "leveling on/off",
    "level_up_channel_id": "level-up channel",
    "level_up_message": "level-up message",
    "voice_xp_cap_enabled": "voice XP daily cap",
    "voice_xp_cap_amount": "voice XP daily cap amount",
    "warn_timeout_at": "warn-timeout threshold",
    "warn_kick_at": "warn-kick threshold",
    "warn_timeout_minutes": "timeout length",
    "report_channel_id": "report channel",
    "report_tracker_channel_id": "report tracker channel",
    "fluxer_patch_notes_channel_id": "Fluxer patch notes channel",
    "fluxer_patch_notes_trigger_hour": "Fluxer patch notes send time",
    "fluxer_patch_notes_trigger_minute": "Fluxer patch notes send time",
    "timezone": "default timezone",
}

_ACTIVITY_LOG_FIELD_LABELS = {
    "log_channel_id": "activity log channel",
    "log_message_edits": "log message edits",
    "log_message_deletes": "log message deletes",
    "log_member_joins": "log member joins",
    "log_member_leaves": "log member leaves",
    "log_channel_changes": "log channel changes",
    "log_role_changes": "log role changes",
    "log_voice_activity": "log voice activity",
    "log_privileged_role_changes": "log privileged-role changes",
}

_REPORT_CHANNEL_FIELD_LABELS = {
    "report_channel_id": "report channel",
    "report_tracker_channel_id": "report tracker channel",
}


async def _maybe_post_report_intro(previous, guild_cfg) -> None:
    """Shared by every path that can change report_channel_id or
    report_tracker_channel_id (the full settings form, and the Reports
    tab's own narrower channel picker): re-posts the explainer embed
    whenever either actually changed, never on an unrelated save that
    happens to pass the same values through again. Changing only the
    tracker channel still needs a re-post, the embed itself names it
    (see build_channel_intro_embed), so leaving the old one up would
    point at a channel reports no longer actually go to."""
    new_report_channel = guild_cfg["report_channel_id"]
    if not new_report_channel:
        return
    previous_report_channel = previous["report_channel_id"] if previous else None
    previous_tracker_channel = previous["report_tracker_channel_id"] if previous else None
    if (new_report_channel != previous_report_channel
            or guild_cfg["report_tracker_channel_id"] != previous_tracker_channel):
        await report_actions.post_channel_intro(
            bot_rest, new_report_channel, guild_cfg["report_tracker_channel_id"],
        )


@app.post("/api/guilds/{guild_id}/settings")
async def api_update_settings(request: Request, guild_id: str, payload: SettingsPayload):
    await _require_manage(request, guild_id)
    user = require_login(request)
    prefix = (payload.command_prefix or "!").strip()[:5] or "!"
    voice_xp_cap_amount = max(1, min(1_000_000, payload.voice_xp_cap_amount or 750))
    patch_notes_trigger_hour = max(0, min(23, payload.fluxer_patch_notes_trigger_hour))
    patch_notes_trigger_minute = max(0, min(59, payload.fluxer_patch_notes_trigger_minute))
    guild_timezone = (payload.timezone or fluxer_patch_notes.DEFAULT_TIMEZONE_NAME).strip()
    try:
        ZoneInfo(guild_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise _ApiError(400, f"'{guild_timezone}' isn't a recognized timezone.")
    previous = await db.get_guild(guild_id)
    await db.update_guild_settings(
        guild_id,
        log_channel_id=payload.log_channel_id or None,
        mute_role_id=payload.mute_role_id or None,
        command_prefix=prefix,
        welcome_channel_id=payload.welcome_channel_id or None,
        welcome_message=payload.welcome_message or "Welcome {user} to {server}! 👋",
        goodbye_channel_id=payload.goodbye_channel_id or None,
        goodbye_message=payload.goodbye_message or "{username} left {server}. 👋",
        leveling_enabled=payload.leveling_enabled,
        level_up_channel_id=payload.level_up_channel_id or None,
        level_up_message=payload.level_up_message or "GG {user}, you reached level {level}! 🎉",
        voice_xp_cap_enabled=payload.voice_xp_cap_enabled,
        voice_xp_cap_amount=voice_xp_cap_amount,
        warn_timeout_at=payload.warn_timeout_at,
        warn_kick_at=payload.warn_kick_at,
        warn_timeout_minutes=payload.warn_timeout_minutes,
        report_channel_id=payload.report_channel_id or None,
        report_tracker_channel_id=payload.report_tracker_channel_id or None,
        fluxer_patch_notes_channel_id=payload.fluxer_patch_notes_channel_id or None,
        fluxer_patch_notes_trigger_hour=patch_notes_trigger_hour,
        fluxer_patch_notes_trigger_minute=patch_notes_trigger_minute,
        timezone=guild_timezone,
    )
    guild_cfg = await db.get_guild(guild_id)
    await _maybe_post_report_intro(previous, guild_cfg)
    await _log_config_change(guild_id, str(user.get("id")),
                              _diff_fields(previous, guild_cfg, _SETTINGS_FIELD_LABELS))
    return {"guild": _guild_to_json(guild_cfg)}


def _activity_log_to_json(row, ignored_users: list[str]) -> dict:
    if row is None:
        return {
            "log_channel_id": None, "log_message_edits": False, "log_message_deletes": False,
            "log_member_joins": False, "log_member_leaves": False, "log_channel_changes": False,
            "log_role_changes": False, "log_voice_activity": False, "log_privileged_role_changes": False,
            "ignored_users": ignored_users,
        }
    return {
        "log_channel_id": row["log_channel_id"],
        "log_message_edits": row["log_message_edits"], "log_message_deletes": row["log_message_deletes"],
        "log_member_joins": row["log_member_joins"], "log_member_leaves": row["log_member_leaves"],
        "log_channel_changes": row["log_channel_changes"], "log_role_changes": row["log_role_changes"],
        "log_voice_activity": row["log_voice_activity"],
        "log_privileged_role_changes": row["log_privileged_role_changes"],
        "ignored_users": ignored_users,
    }


def _relay_mapping_to_json(row) -> dict:
    return {
        "id": row["id"],
        "discord_channel_id": row["discord_channel_id"],
        "fluxer_channel_id": row["fluxer_channel_id"],
        "direction": row["direction"],
        "enabled": row["enabled"],
        "show_attribution": row["show_attribution"],
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat(),
    }


def _discord_invite_url(bot_id: str) -> str:
    return f"https://discord.com/api/oauth2/authorize?client_id={bot_id}&permissions={DISCORD_RELAY_INVITE_PERMISSIONS}&scope=bot"


@app.get("/api/guilds/{guild_id}/discord-relay")
async def api_get_discord_relay(request: Request, guild_id: str):
    await _require_manage(request, guild_id)
    mappings = await db.list_discord_relay_mappings_for_guild(guild_id)
    relay_token = await db.get_discord_relay_token()
    status = await db.get_discord_relay_status()
    return {
        "mappings": [_relay_mapping_to_json(m) for m in mappings],
        "relay_configured": bool(relay_token or config.discord_bot_token),
        "relay_status": {
            "connected": status["connected"],
            "discord_username": status["discord_username"],
        } if status else None,
        # Any guild manager can grab this to invite the shared relay bot
        # into their own Discord server, not just the owner, that's the
        # whole point of surfacing it here rather than only on the
        # owner-only setup page.
        "invite_url": _discord_invite_url(status["discord_bot_id"]) if status and status["discord_bot_id"] else None,
    }


_VALID_RELAY_DIRECTIONS = {"discord_to_fluxer", "fluxer_to_discord", "both"}


class DiscordRelayAddPayload(BaseModel):
    discord_channel_id: str
    fluxer_channel_id: str
    direction: str = "discord_to_fluxer"
    show_attribution: bool = True


@app.post("/api/guilds/{guild_id}/discord-relay")
async def api_add_discord_relay(request: Request, guild_id: str, payload: DiscordRelayAddPayload):
    await _require_manage(request, guild_id)
    discord_channel_id = payload.discord_channel_id.strip()
    fluxer_channel_id = payload.fluxer_channel_id.strip()
    if not discord_channel_id.isdigit():
        raise _ApiError(400, "Discord channel ID must be numeric, copy it with Developer Mode on in Discord.")
    if not fluxer_channel_id.isdigit():
        raise _ApiError(400, "Fluxer channel ID must be numeric.")
    if payload.direction not in _VALID_RELAY_DIRECTIONS:
        raise _ApiError(400, f"direction must be one of {sorted(_VALID_RELAY_DIRECTIONS)}.")
    creator = current_user(request)
    try:
        await db.add_discord_relay_mapping(guild_id, discord_channel_id, fluxer_channel_id,
                                            direction=payload.direction, show_attribution=payload.show_attribution,
                                            created_by=str(creator["id"]) if creator else None)
    except ValueError as e:
        raise _ApiError(409, str(e))
    mappings = await db.list_discord_relay_mappings_for_guild(guild_id)
    return {"mappings": [_relay_mapping_to_json(m) for m in mappings]}


@app.delete("/api/guilds/{guild_id}/discord-relay/{mapping_id}")
async def api_remove_discord_relay(request: Request, guild_id: str, mapping_id: int):
    await _require_manage(request, guild_id)
    await db.remove_discord_relay_mapping(mapping_id, guild_id)
    mappings = await db.list_discord_relay_mappings_for_guild(guild_id)
    return {"mappings": [_relay_mapping_to_json(m) for m in mappings]}


class DiscordRelayTogglePayload(BaseModel):
    enabled: bool


@app.post("/api/guilds/{guild_id}/discord-relay/{mapping_id}/toggle")
async def api_toggle_discord_relay(request: Request, guild_id: str, mapping_id: int, payload: DiscordRelayTogglePayload):
    await _require_manage(request, guild_id)
    await db.set_discord_relay_mapping_enabled(mapping_id, guild_id, payload.enabled)
    mappings = await db.list_discord_relay_mappings_for_guild(guild_id)
    return {"mappings": [_relay_mapping_to_json(m) for m in mappings]}


@app.post("/api/guilds/{guild_id}/discord-relay/{mapping_id}/test")
async def api_test_discord_relay(request: Request, guild_id: str, mapping_id: int):
    """Sends a clearly-labeled test message directly to whichever
    channel(s) this mapping targets, bypassing the relay's own event
    handling entirely. This confirms the bot actually has permission
    and the channel id is correct on each end, the most common failure
    mode, not a full round-trip through the live relay logic (that
    would mean actually posting a real message on the source platform
    and waiting to observe it arrive, more integration test than a
    button click). Said plainly in the response so this isn't mistaken
    for more than it is."""
    await _require_manage(request, guild_id)
    mapping = await db.get_discord_relay_mapping(mapping_id, guild_id)
    if mapping is None:
        raise _ApiError(404, "That mapping doesn't exist (or doesn't belong to this server).")

    results = {}
    if mapping["direction"] in ("discord_to_fluxer", "both"):
        try:
            await bot_rest.send_message(mapping["fluxer_channel_id"],
                                         content="Test message from FluxBot's Discord Relay. If you can see this, "
                                                 "the bot can post here successfully.")
            results["fluxer"] = "sent"
        except FluxerAPIError as e:
            results["fluxer"] = f"failed (HTTP {e.status}), check the bot's permissions in that channel"

    if mapping["direction"] in ("fluxer_to_discord", "both"):
        token = await db.get_discord_relay_token() or config.discord_bot_token
        if not token:
            results["discord"] = "skipped, no relay token configured yet"
        else:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        f"https://discord.com/api/v10/channels/{mapping['discord_channel_id']}/messages",
                        headers={"Authorization": f"Bot {token}"},
                        json={"content": "Test message from FluxBot's Discord Relay. If you can see this, "
                                         "the bot can post here successfully."},
                    )
                if resp.status_code < 300:
                    results["discord"] = "sent"
                else:
                    results["discord"] = f"failed (HTTP {resp.status_code}), check the bot is actually in that server with permission to post there"
            except Exception as e:
                results["discord"] = f"failed ({type(e).__name__}), couldn't reach Discord"

    return {"results": results}


async def _activity_log_response(guild_id: str) -> dict:
    row = await db.get_activity_log_settings(guild_id)
    ignored = await db.list_ignored_log_users(guild_id)
    return _activity_log_to_json(row, ignored)


@app.get("/api/guilds/{guild_id}/activity-log")
async def api_get_activity_log(request: Request, guild_id: str):
    await _require_manage(request, guild_id)
    return await _activity_log_response(guild_id)


class ActivityLogPayload(BaseModel):
    log_channel_id: str = ""
    log_message_edits: bool = False
    log_message_deletes: bool = False
    log_member_joins: bool = False
    log_member_leaves: bool = False
    log_channel_changes: bool = False
    log_role_changes: bool = False
    log_voice_activity: bool = False
    log_privileged_role_changes: bool = False


@app.post("/api/guilds/{guild_id}/activity-log")
async def api_set_activity_log(request: Request, guild_id: str, payload: ActivityLogPayload):
    await _require_manage(request, guild_id)
    user = require_login(request)
    previous = await db.get_activity_log_settings(guild_id)
    await db.set_activity_log_settings(
        guild_id, log_channel_id=payload.log_channel_id or None,
        log_message_edits=payload.log_message_edits, log_message_deletes=payload.log_message_deletes,
        log_member_joins=payload.log_member_joins, log_member_leaves=payload.log_member_leaves,
        log_channel_changes=payload.log_channel_changes, log_role_changes=payload.log_role_changes,
        log_voice_activity=payload.log_voice_activity,
        log_privileged_role_changes=payload.log_privileged_role_changes,
    )
    updated = await db.get_activity_log_settings(guild_id)
    await _log_config_change(guild_id, str(user.get("id")),
                              _diff_fields(previous, updated, _ACTIVITY_LOG_FIELD_LABELS))
    return await _activity_log_response(guild_id)


class IgnoredUserPayload(BaseModel):
    user_id: str


@app.post("/api/guilds/{guild_id}/activity-log/ignored-users")
async def api_add_ignored_log_user(request: Request, guild_id: str, payload: IgnoredUserPayload):
    await _require_manage(request, guild_id)
    user_id = payload.user_id.strip()
    if not user_id.isdigit():
        raise _ApiError(400, "User ID must be numeric.")
    await db.add_ignored_log_user(guild_id, user_id)
    return await _activity_log_response(guild_id)


@app.delete("/api/guilds/{guild_id}/activity-log/ignored-users/{user_id}")
async def api_remove_ignored_log_user(request: Request, guild_id: str, user_id: str):
    await _require_manage(request, guild_id)
    await db.remove_ignored_log_user(guild_id, user_id)
    return await _activity_log_response(guild_id)


@app.post("/api/guilds/{guild_id}/warnings/{user_id}/clear")
async def api_clear_warnings(request: Request, guild_id: str, user_id: str):
    await _require_manage(request, guild_id)
    cleared = await db.clear_warnings(guild_id, user_id)
    response = await _warnings_response(guild_id)
    return {"cleared": cleared, **response}


class AutoroleAddPayload(BaseModel):
    role_id: str


@app.post("/api/guilds/{guild_id}/autoroles")
async def api_add_autorole(request: Request, guild_id: str, payload: AutoroleAddPayload):
    await _require_manage(request, guild_id)
    role_id = payload.role_id.strip()
    if not role_id.isdigit():
        raise _ApiError(400, "Role ID must be numeric, copy it from Fluxer with Developer Mode on.")
    try:
        guild = await bot_rest.get_guild(guild_id)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Couldn't verify that role (HTTP {e.status}).")
    if role_is_privileged(guild, role_id):
        raise _ApiError(400, "That role carries moderation/admin permissions, autoroles can't grant it "
                              "automatically to every new member. Assign it manually instead.")
    await db.add_autorole(guild_id, role_id)
    return {"autoroles": await db.list_autoroles(guild_id)}


@app.delete("/api/guilds/{guild_id}/autoroles/{role_id}")
async def api_remove_autorole(request: Request, guild_id: str, role_id: str):
    await _require_manage(request, guild_id)
    await db.remove_autorole(guild_id, role_id)
    return {"autoroles": await db.list_autoroles(guild_id)}


class ReactionRolePair(BaseModel):
    emoji: str
    label: str = ""
    role_id: str


class ReactionRoleCreatePayload(BaseModel):
    channel_id: str
    title: str = "Pick your roles"
    description: str = ""
    color: str = "5865F2"
    pairs: list[ReactionRolePair]


def _parse_embed_color(color: str) -> int:
    try:
        return int(color.lstrip("#"), 16)
    except (ValueError, AttributeError):
        return 0x5865F2


def _reaction_role_line(emoji: str, label: str) -> str:
    # No role mention here on purpose: it used to be `f"{emoji}, <@&{role}>"`,
    # spelling out exactly which role each reaction grants in a public
    # channel. The label (when staff bother to set one) already says what a
    # reaction is for in plainer, friendlier terms than the raw role name;
    # the role itself is only ever meant to be visible as a mapping here on
    # the dashboard, not advertised in the message members react to.
    return f"{emoji} **{label}**" if label else emoji


def _build_reaction_role_embed(title: str, description: str, color: int,
                                pairs: list[tuple[str, str, str]]) -> dict:
    lines = "\n".join(_reaction_role_line(emoji, label) for emoji, label, _ in pairs)
    return {
        "title": title or "Pick your roles",
        "description": (description + "\n\n" if description else "") + lines,
        "color": color,
    }


async def _check_no_privileged_roles(guild_id: str, pairs: list[tuple[str, str, str]]) -> None:
    try:
        guild = await bot_rest.get_guild(guild_id)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Couldn't verify those roles (HTTP {e.status}).")
    privileged = [role_id for _, _, role_id in pairs if role_is_privileged(guild, role_id)]
    if privileged:
        raise _ApiError(400, "One or more of those roles carry moderation/admin permissions, reaction roles "
                              "can't hand them out to anyone who clicks. Assign them manually instead.")


def _clean_pairs(raw_pairs: list[ReactionRolePair]) -> list[tuple[str, str, str]]:
    return [
        (p.emoji.strip(), p.label.strip(), p.role_id.strip())
        for p in raw_pairs if p.emoji.strip() and p.role_id.strip()
    ]


@app.post("/api/guilds/{guild_id}/reactionroles")
async def api_create_reaction_role(request: Request, guild_id: str, payload: ReactionRoleCreatePayload):
    await _require_manage(request, guild_id)
    channel_id = payload.channel_id.strip()
    pairs = _clean_pairs(payload.pairs)
    if not channel_id.isdigit() or not pairs:
        raise _ApiError(400, "Give a channel ID and at least one emoji + role pair.")
    await _check_no_privileged_roles(guild_id, pairs)

    title = payload.title or "Pick your roles"
    color_int = _parse_embed_color(payload.color)
    embed = _build_reaction_role_embed(title, payload.description, color_int, pairs)

    failed_reactions: list[str] = []
    try:
        sent = await bot_rest.send_message(channel_id, embeds=[embed])
        message_id = str(sent["id"])
        for emoji, label, role_id in pairs:
            try:
                await bot_rest.add_reaction(channel_id, message_id, emoji)
            except FluxerAPIError:
                # Emoji format the instance expects may differ (unicode vs
                # custom emoji id), the mapping is still stored below so
                # reactions added manually will still grant the role. We
                # surface this back to the dashboard instead of hiding it.
                failed_reactions.append(emoji)
            await db.add_reaction_role(guild_id, channel_id, message_id, emoji, role_id, label,
                                        title=title, description=payload.description, color=color_int)
    except FluxerAPIError as e:
        log.warning("Failed to send reaction-role embed: %s", e)
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}), check the bot can post in that channel.")

    return {
        "reaction_roles": [_reaction_role_to_json(r) for r in await db.list_reaction_roles(guild_id)],
        "failed_reactions": failed_reactions,
    }


@app.patch("/api/guilds/{guild_id}/reactionroles/message/{message_id}")
async def api_edit_reaction_role_message(request: Request, guild_id: str, message_id: str,
                                          payload: ReactionRoleCreatePayload):
    """Edits an existing reaction-role message in place: the embed text
    (title/description/color) and which emoji/role/label pairs it has.
    The channel can't change here, that's what resend is for (posting a
    fresh message, possibly worth picking a new channel for, rather than
    editing one in place)."""
    await _require_manage(request, guild_id)
    existing = await db.get_reaction_roles_by_message(guild_id, message_id)
    if not existing:
        raise _ApiError(404, "That reaction-role message doesn't exist (anymore). Try resending it instead.")
    channel_id = existing[0]["channel_id"]
    pairs = _clean_pairs(payload.pairs)
    if not pairs:
        raise _ApiError(400, "Give at least one emoji + role pair.")
    await _check_no_privileged_roles(guild_id, pairs)

    title = payload.title or "Pick your roles"
    color_int = _parse_embed_color(payload.color)
    embed = _build_reaction_role_embed(title, payload.description, color_int, pairs)
    try:
        await bot_rest.edit_message(channel_id, message_id, embeds=[embed])
    except FluxerAPIError as e:
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}), the message may have been deleted, "
                              f"try resending instead.")

    old_emojis = {row["emoji"] for row in existing}
    new_emojis = {emoji for emoji, _, _ in pairs}
    failed_reactions: list[str] = []
    for emoji in new_emojis - old_emojis:
        try:
            await bot_rest.add_reaction(channel_id, message_id, emoji)
        except FluxerAPIError:
            failed_reactions.append(emoji)
    for emoji in old_emojis - new_emojis:
        try:
            await bot_rest.remove_own_reaction(channel_id, message_id, emoji)
        except FluxerAPIError:
            pass  # best-effort tidy-up, removing the mapping below is what actually matters
        await db.remove_reaction_role_by_emoji(guild_id, message_id, emoji)
    for emoji, label, role_id in pairs:
        await db.add_reaction_role(guild_id, channel_id, message_id, emoji, role_id, label,
                                    title=title, description=payload.description, color=color_int)

    return {
        "reaction_roles": [_reaction_role_to_json(r) for r in await db.list_reaction_roles(guild_id)],
        "failed_reactions": failed_reactions,
    }


@app.post("/api/guilds/{guild_id}/reactionroles/message/{message_id}/resend")
async def api_resend_reaction_role_message(request: Request, guild_id: str, message_id: str):
    """Posts a brand new message with the same embed and emoji/role/label
    mappings as an existing one, then moves those mappings over to it.
    Mainly for when the original message was deleted (accidentally, or a
    channel purge) and reacting to it is no longer possible at all, but
    works equally well as "I just want a clean repost"."""
    await _require_manage(request, guild_id)
    rows = await db.get_reaction_roles_by_message(guild_id, message_id)
    if not rows:
        raise _ApiError(404, "That reaction-role message doesn't exist (anymore).")
    channel_id = rows[0]["channel_id"]
    pairs = [(r["emoji"], r["label"], r["role_id"]) for r in rows]
    embed = _build_reaction_role_embed(rows[0]["title"], rows[0]["description"], rows[0]["color"], pairs)

    try:
        sent = await bot_rest.send_message(channel_id, embeds=[embed])
    except FluxerAPIError as e:
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}), check the bot can post in that channel.")
    new_message_id = str(sent["id"])

    failed_reactions: list[str] = []
    for r in rows:
        try:
            await bot_rest.add_reaction(channel_id, new_message_id, r["emoji"])
        except FluxerAPIError:
            failed_reactions.append(r["emoji"])

    await db.repoint_reaction_role_message(guild_id, message_id, new_message_id, channel_id)
    try:
        await bot_rest.delete_message(channel_id, message_id, reason="Reaction-role setup resent via dashboard")
    except FluxerAPIError:
        pass  # old message is usually already gone, which is why this got resent in the first place

    return {
        "reaction_roles": [_reaction_role_to_json(r) for r in await db.list_reaction_roles(guild_id)],
        "failed_reactions": failed_reactions,
    }


@app.delete("/api/guilds/{guild_id}/reactionroles/{mapping_id}")
async def api_remove_reaction_role(request: Request, guild_id: str, mapping_id: int):
    await _require_manage(request, guild_id)
    await db.remove_reaction_role(guild_id, mapping_id)
    return {"reaction_roles": [_reaction_role_to_json(r) for r in await db.list_reaction_roles(guild_id)]}


@app.delete("/api/guilds/{guild_id}/reactionroles/message/{message_id}")
async def api_remove_reaction_role_message(request: Request, guild_id: str, message_id: str):
    """Delete an entire reaction-role setup: all its emoji/role mappings,
    plus a best-effort attempt to delete the actual Fluxer message so
    members don't keep reacting to a dead setup."""
    await _require_manage(request, guild_id)
    rows = await db.get_reaction_roles_by_message(guild_id, message_id)
    if rows:
        channel_id = rows[0]["channel_id"]
        try:
            await bot_rest.delete_message(channel_id, message_id, reason="Reaction-role setup removed via dashboard")
        except FluxerAPIError:
            pass  # message may already be gone; mapping cleanup still proceeds
    await db.remove_reaction_roles_by_message(guild_id, message_id)
    return {"reaction_roles": [_reaction_role_to_json(r) for r in await db.list_reaction_roles(guild_id)]}


# ------------------------------------------------------------------ reports --
class ReportChannelsPayload(BaseModel):
    report_channel_id: str = ""
    report_tracker_channel_id: str = ""


@app.post("/api/guilds/{guild_id}/reports/channels")
async def api_set_report_channels(request: Request, guild_id: str, payload: ReportChannelsPayload):
    """A narrower alternative to the full /settings form, so the
    Reports tab can offer its own channel pickers without having to
    carry (and risk clobbering) every other setting just to change
    these two. update_guild_settings only ever touches the columns
    it's actually passed, so this is safe to call with just these two."""
    await _require_manage(request, guild_id)
    user = require_login(request)
    previous = await db.get_guild(guild_id)
    await db.update_guild_settings(
        guild_id,
        report_channel_id=payload.report_channel_id or None,
        report_tracker_channel_id=payload.report_tracker_channel_id or None,
    )
    guild_cfg = await db.get_guild(guild_id)
    await _maybe_post_report_intro(previous, guild_cfg)
    await _log_config_change(guild_id, str(user.get("id")),
                              _diff_fields(previous, guild_cfg, _REPORT_CHANNEL_FIELD_LABELS))
    return {"guild": _guild_to_json(guild_cfg)}


class ReportStatusPayload(BaseModel):
    status: str
    duplicate_of: Optional[int] = None
    note: str = ""


@app.post("/api/guilds/{guild_id}/reports/{report_id}/status")
async def api_set_report_status(request: Request, guild_id: str, report_id: int, payload: ReportStatusPayload):
    await _require_manage(request, guild_id)
    user = require_login(request)
    try:
        await report_actions.set_status(
            bot_rest, guild_id, report_id, payload.status.strip().lower(),
            duplicate_of=payload.duplicate_of, resolution_note=payload.note.strip() or None,
            resolved_by=str(user.get("id")),
        )
    except ValueError as e:
        raise _ApiError(400, str(e))
    rows = await db.list_reports(guild_id, limit=100)
    names = await _resolve_usernames(guild_id, list({r["reporter_id"] for r in rows if r["visibility"] == "public"}))
    reply_summary = await db.get_report_reply_counts(guild_id)
    open_report_count = await db.count_reports_by_status(guild_id, "open")
    return {
        "reports": [_report_to_json(r, names, reply_summary) for r in rows],
        "open_report_count": open_report_count,
    }


async def _report_detail_response(guild_id: str, report_id: int) -> dict:
    report = await db.get_report(guild_id, report_id)
    if not report:
        raise _ApiError(404, f"No report #{report_id} in this server.")
    is_public = report["visibility"] == "public"
    replies = await db.list_report_replies(report_id)
    reply_summary = await db.get_report_reply_counts(guild_id)

    ids = set()
    if is_public:
        ids.add(report["reporter_id"])
    ids |= {r["author_id"] for r in replies if r["author_id"] and (r["author_type"] != "reporter" or is_public)}
    names = await _resolve_usernames(guild_id, list(ids))

    return {
        "report": _report_to_json(report, names, reply_summary),
        "replies": [_report_reply_to_json(r, names, show_reporter_identity=is_public) for r in replies],
    }


@app.get("/api/guilds/{guild_id}/reports/{report_id}")
async def api_report_detail(request: Request, guild_id: str, report_id: int):
    """Backs the per-report dashboard page: the report itself plus its
    full reply thread, see _report_detail_response. Polled every few
    seconds while that page is open the same way the rest of the
    dashboard is, so a reporter's DM reply shows up without a manual
    refresh."""
    await _require_manage(request, guild_id)
    return await _report_detail_response(guild_id, report_id)


class ReportReplyPayload(BaseModel):
    content: str


@app.post("/api/guilds/{guild_id}/reports/{report_id}/replies")
async def api_add_report_reply(request: Request, guild_id: str, report_id: int, payload: ReportReplyPayload):
    await _require_manage(request, guild_id)
    user = require_login(request)
    content = payload.content.strip()
    if not content:
        raise _ApiError(400, "Reply can't be empty.")
    try:
        _, delivered = await report_actions.add_staff_reply(
            bot_rest, guild_id, report_id, str(user.get("id")), content,
        )
    except ValueError as e:
        raise _ApiError(400, str(e))
    result = await _report_detail_response(guild_id, report_id)
    # Surfaced so the compose box can warn staff the reporter has DMs
    # closed, same as !report reply's own chat reply does -- the reply
    # is still saved and mirrored to the tracker channel either way.
    result["delivered"] = delivered
    return result


# --------------------------------------------------------- roles / channels --
@app.get("/api/guilds/{guild_id}/roles")
async def api_guild_roles(request: Request, guild_id: str):
    """Powers the role picker dropdowns (autoroles, reaction roles, mute
    role) instead of making people copy-paste raw role IDs."""
    await _require_manage(request, guild_id)
    try:
        guild = await bot_rest.get_guild(guild_id)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Couldn't fetch roles from Fluxer (HTTP {e.status}).")
    roles_list = [
        {"id": str(r["id"]), "name": r.get("name", "role"), "color": r.get("color")}
        for r in guild.get("roles", [])
        if str(r.get("id")) != guild_id  # exclude @everyone (id == guild id, Discord convention)
    ]
    return {"roles": roles_list}


# Fluxer's channel `type` enum (https://docs.fluxer.app/http-api/channels/),
# Discord-compatible. GUILD_TEXT and GUILD_ANNOUNCEMENT both take a plain
# POST .../messages like any other text channel, so every channel picker
# in the dashboard (mod-log, welcome, reaction-role target, etc.) offers
# both. GUILD_FORUM/GUILD_MEDIA don't -- Fluxer returns 400
# CANNOT_SEND_MESSAGES_IN_NON_TEXT_CHANNEL for those, you have to start a
# thread/post instead (see bot_rest.start_forum_post) -- so only a picker
# that actually knows how to do that (the embed builder) asks for them,
# via include_posts.
_CHANNEL_TYPE_TEXT = 0
_CHANNEL_TYPE_ANNOUNCEMENT = 5
_CHANNEL_TYPE_FORUM = 15
_CHANNEL_TYPE_MEDIA = 16
_POST_ONLY_CHANNEL_TYPES = {_CHANNEL_TYPE_FORUM, _CHANNEL_TYPE_MEDIA}
_MESSAGEABLE_CHANNEL_TYPES = {_CHANNEL_TYPE_TEXT, _CHANNEL_TYPE_ANNOUNCEMENT, None}


@app.get("/api/guilds/{guild_id}/channels")
async def api_guild_channels(request: Request, guild_id: str, include_posts: bool = False):
    """Powers the channel picker dropdowns (mod-log, welcome, reaction-role
    target channel, embeds). `include_posts=true` (used by the embed
    builder, the one picker that knows how to post into a forum/media
    channel) also includes those in the result; every other caller gets
    just the plain-messageable types."""
    await _require_manage(request, guild_id)
    try:
        guild = await bot_rest.get_guild(guild_id)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Couldn't fetch channels from Fluxer (HTTP {e.status}).")
    allowed_types = _MESSAGEABLE_CHANNEL_TYPES | _POST_ONLY_CHANNEL_TYPES if include_posts else _MESSAGEABLE_CHANNEL_TYPES
    channels_list = [
        {"id": str(c["id"]), "name": c.get("name", "channel"), "type": c.get("type")}
        for c in guild.get("channels", [])
        if c.get("type") in allowed_types
    ]
    return {"channels": channels_list}


def _guild_emoji_to_json(e, media_base: str) -> dict:
    """`reaction` is the exact string Fluxer's reaction endpoints expect
    (confirmed as `name:id` by Fluxer's docs); `tag` is the Discord-style
    inline form (`<:name:id>` / `<a:name:id>`) used when inserting into
    message text -- Fluxer's own docs don't specify that syntax, so this
    follows the same convention the rest of this codebase assumes where
    Fluxer's reference is silent."""
    emoji_id = str(e["id"])
    name = e.get("name", "emoji")
    animated = bool(e.get("animated"))
    return {
        "id": emoji_id,
        "name": name,
        "animated": animated,
        "url": emoji_url(media_base, emoji_id, animated=animated, size=64),
        "reaction": f"{name}:{emoji_id}",
        "tag": f"<{'a' if animated else ''}:{name}:{emoji_id}>",
    }


@app.get("/api/guilds/{guild_id}/emojis")
async def api_guild_emojis(request: Request, guild_id: str):
    """Powers the emoji picker (reaction roles, embed builder) with the
    server's own custom emoji instead of making people paste `name:id`
    by hand."""
    await _require_manage(request, guild_id)
    try:
        emojis = await bot_rest.list_guild_emojis(guild_id)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Couldn't fetch emoji from Fluxer (HTTP {e.status}).")
    media_base = await get_media_base()
    return {"emojis": [_guild_emoji_to_json(e, media_base) for e in emojis]}


# ------------------------------------------------------------------ members --
@app.get("/api/guilds/{guild_id}/members")
async def api_guild_members(request: Request, guild_id: str, q: str = "", offset: int = 0, limit: int = 100):
    """Best-effort member list/search. Fluxer's member-list endpoint (like
    Discord's) is paginated and capped per-request; this fetches one page
    (up to 500) and filters client-side-ish here, which comfortably covers
    small-to-medium communities. For very large servers this won't show
    every member, search by exact ID also works around that.

    offset/limit page through that same up-to-500 in-memory slice (not a
    real cursor into Fluzer's own member list) so "Load more" in the
    dashboard can reveal more of what's already been fetched instead of
    everything past the first 100 just disappearing."""
    await _require_manage(request, guild_id)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    try:
        members = await bot_rest.list_guild_members(guild_id, limit=500)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Couldn't fetch members from Fluxer (HTTP {e.status}).")

    q_lower = q.strip().lower()
    filtered = []
    for m in members:
        user = m.get("user", m)
        username = user.get("username", "")
        user_id = str(user.get("id"))
        if q_lower and q_lower not in username.lower() and q_lower != user_id:
            continue
        filtered.append((m, user, user_id, username))
    total_matched = len(filtered)
    page = filtered[offset:offset + limit]

    media_base = await get_media_base()
    message_counts = await db.get_member_message_counts(guild_id, [uid for _, _, uid, _ in page])
    result = [
        {
            "id": user_id,
            "username": username,
            "avatar": user.get("avatar"),
            "avatar_url": user_avatar_url(media_base, user_id, user.get("avatar"), size=64),
            "roles": m.get("roles", []),
            "joined_at": m.get("joined_at"),
            "message_count": message_counts.get(user_id, 0),
        }
        for m, user, user_id, username in page
    ]
    return {"members": result, "has_more": offset + limit < total_matched}


class MemberActionPayload(BaseModel):
    reason: str = ""


class TimeoutPayload(BaseModel):
    reason: str = ""
    duration_seconds: int = 3600


def _moderator_from_session(request: Request) -> dict:
    user = require_login(request)
    return {"id": str(user.get("id")), "username": user.get("username", "dashboard")}


async def _fetch_member_user(guild_id: str, user_id: str) -> dict:
    try:
        member = await bot_rest.get_guild_member(guild_id, user_id)
    except FluxerAPIError:
        raise _ApiError(404, "Couldn't find that member in this server.")
    return member.get("user", member)


@app.post("/api/guilds/{guild_id}/members/{user_id}/kick")
async def api_kick_member(request: Request, guild_id: str, user_id: str, payload: MemberActionPayload):
    await _require_manage(request, guild_id)
    moderator = _moderator_from_session(request)
    user = await _fetch_member_user(guild_id, user_id)
    try:
        await moderation_actions.kick_member(bot_rest, guild_id, user, moderator, payload.reason or "No reason provided")
    except ModerationBlocked as e:
        raise _ApiError(403, str(e))
    except FluxerAPIError as e:
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}).")
    return {"ok": True}


@app.post("/api/guilds/{guild_id}/members/{user_id}/ban")
async def api_ban_member(request: Request, guild_id: str, user_id: str, payload: MemberActionPayload):
    await _require_manage(request, guild_id)
    moderator = _moderator_from_session(request)
    user = await _fetch_member_user(guild_id, user_id)
    try:
        await moderation_actions.ban_member(bot_rest, guild_id, user, moderator, payload.reason or "No reason provided")
    except ModerationBlocked as e:
        raise _ApiError(403, str(e))
    except FluxerAPIError as e:
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}).")
    return {"ok": True}


@app.post("/api/guilds/{guild_id}/members/{user_id}/timeout")
async def api_timeout_member(request: Request, guild_id: str, user_id: str, payload: TimeoutPayload):
    await _require_manage(request, guild_id)
    moderator = _moderator_from_session(request)
    user = await _fetch_member_user(guild_id, user_id)
    if payload.duration_seconds <= 0:
        raise _ApiError(400, "Duration must be positive.")
    try:
        await moderation_actions.timeout_member(bot_rest, guild_id, user, moderator,
                                                  payload.duration_seconds, payload.reason or "No reason provided")
    except ModerationBlocked as e:
        raise _ApiError(403, str(e))
    except FluxerAPIError as e:
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}).")
    return {"ok": True}


@app.post("/api/guilds/{guild_id}/members/{user_id}/untimeout")
async def api_untimeout_member(request: Request, guild_id: str, user_id: str, payload: MemberActionPayload):
    await _require_manage(request, guild_id)
    moderator = _moderator_from_session(request)
    user = await _fetch_member_user(guild_id, user_id)
    try:
        await moderation_actions.untimeout_member(bot_rest, guild_id, user, moderator, payload.reason)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}).")
    return {"ok": True}


@app.post("/api/guilds/{guild_id}/members/{user_id}/warn")
async def api_warn_member(request: Request, guild_id: str, user_id: str, payload: MemberActionPayload):
    await _require_manage(request, guild_id)
    moderator = _moderator_from_session(request)
    user = await _fetch_member_user(guild_id, user_id)
    try:
        result = await moderation_actions.warn_member(bot_rest, guild_id, user, moderator,
                                                        payload.reason or "No reason provided")
    except ModerationBlocked as e:
        raise _ApiError(403, str(e))
    except FluxerAPIError as e:
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}).")
    response = await _warnings_response(guild_id)
    return {"result": result, **response}


# --------------------------------------------------------------- staff notes --
def _note_to_json(row) -> dict:
    return {
        "id": row["id"], "user_id": row["user_id"], "note": row["note"],
        "created_by": row["created_by"], "created_at": row["created_at"].isoformat(),
    }


class NoteCreatePayload(BaseModel):
    note: str


@app.get("/api/guilds/{guild_id}/members/{user_id}/notes")
async def api_list_member_notes(request: Request, guild_id: str, user_id: str):
    await _require_manage(request, guild_id)
    rows = await db.list_staff_notes(guild_id, user_id)
    return {"notes": [_note_to_json(r) for r in rows]}


@app.post("/api/guilds/{guild_id}/members/{user_id}/notes")
async def api_add_member_note(request: Request, guild_id: str, user_id: str, payload: NoteCreatePayload):
    await _require_manage(request, guild_id)
    user = require_login(request)
    text = payload.note.strip()
    if not text:
        raise _ApiError(400, "Give the note some content.")
    await db.add_staff_note(guild_id, user_id, text, str(user.get("id")))
    rows = await db.list_staff_notes(guild_id, user_id)
    return {"notes": [_note_to_json(r) for r in rows]}


@app.delete("/api/guilds/{guild_id}/members/{user_id}/notes/{note_id}")
async def api_remove_member_note(request: Request, guild_id: str, user_id: str, note_id: int):
    await _require_manage(request, guild_id)
    await db.remove_staff_note(guild_id, note_id)
    rows = await db.list_staff_notes(guild_id, user_id)
    return {"notes": [_note_to_json(r) for r in rows]}


# ---------------------------------------------------------------------- tags --
class TagCreatePayload(BaseModel):
    name: str
    content: str


@app.post("/api/guilds/{guild_id}/tags")
async def api_add_tag(request: Request, guild_id: str, payload: TagCreatePayload):
    await _require_manage(request, guild_id)
    user = require_login(request)
    name = payload.name.strip().lower()
    content = payload.content.strip()
    if not name or not content:
        raise _ApiError(400, "Give a tag name and content.")
    if name in {c.name for c in COMMAND_CATALOG}:
        raise _ApiError(400, f'"{name}" is already a built-in command name, pick another.')
    await db.add_tag(guild_id, name, content, str(user.get("id")))
    return {"tags": [_tag_to_json(t) for t in await db.list_tags(guild_id)]}


@app.delete("/api/guilds/{guild_id}/tags/{tag_name}")
async def api_remove_tag(request: Request, guild_id: str, tag_name: str):
    await _require_manage(request, guild_id)
    await db.remove_tag(guild_id, tag_name)
    return {"tags": [_tag_to_json(t) for t in await db.list_tags(guild_id)]}


# --------------------------------------------------------------------- stats --
# Several pages (Overview, Warnings/Mod Log, Reports, the Levels leaderboard)
# resolve usernames for display, and every one of them is behind the 8s
# background poll in GuildDetail.jsx -- without a cache, a server with a
# long warnings/actions/reports history re-issues one REST call PER UNIQUE
# USER on every single poll tick, forever, just to keep re-displaying the
# same names. A short TTL (comfortably longer than the poll interval, so
# most ticks hit cache) cuts that down close to one real lookup per user
# per TTL window regardless of how many times the page polls in between.
_USERNAME_CACHE_TTL = 60  # seconds
_username_cache: BoundedDict[tuple[str, str], tuple[str, float]] = BoundedDict(max_size=5000)


async def _resolve_usernames(guild_id: str, user_ids: list[str]) -> dict[str, str]:
    """Best-effort user_id -> username lookup via the bot's own REST
    connection, so lists show names instead of raw snowflakes. Falls back
    to the raw ID per-user if that lookup fails (e.g. they left the
    server) rather than failing the whole request."""
    now = time.monotonic()

    async def _one(uid: str) -> tuple[str, str]:
        cached = _username_cache.get((guild_id, uid))
        if cached and (now - cached[1]) < _USERNAME_CACHE_TTL:
            return uid, cached[0]
        try:
            member = await bot_rest.get_guild_member(guild_id, uid)
            username = member.get("user", member).get("username", uid)
        except FluxerAPIError:
            username = uid
        _username_cache[(guild_id, uid)] = (username, now)
        return uid, username

    results = await asyncio.gather(*(_one(uid) for uid in user_ids))
    return dict(results)


async def _warnings_response(guild_id: str) -> dict:
    warnings = await db.list_warnings(guild_id)
    all_ids = list({w["user_id"] for w in warnings} | {w["moderator_id"] for w in warnings})
    names = await _resolve_usernames(guild_id, all_ids)
    return {
        "warnings": [_warning_to_json(w, names) for w in warnings],
        "active_warning_count": sum(1 for w in warnings if w["active"]),
    }


@app.get("/api/guilds/{guild_id}/stats")
async def api_guild_stats(request: Request, guild_id: str, days: int = 14):
    await _require_manage(request, guild_id)
    days = max(1, min(90, days))
    daily = await db.get_daily_stats(guild_id, days)
    top_members = await db.get_top_members(guild_id, 5)
    top_voice_members = await db.get_top_voice_members(guild_id, 5)
    total = await db.get_total_messages(guild_id, 30)
    top_commands = await db.get_top_commands(guild_id, 8)
    heatmap = await db.get_activity_heatmap(guild_id)

    all_ids = list({r["user_id"] for r in top_members} | {r["user_id"] for r in top_voice_members})
    names = await _resolve_usernames(guild_id, all_ids)

    return {
        "daily": [
            {"date": r["day"].isoformat(), "count": r["message_count"], "voice_minutes": round(float(r["voice_minutes"]))}
            for r in daily
        ],
        "top_members": [
            {"user_id": r["user_id"], "username": names.get(r["user_id"], r["user_id"]), "count": r["message_count"]}
            for r in top_members
        ],
        "top_voice_members": [
            {"user_id": r["user_id"], "username": names.get(r["user_id"], r["user_id"]),
             "minutes": round(float(r["minutes"]))}
            for r in top_voice_members
        ],
        "total_messages_30d": total,
        "top_commands": [{"name": r["command_name"], "count": r["count"]} for r in top_commands],
        # day_of_week follows Postgres's EXTRACT(DOW ...) convention:
        # 0 = Sunday ... 6 = Saturday. Same as JS's Date#getDay(), so the
        # frontend can index straight into it without remapping.
        "heatmap": [{"day": r["day_of_week"], "hour": r["hour"], "count": r["message_count"]} for r in heatmap],
    }


# ----------------------------------------------------------------- leveling --
def _level_to_json(row, username: str) -> dict:
    return {
        "user_id": row["user_id"], "username": username, "xp": row["xp"], "level": row["level"],
        "title": leveling.title_for_level(row["level"]),
    }


def _level_role_to_json(row) -> dict:
    return {"id": row["id"], "level": row["level"], "role_id": row["role_id"]}


@app.get("/api/guilds/{guild_id}/levels")
async def api_guild_levels(request: Request, guild_id: str):
    await _require_manage(request, guild_id)
    leaderboard = await db.get_leaderboard(guild_id, 20)
    level_roles_list = await db.list_level_roles(guild_id)
    names = await _resolve_usernames(guild_id, [r["user_id"] for r in leaderboard])
    excluded_channels = await db.list_xp_excluded_channels(guild_id)
    multipliers = await db.list_xp_role_multipliers(guild_id)
    return {
        "leaderboard": [_level_to_json(r, names.get(r["user_id"], r["user_id"])) for r in leaderboard],
        "level_roles": [_level_role_to_json(r) for r in level_roles_list],
        "excluded_channels": excluded_channels,
        "role_multipliers": [{"role_id": r["role_id"], "multiplier": float(r["multiplier"])} for r in multipliers],
    }


class LevelRolePayload(BaseModel):
    level: int
    role_id: str


@app.post("/api/guilds/{guild_id}/level-roles")
async def api_add_level_role(request: Request, guild_id: str, payload: LevelRolePayload):
    await _require_manage(request, guild_id)
    if payload.level < 1:
        raise _ApiError(400, "Level must be 1 or higher.")
    role_id = payload.role_id.strip()
    try:
        guild = await bot_rest.get_guild(guild_id)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Couldn't verify that role (HTTP {e.status}).")
    if role_is_privileged(guild, role_id):
        raise _ApiError(400, "That role carries moderation/admin permissions, level-up rewards can't grant it "
                              "automatically to anyone who levels up. Assign it manually instead.")
    await db.add_level_role(guild_id, payload.level, role_id)
    return {"level_roles": [_level_role_to_json(r) for r in await db.list_level_roles(guild_id)]}


@app.delete("/api/guilds/{guild_id}/level-roles/{level}")
async def api_remove_level_role(request: Request, guild_id: str, level: int):
    await _require_manage(request, guild_id)
    await db.remove_level_role(guild_id, level)
    return {"level_roles": [_level_role_to_json(r) for r in await db.list_level_roles(guild_id)]}


class XpExcludedChannelPayload(BaseModel):
    channel_id: str


@app.post("/api/guilds/{guild_id}/levels/excluded-channels")
async def api_add_xp_excluded_channel(request: Request, guild_id: str, payload: XpExcludedChannelPayload):
    await _require_manage(request, guild_id)
    channel_id = payload.channel_id.strip()
    if not channel_id.isdigit():
        raise _ApiError(400, "Channel ID must be numeric.")
    await db.add_xp_excluded_channel(guild_id, channel_id)
    return {"excluded_channels": await db.list_xp_excluded_channels(guild_id)}


@app.delete("/api/guilds/{guild_id}/levels/excluded-channels/{channel_id}")
async def api_remove_xp_excluded_channel(request: Request, guild_id: str, channel_id: str):
    await _require_manage(request, guild_id)
    await db.remove_xp_excluded_channel(guild_id, channel_id)
    return {"excluded_channels": await db.list_xp_excluded_channels(guild_id)}


class XpMultiplierPayload(BaseModel):
    role_id: str
    multiplier: float


@app.post("/api/guilds/{guild_id}/levels/multipliers")
async def api_set_xp_multiplier(request: Request, guild_id: str, payload: XpMultiplierPayload):
    await _require_manage(request, guild_id)
    if payload.multiplier <= 0 or payload.multiplier > 10:
        raise _ApiError(400, "Multiplier must be greater than 0 and at most 10.")
    await db.set_xp_role_multiplier(guild_id, payload.role_id, payload.multiplier)
    rows = await db.list_xp_role_multipliers(guild_id)
    return {"role_multipliers": [{"role_id": r["role_id"], "multiplier": float(r["multiplier"])} for r in rows]}


@app.delete("/api/guilds/{guild_id}/levels/multipliers/{role_id}")
async def api_remove_xp_multiplier(request: Request, guild_id: str, role_id: str):
    await _require_manage(request, guild_id)
    await db.remove_xp_role_multiplier(guild_id, role_id)
    rows = await db.list_xp_role_multipliers(guild_id)
    return {"role_multipliers": [{"role_id": r["role_id"], "multiplier": float(r["multiplier"])} for r in rows]}


async def _leaderboard_response(guild_id: str) -> dict:
    leaderboard = await db.get_leaderboard(guild_id, 20)
    names = await _resolve_usernames(guild_id, [r["user_id"] for r in leaderboard])
    return {"leaderboard": [_level_to_json(r, names.get(r["user_id"], r["user_id"])) for r in leaderboard]}


@app.post("/api/guilds/{guild_id}/levels/{user_id}/reset")
async def api_reset_user_xp(request: Request, guild_id: str, user_id: str):
    await _require_manage(request, guild_id)
    user = require_login(request)
    await db.reset_user_xp(guild_id, user_id)
    await db.log_action(guild_id, "xp_reset", user_id=user_id, moderator_id=str(user.get("id")),
                         reason="Reset this member's XP/level via dashboard")
    return await _leaderboard_response(guild_id)


class XpAdjustPayload(BaseModel):
    amount: int


@app.post("/api/guilds/{guild_id}/levels/{user_id}/adjust")
async def api_adjust_user_xp(request: Request, guild_id: str, user_id: str, payload: XpAdjustPayload):
    await _require_manage(request, guild_id)
    user = require_login(request)
    if payload.amount == 0:
        raise _ApiError(400, "Give a non-zero amount to add or remove.")
    row = await db.adjust_xp(guild_id, user_id, payload.amount)
    new_level = leveling.level_for_xp(row["xp"])
    await db.set_level(guild_id, user_id, new_level)
    verb = "Added" if payload.amount > 0 else "Removed"
    await db.log_action(guild_id, "xp_adjust", user_id=user_id, moderator_id=str(user.get("id")),
                         reason=f"{verb} {abs(payload.amount)} XP via dashboard")
    return await _leaderboard_response(guild_id)


# --------------------------------------------------------------------- embed --
# Discord's own embed limits, enforced here too so a bad submission gets a
# clear 400 from us instead of an opaque 502 from Fluxer rejecting the whole
# message.
_EMBED_MAX_FIELDS = 25
_EMBED_FIELD_NAME_MAX = 256
_EMBED_FIELD_VALUE_MAX = 1024
_EMBED_TITLE_MAX = 256
_EMBED_DESCRIPTION_MAX = 4096
_EMBED_FOOTER_MAX = 2048
_EMBED_AUTHOR_NAME_MAX = 256
_FORUM_POST_TITLE_MAX = 100  # Fluxer's "start thread" name field, 1-100 chars


class EmbedFieldPayload(BaseModel):
    name: str = ""
    value: str = ""
    inline: bool = False


class EmbedPayload(BaseModel):
    channel_id: str
    post_title: str = ""  # required only when channel_id is a forum/media channel
    title: str = ""
    description: str = ""
    url: str = ""
    color: str = "5865F2"
    image_url: str = ""
    thumbnail_url: str = ""
    footer: str = ""
    author_name: str = ""
    author_icon_url: str = ""
    author_url: str = ""
    timestamp: bool = False
    fields: list[EmbedFieldPayload] = []


def _validate_embed_payload(payload: EmbedPayload) -> None:
    """Pulled out of api_send_embed so it's callable (and testable)
    without the request/session/auth machinery around the endpoint
    itself. Discord's own embed limits, enforced here too so a bad
    submission gets a clear 400 from us instead of an opaque 502 from
    Fluxer rejecting the whole message."""
    channel_id = payload.channel_id.strip()
    if not channel_id.isdigit() or not (payload.title.strip() or payload.description.strip()):
        raise _ApiError(400, "Give a channel and at least a title or description.")
    if len(payload.fields) > _EMBED_MAX_FIELDS:
        raise _ApiError(400, f"An embed can only have up to {_EMBED_MAX_FIELDS} fields.")
    if len(payload.title.strip()) > _EMBED_TITLE_MAX:
        raise _ApiError(400, f"Title is too long (max {_EMBED_TITLE_MAX} characters).")
    if len(payload.description.strip()) > _EMBED_DESCRIPTION_MAX:
        raise _ApiError(400, f"Description is too long (max {_EMBED_DESCRIPTION_MAX} characters).")
    if len(payload.footer.strip()) > _EMBED_FOOTER_MAX:
        raise _ApiError(400, f"Footer is too long (max {_EMBED_FOOTER_MAX} characters).")
    if len(payload.author_name.strip()) > _EMBED_AUTHOR_NAME_MAX:
        raise _ApiError(400, f"Author name is too long (max {_EMBED_AUTHOR_NAME_MAX} characters).")


@app.post("/api/guilds/{guild_id}/embed")
async def api_send_embed(request: Request, guild_id: str, payload: EmbedPayload):
    await _require_manage(request, guild_id)
    user = require_login(request)
    _validate_embed_payload(payload)
    channel_id = payload.channel_id.strip()

    embed: dict = {"color": _parse_embed_color(payload.color)}
    if payload.title.strip():
        embed["title"] = payload.title.strip()
    if payload.description.strip():
        embed["description"] = payload.description.strip()
    if payload.url.strip():
        embed["url"] = payload.url.strip()
    if payload.image_url.strip():
        embed["image"] = {"url": payload.image_url.strip()}
    if payload.thumbnail_url.strip():
        embed["thumbnail"] = {"url": payload.thumbnail_url.strip()}
    if payload.footer.strip():
        embed["footer"] = {"text": payload.footer.strip()}
    if payload.author_name.strip():
        author: dict = {"name": payload.author_name.strip()}
        if payload.author_icon_url.strip():
            author["icon_url"] = payload.author_icon_url.strip()
        if payload.author_url.strip():
            author["url"] = payload.author_url.strip()
        embed["author"] = author
    if payload.timestamp:
        embed["timestamp"] = datetime.now(timezone.utc).isoformat()

    fields = []
    for i, f in enumerate(payload.fields):
        name, value = f.name.strip(), f.value.strip()
        if not name and not value:
            continue  # a field row left blank, not an error, just skip it
        if not name or not value:
            raise _ApiError(400, f"Field {i + 1} needs both a name and a value.")
        if len(name) > _EMBED_FIELD_NAME_MAX or len(value) > _EMBED_FIELD_VALUE_MAX:
            raise _ApiError(400, f"Field {i + 1}'s name/value is too long "
                                  f"(max {_EMBED_FIELD_NAME_MAX}/{_EMBED_FIELD_VALUE_MAX} characters).")
        fields.append({"name": name, "value": value, "inline": f.inline})
    if fields:
        embed["fields"] = fields

    # Forum/media channels don't take a plain message (see
    # _POST_ONLY_CHANNEL_TYPES above), they need a named post instead.
    # Re-fetching the guild here (rather than trusting a type the client
    # sent) means a stale/forged channel_id still gets the right call,
    # and a channel that's vanished since the picker loaded fails with a
    # clear error instead of silently posting nowhere.
    try:
        guild = await bot_rest.get_guild(guild_id)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Couldn't verify that channel with Fluxer (HTTP {e.status}).")
    channel_type = next(
        (c.get("type") for c in guild.get("channels", []) if str(c.get("id")) == channel_id), None,
    )

    try:
        if channel_type in _POST_ONLY_CHANNEL_TYPES:
            post_title = payload.post_title.strip()
            if not post_title:
                raise _ApiError(400, "That's a forum/media channel, give the post a title.")
            if len(post_title) > _FORUM_POST_TITLE_MAX:
                raise _ApiError(400, f"Post title is too long (max {_FORUM_POST_TITLE_MAX} characters).")
            await bot_rest.start_forum_post(channel_id, name=post_title, embeds=[embed])
        else:
            await bot_rest.send_message(channel_id, embeds=[embed])
    except FluxerAPIError as e:
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}), check the bot can post in that channel.")

    await db.log_action(guild_id, "send_embed", moderator_id=str(user.get("id")),
                         reason=f"Sent an embed to <#{channel_id}>")
    return {"ok": True}


# ------------------------------------------------------------ danger zone --
@app.post("/api/guilds/{guild_id}/danger/clear-all-warnings")
async def api_danger_clear_all_warnings(request: Request, guild_id: str):
    await _require_manage(request, guild_id)
    user = require_login(request)
    count = await db.clear_all_warnings(guild_id)
    await db.log_action(guild_id, "danger_clear_warnings", moderator_id=str(user.get("id")),
                         reason=f"Cleared {count} active warning(s) server-wide via Danger Zone")
    return {"cleared": count}


@app.post("/api/guilds/{guild_id}/danger/reset-all-xp")
async def api_danger_reset_all_xp(request: Request, guild_id: str):
    await _require_manage(request, guild_id)
    user = require_login(request)
    count = await db.reset_all_xp(guild_id)
    await db.log_action(guild_id, "danger_reset_xp", moderator_id=str(user.get("id")),
                         reason=f"Reset XP/levels for {count} member(s) via Danger Zone")
    return {"reset": count}


@app.post("/api/guilds/{guild_id}/danger/wipe-reaction-roles")
async def api_danger_wipe_reaction_roles(request: Request, guild_id: str):
    await _require_manage(request, guild_id)
    user = require_login(request)
    count = await db.wipe_all_reaction_roles(guild_id)
    await db.log_action(guild_id, "danger_wipe_reaction_roles", moderator_id=str(user.get("id")),
                         reason=f"Wiped {count} reaction-role mapping(s) via Danger Zone")
    return {"wiped": count, "reaction_roles": []}


# ---------------------------------------------------------------- bot profile --
_ALLOWED_AVATAR_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MAX_AVATAR_BYTES = 8 * 1024 * 1024  # 8 MiB, matches Discord's own avatar upload cap


@app.post("/api/bot-profile/avatar")
async def api_set_bot_avatar(request: Request, file: UploadFile = File(...)):
    _require_owner(request)
    if file.content_type not in _ALLOWED_AVATAR_TYPES:
        raise _ApiError(400, "Only PNG, JPEG, or WEBP images are accepted.")
    data = await file.read()
    if len(data) > _MAX_AVATAR_BYTES:
        raise _ApiError(400, "That image is too large (8 MiB max).")
    if not data:
        raise _ApiError(400, "That file is empty.")

    # The dashboard's own favicon/branding is a purely local asset, it
    # doesn't need Fluxer's cooperation at all, so it's stored and
    # served unconditionally once the image itself is valid. Setting
    # the bot's actual Fluxer avatar (a separate concern entirely, that
    # image showing up as the bot's profile picture on Fluxer) is
    # attempted as best-effort below and reported back on its own,
    # rather than blocking the favicon update if it fails, e.g. some
    # instances currently reject this call outright (see
    # oauth.update_bot_avatar's docstring), and there's no reason a
    # Fluxer-side rejection should prevent updating this site's own
    # favicon, someone can always set the bot's actual Fluxer avatar by
    # hand from Fluxer's own Bot Application page in the meantime.
    await db.set_bot_avatar(data, file.content_type)

    fluxer_updated = False
    fluxer_error: Optional[str] = None
    access_token = request.session.get("access_token")
    if not access_token:
        fluxer_error = "Not logged in with a Fluxer session, favicon updated, bot avatar not attempted."
    else:
        try:
            # Fluxer's own docs put the bot's avatar under the
            # application's bot-profile endpoint, not the generic user
            # profile, and that endpoint is Bearer-authenticated as
            # whoever owns the application (this session), not the
            # bot's own Bot token, see oauth.update_bot_avatar's
            # docstring for the full story.
            bot_user = await bot_rest.get_current_user()
            application_id = str(bot_user["id"])
            avatar_base64 = base64.b64encode(data).decode("ascii")
            await oauth.update_bot_avatar(access_token, application_id, avatar_base64)
            fluxer_updated = True
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:300] if e.response is not None else ""
            fluxer_error = f"Fluxer rejected that image (HTTP {e.response.status_code}): {detail}"
        except FluxerAPIError as e:
            fluxer_error = f"Couldn't look up the bot's own account (HTTP {e.status}): {str(e.body)[:300]}"

    return {"ok": True, "fluxer_updated": fluxer_updated, "fluxer_error": fluxer_error}


async def _serve_bot_avatar_or_default() -> Response:
    """Shared by /favicon.ico and /api/bot-profile/icon: both display the
    same uploaded image (or the same static default if nothing's been
    uploaded yet), just in two different UI spots (the browser tab and
    the dashboard's own top bar)."""
    row = await db.get_bot_avatar()
    if row:
        return Response(content=bytes(row["avatar_bytes"]), media_type=row["avatar_mimetype"])
    static_favicon = FRONTEND_DIST / "favicon.svg"
    if static_favicon.is_file():
        return Response(content=static_favicon.read_bytes(), media_type="image/svg+xml")
    return Response(status_code=404)


@app.get("/favicon.ico")
async def favicon():
    """Serves the same image set via /api/bot-profile/avatar, so uploading
    a new bot avatar updates the browser tab icon too without a frontend
    rebuild. Falls back to the static default if nothing's been uploaded
    yet."""
    return await _serve_bot_avatar_or_default()


@app.get("/api/bot-profile/icon")
async def bot_profile_icon():
    """Same image as the favicon, served under a stable, semantically
    clear path for the dashboard's own UI to reference directly (the
    small icon next to the bot's name in the top bar), rather than
    pointing app code at the browser-tab-icon convention. No auth
    required: this is the same image already publicly visible as the
    favicon and, once set, as the bot's own Fluxer avatar, nothing
    sensitive about serving it here too."""
    return await _serve_bot_avatar_or_default()


# ---------------------------------------------------------- discord relay --
# Discord CDN domains a proxied avatar URL is allowed to come from. This
# endpoint is public (no auth, same reasoning as the icon/favicon routes
# above: it's re-serving a public image, nothing sensitive), so it's
# critical this stays a strict allowlist rather than an open fetch of
# whatever URL is given, an open proxy on a public-facing service is a
# real SSRF vector (scanning internal network resources, hitting this
# same host's own other services, etc), not just a theoretical concern.
_DISCORD_CDN_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}


@app.get("/api/discord-relay/avatar-proxy")
async def discord_avatar_proxy(url: str):
    """Re-hosts a Discord avatar under this dashboard's own domain, for
    bot/discord_relay.py to hand to Fluxer instead of Discord's raw CDN
    link directly. See that module's docstring on why: Fluxer's webhook
    avatar_url apparently can't (or doesn't reliably) fetch directly
    from Discord's CDN, going the other way works fine, an avatar url
    already reachable from this same dashboard's own domain looks no
    different to Fluxer than any other URL it already successfully
    fetches from this app.

    This is a public, unauthenticated endpoint fetching a URL supplied
    in the request, exactly the shape CodeQL's SSRF query looks for, so
    it needs to actually close that off, not just look validated:
    is_safe_external_url restricts the host to Discord's real CDN
    domains (exact match, both required to also be https), and
    follow_redirects is explicitly disabled, an allowlisted host still
    issuing a redirect elsewhere is exactly the gap a hostname check
    alone can't close, this closes it by simply never following one."""
    if not is_safe_external_url(url, allowed_hosts=_DISCORD_CDN_HOSTS, require_https=True):
        raise _ApiError(400, "That's not a Discord CDN URL.")
    try:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            resp = await client.get(url, timeout=10)
    except httpx.HTTPError:
        raise _ApiError(502, "Couldn't reach Discord's CDN right now.")
    if resp.status_code != 200:
        raise _ApiError(502, f"Discord's CDN returned HTTP {resp.status_code} for that avatar.")
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/png"))


@app.get("/api/discord-relay/config")
async def api_get_discord_relay_config(request: Request):
    _require_owner(request)
    token = await db.get_discord_relay_token()
    status = await db.get_discord_relay_status()
    return {
        # Never the token value itself, write-only from the API's
        # perspective, only whether one is actually set right now, and
        # from which source (dashboard takes precedence over .env).
        "token_configured": bool(token or config.discord_bot_token),
        "token_source": "dashboard" if token else ("env" if config.discord_bot_token else None),
        "status": {
            "connected": status["connected"] if status else False,
            "discord_username": status["discord_username"] if status else None,
            "last_connected_at": status["last_connected_at"].isoformat() if status and status["last_connected_at"] else None,
            "last_error": status["last_error"] if status else None,
            "last_error_at": status["last_error_at"].isoformat() if status and status["last_error_at"] else None,
        } if status or token or config.discord_bot_token else None,
    }


class DiscordRelayTokenPayload(BaseModel):
    token: str = ""


@app.post("/api/discord-relay/config")
async def api_set_discord_relay_token(request: Request, payload: DiscordRelayTokenPayload):
    _require_owner(request)
    token = payload.token.strip()
    await db.set_discord_relay_token(token or None)
    return {"ok": True}


@app.get("/api/fluxer-stats")
async def api_fluxer_stats(request: Request):
    """Full Node Statistics Object for the owner-only Fluxer Status page.
    Owner-gated (not just any guild manager) because this is real
    platform infrastructure detail, memory/process/node breakdown, not
    something any particular guild's moderators need or should see.
    The small health pill on each guild's Overview tab gets only the
    coarse "status" word, from api_guild_detail above, not this."""
    _require_owner(request)
    stats = await fluxer_admin.get_gateway_stats()
    if stats is None:
        raise _ApiError(400, "FLUXER_ADMIN_API_KEY isn't configured. Add it to your .env to see Fluxer server "
                              "stats here (see .env.example for how to generate one).")
    return stats


# ------------------------------------------------------ serve the frontend --
def resolve_frontend_path(full_path: str) -> Path:
    """Resolves full_path against FRONTEND_DIST for the SPA catch-all
    below, returning FRONTEND_DIST's own index.html instead whenever the
    result doesn't check out, so callers can always just FileResponse()
    whatever this returns without a separate safety check of their own.

    SECURITY: full_path is attacker-controlled. A naive
    `FRONTEND_DIST / full_path` join is vulnerable to path traversal,
    percent-encoded slashes (e.g. `..%2f..%2f.env`) bypass most
    request-path normalization done earlier in the stack and reach this
    function with literal `..` segments intact. Resolving the joined
    path and explicitly verifying it's still inside FRONTEND_DIST,
    rather than trusting the join result directly, defeats that
    regardless of how the traversal sequence got here, pulled out into
    its own function (importable and testable without a built frontend
    needing to exist on disk) specifically so that claim has a test
    behind it instead of just a comment.
    """
    base = FRONTEND_DIST.resolve()
    candidate = (FRONTEND_DIST / full_path).resolve()
    if full_path and candidate.is_relative_to(base) and candidate.is_file():
        return candidate
    return FRONTEND_DIST / "index.html"


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Catch-all so React Router's client-side routes (e.g. /guild/123)
        work on a hard refresh too, anything not matched above falls
        through to index.html and the SPA takes over routing. See
        resolve_frontend_path() for the path-traversal guard."""
        return FileResponse(resolve_frontend_path(full_path))
else:
    @app.get("/")
    async def frontend_not_built():
        return JSONResponse(
            {"detail": "Frontend isn't built yet. Run `npm install && npm run build` in "
                       "dashboard-frontend/, then restart the dashboard."},
            status_code=503,
        )
