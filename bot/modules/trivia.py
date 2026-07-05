"""Trivia.

    !trivia    starts a random multiple-choice question, auto-closes
                after 30s (via the scheduler) and awards a small XP
                bonus to everyone who reacted with the correct answer

Questions are pulled live from the Open Trivia DB
(https://opentdb.com), a free, keyless, well-established public API,
so the pool isn't limited to whatever's hardcoded here. The local
QUESTIONS bank below is a fallback for when that API is unreachable,
rate-limited, or returns something unexpected, !trivia should still
work even if the external service is briefly down.

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

OPENTDB_URL = "https://opentdb.com/api.php?amount=1&type=multiple"
OPENTDB_TIMEOUT_SECONDS = 5
OPENTDB_MIN_INTERVAL_SECONDS = 5  # opentdb.com's own documented rate limit: 1 request per 5s per IP

_last_api_call_at = 0.0

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


def _random_local_question() -> dict:
    return random.choice(QUESTIONS)


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
        options = incorrect + [correct]
        random.shuffle(options)
        return {"q": question, "options": options, "correct": options.index(correct)}
    except Exception:
        log.warning("Open Trivia DB response had an unexpected shape, falling back to local bank", exc_info=True)
        return None


def register(bot: Bot) -> None:

    @bot.command("trivia", category="Fun", help_text=f"Start a trivia question, closes in {CLOSE_SECONDS}s. Usage: !trivia")
    async def trivia(ctx: Context) -> None:
        q = await _fetch_question_from_api() or _random_local_question()
        lines = "\n".join(f"{NUMBER_EMOJI[i]} {opt}" for i, opt in enumerate(q["options"]))
        embed = {
            "title": f"🧠 {q['q']}",
            "description": lines,
            "color": 0x9b59b6,
            "footer": {"text": f"React with your answer, closes in {CLOSE_SECONDS}s, correct answers earn {XP_REWARD} XP"},
        }
        sent = await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])
        message_id = str(sent["id"])
        for i in range(len(q["options"])):
            try:
                await ctx.bot.rest.add_reaction(ctx.channel_id, message_id, NUMBER_EMOJI[i])
            except Exception:
                pass

        close_at = datetime.now(timezone.utc) + timedelta(seconds=CLOSE_SECONDS)
        await db.add_trivia_question(ctx.guild_id, ctx.channel_id, message_id, q["q"], q["options"], q["correct"], close_at)
