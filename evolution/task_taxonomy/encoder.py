from __future__ import annotations

import re

from mewcode.evolution.task_taxonomy.schema import ProblemSignature, SignatureEncoding


_SEPARATOR_RE = re.compile(r"[_./\\-]+")
_SPACE_RE = re.compile(r"\s+")


def normalize_term(value: str) -> str:
    text = _SEPARATOR_RE.sub(" ", (value or "").strip().lower())
    return _SPACE_RE.sub(" ", text).strip()


class SignatureEncoder:
    def encode(self, signature: ProblemSignature) -> SignatureEncoding:
        family = normalize_term(signature.task_family)
        pattern = normalize_term(signature.problem_pattern)
        failure_mode = normalize_term(signature.failure_mode)
        evidence_terms = [normalize_term(item) for item in signature.evidence_focus]
        evidence_terms = [item for item in evidence_terms if item]
        family_parts = [family, pattern, failure_mode]
        family_pattern_text = " ".join(item for item in family_parts if item)
        return SignatureEncoding(
            bucket_key=f"{signature.operation}::{signature.domain}",
            family_pattern_text=family_pattern_text,
            evidence_text=" ".join(evidence_terms),
            signature_key=".".join(
                [
                    signature.operation,
                    signature.domain,
                    signature.task_family,
                    signature.problem_pattern,
                ]
            ),
        )
