from __future__ import annotations

import logging

from maxapi import Router
from maxapi.enums.parse_mode import Format
from maxapi.filters import BaseFilter
from maxapi.types import BotAdded, MessageCreated, UpdateUnion

from bot.config import Settings, resolve_staff_user_id, set_runtime_group_chat_id
from bot.texts import ID_INFO
from bot.utils import event_user_id, is_dialog, message_text

logger = logging.getLogger(__name__)
router = Router()


def is_menu_post(text: str, has_media: bool = False) -> bool:
    lowered = (text or "").lower()
    markers = ("меню", "#меню", "/меню", "ланч")
    if any(marker in lowered for marker in markers):
        return True
    return has_media and not lowered.strip()

ID_COMMANDS = {"/id", "id", "/айди", "айди"}


class IdCommandFilter(BaseFilter):
    """Ловит /id, /id@бот, айди — в личке и в группе."""

    async def __call__(self, event: UpdateUnion) -> bool:
        if not isinstance(event, MessageCreated) or event.message is None:
            return False
        text = message_text(event.message).lower()
        if not text:
            return False
        first = text.split()[0].split("@")[0]
        return first in ID_COMMANDS


def _chat_type_label(event: MessageCreated) -> str:
    if event.message is None:
        return "—"
    return str(event.message.recipient.chat_type)


async def _reply_ids(event: MessageCreated) -> None:
    if event.message is None:
        return
    user_id = event_user_id(event)
    chat_id = event.message.recipient.chat_id
    logger.info(" /id from user=%s chat=%s type=%s", user_id, chat_id, _chat_type_label(event))
    if chat_id and not is_dialog(event.message):
        set_runtime_group_chat_id(chat_id)
    await event.message.answer(
        ID_INFO.format(
            user_id=user_id or "—",
            chat_id=chat_id or "—",
            chat_type=_chat_type_label(event),
        ),
        format=Format.HTML,
    )


@router.message_created(IdCommandFilter())
async def cmd_id(event: MessageCreated, db=None) -> None:
    """Показывает user_id и chat_id — нужно для .env."""
    if event.message and event.message.recipient.chat_id and not is_dialog(event.message):
        if db is not None:
            await db.set_setting("group_chat_id", str(event.message.recipient.chat_id))
    await _reply_ids(event)


@router.bot_added()
async def on_bot_added(event: BotAdded, db, settings: Settings) -> None:
    """Когда бота добавили в группу — сразу пишем ID чата."""
    set_runtime_group_chat_id(event.chat_id)
    await db.set_setting("group_chat_id", str(event.chat_id))
    logger.info("Bot added to chat %s", event.chat_id)

    text = (
        f"Бот добавлен в этот чат.\n"
        f"ID группы: <b>{event.chat_id}</b>\n\n"
        "Пропишите это значение в GROUP_CHAT_ID и перезапустите бота "
        "(или просто напишите /id)."
    )
    try:
        await event.bot.send_message(
            chat_id=event.chat_id,
            text=text,
            format=Format.HTML,
        )
    except Exception:
        logger.exception("Could not send chat_id to group %s", event.chat_id)

    staff_id = resolve_staff_user_id(settings)
    if staff_id:
        try:
            await event.bot.send_message(
                user_id=staff_id,
                text=f"Бот добавлен в группу. ID: {event.chat_id}",
            )
        except Exception:
            logger.exception("Could not notify staff about group id")


def create_group_router(settings: Settings) -> Router:
    from bot.config import resolve_group_chat_id
    from bot.filters import GroupChatFilter

    group_router = Router()

    @group_router.message_created(GroupChatFilter(settings))
    async def on_group_message(event: MessageCreated, db, settings: Settings) -> None:
        """
        Новое сообщение в группе:
        1) сохраняем как меню дня для гостей;
        2) если задан получатель — пересылаем ему в личку.
        """
        message = event.message
        if message is None or message.body is None:
            return
        if message.sender and message.sender.is_bot:
            return

        text = message_text(message).lower()
        first = text.split()[0].split("@")[0] if text else ""
        if first in ID_COMMANDS or (first.startswith("/") and first != "/"):
            return

        chat_id = message.recipient.chat_id
        mid = message.body.mid
        if chat_id is None:
            return

        await db.save_group_menu_message(chat_id, mid)
        logger.info("Saved group message %s from chat %s", mid, chat_id)

        from bot.services.forwarding import copy_to_duty, duty_user_ids
        from bot.texts import GROUP_FORWARDED_HEADER, GROUP_FORWARD_FAILED

        recipients = duty_user_ids(settings)
        if not recipients:
            logger.warning(
                "GROUP_FORWARD_USER_ID / STAFF_USER_ID не заданы — "
                "сообщение сохранено, но никому не переслано"
            )
            return

        try:
            await copy_to_duty(
                event.bot,
                settings,
                message,
                prefix=GROUP_FORWARDED_HEADER,
            )
            logger.info("Forwarded group message %s to duty", mid)
        except Exception:
            logger.exception(GROUP_FORWARD_FAILED.format(user_id=recipients[0]))
            return

        has_media = bool(message.body.attachments)
        if is_menu_post(message_text(message), has_media):
            from bot.services.menu import send_permanent_menu

            sent = False
            for user_id in duty_user_ids(settings):
                if await send_permanent_menu(event.bot, settings, user_id):
                    logger.info("Permanent menu sent to %s with group post", user_id)
                    sent = True
                    break
            if not sent:
                logger.warning("Permanent menu was not sent")

    logger.info("Group router ready, group_chat_id=%s", resolve_group_chat_id(settings))
    return group_router
