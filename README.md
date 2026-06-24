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
- `garmin_get_day_overview(target_date)`
- `garmin_list_activities(start_date, end_date, activity_type="")`
- `garmin_get_sleep_range(start_date, end_date, include_empty=false)`

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
