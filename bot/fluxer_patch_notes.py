"""Daily Fluxer platform patch notes.

Summarizes the commits landed on fluxerapp/fluxer's `main` branch for a
given calendar day (always computed in America/Chicago, regardless of
where this bot itself runs) and posts them as an embed to whichever
guilds have configured a channel for it. See bot/scheduler.py for when
this actually runs, and common/db.py's fluxer_patch_notes_* functions
for the dedupe/cache log this relies on to fetch GitHub once per day
rather than once per guild.

The upstream repo uses Conventional Commits with PRs squash-merged
(confirmed by hand against the real commit history), so grouping by
theme is a plain prefix match, no summarization model needed.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import aiohttp

from common.config import config

log = logging.getLogger("fluxbot.fluxer_patch_notes")

REPO = "fluxerapp/fluxer"
_API_BASE = f"https://api.github.com/repos/{REPO}"
_CENTRAL = ZoneInfo("America/Chicago")

# Safety cap on pagination: 100/page * 10 = 1000 commits in one day, far
# beyond anything that's ever realistic, just a backstop against an
# accidental infinite loop if GitHub's pagination behaves unexpectedly.
_MAX_PAGES = 10

_COMMIT_PREFIX_RE = re.compile(r"^([a-zA-Z]+)(?:\([^)]*\))?!?:\s*(.+)$")
_BUCKET_LABELS = {"feat": "✨ Features", "fix": "🐛 Fixes"}
_DEFAULT_BUCKET = "🔧 Maintenance"
_BUCKET_ORDER = ["✨ Features", "🐛 Fixes", _DEFAULT_BUCKET]


def central_date_window_utc(report_date: date) -> tuple[str, str]:
    """The (since, until) ISO 8601 UTC timestamps spanning midnight-to-
    midnight of `report_date` in America/Chicago, the window GitHub's
    commits API filters by. Computed explicitly rather than trusting
    GitHub's own "Commits on <date>" day-grouping headers on its commits
    page, which reflect UTC, not Central time -- a commit in the first
    few hours of a UTC day can actually belong to the *previous* Central
    day, and vice versa near the other end."""
    start = datetime(report_date.year, report_date.month, report_date.day, tzinfo=_CENTRAL)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


async def fetch_commits_for_date(report_date: date) -> list[dict]:
    """Every commit on `main` whose committer date falls within
    `report_date`'s Central-time window. Committer date, not author
    date: what matters for "landed on main today" is when it was
    actually merged, not whenever the change was first authored."""
    since, until = central_date_window_utc(report_date)
    headers = {
        "User-Agent": f"{config.bot_name} (https://github.com/your-org/fluxbot, 0.1)",
        "Accept": "application/vnd.github+json",
    }
    start = datetime(report_date.year, report_date.month, report_date.day, tzinfo=_CENTRAL)
    end = start + timedelta(days=1)

    commits: list[dict] = []
    async with aiohttp.ClientSession(headers=headers) as session:
        for page in range(1, _MAX_PAGES + 1):
            params = {"sha": "main", "since": since, "until": until, "per_page": 100, "page": page}
            async with session.get(f"{_API_BASE}/commits", params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"GitHub commits API returned HTTP {resp.status}: {body[:300]}")
                batch = await resp.json()
            if not batch:
                break
            commits.extend(batch)
            if len(batch) < 100:
                break

    # Defensive re-check against the window: since/until should already
    # guarantee this, but a commit's own timestamp is the ground truth.
    def _in_window(commit: dict) -> bool:
        raw = commit.get("commit", {}).get("committer", {}).get("date")
        if not raw:
            return False
        committed_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return start <= committed_at.astimezone(_CENTRAL) < end

    return [c for c in commits if _in_window(c)]


def _bucket_for(message: str) -> tuple[str, str]:
    """(bucket label, display text) for a commit's first message line.
    Falls back to Maintenance (whole message, unprefixed) for anything
    that doesn't match the Conventional Commits shape, so an occasional
    off-convention commit still shows up rather than being dropped."""
    first_line = message.splitlines()[0].strip() if message else ""
    m = _COMMIT_PREFIX_RE.match(first_line)
    if not m:
        return _DEFAULT_BUCKET, first_line
    commit_type, rest = m.group(1).lower(), m.group(2)
    return _BUCKET_LABELS.get(commit_type, _DEFAULT_BUCKET), rest


def build_patch_notes_embed(commits: list[dict], report_date: date) -> dict:
    title = f"Fluxer patch notes — {report_date.isoformat()}"
    commits_url = f"https://github.com/{REPO}/commits/main/"
    if not commits:
        return {
            "title": title,
            "url": commits_url,
            "description": f"No commits to {REPO}'s main branch that day.",
            "color": 0x5865F2,
            "footer": {"text": "0 commits"},
        }

    buckets: dict[str, list[str]] = {}
    for c in commits:
        message = c.get("commit", {}).get("message", "")
        html_url = c.get("html_url", commits_url)
        label, text = _bucket_for(message)
        buckets.setdefault(label, []).append(f"[{text}]({html_url})" if text else f"[{message}]({html_url})")

    sections = [
        f"**{label}**\n" + "\n".join(f"• {line}" for line in buckets[label])
        for label in _BUCKET_ORDER if label in buckets
    ]
    count = len(commits)
    return {
        "title": title,
        "url": commits_url,
        "description": "\n\n".join(sections),
        "color": 0x5865F2,
        "footer": {"text": f"{count} commit{'s' if count != 1 else ''}"},
    }


async def generate_patch_notes(report_date: date) -> tuple[dict, int]:
    """Returns (embed, commit_count) for `report_date`. The one place
    both the embed content and the count stored in
    fluxer_patch_notes_log come from, so they can never drift apart."""
    commits = await fetch_commits_for_date(report_date)
    embed = build_patch_notes_embed(commits, report_date)
    return embed, len(commits)


def central_now() -> datetime:
    return datetime.now(_CENTRAL)


def yesterday_in_central(now: Optional[datetime] = None) -> date:
    """The most recently *completed* Central-time calendar day as of
    `now` (real time if omitted). The scheduler always reports on this
    date, regardless of what hour its trigger is configured for: a
    trigger fires once a day at some HH:MM Central and always delivers a
    complete day's digest (yesterday's), never a still-in-progress
    partial day's."""
    return ((now or central_now()) - timedelta(days=1)).date()
