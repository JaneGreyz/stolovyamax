from __future__ import annotations

import logging

from maxapi import Bot
from maxapi.enums.parse_mode import Format
from maxapi.types import Message, MessageCallback, SendedMessage

from bot.database.db import Database

logger = logging.getLogger(__name__)


def _mid_of(source) -> str | None:
    if source is None:
        return None
    if isinstance(source, str):
        return source
    body = getattr(source, "body", None)
    if body is not None:
        return getattr(body, "mid", None)
    nested = getattr(source, "message", None)
    if nested is not None and nested is not source:
        return _mid_of(nested)
    return None


async def rotate_guest_keyboards(
    bot: Bot,
    db: Database,
    user_id: int | None,
    keep_mid: str | None,
) -> None:
    """Снимаем кнопки со старых сообщений, оставляем только keep_mid."""
    if user_id is None:
        return

    old_mids = await db.get_guest_keyboard_mids(user_id)
    for mid in old_mids:
        if not mid or mid == keep_mid:
            continue
        try:
            await bot.edit_message(message_id=mid, attachments=[], notify=False)
        except Exception:
            logger.debug("Could not remove keyboard from %s", mid, exc_info=True)

    await db.set_guest_keyboard_mids(user_id, [keep_mid] if keep_mid else [])


async def send_guest_buttons(
    bot: Bot,
    db: Database,
    user_id: int | None,
    text: str,
    attachments: list | None,
    *,
    chat_id: int | None = None,
) -> SendedMessage | None:
    kwargs = {
        "text": text,
        "attachments": attachments,
        "format": Format.HTML,
        "disable_link_preview": True,
    }
    if chat_id is not None:
        result = await bot.send_message(chat_id=chat_id, **kwargs)
    else:
        result = await bot.send_message(user_id=user_id, **kwargs)
    try:
        await rotate_guest_keyboards(bot, db, user_id, _mid_of(result))
    except Exception:
        logger.exception("Failed to rotate guest keyboards after send")
    return result


async def reply_guest_buttons(
    message: Message,
    db: Database,
    user_id: int | None,
    text: str,
    attachments: list | None,
) -> SendedMessage | None:
    from bot.utils import answer_html

    result = await answer_html(message, text, attachments)
    bot = getattr(message, "bot", None)
    if bot is None:
        logger.warning("Cannot rotate guest keyboards: message has no bot")
        return result
    try:
        await rotate_guest_keyboards(bot, db, user_id, _mid_of(result))
    except Exception:
        logger.exception("Failed to rotate guest keyboards after reply")
    return result


async def edit_guest_buttons(
    event: MessageCallback,
    db: Database,
    *,
    new_text: str,
    attachments: list | None,
    notification: str | None = None,
):
    user_id = event.callback.user.user_id
    result = await event.answer(
        notification=notification,
        new_text=new_text,
        attachments=attachments,
        format=Format.HTML,
    )
    try:
        keep_mid = _mid_of(event.message)
        if keep_mid:
            known = await db.get_guest_keyboard_mids(user_id)
            if keep_mid not in known:
                known.append(keep_mid)
                await db.set_guest_keyboard_mids(user_id, known)
        await rotate_guest_keyboards(event.bot, db, user_id, keep_mid)
    except Exception:
        logger.exception("Failed to rotate guest keyboards after edit")
    return result


async def send_callback_guest_buttons(
    event: MessageCallback,
    db: Database,
    *,
    text: str,
    attachments: list | None,
):
    user_id = event.callback.user.user_id
    try:
        clicked_mid = _mid_of(event.message)
        if clicked_mid:
            known = await db.get_guest_keyboard_mids(user_id)
            if clicked_mid not in known:
                known.append(clicked_mid)
                await db.set_guest_keyboard_mids(user_id, known)
    except Exception:
        logger.exception("Failed to remember clicked keyboard")
    result = await event.send(
        text=text,
        attachments=attachments,
        format=Format.HTML,
        disable_link_preview=True,
    )
    try:
        await rotate_guest_keyboards(event.bot, db, user_id, _mid_of(result))
    except Exception:
        logger.exception("Failed to rotate guest keyboards after send")
    return result
