"""App/Docker module - app.*, docker.*, catalog.*."""
import asyncio
import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger("truenas.apps")


class AppModule:
    def __init__(self, app):
        self.app = app

    async def app_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        apps = self.app.config_store.get("apps", [])
        if filters:
            apps = apply_filters(apps, filters)
        if options:
            apps = apply_options(apps, options)
        return apps

    async def app_create(self, data: dict = None, context: dict = None):
        apps = await self.app_query()
        if data:
            data["id"] = len(apps) + 1
            apps.append(data)
            await self.app.config_store.set("apps", apps)
        return data or {}

    async def app_update(self, id: int = None, data: dict = None, context: dict = None):
        apps = await self.app_query()
        for a in apps:
            if a.get("id") == id:
                a.update(data or {})
                await self.app.config_store.set("apps", apps)
                return a
        return {}

    async def app_delete(self, id: int = None, context: dict = None):
        apps = await self.app_query()
        apps = [a for a in apps if a.get("id") != id]
        await self.app.config_store.set("apps", apps)
        return None

    async def app_start(self, app_name: str = "", context: dict = None):
        return None

    async def app_stop(self, app_name: str = "", context: dict = None):
        return None

    async def app_available(self, context: dict = None):
        return self.app.config_store.get("available_apps", [])

    async def app_available_apps(self, context: dict = None):
        return await self.app_available()

    async def app_categories(self, context: dict = None):
        return self.app.config_store.get("app_categories", [])

    async def app_latest(self, context: dict = None):
        return await self.app_available()

    # ── Catalog ───────────────────────────────────────────

    async def catalog_query(self, context: dict = None):
        return self.app.config_store.get("catalogs", [])

    async def catalog_create(self, data: dict = None, context: dict = None):
        catalogs = await self.catalog_query()
        if data:
            data["id"] = len(catalogs) + 1
            catalogs.append(data)
            await self.app.config_store.set("catalogs", catalogs)
        return data or {}

    async def catalog_update(self, id: int = None, data: dict = None, context: dict = None):
        catalogs = await self.catalog_query()
        for c in catalogs:
            if c.get("id") == id:
                c.update(data or {})
                await self.app.config_store.set("catalogs", catalogs)
                return c
        return {}

    async def catalog_delete(self, id: int = None, context: dict = None):
        catalogs = await self.catalog_query()
        catalogs = [c for c in catalogs if c.get("id") != id]
        await self.app.config_store.set("catalogs", catalogs)
        return None

    async def catalog_sync(self, id: int = None, context: dict = None):
        job = await self.app.job_manager.create(
            "catalog.sync",
            func=lambda j: {"synced": True},
        )
        return job.id

    async def catalog_sync_all(self, context: dict = None):
        job = await self.app.job_manager.create(
            "catalog.sync_all",
            func=lambda j: {"synced": True},
        )
        return job.id

    async def catalog_train(self, context: dict = None):
        return ["stable", "community"]

    # ── Docker ────────────────────────────────────────────

    async def docker_config(self, context: dict = None):
        return self.app.config_store.get("docker_config", {
            "id": 1,
            "pool": "",
            "dataset": "",
            "address_pools": None,
            "log_driver": "json-file",
            "log_opts": None,
            "iptables": True,
            "live_restore": False,
            "ip_forward": True,
            "ip_masq": True,
            "bridge": None,
            "storage_driver": "",
            "RegistryMirrors": [],
            "registry_mirrors": [],
        })

    async def docker_update(self, data: dict = None, context: dict = None):
        if data:
            current = await self.docker_config()
            current.update(data)
            await self.app.config_store.set("docker_config", current)
        return await self.docker_config()

    async def docker_state(self, context: dict = None):
        from ..backends.linux import run_cmd
        code, stdout, _ = await run_cmd("systemctl is-active docker 2>/dev/null || docker info >/dev/null 2>&1 && echo active || echo inactive")
        return stdout.strip().lower()

    async def docker_status(self, context: dict = None):
        from ..backends.linux import run_cmd
        code, stdout, _ = await run_cmd("docker info >/dev/null 2>&1 && echo running || echo stopped")
        if code == 0 and stdout.strip() == "running":
            return {"status": "RUNNING"}
        return {"status": "UNCONFIGURED"}

    # ── Container ─────────────────────────────────────────

    async def container_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        containers = []
        from ..backends.linux import run_cmd
        code, stdout, _ = await run_cmd("docker ps -a --format '{{json .}}' 2>/dev/null")
        if code == 0:
            for line in stdout.strip().split("\n"):
                if line:
                    try:
                        c = json.loads(line)
                        containers.append({
                            "id": c.get("ID", ""),
                            "name": c.get("Names", ""),
                            "image": c.get("Image", ""),
                            "state": c.get("State", ""),
                            "status": c.get("Status", ""),
                            "ports": c.get("Ports", ""),
                        })
                    except json.JSONDecodeError:
                        pass
        if filters:
            containers = apply_filters(containers, filters)
        if options:
            containers = apply_options(containers, options)
        return containers

    async def container_image_query(self, context: dict = None):
        from ..backends.linux import run_cmd
        images = []
        code, stdout, _ = await run_cmd("docker images --format '{{json .}}' 2>/dev/null")
        if code == 0:
            for line in stdout.strip().split("\n"):
                if line:
                    try:
                        img = json.loads(line)
                        images.append({
                            "id": img.get("ID", ""),
                            "repo_tags": img.get("Repository", "") + ":" + img.get("Tag", ""),
                            "size": img.get("Size", ""),
                            "created": img.get("CreatedSince", ""),
                        })
                    except json.JSONDecodeError:
                        pass
        return images

    async def container_stats(self, context: dict = None):
        from ..backends.linux import run_cmd
        stats = []
        code, stdout, _ = await run_cmd(
            "docker stats --no-stream --format '{{json .}}' 2>/dev/null"
        )
        if code == 0:
            for line in stdout.strip().split("\n"):
                if line:
                    try:
                        stats.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return stats

    async def container_metrics(self, context: dict = None):
        return await self.container_stats()

    async def container_prune(self, context: dict = None):
        from ..backends.linux import run_cmd
        await run_cmd("docker system prune -f 2>/dev/null")
        return {"pruned": True}
