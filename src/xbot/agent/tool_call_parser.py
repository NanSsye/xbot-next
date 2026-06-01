from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParsedToolCall:
    tool: str
    payload: dict[str, Any] = field(default_factory=dict)


class ToolCallParser:
    def extract(self, content: str) -> list[ParsedToolCall]:
        text = self._strip_code_fences(content.strip())
        calls: list[ParsedToolCall] = []
        calls.extend(self._extract_json_tool_calls(text))
        calls.extend(self._extract_xml_tool_calls(text))
        calls.extend(self._extract_text_tool_calls(text))
        calls.extend(self._extract_bracket_tool_calls(text))
        return self._dedupe(calls)

    def contains_intent(self, content: str) -> bool:
        return bool(
            re.search(r'"(?:tool_calls|tools|tool|name|function|arguments|payload)"\s*:', content)
            or re.search(r"<(?:[\w.-]+:)?tool_call\b|<invoke\b|<function_call\b", content)
            or re.search(r"\[(?:TOOL_CALL|tool_call)\]", content)
            or re.search(r"(?im)^\s*(?:tool|function)\s*:\s*[\w.-]+", content)
        )

    def strip_blocks(self, content: str) -> str:
        text = self._strip_json_tool_blocks(content)
        text = re.sub(
            r"<(?:[\w.-]+:)?tool_call\b[^>]*>.*?</(?:[\w.-]+:)?tool_call>\s*",
            "",
            text,
            flags=re.DOTALL,
        )
        text = re.sub(r"<function_call\b[^>]*>.*?</function_call>\s*", "", text, flags=re.DOTALL)
        text = re.sub(r"<invoke\b.*?>\s*", "", text, flags=re.DOTALL)
        text = re.sub(r"\[(?:TOOL_CALL|tool_call)\].*?\[/(?:TOOL_CALL|tool_call)\]\s*", "", text, flags=re.DOTALL)
        text = re.sub(
            r"(?ims)^\s*(?:tool|function)\s*:\s*[\w.-]+\s*\n\s*(?:arguments|payload|args)\s*:\s*\{.*?\}\s*",
            "",
            text,
        )
        return text

    def _extract_json_tool_calls(self, text: str) -> list[ParsedToolCall]:
        calls: list[ParsedToolCall] = []
        for data in self._extract_json_objects(text):
            calls.extend(self._calls_from_json_data(data))
        if not calls:
            calls.extend(self._extract_lenient_json_pairs(text))
        return calls

    def _extract_bracket_tool_calls(self, text: str) -> list[ParsedToolCall]:
        calls = []
        for match in re.finditer(
            r"\[(?:TOOL_CALL|tool_call)\](?P<body>.*?)\[/(?:TOOL_CALL|tool_call)\]",
            text,
            flags=re.DOTALL,
        ):
            call = self._parse_hashrocket_tool_call(match.group("body"))
            if call:
                calls.append(call)
        return calls

    def _parse_hashrocket_tool_call(self, body: str) -> ParsedToolCall | None:
        tool_match = re.search(
            r'["\']?tool["\']?\s*(?:=>|:)\s*(?:"([^"]+)"|\'([^\']+)\'|([\w.-]+))',
            body,
        )
        if not tool_match:
            return None
        tool = (tool_match.group(1) or tool_match.group(2) or tool_match.group(3) or "").strip()
        if not tool:
            return None
        payload: dict[str, Any] = {}
        payload_match = re.search(r'["\']?payload["\']?\s*(?:=>|:)', body)
        if payload_match:
            brace_index = body.find("{", payload_match.end())
            if brace_index >= 0:
                payload = self._parse_relaxed_object(body[brace_index:])
        return ParsedToolCall(tool=tool, payload=payload)

    def _parse_relaxed_object(self, text: str) -> dict[str, Any]:
        raw = self._balanced_brace_slice(text)
        if not raw:
            return {}
        normalized = re.sub(r"=>", ":", raw)
        normalized = re.sub(r"(?<=[{,\s])([A-Za-z_][\w.-]*)\s*:", r'"\1":', normalized)
        normalized = normalized.replace("'", '"')
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _balanced_brace_slice(self, text: str) -> str:
        start = text.find("{")
        if start < 0:
            return ""
        depth = 0
        in_string = ""
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == in_string:
                    in_string = ""
                continue
            if char in {"'", '"'}:
                in_string = char
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return ""

    def _calls_from_json_data(self, data: Any) -> list[ParsedToolCall]:
        if isinstance(data, list):
            calls: list[ParsedToolCall] = []
            for item in data:
                calls.extend(self._calls_from_json_data(item))
            return calls
        if not isinstance(data, dict):
            return []

        raw_calls: list[Any] = []
        if data.get("tool") or self._has_explicit_named_call(data):
            raw_calls.append(data)
        raw_calls.extend(data.get("tool_calls") or data.get("tools") or [])
        if isinstance(data.get("function"), dict):
            raw_calls.append(data)

        calls = []
        for item in raw_calls:
            call = self._call_from_json_item(item)
            if call:
                calls.append(call)
        return calls

    def _call_from_json_item(self, item: Any) -> ParsedToolCall | None:
        if not isinstance(item, dict):
            return None
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        tool = str(item.get("tool") or function.get("name") or "").strip()
        if not tool and self._has_explicit_named_call(item):
            tool = str(item.get("name") or "").strip()
        if not tool:
            return None
        payload = item.get("payload")
        if payload is None:
            payload = item.get("arguments")
        if payload is None:
            payload = function.get("arguments")
        return ParsedToolCall(tool=tool, payload=self._normalize_payload(payload))

    def _extract_lenient_json_pairs(self, text: str) -> list[ParsedToolCall]:
        calls: list[ParsedToolCall] = []
        tool_pattern = re.compile(r'"tool"\s*:\s*"([^"]+)"')
        decoder = json.JSONDecoder()
        for match in tool_pattern.finditer(text):
            payload: dict[str, Any] = {}
            payload_match = re.search(r'"(?:payload|arguments)"\s*:', text[match.end() :])
            if payload_match:
                payload_start = match.end() + payload_match.end()
                brace_index = text.find("{", payload_start)
                if brace_index >= 0:
                    try:
                        parsed_payload, _ = decoder.raw_decode(text[brace_index:])
                    except json.JSONDecodeError:
                        parsed_payload = {}
                    payload = self._normalize_payload(parsed_payload)
            calls.append(ParsedToolCall(tool=match.group(1), payload=payload))
        return calls

    def _has_explicit_named_call(self, data: dict[str, Any]) -> bool:
        if not data.get("name"):
            return False
        return any(key in data for key in ("payload", "arguments", "args"))

    def _extract_xml_tool_calls(self, text: str) -> list[ParsedToolCall]:
        calls = []
        decoder = json.JSONDecoder()
        for match in re.finditer(r"<invoke\b(?P<body>.*?)>", text, flags=re.DOTALL):
            body = match.group("body")
            name_match = re.search(r'\bname\s*=\s*["\']([^"\']+)["\']', body)
            if not name_match:
                continue
            calls.append(ParsedToolCall(tool=name_match.group(1).strip(), payload=self._payload_from_body(body, decoder)))
        for match in re.finditer(r"<function_call\b(?P<body>.*?)>(?P<inner>.*?)</function_call>", text, flags=re.DOTALL):
            body = match.group("body")
            inner = match.group("inner")
            name_match = re.search(r'\bname\s*=\s*["\']([^"\']+)["\']', body)
            if not name_match:
                continue
            payload = self._normalize_payload(inner.strip())
            calls.append(ParsedToolCall(tool=name_match.group(1).strip(), payload=payload))
        return calls

    def _payload_from_body(self, body: str, decoder: json.JSONDecoder) -> dict[str, Any]:
        payload_key = re.search(r'["\']?(?:payload|arguments|args)["\']?\s*[:=]', body)
        if not payload_key:
            return {}
        brace_index = body.find("{", payload_key.end())
        if brace_index < 0:
            return {}
        try:
            parsed, _ = decoder.raw_decode(body[brace_index:])
        except json.JSONDecodeError:
            return {}
        return self._normalize_payload(parsed)

    def _extract_text_tool_calls(self, text: str) -> list[ParsedToolCall]:
        pattern = re.compile(
            r"(?ims)^\s*(?:tool|function)\s*:\s*(?P<tool>[\w.-]+)\s*\n"
            r"\s*(?:arguments|payload|args)\s*:\s*(?P<payload>\{.*?\})\s*$"
        )
        calls = []
        for match in pattern.finditer(text):
            calls.append(
                ParsedToolCall(
                    tool=match.group("tool").strip(),
                    payload=self._normalize_payload(match.group("payload").strip()),
                )
            )
        return calls

    def _extract_json_objects(self, content: str) -> list[Any]:
        text = self._strip_code_fences(content.strip())
        try:
            return [json.loads(text)]
        except json.JSONDecodeError:
            pass
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

    def _normalize_payload(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str) and payload.strip():
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _strip_json_tool_blocks(self, content: str) -> str:
        text = content.lstrip()
        prefix_match = re.match(
            r"^```(?:json)?\s*(\{.*?\"(?:tool_calls|tools|tool|function)\".*?\})\s*```\s*",
            text,
            flags=re.DOTALL,
        )
        if prefix_match:
            return self._strip_json_tool_blocks(text[prefix_match.end() :])
        decoder = json.JSONDecoder()
        try:
            data, index = decoder.raw_decode(text)
        except json.JSONDecodeError:
            return content
        if self._calls_from_json_data(data) or (
            isinstance(data, dict) and any(key in data for key in ("tool_calls", "tools", "tool", "function"))
        ):
            return self._strip_json_tool_blocks(text[index:])
        return content

    def _dedupe(self, calls: list[ParsedToolCall]) -> list[ParsedToolCall]:
        seen = set()
        unique = []
        for call in calls:
            key = (call.tool, json.dumps(call.payload, ensure_ascii=False, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            unique.append(call)
        return unique

    def _strip_code_fences(self, text: str) -> str:
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return text
