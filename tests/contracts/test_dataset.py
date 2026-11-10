from pathlib import Path

import pytest
from pydantic import ValidationError

from mcpgw.contracts import GatewayError, QueryRecord, gold_recall, gold_satisfied
from mcpgw.contracts.dataset import read_dataset, write_dataset


def q(id_: str = "q1", gold: list[list[str]] | None = None) -> QueryRecord:
    return QueryRecord(
        id=id_,
        query="open an issue",
        vagueness="action",
        gold=gold or [["gh__create_issue", "gl__create_issue"]],
    )


def test_group_satisfied_by_any_member() -> None:
    assert gold_satisfied([["a__x", "b__x"]], {"b__x"})


def test_all_groups_required() -> None:
    gold = [["a__x"], ["a__y"]]
    assert not gold_satisfied(gold, {"a__x"})
    assert gold_satisfied(gold, {"a__x", "a__y"})
    assert gold_recall(gold, {"a__x"}) == 0.5


@pytest.mark.parametrize("gold", [[], [[]], [["not-qualified"]]])
def test_invalid_gold_rejected(gold: list[list[str]]) -> None:
    with pytest.raises(ValidationError):
        QueryRecord(id="q", query="x", vagueness="named", gold=gold)


def test_empty_query_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryRecord(id="q", query="  ", vagueness="named", gold=[["a__x"]])


def test_bad_vagueness_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryRecord(id="q", query="x", vagueness="vague", gold=[["a__x"]])


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    recs = [q("a"), q("b")]
    p = tmp_path / "d.jsonl"
    write_dataset(recs, p)
    assert read_dataset(p) == recs


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    p = tmp_path / "d.jsonl"
    write_dataset([q("a"), q("a")], p)
    with pytest.raises(GatewayError, match="duplicate id"):
        read_dataset(p)
