"""Server configuration loader and defaults."""
import os
import json
from pathlib import Path

_DEFAULTS = {
    "host": "0.0.0.0",
    "port": 80,
    "shell_port": 8080,
    "web_ui_path": "./webui-master/dist/webui",
    "data_dir": "/var/lib/truenas-rpi",
    "log_level": "INFO",
    "max_shell_sessions": 5,
    "max_concurrent_calls": 20,
    "token_ttl": 604800,
    "reconnect_token_ttl": 604800,
    "short_token_ttl": 300,
    "smb_conf": "/etc/smb.conf",
    "nfs_exports": "/etc/exports",
}


class Config:
    _instance = None
    _data: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        config_path = os.environ.get(
            "TRUENAS_CONFIG", "config.json"
        )
        self._data = dict(_DEFAULTS)
        if os.path.exists(config_path):
            with open(config_path) as f:
                self._data.update(json.load(f))
        os.makedirs(self._data["data_dir"], exist_ok=True)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key: str):
        return self._data[key]

    def __contains__(self, key: str):
        return key in self._data
