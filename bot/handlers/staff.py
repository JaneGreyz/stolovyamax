from __future__ import annotations

import logging

from maxapi import F, Router
from maxapi.context import MemoryContext
from maxapi.enums.message_link_type import MessageLinkType
from maxapi.enums.parse_mode import Format
from maxapi.types import MessageCallback, MessageCreated

from bot.config import Settings
from bot.database.db import Database
from bot.database.models import ACTIVE_STATUSES, STATUS_CALLBACK_MAP
from bot.filters import StaffFilter
from bot.keyboards import guest_keyboard_for_order, staff_order_keyboard
from bot.services.forwarding import send_as_bot
from bot.services.orders import build_order_card_text, change_order_status
from bot.states import StaffStates
from bot.texts import (
    STAFF_CANCEL_LOCKED,
    STAFF_COMPLETE_LOCKED,
    STAFF_ORDER_CLOSED,
    STAFF_REPLY_CANCELLED,
    STAFF_REPLY_PROMPT,
    STAFF_REPLY_SENT,
    STAFF_STATUS_CHANGED,
    STAFF_UNKNOWN_ORDER,
    STATUS_LABELS,
)
from bot.utils import message_text

logger = logging.getLogger(__name__)


def _guest_reply_keyboard(order) -> list | None:
    return guest_keyboard_for_order(order)


def create_staff_router(settings: Settings) -> Router:
    router = Router()
    staff_filter = StaffFilter(settings)

    @router.message_callback(staff_filter, F.callback.payload.startswith("staff:"))
    async def handle_staff_action(
        event: MessageCallback,
        context: MemoryContext,
        db: Database,
        settings: Settings,
    ) -> None:
        payload = event.callback.payload or ""
        parts = payload.split(":")
        if len(parts) != 3:
            await event.ack(notification="Ошибка")
            return

        _, action, order_id_raw = parts
        try:
            order_id = int(order_id_raw)
        except ValueError:
            await event.ack(notification="Ошибка")
            return

        order = await db.get_order(order_id)
        if not order:
            await event.ack(notification=STAFF_UNKNOWN_ORDER)
            return

        if action == "reply":
            await context.set_state(StaffStates.replying)
            await context.update_data(reply_order_id=order.id)
            await event.ack(notification=STAFF_REPLY_PROMPT.format(order_id=order.id))
            await event.send(
                text=STAFF_REPLY_PROMPT.format(order_id=order.id),
                format=Format.HTML,
            )
            return

        new_status = STATUS_CALLBACK_MAP.get(action)
        if not new_status:
            await event.ack(notification="Неизвестное действие")
            return

        if order.status not in ACTIVE_STATUSES:
            await event.ack(notification=STAFF_ORDER_CLOSED)
            return

        if action == "awaiting_payment":
            await event.ack(notification="Этот статус больше не используется")
            return

        if action == "completed" and order.status != "in_delivery":
            await event.ack(notification=STAFF_COMPLETE_LOCKED)
            return

        if action == "cancelled" and order.status == "in_delivery":
            await event.ack(notification=STAFF_CANCEL_LOCKED)
            return

        order = await change_order_status(event.bot, db, settings, order, new_status)
        label = STATUS_LABELS.get(new_status, new_status)
        await event.answer(
            notification=STAFF_STATUS_CHANGED.format(order_id=order.id, status=label),
            new_text=build_order_card_text(order),
            attachments=staff_order_keyboard(order) or [],
            format=Format.HTML,
        )

    @router.message_created(staff_filter, StaffStates.replying)
    async def staff_typed_reply(
        event: MessageCreated,
        context: MemoryContext,
        db: Database,
        settings: Settings,
    ) -> None:
        if event.message is None:
            return

        text = message_text(event.message)
        if text in {"/cancel", "отмена", "Отмена"}:
            await context.clear()
            await event.message.answer(STAFF_REPLY_CANCELLED)
            return

        data = await context.get_data()
        order_id = data.get("reply_order_id")
        if not order_id:
            await context.clear()
            return

        order = await db.get_order(int(order_id))
        if not order:
            await context.clear()
            await event.message.answer(STAFF_UNKNOWN_ORDER)
            return

        try:
            from bot.services.guest_ui import rotate_guest_keyboards
            from bot.utils import message_mid

            result = await send_as_bot(
                event.bot,
                event.message,
                order.guest_id,
                extra_attachments=_guest_reply_keyboard(order),
            )
            await rotate_guest_keyboards(
                event.bot,
                db,
                order.guest_id,
                message_mid(result),
            )
        except Exception:
            logger.exception("Failed to send anonymous reply to guest %s", order.guest_id)
            await event.message.answer("Не удалось отправить сообщение гостю.")
            return
        await context.clear()
        await event.message.answer(STAFF_REPLY_SENT.format(order_id=order.id))

    @router.message_created(staff_filter)
    async def staff_reply_or_message(
        event: MessageCreated,
        db: Database,
        settings: Settings,
    ) -> None:
        """
        Если сотрудник отвечает Reply на карточку/сообщение гостя —
        пересылаем текст гостю. Иначе игнорируем служебные сообщения.
        """
        message = event.message
        if message is None or message.sender is None or message.sender.is_bot:
            return

        text = message_text(message)
        if text.startswith("/"):
            return

        link = message.link
        if link is None or link.message is None:
            return

        is_reply = (
            link.type == MessageLinkType.REPLY or str(link.type) == "reply"
        )
        if not is_reply:
            return

        order = await db.get_order_by_staff_mid(link.message.mid)
        if not order:
            return

        try:
            from bot.services.guest_ui import rotate_guest_keyboards
            from bot.utils import message_mid

            result = await send_as_bot(
                event.bot,
                message,
                order.guest_id,
                extra_attachments=_guest_reply_keyboard(order),
            )
            await rotate_guest_keyboards(
                event.bot,
                db,
                order.guest_id,
                message_mid(result),
            )
        except Exception:
            logger.exception("Failed to send anonymous reply to guest %s", order.guest_id)
            await message.answer("Не удалось отправить сообщение гостю.")
            return
        await message.answer(STAFF_REPLY_SENT.format(order_id=order.id))

    return router
