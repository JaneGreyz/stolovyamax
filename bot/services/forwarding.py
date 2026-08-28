"""Пересылка сообщений (группа → пользователь, гость ↔ сотрудник)."""

from __future__ import annotations

import asyncio
import logging

from maxapi import Bot
from maxapi.enums.attachment import AttachmentType
from maxapi.enums.parse_mode import Format
from maxapi.enums.upload_type import UploadType
from maxapi.types import Message, SendedMessage
from maxapi.types.attachments.upload import AttachmentPayload, AttachmentUpload

from bot.utils import message_mid, message_text

logger = logging.getLogger(__name__)

# Типы, которые можно переотправить токеном
_MEDIA_TYPES = {
    AttachmentType.IMAGE: UploadType.IMAGE,
    AttachmentType.VIDEO: UploadType.VIDEO,
    AttachmentType.AUDIO: UploadType.AUDIO,
    AttachmentType.FILE: UploadType.FILE,
    "image": UploadType.IMAGE,
    "video": UploadType.VIDEO,
    "audio": UploadType.AUDIO,
    "file": UploadType.FILE,
}


def _media_attachments(message: Message) -> list[AttachmentUpload]:
    """Собираем фото/файлы исходного сообщения для повторной отправки."""
    if message.body is None or not message.body.attachments:
        return []

    result: list[AttachmentUpload] = []
    for att in message.body.attachments:
        upload_type = _MEDIA_TYPES.get(att.type)
        if upload_type is None:
            continue
        token = getattr(att.payload, "token", None)
        if not token:
            continue
        result.append(
            AttachmentUpload(
                type=upload_type,
                payload=AttachmentPayload(token=token),
            )
        )
    return result


async def send_copy_to_user(
    bot: Bot,
    message: Message,
    user_id: int,
    prefix: str | None = None,
) -> SendedMessage | None:
    """
    Копируем текст + медиа в личку пользователю.

    Сначала пробуем нативную пересылку MAX (forward),
    если не вышло — собираем сообщение заново.
    """
    if prefix:
        await bot.send_message(
            user_id=user_id,
            text=prefix,
            format=Format.HTML,
            disable_link_preview=True,
        )
        await asyncio.sleep(0.4)

    try:
        forwarded = await message.forward(chat_id=None, user_id=user_id)
        if forwarded is not None:
            return forwarded
    except Exception:
        logger.exception("Native forward failed, falling back to copy")

    text = message_text(message) or None
    attachments = _media_attachments(message)
    if not text and not attachments:
        return None

    return await bot.send_message(
        user_id=user_id,
        text=text,
        attachments=attachments or None,
        format=Format.HTML,
    )


async def send_as_bot(
    bot: Bot,
    message: Message,
    user_id: int,
    extra_attachments: list | None = None,
) -> SendedMessage | None:
    """
    Отправляем содержимое как обычное сообщение бота:
    без forward, без имени и аватарки менеджера.
    """
    text = message_text(message) or None
    attachments = _media_attachments(message)
    if extra_attachments:
        attachments.extend(extra_attachments)
    if not text and not attachments:
        return None
    return await bot.send_message(
        user_id=user_id,
        text=text,
        attachments=attachments or None,
        format=Format.HTML if text else None,
        disable_link_preview=True,
    )


async def send_to_user(
    bot: Bot,
    user_id: int,
    text: str,
    attachments: list | None = None,
) -> SendedMessage | None:
    return await bot.send_message(
        user_id=user_id,
        text=text,
        attachments=attachments,
        format=Format.HTML,
        disable_link_preview=True,
    )


def duty_user_ids(settings) -> list[int]:
    """Дежурный, затем администраторы — если у дежурного нет диалога с ботом."""
    from bot.config import resolve_staff_user_id

    ids: list[int] = []
    staff_id = resolve_staff_user_id(settings)
    if staff_id:
        ids.append(staff_id)
    for admin_id in settings.admin_ids:
        if admin_id not in ids:
            ids.append(admin_id)
    return ids


async def notify_duty(
    bot: Bot,
    settings,
    text: str,
    attachments: list | None = None,
) -> SendedMessage | None:
    """Пишем дежурному; если диалога нет — администратору."""
    from bot.config import resolve_staff_user_id
    from bot.texts import STAFF_FALLBACK_NOTE, STAFF_NOT_CONFIGURED

    ids = duty_user_ids(settings)
    if not ids:
        raise RuntimeError(STAFF_NOT_CONFIGURED)

    staff_id = resolve_staff_user_id(settings)
    last_error: Exception | None = None
    for user_id in ids:
        body = text
        if staff_id and user_id != staff_id:
            body = STAFF_FALLBACK_NOTE + text
        try:
            result = await send_to_user(bot, user_id, body, attachments)
            if staff_id and user_id != staff_id:
                logger.warning(
                    "Staff %s unreachable, sent to admin %s",
                    staff_id,
                    user_id,
                )
            return result
        except Exception as exc:
            last_error = exc
            logger.warning("Failed to notify user %s: %s", user_id, exc)
    if last_error:
        raise last_error
    raise RuntimeError(STAFF_NOT_CONFIGURED)


async def copy_to_duty(
    bot: Bot,
    settings,
    message: Message,
    prefix: str | None = None,
) -> SendedMessage | None:
    from bot.config import resolve_staff_user_id
    from bot.texts import STAFF_FALLBACK_NOTE, STAFF_NOT_CONFIGURED

    ids = duty_user_ids(settings)
    if not ids:
        raise RuntimeError(STAFF_NOT_CONFIGURED)

    staff_id = resolve_staff_user_id(settings)
    last_error: Exception | None = None
    for user_id in ids:
        header = prefix
        if staff_id and user_id != staff_id:
            header = STAFF_FALLBACK_NOTE + (prefix or "")
        try:
            result = await send_copy_to_user(bot, message, user_id, prefix=header)
            if staff_id and user_id != staff_id:
                logger.warning(
                    "Staff %s unreachable, copied to admin %s",
                    staff_id,
                    user_id,
                )
            return result
        except Exception as exc:
            last_error = exc
            logger.warning("Failed to copy to user %s: %s", user_id, exc)
    if last_error:
        raise last_error
    raise RuntimeError(STAFF_NOT_CONFIGURED)


async def remember_staff_mid(db, result: SendedMessage | None, order_id: int, kind: str) -> None:
    mid = message_mid(result)
    if mid:
        await db.save_staff_message(mid, order_id, kind)
