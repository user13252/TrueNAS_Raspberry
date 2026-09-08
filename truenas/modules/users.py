"""Users/Groups module - user.*, group.*, privilege.*."""
import asyncio
import json
import logging
import os
import secrets
import time
from typing import Any, Optional

log = logging.getLogger("truenas.users")


class UserGroupModule:
    def __init__(self, app):
        self.app = app

    # ── Users ─────────────────────────────────────────────

    async def user_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        users = []
        for username, data in self.app.auth_manager._users.items():
            users.append({
                "id": data.get("id", 0),
                "username": username,
                "full_name": data.get("full_name", ""),
                "builtin": data.get("builtin", False),
                "home": data.get("home", f"/home/{username}"),
                "shell": data.get("shell", "/bin/bash"),
                "uid": data.get("uid", 0),
                "group": {"id": data.get("groupid", 0)},
                "group_create": data.get("group_create", False),
                "smb": data.get("smb", False),
                "locked": data.get("locked", False),
                "email": data.get("email", ""),
                "sshpubkey": data.get("sshpubkey", ""),
                "password_disabled": data.get("password_disabled", False),
                "immutable": data.get("immutable", False),
                "microsoft_account": data.get("microsoft_account", False),
                "last_login": data.get("last_login"),
                "id_type_both": False,
                "local": True,
                "ntlm": False,
                "roles": data.get("roles", []),
                "password_last_change": data.get("password_last_change", 0),
                "authorized_keys": data.get("authorized_keys", ""),
                "twofactor_auth_enabled": False,
                "group_ids": [data.get("groupid", 1)],
                "created_at": data.get("created_at", int(time.time())),
            })
        if filters:
            users = apply_filters(users, filters)
        if options:
            users = apply_options(users, options)
        return users

    async def user_create(self, data: dict = None, context: dict = None):
        if not data:
            return {}
        username = data.get("username", "")
        password = data.get("password", "")
        fullname = data.get("full_name", username)
        if not username:
            raise Exception("Username is required")

        if password:
            self.app.auth_manager.setup_local_admin(username, password, fullname)
        else:
            self.app.auth_manager._users[username] = {
                "password_hash": "",
                "full_name": fullname,
                "roles": data.get("roles", []),
                "builtin": False,
                "id": max(
                    (u.get("id", 0) for u in self.app.auth_manager._users.values()), default=0
                ) + 1,
                "groupid": data.get("group", {}).get("id", 1) if isinstance(data.get("group"), dict) else data.get("group_create", 1),
                "uid": data.get("uid", 1000 + len(self.app.auth_manager._users)),
                "shell": data.get("shell", "/bin/bash"),
                "home": data.get("home", f"/home/{username}"),
                "email": data.get("email", ""),
                "sshpubkey": data.get("sshpubkey", ""),
                "locked": False,
                "smb": data.get("smb", True),
                "password_disabled": data.get("password_disabled", False),
                "immutable": False,
                "microsoft_account": False,
                "last_login": None,
                "created_at": int(time.time()),
                "password_last_change": int(time.time()),
                "authorized_keys": data.get("authorized_keys", ""),
                "group_create": data.get("group_create", False),
            }
            self.app.auth_manager._save_users()

        if data.get("home_create") and data.get("home"):
            os.makedirs(data["home"], exist_ok=True)

        users = await self.user_query(filters=[["username", "=", username]])
        return users[0] if users else {}

    async def user_update(self, id: int = None, data: dict = None, context: dict = None):
        if not data:
            return {}
        for uname, udata in self.app.auth_manager._users.items():
            if udata.get("id") == id:
                if "full_name" in data:
                    udata["full_name"] = data["full_name"]
                if "email" in data:
                    udata["email"] = data["email"]
                if "shell" in data:
                    udata["shell"] = data["shell"]
                if "locked" in data:
                    udata["locked"] = data["locked"]
                if "smb" in data:
                    udata["smb"] = data["smb"]
                if "sshpubkey" in data:
                    udata["sshpubkey"] = data["sshpubkey"]
                if "roles" in data:
                    udata["roles"] = data["roles"]
                if "password" in data and data["password"]:
                    import bcrypt
                    udata["password_hash"] = bcrypt.hashpw(
                        data["password"].encode(), bcrypt.gensalt()
                    ).decode()
                    udata["password_last_change"] = int(time.time())
                self.app.auth_manager._save_users()
                break
        return await self.user_query(filters=[["id", "=", id]])

    async def user_delete(self, id: int = None, data: dict = None, context: dict = None):
        for uname, udata in list(self.app.auth_manager._users.items()):
            if udata.get("id") == id and not udata.get("builtin", False):
                del self.app.auth_manager._users[uname]
                self.app.auth_manager._save_users()
                break
        return None

    async def user_get_user_obj(self, data: dict = None, context: dict = None):
        if data and "username" in data:
            users = await self.user_query(filters=[["username", "=", data["username"]]])
            return users[0] if users else {}
        return {}

    async def user_set_password(self, data: dict = None, context: dict = None):
        if data:
            username = data.get("username", "")
            password = data.get("password", "")
            if username and password:
                import bcrypt
                if username in self.app.auth_manager._users:
                    self.app.auth_manager._users[username]["password_hash"] = bcrypt.hashpw(
                        password.encode(), bcrypt.gensalt()
                    ).decode()
                    self.app.auth_manager._users[username]["password_last_change"] = int(time.time())
                    self.app.auth_manager._save_users()
        return None

    async def user_has_local_administrator_set_up(self, context: dict = None):
        for data in self.app.auth_manager._users.values():
            if data.get("builtin") and data.get("roles"):
                return True
        return False

    async def user_setup_local_administrator(self, data: dict = None, context: dict = None):
        if data:
            username = data.get("username", "admin")
            password = data.get("password", "")
            fullname = data.get("full_name", "Administrator")
            if password:
                self.app.auth_manager.setup_local_admin(username, password, fullname)
        return True

    async def user_next_uid(self, context: dict = None) -> int:
        return max(
            (u.get("uid", 0) for u in self.app.auth_manager._users.values()), default=999
        ) + 1

    # ── Groups ────────────────────────────────────────────

    async def group_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        groups = []
        seen_gids = set()
        for username, data in self.app.auth_manager._users.items():
            gid = data.get("groupid", 0)
            if gid in seen_gids:
                continue
            seen_gids.add(gid)
            members = [
                u for u, d in self.app.auth_manager._users.items()
                if d.get("groupid") == gid
            ]
            groups.append({
                "id": gid,
                "gid": gid,
                "name": data.get("full_name", f"group_{gid}"),
                "builtin": data.get("builtin", False),
                "smb": data.get("smb", False),
                "users": [{"id": d.get("id", 0)} for u, d in self.app.auth_manager._users.items() if d.get("groupid") == gid],
                "local": True,
                "id_type_both": False,
                "ntlm": False,
                "created_at": data.get("created_at", int(time.time())),
            })
        if not groups:
            groups.append({
                "id": 1, "gid": 1, "name": "root",
                "builtin": True, "smb": True, "users": [], "local": True,
                "id_type_both": False, "ntlm": False, "created_at": 0,
            })
        if filters:
            groups = apply_filters(groups, filters)
        if options:
            groups = apply_options(groups, options)
        return groups

    async def group_create(self, data: dict = None, context: dict = None):
        return data or {}

    async def group_update(self, id: int = None, data: dict = None, context: dict = None):
        return data or {}

    async def group_delete(self, id: int = None, context: dict = None):
        return None

    async def group_next_gid(self, context: dict = None) -> int:
        return max(
            (g.get("gid", 0) for g in await self.group_query()), default=999
        ) + 1

    # ── Privileges ────────────────────────────────────────

    async def privilege_query(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        privs = self.app.config_store.get("privileges", [
            {"id": 1, "name": "Full Admin", "roles": ["FULL_ADMIN"], "web_shell": True, "groups": [{"id": 1}]},
        ])
        if filters:
            privs = apply_filters(privs, filters)
        if options:
            privs = apply_options(privs, options)
        return privs

    async def privilege_create(self, data: dict = None, context: dict = None):
        privs = await self.privilege_query()
        if data:
            data["id"] = len(privs) + 1
            privs.append(data)
            await self.app.config_store.set("privileges", privs)
        return data or {}

    async def privilege_update(self, id: int = None, data: dict = None, context: dict = None):
        privs = await self.privilege_query()
        for p in privs:
            if p.get("id") == id:
                p.update(data or {})
                await self.app.config_store.set("privileges", privs)
                return p
        return {}

    async def privilege_delete(self, id: int = None, context: dict = None):
        privs = await self.privilege_query()
        privs = [p for p in privs if p.get("id") != id]
        await self.app.config_store.set("privileges", privs)
        return None

    async def privilege_roles(self, context: dict = None):
        from ..auth import Permission
        return [
            {"name": Permission.FULL_ADMIN, "label": "Full Administrator"},
            {"name": Permission.READ_ONLY, "label": "Read Only"},
            {"name": Permission.SHARING_ADMIN, "label": "Sharing Administrator"},
            {"name": Permission.STORAGE_ADMIN, "label": "Storage Administrator"},
            {"name": Permission.NETWORK_ADMIN, "label": "Network Administrator"},
            {"name": Permission.VM_ADMIN, "label": "VM Administrator"},
        ]
