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

VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

# Never install packages at startup: an agent launching the stdio server must
# not trigger network installs. Set up the runtime with scripts/bootstrap.sh.
if [[ ! -x "${VENV_PYTHON}" ]] || ! "${VENV_PYTHON}" -c "import garminconnect, mcp" >/dev/null 2>&1; then
  echo "Garmin MCP runtime is missing or incomplete: ${VENV_PYTHON}" >&2
  echo "Run ${PROJECT_DIR}/scripts/bootstrap.sh first." >&2
  exit 1
fi

exec "${VENV_PYTHON}" -m garmin_mcp.mcp_server --transport stdio
