"""Sends messages/summaries to the owner's Telegram via the Bot API."""

import logging

import aiohttp

log = logging.getLogger("telegram.sender")

API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramSender:
    def __init__(self, bot_token, owner_chat_id, session=None):
        self._token = bot_token
        self._owner_chat_id = owner_chat_id
        self._session = session
        self._own_session = session is None

    async def _ensure_session(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _send_raw(self, text):
        session = await self._ensure_session()
        url = API_BASE.format(token=self._token, method="sendMessage")
        payload = {
            "chat_id": self._owner_chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        try:
            async with session.post(url, json=payload, timeout=30) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.error("Telegram sendMessage failed %s: %s", resp.status, body)
                    return False
                return True
        except (aiohttp.ClientError, OSError) as e:
            log.error("Telegram sendMessage error: %s", e)
            return False

    async def forward(self, chat_name, sender, text):
        return await self._send_raw(f"[Max – {chat_name}] {sender}: {text}")

    async def send_summary(self, chat_name, summary):
        return await self._send_raw(f"📋 Summary – {chat_name}\n\n{summary}")

    async def send_alert(self, text):
        return await self._send_raw(f"⚠️ {text}")
