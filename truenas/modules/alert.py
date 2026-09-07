"""Alert module - alert.*, alertservice.*, alertclasses.*."""
import asyncio
import logging
import time
from typing import Any, Optional

log = logging.getLogger("truenas.alert")


class AlertModule:
    def __init__(self, app):
        self.app = app
        self._alerts: list[dict] = []

    async def alert_list(self, filters: list = None, options: dict = None, context: dict = None):
        from ..query import apply_filters, apply_options
        alerts = list(self._alerts)
        if filters:
            alerts = apply_filters(alerts, filters)
        if options:
            alerts = apply_options(alerts, options)
        return alerts

    async def alert_dismiss(self, id: int = None, context: dict = None):
        for alert in self._alerts:
            if alert.get("id") == id:
                alert["dismissed"] = True
                break
        return None

    async def alert_restore(self, id: int = None, context: dict = None):
        for alert in self._alerts:
            if alert.get("id") == id:
                alert["dismissed"] = False
                break
        return None

    async def alert_list_categories(self, context: dict = None):
        return []

    async def alert_policy(self, context: dict = None):
        return self.app.config_store.get("alert_policy", {
            "id": 1,
            "policy": "IMMEDIATELY",
        })

    async def alert_policy_update(self, data: dict = None, context: dict = None):
        if data:
            await self.app.config_store.set("alert_policy", {
                "id": 1, **data
            })
        return await self.alert_policy()

    async def alertclasses_config(self, context: dict = None):
        return self.app.config_store.get("alert_classes", {
            "id": 1,
            "classes": {},
        })

    async def alertclasses_update(self, data: dict = None, context: dict = None):
        if data:
            await self.app.config_store.set("alert_classes", {
                "id": 1, **data
            })
        return await self.alertclasses_config()

    async def alertservice_query(self, context: dict = None):
        return self.app.config_store.get("alert_services", [])

    async def alertservice_create(self, data: dict = None, context: dict = None):
        services = await self.alertservice_query()
        if data:
            data["id"] = len(services) + 1
            services.append(data)
            await self.app.config_store.set("alert_services", services)
        return data or {}

    async def alertservice_update(self, id: int = None, data: dict = None, context: dict = None):
        services = await self.alertservice_query()
        for s in services:
            if s.get("id") == id:
                s.update(data or {})
                await self.app.config_store.set("alert_services", services)
                return s
        return {}

    async def alertservice_delete(self, id: int = None, context: dict = None):
        services = await self.alertservice_query()
        services = [s for s in services if s.get("id") != id]
        await self.app.config_store.set("alert_services", services)
        return None

    async def alertservice_test(self, data: dict = None, context: dict = None):
        return {"success": True}

    def add_alert(self, level: str, title: str, text: str, category: str = "GENERAL"):
        alert_id = len(self._alerts) + 1
        self._alerts.append({
            "id": alert_id,
            "level": level,
            "title": title,
            "formatted": text,
            "text": text,
            "category": category,
            "klass": "CRITICAL" if level == "CRITICAL" else "WARNING" if level == "WARNING" else "INFO",
            "dismissed": False,
            "time": int(time.time()),
            "source": "truenas-rpi",
            "key": "",
        })
        return alert_id

    async def check_system_alerts(self):
        from ..backends.linux import run_cmd_lines
        temps = await run_cmd_lines(
            "cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null"
        )
        for temp_str in temps:
            try:
                temp = int(temp_str.strip()) / 1000
                if temp > 80:
                    self.add_alert(
                        "CRITICAL", "High Temperature",
                        f"System temperature is {temp}C",
                        "HARDWARE",
                    )
                elif temp > 70:
                    self.add_alert(
                        "WARNING", "Temperature Warning",
                        f"System temperature is {temp}C",
                        "HARDWARE",
                    )
            except ValueError:
                pass

        from ..backends.linux import run_cmd
        code, stdout, _ = await run_cmd("df -h --output=pcent,target 2>/dev/null")
        if code == 0:
            for line in stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        pct = int(parts[0].replace("%", ""))
                        if pct > 90:
                            self.add_alert(
                                "CRITICAL", "Disk Space Critical",
                                f"Filesystem {parts[1]} is {pct}% full",
                                "STORAGE",
                            )
                        elif pct > 80:
                            self.add_alert(
                                "WARNING", "Disk Space Low",
                                f"Filesystem {parts[1]} is {pct}% full",
                                "STORAGE",
                            )
                    except ValueError:
                        pass
