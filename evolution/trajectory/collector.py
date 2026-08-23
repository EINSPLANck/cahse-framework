from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from mewcode.evolution.task.task_analyzer import TaskAnalyzer
from mewcode.evolution.trajectory.schema import (
    AgentAction,
    FileModification,
    Observation,
    RepositoryInfo,
    TaskTrajectory,
    TestExecutionResult,
    ToolCallRecord,
    utc_now_iso,
)


_TEST_COMMAND_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(^|\s)pytest(\s|$)",
        r"python\s+-m\s+pytest",
        r"(^|\s)uv\s+run\s+pytest(\s|$)",
        r"(^|\s)npm\s+test(\s|$)",
        r"(^|\s)pnpm\s+test(\s|$)",
        r"(^|\s)yarn\s+test(\s|$)",
        r"(^|\s)go\s+test(\s|$)",
        r"(^|\s)cargo\s+test(\s|$)",
        r"(^|\s)dotnet\s+test(\s|$)",
        r"(^|\s)mvn\s+test(\s|$)",
        r"(^|\s)gradle\s+test(\s|$)",
    )
]

_EXIT_CODE_RE = re.compile(r"Exit code\s+(\d+)", re.IGNORECASE)


def _git_value(work_dir: str, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def build_repository_info(work_dir: str) -> RepositoryInfo:
    return RepositoryInfo(
        work_dir=str(Path(work_dir)),
        git_branch=_git_value(work_dir, ["rev-parse", "--abbrev-ref", "HEAD"]),
        git_commit=_git_value(work_dir, ["rev-parse", "HEAD"]),
        environment={
            "cwd": os.getcwd(),
            "platform": os.name,
        },
    )


def _is_test_command(command: str) -> bool:
    return any(pattern.search(command) for pattern in _TEST_COMMAND_PATTERNS)


def _extract_exit_code(output: str, is_error: bool) -> int:
    match = _EXIT_CODE_RE.search(output)
    if match:
        return int(match.group(1))
    return 1 if is_error else 0


def _extract_diff(output: str) -> str:
    lines: list[str] = []
    for line in output.splitlines():
        if line.startswith(("+ ", "- ", "@@", "+++ ", "--- ")):
            lines.append(line)
    return "\n".join(lines)


def _operation_for_tool(tool_name: str) -> str | None:
    if tool_name == "WriteFile":
        return "write"
    if tool_name == "EditFile":
        return "edit"
    return None


class TrajectoryCollector:
    def __init__(self, work_dir: str, session_id: str = "") -> None:
        self.work_dir = work_dir
        self.session_id = session_id
        self.analyzer = TaskAnalyzer()
        self.current: TaskTrajectory | None = None
        self._tool_index: dict[str, ToolCallRecord] = {}

    def start_task(
        self,
        task_description: str,
        *,
        execution_context: str = "",
    ) -> TaskTrajectory:
        metadata = {"execution_context": execution_context} if execution_context else {}
        self.current = TaskTrajectory(
            task_description=task_description,
            repository=build_repository_info(self.work_dir),
            session_id=self.session_id,
            task_metadata=self.analyzer.analyze(
                task_description, execution_context=execution_context
            ),
            metadata=metadata,
        )
        self._tool_index = {}
        self.current.agent_actions.append(
            AgentAction(action_type="task_start", content=task_description)
        )
        return self.current

    def record_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        trajectory = self.current
        if trajectory is None:
            return
        record = ToolCallRecord(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=dict(arguments),
        )
        trajectory.tool_calls.append(record)
        self._tool_index[tool_call_id] = record
        trajectory.agent_actions.append(
            AgentAction(
                action_type="tool_call",
                content=tool_name,
                metadata={"tool_call_id": tool_call_id},
            )
        )

    def record_tool_result(
        self,
        tool_call_id: str,
        tool_name: str,
        output: str,
        is_error: bool,
        elapsed: float,
    ) -> None:
        trajectory = self.current
        if trajectory is None:
            return
        record = self._tool_index.get(tool_call_id)
        if record is None:
            record = ToolCallRecord(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments={},
            )
            trajectory.tool_calls.append(record)
            self._tool_index[tool_call_id] = record
        record.ended_at = utc_now_iso()
        record.elapsed = elapsed
        record.output = output
        record.is_error = is_error

        trajectory.observations.append(
            Observation(
                source=tool_name,
                content=output,
                tool_call_id=tool_call_id,
            )
        )
        self._maybe_record_file_modification(trajectory, record)
        self._maybe_record_test_result(trajectory, record)

    def finish_task(
        self,
        success: bool | None,
        final_message: str = "",
    ) -> TaskTrajectory:
        if self.current is None:
            self.start_task("")
        assert self.current is not None
        self.current.mark_completed(success=success, final_message=final_message)
        self.current.task_metadata = self.analyzer.synthesize_experience(self.current)
        self.current.agent_actions.append(
            AgentAction(action_type="task_end", content=final_message)
        )
        return self.current

    def clear(self) -> None:
        self.current = None
        self._tool_index = {}

    def _maybe_record_file_modification(
        self,
        trajectory: TaskTrajectory,
        record: ToolCallRecord,
    ) -> None:
        operation = _operation_for_tool(record.tool_name)
        if operation is None:
            return
        path = str(
            record.arguments.get("file_path")
            or record.arguments.get("path")
            or ""
        )
        if not path:
            return
        trajectory.file_modifications.append(
            FileModification(
                path=path,
                operation=operation,
                diff=_extract_diff(record.output),
                tool_call_id=record.tool_call_id,
                success=not record.is_error,
            )
        )

    def _maybe_record_test_result(
        self,
        trajectory: TaskTrajectory,
        record: ToolCallRecord,
    ) -> None:
        if record.tool_name != "Bash":
            return
        command = str(record.arguments.get("command", ""))
        if not command or not _is_test_command(command):
            return
        exit_code = _extract_exit_code(record.output, record.is_error)
        trajectory.test_results.append(
            TestExecutionResult(
                command=command,
                output=record.output,
                exit_code=exit_code,
                passed=(not record.is_error and exit_code == 0),
                tool_call_id=record.tool_call_id,
                elapsed=record.elapsed,
            )
        )
