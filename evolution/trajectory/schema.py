from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from mewcode.evolution.task.schema import TaskMetadata


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _dataclass_from_dict(cls: type[Any], data: dict[str, Any] | None) -> Any:
    names = {f.name for f in fields(cls)}
    raw = data if isinstance(data, dict) else {}
    return cls(**{k: v for k, v in raw.items() if k in names})


def _as_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {k: _as_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [_as_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _as_jsonable(v) for k, v in value.items()}
    return value


@dataclass
class RepositoryInfo:
    work_dir: str
    git_branch: str = ""
    git_commit: str = ""
    environment: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentAction:
    action_type: str
    content: str
    timestamp: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallRecord:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    started_at: str = field(default_factory=utc_now_iso)
    ended_at: str = ""
    elapsed: float = 0.0
    output: str = ""
    is_error: bool = False
    source_skills: list[str] = field(default_factory=list)
    source_type: str = "unknown"


@dataclass
class Observation:
    source: str
    content: str
    timestamp: str = field(default_factory=utc_now_iso)
    tool_call_id: str = ""


@dataclass
class FileModification:
    path: str
    operation: Literal["write", "edit", "delete", "unknown"]
    diff: str = ""
    tool_call_id: str = ""
    success: bool = True
    source_skills: list[str] = field(default_factory=list)


@dataclass
class TestExecutionResult:
    command: str
    output: str
    exit_code: int
    passed: bool
    tool_call_id: str = ""
    elapsed: float = 0.0
    source_skills: list[str] = field(default_factory=list)


@dataclass
class HumanFeedback:
    rating: Literal["positive", "negative", "neutral"] = "neutral"
    comment: str = ""


@dataclass
class TrajectoryOutcome:
    task_success: bool | None = None
    test_pass: bool | None = None
    test_result: str = ""
    execution_steps: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _as_jsonable(self)


@dataclass
class TrajectoryEvent:
    trajectory_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)
    session_id: str = ""
    source_skills: list[str] = field(default_factory=list)
    source_type: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return _as_jsonable(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrajectoryEvent":
        return cls(
            trajectory_id=data.get("trajectory_id", ""),
            event_type=data.get("event_type", ""),
            payload=dict(data.get("payload", {})),
            timestamp=data.get("timestamp", "") or utc_now_iso(),
            session_id=data.get("session_id", ""),
            source_skills=list(data.get("source_skills", [])),
            source_type=data.get("source_type", "unknown"),
        )


@dataclass
class TaskTrajectory:
    task_description: str
    repository: RepositoryInfo
    session_id: str = ""
    trajectory_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: str = field(default_factory=utc_now_iso)
    ended_at: str = ""
    task_metadata: TaskMetadata = field(default_factory=TaskMetadata)
    outcome: TrajectoryOutcome = field(default_factory=TrajectoryOutcome)
    agent_actions: list[AgentAction] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    file_modifications: list[FileModification] = field(default_factory=list)
    test_results: list[TestExecutionResult] = field(default_factory=list)
    final_success_status: bool | None = None
    final_message: str = ""
    human_feedback: HumanFeedback | None = None
    active_skills_at_start: list[str] = field(default_factory=list)
    skills_loaded_during_task: list[str] = field(default_factory=list)
    primary_skill: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_completed(
        self,
        success: bool | None,
        final_message: str = "",
        *,
        ended_at: str | None = None,
    ) -> None:
        self.final_success_status = success
        self.final_message = final_message
        self.ended_at = ended_at or utc_now_iso()
        self.outcome.task_success = success
        if self.test_results:
            latest = self.test_results[-1]
            self.outcome.test_pass = latest.passed
            self.outcome.test_result = latest.output
        self.outcome.execution_steps = [action.action_type for action in self.agent_actions]
        self.outcome.tool_calls = [record.tool_name for record in self.tool_calls]

    def to_dict(self) -> dict[str, Any]:
        return _as_jsonable(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskTrajectory":
        repository = _dataclass_from_dict(RepositoryInfo, data.get("repository"))
        trajectory = cls(
            task_description=data.get("task_description", ""),
            repository=repository,
            session_id=data.get("session_id", ""),
            trajectory_id=data.get("trajectory_id") or uuid.uuid4().hex,
            started_at=data.get("started_at") or utc_now_iso(),
            ended_at=data.get("ended_at", ""),
            task_metadata=TaskMetadata.from_dict(data.get("task_metadata")),
            outcome=_dataclass_from_dict(TrajectoryOutcome, data.get("outcome")),
            final_success_status=data.get("final_success_status"),
            final_message=data.get("final_message", ""),
            active_skills_at_start=list(data.get("active_skills_at_start", [])),
            skills_loaded_during_task=list(data.get("skills_loaded_during_task", [])),
            primary_skill=data.get("primary_skill", ""),
            metadata=dict(data.get("metadata", {})),
        )
        trajectory.agent_actions = [
            _dataclass_from_dict(AgentAction, item)
            for item in data.get("agent_actions", [])
        ]
        trajectory.tool_calls = [
            _dataclass_from_dict(ToolCallRecord, item)
            for item in data.get("tool_calls", [])
        ]
        trajectory.observations = [
            _dataclass_from_dict(Observation, item)
            for item in data.get("observations", [])
        ]
        trajectory.file_modifications = [
            _dataclass_from_dict(FileModification, item)
            for item in data.get("file_modifications", [])
        ]
        trajectory.test_results = [
            _dataclass_from_dict(TestExecutionResult, item)
            for item in data.get("test_results", [])
        ]
        feedback = data.get("human_feedback")
        if isinstance(feedback, dict):
            trajectory.human_feedback = _dataclass_from_dict(HumanFeedback, feedback)
        return trajectory

