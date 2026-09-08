"""Authentication, authorization, and session management."""
import asyncio
import hashlib
import secrets
import time
import os
from typing import Any, Optional
from pathlib import Path

import bcrypt


class Permission:
    FULL_ADMIN = "FULL_ADMIN"
    READ_ONLY = "READ_ONLY"
    SHARING_ADMIN = "SHARING_ADMIN"
    STORAGE_ADMIN = "STORAGE_ADMIN"
    NETWORK_ADMIN = "NETWORK_ADMIN"
    VM_ADMIN = "VM_ADMIN"


ROLES_HIERARCHY = {
    Permission.FULL_ADMIN: [
        Permission.SHARING_ADMIN,
        Permission.STORAGE_ADMIN,
        Permission.NETWORK_ADMIN,
        Permission.VM_ADMIN,
        Permission.READ_ONLY,
    ],
    Permission.SHARING_ADMIN: [Permission.READ_ONLY],
    Permission.STORAGE_ADMIN: [Permission.READ_ONLY],
    Permission.NETWORK_ADMIN: [Permission.READ_ONLY],
    Permission.VM_ADMIN: [Permission.READ_ONLY],
    Permission.READ_ONLY: [],
}

METHOD_ROLES = {
    "pool.query": [Permission.READ_ONLY],
    "pool.create": [Permission.STORAGE_ADMIN],
    "pool.export": [Permission.STORAGE_ADMIN],
    "pool.dataset.create": [Permission.STORAGE_ADMIN],
    "pool.dataset.delete": [Permission.STORAGE_ADMIN],
    "pool.snapshot.create": [Permission.STORAGE_ADMIN],
    "pool.snapshot.delete": [Permission.STORAGE_ADMIN],
    "interface.query": [Permission.READ_ONLY],
    "interface.create": [Permission.NETWORK_ADMIN],
    "interface.update": [Permission.NETWORK_ADMIN],
    "interface.delete": [Permission.NETWORK_ADMIN],
    "sharing.smb.create": [Permission.SHARING_ADMIN],
    "sharing.smb.update": [Permission.SHARING_ADMIN],
    "sharing.smb.delete": [Permission.SHARING_ADMIN],
    "sharing.nfs.create": [Permission.SHARING_ADMIN],
    "sharing.nfs.update": [Permission.SHARING_ADMIN],
    "sharing.nfs.delete": [Permission.SHARING_ADMIN],
    "vm.create": [Permission.VM_ADMIN],
    "vm.delete": [Permission.VM_ADMIN],
    "vm.start": [Permission.VM_ADMIN],
    "vm.stop": [Permission.VM_ADMIN],
    "system.reboot": [Permission.FULL_ADMIN],
    "system.shutdown": [Permission.FULL_ADMIN],
    "system.general.update": [Permission.FULL_ADMIN],
    "user.create": [Permission.FULL_ADMIN],
    "user.delete": [Permission.FULL_ADMIN],
    "group.create": [Permission.FULL_ADMIN],
    "group.delete": [Permission.FULL_ADMIN],
    "service.update": [Permission.FULL_ADMIN],
    "service.control": [Permission.FULL_ADMIN],
    "alert.dismiss": [Permission.READ_ONLY],
    "alert.restore": [Permission.READ_ONLY],
    "config.reset": [Permission.FULL_ADMIN],
    "config.upload": [Permission.FULL_ADMIN],
}

READONLY_METHODS = {
    "system.info", "system.general.config", "system.advanced.config",
    "system.security.info", "system.reboot.info",
    "network.general.summary", "network.configuration.config",
    "core.get_jobs", "core.set_options",
    "service.query", "alert.list", "alert.policy",
    "pool.query", "pool.dataset.query", "pool.snapshot.query",
    "disk.query", "interface.query", "staticroute.query",
    "sharing.smb.query", "sharing.nfs.query",
    "user.query", "group.query", "privilege.query",
    "filesystem.listdir", "filesystem.stat", "filesystem.statfs",
    "system.product_type", "system.hostname",
    "app.query", "vm.query", "catalog.query",
    "enclosure2.query", "reporting.graphs",
    "api_key.query", "alertservice.query",
    "keychaincredential.query",
    "virt.global.config",
}


class Session:
    __slots__ = ("token", "reconnect_token", "user", "roles",
                 "created_at", "last_activity", "attributes")

    def __init__(self, user: str, roles: list[str]):
        self.token = secrets.token_hex(32)
        self.reconnect_token = secrets.token_hex(32)
        self.user = user
        self.roles = roles
        self.created_at = time.time()
        self.last_activity = time.time()
        self.attributes: dict = {}


class AuthManager:
    def __init__(self, data_dir: str = "/var/lib/truenas-rpi"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._users_file = self._data_dir / "users.json"
        self._sessions: dict[str, Session] = {}
        self._tokens: dict[str, dict] = {}
        self._load_users()

    def _load_users(self):
        if self._users_file.exists():
            import json
            with open(self._users_file) as f:
                self._users = json.load(f)
        else:
            self._users = {
                "admin": {
                    "password_hash": bcrypt.hashpw(
                        b"admin", bcrypt.gensalt()
                    ).decode(),
                    "full_name": "Administrator",
                    "roles": [Permission.FULL_ADMIN],
                    "builtin": True,
                    "id": 1,
                    "groupid": 1,
                    "uid": 1000,
                    "shell": "/bin/bash",
                    "home": "/root",
                    "email": "",
                    "sshpubkey": "",
                    "locked": False,
                    "smb": True,
                    "password_disabled": False,
                    "immutable": False,
                    "microsoft_account": False,
                    "last_login": None,
                    "created_at": int(time.time()),
                }
            }
            self._save_users()

    def _save_users(self):
        import json
        with open(self._users_file, "w") as f:
            json.dump(self._users, f, indent=2)

    def authenticate_password(
        self, username: str, password: str
    ) -> Optional[Session]:
        user = self._users.get(username)
        if not user:
            return None
        if user.get("locked", False):
            return None
        try:
            if bcrypt.checkpw(
                password.encode(), user["password_hash"].encode()
            ):
                session = Session(username, user.get("roles", []))
                self._sessions[session.token] = session
                user["last_login"] = int(time.time())
                self._save_users()
                return session
        except Exception:
            pass
        return None

    def authenticate_token(self, token: str) -> Optional[Session]:
        if token in self._sessions:
            session = self._sessions[token]
            session.last_activity = time.time()
            return session
        if token in self._tokens:
            info = self._tokens[token]
            if time.time() - info["created"] < info["ttl"]:
                user = self._users.get(info["username"])
                if user:
                    session = Session(
                        info["username"], user.get("roles", [])
                    )
                    self._sessions[session.token] = session
                    return session
        return None

    def authenticate_reconnect(self, reconnect_token: str) -> Optional[Session]:
        for session in self._sessions.values():
            if session.reconnect_token == reconnect_token:
                session.last_activity = time.time()
                return session
        return None

    def generate_token(
        self, username: str, ttl: int = 300
    ) -> Optional[str]:
        if username not in self._users:
            return None
        token = secrets.token_hex(32)
        self._tokens[token] = {
            "username": username,
            "created": time.time(),
            "ttl": ttl,
        }
        return token

    def create_session(self, username: str) -> Session:
        user = self._users.get(username, {})
        session = Session(username, user.get("roles", []))
        self._sessions[session.token] = session
        return session

    def get_session(self, token: str) -> Optional[Session]:
        return self._sessions.get(token)

    def logout(self, token: str):
        self._sessions.pop(token, None)

    def terminate_session(self, token: str):
        self._sessions.pop(token, None)

    def terminate_other_sessions(self, current_token: str):
        to_remove = [
            t for t in self._sessions if t != current_token
        ]
        for t in to_remove:
            del self._sessions[t]

    def has_permission(self, session: Session, method: str) -> bool:
        if Permission.FULL_ADMIN in session.roles:
            return True
        if method in READONLY_METHODS:
            return True
        required = METHOD_ROLES.get(method)
        if required is None:
            return Permission.FULL_ADMIN in session.roles
        return any(r in session.roles for r in required)

    def set_attribute(
        self, token: str, key: str, value: Any
    ) -> bool:
        session = self._sessions.get(token)
        if session:
            session.attributes[key] = value
            return True
        return False

    def get_sessions(self, username: str = None) -> list[dict]:
        result = []
        for token, session in self._sessions.items():
            if username and session.user != username:
                continue
            result.append({
                "id": token,
                "token": token,
                "user": session.user,
                "username": session.user,
                "roles": session.roles,
                "created_at": {"$date": int(session.created_at)},
                "last_activity": {"$date": int(session.last_activity)},
                "attributes": session.attributes,
                "origin": "",
                "current": False,
                "internal": False,
                "credentials_data": {
                    "username": session.user,
                    "parent": None,
                },
            })
        return result

    def setup_local_admin(self, username: str, password: str, fullname: str = ""):
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        uid = max(
            (u.get("uid", 0) for u in self._users.values()), default=999
        ) + 1
        self._users[username] = {
            "password_hash": pw_hash,
            "full_name": fullname or username,
            "roles": [Permission.FULL_ADMIN],
            "builtin": False,
            "id": max(
                (u.get("id", 0) for u in self._users.values()), default=0
            ) + 1,
            "groupid": 1,
            "uid": uid,
            "shell": "/bin/bash",
            "home": f"/home/{username}",
            "email": "",
            "sshpubkey": "",
            "locked": False,
            "smb": True,
            "password_disabled": False,
            "immutable": False,
            "microsoft_account": False,
            "last_login": None,
            "created_at": int(time.time()),
        }
        self._save_users()
