from __future__ import annotations

import hashlib

from mewcode.evolution.task_taxonomy.schema import CandidateCluster, HumanReviewPackage

DEFAULT_REVIEW_ACTIONS = [
    "assign_to_existing_label",
    "create_new_label",
    "split_cluster",
    "mark_as_noise",
]


class HumanReviewPackageBuilder:
    def from_cluster(self, cluster: CandidateCluster) -> HumanReviewPackage:
        return HumanReviewPackage(
            review_id=self._review_id(cluster),
            candidate_cluster_id=cluster.cluster_id,
            bucket_key=cluster.bucket_key,
            representative_signature=cluster.representative_signature,
            member_count=len(cluster.member_task_ids),
            uncertainty_reason=cluster.review_reason,
            suggested_actions=list(DEFAULT_REVIEW_ACTIONS),
            examples=list(cluster.examples),
        )

    @staticmethod
    def _review_id(cluster: CandidateCluster) -> str:
        digest = hashlib.sha1(cluster.cluster_id.encode("utf-8")).hexdigest()[:12]
        return f"review_{digest}"
