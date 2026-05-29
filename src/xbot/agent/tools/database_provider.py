from __future__ import annotations

import re
from typing import Any

from sqlalchemy import inspect, text

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
    registry.register(
        ToolDefinition(
            name="database.schema",
            description="Inspect database schemas, tables, columns, primary keys, and indexes.",
            risk_level="read",
            handler=lambda payload: _schema(payload, storage=storage),
            toolset="database",
            source="database",
            cacheable=True,
            timeout_seconds=60,
            input_schema={
                "type": "object",
                "properties": {
                    "schema": {"type": "string", "default": "public"},
                    "table": {"type": "string"},
                    "include_indexes": {"type": "boolean", "default": True},
                    "limit": {"type": "integer", "default": 200},
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


async def _schema(payload: dict[str, Any], *, storage) -> dict:
    requested_schema = payload.get("schema")
    table = payload.get("table")
    limit = max(1, min(int(payload.get("limit", 200)), 1000))
    include_indexes = bool(payload.get("include_indexes", True))

    def inspect_schema(sync_session) -> dict:
        connection = sync_session.connection()
        inspector = inspect(connection)
        dialect = connection.dialect.name
        default_schema = inspector.default_schema_name
        schema = str(requested_schema) if requested_schema else default_schema
        try:
            schema_names = inspector.get_schema_names()
        except Exception:
            schema_names = [schema] if schema else []

        table_names = [str(table)] if table else inspector.get_table_names(schema=schema)
        table_names = table_names[:limit]
        tables = []
        column_count = 0
        for table_name in table_names:
            columns = [
                {
                    "name": column.get("name"),
                    "type": str(column.get("type")),
                    "nullable": column.get("nullable"),
                    "default": str(column.get("default")) if column.get("default") is not None else None,
                    "primary_key": bool(column.get("primary_key")),
                }
                for column in inspector.get_columns(table_name, schema=schema)
            ]
            primary_key = inspector.get_pk_constraint(table_name, schema=schema) or {}
            primary_key_columns = set(primary_key.get("constrained_columns") or [])
            for column in columns:
                if column["name"] in primary_key_columns:
                    column["primary_key"] = True
            indexes = inspector.get_indexes(table_name, schema=schema) if include_indexes else []
            tables.append(
                {
                    "schema": schema,
                    "name": table_name,
                    "columns": columns,
                    "primary_key": {
                        "name": primary_key.get("name"),
                        "columns": list(primary_key_columns),
                    },
                    "indexes": [
                        {
                            "name": index.get("name"),
                            "columns": index.get("column_names") or [],
                            "unique": bool(index.get("unique")),
                        }
                        for index in indexes
                    ],
                }
            )
            column_count += len(columns)
        return {
            "dialect": dialect,
            "schema": schema,
            "available_schemas": schema_names[:limit],
            "table": str(table) if table else None,
            "table_count": len(tables),
            "column_count": column_count,
            "tables": tables,
        }

    async with storage.session_factory() as session:
        return await session.run_sync(inspect_schema)
