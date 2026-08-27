from __future__ import annotations

from bot.config import Settings, resolve_staff_user_id, set_runtime_staff_user_id
from bot.database.db import Database

STAFF_SETTING_KEY = "staff_user_id"


async def load_staff_assignment(db: Database, settings: Settings) -> int | None:
    """Берём текущего дежурного из БД, иначе из .env."""
    raw = await db.get_setting(STAFF_SETTING_KEY)
    if raw:
        user_id = int(raw)
        set_runtime_staff_user_id(user_id)
        return user_id
    if settings.staff_user_id:
        set_runtime_staff_user_id(settings.staff_user_id)
        await db.set_setting(STAFF_SETTING_KEY, str(settings.staff_user_id))
        return settings.staff_user_id
    return None


async def assign_staff(db: Database, user_id: int) -> int:
    set_runtime_staff_user_id(user_id)
    await db.set_setting(STAFF_SETTING_KEY, str(user_id))
    return user_id


def current_staff_id(settings: Settings) -> int | None:
    return resolve_staff_user_id(settings)
