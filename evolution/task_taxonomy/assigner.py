from __future__ import annotations

from difflib import SequenceMatcher

from mewcode.evolution.task_taxonomy.encoder import normalize_term
from mewcode.evolution.task_taxonomy.schema import (
    LabelAssignment,
    LabelCandidate,
    NormalizedLabel,
    ProblemSignature,
)
from mewcode.evolution.task_taxonomy.taxonomy import TaskTaxonomyRegistry


class TaxonomyAssigner:
    def __init__(
        self,
        registry: TaskTaxonomyRegistry,
        *,
        auto_threshold: float = 0.82,
        review_threshold: float = 0.70,
        margin_threshold: float = 0.10,
    ) -> None:
        self.registry = registry
        self.auto_threshold = auto_threshold
        self.review_threshold = review_threshold
        self.margin_threshold = margin_threshold

    def assign(self, signature: ProblemSignature) -> LabelAssignment:
        labels = self.registry.compatible_labels(signature)
        if not labels:
            return LabelAssignment(
                status="unassigned",
                taxonomy_version=self.registry.taxonomy_version,
                reason="no compatible label for operation/domain",
            )

        scored = sorted(
            (
                LabelCandidate(label_id=label.label_id, score=self._score(signature, label))
                for label in labels
            ),
            key=lambda candidate: candidate.score,
            reverse=True,
        )
        best = scored[0]
        second_score = scored[1].score if len(scored) > 1 else 0.0
        margin = best.score - second_score
        if best.score >= self.auto_threshold and (
            len(scored) == 1 or margin >= self.margin_threshold
        ):
            return LabelAssignment(
                status="auto_assigned",
                normalized_label=best.label_id,
                score=best.score,
                margin=margin,
                taxonomy_version=self.registry.taxonomy_version,
                top_candidates=scored[:3],
            )
        if best.score >= self.review_threshold:
            return LabelAssignment(
                status="needs_review",
                normalized_label=best.label_id,
                score=best.score,
                margin=margin,
                taxonomy_version=self.registry.taxonomy_version,
                reason="label score or margin below auto assignment threshold",
                top_candidates=scored[:3],
            )
        return LabelAssignment(
            status="unassigned",
            score=best.score,
            margin=margin,
            taxonomy_version=self.registry.taxonomy_version,
            reason="top label score below review threshold",
            top_candidates=scored[:3],
        )

    @staticmethod
    def _score(signature: ProblemSignature, label: NormalizedLabel) -> float:
        family_score = _string_similarity(signature.task_family, label.task_family)
        pattern_score = _string_similarity(signature.problem_pattern, label.problem_pattern)
        return 0.20 + 0.20 + 0.25 * family_score + 0.35 * pattern_score


def _string_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_term(left), normalize_term(right)).ratio()
