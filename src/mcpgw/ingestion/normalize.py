"""Turn raw upstream tools into canonical ``ToolRecord`` s (FR-1.3, FR-1.4).

Quality problems are flagged, never silently fixed (SRS 6.1):
``no_description``, ``schema_invalid``, ``output_schema_invalid``, ``duplicate_name`` and
``very_long_description``.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable
from typing import Any

from mcpgw.contracts.errors import ContractError
from mcpgw.contracts.records import ToolRecord
from mcpgw.ingestion.models import RawTool

VERY_LONG_DESCRIPTION = 20_000
_KEEP = {"\n", "\t"}


class Flag:
    NO_DESCRIPTION = "no_description"
    SCHEMA_INVALID = "schema_invalid"
    OUTPUT_SCHEMA_INVALID = "output_schema_invalid"
    DUPLICATE_NAME = "duplicate_name"
    VERY_LONG_DESCRIPTION = "very_long_description"


def clean_text(value: str) -> str:
    """NFC-normalise and strip control characters except newline and tab."""
    stripped = "".join(
        ch for ch in value if ch in _KEEP or unicodedata.category(ch) not in ("Cc", "Cs")
    )
    return unicodedata.normalize("NFC", stripped)


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def is_object_schema(schema: Any) -> bool:
    """MCP requires ``inputSchema`` to be a JSON object schema with ``type: object``."""
    return isinstance(schema, dict) and schema.get("type") == "object" and _json_safe(schema)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return clean_text(str(value)) or None


def normalise(alias: str, raw: RawTool, *, extra_flags: Iterable[str] = ()) -> ToolRecord:
    if not isinstance(raw.name, str) or not raw.name:
        raise ContractError(f"tool without a name from upstream {alias!r}")
    flags: list[str] = list(extra_flags)

    description = clean_text(raw.description) if isinstance(raw.description, str) else ""
    if not description.strip():
        description = ""
        flags.append(Flag.NO_DESCRIPTION)
    elif len(description) > VERY_LONG_DESCRIPTION:
        flags.append(Flag.VERY_LONG_DESCRIPTION)  # stored in full; truncation is M3's job

    if is_object_schema(raw.input_schema):
        input_schema: dict[str, Any] = raw.input_schema
    else:
        input_schema = {}
        flags.append(Flag.SCHEMA_INVALID)

    output_schema: dict[str, Any] | None = None
    if raw.output_schema is not None:
        if isinstance(raw.output_schema, dict) and _json_safe(raw.output_schema):
            output_schema = raw.output_schema
        else:
            flags.append(Flag.OUTPUT_SCHEMA_INVALID)

    annotations = raw.annotations if isinstance(raw.annotations, dict) else None
    if annotations is not None and not _json_safe(annotations):
        annotations = None

    return ToolRecord.model_validate(
        {
            "alias": alias,
            "name": raw.name,
            "title": _optional_text(raw.title),
            "description": description,
            "inputSchema": input_schema,
            "outputSchema": output_schema,
            "annotations": annotations,
            "flags": sorted(set(flags)),
        }
    )


def normalise_all(alias: str, tools: Iterable[RawTool]) -> tuple[list[ToolRecord], list[str]]:
    """Normalise every tool; keep the first of any duplicate name and flag it.

    Returns the records and human-readable warnings."""
    warnings: list[str] = []
    by_name: dict[str, RawTool] = {}
    dupes: set[str] = set()
    for t in tools:
        if not isinstance(t.name, str) or not t.name:
            warnings.append("skipped a tool with no name")
            continue
        if t.name in by_name:
            dupes.add(t.name)
            continue
        by_name[t.name] = t
    for name in sorted(dupes):
        warnings.append(f"duplicate tool name {name!r}: kept the first definition")

    records: list[ToolRecord] = []
    for name, t in by_name.items():
        extra = [Flag.DUPLICATE_NAME] if name in dupes else []
        try:
            records.append(normalise(alias, t, extra_flags=extra))
        except ContractError as e:
            warnings.append(f"skipped tool {name!r}: {e.message}")
    return records, warnings
