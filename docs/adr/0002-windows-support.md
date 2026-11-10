# ADR 0002: Windows is a supported development platform

Status: accepted. Date: 2026-11-10. Resolves SRS open decision Q13.

## Context
The SRS assumes Linux or macOS and does not target Windows. The primary developer works on
Windows 11 and chose to stay there rather than use WSL. Week 1 already hit two Windows-only
failures that Ubuntu CI could not catch: `os.fsync` on a read-only handle (Errno 9), and spawning
a stdio upstream while `sys.stderr` has no file descriptor.

## Decision
- Windows, Linux and macOS are all supported for development and for running the gateway.
- CI runs the full check on `ubuntu-latest` and `windows-latest` (Python 3.11 and 3.12), plus
  Windows with Python 3.14. A change is not mergeable unless every job passes.
- CI calls `uv` directly instead of `make`, because `make` is not standard on Windows. The
  `Makefile` stays as a shortcut on Linux and macOS.

## Rules for code
- Use `pathlib`; never build paths with `/` or `\` strings. Resolve relative config paths against
  the config file's directory (already done in `mcpgw.config`).
- Open files with an explicit `encoding="utf-8"`; Windows defaults to a legacy code page.
- Data files are LF-only (`.gitattributes`), so hashes and byte-identical fixtures match on every
  OS. Write text with `\n`, never `os.linesep`.
- `os.fsync` needs a handle opened for writing. `os.replace` is the atomic rename on all platforms.
- Spawn upstream servers only through the MCP SDK's `stdio_client`; it resolves `.cmd` shims such
  as `npx` on Windows. Pass it a real file for stderr.
- Do not rely on POSIX-only APIs (signals other than SIGINT, `fork`, file modes) without a
  Windows fallback and a test.

## Consequences
CI takes roughly twice as long. Windows regressions are caught before merge instead of by the
developer. Upstream MCP servers that only run on POSIX are a corpus-collection concern (Q2), not
a platform-support one.
