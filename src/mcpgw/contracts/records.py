"""ToolRecord, qualified names, content hashing and JSONL snapshots."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mcpgw.contracts.errors import ContractError

ALIAS_RE = re.compile(r"^[a-z0-9-]{1,32}$")
SEPARATOR = "__"


def make_qualified_name(alias: str, name: str) -> str:
    if not ALIAS_RE.fullmatch(alias):
        raise ContractError(f"invalid alias {alias!r}: must match [a-z0-9-]{{1,32}}")
    if not name:
        raise ContractError("tool name must not be empty")
    return f"{alias}{SEPARATOR}{name}"


def split_qualified_name(qualified: str) -> tuple[str, str]:
    """Split on the first ``__``; aliases cannot contain underscores so this is unambiguous."""
    alias, sep, name = qualified.partition(SEPARATOR)
    if not sep or not name or not ALIAS_RE.fullmatch(alias):
        raise ContractError(f"invalid qualified name {qualified!r}")
    return alias, name


def _nfc(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {_nfc(k): _nfc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_nfc(v) for v in value]
    return value


def canonical_json(obj: Any) -> str:
    """Sorted keys, compact separators, UTF-8 (no ASCII escaping), NFC strings."""
    return json.dumps(_nfc(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_content_hash(
    *,
    name: str,
    title: str | None,
    description: str | None,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any] | None,
    annotations: dict[str, Any] | None,
) -> str:
    payload = {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": input_schema,
        "outputSchema": output_schema,
        "annotations": annotations,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class ToolRecord(BaseModel):
    """One tool from one upstream server. Derived fields are computed and verified."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    alias: str
    name: str
    qualified_name: str
    title: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict, alias="inputSchema")
    output_schema: dict[str, Any] | None = Field(default=None, alias="outputSchema")
    annotations: dict[str, Any] | None = None
    flags: list[str] = Field(default_factory=list)
    content_hash: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        alias, name = d.get("alias"), d.get("name")
        if isinstance(alias, str) and isinstance(name, str):
            expected_q = make_qualified_name(alias, name)
            if d.get("qualified_name", expected_q) != expected_q:
                raise ContractError("qualified_name does not match alias and name")
            d["qualified_name"] = expected_q
            expected_h = compute_content_hash(
                name=name,
                title=d.get("title"),
                description=d.get("description"),
                input_schema=d.get("inputSchema", d.get("input_schema", {})),
                output_schema=d.get("outputSchema", d.get("output_schema")),
                annotations=d.get("annotations"),
            )
            if d.get("content_hash", expected_h) != expected_h:
                raise ContractError("content_hash does not match content")
            d["content_hash"] = expected_h
        return d

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


def write_snapshot(records: Iterable[ToolRecord], path: Path) -> dict[str, Any]:
    """Write records sorted by qualified_name; return a manifest."""
    ordered = sorted(records, key=lambda r: r.qualified_name)
    seen: set[str] = set()
    for r in ordered:
        if r.qualified_name in seen:
            raise ContractError(f"duplicate qualified_name {r.qualified_name!r}")
        seen.add(r.qualified_name)
    lines = [canonical_json(r.to_json_dict()) for r in ordered]
    data = ("\n".join(lines) + "\n" if lines else "").encode("utf-8")
    path.write_bytes(data)
    return {"count": len(ordered), "sha256": hashlib.sha256(data).hexdigest()}


def read_snapshot(path: Path) -> list[ToolRecord]:
    records = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(ToolRecord.model_validate(json.loads(line)))
        except (ValueError, ContractError) as e:
            raise ContractError(f"{path}:{i}: {e}") from e
    return records
