#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_DIR}"
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x /usr/bin/python3.12 ]]; then
    PYTHON_BIN="/usr/bin/python3.12"
  else
    PYTHON_BIN="python3"
  fi
fi

if command -v uv >/dev/null 2>&1; then
  uv venv --clear --seed --python "${PYTHON_BIN}" .venv
else
  "${PYTHON_BIN}" -m venv --clear .venv
fi
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Bootstrap complete. Run: source .venv/bin/activate"
