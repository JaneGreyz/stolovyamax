from __future__ import annotations

import re

from maxapi.enums.chat_type import ChatType
from maxapi.enums.parse_mode import Format
from maxapi.types import Message, MessageCallback, MessageCreated, SendedMessage
from maxapi.types.users import User

PHONE_PATTERN = re.compile(
    r"^\+?[78]?[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}$"
)


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if digits.startswith("7") and len(digits) == 11:
        return f"+{digits[0]} ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return phone.strip()


def is_valid_phone(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    return len(digits) >= 10


def guest_name(user: User | None) -> str:
    if user is None:
        return "Гость"
    return user.full_name or user.first_name or "Гость"


def message_text(message: Message | None) -> str:
    if message is None or message.body is None:
        return ""
    return (message.body.text or "").strip()


def message_mid(result: SendedMessage | Message | None) -> str | None:
    if result is None:
        return None
    body = getattr(result, "body", None)
    if body is not None:
        return getattr(body, "mid", None)
    nested = getattr(result, "message", None)
    if nested is None:
        return None
    nested_body = getattr(nested, "body", None)
    if nested_body is None:
        return None
    return getattr(nested_body, "mid", None)


def is_dialog(message: Message | None) -> bool:
    if message is None:
        return False
    chat_type = message.recipient.chat_type
    return chat_type == ChatType.DIALOG or str(chat_type) == "dialog"


def event_user_id(event: MessageCreated | MessageCallback) -> int | None:
    if isinstance(event, MessageCallback):
        return event.callback.user.user_id
    if event.message and event.message.sender:
        return event.message.sender.user_id
    return None


def event_chat_id(event: MessageCreated | MessageCallback) -> int | None:
    message = event.message
    if message is None:
        return None
    return message.recipient.chat_id


async def answer_html(
    message: Message,
    text: str,
    attachments: list | None = None,
):
    """Ответ в тот же чат с HTML-разметкой."""
    return await message.answer(
        text=text,
        attachments=attachments,
        format=Format.HTML,
        disable_link_preview=True,
    )
