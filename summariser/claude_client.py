"""Calls the Anthropic Messages API to summarise a batch of buffered messages.

Uses aiohttp directly rather than the `anthropic` SDK: the SDK pulls in
Rust-compiled dependencies (jiter/pydantic-core) that have no prebuilt
wheels for Termux/Android and fail to build there.
"""

import logging

import aiohttp

log = logging.getLogger("summariser.claude_client")

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 500

SYSTEM_PROMPT = (
    "You summarise group-chat conversations for someone who was not present. "
    "Be concise. Capture the key points and decisions. "
    "If there are action items or anything urgent, list them under an "
    "'Action items:' heading. "
    "Finish your reply with the exact status string you are given, "
    "on its own final line, with nothing after it."
)


class ClaudeSummariser:
    def __init__(self, api_key, session=None):
        self._api_key = api_key
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

    async def summarise(self, messages, status):
        """messages: list of {sender_name, text, timestamp}. status: str."""
        transcript = "\n".join(
            f"{m.get('sender_name', 'Unknown')}: {m.get('text', '')}" for m in messages
        )
        user_content = (
            f"Conversation transcript:\n\n{transcript}\n\n"
            f"Status string to append on the final line: {status}"
        )
        payload = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_content}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        session = await self._ensure_session()
        async with session.post(
            API_URL, json=payload, headers=headers, timeout=120
        ) as resp:
            body = await resp.json()
            if resp.status != 200:
                raise RuntimeError(
                    f"Anthropic API {resp.status}: {body.get('error', body)}"
                )

        text = "".join(
            block.get("text", "")
            for block in body.get("content", [])
            if block.get("type") == "text"
        ).strip()
        if status not in text.splitlines()[-1:]:
            text = f"{text}\n{status}"
        return text
