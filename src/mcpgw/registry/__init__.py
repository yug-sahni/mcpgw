"""M2 Tool Registry: SQLite storage for servers, tools, immutable versions and snapshots."""

from mcpgw.registry.db import RegistryError, open_database
from mcpgw.registry.registry import Registry, ServerRow, SnapshotDiff, SnapshotInfo, WriteSummary

__all__ = [
    "Registry",
    "RegistryError",
    "ServerRow",
    "SnapshotDiff",
    "SnapshotInfo",
    "WriteSummary",
    "open_database",
]
