"""Fun commands.

    !roll [NdM]     e.g. !roll, !roll 2d6, !roll d20
    !coinflip
    !wheel opt1, opt2, opt3, ...
    !poll "Question" "Option 1" "Option 2" ...
"""
from __future__ import annotations

import random
import re

from bot.commands import Bot, Context

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
                 help_text='Start a reaction poll. Usage: !poll "Question" "Option 1" "Option 2" ...')
    async def poll(ctx: Context) -> None:
        if len(ctx.args) < 3:
            await ctx.reply('Give a question and at least two options, each in quotes: '
                             '`!poll "Best pizza topping?" "Pepperoni" "Mushroom" "Pineapple"`')
            return
        question, *options = ctx.args
        if len(options) > 10:
            await ctx.reply("Keep it to 10 options or fewer.")
            return

        lines = "\n".join(f"{NUMBER_EMOJI[i]} {opt}" for i, opt in enumerate(options))
        embed = {
            "title": f"📊 {question}",
            "description": lines,
            "color": 0x5865F2,
            "footer": {"text": f"Poll started by {ctx.author.get('username', 'someone')}"},
        }
        sent = await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])
        message_id = str(sent["id"])
        for i in range(len(options)):
            try:
                await ctx.bot.rest.add_reaction(ctx.channel_id, message_id, NUMBER_EMOJI[i])
            except Exception:
                pass
