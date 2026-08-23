from __future__ import annotations

import json
import re
from pathlib import Path

from mewcode.evolution.evaluator import EvaluationResult
from mewcode.evolution.extractor import SkillCandidate
from mewcode.evolution.staging import StagedSkill


_SAFE_SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class SkillRepository:
    def __init__(self, work_dir: str) -> None:
        self.work_dir = Path(work_dir)
        self.staging_root = self.work_dir / ".skillopt-sleep" / "staging"
        self.skills_root = self.work_dir / ".mewcode" / "skills"

    def stage_candidate(
        self,
        candidate: SkillCandidate,
        evaluation: EvaluationResult,
    ) -> StagedSkill:
        self._validate_skill_name(candidate.skill_name)
        stage_dir = self.staging_root / candidate.skill_name
        stage_dir.mkdir(parents=True, exist_ok=True)
        live_skill_path = (
            self.skills_root / candidate.skill_name / "SKILL.md"
        )
        proposed_skill_path = stage_dir / f"proposed_SKILL.{candidate.skill_name}.md"
        manifest_path = stage_dir / "manifest.json"
        report_json_path = stage_dir / "report.json"
        report_md_path = stage_dir / "report.md"

        proposed_skill_path.write_text(
            candidate.to_skillopt_markdown(),
            encoding="utf-8",
        )
        manifest = {
            "live_skill_path": str(live_skill_path.resolve()),
            "live_memory_path": "",
            "has_skill": live_skill_path.exists(),
            "has_memory": False,
            "accepted": False,
            "skills": [
                {
                    "skill_name": candidate.skill_name,
                    "proposed_file": proposed_skill_path.name,
                    "live_skill_path": str(live_skill_path.resolve()),
                }
            ],
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        report = {
            "candidate": candidate.to_dict(),
            "evaluation": evaluation.to_dict(),
        }
        report_json_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        report_md_path.write_text(
            self._render_report(candidate, evaluation),
            encoding="utf-8",
        )
        return StagedSkill(
            candidate=candidate,
            stage_dir=stage_dir,
            manifest_path=manifest_path,
            report_json_path=report_json_path,
            report_md_path=report_md_path,
            proposed_skill_path=proposed_skill_path,
            live_skill_path=live_skill_path,
        )

    def adopt(self, staged: StagedSkill) -> Path:
        self._validate_skill_name(staged.candidate.skill_name)
        staged.live_skill_path.parent.mkdir(parents=True, exist_ok=True)
        if staged.live_skill_path.exists():
            backup_path = staged.live_skill_path.with_suffix(".md.bak")
            backup_path.write_text(
                staged.live_skill_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        staged.live_skill_path.write_text(
            staged.candidate.to_mewcode_skill_markdown(),
            encoding="utf-8",
        )
        if staged.manifest_path.exists():
            manifest = json.loads(staged.manifest_path.read_text(encoding="utf-8"))
            manifest["accepted"] = True
            staged.manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
        return staged.live_skill_path

    @staticmethod
    def _validate_skill_name(name: str) -> None:
        if not _SAFE_SKILL_RE.fullmatch(name):
            raise ValueError(f"invalid skill name: {name}")

    @staticmethod
    def _render_report(
        candidate: SkillCandidate,
        evaluation: EvaluationResult,
    ) -> str:
        reasons = "\n".join(f"- {reason}" for reason in evaluation.reasons)
        return "\n".join(
            [
                f"# SkillOpt Proposal: {candidate.skill_name}",
                "",
                f"- accepted: {evaluation.accepted}",
                f"- hard score: {evaluation.hard_score:.2f}",
                f"- soft score: {evaluation.soft_score:.2f}",
                f"- source trajectory: {candidate.source_trajectory_id}",
                "",
                "## Reasons",
                "",
                reasons,
                "",
            ]
        )
