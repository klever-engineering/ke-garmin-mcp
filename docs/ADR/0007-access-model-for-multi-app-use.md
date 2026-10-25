# ADR 0007: Access Model for Multi-App Use

- Status: Accepted (owner approved option 2 on 2026-10-25)
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

## Decision

Adopt option 2:

- Keep binding to `127.0.0.1`. Any non-localhost bind is refused unless client
  tokens are configured.
- `GARMIN_MCP_CLIENT_TOKENS` (in the workspace `.env`) holds
  `name=token` pairs, for example `life-daily-report=...,lifeos-sessions=...`.
  When it is set, every HTTP request must carry a matching bearer token (HTTP
  401 otherwise). When it is unset, the server keeps today's behavior and logs
  a startup warning. `GARMIN_MCP_AUTH=observe` accepts requests without a valid
  token but logs them as `client=unauthenticated`, so the tokens can be rolled
  out one consumer at a time.
- Tokens are at least 32 characters, unique per client, and compared in
  constant time. Startup fails on a malformed `GARMIN_MCP_CLIENT_TOKENS`.
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

## Implementation

- `src/garmin_mcp/access.py`: token parsing, bind check, ASGI middleware and
  the access log (`access client=... method=... tool=... dates=... status=...`).
- Consumers: life-daily-report reads `LDR_GARMIN_TOKEN`; lifeos-sessions reads
  `LIFEOS_GARMIN_MCP_TOKEN` from its environment or from that single key in
  the workspace `.env` (`LIFEOS_OPENCLAW_ENV_FILE`).
- The owner confirmed that the tokens live in the workspace `.env`, which is
  not tracked.
