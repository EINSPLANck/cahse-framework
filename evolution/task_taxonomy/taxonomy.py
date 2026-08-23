from __future__ import annotations

import json
from pathlib import Path

from mewcode.evolution.task_taxonomy.schema import NormalizedLabel, ProblemSignature


class TaskTaxonomyRegistry:
    def __init__(
        self,
        labels: list[NormalizedLabel],
        *,
        taxonomy_version: str = "",
    ) -> None:
        self.taxonomy_version = taxonomy_version
        self.labels = labels
        self._by_id = {label.label_id: label for label in labels}

    @classmethod
    def load(cls, path: str | Path) -> "TaskTaxonomyRegistry":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_labels = data.get("labels", [])
        if not isinstance(raw_labels, list):
            raise ValueError("taxonomy labels must be an array")
        labels = [
            NormalizedLabel.from_dict(item)
            for item in raw_labels
            if isinstance(item, dict)
        ]
        return cls(labels, taxonomy_version=str(data.get("taxonomy_version", "")))

    def get(self, label_id: str) -> NormalizedLabel | None:
        return self._by_id.get(label_id)

    def compatible_labels(self, signature: ProblemSignature) -> list[NormalizedLabel]:
        return [
            label
            for label in self.labels
            if label.status == "active"
            and label.operation == signature.operation
            and label.domain == signature.domain
        ]
