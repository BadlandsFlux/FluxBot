from __future__ import annotations

import asyncio
import logging

from bot.commands import Bot
from bot.modules import activity, fun, info, leveling, logging_mod, moderation, reminders, roles, tags, utility
from bot.scheduler import run_scheduler
from bot import voice_tracker
from common import db
from common.config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("fluxbot.main")


async def main() -> None:
    if not config.bot_token:
        raise SystemExit("FLUXER_BOT_TOKEN is not set — copy .env.example to .env and fill it in.")

    await db.init_pool()
    log.info("Connected to Postgres at %s", config.database_url.split("@")[-1])

    bot = Bot(config.bot_token)

    # Register command/event modules.
    moderation.register(bot)
    roles.register(bot)
    fun.register(bot)
    utility.register(bot)
    info.register(bot)
    tags.register(bot)
    reminders.register(bot)
    leveling.register(bot)
    activity.register(bot)
    voice_tracker.register(bot)

    @bot.on("GUILD_CREATE")
    async def on_guild_create(data: dict) -> None:
        guild_id = str(data.get("id"))
        await db.upsert_guild(guild_id, name=data.get("name", ""), icon=data.get("icon"))
        bot.invalidate_guild(guild_id)
        log.info("Tracking guild %s (%s)", guild_id, data.get("name"))

    @bot.on("GUILD_UPDATE")
    async def on_guild_update(data: dict) -> None:
        guild_id = str(data.get("id"))
        await db.upsert_guild(guild_id, name=data.get("name", ""), icon=data.get("icon"))
        bot.invalidate_guild(guild_id)

    log.info("Starting gateway connection to %s ...", config.api_base)
    scheduler_task = asyncio.create_task(run_scheduler(bot))
    try:
        await bot.start()
    finally:
        scheduler_task.cancel()
        await bot.close()
        await db.close_pool()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
