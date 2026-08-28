from __future__ import annotations

from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from bot.database.models import ACTIVE_STATUSES, Address, Order
from bot.texts import (
    BUTTON_CANCEL_ORDER,
    BUTTON_CONTACT_MANAGER,
    BUTTON_MAKE_ORDER,
    BUTTON_QA,
    BUTTON_REPLY_GUEST,
    BUTTON_STATUS_ACCEPTED,
    BUTTON_STATUS_CANCELLED,
    BUTTON_STATUS_COMPLETED,
    BUTTON_STATUS_IN_DELIVERY,
    REVIEW_SKIP,
)


def _markup(builder: InlineKeyboardBuilder):
    return [builder.as_markup()]


def guest_main_keyboard(*, can_order: bool = True):
    builder = InlineKeyboardBuilder()
    if can_order:
        builder.row(CallbackButton(text=BUTTON_MAKE_ORDER, payload="main:order"))
    builder.row(CallbackButton(text=BUTTON_QA, payload="main:qa"))
    builder.row(CallbackButton(text=BUTTON_CONTACT_MANAGER, payload="main:contact"))
    return _markup(builder)


def guest_busy_keyboard(*, can_cancel: bool = False):
    """Активный заказ: без «Сделать заказ». «Отменить заказ» — только до доставки."""
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text=BUTTON_QA, payload="main:qa"))
    builder.row(CallbackButton(text=BUTTON_CONTACT_MANAGER, payload="main:contact"))
    if can_cancel:
        builder.row(CallbackButton(text=BUTTON_CANCEL_ORDER, payload="main:cancel"))
    return _markup(builder)


def guest_keyboard_for_order(order: Order | None):
    if order is None or order.status in ("completed", "cancelled"):
        return guest_main_keyboard()
    if not order.submitted:
        return guest_order_keyboard()
    return guest_busy_keyboard(can_cancel=order.status != "in_delivery")


async def keyboard_for_guest(db, user_id: int | None, context=None):
    from bot.states import OrderStates, ReviewStates

    if user_id is None:
        return guest_main_keyboard()
    try:
        if context is not None:
            state = await context.get_state()
            if state == ReviewStates.waiting_comment:
                return review_skip_keyboard()
            # State в maxapi нельзя класть в set — только сравнение через tuple/`==`
            if state in (
                OrderStates.choosing_address,
                OrderStates.address_clarification,
                OrderStates.phone,
                OrderStates.order_text,
            ):
                return guest_order_keyboard()
        order = await db.get_active_order_for_guest(user_id)
        return guest_keyboard_for_order(order)
    except Exception:
        return guest_main_keyboard()


def guest_order_keyboard():
    """Кнопки во время оформления заказа — с отменой."""
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text=BUTTON_QA, payload="main:qa"))
    builder.row(CallbackButton(text=BUTTON_CONTACT_MANAGER, payload="main:contact"))
    builder.row(CallbackButton(text=BUTTON_CANCEL_ORDER, payload="order:cancel"))
    return _markup(builder)


def cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text=BUTTON_CANCEL_ORDER, payload="order:cancel"))
    return _markup(builder)


def review_rating_keyboard(order_id: int):
    """Оценка звёздами 1–5, как в Telegram-боте столовой."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="⭐", payload=f"review:{order_id}:1"),
        CallbackButton(text="⭐⭐", payload=f"review:{order_id}:2"),
        CallbackButton(text="⭐⭐⭐", payload=f"review:{order_id}:3"),
    )
    builder.row(
        CallbackButton(text="⭐⭐⭐⭐", payload=f"review:{order_id}:4"),
        CallbackButton(text="⭐⭐⭐⭐⭐", payload=f"review:{order_id}:5"),
    )
    return _markup(builder)


def review_skip_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text=REVIEW_SKIP, payload="review:skip"))
    return _markup(builder)


def addresses_keyboard(addresses: list[Address]):
    builder = InlineKeyboardBuilder()
    for addr in addresses:
        builder.row(CallbackButton(text=addr.full_name, payload=f"addr:{addr.id}"))
    builder.row(CallbackButton(text=BUTTON_CANCEL_ORDER, payload="order:cancel"))
    return _markup(builder)


def cancel_active_order_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text=BUTTON_CANCEL_ORDER, payload="guest:cancel_active"))
    return _markup(builder)


def staff_order_keyboard(order: Order):
    """Кнопки статусов и ответа гостю на карточке заказа."""
    if order.status not in ACTIVE_STATUSES:
        return None

    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text=BUTTON_STATUS_ACCEPTED,
            payload=f"staff:accepted:{order.id}",
        ),
        CallbackButton(
            text=BUTTON_STATUS_IN_DELIVERY,
            payload=f"staff:in_delivery:{order.id}",
        ),
    )
    if order.status == "in_delivery":
        builder.row(
            CallbackButton(
                text=BUTTON_STATUS_COMPLETED,
                payload=f"staff:completed:{order.id}",
            )
        )
    else:
        builder.row(
            CallbackButton(
                text=BUTTON_STATUS_CANCELLED,
                payload=f"staff:cancelled:{order.id}",
            )
        )
    builder.row(
        CallbackButton(
            text=BUTTON_REPLY_GUEST,
            payload=f"staff:reply:{order.id}",
        )
    )
    return _markup(builder)
