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
export GARMIN_TOKENS_DIR="${GARMIN_TOKENS_DIR:-.state/garmin-tokens}"
export GARMIN_MAX_RANGE_DAYS="${GARMIN_MAX_RANGE_DAYS:-93}"
export LIFEOS_OTEL_DISABLE_OTLP="${LIFEOS_OTEL_DISABLE_OTLP:-1}"

VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
BOOTSTRAP_LOCK="${PROJECT_DIR}/.state/bootstrap.lock"

acquire_lock() {
  mkdir -p "${PROJECT_DIR}/.state"
  if [[ -d "${BOOTSTRAP_LOCK}" ]]; then
    LOCK_AGE_SECONDS=$(( $(date +%s) - $(stat -c %Y "${BOOTSTRAP_LOCK}") ))
    if [[ "${LOCK_AGE_SECONDS}" -gt 600 ]]; then
      rmdir "${BOOTSTRAP_LOCK}" 2>/dev/null || true
    fi
  fi

  local retries=120
  local delay=0.25
  until mkdir "${BOOTSTRAP_LOCK}" 2>/dev/null; do
    retries=$((retries - 1))
    if [[ "${retries}" -le 0 ]]; then
      echo "Timed out waiting for bootstrap lock: ${BOOTSTRAP_LOCK}" >&2
      return 1
    fi
    sleep "${delay}"
  done
  trap 'rmdir "${BOOTSTRAP_LOCK}" 2>/dev/null || true' EXIT
}

ensure_runtime() {
  if [[ -x "${VENV_PYTHON}" ]] && "${VENV_PYTHON}" -c "import sys, garminconnect, mcp; raise SystemExit(0 if sys.version_info < (3, 13) else 1)" >/dev/null 2>&1; then
    return 0
  fi

  acquire_lock

  # Another process may have completed bootstrap while we waited.
  if [[ -x "${VENV_PYTHON}" ]] && "${VENV_PYTHON}" -c "import sys, garminconnect, mcp; raise SystemExit(0 if sys.version_info < (3, 13) else 1)" >/dev/null 2>&1; then
    rmdir "${BOOTSTRAP_LOCK}" 2>/dev/null || true
    return 0
  fi

  echo "Bootstrapping Garmin MCP runtime (.venv + dependencies)..." >&2
  PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3.12}" "${PROJECT_DIR}/scripts/bootstrap.sh" >&2
  rmdir "${BOOTSTRAP_LOCK}" 2>/dev/null || true
}

ensure_runtime

exec "${VENV_PYTHON}" -m garmin_mcp.mcp_server --transport stdio
