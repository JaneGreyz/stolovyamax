from __future__ import annotations

import logging

from maxapi import Bot, Dispatcher
from maxapi.types import BotCommand

from bot.config import load_settings, set_runtime_group_chat_id
from bot.database.db import Database
from bot.handlers.admin import router as admin_router
from bot.handlers.common import create_group_router, router as common_router
from bot.handlers.guest import router as guest_router
from bot.handlers.staff import create_staff_router
from bot.middlewares import DependencyMiddleware, LogUpdatesMiddleware
from bot.middlewares.working_hours import WorkingHoursMiddleware
from bot.services.staff import load_staff_assignment

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings()
    bot = Bot(token=settings.bot_token)

    logger.info("Starting MAX bot...")
    logger.info("Staff user id: %s", settings.staff_user_id)
    logger.info("Admin ids: %s", settings.admin_ids)
    logger.info("Group chat id: %s", settings.group_chat_id)

    db = Database(settings.database_path)
    await db.connect()

    saved_group = await db.get_setting("group_chat_id")
    if saved_group:
        set_runtime_group_chat_id(int(saved_group))
        logger.info("Loaded group_chat_id from db: %s", saved_group)

    current_staff = await load_staff_assignment(db, settings)
    logger.info("Active staff user id: %s", current_staff)

    dp = Dispatcher()
    dp.register_outer_middleware(LogUpdatesMiddleware())
    dp.register_outer_middleware(DependencyMiddleware(db, settings))
    dp.register_outer_middleware(WorkingHoursMiddleware(settings))

    # /id и bot_added первыми, иначе пересылка из канала «съедает» команду
    dp.include_routers(
        common_router,
        admin_router,
        create_group_router(settings),
        create_staff_router(settings),
        guest_router,
    )

    try:
        await bot.delete_webhook()
    except Exception:
        logger.warning("Could not delete webhook (это нормально, если его не было)")

    try:
        await bot.set_commands(
            BotCommand(name="/start", description="Начать заказ"),
            BotCommand(name="/id", description="Показать ID чата и пользователя"),
            BotCommand(name="/staff", description="Кто сейчас дежурный"),
            BotCommand(name="/setstaff", description="Сменить дежурного (админ)"),
        )
    except Exception:
        logger.warning("Could not set bot commands")

    logger.info("Polling started")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        session = getattr(bot, "session", None)
        if session is not None:
            await session.close()


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except KeyError as exc:
        logger.error("Missing required environment variable: %s", exc)
        raise SystemExit(1) from exc
