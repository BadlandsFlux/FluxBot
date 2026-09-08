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
import json
import logging
import re
from datetime import timedelta
from typing import Optional
from urllib.parse import quote

import aiohttp
import discord

from bot.commands import Bot
from bot.rest import FluxerAPIError, FluxerREST
from common import db
from common.config import config
from common.discovery import get_media_base, user_avatar_url
from common.url_safety import is_safe_external_url

log = logging.getLogger("fluxbot.discord_relay")

# A sanity ceiling on what gets downloaded into memory before re-upload,
# not an attempt to guess Fluxer's (or Discord's) own actual limit.
# Discord's own base (non-boosted-server) upload cap, oversized files
# are skipped with a log line rather than attempted and left to fail.
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

WEBHOOK_NAME = "FluxBot Relay"

# A ceiling on how many messages a single reconnect backfill pass pulls
# from one channel's history, not a guess at Discord's own limits.
# Keeps a very busy channel over a long outage from turning a reconnect
# into an extended, rate-limit-heavy history crawl; anything beyond
# this cap is simply not recovered, the same "give up eventually"
# philosophy as the Fluxer-to-Discord queue's 24h horizon.
MAX_BACKFILL_MESSAGES = 200

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


def _snippet(content: Optional[str], max_chars: int = 80) -> str:
    content = (content or "").replace("\n", " ").strip()
    if not content:
        return "*(no text)*"
    return content if len(content) <= max_chars else content[: max_chars - 1] + "…"


def _reply_prefix(*, author_name: str, snippet: str, jump_link: Optional[str], source_label: str) -> str:
    """A text-based stand-in for a real threaded reply, since neither
    Discord's nor (presumably) Fluxer's webhook-execute API can set a
    genuine message reference, that's only possible for a regular bot-
    or user-sent message, not one sent through a webhook, which is the
    primary relay path whenever attribution is on. With a jump link
    (the replied-to message was itself relayed, so there's a real
    corresponding message on the OTHER platform to point at) or
    without one (it wasn't relayed, or predates the mapping, so this
    just names who and what, on which platform, without a working
    link)."""
    if jump_link:
        return f"↩️ *replying to [{author_name}]({jump_link}): {snippet}*"
    return f"↩️ *replying to {author_name} on {source_label}: {snippet}*"


def _discord_jump_url(guild_id, channel_id, message_id) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _fluxer_jump_url(guild_id, channel_id, message_id) -> str:
    return f"{config.web_base}/channels/{guild_id}/{channel_id}/{message_id}"


async def _prepend_fluxer_reply_prefix(bot: Bot, data: dict, content: Optional[str]) -> Optional[str]:
    """Fluxer-side mirror of RelayClient._prepend_reply_prefix, a
    module-level function rather than a method since the handlers in
    register_fluxer_side are nested functions, not part of a class.
    Same "Discord convention, assumed mirrored" caveat as the rest of
    this module's Fluxer-payload-shape assumptions: message_reference
    for the pointer, referenced_message for the already-resolved
    original (Discord's own raw gateway payload includes this inline
    on a reply, no separate fetch needed in the common case), falling
    back to a REST fetch only if that's missing."""
    ref = data.get("message_reference") or {}
    ref_message_id = ref.get("message_id")
    if not ref_message_id:
        return content

    referenced = data.get("referenced_message")
    if referenced is None:
        try:
            referenced = await bot.rest.get_message(str(ref.get("channel_id")), str(ref_message_id))
        except Exception:
            referenced = None

    author_name = (referenced.get("author", {}).get("username", "someone")) if referenced else "someone"
    snippet = _snippet(referenced.get("content") if referenced else None)

    jump_link = None
    links = await db.get_relay_message_links("fluxer", str(ref_message_id))
    for link in links:
        if link["target_platform"] != "discord":
            continue
        jump_link = _discord_jump_url(data.get("guild_id"), link["target_channel_id"], link["target_message_id"])
        break

    prefix = _reply_prefix(author_name=author_name, snippet=snippet, jump_link=jump_link, source_label="Fluxer")
    return f"{prefix}\n{content}" if content else prefix


def _is_safe_download_url(url: str) -> bool:
    return is_safe_external_url(url)


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


def _proxied_discord_avatar_url(discord_cdn_url: Optional[str]) -> Optional[str]:
    """Fluxer's webhook avatar_url apparently can't (or doesn't
    reliably) fetch directly from Discord's CDN: reported as Discord
    avatars never showing up on relayed messages while Fluxer avatars
    reach Discord fine, an asymmetry that points squarely at fetching
    FROM Discord's CDN specifically being the broken half, not
    anything about the webhook mechanism itself (which the Fluxer to
    Discord direction already proves works). Routes it through this
    dashboard's own avatar-proxy endpoint instead (see dashboard/
    app.py), a URL on the SAME kind of domain Fluxer already fetches
    from successfully elsewhere in this app, which re-fetches the real
    image from Discord server-side and serves it back under this
    dashboard's own domain. Falls back to the raw Discord URL
    unchanged if the dashboard's own public URL still looks like the
    unconfigured localhost default, no worse than the pre-proxy
    behavior in that edge case rather than actively worse (dropping
    the avatar outright)."""
    if not discord_cdn_url:
        return None
    if not config.dashboard_public_url or "localhost" in config.dashboard_public_url or "127.0.0.1" in config.dashboard_public_url:
        return discord_cdn_url
    return f"{config.dashboard_public_url}/api/discord-relay/avatar-proxy?url={quote(discord_cdn_url, safe='')}"


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
                                    username: str, avatar_url: Optional[str]) -> Optional[tuple[dict, str, str]]:
    """None on any failure (never raises), the caller falls back to a
    plain send in that case. On success, returns (result, webhook_id,
    webhook_token), the EXACT credentials that sent this message, not
    just "a webhook succeeded", since a later edit or delete needs
    those same credentials specifically, not whatever's on file for
    the channel by the time that happens (see discord_relay_message_
    links.webhook_id's column comment in schema.sql for why that
    distinction matters). On a 404 specifically (the webhook was
    deleted from the channel's integrations directly, out from under
    the stored record), clears that record and retries once with a
    freshly created one before giving up."""
    webhook = await _get_or_create_fluxer_webhook(fluxer_rest, channel_id)
    if not webhook:
        return None
    webhook_id, webhook_token = webhook
    try:
        result = await fluxer_rest.execute_webhook(webhook_id, webhook_token, content=content, embeds=embeds,
                                                     files=files, username=username, avatar_url=avatar_url)
        return result, webhook_id, webhook_token
    except FluxerAPIError as e:
        if e.status != 404:
            return None
        await db.delete_relay_webhook("fluxer", channel_id)
        webhook2 = await _get_or_create_fluxer_webhook(fluxer_rest, channel_id)
        if not webhook2:
            return None
        try:
            result = await fluxer_rest.execute_webhook(webhook2[0], webhook2[1], content=content, embeds=embeds,
                                                         files=files, username=username, avatar_url=avatar_url)
            return result, webhook2[0], webhook2[1]
        except FluxerAPIError:
            return None


async def _resolve_link_webhook(link, platform: str) -> Optional[tuple[str, str]]:
    """The webhook to use for editing/deleting a specific relayed
    message: the EXACT one that sent it, stored on the link itself,
    when available. Falls back to whatever's currently on file for the
    channel only for a link created before that column existed, the
    best available guess for that case, not a guarantee (this is
    exactly the lookup that broke before this column was added: a
    channel's webhook can be recreated after a message was sent, and
    the "current" one is then simply the wrong webhook for that
    message)."""
    if link.get("webhook_id") and link.get("webhook_token"):
        return link["webhook_id"], link["webhook_token"]
    webhook = await db.get_relay_webhook(platform, link["target_channel_id"])
    if webhook:
        return webhook["webhook_id"], webhook["webhook_token"]
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

    async def _prepend_reply_prefix(self, message: discord.Message, content: Optional[str]) -> Optional[str]:
        ref = message.reference
        referenced = ref.resolved if ref.resolved and not isinstance(ref.resolved, discord.DeletedReferencedMessage) else None
        if referenced is None and ref.message_id:
            try:
                channel = await self._get_channel(str(ref.channel_id)) if ref.channel_id else message.channel
                referenced = await channel.fetch_message(ref.message_id) if channel else None
            except Exception:
                referenced = None

        author_name = referenced.author.display_name if referenced else "someone"
        snippet = _snippet(referenced.content if referenced else None)

        jump_link = None
        links = await db.get_relay_message_links("discord", str(ref.message_id))
        for link in links:
            if link["target_platform"] != "fluxer":
                continue
            mapping = await db.get_discord_relay_mapping_by_id(link["mapping_id"]) if link["mapping_id"] else None
            if mapping:
                jump_link = _fluxer_jump_url(mapping["fluxer_guild_id"], link["target_channel_id"], link["target_message_id"])
                break

        prefix = _reply_prefix(author_name=author_name, snippet=snippet, jump_link=jump_link, source_label="Discord")
        return f"{prefix}\n{content}" if content else prefix

    async def on_ready(self) -> None:
        log.info("Discord relay connected as %s", self.user)
        await db.update_discord_relay_status(
            connected=True, discord_username=str(self.user),
            discord_bot_id=str(self.user.id) if self.user else None,
        )
        asyncio.create_task(self._recover_after_reconnect())

    async def on_disconnect(self) -> None:
        await db.update_discord_relay_status(connected=False)
        await db.mark_relay_disconnected()

    async def _recover_after_reconnect(self) -> None:
        """Runs as a background task after every on_ready, not awaited
        directly there, a potentially-long backfill across several
        channels plus a queue drain shouldn't hold up anything else
        discord.py wants to do right after connecting. Backfill first,
        then drain the outbound queue, in that order, though the two
        are independent enough that the order mostly doesn't matter.
        Clears the disconnected-at marker only after this whole pass
        actually runs (not if it raises outright before even starting),
        so a reconnect that fails to properly recover doesn't lose
        track of when the outage began, a LATER reconnect within the
        24h cap gets another chance at the same window rather than
        just the time between that reconnect and now."""
        try:
            await self._backfill_discord_to_fluxer()
            await _drain_fluxer_to_discord_queue(self)
            await db.clear_relay_disconnected_at()
        except Exception:
            log.warning("Post-reconnect recovery (backfill/queue drain) failed", exc_info=True)

    async def _backfill_discord_to_fluxer(self) -> None:
        """Catches up on Discord messages sent while this side was
        disconnected. Unlike the Fluxer-to-Discord direction, there's no
        queue to drain here, the bot simply never receives a Discord
        gateway event at all while disconnected, nothing to catch or
        persist in the moment. Instead, once reconnected, this fetches
        real message history via REST for every channel that's a source
        for at least one enabled mapping, and relays anything not
        already linked. Bounded to exactly how long the outage actually
        was (discord_relay_status.last_disconnected_at), capped at 24h
        for a longer outage, the same give-up horizon as the
        Fluxer-to-Discord queue, and capped per-channel at
        MAX_BACKFILL_MESSAGES so a very busy channel over a long outage
        can't turn a reconnect into an extended, rate-limit-heavy
        history crawl."""
        status = await db.get_discord_relay_status()
        since = status["last_disconnected_at"] if status else None
        if since is None:
            return  # first ever connect, or a previous pass already cleared this
        cutoff = max(since, discord.utils.utcnow() - timedelta(hours=24))

        channel_ids = await db.list_discord_relay_backfill_source_channels()
        for channel_id in channel_ids:
            try:
                channel = await self._get_channel(channel_id)
                if channel is None:
                    continue
                mappings = await db.list_discord_relay_mappings_for_discord_channel(channel_id)
                if not mappings:
                    continue
                relayed_count = 0
                async for message in channel.history(after=cutoff, limit=MAX_BACKFILL_MESSAGES, oldest_first=True):
                    if self._is_self(message.author.id):
                        continue
                    if message.webhook_id and await self._is_own_webhook("discord", channel_id, message.webhook_id):
                        continue
                    # Already relayed is the normal case for anything the
                    # live path caught during a brief reconnect blip
                    # rather than a genuine miss, skip re-sending it.
                    if await db.get_relay_message_links("discord", str(message.id)):
                        continue
                    await self._relay_discord_message(message, mappings=mappings)
                    relayed_count += 1
                if relayed_count:
                    log.info("Backfilled %d Discord message(s) from channel %s after reconnect", relayed_count, channel_id)
            except Exception:
                log.warning("Failed to backfill Discord channel %s after reconnect", channel_id, exc_info=True)

    async def on_message(self, message: discord.Message) -> None:
        if self._is_self(message.author.id):
            return  # this relay's own post (from the fluxer_to_discord direction), never re-relay it
        if message.webhook_id and await self._is_own_webhook("discord", str(message.channel.id), message.webhook_id):
            return  # this relay's own webhook echo, same loop risk as above, just a different identity
        await self._relay_discord_message(message)

    async def _relay_discord_message(self, message: discord.Message, mappings: Optional[list] = None) -> None:
        """The actual "take this Discord message and relay it to Fluxer"
        logic, split out from on_message so the reconnect backfill (see
        _backfill_discord_to_fluxer) can run the exact same path against
        a real historical discord.Message pulled from REST, rather than
        duplicating everything here a second time for "replay" purposes.
        Loop-prevention checks (self/own-webhook) are the CALLER's
        responsibility, not repeated here, on_message already does them
        for the live path and backfill has its own reasons not to need
        them (see that method). mappings can be passed in to skip a
        redundant lookup when the caller already has them (backfill
        fetches them once per channel before iterating its history)."""
        if mappings is None:
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

        if message.reference and message.reference.message_id:
            raw_content = await self._prepend_reply_prefix(message, raw_content)

        display_name = message.author.display_name
        avatar_url = _proxied_discord_avatar_url(message.author.display_avatar.url if message.author.display_avatar else None)

        for mapping in mappings:
            target = mapping["fluxer_channel_id"]
            result, sent_via_webhook = None, False
            used_webhook_id, used_webhook_token = None, None

            if mapping["show_attribution"]:
                webhook_send = await _send_via_fluxer_webhook(
                    self._fluxer_rest, target, content=raw_content, embeds=embeds, files=files,
                    username=display_name, avatar_url=avatar_url,
                )
                if webhook_send is not None:
                    result, used_webhook_id, used_webhook_token = webhook_send
                    sent_via_webhook = True

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
                                                  sent_via_webhook=sent_via_webhook,
                                                  webhook_id=used_webhook_id, webhook_token=used_webhook_token)

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
                    webhook = await _resolve_link_webhook(link, "fluxer")
                    if not webhook:
                        continue  # webhook's gone, nothing to edit through, leave the original as-is
                    await self._fluxer_rest.edit_webhook_message(
                        webhook[0], webhook[1], link["target_message_id"], content=new_content,
                    )
                else:
                    mapping = await db.get_discord_relay_mapping_by_id(link["mapping_id"]) if link["mapping_id"] else None
                    prefix = None
                    if mapping and mapping["show_attribution"]:
                        display_name = author.get("global_name") or author.get("username", "unknown")
                        prefix = f"**[Discord] {display_name}:**"
                    content = _with_attribution(new_content, prefix)
                    await self._fluxer_rest.edit_message(link["target_channel_id"], link["target_message_id"], content=content)
            except FluxerAPIError as e:
                if e.status == 404:
                    log.info("Fluxer message %s to edit is already gone, nothing to sync", link["target_message_id"])
                else:
                    log.warning("Failed to sync a Discord edit to Fluxer message %s", link["target_message_id"], exc_info=True)

    async def _sync_discord_delete(self, message_id) -> None:
        links = await db.get_relay_message_links("discord", str(message_id))
        for link in links:
            if link["target_platform"] != "fluxer":
                continue
            try:
                if link["sent_via_webhook"]:
                    webhook = await _resolve_link_webhook(link, "fluxer")
                    if webhook:
                        await self._fluxer_rest.delete_webhook_message(
                            webhook[0], webhook[1], link["target_message_id"],
                        )
                else:
                    await self._fluxer_rest.delete_message(link["target_channel_id"], link["target_message_id"])
            except FluxerAPIError as e:
                if e.status == 404:
                    log.info("Fluxer message %s to delete is already gone, nothing to sync", link["target_message_id"])
                else:
                    log.warning("Failed to sync a Discord delete to Fluxer message %s", link["target_message_id"], exc_info=True)
            await db.delete_relay_message_link(link["id"])

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        await self._sync_discord_delete(payload.message_id)

    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        """A moderator bulk-deleting/purging messages fires this instead
        of a series of individual RawMessageDeleteEvents, so without
        this handler none of those deletes would ever sync, only
        one-at-a-time deletes would. Syncs each affected message that
        was actually relayed, same per-message logic as a single
        delete, one at a time rather than trying to batch the Fluxer
        side (Fluxer's own bulk-delete equivalent, if one even exists,
        isn't confirmed, and mixing regular and webhook-sent messages
        in the same purge means they wouldn't all go through the same
        endpoint anyway)."""
        for message_id in payload.message_ids:
            await self._sync_discord_delete(message_id)

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
                               fallback_content: Optional[str] = None) -> tuple[Optional[str], bool, Optional[str], Optional[str]]:
        """Returns (sent_message_id, sent_via_webhook, webhook_id,
        webhook_token). The last two are the EXACT credentials that
        sent this message when sent_via_webhook is True (needed for a
        later edit/delete to target the right webhook even if the
        channel's "current" one has since been recreated, see
        discord_relay_message_links.webhook_id's column comment in
        schema.sql), and None otherwise. Tries a webhook first (shows
        the real username/avatar) when username is given, falling back
        to a plain bot-identity send using fallback_content (typically
        the same content with a "[Fluxer] username:" prefix re-applied,
        since a plain send can't show the real identity any other way)
        if that fails, same graceful-degradation shape as the Fluxer
        side."""
        discord_embeds = [discord.Embed.from_dict(e) for e in embeds] if embeds else None

        if username:
            webhook = await self._get_or_create_discord_webhook(discord_channel_id)
            if webhook:
                discord_files = [discord.File(fp=io.BytesIO(b), filename=name) for name, b in (files or [])]
                try:
                    sent = await webhook.send(content=content or None, embeds=discord_embeds or [],
                                               files=discord_files or [], username=username,
                                               avatar_url=avatar_url, wait=True)
                    return str(sent.id), True, str(webhook.id), webhook.token
                except discord.NotFound:
                    await db.delete_relay_webhook("discord", discord_channel_id)
                    webhook2 = await self._get_or_create_discord_webhook(discord_channel_id)
                    if webhook2:
                        try:
                            discord_files2 = [discord.File(fp=io.BytesIO(b), filename=name) for name, b in (files or [])]
                            sent = await webhook2.send(content=content or None, embeds=discord_embeds or [],
                                                        files=discord_files2 or [], username=username,
                                                        avatar_url=avatar_url, wait=True)
                            return str(sent.id), True, str(webhook2.id), webhook2.token
                        except discord.HTTPException:
                            pass
                except discord.HTTPException:
                    pass

        channel = await self._get_channel(discord_channel_id)
        if channel is None:
            log.warning("Can't reach Discord channel %s, is the relay bot actually in that server?",
                        discord_channel_id)
            return None, False, None, None
        discord_files = [discord.File(fp=io.BytesIO(b), filename=name) for name, b in (files or [])]
        plain_content = fallback_content if fallback_content is not None else content
        sent = await channel.send(content=plain_content or None, embeds=discord_embeds or [], files=discord_files or [])
        return str(sent.id), False, None, None


async def _drain_fluxer_to_discord_queue(relay_client: RelayClient) -> None:
    """Delivers everything queued while the relay's Discord side was
    down (see RelayClient._recover_after_reconnect, this runs right
    after the backfill in the same post-reconnect pass), oldest first
    so a backed-up conversation arrives in the order it actually
    happened. Anything already past the 24h horizon is simply dropped
    without an attempt, that's the give-up point, not a threshold to
    approach cautiously. A message that fails again here (a genuinely
    broken channel or webhook, not the relay being down, we just
    reconnected) is left in place rather than dropped immediately,
    picked up again on the next reconnect or eventually swept by the
    24h prune, either in this same pass next time or the scheduler's
    periodic backstop."""
    expired = await db.list_fluxer_to_discord_queue(older_than_hours=24)
    for entry in expired:
        log.info("Giving up on queued Fluxer message %s, queued over 24h ago", entry["source_message_id"])
        await db.delete_fluxer_to_discord_queue_entry(entry["id"])

    pending = await db.list_fluxer_to_discord_queue()
    if not pending:
        return
    log.info("Draining %d queued Fluxer-to-Discord message(s) after reconnect", len(pending))

    for entry in pending:
        try:
            embeds = json.loads(entry["embeds_json"]) if entry["embeds_json"] else None
            attachment_refs = json.loads(entry["attachments_json"]) if entry["attachments_json"] else []
            files: list[tuple[str, bytes]] = []
            for ref in attachment_refs:
                file_bytes = await _download(ref["url"], MAX_ATTACHMENT_BYTES)
                if file_bytes is not None:
                    files.append((ref["filename"], file_bytes))
                else:
                    log.warning("Couldn't re-download queued attachment %s for Fluxer message %s",
                                ref["filename"], entry["source_message_id"])

            sent_id, sent_via_webhook, used_webhook_id, used_webhook_token = await relay_client.send_to_discord(
                entry["target_channel_id"], content=entry["content"], embeds=embeds, files=files,
                username=entry["username"], avatar_url=entry["avatar_url"], fallback_content=entry["fallback_content"],
            )
            if sent_id:
                await db.add_relay_message_link(entry["mapping_id"], "fluxer", entry["source_message_id"],
                                                  "discord", sent_id, entry["target_channel_id"],
                                                  sent_via_webhook=sent_via_webhook,
                                                  webhook_id=used_webhook_id, webhook_token=used_webhook_token)
                await db.delete_fluxer_to_discord_queue_entry(entry["id"])
            # sent_id is None only when the target channel itself can't be
            # reached at all (see send_to_discord), leave the entry for a
            # later attempt rather than silently losing it here.
        except Exception:
            log.warning("Failed to deliver queued Fluxer message %s, will retry on next reconnect",
                        entry["source_message_id"], exc_info=True)


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

        # Just the references at this point (filename + url), not the
        # downloaded bytes: if the relay turns out to be down below,
        # queueing only needs enough to re-fetch the file later, holding
        # the actual bytes in the queue table for a possibly-long-lived
        # backlog is unnecessary weight this doesn't need to carry.
        attachment_refs = [
            {"filename": a.get("filename", "file"), "url": a.get("url"), "size": a.get("size", 0)}
            for a in (data.get("attachments", []) or []) if a.get("url")
        ]

        if not raw_content and not embeds and not attachment_refs:
            return

        raw_content = await _prepend_fluxer_reply_prefix(bot, data, raw_content)

        username = author.get("username", "unknown")
        avatar_url = await _fluxer_avatar_url(str(author.get("id")), author.get("avatar")) if mappings and any(m["show_attribution"] for m in mappings) else None

        if not relay_client.is_ready():
            # The Discord side is down: there's no point even trying,
            # every send below would just fail the same way. Queue each
            # mapping's copy instead (already fully prepared, mentions
            # translated, reply prefix applied, so draining this later
            # is just "attempt delivery with what's here", nothing left
            # to rebuild), drained automatically the moment the relay
            # reconnects (see RelayClient._recover_after_reconnect).
            embeds_json = json.dumps(embeds) if embeds else None
            attachments_json = json.dumps(attachment_refs) if attachment_refs else None
            for mapping in mappings:
                fallback_content = _with_attribution(raw_content, f"**[Fluxer] {username}:**") if mapping["show_attribution"] else None
                await db.enqueue_fluxer_to_discord_message(
                    mapping["id"], str(message_id), mapping["discord_channel_id"], raw_content, embeds_json,
                    attachments_json, username if mapping["show_attribution"] else None,
                    avatar_url if mapping["show_attribution"] else None, fallback_content,
                )
            return

        files: list[tuple[str, bytes]] = []
        for ref in attachment_refs:
            if ref["size"] and ref["size"] > MAX_ATTACHMENT_BYTES:
                log.warning("Skipping oversized Fluxer attachment %s (%d bytes)", ref["filename"], ref["size"])
                continue
            file_bytes = await _download(ref["url"], MAX_ATTACHMENT_BYTES)
            if file_bytes is not None:
                files.append((ref["filename"], file_bytes))
            else:
                log.warning("Couldn't download Fluxer attachment %s for relay to Discord", ref["filename"])

        for mapping in mappings:
            target = mapping["discord_channel_id"]
            try:
                if mapping["show_attribution"]:
                    fallback_content = _with_attribution(raw_content, f"**[Fluxer] {username}:**")
                    sent_id, sent_via_webhook, used_webhook_id, used_webhook_token = await relay_client.send_to_discord(
                        target, content=raw_content, embeds=embeds, files=files,
                        username=username, avatar_url=avatar_url, fallback_content=fallback_content,
                    )
                else:
                    sent_id, sent_via_webhook, used_webhook_id, used_webhook_token = await relay_client.send_to_discord(
                        target, content=raw_content, embeds=embeds, files=files)
                if sent_id:
                    await db.add_relay_message_link(mapping["id"], "fluxer", str(message_id),
                                                      "discord", sent_id, target, sent_via_webhook=sent_via_webhook,
                                                      webhook_id=used_webhook_id, webhook_token=used_webhook_token)
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
                if link["sent_via_webhook"]:
                    webhook_creds = await _resolve_link_webhook(link, "discord")
                    if not webhook_creds:
                        continue
                    webhook = discord.Webhook.partial(int(webhook_creds[0]), webhook_creds[1], client=relay_client)
                    await webhook.edit_message(int(link["target_message_id"]), content=new_content)
                else:
                    channel = await relay_client._get_channel(link["target_channel_id"])
                    if channel is None:
                        continue
                    mapping = await db.get_discord_relay_mapping_by_id(link["mapping_id"]) if link["mapping_id"] else None
                    prefix = None
                    if mapping and mapping["show_attribution"]:
                        prefix = f"**[Fluxer] {author.get('username', 'unknown')}:**"
                    content = _with_attribution(new_content, prefix)
                    discord_msg = await channel.fetch_message(int(link["target_message_id"]))
                    await discord_msg.edit(content=content)
            except discord.NotFound:
                log.info("Discord message %s to edit is already gone, nothing to sync", link["target_message_id"])
            except Exception:
                log.warning("Failed to sync a Fluxer edit to Discord message %s", link["target_message_id"], exc_info=True)

    async def _sync_fluxer_delete(message_id) -> None:
        links = await db.get_relay_message_links("fluxer", str(message_id))
        for link in links:
            if link["target_platform"] != "discord":
                continue
            try:
                if link["sent_via_webhook"]:
                    webhook_creds = await _resolve_link_webhook(link, "discord")
                    if webhook_creds:
                        webhook = discord.Webhook.partial(int(webhook_creds[0]), webhook_creds[1], client=relay_client)
                        await webhook.delete_message(int(link["target_message_id"]))
                else:
                    channel = await relay_client._get_channel(link["target_channel_id"])
                    if channel is not None:
                        discord_msg = await channel.fetch_message(int(link["target_message_id"]))
                        await discord_msg.delete()
            except discord.NotFound:
                log.info("Discord message %s to delete is already gone, nothing to sync", link["target_message_id"])
            except Exception:
                log.warning("Failed to sync a Fluxer delete to Discord message %s", link["target_message_id"], exc_info=True)
            await db.delete_relay_message_link(link["id"])

    @bot.on("MESSAGE_DELETE")
    async def on_fluxer_message_delete(data: dict) -> None:
        message_id = data.get("id")
        if not message_id:
            return
        await _sync_fluxer_delete(message_id)

    @bot.on("MESSAGE_DELETE_BULK")
    async def on_fluxer_message_delete_bulk(data: dict) -> None:
        """Fluxer's presumed equivalent of Discord's bulk-delete event
        (Discord convention: MESSAGE_DELETE_BULK with an "ids" array),
        unconfirmed against Fluxer's own docs like most of this
        project's gateway-event-shape assumptions, but this bot's own
        !purge command already bulk-deletes messages, so if Fluxer
        fires something for that at all, this is the most likely shape.
        Without this, purging a relayed Fluxer channel would leave the
        Discord-side copies behind, only one-at-a-time deletes would
        ever sync."""
        for message_id in data.get("ids", []) or []:
            await _sync_fluxer_delete(message_id)


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
