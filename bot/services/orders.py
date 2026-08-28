from __future__ import annotations

import logging
from html import escape

from maxapi import Bot
from maxapi.context import MemoryContext
from maxapi.enums.parse_mode import Format

from bot.config import Settings, resolve_staff_user_id
from bot.database.db import Database
from bot.database.models import Order
from bot.keyboards import guest_keyboard_for_order, staff_order_keyboard
from bot.services.forwarding import copy_to_duty, notify_duty, remember_staff_mid, send_to_user
from bot.texts import (
    GUEST_STATUS_NOTIFICATIONS,
    STAFF_GUEST_CANCELLED,
    STAFF_NOT_CONFIGURED,
    STAFF_ORDER_CARD,
    STATUS_LABELS,
)

logger = logging.getLogger(__name__)


def build_order_card_text(order: Order) -> str:
    username_line = ""
    if order.guest_username:
        username_line = f"🔗 <b>Username:</b> @{escape(order.guest_username)}\n"

    status_line = ""
    if order.status != "new":
        label = STATUS_LABELS.get(order.status, order.status)
        status_line = f"\n📌 <b>Статус:</b> {label}\n"

    return STAFF_ORDER_CARD.format(
        order_id=order.id,
        address=escape(order.address),
        clarification=escape(order.address_clarification or "—"),
        phone=escape(order.phone),
        guest_name=escape(order.guest_name),
        guest_id=order.guest_id,
        username_line=username_line,
        order_text=escape(order.order_text or "—"),
        status_line=status_line,
    )


async def send_order_to_staff(
    bot: Bot,
    db: Database,
    settings: Settings,
    order: Order,
) -> Order:
    """Отправляем карточку заказа сотруднику в личку."""
    if not resolve_staff_user_id(settings) and not settings.admin_ids:
        logger.error("STAFF_USER_ID is not set, cannot notify staff")
        raise RuntimeError(STAFF_NOT_CONFIGURED)

    markup = staff_order_keyboard(order)
    result = await notify_duty(
        bot,
        settings,
        build_order_card_text(order),
        attachments=markup,
    )
    mid = None
    if result and result.message and result.message.body:
        mid = result.message.body.mid

    await db.mark_order_submitted(order.id, mid)
    if mid:
        await db.save_staff_message(mid, order.id, "card")

    updated = await db.get_order(order.id)
    if updated is None:
        raise RuntimeError("Order not found after submit")
    return updated


async def finalize_order(
    bot: Bot,
    db: Database,
    settings: Settings,
    order: Order,
    order_text: str,
) -> Order:
    await db.update_order_text(order.id, order_text)
    order = await db.get_order(order.id)
    if order is None:
        raise RuntimeError("Order not found")

    if not order.submitted:
        order = await send_order_to_staff(bot, db, settings, order)
    return order


async def cancel_guest_active_order(
    bot: Bot,
    db: Database,
    settings: Settings,
    guest_id: int,
    context: MemoryContext | None = None,
) -> Order | None:
    order = await db.get_active_order_for_guest(guest_id)
    if not order:
        return None

    if order.status == "in_delivery":
        return None

    await db.update_order_status(order.id, "cancelled")
    if context is not None:
        await context.clear()

    if order.submitted:
        try:
            await notify_duty(
                bot,
                settings,
                STAFF_GUEST_CANCELLED.format(order_id=order.id),
            )
        except Exception:
            logger.exception("Failed to notify staff about guest cancel #%s", order.id)

    return order


async def change_order_status(
    bot: Bot,
    db: Database,
    settings: Settings,
    order: Order,
    new_status: str,
) -> Order:
    await db.update_order_status(order.id, new_status)
    order = await db.get_order(order.id)
    if order is None:
        raise RuntimeError("Order not found")

    notification = GUEST_STATUS_NOTIFICATIONS.get(new_status)
    if new_status == "completed" and not await db.has_review(order.id):
        from bot.keyboards import review_rating_keyboard
        from bot.texts import REVIEW_REQUEST

        attachments = review_rating_keyboard(order.id)
        text = (
            notification.format(order_id=order.id)
            + "\n\n"
            + REVIEW_REQUEST.format(order_id=order.id)
        )
    elif notification:
        attachments = guest_keyboard_for_order(order)
        text = notification.format(order_id=order.id)
    else:
        return order

    try:
        from bot.services.guest_ui import rotate_guest_keyboards
        from bot.utils import message_mid

        result = await send_to_user(
            bot,
            order.guest_id,
            text,
            attachments=attachments,
        )
        await rotate_guest_keyboards(bot, db, order.guest_id, message_mid(result))
    except Exception:
        logger.exception("Failed to notify guest about status #%s", order.id)

    return order


async def send_review_to_staff(
    bot: Bot,
    settings: Settings,
    order: Order,
    rating: int,
    comment: str,
) -> None:
    from bot.texts import STAFF_REVIEW
    from html import escape as html_escape

    stars = "⭐" * int(rating)
    text = STAFF_REVIEW.format(
        order_id=order.id,
        stars=stars,
        rating=rating,
        guest_name=html_escape(order.guest_name),
    )
    if comment:
        text += f"\n💬 {html_escape(comment)}"
    try:
        await notify_duty(bot, settings, text)
    except Exception:
        logger.exception("Failed to send review for order #%s to staff", order.id)


async def forward_guest_to_staff(
    bot: Bot,
    db: Database,
    settings: Settings,
    order: Order,
    message,
    header: str,
) -> None:
    try:
        result = await copy_to_duty(bot, settings, message, prefix=header)
    except Exception:
        logger.exception("Failed to forward guest message for order #%s", order.id)
        return
    await remember_staff_mid(db, result, order.id, "guest_msg")
