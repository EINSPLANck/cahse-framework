from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


AssignmentStatus = Literal["auto_assigned", "needs_review", "unassigned"]


@dataclass
class ProblemSignature:
    task_family: str
    problem_pattern: str
    operation: str
    domain: str
    evidence_focus: list[str] = field(default_factory=list)
    failure_mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SignatureEncoding:
    bucket_key: str
    family_pattern_text: str
    evidence_text: str
    signature_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedLabel:
    label_id: str
    operation: str
    domain: str
    task_family: str
    problem_pattern: str
    definition: str = ""
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NormalizedLabel":
        return cls(
            label_id=str(data.get("label_id", "")),
            operation=str(data.get("operation", "")),
            domain=str(data.get("domain", "")),
            task_family=str(data.get("task_family", "")),
            problem_pattern=str(data.get("problem_pattern", "")),
            definition=str(data.get("definition", "")),
            status=str(data.get("status", "active")),
        )


@dataclass
class LabelCandidate:
    label_id: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LabelAssignment:
    status: AssignmentStatus
    normalized_label: str = ""
    score: float = 0.0
    margin: float = 0.0
    taxonomy_version: str = ""
    reason: str = ""
    top_candidates: list[LabelCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["top_candidates"] = [item.to_dict() for item in self.top_candidates]
        return data


@dataclass
class UnknownTaskRecord:
    task_id: str
    signature: ProblemSignature
    assignment: LabelAssignment
    generated_problem: str = ""
    raw_problem_excerpt: str = ""
    changed_files: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["signature"] = self.signature.to_dict()
        data["assignment"] = self.assignment.to_dict()
        return data


@dataclass
class ClusterExample:
    task_id: str
    generated_problem: str = ""
    raw_problem_excerpt: str = ""
    changed_files: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateCluster:
    cluster_id: str
    bucket_key: str
    representative_signature: ProblemSignature
    member_task_ids: list[str]
    cluster_confidence: float
    review_reason: str = ""
    examples: list[ClusterExample] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["representative_signature"] = self.representative_signature.to_dict()
        data["examples"] = [example.to_dict() for example in self.examples]
        return data


@dataclass
class ClusterResult:
    clusters: list[CandidateCluster] = field(default_factory=list)
    noise_task_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clusters": [cluster.to_dict() for cluster in self.clusters],
            "noise_task_ids": list(self.noise_task_ids),
        }


@dataclass
class HumanReviewPackage:
    review_id: str
    candidate_cluster_id: str
    bucket_key: str
    representative_signature: ProblemSignature
    member_count: int
    uncertainty_reason: str
    suggested_actions: list[str]
    examples: list[ClusterExample] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "candidate_cluster_id": self.candidate_cluster_id,
            "bucket_key": self.bucket_key,
            "representative_signature": self.representative_signature.to_dict(),
            "member_count": self.member_count,
            "uncertainty_reason": self.uncertainty_reason,
            "suggested_actions": list(self.suggested_actions),
            "examples": [example.to_dict() for example in self.examples],
        }

