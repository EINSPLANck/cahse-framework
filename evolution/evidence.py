from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_SENSITIVE_KEY_PARTS = ("api_key", "token", "secret", "password", "credential")


class EvidenceLog:
    def __init__(self, path: Path, max_value_chars: int = 4000) -> None:
        self.path = path
        self.max_value_chars = max_value_chars
        self._seq = self._read_existing_count()

    def append(self, stage: str, event: str, **payload: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq += 1
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "stage": stage,
            "event": event,
            "seq": self._seq,
        }
        record.update(self._sanitize_mapping(payload))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    def _read_existing_count(self) -> int:
        if not self.path.exists():
            return 0
        try:
            return len(self.path.read_text(encoding="utf-8").splitlines())
        except OSError:
            return 0

    def _sanitize_mapping(self, data: dict[str, Any]) -> dict[str, Any]:
        return {key: self._sanitize_value(key, value) for key, value in data.items()}

    def _sanitize_value(self, key: str, value: Any) -> Any:
        key_lower = key.lower()
        if any(part in key_lower for part in _SENSITIVE_KEY_PARTS):
            return "[redacted]"
        if isinstance(value, str):
            if len(value) > self.max_value_chars:
                return value[: self.max_value_chars] + "..."
            return value
        if isinstance(value, dict):
            return {
                str(k): self._sanitize_value(str(k), v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self._sanitize_value(key, item) for item in value]
        return value
