"""Misc module - mail.*, snmp.*, ssh.*, ftp.*, ups.*, reporting.*, api_key.*, keychaincredential.*, certificate.*, failover.*, truenas.*, audit.*, kmip.*, acme.*, dns.*, etc."""
import asyncio
import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger("truenas.misc")


class MiscModule:
    def __init__(self, app):
        self.app = app

    # ── WebUI ────────────────────────────────────────────

    async def dashboard_sys_info(self, context: dict = None):
        from ..backends.linux import run_cmd
        version = "RPi-24.10.0"
        uptime = 0
        try:
            with open("/proc/uptime", "r", errors="replace") as f:
                uptime = int(float(f.readline().split()[0]))
        except Exception:
            pass
        code, stdout, _ = await run_cmd("cat /etc/truenas/version 2>/dev/null || echo")
        if code == 0 and stdout.strip():
            version = stdout.strip()
        return {
            "version": version,
            "uptime_seconds": uptime,
            "license": None,
        }

    # ── Mail ──────────────────────────────────────────────

    async def mail_config(self, context: dict = None):
        return self.app.config_store.get("mail_config", {
            "id": 1,
            "fromname": "TrueNAS RPi",
            "fromaddress": "root@truenas.local",
            "outgoingserver": "",
            "port": 25,
            "security": "PLAIN",
            "username": "",
            "password": "",
            "smtphost": "",
            "smtpemail": "",
            "smtp": False,
            "mail_client_": None,
        })

    async def mail_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.mail_config()
            current.update(data)
            await self.app.config_store.set("mail_config", current)
        return await self.mail_config()

    async def mail_send(self, data: dict = None, context: dict = None):
        return None

    # ── SNMP ──────────────────────────────────────────────

    async def snmp_config(self, context: dict = None):
        return self.app.config_store.get("snmp_config", {
            "id": 1,
            "location": "",
            "contact": "",
            "trap": "",
            "community": "public",
            "v3": False,
            "v3_username": "",
            "v3_password": "",
            "v3_authproto": "MD5",
            "v3_privproto": "DES",
            "v3_privpassphrase": "",
            "options": {},
        })

    async def snmp_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.snmp_config()
            current.update(data)
            await self.app.config_store.set("snmp_config", current)
        return await self.snmp_config()

    # ── SSH ───────────────────────────────────────────────

    async def ssh_config(self, context: dict = None):
        return self.app.config_store.get("ssh_config", {
            "id": 1,
            "bindiface": ["lan0"],
            "tcpport": 22,
            "tcpfwd": True,
            "passwordauth": True,
            "pubkeyauth": True,
            "kerberosauth": False,
            "tcpwrappers": False,
            "compression": True,
            "sftp_log_level": "",
            "sftp_log_facility": "",
            "log_level": "INFO",
            "log_facility": "AUTH",
        })

    async def ssh_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.ssh_config()
            current.update(data)
            await self.app.config_store.set("ssh_config", current)
        return await self.ssh_config()

    # ── FTP ───────────────────────────────────────────────

    async def ftp_config(self, context: dict = None):
        return self.app.config_store.get("ftp_config", {
            "id": 1,
            "port": 21,
            "rootlogin": False,
            "rootdir": "/mnt",
            "banner": "",
            "anonymous": False,
            "onlyanonymous": False,
            "localuser": True,
            "onlylocal": False,
            "anonpath": "",
            "filemask": "077",
            "dirmask": "077",
            "fxp": False,
            "resume": True,
            "passive": True,
            "passiveports": {"low": 49152, "high": 65535},
            "ident": False,
            "ssl": False,
            "ssl_certfile": "",
            "ssl_keyfile": "",
            "ssl_ciphers": "",
            "tls": False,
        })

    async def ftp_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.ftp_config()
            current.update(data)
            await self.app.config_store.set("ftp_config", current)
        return await self.ftp_config()

    # ── UPS ───────────────────────────────────────────────

    async def ups_config(self, context: dict = None):
        return self.app.config_store.get("ups_config", {
            "id": 1,
            "mode": "STANDALONE",
            "host": "localhost",
            "port": "auto",
            "driver": "usbhid-ups",
            "upscmd": "",
            "upsdusers": "upsmon",
            "upsdconf": "upsd.conf",
            "monitor": 1,
        })

    async def ups_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.ups_config()
            current.update(data)
            await self.app.config_store.set("ups_config", current)
        return await self.ups_config()

    # ── Reporting ─────────────────────────────────────────

    async def reporting_graphs(self, context: dict = None):
        return [
            {"id": "cpu", "title": "CPU Usage", "type": "LINE", "vertical_label": "%"},
            {"id": "cputemp", "title": "CPU Temperature", "type": "LINE", "vertical_label": "\u00b0C"},
            {"id": "disk", "title": "Disk I/O", "type": "LINE", "vertical_label": "kbytes/s"},
            {"id": "disktemp", "title": "Disk Temperature", "type": "LINE", "vertical_label": "\u00b0C"},
            {"id": "enclosure", "title": "Enclosure", "type": "LINE", "vertical_label": ""},
            {"id": "if", "title": "Network Interface", "type": "LINE", "vertical_label": "kbits/s"},
            {"id": "memory", "title": "Memory", "type": "LINE", "vertical_label": "Mbytes"},
            {"id": "partition", "title": "Partition Usage", "type": "LINE", "vertical_label": "%"},
            {"id": "pool", "title": "Pool I/O", "type": "LINE", "vertical_label": "kbytes/s"},
            {"id": "processes", "title": "Processes", "type": "LINE", "vertical_label": ""},
            {"id": "system", "title": "System Load", "type": "LINE", "vertical_label": ""},
            {"id": "swap", "title": "Swap Usage", "type": "LINE", "vertical_label": "%"},
            {"id": "uptime", "title": "Uptime", "type": "LINE", "vertical_label": "days"},
            {"id": "vmstat", "title": "VM Stat", "type": "LINE", "vertical_label": ""},
            {"id": "nfsstat", "title": "NFS Stats", "type": "LINE", "vertical_label": "calls/s"},
            {"id": "smbstat", "title": "SMB Stats", "type": "LINE", "vertical_label": "kbytes/s"},
        ]

    async def reporting_get_data(self, graphs: list = None, context: dict = None):
        return []

    async def reporting_realtime(self, context: dict = None):
        from ..backends.linux import run_cmd
        cpu_data = {"usage": 0}
        code, stdout, _ = await run_cmd("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")
        if code == 0:
            try:
                cpu_data["usage"] = float(stdout.strip())
            except ValueError:
                pass

        memory_data = {"total": 0, "free": 0, "available": 0, "cached": 0, "buffers": 0}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    key = parts[0].rstrip(":")
                    val = int(parts[1]) * 1024
                    if key == "MemTotal":
                        memory_data["total"] = val
                    elif key == "MemFree":
                        memory_data["free"] = val
                    elif key == "MemAvailable":
                        memory_data["available"] = val
                    elif key == "Cached":
                        memory_data["cached"] = val
                    elif key == "Buffers":
                        memory_data["buffers"] = val
        except Exception:
            pass

        return {
            "cpu": cpu_data,
            "memory": memory_data,
            "interfaces": {},
            "disks": {},
            "protocols": {},
            "zfs": {},
        }

    # ── API Keys ──────────────────────────────────────────

    async def api_key_query(self, context: dict = None):
        return self.app.config_store.get("api_keys", [])

    async def api_key_create(self, data: dict = None, context: dict = None):
        import secrets
        keys = await self.api_key_query()
        if data:
            data["id"] = len(keys) + 1
            data["key"] = f"uk-{secrets.token_hex(24)}"
            keys.append(data)
            await self.app.config_store.set("api_keys", keys)
        return data or {}

    async def api_key_update(self, id: int = None, data: dict = None, context: dict = None):
        keys = await self.api_key_query()
        for k in keys:
            if k.get("id") == id:
                k.update(data or {})
                await self.app.config_store.set("api_keys", keys)
                return k
        return {}

    async def api_key_delete(self, id: int = None, context: dict = None):
        keys = await self.api_key_query()
        keys = [k for k in keys if k.get("id") != id]
        await self.app.config_store.set("api_keys", keys)
        return None

    # ── Keychain Credentials ──────────────────────────────

    async def keychaincredential_query(self, context: dict = None):
        return self.app.config_store.get("keychain_credentials", [])

    async def keychaincredential_create(self, data: dict = None, context: dict = None):
        creds = await self.keychaincredential_query()
        if data:
            data["id"] = len(creds) + 1
            creds.append(data)
            await self.app.config_store.set("keychain_credentials", creds)
        return data or {}

    async def keychaincredential_update(self, id: int = None, data: dict = None, context: dict = None):
        creds = await self.keychaincredential_query()
        for c in creds:
            if c.get("id") == id:
                c.update(data or {})
                await self.app.config_store.set("keychain_credentials", creds)
                return c
        return {}

    async def keychaincredential_delete(self, id: int = None, context: dict = None):
        creds = await self.keychaincredential_query()
        creds = [c for c in creds if c.get("id") != id]
        await self.app.config_store.set("keychain_credentials", creds)
        return None

    async def keychaincredential_generate_ssh_key_pair(self, context: dict = None):
        from ..backends.linux import run_cmd
        import tempfile
        key_file = tempfile.mktemp(suffix="_key")
        code, _, _ = await run_cmd(f"ssh-keygen -t ed25519 -f {key_file} -N ''")
        if code == 0:
            with open(key_file) as f:
                private_key = f.read()
            with open(f"{key_file}.pub") as f:
                public_key = f.read().strip()
            os.unlink(key_file)
            os.unlink(f"{key_file}.pub")
            return {"private_key": private_key, "public_key": public_key}
        return {"private_key": "", "public_key": ""}

    # ── Failover ──────────────────────────────────────────

    async def failover_config(self, context: dict = None):
        return {"id": 1, "disabled": True, "reasons": []}

    async def failover_status(self, context: dict = None):
        return {"status": "SINGLE", "disabled_reasons": []}

    async def failover_disabled_reasons(self, context: dict = None):
        return []

    async def failover_licensed(self, context: dict = None):
        return False

    async def failover_reboot_info(self, context: dict = None):
        return {"status": "SINGLE"}

    # ── TrueNAS / License ─────────────────────────────────

    async def truenas_eula_accepted(self, context: dict = None):
        return True

    async def truenas_set_eula_accepted(self, context: dict = None):
        return True

    async def truenas_is_production(self, context: dict = None):
        return True

    async def truenas_managed_by_truecommand(self, context: dict = None):
        return False

    async def truenas_is_ix_hardware(self, context: dict = None):
        return False

    async def truenas_license_info(self, context: dict = None):
        return None

    async def truecommand_config(self, context: dict = None):
        return {"enabled": False, "status": "DISABLED"}

    async def tn_connect_ips_with_hostnames(self, context: dict = None):
        return {}

    async def fc_capable(self, context: dict = None):
        return False

    # ── Audit ─────────────────────────────────────────────

    async def audit_config(self, context: dict = None):
        return {"id": 1, "reservation": 4}

    async def audit_update(self, data: dict = None, context: dict = None):
        return await self.audit_config()

    async def audit_query(self, filters: list = None, options: dict = None, context: dict = None):
        return []

    async def audit_export(self, data: dict = None, context: dict = None):
        return {}

    async def audit_download_report(self, data: dict = None, context: dict = None):
        return {}

    # ── Certificates ──────────────────────────────────────

    async def certificate_query(self, context: dict = None):
        return self.app.config_store.get("certificates", [])

    async def certificate_ca_query(self, context: dict = None):
        return self.app.config_store.get("certificate_authorities", [])

    # ── KMIP ──────────────────────────────────────────────

    async def kmip_config(self, context: dict = None):
        return {"enabled": False, "manage_sed_disks": False, "manage_zfs_keys": False}

    # ── ACME ──────────────────────────────────────────────

    async def acme_dns_authenticator_query(self, context: dict = None):
        return []

    # ── Cloud Credential ──────────────────────────────────

    async def cloud_credential_query(self, context: dict = None):
        return self.app.config_store.get("cloud_credentials", [])

    async def cloud_credential_create(self, data: dict = None, context: dict = None):
        creds = await self.cloud_credential_query()
        if data:
            data["id"] = len(creds) + 1
            creds.append(data)
            await self.app.config_store.set("cloud_credentials", creds)
        return data or {}

    async def cloud_credential_update(self, id: int = None, data: dict = None, context: dict = None):
        creds = await self.cloud_credential_query()
        for c in creds:
            if c.get("id") == id:
                c.update(data or {})
                await self.app.config_store.set("cloud_credentials", creds)
                return c
        return {}

    async def cloud_credential_delete(self, id: int = None, context: dict = None):
        creds = await self.cloud_credential_query()
        creds = [c for c in creds if c.get("id") != id]
        await self.app.config_store.set("cloud_credentials", creds)
        return None

    async def cloud_credential_verify(self, data: dict = None, context: dict = None):
        return {"valid": True}

    # ── Directory Services ────────────────────────────────

    async def directoryservices_status(self, context: dict = None):
        return {"ldap": None, "ad": None, "nt4": None}

    async def directoryservices_cache_refresh(self, context: dict = None):
        return None

    async def ldap_config(self, context: dict = None):
        return self.app.config_store.get("ldap_config", {"id": 1, "enable": False})

    async def ldap_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.ldap_config()
            current.update(data)
            await self.app.config_store.set("ldap_config", current)
        return await self.ldap_config()

    # ── Kerberos ──────────────────────────────────────────

    async def kerberos_config(self, context: dict = None):
        return self.app.config_store.get("kerberos_config", {"id": 1, "realm": "", "kdc": ""})

    async def kerberos_realm_query(self, context: dict = None):
        return []

    async def kerberos_keytab_query(self, context: dict = None):
        return []

    # ── Support ───────────────────────────────────────────

    async def support_query(self, context: dict = None):
        return []

    # ── Enclosure ─────────────────────────────────────────

    async def enclosure2_query(self, context: dict = None):
        return []
