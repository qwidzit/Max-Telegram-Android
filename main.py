"""Entry point. Wires all components and runs the three concurrent tasks."""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from buffer.message_buffer import MessageBuffer
from config.config_manager import ConfigManager
from max_listener.client import MaxListener
from router.router import Router
from summariser.claude_client import ClaudeSummariser
from telegram.command_handler import CommandHandler
from telegram.sender import TelegramSender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


def _require(name):
    val = os.getenv(name)
    if not val:
        log.error("Missing required env var: %s", name)
        sys.exit(1)
    return val


async def main():
    load_dotenv()

    anthropic_key = _require("ANTHROPIC_API_KEY")
    bot_token = _require("TELEGRAM_BOT_TOKEN")
    owner_chat_id = _require("TELEGRAM_OWNER_CHAT_ID")
    max_phone = _require("MAX_PHONE")
    max_password = os.getenv("MAX_PASSWORD", "")
    session_file = os.getenv("MAX_SESSION_FILE", "max_session")

    config_manager = ConfigManager("config.json")
    sender = TelegramSender(bot_token, owner_chat_id)
    summariser = ClaudeSummariser(anthropic_key)
    message_buffer = MessageBuffer(config_manager, summariser, sender)
    router = Router(config_manager, sender, message_buffer)
    command_handler = CommandHandler(bot_token, owner_chat_id, config_manager)
    max_listener = MaxListener(
        max_phone, max_password, session_file, router.handle
    )

    log.info("Starting Max → Telegram bridge")
    tasks = [
        asyncio.create_task(max_listener.run(), name="max_listener"),
        asyncio.create_task(command_handler.run(), name="command_handler"),
        asyncio.create_task(
            message_buffer.run_timeout_checker(), name="timeout_checker"
        ),
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        log.info("Shutting down")
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await sender.close()
        await command_handler.close()
        await summariser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted, exiting")
