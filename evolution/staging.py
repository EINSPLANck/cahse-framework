from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mewcode.evolution.extractor import SkillCandidate


@dataclass
class StagedSkill:
    candidate: SkillCandidate
    stage_dir: Path
    manifest_path: Path
    report_json_path: Path
    report_md_path: Path
    proposed_skill_path: Path
    live_skill_path: Path
