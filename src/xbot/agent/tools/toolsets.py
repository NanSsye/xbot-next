from __future__ import annotations

import re


def toolsets_for_source(config, source: str) -> set[str]:
    mode = getattr(config, "mode", "developer")
    if mode == "admin":
        return set(config.toolsets.admin)
    if source.startswith("channel:"):
        context = source_context(source)
        if context.get("scope") == "group":
            return set(config.toolsets.group)
        if context.get("scope") == "private":
            return set(config.toolsets.private)
    return set(config.toolsets.api)


def source_context(source: str) -> dict[str, str]:
    if not source.startswith("channel:"):
        return {}
    parts = source.split(":", 4)
    context = {
        "platform": parts[1] if len(parts) > 1 else "",
        "adapter": parts[2] if len(parts) > 2 else "",
        "conversation": parts[3] if len(parts) > 3 else "",
        "scope": "",
    }
    match = re.search(r":(private|group|channel|agent_task|system):", source)
    if match:
        context["scope"] = match.group(1)
    elif context["conversation"].endswith("@chatroom"):
        context["scope"] = "group"
    elif context["conversation"]:
        context["scope"] = "private"
    return context
