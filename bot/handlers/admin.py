from __future__ import annotations

import logging
import re

from maxapi import Router
from maxapi.enums.parse_mode import Format
from maxapi.types import Command, MessageCreated

from bot.config import Settings, is_admin, resolve_staff_user_id
from bot.database.db import Database
from bot.filters import DialogFilter
from bot.services.staff import assign_staff
from bot.texts import (
    ADMIN_NO_ACCESS,
    STAFF_ASSIGNED,
    STAFF_ASSIGN_HINT,
    STAFF_ASSIGN_USAGE,
    STAFF_CURRENT,
    STAFF_MUST_START,
)
from bot.utils import event_user_id, message_text

logger = logging.getLogger(__name__)
router = Router()

_ID_RE = re.compile(r"\d+")


@router.message_created(DialogFilter(), Command("staff"))
async def cmd_staff(event: MessageCreated, settings: Settings) -> None:
    staff_id = resolve_staff_user_id(settings)
    await event.message.answer(
        STAFF_CURRENT.format(staff_id=staff_id or "не назначен"),
        format=Format.HTML,
    )


@router.message_created(DialogFilter(), Command("setstaff"))
async def cmd_setstaff(
    event: MessageCreated,
    db: Database,
    settings: Settings,
) -> None:
    user_id = event_user_id(event)
    if not is_admin(user_id, settings):
        await event.message.answer(ADMIN_NO_ACCESS)
        return

    text = message_text(event.message)
    parts = text.split(maxsplit=1)
    raw = parts[1].strip() if len(parts) > 1 else ""
    match = _ID_RE.search(raw)
    if not match:
        await event.message.answer(STAFF_ASSIGN_USAGE, format=Format.HTML)
        return

    new_id = int(match.group(0))
    await assign_staff(db, new_id)
    logger.info("Staff assigned to %s by admin %s", new_id, user_id)
    await event.message.answer(
        STAFF_ASSIGNED.format(staff_id=new_id) + "\n\n" + STAFF_MUST_START,
        format=Format.HTML,
    )

    try:
        await event.bot.send_message(
            user_id=new_id,
            text=STAFF_ASSIGN_HINT,
            format=Format.HTML,
        )
    except Exception:
        logger.warning("Could not notify new staff %s — they may need to /start first", new_id)
        await event.message.answer(
            "Не удалось написать новому сотруднику. "
            "Пусть один раз откроет бота и нажмёт /start."
        )
