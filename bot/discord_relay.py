"""Discord <-> Fluxer message relay.

Watches specific Discord channels and forwards new messages, content,
embeds, and attachments, into mapped Fluxer channel(s), and optionally
the other way too, per mapping (see discord_relay_mappings.direction
in schema.sql: 'discord_to_fluxer', 'fluxer_to_discord', or 'both').
Also syncs edits and deletes across the bridge for anything it relayed
(see discord_relay_message_links, pruned periodically by the
scheduler).

ATTRIBUTION (per-mapping show_attribution, on by default): relayed
messages post through a webhook on the destination platform, showing
the ORIGINAL author's real username and avatar, the same mechanism
every real Discord/Fluxer bridge uses, since a regular bot-token-sent
message always shows up as the bot itself and can't be made to look
like anyone else. One webhook per destination channel, created lazily
the first time it's needed and reused after that (discord_relay_
webhooks table), recreated automatically if it ever goes missing
(deleted from the channel's integrations directly). If webhook
creation or execution fails for any reason (missing permission, etc),
falls back to a plain bot-identity send with a "[Discord] username:"
text prefix instead, so relaying itself never breaks just because the
richer path isn't available. With show_attribution off, messages
relay as plain bot-identity sends with no attribution at all.

Uses a real Discord Bot application via discord.py, never a self-bot
or user-token approach: automating a personal Discord account is
against Discord's own Terms of Service, and this project won't help
circumvent that, regardless of how the request is framed.

The bot token is dashboard-configurable (discord_relay_config table,
owner-only to set, never returned by any GET response), falling back
to DISCORD_BOT_TOKEN in .env if nothing's set there. Entirely optional
either way: with no token from either source, the relay simply never
starts, everything else about the bot runs the same regardless.

Runs as a second, independent gateway connection alongside the Fluxer
bot's own, within the same process (see bot/main.py), not a separate
script, coordinated via asyncio.create_task the same way the scheduler
already is.

LOOP PREVENTION for two-way mappings: without this, a message relayed
Discord -> Fluxer could get picked back up by the Fluxer -> Discord
side and relayed again, then AGAIN back the other way, forever. Each
side skips anything authored by the relay's own identity on THAT
platform specifically: the Discord listener skips messages from this
Discord bot's own user id, the Fluxer listener (registered on the main
Fluxer bot, see register_fluxer_side below) skips messages from the
main Fluxer bot's own user id, since that's the identity the relay
posts through on that side when NOT using a webhook. Webhook-sent
messages are authored by the webhook itself, a distinct identity
neither listener's self-check would ever match, so they can't loop
back either way on their own.

Deliberately does NOT filter out other bot-authored Discord messages:
the motivating use case is Discord's own channel-following/cross-post
feature aggregating announcements into one channel, which can arrive
via a bot or webhook-style mechanism depending on the source. Filtering
those out too would silently drop exactly the content this exists to
relay. The person configuring a mapping already chose which channel to
watch, that's the actual gate, not an author-type heuristic.
"""
from __future__ import annotations

import asyncio
import io
import ipaddress
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import discord

from bot.commands import Bot
from bot.rest import FluxerAPIError, FluxerREST
from common import db
from common.config import config
from common.discovery import get_media_base, user_avatar_url

log = logging.getLogger("fluxbot.discord_relay")

# A sanity ceiling on what gets downloaded into memory before re-upload,
# not an attempt to guess Fluxer's (or Discord's) own actual limit.
# Discord's own base (non-boosted-server) upload cap, oversized files
# are skipped with a log line rather than attempted and left to fail.
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

WEBHOOK_NAME = "FluxBot Relay"

# Discord permission bits requested by the invite link the dashboard
# builds (see dashboard/app.py's discord-relay/invite-url endpoint):
# View Channel, Send Messages, Read Message History, Manage Webhooks
# (needed to create the per-channel webhook attribution relies on).
INVITE_PERMISSIONS = (1 << 10) | (1 << 11) | (1 << 16) | (1 << 29)


def _convert_embed(embed: discord.Embed) -> dict:
    """Discord's own embed object to the plain dict shape this project
    sends everywhere else. Fluxer is assumed to mirror Discord's embed
    convention (as throughout this project), so this is close to a
    direct field-for-field pass-through."""
    data = embed.to_dict()
    data.pop("type", None)  # meaningful to Discord's own client rendering, not to anything Fluxer-side
    return data


def _with_attribution(content: Optional[str], prefix: Optional[str]) -> Optional[str]:
    if not prefix:
        return content
    return f"{prefix} {content}" if content else prefix


_USER_MENTION_RE = re.compile(r"<@!?(\d+)>")
_CHANNEL_MENTION_RE = re.compile(r"<#(\d+)>")
_ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")


def _translate_mentions(content: Optional[str], *, users: dict, channels: dict, roles: dict) -> Optional[str]:
    """Replaces Discord/Fluxer-style <@id>/<#id>/<@&id> mention tokens
    with plain "@name"/"#name" text. Necessary because these tokens
    encode a PLATFORM-SPECIFIC id: Discord and Fluxer are entirely
    separate id spaces, so passing a raw token straight through to the
    other platform would either render as a dead, unparsed token or,
    in the unlikely case the numeric id happens to coincide with
    something real over there, silently mention the wrong person
    entirely. This can't produce a live, clickable mention on the
    other platform either way, there's no cross-platform id mapping
    that would make one possible, so plain readable text is the best
    available outcome. Falls back to "unknown-user"/"unknown-channel"/
    "unknown-role" for an id this particular lookup couldn't resolve
    (a deleted channel, a role from before the bot had that guild
    cached, etc), rather than leaving the broken raw token in place.
    Role pattern is substituted before the user pattern deliberately
    (even though <@&id> can't actually match the user regex, & isn't
    ! and isn't a digit, so there's no real collision) just to keep
    the more specific pattern resolved first, in case that ever
    changes."""
    if not content:
        return content
    content = _ROLE_MENTION_RE.sub(lambda m: f"@{roles.get(m.group(1), 'unknown-role')}", content)
    content = _USER_MENTION_RE.sub(lambda m: f"@{users.get(m.group(1), 'unknown-user')}", content)
    content = _CHANNEL_MENTION_RE.sub(lambda m: f"#{channels.get(m.group(1), 'unknown-channel')}", content)
    return content


def _discord_mention_maps(message: discord.Message) -> tuple[dict, dict, dict]:
    """The create path: discord.py has already parsed and resolved
    these straight from the full Message object, no extra lookups
    needed."""
    users = {str(u.id): u.display_name for u in message.mentions}
    channels = {str(c.id): c.name for c in message.channel_mentions}
    roles = {str(r.id): r.name for r in message.role_mentions}
    return users, channels, roles


def _discord_mention_maps_from_raw(relay_client: "RelayClient", guild_id, content: str, data: dict) -> tuple[dict, dict, dict]:
    """The edit path: a raw gateway payload, not a full Message object,
    so no pre-resolved mention lists here. User mentions still come
    resolved in the raw payload itself (Discord convention); channels
    and roles don't, so those are looked up from discord.py's own
    guild cache (already populated from the initial connection, not a
    fresh API call), and only bothered with at all if the content
    actually contains that kind of token."""
    users = {str(u["id"]): u.get("global_name") or u.get("username", "unknown") for u in (data.get("mentions") or [])}
    channels: dict = {}
    roles: dict = {}
    if guild_id:
        guild = relay_client.get_guild(int(guild_id))
        if guild:
            if _CHANNEL_MENTION_RE.search(content or ""):
                channels = {str(c.id): c.name for c in guild.channels}
            if _ROLE_MENTION_RE.search(content or ""):
                roles = {str(r.id): r.name for r in guild.roles}
    return users, channels, roles


async def _fluxer_mention_maps(bot: Bot, guild_id, content: str, data: dict) -> tuple[dict, dict, dict]:
    """Same shape as the Discord side: user mentions are assumed to
    come pre-resolved in the raw payload (Discord convention, same
    caveat as everywhere this project relies on Fluxer mirroring it),
    channels and roles aren't, so those come from the guild's own
    cached fetch (bot.get_guild, TTL-cached already, not a fresh call
    per message), and only fetched at all if the content actually has
    that kind of token."""
    users = {str(u["id"]): u.get("username", "unknown") for u in (data.get("mentions") or [])}
    channels: dict = {}
    roles: dict = {}
    if guild_id and (_CHANNEL_MENTION_RE.search(content or "") or _ROLE_MENTION_RE.search(content or "")):
        try:
            guild = await bot.get_guild(guild_id)
        except Exception:
            guild = None
        if guild:
            channels = {str(c["id"]): c.get("name", "unknown") for c in guild.get("channels", [])}
            roles = {str(r["id"]): r.get("name", "unknown") for r in guild.get("roles", [])}
    return users, channels, roles


def _translate_embed_mentions(embed: dict, *, users: dict, channels: dict, roles: dict) -> dict:
    """Same translation, applied to the handful of embed text fields
    that can realistically carry a mention token: description, each
    field's name/value, the footer text, and the author name. Title,
    image/thumbnail URLs, and colors don't take mention syntax, left
    alone. Returns a new dict rather than mutating the one passed in,
    since the caller may still need the original for other targets in
    a fan-out."""
    if not any((users, channels, roles)):
        return embed
    out = dict(embed)
    if out.get("description"):
        out["description"] = _translate_mentions(out["description"], users=users, channels=channels, roles=roles)
    if out.get("fields"):
        out["fields"] = [
            {**f, "name": _translate_mentions(f.get("name"), users=users, channels=channels, roles=roles) or f.get("name", ""),
             "value": _translate_mentions(f.get("value"), users=users, channels=channels, roles=roles) or f.get("value", "")}
            for f in out["fields"]
        ]
    if out.get("footer", {}).get("text"):
        out["footer"] = {**out["footer"], "text": _translate_mentions(out["footer"]["text"], users=users, channels=channels, roles=roles)}
    if out.get("author", {}).get("name"):
        out["author"] = {**out["author"], "name": _translate_mentions(out["author"]["name"], users=users, channels=channels, roles=roles)}
    return out


def _translate_embeds_mentions(embeds: Optional[list], *, users: dict, channels: dict, roles: dict) -> Optional[list]:
    if not embeds or not any((users, channels, roles)):
        return embeds
    return [_translate_embed_mentions(e, users=users, channels=channels, roles=roles) for e in embeds]


def _is_safe_download_url(url: str) -> bool:
    """Defense-in-depth before fetching an attachment URL taken from a
    Fluxer message payload: this project has repeatedly noted Fluxer's
    exact API guarantees aren't fully confirmed, so a URL that's
    supposed to always be a Fluxer-CDN link (server-generated, not
    client-injectable, in the well-behaved case) gets a basic check
    anyway rather than being fetched blindly. Blocks non-http(s)
    schemes and literal private/loopback/link-local IP addresses.
    Doesn't attempt full DNS-rebinding protection (re-resolving and
    re-checking at connect time), that's real added complexity for
    what should normally never be attacker-reachable data in the
    first place, this is a reasonable, proportionate floor, not a
    complete SSRF defense."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    if host.lower() in ("localhost", "localhost.localdomain"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # a real hostname, not a literal IP, allowed (see docstring: not full DNS-rebinding protection)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)


async def _download(url: str, max_bytes: int) -> Optional[bytes]:
    if not _is_safe_download_url(url):
        log.warning("Refusing to download attachment from an unsafe-looking URL: %s", url)
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                if len(data) > max_bytes:
                    return None
                return data
    except Exception:
        return None


async def _fluxer_avatar_url(user_id: str, avatar_hash: Optional[str]) -> Optional[str]:
    if not avatar_hash:
        return None
    try:
        media_base = await get_media_base()
        return user_avatar_url(media_base, user_id, avatar_hash)
    except Exception:
        return None


async def _get_or_create_fluxer_webhook(fluxer_rest: FluxerREST, channel_id: str) -> Optional[tuple[str, str]]:
    """Returns (webhook_id, webhook_token) for the given Fluxer channel,
    creating and persisting one the first time it's needed. Returns
    None (never raises) if creation fails, e.g. the bot lacks Manage
    Webhooks there, letting the caller fall back to a plain send
    instead of failing outright."""
    existing = await db.get_relay_webhook("fluxer", channel_id)
    if existing:
        return existing["webhook_id"], existing["webhook_token"]
    try:
        webhook = await fluxer_rest.create_channel_webhook(channel_id, WEBHOOK_NAME)
        webhook_id, webhook_token = str(webhook["id"]), webhook["token"]
        await db.save_relay_webhook("fluxer", channel_id, webhook_id, webhook_token)
        return webhook_id, webhook_token
    except Exception:
        log.warning("Couldn't create a Fluxer webhook for channel %s, falling back to plain messages",
                    channel_id, exc_info=True)
        return None


async def _send_via_fluxer_webhook(fluxer_rest: FluxerREST, channel_id: str, *, content: Optional[str],
                                    embeds: Optional[list], files: Optional[list[tuple[str, bytes]]],
                                    username: str, avatar_url: Optional[str]) -> Optional[dict]:
    """None on any failure (never raises), the caller falls back to a
    plain send in that case. On a 404 specifically (the webhook was
    deleted from the channel's integrations directly, out from under
    the stored record), clears that record and retries once with a
    freshly created one before giving up."""
    webhook = await _get_or_create_fluxer_webhook(fluxer_rest, channel_id)
    if not webhook:
        return None
    webhook_id, webhook_token = webhook
    try:
        return await fluxer_rest.execute_webhook(webhook_id, webhook_token, content=content, embeds=embeds,
                                                  files=files, username=username, avatar_url=avatar_url)
    except FluxerAPIError as e:
        if e.status != 404:
            return None
        await db.delete_relay_webhook("fluxer", channel_id)
        webhook2 = await _get_or_create_fluxer_webhook(fluxer_rest, channel_id)
        if not webhook2:
            return None
        try:
            return await fluxer_rest.execute_webhook(webhook2[0], webhook2[1], content=content, embeds=embeds,
                                                       files=files, username=username, avatar_url=avatar_url)
        except FluxerAPIError:
            return None


class RelayClient(discord.Client):
    def __init__(self, fluxer_rest: FluxerREST):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._fluxer_rest = fluxer_rest

    def _is_self(self, user_id) -> bool:
        return bool(self.user and str(user_id) == str(self.user.id))

    async def _is_own_webhook(self, platform: str, channel_id: str, webhook_id) -> bool:
        """Deliberately scoped to THIS relay's own stored webhook for
        that specific channel, not "is this any webhook at all". Other
        webhooks legitimately posting content (the original motivating
        use case: Discord's own channel-following/cross-post feature,
        which can arrive via a webhook depending on the source) still
        need to relay normally, only this relay's own echo of something
        it already sent should be excluded."""
        own = await db.get_relay_webhook(platform, channel_id)
        return bool(own and str(webhook_id) == str(own["webhook_id"]))

    async def on_ready(self) -> None:
        log.info("Discord relay connected as %s", self.user)
        await db.update_discord_relay_status(
            connected=True, discord_username=str(self.user),
            discord_bot_id=str(self.user.id) if self.user else None,
        )

    async def on_disconnect(self) -> None:
        await db.update_discord_relay_status(connected=False)

    async def on_message(self, message: discord.Message) -> None:
        if self._is_self(message.author.id):
            return  # this relay's own post (from the fluxer_to_discord direction), never re-relay it
        if message.webhook_id and await self._is_own_webhook("discord", str(message.channel.id), message.webhook_id):
            return  # this relay's own webhook echo, same loop risk as above, just a different identity
        mappings = await db.list_discord_relay_mappings_for_discord_channel(str(message.channel.id))
        if not mappings:
            return

        raw_content = message.content or None
        users, channels, roles = ({}, {}, {})
        if raw_content or message.embeds:
            users, channels, roles = _discord_mention_maps(message)
            raw_content = _translate_mentions(raw_content, users=users, channels=channels, roles=roles)
        embeds = [_convert_embed(e) for e in message.embeds] if message.embeds else None
        embeds = _translate_embeds_mentions(embeds, users=users, channels=channels, roles=roles)

        files: list[tuple[str, bytes]] = []
        for attachment in message.attachments:
            if attachment.size > MAX_ATTACHMENT_BYTES:
                log.warning("Skipping oversized attachment %s (%d bytes) from Discord message %s",
                            attachment.filename, attachment.size, message.id)
                continue
            try:
                files.append((attachment.filename, await attachment.read()))
            except Exception:
                log.warning("Couldn't download attachment %s from Discord message %s",
                             attachment.filename, message.id, exc_info=True)

        if not raw_content and not embeds and not files:
            return  # nothing worth forwarding (e.g. a sticker-only message, not supported here)

        display_name = message.author.display_name
        avatar_url = message.author.display_avatar.url if message.author.display_avatar else None

        for mapping in mappings:
            target = mapping["fluxer_channel_id"]
            result, sent_via_webhook = None, False

            if mapping["show_attribution"]:
                result = await _send_via_fluxer_webhook(
                    self._fluxer_rest, target, content=raw_content, embeds=embeds, files=files,
                    username=display_name, avatar_url=avatar_url,
                )
                sent_via_webhook = result is not None

            if result is None:
                prefix = f"**[Discord] {display_name}:**" if mapping["show_attribution"] else None
                content = _with_attribution(raw_content, prefix)
                try:
                    if files:
                        result = await self._fluxer_rest.send_message_with_files(target, files, content=content, embeds=embeds)
                    else:
                        result = await self._fluxer_rest.send_message(target, content=content, embeds=embeds)
                except FluxerAPIError:
                    log.warning("Failed to relay Discord message %s to Fluxer channel %s",
                                message.id, target, exc_info=True)
                    continue

            if result and result.get("id"):
                await db.add_relay_message_link(mapping["id"], "discord", str(message.id),
                                                  "fluxer", str(result["id"]), target,
                                                  sent_via_webhook=sent_via_webhook)

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        author = (payload.data or {}).get("author", {})
        if author and self._is_self(author.get("id")):
            return
        new_content = payload.data.get("content") if payload.data else None
        if new_content is None:
            return  # not a content-bearing update
        users, channels, roles = _discord_mention_maps_from_raw(self, payload.guild_id, new_content, payload.data or {})
        new_content = _translate_mentions(new_content, users=users, channels=channels, roles=roles)
        links = await db.get_relay_message_links("discord", str(payload.message_id))
        for link in links:
            if link["target_platform"] != "fluxer":
                continue
            try:
                if link["sent_via_webhook"]:
                    webhook = await db.get_relay_webhook("fluxer", link["target_channel_id"])
                    if not webhook:
                        continue  # webhook's gone, nothing to edit through, leave the original as-is
                    await self._fluxer_rest.edit_webhook_message(
                        webhook["webhook_id"], webhook["webhook_token"], link["target_message_id"], content=new_content,
                    )
                else:
                    mapping = await db.get_discord_relay_mapping_by_id(link["mapping_id"]) if link["mapping_id"] else None
                    prefix = None
                    if mapping and mapping["show_attribution"]:
                        display_name = author.get("global_name") or author.get("username", "unknown")
                        prefix = f"**[Discord] {display_name}:**"
                    content = _with_attribution(new_content, prefix)
                    await self._fluxer_rest.edit_message(link["target_channel_id"], link["target_message_id"], content=content)
            except FluxerAPIError:
                log.warning("Failed to sync a Discord edit to Fluxer message %s", link["target_message_id"], exc_info=True)

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        links = await db.get_relay_message_links("discord", str(payload.message_id))
        for link in links:
            if link["target_platform"] != "fluxer":
                continue
            try:
                if link["sent_via_webhook"]:
                    webhook = await db.get_relay_webhook("fluxer", link["target_channel_id"])
                    if webhook:
                        await self._fluxer_rest.delete_webhook_message(
                            webhook["webhook_id"], webhook["webhook_token"], link["target_message_id"],
                        )
                else:
                    await self._fluxer_rest.delete_message(link["target_channel_id"], link["target_message_id"])
            except FluxerAPIError:
                log.warning("Failed to sync a Discord delete to Fluxer message %s", link["target_message_id"], exc_info=True)
            await db.delete_relay_message_link(link["id"])

    async def _get_channel(self, channel_id: str):
        channel = self.get_channel(int(channel_id))
        if channel is not None:
            return channel
        try:
            return await self.fetch_channel(int(channel_id))
        except discord.HTTPException:
            return None

    async def _get_or_create_discord_webhook(self, channel_id: str) -> Optional[discord.Webhook]:
        existing = await db.get_relay_webhook("discord", channel_id)
        if existing:
            return discord.Webhook.partial(int(existing["webhook_id"]), existing["webhook_token"], client=self)
        channel = await self._get_channel(channel_id)
        if channel is None:
            log.warning("Can't reach Discord channel %s, is the relay bot actually in that server?", channel_id)
            return None
        try:
            webhook = await channel.create_webhook(name=WEBHOOK_NAME)
            await db.save_relay_webhook("discord", channel_id, str(webhook.id), webhook.token)
            return webhook
        except discord.HTTPException:
            log.warning("Couldn't create a Discord webhook for channel %s, falling back to plain messages",
                        channel_id, exc_info=True)
            return None

    async def send_to_discord(self, discord_channel_id: str, *, content: Optional[str],
                               embeds: Optional[list[dict]], files: Optional[list[tuple[str, bytes]]] = None,
                               username: Optional[str] = None, avatar_url: Optional[str] = None,
                               fallback_content: Optional[str] = None) -> tuple[Optional[str], bool]:
        """Returns (sent_message_id, sent_via_webhook). Tries a webhook
        first (shows the real username/avatar) when username is given,
        falling back to a plain bot-identity send using fallback_content
        (typically the same content with a "[Fluxer] username:" prefix
        re-applied, since a plain send can't show the real identity any
        other way) if that fails, same graceful-degradation shape as
        the Fluxer side."""
        discord_embeds = [discord.Embed.from_dict(e) for e in embeds] if embeds else None

        if username:
            webhook = await self._get_or_create_discord_webhook(discord_channel_id)
            if webhook:
                discord_files = [discord.File(fp=io.BytesIO(b), filename=name) for name, b in (files or [])]
                try:
                    sent = await webhook.send(content=content or None, embeds=discord_embeds or [],
                                               files=discord_files or [], username=username,
                                               avatar_url=avatar_url, wait=True)
                    return str(sent.id), True
                except discord.NotFound:
                    await db.delete_relay_webhook("discord", discord_channel_id)
                    webhook2 = await self._get_or_create_discord_webhook(discord_channel_id)
                    if webhook2:
                        try:
                            discord_files2 = [discord.File(fp=io.BytesIO(b), filename=name) for name, b in (files or [])]
                            sent = await webhook2.send(content=content or None, embeds=discord_embeds or [],
                                                        files=discord_files2 or [], username=username,
                                                        avatar_url=avatar_url, wait=True)
                            return str(sent.id), True
                        except discord.HTTPException:
                            pass
                except discord.HTTPException:
                    pass

        channel = await self._get_channel(discord_channel_id)
        if channel is None:
            log.warning("Can't reach Discord channel %s, is the relay bot actually in that server?",
                        discord_channel_id)
            return None, False
        discord_files = [discord.File(fp=io.BytesIO(b), filename=name) for name, b in (files or [])]
        plain_content = fallback_content if fallback_content is not None else content
        sent = await channel.send(content=plain_content or None, embeds=discord_embeds or [], files=discord_files or [])
        return str(sent.id), False


def register_fluxer_side(bot: Bot, relay_client: RelayClient) -> None:
    """The Fluxer -> Discord half of two-way mappings. Registered on the
    MAIN Fluxer bot (it already has a live gateway connection and sees
    every message), not a second listener on the relay client, there's
    only one Fluxer connection in this whole process."""

    def _self_fluxer_id() -> Optional[str]:
        return (bot.gateway.user or {}).get("id")

    @bot.on("MESSAGE_CREATE")
    async def on_fluxer_message(data: dict) -> None:
        guild_id = data.get("guild_id")
        channel_id = data.get("channel_id")
        author = data.get("author", {})
        message_id = data.get("id")
        if not guild_id or not channel_id or not message_id:
            return
        self_id = _self_fluxer_id()
        if self_id and str(author.get("id")) == str(self_id):
            return  # this relay's own post (from the discord_to_fluxer direction), never re-relay it
        webhook_id = data.get("webhook_id")  # Discord convention (message object shape), assumed mirrored on Fluxer
        if webhook_id:
            own_webhook = await db.get_relay_webhook("fluxer", str(channel_id))
            if own_webhook and str(webhook_id) == str(own_webhook["webhook_id"]):
                return  # this relay's own webhook echo, same loop risk as above, just a different identity

        mappings = await db.list_discord_relay_mappings_for_fluxer_channel(str(channel_id))
        if not mappings:
            return

        raw_content = data.get("content") or None
        embeds = data.get("embeds") or None
        users, channels, roles = await _fluxer_mention_maps(bot, guild_id, raw_content or "", data)
        raw_content = _translate_mentions(raw_content, users=users, channels=channels, roles=roles)
        embeds = _translate_embeds_mentions(embeds, users=users, channels=channels, roles=roles)

        files: list[tuple[str, bytes]] = []
        for attachment in data.get("attachments", []) or []:
            url = attachment.get("url")
            size = attachment.get("size", 0)
            filename = attachment.get("filename", "file")
            if not url:
                continue
            if size and size > MAX_ATTACHMENT_BYTES:
                log.warning("Skipping oversized Fluxer attachment %s (%d bytes)", filename, size)
                continue
            file_bytes = await _download(url, MAX_ATTACHMENT_BYTES)
            if file_bytes is not None:
                files.append((filename, file_bytes))
            else:
                log.warning("Couldn't download Fluxer attachment %s for relay to Discord", filename)

        if not raw_content and not embeds and not files:
            return

        username = author.get("username", "unknown")
        avatar_url = await _fluxer_avatar_url(str(author.get("id")), author.get("avatar")) if mappings and any(m["show_attribution"] for m in mappings) else None

        for mapping in mappings:
            target = mapping["discord_channel_id"]
            try:
                if mapping["show_attribution"]:
                    fallback_content = _with_attribution(raw_content, f"**[Fluxer] {username}:**")
                    sent_id, sent_via_webhook = await relay_client.send_to_discord(
                        target, content=raw_content, embeds=embeds, files=files,
                        username=username, avatar_url=avatar_url, fallback_content=fallback_content,
                    )
                else:
                    sent_id, sent_via_webhook = await relay_client.send_to_discord(target, content=raw_content, embeds=embeds, files=files)
                if sent_id:
                    await db.add_relay_message_link(mapping["id"], "fluxer", str(message_id),
                                                      "discord", sent_id, target, sent_via_webhook=sent_via_webhook)
            except Exception:
                log.warning("Failed to relay Fluxer message to Discord channel %s", target, exc_info=True)

    @bot.on("MESSAGE_UPDATE")
    async def on_fluxer_message_update(data: dict) -> None:
        author = data.get("author", {})
        self_id = _self_fluxer_id()
        if author and self_id and str(author.get("id")) == str(self_id):
            return
        message_id = data.get("id")
        new_content = data.get("content")
        if not message_id or new_content is None:
            return
        guild_id = data.get("guild_id")
        users, channels, roles = await _fluxer_mention_maps(bot, guild_id, new_content, data)
        new_content = _translate_mentions(new_content, users=users, channels=channels, roles=roles)
        links = await db.get_relay_message_links("fluxer", str(message_id))
        for link in links:
            if link["target_platform"] != "discord":
                continue
            try:
                channel = await relay_client._get_channel(link["target_channel_id"])
                if channel is None:
                    continue
                if link["sent_via_webhook"]:
                    webhook_row = await db.get_relay_webhook("discord", link["target_channel_id"])
                    if not webhook_row:
                        continue
                    webhook = discord.Webhook.partial(int(webhook_row["webhook_id"]), webhook_row["webhook_token"], client=relay_client)
                    await webhook.edit_message(int(link["target_message_id"]), content=new_content)
                else:
                    mapping = await db.get_discord_relay_mapping_by_id(link["mapping_id"]) if link["mapping_id"] else None
                    prefix = None
                    if mapping and mapping["show_attribution"]:
                        prefix = f"**[Fluxer] {author.get('username', 'unknown')}:**"
                    content = _with_attribution(new_content, prefix)
                    discord_msg = await channel.fetch_message(int(link["target_message_id"]))
                    await discord_msg.edit(content=content)
            except Exception:
                log.warning("Failed to sync a Fluxer edit to Discord message %s", link["target_message_id"], exc_info=True)

    @bot.on("MESSAGE_DELETE")
    async def on_fluxer_message_delete(data: dict) -> None:
        message_id = data.get("id")
        if not message_id:
            return
        links = await db.get_relay_message_links("fluxer", str(message_id))
        for link in links:
            if link["target_platform"] != "discord":
                continue
            try:
                if link["sent_via_webhook"]:
                    webhook_row = await db.get_relay_webhook("discord", link["target_channel_id"])
                    if webhook_row:
                        webhook = discord.Webhook.partial(int(webhook_row["webhook_id"]), webhook_row["webhook_token"], client=relay_client)
                        await webhook.delete_message(int(link["target_message_id"]))
                else:
                    channel = await relay_client._get_channel(link["target_channel_id"])
                    if channel is not None:
                        discord_msg = await channel.fetch_message(int(link["target_message_id"]))
                        await discord_msg.delete()
            except Exception:
                log.warning("Failed to sync a Fluxer delete to Discord message %s", link["target_message_id"], exc_info=True)
            await db.delete_relay_message_link(link["id"])


def build_relay_client(bot: Bot) -> RelayClient:
    """Constructs the client and registers the Fluxer -> Discord listener
    on the main bot SYNCHRONOUSLY. Deliberately split from run_relay()
    below: if this registration happened inside that async function
    instead, there'd be a race between it and bot.start() actually
    beginning to process gateway events (both get scheduled via
    asyncio.create_task around the same point in main.py, with no
    guarantee which runs first). Calling this directly, before either
    task starts, makes the ordering guaranteed rather than probable."""
    client = RelayClient(bot.rest)
    register_fluxer_side(bot, client)
    return client


async def run_relay(bot: Bot, client: RelayClient) -> None:
    """Loops rather than returning outright when there's no token yet, or
    the last attempt failed, specifically so someone completing the
    dashboard's setup wizard (or fixing a bad token) doesn't need to
    restart the whole bot process to pick it up. discord.py's own
    Client.start() already handles transient reconnects internally once
    actually connected, this loop is only about "no usable token right
    now", not general retry logic duplicating what the library does."""
    while True:
        token = await db.get_discord_relay_token() or config.discord_bot_token
        if not token:
            log.info("No Discord relay token configured yet, checking again in 30s.")
            await asyncio.sleep(30)
            continue
        try:
            await client.start(token)
        except asyncio.CancelledError:
            raise  # bot shutting down, don't swallow this into a retry
        except discord.LoginFailure:
            log.error("Discord relay couldn't log in, the token is invalid.")
            await db.update_discord_relay_status(connected=False, error="Invalid bot token.")
            await asyncio.sleep(30)  # gives time to fix it via the dashboard before trying again
        except Exception as e:
            log.exception("Discord relay crashed, retrying in 30s")
            await db.update_discord_relay_status(connected=False, error=str(e)[:500])
            await asyncio.sleep(30)
        finally:
            await client.close()
            await db.update_discord_relay_status(connected=False)
