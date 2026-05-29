from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field


class PlannedToolCall(BaseModel):
    tool: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    final: str | None = None
    tool_calls: list[PlannedToolCall] = Field(default_factory=list)


class AgentPlanner:
    async def plan(self, task: str) -> list[str]:
        return [task]

    def parse_llm_response(self, content: str) -> AgentPlan:
        objects = self._extract_json_objects(content)
        if not objects:
            return AgentPlan(final=content)
        calls = []
        final = None
        for data in objects:
            if not isinstance(data, dict):
                continue
            calls.extend(data.get("tool_calls") or data.get("tools") or [])
            final = data.get("final") or data.get("answer") or final
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
                    return final.strip()

        stripped = self._strip_tool_json_blocks(text)
        return stripped.strip()

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

    def _strip_tool_json_blocks(self, content: str) -> str:
        text = content.lstrip()
        prefix_match = re.match(
            r"^```(?:json)?\s*(\{.*?\"(?:tool_calls|tools)\".*?\})\s*```\s*",
            text,
            flags=re.DOTALL,
        )
        if prefix_match:
            return self._strip_tool_json_blocks(text[prefix_match.end() :])

        decoder = json.JSONDecoder()
        try:
            data, index = decoder.raw_decode(text)
        except json.JSONDecodeError:
            return content
        if isinstance(data, dict) and ("tool_calls" in data or "tools" in data):
            return self._strip_tool_json_blocks(text[index:])
        return content
