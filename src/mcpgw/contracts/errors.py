"""Error hierarchy and the error codes returned to MCP clients."""

from __future__ import annotations

from enum import StrEnum


class ExitCode:
    OK = 0
    GENERAL = 1
    USAGE = 2
    INGEST = 3
    INDEX = 4
    EVALUATION = 5
    INTERRUPTED = 130


class ToolErrorCode(StrEnum):
    """Codes surfaced in MCP tool results (never as raw exceptions)."""

    INVALID_ARGUMENT = "invalid_argument"
    UNKNOWN_SERVER = "unknown_server"
    NO_INDEX = "no_index"
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_NOT_PERMITTED = "tool_not_permitted"
    INVALID_ARGUMENTS = "invalid_arguments"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    RESULT_TOO_LARGE = "result_too_large"
    INTERNAL_ERROR = "internal_error"


class GatewayError(Exception):
    """Base class for all expected errors."""

    exit_code: int = ExitCode.GENERAL
    code: ToolErrorCode = ToolErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, *, code: ToolErrorCode | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class ConfigError(GatewayError):
    exit_code = ExitCode.USAGE
    code = ToolErrorCode.INVALID_ARGUMENT


class IngestError(GatewayError):
    exit_code = ExitCode.INGEST
    code = ToolErrorCode.UPSTREAM_UNAVAILABLE


class IndexingError(GatewayError):
    exit_code = ExitCode.INDEX
    code = ToolErrorCode.NO_INDEX


class EvaluationError(GatewayError):
    exit_code = ExitCode.EVALUATION


class ContractError(GatewayError):
    exit_code = ExitCode.USAGE
    code = ToolErrorCode.INVALID_ARGUMENT
