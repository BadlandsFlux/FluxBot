from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from bot import moderation_actions
from bot import voice_tracker
from bot.commands import Bot as BotFramework
from bot.modules import fun, info as info_module, leveling, moderation, reminders, roles, tags, utility
from bot.modules import afk as afk_module
from bot.permissions import permission_name
from bot.rest import FluxerAPIError, FluxerREST
from common import db
from common.config import config
from common.discovery import get_media_base, guild_icon_url
from dashboard import oauth

log = logging.getLogger("fluxbot.dashboard")

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = BASE_DIR.parent / "dashboard-frontend" / "dist"

# A REST client authenticated as the bot itself — used for dashboard actions
# that need to act *as* the bot (sending the reaction-role embed message,
# reacting to it). This talks to Fluxer over plain HTTP; it doesn't need the
# bot's gateway connection, so it works whether or not the bot process is
# currently running.
bot_rest = FluxerREST(config.bot_token)


def _build_command_catalog() -> list:
    """Build the command list by actually registering every command module
    against a throwaway Bot instance — so /api/commands can never drift from
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
    afk_module.register(catalog_bot)
    seen = set()
    commands = []
    for cmd in catalog_bot.commands.values():
        if cmd.name in seen:
            continue
        seen.add(cmd.name)
        commands.append(cmd)
    return sorted(commands, key=lambda c: (c.category, c.name))


COMMAND_CATALOG = _build_command_catalog()


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_session_secret()
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
    except httpx.HTTPStatusError:
        raise _ApiError(502, "Couldn't verify your Fluxer permissions right now.")
    entry = next((g for g in my_guilds if str(g.get("id")) == guild_id), None)
    if not entry or not oauth.can_manage(entry):
        raise _ApiError(403, "You don't have permission to manage this server.")


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
        return RedirectResponse(f"/?login_error={error}")
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
    return {"user": user, "bot_name": config.bot_name}


@app.get("/api/guilds")
async def api_guilds(request: Request):
    require_login(request)
    access_token = request.session.get("access_token")
    try:
        my_guilds = await oauth.fetch_my_guilds(access_token)
    except httpx.HTTPStatusError:
        my_guilds = []

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
    }


def _warning_to_json(row) -> dict:
    return {
        "id": row["id"], "user_id": row["user_id"], "moderator_id": row["moderator_id"],
        "reason": row["reason"], "active": row["active"],
        "created_at": row["created_at"].isoformat(),
    }


def _action_to_json(row) -> dict:
    return {
        "id": row["id"], "user_id": row["user_id"], "moderator_id": row["moderator_id"],
        "action": row["action"], "reason": row["reason"],
        "created_at": row["created_at"].isoformat(),
    }


def _reaction_role_to_json(row) -> dict:
    return {
        "id": row["id"], "channel_id": row["channel_id"], "message_id": row["message_id"],
        "emoji": row["emoji"], "role_id": row["role_id"], "label": row["label"],
    }


def _tag_to_json(row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "content": row["content"],
        "created_by": row["created_by"], "created_at": row["created_at"].isoformat(),
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

    return {
        "guild": _guild_to_json(guild_cfg),
        "actions": [_action_to_json(a) for a in actions],
        "warnings": [_warning_to_json(w) for w in warnings],
        "autoroles": autoroles,
        "reaction_roles": [_reaction_role_to_json(r) for r in reaction_roles],
        "tags": [_tag_to_json(t) for t in guild_tags],
        "active_warning_count": sum(1 for w in warnings if w["active"]),
    }


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
    warn_timeout_at: int = 3
    warn_kick_at: int = 5
    warn_timeout_minutes: int = 60


@app.post("/api/guilds/{guild_id}/settings")
async def api_update_settings(request: Request, guild_id: str, payload: SettingsPayload):
    await _require_manage(request, guild_id)
    prefix = (payload.command_prefix or "!").strip()[:5] or "!"
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
        warn_timeout_at=payload.warn_timeout_at,
        warn_kick_at=payload.warn_kick_at,
        warn_timeout_minutes=payload.warn_timeout_minutes,
    )
    guild_cfg = await db.get_guild(guild_id)
    return {"guild": _guild_to_json(guild_cfg)}


@app.post("/api/guilds/{guild_id}/warnings/{user_id}/clear")
async def api_clear_warnings(request: Request, guild_id: str, user_id: str):
    await _require_manage(request, guild_id)
    cleared = await db.clear_warnings(guild_id, user_id)
    warnings = await db.list_warnings(guild_id)
    return {
        "cleared": cleared,
        "warnings": [_warning_to_json(w) for w in warnings],
        "active_warning_count": sum(1 for w in warnings if w["active"]),
    }


class AutoroleAddPayload(BaseModel):
    role_id: str


@app.post("/api/guilds/{guild_id}/autoroles")
async def api_add_autorole(request: Request, guild_id: str, payload: AutoroleAddPayload):
    await _require_manage(request, guild_id)
    role_id = payload.role_id.strip()
    if not role_id.isdigit():
        raise _ApiError(400, "Role ID must be numeric — copy it from Fluxer with Developer Mode on.")
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


@app.post("/api/guilds/{guild_id}/reactionroles")
async def api_create_reaction_role(request: Request, guild_id: str, payload: ReactionRoleCreatePayload):
    await _require_manage(request, guild_id)
    channel_id = payload.channel_id.strip()
    pairs = [
        (p.emoji.strip(), p.label.strip(), p.role_id.strip())
        for p in payload.pairs if p.emoji.strip() and p.role_id.strip()
    ]
    if not channel_id.isdigit() or not pairs:
        raise _ApiError(400, "Give a channel ID and at least one emoji + role pair.")

    def _line(emoji: str, label: str, role: str) -> str:
        return f"{emoji} **{label}** — <@&{role}>" if label else f"{emoji} — <@&{role}>"

    lines = "\n".join(_line(emoji, label, role) for emoji, label, role in pairs)
    embed = {
        "title": payload.title or "Pick your roles",
        "description": (payload.description + "\n\n" if payload.description else "") + lines,
        "color": _parse_embed_color(payload.color),
    }

    failed_reactions: list[str] = []
    try:
        sent = await bot_rest.send_message(channel_id, embeds=[embed])
        message_id = str(sent["id"])
        for emoji, label, role_id in pairs:
            try:
                await bot_rest.add_reaction(channel_id, message_id, emoji)
            except FluxerAPIError:
                # Emoji format the instance expects may differ (unicode vs
                # custom emoji id) — the mapping is still stored below so
                # reactions added manually will still grant the role. We
                # surface this back to the dashboard instead of hiding it.
                failed_reactions.append(emoji)
            await db.add_reaction_role(guild_id, channel_id, message_id, emoji, role_id, label)
    except FluxerAPIError as e:
        log.warning("Failed to send reaction-role embed: %s", e)
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}) — check the bot can post in that channel.")

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


@app.get("/api/guilds/{guild_id}/channels")
async def api_guild_channels(request: Request, guild_id: str):
    """Powers the channel picker dropdowns (mod-log, welcome, reaction-role
    target channel)."""
    await _require_manage(request, guild_id)
    try:
        guild = await bot_rest.get_guild(guild_id)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Couldn't fetch channels from Fluxer (HTTP {e.status}).")
    # Best-effort text-channel filter: Discord-style type 0 = text. If an
    # instance omits `type` entirely we keep the channel rather than hide it.
    channels_list = [
        {"id": str(c["id"]), "name": c.get("name", "channel")}
        for c in guild.get("channels", [])
        if c.get("type") in (0, None)
    ]
    return {"channels": channels_list}


# ------------------------------------------------------------------ members --
@app.get("/api/guilds/{guild_id}/members")
async def api_guild_members(request: Request, guild_id: str, q: str = ""):
    """Best-effort member list/search. Fluxer's member-list endpoint (like
    Discord's) is paginated and capped per-request; this fetches one page
    (up to 500) and filters client-side-ish here, which comfortably covers
    small-to-medium communities. For very large servers this won't show
    every member — search by exact ID also works around that."""
    await _require_manage(request, guild_id)
    try:
        members = await bot_rest.list_guild_members(guild_id, limit=500)
    except FluxerAPIError as e:
        raise _ApiError(502, f"Couldn't fetch members from Fluxer (HTTP {e.status}).")

    q_lower = q.strip().lower()
    result = []
    for m in members:
        user = m.get("user", m)
        username = user.get("username", "")
        user_id = str(user.get("id"))
        if q_lower and q_lower not in username.lower() and q_lower != user_id:
            continue
        result.append({
            "id": user_id,
            "username": username,
            "avatar": user.get("avatar"),
            "roles": m.get("roles", []),
            "joined_at": m.get("joined_at"),
        })
    return {"members": result[:100]}


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
    result = await moderation_actions.warn_member(bot_rest, guild_id, user, moderator,
                                                    payload.reason or "No reason provided")
    warnings = await db.list_warnings(guild_id)
    return {
        "result": result,
        "warnings": [_warning_to_json(w) for w in warnings],
        "active_warning_count": sum(1 for w in warnings if w["active"]),
    }


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
        raise _ApiError(400, f'"{name}" is already a built-in command name — pick another.')
    await db.add_tag(guild_id, name, content, str(user.get("id")))
    return {"tags": [_tag_to_json(t) for t in await db.list_tags(guild_id)]}


@app.delete("/api/guilds/{guild_id}/tags/{tag_name}")
async def api_remove_tag(request: Request, guild_id: str, tag_name: str):
    await _require_manage(request, guild_id)
    await db.remove_tag(guild_id, tag_name)
    return {"tags": [_tag_to_json(t) for t in await db.list_tags(guild_id)]}


# --------------------------------------------------------------------- stats --
async def _resolve_usernames(guild_id: str, user_ids: list[str]) -> dict[str, str]:
    """Best-effort user_id -> username lookup via the bot's own REST
    connection, so lists show names instead of raw snowflakes. Falls back
    to the raw ID per-user if that lookup fails (e.g. they left the
    server) rather than failing the whole request."""
    async def _one(uid: str) -> tuple[str, str]:
        try:
            member = await bot_rest.get_guild_member(guild_id, uid)
            return uid, member.get("user", member).get("username", uid)
        except FluxerAPIError:
            return uid, uid

    results = await asyncio.gather(*(_one(uid) for uid in user_ids))
    return dict(results)


@app.get("/api/guilds/{guild_id}/stats")
async def api_guild_stats(request: Request, guild_id: str, days: int = 14):
    await _require_manage(request, guild_id)
    days = max(1, min(90, days))
    daily = await db.get_daily_stats(guild_id, days)
    top_members = await db.get_top_members(guild_id, 5)
    top_voice_members = await db.get_top_voice_members(guild_id, 5)
    total = await db.get_total_messages(guild_id, 30)

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
    }


# ----------------------------------------------------------------- leveling --
def _level_to_json(row, username: str) -> dict:
    return {"user_id": row["user_id"], "username": username, "xp": row["xp"], "level": row["level"]}


def _level_role_to_json(row) -> dict:
    return {"id": row["id"], "level": row["level"], "role_id": row["role_id"]}


@app.get("/api/guilds/{guild_id}/levels")
async def api_guild_levels(request: Request, guild_id: str):
    await _require_manage(request, guild_id)
    leaderboard = await db.get_leaderboard(guild_id, 20)
    level_roles_list = await db.list_level_roles(guild_id)
    names = await _resolve_usernames(guild_id, [r["user_id"] for r in leaderboard])
    return {
        "leaderboard": [_level_to_json(r, names.get(r["user_id"], r["user_id"])) for r in leaderboard],
        "level_roles": [_level_role_to_json(r) for r in level_roles_list],
    }


class LevelRolePayload(BaseModel):
    level: int
    role_id: str


@app.post("/api/guilds/{guild_id}/level-roles")
async def api_add_level_role(request: Request, guild_id: str, payload: LevelRolePayload):
    await _require_manage(request, guild_id)
    if payload.level < 1:
        raise _ApiError(400, "Level must be 1 or higher.")
    await db.add_level_role(guild_id, payload.level, payload.role_id)
    return {"level_roles": [_level_role_to_json(r) for r in await db.list_level_roles(guild_id)]}


@app.delete("/api/guilds/{guild_id}/level-roles/{level}")
async def api_remove_level_role(request: Request, guild_id: str, level: int):
    await _require_manage(request, guild_id)
    await db.remove_level_role(guild_id, level)
    return {"level_roles": [_level_role_to_json(r) for r in await db.list_level_roles(guild_id)]}


# ------------------------------------------------------------------ announce --
class AnnouncePayload(BaseModel):
    channel_id: str
    title: str = ""
    description: str = ""
    color: str = "5865F2"
    image_url: str = ""
    footer: str = ""


@app.post("/api/guilds/{guild_id}/announce")
async def api_announce(request: Request, guild_id: str, payload: AnnouncePayload):
    await _require_manage(request, guild_id)
    user = require_login(request)
    channel_id = payload.channel_id.strip()
    if not channel_id.isdigit() or not (payload.title.strip() or payload.description.strip()):
        raise _ApiError(400, "Give a channel and at least a title or description.")

    embed: dict = {"color": _parse_embed_color(payload.color)}
    if payload.title.strip():
        embed["title"] = payload.title.strip()
    if payload.description.strip():
        embed["description"] = payload.description.strip()
    if payload.image_url.strip():
        embed["image"] = {"url": payload.image_url.strip()}
    if payload.footer.strip():
        embed["footer"] = {"text": payload.footer.strip()}

    try:
        await bot_rest.send_message(channel_id, embeds=[embed])
    except FluxerAPIError as e:
        raise _ApiError(502, f"Fluxer rejected that (HTTP {e.status}) — check the bot can post in that channel.")

    await db.log_action(guild_id, "announce", moderator_id=str(user.get("id")),
                         reason=f"Sent an announcement to <#{channel_id}>")
    return {"ok": True}


# ------------------------------------------------------ serve the frontend --
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend-assets")
    _FRONTEND_DIST_RESOLVED = FRONTEND_DIST.resolve()

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Catch-all so React Router's client-side routes (e.g. /guild/123)
        work on a hard refresh too, anything not matched above falls
        through to index.html and the SPA takes over routing.

        SECURITY: full_path is attacker-controlled. A naive
        `FRONTEND_DIST / full_path` join is vulnerable to path traversal,
        percent-encoded slashes (e.g. `..%2f..%2f.env`) bypass most
        request-path normalization done earlier in the stack and reach
        this handler with literal `..` segments intact. We resolve the
        joined path and explicitly verify it's still inside FRONTEND_DIST
        before ever touching the filesystem with it, rather than trusting
        the join result directly.
        """
        candidate = (FRONTEND_DIST / full_path).resolve()
        is_contained = candidate == _FRONTEND_DIST_RESOLVED or _FRONTEND_DIST_RESOLVED in candidate.parents
        if full_path and is_contained and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    async def frontend_not_built():
        return JSONResponse(
            {"detail": "Frontend isn't built yet. Run `npm install && npm run build` in "
                       "dashboard-frontend/, then restart the dashboard."},
            status_code=503,
        )
