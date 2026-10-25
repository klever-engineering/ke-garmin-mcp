# ADR 0009: Migrate to mcp 2.x (MCPServer)

- Status: Accepted (owner approved 2026-10-25)
- Date: 2026-10-25
- Issue: #22
- Supersedes: ADR 0005 decision 3 (defer mcp 2.x)

## Context

ADR 0005 pinned `mcp<2` because mcp 2.x renamed `FastMCP` to
`mcp.server.mcpserver.MCPServer` and the server failed to import under 2.3.0.
The 1.x line will stop receiving fixes, including security fixes. The owner
chose to migrate now rather than wait for the 2027-01-31 revisit date.

## Decision

- Depend on `mcp>=2.3.0,<3`, locked in `uv.lock` (2.3.0 at migration time).
- Build the server with `MCPServer`. Tool names, arguments and response
  payloads do not change, so the response contract (ADR 0006) does not change.
- In 2.x the HTTP host and port are no longer read from `FASTMCP_*`
  settings. The server builds the ASGI app itself (`build_http_app`) and
  runs it with uvicorn. The bind comes from `GARMIN_MCP_HOST`/`GARMIN_MCP_PORT`,
  and the old `FASTMCP_HOST`/`FASTMCP_PORT` names are still accepted. Owning
  the app also gives one place to add client authentication (#17, ADR 0007).
- Stateful streamable HTTP stays on: both consumers send `initialize` with
  protocol version `2025-03-26`, reuse `mcp-session-id`, and read
  `structuredContent`. `tests/test_http.py` checks that exchange against the
  real app.
- Dependabot still ignores new major versions of `mcp`; each one is migrated
  as its own issue.

## Consequences

- The server is on the supported mcp line.
- A future mcp major version needs the same kind of migration and check.
