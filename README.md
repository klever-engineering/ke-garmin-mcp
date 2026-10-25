# garmin-mcp

Local Garmin Connect integration with:
- CLI commands for daily metrics, activities, and sleep ranges
- MCP server tools callable by agents over `stdio`
- Docker packaging for portable execution

## Dependencies

Direct dependencies are declared once, as ranges, in `pyproject.toml`.
`uv.lock` pins every package; `requirements.txt` is generated from it (with
hashes) for pip, Docker and CI. Do not edit `requirements.txt` by hand:

```bash
make lock   # re-resolve uv.lock and regenerate requirements.txt
```

Current lock: `garminconnect` 0.3.20 (Garmin SSO via `curl_cffi`; no longer
uses `garth`), `mcp` 1.30.0 (pinned `<2`, see
[ADR 0005](docs/ADR/0005-dependency-locking-and-mcp-2-deferral.md)), Python 3.12+.

Upgrading from `garminconnect` 0.2.x: old garth tokens (`oauth1_token.json`,
`oauth2_token.json`) cannot be read. Run `lifeos.garmin-cli login` once; it
performs one credential login and saves `garmin_tokens.json` in the token
directory.

## Bootstrap (local)

```bash
cd repositories/mcps/garmin-mcp
./scripts/bootstrap.sh
```

## Configuration

All settings are resolved in one place, `src/garmin_mcp/config.py`. The
launch scripts do not read `.env` themselves; they only `cd` into the project
directory, so resolution is the same for the systemd service, stdio clients
and the CLI.

**`.env` loading order** (the first match wins; only that one file is read,
and values already set in the process environment are never overridden):

1. `GARMIN_ENV_FILE`, if set (an absolute path; if the file does not exist,
   no `.env` is loaded);
2. otherwise the nearest `.env` walking up from the working directory: the
   project's own `repositories/mcps/garmin-mcp/.env` if present, else the
   workspace root `.env`.

Settings are read once per server process; restart the service after changes
(`./scripts/install-user-service.sh`).

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `GARMIN_USERNAME`, `GARMIN_PASSWORD` | for the first login and when saved tokens are rejected | none | Garmin Connect credentials |
| `GARMIN_TOKENS_DIR` | no | `config/garmin-mcp/tokens` | Token directory; relative paths resolve from the workspace root (the folder containing `config/` and `repositories/`) |
| `GARMIN_MAX_RANGE_DAYS` | no | `93` | Largest date range a range tool accepts |
| `GARMIN_ENV_FILE` | no | unset | Explicit `.env` path |
| `FASTMCP_HOST`, `FASTMCP_PORT` | no | `127.0.0.1`, `8000` | HTTP bind (set by `scripts/mcp_streamable_http.sh`) |
| `LIFEOS_OTEL_DISABLE_OTLP` | no | `1` in the scripts | Set `0` to export traces over OTLP |

**Token location.** After the garminconnect 0.3 upgrade the token directory
holds `garmin_tokens.json`. The directory currently sits on a drive mounted
without Unix permissions, so the token files are readable by other local
users; moving it to a Linux filesystem under your home directory with owner-only
permissions is tracked in #13.

## Tests

```bash
make test
```

`make test` runs the unit tests with the project venv. After `./scripts/bootstrap.sh`
the package is installed in editable mode, so `python -m unittest discover -s tests`
also works without setting `PYTHONPATH`. GitHub Actions runs the same target on
every push to `main` and on every pull request (`.github/workflows/tests.yml`).

## CLI

```bash
source .venv/bin/activate
PYTHONPATH=src python -m garmin_mcp.cli login
PYTHONPATH=src python -m garmin_mcp.cli today
PYTHONPATH=src python -m garmin_mcp.cli day --date 2026-03-03
PYTHONPATH=src python -m garmin_mcp.cli activities --start-date 2026-02-01 --end-date 2026-02-28
PYTHONPATH=src python -m garmin_mcp.cli sleep-range --start-date 2026-02-01 --end-date 2026-03-03
PYTHONPATH=src python -m garmin_mcp.cli calories --start-date 2026-02-01 --end-date 2026-02-28
```

Installed script names (namespaced):

```bash
lifeos.garmin-cli --help
lifeos.garmin-mcp --transport stdio
```

## MCP Server (agent-callable)

Local stdio run:

```bash
./scripts/mcp_stdio.sh
```

Local long-running HTTP MCP:

```bash
./scripts/mcp_streamable_http.sh
```

Direct Python run:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m garmin_mcp.mcp_server --transport stdio
```

Exposed tools:
- `garmin_get_day_overview(target_date="")` — omit `target_date` for the server's current local date, resolved on each call. Includes `wear_data` (see [No-wear day semantics](#no-wear-day-semantics)).
- `garmin_get_health_history(start_date, end_date)` — daily resting heart rate and Body Battery charged/drained/start/end values, coverage, averages, and first-week versus last-week changes (date-range cap: `GARMIN_MAX_RANGE_DAYS`, default 93).
- `garmin_list_activities(start_date, end_date, activity_type="")`
- `garmin_get_sleep_range(start_date, end_date, include_empty=false)`

## Response contract

Every tool response (and the matching CLI command output) is built in
`src/garmin_mcp/contract.py`. MCP responses add `"ok": true`; failures return
`{"ok": false, "error": "<code>", "message": "..."}` with `error` one of
`authentication_error`, `rate_limited`, `connection_error`,
`validation_error`, `unexpected_error`.

**Date and source.** Each response carries `calendar_date` (one day) or
`start_date`/`end_date` (range), plus:

```json
"source": {
  "provider": "garmin_connect",
  "client": "garminconnect 0.3.20",
  "server": "garmin-mcp 0.2.0",
  "endpoints": ["get_user_summary", "get_sleep_data", "get_activities_by_date"],
  "retrieved_at": "2026-10-25T19:30:00+00:00",
  "date_basis": "garmin_calendar_date_local"
}
```

`server` is the response-contract version (semantic versioning, see
[ADR 0006](docs/ADR/0006-streamable-http-access-point.md) and `CHANGELOG.md`).
Dates are Garmin calendar dates in the account's local time zone.
`retrieved_at` is when this server read the values (UTC).

**Missing values are `null`, never 0.** A real 0 (for example an observed 0 s
heart-rate zone) stays 0. See [No-wear day semantics](#no-wear-day-semantics)
for days Garmin fills with zeros.

| Field (tool) | Unit | Kind | Garmin source field |
|---|---|---|---|
| `daily_summary.steps` (day) | count | measured | `totalSteps` |
| `daily_summary.distance_meters` (day) | meters | measured | `totalDistanceMeters` |
| `daily_summary.active_kilocalories`, `calories.active_kilocalories` (day, calories) | kcal | Garmin estimate from activity | `activeKilocalories` |
| `daily_summary.resting_heart_rate` (day) | beats per minute | measured | `restingHeartRate` |
| `calories.total_kilocalories` | kcal | Garmin estimate (BMR + active); `estimate: "bmr_only"` on no-wear days | `totalKilocalories` |
| `calories.bmr_kilocalories` | kcal | Garmin estimate from profile | `bmrKilocalories` |
| `calories.consumed_kilocalories` / `remaining_kilocalories` | kcal | user-logged / derived | `consumedKilocalories` / `remainingKilocalories` |
| `wear_data` (day, calories rows, health rows) | true / false / null | derived (see no-wear rule) | `totalSteps`, `averageStressLevel`, `sedentarySeconds` |
| `sleep.sleep_time_seconds` and `deep/light/rem/awake_sleep_seconds` (day, sleep range) | seconds | measured by device, staged by Garmin | `dailySleepDTO.*SleepSeconds` |
| `workouts[]` / `activities[]`: `duration_seconds`, `distance_meters` | seconds, meters | measured | `duration`, `distance` |
| `workouts[]` / `activities[]`: `average_heart_rate`, `max_heart_rate` | beats per minute | measured | `averageHR`, `maxHR` |
| `workouts[]` / `activities[]`: `heart_rate_zone_N_seconds` | seconds | measured | `hrTimeInZone_N` |
| `workouts[]` / `activities[]`: `start_time_local` | local time, no UTC offset | measured | `startTimeLocal` |
| `rows[].resting_heart_rate` (health history) | beats per minute | measured | `restingHeartRate` |
| `rows[].body_battery_*` (health history) | Body Battery points (0-100) | Garmin estimate | `charged`, `drained`, `bodyBatteryValuesArray` |

Summaries (`summary` in range tools) count only tracked days or nights and
return `null` averages and totals when nothing was tracked.

## No-wear day semantics

Observed live on 2026-10-25 by scanning daily summaries for 2026-07-25 to
2026-10-24 (92 days) and one date before any device (2012-01-15):

| Case | Example | steps | distance_meters | active_kilocalories | total_kilocalories | resting_heart_rate | sleep |
|---|---|---|---|---|---|---|---|
| Worn day | 2026-10-24 | 15615 | 12282 | 821 | 2635 | 53 | 26520 s |
| **No-wear day** (6 of 92 days: 08-19, 09-18, 09-25, 09-29, 09-30, 10-13) | 2026-08-19 | **null** | **0** (null on 09-30) | **0** | **2047** (BMR estimate only) | null | null |
| Before any device | 2012-01-15 | null | null | null | null | null | null |

Garmin fills a no-wear day with zeros and a profile-based BMR estimate rather
than nulls. The raw summary identifies it: `totalSteps` is null and
`averageStressLevel` is -1 or `sedentarySeconds` is 86400.

The MCP normalizes this (`wear_data_status` in `src/garmin_mcp/client.py`):

- `wear_data` on the day overview, calorie rows and health-history rows:
  `true` (the device recorded the day, even with few steps), `false` (no-wear
  filler day), or `null` (no Garmin record for the date).
- On a no-wear day, `distance_meters` and `active_kilocalories` are `null`,
  not 0. `total_kilocalories` keeps Garmin's value, with
  `calories.estimate: "bmr_only"` to mark it as an estimate rather than a
  measurement.
- No-wear days are not counted as tracked calorie days and are excluded from
  calorie averages. They appear in calorie rows only with `include_empty=true`.

Dates with no Garmin record at all return null for every field. Both cases are
covered by `tests/test_contract.py`.

## Request budget

The MCP server logs in to Garmin **once per process** and reuses the client
(`src/garmin_mcp/session.py`). A token login itself costs 2 Garmin requests
(profile and user settings), so this matters for the 24/7 service.

| Tool call | Garmin data requests |
|---|---|
| `garmin_get_day_overview` | 3 (summary, sleep, activities) |
| `garmin_list_activities` | 1 |
| `garmin_get_sleep_range` | 1 per day |
| `garmin_get_calories` | 1 per day |
| `garmin_get_health_history` | 1 per day + 1 (Body Battery range) |

With the default `GARMIN_MAX_RANGE_DAYS=93`, one call makes at most 94 data
requests. Each data request is tried at most 3 times: after a rate limit (429)
or connection error the server waits 2 s, then 4 s, so the worst case is 3x
the table above. Any other error is not retried.

Login rules:

- A username/password login happens only when the saved tokens are missing,
  corrupt, or rejected by Garmin. Network failures and rate limits during a
  token login are reported as `connection_error` / `rate_limited`, never
  "fixed" with a password login (repeated credential logins risk Garmin rate
  limits or an account lock). The fallback reason is logged by error class only.
- If Garmin rejects the session during a tool call, the server logs in again
  once and repeats the call; a second rejection is returned as
  `authentication_error`.
- Settings (`.env`) are read once per process; restart the service after
  changing them.

## Docker

Build:

```bash
docker build -t lifeos.garmin-mcp:local .
```

Run stdio MCP:

```bash
docker run -i --rm \
  --env-file .env \
  -e GARMIN_TOKENS_DIR=/data/config/garmin-mcp/tokens \
  -v "$(pwd)/../../../config:/data/config" \
  lifeos.garmin-mcp:local --transport stdio
```

With Compose:

```bash
docker compose build
docker compose run --rm garmin-mcp
```

Run the streamable-HTTP server in Docker instead (the production path is the
systemd user service; this is for portable or test setups). Bind the
published port to localhost only, since the server has no client
authentication yet (#17):

```bash
docker run --rm -p 127.0.0.1:8000:8000 \
  --env-file .env -e FASTMCP_HOST=0.0.0.0 -e FASTMCP_PORT=8000 \
  -e GARMIN_TOKENS_DIR=/data/config/garmin-mcp/tokens \
  -v "$(pwd)/../../../config:/data/config" \
  lifeos.garmin-mcp:local --transport streamable-http
```

## 24/7 user service

The unit is a template, `systemd/lifeos-garmin-mcp.service.in`, with no
machine paths. Install, update and roll back with
[docs/runbook.md](docs/runbook.md); the short version:

```bash
./scripts/install-user-service.sh   # render for this checkout, enable, (re)start
```

Verification:

```bash
systemctl --user status lifeos-garmin-mcp.service --no-pager
journalctl --user-unit lifeos-garmin-mcp.service -n 50 --no-pager
curl -H 'Accept: text/event-stream' http://127.0.0.1:8000/mcp
```

Downstream use:

- `repositories/tools/life-daily-report` reads Garmin data from this
  streamable HTTP service by default.
- `workspaces/lifeos-sessions` (`lifeos-garmin-refresh.timer`, every 6 hours)
  reads `garmin_list_activities` to record Garmin activities as LifeOS
  observations and Signals (`LIFEOS_GARMIN_MCP_URL`).
- Check both after a release: `../../tools/life-daily-report/scripts/garmin-status`
  and `systemctl --user show lifeos-garmin-refresh.service -p Result`.
- If the service is down, the daily report renders a Garmin source warning
  instead of shelling into the Garmin CLI unless its source config is
  intentionally switched back to `transport: "cli"`.

## Security Notes

- Keep `.env` and `.state/` out of git.
- Token files are sensitive and should remain local under `config/garmin-mcp/tokens/`.
- Do not store credentials in IDE MCP config; keep them in `.env`.

## Verifying LifeOS expected outputs

Each GitHub issue on this Track has a LifeOS expected output whose done-when is
checked by a script, so anyone (agent or owner) can see its status without
asking:

```bash
make verify-outputs                                    # all outputs
python3 scripts/verify_expected_outputs.py --only 8,9  # selected issues
python3 scripts/verify_expected_outputs.py --offline   # no live service/GitHub/PyPI calls
python3 scripts/verify_expected_outputs.py --save      # keep a JSON report in .state/expected-outputs/
```

Each check prints PASS, FAIL or SKIP with evidence. Checks cover tests, files,
GitHub CI, the running service, and behavior probes run against a fake Garmin
client. An output is ACCOMPLISHED only when all its checks pass. The script
only observes: verifying outputs and confirming claims in LifeOS stays with the
owner. When an issue's done-when changes, update its checks in the script and
the matching LifeOS done-when together.
