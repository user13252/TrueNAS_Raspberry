"""Service module - service.query, service.update, service.control."""
import asyncio
import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger("truenas.service")

KNOWN_SERVICES = [
    {"id": "afp", "service": "afp", "title": "AFP", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "cifs", "service": "cifs", "title": "SMB", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "/var/log/samba4/log.smbd", "logs_fadvise": ""},
    {"id": "nfs", "service": "nfs", "title": "NFS", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "webdav", "service": "webdav", "title": "WebDAV", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "ftp", "service": "ftp", "title": "FTP", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "tftp", "service": "tftp", "title": "TFTP", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "s3", "service": "s3", "title": "S3", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "rsyncd", "service": "rsyncd", "title": "Rsyncd", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "lldp", "service": "lldp", "title": "LLDP", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "mdns", "service": "mdns", "title": "mDNS/DNS-SD", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "snmp", "service": "snmp", "title": "SNMP", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "ups", "service": "ups", "title": "UPS", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "dynamicdns", "service": "dynamicdns", "title": "Dynamic DNS", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "openvpn", "service": "openvpn", "title": "OpenVPN", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "wireguard", "service": "wireguard", "title": "WireGuard", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "disk_local", "service": "disk_local", "title": "S.M.A.R.T.", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "smartd", "service": "smartd", "title": "S.M.A.R.T.", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "docker", "service": "docker", "title": "Docker", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
    {"id": "kubernetes", "service": "kubernetes", "title": "Kubernetes", "state": "STOPPED", "enable": False, "pids": [], "logs_path": "", "logs_fadvise": ""},
]

SERVICE_COMMANDS = {
    "cifs": {"start": "smbd --no-process-group", "stop": "killall smbd", "restart": "systemctl restart smbd"},
    "nfs": {"start": "rpcbind && nfsd", "stop": "killall nfsd", "restart": "systemctl restart nfs-kernel-server"},
    "s3": {"start": "minio server /data", "stop": "killall minio", "restart": "systemctl restart minio"},
    "snmp": {"start": "snmpd", "stop": "killall snmpd", "restart": "systemctl restart snmpd"},
}


class ServiceModule:
    def __init__(self, app):
        self.app = app

    async def query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        services = list(KNOWN_SERVICES)
        saved = self.app.config_store.get("services", {})
        for svc in services:
            sid = svc["id"]
            if sid in saved:
                svc.update(saved[sid])
        if filters:
            services = apply_filters(services, filters)
        if options:
            services = apply_options(services, options)
        return services

    async def update(self, id: str = None, data: dict = None, context: dict = None):
        saved = self.app.config_store.get("services", {})
        if id and data:
            saved[id] = data
            await self.app.config_store.set("services", saved)
            await self.app.sub_manager.publish("service.query", id, "changed", data)
        return await self.query(filters=[["id", "=", id]])

    async def control(self, service: str = "", action: str = "", context: dict = None):
        from ..backends.linux import run_cmd
        cmds = SERVICE_COMMANDS.get(service, {})
        cmd = cmds.get(action)
        if not cmd:
            if action == "start":
                cmd = f"systemctl start {service}"
            elif action == "stop":
                cmd = f"systemctl stop {service}"
            elif action == "restart":
                cmd = f"systemctl restart {service}"

        if cmd:
            code, stdout, stderr = await run_cmd(cmd, timeout=30)
            state = "RUNNING" if action in ("start", "restart") else "STOPPED"
            if code != 0:
                log.warning("Service %s %s failed: %s", service, action, stderr)
                state = "FAILED"

            saved = self.app.config_store.get("services", {})
            if service in saved:
                saved[service]["state"] = state
            else:
                saved[service] = {"state": state}
            await self.app.config_store.set("services", saved)
            await self.app.sub_manager.publish("service.query", service, "changed", {"state": state})
            return state

        return "UNKNOWN"
