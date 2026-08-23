from __future__ import annotations

import hashlib
from collections import defaultdict

from mewcode.evolution.task_taxonomy.encoder import SignatureEncoder
from mewcode.evolution.task_taxonomy.schema import (
    CandidateCluster,
    ClusterExample,
    ClusterResult,
    UnknownTaskRecord,
)

_REVIEWABLE_STATUSES = {"unassigned", "needs_review"}


class UnknownTaskClusterer:
    def __init__(
        self,
        *,
        min_cluster_size: int = 3,
        similarity_threshold: float = 0.45,
        encoder: SignatureEncoder | None = None,
    ) -> None:
        self.min_cluster_size = max(1, min_cluster_size)
        self.similarity_threshold = similarity_threshold
        self.encoder = encoder or SignatureEncoder()

    def cluster(self, records: list[UnknownTaskRecord]) -> ClusterResult:
        buckets: dict[str, list[UnknownTaskRecord]] = defaultdict(list)
        for record in records:
            if record.assignment.status not in _REVIEWABLE_STATUSES:
                continue
            bucket_key = self.encoder.encode(record.signature).bucket_key
            buckets[bucket_key].append(record)

        clusters: list[CandidateCluster] = []
        noise_task_ids: list[str] = []
        for bucket_key, bucket_records in buckets.items():
            groups = self._cluster_bucket(bucket_records)
            for group in groups:
                if len(group) < self.min_cluster_size:
                    noise_task_ids.extend(record.task_id for record in group)
                    continue
                clusters.append(self._to_candidate_cluster(bucket_key, group))
        return ClusterResult(clusters=clusters, noise_task_ids=noise_task_ids)

    def _cluster_bucket(self, records: list[UnknownTaskRecord]) -> list[list[UnknownTaskRecord]]:
        groups: list[list[UnknownTaskRecord]] = []
        for record in records:
            for group in groups:
                similarity = self._signature_similarity(record, group[0])
                if similarity >= self.similarity_threshold:
                    group.append(record)
                    break
            else:
                groups.append([record])
        return groups

    def _to_candidate_cluster(
        self,
        bucket_key: str,
        records: list[UnknownTaskRecord],
    ) -> CandidateCluster:
        representative = records[0]
        similarities = [
            self._signature_similarity(record, representative)
            for record in records[1:]
        ]
        confidence = sum(similarities) / len(similarities) if similarities else 1.0
        return CandidateCluster(
            cluster_id=self._cluster_id(bucket_key, records),
            bucket_key=bucket_key,
            representative_signature=representative.signature,
            member_task_ids=[record.task_id for record in records],
            cluster_confidence=round(confidence, 4),
            review_reason="unassigned signatures formed a similar residual cluster",
            examples=[self._example(record) for record in records[:5]],
        )

    def _signature_similarity(self, left: UnknownTaskRecord, right: UnknownTaskRecord) -> float:
        left_tokens = self._semantic_tokens(left)
        right_tokens = self._semantic_tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    def _semantic_tokens(self, record: UnknownTaskRecord) -> set[str]:
        encoded = self.encoder.encode(record.signature)
        return set(encoded.family_pattern_text.split())

    @staticmethod
    def _cluster_id(bucket_key: str, records: list[UnknownTaskRecord]) -> str:
        digest = hashlib.sha1(
            (bucket_key + "::" + "::".join(record.task_id for record in records)).encode("utf-8")
        ).hexdigest()[:12]
        safe_bucket = bucket_key.replace("::", "_").replace("/", "_")
        return f"candidate_cluster_{safe_bucket}_{digest}"

    @staticmethod
    def _example(record: UnknownTaskRecord) -> ClusterExample:
        return ClusterExample(
            task_id=record.task_id,
            generated_problem=record.generated_problem,
            raw_problem_excerpt=record.raw_problem_excerpt,
            changed_files=list(record.changed_files),
            tests=list(record.tests),
        )
