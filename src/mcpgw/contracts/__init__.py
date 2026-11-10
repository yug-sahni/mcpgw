"""Shared contracts. Changes require review from both developers (see docs/adr/0001)."""

from mcpgw.contracts.dataset import QueryRecord, gold_recall, gold_satisfied
from mcpgw.contracts.errors import (
    ConfigError,
    EvaluationError,
    ExitCode,
    GatewayError,
    IngestError,
    ToolErrorCode,
)
from mcpgw.contracts.llm import LLMClient, LLMResponse, Message, ToolCall, Usage
from mcpgw.contracts.records import (
    ToolRecord,
    canonical_json,
    compute_content_hash,
    make_qualified_name,
    read_snapshot,
    split_qualified_name,
    write_snapshot,
)
from mcpgw.contracts.retrieval import Item, RetrievalFilter, RetrievalResult, Retriever
from mcpgw.contracts.selector import SelectionResult, ToolDefinition, ToolSelector

__all__ = [
    "ConfigError",
    "EvaluationError",
    "ExitCode",
    "GatewayError",
    "IngestError",
    "Item",
    "LLMClient",
    "LLMResponse",
    "Message",
    "QueryRecord",
    "RetrievalFilter",
    "RetrievalResult",
    "Retriever",
    "SelectionResult",
    "ToolCall",
    "ToolDefinition",
    "ToolErrorCode",
    "ToolRecord",
    "ToolSelector",
    "Usage",
    "canonical_json",
    "compute_content_hash",
    "gold_recall",
    "gold_satisfied",
    "make_qualified_name",
    "read_snapshot",
    "split_qualified_name",
    "write_snapshot",
]
