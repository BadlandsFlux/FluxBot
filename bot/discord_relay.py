"""Discord <-> Fluxer message relay.

Watches specific Discord channels and forwards new messages, content,
embeds, and attachments, into mapped Fluxer channel(s), and optionally
the other way too, per mapping (see discord_relay_mappings.direction
in schema.sql: 'discord_to_fluxer', 'fluxer_to_discord', or 'both').
Also syncs edits and deletes across the bridge for anything it relayed
(see discord_relay_message_links, pruned periodically by the
scheduler), and can prefix relayed content with who actually sent it
and from where (per-mapping show_attribution).

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
posts through on that side. The same check applies to edit/delete
syncing too, not just creates.

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
import logging
from typing import Optional

import aiohttp
import discord

from bot.commands import Bot
from bot.rest import FluxerAPIError, FluxerREST
from common import db
from common.config import config

log = logging.getLogger("fluxbot.discord_relay")

# A sanity ceiling on what gets downloaded into memory before re-upload,
# not an attempt to guess Fluxer's (or Discord's) own actual limit.
# Discord's own base (non-boosted-server) upload cap, oversized files
# are skipped with a log line rather than attempted and left to fail.
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

# Discord permission bits requested by the invite link the dashboard
# builds (see dashboard/app.py's discord-relay/invite-url endpoint):
# View Channel, Send Messages, Read Message History. Enough for either
# relay direction; a one-way Discord-to-Fluxer-only setup doesn't
# technically need Send Messages, but there's little downside to
# including it up front rather than making someone re-invite the bot
# later if they turn on two-way.
INVITE_PERMISSIONS = (1 << 10) | (1 << 11) | (1 << 16)


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


async def _download(url: str, max_bytes: int) -> Optional[bytes]:
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


class RelayClient(discord.Client):
    def __init__(self, fluxer_rest: FluxerREST):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._fluxer_rest = fluxer_rest

    def _is_self(self, user_id) -> bool:
        return bool(self.user and str(user_id) == str(self.user.id))

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
        mappings = await db.list_discord_relay_mappings_for_discord_channel(str(message.channel.id))
        if not mappings:
            return

        raw_content = message.content or None
        embeds = [_convert_embed(e) for e in message.embeds] if message.embeds else None

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

        for mapping in mappings:
            target = mapping["fluxer_channel_id"]
            prefix = f"**[Discord] {message.author.display_name}:**" if mapping["show_attribution"] else None
            content = _with_attribution(raw_content, prefix)
            try:
                if files:
                    result = await self._fluxer_rest.send_message_with_files(target, files, content=content, embeds=embeds)
                else:
                    result = await self._fluxer_rest.send_message(target, content=content, embeds=embeds)
                if result and result.get("id"):
                    await db.add_relay_message_link(mapping["id"], "discord", str(message.id),
                                                      "fluxer", str(result["id"]), target)
            except FluxerAPIError:
                log.warning("Failed to relay Discord message %s to Fluxer channel %s",
                            message.id, target, exc_info=True)

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        author = (payload.data or {}).get("author", {})
        if author and self._is_self(author.get("id")):
            return
        new_content = payload.data.get("content") if payload.data else None
        if new_content is None:
            return  # not a content-bearing update
        links = await db.get_relay_message_links("discord", str(payload.message_id))
        for link in links:
            if link["target_platform"] != "fluxer":
                continue
            mapping = await db.get_discord_relay_mapping_by_id(link["mapping_id"]) if link["mapping_id"] else None
            prefix = None
            if mapping and mapping["show_attribution"]:
                display_name = author.get("global_name") or author.get("username", "unknown")
                prefix = f"**[Discord] {display_name}:**"
            content = _with_attribution(new_content, prefix)
            try:
                await self._fluxer_rest.edit_message(link["target_channel_id"], link["target_message_id"], content=content)
            except FluxerAPIError:
                log.warning("Failed to sync a Discord edit to Fluxer message %s", link["target_message_id"], exc_info=True)

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        links = await db.get_relay_message_links("discord", str(payload.message_id))
        for link in links:
            if link["target_platform"] != "fluxer":
                continue
            try:
                await self._fluxer_rest.delete_message(link["target_channel_id"], link["target_message_id"])
            except FluxerAPIError:
                log.warning("Failed to sync a Discord delete to Fluxer message %s", link["target_message_id"], exc_info=True)
            await db.delete_relay_message_link(link["id"])

    async def send_to_discord(self, discord_channel_id: str, *, content: Optional[str],
                               embeds: Optional[list[dict]], files: Optional[list[tuple[str, bytes]]] = None) -> Optional[str]:
        channel = self.get_channel(int(discord_channel_id))
        if channel is None:
            # Not in this client's cache, most often means the bot isn't
            # actually a member of the server that channel belongs to, or
            # the channel id is wrong. fetch_channel hits the REST API
            # directly rather than relying on gateway-populated cache, a
            # slower but more definitive check before giving up.
            try:
                channel = await self.fetch_channel(int(discord_channel_id))
            except discord.HTTPException:
                log.warning("Can't reach Discord channel %s, is the relay bot actually in that server?",
                            discord_channel_id)
                return None
        discord_embeds = [discord.Embed.from_dict(e) for e in embeds] if embeds else None
        discord_files = [discord.File(fp=io.BytesIO(b), filename=name) for name, b in (files or [])]
        sent = await channel.send(content=content or None, embeds=discord_embeds or [], files=discord_files or [])
        return str(sent.id)


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

        mappings = await db.list_discord_relay_mappings_for_fluxer_channel(str(channel_id))
        if not mappings:
            return

        raw_content = data.get("content") or None
        embeds = data.get("embeds") or None

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

        for mapping in mappings:
            target = mapping["discord_channel_id"]
            prefix = f"**[Fluxer] {author.get('username', 'unknown')}:**" if mapping["show_attribution"] else None
            content = _with_attribution(raw_content, prefix)
            try:
                sent_id = await relay_client.send_to_discord(target, content=content, embeds=embeds, files=files)
                if sent_id:
                    await db.add_relay_message_link(mapping["id"], "fluxer", str(message_id),
                                                      "discord", sent_id, target)
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
        links = await db.get_relay_message_links("fluxer", str(message_id))
        for link in links:
            if link["target_platform"] != "discord":
                continue
            mapping = await db.get_discord_relay_mapping_by_id(link["mapping_id"]) if link["mapping_id"] else None
            prefix = None
            if mapping and mapping["show_attribution"]:
                prefix = f"**[Fluxer] {author.get('username', 'unknown')}:**"
            content = _with_attribution(new_content, prefix)
            try:
                channel = relay_client.get_channel(int(link["target_channel_id"]))
                if channel is None:
                    channel = await relay_client.fetch_channel(int(link["target_channel_id"]))
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
                channel = relay_client.get_channel(int(link["target_channel_id"]))
                if channel is None:
                    channel = await relay_client.fetch_channel(int(link["target_channel_id"]))
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
