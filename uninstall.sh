#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail

APP_NAME="blecastd"
INSTALL_DIR="/opt/blecastd"
SERVICE_FILE="/etc/systemd/system/blecastd.service"
TMPFILES_FILE="/etc/tmpfiles.d/blecastd.conf"

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "uninstall.sh must be run as root. Try: sudo ./uninstall.sh" >&2
        exit 1
    fi
}

main() {
    require_root

    if command -v systemctl >/dev/null 2>&1; then
        systemctl stop "${APP_NAME}.service" >/dev/null 2>&1 || true
        systemctl disable "${APP_NAME}.service" >/dev/null 2>&1 || true
    fi

    rm -f "${SERVICE_FILE}"
    rm -f "${TMPFILES_FILE}"
    rm -rf "${INSTALL_DIR}"

    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload
    fi

    echo "removed ${APP_NAME} service files and ${INSTALL_DIR}"
    echo "kept /etc/blecastd and the blecast group"
}

main "$@"
