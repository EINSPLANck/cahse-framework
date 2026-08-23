from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path


PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from mewcode.evolution.skillopt_adapter import SkillOptAdapter
from mewcode.evolution.task.schema import TaskMetadata
from mewcode.evolution.task.task_analyzer import TaskAnalyzer
from mewcode.evolution.trajectory.storage import TrajectoryStorage
from mewcode.evolution.trajectory.schema import (
    FileModification,
    RepositoryInfo,
    TaskTrajectory,
    TestExecutionResult as MewTestExecutionResult,
)


def test_task_analyzer_builds_execution_context_from_memory_before_truncation() -> None:
    analyzer = TaskAnalyzer()
    builder = getattr(analyzer, "build_execution_context", None)

    assert callable(builder)

    context = builder(
        "请修复登录报错",
        memory_context="project memory: auth/login.py owns the login flow",
        active_skills={"debug": "debugging guidance"},
        max_chars=120,
    )

    assert "请修复登录报错" in context
    assert "auth/login.py" in context
    assert len(context) <= 120


def test_skillopt_record_uses_post_execution_problem_answer_and_structured_experience() -> None:
    trajectory = TaskTrajectory(
        task_description="Fix failing checkout validation.",
        repository=RepositoryInfo(work_dir="repo"),
        session_id="session-1",
    )
    trajectory.file_modifications.append(
        FileModification(path="src/checkout.py", operation="edit", success=True)
    )
    trajectory.test_results.append(
        MewTestExecutionResult(
            command="pytest tests/test_checkout.py",
            output="1 passed",
            exit_code=0,
            passed=True,
        )
    )
    trajectory.mark_completed(
        success=True,
        final_message="Fixed checkout validation and verified the focused tests.",
    )

    synthesizer = getattr(TaskAnalyzer(), "synthesize_experience", None)
    assert callable(synthesizer)

    trajectory.task_metadata = synthesizer(trajectory)
    record = SkillOptAdapter().to_task_record(trajectory)

    assert record.intent == "Fix failing checkout validation in src/checkout.py"
    assert "Changed files: src/checkout.py" in record.attempted_solution
    assert "pytest tests/test_checkout.py" in record.attempted_solution
    assert record.reference_kind == "rubric"
    assert isinstance(record.judge, dict)
    assert "src/checkout.py" in record.reference
    assert "pytest tests/test_checkout.py" in record.reference
    assert '"schema_version": "mewcode.task_experience.v1"' in record.context_excerpt
    assert "skillopt-compatible" in record.tags

def test_trajectory_storage_load_returns_final_synthesized_snapshot() -> None:
    work_dir = Path(__file__).parent / ".tmp_storage" / uuid.uuid4().hex
    try:
        trajectory = TaskTrajectory(
            task_description="Fix persisted metadata.",
            repository=RepositoryInfo(work_dir=str(work_dir)),
        )
        trajectory.task_metadata = TaskMetadata(
            task_type="unknown",
            task_description="Fix persisted metadata.",
            target_component="",
        )

        storage = TrajectoryStorage(str(work_dir))
        storage.start(trajectory)
        trajectory.task_metadata = TaskMetadata(
            task_type="bug_fix",
            task_description="Fix persisted metadata in evolution/trajectory/storage.py",
            target_component="evolution/trajectory/storage.py",
        )
        trajectory.mark_completed(success=True, final_message="done")
        storage.finalize(trajectory, keep=True)

        loaded = storage.load(trajectory.trajectory_id)

        assert (
            loaded.task_metadata.task_description
            == "Fix persisted metadata in evolution/trajectory/storage.py"
        )
    finally:
        shutil.rmtree(work_dir.parent, ignore_errors=True)

