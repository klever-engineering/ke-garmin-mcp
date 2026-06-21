#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_DIR="$(cd "${PROJECT_DIR}/../.." && pwd)"

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
export GARMIN_TOKENS_DIR="${GARMIN_TOKENS_DIR:-.state/garmin-tokens}"
export GARMIN_MAX_RANGE_DAYS="${GARMIN_MAX_RANGE_DAYS:-93}"
export LIFEOS_OTEL_DISABLE_OTLP="${LIFEOS_OTEL_DISABLE_OTLP:-1}"
export FASTMCP_HOST="${FASTMCP_HOST:-127.0.0.1}"
export FASTMCP_PORT="${FASTMCP_PORT:-8000}"

VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Missing runtime: ${VENV_PYTHON}" >&2
  echo "Run ${PROJECT_DIR}/scripts/bootstrap.sh first." >&2
  exit 1
fi

exec "${VENV_PYTHON}" -m garmin_mcp.mcp_server --transport streamable-http
