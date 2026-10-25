# Garmin MCP service runbook

How to install, update, check and roll back the `lifeos-garmin-mcp` systemd
user service (streamable HTTP on `http://127.0.0.1:8000/mcp`, see
[ADR 0006](ADR/0006-streamable-http-access-point.md)). All commands run from
the repository root as the user who owns the service. Nothing here needs root.

## First install on a machine

```bash
./scripts/bootstrap.sh               # .venv from requirements.txt (Python 3.12+)
.venv/bin/lifeos.garmin-cli login    # one credential login; saves garmin_tokens.json
./scripts/install-user-service.sh    # renders the unit for this checkout, enables and starts it
systemctl --user enable --now lifeos-garmin-mcp.service   # same as the script's last step, if done by hand
```

`install-user-service.sh` fills `@PROJECT_DIR@` in
`systemd/lifeos-garmin-mcp.service.in` with this checkout's path and writes
`~/.config/systemd/user/lifeos-garmin-mcp.service`. Use `--print` to see the
rendered unit, or `--no-start` to install without restarting.

Credentials (`GARMIN_USERNAME`, `GARMIN_PASSWORD`) and optional settings are
read from `.env` (see README "Environment"). To keep the service running
while you are logged out, enable lingering once: `loginctl enable-linger "$USER"`.

## Update (deploy a new version)

```bash
git pull --ff-only
./scripts/bootstrap.sh               # or: uv pip sync --python .venv/bin/python requirements.txt
.venv/bin/python -m pip install --no-deps -e .
./scripts/install-user-service.sh    # re-renders the unit if the template changed, then restarts
make verify-outputs                  # optional: observe LifeOS expected outputs
```

The server logs in to Garmin once per process and reads settings once, so
code, dependency and `.env` changes take effect only after the restart.

## Check

```bash
systemctl --user status lifeos-garmin-mcp.service --no-pager
journalctl --user-unit lifeos-garmin-mcp.service -n 50 --no-pager
../../tools/life-daily-report/scripts/garmin-status    # end-to-end through the main consumer
```

Healthy: the unit is `active (running)`, the journal shows no
`token login failed` or repeated `retry` warnings, and `garmin-status` prints
today's values.

## Roll back

```bash
git checkout <previous-tag>          # for example v0.2.0
./scripts/bootstrap.sh
./scripts/install-user-service.sh
```

If a rollback crosses the garminconnect 0.3 upgrade (versions before 0.2.0),
the old version needs the old garth token files; run
`.venv/bin/lifeos.garmin-cli login` again after rolling back.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Tools return `authentication_error` | Saved tokens rejected and no credentials in `.env` | Add credentials, run `lifeos.garmin-cli login`, restart |
| Tools return `rate_limited` | Garmin 429 after 3 tries | Wait a few minutes; see README "Request budget" |
| `mcp_stdio.sh` exits "runtime is missing" | `.venv` missing or incomplete | `./scripts/bootstrap.sh` |
| Consumer gets HTTP 401 | Its token is missing or differs from `GARMIN_MCP_CLIENT_TOKENS` | Compare the app's token variable in `.env` (README "Client access"), restart the service |
| Service restarts in a loop | Missing `.venv` or a Python error | `journalctl --user-unit lifeos-garmin-mcp.service -n 100` |
