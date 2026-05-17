"""Collects messages per chat and fires the two summary triggers.

Count trigger: >= message_count buffered -> summarise "discussion ongoing",
clear messages, keep watching (silence timer keeps running).

Timeout trigger: no new message for timeout_minutes -> summarise
"conversation ended", clear the buffer entry.
"""

import asyncio
import logging
import time

from config.config_manager import DEFAULT_MESSAGE_COUNT, DEFAULT_TIMEOUT_MINUTES

log = logging.getLogger("buffer.message_buffer")

STATUS_ONGOING = "discussion ongoing"
STATUS_ENDED = "conversation ended"
CHECK_INTERVAL_SECONDS = 60


class MessageBuffer:
    def __init__(self, config_manager, summariser, sender):
        self._cfg = config_manager
        self._summariser = summariser
        self._sender = sender
        self._buffers = {}  # chat_name -> {messages: [], last_activity: float}
        self._lock = asyncio.Lock()

    async def add_message(self, chat_name, message):
        async with self._lock:
            entry = self._buffers.setdefault(
                chat_name, {"messages": [], "last_activity": 0.0}
            )
            entry["messages"].append(message)
            entry["last_activity"] = time.monotonic()
            cfg = await self._cfg.get_chat_config(chat_name) or {}
            threshold = cfg.get("message_count", DEFAULT_MESSAGE_COUNT)
            should_flush = len(entry["messages"]) >= threshold
            batch = list(entry["messages"]) if should_flush else None
            if should_flush:
                entry["messages"].clear()  # keep entry so silence timer continues

        if should_flush:
            await self._summarise_and_send(chat_name, batch, STATUS_ONGOING)

    async def _summarise_and_send(self, chat_name, messages, status):
        if not messages:
            return
        try:
            summary = await self._summariser.summarise(messages, status)
        except Exception as e:  # noqa: BLE001
            log.exception("summarisation failed for %s", chat_name)
            await self._sender.send_alert(
                f"Claude summarisation failed for '{chat_name}': {e}"
            )
            return
        await self._sender.send_summary(chat_name, summary)

    async def run_timeout_checker(self):
        """Background loop: flush chats that have gone silent."""
        while True:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            now = time.monotonic()
            expired = []
            async with self._lock:
                for chat_name, entry in list(self._buffers.items()):
                    cfg = await self._cfg.get_chat_config(chat_name) or {}
                    timeout_s = (
                        cfg.get("timeout_minutes", DEFAULT_TIMEOUT_MINUTES) * 60
                    )
                    if now - entry["last_activity"] >= timeout_s:
                        if entry["messages"]:
                            expired.append((chat_name, list(entry["messages"])))
                        del self._buffers[chat_name]

            for chat_name, messages in expired:
                await self._summarise_and_send(chat_name, messages, STATUS_ENDED)
