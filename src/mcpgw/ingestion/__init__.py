"""M1 Tool Ingestion: list tools from upstream MCP servers and normalise them.

``run_ingest`` / ``ingest_all`` live in ``mcpgw.ingestion.ingest``; they are not re-exported here
because they depend on the registry, which itself imports this package's models.
"""

from mcpgw.ingestion.models import Param, RawTool, ServerInfo, ServerResult, ToolPage
from mcpgw.ingestion.normalize import Flag, normalise, normalise_all
from mcpgw.ingestion.params import extract_params

__all__ = [
    "Flag",
    "Param",
    "RawTool",
    "ServerInfo",
    "ServerResult",
    "ToolPage",
    "extract_params",
    "normalise",
    "normalise_all",
]
