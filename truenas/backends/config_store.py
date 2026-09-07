"""JSON-based config persistence store."""
import json
import os
import asyncio
from pathlib import Path
from typing import Any, Optional


class ConfigStore:
    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._lock = asyncio.Lock()
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                with open(self._path) as f:
                    self._data = json.load(f)
            except json.JSONDecodeError:
                self._data = {}
        else:
            self._data = {}

    async def save(self):
        async with self._lock:
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=2, default=str)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    async def set(self, key: str, value: Any):
        async with self._lock:
            self._data[key] = value
        await self.save()

    async def update(self, updates: dict):
        async with self._lock:
            self._data.update(updates)
        await self.save()

    async def delete(self, key: str):
        async with self._lock:
            self._data.pop(key, None)
        await self.save()

    def get_all(self) -> dict:
        return dict(self._data)

    async def set_nested(self, *keys: str, value: Any):
        async with self._lock:
            obj = self._data
            for k in keys[:-1]:
                obj = obj.setdefault(k, {})
            obj[keys[-1]] = value
        await self.save()
