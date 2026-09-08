"""Linux system backend - executes OS-level commands."""
import asyncio
import os
import platform
import socket
import subprocess
import json
from pathlib import Path
from typing import Optional
from datetime import datetime


async def run_cmd(cmd: str, timeout: float = 30) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return (
            proc.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "Command timed out"


async def run_cmd_lines(cmd: str, timeout: float = 30) -> list[str]:
    code, stdout, _ = await run_cmd(cmd, timeout)
    if code != 0:
        return []
    return [line for line in stdout.strip().split("\n") if line]


def get_hostname() -> str:
    return socket.gethostname()


def get_system_info() -> dict:
    try:
        with open("/proc/cpuinfo") as f:
            lines = f.readlines()
        model = ""
        for line in lines:
            if "Model" in line or "model name" in line:
                model = line.split(":", 1)[1].strip()
                break
    except Exception:
        model = platform.machine()

    try:
        with open("/proc/meminfo") as f:
            meminfo = f.readlines()
        total_mem = 0
        for line in meminfo:
            if "MemTotal" in line:
                total_mem = int(line.split()[1]) * 1024
                break
    except Exception:
        total_mem = 0

    try:
        with open("/proc/loadavg") as f:
            loadavg = [float(x) for x in f.read().split()[:3]]
    except Exception:
        loadavg = [0.0, 0.0, 0.0]

    now = datetime.now().timestamp()
    return {
        "hostname": get_hostname(),
        "system_product": model,
        "system_product_version": "",
        "system_serial": "",
        "platform": "trueNAS",
        "model": model,
        "system_manufacturer": "Raspberry Pi",
        "system_time": {
            "system_time": now,
            "boot_time": now,
        },
        "version": "RPi-24.10.0",
        "build": "truenas-rpi",
        "buildtime": now,
        "datetime": now,
        "boottime": now,
        "type": "SCALE",
        "status": {"status": "LOADED"},
        "license": {"license": "Unlicensed", "expired": False},
        "system_machine_id": _get_machine_id(),
        "timezone": "UTC",
        "language": "en",
        "cpu_arch": platform.machine(),
        "cores": os.cpu_count() or 1,
        "physical_cores": os.cpu_count() or 1,
        "physical_memory": total_mem,
        "physmem": total_mem,
        "ecc_memory": False,
        "loadavg": loadavg,
        "uptime": _get_uptime(),
        "uptime_seconds": _get_uptime(),
        "remote_info": None,
        "system_product": model,
    }


def _get_machine_id() -> str:
    try:
        with open("/etc/machine-id") as f:
            return f.read().strip()
    except Exception:
        return "00000000000000000000000000000000"


def _get_uptime() -> float:
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0


async def get_disk_info() -> list[dict]:
    disks = []
    code, stdout, _ = await run_cmd("lsblk -Jb -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL,SERIAL")
    if code == 0:
        try:
            data = json.loads(stdout)
            for dev in data.get("blockdevices", []):
                disks.append({
                    "name": dev["name"],
                    "size": int(dev.get("size", 0) or 0),
                    "type": dev.get("type", "disk"),
                    "fstype": dev.get("fstype"),
                    "mountpoint": dev.get("mountpoint"),
                    "model": dev.get("model", ""),
                    "serial": dev.get("serial", ""),
                    "hctl": "",
                    "size_human": _human_size(int(dev.get("size", 0) or 0)),
                })
        except json.JSONDecodeError:
            pass
    return disks


async def get_network_interfaces() -> list[dict]:
    interfaces = []
    try:
        import netifaces
        for iface in netifaces.interfaces():
            if iface == "lo":
                continue
            addrs = netifaces.ifaddresses(iface)
            ipv4 = addrs.get(netifaces.AF_INET, [])
            ipv6 = addrs.get(netifaces.AF_INET6, [])
            mac = addrs.get(netifaces.AF_LINK, [{}])
            flags = 0
            try:
                with open(f"/sys/class/net/{iface}/flags") as f:
                    flags = int(f.read().strip(), 16)
            except Exception:
                pass

            interfaces.append({
                "id": iface,
                "name": iface,
                "type": "PHYSICAL",
                "addresses": [
                    {"address": a.get("addr", ""), "netmask": a.get("netmask", ""), "type": "INHERIT"}
                    for a in ipv4
                ] + [
                    {"address": a.get("addr", "").split("%")[0], "netmask": a.get("netmask", ""), "type": "INHERIT"}
                    for a in ipv6
                ],
                "status": {
                    "carrier": bool(flags & 1),
                    "speed": _get_link_speed(iface),
                },
                "mtu": _get_mtu(iface),
                "mac_address": mac[0].get("addr", "") if mac else "",
                "aliases": [],
                "vlan": [],
                "lagg": {},
                "bridge": {},
            })
    except ImportError:
        code, stdout, _ = await run_cmd("ip -j addr show")
        if code == 0:
            try:
                data = json.loads(stdout)
                for iface in data:
                    if iface.get("ifindex", 0) == 1:
                        continue
                    interfaces.append({
                        "id": iface.get("ifname", ""),
                        "name": iface.get("ifname", ""),
                        "type": "PHYSICAL",
                        "addresses": [],
                        "status": {"carrier": True, "speed": 0},
                        "mtu": iface.get("mtu", 1500),
                        "mac_address": iface.get("address", ""),
                        "aliases": [],
                        "vlan": [],
                        "lagg": {},
                        "bridge": {},
                    })
            except json.JSONDecodeError:
                pass
    return interfaces


def _get_link_speed(iface: str) -> int:
    try:
        with open(f"/sys/class/net/{iface}/speed") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def _get_mtu(iface: str) -> int:
    try:
        with open(f"/sys/class/net/{iface}/mtu") as f:
            return int(f.read().strip())
    except Exception:
        return 1500


def _human_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
