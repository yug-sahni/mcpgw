"""Parameter metadata from an ``inputSchema`` (FR-1.6).

Walks ``properties`` to a depth of two with dotted paths (``options.recursive``) and resolves
``$ref`` values that point inside the same schema (``#/$defs/...``, ``#/definitions/...``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from mcpgw.ingestion.models import Param

MAX_DEPTH = 2
_MAX_REF_HOPS = 8


def _resolve_local_ref(node: Any, root: dict[str, Any]) -> Any:
    hops = 0
    while isinstance(node, dict) and isinstance(node.get("$ref"), str) and hops < _MAX_REF_HOPS:
        ref: str = node["$ref"]
        if not ref.startswith("#/"):
            return node  # remote refs are never fetched
        target: Any = root
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return node
            target = target[part]
        node = target
        hops += 1
    return node


def json_type(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    t = node.get("type")
    if isinstance(t, str):
        return t
    if isinstance(t, list):
        names = sorted({x for x in t if isinstance(x, str) and x != "null"})
        return "|".join(names) or None
    if "properties" in node:
        return "object"
    return None


def _walk(
    schema: Any, root: dict[str, Any], depth: int, prefix: str, seen: set[str]
) -> Iterator[Param]:
    if not isinstance(schema, dict):
        return
    props = schema.get("properties")
    if not isinstance(props, dict):
        return
    required = schema.get("required")
    required_set = (
        {r for r in required if isinstance(r, str)} if isinstance(required, list) else set()
    )
    for name, sub in props.items():
        if not isinstance(name, str):
            continue
        path = f"{prefix}{name}"
        if path in seen:
            continue
        seen.add(path)
        node = _resolve_local_ref(sub, root)
        desc = node.get("description") if isinstance(node, dict) else None
        yield Param(
            path=path,
            json_type=json_type(node),
            is_required=name in required_set,
            description=desc if isinstance(desc, str) else None,
        )
        if depth + 1 < MAX_DEPTH and json_type(node) == "object":
            yield from _walk(node, root, depth + 1, f"{path}.", seen)


def extract_params(schema: Any) -> list[Param]:
    if not isinstance(schema, dict):
        return []
    return list(_walk(schema, schema, 0, "", set()))
