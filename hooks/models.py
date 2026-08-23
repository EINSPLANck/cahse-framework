# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mewcode.hooks.conditions import ConditionGroup


@dataclass
class Action:
    type: str
    command: str = ""
    message: str = ""
    url: str = ""
    method: str = "POST"
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    prompt: str = ""
    timeout: int = 30


@dataclass
class ActionResult:
    output: str = ""
    success: bool = True


@dataclass
class Hook:
    id: str
    event: str
    action: Action
    condition: ConditionGroup | None = None
    reject: bool = False
    once: bool = False
    async_exec: bool = False
    executed: bool = False


    def should_run(self) -> bool:
        if self.once and self.executed:
            return False
        return True


    def mark_executed(self) -> None:
        self.executed = True


@dataclass
class HookContext:
    event_name: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    file_path: str = ""
    message: str = ""
    error: str = ""
    tool_call_id: str = ""
    output: str = ""
    is_error: bool = False
    elapsed: float = 0.0
    session_id: str = ""
    task_description: str = ""
    active_skills: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_field(self, name: str) -> str:
        if name == "tool":
            return self.tool_name
        if name == "event":
            return self.event_name
        if name == "output":
            return self.output
        if name == "error":
            return self.error
        if name == "session_id":
            return self.session_id
        if name == "task_description":
            return self.task_description
        if name == "tool_call_id":
            return self.tool_call_id
        if name.startswith("args."):
            key = name[5:]
            value = self.tool_args.get(key, "")
            return str(value) if value else ""
        if name.startswith("metadata."):
            key = name[9:]
            value = self.metadata.get(key, "")
            return str(value) if value else ""
        return ""

    def expand(self, template: str) -> str:
        result = template
        result = result.replace("$EVENT", self.event_name)
        result = result.replace("$TOOL_NAME", self.tool_name)
        result = result.replace("$TOOL_CALL_ID", self.tool_call_id)
        result = result.replace("$FILE_PATH", self.file_path)
        result = result.replace("$MESSAGE", self.message)
        result = result.replace("$ERROR", self.error)
        result = result.replace("$OUTPUT", self.output)
        result = result.replace("$SESSION_ID", self.session_id)
        result = result.replace("$TASK_DESCRIPTION", self.task_description)
        for key, value in self.tool_args.items():
            result = result.replace(f"$TOOL_ARGS.{key}", str(value))
        for key, value in self.metadata.items():
            result = result.replace(f"$METADATA.{key}", str(value))
        return result


class ToolRejectedError(Exception):
    def __init__(self, tool: str, reason: str, hook_id: str) -> None:
        self.tool = tool
        self.reason = reason
        self.hook_id = hook_id
        super().__init__(f"Tool '{tool}' rejected by hook '{hook_id}': {reason}")
