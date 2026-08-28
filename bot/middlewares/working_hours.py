from datetime import datetime
from typing import Any, Awaitable, Callable
import logging

from maxapi.enums.parse_mode import Format
from maxapi.filters.middleware import BaseMiddleware
from maxapi.types import MessageCallback, UpdateUnion

from bot.config import Settings
from bot.keyboards import guest_main_keyboard
from bot.services.working_hours import format_work_hours, get_tz, is_working_hours
from bot.texts import OUTSIDE_WORKING_HOURS, OUTSIDE_WORKING_HOURS_WEEKEND

logger = logging.getLogger(__name__)


class WorkingHoursMiddleware(BaseMiddleware):
    """Блокируем оформление заказа вне рабочего времени."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _outside_message(self) -> str:
        schedule = format_work_hours(self.settings)
        tz = get_tz(self.settings)
        now = datetime.now(tz)
        if self.settings.work_weekdays_only and now.weekday() >= 5:
            return OUTSIDE_WORKING_HOURS_WEEKEND.format(schedule=schedule)
        return OUTSIDE_WORKING_HOURS.format(schedule=schedule)

    async def __call__(
        self,
        handler: Callable[[UpdateUnion, dict[str, Any]], Awaitable[Any]],
        event_object: UpdateUnion,
        data: dict[str, Any],
    ) -> Any:
        if is_working_hours(self.settings):
            return await handler(event_object, data)

        payload = ""
        if isinstance(event_object, MessageCallback) and event_object.callback.payload:
            payload = event_object.callback.payload

        if payload == "main:order" or payload.startswith("addr:"):
            text = self._outside_message()
            logger.info("Order blocked outside working hours, payload=%s", payload)
            try:
                await event_object.answer(notification="Сейчас нерабочее время")
            except Exception:
                logger.exception("Failed to ack callback outside hours")
            try:
                from bot.services.guest_ui import send_callback_guest_buttons

                db = data.get("db")
                if db is not None:
                    await send_callback_guest_buttons(
                        event_object,
                        db,
                        text=text,
                        attachments=guest_main_keyboard(),
                    )
                else:
                    await event_object.send(
                        text=text,
                        attachments=guest_main_keyboard(),
                        format=Format.HTML,
                    )
            except Exception:
                logger.exception("Failed to send outside-hours message")
            return None

        return await handler(event_object, data)
