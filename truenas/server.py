"""TrueNAS Scale RPi - Main Application & WebSocket Server."""
import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

from .config import Config
from .rpc import JsonRpcHandler, JsonRpcError
from .auth import AuthManager
from .jobs import JobManager
from .subscriptions import SubscriptionManager
from .backends.config_store import ConfigStore

from .modules.core import CoreModule
from .modules.system import SystemModule
from .modules.storage import StorageModule
from .modules.network import NetworkModule
from .modules.service import ServiceModule
from .modules.sharing import SharingModule
from .modules.alert import AlertModule
from .modules.filesystem import FilesystemModule
from .modules.users import UserGroupModule
from .modules.app import AppModule
from .modules.vm import VmModule
from .modules.dataprotection import ReplicationModule
from .modules.misc import MiscModule
from .shell.terminal import ShellManager

log = logging.getLogger("truenas")

FORBIDDEN_TEXT = """<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>403 Forbidden</title></head>
<body style="font-family:sans-serif;margin:2rem">
<h1>403 Forbidden</h1>
<p>As APIs deste servidor s&atilde;o internas.</p>
<p>Somente a interface web servida por este servidor (mesmo origin) pode
comunicar-se com elas.</p>
</body>
</html>
"""

ROOT_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>TrueNAS Scale RPi</title></head>
<body style="font-family:sans-serif;margin:2rem">
<h1>TrueNAS Scale RPi</h1>
<p>O backend esta ativo (WebSocket API em <code>/api/current</code>).</p>
<p><strong>UI nao encontrada.</strong> A interface Angular ainda nao foi compilada.</p>
<p>Para compilar, rode novamente o instalador:</p>
<pre>cd ~/TrueNAS_Raspberry
sudo ./install.sh</pre>
<p>Ou compile manualmente:</p>
<pre>cd /opt/truenas-rpi/webui-master
sudo yarn build:prod</pre>
<p>Depois recarregue <code>http://(ip_do_host)/</code></p>
</body>
</html>
"""


class WSAdapter:
    """Adapta um aiohttp WebSocketResponse a API usada pelos handlers
    (send / recv / iteracao) herdada da biblioteca `websockets`."""

    def __init__(self, ws):
        self._ws = ws

    async def send(self, data):
        if isinstance(data, (bytes, bytearray, memoryview)):
            await self._ws.send_bytes(bytes(data))
        else:
            await self._ws.send_str(str(data))

    async def recv(self):
        from aiohttp import WSMsgType
        while True:
            msg = await self._ws.receive()
            if msg.type == WSMsgType.TEXT:
                return msg.data
            if msg.type == WSMsgType.BINARY:
                return msg.data
            if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
        import websockets
        raise websockets.exceptions.ConnectionClosedError(None, None)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        from aiohttp import WSMsgType
        async for msg in self._ws:
            if msg.type == WSMsgType.TEXT:
                yield msg.data
            elif msg.type == WSMsgType.BINARY:
                yield msg.data
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                return


class TrueNasApp:
    def __init__(self):
        self.config = Config()
        self.rpc_handler = JsonRpcHandler()
        self.auth_manager = AuthManager(self.config["data_dir"])
        self.job_manager = JobManager()
        self.sub_manager = SubscriptionManager()
        self.config_store = ConfigStore(
            os.path.join(self.config["data_dir"], "config.json")
        )
        self.shell_manager = ShellManager(self)
        self._connected_clients: dict[str, dict] = {}

        self._register_modules()
        self._register_auth_middleware()

    def _register_modules(self):
        core = CoreModule(self)
        system = SystemModule(self)
        storage = StorageModule(self)
        network = NetworkModule(self)
        service = ServiceModule(self)
        sharing = SharingModule(self)
        alert = AlertModule(self)
        filesystem = FilesystemModule(self)
        users = UserGroupModule(self)
        app = AppModule(self)
        vm = VmModule(self)
        dataprotection = ReplicationModule(self)
        misc = MiscModule(self)

        core_methods = [
            "set_options", "get_jobs", "subscribe", "unsubscribe",
            "job_abort", "download", "resize_shell", "bulk",
        ]

        system_api = {
            "info": "info",
            "product_type": "product_type",
            "hostname": "hostname",
            "reboot_info": "reboot_info",
            "reboot": "reboot",
            "shutdown": "shutdown",
            "config_reset": "config_reset",
            "update.check": "update_check",
            "update.update": "update_update",
            "is_freebsd": "is_freebsd",
            "is_enterprise": "is_enterprise",
            "is_ix_hardware": "is_ix_hardware",
            "general.config": "general_config",
            "general.update": "general_update",
            "advanced.config": "advanced_config",
            "advanced.update": "advanced_update",
            "security.config": "security_config",
            "security.update": "security_update",
            "ntpserver.query": "ntp_server_query",
            "ntpserver.create": "ntp_server_create",
            "ntpserver.update": "ntp_server_update",
            "ntpserver.delete": "ntp_server_delete",
            "tunable.query": "tunable_query",
            "tunable.create": "tunable_create",
            "tunable.update": "tunable_update",
            "tunable.delete": "tunable_delete",
            "initshutdownscript.query": "initshutdownscript_query",
            "initshutdownscript.create": "initshutdownscript_create",
            "initshutdownscript.update": "initshutdownscript_update",
            "initshutdownscript.delete": "initshutdownscript_delete",
        }

        iscsi_api = {
            "global.config": "iscsi_global_config",
            "global.update": "iscsi_global_update",
            "portal.query": "iscsi_portals_query",
            "portal.create": "iscsi_portals_create",
            "portal.update": "iscsi_portals_update",
            "portal.delete": "iscsi_portals_delete",
            "target.query": "iscsi_targets_query",
            "target.create": "iscsi_targets_create",
            "target.update": "iscsi_targets_update",
            "target.delete": "iscsi_targets_delete",
            "extent.query": "iscsi_extents_query",
            "extent.create": "iscsi_extents_create",
            "extent.update": "iscsi_extents_update",
            "extent.delete": "iscsi_extents_delete",
            "targetextent.query": "iscsi_targetextent_query",
            "targetextent.create": "iscsi_targetextent_create",
            "targetextent.delete": "iscsi_targetextent_delete",
            "initiator.query": "iscsi_initiators_query",
            "initiator.create": "iscsi_initiators_create",
            "initiator.update": "iscsi_initiators_update",
            "initiator.delete": "iscsi_initiators_delete",
            "auth.query": "iscsi_auth_query",
            "auth.create": "iscsi_auth_create",
            "auth.delete": "iscsi_auth_delete",
            "session.query": "iscsi_sessions_query",
        }

        filesystem_api = {
            "listdir": "listdir",
            "stat": "stat",
            "statfs": "statfs",
            "getacl": "getacl",
            "setacl": "setacl",
            "setperm": "setperm",
            "put": "put",
            "file_tail_follow": "file_tail_follow",
            "mkdir": "mkdir",
            "unlink": "unlink",
            "rename": "rename",
            "acl_is_trivial": "acl_is_trivial",
            "acltemplate.query": "acltemplate_query",
        }

        vm_api = {
            "query": "query", "create": "create", "update": "update",
            "delete": "delete", "start": "start", "stop": "stop",
            "restart": "restart", "reset": "reset", "poweroff": "poweroff",
            "resume": "resume", "display_devices": "display_devices",
            "display_web_uri": "display_web_uri", "port_wizard": "port_wizard",
            "virtualization_details": "virtualization_details",
            "vnc_port_wizard": "vnc_port_wizard",
        }

        failover_api = {
            "config": "failover_config",
            "status": "failover_status",
            "disabled.reasons": "failover_disabled_reasons",
            "reboot.info": "failover_reboot_info",
        }

        kerberos_api = {
            "config": "kerberos_config",
            "realm.query": "kerberos_realm_query",
            "keytab.query": "kerberos_keytab_query",
        }

        self.rpc_handler.register_module("core", core, include=core_methods)
        self.rpc_handler.register_module("system", system, mapping=system_api)
        self.rpc_handler.register_module("pool", storage)
        self.rpc_handler.register_module("pool.dataset", storage)
        self.rpc_handler.register_module("pool.snapshot", storage)
        self.rpc_handler.register_module("pool.snapshottask", storage)
        self.rpc_handler.register_module("pool.scrub", storage)
        self.rpc_handler.register_module("pool.resilver", storage)
        self.rpc_handler.register_module("disk", storage)
        self.rpc_handler.register_module("zpool", storage, mapping={"query": "pool_query"})
        self.rpc_handler.register_module("boot", storage)
        self.rpc_handler.register_module("systemdataset", storage)
        self.rpc_handler.register_module("interface", network)
        self.rpc_handler.register_module("network.configuration", network)
        self.rpc_handler.register_module("staticroute", network)
        self.rpc_handler.register_module("service", service, include=["query", "update", "control"])
        self.rpc_handler.register_module("sharing.smb", sharing,
                                         mapping={"share_precheck": "smb_precheck"})
        self.rpc_handler.register_module("sharing.nfs", sharing)
        self.rpc_handler.register_module("sharing.s3", sharing)
        self.rpc_handler.register_module("sharing.webdav", sharing)
        self.rpc_handler.register_module("smb", sharing)
        self.rpc_handler.register_module("nfs", sharing)
        self.rpc_handler.register_module("s3", sharing)
        self.rpc_handler.register_module("iscsi", sharing, mapping=iscsi_api)
        self.rpc_handler.register_module("alert", alert)
        self.rpc_handler.register_module("alertservice", alert)
        self.rpc_handler.register_module("alertclasses", alert)
        self.rpc_handler.register_module("filesystem", filesystem, mapping=filesystem_api)
        self.rpc_handler.register_module("device", filesystem)
        self.rpc_handler.register_module("user", users)
        self.rpc_handler.register_module("group", users)
        self.rpc_handler.register_module("privilege", users)
        self.rpc_handler.register_module("app", app)
        self.rpc_handler.register_module("docker", app)
        self.rpc_handler.register_module("catalog", app)
        self.rpc_handler.register_module("container", app, mapping={
            "query": "container_query",
            "image.query": "container_image_query",
            "stats": "container_stats",
            "metrics": "container_metrics",
            "prune": "container_prune",
        })
        self.rpc_handler.register_module("vm", vm, mapping=vm_api)
        self.rpc_handler.register_module("vm.device", vm)
        self.rpc_handler.register_module("vmware", vm)
        self.rpc_handler.register_module("replication", dataprotection)
        self.rpc_handler.register_module("cloudsync", dataprotection)
        self.rpc_handler.register_module("cloud_backup", dataprotection)
        self.rpc_handler.register_module("rsynctask", dataprotection)
        self.rpc_handler.register_module("snapshottask", dataprotection)
        self.rpc_handler.register_module("mail", misc)
        self.rpc_handler.register_module("snmp", misc)
        self.rpc_handler.register_module("ssh", misc)
        self.rpc_handler.register_module("ftp", misc)
        self.rpc_handler.register_module("ups", misc)
        self.rpc_handler.register_module("reporting", misc)
        self.rpc_handler.register_module("api_key", misc)
        self.rpc_handler.register_module("keychaincredential", misc)
        self.rpc_handler.register_module("failover", misc, mapping=failover_api)
        self.rpc_handler.register_module("truenas", misc)
        self.rpc_handler.register_module("truecommand", misc)
        self.rpc_handler.register_module("audit", misc)
        self.rpc_handler.register_module("kmip", misc)
        self.rpc_handler.register_module("acme.dns.authenticator", misc,
                                         mapping={"query": "acme_dns_authenticator_query"})
        self.rpc_handler.register_module("cloud_credential", misc)
        self.rpc_handler.register_module("directoryservices", misc)
        self.rpc_handler.register_module("ldap", misc)
        self.rpc_handler.register_module("kerberos", misc, mapping=kerberos_api)
        self.rpc_handler.register_module("support", misc)
        self.rpc_handler.register_module("enclosure2", misc)
        self.rpc_handler.register_module("certificate", misc)
        self.rpc_handler.register_module("certificate.certificateauthority", misc,
                                         mapping={"query": "certificate_ca_query"})
        self.rpc_handler.register_module("tn_connect", misc,
                                         mapping={"config": "truecommand_config"})

        self.rpc_handler.register("auth.login_ex", self._handle_login_ex)
        self.rpc_handler.register("auth.login_ex_continue", self._handle_login_ex_continue)
        self.rpc_handler.register("auth.logout", self._handle_logout)
        self.rpc_handler.register("auth.me", self._handle_auth_me)
        self.rpc_handler.register("auth.generate_token", self._handle_generate_token)
        self.rpc_handler.register("auth.sessions", self._handle_auth_sessions)
        self.rpc_handler.register("auth.terminate_session", self._handle_terminate_session)
        self.rpc_handler.register("auth.terminate_other_sessions", self._handle_terminate_other_sessions)
        self.rpc_handler.register("auth.set_attribute", self._handle_set_attribute)
        self.rpc_handler.register("auth.twofactor.config", self._handle_2fa_config)

        self.rpc_handler.register("boot_id", self._handle_boot_id)

    def _register_auth_middleware(self):
        async def auth_middleware(method: str, params: list, context: dict):
            skip_auth = {
                "auth.login_ex", "auth.login_ex_continue",
                "core.set_options",
            }
            if method in skip_auth:
                return True

            token = context.get("auth_token", "")
            if not token:
                token = context.get("token", "")

            if not token:
                return False

            session = self.auth_manager.get_session(token)
            if not session:
                return False

            if not self.auth_manager.has_permission(session, method):
                return False

            context["session"] = session
            context["user"] = session.user
            return True

        self.rpc_handler.add_middleware(auth_middleware)

    # ── Auth Handlers ─────────────────────────────────────

    async def _handle_login_ex(self, mechanisms: list = None, context: dict = None):
        if not mechanisms:
            return {"auth_result": "DENIED", "response_type": "DENIED"}

        for mech in mechanisms:
            mech_type = mech.get("mechanism", "")
            if mech_type == "PASSWORD_PLAIN":
                username = mech.get("username", "")
                password = mech.get("password", "")
                session = self.auth_manager.authenticate_password(username, password)
                if session:
                    return {
                        "auth_result": "SUCCESS",
                        "response_type": "SUCCESS",
                        "user_info": {
                            "username": session.user,
                            "privilege": {
                                "web_shell": True,
                                "webui_access": True,
                                "roles": session.roles,
                            },
                            "roles": session.roles,
                        },
                        "reconnect_token": session.reconnect_token,
                    }
                return {"auth_result": "DENIED", "response_type": "DENIED"}

            elif mech_type == "TOKEN_PLAIN":
                token = mech.get("token", "")
                session = self.auth_manager.authenticate_reconnect(token)
                if session:
                    return {
                        "auth_result": "SUCCESS",
                        "response_type": "SUCCESS",
                        "user_info": {
                            "username": session.user,
                            "privilege": {
                                "web_shell": True,
                                "webui_access": True,
                                "roles": session.roles,
                            },
                            "roles": session.roles,
                        },
                        "reconnect_token": session.reconnect_token,
                    }
                return {"auth_result": "DENIED", "response_type": "DENIED"}

        return {"auth_result": "DENIED", "response_type": "DENIED"}

    async def _handle_login_ex_continue(self, **kwargs):
        return {"auth_result": "SUCCESS"}

    async def _handle_logout(self, context: dict = None):
        token = context.get("auth_token", "")
        if token:
            self.auth_manager.logout(token)
        return None

    async def _handle_auth_me(self, context: dict = None):
        session = context.get("session")
        if session:
            return {
                "username": session.user,
                "privilege": {"web_shell": True},
                "roles": session.roles,
            }
        return {"username": "", "privilege": {"web_shell": False}, "roles": []}

    async def _handle_generate_token(self, data: dict = None, context: dict = None):
        session = context.get("session")
        if session:
            token = self.auth_manager.generate_token(session.user, ttl=300)
            return {"token": token, "ttl": 300}
        return {"token": "", "ttl": 0}

    async def _handle_auth_sessions(self, data: dict = None, context: dict = None):
        return self.auth_manager.get_sessions()

    async def _handle_terminate_session(self, data: dict = None, context: dict = None):
        if data:
            token = data.get("token", "")
            self.auth_manager.terminate_session(token)
        return None

    async def _handle_terminate_other_sessions(self, context: dict = None):
        token = context.get("auth_token", "")
        if token:
            self.auth_manager.terminate_other_sessions(token)
        return None

    async def _handle_set_attribute(self, key: str = "", value: Any = None, context: dict = None):
        token = context.get("auth_token", "")
        if token and key:
            self.auth_manager.set_attribute(token, key, value)
        return True

    async def _handle_2fa_config(self, context: dict = None):
        return {"enabled": False, "secret": "", "otp_digits": 6, "interval": 30}

    async def _handle_boot_id(self, context: dict = None):
        try:
            with open("/proc/sys/kernel/random/boot_id") as f:
                return f.read().strip()
        except Exception:
            return str(uuid.uuid4())

    # ── WebSocket Handler ─────────────────────────────────

    async def handle_api_websocket(self, websocket: WebSocketServerProtocol):
        client_id = str(uuid.uuid4())[:8]
        self._connected_clients[client_id] = {
            "websocket": websocket,
            "auth_token": None,
            "connected_at": time.time(),
            "client_options": {},
        }
        log.info("Client connected: %s", client_id)

        try:
            async for raw_message in websocket:
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue

                context = {
                    "websocket": websocket,
                    "client_id": client_id,
                    "auth_token": self._connected_clients[client_id].get("auth_token", ""),
                }

                if self._connected_clients[client_id].get("auth_token"):
                    session = self.auth_manager.get_session(
                        self._connected_clients[client_id]["auth_token"]
                    )
                    if session:
                        context["session"] = session
                        context["user"] = session.user
                        context["token"] = self._connected_clients[client_id]["auth_token"]

                response = await self.rpc_handler.handle(message, context)

                if message.get("method") == "auth.login_ex" and response:
                    result = response.get("result", {})
                    if isinstance(result, dict) and result.get("auth_result") == "SUCCESS":
                        reconnect = result.get("reconnect_token", "")
                        for t, s in self.auth_manager._sessions.items():
                            if s.reconnect_token == reconnect:
                                self._connected_clients[client_id]["auth_token"] = t
                                context["auth_token"] = t
                                break

                if message.get("method") == "auth.logout":
                    self._connected_clients[client_id]["auth_token"] = None

                if response is not None:
                    await websocket.send(json.dumps(response))

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            log.exception("WebSocket error for client %s: %s", client_id, e)
        finally:
            client = self._connected_clients.get(client_id)
            if client:
                for q in client.get("queues", []):
                    self.sub_manager.remove_queue(q)
                for sid in client.get("sub_ids", []):
                    self.sub_manager.unsubscribe(sid)
            self._connected_clients.pop(client_id, None)
            log.info("Client disconnected: %s", client_id)

    # ── HTTP origin / UI helpers ──────────────────────────

    @staticmethod
    def _split_host_port(host_header: str):
        """('host', port|None) a partir de um cabeçalho Host (ipv4/v6, c/ ou s/ porta)."""
        host_header = host_header.strip()
        if host_header.startswith("["):  # [::1] ou [::1]:8080
            end = host_header.find("]")
            host = host_header[1:end].lower()
            rest = host_header[end + 1:] or ""
            port = None
            if rest.startswith(":"):
                try:
                    port = int(rest[1:])
                except (ValueError, IndexError):
                    port = None
            return host, port
        if host_header.count(":") == 1:  # host:port
            host, _, port_str = host_header.partition(":")
            try:
                return host.lower(), int(port_str)
            except ValueError:
                return host.lower(), None
        return host_header.lower(), None

    def _origin_allowed(self, request) -> bool:
        """Mesmo-origin: o cabeçalho Origin (browser) deve bater com o Host do request.
        Requests sem Origin (não-browser) são recusados: só a Web UI fala com as APIs."""
        from urllib.parse import urlsplit

        origin = request.headers.get("Origin")
        if not origin:
            return False
        try:
            parts = urlsplit(origin)
        except Exception:
            return False
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        origin_host = parts.hostname.lower()
        origin_port = parts.port
        if origin_port is None:
            origin_port = 443 if parts.scheme == "https" else 80

        req_host, req_port = self._split_host_port(request.host)
        if req_port is None:
            req_port = 443 if request.secure else 80
        return origin_host == req_host and origin_port == req_port

    def _find_ui_dir(self) -> str:
        """Localiza o diretório com o index.html real (dist/, dist/browser/, ...)."""
        base = self.config.get("web_ui_path", "")
        for cand in (
            base,
            os.path.join(base, "browser"),
            os.path.join(base, "webui"),
            os.path.join(base, "webui", "browser"),
        ):
            if cand and os.path.isfile(os.path.join(cand, "index.html")):
                return cand
        return base if base and os.path.isdir(base) else ""

    async def start_http_server(self):
        """Serve a Web UI na raiz (/) e os endpoints de API/WS (mesmo-origin)."""
        from aiohttp import web

        app = web.Application()

        app.router.add_get("/api/current", self._handle_api_ws)
        app.router.add_get("/websocket/shell", self._handle_shell_ws)
        app.router.add_get("/websocket/shell/", self._handle_shell_ws)
        app.router.add_get("/api/boot_id", self._handle_boot_id_http)
        app.router.add_get("/api/docs", self._handle_api_docs)
        app.router.add_get("/{path:.*}", self._handle_static)

        ui_dir = self._find_ui_dir()
        log.info(
            "Web UI: %s (%s)",
            ui_dir or "NAO encontrada",
            self.config.get("web_ui_path", ""),
        )

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(
            runner,
            self.config.get("host", "0.0.0.0"),
            self.config.get("port", 80),
        )
        await site.start()
        log.info(
            "HTTP server started on %s:%s",
            self.config.get("host"),
            self.config.get("port"),
        )

    def _safe_join(self, ui_dir: str, rel_path: str) -> str:
        """Une um caminho relativo a UI, impedindo traversal para fora da pasta."""
        if rel_path in ("", ".", "/"):
            return os.path.realpath(ui_dir)
        candidate = os.path.realpath(os.path.join(ui_dir, rel_path))
        root = os.path.realpath(ui_dir)
        if candidate == root or candidate.startswith(root + os.sep):
            return candidate
        return None

    async def _handle_static(self, request):
        from aiohttp import web

        ui_dir = self._find_ui_dir()
        if not ui_dir:
            return web.Response(text=ROOT_HTML, content_type="text/html")

        path = request.match_info.get("path", "") or request.path
        rel = os.path.normpath(path.lstrip("/"))
        if rel.startswith(".."):
            raise web.HTTPForbidden()
        candidate = self._safe_join(ui_dir, rel)
        if candidate is None:
            raise web.HTTPForbidden()

        if os.path.isfile(candidate):
            return web.FileResponse(candidate)
        if os.path.isdir(candidate):
            if path and not path.endswith("/"):
                raise web.HTTPFound(request.path + "/")
            index = os.path.join(candidate, "index.html")
            if os.path.isfile(index):
                return web.FileResponse(index)
            raise web.HTTPNotFound()

        # Fallback SPA (TrueNAS Scale usa history routing: /dashboard, /network, ...).
        index = os.path.join(ui_dir, "index.html")
        if os.path.isfile(index):
            ext = os.path.splitext(path)[1].lower()
            accept = request.headers.get("Accept", "")
            if not ext or "text/html" in accept:
                return web.FileResponse(index)
        raise web.HTTPNotFound()

    async def _handle_api_ws(self, request):
        from aiohttp import web
        if not self._origin_allowed(request):
            log.warning("API WS rejeitado (origin não permitido): %s",
                        request.headers.get("Origin", "(sem origin)"))
            return web.Response(status=403, text=FORBIDDEN_TEXT, content_type="text/html")
        ws = web.WebSocketResponse(max_msg_size=2**20)
        await ws.prepare(request)
        await self.handle_api_websocket(WSAdapter(ws))
        return ws

    async def _handle_shell_ws(self, request):
        from aiohttp import web
        if not self._origin_allowed(request):
            log.warning("Shell WS rejeitado (origin não permitido): %s",
                        request.headers.get("Origin", "(sem origin)"))
            return web.Response(status=403, text=FORBIDDEN_TEXT, content_type="text/html")
        ws = web.WebSocketResponse(max_msg_size=2**20)
        await ws.prepare(request)
        await self.shell_manager.handle_shell_websocket(WSAdapter(ws))
        return ws

    async def _handle_boot_id_http(self, request):
        from aiohttp import web
        if not self._origin_allowed(request):
            return web.Response(status=403, text=FORBIDDEN_TEXT, content_type="text/html")
        boot_id = await self._handle_boot_id()
        return web.json_response({"boot_id": boot_id})

    async def _handle_api_docs(self, request):
        from aiohttp import web
        if not self._origin_allowed(request):
            return web.Response(status=403, text=FORBIDDEN_TEXT, content_type="text/html")
        return web.json_response({
            "openapi": "3.0.0",
            "info": {"title": "TrueNAS Scale RPi API", "version": "0.1.0"},
            "paths": {},
        })

    async def start_alert_checker(self):
        while True:
            try:
                alert_module = AlertModule(self)
                await alert_module.check_system_alerts()
            except Exception as e:
                log.warning("Alert check failed: %s", e)
            await asyncio.sleep(300)

    async def run(self):
        log.info("Starting TrueNAS Scale RPi Backend v0.1.0")

        await self.start_http_server()

        shell_port = self.config.get("shell_port", 8080)
        shell_server = await websockets.serve(
            self.shell_manager.handle_shell_websocket,
            "127.0.0.1",  # interno: a UI usa o shell na porta 80 (/websocket/shell/)
            shell_port,
            max_size=2**20,
        )
        log.info(
            "Shell WebSocket interno iniciado em ws://127.0.0.1:%s (loopback somente)",
            shell_port,
        )

        asyncio.create_task(self.start_alert_checker())

        stop = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass

        await stop.wait()
        shell_server.close()
        log.info("TrueNAS Scale RPi Backend stopped")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    app = TrueNasApp()
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
