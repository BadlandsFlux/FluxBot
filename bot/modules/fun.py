"""Fun commands.

    !roll [NdM]     e.g. !roll, !roll 2d6, !roll d20
    !coinflip
    !wheel opt1, opt2, opt3, ...
"""
from __future__ import annotations

import random
import re

from bot.commands import Bot, Context

DICE_RE = re.compile(r"^(\d*)d(\d+)$", re.IGNORECASE)


def register(bot: Bot) -> None:

    @bot.command("roll", aliases=["dice"], help_text="Roll dice. Usage: !roll [NdM], e.g. !roll 2d6")
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

    @bot.command("coinflip", aliases=["flip", "coin"], help_text="Flip a coin. Usage: !coinflip")
    async def coinflip(ctx: Context) -> None:
        result = random.choice(["Heads", "Tails"])
        await ctx.reply(f"🪙 **{result}!**")

    @bot.command("wheel", aliases=["spin"],
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
