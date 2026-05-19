"""Long-polls the Telegram Bot API for owner commands and updates config."""

import asyncio
import logging

import aiohttp

from config.config_manager import DEFAULT_MESSAGE_COUNT, DEFAULT_TIMEOUT_MINUTES

log = logging.getLogger("telegram.command_handler")

API_BASE = "https://api.telegram.org/bot{token}/{method}"

HELP_TEXT = (
    "Commands:\n"
    "/autoresend <chat name>\n"
    "/summarise <chat name> [mins] [count]\n"
    "/timeout <chat name> <mins>\n"
    "/count <chat name> <n>\n"
    "/remove <chat name>\n"
    "/list\n"
    "/status"
)


def _split_trailing_ints(parts, max_ints):
    """Pull up to max_ints trailing integers off the token list.

    Returns (name_tokens, ints) where ints preserves left-to-right order.
    """
    ints = []
    while parts and len(ints) < max_ints and parts[-1].lstrip("-").isdigit():
        ints.insert(0, int(parts.pop()))
    return parts, ints


class CommandHandler:
    def __init__(self, bot_token, owner_chat_id, config_manager, session=None):
        self._token = bot_token
        self._owner_chat_id = int(owner_chat_id)
        self._cfg = config_manager
        self._session = session
        self._own_session = session is None
        self._offset = None

    async def _ensure_session(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _reply(self, text):
        session = await self._ensure_session()
        url = API_BASE.format(token=self._token, method="sendMessage")
        try:
            async with session.post(
                url,
                json={"chat_id": self._owner_chat_id, "text": text},
                timeout=30,
            ) as resp:
                if resp.status != 200:
                    log.error("reply failed %s: %s", resp.status, await resp.text())
        except (aiohttp.ClientError, OSError) as e:
            log.error("reply error: %s", e)

    async def run(self):
        """Long-poll forever, dispatching owner commands."""
        session = await self._ensure_session()
        url = API_BASE.format(token=self._token, method="getUpdates")
        while True:
            try:
                params = {"timeout": 50}
                if self._offset is not None:
                    params["offset"] = self._offset
                async with session.get(url, params=params, timeout=70) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        if resp.status == 409:
                            log.error(
                                "Telegram 409 Conflict — another bot instance "
                                "is polling with this token. Backing off 15s."
                            )
                            await asyncio.sleep(15)
                        else:
                            log.error("getUpdates %s: %s", resp.status, body)
                            await asyncio.sleep(5)
                        continue
                    data = await resp.json()
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as e:
                log.warning("getUpdates error, retrying in 5s: %s", e)
                await asyncio.sleep(5)
                continue

            for update in data.get("result", []):
                self._offset = update["update_id"] + 1
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue
                if msg.get("chat", {}).get("id") != self._owner_chat_id:
                    continue  # security: ignore anyone but the owner
                text = msg.get("text", "")
                if text:
                    await self._dispatch(text.strip())

    async def _dispatch(self, text):
        if not text.startswith("/"):
            return
        parts = text.split()
        cmd = parts[0].lower().lstrip("/")
        args = parts[1:]

        try:
            if cmd == "status":
                await self._reply("✅ Bot is alive and running.")
            elif cmd == "list":
                await self._cmd_list()
            elif cmd == "autoresend":
                await self._cmd_autoresend(args)
            elif cmd == "summarise":
                await self._cmd_summarise(args)
            elif cmd == "timeout":
                await self._cmd_timeout(args)
            elif cmd == "count":
                await self._cmd_count(args)
            elif cmd == "remove":
                await self._cmd_remove(args)
            else:
                pass  # ignore unrecognised input silently
        except Exception as e:  # noqa: BLE001 - never let the poll loop die
            log.exception("command failed")
            await self._reply(f"⚠️ Command failed: {e}")

    async def _cmd_list(self):
        chats = await self._cfg.list_chats()
        if not chats:
            await self._reply("No chats monitored.")
            return
        lines = []
        for name, c in chats.items():
            if c.get("mode") == "summarise":
                lines.append(
                    f"• {name} — summarise "
                    f"(timeout {c.get('timeout_minutes', DEFAULT_TIMEOUT_MINUTES)}m, "
                    f"count {c.get('message_count', DEFAULT_MESSAGE_COUNT)})"
                )
            else:
                lines.append(f"• {name} — autoresend")
        await self._reply("Monitored chats:\n" + "\n".join(lines))

    async def _cmd_autoresend(self, args):
        name = " ".join(args).strip()
        if not name:
            await self._reply("Usage: /autoresend <chat name>")
            return
        await self._cfg.set_chat_config(name, {"mode": "autoresend"})
        await self._reply(f"✅ '{name}' set to autoresend.")

    async def _cmd_summarise(self, args):
        name_tokens, ints = _split_trailing_ints(list(args), 2)
        name = " ".join(name_tokens).strip()
        if not name:
            await self._reply("Usage: /summarise <chat name> [mins] [count]")
            return
        cfg = {
            "mode": "summarise",
            "timeout_minutes": ints[0] if len(ints) >= 1 else DEFAULT_TIMEOUT_MINUTES,
            "message_count": ints[1] if len(ints) >= 2 else DEFAULT_MESSAGE_COUNT,
        }
        await self._cfg.set_chat_config(name, cfg)
        await self._reply(
            f"✅ '{name}' set to summarise "
            f"(timeout {cfg['timeout_minutes']}m, count {cfg['message_count']})."
        )

    async def _cmd_timeout(self, args):
        name_tokens, ints = _split_trailing_ints(list(args), 1)
        name = " ".join(name_tokens).strip()
        if not name or not ints:
            await self._reply("Usage: /timeout <chat name> <mins>")
            return
        existing = await self._cfg.get_chat_config(name)
        if not existing or existing.get("mode") != "summarise":
            await self._reply(f"'{name}' is not in summarise mode.")
            return
        existing["timeout_minutes"] = ints[0]
        await self._cfg.set_chat_config(name, existing)
        await self._reply(f"✅ '{name}' timeout set to {ints[0]}m.")

    async def _cmd_count(self, args):
        name_tokens, ints = _split_trailing_ints(list(args), 1)
        name = " ".join(name_tokens).strip()
        if not name or not ints:
            await self._reply("Usage: /count <chat name> <n>")
            return
        existing = await self._cfg.get_chat_config(name)
        if not existing or existing.get("mode") != "summarise":
            await self._reply(f"'{name}' is not in summarise mode.")
            return
        existing["message_count"] = ints[0]
        await self._cfg.set_chat_config(name, existing)
        await self._reply(f"✅ '{name}' message count set to {ints[0]}.")

    async def _cmd_remove(self, args):
        name = " ".join(args).strip()
        if not name:
            await self._reply("Usage: /remove <chat name>")
            return
        removed = await self._cfg.remove_chat(name)
        await self._reply(
            f"✅ Stopped monitoring '{name}'." if removed else f"'{name}' was not monitored."
        )
