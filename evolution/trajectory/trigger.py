from __future__ import annotations

from dataclasses import dataclass


_CODING_KEYWORDS = (
    "bug",
    "fix",
    "error",
    "crash",
    "pytest",
    "test",
    "refactor",
    "code",
    "implement",
    "修改",
    "修复",
    "报错",
    "失败",
    "测试",
    "重构",
    "实现",
)


@dataclass
class TrajectoryTrigger:
    enabled: bool = True

    def should_start(
        self,
        task_description: str,
        *,
        has_active_session: bool,
    ) -> bool:
        if not self.enabled or has_active_session:
            return False
        text = (task_description or "").strip()
        if not text:
            return False
        lowered = text.lower()
        return any(keyword in lowered or keyword in text for keyword in _CODING_KEYWORDS)
