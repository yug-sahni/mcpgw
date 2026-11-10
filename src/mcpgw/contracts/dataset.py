"""Benchmark query records. ``gold`` is a list of groups of interchangeable qualified names;
every group must be satisfied by at least one retrieved tool."""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

from mcpgw.contracts.errors import ContractError
from mcpgw.contracts.records import split_qualified_name

Vagueness = Literal["named", "action", "goal"]
Split = Literal["dev", "test"]


class QueryRecord(BaseModel):
    id: str
    query: str
    vagueness: Vagueness
    gold: list[list[str]]
    split: Split | None = None
    tags: list[str] = []

    @field_validator("query")
    @classmethod
    def _query_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be empty")
        return v

    @field_validator("gold")
    @classmethod
    def _gold_valid(cls, groups: list[list[str]]) -> list[list[str]]:
        if not groups:
            raise ValueError("gold must contain at least one group")
        for group in groups:
            if not group:
                raise ValueError("gold groups must not be empty")
            for q in group:
                try:
                    split_qualified_name(q)
                except ContractError as e:
                    raise ValueError(e.message) from e
        return groups


def gold_satisfied(gold: list[list[str]], retrieved: Collection[str]) -> bool:
    """AllGold: every group has at least one member in ``retrieved``."""
    got = set(retrieved)
    return all(any(q in got for q in group) for group in gold)


def gold_recall(gold: list[list[str]], retrieved: Collection[str]) -> float:
    """Fraction of gold groups satisfied."""
    got = set(retrieved)
    return sum(any(q in got for q in g) for g in gold) / len(gold)


def write_dataset(records: Iterable[QueryRecord], path: Path) -> None:
    lines = [r.model_dump_json() for r in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_dataset(path: Path) -> list[QueryRecord]:
    out: list[QueryRecord] = []
    ids: set[str] = set()
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = QueryRecord.model_validate(json.loads(line))
        except ValueError as e:
            raise ContractError(f"{path}:{i}: {e}") from e
        if rec.id in ids:
            raise ContractError(f"{path}:{i}: duplicate id {rec.id!r}")
        ids.add(rec.id)
        out.append(rec)
    return out
