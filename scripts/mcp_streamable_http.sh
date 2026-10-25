#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Configuration (.env, GARMIN_TOKENS_DIR, GARMIN_MAX_RANGE_DAYS) is resolved in
# one place, src/garmin_mcp/config.py (README "Configuration"). Run from the
# project directory so that resolution does not depend on the caller's cwd.
cd "${PROJECT_DIR}"

export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export LIFEOS_OTEL_DISABLE_OTLP="${LIFEOS_OTEL_DISABLE_OTLP:-1}"
# Bind: GARMIN_MCP_HOST / GARMIN_MCP_PORT, default 127.0.0.1:8000 (mcp_server.http_bind).

VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Missing runtime: ${VENV_PYTHON}" >&2
  echo "Run ${PROJECT_DIR}/scripts/bootstrap.sh first." >&2
  exit 1
fi

exec "${VENV_PYTHON}" -m garmin_mcp.mcp_server --transport streamable-http
