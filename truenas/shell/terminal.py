"""Shell module - terminal WebSocket for system shell."""
import asyncio
import json
import logging
import os
import signal
from typing import Any, Optional

try:
    import pty
    import fcntl
    import struct
    import termios
    HAS_PTY = True
except ImportError:
    HAS_PTY = False

log = logging.getLogger("truenas.shell")


class ShellSession:
    __slots__ = ("id", "pid", "fd", "master_fd", "slave_fd", "width", "height", "alive")

    def __init__(self, session_id: str, width: int = 80, height: int = 24):
        self.id = session_id
        self.pid = 0
        self.fd = None
        self.master_fd = None
        self.slave_fd = None
        self.width = width
        self.height = height
        self.alive = True

    def resize(self, width: int, height: int):
        self.width = width
        self.height = height
        if self.master_fd:
            try:
                winsize = struct.pack("HHHH", height, width, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except Exception:
                pass


class ShellManager:
    def __init__(self, app):
        self.app = app
        self._sessions: dict[str, ShellSession] = {}
        self._max_sessions = app.config.get("max_shell_sessions", 5)

    async def handle_shell_websocket(self, websocket):
        import secrets
        token = secrets.token_hex(32)
        session_id = secrets.token_hex(16)
        session = ShellSession(session_id)

        try:
            first_msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            msg_data = json.loads(first_msg) if isinstance(first_msg, str) else {}
            auth_token = msg_data.get("token", "")
            options = msg_data.get("options", {})
            session.width = options.get("cols", 80)
            session.height = options.get("rows", 24)
        except Exception:
            pass

        if len(self._sessions) >= self._max_sessions:
            await websocket.send(json.dumps({"error": "Maximum shell sessions reached"}))
            return

        self._sessions[session_id] = session

        if not HAS_PTY:
            error = "Shell support requires a POSIX system (PTY unavailable)"
            log.warning(error)
            await websocket.send(error.encode())
            self._sessions.pop(session_id, None)
            return

        try:
            pid, master_fd = pty.fork()
            if pid == 0:
                os.execv("/bin/bash", ["/bin/bash", "--login"])
            else:
                session.pid = pid
                session.master_fd = master_fd
                session.alive = True
                session.resize(session.width, session.height)

                reader_task = asyncio.create_task(
                    self._read_and_forward(master_fd, websocket, session)
                )

                try:
                    async for message in websocket:
                        if isinstance(message, bytes):
                            os.write(master_fd, message)
                        elif isinstance(message, str):
                            try:
                                data = json.loads(message)
                                if "resize" in data:
                                    session.resize(
                                        data["resize"].get("cols", 80),
                                        data["resize"].get("rows", 24),
                                    )
                                elif "data" in data:
                                    os.write(master_fd, data["data"].encode())
                            except json.JSONDecodeError:
                                os.write(master_fd, message.encode())
                finally:
                    reader_task.cancel()
        except Exception as e:
            log.exception("Shell session error: %s", e)
        finally:
            session.alive = False
            if session.master_fd:
                try:
                    os.close(session.master_fd)
                except Exception:
                    pass
            if session.pid:
                try:
                    os.kill(session.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            self._sessions.pop(session_id, None)

    async def _read_and_forward(self, master_fd: int, websocket, session: ShellSession):
        loop = asyncio.get_event_loop()
        try:
            while session.alive:
                data = await loop.run_in_executor(None, os.read, master_fd, 4096)
                if not data:
                    break
                await websocket.send(data)
        except asyncio.CancelledError:
            pass
        except Exception:
            session.alive = False

    def resize(self, session_id: str, width: int, height: int):
        session = self._sessions.get(session_id)
        if session:
            session.resize(width, height)

    def close_session(self, session_id: str):
        session = self._sessions.pop(session_id, None)
        if session:
            session.alive = False
            if session.pid:
                try:
                    os.kill(session.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if session.master_fd:
                try:
                    os.close(session.master_fd)
                except Exception:
                    pass

    def get_sessions(self) -> list[dict]:
        return [
            {"id": s.id, "pid": s.pid, "alive": s.alive, "width": s.width, "height": s.height}
            for s in self._sessions.values()
        ]
