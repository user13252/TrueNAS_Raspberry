"""ZFS backend - wraps zfs/zpool commands for storage management."""
import asyncio
import json
import os
from typing import Any, Optional

from .linux import run_cmd, run_cmd_lines, _human_size


async def zpool_list() -> list[dict]:
    pools = []
    code, stdout, _ = await run_cmd(
        "zpool list -J -o name,size,allocated,free,capacity,health,guid,"
        "fragmentation,autoexpand,autotrim,ashift,version,feature@allocation_classes,"
        "feature@async_destroy,feature@bookmarks,feature@embedded_data,"
        "feature@enabled_tsns,feature@empty_bpobj,feature@extensible_dataset,"
        "feature@filesystem_limits,feature@hole_birth,feature@large_blocks,"
        "feature@lz4_compress,feature@metadata_reserve,feature@multi_vdev_panzilla,"
        "feature@obsolete_counts,feature@redacted_send,feature@resilver_defer,"
        "feature@spacemap_histogram,feature@spacemap_v2,feature@tournament_tree,"
        "feature@userobj_accounting,zones"
    )
    if code == 0:
        try:
            data = json.loads(stdout)
            for p in data:
                pools.append({
                    "name": p.get("name", ""),
                    "size": int(p.get("size", 0)),
                    "allocated": int(p.get("allocated", 0)),
                    "free": int(p.get("free", 0)),
                    "capacity": p.get("capacity", "0%"),
                    "health": p.get("health", "UNKNOWN"),
                    "guid": p.get("guid", ""),
                    "fragmentation": p.get("fragmentation", "0%"),
                    "autoexpand": p.get("autoexpand", "off"),
                    "autotrim": p.get("autotrim", "off"),
                    "ashift": p.get("ashift", "12"),
                })
        except (json.JSONDecodeError, KeyError):
            pass
    return pools


async def zpool_status(pool_name: str = None) -> dict:
    cmd = "zpool status -J"
    if pool_name:
        cmd += f" {pool_name}"
    code, stdout, _ = await run_cmd(cmd)
    if code == 0:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            pass
    return {}


async def zpool_import(pool_name: str = None, cache_file: str = None) -> tuple[bool, str]:
    cmd = "zpool import -f -a -o cachefile=none"
    if pool_name:
        cmd = f"zpool import -f {pool_name} -o cachefile=none"
    code, stdout, stderr = await run_cmd(cmd, timeout=120)
    return code == 0, stderr if code != 0 else stdout


async def zpool_export(pool_name: str, force: bool = False) -> tuple[bool, str]:
    cmd = f"zpool export {'-f ' if force else ''}{pool_name}"
    code, stdout, stderr = await run_cmd(cmd, timeout=120)
    return code == 0, stderr if code != 0 else stdout


async def zpool_create(
    name: str,
    vdevs: list[dict],
    options: dict = None,
    mountpoint: str = None,
) -> tuple[bool, str]:
    cmd_parts = ["zpool", "create", "-f"]

    if options:
        for k, v in options.items():
            cmd_parts.extend(["-o", f"{k}={v}"])

    if mountpoint:
        cmd_parts.extend(["-o", f"mountpoint={mountpoint}"])

    cmd_parts.append(name)

    for vdev in vdevs:
        vtype = vdev.get("type", "stripe")
        if vtype == "mirror":
            cmd_parts.append("mirror")
            for d in vdev.get("disks", []):
                cmd_parts.append(d)
        elif vtype == "raidz":
            cmd_parts.append(vtype)
            for d in vdev.get("disks", []):
                cmd_parts.append(d)
        elif vtype == "raidz2":
            cmd_parts.append("raidz2")
            for d in vdev.get("disks", []):
                cmd_parts.append(d)
        elif vtype == "raidz3":
            cmd_parts.append("raidz3")
            for d in vdev.get("disks", []):
                cmd_parts.append(d)
        else:
            for d in vdev.get("disks", []):
                cmd_parts.append(d)

    cmd = " ".join(cmd_parts)
    code, stdout, stderr = await run_cmd(cmd, timeout=300)
    return code == 0, stderr if code != 0 else stdout


async def zpool_destroy(pool_name: str) -> tuple[bool, str]:
    code, stdout, stderr = await run_cmd(
        f"zpool destroy {pool_name}", timeout=120
    )
    return code == 0, stderr if code != 0 else stdout


async def zfs_list(
    pool: str = None,
    type_filter: str = None,
    properties: list[str] = None,
) -> list[dict]:
    props = "name,used,available,usedbysnapshots,referenced,mountpoint,type,encryption,encryptionroot,keystatus,compressratio,compression,recordsize,atime,xattr,dnodesize,utf8only,normalizetoformd,special_small_blocks,volblocksize,sync,doblake2,primarycache,secondarycache,l2cache,encrypted,clones,origin,reservation,refreservation"
    cmd = f"zfs list -J -o {props}"
    if pool:
        cmd += f" {pool}"
    if type_filter:
        cmd += f" -t {type_filter}"

    code, stdout, _ = await run_cmd(cmd)
    if code == 0:
        try:
            data = json.loads(stdout)
            return data if isinstance(data, list) else data.get("datasets", [])
        except json.JSONDecodeError:
            pass
    return []


async def zfs_get(
    dataset: str, property: str
) -> Optional[str]:
    code, stdout, _ = await run_cmd(
        f'zfs get -Hp -o value {property} {dataset}'
    )
    if code == 0:
        return stdout.strip()
    return None


async def zfs_set(dataset: str, properties: dict) -> tuple[bool, str]:
    props = " ".join(f"{k}={v}" for k, v in properties.items())
    code, stdout, stderr = await run_cmd(
        f"zfs set {props} {dataset}"
    )
    return code == 0, stderr if code != 0 else stdout


async def zfs_create(dataset: str, options: dict = None) -> tuple[bool, str]:
    cmd_parts = ["zfs", "create"]
    if options:
        for k, v in options.items():
            cmd_parts.extend(["-o", f"{k}={v}"])
    cmd_parts.append(dataset)
    cmd = " ".join(cmd_parts)
    code, stdout, stderr = await run_cmd(cmd, timeout=60)
    return code == 0, stderr if code != 0 else stdout


async def zfs_destroy(dataset: str, recursive: bool = True, force: bool = True) -> tuple[bool, str]:
    flags = "-r" if recursive else ""
    if force:
        flags += " -f"
    code, stdout, stderr = await run_cmd(
        f"zfs destroy {flags} {dataset}", timeout=120
    )
    return code == 0, stderr if code != 0 else stdout


async def zfs_snapshot(
    dataset: str, snapshot_name: str, recursive: bool = False, properties: dict = None
) -> tuple[bool, str]:
    cmd_parts = ["zfs", "snapshot"]
    if recursive:
        cmd_parts.append("-r")
    if properties:
        for k, v in properties.items():
            cmd_parts.extend(["-o", f"{k}={v}"])
    cmd_parts.append(f"{dataset}@{snapshot_name}")
    cmd = " ".join(cmd_parts)
    code, stdout, stderr = await run_cmd(cmd, timeout=120)
    return code == 0, stderr if code != 0 else stdout


async def zfs_clone(
    snapshot: str, target: str, options: dict = None
) -> tuple[bool, str]:
    cmd_parts = ["zfs", "clone"]
    if options:
        for k, v in options.items():
            cmd_parts.extend(["-o", f"{k}={v}"])
    cmd_parts.extend([snapshot, target])
    cmd = " ".join(cmd_parts)
    code, stdout, stderr = await run_cmd(cmd, timeout=60)
    return code == 0, stderr if code != 0 else stdout


async def zfs_rollback(snapshot: str, force: bool = True) -> tuple[bool, str]:
    flag = "-r" if force else ""
    code, stdout, stderr = await run_cmd(
        f"zfs rollback {flag} {snapshot}", timeout=120
    )
    return code == 0, stderr if code != 0 else stdout


async def zfs_hold(tag: str, snapshot: str) -> tuple[bool, str]:
    code, stdout, stderr = await run_cmd(
        f"zfs hold {tag} {snapshot}"
    )
    return code == 0, stderr if code != 0 else stdout


async def zfs_release(tag: str, snapshot: str) -> tuple[bool, str]:
    code, stdout, stderr = await run_cmd(
        f"zfs release {tag} {snapshot}"
    )
    return code == 0, stderr if code != 0 else stdout


async def zpool_scrub(pool: str, start: bool = True) -> tuple[bool, str]:
    action = "start" if start else "stop"
    code, stdout, stderr = await run_cmd(
        f"zpool {action} {pool}", timeout=300
    )
    return code == 0, stderr if code != 0 else stdout


async def disk_list() -> list[dict]:
    disks = []
    code, stdout, _ = await run_cmd(
        "lsblk -Jb -o NAME,SIZE,TYPE,FSTYPE,SERIAL,MODEL,ROTA,RO,TRAN,HCTL,PATH"
    )
    if code == 0:
        try:
            data = json.loads(stdout)
            for dev in data.get("blockdevices", []):
                if dev.get("type") == "disk":
                    disks.append({
                        "name": dev["name"],
                        "path": dev.get("path", f"/dev/{dev['name']}"),
                        "size": int(dev.get("size", 0) or 0),
                        "serial": dev.get("serial", ""),
                        "model": (dev.get("model") or "").strip(),
                        "rotation": dev.get("rota", "1") == "1",
                        "transfer": dev.get("tran", ""),
                        "hctl": dev.get("hctl", ""),
                        "type": dev.get("type", "UNKNOWN"),
                        "zfs_guid": "",
                        "bus": dev.get("tran", "UNKNOWN"),
                        "tident": "",
                        "description": "",
                        "cooling": "",
                        "power_on_hours": 0,
                        "temperature": None,
                        "size_human": _human_size(int(dev.get("size", 0) or 0)),
                    })
        except json.JSONDecodeError:
            pass
    return disks


async def boot_get_state() -> dict:
    code, stdout, _ = await run_cmd("zpool list -J boot-pool")
    if code == 0:
        try:
            data = json.loads(stdout)
            if data:
                pool = data[0]
                return {
                    "state": "LOADED",
                    "pool": "boot-pool",
                    "version": pool.get("version", ""),
                    "status": "OK",
                    "action": "",
                    "status_code": "",
                    "scan": None,
                }
        except (json.JSONDecodeError, IndexError):
            pass
    return {"state": "NONE", "pool": "", "version": "", "status": "UNKNOWN"}
