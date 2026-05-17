"""Max messenger userbot listener.

Connects to Max over its (unofficial) API, authenticates as the phone owner,
and emits one normalised event per incoming message:

    {chat_name, sender_name, text, timestamp}

The wire protocol is provided by a third-party library (`maxapi`). Library
APIs for Max are unofficial and move quickly, so all library-specific code is
isolated to `_connect_and_listen`. If the installed `maxapi` version exposes
a different surface, that single method is the only place to adjust.

Auto-reconnects with exponential backoff on disconnect.
"""

import asyncio
import logging
import time

log = logging.getLogger("max_listener.client")

_MAX_BACKOFF_SECONDS = 300


class MaxListener:
    def __init__(self, phone, password, session_file, on_message):
        """on_message: async callable receiving the normalised event dict."""
        self._phone = phone
        self._password = password
        self._session_file = session_file
        self._on_message = on_message

    async def run(self):
        backoff = 2
        while True:
            try:
                await self._connect_and_listen()
                backoff = 2  # clean exit -> reset backoff
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Max connection dropped; reconnecting in %ss", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)

    async def _emit(self, chat_name, sender_name, text, timestamp=None):
        await self._on_message(
            {
                "chat_name": chat_name,
                "sender_name": sender_name,
                "text": text,
                "timestamp": timestamp or time.time(),
            }
        )

    async def _connect_and_listen(self):
        """Library-specific integration point — adjust here for maxapi version."""
        from maxapi import Bot, Dispatcher
        from maxapi.types import MessageCreated

        bot = Bot(phone=self._phone, password=self._password,
                  session_file=self._session_file)
        dp = Dispatcher()

        @dp.message_created()
        async def _handler(event: MessageCreated):  # noqa: ANN001
            msg = event.message
            chat = getattr(msg, "chat", None)
            sender = getattr(msg, "sender", None)
            chat_name = (
                getattr(chat, "title", None)
                or getattr(chat, "name", None)
                or str(getattr(msg, "chat_id", "unknown"))
            )
            sender_name = (
                getattr(sender, "name", None)
                or getattr(sender, "first_name", None)
                or "Unknown"
            )
            text = getattr(msg, "text", "") or getattr(msg, "body", "") or ""
            if text:
                await self._emit(
                    chat_name, sender_name, text, getattr(msg, "timestamp", None)
                )

        log.info("Connecting to Max as %s", self._phone)
        await dp.start_polling(bot)
