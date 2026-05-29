from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

from xbot.agent.tool_registry import ToolDefinition, ToolRegistry
from xbot.core.exceptions import PolicyDeniedError, XBotError


READONLY_SQL = re.compile(r"^\s*(select|with|explain)\b", re.IGNORECASE)
MUTATING_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|execute)\b",
    re.IGNORECASE,
)


def register_database_tools(registry: ToolRegistry, *, storage) -> None:
    registry.register(
        ToolDefinition(
            name="database.query",
            description="Run a read-only SQL query against the configured application database.",
            risk_level="read",
            handler=lambda payload: _query(payload, storage=storage),
            toolset="database",
            source="database",
            timeout_seconds=60,
            input_schema={
                "type": "object",
                "required": ["sql"],
                "properties": {
                    "sql": {"type": "string"},
                    "params": {"type": "object", "default": {}},
                    "limit": {"type": "integer", "default": 100},
                },
            },
        )
    )


async def _query(payload: dict[str, Any], *, storage) -> dict:
    sql = str(payload["sql"]).strip()
    if not READONLY_SQL.match(sql) or MUTATING_SQL.search(sql):
        raise PolicyDeniedError("Only read-only SELECT/WITH/EXPLAIN database queries are allowed.")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        raise XBotError("database.query params must be an object.")
    limit = max(1, min(int(payload.get("limit", 100)), 500))
    async with storage.session_factory() as session:
        result = await session.execute(text(sql), params)
        rows = result.mappings().fetchmany(limit)
        return {
            "row_count": len(rows),
            "truncated": len(rows) == limit,
            "rows": [dict(row) for row in rows],
        }
