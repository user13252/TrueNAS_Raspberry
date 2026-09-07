"""Filesystem module - filesystem.*, device.*."""
import asyncio
import json
import logging
import os
import stat
from pathlib import Path
from typing import Any, Optional

try:
    import pwd
    import grp
    HAS_PWD = True
except ImportError:
    HAS_PWD = False

log = logging.getLogger("truenas.filesystem")


class FilesystemModule:
    def __init__(self, app):
        self.app = app

    async def listdir(self, path: str = "", filters: list = None,
                      options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        if not path:
            path = "/"
        entries = []
        try:
            p = Path(path)
            if not p.exists():
                return []
            for item in p.iterdir():
                try:
                    st = item.stat(follow_symlinks=False)
                    entry = {
                        "name": item.name,
                        "path": str(item),
                        "type": self._get_type(st),
                        "size": st.st_size,
                        "atime": st.st_atime,
                        "mtime": st.st_mtime,
                        "ctime": st.st_ctime,
                        "mode": stat.S_IMODE(st.st_mode),
                        "uid": st.st_uid,
                        "gid": st.st_gid,
                        "acl": None,
                    }
                    try:
                        if HAS_PWD:
                            entry["user"] = pwd.getpwuid(st.st_uid).pw_name
                        else:
                            entry["user"] = str(st.st_uid)
                    except KeyError:
                        entry["user"] = str(st.st_uid)
                    try:
                        if HAS_PWD:
                            entry["group"] = grp.getgrgid(st.st_gid).gr_name
                        else:
                            entry["group"] = str(st.st_gid)
                    except KeyError:
                        entry["group"] = str(st.st_gid)
                    entries.append(entry)
                except (PermissionError, OSError):
                    entries.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "DIRECTORY",
                        "size": 0,
                        "error": "Permission denied",
                    })
        except PermissionError:
            return []
        if filters:
            entries = apply_filters(entries, filters)
        if options:
            entries = apply_options(entries, options)
        return entries

    def _get_type(self, st) -> str:
        mode = st.st_mode
        if stat.S_ISDIR(mode):
            return "DIRECTORY"
        elif stat.S_ISREG(mode):
            return "FILE"
        elif stat.S_ISLNK(mode):
            return "SYMLINK"
        elif stat.S_ISBLK(mode):
            return "BLOCK"
        elif stat.S_ISCHR(mode):
            return "CHARACTER"
        elif stat.S_ISFIFO(mode):
            return "FIFO"
        elif stat.S_ISSOCK(mode):
            return "SOCKET"
        return "UNKNOWN"

    async def stat(self, path: str = "", context: dict = None) -> dict:
        if not path:
            return {}
        try:
            st = os.stat(path)
            return {
                "name": os.path.basename(path),
                "path": path,
                "type": self._get_type(st),
                "size": st.st_size,
                "atime": st.st_atime,
                "mtime": st.st_mtime,
                "ctime": st.st_ctime,
                "mode": stat.S_IMODE(st.st_mode),
                "uid": st.st_uid,
                "gid": st.st_gid,
            }
        except Exception:
            return {}

    async def statfs(self, path: str = "", context: dict = None) -> dict:
        if not path:
            return {}
        try:
            s = os.statvfs(path)
            return {
                "f_bsize": s.f_bsize,
                "f_frsize": s.f_frsize,
                "f_blocks": s.f_blocks,
                "f_bfree": s.f_bfree,
                "f_bavail": s.f_bavail,
                "f_files": s.f_files,
                "f_ffree": s.f_ffree,
                "f_favail": s.f_favail,
                "f_namemax": s.f_namemax,
            }
        except Exception:
            return {}

    async def getacl(self, path: str = "", context: dict = None) -> dict:
        if not path:
            return {}
        from ..backends.linux import run_cmd
        code, stdout, _ = await run_cmd(f"getfacl -p '{path}' 2>/dev/null")
        acl = {"acl": [], "nfs41_acl": []}
        if code == 0:
            for line in stdout.strip().split("\n"):
                if line.startswith("user:") or line.startswith("group:") or line.startswith("other:"):
                    acl["acl"].append({"tag": line.split(":")[0], "content": line})
        return acl

    async def setacl(self, path: str = "", dacl: dict = None, acl: dict = None,
                     mode: str = None, context: dict = None):
        from ..backends.linux import run_cmd
        if path and dacl:
            entries = dacl.get("acl", [])
            for entry in entries:
                tag = entry.get("tag", "")
                who = entry.get("who", "")
                perms = entry.get("perms", {})
                perm_str = ""
                if perms.get("READ"):
                    perm_str += "r"
                if perms.get("WRITE"):
                    perm_str += "w"
                if perms.get("EXECUTE"):
                    perm_str += "x"
                if tag == "USER" and who:
                    await run_cmd(f"setfacl -m u:{who}:{perm_str} '{path}'")
                elif tag == "GROUP" and who:
                    await run_cmd(f"setfacl -m g:{who}:{perm_str} '{path}'")
        if path and mode:
            await run_cmd(f"chmod {mode} '{path}'")
        return None

    async def setperm(self, path: str = "", mode: str = "", context: dict = None):
        from ..backends.linux import run_cmd
        if path and mode:
            await run_cmd(f"chmod {mode} '{path}'")
        return None

    async def put(self, path: str = "", content: bytes = b"",
                  mode: str = "644", context: dict = None):
        try:
            with open(path, "wb") as f:
                f.write(content)
            if mode:
                os.chmod(path, int(mode, 8))
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def file_tail_follow(self, path: str = "", offset: int = 0,
                               limit: int = 0, context: dict = None):
        if not path or not os.path.exists(path):
            return []
        try:
            with open(path) as f:
                if offset:
                    f.seek(offset)
                lines = f.readlines()
                if limit:
                    lines = lines[:limit]
                return [{"line": l.rstrip()} for l in lines]
        except Exception:
            return []

    async def mkdir(self, path: str = "", mode: str = "755", context: dict = None):
        if path:
            os.makedirs(path, exist_ok=True)
            if mode:
                os.chmod(path, int(mode, 8))
        return None

    async def unlink(self, path: str = "", context: dict = None):
        if path and os.path.exists(path):
            os.remove(path)
        return None

    async def rename(self, path: str = "", new_path: str = "", context: dict = None):
        if path and new_path:
            os.rename(path, new_path)
        return None

    async def acltemplate_query(self, path: str = "", recursive: bool = False,
                                context: dict = None):
        return []

    async def acl_is_trivial(self, path: str = "", context: dict = None) -> bool:
        if path:
            from ..backends.linux import run_cmd
            code, stdout, _ = await run_cmd(f"getfacl -p '{path}' 2>/dev/null")
            if code == 0 and "default:" in stdout:
                return False
        return True

    # ── Device ────────────────────────────────────────────

    async def device_get_info(self, dtype: str = "", context: dict = None) -> dict:
        from ..backends.linux import run_cmd
        if dtype == "GPU":
            code, stdout, _ = await run_cmd("lspci | grep -i vga 2>/dev/null")
            gpus = []
            if code == 0:
                for line in stdout.strip().split("\n"):
                    if line:
                        gpus.append({"description": line.strip(), "drivers": [], "vendor": ""})
            return {"devices": gpus}
        return {"devices": []}
