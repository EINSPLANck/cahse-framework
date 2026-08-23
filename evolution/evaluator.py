from __future__ import annotations

from dataclasses import asdict, dataclass

from mewcode.evolution.trajectory.schema import TaskTrajectory


@dataclass
class EvaluationResult:
    accepted: bool
    hard_score: float
    soft_score: float
    reasons: list[str]
    gate_action: str = "reject"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class TrajectoryEvaluator:
    def evaluate(self, trajectory: TaskTrajectory) -> EvaluationResult:
        outcome = getattr(trajectory, "outcome", None)
        if outcome is not None and (
            outcome.task_success is not None or outcome.test_pass is not None
        ):
            return self._evaluate_outcome(trajectory)
        return self._evaluate_legacy(trajectory)

    def _evaluate_outcome(self, trajectory: TaskTrajectory) -> EvaluationResult:
        reasons: list[str] = []
        outcome = trajectory.outcome
        task_success = outcome.task_success is True
        test_pass = outcome.test_pass is True

        if task_success:
            reasons.append("task completed")
        else:
            reasons.append("task did not complete")

        failed_tests = [
            result
            for result in trajectory.test_results
            if not result.passed or result.exit_code != 0
        ]
        if test_pass:
            if failed_tests:
                reasons.append("latest tests passed")
                reasons.append("earlier failed tests captured as debugging process")
            else:
                reasons.append("tests passed")
        else:
            reasons.append("tests did not pass")
            if trajectory.test_results:
                reasons.append("failed tests")

        soft_score = 1.0 if task_success else 0.0
        feedback = trajectory.human_feedback
        if feedback is not None:
            if feedback.rating == "positive":
                soft_score = max(soft_score, 0.9)
                reasons.append("positive human feedback")
            elif feedback.rating == "negative":
                soft_score = min(soft_score, 0.2)
                reasons.append("negative human feedback")
            else:
                reasons.append("neutral human feedback")

        accepted = task_success and test_pass and (
            feedback is None or feedback.rating != "negative"
        )
        return EvaluationResult(
            accepted=accepted,
            hard_score=1.0 if test_pass else 0.0,
            soft_score=soft_score,
            reasons=reasons,
            gate_action="accept" if accepted else "reject",
        )

    def _evaluate_legacy(self, trajectory: TaskTrajectory) -> EvaluationResult:
        reasons: list[str] = []
        task_complete = trajectory.final_success_status is True

        failed_tests = [
            result
            for result in trajectory.test_results
            if not result.passed or result.exit_code != 0
        ]
        latest_test = trajectory.test_results[-1] if trajectory.test_results else None
        if latest_test is not None:
            if latest_test.passed and latest_test.exit_code == 0:
                hard_score = 1.0
                if failed_tests:
                    reasons.append("latest tests passed")
                    reasons.append("earlier failed tests captured as debugging process")
                else:
                    reasons.append("tests passed")
            else:
                hard_score = 0.0
                reasons.append("failed tests")
        else:
            hard_score = 1.0 if task_complete else 0.0
            reasons.append("no tests recorded" if task_complete else "task incomplete")

        soft_score = 1.0 if task_complete else 0.0
        if not task_complete:
            reasons.append("task incomplete")

        feedback = trajectory.human_feedback
        if feedback is not None:
            if feedback.rating == "positive":
                soft_score = max(soft_score, 0.9)
                reasons.append("positive human feedback")
            elif feedback.rating == "negative":
                soft_score = min(soft_score, 0.2)
                reasons.append("negative human feedback")
            else:
                reasons.append("neutral human feedback")

        accepted = (
            task_complete
            and hard_score >= 1.0
            and (feedback is None or feedback.rating != "negative")
        )
        return EvaluationResult(
            accepted=accepted,
            hard_score=hard_score,
            soft_score=soft_score,
            reasons=reasons,
            gate_action="accept" if accepted else "reject",
        )


