"""Core module - core.set_options, core.get_jobs, core.subscribe, core.unsubscribe, core.bulk, core.job_abort, core.download, core.resize_shell."""
import asyncio
import logging
from typing import Any, Optional

log = logging.getLogger("truenas.core")


class CoreModule:
    def __init__(self, app):
        self.app = app

    async def ping(self, context: dict = None):
        return "pong"

    async def set_options(self, options: dict = None, context: dict = None):
        if options:
            ctx = context or {}
            ctx.setdefault("client_options", {}).update(options)
        return None

    async def get_jobs(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        jobs = self.app.job_manager.get_all()
        if filters:
            jobs = apply_filters(jobs, filters)
        if options:
            jobs = apply_options(jobs, options)
        return jobs

    async def subscribe(self, methods: list = None, context: dict = None):
        if not methods:
            return ""
        sub_ids = []
        for method in (methods if isinstance(methods, list) else [methods]):
            sub_id = self.app.sub_manager.subscribe(method)
            sub_ids.append(sub_id)
            if context:
                ws = context.get("websocket")
                if ws:
                    q = asyncio.Queue(maxsize=200)
                    self.app.sub_manager.add_queue(sub_id, q)
                    client_id = context.get("client_id")
                    if client_id and client_id in getattr(
                        self.app, "_connected_clients", {}
                    ):
                        client = self.app._connected_clients[client_id]
                        client.setdefault("queues", []).append(q)
                        client.setdefault("sub_ids", []).append(sub_id)
                    asyncio.create_task(
                        self._push_subscriber(ws, q)
                    )
        return sub_ids[0] if len(sub_ids) == 1 else sub_ids

    async def _push_subscriber(self, ws, queue: asyncio.Queue):
        try:
            while True:
                update = await queue.get()
                msg = {
                    "jsonrpc": "2.0",
                    "method": "collection_update",
                    "params": update,
                }
                if hasattr(ws, 'send'):
                    import json
                    await ws.send(json.dumps(msg))
        except Exception:
            pass

    async def unsubscribe(self, subscriptions: list = None, context: dict = None):
        if subscriptions:
            ids = subscriptions if isinstance(subscriptions, list) else [subscriptions]
            for sub_id in ids:
                self.app.sub_manager.unsubscribe(sub_id)
        return None

    async def job_abort(self, job_id: int = None, context: dict = None):
        if job_id is not None:
            self.app.job_manager.abort(job_id)
        return None

    async def download(self, method: str = None, args: list = None,
                       filename: str = "", context: dict = None):
        import secrets
        token = self.app.auth_manager.generate_token("admin", ttl=300)
        job = await self.app.job_manager.create(
            "core.download",
            arguments={"method": method, "args": args, "filename": filename},
            func=lambda j: {"job_id": j.id, "url": f"/_download?auth_token={token}"},
        )
        return {"job_id": job.id, "url": f"/_download?auth_token={token}"}

    async def resize_shell(self, id: int = None, width: int = 80,
                           height: int = 24, context: dict = None):
        return None

    async def bulk(self, jobs: list = None, context: dict = None):
        if not jobs:
            return []
        results = []
        for job_def in jobs:
            method = job_def.get("method")
            params = job_def.get("params", [])
            try:
                result = await self.app.rpc_handler.handle(
                    {"method": method, "params": params, "id": "bulk"},
                    context or {},
                )
                if result and "result" in result:
                    results.append({"result": result["result"]})
                elif result and "error" in result:
                    results.append({"error": result["error"]})
                else:
                    results.append({"result": None})
            except Exception as e:
                results.append({"error": {"message": str(e)}})
        return results
