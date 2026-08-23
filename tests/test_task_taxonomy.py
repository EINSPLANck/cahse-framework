from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path


PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from mewcode.evolution.task_taxonomy import (
    LabelAssignment,
    ProblemSignature,
    SignatureEncoder,
    TaskTaxonomyRegistry,
    TaxonomyAssigner,
    HumanReviewPackageBuilder,
    UnknownTaskClusterer,
    UnknownTaskRecord,
)


TAXONOMY_PAYLOAD = {
    "taxonomy_version": "task_taxonomy_v1",
    "labels": [
        {
            "label_id": "web_security.authentication.token_lifecycle.bug_fix",
            "operation": "bug_fix",
            "domain": "web_security",
            "task_family": "authentication_debugging",
            "problem_pattern": "token_lifecycle_failure",
            "definition": "修复认证 token 生命周期问题。",
            "status": "active",
        }
    ],
}


def _write_taxonomy_file(payload: dict) -> Path:
    work_dir = Path(__file__).parent / ".tmp_taxonomy" / uuid.uuid4().hex
    work_dir.mkdir(parents=True, exist_ok=True)
    taxonomy_path = work_dir / "task_taxonomy.json"
    taxonomy_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return taxonomy_path


def _cleanup_taxonomy_tmp() -> None:
    shutil.rmtree(Path(__file__).parent / ".tmp_taxonomy", ignore_errors=True)


def test_signature_encoder_builds_stable_cluster_encoding() -> None:
    signature = ProblemSignature(
        task_family="authentication_debugging",
        problem_pattern="token_lifecycle_failure",
        operation="bug_fix",
        domain="web_security",
        evidence_focus=["auth_middleware", "token_refresh"],
        failure_mode="expired_token_not_refreshed",
    )

    encoded = SignatureEncoder().encode(signature)

    assert encoded.bucket_key == "bug_fix::web_security"
    assert (
        encoded.family_pattern_text
        == "authentication debugging token lifecycle failure expired token not refreshed"
    )
    assert encoded.evidence_text == "auth middleware token refresh"
    assert (
        encoded.signature_key
        == "bug_fix.web_security.authentication_debugging.token_lifecycle_failure"
    )


def test_taxonomy_assigner_auto_assigns_matching_fixed_label() -> None:
    taxonomy_path = _write_taxonomy_file(TAXONOMY_PAYLOAD)
    try:
        registry = TaskTaxonomyRegistry.load(taxonomy_path)
        signature = ProblemSignature(
            task_family="authentication_debugging",
            problem_pattern="token_lifecycle_failure",
            operation="bug_fix",
            domain="web_security",
        )

        assignment = TaxonomyAssigner(registry).assign(signature)

        assert assignment.status == "auto_assigned"
        assert (
            assignment.normalized_label
            == "web_security.authentication.token_lifecycle.bug_fix"
        )
        assert assignment.score >= 0.82
        assert assignment.taxonomy_version == "task_taxonomy_v1"
    finally:
        _cleanup_taxonomy_tmp()


def test_taxonomy_assigner_defers_unknown_signature_for_review() -> None:
    taxonomy_path = _write_taxonomy_file(TAXONOMY_PAYLOAD)
    try:
        registry = TaskTaxonomyRegistry.load(taxonomy_path)
        signature = ProblemSignature(
            task_family="cache_debugging",
            problem_pattern="stale_distributed_cache",
            operation="bug_fix",
            domain="backend_infrastructure",
        )

        assignment = TaxonomyAssigner(registry).assign(signature)

        assert assignment.status == "unassigned"
        assert assignment.normalized_label == ""
        assert "no compatible label" in assignment.reason
    finally:
        _cleanup_taxonomy_tmp()


def test_unknown_task_clusterer_groups_only_unassigned_similar_tasks() -> None:
    records = [
        UnknownTaskRecord(
            task_id="known-auth",
            signature=ProblemSignature(
                task_family="authentication_debugging",
                problem_pattern="token_lifecycle_failure",
                operation="bug_fix",
                domain="web_security",
            ),
            assignment=LabelAssignment(
                status="auto_assigned",
                normalized_label="web_security.authentication.token_lifecycle.bug_fix",
            ),
            generated_problem="Known auth token lifecycle task",
        ),
        UnknownTaskRecord(
            task_id="unknown-auth-1",
            signature=ProblemSignature(
                task_family="authentication_debugging",
                problem_pattern="token_lifecycle_failure",
                operation="bug_fix",
                domain="web_security",
                failure_mode="expired_token_not_refreshed",
            ),
            assignment=LabelAssignment(status="unassigned"),
            generated_problem="Access token expires and refresh does not happen.",
        ),
        UnknownTaskRecord(
            task_id="unknown-auth-2",
            signature=ProblemSignature(
                task_family="authentication_debugging",
                problem_pattern="token_refresh_failure",
                operation="bug_fix",
                domain="web_security",
                failure_mode="expired_token_not_renewed",
            ),
            assignment=LabelAssignment(status="needs_review"),
            generated_problem="Expired token is not renewed during authenticated calls.",
        ),
        UnknownTaskRecord(
            task_id="unknown-oauth",
            signature=ProblemSignature(
                task_family="oauth_integration",
                problem_pattern="redirect_url_mismatch",
                operation="bug_fix",
                domain="web_security",
            ),
            assignment=LabelAssignment(status="unassigned"),
            generated_problem="OAuth callback URL is generated incorrectly.",
        ),
    ]

    result = UnknownTaskClusterer(min_cluster_size=2, similarity_threshold=0.35).cluster(records)

    assert len(result.clusters) == 1
    cluster = result.clusters[0]
    assert cluster.bucket_key == "bug_fix::web_security"
    assert cluster.member_task_ids == ["unknown-auth-1", "unknown-auth-2"]
    assert cluster.representative_signature.task_family == "authentication_debugging"
    assert "known-auth" not in cluster.member_task_ids
    assert result.noise_task_ids == ["unknown-oauth"]


def test_human_review_package_builder_exports_cluster_review_payload() -> None:
    records = [
        UnknownTaskRecord(
            task_id="unknown-auth-1",
            signature=ProblemSignature(
                task_family="authentication_debugging",
                problem_pattern="token_lifecycle_failure",
                operation="bug_fix",
                domain="web_security",
                failure_mode="expired_token_not_refreshed",
            ),
            assignment=LabelAssignment(status="unassigned"),
            generated_problem="Access token expires and refresh does not happen.",
            raw_problem_excerpt="User reports expired access token is never refreshed.",
            changed_files=["auth/middleware.py"],
            tests=["pytest tests/auth/test_token_refresh.py"],
        ),
        UnknownTaskRecord(
            task_id="unknown-auth-2",
            signature=ProblemSignature(
                task_family="authentication_debugging",
                problem_pattern="token_refresh_failure",
                operation="bug_fix",
                domain="web_security",
                failure_mode="expired_token_not_renewed",
            ),
            assignment=LabelAssignment(status="needs_review"),
            generated_problem="Expired token is not renewed during authenticated calls.",
        ),
    ]
    cluster = UnknownTaskClusterer(min_cluster_size=2, similarity_threshold=0.35).cluster(records).clusters[0]

    package = HumanReviewPackageBuilder().from_cluster(cluster)
    payload = package.to_dict()

    assert package.review_id.startswith("review_")
    assert package.candidate_cluster_id == cluster.cluster_id
    assert package.bucket_key == "bug_fix::web_security"
    assert package.member_count == 2
    assert package.suggested_actions == [
        "assign_to_existing_label",
        "create_new_label",
        "split_cluster",
        "mark_as_noise",
    ]
    assert "unassigned signatures" in package.uncertainty_reason
    assert payload["representative_signature"]["task_family"] == "authentication_debugging"
    assert payload["examples"][0]["changed_files"] == ["auth/middleware.py"]

