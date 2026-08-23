from __future__ import annotations

import re
from typing import Any

from mewcode.evolution.task.schema import TaskMetadata, TaskType

_PATH_RE = re.compile(
    r"(?P<path>(?:[\w.-]+[\\/])+[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|md|toml|yaml|yml|json))"
)


class TaskAnalyzer:
    def analyze(self, task_description: str, *, execution_context: str = "") -> TaskMetadata:
        text = (task_description or "").strip()
        context = (execution_context or text).strip()
        analysis_text = context or text
        lowered = analysis_text.lower()
        return TaskMetadata(
            task_type=self._infer_task_type(analysis_text, lowered),
            task_description=analysis_text[:500],
            target_component=self._infer_target_component(analysis_text),
        )

    def build_execution_context(
        self,
        task_description: str,
        *,
        memory_context: str = "",
        active_skills: dict[str, str] | None = None,
        repository_context: str = "",
        max_chars: int = 8_000,
    ) -> str:
        sections: list[str] = []
        task = (task_description or "").strip()
        if task:
            sections.append("# Task\n" + task)
        repo = (repository_context or "").strip()
        if repo:
            sections.append("# Repository Context\n" + repo)
        memory = (memory_context or "").strip()
        if memory:
            sections.append("# Memory Context\n" + memory)
        if active_skills:
            names = ", ".join(sorted(active_skills))
            if names:
                sections.append("# Active Skills\n" + names)
        context = "\n\n".join(sections).strip()
        return self._truncate_context(context, max_chars)

    def synthesize_experience(self, trajectory: Any) -> TaskMetadata:
        raw_description = str(getattr(trajectory, "task_description", "") or "").strip()
        modified_paths = self._successful_modified_paths(trajectory)
        target_component = modified_paths[0] if modified_paths else self._infer_target_component(raw_description)
        problem = self._problem_headline(raw_description)
        if target_component and target_component not in problem:
            problem = f"{problem} in {target_component}"

        analysis_text = "\n".join([raw_description, " ".join(modified_paths)]).strip()
        task_type = self._infer_task_type(analysis_text, analysis_text.lower())
        solution_answer = self._solution_answer(trajectory, problem, modified_paths)
        structured_experience = self._structured_experience(
            trajectory,
            problem,
            task_type,
            target_component,
            solution_answer,
            modified_paths,
        )
        return TaskMetadata(
            task_type=task_type,
            task_description=problem[:500],
            target_component=target_component,
            solution_answer=solution_answer,
            structured_experience=structured_experience,
        )

    def _infer_task_type(self, text: str, lowered: str) -> TaskType:
        if any(token in lowered for token in ("bug", "fix", "failure", "failed", "error", "crash")):
            return "bug_fix"
        if any(token in text for token in ("修复", "报错", "失败", "错误", "崩溃")):
            return "bug_fix"
        if any(token in lowered for token in ("test", "pytest", "unittest")):
            return "test_fix"
        if any(token in text for token in ("测试", "单测")):
            return "test_fix"
        if any(token in lowered for token in ("refactor", "cleanup", "simplify")):
            return "refactor"
        if any(token in text for token in ("重构", "整理")):
            return "refactor"
        if any(token in lowered for token in ("doc", "readme", "comment")):
            return "documentation"
        if any(token in text for token in ("文档", "注释")):
            return "documentation"
        if any(token in lowered for token in ("change", "modify", "add", "implement", "update")):
            return "code_modify"
        if any(token in text for token in ("修改", "增加", "实现", "更新")):
            return "code_modify"
        return "unknown"

    def _infer_target_component(self, text: str) -> str:
        match = _PATH_RE.search(text)
        if match:
            return match.group("path").replace("\\", "/")
        return ""

    @staticmethod
    def _truncate_context(context: str, max_chars: int) -> str:
        if max_chars <= 0:
            return ""
        if len(context) <= max_chars:
            return context
        marker = "\n\n...\n"
        if max_chars <= len(marker) + 20:
            return context[:max_chars]
        head_len = max_chars // 2
        tail_len = max_chars - head_len - len(marker)
        return context[:head_len].rstrip() + marker + context[-tail_len:].lstrip()

    @staticmethod
    def _successful_modified_paths(trajectory: Any) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for modification in getattr(trajectory, "file_modifications", []) or []:
            path = str(getattr(modification, "path", "") or "").replace("\\", "/")
            if not path or path in seen or getattr(modification, "success", True) is False:
                continue
            seen.add(path)
            paths.append(path)
        return paths

    @staticmethod
    def _problem_headline(raw_description: str) -> str:
        for line in raw_description.splitlines():
            headline = line.strip().strip("# ").strip()
            if headline:
                return headline.rstrip(". ")
        return "Complete coding task"

    @staticmethod
    def _solution_answer(trajectory: Any, problem: str, modified_paths: list[str]) -> str:
        tests = [str(result.command) for result in getattr(trajectory, "test_results", []) or [] if str(result.command)]
        latest_test = tests[-1] if tests else "none recorded"
        outcome = "success" if getattr(trajectory, "final_success_status", None) is True else "unknown"
        final_message = str(getattr(trajectory, "final_message", "") or "").strip()
        lines = [
            f"Problem: {problem}",
            "Changed files: " + (", ".join(modified_paths) if modified_paths else "none recorded"),
            "Validation: " + latest_test,
            "Outcome: " + outcome,
        ]
        if final_message:
            lines.extend(["", "Final answer:", final_message])
        return "\n".join(lines)

    @staticmethod
    def _structured_experience(
        trajectory: Any,
        problem: str,
        task_type: TaskType,
        target_component: str,
        solution_answer: str,
        modified_paths: list[str],
    ) -> dict[str, Any]:
        tests = []
        for result in getattr(trajectory, "test_results", []) or []:
            tests.append(
                {
                    "command": str(getattr(result, "command", "") or ""),
                    "passed": bool(getattr(result, "passed", False)),
                    "exit_code": int(getattr(result, "exit_code", 0) or 0),
                }
            )
        tool_sequence = [str(getattr(record, "tool_name", "") or "") for record in getattr(trajectory, "tool_calls", []) or []]
        execution_context = str(getattr(trajectory, "metadata", {}).get("execution_context", "") or "")
        return {
            "schema_version": "mewcode.task_experience.v1",
            "problem": {
                "description": problem,
                "task_type": task_type,
                "component": target_component,
            },
            "solution": {
                "answer": solution_answer,
                "changed_files": modified_paths,
                "tests": tests,
                "success": getattr(trajectory, "final_success_status", None) is True,
            },
            "trajectory": {
                "id": str(getattr(trajectory, "trajectory_id", "") or ""),
                "session_id": str(getattr(trajectory, "session_id", "") or ""),
                "tool_sequence": [name for name in tool_sequence if name],
                "execution_context_excerpt": execution_context[:2000],
            },
            "skillopt": {
                "compatible": True,
                "intent_field": "problem.description",
                "attempted_solution_field": "solution.answer",
                "reference_field": "solution.tests",
            },
        }
