#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_DIR}"
# Python 3.12+ is required (garminconnect 0.3). Override with PYTHON_BIN.
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  for candidate in python3.12 python3.13 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      PYTHON_BIN="$(command -v "${candidate}")"
      break
    fi
  done
fi
if ! "${PYTHON_BIN}" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"; then
  echo "Python 3.12 or newer is required; set PYTHON_BIN (found: ${PYTHON_BIN})." >&2
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  uv venv --clear --seed --python "${PYTHON_BIN}" .venv
else
  "${PYTHON_BIN}" -m venv --clear .venv
fi
. .venv/bin/activate
python -m pip install --upgrade pip
# requirements.txt is generated from uv.lock with hashes (make lock).
python -m pip install -r requirements.txt
# Editable install so tests and tools import garmin_mcp without PYTHONPATH.
python -m pip install --no-deps -e .

echo "Bootstrap complete. Run: source .venv/bin/activate"
