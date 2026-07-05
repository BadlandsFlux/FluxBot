"""Trivia.

    !trivia    starts a random multiple-choice question, auto-closes
                after 30s (via the scheduler) and awards a small XP
                bonus to everyone who reacted with the correct answer

Question bank is intentionally small and general-knowledge, not meant
to be exhaustive, easy to extend by just adding entries to QUESTIONS.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from bot.commands import Bot, Context
from common import db

NUMBER_EMOJI = ["1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3", "4\ufe0f\u20e3"]
CLOSE_SECONDS = 30
XP_REWARD = 25

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


def register(bot: Bot) -> None:

    @bot.command("trivia", category="Fun", help_text=f"Start a trivia question, closes in {CLOSE_SECONDS}s. Usage: !trivia")
    async def trivia(ctx: Context) -> None:
        q = random.choice(QUESTIONS)
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
