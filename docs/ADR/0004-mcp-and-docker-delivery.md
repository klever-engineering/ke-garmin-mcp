# ADR 0004: MCP and Docker Delivery

- Status: Accepted
- Date: 2026-03-03

## Context

The connector must be callable by agents (MCP tool surface) and portable across local setups.

## Decision

- Add an MCP server using the official Python MCP SDK (`mcp`), served over `stdio`.
- Keep tool scope focused on phase-1 metrics:
  - day overview
  - activity list by range
  - sleep range with summary
- Package runtime with Docker (`python:3.12-slim`) and a non-root user.
- Provide shell scripts for:
  - local bootstrap
  - stdio MCP startup with `.env` loading

## Consequences

- Pros:
  - Agent-callable interface is available immediately.
  - Repeatable local and container runs.
  - No credentials embedded in IDE configs.
- Cons:
  - Stdio MCP in Docker requires interactive container invocation.
  - API/auth instability risk remains from unofficial Garmin client usage.

## Revisit Trigger

Revisit when phase 2 introduces database sync and expanded tools (trend analysis, workout details, alarms).

