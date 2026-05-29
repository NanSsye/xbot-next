from __future__ import annotations

from pydantic import BaseModel, Field


class PluginRouting(BaseModel):
    enabled: bool = True
    priority: int = 100
    fallback: bool = False
    exclusive: bool = False
    message_types: list[str] = Field(default_factory=lambda: ["text"])
    platforms: list[str] = Field(default_factory=list)
    adapters: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    prefixes: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    exact: list[str] = Field(default_factory=list)


class PluginManifest(BaseModel):
    name: str
    version: str = "0.0.0"
    entry: str
    author: str | None = None
    description: str | None = None
    enabled: bool = True
    routing: PluginRouting = Field(default_factory=PluginRouting)
