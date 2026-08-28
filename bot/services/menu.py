from __future__ import annotations

import asyncio
import logging

from maxapi import Bot
from maxapi.enums.parse_mode import Format
from maxapi.enums.upload_type import UploadType
from maxapi.types import InputMedia

from bot.config import BASE_DIR, Settings
from bot.database.db import Database
from bot.texts import (
    GROUP_MENU_INTRO,
    MENU_FALLBACK,
    PERMANENT_MENU_CAPTION,
    SENDING_MENUS,
)

logger = logging.getLogger(__name__)

PERMANENT_MENU_PATH = BASE_DIR / "bot" / "assets" / "permanent_menu.png"


async def send_permanent_menu(
    bot: Bot,
    settings: Settings,
    user_id: int,
) -> bool:
    """Отправляем готовое фото постоянного меню — без PDF и Google Sheets."""
    if not PERMANENT_MENU_PATH.is_file():
        logger.error("Permanent menu file is missing: %s", PERMANENT_MENU_PATH)
        return False

    try:
        await bot.send_message(
            user_id=user_id,
            text=PERMANENT_MENU_CAPTION,
            attachments=[
                InputMedia(
                    path=str(PERMANENT_MENU_PATH),
                    type=UploadType.IMAGE,
                )
            ],
            format=Format.HTML,
        )
    except Exception:
        logger.exception("Failed to send permanent menu to %s", user_id)
        return False
    logger.info("Permanent menu sent to user %s", user_id)
    return True


send_permanent_menu_from_sheets = send_permanent_menu


async def send_group_menu_to_guest(
    bot: Bot,
    db: Database,
    user_id: int,
) -> bool:
    """Отправляем гостю последние сообщения из группы (меню дня)."""
    saved = await db.get_group_menu_mids()
    if not saved:
        return False

    _, mids = saved
    sent_any = False
    await bot.send_message(
        user_id=user_id,
        text=GROUP_MENU_INTRO,
        format=Format.HTML,
    )
    await asyncio.sleep(0.4)

    from bot.services.forwarding import send_copy_to_user

    for mid in mids:
        try:
            source = await bot.get_message(mid)
            if source is None:
                continue
            await send_copy_to_user(bot, source, user_id)
            sent_any = True
            await asyncio.sleep(0.5)
        except Exception:
            logger.exception("Failed to copy group menu message %s", mid)
    return sent_any


async def send_menus_to_guest(
    bot: Bot,
    db: Database,
    settings: Settings,
    user_id: int,
) -> None:
    try:
        await bot.send_message(
            user_id=user_id,
            text=SENDING_MENUS,
            format=Format.HTML,
        )
        await asyncio.sleep(0.4)

        group_ok = await send_group_menu_to_guest(bot, db, user_id)
        permanent_ok = await send_permanent_menu(bot, settings, user_id)
        if not group_ok and not permanent_ok:
            await bot.send_message(
                user_id=user_id,
                text=MENU_FALLBACK,
                format=Format.HTML,
            )
    except Exception:
        logger.exception("Failed to send menus to guest %s", user_id)
        await bot.send_message(
            user_id=user_id,
            text=MENU_FALLBACK,
            format=Format.HTML,
        )
