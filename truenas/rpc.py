"""JSON-RPC 2.0 handler for TrueNAS middleware protocol."""
import asyncio
import time
import logging
from typing import Any, Callable, Coroutine, Optional

log = logging.getLogger("truenas.rpc")


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data


class JsonRpcHandler:
    def __init__(self):
        self._methods: dict[str, Callable] = {}
        self._middleware: list[Callable] = []
        self._error_subscribers: list[Callable] = []

    def register(self, name: str, func: Callable):
        self._methods[name] = func

    def register_module(self, prefix: str, module: Any,
                        mapping: dict = None, include: list = None):
        """Register module methods under a prefix.

        Three registration mechanisms, applied in order:
          * ``mapping`` -- explicit ``{api_suffix: method_name}`` (overrides)
          * ``include`` -- method names registered verbatim as ``prefix.name``
          * auto-strip -- methods named ``<last_segment>_<rest>`` become
            ``prefix.<rest>`` (e.g. ``pool_query`` -> ``pool.query``)

        Auto-strip only registers methods that start with the prefix's last
        segment, so registering the same module under ``pool``, ``disk`` and
        ``boot`` yields clean disjoint API surfaces (no name duplication).
        """
        prefix_last = prefix.split(".")[-1]

        if include:
            for name in include:
                self.register(f"{prefix}.{name}", getattr(module, name))

        if mapping:
            for api_suffix, method_name in mapping.items():
                self.register(
                    f"{prefix}.{api_suffix}",
                    getattr(module, method_name),
                )

        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            if not attr_name.startswith(prefix_last + "_"):
                continue
            attr = getattr(module, attr_name)
            if not callable(attr):
                continue
            suffix = attr_name[len(prefix_last) + 1:]
            self.register(f"{prefix}.{suffix}", attr)

    def add_middleware(self, func: Callable):
        self._middleware.append(func)

    async def handle(
        self, message: dict, context: dict
    ) -> Optional[dict]:
        if "method" not in message:
            return self._error_response(
                message.get("id"), -32600, "Invalid Request"
            )

        method = message["method"]
        params = message.get("params", [])
        req_id = message.get("id")

        for mw in self._middleware:
            try:
                allowed = await mw(method, params, context)
                if allowed is False:
                    return self._error_response(
                        req_id,
                        -32001,
                        "Not permitted",
                        {"method": method},
                    )
            except Exception as e:
                log.exception("Middleware error for %s", method)
                return self._error_response(
                    req_id, -32001, str(e)
                )

        if method not in self._methods:
            return self._error_response(
                req_id,
                -32601,
                f"Method not found: {method}",
            )

        try:
            func = self._methods[method]

            async def _invoke(*args, **kwargs):
                try:
                    if asyncio.iscoroutinefunction(func):
                        return await func(*args, **kwargs)
                    return func(*args, **kwargs)
                except TypeError:
                    if "context" in kwargs:
                        kwargs.pop("context")
                        if asyncio.iscoroutinefunction(func):
                            return await func(*args, **kwargs)
                        return func(*args, **kwargs)
                    raise

            if isinstance(params, list):
                result = await _invoke(*params, context=context)
            elif isinstance(params, dict):
                result = await _invoke(**params, context=context)
            else:
                result = await _invoke(context=context)

            if req_id is None:
                return None

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }

        except JsonRpcError as e:
            return self._error_response(
                req_id, e.code, e.message, e.data
            )
        except Exception as e:
            log.exception("Error handling %s", method)
            return self._error_response(
                req_id,
                -32000,
                f"Internal error: {e}",
                {"errname": type(e).__name__, "reason": str(e)},
            )

    def _error_response(
        self,
        req_id: Any,
        code: int,
        message: str,
        data: Any = None,
    ) -> dict:
        err: dict = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        resp = {"jsonrpc": "2.0", "id": req_id, "error": err}
        return resp
