"""Routes each normalised Max message to autoresend, summarise, or ignore."""

import logging

log = logging.getLogger("router.router")


class Router:
    def __init__(self, config_manager, sender, message_buffer):
        self._cfg = config_manager
        self._sender = sender
        self._buffer = message_buffer

    async def handle(self, event):
        """event: {chat_name, sender_name, text, timestamp}"""
        chat_name = event.get("chat_name")
        if not chat_name:
            return
        cfg = await self._cfg.get_chat_config(chat_name)
        if not cfg:
            return  # not configured -> silently ignore

        mode = cfg.get("mode")
        if mode == "autoresend":
            await self._sender.forward(
                chat_name, event.get("sender_name", "Unknown"), event.get("text", "")
            )
        elif mode == "summarise":
            await self._buffer.add_message(
                chat_name,
                {
                    "sender_name": event.get("sender_name", "Unknown"),
                    "text": event.get("text", ""),
                    "timestamp": event.get("timestamp"),
                },
            )
        else:
            log.warning("Unknown mode '%s' for chat '%s'", mode, chat_name)
