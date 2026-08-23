from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from mewcode.evolution.evaluator import EvaluationResult
from mewcode.evolution.trajectory.schema import TaskTrajectory


def _slugify(text: str, fallback: str = "coding-repair-skill") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        slug = fallback
    parts = slug.split("-")[:5]
    return "-".join(parts)


def _yaml_quote(value: str) -> str:
    return json.dumps(value)


@dataclass
class SkillCandidate:
    skill_name: str
    description: str
    applicable_scenario: str
    execution_procedure: list[str]
    confidence_score: float
    source_trajectory_id: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_skillopt_markdown(self) -> str:
        lines = [
            f"# {self.skill_name}",
            "",
            self.description,
            "",
            f"- applicable scenario: {self.applicable_scenario}",
            f"- confidence score: {self.confidence_score:.2f}",
            f"- source trajectory: {self.source_trajectory_id}",
            "",
            "## Execution Procedure",
            "",
        ]
        for idx, step in enumerate(self.execution_procedure, start=1):
            lines.append(f"{idx}. {step}")
        lines.append("")
        return "\n".join(lines)

    def to_mewcode_skill_markdown(self) -> str:
        return "\n".join(
            [
                "---",
                f"name: {self.skill_name}",
                f"description: {_yaml_quote(self.description)}",
                "mode: inline",
                "---",
                "",
                self.to_skillopt_markdown(),
            ]
        )


class SkillExtractor:
    def extract(
        self,
        trajectory: TaskTrajectory,
        evaluation: EvaluationResult,
    ) -> SkillCandidate | None:
        if not evaluation.accepted:
            return None

        test_commands = [result.command for result in trajectory.test_results]
        modified_paths = [mod.path for mod in trajectory.file_modifications if mod.success]
        skill_name = _slugify(trajectory.task_description)
        description = (
            "Reusable coding repair procedure extracted from a successful "
            "MewCode task trajectory."
        )
        scenario = trajectory.task_description or "A similar coding task needs a safe repair."

        procedure = [
            "Restate the failing behavior and identify the smallest relevant code path.",
            "Inspect the files that define or exercise that behavior before editing.",
        ]
        if test_commands:
            procedure.append(f"Run the known validation command: `{test_commands[-1]}`.")
        if modified_paths:
            procedure.append(
                "Apply a focused patch to the relevant file set: "
                + ", ".join(modified_paths[:5])
                + "."
            )
        procedure.append("Re-run the same validation command and only finish after it passes.")
        procedure.append("Summarize the repair strategy and any remaining risk.")

        return SkillCandidate(
            skill_name=skill_name,
            description=description,
            applicable_scenario=scenario,
            execution_procedure=procedure,
            confidence_score=evaluation.soft_score,
            source_trajectory_id=trajectory.trajectory_id,
        )
