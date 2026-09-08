"""Network module - interface.*, network.configuration.*, staticroute.*."""
import asyncio
import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger("truenas.network")


class NetworkModule:
    def __init__(self, app):
        self.app = app

    async def interface_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..backends.linux import get_network_interfaces
        from ..query import apply_filters, apply_options
        ifaces = await get_network_interfaces()
        saved = self.app.config_store.get("interfaces", {})
        for iface in ifaces:
            name = iface.get("name", "")
            if name in saved:
                iface.update(saved[name])
        if filters:
            ifaces = apply_filters(ifaces, filters)
        if options:
            ifaces = apply_options(ifaces, options)
        return ifaces

    async def interface_create(self, data: dict = None, context: dict = None):
        if not data:
            return {}
        name = data.get("name", "")
        iface_type = data.get("type", "PHYSICAL")
        from ..backends.linux import run_cmd

        if iface_type == "VLAN":
            parent = data.get("vlan_parent_interface", "")
            vlan_tag = data.get("vlan_tag", 0)
            vlan_pcp = data.get("vlan_pcp", 0)
            if parent and vlan_tag:
                await run_cmd(f"ip link add link {parent} name {name} type vlan id {vlan_tag}")
                await run_cmd(f"ip link set {name} up")
        elif iface_type == "BRIDGE":
            await run_cmd(f"ip link add name {name} type bridge")
            for member in data.get("bridge_members", []):
                await run_cmd(f"ip link set {member} master {name}")
            await run_cmd(f"ip link set {name} up")
        elif iface_type == "LAGG":
            lagg_type = data.get("lagg_protocol", "LACP")
            members = data.get("lagg_interfaces", [])
            lagg_mode = {"LACP": "802.3ad", "FAILOVER": "active-backup", "LOADBALANCE": "balance-xor", "ROUNDROBIN": "balance-rr"}.get(lagg_type, "balance-rr")
            if members:
                primary = members[0]
                await run_cmd(f"ip link add name {name} type bond mode {lagg_mode} miimon 100")
                await run_cmd(f"ip link set {primary} down")
                await run_cmd(f"ip link set {primary} master {name}")
                await run_cmd(f"ip link set {primary} up")
                for m in members[1:]:
                    await run_cmd(f"ip link set {m} down")
                    await run_cmd(f"ip link set {m} master {name}")
                    await run_cmd(f"ip link set {m} up")
                await run_cmd(f"ip link set {name} up")
        else:
            await run_cmd(f"ip link set {name} up")

        addresses = data.get("aliases", [])
        for addr in addresses:
            ip = addr.get("address", "")
            netmask = addr.get("netmask", "24")
            if ip:
                if "/" not in str(netmask):
                    prefix = self._netmask_to_prefix(netmask)
                else:
                    prefix = netmask
                await run_cmd(f"ip addr add {ip}/{prefix} dev {name}")

        saved = self.app.config_store.get("interfaces", {})
        saved[name] = data
        await self.app.config_store.set("interfaces", saved)

        return await self.interface_query(filters=[["name", "=", name]])

    async def interface_update(self, id: str = None, data: dict = None, context: dict = None):
        if not id or not data:
            return await self.interface_query(filters=[["name", "=", id]])
        saved = self.app.config_store.get("interfaces", {})
        if id in saved:
            saved[id].update(data)
        else:
            saved[id] = data
        await self.app.config_store.set("interfaces", saved)
        return await self.interface_query(filters=[["name", "=", id]])

    async def interface_delete(self, id: str = None, context: dict = None):
        from ..backends.linux import run_cmd
        if id:
            await run_cmd(f"ip link delete {id}")
            saved = self.app.config_store.get("interfaces", {})
            saved.pop(id, None)
            await self.app.config_store.set("interfaces", saved)
        return None

    async def interface_has_carp(self, id: str = None, context: dict = None):
        return False

    async def interface_checkin(self, context: dict = None):
        return {"rollback": True}

    async def interface_commit(self, rollback: bool = True, context: dict = None):
        return None

    async def interface_rollback(self, context: dict = None):
        return None

    async def interface_defaults(self, context: dict = None):
        return {"ipv4": {"netmask": 24}}

    async def interface_websocket_local_ip(self, context: dict = None):
        ws = (context or {}).get("websocket")
        try:
            addr = getattr(ws, "local_address", None)
            if addr:
                return str(addr[0])
        except Exception:
            pass
        try:
            import socket
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

    def _netmask_to_prefix(self, netmask: str) -> int:
        if "." in netmask:
            return sum(bin(int(x)).count("1") for x in netmask.split("."))
        try:
            return int(netmask)
        except ValueError:
            return 24

    # ── Network Configuration ─────────────────────────────

    async def configuration_config(self, context: dict = None):
        stored = self.app.config_store.get("network_config", {
            "hostname": "truenas.local",
            "domain": "local",
            "domains": ["local"],
            "nameservers": ["8.8.8.8", "8.8.4.4"],
            "ipv4gateway": "",
            "ipv6gateway": "",
            "routes": [],
            "httpproxy": "",
            "host": "0.0.0.0",
            "activity": [],
            "inv4default": {},
            "inv6default": {},
        })
        return stored

    async def configuration_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.configuration_config()
            current.update(data)
            await self.app.config_store.set("network_config", current)
            if "hostname" in data:
                from ..backends.linux import run_cmd
                await run_cmd(f"hostnamectl set-hostname {data['hostname']}")
            if "nameservers" in data:
                dns_conf = "# Generated by truenas-rpi\n"
                for ns in data["nameservers"]:
                    dns_conf += f"nameserver {ns}\n"
                try:
                    with open("/etc/resolv.conf", "w") as f:
                        f.write(dns_conf)
                except PermissionError:
                    pass
        return await self.configuration_config()

    async def configuration_summary(self, context: dict = None):
        from ..backends.linux import get_network_interfaces
        ifaces = await get_network_interfaces()
        config = await self.configuration_config()
        return {
            "hostname": config.get("hostname", ""),
            "interfaces": ifaces,
            "default_routes": [],
            "nameservers": config.get("nameservers", []),
        }

    # ── Static Routes ─────────────────────────────────────

    async def staticroute_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        routes = self.app.config_store.get("static_routes", [])
        if filters:
            routes = apply_filters(routes, filters)
        if options:
            routes = apply_options(routes, options)
        return routes

    async def staticroute_create(self, data: dict = None, context: dict = None):
        routes = await self.staticroute_query()
        if data:
            data["id"] = len(routes) + 1
            routes.append(data)
            await self.app.config_store.set("static_routes", routes)
            network = data.get("network", "")
            gateway = data.get("gateway", "")
            if network and gateway:
                from ..backends.linux import run_cmd
                await run_cmd(f"ip route add {network} via {gateway}")
        return data or {}

    async def staticroute_update(self, id: int = None, data: dict = None, context: dict = None):
        routes = await self.staticroute_query()
        for r in routes:
            if r.get("id") == id:
                r.update(data or {})
                await self.app.config_store.set("static_routes", routes)
                return r
        return {}

    async def staticroute_delete(self, id: int = None, context: dict = None):
        routes = await self.staticroute_query()
        route = next((r for r in routes if r.get("id") == id), None)
        if route:
            network = route.get("network", "")
            gateway = route.get("gateway", "")
            if network and gateway:
                from ..backends.linux import run_cmd
                await run_cmd(f"ip route del {network} via {gateway}")
        routes = [r for r in routes if r.get("id") != id]
        await self.app.config_store.set("static_routes", routes)
        return None
