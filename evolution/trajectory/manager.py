from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mewcode.evolution.evaluator import TrajectoryEvaluator
from mewcode.evolution.task.task_analyzer import TaskAnalyzer
from mewcode.evolution.trajectory.collector import (
    _extract_diff,
    _extract_exit_code,
    _is_test_command,
    build_repository_info,
)
from mewcode.evolution.trajectory.schema import (
    AgentAction,
    FileModification,
    Observation,
    TaskTrajectory,
    TestExecutionResult,
    ToolCallRecord,
    TrajectoryEvent,
    TrajectoryOutcome,
    utc_now_iso,
)
from mewcode.evolution.trajectory.storage import TrajectoryStorage
from mewcode.evolution.trajectory.trigger import TrajectoryTrigger

log = logging.getLogger(__name__)


@dataclass
class _HookSnapshot:
    event: str
    event_name: str = ""
    session_id: str = ""
    task_description: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    file_path: str = ""
    message: str = ""
    output: str = ""
    is_error: bool = False
    elapsed: float = 0.0
    active_skills: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


_EVENT_ALIASES = {
    "session_start": "task_start",
    "pre_tool_use": "tool_call",
    "post_tool_use": "tool_result",
    "session_end": "task_end",
}


class TrajectoryManager:
    def __init__(
        self,
        work_dir: str,
        *,
        enabled: bool = True,
        max_consecutive_failures: int = 5,
        max_events: int = 500,
        max_duration_seconds: float = 60 * 60,
    ) -> None:
        self.work_dir = work_dir
        self.storage = TrajectoryStorage(work_dir)
        self.analyzer = TaskAnalyzer()
        self.evaluator = TrajectoryEvaluator()
        self.trigger = TrajectoryTrigger(enabled=enabled)
        self.max_consecutive_failures = max_consecutive_failures
        self.max_events = max_events
        self.max_duration_seconds = max_duration_seconds
        self.current: TaskTrajectory | None = None
        self._tool_index: dict[str, ToolCallRecord] = {}
        self._event_count = 0
        self._consecutive_failures = 0
        self._queue: asyncio.Queue[_HookSnapshot] | None = None
        self._worker: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self.session_id: str = ""

    def set_session_id(self, session_id: str) -> None:
        self.session_id = session_id
        if self.current is not None:
            self.current.session_id = session_id

    def handle_hook_event(self, event: str, ctx: Any) -> None:
        try:
            snapshot = self._snapshot(event, ctx)
            loop = asyncio.get_running_loop()
            if self._queue is None:
                self._queue = asyncio.Queue()
            self._queue.put_nowait(snapshot)
            if self._worker is None or self._worker.done():
                self._worker = loop.create_task(self._run_worker())
                self._tasks.add(self._worker)
                self._worker.add_done_callback(self._tasks.discard)
        except Exception as exc:
            log.debug("Trajectory hook listener failed: %s", exc)
            self._abort_current()

    async def _run_worker(self) -> None:
        assert self._queue is not None
        while not self._queue.empty():
            item = await self._queue.get()
            try:
                self._process_snapshot(item)
            except Exception as exc:
                log.debug("Trajectory collector failed: %s", exc)
                self._abort_current()
            finally:
                self._queue.task_done()

    async def wait_for_pending(self) -> None:
        if self._queue is not None:
            await self._queue.join()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _snapshot(self, event: str, ctx: Any) -> _HookSnapshot:
        return _HookSnapshot(
            event=event,
            event_name=str(getattr(ctx, "event_name", "")),
            session_id=str(getattr(ctx, "session_id", "") or self.session_id),
            task_description=str(getattr(ctx, "task_description", "")),
            tool_call_id=str(getattr(ctx, "tool_call_id", "")),
            tool_name=str(getattr(ctx, "tool_name", "")),
            tool_args=dict(getattr(ctx, "tool_args", {}) or {}),
            file_path=str(getattr(ctx, "file_path", "")),
            message=str(getattr(ctx, "message", "")),
            output=str(getattr(ctx, "output", "")),
            is_error=bool(getattr(ctx, "is_error", False)),
            elapsed=float(getattr(ctx, "elapsed", 0.0) or 0.0),
            active_skills=dict(getattr(ctx, "active_skills", {}) or {}),
            metadata=dict(getattr(ctx, "metadata", {}) or {}),
        )

    def _process_snapshot(self, snapshot: _HookSnapshot) -> None:
        event_type = _EVENT_ALIASES.get(snapshot.event, snapshot.event)
        if event_type == "task_start":
            self._start(snapshot)
            return
        if self.current is None:
            return
        if self._limits_exceeded():
            self._abort_current()
            return
        if event_type == "tool_call":
            self._record_tool_call(snapshot)
        elif event_type == "tool_result":
            self._record_tool_result(snapshot)
        elif event_type == "task_end":
            self._finish(snapshot)

    def _start(self, snapshot: _HookSnapshot) -> None:
        task_description = snapshot.task_description or snapshot.message
        if not self.trigger.should_start(
            task_description,
            has_active_session=self.current is not None,
        ):
            return
        active_skills = sorted(snapshot.active_skills)
        execution_context = str(snapshot.metadata.get("execution_context", "") or "")
        task_metadata = self.analyzer.analyze(
            task_description, execution_context=execution_context
        )
        self.current = TaskTrajectory(
            task_description=task_description,
            repository=build_repository_info(self.work_dir),
            session_id=snapshot.session_id,
            task_metadata=task_metadata,
            active_skills_at_start=active_skills,
            primary_skill=active_skills[0] if len(active_skills) == 1 else "",
            metadata=dict(snapshot.metadata),
        )
        self._tool_index = {}
        self._event_count = 0
        self._consecutive_failures = 0
        self.current.agent_actions.append(
            AgentAction(action_type="task_start", content=task_description)
        )
        self.storage.start(self.current)
        self._append(
            "task_start",
            {
                "task_description": task_description,
                "task_metadata": task_metadata.to_dict(),
                "execution_context": execution_context,
            },
            snapshot,
        )

    def _record_tool_call(self, snapshot: _HookSnapshot) -> None:
        assert self.current is not None
        source_skills = self._source_skills(snapshot)
        source_type = self._source_type(snapshot, "active_skill_context")
        record = ToolCallRecord(
            tool_call_id=snapshot.tool_call_id,
            tool_name=snapshot.tool_name,
            arguments=dict(snapshot.tool_args),
            source_skills=source_skills,
            source_type=source_type,
        )
        self.current.tool_calls.append(record)
        self._tool_index[snapshot.tool_call_id] = record
        if snapshot.tool_name == "LoadSkill" and snapshot.tool_args.get("name"):
            skill = str(snapshot.tool_args["name"])
            if skill not in self.current.skills_loaded_during_task:
                self.current.skills_loaded_during_task.append(skill)
        self.current.agent_actions.append(
            AgentAction(
                action_type="tool_call",
                content=snapshot.tool_name,
                metadata={"tool_call_id": snapshot.tool_call_id},
            )
        )
        self._append(
            "tool_call",
            {
                "tool_call_id": snapshot.tool_call_id,
                "tool_name": snapshot.tool_name,
                "arguments": snapshot.tool_args,
            },
            snapshot,
            source_skills=source_skills,
            source_type=source_type,
        )

    def _record_tool_result(self, snapshot: _HookSnapshot) -> None:
        assert self.current is not None
        source_skills = self._source_skills(snapshot)
        source_type = self._source_type(snapshot, "active_skill_context")
        record = self._tool_index.get(snapshot.tool_call_id)
        if record is None:
            record = ToolCallRecord(
                tool_call_id=snapshot.tool_call_id,
                tool_name=snapshot.tool_name,
                arguments=dict(snapshot.tool_args),
                source_skills=source_skills,
                source_type=source_type,
            )
            self.current.tool_calls.append(record)
            self._tool_index[snapshot.tool_call_id] = record
        record.ended_at = utc_now_iso()
        record.elapsed = snapshot.elapsed
        record.output = snapshot.output
        record.is_error = snapshot.is_error
        self.current.observations.append(
            Observation(
                source=snapshot.tool_name,
                content=snapshot.output,
                tool_call_id=snapshot.tool_call_id,
            )
        )
        self._append(
            "tool_result",
            {
                "tool_call_id": snapshot.tool_call_id,
                "tool_name": snapshot.tool_name,
                "output": snapshot.output,
                "is_error": snapshot.is_error,
                "elapsed": snapshot.elapsed,
            },
            snapshot,
            source_skills=source_skills,
            source_type=source_type,
        )
        if snapshot.is_error:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0
        if snapshot.tool_name in {"WriteFile", "EditFile"}:
            self._record_file_change(snapshot, source_skills)
        if snapshot.tool_name == "Bash":
            self._record_command_execution(snapshot, source_skills)
            self._record_test_result(snapshot, source_skills)

    def _record_file_change(self, snapshot: _HookSnapshot, source_skills: list[str]) -> None:
        assert self.current is not None
        path = str(
            snapshot.tool_args.get("file_path")
            or snapshot.tool_args.get("path")
            or snapshot.file_path
        )
        operation = "write" if snapshot.tool_name == "WriteFile" else "edit"
        modification = FileModification(
            path=path,
            operation=operation,
            diff=_extract_diff(snapshot.output),
            tool_call_id=snapshot.tool_call_id,
            success=not snapshot.is_error,
            source_skills=source_skills,
        )
        self.current.file_modifications.append(modification)
        self._append("file_change", modification.__dict__, snapshot, source_skills=source_skills)

    def _record_command_execution(self, snapshot: _HookSnapshot, source_skills: list[str]) -> None:
        self._append(
            "command_execution",
            {
                "tool_call_id": snapshot.tool_call_id,
                "command": snapshot.tool_args.get("command", ""),
                "output": snapshot.output,
                "is_error": snapshot.is_error,
                "elapsed": snapshot.elapsed,
            },
            snapshot,
            source_skills=source_skills,
        )

    def _record_test_result(self, snapshot: _HookSnapshot, source_skills: list[str]) -> None:
        assert self.current is not None
        command = str(snapshot.tool_args.get("command", ""))
        if not command or not _is_test_command(command):
            return
        exit_code = _extract_exit_code(snapshot.output, snapshot.is_error)
        result = TestExecutionResult(
            command=command,
            output=snapshot.output,
            exit_code=exit_code,
            passed=(not snapshot.is_error and exit_code == 0),
            tool_call_id=snapshot.tool_call_id,
            elapsed=snapshot.elapsed,
            source_skills=source_skills,
        )
        self.current.test_results.append(result)
        self._append("test_result", result.__dict__, snapshot, source_skills=source_skills)

    def _finish(self, snapshot: _HookSnapshot) -> None:
        trajectory = self.current
        if trajectory is None:
            return
        task_success = snapshot.metadata.get("task_success")
        if task_success is None:
            task_success = True
        latest_test = trajectory.test_results[-1] if trajectory.test_results else None
        trajectory.final_message = snapshot.message
        trajectory.ended_at = utc_now_iso()
        trajectory.final_success_status = bool(task_success)
        trajectory.outcome = TrajectoryOutcome(
            task_success=bool(task_success),
            test_pass=latest_test.passed if latest_test is not None else False,
            test_result=latest_test.output if latest_test is not None else "",
            execution_steps=[action.action_type for action in trajectory.agent_actions],
            tool_calls=[record.tool_name for record in trajectory.tool_calls],
        )
        trajectory.task_metadata = self.analyzer.synthesize_experience(trajectory)
        self._append(
            "experience_synthesized",
            {"task_metadata": trajectory.task_metadata.to_dict()},
            snapshot,
        )
        evaluation = self.evaluator.evaluate(trajectory)
        self.storage.finalize(trajectory, keep=evaluation.accepted)
        self.current = None
        self._tool_index = {}
        self._event_count = 0
        self._consecutive_failures = 0

    def _append(
        self,
        event_type: str,
        payload: dict[str, Any],
        snapshot: _HookSnapshot,
        *,
        source_skills: list[str] | None = None,
        source_type: str | None = None,
    ) -> None:
        trajectory = self.current
        if trajectory is None:
            return
        event = TrajectoryEvent(
            trajectory_id=trajectory.trajectory_id,
            event_type=event_type,
            payload=payload,
            session_id=trajectory.session_id,
            source_skills=source_skills if source_skills is not None else self._source_skills(snapshot),
            source_type=source_type or self._source_type(snapshot, "active_skill_context"),
        )
        self.storage.append_event(trajectory.trajectory_id, event)
        self._event_count += 1

    def _limits_exceeded(self) -> bool:
        trajectory = self.current
        if trajectory is None:
            return False
        if self._consecutive_failures >= self.max_consecutive_failures:
            return True
        if self._event_count >= self.max_events:
            return True
        try:
            from datetime import datetime

            started = datetime.fromisoformat(trajectory.started_at)
            elapsed = (datetime.fromisoformat(utc_now_iso()) - started).total_seconds()
            return elapsed > self.max_duration_seconds
        except Exception:
            return False

    def _abort_current(self) -> None:
        if self.current is not None:
            self.storage.delete(self.current.trajectory_id)
        self.current = None
        self._tool_index = {}
        self._event_count = 0
        self._consecutive_failures = 0

    @staticmethod
    def _source_skills(snapshot: _HookSnapshot) -> list[str]:
        if snapshot.tool_name == "LoadSkill" and snapshot.tool_args.get("name"):
            return [str(snapshot.tool_args["name"])]
        return sorted(snapshot.active_skills)

    @staticmethod
    def _source_type(snapshot: _HookSnapshot, default: str) -> str:
        if snapshot.tool_name == "LoadSkill" and snapshot.tool_args.get("name"):
            return "explicit_load_skill"
        return default if snapshot.active_skills else "unknown"

