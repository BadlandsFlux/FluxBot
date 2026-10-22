"""Fun commands.

    !roll [spec ...]    e.g. !roll, !roll 2d6, !roll 1d20+5 2d4, !roll adv, !roll 4d6kh3, !roll help
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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from bot.bounded_cache import BoundedDict
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

NUMBER_EMOJI = [f"{i}\ufe0f\u20e3" for i in range(1, 10)] + ["\U0001F51F"]  # 1..9, then 🔟


GROUP_RE = re.compile(r"^(\d*)d(\d+)(kh\d+|kl\d+)?([+-]\d+)?$", re.IGNORECASE)
ADV_RE = re.compile(r"^(?:adv|advantage)([+-]\d+)?$", re.IGNORECASE)
DIS_RE = re.compile(r"^(?:dis|disadvantage)([+-]\d+)?$", re.IGNORECASE)

STANDARD_DICE = ["d4", "d6", "d8", "d10", "d12", "d20", "d100"]
MAX_GROUPS = len(NUMBER_EMOJI)
MAX_DICE_PER_GROUP = 100
MAX_SIDES = 1000
MAX_MODIFIER = 1000
DISPLAY_CAP = 30
REROLL_ALL_EMOJI = "\U0001F501"
CLOSE_EMOJI = "❌"  # ❌
CLOSED_COLOR = 0x95A5A6  # same gray !poll uses once it's closed

_MAX_ROLL_SESSIONS = 500
_roll_sessions = BoundedDict(max_size=_MAX_ROLL_SESSIONS)


@dataclass
class DiceGroup:
    label: str
    count: int
    sides: int
    keep_mode: Optional[str] = None
    keep_n: Optional[int] = None
    modifier: int = 0
    rolls: list = field(default_factory=list)

    def reroll(self) -> None:
        self.rolls = [random.randint(1, self.sides) for _ in range(self.count)]

    @property
    def _kept_mask(self):
        if not self.keep_mode:
            return [True] * len(self.rolls)
        order = sorted(range(len(self.rolls)), key=lambda i: self.rolls[i], reverse=(self.keep_mode == "kh"))
        kept_idx = set(order[: self.keep_n])
        return [i in kept_idx for i in range(len(self.rolls))]

    @property
    def total(self) -> int:
        kept = [v for v, keep in zip(self.rolls, self._kept_mask) if keep]
        return sum(kept) + self.modifier

    def format(self) -> str:
        indexed = list(zip(self.rolls, self._kept_mask))
        # Kept dice first so a small keep_n on a large count (e.g. 100d6kh3)
        # doesn't get silently truncated out of the displayed pips.
        ordered = [t for t in indexed if t[1]] + [t for t in indexed if not t[1]]
        shown = ordered[:DISPLAY_CAP]
        pieces = []
        for value, keep in shown:
            text = str(value)
            if self.sides == 20 and value == 20:
                text = f"**{value}**\U0001F4A5"
            elif self.sides == 20 and value == 1:
                text = f"**{value}**\U0001F4A2"
            if not keep:
                text = f"~~{text}~~"
            pieces.append(text)
        extra = len(ordered) - len(shown)
        rolls_str = "[" + ", ".join(pieces) + (f", ...+{extra} more" if extra else "") + "]"
        if self.keep_mode:
            kept_label = "highest" if self.keep_mode == "kh" else "lowest"
            suffix = f" -> kept {kept_label} {self.keep_n}"
        else:
            suffix = ""
        mod_str = f" {'+' if self.modifier >= 0 else '-'} {abs(self.modifier)}" if self.modifier else ""
        return f"{rolls_str}{suffix}{mod_str} = **{self.total}**"


@dataclass
class _RollSession:
    user_id: str
    channel_id: str
    title: str
    footer: str
    groups: list


def _parse_dice_spec(spec: str):
    adv = ADV_RE.match(spec)
    dis = DIS_RE.match(spec)
    expanded = spec
    if adv or dis:
        modifier_text = (adv or dis).group(1) or ""
        expanded = f"2d20{'kh' if adv else 'kl'}1{modifier_text}"

    m = GROUP_RE.match(expanded)
    if not m:
        return f"Can't parse `{spec}`. Try dice notation like `2d6`, `1d20+5`, `4d6kh3`, or `adv`/`dis`."

    count = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    keep_token = m.group(3)
    modifier = int(m.group(4)) if m.group(4) else 0

    if not (1 <= count <= MAX_DICE_PER_GROUP):
        return f"`{spec}`: keep dice count between 1 and {MAX_DICE_PER_GROUP}."
    if not (2 <= sides <= MAX_SIDES):
        return f"`{spec}`: keep sides between 2 and {MAX_SIDES}."
    if not (-MAX_MODIFIER <= modifier <= MAX_MODIFIER):
        return f"`{spec}`: keep the modifier within +/-{MAX_MODIFIER}."

    keep_mode = keep_n = None
    if keep_token:
        keep_mode = keep_token[:2].lower()
        keep_n = int(keep_token[2:])
        if not (1 <= keep_n <= count):
            return f"`{spec}`: `{keep_token}` needs a number between 1 and {count}."

    group = DiceGroup(label=spec, count=count, sides=sides, keep_mode=keep_mode, keep_n=keep_n, modifier=modifier)
    group.reroll()
    return group


def _build_roll_embed(title: str, groups, footer: str, closed: bool = False) -> dict:
    fields = []
    for i, g in enumerate(groups):
        # Prefix with the reaction number that rerolls just this group, so
        # it's clear at a glance which click targets which die (the bare
        # !roll's d4/d6/.../d100 fields looked identical otherwise).
        name = f"{NUMBER_EMOJI[i]} {g.label}" if len(groups) > 1 else g.label
        fields.append({"name": name, "value": g.format(), "inline": len(groups) > 1})
    embed = {
        "title": f"{title}, Closed" if closed else title,
        "color": CLOSED_COLOR if closed else 0x5865F2,
        "fields": fields,
        "footer": {"text": footer},
    }
    if len(groups) > 1:
        embed["description"] = f"**Grand total: {sum(g.total for g in groups)}**"
    return embed


def _build_roll_help_embed() -> dict:
    return {
        "title": "🎲 !roll help",
        "color": 0x5865F2,
        "description": "Roll dice, D&D-style. Everything below can be combined in one command.",
        "fields": [
            {"name": "Basic", "value": "`!roll 2d6` — 2 six-sided dice\n`!roll d20` — count defaults to 1", "inline": False},
            {"name": "Modifiers", "value": "`!roll 1d20+5`, `!roll 3d4-2`", "inline": False},
            {"name": "Multiple groups", "value": "`!roll 2d6 1d20+5` — rolls both, plus a grand total", "inline": False},
            {"name": "Keep highest/lowest", "value": "`!roll 4d6kh3` — ability scores (drop the lowest)\n"
                                                       "`!roll 2d20kl1` — same as disadvantage", "inline": False},
            {"name": "Advantage / disadvantage", "value": "`!roll adv` → `2d20kh1`\n`!roll dis` → `2d20kl1`\n"
                                                            "`!roll adv+2` adds a modifier too", "inline": False},
            {"name": "Bare !roll", "value": "Shows the standard set: d4, d6, d8, d10, d12, d20, d100", "inline": False},
            {"name": "Limits", "value": f"Up to {MAX_DICE_PER_GROUP} dice and {MAX_SIDES} sides per group, "
                                         f"±{MAX_MODIFIER} modifier, {MAX_GROUPS} groups per command", "inline": False},
            {"name": "Reactions", "value": f"{REROLL_ALL_EMOJI} reroll everything · a number rerolls just that "
                                            f"group (multi-group rolls only) · {CLOSE_EMOJI} close the roll",
             "inline": False},
        ],
    }


def register(bot: Bot) -> None:

    @bot.command("roll", category="Fun", aliases=["dice"],
                 help_text="Roll dice, D&D-style. Usage: !roll [spec ...], e.g. !roll 2d6, "
                            "!roll 1d20+5 2d4, !roll adv, !roll 4d6kh3. Bare !roll shows the standard set. "
                            "!roll help for the full notation guide. "
                            "React with 🔁 to reroll everything, a number to reroll just that group, "
                            "or ❌ to close.")
    async def roll(ctx: Context) -> None:
        if ctx.args and ctx.args[0].lower() == "help":
            await ctx.bot.rest.send_message(ctx.channel_id, embeds=[_build_roll_help_embed()])
            return

        specs = list(ctx.args) if ctx.args else list(STANDARD_DICE)
        title = "🎲 Standard dice set" if not ctx.args else "🎲 Dice roll"

        if len(specs) > MAX_GROUPS:
            await ctx.reply(f"Keep it to {MAX_GROUPS} dice groups or fewer per roll.")
            return

        groups: list[DiceGroup] = []
        for spec in specs:
            result = _parse_dice_spec(spec)
            if isinstance(result, str):
                await ctx.reply(result)
                return
            groups.append(result)

        footer = f"Rolled by {ctx.author.get('username', 'someone')}"
        embed = _build_roll_embed(title, groups, footer)
        sent = await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])
        message_id = str(sent["id"])

        _roll_sessions[message_id] = _RollSession(
            user_id=str(ctx.author.get("id")), channel_id=ctx.channel_id,
            title=title, footer=footer, groups=groups,
        )
        try:
            await ctx.bot.rest.add_reaction(ctx.channel_id, message_id, REROLL_ALL_EMOJI)
            if len(groups) > 1:
                for i in range(len(groups)):
                    await ctx.bot.rest.add_reaction(ctx.channel_id, message_id, NUMBER_EMOJI[i])
            await ctx.bot.rest.add_reaction(ctx.channel_id, message_id, CLOSE_EMOJI)
        except Exception:
            pass  # the roll itself already sent fine; reroll reactions just won't be clickable

    @bot.on("MESSAGE_REACTION_ADD")
    async def on_roll_reaction(data: dict) -> None:
        message_id = str(data.get("message_id"))
        session = _roll_sessions.get(message_id)
        if not session:
            return

        emoji_data = data.get("emoji", {})
        emoji = emoji_data.get("name") if isinstance(emoji_data, dict) else emoji_data
        group_count = len(session.groups)
        valid_emoji = {REROLL_ALL_EMOJI, CLOSE_EMOJI}
        if group_count > 1:
            valid_emoji |= set(NUMBER_EMOJI[:group_count])
        if emoji not in valid_emoji:
            return

        user_id = str(data.get("user_id"))
        bot_user_id = (bot.gateway.user or {}).get("id")
        if bot_user_id and user_id == str(bot_user_id):
            return  # our own seed reactions added when the roll was posted
        if user_id != session.user_id:
            return  # only the original roller can trigger their own reroll/close

        if emoji == CLOSE_EMOJI:
            del _roll_sessions[message_id]
            embed = _build_roll_embed(session.title, session.groups, session.footer, closed=True)
            try:
                await bot.rest.edit_message(session.channel_id, message_id, content="", embeds=[embed])
            except Exception:
                return
            seeded = [REROLL_ALL_EMOJI, CLOSE_EMOJI] + (list(NUMBER_EMOJI[:group_count]) if group_count > 1 else [])
            for seeded_emoji in seeded:
                try:
                    await bot.rest.remove_own_reaction(session.channel_id, message_id, seeded_emoji)
                except Exception:
                    pass  # bot likely lacks Manage Messages; the roll is still marked closed either way
            return

        indices = range(group_count) if emoji == REROLL_ALL_EMOJI else [NUMBER_EMOJI.index(emoji)]
        for i in indices:
            session.groups[i].reroll()

        embed = _build_roll_embed(session.title, session.groups, session.footer)
        try:
            await bot.rest.edit_message(session.channel_id, message_id, content="", embeds=[embed])
        except Exception:
            return
        try:
            await bot.rest.remove_user_reaction(session.channel_id, message_id, emoji, user_id)
        except Exception:
            pass  # bot likely lacks Manage Messages; reroll still works, just can't re-click instantly

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
