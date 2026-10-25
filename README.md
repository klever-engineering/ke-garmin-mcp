# garmin-mcp

Local Garmin Connect integration with:
- CLI commands for daily metrics, activities, and sleep ranges
- MCP server tools callable by agents over `stdio`
- Docker packaging for portable execution

## Dependencies (latest stable, verified)

- `garminconnect==0.2.38`
- `mcp==1.26.0`
- `python-dotenv==1.2.2`
- `typer==0.24.1`

Note: `garminconnect` currently constrains `garth` to `<0.6.0`. Resolver will install a compatible stable release.

## Bootstrap (local)

```bash
cd repositories/mcps/garmin-mcp
./scripts/bootstrap.sh
```

## Environment

The runtime loads `.env` from:
1. `repositories/mcps/garmin-mcp/.env` (if present)
2. workspace root `.env` (`../../.env`) via `scripts/mcp_stdio.sh`

Required:
- `GARMIN_USERNAME`
- `GARMIN_PASSWORD`

Optional:
- `GARMIN_TOKENS_DIR` (default: `config/garmin-mcp/tokens`, resolved from the workspace root)
- `GARMIN_MAX_RANGE_DAYS` (default: `93`)
- `GARMIN_ENV_FILE` (explicit env file path)

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

## 24/7 user service

Checked-in user unit:

```bash
systemd/lifeos-garmin-mcp.service
```

Install and enable:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/lifeos-garmin-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now lifeos-garmin-mcp.service
```

Verification:

```bash
systemctl --user status lifeos-garmin-mcp.service --no-pager
journalctl --user-unit lifeos-garmin-mcp.service -n 50 --no-pager
curl -H 'Accept: text/event-stream' http://127.0.0.1:8000/mcp
```

Downstream use:

- `repositories/tools/life-daily-report` now reads Garmin data from this
  streamable HTTP service by default.
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
