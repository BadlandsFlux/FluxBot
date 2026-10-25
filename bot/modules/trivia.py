"""Trivia.

    !trivia    starts a random multiple-choice question, auto-closes
                after 30s (via the scheduler) and awards a small XP
                bonus to whoever's LATEST reaction, by the time it
                closes, is the correct answer -- changing your mind
                clears your old reaction so only your current pick
                shows, but spamming your reaction past SPAM_PICK_LIMIT
                disqualifies you from that round (and says so in
                channel). Only one round can be open per server at a
                time, and a member's trivia XP is capped per day (see
                guilds.trivia_xp_cap_enabled/trivia_xp_cap_amount on
                the dashboard's Levels tab, on by default) so grinding
                !trivia can't out-earn chat/voice.

Questions are pulled live from the Open Trivia DB
(https://opentdb.com), a free, keyless, well-established public API,
so the pool isn't limited to whatever's hardcoded here. The local
QUESTIONS bank below is a fallback for when that API is unreachable,
rate-limited, or returns something unexpected, !trivia should still
work even if the external service is briefly down. Both paths run
their answer choices through the same `_shuffle_answer` so the correct
answer's on-screen position is freshly randomized every round rather
than sitting at whatever slot the question happened to be authored or
returned in.

CAVEAT: this integration couldn't be tested against the live API from
the environment this bot was built in (no network access to
opentdb.com there), only against its publicly documented behavior. It
should work as described, but the first real !trivia run against the
actual API is effectively the first real-world test of this code path.
"""
from __future__ import annotations

import html
import logging
import random
import time
from datetime import datetime, timedelta, timezone

import aiohttp

from bot.commands import Bot, Context
from common import db

log = logging.getLogger("fluxbot.trivia")

NUMBER_EMOJI = ["1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3", "4\ufe0f\u20e3"]
CLOSE_SECONDS = 30
XP_REWARD = 25

# Fallback for the rare case a guild's row is missing when the scheduler
# closes a round (see bot/scheduler.py's _close_trivia); every real guild
# row carries its own trivia_xp_cap_amount, defaulted to this same value
# by the schema. Four correct answers' worth a day -- trivia rounds are
# guild-wide (anyone can react, not just one member per round), so this
# only ever limits one member grinding !trivia solo, not normal play.
TRIVIA_XP_CAP_DEFAULT = 150

_DEFAULT_COLOR = 0x9b59b6
_DIFFICULTY_COLORS = {"easy": 0x2ecc71, "medium": 0x9b59b6, "hard": 0xe74c3c}

OPENTDB_URL = "https://opentdb.com/api.php?amount=1&type=multiple"
OPENTDB_TIMEOUT_SECONDS = 5
OPENTDB_MIN_INTERVAL_SECONDS = 5  # opentdb.com's own documented rate limit: 1 request per 5s per IP

_last_api_call_at = 0.0

# Changing your mind is fine; a 6th reaction in the same round reads as
# spamming rather than genuinely weighing the options, and disqualifies
# you. Scoring is always driven by our own pick history below, never by
# asking Fluxer what's currently reacted -- on_trivia_reaction's removal
# of a member's previous pick is purely a visual nicety on top of that,
# and self-heals (re-seeds its own reaction right after) in case removing
# one member's reaction ever clears the whole thing for everyone again.
SPAM_PICK_LIMIT = 5

# message_id -> {"option_emoji": [...], "picks": {user_id: [emoji, ...]},
# "disqualified": {user_id, ...}} for each still-open round. In-memory
# only (same tradeoff as !roll/!help's own reaction sessions): a bot
# restart mid-round loses this, so _close_trivia (scheduler.py) falls
# back to asking Fluxer who's currently reacting with what when a round
# it's about to close has no entry here.
_active_trivia_rounds: dict[str, dict] = {}

QUESTIONS = [
    {"q": "What's the largest planet in the solar system?", "options": ["Earth", "Jupiter", "Saturn", "Neptune"], "correct": 1},
    {"q": "How many continents are there?", "options": ["5", "6", "7", "8"], "correct": 2},
    {"q": "What's the chemical symbol for gold?", "options": ["Go", "Gd", "Au", "Ag"], "correct": 2},
    {"q": "Which language has the most native speakers worldwide?", "options": ["English", "Spanish", "Hindi", "Mandarin Chinese"], "correct": 3},
    {"q": "What year did the Berlin Wall fall?", "options": ["1987", "1989", "1991", "1993"], "correct": 1},
    {"q": "What's the smallest prime number?", "options": ["0", "1", "2", "3"], "correct": 2},
    {"q": "Which planet is known as the Red Planet?", "options": ["Venus", "Mars", "Jupiter", "Mercury"], "correct": 1},
    {"q": "How many strings does a standard guitar have?", "options": ["4", "5", "6", "7"], "correct": 2},
    {"q": "What's the capital of Australia?", "options": ["Sydney", "Melbourne", "Canberra", "Perth"], "correct": 2},
    {"q": "Which element has the atomic number 1?", "options": ["Helium", "Hydrogen", "Oxygen", "Carbon"], "correct": 1},
    {"q": "What's the longest river in the world?", "options": ["Amazon", "Nile", "Yangtze", "Mississippi"], "correct": 1},
    {"q": "How many sides does a hexagon have?", "options": ["5", "6", "7", "8"], "correct": 1},
]


def _shuffle_answer(correct: str, incorrect: list[str]) -> tuple[list[str], int]:
    """Shared by both question sources: shuffles `correct` into a fresh
    random slot among `incorrect` every time it's called, rather than
    trusting whatever order a source already handed back. The local
    QUESTIONS bank's own hand-authored `options` lists skew hard toward
    index 1-2 (the correct answer was never once written as the first
    option), which would otherwise make the right answer's position
    visibly predictable the moment someone sees a few repeats."""
    options = incorrect + [correct]
    random.shuffle(options)
    return options, options.index(correct)


def _random_local_question() -> dict:
    q = random.choice(QUESTIONS)
    correct_text = q["options"][q["correct"]]
    incorrect_texts = [opt for i, opt in enumerate(q["options"]) if i != q["correct"]]
    options, correct_index = _shuffle_answer(correct_text, incorrect_texts)
    return {"q": q["q"], "options": options, "correct": correct_index, "category": None, "difficulty": None}


async def _fetch_question_from_api() -> dict | None:
    """Best-effort fetch from Open Trivia DB. Returns None on absolutely
    anything unexpected (network error, timeout, rate limit, malformed
    response) so the caller can fall back to the local bank without the
    command ever actually failing for the user."""
    global _last_api_call_at
    now = time.monotonic()
    if now - _last_api_call_at < OPENTDB_MIN_INTERVAL_SECONDS:
        return None  # don't risk tripping their rate limit, just use the local bank this time
    _last_api_call_at = now

    try:
        timeout = aiohttp.ClientTimeout(total=OPENTDB_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(OPENTDB_URL) as resp:
                if resp.status != 200:
                    log.warning("Open Trivia DB returned HTTP %s, falling back to local bank", resp.status)
                    return None
                data = await resp.json(content_type=None)
    except Exception:
        log.warning("Open Trivia DB request failed, falling back to local bank", exc_info=True)
        return None

    if data.get("response_code") != 0 or not data.get("results"):
        log.warning("Open Trivia DB response_code=%s (0=success), falling back to local bank",
                    data.get("response_code"))
        return None

    try:
        result = data["results"][0]
        question = html.unescape(result["question"])
        correct = html.unescape(result["correct_answer"])
        incorrect = [html.unescape(a) for a in result["incorrect_answers"]]
        options, correct_index = _shuffle_answer(correct, incorrect)
        category = html.unescape(result["category"]) if result.get("category") else None
        return {
            "q": question, "options": options, "correct": correct_index,
            "category": category, "difficulty": result.get("difficulty"),
        }
    except Exception:
        log.warning("Open Trivia DB response had an unexpected shape, falling back to local bank", exc_info=True)
        return None


def register(bot: Bot) -> None:

    @bot.command("trivia", category="Fun", help_text=f"Start a trivia question, closes in {CLOSE_SECONDS}s. Usage: !trivia")
    async def trivia(ctx: Context) -> None:
        existing = await db.get_open_trivia(ctx.guild_id)
        if existing:
            await ctx.reply(
                f"A trivia question is already running in <#{existing['channel_id']}> "
                "-- answer it or wait for it to close before starting another."
            )
            return

        q = await _fetch_question_from_api() or _random_local_question()
        close_at = datetime.now(timezone.utc) + timedelta(seconds=CLOSE_SECONDS)

        lines = "\n".join(f"{NUMBER_EMOJI[i]} {opt}" for i, opt in enumerate(q["options"]))
        fields = [
            {"name": "Closes", "value": f"<t:{int(close_at.timestamp())}:R>", "inline": True},
            {"name": "Reward", "value": f"+{XP_REWARD} XP", "inline": True},
        ]
        if q.get("category"):
            fields.append({"name": "Category", "value": q["category"], "inline": True})
        embed = {
            "title": f"🧠 {q['q']}",
            "description": lines,
            "color": _DIFFICULTY_COLORS.get(q.get("difficulty"), _DEFAULT_COLOR),
            "fields": fields,
            "footer": {"text": "React with your answer -- you can change your mind, just don't spam it"},
        }
        sent = await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])
        message_id = str(sent["id"])
        option_emoji = NUMBER_EMOJI[:len(q["options"])]
        _active_trivia_rounds[message_id] = {"option_emoji": option_emoji, "picks": {}, "disqualified": set()}
        for emoji in option_emoji:
            try:
                await ctx.bot.rest.add_reaction(ctx.channel_id, message_id, emoji)
            except Exception:
                pass

        await db.add_trivia_question(ctx.guild_id, ctx.channel_id, message_id, q["q"], q["options"], q["correct"], close_at)

    @bot.on("MESSAGE_REACTION_ADD")
    async def on_trivia_reaction(data: dict) -> None:
        message_id = str(data.get("message_id"))
        round_state = _active_trivia_rounds.get(message_id)
        if not round_state:
            return

        emoji_data = data.get("emoji", {})
        emoji = emoji_data.get("name") if isinstance(emoji_data, dict) else emoji_data
        if emoji not in round_state["option_emoji"]:
            return

        user_id = str(data.get("user_id"))
        bot_user_id = (bot.gateway.user or {}).get("id")
        if bot_user_id and user_id == str(bot_user_id):
            return  # our own seed reactions

        if user_id in round_state["disqualified"]:
            return  # already flagged and told once; nothing more to do

        picks = round_state["picks"].setdefault(user_id, [])
        previous_emoji = picks[-1] if picks else None
        picks.append(emoji)

        if len(picks) > SPAM_PICK_LIMIT:
            round_state["disqualified"].add(user_id)
            try:
                await bot.rest.send_message(
                    str(data.get("channel_id")),
                    content=f"<@{user_id}> changed their answer too many times and is disqualified from this round.",
                    allowed_mentions=bot.rest.mention_only(user_id),
                )
            except Exception:
                pass
            return

        if previous_emoji and previous_emoji != emoji:
            channel_id = str(data.get("channel_id"))
            try:
                await bot.rest.remove_user_reaction(channel_id, message_id, previous_emoji, user_id)
            except Exception:
                pass  # bot likely lacks Manage Messages; _close_trivia's own pick history still scores correctly
            # Re-assert our own seed reaction on the emoji we just cleared:
            # removing one member's reaction has, on this Fluxer instance,
            # sometimes cleared the whole reaction rather than just theirs
            # (see the PR that first found this), which would make that
            # option's reaction vanish for everyone. Re-adding our seed is a
            # no-op if it's still there and heals it the instant it isn't.
            try:
                await bot.rest.add_reaction(channel_id, message_id, previous_emoji)
            except Exception:
                pass  # best-effort repair; a miss here just means that option stays gone until someone else reacts to it
