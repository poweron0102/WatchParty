from __future__ import annotations

import asyncio
import secrets
import time


class Job:
    def __init__(self, kind: str):
        self.id = secrets.token_urlsafe(12); self.kind = kind; self.state = "queued"
        self.completed = 0; self.total = 0; self.message = None; self.error = None
        self.created_at = time.time(); self.updated_at = self.created_at
        self.cancelled = asyncio.Event(); self.resumed = asyncio.Event(); self.resumed.set()

    def view(self):
        return {key: getattr(self, key) for key in ("id", "kind", "state", "completed", "total", "message", "error", "created_at", "updated_at")}

    async def checkpoint(self):
        if self.cancelled.is_set(): raise asyncio.CancelledError
        await self.resumed.wait()
        if self.cancelled.is_set(): raise asyncio.CancelledError

    def progress(self, completed: int | None = None, total: int | None = None, message: str | None = None):
        if completed is not None: self.completed = completed
        if total is not None: self.total = total
        if message is not None: self.message = message
        self.updated_at = time.time()


class TransientJobs:
    def __init__(self):
        self.jobs: dict[str, Job] = {}; self.tasks: dict[str, asyncio.Task] = {}

    def start(self, kind, runner):
        job = Job(kind); self.jobs[job.id] = job
        async def execute():
            job.state = "running"; job.updated_at = time.time()
            try:
                await runner(job)
                if job.state != "cancelled": job.state = "completed"
            except asyncio.CancelledError:
                job.state = "cancelled"
            except Exception as exc:
                job.state = "failed"; job.error = str(exc)[:500]
            finally: job.updated_at = time.time()
        task = asyncio.create_task(execute()); self.tasks[job.id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job.id, None))
        return job

    def list(self): return [job.view() for job in self.jobs.values()]

    def get(self, job_id):
        try: return self.jobs[job_id]
        except KeyError as exc: raise KeyError("job não encontrado") from exc

    def pause(self, job_id):
        job = self.get(job_id); job.resumed.clear(); job.state = "paused"; job.updated_at = time.time(); return job

    def resume(self, job_id):
        job = self.get(job_id); job.resumed.set(); job.state = "running"; job.updated_at = time.time(); return job

    def cancel(self, job_id):
        job = self.get(job_id); job.cancelled.set(); job.resumed.set(); job.state = "cancelled"; job.updated_at = time.time()
        task = self.tasks.get(job_id)
        if task: task.cancel()
        return job
