from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from mewcode.evolution.evaluator import TrajectoryEvaluator
from mewcode.evolution.evidence import EvidenceLog
from mewcode.evolution.extractor import SkillExtractor
from mewcode.evolution.repository import SkillRepository
from mewcode.evolution.skillopt_adapter import SkillOptAdapter
from mewcode.evolution.trajectory.collector import TrajectoryCollector
from mewcode.evolution.trajectory.schema import TaskTrajectory
from mewcode.evolution.trajectory.storage import TrajectoryStorage

log = logging.getLogger(__name__)


class EvolutionManager:
    def __init__(self, work_dir: str, session_id: str = "") -> None:
        self.work_dir = work_dir
        self.collector = TrajectoryCollector(work_dir=work_dir, session_id=session_id)
        self.storage = TrajectoryStorage(work_dir=work_dir)
        self.evaluator = TrajectoryEvaluator()
        self.extractor = SkillExtractor()
        self.repository = SkillRepository(work_dir=work_dir)
        self.adapter = SkillOptAdapter(self.evaluator)
        self.evidence = EvidenceLog(
            Path(work_dir) / ".skillopt-sleep" / "evidence.jsonl"
        )
        self._tasks: set[asyncio.Task[None]] = set()

    def set_session_id(self, session_id: str) -> None:
        self.collector.session_id = session_id
        if self.collector.current is not None:
            self.collector.current.session_id = session_id

    def start_task(
        self,
        task_description: str,
        *,
        execution_context: str = "",
    ) -> TaskTrajectory:
        return self.collector.start_task(
            task_description, execution_context=execution_context
        )

    def record_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        self.collector.record_tool_call(tool_call_id, tool_name, arguments)

    def record_tool_result(
        self,
        tool_call_id: str,
        tool_name: str,
        output: str,
        is_error: bool,
        elapsed: float,
    ) -> None:
        self.collector.record_tool_result(
            tool_call_id,
            tool_name,
            output,
            is_error,
            elapsed,
        )

    def finish_task(
        self,
        success: bool | None,
        final_message: str = "",
    ) -> TaskTrajectory:
        trajectory = self.collector.finish_task(success, final_message)
        self._submit_background_job(trajectory)
        self.collector.clear()
        return trajectory

    def _submit_background_job(self, trajectory: TaskTrajectory) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._process_trajectory(trajectory))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _process_trajectory(self, trajectory: TaskTrajectory) -> None:
        try:
            evaluation = self.evaluator.evaluate(trajectory)
            replay = self.adapter.to_replay_result(trajectory, evaluation)
            self.evidence.append(
                stage="gate",
                event="trajectory_evaluated",
                trajectory_id=trajectory.trajectory_id,
                replay=replay.to_dict(),
                accepted=evaluation.accepted,
            )
            if not evaluation.accepted:
                return

            path = self.storage.save(trajectory)
            digest = self.adapter.to_session_digest(trajectory)
            task_record = self.adapter.to_task_record(trajectory)
            self.evidence.append(
                stage="harvest",
                event="trajectory_persisted",
                trajectory_id=trajectory.trajectory_id,
                path=str(path),
                session_digest=digest.to_dict(),
                task_record=task_record.to_dict(),
            )

            candidate = self.extractor.extract(trajectory, evaluation)
            if candidate is None:
                return
            staged = self.repository.stage_candidate(candidate, evaluation)
            self.evidence.append(
                stage="stage",
                event="skill_staged",
                trajectory_id=trajectory.trajectory_id,
                skill_name=candidate.skill_name,
                proposed_skill_path=str(staged.proposed_skill_path),
            )
        except Exception as exc:
            log.debug("Evolution background job failed: %s", exc)

    async def wait_for_pending(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
