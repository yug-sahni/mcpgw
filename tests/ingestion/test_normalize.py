import pytest

from mcpgw.contracts.records import compute_content_hash
from mcpgw.ingestion.models import RawTool
from mcpgw.ingestion.normalize import Flag, clean_text, normalise, normalise_all
from mcpgw.ingestion.params import extract_params
from tests.fixtures.fake_upstreams import malformed_tools


def test_well_formed_tool() -> None:
    schema = {"type": "object", "properties": {"path": {"type": "string"}}}
    rec = normalise(
        "fs", RawTool(name="read_file", description="Read a file.", input_schema=schema)
    )
    assert rec.qualified_name == "fs__read_file"
    assert rec.flags == []
    assert rec.content_hash == compute_content_hash(
        name="read_file",
        title=None,
        description="Read a file.",
        input_schema=schema,
        output_schema=None,
        annotations=None,
    )


def test_hash_changes_with_any_model_visible_field() -> None:
    base = RawTool(name="t", description="d", input_schema={"type": "object"})
    h = normalise("a", base).content_hash
    for changed in (
        RawTool(name="t", description="d2", input_schema={"type": "object"}),
        RawTool(name="t", title="T", description="d", input_schema={"type": "object"}),
        RawTool(name="t", description="d", input_schema={"type": "object", "properties": {}}),
        RawTool(name="t", description="d", input_schema={"type": "object"}, annotations={"x": 1}),
    ):
        assert normalise("a", changed).content_hash != h


def test_clean_text() -> None:
    assert clean_text("a\x07b\x00c\r\nd\te") == "abc\nd\te"
    assert clean_text("é") == "é"  # NFC


def test_malformed_fixture_flags() -> None:
    records, warnings = normalise_all("bad", malformed_tools())
    by_name = {r.name: r for r in records}
    assert Flag.NO_DESCRIPTION in by_name["no_desc"].flags
    assert by_name["blank_desc"].description == ""
    assert Flag.NO_DESCRIPTION in by_name["blank_desc"].flags
    for name in ("bad_schema", "not_object", "missing_schema"):
        assert Flag.SCHEMA_INVALID in by_name[name].flags
        assert by_name[name].input_schema == {}
    assert by_name["dupe"].description == "First definition."
    assert Flag.DUPLICATE_NAME in by_name["dupe"].flags
    assert Flag.VERY_LONG_DESCRIPTION in by_name["huge"].flags
    assert len(by_name["huge"].description or "") == 30_000  # stored in full
    assert by_name["ctrl"].description == "Bell and nul\nkept\ttab"
    assert "" not in by_name
    assert any("duplicate tool name 'dupe'" in w for w in warnings)
    assert any("no name" in w for w in warnings)


def test_invalid_output_schema_flagged() -> None:
    rec = normalise("a", RawTool(name="t", input_schema={"type": "object"}, output_schema="x"))
    assert rec.output_schema is None
    assert Flag.OUTPUT_SCHEMA_INVALID in rec.flags


@pytest.mark.parametrize("schema", [None, [], "x", {"properties": {}}])
def test_extract_params_tolerates_garbage(schema: object) -> None:
    assert extract_params(schema) == []


def test_extract_params_depth_refs_and_required() -> None:
    schema = {
        "type": "object",
        "required": ["url"],
        "$defs": {
            "Opts": {
                "type": "object",
                "description": "Options",
                "properties": {
                    "raw": {"type": "boolean"},
                    "deep": {"type": "object", "properties": {"too_deep": {"type": "string"}}},
                },
            }
        },
        "properties": {
            "url": {"type": "string", "description": "Target URL"},
            "opts": {"$ref": "#/$defs/Opts"},
            "remote": {"$ref": "https://example.com/schema.json"},
            "maybe": {"type": ["string", "null"]},
        },
    }
    params = {p.path: p for p in extract_params(schema)}
    assert set(params) == {"url", "opts", "opts.raw", "opts.deep", "remote", "maybe"}
    assert params["url"].is_required and params["url"].description == "Target URL"
    assert params["opts"].json_type == "object" and params["opts"].description == "Options"
    assert params["opts.raw"].json_type == "boolean"
    assert params["remote"].json_type is None
    assert params["maybe"].json_type == "string"


def test_extract_params_self_ref_terminates() -> None:
    schema = {"type": "object", "properties": {"a": {"$ref": "#/properties/a"}}}
    assert [p.path for p in extract_params(schema)] == ["a"]
