from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ID группы, который узнали в рантайме (событие bot_added или /id),
# если GROUP_CHAT_ID ещё не прописан в .env
_runtime_group_chat_id: int | None = None
# Текущий дежурный сотрудник (можно менять командой /setstaff без перезапуска)
_runtime_staff_user_id: int | None = None


def set_runtime_group_chat_id(chat_id: int) -> None:
    global _runtime_group_chat_id
    _runtime_group_chat_id = chat_id


def resolve_group_chat_id(settings: Settings) -> int | None:
    return settings.group_chat_id or _runtime_group_chat_id


def set_runtime_staff_user_id(user_id: int | None) -> None:
    global _runtime_staff_user_id
    _runtime_staff_user_id = user_id


def resolve_staff_user_id(settings: Settings) -> int | None:
    return _runtime_staff_user_id or settings.staff_user_id


def resolve_group_forward_user_id(settings: Settings) -> int | None:
    return settings.group_forward_user_id or resolve_staff_user_id(settings)


def is_admin(user_id: int | None, settings: Settings) -> bool:
    return user_id is not None and user_id in settings.admin_ids


def is_staff_operator(user_id: int | None, settings: Settings) -> bool:
    if user_id is None:
        return False
    if is_admin(user_id, settings):
        return True
    return user_id == resolve_staff_user_id(settings)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    staff_user_id: int | None
    admin_ids: tuple[int, ...]
    group_chat_id: int | None
    group_forward_user_id: int | None
    database_path: Path
    timezone: str
    work_start: time
    full_menu_start: time
    work_end: time
    work_weekdays_only: bool
    skip_working_hours: bool
    min_order_amount: int
    daily_menu_sheet_id: str | None
    daily_menu_gid: int | None


def _parse_time(value: str) -> time:
    hours, minutes = value.strip().split(":")
    return time(int(hours), int(minutes))


def _parse_optional_int(raw: str | None) -> int | None:
    if not raw or not raw.strip():
        return None
    return int(raw.strip())


def _parse_admin_ids(value: str) -> tuple[int, ...]:
    if not value.strip():
        return ()
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def load_settings() -> Settings:
    database_path = Path(os.getenv("DATABASE_PATH", "data/bot.db"))
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path

    staff_user_id = _parse_optional_int(os.getenv("STAFF_USER_ID"))
    group_forward_user_id = _parse_optional_int(os.getenv("GROUP_FORWARD_USER_ID"))
    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

    sheet_id = os.getenv("DAILY_MENU_SHEET_ID", "").strip() or None
    gid_raw = os.getenv("DAILY_MENU_GID", "").strip()

    return Settings(
        bot_token=os.environ["BOT_TOKEN"],
        staff_user_id=staff_user_id,
        admin_ids=admin_ids,
        group_chat_id=_parse_optional_int(os.getenv("GROUP_CHAT_ID")),
        group_forward_user_id=group_forward_user_id,
        database_path=database_path,
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        work_start=_parse_time(os.getenv("WORK_START", "08:45")),
        full_menu_start=_parse_time(os.getenv("FULL_MENU_START", "08:45")),
        work_end=_parse_time(os.getenv("WORK_END", "16:45")),
        work_weekdays_only=os.getenv("WORK_WEEKDAYS_ONLY", "1") == "1",
        skip_working_hours=os.getenv("SKIP_WORKING_HOURS", "0") == "1",
        min_order_amount=int(os.getenv("MIN_ORDER_AMOUNT", "500")),
        daily_menu_sheet_id=sheet_id,
        daily_menu_gid=int(gid_raw) if gid_raw else None,
    )
