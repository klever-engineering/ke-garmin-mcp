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
- `GARMIN_TOKENS_DIR` (default: `.state/garmin-tokens`)
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
  -e GARMIN_TOKENS_DIR=/data/garmin-tokens \
  -v "$(pwd)/.state:/data" \
  lifeos.garmin-mcp:local --transport stdio
```

With Compose:

```bash
docker compose build
docker compose run --rm garmin-mcp
```

## Security Notes

- Keep `.env` and `.state/` out of git.
- Token files are sensitive and should remain local.
- Do not store credentials in IDE MCP config; keep them in `.env`.
