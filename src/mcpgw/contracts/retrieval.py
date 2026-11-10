"""Retriever interface (Developer 1 implements, Developer 2 consumes)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class RetrievalFilter(BaseModel):
    """Restrict retrieval. ``None`` means no restriction on that dimension."""

    model_config = ConfigDict(frozen=True)

    aliases: frozenset[str] | None = None
    tool_ids: frozenset[str] | None = None


class Item(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_id: int | str
    qualified_name: str
    score: float
    rank: int = Field(ge=1)
    source: str  # which retriever produced it, e.g. "bm25", "dense", "rrf"


class RetrievalResult(BaseModel):
    items: list[Item] = Field(default_factory=list)
    degraded: bool = False  # True if a component failed and a fallback was used
    timings_ms: Mapping[str, float] = Field(default_factory=dict)


@runtime_checkable
class Retriever(Protocol):
    name: str

    def retrieve(
        self, query: str, k: int, filter: RetrievalFilter | None = None
    ) -> RetrievalResult: ...
