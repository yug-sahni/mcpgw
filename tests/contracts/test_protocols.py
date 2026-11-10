from collections.abc import Sequence

import pytest

from mcpgw.contracts import (
    ConfigError,
    ExitCode,
    GatewayError,
    Item,
    LLMClient,
    LLMResponse,
    Message,
    RetrievalFilter,
    RetrievalResult,
    Retriever,
    SelectionResult,
    ToolDefinition,
    ToolErrorCode,
    ToolSelector,
)


class FakeRetriever:
    name = "fake"

    def retrieve(
        self, query: str, k: int, filter: RetrievalFilter | None = None
    ) -> RetrievalResult:
        return RetrievalResult(
            items=[Item(tool_id=1, qualified_name="a__x", score=1.0, rank=1, source="fake")]
        )


class FakeSelector:
    def select(
        self, query: str, k: int = 8, servers: Sequence[str] | None = None
    ) -> SelectionResult:
        return SelectionResult(tools=[ToolDefinition(name="a__x")], scores=[1.0])


class FakeLLM:
    def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        return LLMResponse(text="ok")

    def generate(self, prompt: str) -> str:
        return "ok"


def test_fakes_satisfy_protocols() -> None:
    assert isinstance(FakeRetriever(), Retriever)
    assert isinstance(FakeSelector(), ToolSelector)
    assert isinstance(FakeLLM(), LLMClient)


def test_object_without_methods_is_not_retriever() -> None:
    assert not isinstance(object(), Retriever)


def test_rank_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Item(tool_id=1, qualified_name="a__x", score=0.0, rank=0, source="s")


def test_tool_definition_accepts_input_schema_alias() -> None:
    t = ToolDefinition.model_validate({"name": "a__x", "inputSchema": {"type": "object"}})
    assert t.input_schema == {"type": "object"}


def test_error_codes_and_exit_codes() -> None:
    assert ConfigError("x").exit_code == ExitCode.USAGE
    assert GatewayError("x").exit_code == ExitCode.GENERAL
    assert GatewayError("x", code=ToolErrorCode.NO_INDEX).code == "no_index"
