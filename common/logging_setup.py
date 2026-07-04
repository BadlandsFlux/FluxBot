"""Shared logging configuration for both the bot and dashboard processes.

Controlled by LOG_LEVEL in .env: DEBUG, INFO, WARNING, ERROR, or CRITICAL.
Defaults to INFO. An invalid value falls back to INFO with a warning
rather than crashing on startup.
"""
from __future__ import annotations

import logging

from common.config import config

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def configure_logging() -> None:
    level_name = config.log_level
    level = getattr(logging, level_name, None) if level_name in _VALID_LEVELS else None

    logging.basicConfig(
        level=level or logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    if level is None:
        logging.getLogger("fluxbot").warning(
            "LOG_LEVEL=%r isn't valid (use one of %s), falling back to INFO",
            level_name, ", ".join(sorted(_VALID_LEVELS)),
        )
