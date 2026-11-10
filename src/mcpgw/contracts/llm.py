"""Provider-neutral LLM client interface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from mcpgw.contracts.selector import ToolDefinition


class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)


@runtime_checkable
class LLMClient(Protocol):
    def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse: ...

    def generate(self, prompt: str) -> str: ...
