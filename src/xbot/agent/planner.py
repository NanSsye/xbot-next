from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from xbot.agent.tool_call_parser import ToolCallParser


class PlannedToolCall(BaseModel):
    tool: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    final: str | None = None
    tool_calls: list[PlannedToolCall] = Field(default_factory=list)


class AgentPlanner:
    _REASONING_BLOCK_RE = re.compile(
        r"<\s*(think|thinking|reasoning|analysis)\s*>.*?<\s*/\s*\1\s*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    _REASONING_FENCE_RE = re.compile(
        r"```(?:think|thinking|reasoning|analysis)\s+.*?```",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def __init__(self) -> None:
        self.tool_parser = ToolCallParser()

    async def plan(self, task: str) -> list[str]:
        return [task]

    def parse_llm_response(self, content: str) -> AgentPlan:
        objects = self._extract_json_objects(content)
        parsed_calls = self.tool_parser.extract(content)
        if not objects:
            return AgentPlan(
                final=None if parsed_calls else content,
                tool_calls=[
                    PlannedToolCall(tool=call.tool, payload=call.payload)
                    for call in parsed_calls
                ],
            )
        calls = []
        final = None
        for data in objects:
            if not isinstance(data, dict):
                continue
            if data.get("tool") or data.get("name"):
                calls.append(data)
            calls.extend(data.get("tool_calls") or data.get("tools") or [])
            final = data.get("final") or data.get("answer") or final
        if parsed_calls:
            return AgentPlan(
                final=final,
                tool_calls=[
                    PlannedToolCall(tool=call.tool, payload=call.payload)
                    for call in parsed_calls
                ],
            )
        return AgentPlan(
            final=final,
            tool_calls=[
                PlannedToolCall(
                    tool=str(item.get("tool") or item.get("name")),
                    payload=item.get("payload") or item.get("arguments") or {},
                )
                for item in calls
                if isinstance(item, dict) and (item.get("tool") or item.get("name"))
            ],
        )

    def clean_final_output(self, content: str) -> str:
        text = content.strip()
        for data in reversed(self._extract_json_objects(text)):
            if isinstance(data, dict) and not (data.get("tool_calls") or data.get("tools")):
                final = data.get("final") or data.get("answer")
                if isinstance(final, str) and final.strip():
                    return self._strip_reasoning_blocks(final).strip()
        lenient_final = self._extract_lenient_final(text)
        if lenient_final:
            return self._strip_reasoning_blocks(lenient_final).strip()

        stripped = self.tool_parser.strip_blocks(text)
        stripped = self._strip_reasoning_blocks(stripped)
        if self.contains_tool_call_intent(stripped):
            return ""
        return stripped.strip()

    def contains_tool_call_intent(self, content: str) -> bool:
        return self.tool_parser.contains_intent(content)

    def is_empty_final_response(self, content: str) -> bool:
        data = self._extract_json(content)
        if not isinstance(data, dict):
            return not content.strip()
        has_tool_key = "tool_calls" in data or "tools" in data
        calls = data.get("tool_calls") or data.get("tools") or []
        final = data.get("final") if "final" in data else data.get("answer")
        return not calls and (final is None or str(final).strip() == "") and not has_tool_key

    def _extract_json(self, content: str) -> Any:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    def _extract_json_objects(self, content: str) -> list[Any]:
        text = self._strip_code_fences(content.strip())
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            return [data]

        decoder = json.JSONDecoder()
        objects = []
        index = 0
        while index < len(text):
            brace_index = text.find("{", index)
            if brace_index < 0:
                break
            try:
                data, end = decoder.raw_decode(text[brace_index:])
            except json.JSONDecodeError:
                index = brace_index + 1
                continue
            objects.append(data)
            index = brace_index + end
        return objects

    def _strip_code_fences(self, text: str) -> str:
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return text

    def _extract_lenient_final(self, content: str) -> str:
        text = self._strip_code_fences(content.strip())
        match = re.match(
            r'^\{\s*"(?:final|answer)"\s*:\s*"(.*)"\s*\}\s*$',
            text,
            flags=re.DOTALL,
        )
        if not match:
            return ""
        value = match.group(1).strip()
        try:
            return json.loads(f'"{value}"').strip()
        except json.JSONDecodeError:
            return value.replace('\\"', '"').strip()

    def _strip_reasoning_blocks(self, content: str) -> str:
        text = self._REASONING_BLOCK_RE.sub("", content)
        text = self._REASONING_FENCE_RE.sub("", text)
        return text.strip()
