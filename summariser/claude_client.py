"""Calls the Claude API to summarise a batch of buffered messages."""

import logging

from anthropic import AsyncAnthropic

log = logging.getLogger("summariser.claude_client")

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
    def __init__(self, api_key):
        self._client = AsyncAnthropic(api_key=api_key)

    async def summarise(self, messages, status):
        """messages: list of {sender_name, text, timestamp}. status: str."""
        transcript = "\n".join(
            f"{m.get('sender_name', 'Unknown')}: {m.get('text', '')}" for m in messages
        )
        user_content = (
            f"Conversation transcript:\n\n{transcript}\n\n"
            f"Status string to append on the final line: {status}"
        )
        resp = await self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        ).strip()
        if status not in text.splitlines()[-1:]:
            text = f"{text}\n{status}"
        return text
