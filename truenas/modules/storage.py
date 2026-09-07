"""Storage module - pool.*, pool.dataset.*, pool.snapshot.*, disk.*, zpool.*, boot.*."""
import asyncio
import logging
import time
from typing import Any, Optional

log = logging.getLogger("truenas.storage")


class StorageModule:
    def __init__(self, app):
        self.app = app

    # ── Pool ──────────────────────────────────────────────

    async def pool_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..backends.zfs import zpool_list, zpool_status
        from ..query import apply_filters, apply_options
        pools_data = await zpool_list()
        result = []
        for p in pools_data:
            status = await zpool_status(p["name"])
            topology = self._parse_topology(status)
            scan_info = self._parse_scan(status)
            result.append({
                "id": p.get("name", ""),
                "name": p.get("name", ""),
                "guid": str(p.get("guid", "")),
                "status": p.get("health", "UNKNOWN"),
                "healthy": p.get("health") == "ONLINE",
                "warning": None,
                "critical": None,
                "size": p.get("size", 0),
                "allocated": p.get("allocated", 0),
                "free": p.get("free", 0),
                "fragmentation": p.get("fragmentation", "0%"),
                "autotrim": {"value": p.get("autotrim", "off")},
                "status_code": None,
                "topology": topology,
                "scan": scan_info,
                "features": {},
                "fts": time.time(),
            })
        if filters:
            result = apply_filters(result, filters)
        if options:
            result = apply_options(result, options)
        return result

    def _parse_topology(self, status: dict) -> dict:
        topology = {"data": [], "log": [], "cache": [], "spare": [], "special": []}
        try:
            pools = status.get("pool-list", [status])
            if isinstance(pools, dict):
                pools = [pools]
            for pool in pools:
                for vdev in pool.get("vdevs", []):
                    vtype = vdev.get("vdev_tree", {}).get("type", "UNKNOWN")
                    children = vdev.get("vdev_tree", {}).get("children", [])
                    items = []
                    for child in children:
                        items.append({
                            "type": "DISK",
                            "name": child.get("name", ""),
                            "status": child.get("state", "UNKNOWN"),
                            "stats": {
                                "timestamp": 0,
                                "size": 0,
                                "timestamp2": 0,
                                "reads": 0,
                                "writes": 0,
                                "writes_done": 0,
                                "read_errors": 0,
                                "write_errors": 0,
                                "checksum_errors": 0,
                            },
                            "children": [],
                        })
                    topology.setdefault(vtype.lower(), []).append({
                        "type": vtype,
                        "is_log": vtype == "LOG",
                        "is_cache": vtype == "CACHE",
                        "children": items,
                    })
        except Exception:
            pass
        return topology

    def _parse_scan(self, status: dict) -> dict:
        try:
            pools = status.get("pool-list", [status])
            if isinstance(pools, dict):
                pools = [pools]
            for pool in pools:
                scan = pool.get("scan", {})
                return {
                    "function": scan.get("function", "none"),
                    "state": scan.get("state", "finished"),
                    "start_time": scan.get("start_time", 0),
                    "end_time": scan.get("end_time", 0),
                    "percentage": scan.get("percentage", 0),
                    "bytes_to_scan": scan.get("bytes_to_scan", 0),
                    "bytes_issued": scan.get("bytes_issued", 0),
                    "pause_time": scan.get("pause_time", 0),
                }
        except Exception:
            pass
        return {"function": "none", "state": "finished"}

    async def pool_get_disks(self, id: str = None, context: dict = None):
        from ..backends.zfs import run_cmd
        if not id:
            return []
        code, stdout, _ = await run_cmd(f"zpool status {id} -j")
        disks = []
        if code == 0:
            try:
                import json
                data = json.loads(stdout)
                self._extract_disks(data, disks)
            except Exception:
                pass
        return disks

    def _extract_disks(self, node: dict, result: list):
        if node.get("type") == "disk":
            name = node.get("name", "")
            if name:
                result.append(name)
        for child in node.get("vdevs", node.get("children", [])):
            self._extract_disks(child, result)

    async def pool_create(self, name: str = "", topology: dict = None,
                          options: dict = None, encryption: dict = None,
                          context: dict = None):
        from ..backends.zfs import zpool_create
        vdevs = []
        if topology:
            for vdev_type in ["data", "log", "cache", "spare", "special"]:
                for v in topology.get(vdev_type, []):
                    disks = []
                    for child in v.get("children", []):
                        if child.get("type") == "DISK":
                            disks.append(child.get("name", ""))
                    if disks:
                        vdevs.append({"type": v.get("type", "stripe"), "disks": disks})
        opts = {}
        if options:
            if "autotrim" in options:
                opts["autotrim"] = options["autotrim"].get("value", "off") if isinstance(options["autotrim"], dict) else options["autotrim"]
        success, msg = await zpool_create(name, vdevs, options=opts)
        if not success:
            raise Exception(f"Failed to create pool: {msg}")
        return await self.pool_query(filters=[["name", "=", name]])

    async def pool_export(self, id: str = None, confirmrerun: bool = False,
                          force: bool = False, context: dict = None):
        from ..backends.zfs import zpool_export
        if not id:
            raise Exception("Pool name required")
        success, msg = await zpool_export(id, force=force)
        if not success:
            raise Exception(f"Failed to export pool: {msg}")
        return None

    async def pool_import_pool(self, pool: str = None, guid: str = None,
                               name: str = None, context: dict = None):
        from ..backends.zfs import zpool_import
        success, msg = await zpool_import(pool_name=pool)
        if not success:
            raise Exception(f"Failed to import pool: {msg}")
        return await self.pool_query(filters=[["name", "=", pool or name]])

    async def pool_update(self, id: str = None, data: dict = None, context: dict = None):
        if data and "autotrim" in data:
            from ..backends.zfs import run_cmd
            val = data["autotrim"]
            if isinstance(val, dict):
                val = val.get("value", "off")
            await run_cmd(f"zpool set autotrim={val} {id}")
        return await self.pool_query(filters=[["name", "=", id]])

    async def pool_attach(self, id: str = None, new: dict = None,
                          force: bool = False, context: dict = None):
        return await self.pool_query(filters=[["name", "=", id]])

    async def pool_detach(self, id: str = None, label: str = "", context: dict = None):
        from ..backends.zfs import run_cmd
        if id and label:
            await run_cmd(f"zpool detach {id} {label}")
        return None

    async def pool_offline(self, id: str = None, label: str = "",
                           force: bool = False, context: dict = None):
        from ..backends.zfs import run_cmd
        if id and label:
            f = "-f" if force else ""
            await run_cmd(f"zpool offline {f} {id} {label}")
        return None

    async def pool_online(self, id: str = None, label: str = "", context: dict = None):
        from ..backends.zfs import run_cmd
        if id and label:
            await run_cmd(f"zpool online {id} {label}")
        return None

    async def pool_replace(self, id: str = None, label: str = "",
                           new: dict = None, force: bool = False, context: dict = None):
        from ..backends.zfs import run_cmd
        if id and label and new:
            await run_cmd(f"zpool replace -f {id} {label} {new.get('dev', '')}")
        return None

    async def pool_upgrade(self, id: str = None, context: dict = None):
        from ..backends.zfs import run_cmd
        if id:
            await run_cmd(f"zpool upgrade {id}")
        return None

    async def pool_scan(self, id: str = None, context: dict = None):
        from ..backends.zfs import zpool_status
        if not id:
            return {}
        return self._parse_scan(await zpool_status(id))

    async def pool_expand(self, id: str = None, context: dict = None):
        from ..backends.zfs import run_cmd
        if id:
            await run_cmd(f"zpool online -e {id}")
        return None

    async def pool_get_encrypted_disk_keys(self, id: str = None, context: dict = None):
        return []

    async def pool_import_disk(self, device: str = "", fs_type: str = "",
                               pool_name: str = "", context: dict = None):
        return {}

    # ── Pool Dataset ──────────────────────────────────────

    async def dataset_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..backends.zfs import zfs_list
        from ..query import apply_filters, apply_options
        datasets = await zfs_list()
        result = []
        for ds in datasets:
            result.append(self._format_dataset(ds))
        if filters:
            result = apply_filters(result, filters)
        if options:
            result = apply_options(result, options)
        return result

    def _format_dataset(self, ds: dict) -> dict:
        return {
            "id": ds.get("name", ""),
            "name": ds.get("name", ""),
            "type": ds.get("type", "FILESYSTEM"),
            "mountpoint": ds.get("mountpoint", ""),
            "used": ds.get("used", 0),
            "available": ds.get("available", 0),
            "usedbysnapshots": ds.get("usedbysnapshots", 0),
            "referenced": ds.get("referenced", 0),
            "compressratio": ds.get("compressratio", "1.00x"),
            "compression": ds.get("compression", "off"),
            "recordsize": ds.get("recordsize", "128K"),
            "atime": ds.get("atime", "on"),
            "xattr": ds.get("xattr", "sa"),
            "dnodesize": ds.get("dnodesize", "auto"),
            "encryption": ds.get("encryption", "off"),
            "encryption_root": ds.get("encryption_root", ""),
            "keystatus": ds.get("keystatus", ""),
            "clones": ds.get("clones", ""),
            "origin": ds.get("origin", ""),
            "special_small_blocks": ds.get("special_small_blocks", "0"),
            "volblocksize": ds.get("volblocksize", ""),
            "sync": ds.get("sync", "standard"),
            "primarycache": ds.get("primarycache", "all"),
            "secondarycache": ds.get("secondarycache", "all"),
            "encrypted": ds.get("encrypted", "off") == "on",
            "snapshot_count": 0,
            "creation": 0,
            "comments": "",
            "snapshots": [],
            "dataset": ds.get("name", ""),
            "pool": ds.get("name", "").split("/")[0] if "/" in ds.get("name", "") else ds.get("name", ""),
        }

    async def dataset_create(self, name: str = "", type: str = "FILESYSTEM",
                             properties: dict = None, encryption: dict = None,
                             context: dict = None):
        from ..backends.zfs import zfs_create
        opts = {}
        if properties:
            opts.update(properties)
        success, msg = await zfs_create(name, opts)
        if not success:
            raise Exception(f"Failed to create dataset: {msg}")
        return await self.dataset_query(filters=[["name", "=", name]])

    async def dataset_update(self, id: str = None, data: dict = None, context: dict = None):
        from ..backends.zfs import zfs_set
        if data and id:
            success, msg = await zfs_set(id, data)
            if not success:
                raise Exception(f"Failed to update dataset: {msg}")
        return await self.dataset_query(filters=[["name", "=", id]])

    async def dataset_delete(self, id: str = None, recursive: bool = True,
                             force: bool = True, context: dict = None):
        from ..backends.zfs import zfs_destroy
        if id:
            success, msg = await zfs_destroy(id, recursive=recursive, force=force)
            if not success:
                raise Exception(f"Failed to delete dataset: {msg}")
        return None

    async def dataset_child(self, id: str = None, context: dict = None):
        if not id:
            return []
        datasets = await self.dataset_query()
        return [d for d in datasets if d.get("name", "").startswith(f"{id}/")]

    async def dataset_process(self, id: str = None, context: dict = None):
        from ..backends.linux import run_cmd
        if not id:
            return []
        code, stdout, _ = await run_cmd(
            f"lsof +D $(zfs get -H -o value mountpoint {id} 2>/dev/null) 2>/dev/null"
        )
        processes = []
        if code == 0 and stdout:
            for line in stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    processes.append({
                        "pid": parts[1],
                        "name": parts[0],
                    })
        return processes

    async def dataset_rollback(self, id: str = None, context: dict = None):
        from ..backends.zfs import zfs_rollback
        if id:
            success, msg = await zfs_rollback(id)
            if not success:
                raise Exception(f"Failed to rollback: {msg}")
        return None

    async def dataset_promote(self, id: str = None, context: dict = None):
        from ..backends.zfs import run_cmd
        if id:
            await run_cmd(f"zfs promote {id}")
        return None

    async def dataset_set_quota(self, id: str = None, quota_type: str = "",
                                quota: str = "0", context: dict = None):
        from ..backends.zfs import zfs_set
        if id and quota_type:
            prop = f"{quota_type}quota"
            success, msg = await zfs_set(id, {prop: quota})
            if not success:
                raise Exception(f"Failed to set quota: {msg}")
        return None

    async def dataset_inherit_quota(self, id: str = None, quota_type: str = "",
                                    context: dict = None):
        from ..backends.zfs import zfs_set
        if id and quota_type:
            prop = f"{quota_type}quota"
            success, msg = await zfs_set(id, {prop: "none"})
            if not success:
                raise Exception(f"Failed to inherit quota: {msg}")
        return None

    async def dataset_permissions(self, path: str = "", uid: int = 0,
                                  gid: int = 0, mode: str = "",
                                  acl: dict = None, context: dict = None):
        from ..backends.linux import run_cmd
        if path:
            if uid and gid:
                await run_cmd(f"chown {uid}:{gid} '{path}'")
            if mode:
                await run_cmd(f"chmod {mode} '{path}'")
        return None

    # ── Pool Snapshot ─────────────────────────────────────

    async def snapshot_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..backends.zfs import zfs_list
        from ..query import apply_filters, apply_options
        snapshots = await zfs_list(type_filter="snapshot")
        result = []
        for ss in snapshots:
            name = ss.get("name", "")
            pool = name.split("/")[0] if "/" in name else ""
            dataset = name.split("@")[0] if "@" in name else ""
            snap_name = name.split("@")[1] if "@" in name else ""
            result.append({
                "id": name,
                "name": name,
                "dataset": dataset,
                "snapshot_name": snap_name,
                "pool": pool,
                "referenced": ss.get("referenced", 0),
                "used": ss.get("used", 0),
                "available": ss.get("available", 0),
                "mountpoint": ss.get("mountpoint", ""),
                "clones": ss.get("clones", ""),
                "encryption": ss.get("encryption", ""),
                "keystatus": ss.get("keystatus", ""),
                "type": "SNAPSHOT",
                "keep_since": None,
                "visible": True,
                "nation": False,
                "alerts": [],
                "holds": 0,
                "refs": 0,
                "creation": 0,
            })
        if filters:
            result = apply_filters(result, filters)
        if options:
            result = apply_options(result, options)
        return result

    async def snapshot_create(self, dataset: str = "", name: str = "",
                              recursive: bool = False, properties: dict = None,
                              context: dict = None):
        from ..backends.zfs import zfs_snapshot
        if dataset and name:
            success, msg = await zfs_snapshot(dataset, name, recursive=recursive, properties=properties)
            if not success:
                raise Exception(f"Failed to create snapshot: {msg}")
        snap_name = f"{dataset}@{name}"
        return await self.snapshot_query(filters=[["name", "=", snap_name]])

    async def snapshot_delete(self, id: str = None, defer: bool = False,
                              context: dict = None):
        from ..backends.zfs import zfs_destroy
        if id:
            success, msg = await zfs_destroy(id, recursive=False, force=True)
            if not success:
                raise Exception(f"Failed to delete snapshot: {msg}")
        return None

    async def snapshot_clone(self, id: str = "", dataset_dst: str = "",
                             dataset_src: str = "", recursive: bool = True,
                             properties: dict = None, context: dict = None):
        from ..backends.zfs import zfs_clone
        if id and dataset_dst:
            success, msg = await zfs_clone(id, dataset_dst, properties=properties)
            if not success:
                raise Exception(f"Failed to clone snapshot: {msg}")
        return None

    async def snapshot_rollback(self, id: str = "", force: bool = True,
                                context: dict = None):
        from ..backends.zfs import zfs_rollback
        if id:
            success, msg = await zfs_rollback(id, force=force)
            if not success:
                raise Exception(f"Failed to rollback snapshot: {msg}")
        return None

    async def snapshot_hold(self, tag: str = "", id: str = "",
                            recursive: bool = False, context: dict = None):
        from ..backends.zfs import zfs_hold
        if tag and id:
            success, msg = await zfs_hold(tag, id)
            if not success:
                raise Exception(f"Failed to hold snapshot: {msg}")
        return None

    async def snapshot_release(self, tag: str = "", id: str = "",
                               recursive: bool = False, context: dict = None):
        from ..backends.zfs import zfs_release
        if tag and id:
            success, msg = await zfs_release(tag, id)
            if not success:
                raise Exception(f"Failed to release snapshot: {msg}")
        return None

    # ── Snapshot Task ─────────────────────────────────────

    async def snapshottask_query(self, filters: list = None, options: dict = None, context: dict = None):
        return self.app.config_store.get("snapshot_tasks", [])

    async def snapshottask_create(self, data: dict = None, context: dict = None):
        tasks = await self.snapshottask_query()
        if data:
            data["id"] = len(tasks) + 1
            tasks.append(data)
            await self.app.config_store.set("snapshot_tasks", tasks)
        return data or {}

    async def snapshottask_update(self, id: int = None, data: dict = None, context: dict = None):
        tasks = await self.snapshottask_query()
        for t in tasks:
            if t.get("id") == id:
                t.update(data or {})
                await self.app.config_store.set("snapshot_tasks", tasks)
                return t
        return {}

    async def snapshottask_delete(self, id: int = None, context: dict = None):
        tasks = await self.snapshottask_query()
        tasks = [t for t in tasks if t.get("id") != id]
        await self.app.config_store.set("snapshot_tasks", tasks)
        return None

    async def snapshottask_retention_validate(self, data: dict = None, context: dict = None):
        return True

    # ── Scrub ─────────────────────────────────────────────

    async def scrub_query(self, filters: list = None, options: dict = None, context: dict = None):
        return self.app.config_store.get("scrub_tasks", [])

    async def scrub_create(self, data: dict = None, context: dict = None):
        tasks = await self.scrub_query()
        if data:
            data["id"] = len(tasks) + 1
            tasks.append(data)
            await self.app.config_store.set("scrub_tasks", tasks)
        return data or {}

    async def scrub_update(self, id: int = None, data: dict = None, context: dict = None):
        tasks = await self.scrub_query()
        for t in tasks:
            if t.get("id") == id:
                t.update(data or {})
                await self.app.config_store.set("scrub_tasks", tasks)
                return t
        return {}

    async def scrub_delete(self, id: int = None, context: dict = None):
        tasks = await self.scrub_query()
        tasks = [t for t in tasks if t.get("id") != id]
        await self.app.config_store.set("scrub_tasks", tasks)
        return None

    async def scrub_run(self, id: str = None, context: dict = None):
        from ..backends.zfs import zpool_scrub
        if id:
            success, msg = await zpool_scrub(id, start=True)
            if not success:
                raise Exception(f"Failed to start scrub: {msg}")
        return None

    # ── Disk ──────────────────────────────────────────────

    async def disk_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..backends.zfs import disk_list
        from ..query import apply_filters, apply_options
        disks = await disk_list()
        if filters:
            disks = apply_filters(disks, filters)
        if options:
            disks = apply_options(disks, options)
        return disks

    async def disk_temperature_agg(self, filters: list = None, options: dict = None, context: dict = None):
        return {}

    async def disk_update(self, name: str = None, data: dict = None, context: dict = None):
        return {}

    # ── Boot ──────────────────────────────────────────────

    async def boot_query(self, context: dict = None):
        from ..backends.zfs import boot_get_state
        return [await boot_get_state()]

    async def boot_pool_query(self, context: dict = None):
        return await self.pool_query(filters=[["name", "=", "boot-pool"]])

    async def boot_attach(self, device: str = "", options: dict = None, context: dict = None):
        from ..backends.zfs import run_cmd
        if device:
            await run_cmd(f"zpool attach boot-pool {device}")
        return None

    async def boot_detach(self, device: str = "", context: dict = None):
        from ..backends.zfs import run_cmd
        if device:
            await run_cmd(f"zpool detach boot-pool {device}")
        return None

    async def boot_replace(self, device: str = "", context: dict = None):
        from ..backends.zfs import run_cmd
        if device:
            await run_cmd(f"zpool replace boot-pool {device}")
        return None

    async def boot_online(self, devname: str = "", context: dict = None):
        from ..backends.zfs import run_cmd
        if devname:
            await run_cmd(f"zpool online boot-pool {devname}")
        return None

    async def boot_offline(self, devname: str = "", context: dict = None):
        from ..backends.zfs import run_cmd
        if devname:
            await run_cmd(f"zpool offline boot-pool {devname}")
        return None

    # ── Resilver ──────────────────────────────────────────

    async def resilver_config(self, context: dict = None):
        return self.app.config_store.get("resilver", {"begin": 2, "end": 8})

    async def resilver_update(self, data: dict = None, context: dict = None):
        if data:
            await self.app.config_store.set("resilver", data)
        return await self.resilver_config()

    # ── System Dataset ────────────────────────────────────

    async def systemdataset_config(self, context: dict = None):
        return self.app.config_store.get("systemdataset", {
            "pool": "boot-pool",
            "ds_name": "system",
            "dataset": "boot-pool/system",
            "syslog": True,
            "heartbeat": False,
            "path": "/var/db/system",
        })

    async def systemdataset_update(self, data: dict = None, context: dict = None):
        if data:
            await self.app.config_store.set("systemdataset", data)
        return await self.systemdataset_config()
