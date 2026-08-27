from __future__ import annotations

from maxapi.filters import BaseFilter
from maxapi.types import MessageCallback, MessageCreated, UpdateUnion

from bot.config import Settings, is_staff_operator, resolve_group_chat_id
from bot.utils import event_user_id, is_dialog


class DialogFilter(BaseFilter):
    """Только личные сообщения с ботом."""

    async def __call__(self, event: UpdateUnion) -> bool:
        if isinstance(event, MessageCallback):
            message = event.message
            if message is None:
                return True
            return is_dialog(message)
        message = getattr(event, "message", None)
        if message is None:
            return type(event).__name__ == "BotStarted"
        return is_dialog(message)


class GroupChatFilter(BaseFilter):
    """Сообщения из настроенной группы MAX."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(self, event: UpdateUnion) -> bool:
        if not isinstance(event, MessageCreated) or event.message is None:
            return False
        group_id = resolve_group_chat_id(self.settings)
        if not group_id:
            return False
        return event.message.recipient.chat_id == group_id


class StaffFilter(BaseFilter):
    """События от текущего дежурного или администратора."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(self, event: UpdateUnion) -> bool:
        if not isinstance(event, (MessageCreated, MessageCallback)):
            return False
        user_id = event_user_id(event)
        if not is_staff_operator(user_id, self.settings):
            return False
        message = getattr(event, "message", None)
        return message is None or is_dialog(message)
