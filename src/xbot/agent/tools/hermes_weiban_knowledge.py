from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_TOOLSET = "weiban-knowledge"
_MAX_FILE_BYTES = 128 * 1024


def _knowledge_path() -> Path:
    return Path(__file__).resolve().parents[4] / "skills" / "weiban-knowledge" / "KNOWLEDGE.md"


def _bigrams(value: str) -> set[str]:
    normalized = re.sub(r"\s+", "", value.casefold())
    return {normalized[index : index + 2] for index in range(max(0, len(normalized) - 1))}


def search_knowledge(args: dict[str, Any], **_: Any) -> str:
    query = str(args.get("query") or "").strip() if isinstance(args, dict) else ""
    if not query or len(query) > 200:
        return json.dumps(
            {"success": False, "error": "invalid_query", "message": "请输入简短的微伴问题。"},
            ensure_ascii=False,
        )
    path = _knowledge_path()
    try:
        raw = path.read_bytes()
    except OSError:
        return json.dumps(
            {"success": False, "error": "knowledge_unavailable", "message": "微伴知识库暂不可用。"},
            ensure_ascii=False,
        )
    if len(raw) > _MAX_FILE_BYTES:
        return json.dumps(
            {"success": False, "error": "knowledge_unavailable", "message": "微伴知识库暂不可用。"},
            ensure_ascii=False,
        )
    text = raw.decode("utf-8")
    sections = [section.strip() for section in re.split(r"(?=^##\s+)", text, flags=re.MULTILINE)]
    query_bigrams = _bigrams(query)
    ranked = sorted(
        (
            (len(query_bigrams.intersection(_bigrams(section))), index, section)
            for index, section in enumerate(sections)
            if section
        ),
        key=lambda item: (-item[0], item[1]),
    )
    matches = [section for score, _, section in ranked if score > 0][:4]
    if not matches:
        matches = sections[:2]
    return json.dumps(
        {"success": True, "query": query, "content": "\n\n".join(matches)},
        ensure_ascii=False,
    )


def register_xbot_weiban_knowledge_tools() -> None:
    from tools.registry import registry

    schema = {
        "name": "weiban_search_knowledge",
        "description": (
            "Search the public Weiban Lyvu product knowledge base for features, account setup, "
            "community commands, quotas, memory, images, voice, and troubleshooting."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's concise question about Weiban or Lyvu.",
                    "minLength": 1,
                    "maxLength": 200,
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    }
    existing = registry.get_entry("weiban_search_knowledge")
    if existing is not None and existing.handler is search_knowledge and existing.toolset == _TOOLSET:
        return
    registry.register(
        name="weiban_search_knowledge",
        toolset=_TOOLSET,
        schema=schema,
        handler=search_knowledge,
        description=schema["description"],
        override=existing is not None,
    )
