"""Job management system for long-running tasks."""
import asyncio
import time
import uuid
from typing import Any, Callable, Optional


class Job:
    __slots__ = (
        "id", "method", "arguments", "state", "progress",
        "result", "error", "exception", "abortable",
        "time_started", "time_finished", "queue",
        "_cancel_event",
    )

    def __init__(self, method: str, arguments: Any = None):
        self.id = uuid.uuid4().int & 0xFFFFFFFF
        self.method = method
        self.arguments = arguments
        self.state = "PENDING"
        self.progress: dict = {"percent": 0, "description": ""}
        self.result: Any = None
        self.error: Optional[str] = None
        self.exception: Optional[str] = None
        self.abortable = True
        self.time_started: Optional[float] = None
        self.time_finished: Optional[float] = None
        self.queue: Optional[str] = None
        self._cancel_event = asyncio.Event()

    def set_progress(self, percent: float, description: str = ""):
        self.progress = {"percent": percent, "description": description}

    def set_result(self, result: Any):
        self.result = result
        self.state = "SUCCESS"
        self.time_finished = time.time()

    def set_error(self, error: str, exception: str = ""):
        self.error = error
        self.exception = exception
        self.state = "FAILED"
        self.time_finished = time.time()

    def abort(self):
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "method": self.method,
            "arguments": self.arguments,
            "state": self.state,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "exception": self.exception,
            "abortable": self.abortable,
            "time_started": self.time_started,
            "time_finished": self.time_finished,
            "queue": self.queue,
        }
        return d


class JobManager:
    def __init__(self):
        self._jobs: dict[int, Job] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    async def create(
        self,
        method: str,
        arguments: Any = None,
        func: Optional[Callable] = None,
        queue: Optional[str] = None,
    ) -> Job:
        job = Job(method, arguments)
        job.queue = queue
        job.time_started = time.time()
        job.state = "RUNNING"
        self._jobs[job.id] = job

        if func is not None:
            asyncio.create_task(self._run_job(job, func))

        return job

    async def _run_job(self, job: Job, func: Callable):
        try:
            result = await func(job)
            if not job.cancelled:
                job.set_result(result)
        except asyncio.CancelledError:
            job.set_error("Job was cancelled", "CANCELLED")
        except Exception as e:
            job.set_error(str(e), type(e).__name__)
        finally:
            await self._notify_subscribers(job)

    async def _notify_subscribers(self, job: Job):
        key = f"core.get_jobs"
        if key in self._subscribers:
            for q in self._subscribers[key]:
                try:
                    q.put_nowait(("changed", job.id, job.to_dict()))
                except asyncio.QueueFull:
                    pass

    def get(self, job_id: int) -> Optional[Job]:
        return self._jobs.get(job_id)

    def get_all(self) -> list[dict]:
        return [j.to_dict() for j in self._jobs.values()]

    def abort(self, job_id: int) -> bool:
        job = self._jobs.get(job_id)
        if job and job.abortable:
            job.abort()
            return True
        return False

    def subscribe(self, key: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(key, []).append(q)
        return q

    def unsubscribe(self, key: str, q: asyncio.Queue):
        if key in self._subscribers:
            self._subscribers[key] = [
                x for x in self._subscribers[key] if x is not q
            ]

    def cleanup(self, max_age: float = 86400):
        now = time.time()
        to_remove = []
        for jid, job in self._jobs.items():
            if (
                job.time_finished
                and (now - job.time_finished) > max_age
            ):
                to_remove.append(jid)
        for jid in to_remove:
            del self._jobs[jid]
