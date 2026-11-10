"""ToolSelector: the harness-mode (Mode B) entry point."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ToolDefinition(BaseModel):
    """What an LLM needs to call a tool."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: str  # qualified name
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict, alias="inputSchema")


class SelectionResult(BaseModel):
    tools: list[ToolDefinition] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)
    degraded: bool = False
    timings_ms: Mapping[str, float] = Field(default_factory=dict)


@runtime_checkable
class ToolSelector(Protocol):
    def select(
        self, query: str, k: int = 8, servers: Sequence[str] | None = None
    ) -> SelectionResult: ...
