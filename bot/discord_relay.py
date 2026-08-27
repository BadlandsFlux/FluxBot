"""Discord <-> Fluxer message relay.

Watches specific Discord channels and forwards new messages, content,
embeds, and attachments, into mapped Fluxer channel(s), and optionally
the other way too, per mapping (see discord_relay_mappings.direction
in schema.sql: 'discord_to_fluxer', 'fluxer_to_discord', or 'both').

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
posts through on that side.

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
import logging
from typing import Optional

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


def _convert_embed(embed: discord.Embed) -> dict:
    """Discord's own embed object to the plain dict shape this project
    sends everywhere else. Fluxer is assumed to mirror Discord's embed
    convention (as throughout this project), so this is close to a
    direct field-for-field pass-through."""
    data = embed.to_dict()
    data.pop("type", None)  # meaningful to Discord's own client rendering, not to anything Fluxer-side
    return data


class RelayClient(discord.Client):
    def __init__(self, fluxer_rest: FluxerREST):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._fluxer_rest = fluxer_rest

    async def on_ready(self) -> None:
        log.info("Discord relay connected as %s", self.user)
        await db.update_discord_relay_status(connected=True, discord_username=str(self.user))

    async def on_disconnect(self) -> None:
        await db.update_discord_relay_status(connected=False)

    async def on_message(self, message: discord.Message) -> None:
        if self.user and message.author.id == self.user.id:
            return  # this relay's own post (from the fluxer_to_discord direction), never re-relay it
        mappings = await db.list_discord_relay_mappings_for_discord_channel(str(message.channel.id))
        if not mappings:
            return

        content = message.content or None
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

        if not content and not embeds and not files:
            return  # nothing worth forwarding (e.g. a sticker-only message, not supported here)

        for mapping in mappings:
            target = mapping["fluxer_channel_id"]
            try:
                if files:
                    await self._fluxer_rest.send_message_with_files(target, files, content=content, embeds=embeds)
                else:
                    await self._fluxer_rest.send_message(target, content=content, embeds=embeds)
            except FluxerAPIError:
                log.warning("Failed to relay Discord message %s to Fluxer channel %s",
                            message.id, target, exc_info=True)

    async def send_to_discord(self, discord_channel_id: str, *, content: Optional[str],
                               embeds: Optional[list[dict]]) -> None:
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
                return
        discord_embeds = [discord.Embed.from_dict(e) for e in embeds] if embeds else None
        await channel.send(content=content or None, embeds=discord_embeds or [])


def register_fluxer_side(bot: Bot, relay_client: RelayClient) -> None:
    """The Fluxer -> Discord half of two-way mappings. Registered on the
    MAIN Fluxer bot (it already has a live gateway connection and sees
    every message), not a second listener on the relay client, there's
    only one Fluxer connection in this whole process."""

    @bot.on("MESSAGE_CREATE")
    async def on_fluxer_message(data: dict) -> None:
        guild_id = data.get("guild_id")
        channel_id = data.get("channel_id")
        author = data.get("author", {})
        if not guild_id or not channel_id:
            return
        self_id = (bot.gateway.user or {}).get("id")
        if self_id and str(author.get("id")) == str(self_id):
            return  # this relay's own post (from the discord_to_fluxer direction), never re-relay it

        mappings = await db.list_discord_relay_mappings_for_fluxer_channel(str(channel_id))
        if not mappings:
            return

        content = data.get("content") or None
        embeds = data.get("embeds") or None
        # Attachments aren't relayed in this direction yet: Fluxer's
        # MESSAGE_CREATE attachment payload shape isn't confirmed (same
        # general uncertainty as the rest of this project's Fluxer
        # assumptions), and re-hosting them through Discord's own upload
        # flow needs bytes in hand the way discord.py's attachment.read()
        # conveniently gives on the other side. Content and embeds cover
        # the motivating use case; attachment support here is a
        # reasonable follow-up, not a blocker for shipping the rest.
        if not content and not embeds:
            return

        for mapping in mappings:
            try:
                await relay_client.send_to_discord(mapping["discord_channel_id"], content=content, embeds=embeds)
            except Exception:
                log.warning("Failed to relay Fluxer message to Discord channel %s",
                            mapping["discord_channel_id"], exc_info=True)


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
