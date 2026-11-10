"""The committed shared fixture must stay valid against contract A and in sync with its source."""

from pathlib import Path

from mcpgw.contracts.records import read_snapshot, write_snapshot
from tests.fixtures.sample_corpus import SAMPLE_PATH, build_sample_records


def test_sample_fixture_is_current(tmp_path: Path) -> None:
    regenerated = tmp_path / "sample.jsonl"
    write_snapshot(build_sample_records(), regenerated)
    assert SAMPLE_PATH.read_bytes() == regenerated.read_bytes(), (
        "tests/fixtures/data/sample_tools.jsonl is stale; run "
        "`uv run python -m tests.fixtures.sample_corpus`"
    )


def test_sample_fixture_shape() -> None:
    records = read_snapshot(SAMPLE_PATH)  # verifies every content hash
    assert len(records) == 12
    assert len({r.alias for r in records}) == 4
    assert [r.qualified_name for r in records] == sorted(r.qualified_name for r in records)
    assert {"docs__search", "web__search"} <= {r.qualified_name for r in records}
    assert any("no_description" in r.flags for r in records)
