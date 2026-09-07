"""Sharing module - sharing.smb.*, sharing.nfs.*, sharing.s3.*, smb.*, nfs.*, iscsi.*."""
import asyncio
import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger("truenas.sharing")


class SharingModule:
    def __init__(self, app):
        self.app = app

    # ── SMB Shares ────────────────────────────────────────

    async def smb_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        shares = self.app.config_store.get("smb_shares", [])
        if filters:
            shares = apply_filters(shares, filters)
        if options:
            shares = apply_options(shares, options)
        return shares

    async def smb_create(self, data: dict = None, context: dict = None):
        shares = await self.smb_query()
        if data:
            data["id"] = len(shares) + 1
            shares.append(data)
            await self.app.config_store.set("smb_shares", shares)
            await self._apply_smb_config()
        return data or {}

    async def smb_update(self, id: int = None, data: dict = None, context: dict = None):
        shares = await self.smb_query()
        for s in shares:
            if s.get("id") == id:
                s.update(data or {})
                await self.app.config_store.set("smb_shares", shares)
                await self._apply_smb_config()
                return s
        return {}

    async def smb_delete(self, id: int = None, context: dict = None):
        shares = await self.smb_query()
        shares = [s for s in shares if s.get("id") != id]
        await self.app.config_store.set("smb_shares", shares)
        await self._apply_smb_config()
        return None

    async def smb_precheck(self, data: dict = None, context: dict = None):
        return {"valid": True, "verrors": None}

    async def _apply_smb_config(self):
        shares = await self.smb_query()
        conf_path = self.app.config.get("smb_conf", "/etc/samba/smb.conf")
        try:
            lines = ["[global]", "workgroup = WORKGROUP", "server string = TrueNAS RPi",
                     "security = user", "map to guest = Bad User", ""]
            for share in shares:
                name = share.get("name", "")
                path = share.get("path", "")
                if name and path:
                    lines.append(f"[{name}]")
                    lines.append(f"   path = {path}")
                    if share.get("comment"):
                        lines.append(f"   comment = {share['comment']}")
                    if share.get("browsable", True):
                        lines.append("   browsable = yes")
                    else:
                        lines.append("   browsable = no")
                    if share.get("readonly", False):
                        lines.append("   read only = yes")
                    else:
                        lines.append("   read only = no")
                    if share.get("guestok", False):
                        lines.append("   guest ok = yes")
                    if share.get("home", False):
                        lines.append("   valid users = %S")
                    lines.append("")
            with open(conf_path, "w") as f:
                f.write("\n".join(lines))
            from ..backends.linux import run_cmd
            await run_cmd("systemctl restart smbd || true")
        except Exception as e:
            log.error("Failed to write SMB config: %s", e)

    async def smb_config(self, context: dict = None):
        return self.app.config_store.get("smb_config", {
            "id": 1,
            "netbiosname": "TRUENAS-RPI",
            "netbiosalias": [],
            "workgroup": "WORKGROUP",
            "description": "TrueNAS RPi Server",
            "unixcharset": "UTF-8",
            "guestonly": False,
            "guest": "nobody",
            "admin_group": "admin",
            "smb_options": "",
            "durablehandle": True,
            "enable_smb1": False,
            "enable_smb2": True,
            "enable_smb3": True,
            "coalition_support": False,
            "ntlmv1_auth": False,
        })

    async def smb_config_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.smb_config()
            current.update(data)
            await self.app.config_store.set("smb_config", current)
        return await self.smb_config()

    # ── NFS Shares ────────────────────────────────────────

    async def nfs_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        shares = self.app.config_store.get("nfs_shares", [])
        if filters:
            shares = apply_filters(shares, filters)
        if options:
            shares = apply_options(shares, options)
        return shares

    async def nfs_create(self, data: dict = None, context: dict = None):
        shares = await self.nfs_query()
        if data:
            data["id"] = len(shares) + 1
            shares.append(data)
            await self.app.config_store.set("nfs_shares", shares)
            await self._apply_nfs_exports()
        return data or {}

    async def nfs_update(self, id: int = None, data: dict = None, context: dict = None):
        shares = await self.nfs_query()
        for s in shares:
            if s.get("id") == id:
                s.update(data or {})
                await self.app.config_store.set("nfs_shares", shares)
                await self._apply_nfs_exports()
                return s
        return {}

    async def nfs_delete(self, id: int = None, context: dict = None):
        shares = await self.nfs_query()
        shares = [s for s in shares if s.get("id") != id]
        await self.app.config_store.set("nfs_shares", shares)
        await self._apply_nfs_exports()
        return None

    async def _apply_nfs_exports(self):
        shares = await self.nfs_query()
        exports_path = self.app.config.get("nfs_exports", "/etc/exports")
        try:
            lines = []
            for share in shares:
                path = share.get("path", "")
                opts = []
                if share.get("ro", False):
                    opts.append("ro")
                else:
                    opts.append("rw")
                if share.get("mapall_user"):
                    opts.append(f"mapall={share['mapall_user']}")
                if share.get("security"):
                    for sec in share["security"]:
                        opts.append(f"sec={sec}")
                networks = share.get("networks", ["*"])
                for net in networks:
                    lines.append(f"{path} {net}({','.join(opts)})")
            with open(exports_path, "w") as f:
                f.write("\n".join(lines) + "\n" if lines else "")
            from ..backends.linux import run_cmd
            await run_cmd("exportfs -ra")
        except Exception as e:
            log.error("Failed to write NFS exports: %s", e)

    async def nfs_config(self, context: dict = None):
        return self.app.config_store.get("nfs_config", {
            "id": 1,
            "servers": 4,
            "udp": False,
            "allow_non_root": False,
            "v4": True,
            "v4_v3owner": False,
            "v4_krb": False,
            "v4_domain": "",
            "v4_local": True,
            "bindip": [],
            "mountd_port": "",
            "rpcstatd_port": "",
            "rpclockd_port": "",
        })

    async def nfs_config_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.nfs_config()
            current.update(data)
            await self.app.config_store.set("nfs_config", current)
        return await self.nfs_config()

    # ── S3 Shares ─────────────────────────────────────────

    async def s3_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        buckets = self.app.config_store.get("s3_buckets", [])
        if filters:
            buckets = apply_filters(buckets, filters)
        if options:
            buckets = apply_options(buckets, options)
        return buckets

    async def s3_create(self, data: dict = None, context: dict = None):
        buckets = await self.s3_query()
        if data:
            data["id"] = len(buckets) + 1
            buckets.append(data)
            await self.app.config_store.set("s3_buckets", buckets)
        return data or {}

    async def s3_update(self, id: int = None, data: dict = None, context: dict = None):
        buckets = await self.s3_query()
        for b in buckets:
            if b.get("id") == id:
                b.update(data or {})
                await self.app.config_store.set("s3_buckets", buckets)
                return b
        return {}

    async def s3_delete(self, id: int = None, context: dict = None):
        buckets = await self.s3_query()
        buckets = [b for b in buckets if b.get("id") != id]
        await self.app.config_store.set("s3_buckets", buckets)
        return None

    async def s3_config(self, context: dict = None):
        return self.app.config_store.get("s3_config", {
            "id": 1,
            "bindip": "0.0.0.0",
            "bindport": 9000,
            "access_key": "",
            "secret_key": "",
            "browser": True,
            "storage_path": "/mnt/data/s3",
        })

    async def s3_config_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.s3_config()
            current.update(data)
            await self.app.config_store.set("s3_config", current)
        return await self.s3_config()

    # ── WebDAV ────────────────────────────────────────────

    async def webdav_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        shares = self.app.config_store.get("webdav_shares", [])
        if filters:
            shares = apply_filters(shares, filters)
        if options:
            shares = apply_options(shares, options)
        return shares

    async def webdav_create(self, data: dict = None, context: dict = None):
        shares = await self.webdav_query()
        if data:
            data["id"] = len(shares) + 1
            shares.append(data)
            await self.app.config_store.set("webdav_shares", shares)
        return data or {}

    async def webdav_update(self, id: int = None, data: dict = None, context: dict = None):
        shares = await self.webdav_query()
        for s in shares:
            if s.get("id") == id:
                s.update(data or {})
                await self.app.config_store.set("webdav_shares", shares)
                return s
        return {}

    async def webdav_delete(self, id: int = None, context: dict = None):
        shares = await self.webdav_query()
        shares = [s for s in shares if s.get("id") != id]
        await self.app.config_store.set("webdav_shares", shares)
        return None

    # ── iSCSI ─────────────────────────────────────────────

    async def iscsi_global_config(self, context: dict = None):
        return self.app.config_store.get("iscsi_global", {
            "id": 1,
            "basename": "iqn.2005-10.org.freenas.ctl",
            "isns_servers": [],
            "poll_interval": 0,
            "enable_password_auth": False,
        })

    async def iscsi_global_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.iscsi_global_config()
            current.update(data)
            await self.app.config_store.set("iscsi_global", current)
        return await self.iscsi_global_config()

    async def iscsi_portals_query(self, context: dict = None):
        return self.app.config_store.get("iscsi_portals", [])

    async def iscsi_portals_create(self, data: dict = None, context: dict = None):
        portals = await self.iscsi_portals_query()
        if data:
            data["id"] = len(portals) + 1
            portals.append(data)
            await self.app.config_store.set("iscsi_portals", portals)
        return data or {}

    async def iscsi_portals_update(self, id: int = None, data: dict = None, context: dict = None):
        portals = await self.iscsi_portals_query()
        for p in portals:
            if p.get("id") == id:
                p.update(data or {})
                await self.app.config_store.set("iscsi_portals", portals)
                return p
        return {}

    async def iscsi_portals_delete(self, id: int = None, context: dict = None):
        portals = await self.iscsi_portals_query()
        portals = [p for p in portals if p.get("id") != id]
        await self.app.config_store.set("iscsi_portals", portals)
        return None

    async def iscsi_targets_query(self, context: dict = None):
        return self.app.config_store.get("iscsi_targets", [])

    async def iscsi_targets_create(self, data: dict = None, context: dict = None):
        targets = await self.iscsi_targets_query()
        if data:
            data["id"] = len(targets) + 1
            targets.append(data)
            await self.app.config_store.set("iscsi_targets", targets)
        return data or {}

    async def iscsi_targets_update(self, id: int = None, data: dict = None, context: dict = None):
        targets = await self.iscsi_targets_query()
        for t in targets:
            if t.get("id") == id:
                t.update(data or {})
                await self.app.config_store.set("iscsi_targets", targets)
                return t
        return {}

    async def iscsi_targets_delete(self, id: int = None, context: dict = None):
        targets = await self.iscsi_targets_query()
        targets = [t for t in targets if t.get("id") != id]
        await self.app.config_store.set("iscsi_targets", targets)
        return None

    async def iscsi_extents_query(self, context: dict = None):
        return self.app.config_store.get("iscsi_extents", [])

    async def iscsi_extents_create(self, data: dict = None, context: dict = None):
        extents = await self.iscsi_extents_query()
        if data:
            data["id"] = len(extents) + 1
            extents.append(data)
            await self.app.config_store.set("iscsi_extents", extents)
        return data or {}

    async def iscsi_extents_update(self, id: int = None, data: dict = None, context: dict = None):
        extents = await self.iscsi_extents_query()
        for e in extents:
            if e.get("id") == id:
                e.update(data or {})
                await self.app.config_store.set("iscsi_extents", extents)
                return e
        return {}

    async def iscsi_extents_delete(self, id: int = None, context: dict = None):
        extents = await self.iscsi_extents_query()
        extents = [e for e in extents if e.get("id") != id]
        await self.app.config_store.set("iscsi_extents", extents)
        return None

    async def iscsi_targetextent_query(self, context: dict = None):
        return self.app.config_store.get("iscsi_targetextents", [])

    async def iscsi_targetextent_create(self, data: dict = None, context: dict = None):
        tes = await self.iscsi_targetextent_query()
        if data:
            data["id"] = len(tes) + 1
            tes.append(data)
            await self.app.config_store.set("iscsi_targetextents", tes)
        return data or {}

    async def iscsi_targetextent_delete(self, id: int = None, context: dict = None):
        tes = await self.iscsi_targetextent_query()
        tes = [t for t in tes if t.get("id") != id]
        await self.app.config_store.set("iscsi_targetextents", tes)
        return None

    async def iscsi_initiators_query(self, context: dict = None):
        return self.app.config_store.get("iscsi_initiators", [])

    async def iscsi_initiators_create(self, data: dict = None, context: dict = None):
        inits = await self.iscsi_initiators_query()
        if data:
            data["id"] = len(inits) + 1
            inits.append(data)
            await self.app.config_store.set("iscsi_initiators", inits)
        return data or {}

    async def iscsi_initiators_update(self, id: int = None, data: dict = None, context: dict = None):
        inits = await self.iscsi_initiators_query()
        for i in inits:
            if i.get("id") == id:
                i.update(data or {})
                await self.app.config_store.set("iscsi_initiators", inits)
                return i
        return {}

    async def iscsi_initiators_delete(self, id: int = None, context: dict = None):
        inits = await self.iscsi_initiators_query()
        inits = [i for i in inits if i.get("id") != id]
        await self.app.config_store.set("iscsi_initiators", inits)
        return None

    async def iscsi_auth_query(self, context: dict = None):
        return self.app.config_store.get("iscsi_auth", [])

    async def iscsi_auth_create(self, data: dict = None, context: dict = None):
        auth = await self.iscsi_auth_query()
        if data:
            data["id"] = len(auth) + 1
            auth.append(data)
            await self.app.config_store.set("iscsi_auth", auth)
        return data or {}

    async def iscsi_auth_delete(self, id: int = None, context: dict = None):
        auth = await self.iscsi_auth_query()
        auth = [a for a in auth if a.get("id") != id]
        await self.app.config_store.set("iscsi_auth", auth)
        return None

    async def iscsi_sessions_query(self, context: dict = None):
        return []
