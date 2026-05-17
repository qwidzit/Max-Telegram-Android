"""Reads/writes config.json. Async-lock protected. Source of truth for chat settings."""

import asyncio
import json
import os

DEFAULT_TIMEOUT_MINUTES = 10
DEFAULT_MESSAGE_COUNT = 20


class ConfigManager:
    def __init__(self, path="config.json"):
        self._path = path
        self._lock = asyncio.Lock()
        self._data = {"chats": {}}
        self._loaded = False

    async def _ensure_loaded(self):
        if self._loaded:
            return
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {"chats": {}}
        if "chats" not in self._data:
            self._data["chats"] = {}
        self._loaded = True

    async def _persist(self):
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self._path)

    async def get_chat_config(self, chat_name):
        async with self._lock:
            await self._ensure_loaded()
            cfg = self._data["chats"].get(chat_name)
            return dict(cfg) if cfg else None

    async def set_chat_config(self, chat_name, config):
        async with self._lock:
            await self._ensure_loaded()
            self._data["chats"][chat_name] = config
            await self._persist()

    async def remove_chat(self, chat_name):
        async with self._lock:
            await self._ensure_loaded()
            existed = chat_name in self._data["chats"]
            self._data["chats"].pop(chat_name, None)
            if existed:
                await self._persist()
            return existed

    async def list_chats(self):
        async with self._lock:
            await self._ensure_loaded()
            return {name: dict(cfg) for name, cfg in self._data["chats"].items()}
