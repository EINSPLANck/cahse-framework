from __future__ import annotations

import json
from pathlib import Path

from mewcode.evolution.trajectory.schema import (
    TaskTrajectory,
    TrajectoryEvent,
)


class TrajectoryStorage:
    def __init__(self, work_dir: str, base_dir: str = ".mewcode/evolution") -> None:
        self.work_dir = Path(work_dir)
        self.base_dir = self.work_dir / base_dir
        self.trajectories_dir = self.base_dir / "trajectories"
        self.tmp_dir = self.trajectories_dir / "tmp"
        self.validated_dir = self.trajectories_dir / "validated"

    def start(self, trajectory: TaskTrajectory) -> Path:
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        path = self._tmp_path(trajectory.trajectory_id)
        if path.exists():
            path.unlink()
        snapshot = TrajectoryEvent(
            trajectory_id=trajectory.trajectory_id,
            event_type="trajectory_snapshot",
            payload=trajectory.to_dict(),
            session_id=trajectory.session_id,
            source_skills=trajectory.active_skills_at_start,
            source_type="active_skill_context" if trajectory.active_skills_at_start else "unknown",
        )
        self._append_jsonl(path, snapshot.to_dict())
        return path

    def append_event(self, trajectory_id: str, event: TrajectoryEvent) -> Path:
        path = self._tmp_path(trajectory_id)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self._append_jsonl(path, event.to_dict())
        return path

    def finalize(self, trajectory: TaskTrajectory, *, keep: bool) -> Path:
        temp_path = self._tmp_path(trajectory.trajectory_id)
        if keep:
            source_type = "active_skill_context" if trajectory.active_skills_at_start else "unknown"
            self.append_event(
                trajectory.trajectory_id,
                TrajectoryEvent(
                    trajectory_id=trajectory.trajectory_id,
                    event_type="trajectory_snapshot",
                    payload=trajectory.to_dict(),
                    session_id=trajectory.session_id,
                    source_skills=trajectory.active_skills_at_start,
                    source_type=source_type,
                ),
            )
            self.append_event(
                trajectory.trajectory_id,
                TrajectoryEvent(
                    trajectory_id=trajectory.trajectory_id,
                    event_type="task_end",
                    payload={
                        "final_message": trajectory.final_message,
                        "outcome": trajectory.outcome.to_dict()
                        if hasattr(trajectory.outcome, "to_dict")
                        else trajectory.outcome.__dict__,
                        "task_metadata": trajectory.task_metadata.to_dict(),
                    },
                    session_id=trajectory.session_id,
                    source_skills=trajectory.active_skills_at_start,
                    source_type=source_type,
                ),
            )
            self.validated_dir.mkdir(parents=True, exist_ok=True)
            validated_path = self._validated_path(trajectory.trajectory_id)
            if validated_path.exists():
                validated_path.unlink()
            temp_path.replace(validated_path)
            return validated_path
        self.delete(trajectory.trajectory_id)
        return temp_path

    def delete(self, trajectory_id: str) -> None:
        for path in (self._tmp_path(trajectory_id), self._validated_path(trajectory_id)):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass

    def save(self, trajectory: TaskTrajectory) -> Path:
        self.start(trajectory)
        return self.finalize(trajectory, keep=True)

    def load(self, trajectory_id: str) -> TaskTrajectory:
        path = self._validated_path(trajectory_id)
        if not path.exists():
            legacy = self.trajectories_dir / f"{trajectory_id}.json"
            if legacy.exists():
                return TaskTrajectory.from_dict(
                    json.loads(legacy.read_text(encoding="utf-8"))
                )
            path = self._tmp_path(trajectory_id)
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not rows:
            raise FileNotFoundError(f"No trajectory data for {trajectory_id}")
        snapshot_payload = None
        for row in rows:
            if row.get("event_type") == "trajectory_snapshot":
                snapshot_payload = row.get("payload", {})
        if snapshot_payload is not None:
            return TaskTrajectory.from_dict(snapshot_payload)
        return TaskTrajectory.from_dict(rows[0])

    def read_events(self, trajectory_id: str) -> list[TrajectoryEvent]:
        path = self._validated_path(trajectory_id)
        if not path.exists():
            path = self._tmp_path(trajectory_id)
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return [TrajectoryEvent.from_dict(row) for row in rows]

    def _tmp_path(self, trajectory_id: str) -> Path:
        return self.tmp_dir / f"{trajectory_id}.jsonl"

    def _validated_path(self, trajectory_id: str) -> Path:
        return self.validated_dir / f"{trajectory_id}.jsonl"

    @staticmethod
    def _append_jsonl(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=True) + "\n")
