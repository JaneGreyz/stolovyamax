from typing import Any, Awaitable, Callable
import logging

from maxapi.filters.middleware import BaseMiddleware
from maxapi.types import MessageCallback, MessageCreated, UpdateUnion

from bot.config import Settings
from bot.database.db import Database

logger = logging.getLogger(__name__)


class DependencyMiddleware(BaseMiddleware):
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[UpdateUnion, dict[str, Any]], Awaitable[Any]],
        event_object: UpdateUnion,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        data["settings"] = self.settings
        return await handler(event_object, data)


class LogUpdatesMiddleware(BaseMiddleware):
    """Пишем в лог входящие события — чтобы понять, доходят ли сообщения."""

    async def __call__(
        self,
        handler: Callable[[UpdateUnion, dict[str, Any]], Awaitable[Any]],
        event_object: UpdateUnion,
        data: dict[str, Any],
    ) -> Any:
        name = type(event_object).__name__
        extra = ""
        if isinstance(event_object, MessageCreated) and event_object.message:
            rec = event_object.message.recipient
            text = ""
            if event_object.message.body:
                text = event_object.message.body.text or ""
            extra = f" chat_id={rec.chat_id} type={rec.chat_type} text={text!r:.80}"
        elif isinstance(event_object, MessageCallback):
            extra = f" payload={event_object.callback.payload!r}"
        logger.info("Update %s%s", name, extra)
        return await handler(event_object, data)

