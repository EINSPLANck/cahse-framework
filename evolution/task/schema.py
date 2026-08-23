from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

TaskType = Literal[
    "bug_fix",
    "code_modify",
    "refactor",
    "test_fix",
    "documentation",
    "unknown",
]


@dataclass
class TaskMetadata:
    task_type: TaskType = "unknown"
    task_description: str = ""
    target_component: str = ""
    solution_answer: str = ""
    structured_experience: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TaskMetadata":
        if not isinstance(data, dict):
            return cls()
        return cls(
            task_type=data.get("task_type", "unknown"),
            task_description=data.get("task_description", ""),
            target_component=data.get("target_component", ""),
            solution_answer=data.get("solution_answer", ""),
            structured_experience=data.get("structured_experience", {})
            if isinstance(data.get("structured_experience"), dict)
            else {},
        )
