from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from mewcode.evolution.evaluator import EvaluationResult, TrajectoryEvaluator
from mewcode.evolution.trajectory.schema import TaskTrajectory


@dataclass
class SessionDigest:
    session_id: str
    project: str
    git_branch: str
    started_at: str
    ended_at: str
    user_prompts: list[str]
    assistant_finals: list[str]
    tools_used: list[str]
    skills_used: list[str]
    files_touched: list[str]
    feedback_signals: list[str]
    n_user_turns: int
    n_assistant_turns: int
    raw_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class TaskRecord:
    id: str
    project: str
    intent: str
    context_excerpt: str
    system: str
    attempted_solution: str
    outcome: str
    reference_kind: str
    reference: str
    judge: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    source_sessions: list[str] = field(default_factory=list)
    split: str = "train"
    origin: str = "real"
    derived_from: str = ""
    skill_hint: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class ReplayResult:
    id: str
    hard: float
    soft: float
    response: str
    fail_reason: str
    task_type: str
    judge_rationale: str
    tools_called: list[str]
    tokens: int = 0
    latency_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class EditRecord:
    target: str
    op: str
    content: str
    anchor: str = ""
    rationale: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class SleepReport:
    night: int
    project: str
    started_at: str
    ended_at: str
    baseline_score: float
    candidate_score: float
    accepted: bool
    gate_action: str
    edits: list[EditRecord]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["edits"] = [edit.to_dict() for edit in self.edits]
        return data


class SkillOptAdapter:
    def __init__(self, evaluator: TrajectoryEvaluator | None = None) -> None:
        self.evaluator = evaluator or TrajectoryEvaluator()

    def to_session_digest(self, trajectory: TaskTrajectory) -> SessionDigest:
        feedback = []
        if trajectory.human_feedback is not None:
            feedback.append(trajectory.human_feedback.rating)
        return SessionDigest(
            session_id=trajectory.session_id or trajectory.trajectory_id,
            project=trajectory.repository.work_dir,
            git_branch=trajectory.repository.git_branch,
            started_at=trajectory.started_at,
            ended_at=trajectory.ended_at,
            user_prompts=[trajectory.task_description] if trajectory.task_description else [],
            assistant_finals=[trajectory.final_message] if trajectory.final_message else [],
            tools_used=[record.tool_name for record in trajectory.tool_calls],
            skills_used=[
                str(record.arguments.get("name"))
                for record in trajectory.tool_calls
                if record.tool_name == "LoadSkill" and record.arguments.get("name")
            ],
            files_touched=[mod.path for mod in trajectory.file_modifications],
            feedback_signals=feedback,
            n_user_turns=1 if trajectory.task_description else 0,
            n_assistant_turns=1 if trajectory.final_message else 0,
        )

    def to_task_record(self, trajectory: TaskTrajectory) -> TaskRecord:
        evaluation = self.evaluator.evaluate(trajectory)
        latest_test = trajectory.test_results[-1] if trajectory.test_results else None
        metadata = trajectory.task_metadata
        skill_hint = ""
        for record in trajectory.tool_calls:
            if record.tool_name == "LoadSkill" and record.arguments.get("name"):
                skill_hint = str(record.arguments["name"])
                break
        tags = ["coding", "trajectory", "skillopt-compatible"]
        if metadata.task_type and metadata.task_type != "unknown":
            tags.append(metadata.task_type)
        reference = self._rubric_reference(trajectory)
        return TaskRecord(
            id=trajectory.trajectory_id,
            project=trajectory.repository.work_dir,
            intent=metadata.task_description or trajectory.task_description,
            context_excerpt=self._context_excerpt(trajectory),
            system="mewcode",
            attempted_solution=metadata.solution_answer or trajectory.final_message,
            outcome="success" if evaluation.accepted else "fail",
            reference_kind="rubric" if reference else "none",
            reference=reference,
            judge={},
            tags=tags,
            source_sessions=[trajectory.session_id] if trajectory.session_id else [],
            origin="real",
            derived_from=trajectory.trajectory_id,
            skill_hint=skill_hint,
        )

    def to_replay_result(
        self,
        trajectory: TaskTrajectory,
        evaluation: EvaluationResult | None = None,
    ) -> ReplayResult:
        result = evaluation or self.evaluator.evaluate(trajectory)
        return ReplayResult(
            id=trajectory.trajectory_id,
            hard=result.hard_score,
            soft=result.soft_score,
            response=trajectory.final_message,
            fail_reason="" if result.accepted else "; ".join(result.reasons),
            task_type="coding",
            judge_rationale="; ".join(result.reasons),
            tools_called=[record.tool_name for record in trajectory.tool_calls],
            latency_ms=int(sum(record.elapsed for record in trajectory.tool_calls) * 1000),
        )

    def to_edit_record(self, content: str, rationale: str = "") -> EditRecord:
        return EditRecord(
            target="skill",
            op="add",
            content=content,
            rationale=rationale,
        )

    @staticmethod
    def _rubric_reference(trajectory: TaskTrajectory) -> str:
        metadata = trajectory.task_metadata
        paths = [mod.path for mod in trajectory.file_modifications if mod.success]
        tests = [result.command for result in trajectory.test_results if result.command]
        lines = ["A successful solution should:"]
        intent = metadata.task_description or trajectory.task_description
        if intent:
            lines.append(f"- Address the task: {intent}")
        if paths:
            lines.append("- Keep the repair focused around: " + ", ".join(paths[:5]))
        if tests:
            lines.append("- Pass or preserve the validation command: " + tests[-1])
        if metadata.solution_answer:
            lines.append("- Produce an answer consistent with the captured MewCode solution evidence.")
        return "\n".join(lines) if len(lines) > 1 else ""

    @staticmethod
    def _context_excerpt(trajectory: TaskTrajectory) -> str:
        parts = []
        if trajectory.file_modifications:
            paths = ", ".join(mod.path for mod in trajectory.file_modifications[:5])
            parts.append(f"files touched: {paths}")
        if trajectory.test_results:
            tests = ", ".join(result.command for result in trajectory.test_results[:3])
            parts.append(f"tests: {tests}")
        structured = getattr(trajectory.task_metadata, "structured_experience", {})
        if isinstance(structured, dict) and structured:
            payload: dict[str, Any] = structured
            parts.append(
                "structured_experience: "
                + json.dumps(payload, ensure_ascii=False, sort_keys=True)
            )
        return "\n".join(parts)
