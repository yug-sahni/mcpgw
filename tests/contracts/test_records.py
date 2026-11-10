import json
import unicodedata
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mcpgw.contracts import (
    GatewayError,
    ToolRecord,
    canonical_json,
    make_qualified_name,
    read_snapshot,
    split_qualified_name,
    write_snapshot,
)


def rec(alias: str = "gh", name: str = "create_issue", **kw: object) -> ToolRecord:
    data: dict[str, object] = {
        "alias": alias,
        "name": name,
        "description": "Create an issue",
        "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}},
    }
    data.update(kw)
    return ToolRecord.model_validate(data)


def test_qualified_name_roundtrip() -> None:
    q = make_qualified_name("my-srv", "do__thing")
    assert q == "my-srv__do__thing"
    assert split_qualified_name(q) == ("my-srv", "do__thing")


@pytest.mark.parametrize("alias", ["", "Bad", "has_underscore", "x" * 33, "sp ace"])
def test_invalid_alias_rejected(alias: str) -> None:
    with pytest.raises(GatewayError):
        make_qualified_name(alias, "t")


@pytest.mark.parametrize("q", ["noseparator", "gh__", "__tool", "Bad__x"])
def test_invalid_qualified_name_rejected(q: str) -> None:
    with pytest.raises(GatewayError):
        split_qualified_name(q)


def test_hash_stable_across_key_order() -> None:
    a = rec(inputSchema={"a": 1, "b": 2})
    b = rec(inputSchema={"b": 2, "a": 1})
    assert a.content_hash == b.content_hash


def test_hash_changes_with_description() -> None:
    assert rec().content_hash != rec(description="Other").content_hash


def test_hash_ignores_nfc_differences() -> None:
    composed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", "café")
    assert rec(description=composed).content_hash == rec(description=decomposed).content_hash


def test_hash_golden() -> None:
    assert rec().content_hash == rec().content_hash
    assert len(rec().content_hash) == 64


def test_tampered_hash_rejected() -> None:
    with pytest.raises(GatewayError):
        rec(content_hash="0" * 64)


def test_tampered_qualified_name_rejected() -> None:
    with pytest.raises(GatewayError):
        rec(qualified_name="gh__other")


def test_frozen() -> None:
    r = rec()
    with pytest.raises(ValueError):
        r.name = "x"  # type: ignore[misc]


def test_canonical_json_compact_sorted() -> None:
    assert canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'


def test_snapshot_roundtrip_sorted(tmp_path: Path) -> None:
    records = [rec("zz", "b"), rec("aa", "z"), rec("aa", "a")]
    path = tmp_path / "snap.jsonl"
    manifest = write_snapshot(records, path)
    assert manifest["count"] == 3
    names = [json.loads(line)["qualified_name"] for line in path.read_text().splitlines()]
    assert names == sorted(names)
    assert read_snapshot(path) == sorted(records, key=lambda r: r.qualified_name)


def test_snapshot_deterministic(tmp_path: Path) -> None:
    records = [rec("a", "x"), rec("b", "y")]
    m1 = write_snapshot(records, tmp_path / "1.jsonl")
    m2 = write_snapshot(list(reversed(records)), tmp_path / "2.jsonl")
    assert m1 == m2


def test_snapshot_duplicate_rejected(tmp_path: Path) -> None:
    with pytest.raises(GatewayError):
        write_snapshot([rec(), rec()], tmp_path / "s.jsonl")


def test_snapshot_bad_line_reports_location(tmp_path: Path) -> None:
    p = tmp_path / "s.jsonl"
    p.write_text('{"alias": "Bad", "name": "x"}\n', encoding="utf-8")
    with pytest.raises(GatewayError, match=r"s\.jsonl:1"):
        read_snapshot(p)


@given(st.dictionaries(st.text(max_size=5), st.integers(), max_size=5))
def test_hash_order_independent(d: dict[str, int]) -> None:
    items = list(d.items())
    assert (
        rec(inputSchema=dict(items)).content_hash
        == rec(inputSchema=dict(reversed(items))).content_hash
    )
