from __future__ import annotations

import logging
from datetime import datetime

from maxapi import F, Router
from maxapi.context import MemoryContext
from maxapi.types import (
    BotStarted,
    CommandStart,
    MessageCallback,
    MessageCreated,
)

from bot.config import Settings
from bot.database.db import Database
from bot.database.models import Order
from bot.filters import DialogFilter
from bot.keyboards import (
    addresses_keyboard,
    cancel_keyboard,
    guest_busy_keyboard,
    guest_keyboard_for_order,
    guest_main_keyboard,
    guest_order_keyboard,
    keyboard_for_guest,
    review_rating_keyboard,
    review_skip_keyboard,
)
from bot.services.guest_ui import (
    edit_guest_buttons,
    reply_guest_buttons,
    send_callback_guest_buttons,
    send_guest_buttons,
)
from bot.services.menu import send_menus_to_guest
from bot.services.orders import (
    cancel_guest_active_order,
    finalize_order,
    forward_guest_to_staff,
    send_review_to_staff,
)
from bot.services.working_hours import format_work_hours, get_tz, is_working_hours
from bot.states import OrderStates, ReviewStates
from bot.texts import (
    CHOOSE_ADDRESS,
    CONTACT_MANAGER,
    CONTACT_MANAGER_FAILED,
    CONTACT_MANAGER_NO_ORDER,
    DELIVERY_UNAVAILABLE,
    ENTER_ADDRESS_CLARIFICATION,
    ENTER_ORDER_TEXT,
    ENTER_PHONE,
    INVALID_PHONE,
    ORDER_ACCEPTED,
    ORDER_CANCELLED_ACTIVE,
    ORDER_CANCELLED_BY_GUEST,
    ORDER_CANNOT_CANCEL_IN_DELIVERY,
    ORDER_ERROR,
    ORDER_IN_PROGRESS,
    ORDER_IN_PROGRESS_DELIVERY,
    ORDER_NO_ACTIVE,
    OUTSIDE_WORKING_HOURS,
    OUTSIDE_WORKING_HOURS_WEEKEND,
    QA_MESSAGE,
    REVIEW_ALREADY,
    REVIEW_REQUEST,
    REVIEW_SAVED,
    REVIEW_THANKS,
    STAFF_CONTACT_REQUEST,
    STAFF_CONTACT_REQUEST_NO_ORDER,
    STAFF_GUEST_MESSAGE_HEADER,
    USE_BUTTONS,
    WELCOME,
)
from bot.utils import (
    event_user_id,
    guest_name,
    is_valid_phone,
    message_text,
    normalize_phone,
)

logger = logging.getLogger(__name__)
router = Router()


def _stars(rating: int) -> str:
    return "⭐" * max(1, min(5, int(rating)))


async def _checkout_prompt(context: MemoryContext, db: Database, user_id: int | None):
    """Текст и кнопки текущего шага оформления; восстанавливает FSM по черновику."""
    state = await context.get_state()
    data = await context.get_data()
    draft = await db.get_pending_order_for_guest(user_id) if user_id else None

    if state == ReviewStates.waiting_comment:
        return None, None

    if state is None and draft:
        await context.update_data(order_id=draft.id)
        await context.set_state(OrderStates.order_text)
        state = OrderStates.order_text

    if state == OrderStates.choosing_address:
        addresses = await db.get_active_addresses()
        return CHOOSE_ADDRESS, addresses_keyboard(addresses)
    if state == OrderStates.address_clarification:
        address = data.get("address") or ""
        prefix = f"📍 {address}\n\n" if address else ""
        return f"{prefix}{ENTER_ADDRESS_CLARIFICATION}", cancel_keyboard()
    if state == OrderStates.phone:
        return ENTER_PHONE, guest_order_keyboard()
    if state == OrderStates.order_text or draft:
        return ENTER_ORDER_TEXT, guest_order_keyboard()
    return None, None


def _welcome_extra(settings: Settings) -> str:
    if is_working_hours(settings):
        return ""
    schedule = format_work_hours(settings)
    tz = get_tz(settings)
    if settings.work_weekdays_only and datetime.now(tz).weekday() >= 5:
        return f"\n\n⏰ {OUTSIDE_WORKING_HOURS_WEEKEND.format(schedule=schedule)}"
    return f"\n\n⏰ {OUTSIDE_WORKING_HOURS.format(schedule=schedule)}"


async def show_welcome(
    event,
    context: MemoryContext,
    settings: Settings,
    db: Database,
) -> None:
    user_id = (
        event.user.user_id
        if isinstance(event, BotStarted)
        else event_user_id(event)
    )
    active = await db.get_active_order_for_guest(user_id) if user_id else None

    if active and active.submitted:
        if active.status == "in_delivery":
            text = ORDER_IN_PROGRESS_DELIVERY.format(order_id=active.id)
        else:
            text = ORDER_IN_PROGRESS.format(order_id=active.id)
        keyboard = guest_keyboard_for_order(active)
        if isinstance(event, BotStarted):
            await send_guest_buttons(
                event.bot,
                db,
                user_id,
                text,
                keyboard,
                chat_id=event.chat_id,
            )
            return
        await reply_guest_buttons(event.message, db, user_id, text, keyboard)
        return

    prompt, keyboard = await _checkout_prompt(context, db, user_id)
    if prompt and keyboard:
        if isinstance(event, BotStarted):
            await send_guest_buttons(
                event.bot,
                db,
                user_id,
                prompt,
                keyboard,
                chat_id=event.chat_id,
            )
            return
        await reply_guest_buttons(event.message, db, user_id, prompt, keyboard)
        return

    pending_review = (
        await db.get_last_completed_order_without_review(user_id)
        if user_id
        else None
    )
    if pending_review:
        state = await context.get_state()
        data = await context.get_data()
        rating = data.get("review_rating")
        if state == ReviewStates.waiting_comment and rating:
            text = REVIEW_THANKS.format(stars=_stars(int(rating)))
            keyboard = review_skip_keyboard()
        else:
            text = REVIEW_REQUEST.format(order_id=pending_review.id)
            keyboard = review_rating_keyboard(pending_review.id)
        if isinstance(event, BotStarted):
            await send_guest_buttons(
                event.bot,
                db,
                user_id,
                text,
                keyboard,
                chat_id=event.chat_id,
            )
            return
        await reply_guest_buttons(event.message, db, user_id, text, keyboard)
        return

    await context.clear()
    text = WELCOME.format(min_amount=settings.min_order_amount) + _welcome_extra(settings)
    if isinstance(event, BotStarted):
        await send_guest_buttons(
            event.bot,
            db,
            user_id,
            text,
            guest_main_keyboard(),
            chat_id=event.chat_id,
        )
        return
    await reply_guest_buttons(event.message, db, user_id, text, guest_main_keyboard())


@router.bot_started()
async def on_bot_started(
    event: BotStarted,
    context: MemoryContext,
    settings: Settings,
    db: Database,
) -> None:
    await show_welcome(event, context, settings, db)


@router.message_created(DialogFilter(), CommandStart())
async def cmd_start(
    event: MessageCreated,
    context: MemoryContext,
    settings: Settings,
    db: Database,
) -> None:
    await show_welcome(event, context, settings, db)


@router.message_callback(DialogFilter(), F.callback.payload == "main:qa")
async def show_qa(
    event: MessageCallback,
    context: MemoryContext,
    db: Database,
) -> None:
    await event.ack(notification="Вопрос/ответ")
    keyboard = await keyboard_for_guest(db, event_user_id(event), context)
    await send_callback_guest_buttons(
        event,
        db,
        text=QA_MESSAGE,
        attachments=keyboard,
    )


@router.message_callback(DialogFilter(), F.callback.payload == "main:order")
async def start_order(
    event: MessageCallback,
    context: MemoryContext,
    db: Database,
) -> None:
    user_id = event_user_id(event)
    if user_id is None:
        return

    prompt, keyboard = await _checkout_prompt(context, db, user_id)
    if prompt and keyboard:
        await edit_guest_buttons(
            event,
            db,
            new_text=prompt,
            attachments=keyboard,
        )
        return

    active = await db.get_active_order_for_guest(user_id)
    if active:
        if active.submitted:
            text = (
                ORDER_IN_PROGRESS_DELIVERY.format(order_id=active.id)
                if active.status == "in_delivery"
                else ORDER_IN_PROGRESS.format(order_id=active.id)
            )
            await edit_guest_buttons(
                event,
                db,
                new_text=text,
                attachments=guest_keyboard_for_order(active),
            )
            return
        await context.update_data(order_id=active.id)
        await context.set_state(OrderStates.order_text)
        await edit_guest_buttons(
            event,
            db,
            new_text=ENTER_ORDER_TEXT,
            attachments=guest_order_keyboard(),
        )
        return

    addresses = await db.get_active_addresses()
    if not addresses:
        await edit_guest_buttons(
            event,
            db,
            new_text=DELIVERY_UNAVAILABLE,
            attachments=guest_main_keyboard(),
        )
        return

    await context.set_state(OrderStates.choosing_address)
    await edit_guest_buttons(
        event,
        db,
        new_text=CHOOSE_ADDRESS,
        attachments=addresses_keyboard(addresses),
    )


@router.message_callback(DialogFilter(), F.callback.payload.startswith("addr:"))
async def choose_address(
    event: MessageCallback,
    context: MemoryContext,
    db: Database,
) -> None:
    payload = event.callback.payload or ""
    try:
        address_id = int(payload.split(":")[1])
    except (IndexError, ValueError):
        await event.ack(notification="Адрес недоступен")
        return

    address = await db.get_address_by_id(address_id)
    if not address or not address.is_active:
        await event.ack(notification="Адрес недоступен")
        return

    await context.update_data(
        address_id=address.id,
        address=address.full_name,
        address_short=address.short_name,
    )
    await context.set_state(OrderStates.address_clarification)
    await edit_guest_buttons(
        event,
        db,
        new_text=f"📍 {address.full_name}\n\n{ENTER_ADDRESS_CLARIFICATION}",
        attachments=cancel_keyboard(),
    )


@router.message_created(DialogFilter(), OrderStates.choosing_address)
async def wait_address_choice(event: MessageCreated, db: Database) -> None:
    await reply_guest_buttons(
        event.message,
        db,
        event_user_id(event),
        USE_BUTTONS,
        cancel_keyboard(),
    )


@router.message_created(DialogFilter(), OrderStates.address_clarification)
async def process_clarification(
    event: MessageCreated,
    context: MemoryContext,
    db: Database,
) -> None:
    text = message_text(event.message)
    user_id = event_user_id(event)
    if not text:
        await reply_guest_buttons(
            event.message,
            db,
            user_id,
            ENTER_ADDRESS_CLARIFICATION,
            cancel_keyboard(),
        )
        return

    await context.update_data(address_clarification=text)
    await context.set_state(OrderStates.phone)
    await reply_guest_buttons(
        event.message,
        db,
        user_id,
        ENTER_PHONE,
        guest_order_keyboard(),
    )


@router.message_created(DialogFilter(), OrderStates.phone)
async def process_phone(
    event: MessageCreated,
    context: MemoryContext,
    db: Database,
    settings: Settings,
) -> None:
    user = event.message.sender if event.message else None
    if user is None:
        return

    text = message_text(event.message)
    if not is_valid_phone(text):
        await reply_guest_buttons(
            event.message,
            db,
            user.user_id,
            INVALID_PHONE,
            guest_order_keyboard(),
        )
        return

    phone = normalize_phone(text)
    data = await context.get_data()
    order = await db.create_order(
        guest_id=user.user_id,
        guest_username=user.username,
        guest_name=guest_name(user),
        address=data["address"],
        address_short=data["address_short"],
        address_clarification=data.get("address_clarification", ""),
        phone=phone,
    )
    await context.update_data(order_id=order.id)
    await context.set_state(OrderStates.order_text)

    await send_menus_to_guest(event.bot, db, settings, user.user_id)
    await reply_guest_buttons(
        event.message,
        db,
        user.user_id,
        ENTER_ORDER_TEXT,
        guest_order_keyboard(),
    )


async def _resolve_pending_order(
    event: MessageCreated,
    context: MemoryContext,
    db: Database,
) -> Order | None:
    user_id = event_user_id(event)
    if user_id is None:
        return None

    data = await context.get_data()
    order_id = data.get("order_id")
    if order_id:
        order = await db.get_order(int(order_id))
        if order and not order.submitted:
            return order

    order = await db.get_pending_order_for_guest(user_id)
    if order:
        await context.update_data(order_id=order.id)
        await context.set_state(OrderStates.order_text)
    return order


@router.message_created(DialogFilter(), OrderStates.order_text)
async def process_order_message(
    event: MessageCreated,
    context: MemoryContext,
    db: Database,
    settings: Settings,
) -> None:
    user = event.message.sender if event.message else None
    if user is None:
        return

    order = await _resolve_pending_order(event, context, db)
    if not order:
        await context.clear()
        await reply_guest_buttons(
            event.message,
            db,
            user.user_id,
            ORDER_ERROR,
            guest_main_keyboard(),
        )
        return

    order_text = message_text(event.message)
    if not order_text:
        await reply_guest_buttons(
            event.message,
            db,
            user.user_id,
            ENTER_ORDER_TEXT,
            guest_order_keyboard(),
        )
        return

    try:
        order = await finalize_order(event.bot, db, settings, order, order_text)
    except Exception:
        logger.exception("Failed to finalize order %s", order.id)
        await reply_guest_buttons(
            event.message,
            db,
            user.user_id,
            "Не удалось передать заказ менеджеру. Попробуйте ещё раз.",
            guest_order_keyboard(),
        )
        return

    # Если гость приложил фото к составу заказа — дублируем сотруднику
    if event.message and event.message.body and event.message.body.attachments:
        await forward_guest_to_staff(
            event.bot,
            db,
            settings,
            order,
            event.message,
            STAFF_GUEST_MESSAGE_HEADER.format(order_id=order.id),
        )

    await context.clear()
    await reply_guest_buttons(
        event.message,
        db,
        user.user_id,
        ORDER_ACCEPTED.format(order_id=order.id),
        guest_busy_keyboard(can_cancel=True),
    )


@router.message_callback(DialogFilter(), F.callback.payload == "order:cancel")
async def cancel_draft_order(
    event: MessageCallback,
    context: MemoryContext,
    db: Database,
) -> None:
    data = await context.get_data()
    order_id = data.get("order_id")
    if order_id:
        await db.update_order_status(int(order_id), "cancelled")
    await context.clear()
    await edit_guest_buttons(
        event,
        db,
        new_text=ORDER_CANCELLED_BY_GUEST,
        attachments=guest_main_keyboard(),
    )


@router.message_callback(DialogFilter(), F.callback.payload == "guest:cancel_active")
@router.message_callback(DialogFilter(), F.callback.payload == "main:cancel")
async def cancel_active_order(
    event: MessageCallback,
    context: MemoryContext,
    db: Database,
    settings: Settings,
) -> None:
    user_id = event_user_id(event)
    if user_id is None:
        return

    active = await db.get_active_order_for_guest(user_id)
    if active and active.status == "in_delivery":
        await edit_guest_buttons(
            event,
            db,
            new_text=ORDER_CANNOT_CANCEL_IN_DELIVERY,
            attachments=guest_keyboard_for_order(active),
        )
        return

    order = await cancel_guest_active_order(event.bot, db, settings, user_id, context)
    if not order:
        await edit_guest_buttons(
            event,
            db,
            new_text=ORDER_NO_ACTIVE,
            attachments=guest_main_keyboard(),
        )
        return

    await edit_guest_buttons(
        event,
        db,
        new_text=ORDER_CANCELLED_ACTIVE.format(order_id=order.id),
        attachments=guest_main_keyboard(),
    )


@router.message_callback(DialogFilter(), F.callback.payload.startswith("review:"))
async def process_review_callback(
    event: MessageCallback,
    context: MemoryContext,
    db: Database,
    settings: Settings,
) -> None:
    payload = event.callback.payload or ""
    user = event.callback.user

    if payload == "review:skip":
        data = await context.get_data()
        order_id = data.get("review_order_id")
        rating = data.get("review_rating")
        if order_id and rating and not await db.has_review(int(order_id)):
            await db.save_review(int(order_id), user.user_id, int(rating))
            order = await db.get_order(int(order_id))
            if order:
                await send_review_to_staff(
                    event.bot, settings, order, int(rating), ""
                )
        await context.clear()
        await edit_guest_buttons(
            event,
            db,
            new_text=REVIEW_SAVED,
            attachments=guest_main_keyboard(),
        )
        return

    parts = payload.split(":")
    if len(parts) != 3:
        await event.ack(notification="Ошибка")
        return
    try:
        order_id = int(parts[1])
        rating = int(parts[2])
    except ValueError:
        await event.ack(notification="Ошибка")
        return
    if rating not in (1, 2, 3, 4, 5):
        await event.ack(notification="Ошибка")
        return

    order = await db.get_order(order_id)
    if not order or order.guest_id != user.user_id:
        await event.ack(notification="Заказ не найден")
        return
    if await db.has_review(order_id):
        await context.clear()
        await edit_guest_buttons(
            event,
            db,
            new_text=REVIEW_ALREADY,
            attachments=guest_main_keyboard(),
        )
        return

    await context.set_state(ReviewStates.waiting_comment)
    await context.update_data(review_order_id=order_id, review_rating=rating)
    await edit_guest_buttons(
        event,
        db,
        new_text=REVIEW_THANKS.format(stars=_stars(rating)),
        attachments=review_skip_keyboard(),
    )


@router.message_created(DialogFilter(), ReviewStates.waiting_comment)
async def process_review_comment(
    event: MessageCreated,
    context: MemoryContext,
    db: Database,
    settings: Settings,
) -> None:
    user_id = event_user_id(event)
    text = message_text(event.message)
    if text.startswith("/"):
        return

    data = await context.get_data()
    order_id = data.get("review_order_id")
    rating = data.get("review_rating")
    if not order_id or not rating or user_id is None:
        await context.clear()
        await reply_guest_buttons(
            event.message,
            db,
            user_id,
            WELCOME.format(min_amount=settings.min_order_amount),
            guest_main_keyboard(),
        )
        return

    comment = text.strip()
    if not comment:
        await reply_guest_buttons(
            event.message,
            db,
            user_id,
            REVIEW_THANKS.format(stars=_stars(int(rating))),
            review_skip_keyboard(),
        )
        return

    if not await db.has_review(int(order_id)):
        await db.save_review(int(order_id), user_id, int(rating), comment)
        order = await db.get_order(int(order_id))
        if order:
            await send_review_to_staff(
                event.bot, settings, order, int(rating), comment
            )

    await context.clear()
    await reply_guest_buttons(
        event.message,
        db,
        user_id,
        REVIEW_SAVED,
        guest_main_keyboard(),
    )


@router.message_callback(DialogFilter(), F.callback.payload == "main:contact")
async def contact_manager(
    event: MessageCallback,
    context: MemoryContext,
    db: Database,
    settings: Settings,
) -> None:
    user = event.callback.user
    order = await db.get_active_order_for_guest(user.user_id)
    keyboard = await keyboard_for_guest(db, user.user_id, context)

    if order and order.submitted:
        staff_text = STAFF_CONTACT_REQUEST.format(
            order_id=order.id,
            guest_name=guest_name(user),
            guest_id=user.user_id,
        )
        guest_text = CONTACT_MANAGER
    else:
        staff_text = STAFF_CONTACT_REQUEST_NO_ORDER.format(
            guest_name=guest_name(user),
            guest_id=user.user_id,
        )
        guest_text = CONTACT_MANAGER_NO_ORDER

    from bot.services.forwarding import notify_duty

    try:
        await notify_duty(event.bot, settings, staff_text)
    except Exception:
        logger.exception("Failed to notify duty about contact request from %s", user.user_id)
        await event.ack(notification="Не удалось отправить")
        await send_callback_guest_buttons(
            event,
            db,
            text=CONTACT_MANAGER_FAILED,
            attachments=keyboard,
        )
        return

    await event.ack(notification="Запрос отправлен")
    await send_callback_guest_buttons(
        event,
        db,
        text=guest_text,
        attachments=keyboard,
    )


@router.message_created(DialogFilter())
async def forward_guest_followup(
    event: MessageCreated,
    context: MemoryContext,
    db: Database,
    settings: Settings,
) -> None:
    """После оформления заказа сообщения гостя уходят сотруднику с номером заказа."""
    if await context.get_state() is not None:
        return

    user_id = event_user_id(event)
    if user_id is None or event.message is None:
        return

    # Команды не пересылаем
    text = message_text(event.message)
    if text.startswith("/"):
        return

    order = await db.get_active_order_for_guest(user_id)
    if not order or not order.submitted:
        return

    await forward_guest_to_staff(
        event.bot,
        db,
        settings,
        order,
        event.message,
        STAFF_GUEST_MESSAGE_HEADER.format(order_id=order.id),
    )
