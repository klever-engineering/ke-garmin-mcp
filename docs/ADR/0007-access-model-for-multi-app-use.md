# ADR 0007: Access Model for Multi-App Use

- Status: Proposed (awaiting owner decision)
- Date: 2026-10-25
- Issue: #17

## Context

ADR 0006 makes this server the access point for Garmin Connect data. Its
streamable-HTTP transport has no client authentication or access control:
any process on the machine can call `http://127.0.0.1:8000/mcp` and read all
Garmin health data, and requests are not attributed to a client.

Observed on 2026-10-25:

- The server listens on `127.0.0.1:8000` only.
- Two HTTP consumers exist, both on the host:
  - `repositories/tools/life-daily-report` (Garmin source,
    `LDR_GARMIN_SERVER_URL`, default `http://127.0.0.1:8000/mcp`);
  - `workspaces/lifeos-sessions` `lifeos-garmin-refresh.timer` (every 6 h,
    `LIFEOS_GARMIN_MCP_URL`, reads `garmin_list_activities`).
- Agent clients such as Claude Code use `scripts/mcp_stdio.sh` (stdio), which
  never goes over HTTP.
- The workspace drive is mounted with `allow_other`, so other local users are a
  realistic reader of anything not protected (see #13 for the token files).

## Options

1. **Keep localhost-only, no credential.** Simplest; any local process or user
   can read all data; no per-client attribution.
2. **Localhost-only plus per-client bearer tokens (recommended).** Each HTTP
   client gets its own token; requests without a valid
   `Authorization: Bearer <token>` get HTTP 401; the server logs client name
   and tool, never health values.
3. **Remote/LAN exposure with OAuth (MCP authorization spec).** Needed only if
   apps off this machine must call the server; much more setup (TLS, an
   authorization server). Out of scope until such an app exists.

## Proposed decision

Adopt option 2:

- Keep binding to `127.0.0.1`. Any non-localhost bind is refused unless client
  tokens are configured.
- `GARMIN_MCP_CLIENT_TOKENS` (in the workspace `.env`) holds
  `name=token` pairs, for example `life-daily-report=...,lifeos-sessions=...`.
  When it is set, every HTTP request must carry a matching bearer token. When
  it is unset, the server keeps today's behavior and logs a startup warning,
  so the rollout can proceed one step at a time.
- Log one line per tool call: time, client name, tool, date range, result
  code. No Garmin values in logs.
- stdio is unchanged: it is reachable only by the process that launched it.

## Rollout (keeps both consumers working)

1. Server: add token checking that is enforced only when
   `GARMIN_MCP_CLIENT_TOKENS` is set, plus request logging; release.
2. Consumers: life-daily-report and lifeos-sessions send
   `Authorization: Bearer $LDR_GARMIN_TOKEN` / `$LIFEOS_GARMIN_MCP_TOKEN` when
   set (they still work without it).
3. Owner sets the tokens in `.env`, restarts the service, and confirms
   `life-daily-report/scripts/garmin-status` and one
   `lifeos-garmin-refresh.service` run succeed.
4. Mark this ADR Accepted.

## Decision needed from the owner

- Accept option 2, or choose 1 or 3.
- Confirm that the tokens live in the workspace `.env` (not tracked).
