#!/usr/bin/env bash
# Install or update the lifeos-garmin-mcp systemd user service from
# systemd/lifeos-garmin-mcp.service.in for this checkout.
#
#   scripts/install-user-service.sh             # install/update, enable, (re)start
#   scripts/install-user-service.sh --no-start  # install/update and enable only
#   scripts/install-user-service.sh --print     # print the rendered unit and exit
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
UNIT_NAME="lifeos-garmin-mcp.service"
TEMPLATE="${PROJECT_DIR}/systemd/${UNIT_NAME}.in"
UNIT_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
TARGET="${UNIT_DIR}/${UNIT_NAME}"

mode="start"
case "${1:-}" in
  "") ;;
  --no-start) mode="no-start" ;;
  --print) mode="print" ;;
  *) echo "Usage: $0 [--no-start|--print]" >&2; exit 2 ;;
esac

rendered="$(grep -v '^#' "${TEMPLATE}" | sed "s|@PROJECT_DIR@|${PROJECT_DIR}|g")"
if [[ "${mode}" == "print" ]]; then
  printf '%s\n' "${rendered}"
  exit 0
fi

if [[ ! -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
  echo "Missing ${PROJECT_DIR}/.venv. Run scripts/bootstrap.sh first." >&2
  exit 1
fi

mkdir -p "${UNIT_DIR}"
if [[ -f "${TARGET}" ]] && [[ "$(cat "${TARGET}")" == "${rendered}" ]]; then
  echo "Unit already up to date: ${TARGET}"
else
  printf '%s\n' "${rendered}" > "${TARGET}"
  echo "Installed ${TARGET}"
fi

systemctl --user daemon-reload
systemctl --user enable "${UNIT_NAME}" >/dev/null
if [[ "${mode}" == "start" ]]; then
  systemctl --user restart "${UNIT_NAME}"
  echo "Restarted ${UNIT_NAME}; check: systemctl --user status ${UNIT_NAME} --no-pager"
fi
