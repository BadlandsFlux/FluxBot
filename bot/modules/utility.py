"""Utility commands: !help, !ping."""
from __future__ import annotations

import time

from bot.commands import Bot, Context
from bot.permissions import permission_name
from bot.timeutil import format_duration
from common import db
from common.config import config

CATEGORY_ORDER = ["Moderation", "Roles", "Info", "Fun", "Utility", "General"]
CATEGORY_EMOJI = {
    "Moderation": "🛡️", "Roles": "🎭", "Info": "ℹ️",
    "Fun": "🎉", "Utility": "🔧", "General": "📎",
}


def register(bot: Bot) -> None:

    @bot.command("ping", category="Utility",
                 help_text="Show latency, uptime, and other live stats. Usage: !ping")
    async def ping(ctx: Context) -> None:
        api_start = time.monotonic()
        sent = await ctx.bot.rest.send_message(ctx.channel_id, content="🏓 Pinging...")
        api_latency_ms = (time.monotonic() - api_start) * 1000

        db_start = time.monotonic()
        try:
            await db.get_guild(ctx.guild_id)
            db_status = f"{(time.monotonic() - db_start) * 1000:.0f}ms"
        except Exception:
            db_status = "unreachable"

        gw_latency = ctx.bot.gateway.latency_ms
        gw_status = f"{gw_latency:.0f}ms" if gw_latency is not None else "warming up…"

        guild_count = await ctx.bot.guild_count()
        uptime = format_duration(ctx.bot.uptime_seconds)

        embed = {
            "title": f"🏓 {config.bot_name} status",
            "color": 0x5865F2,
            "fields": [
                {"name": "Gateway latency", "value": gw_status, "inline": True},
                {"name": "API latency", "value": f"{api_latency_ms:.0f}ms", "inline": True},
                {"name": "Database latency", "value": db_status, "inline": True},
                {"name": "Uptime", "value": uptime, "inline": True},
                {"name": "Servers", "value": str(guild_count), "inline": True},
                {"name": "Commands loaded", "value": str(len(set(c.name for c in bot.commands.values()))),
                 "inline": True},
            ],
        }
        try:
            await ctx.bot.rest.edit_message(ctx.channel_id, str(sent["id"]), content="", embeds=[embed])
        except Exception:
            await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])

    @bot.command("help", category="Utility", help_text="List commands. Usage: !help")
    async def help_cmd(ctx: Context) -> None:
        prefix = await ctx.bot.get_prefix(ctx.guild_id)

        by_category: dict[str, list] = {}
        seen = set()
        for cmd in bot.commands.values():
            if cmd.name in seen:
                continue
            seen.add(cmd.name)
            by_category.setdefault(cmd.category, []).append(cmd)

        fields = []
        categories = [c for c in CATEGORY_ORDER if c in by_category]
        categories += [c for c in by_category if c not in categories]

        for category in categories:
            cmds = sorted(by_category[category], key=lambda c: c.name)
            lines = []
            for cmd in cmds:
                perm = permission_name(cmd.required_permission)
                perm_note = "" if perm == "Everyone" else f"  ·  _{perm}_"
                if cmd.owner_only:
                    perm_note = "  ·  _Owner only_"
                lines.append(f"**`{prefix}{cmd.name}`** — {cmd.help_text or 'No description.'}{perm_note}")
            emoji = CATEGORY_EMOJI.get(category, "•")
            fields.append({"name": f"{emoji} {category}", "value": "\n".join(lines), "inline": False})

        embed = {
            "title": f"{config.bot_name} commands",
            "description": f"Prefix for this server: `{prefix}`",
            "color": 0x5865F2,
            "fields": fields,
        }
        await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])
