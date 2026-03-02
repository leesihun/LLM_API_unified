from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Awaitable, Callable

from app.config import config
from app.process_runner import run_cli

logger = logging.getLogger(__name__)

MAX_HISTORY = 200


class TaskStatus(str, Enum):
    QUEUED = "queued"
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: str
    tool: str
    prompt: str
    delay_minutes: float = 0
    allowed_tools: list[str] = field(default_factory=list)
    skip_permissions: bool = False
    status: TaskStatus = TaskStatus.QUEUED
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    scheduled_for: datetime | None = None
    output: str = ""
    exit_code: int | None = None
    error: str | None = None


class TaskManager:
    def __init__(self) -> None:
        self.queue: list[Task] = []
        self.history: list[Task] = []
        self._current: Task | None = None
        self._run_handle: asyncio.Task | None = None
        self._broadcast: Callable | None = None
        self._running = False
        self._worker: asyncio.Task | None = None

    @property
    def current_task(self) -> Task | None:
        return self._current

    def set_broadcast(self, fn: Callable) -> None:
        self._broadcast = fn

    def start(self) -> None:
        self._running = True
        self._worker = asyncio.create_task(self._process_queue())
        logger.info("Task manager started")

    async def stop(self) -> None:
        self._running = False
        if self._run_handle:
            self._run_handle.cancel()
        if self._worker:
            self._worker.cancel()
        logger.info("Task manager stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_task(
        self,
        tool: str,
        prompt: str,
        delay_minutes: float = 0,
        allowed_tools: list[str] | None = None,
        skip_permissions: bool = False,
    ) -> Task:
        task = Task(
            id=uuid.uuid4().hex[:8],
            tool=tool,
            prompt=prompt,
            delay_minutes=delay_minutes,
            allowed_tools=allowed_tools or [],
            skip_permissions=skip_permissions,
        )
        if delay_minutes > 0:
            task.scheduled_for = datetime.now() + timedelta(minutes=delay_minutes)
        self.queue.append(task)
        return task

    async def cancel_task(self, task_id: str) -> bool:
        for i, task in enumerate(self.queue):
            if task.id == task_id:
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now()
                self.queue.pop(i)
                self._archive(task)
                return True

        if (
            self._current
            and self._current.id == task_id
            and self._run_handle
        ):
            self._run_handle.cancel()
            return True

        return False

    def get_state(self) -> dict:
        return {
            "queue": [serialize_task(t) for t in self.queue],
            "history": [serialize_task(t) for t in self.history[-50:]],
            "current": serialize_task(self._current) if self._current else None,
        }

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    async def _process_queue(self) -> None:
        try:
            await self._loop()
        except asyncio.CancelledError:
            if self._run_handle:
                self._run_handle.cancel()
                try:
                    await self._run_handle
                except (asyncio.CancelledError, Exception):
                    pass

    async def _loop(self) -> None:
        while self._running:
            if not self.queue:
                await asyncio.sleep(0.5)
                continue

            task = self.queue[0]

            # ---- honour scheduled time ----
            if task.scheduled_for and datetime.now() < task.scheduled_for:
                if task.status != TaskStatus.WAITING:
                    task.status = TaskStatus.WAITING
                    await self._notify("task_waiting", task)
                remaining = (task.scheduled_for - datetime.now()).total_seconds()
                await asyncio.sleep(min(remaining, 2))
                continue

            # ---- run the task ----
            self.queue.pop(0)
            self._current = task
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            logger.info(f"Task {task.id} starting: {task.tool}")
            await self._notify("task_started", task)

            try:
                cmd = config.CLAUDE_CMD if task.tool == "claude" else config.CURSOR_CMD

                async def on_output(text: str) -> None:
                    task.output += text
                    await self._notify("stream", task, text)

                self._run_handle = asyncio.create_task(
                    run_cli(
                        command=cmd,
                        prompt=task.prompt,
                        workspace=config.active_workspace,
                        timeout=config.TASK_TIMEOUT_SECONDS,
                        on_output=on_output,
                        allowed_tools=task.allowed_tools or None,
                        skip_permissions=task.skip_permissions,
                    )
                )
                result = await self._run_handle

                task.exit_code = result["exit_code"]
                if "error" in result:
                    task.status = TaskStatus.FAILED
                    task.error = result["error"]
                    logger.error(f"Task {task.id} failed: {task.error}")
                else:
                    task.status = TaskStatus.COMPLETED
                    logger.info(f"Task {task.id} completed: {len(task.output)} chars output")

            except asyncio.CancelledError:
                task.status = TaskStatus.CANCELLED
                logger.info(f"Task {task.id} cancelled")
            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                logger.exception(f"Task {task.id} exception: {exc}")

            task.completed_at = datetime.now()
            self._current = None
            self._run_handle = None

            await self._notify(
                {
                    TaskStatus.COMPLETED: "task_done",
                    TaskStatus.FAILED: "task_error",
                    TaskStatus.CANCELLED: "task_cancelled",
                }.get(task.status, "task_done"),
                task,
            )
            self._archive(task)

            if self.queue and config.MIN_TASK_GAP_SECONDS > 0:
                await asyncio.sleep(config.MIN_TASK_GAP_SECONDS)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _archive(self, task: Task) -> None:
        self.history.append(task)
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[-MAX_HISTORY:]

    async def _notify(self, event_type: str, task: Task, text: str = "") -> None:
        if self._broadcast:
            await self._broadcast(event_type, task, text)


def serialize_task(task: Task) -> dict:
    return {
        "id": task.id,
        "tool": task.tool,
        "prompt": task.prompt,
        "status": task.status.value,
        "delayMinutes": task.delay_minutes,
        "allowedTools": task.allowed_tools,
        "skipPermissions": task.skip_permissions,
        "createdAt": task.created_at.isoformat(),
        "startedAt": task.started_at.isoformat() if task.started_at else None,
        "completedAt": task.completed_at.isoformat() if task.completed_at else None,
        "scheduledFor": task.scheduled_for.isoformat() if task.scheduled_for else None,
        "output": task.output,
        "exitCode": task.exit_code,
        "error": task.error,
    }
