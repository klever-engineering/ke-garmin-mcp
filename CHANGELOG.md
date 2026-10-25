# Changelog

This project follows semantic versioning on its response contract
([ADR 0006](docs/ADR/0006-streamable-http-access-point.md)). Every response's
`source.server` names the version that produced it.

## Unreleased

### Changed (runtime)
- Default token directory is `~/.config/lifeos/garmin-mcp/tokens`
  (`$XDG_CONFIG_HOME/lifeos/garmin-mcp/tokens` when set), created with mode
  700; token files are set to 600 after each login, with a warning when the
  filesystem ignores modes (ADR 0008). Set `GARMIN_TOKENS_DIR` to keep a
  custom location.
- Docker mounts the token directory at `/data/tokens` and runs as the host user.
- `mcp` 2.3.0 (`MCPServer`, ADR 0009). Tools and payloads are unchanged.
  The HTTP bind is now read from `GARMIN_MCP_HOST`/`GARMIN_MCP_PORT`, and
  `FASTMCP_HOST`/`FASTMCP_PORT` still work.

## 0.2.0 - 2026-10-25

First versioned release of the Garmin access point.

### Added
- `garmin_get_health_history` tool: daily resting heart rate and Body Battery
  with coverage and first-week versus last-week changes.
- `wear_data` (`true`/`false`/`null`) on the day overview, calorie rows and
  health-history rows.
- `source` object on every response: provider, Garmin client version, server
  version, endpoints read, `retrieved_at` (UTC) and `date_basis`.
- Heart-rate zone seconds on workouts and activities (`heart_rate_zone_N_seconds`).
- README "Response contract" (fields, units, measured versus estimate),
  "No-wear day semantics" and "Request budget".

### Changed (contract)
- **Breaking (0.x):** on no-wear days `distance_meters` and
  `active_kilocalories` are `null` instead of Garmin's filler `0`, the calorie
  total is marked `estimate: "bmr_only"`, and those days no longer count as
  tracked calorie days.
- **Breaking (0.x):** calorie summary totals are `null` instead of `0` when no
  day is tracked.
- `garmin_get_day_overview` with no `target_date` returns the current date at
  call time, not the date the service started.

### Changed (runtime)
- One Garmin login per process; credential login only when the saved tokens
  are missing, corrupt or rejected; retries with backoff on rate limits and
  connection errors.
- `garminconnect` 0.3.20 (no longer uses `garth`; tokens move to
  `garmin_tokens.json` after one credential login), `mcp` 1.30.0 (`<2`).
  Dependencies are locked in `uv.lock`.
- Python 3.12 or newer.

## 0.1.0 - 2026-03-04

Initial CLI and stdio MCP server: day overview, activities, sleep range;
calories added 2026-06-15; streamable-HTTP user service added 2026-06-21.
