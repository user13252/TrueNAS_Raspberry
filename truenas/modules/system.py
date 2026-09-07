"""System module - system.info, system.general, system.advanced, system.reboot, etc."""
import asyncio
import json
import logging
import os
import platform
import time
from typing import Any, Optional

log = logging.getLogger("truenas.system")


class SystemModule:
    def __init__(self, app):
        self.app = app
        self._config_store = app.config_store
        self._general_defaults = {
            "ui_address": "0.0.0.0",
            "ui_port": 80,
            "ui_httpsport": 443,
            "ui_httpsredirect": False,
            "ui_httpprotocols": False,
            "timezone": "UTC",
            "language": "en",
            "kbmap": "us",
            "kbdmap": "",
            "consolemsg": True,
            "syslogserver": "",
            "sysloglevel": "f_info",
            "motd": "",
            "reportingfrequency": "hourly",
            "crashreporting": False,
            "usage_collection": False,
            "advancedmode": False,
            "serialconsole": False,
            "serialport": "",
            "serialspeed": 115200,
            "powerdaemon": True,
            "autotune": False,
            "debug": False,
            "traceback": False,
            "syslog_tls_certificate": None,
            "ui_certificate": None,
            "hci": False,
        }
        self._advanced_defaults = {
            "serialconsole": False,
            "serialport": "",
            "serialspeed": 115200,
            "powerdaemon": True,
            "autotune": False,
            "debug": False,
            "traceback": False,
            "consolemsg": True,
            "sed_user": "user",
            "sed_passwd": "",
            "sysloglevel": "f_info",
            "syslogserver": "",
            "is_debug": False,
            "traceback": False,
            "kernel_extra_options": "",
            "failovervents": False,
        }

    async def info(self, context: dict = None):
        from ..backends.linux import get_system_info, get_disk_info
        info = get_system_info()
        disks = await get_disk_info()
        info["disks"] = {d["name"]: d for d in disks}
        info["memory"] = {
            "physical": info.get("physical_memory", 0),
        }
        return info

    async def product_type(self, context: dict = None):
        return "SCALE"

    async def hostname(self, context: dict = None):
        import socket
        return socket.gethostname()

    async def general_config(self, context: dict = None):
        stored = self._config_store.get("system_general", {})
        config = dict(self._general_defaults)
        config.update(stored)
        return config

    async def general_update(self, data: dict = None, context: dict = None):
        if data:
            await self._config_store.set("system_general", data)
        return await self.general_config()

    async def advanced_config(self, context: dict = None):
        stored = self._config_store.get("system_advanced", {})
        config = dict(self._advanced_defaults)
        config.update(stored)
        return config

    async def advanced_update(self, data: dict = None, context: dict = None):
        if data:
            await self._config_store.set("system_advanced", data)
        return await self.advanced_config()

    async def security_config(self, context: dict = None):
        return {
            "enable_fips": False,
        }

    async def security_update(self, data: dict = None, context: dict = None):
        return await self.security_config()

    async def reboot_info(self, context: dict = None):
        return {
            "delay": 0,
            "reason": "REBOOT_NONE",
        }

    async def reboot(self, delay: int = 0, context: dict = None):
        job = await self.app.job_manager.create(
            "system.reboot",
            func=lambda j: self._do_reboot(delay),
        )
        return job.id

    async def _do_reboot(self, delay: int):
        await asyncio.sleep(delay)
        from ..backends.linux import run_cmd
        await run_cmd("reboot")
        return True

    async def shutdown(self, delay: int = 0, context: dict = None):
        job = await self.app.job_manager.create(
            "system.shutdown",
            func=lambda j: self._do_shutdown(delay),
        )
        return job.id

    async def _do_shutdown(self, delay: int):
        await asyncio.sleep(delay)
        from ..backends.linux import run_cmd
        await run_cmd("shutdown -h now")
        return True

    async def config_reset(self, context: dict = None):
        job = await self.app.job_manager.create(
            "system.config_reset",
            func=lambda j: self._do_config_reset(),
        )
        return job.id

    async def _do_config_reset(self):
        for key in ["system_general", "system_advanced", "system_security"]:
            await self._config_store.delete(key)
        return True

    async def update_check(self, context: dict = None):
        return {
            "status": "available",
            "changes": [],
        }

    async def update_update(self, train: str = "", context: dict = None):
        return await self.update_check()

    async def ntp_server_query(self, context: dict = None):
        return self._config_store.get("ntp_servers", [
            {"address": "0.pool.ntp.org", "burst": False, "iburst": True, "prefer": False, "minpoll": 6, "maxpoll": 10, "offset": 0},
            {"address": "1.pool.ntp.org", "burst": False, "iburst": True, "prefer": False, "minpoll": 6, "maxpoll": 10, "offset": 0},
            {"address": "2.pool.ntp.org", "burst": False, "iburst": True, "prefer": False, "minpoll": 6, "maxpoll": 10, "offset": 0},
        ])

    async def ntp_server_create(self, data: dict = None, context: dict = None):
        servers = await self.ntp_server_query()
        if data:
            servers.append(data)
            await self._config_store.set("ntp_servers", servers)
        return data or {}

    async def ntp_server_update(self, id: int = None, data: dict = None, context: dict = None):
        servers = await self.ntp_server_query()
        if data is not None:
            servers[id] = {**servers[id], **data}
            await self._config_store.set("ntp_servers", servers)
        return servers[id] if id is not None and id < len(servers) else {}

    async def ntp_server_delete(self, id: int = None, context: dict = None):
        servers = await self.ntp_server_query()
        if id is not None and id < len(servers):
            servers.pop(id)
            await self._config_store.set("ntp_servers", servers)
        return None

    async def tunable_query(self, context: dict = None):
        return self._config_store.get("tunables", [])

    async def tunable_create(self, data: dict = None, context: dict = None):
        tunables = await self.tunable_query()
        if data:
            data["id"] = len(tunables) + 1
            tunables.append(data)
            await self._config_store.set("tunables", tunables)
        return data or {}

    async def tunable_update(self, id: int = None, data: dict = None, context: dict = None):
        tunables = await self.tunable_query()
        for t in tunables:
            if t.get("id") == id:
                t.update(data or {})
                await self._config_store.set("tunables", tunables)
                return t
        return {}

    async def tunable_delete(self, id: int = None, context: dict = None):
        tunables = await self.tunable_query()
        tunables = [t for t in tunables if t.get("id") != id]
        await self._config_store.set("tunables", tunables)
        return None

    async def initshutdownscript_query(self, context: dict = None):
        return self._config_store.get("init_scripts", [])

    async def initshutdownscript_create(self, data: dict = None, context: dict = None):
        scripts = await self.initshutdownscript_query()
        if data:
            data["id"] = len(scripts) + 1
            scripts.append(data)
            await self._config_store.set("init_scripts", scripts)
        return data or {}

    async def initshutdownscript_update(self, id: int = None, data: dict = None, context: dict = None):
        scripts = await self.initshutdownscript_query()
        for s in scripts:
            if s.get("id") == id:
                s.update(data or {})
                await self._config_store.set("init_scripts", scripts)
                return s
        return {}

    async def initshutdownscript_delete(self, id: int = None, context: dict = None):
        scripts = await self.initshutdownscript_query()
        scripts = [s for s in scripts if s.get("id") != id]
        await self._config_store.set("init_scripts", scripts)
        return None

    async def is_freebsd(self, context: dict = None):
        return False

    async def is_enterprise(self, context: dict = None):
        return False

    async def is_ix_hardware(self, context: dict = None):
        return False
