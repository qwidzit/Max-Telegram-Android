"""Max (VK) messenger listener using VK Long Poll API.

No library beyond aiohttp is required. Uses VK's password auth to obtain
an access token, then drives the VK Long Poll API to receive new messages.

All library-specific protocol details are contained in this file.
"""

import asyncio
import json
import logging
import os
import time

import aiohttp

log = logging.getLogger("max_listener.client")

VK_API_BASE = "https://api.vk.com/method"
OAUTH_URL = "https://oauth.vk.com/token"
API_VERSION = "5.131"

# Official VK Android client credentials
_CLIENT_ID = "2274003"
_CLIENT_SECRET = "hHbZxrka2uZ6jB1inYsH"

CHAT_PEER_OFFSET = 2_000_000_000  # peer_id above this = group chat
MAX_BACKOFF = 300


class MaxListener:
    def __init__(self, phone, password, session_file, on_message):
        self._phone = phone
        self._password = password
        self._session_file = session_file
        self._on_message = on_message
        self._token = None
        self._http = None
        self._chat_cache = {}
        self._user_cache = {}

    # ------------------------------------------------------------------ run

    async def run(self):
        if not self._phone:
            log.warning("MAX_PHONE not set — Max listener disabled.")
            return
        self._http = aiohttp.ClientSession()
        try:
            backoff = 2
            while True:
                try:
                    await self._authenticate()
                    await self._poll_loop()
                    backoff = 2
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("Max listener error; reconnecting in %ss", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
        finally:
            await self._http.close()
            self._http = None

    # --------------------------------------------------------- auth / session

    def _load_token(self):
        if os.path.exists(self._session_file):
            try:
                with open(self._session_file, "r") as f:
                    data = json.load(f)
                self._token = data.get("access_token")
                return bool(self._token)
            except (json.JSONDecodeError, OSError):
                pass
        return False

    def _save_token(self):
        try:
            with open(self._session_file, "w") as f:
                json.dump({"access_token": self._token}, f)
        except OSError as e:
            log.warning("Could not save session file: %s", e)

    async def _authenticate(self):
        if self._load_token():
            log.info("Loaded existing Max session from %s", self._session_file)
            return
        if not self._password:
            raise RuntimeError(
                "MAX_PASSWORD is not set. Fill it in .env and restart."
            )
        log.info("Authenticating with Max (VK) as %s …", self._phone)
        async with self._http.post(
            OAUTH_URL,
            data={
                "grant_type": "password",
                "client_id": _CLIENT_ID,
                "client_secret": _CLIENT_SECRET,
                "username": self._phone,
                "password": self._password,
                "scope": "messages,offline",
                "v": API_VERSION,
                "2fa_supported": "1",
            },
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json(content_type=None)

        if "access_token" not in data:
            err = data.get("error_description") or data.get("error") or str(data)
            raise RuntimeError(f"Max auth failed: {err}")

        self._token = data["access_token"]
        self._save_token()
        log.info("Max authentication successful.")

    # -------------------------------------------------------------- VK API

    async def _api(self, method, **params):
        params["access_token"] = self._token
        params["v"] = API_VERSION
        async with self._http.get(
            f"{VK_API_BASE}/{method}",
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            body = await resp.json(content_type=None)
        if "error" in body:
            code = body["error"].get("error_code")
            msg = body["error"].get("error_msg", str(body["error"]))
            # token expired — clear session so next iteration re-authenticates
            if code in (5, 1117):
                self._token = None
                if os.path.exists(self._session_file):
                    os.remove(self._session_file)
            raise RuntimeError(f"VK API {method}: [{code}] {msg}")
        return body["response"]

    # ----------------------------------------------------- name resolution

    async def _chat_name(self, peer_id):
        if peer_id in self._chat_cache:
            return self._chat_cache[peer_id]
        try:
            if peer_id > CHAT_PEER_OFFSET:
                info = await self._api(
                    "messages.getChat", chat_id=peer_id - CHAT_PEER_OFFSET
                )
                name = info.get("title") or f"Chat {peer_id - CHAT_PEER_OFFSET}"
            else:
                users = await self._api("users.get", user_ids=peer_id)
                u = users[0]
                name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
                name = name or str(peer_id)
        except Exception:
            log.debug("Could not resolve peer_id %s", peer_id, exc_info=True)
            name = str(peer_id)
        self._chat_cache[peer_id] = name
        return name

    async def _user_name(self, user_id):
        if not user_id:
            return "Unknown"
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            users = await self._api("users.get", user_ids=user_id)
            u = users[0]
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            name = name or str(user_id)
        except Exception:
            log.debug("Could not resolve user_id %s", user_id, exc_info=True)
            name = str(user_id)
        self._user_cache[user_id] = name
        return name

    # ---------------------------------------------------------- long poll

    async def _poll_loop(self):
        lp = await self._api(
            "messages.getLongPollServer", lp_version=3, need_pts=0
        )
        server = lp["server"]
        if not server.startswith("http"):
            server = "https://" + server
        key = lp["key"]
        ts = str(lp["ts"])
        log.info("Max long poll connected.")

        while True:
            try:
                async with self._http.get(
                    server,
                    params={
                        "act": "a_check",
                        "key": key,
                        "ts": ts,
                        "wait": 25,
                        "mode": 2,
                        "version": 3,
                    },
                    timeout=aiohttp.ClientTimeout(total=35),
                ) as resp:
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.warning("Long poll request error (%s), retrying", e)
                await asyncio.sleep(1)
                continue

            failed = data.get("failed")
            if failed == 1:
                ts = str(data["ts"])
                continue
            if failed in (2, 3):
                log.info("Long poll expired (failed=%s), re-fetching server", failed)
                lp = await self._api(
                    "messages.getLongPollServer", lp_version=3, need_pts=0
                )
                server = lp["server"]
                if not server.startswith("http"):
                    server = "https://" + server
                key = lp["key"]
                ts = str(lp["ts"])
                continue

            ts = str(data.get("ts", ts))
            for update in data.get("updates", []):
                if update[0] == 4:
                    await self._handle_update(update)

    async def _handle_update(self, update):
        # [4, msg_id, flags, peer_id, timestamp, text, extra_dict]
        flags = update[2]
        if flags & 2:  # outgoing — skip
            return
        peer_id = update[3]
        timestamp = update[4]
        text = update[5] if len(update) > 5 else ""
        extra = update[6] if len(update) > 6 else {}

        if not text:
            return  # sticker / voice / attachment-only — nothing to forward

        # Sender: group chats carry "from" in the extra dict; 1:1 = peer itself
        raw_from = extra.get("from") if isinstance(extra, dict) else None
        sender_id = int(raw_from) if raw_from else (peer_id if peer_id < CHAT_PEER_OFFSET else 0)

        chat_name = await self._chat_name(peer_id)
        sender_name = await self._user_name(sender_id)

        await self._on_message(
            {
                "chat_name": chat_name,
                "sender_name": sender_name,
                "text": text,
                "timestamp": timestamp,
            }
        )
