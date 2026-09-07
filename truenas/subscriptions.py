"""Subscription manager for collection_update push events."""
import asyncio
import uuid
from typing import Any


class SubscriptionManager:
    def __init__(self):
        self._subscriptions: dict[str, dict] = {}

    def subscribe(self, method: str, params: Any = None) -> str:
        sub_id = str(uuid.uuid4())
        self._subscriptions[sub_id] = {
            "method": method,
            "params": params,
            "queues": [],
        }
        return sub_id

    def unsubscribe(self, sub_id: str):
        self._subscriptions.pop(sub_id, None)

    def add_queue(self, sub_id: str, queue: asyncio.Queue):
        if sub_id in self._subscriptions:
            self._subscriptions[sub_id]["queues"].append(queue)

    def remove_queue(self, queue: asyncio.Queue):
        for sub in self._subscriptions.values():
            sub["queues"] = [q for q in sub["queues"] if q is not queue]

    async def publish(
        self, collection: str, id_val: Any, msg: str, fields: dict = None
    ):
        for sub_id, sub in self._subscriptions.items():
            if sub["method"] == collection:
                for q in sub["queues"]:
                    try:
                        q.put_nowait({
                            "collection": collection,
                            "id": id_val,
                            "msg": msg,
                            "fields": fields or {},
                        })
                    except asyncio.QueueFull:
                        pass

    def get_subscriptions_for(self, method: str) -> list[str]:
        return [
            sid
            for sid, sub in self._subscriptions.items()
            if sub["method"] == method
        ]
