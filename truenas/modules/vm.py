"""VM module - vm.*, vm.device.*, vmware.*."""
import asyncio
import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger("truenas.vm")


class VmModule:
    def __init__(self, app):
        self.app = app

    async def query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        vms = self.app.config_store.get("vms", [])
        if filters:
            vms = apply_filters(vms, filters)
        if options:
            vms = apply_options(vms, options)
        return vms

    async def create(self, data: dict = None, context: dict = None):
        vms = await self.query()
        if data:
            data["id"] = len(vms) + 1
            data.setdefault("status", {"state": "STOPPED"})
            data.setdefault("state", "STOPPED")
            vms.append(data)
            await self.app.config_store.set("vms", vms)
        return data or {}

    async def update(self, id: int = None, data: dict = None, context: dict = None):
        vms = await self.query()
        for vm in vms:
            if vm.get("id") == id:
                vm.update(data or {})
                await self.app.config_store.set("vms", vms)
                return vm
        return {}

    async def delete(self, id: int = None, data: dict = None, context: dict = None):
        vms = await self.query()
        vms = [v for v in vms if v.get("id") != id]
        await self.app.config_store.set("vms", vms)
        return None

    async def start(self, id: int = None, context: dict = None):
        vms = await self.query()
        for vm in vms:
            if vm.get("id") == id:
                vm["status"] = {"state": "RUNNING"}
                vm["state"] = "RUNNING"
                await self.app.config_store.set("vms", vms)
                break
        return None

    async def stop(self, id: int = None, data: dict = None, context: dict = None):
        vms = await self.query()
        for vm in vms:
            if vm.get("id") == id:
                vm["status"] = {"state": "STOPPED"}
                vm["state"] = "STOPPED"
                await self.app.config_store.set("vms", vms)
                break
        return None

    async def restart(self, id: int = None, context: dict = None):
        await self.stop(id=id, context=context)
        await self.start(id=id, context=context)
        return None

    async def reset(self, id: int = None, context: dict = None):
        return await self.restart(id=id, context=context)

    async def poweroff(self, id: int = None, context: dict = None):
        return await self.stop(id=id, context=context)

    async def resume(self, id: int = None, context: dict = None):
        vms = await self.query()
        for vm in vms:
            if vm.get("id") == id:
                vm["status"] = {"state": "RUNNING"}
                vm["state"] = "RUNNING"
                await self.app.config_store.set("vms", vms)
                break
        return None

    async def display_devices(self, id: int = None, context: dict = None):
        return []

    async def display_web_uri(self, id: int = None, context: dict = None):
        return {}

    async def port_wizard(self, context: dict = None):
        return {"port": 5900}

    async def virtualization_details(self, context: dict = None):
        from ..backends.linux import run_cmd
        code, stdout, _ = await run_cmd("uname -m")
        arch = stdout.strip() if code == 0 else "unknown"
        return {
            "supported_archs": [arch],
            "hypervisor": "KVM" if arch in ("x86_64", "aarch64") else "NONE",
            "status": "DISABLED" if arch not in ("x86_64", "aarch64") else "LOADED",
        }

    async def vnc_port_wizard(self, context: dict = None):
        return {"port": 5900}

    # ── VM Devices ────────────────────────────────────────

    async def device_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        devices = self.app.config_store.get("vm_devices", [])
        if filters:
            devices = apply_filters(devices, filters)
        if options:
            devices = apply_options(devices, options)
        return devices

    async def device_create(self, data: dict = None, context: dict = None):
        devices = await self.device_query()
        if data:
            data["id"] = len(devices) + 1
            devices.append(data)
            await self.app.config_store.set("vm_devices", devices)
        return data or {}

    async def device_update(self, id: int = None, data: dict = None, context: dict = None):
        devices = await self.device_query()
        for d in devices:
            if d.get("id") == id:
                d.update(data or {})
                await self.app.config_store.set("vm_devices", devices)
                return d
        return {}

    async def device_delete(self, id: int = None, context: dict = None):
        devices = await self.device_query()
        devices = [d for d in devices if d.get("id") != id]
        await self.app.config_store.set("vm_devices", devices)
        return None

    async def device_pci_passthrough_choices(self, context: dict = None):
        return []

    async def device_usb_passthrough_choices(self, context: dict = None):
        from ..backends.linux import run_cmd
        devices = []
        code, stdout, _ = await run_cmd("lsusb 2>/dev/null")
        if code == 0:
            for line in stdout.strip().split("\n"):
                if line:
                    devices.append({"vendor_id": "", "product_id": "", "description": line.strip()})
        return devices

    # ── VMware Snapshots ──────────────────────────────────

    async def vmware_query(self, context: dict = None):
        return self.app.config_store.get("vmware_configs", [])

    async def vmware_create(self, data: dict = None, context: dict = None):
        configs = await self.vmware_query()
        if data:
            data["id"] = len(configs) + 1
            configs.append(data)
            await self.app.config_store.set("vmware_configs", configs)
        return data or {}

    async def vmware_update(self, id: int = None, data: dict = None, context: dict = None):
        configs = await self.vmware_query()
        for c in configs:
            if c.get("id") == id:
                c.update(data or {})
                await self.app.config_store.set("vmware_configs", configs)
                return c
        return {}

    async def vmware_delete(self, id: int = None, context: dict = None):
        configs = await self.vmware_query()
        configs = [c for c in configs if c.get("id") != id]
        await self.app.config_store.set("vmware_configs", configs)
        return None

    async def vmware_match_products(self, context: dict = None):
        return []

    async def vmware_get_datastores(self, data: dict = None, context: dict = None):
        return []
