# ADR 0003: Phase-1 Scope and Interface

- Status: Accepted
- Date: 2026-03-03

## Context

We need working value quickly, before building a full MCP server and persistence/analytics pipeline.

## Decision

Phase 1 is a local CLI with commands to:
- authenticate and persist tokens
- fetch one-day sleep/workouts/daily summary payloads

CLI commands:
- `login`
- `today`
- `day --date YYYY-MM-DD [--raw]`

## Consequences

- Pros:
  - Fast to validate account connectivity and data shape.
  - Minimal operational overhead.
- Cons:
  - No MCP tools yet.
  - No historical database cache yet.

## Revisit Trigger

Revisit when phase 2 starts (MCP server and local database sync).

