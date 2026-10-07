"""Fun commands.

    !roll [NdM]     e.g. !roll, !roll 2d6, !roll d20
    !coinflip
    !wheel opt1, opt2, opt3, ...
    !poll "Question" "Option 1" "Option 2" ... [duration]
    !8ball <question>
    !neofetch       bot/system/community stats, neofetch-style
"""
from __future__ import annotations

import platform
import random
import re
from datetime import datetime, timedelta, timezone

from bot.commands import Bot, Context
from bot.timeutil import format_duration, parse_duration_seconds
from common import db
from common.config import config

EIGHT_BALL_RESPONSES = [
    "It is certain.", "Without a doubt.", "Yes, definitely.", "You may rely on it.",
    "As I see it, yes.", "Most likely.", "Outlook good.", "Yes.", "Signs point to yes.",
    "Reply hazy, try again.", "Ask again later.", "Better not tell you now.",
    "Cannot predict now.", "Concentrate and ask again.",
    "Don't count on it.", "My reply is no.", "My sources say no.",
    "Outlook not so good.", "Very doubtful.",
]

NEOFETCH_ART = [
    "  /\\_/\\  ",
    " ( o.o ) ",
    "  > ^ <  ",
    "         ",
]

DICE_RE = re.compile(r"^(\d*)d(\d+)$", re.IGNORECASE)
NUMBER_EMOJI = [f"{i}\ufe0f\u20e3" for i in range(1, 10)] + ["\U0001F51F"]  # 1..9, then 🔟


def register(bot: Bot) -> None:

    @bot.command("roll", category="Fun", aliases=["dice"], help_text="Roll dice. Usage: !roll [NdM], e.g. !roll 2d6")
    async def roll(ctx: Context) -> None:
        spec = ctx.args[0] if ctx.args else "1d6"
        m = DICE_RE.match(spec)
        if not m:
            await ctx.reply("Format is `NdM`, e.g. `!roll 2d6` or `!roll d20`.")
            return
        count = int(m.group(1)) if m.group(1) else 1
        sides = int(m.group(2))
        if not (1 <= count <= 20) or not (2 <= sides <= 1000):
            await ctx.reply("Keep it reasonable: 1-20 dice, 2-1000 sides.")
            return
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        if count == 1:
            await ctx.reply(f"🎲 Rolled a **{total}** (d{sides}).")
        else:
            await ctx.reply(f"🎲 Rolled {rolls} = **{total}** ({count}d{sides}).")

    @bot.command("coinflip", category="Fun", aliases=["flip", "coin"], help_text="Flip a coin. Usage: !coinflip")
    async def coinflip(ctx: Context) -> None:
        result = random.choice(["Heads", "Tails"])
        await ctx.reply(f"🪙 **{result}!**")

    @bot.command("wheel", category="Fun", aliases=["spin"],
                 help_text="Spin a wheel of options. Usage: !wheel option1, option2, option3")
    async def wheel(ctx: Context) -> None:
        if not ctx.raw_args:
            await ctx.reply("Give some comma-separated options, e.g. `!wheel pizza, tacos, sushi`.")
            return
        options = [o.strip() for o in ctx.raw_args.split(",") if o.strip()]
        if len(options) < 2:
            await ctx.reply("Give at least two comma-separated options.")
            return
        winner = random.choice(options)
        await ctx.embed("🎡 Wheel spin", f"Options: {', '.join(options)}\n\n**Landed on: {winner}**")

    @bot.command("poll", category="Fun",
                 help_text='Start a reaction poll, optionally auto-closing. '
                            'Usage: !poll "Question" "Option 1" "Option 2" ... [duration]')
    async def poll(ctx: Context) -> None:
        if len(ctx.args) < 3:
            await ctx.reply('Give a question and at least two options, each in quotes: '
                             '`!poll "Best pizza topping?" "Pepperoni" "Mushroom" "Pineapple"`. '
                             'Optionally add a duration at the end to auto-close, e.g. `... 1h`.')
            return

        args = list(ctx.args)
        close_seconds = None
        # If the last arg parses as a duration, treat it as auto-close rather
        # than a poll option — as long as there'd still be >=2 options left.
        maybe_duration = parse_duration_seconds(args[-1])
        if maybe_duration is not None and len(args) - 1 >= 3:
            close_seconds = maybe_duration
            args = args[:-1]

        question, *options = args
        if len(options) > 10:
            await ctx.reply("Keep it to 10 options or fewer.")
            return

        lines = "\n".join(f"{NUMBER_EMOJI[i]} {opt}" for i, opt in enumerate(options))
        footer = f"Poll started by {ctx.author.get('username', 'someone')}"
        if close_seconds:
            footer += " · auto-closes and posts results"
        embed = {
            "title": f"📊 {question}",
            "description": lines,
            "color": 0x5865F2,
            "footer": {"text": footer},
        }
        sent = await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])
        message_id = str(sent["id"])
        for i in range(len(options)):
            try:
                await ctx.bot.rest.add_reaction(ctx.channel_id, message_id, NUMBER_EMOJI[i])
            except Exception:
                pass

        close_at = (datetime.now(timezone.utc) + timedelta(seconds=close_seconds)) if close_seconds else None
        await db.add_poll(ctx.guild_id, ctx.channel_id, message_id, question, options, close_at)

    @bot.command("8ball", category="Fun", aliases=["eightball"],
                 help_text="Ask the magic 8-ball a question. Usage: !8ball <question>")
    async def eight_ball(ctx: Context) -> None:
        if not ctx.raw_args:
            await ctx.reply("Ask a question, e.g. `!8ball will it rain tomorrow?`")
            return
        await ctx.reply(f"🎱 {random.choice(EIGHT_BALL_RESPONSES)}")

    @bot.command("neofetch", category="Fun",
                 help_text="Bot/system/community stats, neofetch-style. Usage: !neofetch")
    async def neofetch(ctx: Context) -> None:
        guild = ctx.guild or {}
        prefix = await ctx.bot.get_prefix(ctx.guild_id)
        stats = [
            f"bot@{config.bot_name}",
            "-" * (len(config.bot_name) + 4),
            f"OS: {platform.system()} {platform.release()}",
            f"Python: {platform.python_version()}",
            f"Uptime: {format_duration(ctx.bot.uptime_seconds)}",
            f"Servers: {await ctx.bot.guild_count()}",
            f"Members here: {guild.get('member_count', 'Unknown')}",
            f"Commands: {len(set(c.name for c in ctx.bot.commands.values()))}",
            f"Prefix: {prefix}",
        ]
        lines = []
        art_width = len(NEOFETCH_ART[0])
        for i in range(max(len(NEOFETCH_ART), len(stats))):
            art = NEOFETCH_ART[i] if i < len(NEOFETCH_ART) else " " * art_width
            stat = stats[i] if i < len(stats) else ""
            lines.append(f"{art} {stat}")
        await ctx.reply("```\n" + "\n".join(lines) + "\n```")
