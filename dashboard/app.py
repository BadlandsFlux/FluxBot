from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from common import db
from common.config import config
from dashboard import oauth

log = logging.getLogger("fluxerbot.dashboard")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    yield
    await db.close_pool()


app = FastAPI(title="Fluxer Mod Bot Dashboard", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.session_secret, same_site="lax")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def current_user(request: Request) -> dict | None:
    return request.session.get("user")


# -------------------------------------------------------------------- auth --
@app.get("/login")
async def login(request: Request):
    state = oauth.new_state()
    request.session["oauth_state"] = state
    return RedirectResponse(oauth.build_authorize_url(state))


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str | None = None, state: str | None = None,
                         error: str | None = None):
    if error:
        return templates.TemplateResponse(request, "login.html", {"error": error})
    expected_state = request.session.pop("oauth_state", None)
    if not code or not state or state != expected_state:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Login failed (state mismatch). Try again."}
        )
    try:
        token_data = await oauth.exchange_code(code)
        access_token = token_data["access_token"]
        me = await oauth.fetch_me(access_token)
    except httpx.HTTPStatusError as e:
        log.warning("OAuth exchange failed: %s", e)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Fluxer rejected that login. Try again."}
        )
    request.session["user"] = me
    request.session["access_token"] = access_token
    return RedirectResponse("/")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")


# ------------------------------------------------------------------ pages --
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = current_user(request)
    if not user:
        return templates.TemplateResponse(request, "login.html", {})

    access_token = request.session.get("access_token")
    try:
        my_guilds = await oauth.fetch_my_guilds(access_token)
    except httpx.HTTPStatusError:
        my_guilds = []

    bot_guild_ids = {g["guild_id"] for g in await db.list_guilds()}
    manageable = [
        g for g in my_guilds
        if str(g.get("id")) in bot_guild_ids and oauth.can_manage(g)
    ]
    return templates.TemplateResponse(
        request, "index.html", {"user": user, "guilds": manageable}
    )


async def _require_manage(request: Request, guild_id: str) -> bool:
    access_token = request.session.get("access_token")
    if not access_token:
        return False
    try:
        my_guilds = await oauth.fetch_my_guilds(access_token)
    except httpx.HTTPStatusError:
        return False
    entry = next((g for g in my_guilds if str(g.get("id")) == guild_id), None)
    return bool(entry and oauth.can_manage(entry))


@app.get("/guild/{guild_id}", response_class=HTMLResponse)
async def guild_page(request: Request, guild_id: str):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login")
    if not await _require_manage(request, guild_id):
        return HTMLResponse("You don't have permission to manage this server.", status_code=403)

    guild_cfg = await db.get_guild(guild_id)
    if guild_cfg is None:
        return HTMLResponse("The bot isn't in this server (yet).", status_code=404)

    actions = await db.list_actions(guild_id, limit=50)
    warnings = await db.list_warnings(guild_id)
    autoroles = await db.list_autoroles(guild_id)
    reaction_roles = await db.list_reaction_roles(guild_id)

    return templates.TemplateResponse(request, "guild.html", {
        "user": user, "guild": guild_cfg,
        "actions": actions, "warnings": warnings,
        "autoroles": autoroles, "reaction_roles": reaction_roles,
    })


@app.post("/guild/{guild_id}/settings")
async def update_settings(
    request: Request, guild_id: str,
    log_channel_id: str = Form(""), mute_role_id: str = Form(""),
    warn_timeout_at: int = Form(3), warn_kick_at: int = Form(5),
    warn_timeout_minutes: int = Form(60),
):
    if not await _require_manage(request, guild_id):
        return HTMLResponse("You don't have permission to manage this server.", status_code=403)
    await db.update_guild_settings(
        guild_id,
        log_channel_id=log_channel_id or None,
        mute_role_id=mute_role_id or None,
        warn_timeout_at=warn_timeout_at,
        warn_kick_at=warn_kick_at,
        warn_timeout_minutes=warn_timeout_minutes,
    )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


@app.post("/guild/{guild_id}/warnings/{user_id}/clear")
async def clear_warnings(request: Request, guild_id: str, user_id: str):
    if not await _require_manage(request, guild_id):
        return HTMLResponse("You don't have permission to manage this server.", status_code=403)
    await db.clear_warnings(guild_id, user_id)
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)
