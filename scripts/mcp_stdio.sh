#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_DIR="$(cd "${PROJECT_DIR}/../.." && pwd)"

# Load project-local env first, then workspace env if still available.
if [[ -f "${PROJECT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_DIR}/.env"
  set +a
fi

if [[ -f "${WORKSPACE_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${WORKSPACE_DIR}/.env"
  set +a
fi

export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export GARMIN_TOKENS_DIR="${GARMIN_TOKENS_DIR:-config/garmin-mcp/tokens}"
export GARMIN_MAX_RANGE_DAYS="${GARMIN_MAX_RANGE_DAYS:-93}"
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
