"""Max messenger listener via Android notifications (Termux:API).

The Max app (package `ru.oneme.app`) posts a `CHAT_NOTIF` notification for
each incoming message. We poll `termux-notification-list` and emit a
normalised event per new message. No Max API auth is involved.

Requires the Termux:API app installed and the `termux-api` package, with
Notification Access granted to Termux:API in Android settings.

Limitation: Android may truncate very long message text in notifications.
"""

import asyncio
import json
import logging
from collections import OrderedDict

log = logging.getLogger("max_listener.client")

MAX_PACKAGE = "ru.oneme.app"
CHAT_TAG = "CHAT_NOTIF"
POLL_INTERVAL_SECONDS = 4
SEEN_LIMIT = 5000


class MaxListener:
    def __init__(self, on_message, poll_interval=POLL_INTERVAL_SECONDS):
        self._on_message = on_message
        self._poll_interval = poll_interval
        self._seen = OrderedDict()  # signature -> None, bounded FIFO
        self._primed = False

    async def run(self):
        if not await self._termux_available():
            log.warning(
                "termux-notification-list not available. Install the Termux:API "
                "app + `pkg install termux-api` and grant Notification Access. "
                "Max listener disabled."
            )
            return
        log.info("Max notification listener started (package %s).", MAX_PACKAGE)
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Notification poll failed; continuing")
            await asyncio.sleep(self._poll_interval)

    async def _termux_available(self):
        try:
            proc = await asyncio.create_subprocess_exec(
                "termux-notification-list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=15)
            return proc.returncode == 0
        except (FileNotFoundError, asyncio.TimeoutError, OSError):
            return False

    async def _poll_once(self):
        proc = await asyncio.create_subprocess_exec(
            "termux-notification-list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        if proc.returncode != 0:
            log.warning("termux-notification-list exited %s", proc.returncode)
            return
        try:
            notifications = json.loads(out.decode("utf-8") or "[]")
        except json.JSONDecodeError:
            log.warning("Could not parse notification list JSON")
            return

        # First successful poll: record existing notifications as baseline
        # so we don't replay old/unread messages on startup.
        priming = not self._primed

        for n in notifications:
            if n.get("packageName") != MAX_PACKAGE:
                continue
            if n.get("tag") != CHAT_TAG:
                continue
            title = (n.get("title") or "").strip()
            content = (n.get("content") or "").strip()
            when = n.get("when", "")
            if not title or not content:
                continue

            signature = f"{n.get('key', '')}|{when}|{content}"
            if signature in self._seen:
                continue
            self._remember(signature)
            if priming:
                continue

            chat_name, sender_name, text = self._parse(title, content)
            await self._on_message(
                {
                    "chat_name": chat_name,
                    "sender_name": sender_name,
                    "text": text,
                    "timestamp": when,
                }
            )

        self._primed = True

    def _remember(self, signature):
        self._seen[signature] = None
        while len(self._seen) > SEEN_LIMIT:
            self._seen.popitem(last=False)

    @staticmethod
    def _parse(title, content):
        """title = chat name. Group messages prefix the sender as 'Name: text'."""
        if "\n" not in content.split(":", 1)[0]:
            head, sep, rest = content.partition(": ")
            if sep and 0 < len(head) <= 40 and "\n" not in head:
                return title, head.strip(), rest.strip()
        # 1:1 chat: the chat title is the sender.
        return title, title, content
